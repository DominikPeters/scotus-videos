"""Owner-requested Reels: convert, host privately and publish entirely in Cloud Run."""
import json,os,subprocess,time,uuid
from .google import split_gs
from .clip_control import signed_media_url


def api(session,token,method,endpoint,**data):
    # Bearer header keeps credentials out of URLs and error diagnostics.
    response=session.request(method,'https://graph.instagram.com/v25.0/'+endpoint,
        headers={'Authorization':'Bearer '+token},data=data if method=='POST' else None,
        params=data if method=='GET' else None,timeout=60)
    if response.status_code>=400:
        error=response.json().get('error',{})
        raise ValueError('Instagram HTTP '+str(response.status_code)+' (code '+str(error.get('code','unknown'))+')')
    return response.json()


def publish(session,credential,state,checkpoint,caption,url,check,wait=time.sleep,location_id=None):
    """Checkpoint every external identity; uncertain POSTs never create duplicates."""
    token=credential['access_token'];uid=credential['user_id']
    # Freeze the requested place once a container exists; retries never retag it.
    location_id=state.get('location_id') if state.get('container_id') or state.get('media_id') else state.get('location_id',location_id)
    if location_id is not None and (not isinstance(location_id,str) or not location_id.isdecimal() or len(location_id)>32):raise ValueError('Instagram location must be a numeric place Page ID')
    media=state.get('media_id')
    if not media:
        container=state.get('container_id')
        if not container:
            if state.get('creation_pending'):raise ValueError('Instagram upload creation is unconfirmed; reconcile before another upload')
            location={'location_id':location_id} if location_id else {}
            checkpoint(creation_pending=True,**location)
            container=api(session,token,'POST',uid+'/media',media_type='REELS',video_url=url,caption=caption,share_to_feed='true',**location)['id']
            checkpoint(container_id=container,creation_pending=False)
        for _ in range(48):
            check();status=api(session,token,'GET',container,fields='status_code')['status_code']
            if status=='FINISHED':break
            if status in ('ERROR','EXPIRED'):raise ValueError('Instagram processing '+status.lower())
            if status=='PUBLISHED':raise ValueError('Instagram already published this container; reconcile its media identity')
            wait(10)
        else:raise ValueError('Instagram is still processing; retry will reuse the same upload')
        if state.get('publish_pending'):raise ValueError('Instagram publication is unconfirmed; reconcile before publishing again')
        check();checkpoint(publish_pending=True)
        media=api(session,token,'POST',uid+'/media_publish',creation_id=container)['id']
        checkpoint(media_id=media,publish_pending=False,published=True)
    result=api(session,token,'GET',media,fields='id,permalink')
    return {'published':True,'media_id':media,'url':result['permalink'],'caption':caption}


def transfer(job,clip,settings,cloud,lease,folder):
    import requests
    token=lease.dashboard.call('auth_claim',name='instagram')
    if not token:raise ValueError('Instagram credentials are busy; retry shortly')
    lease.auth=('instagram',token)
    try:
        credential=json.loads(cloud.secret(settings.get('instagram_secret','scotus-video-instagram')))
        if credential.get('username','').lower()!='scotus.oral.arguments':raise ValueError('Instagram account differs')
        state=dict(clip.get('instagram_checkpoint') or {})
        def check():
            lease.check();lease.dashboard.call('auth_check',name='instagram',token=token)
        def checkpoint(**values):
            check();lease.call('checkpoint',checkpoint=values);state.update(values)
        uri=state.get('video_uri')
        if not uri and not state.get('container_id') and not state.get('media_id'):
            src=folder/'source.mp4';dst=folder/'instagram.mp4'
            cloud.storage_download(clip['result']['video_uri'],src,expected_sha256=clip['result']['sha256'])
            subprocess.run(['ffmpeg','-nostdin','-y','-hide_banner','-loglevel','error','-i',str(src),'-vf','fps=30','-c:v','libx264','-preset','veryfast','-crf','23','-c:a','aac','-ar','48000','-b:a','128k','-movflags','+faststart',str(dst)],check=True,timeout=240)
            lease.update(.35)
            uri=f"gs://{settings['bucket']}/clips/{job['id']}/{clip['id']}/instagram/{uuid.uuid4().hex}/video.mp4"
            cloud.storage_upload(dst,uri,'video/mp4');checkpoint(video_uri=uri)
        url=None
        if not state.get('container_id') and not state.get('media_id'):
            bucket,key=split_gs(uri)
            if bucket!=settings['bucket'] or not key.startswith(f"clips/{job['id']}/{clip['id']}/instagram/"):raise ValueError('Unexpected Instagram source')
            signer=settings.get('instagram_signer', ('scotus-video-upload@' if os.environ.get('SCOTUS_SECRET_BUNDLES') == '1' else 'scotus-video-control@')+settings['project']+'.iam.gserviceaccount.com')
            url=signed_media_url(cloud,signer,uri,3600)['url']
        return publish(requests.Session(),credential,state,checkpoint,clip['instagram']['caption'],url,check,location_id=settings.get('instagram_location_id'))
    finally:
        lease.auth=None;lease.dashboard.call('auth_release',name='instagram',token=token)
