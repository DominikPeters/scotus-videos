"""Narrow Studio session adapter for a Short's native full-video reference."""
import copy,hashlib,json,re,time

ORIGIN='https://studio.youtube.com'
VIDEO_ID=re.compile(r'[A-Za-z0-9_-]{11}\Z')


def authorization(cookies,now=None):
    stamp=str(int(time.time() if now is None else now));parts=[]
    for scheme,name in [('SAPISIDHASH','SAPISID'),('SAPISID1PHASH','__Secure-1PAPISID'),('SAPISID3PHASH','__Secure-3PAPISID')]:
        value=cookies.get(name) or (cookies.get('__Secure-3PAPISID') if name=='SAPISID' else None)
        if value:
            digest=hashlib.sha1((stamp+' '+value+' '+ORIGIN).encode()).hexdigest()
            parts.append(scheme+' '+stamp+'_'+digest)
    if not parts:raise ValueError('YouTube Studio session needs renewal')
    return ' '.join(parts)


class Studio:
    def __init__(self,credential,session=None):
        import requests
        self.credential=copy.deepcopy(credential);self.session=session or requests.Session()
        self.cookies=dict(credential['cookies'])
    def call(self,operation,data):
        if operation not in ('creator/get_creator_videos','video_manager/metadata_update'):raise ValueError('Unsupported Studio action')
        headers={k:v for k,v in self.credential.get('headers',{}).items() if k.lower() in ('user-agent','x-goog-authuser','x-youtube-delegation-context','x-youtube-client-name','x-youtube-client-version')}
        headers.update({'Origin':ORIGIN,'X-Origin':ORIGIN,'Content-Type':'application/json','Authorization':authorization(self.cookies),'Cookie':'; '.join(k+'='+v for k,v in self.cookies.items())})
        body={'context':copy.deepcopy(self.credential['context']),**data}
        try:r=self.session.post(ORIGIN+'/youtubei/v1/'+operation+'?alt=json',headers=headers,json=body,timeout=30,allow_redirects=False)
        except Exception:raise ValueError('YouTube Studio request did not complete; read back before retrying') from None
        if r.status_code!=200:raise ValueError('YouTube Studio HTTP '+str(r.status_code)+'; session or browser verification may need renewal')
        # Honor session-cookie rotation between the read, update and verification.
        from requests.cookies import RequestsCookieJar
        if isinstance(getattr(r,'cookies',None),RequestsCookieJar):
            for cookie in r.cookies:
                if cookie.name in self.cookies and cookie.domain.lstrip('.') in ('youtube.com','studio.youtube.com'):
                    self.cookies[cookie.name]=cookie.value
            self.credential['cookies']=dict(self.cookies)
        try:result=r.json()
        except ValueError:raise ValueError('YouTube Studio returned an unexpected response') from None
        if result.get('error'):raise ValueError('YouTube Studio rejected the related-video request')
        return result
    def read(self,video_id):
        if not VIDEO_ID.fullmatch(video_id):raise ValueError('Invalid YouTube video ID')
        result=self.call('creator/get_creator_videos',{'videoIds':[video_id],'mask':{'videoId':True,'channelId':True,'title':True,'videoLinkageShortsAttribution':{'all':True}},'failOnError':True,'criticalRead':True})
        rows=result.get('videos',[])
        if len(rows)!=1 or rows[0].get('videoId')!=video_id:raise ValueError('Studio did not return the selected video')
        return rows[0]
    def link(self,video_id,target_id,expected_channel,checkpoint=lambda **values:None):
        if not VIDEO_ID.fullmatch(target_id) or video_id==target_id:raise ValueError('Invalid full-video target')
        video=self.read(video_id);target=self.read(target_id)
        if video.get('channelId')!=expected_channel or target.get('channelId')!=expected_channel:raise ValueError('Related videos must belong to the configured channel')
        def matches(row):return [link.get('targetExternalVideoId') for link in row.get('videoLinkageShortsAttribution',{}).get('links',[])]==[target_id]
        if not matches(video):
            checkpoint(related_video_id=target_id,related_video_pending=True)
            self.call('video_manager/metadata_update',{'encryptedVideoId':video_id,'flowType':'MDE_FLOW_TYPE_EDIT','videoReadMask':{'videoId':True,'videoLinkageShortsAttribution':{'all':True}},'videoLinkageShortsAttribution':{'targetExternalVideoId':[target_id]}})
            for attempt in range(4):
                if matches(self.read(video_id)):break
                if attempt<3:time.sleep(2)
            else:raise ValueError('YouTube Studio related-video update is not yet confirmed')
        checkpoint(related_video_id=target_id,related_video_pending=False,related_video_verified=True)
        return {'related_video_id':target_id,'related_video_verified':True}


def link_for_clip(job,clip,settings,cloud,lease,video_id):
    target=job.get('stages',{}).get('upload',{}).get('result',{}).get('video_id')
    if not target:return {'related_video_status':'no_source_video'}
    if not settings.get('youtube_studio_secret'):return {'related_video_status':'not_configured'}
    try:
        credential=json.loads(cloud.secret(settings['youtube_studio_secret']))
        result=Studio(credential).link(video_id,target,settings['youtube_channel_id'],lambda **values:lease.call('checkpoint',checkpoint=values))
        return {**result,'related_video_status':'linked'}
    except Exception as error:
        # Upload succeeded; a metadata problem must not trigger another media upload.
        message=str(error) if isinstance(error,ValueError) else 'Studio session or connection needs attention'
        return {'related_video_id':target,'related_video_verified':False,'related_video_status':'needs_attention','related_video_error':message[:240]}


def link_existing(job,clip,settings,cloud,lease):
    video_id=(clip.get('youtube') or {}).get('video_id') or (clip.get('upload') or {}).get('video_id')
    if not video_id:raise ValueError('Upload this clip to YouTube first')
    token=lease.dashboard.call('auth_claim',name='youtube')
    if not token:raise ValueError('YouTube credentials are busy; retry shortly')
    lease.auth=('youtube',token)
    try:return {**clip.get('youtube',{}),**link_for_clip(job,clip,settings,cloud,lease,video_id)}
    finally:
        lease.auth=None;lease.dashboard.call('auth_release',name='youtube',token=token)
