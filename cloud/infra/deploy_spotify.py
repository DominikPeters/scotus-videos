"""Deploy manual Spotify delivery without launching transfers or enabling automation."""

try:
    from managed_secrets import run_gcloud
except ModuleNotFoundError:
    from infra.managed_secrets import run_gcloud
import argparse,json,secrets,shlex,shutil,subprocess,tempfile
from pathlib import Path
from registry_cleanup import refresh as refresh_registry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['setup','build','deploy']);parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True);parser.add_argument('--credentials',type=Path)
    parser.add_argument('--base-image');parser.add_argument('--gcloud',default='gcloud');args=parser.parse_args()
    cfg=json.loads(args.config.read_text());project=cfg['project'];region=cfg['region']
    state=json.loads(args.state.read_text()) if args.state.exists() else {}
    name='scotus-spotify-delivery';job='scotus-spotify-transfer';secret='scotus-spotify-auth';config_secret='scotus-spotify-config'
    account=name+'@'+project+'.iam.gserviceaccount.com';controller='scotus-video-control@'+project+'.iam.gserviceaccount.com'
    def save():args.state.write_text(json.dumps(state,indent=2));args.state.chmod(0o600)
    def call(*argv,parse=False,optional=False):
        r=run_gcloud([args.gcloud,*argv,'--project='+project,'--quiet',*(['--format=json'] if parse else [])],capture_output=True,text=True,timeout=180)
        if r.returncode:
            if optional:return None
            raise RuntimeError(r.stderr[-1200:])
        return json.loads(r.stdout) if parse else r.stdout
    def add_secret(name,path):
        if call('secrets','describe',name,optional=True) is None:call('secrets','create',name,'--replication-policy=automatic')
        call('secrets','versions','add',name,'--data-file='+str(path.resolve()))
    if args.phase=='setup':
        if call('iam','service-accounts','describe',account,optional=True) is None:call('iam','service-accounts','create',name)
        if not args.credentials:raise ValueError('Private Spotify credentials required')
        credentials=json.loads(args.credentials.read_text())
        if credentials.get('refresh_token'):credentials.pop('sp_dc',None);credentials.pop('sp_key',None)
        args.credentials.write_text(json.dumps(credentials));args.credentials.chmod(0o600);add_secret(secret,args.credentials)
        state.setdefault('worker_key',secrets.token_hex(32));save()
        runtime={'project':project,'region':region,'dashboard_url':cfg['dashboard_url'],'worker_key':state['worker_key'],
                 'spotify_secret':secret,'show_id':'3fxexipVTGI255vbjckmgJ','transfer_job':job}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_text(json.dumps(runtime));path.chmod(0o600);add_secret(config_secret,path)
        for resource in (secret,config_secret):call('secrets','add-iam-policy-binding',resource,'--member=serviceAccount:'+account,'--role=roles/secretmanager.secretAccessor')
        for role in ('roles/secretmanager.viewer','roles/secretmanager.secretVersionAdder'):
            call('secrets','add-iam-policy-binding',secret,'--member=serviceAccount:'+controller,'--role='+role)
        role='scotusSpotifyCredentialRenewal'
        permissions='secretmanager.versions.add,secretmanager.versions.list,secretmanager.versions.disable'
        if call('iam','roles','describe',role,optional=True) is None:
            call('iam','roles','create',role,'--title=Spotify credential renewal','--permissions='+permissions,'--stage=GA')
        call('secrets','add-iam-policy-binding',secret,'--member=serviceAccount:'+account,'--role=projects/'+project+'/roles/'+role)
        call('storage','buckets','add-iam-policy-binding','gs://'+cfg['bucket'],'--member=serviceAccount:'+account,'--role=roles/storage.objectViewer','--condition=expression=resource.name.startsWith("projects/_/buckets/'+cfg['bucket']+'/objects/scratch/"),title=spotify-recordings')
        print('Spotify private resources ready; no transfers started.');return
    image=region+'-docker.pkg.dev/'+project+'/scotus-videos/spotify'
    if args.phase=='build':
        if state.get('build_id'):raise ValueError('Build already submitted')
        if not args.base_image or '@sha256:' not in args.base_image:raise ValueError('Pinned small control base required')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'scotus_cloud').mkdir();source=Path(__file__).resolve().parents[1]/'scotus_cloud'
            for file in ('spotify.py','spotify_service.py','spotify_worker.py','google.py','secret_store.py','remote.py'):shutil.copy2(source/file,root/'scotus_cloud'/file)
            (root/'Dockerfile').write_text('FROM '+args.base_image+'\nRUN pip install --no-cache-dir PyYAML==6.0.3\nCOPY scotus_cloud /app/scotus_cloud\nCMD ["gunicorn","--bind","0.0.0.0:8080","--workers","1","--threads","1","--timeout","60","scotus_cloud.spotify_service:load_app()"]\n')
            size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
            if size>64*1024:raise ValueError('Spotify source exceeds small-transfer cap')
            receipt=call('builds','submit',str(root),'--region='+region,'--tag='+image+':latest','--timeout=180s','--async',
                         '--service-account=projects/'+project+'/serviceAccounts/scotus-video-builder@'+project+'.iam.gserviceaccount.com',
                         '--gcs-source-staging-dir=gs://'+project+'-scotus-control-build/source','--gcs-log-dir=gs://'+project+'-scotus-control-build/logs',parse=True)
            state.update(build_id=receipt['id'],source_bytes=size);save();print(json.dumps({'build_id':receipt['id'],'source_bytes':size}));return
    receipt=call('builds','describe',state['build_id'],'--region='+region,parse=True)
    if receipt['status']!='SUCCESS':raise ValueError('Build not successful')
    image+='@'+receipt['results']['images'][0]['digest'];refresh_registry(project,region,args.gcloud,[image],apply=True)
    common=['--image='+image,'--region='+region,'--service-account='+account,'--cpu=1','--memory=512Mi','--set-secrets=/secrets/spotify/config.json='+config_secret+':latest']
    call('run','jobs','deploy',job,*common,'--tasks=1','--parallelism=1','--max-retries=0','--task-timeout=900s','--command=python','--args=-m,scotus_cloud.spotify_worker')
    call('run','jobs','add-iam-policy-binding',job,'--region='+region,'--member=serviceAccount:'+account,'--role=roles/run.jobsExecutorWithOverrides')
    call('run','deploy',name,*common,'--min-instances=0','--max-instances=1','--concurrency=1','--timeout=60s','--cpu-throttling','--no-allow-unauthenticated')
    call('run','services','add-iam-policy-binding',name,'--region='+region,'--member=serviceAccount:'+controller,'--role=roles/run.invoker')
    info=call('run','services','describe',name,'--region='+region,parse=True)
    cfg['spotify']={'enabled':True,'automatic':False,'service':info['status']['url'],'show_id':'3fxexipVTGI255vbjckmgJ'}
    cfg['secrets']['spotify']=secret;args.config.write_text(json.dumps(cfg,indent=2));args.config.chmod(0o600)
    call('secrets','versions','add','scotus-video-control-config','--data-file='+str(args.config.resolve()))
    # Patch only these configuration fields; preserve passkeys and all existing secrets.
    script="""$p='/www/htdocs/w008ef9a/.scotus-youtube-private/config.php';$c=require $p;$input=json_decode(stream_get_contents(STDIN),true,512,JSON_THROW_ON_ERROR);$c['worker_keys']['spotify']=$input['key'];$c['spotify_enabled']=true;$c['spotify_auto_transfer']=false;$t=tempnam(dirname($p),'.config-');file_put_contents($t,'<?php return '.var_export($c,true).';');chmod($t,0640);rename($t,$p);echo 'Manual Spotify access configured.';"""
    r=subprocess.run(['ssh','kas','php -r '+shlex.quote(script)],input=json.dumps({'key':state['worker_key']}).encode(),capture_output=True,timeout=60)
    if r.returncode:raise RuntimeError('Private dashboard configuration failed')
    refresh_registry(project,region,args.gcloud,apply=True)
    state.update(url=info['status']['url'],image=image);save();print(json.dumps({'manual_enabled':True,'automatic':False,'transfers_started':0}))


if __name__=='__main__':main()
