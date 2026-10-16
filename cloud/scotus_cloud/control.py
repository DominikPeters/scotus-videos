"""Cloud Run control API. PHP authenticates people; HMAC authenticates PHP.

This small service launches configured jobs, exchanges sign-in codes and writes
secret versions. It can read application keys for those exchanges; stored
YouTube/Codex account credentials remain restricted to their private workers.
"""

import hmac
import json
import os
from pathlib import Path
import re
import time
import base64

from .google import Google
from .model import STAGES,alignment_cpus
from .remote import Dashboard, signature
from .connections import (validate_web_client, youtube_authorize, youtube_exchange,
                          github_exchange, github_install, GITHUB_REPOSITORY,
                          validate_instagram_client, instagram_authorize, instagram_exchange, InstagramConnectionError)


def validate_secret(name, value):
    if not isinstance(value, dict):
        raise ValueError('Expected a credential JSON object')
    if name == 'youtube':
        if not all(isinstance(value.get(k), str) and value[k] for k in ('client_id', 'client_secret', 'refresh_token')):
            raise ValueError('YouTube credentials need client_id, client_secret and refresh_token')
        if value.get('token_uri', 'https://oauth2.googleapis.com/token') not in (
                'https://oauth2.googleapis.com/token', 'https://accounts.google.com/o/oauth2/token'):
            raise ValueError('Unsupported Google token endpoint')
    elif name == 'spotify':
        from .spotify import validate_credentials
        value=validate_credentials(value)
    elif name == 'codex':
        if value.get('auth_mode') != 'chatgpt' or not value.get('tokens', {}).get('refresh_token'):
            raise ValueError('Expected ChatGPT Codex auth.json with a refresh token')
        if value.get('OPENAI_API_KEY'):
            raise ValueError('The Codex worker uses subscription authentication')
    else:
        raise ValueError('Unknown credential')
    encoded = json.dumps(value, separators=(',', ':')).encode()
    if len(encoded) > 65536:
        raise ValueError('Credential is too large for Secret Manager')
    return encoded


def next_stage(job):
    """Preparation feeds independent enrichment/alignment branches; planning joins them."""
    stages=job['stages']
    if job['status'] in ('failed','cancelled','complete'):return None
    if job['status']=='needs_review' and stages['enrich']['status']!='needs_review':return None
    active={name for name,value in stages.items() if value['status'] in ('starting','running')}
    if stages['prepare']['status']!='complete':
        return 'prepare' if stages['prepare']['status']=='pending' and not active else None
    if active-{'enrich','align'}:return None
    if stages['align']['status']=='pending':return 'align'
    if stages['enrich']['status']=='pending':return 'enrich'
    if stages['enrich']['status']!='complete' or stages['align']['status']!='complete' or active:return None
    for name in ('plan','render','assemble','upload'):
        if stages[name]['status']!='complete':return name if stages[name]['status']=='pending' else None
    return None



def dispatch_video_action(dashboard,google,settings,job):
    action=dashboard.call('video_action_dispatch',job=job)
    if not action:return {'status':'no_queued_action'}
    if settings.get('youtube_action_service'):
        result=google.invoke_action_service(settings['youtube_action_service'],{'job':job,'action':action['id'],'token':action['dispatch_token']})
        return {'job':job,'stage':'video_action',**result}
    operation=google.execute(settings['region'],settings['jobs']['upload'],{'SCOTUS_STAGE':'upload','SCOTUS_JOB_ID':job,'SCOTUS_VIDEO_ACTION':action['id'],'SCOTUS_ACTION_TOKEN':action['dispatch_token']})
    return {'job':job,'stage':'video_action','operation':operation}


def dispatch(dashboard,google,settings):
    # Source discovery and worker launches take priority over notification services.
    result=_dispatch_work(dashboard,google,settings)
    from .notifications import drain_notifications
    try:drain_notifications(dashboard,settings)
    except Exception:pass
    return result


