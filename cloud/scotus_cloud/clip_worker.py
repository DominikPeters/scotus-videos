"""Independent short vertical derivatives of an approved, frozen case bundle."""
import base64,hashlib,json,os,shutil,subprocess,tarfile,tempfile,threading,time,uuid
from pathlib import Path
from .secret_store import runtime_settings
from .google import Google
from .remote import Dashboard

class ClipLease:
    def __init__(self,dashboard,job,clip):
        self.dashboard=dashboard;self.data={'job':job,'clip':clip['id'],'lease':clip['lease']};self.auth=None;self.progress=0;self.error=None;self.stopped=threading.Event()
    def call(self,op,**kwargs):return self.dashboard.call('clip_'+op,**self.data,**kwargs)
    def check(self):
        if self.error:raise RuntimeError('Clip lease could not be renewed')
    def update(self,value):self.check();self.progress=value
    def heartbeat(self):
        while not self.stopped.wait(25):
            try:
                self.call('heartbeat',progress=self.progress)
                if self.auth:self.dashboard.call('auth_check',name=self.auth[0],token=self.auth[1])
            except Exception as e:self.error=e;return


def upload(path,job,clip,settings,cloud,lease):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    from google.auth.exceptions import RefreshError
    from .youtube import api,owned_channel,UploadError
    from .youtube_transfer import transfer
    token=lease.dashboard.call('auth_claim',name='youtube')
    if not token:raise ValueError('YouTube credentials are busy; retry this clip upload shortly')
    credentials=None;original=None;lease.auth=('youtube',token)
    try:
        original=cloud.secret(settings['youtube_secret']);credentials=Credentials.from_authorized_user_info(json.loads(original));session=AuthorizedSession(credentials)
        channel=owned_channel(session,settings);saved=dict(clip.get('upload') or {})
        if not saved.get('video_id'):
            url=saved.get('session_url')
            if not url:
                if saved.get('creation_pending'):raise ValueError('YouTube upload creation is unconfirmed. Reconcile before creating another upload.')
                lease.call('checkpoint',checkpoint={'creation_pending':True})
                source=job.get('stages',{}).get('upload',{}).get('result',{}).get('video_id')
                description=f"{job['case_name']} ({job['docket']})\nArgument excerpt: {clip['start']:.2f}–{clip['end']:.2f} seconds."
                if source:description+='\nFull argument: https://www.youtube.com/watch?v='+source
                credit=clip.get('result',{}).get('credit','')
                if credit and not credit.startswith('Justice portraits:'):description+='\n'+credit
                response=session.post('https://www.googleapis.com/upload/youtube/v3/videos',params={'uploadType':'resumable','part':'snippet,status'},headers={'X-Upload-Content-Length':str(path.stat().st_size),'X-Upload-Content-Type':'video/mp4'},json={'snippet':{'title':clip['title'],'description':description,'categoryId':'25'},'status':{'privacyStatus':'unlisted','selfDeclaredMadeForKids':False}},timeout=60)
                if response.status_code not in (200,201):raise UploadError('upload_uncertain')
                url=response.headers['Location'];lease.call('checkpoint',checkpoint={'session_url':url})
            video=transfer(session,url,path,lease);saved['video_id']=video['id'];lease.call('checkpoint',checkpoint={'video_id':video['id']})
        video_id=saved['video_id'];videos=api(session,'GET','videos',params={'part':'snippet,status','id':video_id}).get('items',[])
        if len(videos)!=1 or videos[0]['snippet']['channelId']!=channel:raise UploadError('upload_uncertain')
        from .youtube_studio import link_for_clip
        related=link_for_clip(job,clip,settings,cloud,lease,video_id)
        return {'video_id':video_id,'video_url':'https://www.youtube.com/watch?v='+video_id,'privacy':videos[0]['status']['privacyStatus'],**related}
    except RefreshError:
        raise ValueError('YouTube connection expired or was revoked. Reconnect YouTube in Settings, then retry this clip; the rendered MP4 is saved.') from None
    finally:
        try:
            if credentials and json.loads(credentials.to_json())!=json.loads(original):
                lease.dashboard.call('auth_check',name='youtube',token=token);cloud.add_secret_version(settings['youtube_secret'],credentials.to_json().encode())
        finally:
            lease.auth=None;lease.dashboard.call('auth_release',name='youtube',token=token)


