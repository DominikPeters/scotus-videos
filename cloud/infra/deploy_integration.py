"""Provision fixed auxiliary jobs/timer. No video execution is started."""

try:
    from managed_secrets import run_gcloud
except ModuleNotFoundError:
    from infra.managed_secrets import run_gcloud
from infra.registry_cleanup import refresh as refresh_registry
import argparse,json,secrets,shlex,subprocess,tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.repair_policy import baseline_files
from scotus_cloud.model import STAGES,digest_json
from deploy_workers import HARDWARE


def main():
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--build-state',type=Path,required=True);cli.add_argument('--config',type=Path,required=True);cli.add_argument('--gcloud',required=True);args=cli.parse_args()
    cfg=json.loads(args.config.read_text());project=cfg['project'];region=cfg['region'];cloudroot=Path(__file__).resolve().parents[1]
    def call(*argv,optional=False,parse=False):
        if argv[:3]==('storage','buckets','add-iam-policy-binding') and not any(c.startswith('--condition=') for c in argv):argv=(*argv,'--condition=None')
        r=run_gcloud([args.gcloud,*argv,'--project='+project,'--quiet',*(['--format=json'] if parse else [])],capture_output=True,text=True,timeout=180)
        if r.returncode:
            if optional:return None
            raise RuntimeError(r.stderr[-1500:])
        return json.loads(r.stdout) if parse else r.stdout
    build=json.loads(args.build_state.read_text());receipt=call('builds','describe',build['build_id'],'--region='+region,parse=True)
    if receipt['status']!='SUCCESS':raise ValueError('Pipeline build has not succeeded')
    image=build['image'].split(':')[0]+'@'+receipt['results']['images'][0]['digest'];bucket=project+'-scotus-video-media'
    refresh_registry(project,region,args.gcloud,[image],apply=True)
    dashboard_path=args.config.parent/'dashboard-settings.json';dashboard=json.loads(dashboard_path.read_text())
    for role in (*STAGES,'dispatcher','recovery','assets'):dashboard['worker_keys'].setdefault(role,secrets.token_hex(32))
    cfg.update(bucket=bucket,control_url=dashboard['control_url'],recovery_key=cfg.get('recovery_key') or secrets.token_hex(32))
    dashboard_path.write_text(json.dumps(dashboard,indent=2));dashboard_path.chmod(0o600)
    args.config.write_text(json.dumps(cfg,indent=2))
    profile={**cfg,'bucket':bucket,'youtube_secret':cfg['secrets']['youtube'],'codex_secret':cfg['secrets']['codex'],
        'chunk_seconds':300,'parallelism':16,'worker_keys':dashboard['worker_keys'],'images':{stage:image for stage in STAGES},
        'title_history_uri':f'gs://{bucket}/inputs/title-history.json','playlists':json.loads((cloudroot.parent/'playlist_ids.json').read_text()) if (cloudroot.parent/'playlist_ids.json').exists() else {}}
    profile_path=args.config.parent/'worker-profile.json';profile_path.write_text(json.dumps(profile));profile_path.chmod(0o600)
    subprocess.run([sys.executable,str(Path(__file__).with_name('deploy_workers.py')),'--profile',str(profile_path),'--apply','--gcloud',args.gcloud],check=True,stdout=subprocess.DEVNULL)
    control_sa='scotus-video-control@'+project+'.iam.gserviceaccount.com'
    reader='scotusExecutionStatusReader'
    if call('iam','roles','describe',reader,optional=True) is None:
        call('iam','roles','create',reader,'--title=Scotus recovery evidence reader','--permissions=run.operations.get,run.jobs.get,run.executions.get,run.executions.list,logging.logEntries.list','--stage=GA')
    else:call('iam','roles','update',reader,'--permissions=run.operations.get,run.jobs.get,run.executions.get,run.executions.list,logging.logEntries.list')
    call('projects','add-iam-policy-binding',project,'--member=serviceAccount:'+control_sa,
         '--role=projects/'+project+'/roles/'+reader,'--condition=None')
    call('storage','buckets','add-iam-policy-binding','gs://'+bucket,'--member=serviceAccount:'+control_sa,'--role=roles/storage.objectViewer')
    call('storage','buckets','add-iam-policy-binding','gs://'+bucket,'--member=serviceAccount:'+control_sa,'--role=roles/storage.objectCreator')
    # Small input snapshots, never auth files or local media.
    call('storage','cp',str(cloudroot/'work/editorial/title-history.json'),f'gs://{bucket}/inputs/title-history.json')
    baseline=args.config.parent/'repair-baseline.json';baseline.write_text(json.dumps(baseline_files(cloudroot)))
    cfg['workflow_baseline_sha256']=digest_json(json.loads(baseline.read_text()))
    call('storage','cp',str(baseline),f"gs://{bucket}/recovery/baselines/{cfg['workflow_baseline_sha256']}.json")
    call('storage','cp',str(baseline),f'gs://{bucket}/recovery/baseline.json')
    cfg['jobs']={stage:'scotus-video-'+stage for stage in STAGES};cfg['workers_enabled']=True
    resources={stage:[int(HARDWARE[stage][0]),float(HARDWARE[stage][1].replace('Gi','')),int(HARDWARE[stage][2].rstrip('s'))] for stage in STAGES}
    cfg['recovery']={'enabled':True,'job':'scotus-video-recovery','test_job':'scotus-video-recovery-test','bucket':bucket,'baseline_uri':f'gs://{bucket}/recovery/baseline.json','stage_resources':resources}
    cfg['asset_job']='scotus-video-assets'
    for kind,cpu,memory,seconds,module,mount in [('recovery',1,'2Gi',1320,'recovery_worker','recovery'),('recovery-test',1,'1Gi',180,'recovery_test_worker',None),('assets',1,'1Gi',300,'asset_publisher','assets')]:
        print('Provisioning '+kind,flush=True)
        job='scotus-video-'+kind;sa=job+'@'+project+'.iam.gserviceaccount.com'
        if call('iam','service-accounts','describe',sa,optional=True) is None:call('iam','service-accounts','create',job)
        call('storage','buckets','add-iam-policy-binding','gs://'+bucket,'--member=serviceAccount:'+sa,'--role=roles/storage.objectViewer')
        prefix='projects/_/buckets/'+bucket+'/objects/'
        folders=['recovery/workspaces/','recovery/sessions/'] if kind=='recovery' else ['recovery/tests/'] if kind=='recovery-test' else []
        condition=[]
        if folders:condition=['--condition=title='+kind+'-writes,expression='+(' || '.join("resource.name.startsWith('"+prefix+folder+"')" for folder in folders))]
        call('storage','buckets','add-iam-policy-binding','gs://'+bucket,'--member=serviceAccount:'+sa,'--role=roles/storage.objectCreator',*condition)
        flags=[]
        if mount:
            value={'project':project,'region':region,'bucket':bucket,'dashboard_url':cfg['dashboard_url'],'control_url':cfg['control_url'],
                'dashboard_key':dashboard['worker_keys'][kind],'worker_key':dashboard['worker_keys'][kind],
                'codex_secret':cfg['secrets']['codex'],'github_secret':cfg['secrets']['github'],'recovery_key':cfg['recovery_key']}
            private=args.config.parent/(kind+'-config.json');private.write_text(json.dumps(value));private.chmod(0o600)
            secret=job+'-config'
            if call('secrets','describe',secret,optional=True) is None:call('secrets','create',secret,'--replication-policy=automatic')
            call('secrets','versions','add',secret,'--data-file='+str(private))
            call('secrets','add-iam-policy-binding',secret,'--member=serviceAccount:'+sa,'--role=roles/secretmanager.secretAccessor')
            flags=['--set-secrets=/secrets/'+mount+'/config.json='+secret+':latest']
            account_secret=cfg['secrets']['codex' if kind=='recovery' else 'github']
            call('secrets','add-iam-policy-binding',account_secret,'--member=serviceAccount:'+sa,'--role=roles/secretmanager.secretAccessor')
            if kind=='recovery':call('secrets','add-iam-policy-binding',account_secret,'--member=serviceAccount:'+sa,'--role=roles/secretmanager.secretVersionAdder')
        call('run','jobs','deploy',job,'--region='+region,'--image='+image,'--service-account='+sa,'--cpu='+str(cpu),'--memory='+memory,'--task-timeout='+str(seconds)+'s','--tasks=1','--parallelism=1','--max-retries=0','--command=python','--args=-m,scotus_cloud.'+module,*flags)
        call('run','jobs','add-iam-policy-binding',job,'--region='+region,'--member=serviceAccount:'+control_sa,'--role=roles/run.jobsExecutorWithOverrides')
    cfg['photo_job']='scotus-video-photos'
    call('run','jobs','deploy',cfg['photo_job'],'--region='+region,'--image='+image,
         '--service-account=scotus-video-enrich@'+project+'.iam.gserviceaccount.com',
         '--cpu=1','--memory=2Gi','--tasks=1','--parallelism=1','--task-timeout=900s','--max-retries=0',
         '--command=python','--args=-m,scotus_cloud.photo_worker',
         '--set-secrets=/secrets/worker/config.json=scotus-video-enrich-config:latest')
    call('run','jobs','add-iam-policy-binding',cfg['photo_job'],'--region='+region,
         '--member=serviceAccount:'+control_sa,'--role=roles/run.jobsExecutorWithOverrides')
    cfg['scheduler_account']='scotus-video-timer@'+project+'.iam.gserviceaccount.com'
    if call('iam','service-accounts','describe',cfg['scheduler_account'],optional=True) is None:call('iam','service-accounts','create','scotus-video-timer')
    # Discovery is configured for backfill but remains behind the dashboard pause.
    cfg['discovery']={'enabled':True,'interval_seconds':1800}
    args.config.write_text(json.dumps(cfg,indent=2));dashboard_path.write_text(json.dumps(dashboard,indent=2));dashboard_path.chmod(0o600)
    patch={'worker_keys':dashboard['worker_keys']}
    remote="""$p='/www/htdocs/w008ef9a/.scotus-youtube-private/config.php';$c=require $p;$patch=json_decode(stream_get_contents(STDIN),true);$c['worker_keys']=array_replace($c['worker_keys'],$patch['worker_keys']);$t=tempnam(dirname($p),'.config-');file_put_contents($t,'<?php return '.var_export($c,true).';');chmod($t,0600);rename($t,$p);echo 'Worker roles updated; passkeys and state preserved.';"""
    r=subprocess.run(['ssh','kas','php -r '+shlex.quote(remote)],input=json.dumps(patch),text=True,capture_output=True,timeout=60)
    if r.returncode:raise RuntimeError('Dashboard role update failed')
    call('secrets','versions','add','scotus-video-control-config','--data-file='+str(args.config))
    # Five-minute tick is a small authenticated service request, not a billed job.
    call('services','enable','cloudscheduler.googleapis.com')
    name='scotus-video-tick';exists=call('scheduler','jobs','describe',name,'--location='+region,optional=True)
    call('scheduler','jobs','update' if exists is not None else 'create','http',name,'--location='+region,'--schedule=*/10 * * * *','--time-zone=UTC','--uri='+cfg['control_url']+'/v1/tick','--http-method=POST','--message-body={}','--oidc-service-account-email='+cfg['scheduler_account'],'--oidc-token-audience='+cfg['control_url'],'--attempt-deadline=60s')
    refresh_registry(project,region,args.gcloud,apply=True)
    print(json.dumps({'jobs':[*cfg['jobs'].values(),cfg['asset_job'],cfg['photo_job'],cfg['recovery']['job'],cfg['recovery']['test_job']],'scheduler':name,'workers_configured':True,'executions_started':0,'dashboard_remains_paused':True}))

if __name__=='__main__':main()
