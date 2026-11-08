"""Repair execution broker. Only fixed jobs, tested releases and owned recordings."""
import hashlib,json,uuid,re
from .model import digest_json
from .attempts import launch
from .repair_policy import reserve_estimate,verify_release,validate_changes,file_hash
from .releases import repair_source,current as current_deployment


def current_release(baseline,release,google,profile,release_id=None):
    """Rebase only when every edited file still has exactly its original source."""
    if release.get('schema_version')==2:
        if release.get('release_id')==release_id:
            verify_release(baseline,release,release_id);return release
        if any((file_hash(baseline[name]) if name in baseline else None)!=old for name,old in release['base_files'].items()):return None
        return validate_changes(baseline,release['files'],release_id)
    if release.get('baseline_sha256')==digest_json(baseline):
        verify_release(baseline,release);return validate_changes(baseline,release["files"],release_id) if release_id else release
    old_hash=release.get('baseline_sha256','')
    if not re.fullmatch('[a-f0-9]{64}',old_hash):raise ValueError('Invalid repair baseline hash')
    old=google.storage_json(f"gs://{profile['bucket']}/recovery/baselines/{old_hash}.json",max_bytes=2097152)
    if not old or digest_json(old)!=old_hash:return None
    verify_release(old,release)
    if any(baseline.get(name)!=old.get(name) for name in release['files']):return None
    return validate_changes(baseline,release['files'],release_id)