def clip_credit(bundle):
    credit=json.loads((bundle/'credit.json').read_text()).get('text','')
    return '' if credit.startswith('Justice portraits:') else credit


def render(job,clip,cloud,settings,lease,folder):
    bundle=folder/'bundle';bundle.mkdir();archive=folder/'bundle.tar.gz';cloud.storage_download(clip['source_plan']['bundle_uri'],archive)
    with tarfile.open(archive) as tar:tar.extractall(folder,filter='data')
    if not (bundle/'script.js').exists():raise ValueError('Case bundle has no presentation')
    # The bundle's approved annotation cards (json/<job>-cards.json) show under the bench.
    shutil.copy2('/app/vertical.html',bundle/'vertical.html')
    plan=folder/'clip-plan.json';command=['node','/app/render/vertical.js',str(bundle),job['id'],str(clip['start']),str(clip['end']),str(plan)]
    with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True) as process:
        recent=[]
        for line in process.stdout:
            recent.append(line.strip());recent=recent[-8:]
            try:lease.update(json.loads(line)['progress']*.8)
            except (ValueError,KeyError,TypeError):pass
            if lease.error:process.terminate();raise RuntimeError('Clip lease lost')
        if process.wait():raise ValueError('Vertical rendering failed: '+' '.join(recent)[-900:])
    audio=folder/'audio.mp3';cloud.storage_download(clip['audio_uri'],audio)
    video=folder/'clip.mp4';length=(round(clip['end']*20)-round(clip['start']*20))/20
    subprocess.run(['ffmpeg','-nostdin','-y','-hide_banner','-loglevel','error','-i',str(plan)+'.mp4','-ss',str(clip['start']),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-t',str(length),'-c:v','copy','-c:a','aac','-b:a','128k','-movflags','+faststart',str(video)],check=True,timeout=180)
    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))['streams'];v=next(s for s in streams if s['codec_type']=='video')
    if (v['width'],v['height'])!=(1080,1920) or abs(float(v['duration'])-length)>.06 or not any(s['codec_type']=='audio' for s in streams):raise ValueError('Clip geometry, duration or audio differs')
    uri=f"gs://{settings['bucket']}/clips/{job['id']}/{clip['id']}/{uuid.uuid4().hex}/video.mp4";cloud.storage_upload(video,uri)
    return {'video_uri':uri,'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'duration_seconds':length,'width':1080,'height':1920,'credit':clip_credit(bundle)}


def main():
    if not os.environ.get('CLOUD_RUN_JOB'):raise RuntimeError('Clips run in the cloud')
    cfg=runtime_settings('/secrets/worker/config.json');cloud=Google(cfg['project']);dashboard=Dashboard(cfg['dashboard_url'],cfg['worker_key'],'upload')
    context=dashboard.call('clip_claim',job=os.environ['SCOTUS_JOB_ID'],clip=os.environ['SCOTUS_CLIP_ID'],token=os.environ['SCOTUS_CLIP_TOKEN'])
    if not context:return
    job,clip=context['job'],context['clip'];lease=ClipLease(dashboard,job['id'],clip);thread=threading.Thread(target=lease.heartbeat,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            if clip['mode']=='youtube_link':
                from .youtube_studio import link_existing
                result=link_existing(job,clip,cfg,cloud,lease)
            elif clip['mode']=='instagram_publish':
                from .instagram_clip import transfer as instagram_transfer
                result=instagram_transfer(job,clip,cfg,cloud,lease,folder)
            elif clip['mode'].startswith('tiktok_'):
                from .tiktok import transfer as tiktok_transfer
                result=tiktok_transfer(job,clip,cfg,cloud,lease,folder)
            elif clip['mode']=='upload':
                video=folder/'clip.mp4'
                if not clip.get('upload',{}).get('video_id'):cloud.storage_download(clip['result']['video_uri'],video,expected_sha256=clip['result']['sha256'])
                result=upload(video,job,clip,cfg,cloud,lease)
            else:result=render(job,clip,cloud,cfg,lease,folder)
            lease.check();lease.call('finish',result=result)
    except Exception as e:
        message=str(e)[:500] if isinstance(e,ValueError) else getattr(e,'category',None) or type(e).__name__+' while processing the clip'
        lease.call('finish',error=message);raise SystemExit(type(e).__name__) from None
    finally:lease.stopped.set();thread.join(timeout=2)

if __name__=='__main__':main()