def _dispatch_work(dashboard, google, settings):
    # A container can exit before claiming a lease. Heartbeats cannot detect that.
    snapshot=dashboard.call('snapshot')
    for job in (snapshot.get('jobs') or {}).values():
        if job['status']=='cancelled':continue
        for stage,value in job['stages'].items():
            operation=value.get('cloud_operation')
            if not operation or value['status'] not in ('starting','running'):continue
            try:status=google.operation_status(operation)
            except Exception:continue # Retain the pointer and retry at the next tick.
            if status['done']:
                dashboard.call('execution_closed',job=job['id'],stage=stage,operation=operation)
    from .recovery_control import dispatch_recoveries
    recovery=dispatch_recoveries(dashboard,google,settings)
    if not settings.get('workers_enabled'):
        return {'message': 'Video workers are not enabled yet.', 'launched': recovery}
    from .discovery import discover
    try:discover(dashboard,settings)
    except Exception:pass
    snapshot = dashboard.call('snapshot')
    launched = list(recovery)
    jobs=snapshot.get('jobs') or {}
    spotify=settings.get('spotify') or {}
    if spotify.get('enabled'):
        # Only owner-requested transfers are polled, even while video work is paused.
        for job in [j for j in jobs.values() if (j.get('spotify') or {}).get('manual') and j['spotify'].get('status') in ('queued','waiting_episode','publish_queued','publishing') and j['spotify'].get('retry_after',0)<=time.time()][:2]:
            try:google.invoke_action_service(spotify['service'],{'job':job['id']})
            except Exception:pass
    if settings.get('statistics_job'):
        from .statistics_control import dispatch_statistics
        try:dispatch_statistics(dashboard,google,settings)
        except Exception as error:print(json.dumps({'statistics_dispatch_error':str(error)[:200]}),flush=True)
    from .podcast import publish_alignments
    try:publish_alignments(dashboard,google,settings,jobs)
    except Exception as error:print(json.dumps({'podcast_export_error':type(error).__name__}),flush=True)
    eligible=[job for job in jobs.values() if not snapshot['paused'] or job.get('run_requested')]
    active={job['id'] for job in eligible if job['status']=='running' or
            (job['status']=='needs_review' and (next_stage(job) is not None or any(s['status'] in ('starting','running') for s in job['stages'].values())))}
    candidates=set(active)
    candidates.update(job['id'] for job in eligible if job['status']=='queued' and job.get('run_requested'))
    repairing=any(rec['status'] in ('starting','running') for rec in (snapshot.get('recoveries') or {}).values())
    if not snapshot['paused'] and not candidates and not repairing:
        queued=[job for job in eligible if job['status']=='queued']
        if queued:candidates.add(sorted(queued,key=lambda job:job['created_at'])[0]['id'])
    if settings.get('clip_job'):
        from .clip_control import dispatch_clip
        for clip_job in (snapshot.get('jobs') or {}).values():
            for clip in (clip_job.get('clips') or {}).values():
                if clip['status'] in ('render_queued','upload_queued','tiktok_draft_queued','tiktok_publish_queued','starting','rendering','uploading'):
                    try:dispatch_clip(dashboard,google,settings,clip_job['id'],clip['id'])
                    except Exception:pass
    for job in eligible:
        if job['status']!='cancelled' and settings.get('photo_job'):
            for request in (job.get('photo_requests') or {}).values():
                if request['status']!='queued':continue
                claim=dashboard.call('photo_dispatch',job=job['id'],request=request['id'])
                if not claim:continue
                try:
                    operation=google.execute(settings['region'],settings['photo_job'],{'SCOTUS_JOB_ID':job['id'],'SCOTUS_PHOTO_REQUEST':request['id'],'SCOTUS_PHOTO_TOKEN':claim['dispatch_token']})
                    launched.append({'job':job['id'],'stage':'photo_revision','operation':operation})
                except Exception:dashboard.call('photo_dispatch_failed',job=job['id'],request=request['id'],dispatch_token=claim['dispatch_token'])
                break
        if job['status']!='cancelled' and settings.get('asset_job') and job.get('asset_publication',{}).get('status')=='queued':
            claim=dashboard.call('asset_publish_dispatch',job=job['id'])
            if claim:
                google.execute(settings['region'],settings['asset_job'],{'SCOTUS_JOB_ID':job['id'],'SCOTUS_ASSET_TOKEN':claim['dispatch_token']})
        if job['status']=='complete':
            if settings.get('jobs',{}).get('upload'):
                action=dispatch_video_action(dashboard,google,settings,job['id'])
                if action.get('stage'):launched.append(action)
            continue
        if job['status'] in ('failed', 'cancelled') or job['id'] not in candidates:
            continue
        stage=next_stage(job)
        if stage is None:continue
        if stage not in settings.get('jobs', {}):
            continue
        claimed = dashboard.call('dispatch', job=job['id'], stage=stage,baseline_sha256=settings.get('workflow_baseline_sha256',''))
        if not claimed:
            continue
        indices=[i for i,item in enumerate(claimed['job']['stages'][stage].get('tasks',[])) if item['status']!='complete'] if stage=='render' else []
        count=len(indices) if stage=='render' else 1
        env = {'SCOTUS_JOB_ID': job['id'], 'SCOTUS_STAGE': stage,
               'SCOTUS_DISPATCH_TOKEN': claimed['dispatch_token']}
        if stage=='render':env['SCOTUS_RENDER_TASKS']=json.dumps(indices)
        release=claimed.get('workflow_release') or claimed['job'].get('workflow_release')
        if release:env.update(SCOTUS_WORKFLOW_RELEASE_URI=release['uri'],SCOTUS_WORKFLOW_RELEASE_SHA256=release['sha256'])
        try:
            extra={}
            worker_job=settings['jobs'][stage]
            if stage=='prepare' and settings.get('research_job') and not release:
                worker_job=settings['research_job'];env['SCOTUS_CONTINUE_ENRICH']='1'
            if stage=='assemble' and settings.get('delivery_job') and not release:
                worker_job=settings['delivery_job'];env['SCOTUS_CONTINUE_UPLOAD']='1'
            if stage=='align':
                cpus=alignment_cpus(claimed['job'],google) if settings.get('alignment_long_job') else 4
                if cpus==8:worker_job=settings['alignment_long_job']
                env['SCOTUS_ALIGN_THREADS']=str(cpus)
            if stage=='upload' and claimed['job']['stages']['upload'].get('checkpoint',{}).get('video_id'):
                extra['timeout_seconds']=min(300,settings.get('recovery',{}).get('stage_resources',{}).get('upload',[1,2,300])[2])
            operation = google.execute(settings['region'], worker_job, env, tasks=count,**extra)
        except Exception:
            dashboard.call('dispatch_failed', job=job['id'], stage=stage,
                           dispatch_token=claimed['dispatch_token'])
            continue
        launched.append({'job': job['id'], 'stage': stage, 'operation': operation})
        dashboard.call('execution_record',job=job['id'],stage=stage,
                       dispatch_token=claimed['dispatch_token'],operation=operation,cloud_job=worker_job)
        if len(launched) >= settings.get('max_launches_per_request', 2):
            break
    from .chunk_cleanup import cleanup_completed_chunks
    try:cleanup_completed_chunks(dashboard,google,settings,jobs)
    except Exception as error:print(json.dumps({'chunk_cleanup_error':type(error).__name__}),flush=True)
    message='Automatic work is paused.' if snapshot['paused'] and not launched else f'{len(launched)} cloud execution(s) started.'
    return {'message': message, 'launched': launched}