def safe_upload_checkpoint(saved):
    checkpoint={key:saved[key] for key in ('creation_pending','thumbnail_done','playlist_done','comment_done','postprocessing_complete') if isinstance(saved.get(key),bool)}
    import re
    if re.fullmatch(r'[A-Za-z0-9_-]{11}',str(saved.get('video_id',''))):checkpoint['video_id']=saved['video_id']
    error=saved.get('last_error')
    if isinstance(error,dict) and error.get('operation')=='thumbnail' and isinstance(error.get('status'),int):
        reasons=error.get('reasons',[])
        checkpoint['last_error']={'operation':'thumbnail','status':error['status'],'reasons':[reason for reason in reasons if isinstance(reason,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',reason)][:5] if isinstance(reasons,list) else []}
    return checkpoint


def dispatch_recoveries(dashboard,google,settings):
    profile=settings.get('recovery',{})
    if not profile.get('enabled'):return []
    records=dashboard.call('recoveries')
    for rec in records.values():
        if rec['status']!='waiting_for_tests':continue
        action=rec.get('actions',{}).get(rec.get('pending_action'),{})
        result=action.get('result',{});uri=result.get('report_uri')
        if not uri:continue
        try:report=google.storage_json(uri,max_bytes=65536)
        except Exception:continue
        if report is None:
            job_name=profile['test_job'] if action['kind'] in ('tests','probe') else settings['jobs']['upload']
            try:execution=google.find_repair_execution(settings['region'],job_name,rec['pending_action'])
            except Exception:continue
            if execution and execution['done']:
                report={'passed':False,'kind':action['kind'],'private_note':'The owned execution ended without a report. Inspect its action logs before retrying.'}
            elif not execution:
                from datetime import datetime,timezone
                created=datetime.fromisoformat(action['created_at'])
                if (datetime.now(timezone.utc)-created).total_seconds()>300:
                    report={'passed':False,'kind':action['kind'],'private_note':'No matching cloud execution appeared within five minutes. Reconcile this action before a new launch.'}
        if report is not None:
            dashboard.call('recovery_tests_ready',recovery=rec['id'],action_id=rec['pending_action'],passed=bool(report.get('passed')),report=report)
    records=dashboard.call('recoveries')
    if any(r['status'] in ('starting','running') for r in records.values()):return []
    for rec in records.values():
        if rec['status']!='queued':continue
        claimed=dashboard.call('recovery_dispatch',recovery=rec['id'],reserve_usd=reserve_estimate(1,2,1320),seconds=1320)
        if not claimed:continue
        try:
            operation=launch(dashboard,google,settings,{'kind':'recovery','recovery':rec['id']},profile['job'],{'SCOTUS_RECOVERY_ID':rec['id'],'SCOTUS_RECOVERY_TOKEN':claimed['dispatch_token']})
        except Exception:
            return []
        return [{'recovery':rec['id'],'operation':operation}]
    return []


def broker(dashboard,google,settings,data):
    rid=data['recovery'];lease=data['lease'];tool=data['tool'];args=data.get('arguments',{})
    context=dashboard.call('recovery_context',recovery=rid,lease=lease)
    rec=context['recovery'];job=context['job'];profile=settings['recovery']
    if tool in ('context','logs','source_info'):
        from .recovery_evidence import evidence
        return evidence(tool,args,context,settings,google)
    if tool=='media':
        from .recovery_evidence import media_locator
        return media_locator(args,context,settings)
    if tool=='probe':
        from .recovery_evidence import launch_probe
        return launch_probe(dashboard,google,settings,context,data)
    if tool=='reconcile_action':
        action=rec.get('actions',{}).get(args['action'])
        if not action or action['kind'] not in ('tests','probe','upload_audit'):raise ValueError('Unknown owned recovery action')
        job_name=profile['test_job'] if action['kind'] in ('tests','probe') else settings['jobs']['upload']
        execution=google.find_repair_execution(settings['region'],job_name,args['action'])
        return {'action':args['action'],'execution':execution,'recorded_result':action.get('result'),
                'private_note':'A matching execution means do not launch a duplicate. An absent execution should be checked again after the five-minute launch grace period.'}
    if tool=='artifact':
        field=args['field'];stage=args['stage']
        if field=='upload_state':
            if rec['stage']!='upload' or stage!='upload':raise ValueError('Upload context is scoped to this recovery')
            saved=job['stages']['upload'].get('checkpoint',{})
            checkpoint=safe_upload_checkpoint(saved)
            actions=[]
            for key,action in rec.get('actions',{}).items():
                if action['kind']!='upload_audit':continue
                uri=f"gs://{profile['bucket']}/recovery/audits/{rid}/{key}.json"
                report=google.storage_json(uri,max_bytes=65536)
                actions.append({'action':key,'status':'complete' if report else action['status'],'report':report})
            value={'checkpoint':checkpoint,'session_saved':bool(saved.get('session_url')),'audit_actions':actions}
            text=json.dumps(value);offset=max(0,int(args['offset']))
            return {'text':text[offset:offset+32000],'offset':offset,'total_characters':len(text)}
        if field not in ('transcript_uri','words_uri','plan_uri','interactions_uri','enrichment_uri'):raise ValueError('Unknown JSON artifact')
        uri=job['stages'][stage].get('result',{}).get(field)
        if not uri or not uri.startswith('gs://'+profile['bucket']+'/') or not uri.endswith('.json'):raise ValueError('Unowned JSON artifact')
        if args.get('export_file'):return {'uri':uri,'filename':stage+'-'+field.removesuffix('_uri')+'.json'}
        value=google.storage_json(uri,max_bytes=2097152);offset=max(0,int(args['offset']))
        text=json.dumps(value,ensure_ascii=False)
        return {'text':text[offset:offset+32000],'offset':offset,'total_characters':len(text),'untrusted_source_data':True}
    if tool=='refresh_sources':
        from .maintenance import refresh
        return refresh(dashboard,google,settings,job['id'],manual=True,keep_recovery=rid,lease=lease)
    if tool=='tests':
        baseline,release_id=repair_source(google,settings)
        uri=args['release_uri']
        if not uri.startswith(f"gs://{profile['bucket']}/recovery/workspaces/{rid}/"):raise ValueError('Unowned release')
        supplied=google.storage_json(uri,max_bytes=262144)
        release=current_release(baseline,supplied,google,profile,release_id)
        if release is None:
            return {'status':'source_changed','private_note':'The workflow changed after this repair turn started. No test was launched. Restart recovery against current source; do not overwrite the updated files.'}
        if release!=supplied:
            import tempfile
            from pathlib import Path
            uri=f"gs://{profile['bucket']}/recovery/workspaces/{rid}/{uuid.uuid4().hex}.json"
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'release.json';path.write_text(json.dumps(release));google.storage_upload(path,uri,'application/json')
        if not release['stages']:raise ValueError('Pair regression tests with a workflow fix, or use a diagnostic probe')
        key=hashlib.sha256((rid+data['call_id']).encode()).hexdigest()
        out=f"gs://{profile['bucket']}/recovery/tests/{rid}/{key}.json"
        claimed=dashboard.call('recovery_action_claim',recovery=rid,lease=lease,action_id=key,
            request_hash=digest_json(args),kind='tests',reserve_usd=reserve_estimate(1,1,180),seconds=180)
        if 'existing' in claimed:return {'action':key,**claimed['existing']}
        if claimed.get('budget_exhausted'):return {'budget_exhausted':True}
        result={'operation':None,'report_uri':out,'release_uri':uri,'release_sha256':digest_json(release)}
        dashboard.call('recovery_action_result',recovery=rid,lease=lease,action_id=key,result=result)
        operation=google.execute(settings['region'],profile['test_job'],{'SCOTUS_PROJECT':settings['project'],
            'SCOTUS_TEST_SOURCE_URI':uri,'SCOTUS_TEST_RESULT_URI':out,
            'SCOTUS_REPAIR_ACTION_ID':key,
            **({'SCOTUS_TEST_BASELINE_URI':f"gs://{profile['bucket']}/recovery/baselines/{release['baseline_sha256']}.json"} if release.get('schema_version')==1 else {})})
        result['operation']=operation
        dashboard.call('recovery_action_result',recovery=rid,lease=lease,action_id=key,result=result)
        return {'action':key,**result}
    if tool=='poll':
        action=rec['actions'].get(args['action'])
        if not action:raise ValueError('Unknown repair action')
        result=action.get('result')
        if not result and action['kind']=='upload_audit':
            result={'report_uri':f"gs://{profile['bucket']}/recovery/audits/{rid}/{args['action']}.json"}
        if not result:return {'status':'execution_not_confirmed'}
        report=google.storage_json(result['report_uri'],max_bytes=65536) or action.get('completion_report')
        return {'status':'complete' if report else 'running','report':report}
    if tool=='inspect_upload':
        if rec['stage']!='upload':raise ValueError('Upload audit is only for the failed upload stage')
        key=hashlib.sha256((rid+data['call_id']).encode()).hexdigest()
        claimed=dashboard.call('recovery_action_claim',recovery=rid,lease=lease,action_id=key,request_hash=digest_json(args),kind='upload_audit',reserve_usd=reserve_estimate(1,2,180),seconds=180)
        if 'existing' in claimed:return {'action':key,**claimed['existing']}
        if claimed.get('budget_exhausted'):return {'budget_exhausted':True}
        out=f"gs://{profile['bucket']}/recovery/audits/{rid}/{key}.json"
        result={'operation':None,'report_uri':out}
        dashboard.call('recovery_action_result',recovery=rid,lease=lease,action_id=key,result=result)
        operation=google.execute(settings['region'],settings['jobs']['upload'],{'SCOTUS_STAGE':'upload','SCOTUS_JOB_ID':job['id'],'SCOTUS_UPLOAD_AUDIT':'1','SCOTUS_AUDIT_ACTION':key,'SCOTUS_AUDIT_REPORT':out,'SCOTUS_REPAIR_ACTION_ID':key},timeout_seconds=180)
        result['operation']=operation
        dashboard.call('recovery_action_result',recovery=rid,lease=lease,action_id=key,result=result);return {'action':key,**result}
    if tool=='adopt_upload':
        action=rec['actions'].get(args['action'])
        if not action or action['kind']!='upload_audit':raise ValueError('An owned upload audit is required')
        report=google.storage_json(action['result']['report_uri'],max_bytes=65536)
        if not report or report['recording']!=job['id'] or not any(c['video_id']==args['video_id'] for c in report['candidates']):raise ValueError('This video has not been verified by the uploader')
        return dashboard.call('recovery_adopt_upload',recovery=rid,lease=lease,video_id=args['video_id'])
    if tool=='retry':
        if not settings.get('workers_enabled'):return {'status':'workers_disabled'}
        from .model import STAGE_ORDER,removed_render_chunks
        restart=args.get('restart_from') or rec['stage']
        if restart not in STAGE_ORDER or STAGE_ORDER.index(restart)>STAGE_ORDER.index(rec['stage']):raise ValueError('Restart must be this phase or an upstream phase')
        restore_chunks=restart=='assemble' and bool(removed_render_chunks(job))
        if restore_chunks:restart='render'
        render_only=job.get('render_revision',{}).get('status')=='queued' and restart in ('plan','render','assemble') and rec['stage'] in ('plan','render','assemble')
        if restart!=rec['stage'] and job['stages']['upload'].get('checkpoint') and not render_only:raise ValueError('An existing upload cannot be rewound automatically')
        release_pointer=None;release_stages=[];reusable=None
        if args.get('action'):
            baseline,release_id=repair_source(google,settings)
            action=rec['actions'].get(args['action'],{}).get('result',{})
            report=google.storage_json(action['report_uri'],max_bytes=65536)
            if not report or not report.get('passed') or report['release_sha256']!=action['release_sha256']:raise ValueError('Patch has not passed isolated tests')
            release_pointer={'uri':action['release_uri'],'sha256':action['release_sha256']}
            release=google.storage_json(action['release_uri'],max_bytes=262144)
            if (release.get('schema_version')==2 and release.get('release_id')!=release_id) or (release.get('schema_version')==1 and release.get('baseline_sha256')!=digest_json(baseline)):
                return {'status':'source_changed','private_note':'Workflow source changed since these tests passed. Test the candidate against current source before requesting a retry.'}
            verify_release(baseline,release,release_id)
            release_stages=release['stages']
            if any(STAGE_ORDER.index(s)<STAGE_ORDER.index(restart) for s in release_stages):raise ValueError('Restart from the earliest phase affected by the tested patch')
            if 'render' in release_stages:restore_chunks=False
            if args.get('reusable'):
                reason=args.get('reuse_reason','').strip()
                if not reason or len(reason)>2000:raise ValueError('Explain why this repair is input-independent')
                reusable={**release_pointer,**({'release_id':release_id} if release_id else {'baseline_sha256':release['baseline_sha256']}),'stages':release_stages,'reason':reason,'test_report_uri':action['report_uri']}
        elif args.get('reusable'):raise ValueError('Only tested code changes can become reusable defaults')
        if rec['error']=='upload_uncertain':return {'status':'upload_reconciliation_required'}
        resource=profile.get('stage_resources',{}).get(restart)
        if not resource:return {'status':'resource_profile_unavailable'}
        if restart=='align' and settings.get('alignment_long_job'):
            from .model import alignment_cpus
            resource=[alignment_cpus(job,google),*resource[1:]]
        if rec['stage']=='upload' and job['stages']['upload'].get('checkpoint',{}).get('video_id'):
            resource=[*resource[:2],min(300,resource[2])]
        tasks=job['stages'][restart].get('tasks',[])
        rerender_all=restart=='render' and (('render' in release_stages) or (restart!=rec['stage'] and not restore_chunks))
        missing=removed_render_chunks(job) if restart=='render' else set()
        count=(len(tasks) if rerender_all else sum(item.get('status')!='complete' or i in missing for i,item in enumerate(tasks))) or 1
        estimate=reserve_estimate(*resource,tasks=count)
        if estimate>1:return {'budget_exhausted':True,'conservative_reservation_usd':estimate,'private_note':'This retry exceeds the $1 daily repair cap.'}
        key=hashlib.sha256((rid+data['call_id']).encode()).hexdigest()
        claimed=dashboard.call('recovery_action_claim',recovery=rid,lease=lease,action_id=key,request_hash=digest_json(args),
            kind='retry',reserve_usd=estimate,seconds=resource[2])
        if 'existing' in claimed:return {'action':key,**claimed['existing']}
        if claimed.get('budget_exhausted'):return {'budget_exhausted':True}
        dashboard.call('recovery_retry',recovery=rid,lease=lease,release=release_pointer,release_stages=release_stages,reusable=reusable,restart_from=restart,restore_render_chunks=restore_chunks)
        result={'status':'queued','release':release_pointer,'restart_from':restart}
        dashboard.call('recovery_action_result',recovery=rid,lease=lease,action_id=key,result=result)
        return result
    raise ValueError('Unknown repair execution tool')
