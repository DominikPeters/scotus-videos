"""Deploy owner-triggered Instagram clip publication; never starts a publication."""

try:
    from managed_secrets import run_gcloud
except ModuleNotFoundError:
    from infra.managed_secrets import run_gcloud
from infra.registry_cleanup import refresh as refresh_registry
import argparse,json,re,subprocess

def controller_configuration(raw):
    config=json.loads(raw)
    if not {'project','dashboard_url','dispatcher_key','control_key','clip_job'}<=config.keys():
        raise ValueError('Incomplete controller configuration; refusing to replace it')
    return config | {'instagram_clip_job':'scotus-video-instagram-clips'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True);p.add_argument('--region',default='us-central1');p.add_argument('--gcloud',default='gcloud');p.add_argument('--worker-image',required=True);p.add_argument('--controller-image',required=True)
    a=p.parse_args();project=a.project;region=a.region
    for name,image in [('clips',a.worker_image),('control',a.controller_image)]:
     if not re.fullmatch(re.escape(region+'-docker.pkg.dev/'+project+'/scotus-videos/'+name)+r'@sha256:[a-f0-9]{64}',image):raise ValueError('Supply pinned project images')
    def call(*args,data=None,parse=False):
     r=run_gcloud([a.gcloud,*args,'--project='+project,'--quiet',*(['--format=json'] if parse else [])],input=data,capture_output=True,check=True)
     return json.loads(r.stdout) if parse else None
    refresh_registry(project,region,a.gcloud,[a.worker_image,a.controller_image],apply=True)
    account='scotus-video-upload@'+project+'.iam.gserviceaccount.com';job='scotus-video-instagram-clips'
    # Existing controller identity already signs URLs and reads/writes clip artifacts.
    # New credential grants are limited to Instagram and the worker callback config.
    for secret in ['scotus-video-instagram','scotus-video-upload-config']:
     call('secrets','add-iam-policy-binding',secret,'--member=serviceAccount:'+account,'--role=roles/secretmanager.secretAccessor')
    call('iam','service-accounts','add-iam-policy-binding',account,'--member=serviceAccount:'+account,'--role=roles/iam.serviceAccountTokenCreator')
    call('run','jobs','deploy',job,'--image='+a.worker_image,'--region='+region,'--service-account='+account,
     '--cpu=2','--memory=2Gi','--task-timeout=900s','--tasks=1','--parallelism=1','--max-retries=0',
     '--set-secrets=/secrets/worker/config.json=scotus-video-upload-config:latest')
    call('run','jobs','add-iam-policy-binding',job,'--region='+region,'--member=serviceAccount:'+account,'--role=roles/run.jobsExecutorWithOverrides')
    raw=run_gcloud([a.gcloud,'secrets','versions','access','latest','--secret=scotus-video-control-config','--project='+project],capture_output=True,check=True).stdout
    config=controller_configuration(raw)
    call('secrets','versions','add','scotus-video-control-config','--data-file=-',data=json.dumps(config).encode())
    call('run','jobs','update','scotus-video-clips','--region='+region,'--image='+a.worker_image)
    call('run','services','update','scotus-video-control','--region='+region,'--image='+a.controller_image)
    refresh_registry(project,region,a.gcloud,apply=True)
    print(json.dumps({'job':job,'deployed':True,'publication_started':False}))


if __name__=='__main__':main()
