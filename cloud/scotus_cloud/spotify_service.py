"""Private, short-lived Spotify reconciliation requests; no media transfer here."""
import json
from pathlib import Path
import time
import requests

from .google import Google
from .remote import Dashboard
from .spotify import Spotify, SpotifyAuthRequired, SpotifyError


def reconcile(job_id, settings, google, dashboard, client):
    context=dashboard.call('spotify_context',job=job_id);item=context['spotify']
    status=item.get('status')
    if not status or status in ('starting','uploading','published','failed','needs_auth') or item.get('retry_after',0)>time.time():return {'status':status or 'idle'}
    generation=item['generation']
    def update(target,**fields):
        return dashboard.call('spotify_update',job=job_id,generation=generation,expected_status=status,status=target,**fields)
    try:
        if status in ('queued','waiting_episode'):
            episode=client.metadata(item['episode_id']) if item.get('episode_id') else client.find_episode(context)
            if episode and ('['+context['docket']+']' not in episode.get('name','') or (context.get('duration_seconds') and abs(float(episode.get('duration',0))/1000-float(context['duration_seconds']))>5)):
                raise SpotifyError('Selected Spotify episode does not match this recording')
            if not episode:
                update('waiting_episode',retry_after=int(time.time())+300,note='Waiting for Spotify to discover the RSS episode')
                return {'status':'waiting_episode'}
            if episode.get('hasVideo'):
                update('published',episode_id=episode['id'],note='The existing Spotify episode already has a video')
                return {'status':'published'}
            if item.get('upload_id'):
                remote=client.upload_status(item['upload_id'])
                if remote.get('spotifyEpisodeId')!=episode['id']:raise SpotifyError('Saved upload belongs to a different episode')
                if remote.get('status') in ('UPLOADED','PUBLISHING','PUBLISHED'):
                    # PHP fences this transition and requires saved owner approval
                    # before any later publish operation.
                    update('uploaded',episode_id=episode['id'],note='Existing upload recovered; no media retransmitted')
                    return {'status':'uploaded'}
            reserved=dashboard.call('spotify_reserve',job=job_id,generation=generation,episode_id=episode['id'])
            if not reserved:return {'status':'changed'}
            try:
                operation=google.execute(settings['region'],settings['transfer_job'],{
                    'SCOTUS_JOB_ID':job_id,'SCOTUS_SPOTIFY_GENERATION':generation,
                    'SCOTUS_SPOTIFY_TOKEN':reserved['dispatch_token']})
                return {'status':'starting','operation':operation}
            except Exception:
                dashboard.call('spotify_update',job=job_id,generation=generation,expected_status='starting',status='failed',error='Cloud launch was not confirmed. Retry safely fences any delayed worker.')
                return {'status':'failed'}
        remote=client.upload_status(item['upload_id'])
        if remote.get('spotifyEpisodeId')!=item['episode_id']:raise SpotifyError('Saved upload belongs to a different episode')
        if remote.get('failureReason') or remote.get('status') in ('FAILED','ERROR'):
            raise SpotifyError('Spotify processing failed: '+str(remote.get('failureReason') or remote.get('status'))[:200])
        if remote.get('status')=='PUBLISHED':
            metadata=client.metadata(item['episode_id'])
            if metadata.get('hasVideo') and metadata.get('mediaUploadId')==item['upload_id']:
                update('published',note='Spotify finished processing the video');return {'status':'published'}
        if status=='publish_queued':
            if not item.get('publish_authorized'):raise SpotifyError('Publication needs your approval')
            if update('publishing',retry_after=int(time.time())+60,note='Spotify publication requested'):
                try:client.publish(item['episode_id'],item['upload_id'])
                except SpotifyAuthRequired:
                    dashboard.call('spotify_update',job=job_id,generation=generation,expected_status='publishing',status='needs_auth',error='Reconnect Spotify, then retry publication')
                except SpotifyError as error:
                    dashboard.call('spotify_update',job=job_id,generation=generation,expected_status='publishing',status='failed',error=str(error))
                except requests.RequestException:
                    pass # Reconcile this saved upload on the next tick; never reupload.
            return {'status':'publishing'}
        if status=='publishing' and remote.get('status')=='UPLOADED':
            update('failed',error='Spotify has not started publication. Retry reconciles the saved upload, then use Publish on Spotify again.');return {'status':'failed'}
        update(status,retry_after=int(time.time())+60)
        return {'status':status}
    except SpotifyAuthRequired as error:
        update('needs_auth',error=str(error));return {'status':'needs_auth'}
    except SpotifyError as error:
        update('failed',error=str(error));return {'status':'failed'}
    except Exception:
        update(status,retry_after=int(time.time())+300,note='Spotify connection unavailable; will check again')
        return {'status':status}


def make_app(settings,google_factory=Google):
    def app(environ,start_response):
        try:
            if environ.get('REQUEST_METHOD')!='POST' or environ.get('PATH_INFO')!='/action':raise ValueError('Unknown route')
            length=int(environ.get('CONTENT_LENGTH',0))
            if not 0<length<=4096:raise ValueError('Invalid request')
            data=json.loads(environ['wsgi.input'].read(length));google=google_factory(settings['project'])
            dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'spotify')
            client=Spotify(google,dashboard,settings['spotify_secret'],settings['show_id'])
            if data.get('probe'):
                client.authenticate();result={'connected':True,'automatic':False}
            else:result=reconcile(data['job'],settings,google,dashboard,client)
            body=json.dumps({'ok':True,'result':result}).encode();status='200 OK'
        except SpotifyAuthRequired:
            body=json.dumps({'ok':False,'error':'Spotify sign-in needs renewal'}).encode();status='409 Conflict'
        except Exception:
            body=json.dumps({'ok':False,'error':'Spotify delivery unavailable'}).encode();status='503 Service Unavailable'
        start_response(status,[('Content-Type','application/json'),('Content-Length',str(len(body)))]);return [body]
    return app


def load_app():return make_app(json.loads(Path('/secrets/spotify/config.json').read_text()))
