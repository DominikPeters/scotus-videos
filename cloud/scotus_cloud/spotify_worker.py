"""Stream a saved MP4 from GCS into Spotify unchanged and publish within the same authorized transfer."""
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import time
from urllib.parse import quote
import uuid

from .secret_store import runtime_settings
from .google import Google,split_gs
from .remote import Dashboard
from .spotify import Spotify,SpotifyAuthRequired,SpotifyError,transfer_thumbnail


def transfer(context,client,google,checkpoint,heartbeat):
    item=context['spotify'];episode=item['episode_id']
    metadata=client.metadata(episode)
    if metadata.get('hasVideo'):raise SpotifyError('This Spotify episode already has a video; reconcile before retrying')
    uri=context['video']['video_uri'];bucket,key=split_gs(uri)
    if bucket!=google.project+'-scotus-video-media' or not key.startswith('scratch/'+context['id']+'/assemble/') or not key.endswith('/video.mp4'):
        raise ValueError('Invalid recording video')
    info=google.request('GET',f'https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(key,safe="")}')
    size=int(info['size']);generation=info['generation'];offset=0
    upload=item.get('upload_id')
    if upload:
        status=client.upload_status(upload)
        if status.get('spotifyEpisodeId')!=episode:raise SpotifyError('Saved upload belongs to another episode')
        if status.get('status')=='UPLOADED':return upload
        if status.get('status')!='UPLOADING':raise SpotifyError('Saved upload is not resumable; reconcile its status')
        offset=int(status.get('uploadedBytes') or 0)
        if not 0<=offset<size:raise SpotifyError('Saved upload offset needs review')
    else:
        upload=client.reserve_upload(episode)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',upload):raise SpotifyError('Invalid upload identity')
        if not checkpoint(upload):raise SpotifyError('Upload checkpoint could not be saved')
        # # Durably save identity before sending any media.
    boundary='scotus'+uuid.uuid4().hex
    filename=context['id']+'.mp4'
    prefix=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: video/mp4\r\n\r\n').encode()
    suffix=(f'\r\n--{boundary}--\r\n').encode()
    connection=http.client.HTTPSConnection('media-importer.spotify.com',timeout=120,context=ssl.create_default_context())
    connection.putrequest('POST','/v1/uploadfile/'+upload)
    for k,v in client.headers().items():connection.putheader(k,v)
    connection.putheader('Content-Type','multipart/form-data; boundary='+boundary)
    connection.putheader('Content-Length',str(len(prefix)+size-offset+len(suffix)))
    if offset:connection.putheader('offset',str(offset))
    connection.endheaders();connection.send(prefix)
    url=f'https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(key,safe="")}'
    sent=offset;last=time.monotonic();heartbeat(sent/size)
    try:
        with google.session.get(url,params={'alt':'media','generation':generation},headers={'Range':f'bytes={offset}-'} if offset else {},stream=True,timeout=60) as response:
            if response.status_code!=(206 if offset else 200):raise SpotifyError('Saved video could not be read')
            for block in response.iter_content(1024*1024):
                if time.monotonic()-last>=20:heartbeat(sent/size);last=time.monotonic()
                connection.send(block);sent+=len(block)
        if sent!=size:raise SpotifyError('Video transfer ended early')
        connection.send(suffix);response=connection.getresponse();body=response.read(65536)
        if response.status!=200:raise SpotifyError('Spotify upload HTTP '+str(response.status))
        result=json.loads(body)
        if result.get('uploadId')!=upload or result.get('status')!='UPLOADED':raise SpotifyError('Spotify upload needs reconciliation')
        heartbeat(1);return upload
    finally:connection.close()


def main():
    if not os.environ.get('CLOUD_RUN_JOB'):raise RuntimeError('Cloud worker required')
    settings=runtime_settings('/secrets/spotify/config.json');google=Google(settings['project'])
    dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'spotify')
    identity={'job':os.environ['SCOTUS_JOB_ID'],'generation':os.environ['SCOTUS_SPOTIFY_GENERATION']}
    claim=dashboard.call('spotify_claim',**identity,dispatch_token=os.environ['SCOTUS_SPOTIFY_TOKEN'],claim_id=uuid.uuid4().hex)
    if not claim:return
    lease=claim['lease'];expected='uploading'
    def update(status,**fields):return dashboard.call('spotify_update',**identity,lease=lease,expected_status=expected,status=status,**fields)
    try:
        context=dashboard.call('spotify_context',job=identity['job'])
        client=Spotify(google,dashboard,settings['spotify_secret'],settings['show_id'])
        upload=transfer(context,client,google,lambda value:update('uploading',upload_id=value),
                        lambda progress:dashboard.call('spotify_heartbeat',**identity,lease=lease,progress=progress))
        if context['spotify'].get('publish_authorized'):
            thumbnail=transfer_thumbnail(context,client,google)
            if not update('publishing',upload_id=upload,retry_after=int(time.time())+60,note='Video uploaded; publishing on Spotify'):
                raise SpotifyError('Spotify transfer state changed before publication')
            expected='publishing'
            if thumbnail:update('publishing',**thumbnail)
            client.publish(context['spotify']['episode_id'],upload)
        else:
            update('uploaded',upload_id=upload,note='Original video uploaded; legacy transfer needs publication authorization')
        print('Spotify transfer complete',flush=True)
    except Exception as error:
        try:update('needs_auth' if isinstance(error,SpotifyAuthRequired) else 'failed',error=str(error)[:300] if isinstance(error,SpotifyError) or isinstance(error,SpotifyAuthRequired) else 'Transfer interrupted. Retry checks the saved upload before resuming.')
        except Exception:pass
        print('Spotify transfer needs attention',flush=True)
        raise RuntimeError('Spotify transfer failed; inspect the private dashboard') from None


if __name__=='__main__':main()
