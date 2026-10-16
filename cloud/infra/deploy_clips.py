"""Provision clip jobs and direct private downloads without queuing work."""
import json,subprocess,tempfile,os
from pathlib import Path
import argparse,re
parser=argparse.ArgumentParser(description='Deploy explicit owner-selected vertical clip support; starts no media work.')
parser.add_argument('--project',required=True);parser.add_argument('--region',default='us-central1');parser.add_argument('--gcloud',default='gcloud')
parser.add_argument('--worker-image',required=True);parser.add_argument('--controller-image',required=True)
args=parser.parse_args();p=args.project;region=args.region;g=args.gcloud
for name,value in [('clips',args.worker_image),('control',args.controller_image)]:
 if not re.fullmatch(re.escape(region+'-docker.pkg.dev/'+p+'/scotus-videos/'+name)+r'@sha256:[a-f0-9]{64}',value):raise ValueError('Supply pinned images in this project registry')
def call(*args,parse=False):
 r=subprocess.run([g,*args,'--project='+p,'--quiet',*(['--format=json'] if parse else [])],capture_output=True,text=True,check=True)
 return json.loads(r.stdout) if parse else r.stdout.strip()
clips=args.worker_image;control=args.controller_image
controller=call('run','services','describe','scotus-video-control','--region='+region,parse=True)
uploader=call('run','jobs','describe','scotus-video-upload','--region='+region,parse=True)
signer=controller['spec']['template']['spec']['serviceAccountName'];upload=uploader['spec']['template']['spec']['template']['spec']['serviceAccountName']
call('run','jobs','deploy','scotus-video-clips','--image='+clips,'--region='+region,'--service-account='+upload,'--cpu=4','--memory=4Gi','--task-timeout=900s','--tasks=1','--parallelism=1','--max-retries=0','--set-secrets=/secrets/worker/config.json=scotus-video-upload-config:latest')
call('run','jobs','add-iam-policy-binding','scotus-video-clips','--region='+region,'--member=serviceAccount:'+signer,'--role=roles/run.jobsExecutorWithOverrides')
call('services','enable','iamcredentials.googleapis.com')
call('iam','service-accounts','add-iam-policy-binding',signer,'--member=serviceAccount:'+signer,'--role=roles/iam.serviceAccountTokenCreator')
# Download signatures may read only clip outputs; existing roles stay untouched.
condition="expression=resource.name.startsWith('projects/_/buckets/"+p+"-scotus-video-media/objects/clips/'),title=scotus-clip-downloads"
call('storage','buckets','add-iam-policy-binding','gs://'+p+'-scotus-video-media','--member=serviceAccount:'+signer,'--role=roles/storage.objectViewer','--condition='+condition)
cfg=json.loads(call('secrets','versions','access','latest','--secret=scotus-video-control-config'));cfg.update(clip_job='scotus-video-clips',clip_signer=signer)
with tempfile.NamedTemporaryFile(mode='w',suffix='.json') as f:
 os.chmod(f.name,0o600);json.dump(cfg,f);f.flush();call('secrets','versions','add','scotus-video-control-config','--data-file='+f.name)
call('run','services','update','scotus-video-control','--region='+region,'--image='+control)
print('Clip worker, controller and scoped download signing deployed.')