def make_app(settings, google_factory=Google):
    dashboard = Dashboard(settings['dashboard_url'], settings['dispatcher_key'], 'dispatcher')

    def app(environ, start_response):
        status, value = '200 OK', None
        try:
            if environ.get('REQUEST_METHOD') != 'POST' or environ.get('PATH_INFO') not in ('/v1/request','/v1/recovery','/v1/tick','/v1/watch'):
                raise ValueError('Unknown route')
            if environ['PATH_INFO'] in ('/v1/tick','/v1/watch'):
                from google.oauth2.id_token import verify_oauth2_token
                from google.auth.transport.requests import Request as AuthRequest
                token=environ.get('HTTP_AUTHORIZATION','').removeprefix('Bearer ')
                try:claims=verify_oauth2_token(token,AuthRequest(),audience=settings['control_url'])
                except Exception:raise PermissionError('Invalid scheduler authentication') from None
                if claims.get('email')!=settings['scheduler_account'] or not claims.get('email_verified'):raise PermissionError('Unknown scheduler identity')
                if environ['PATH_INFO']=='/v1/watch':
                    from .discovery import poll_watches
                    watches=poll_watches(dashboard,settings)
                    launched=dispatch(dashboard,google_factory(settings['project']),settings) if any(r.get('found') for r in watches) else None
                    value={'ok':True,'result':{'watches':watches,'dispatch':launched}}
                else:value={'ok':True,'result':dispatch(dashboard,google_factory(settings['project']),settings)}
                encoded=json.dumps(value).encode();start_response('200 OK',[('Content-Type','application/json'),('Content-Length',str(len(encoded)))]);return [encoded]
            length = int(environ.get('CONTENT_LENGTH') or 0)
            if not 0 < length <= 262144:
                raise ValueError('Invalid request size')
            body = environ['wsgi.input'].read(length)
            timestamp = environ.get('HTTP_X_SCOTUS_TIME', '')
            nonce = environ.get('HTTP_X_SCOTUS_NONCE', '')
            if not timestamp.isdecimal() or abs(time.time() - int(timestamp)) > 300 or not re.fullmatch('[a-f0-9]{32}', nonce):
                raise PermissionError('Invalid authentication')
            route=environ['PATH_INFO'];key=settings.get('recovery_key','') if route=='/v1/recovery' else settings['control_key']
            if not key:raise PermissionError('Recovery not configured')
            expected = signature(key, timestamp, nonce, 'POST', route, body)
            if not hmac.compare_digest(expected, environ.get('HTTP_X_SCOTUS_SIGNATURE', '')):
                raise PermissionError('Invalid authentication')
            request = json.loads(body)
            op, data = request.get('op'), request.get('data', {})
            # These authenticated reads have no side effects; avoid a PHP callback
            # while PHP itself is waiting for this response. Mutations stay fenced.
            if route=='/v1/recovery' or not (op=='secret_status' or (op=='asset_data' and data.get('uri'))):
                dashboard.call('reserve_control_nonce', nonce=nonce)
            google = google_factory(settings['project'])
            if route=='/v1/recovery':
                from .recovery_control import broker
                value=broker(dashboard,google,settings,request)
            elif op == 'secret_status':
                names = [name for name in ('youtube', 'codex', 'github', 'spotify', 'instagram') if name in settings['secrets']]
                value = {'workers_enabled': settings.get('workers_enabled', False), 'credentials': {
                    name: google.secret_status(settings['secrets'][name]) for name in names}}
                value['youtube_client_configured'] = google.secret_status(settings['secrets']['youtube_client'])['configured']
                value['instagram_client_configured'] = bool(settings['secrets'].get('instagram_client')) and google.secret_status(settings['secrets']['instagram_client'])['configured']
                value['codex_login_enabled'] = bool(settings.get('codex_auth_job'))
                value['github_repository'] = GITHUB_REPOSITORY
                if value['credentials'].get('github', {}).get('configured'):
                    saved = json.loads(google.secret(settings['secrets']['github']))
                    value['credentials']['github']['configured'] = bool(saved.get('installation_id'))
                    value['credentials']['github']['app_created'] = True
            elif op == 'secret_replace':
                name = data.get('name')
                payload = validate_secret(name, data.get('value'))
                token = dashboard.call('auth_claim', name=name)
                if not token:
                    raise ValueError('Credential is in use; retry after the current job')
                try:
                    dashboard.call('auth_check', name=name, token=token)
                    google.add_secret_version(settings['secrets'][name], payload)
                finally:
                    dashboard.call('auth_release', name=name, token=token)
                value = {'saved': True}
            elif op == 'youtube_client_replace':
                payload = validate_web_client(data.get('value'), settings)
                google.add_secret_version(settings['secrets']['youtube_client'], payload)
                value = {'saved': True}
            elif op == 'youtube_authorize':
                value = youtube_authorize(data, settings, google)
            elif op == 'instagram_client_replace':
                google.add_secret_version(settings['secrets']['instagram_client'], validate_instagram_client(data.get('value')))
                value = {'saved': True}
            elif op == 'instagram_authorize':
                value = instagram_authorize(data, settings, google)
            elif op == 'instagram_exchange':
                token = dashboard.call('auth_claim', name='instagram')
                if not token: raise ValueError('Credential is in use')
                try:
                    credential = instagram_exchange(data, settings, google)
                    dashboard.call('auth_check', name='instagram', token=token)
                    google.add_secret_version(settings['secrets']['instagram'], json.dumps(credential).encode())
                except InstagramConnectionError as error:
                    print(json.dumps({'instagram_connection_error': str(error)}), flush=True)
                    raise
                except Exception as error:
                    print(json.dumps({'instagram_connection_error_type': type(error).__name__}), flush=True)
                    raise
                finally:
                    dashboard.call('auth_release', name='instagram', token=token)
                value = {'saved': True}
            elif op == 'youtube_exchange':
                token = dashboard.call('auth_claim', name='youtube')
                if not token:
                    raise ValueError('Credential is in use')
                try:
                    credential = youtube_exchange(data, settings, google)
                    dashboard.call('auth_check', name='youtube', token=token)
                    google.add_secret_version(settings['secrets']['youtube'], validate_secret('youtube', credential))
                finally:
                    dashboard.call('auth_release', name='youtube', token=token)
                value = {'saved': True}
            elif op in ('github_exchange', 'github_install'):
                token = dashboard.call('auth_claim', name='github')
                if not token:
                    raise ValueError('Credential is in use')
                try:
                    if op == 'github_exchange':
                        credential = github_exchange(data, settings)
                    else:
                        credential = github_install(json.loads(google.secret(settings['secrets']['github'])), data.get('installation_id'))
                    dashboard.call('auth_check', name='github', token=token)
                    google.add_secret_version(settings['secrets']['github'], json.dumps(credential).encode())
                finally:
                    dashboard.call('auth_release', name='github', token=token)
                value = {'saved': True, 'slug': credential['slug'], 'configured': bool(credential.get('installation_id'))}
            elif op == 'github_existing':
                if google.secret_status(settings['secrets']['github'])['configured']:
                    saved = json.loads(google.secret(settings['secrets']['github']))
                    value = {'slug': saved['slug']}
                else:
                    value = {}
            elif op == 'codex_login_start':
                if not settings.get('codex_auth_job'):
                    raise ValueError('Codex sign-in job is unavailable')
                login = dashboard.call('login_begin', owner=data['owner'], daily_limit=settings.get('codex_auth_daily_limit', 3))
                try:
                    google.execute(settings['region'], settings['codex_auth_job'], {
                        'SCOTUS_LOGIN_ID': login['id'], 'SCOTUS_LOGIN_TOKEN': login['token']})
                except Exception:
                    dashboard.call('login_update', id=login['id'], token=login['token'], status='failed')
                    raise
                value = {'id': login['id'], 'status': 'starting'}
            elif op=='cleanup_chunks':
                from .chunk_cleanup import cleanup_completed_chunks
                value=cleanup_completed_chunks(dashboard,google,settings,dashboard.call('snapshot')['jobs'])
            elif op == 'dispatch':
                value = dispatch(dashboard, google, settings)
            elif op in ('clip_dispatch','clip_download'):
                from .clip_control import dispatch_clip,download_url
                value=(dispatch_clip if op=='clip_dispatch' else download_url)(dashboard,google,settings,data['job'],data['clip'])
            elif op == 'video_action':
                value=dispatch_video_action(dashboard,google,settings,data['job'])
            elif op == 'video_action_probe':
                value=google.invoke_action_service(settings['youtube_action_service'],{'probe':True})
            elif op in ('spotify_dispatch','spotify_probe'):
                if not settings.get('spotify',{}).get('enabled'):raise ValueError('Spotify is not configured')
                value=google.invoke_action_service(settings['spotify']['service'],{'probe':True} if op=='spotify_probe' else {'job':data['job']})
            elif op=='notifications':
                from .notifications import drain_notifications
                value=drain_notifications(dashboard,settings)
            elif op=='notification_test':
                from .notifications import drain_notifications
                if not re.fullmatch('[a-f0-9]{64}',str(data.get('notice_id',''))):raise ValueError('Invalid test notice')
                results=drain_notifications(dashboard,settings,notice_id=data['notice_id'])
                value=results[0] if results else {'delivered':0}
            elif op=='photo_add':
                import tempfile
                from .enrichment import store_photo
                job=dashboard.call('review_context',job=data['job'])
                if data['revision']!=job['review']['revision'] or data['person'] not in job['review']['photos']:raise ValueError('Review changed')
                image=base64.b64decode(data['image'],validate=True)
                if len(image)>131072 or data.get('kind') not in ('photo','logo','initials'):raise ValueError('Invalid image')
                source=data.get('source_url','')
                if source and not source.startswith('https://'):raise ValueError('Invalid source')
                with tempfile.TemporaryDirectory() as folder:
                    choice=store_photo(google,settings['bucket'],job['id'],data['person'],image,
                        {'kind':data['kind'],'source_url':source,'identity_source_url':'','origin':'owner_upload','private_note':data.get('note','')[:2000]},Path(folder),preserve=True)
                value=dashboard.call('review_candidate_add',job=job['id'],revision=data['revision'],person=data['person'],candidate=choice)
            elif op=='asset_data' and data.get('uri'):
                uri=data['uri']
                if not isinstance(uri,str) or not any(uri.startswith('gs://'+settings['bucket']+'/'+prefix+'/') for prefix in ('scratch','reviews')) or data.get('kind') not in ('photo','frame','thumbnail','card'):
                    raise ValueError('Unknown preview')
                image=google.storage_bytes(uri,max_bytes=8388608)
                if data['kind']=='frame':
                    from .enrichment import jpeg_preview
                    _,image=jpeg_preview(image,edge=960)
                value={'mime':'image/jpeg','data':base64.b64encode(image).decode()}
            elif op=='asset_data':
                job=dashboard.call('review_context',job=data['job'])
                uri=None
                if data.get('kind')=='photo':
                    candidates=job.get('review',{}).get('photos',{}).get(data['person'],{}).get('candidates',[])
                    selected=next((c for c in candidates if c['id']==data['candidate']),None)
                    if selected:uri=selected.get('source_preview_uri') or selected.get('preview_uri') if data.get('variant')=='source' else selected.get('preview_uri')
                elif data.get('kind')=='frame':
                    tasks=job['stages']['render'].get('tasks',[])
                    if tasks:uri=tasks[0].get('result',{}).get('preview_uri')
                    if uri:
                        from .enrichment import jpeg_preview
                        _,preview=jpeg_preview(google.storage_bytes(uri,max_bytes=8388608),edge=960)
                        value={'mime':'image/jpeg','data':base64.b64encode(preview).decode()}
                else:
                    result=job['stages']['plan'].get('result',{})
                    uri=result.get({'thumbnail':'thumbnail_preview_uri','frame':'preview_uri'}.get(data.get('kind')))
                if not uri:raise ValueError('Unknown preview')
                if data.get('kind')!='frame':value={'mime':'image/jpeg','data':base64.b64encode(google.storage_bytes(uri)).decode()}
            else:
                raise ValueError('Unknown operation')
        except PermissionError:
            status, value = '401 Unauthorized', {'ok': False, 'error': 'Authentication failed'}
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            if environ.get('PATH_INFO')=='/v1/recovery':
                from .diagnostics import Redactor
                detail=Redactor(settings,locals().get('request',{})).text(error,1500)
                status,value='400 Bad Request',{'ok':False,'error':'Repair request rejected: '+detail}
            else:status, value = '400 Bad Request', {'ok': False, 'error': 'Invalid request or credential currently in use'}
        except Exception:
            status, value = '503 Service Unavailable', {'ok': False, 'error': 'Cloud operation unavailable'}
        if status == '200 OK':
            value = {'ok': True, 'result': value}
        encoded = json.dumps(value).encode()
        start_response(status, [('Content-Type', 'application/json'), ('Cache-Control', 'no-store'),
                                ('Content-Length', str(len(encoded)))])
        return [encoded]
    return app


def load_app():
    path = Path(os.environ.get('SCOTUS_CONTROL_CONFIG', '/secrets/control/config.json'))
    return make_app(json.loads(path.read_text()))
