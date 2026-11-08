"""Build/deploy the small private YouTube metadata service; no video processing."""

try:
    from managed_secrets import run_gcloud
except ModuleNotFoundError:
    from infra.managed_secrets import run_gcloud
from registry_cleanup import refresh as refresh_registry
import argparse,json,shutil,subprocess,tempfile
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['build','deploy']);parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True);parser.add_argument('--base-image');parser.add_argument('--gcloud',default='gcloud')
    args=parser.parse_args();cfg=json.loads(args.config.read_text());project=cfg['project'];region=cfg['region']
    state=json.loads(args.state.read_text()) if args.state.exists() else {}
    def call(*argv,parse=False):
        r=run_gcloud([args.gcloud,*argv,'--project='+project,'--quiet',*(['--format=json'] if parse else [])],capture_output=True,text=True,timeout=180)
        if r.returncode:raise RuntimeError(r.stderr[-1200:])
        return json.loads(r.stdout) if parse else r.stdout
    if args.phase=='build':
        if state.get('build_id'):raise ValueError('Build already submitted')
        if not args.base_image or '@sha256:' not in args.base_image:raise ValueError('Use a pinned control dependency image')
        source=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'scotus_cloud').mkdir()
            for name in ('action_service.py','youtube.py','google.py','secret_store.py','remote.py'):shutil.copy2(source/'scotus_cloud'/name,root/'scotus_cloud'/name)
            (root/'Dockerfile').write_text('FROM '+args.base_image+'\nCOPY scotus_cloud /app/scotus_cloud\nCMD ["gunicorn","--bind","0.0.0.0:8080","--workers","1","--threads","1","--timeout","60","scotus_cloud.action_service:load_app()"]\n')
            receipt=call('builds','submit',str(root),'--region='+region,'--tag='+region+'-docker.pkg.dev/'+project+'/scotus-videos/actions:latest',
                '--timeout=180s','--async','--service-account=projects/'+project+'/serviceAccounts/scotus-video-builder@'+project+'.iam.gserviceaccount.com',
                '--gcs-source-staging-dir=gs://'+project+'-scotus-control-build/source','--gcs-log-dir=gs://'+project+'-scotus-control-build/logs',parse=True)
            state['build_id']=receipt['id'];args.state.write_text(json.dumps(state));print('Action-service build submitted.');return
    receipt=call('builds','describe',state['build_id'],'--region='+region,parse=True)
    if receipt['status']!='SUCCESS':raise ValueError('Build has not passed')
    image=region+'-docker.pkg.dev/'+project+'/scotus-videos/actions@'+receipt['results']['images'][0]['digest']
    name='scotus-youtube-actions';account='scotus-video-upload@'+project+'.iam.gserviceaccount.com'
    refresh_registry(project, region, args.gcloud, [image], apply=True)
    call('run','deploy',name,'--image='+image,'--region='+region,'--service-account='+account,'--cpu=1','--memory=256Mi',
        '--min-instances=0','--max-instances=1','--concurrency=1','--timeout=60s','--cpu-throttling','--no-allow-unauthenticated',
        '--set-secrets=/secrets/worker/config.json=scotus-video-upload-config:latest')
    refresh_registry(project, region, args.gcloud, apply=True)
    call('run','services','add-iam-policy-binding',name,'--region='+region,'--member=serviceAccount:scotus-video-control@'+project+'.iam.gserviceaccount.com','--role=roles/run.invoker')
    info=call('run','services','describe',name,'--region='+region,parse=True);cfg['youtube_action_service']=info['status']['url']
    args.config.write_text(json.dumps(cfg,indent=2));call('secrets','versions','add','scotus-video-control-config','--data-file='+str(args.config))
    state.update(url=cfg['youtube_action_service'],image=image);args.state.write_text(json.dumps(state));print(json.dumps({'action_service':state['url'],'public_access':False,'minimum_instances':0}))


if __name__=='__main__':main()
