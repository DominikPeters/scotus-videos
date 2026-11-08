"""Enable native full-video links after clip uploads; starts no media uploads."""

try:
    from managed_secrets import run_gcloud
except ModuleNotFoundError:
    from infra.managed_secrets import run_gcloud
from infra.registry_cleanup import refresh as refresh_registry
import argparse,json,re,subprocess
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',required=True);p.add_argument('--region',default='us-central1');p.add_argument('--gcloud',default='gcloud');p.add_argument('--worker-image',required=True);p.add_argument('--controller-image',required=True);a=p.parse_args()
for name,image in [('clips',a.worker_image),('control',a.controller_image)]:
 if not re.fullmatch(re.escape(a.region+'-docker.pkg.dev/'+a.project+'/scotus-videos/'+name)+r'@sha256:[a-f0-9]{64}',image):raise ValueError('Supply pinned project images')
def call(*args,data=None):
 r=run_gcloud([a.gcloud,*args,'--project='+a.project,'--quiet'],input=data,capture_output=True,check=True);return r.stdout
refresh_registry(a.project,a.region,a.gcloud,[a.worker_image,a.controller_image],apply=True)
config=json.loads(call('secrets','versions','access','latest','--secret=scotus-video-upload-config'))
if not {'project','youtube_channel_id','youtube_secret','worker_key'}<=config.keys():raise ValueError('Incomplete worker configuration')
config['youtube_studio_secret']='scotus-video-youtube-studio-session'
call('secrets','versions','add','scotus-video-upload-config','--data-file=-',data=json.dumps(config).encode())
call('run','jobs','update','scotus-video-clips','--region='+a.region,'--image='+a.worker_image)
call('run','services','update','scotus-video-control','--region='+a.region,'--image='+a.controller_image)
refresh_registry(a.project,a.region,a.gcloud,apply=True)
print(json.dumps({'native_linking_enabled':True,'media_upload_started':False}))
