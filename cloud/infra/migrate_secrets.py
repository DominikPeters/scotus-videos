"""Plan/stage the three-bundle migration using already built, pinned images.

Default is metadata-only planning. --apply requires a quiesced, private controller
and paused dashboard, no active executions, and a complete old->new image map.
It never submits builds or starts media processing. Legacy retirement is a
separate explicit step after the deployed credential probes have succeeded.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from managed_secrets import cli_cloud, grant_writer, grant_reader, runtime_flags
except ModuleNotFoundError:
    from infra.managed_secrets import cli_cloud, grant_writer, grant_reader, runtime_flags
from infra.registry_cleanup import refresh as refresh_registry, execution_active
from scotus_cloud.secret_store import GROUPS, SecretStore, canonical, encode_bundle, group_for


def pod(value):
    if isinstance(value, dict):
        if 'containers' in value: return value
        for child in value.values():
            result = pod(child)
            if result is not None: return result
    elif isinstance(value, list):
        for child in value:
            result = pod(child)
            if result is not None: return result
    return None


def resource_plan(services, jobs):
    resources = []
    for kind, rows in (('service', services), ('job', jobs)):
        for item in rows:
            spec = pod(item['spec'])
            if not spec or len(spec['containers']) != 1: raise ValueError('Review nonstandard container layout')
            mounts = [v['secret'] for v in spec.get('volumes', []) if 'secret' in v]
            # Older deploys can leave duplicate volume definitions for one config.
            mounts=list({json.dumps(m,sort_keys=True):m for m in mounts}.values())
            if len(mounts) > 1: raise ValueError('Review multiple distinct secret mounts')
            if any(v.get('valueFrom') for v in spec['containers'][0].get('env', [])):
                raise ValueError('Review secret environment references before migration')
            environment = {v['name']:v.get('value') for v in spec['containers'][0].get('env', [])}
            entry = environment.get('SCOTUS_RUNTIME_CONFIG') or (mounts[0]['secretName'] if mounts else ({'scotus-statistics':'scotus-statistics-config','scotus-video-tiktok-pilot':'scotus-video-upload-config'}.get(item['metadata']['name'])))
            if entry and group_for(entry) != GROUPS[0]: raise ValueError('Review direct account credential mount')
            if mounts and any(v['key'] != 'latest' for v in mounts[0].get('items', [])):
                raise ValueError('Review pinned configuration version')
            account = spec['serviceAccountName']
            if item['metadata']['name'] == 'scotus-video-instagram-clips':
                account = account.replace('scotus-video-control@', 'scotus-video-upload@')
            resources.append({'kind':kind, 'name':item['metadata']['name'],
                              'region':item['metadata']['labels']['cloud.googleapis.com/location'],
                              'account':account, 'config_entry':entry, 'image':spec['containers'][0]['image'],
                              'bundle_mode':environment.get('SCOTUS_SECRET_BUNDLES') == '1',
                              'legacy_volume_names':[v['name'] for v in spec.get('volumes',[]) if v.get('name') and 'secret' in v and v['secret']['secretName'] not in GROUPS],
                              'legacy_mounts':[v['secretName'] for v in mounts if v['secretName'] not in GROUPS]})
    return resources


def reader_map(resources):
    result = {}
    for item in resources:
        if item['config_entry'] and item['config_entry'] != 'scotus-video-control-config':
            result.setdefault(item['account'], set()).add(item['config_entry'])
    return {k:sorted(v) for k,v in result.items()}


def validate_images(resources, images):
    for item in resources:
        image = images.get(item['image'], '')
        prefix = item['image'].split('/scotus-videos/')[0]+'/scotus-videos/'
        if not re.fullmatch(re.escape(prefix)+r'[a-z0-9-]+@sha256:[a-f0-9]{64}', image):
            raise ValueError('Supply an already built, project-pinned image for every source image')
        if image == item['image']: raise ValueError('Migration needs images containing the new secret runtime')


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--project', required=True)
    cli.add_argument('--gcloud', default='gcloud')
    cli.add_argument('--image-map', type=Path)
    cli.add_argument('--state', type=Path)
    cli.add_argument('--workflow-baseline', type=Path, help='Exact source baseline from the pipeline build context')
    cli.add_argument('--apply', action='store_true')
    cli.add_argument('--resume', action='store_true', help='Resume a recorded, quiesced migration without overwriting existing bundles')
    cli.add_argument('--quiesced', action='store_true', help='Controller invocation has been disabled and existing requests drained')
    cli.add_argument('--retire-legacy', action='store_true')
    cli.add_argument('--verified', action='store_true', help='All deployed startup/credential/negative-access probes passed')
    args = cli.parse_args();project=args.project
    def call(*parts, optional=False):
        r=subprocess.run([args.gcloud,*parts,'--project='+project,'--quiet','--format=json'],capture_output=True,text=True,timeout=180)
        if r.returncode:
            if optional and 'NOT_FOUND' in r.stderr:return None
            raise RuntimeError('Migration command failed: '+' '.join(parts[:3]))
        if 'unreachable' in r.stderr.lower():raise RuntimeError('Resource inventory is incomplete')
        return json.loads(r.stdout or 'null')
    if call('config','list').get('run',{}).get('region'):raise ValueError('Unset run/region before global inventory')
    services=call('run','services','list');jobs=call('run','jobs','list')
    resources=resource_plan(services,jobs)
    legacy=[s for s in call('secrets','list') if s['name'].rsplit('/',1)[-1].startswith('scotus-') and s['name'].rsplit('/',1)[-1] not in GROUPS]
    names=[s['name'].rsplit('/',1)[-1] for s in legacy]
    for name in names:group_for(name)
    controller=next(s for s in services if s['metadata']['name']=='scotus-video-control')
    region=controller['metadata']['labels']['cloud.googleapis.com/location'];url=controller['status']['url']
    if args.retire_legacy:
        if not (args.apply and args.verified and args.state):raise ValueError('Retirement requires --apply --verified and a completed migration --state')
        saved=json.loads(args.state.read_text())
        if saved.get('project') != project or not saved.get('deployed'):raise ValueError('Migration deployment is not complete')
        expected={(r['kind'],r['name'],r['account'],r['config_entry']) for r in saved['resources']}
        if expected != {(r['kind'],r['name'],r['account'],r['config_entry']) for r in resources}:raise ValueError('Resource scope changed before retirement')
        store=SecretStore(cli_cloud(project,args.gcloud))
        for group in GROUPS:
            _,current_version=store.raw(group)
            active=[v for v in call('secrets','versions','list',group) if v['state'] != 'DESTROYED']
            if len(active) != 1 or active[0]['name'] != current_version:raise ValueError('Credential group replacement needs reconciliation')
        for item in resources:
            if item['image'] not in saved['replacement_images']:raise ValueError('A resource still uses a pre-migration image')
            if item['config_entry'] and (not item['bundle_mode'] or item['legacy_mounts']):raise ValueError('Legacy runtime configuration is still in use')
        for loc in sorted({i['region'] for i in resources}):
            if any(execution_active(e) for e in call('run','jobs','executions','list','--region='+loc)):
                raise ValueError('Wait for active executions before legacy retirement')
        for svc in services:
            ready=svc.get('status',{}).get('latestReadyRevisionName')
            if any((t.get('percent',0) or t.get('tag')) and t.get('revisionName') != ready for t in svc.get('status',{}).get('traffic',[])):
                raise ValueError('An old service revision still receives traffic')
        current={s['name'] for s in legacy}
        if not current.issubset(set(saved['legacy_secrets'])):raise ValueError('Legacy secret inventory changed; review new scope')
        # The operator confirms the exact remaining legacy-secret scope separately.
        for secret in legacy:call('secrets','delete',secret['name'].rsplit('/',1)[-1],'--etag='+secret['etag'])
        print(json.dumps({'legacy_secrets_deleted':len(legacy),'current_groups':list(GROUPS)}));return
    print(json.dumps({'resources':resources,'groups':{group:[n for n in names if group_for(n)==group] for group in GROUPS},
                      'unique_images_to_refresh':sorted({i['image'] for i in resources}), 'applied':args.apply},indent=2),flush=True)
    if not args.apply:return
    if not args.state or not args.quiesced:raise ValueError('Supply --state and --quiesced before migration')
    saved=None
    if args.resume:
        saved=json.loads(args.state.read_text())
        if saved['project'] != project:raise ValueError('Migration state belongs to another project')
        visible={(r['kind'],r['name']):r for r in resources}
        original=saved['resources'];images=saved['images']
        if set(visible) != {(r['kind'],r['name']) for r in original}:raise ValueError('Resource scope changed during migration')
        for r in original:
            if visible[(r['kind'],r['name'])]['image'] not in (r['image'],images[r['image']]):raise ValueError('Resource image changed outside migration')
            r['legacy_volume_names']=visible[(r['kind'],r['name'])]['legacy_volume_names']
        resources=original
    else:
        if args.state.exists():raise ValueError('Migration state already exists; use --resume after reconciliation')
        if not args.image_map:raise ValueError('Supply --image-map before migration')
        images=json.loads(args.image_map.read_text())
    validate_images(resources,images)
    if not args.workflow_baseline:raise ValueError('Supply the exact new pipeline --workflow-baseline')
    from scotus_cloud.model import digest_json
    baseline_bytes=args.workflow_baseline.read_bytes()
    if len(baseline_bytes)>2097152:raise ValueError('Workflow baseline exceeds runtime read limit')
    baseline=json.loads(baseline_bytes);baseline_hash=digest_json(baseline)
    if saved and saved.get('workflow_baseline_sha256') != baseline_hash:raise ValueError('Workflow baseline changed during migration')
    if any(t.get('tag') for svc in services for t in svc.get('status',{}).get('traffic',[])):
        raise ValueError('Review tagged service revisions before migration')
    policy=call('run','services','get-iam-policy','scotus-video-control','--region='+region)
    if any('allUsers' in b.get('members',[]) or 'allAuthenticatedUsers' in b.get('members',[]) for b in policy.get('bindings',[])):
        raise ValueError('Temporarily remove public controller invocation and drain requests before migration')
    for loc in sorted({i['region'] for i in resources}):
        if any(execution_active(e) for e in call('run','jobs','executions','list','--region='+loc)):
            raise ValueError('Wait for active executions before migration')
    cloud=cli_cloud(project,args.gcloud)
    bundles={group:{'schema_version':1,'entries':{}} for group in GROUPS}
    policies={}
    for secret in legacy:
        name=secret['name'].rsplit('/',1)[-1]
        versions=call('secrets','versions','list',name)
        live=[v for v in versions if v['state']=='ENABLED']
        if not live:
            if name != 'scotus-video-instagram-pending':raise ValueError('Review inactive logical secret: '+name)
            continue
        if len(live)!=1:raise ValueError('Review unexpected legacy version history: '+name)
        number=live[0]['name'].rsplit('/',1)[1]
        raw=cloud.request('GET','https://secretmanager.googleapis.com/v1/'+live[0]['name']+':access')
        value=base64.b64decode(raw['payload']['data'])
        if group_for(name)==GROUPS[0]:
            configuration=json.loads(value);configuration.setdefault('project',project)
            if configuration['project'] != project:raise ValueError('Runtime configuration belongs to another project')
            value=json.dumps(configuration).encode()
        if name=='scotus-video-control-config':
            config=json.loads(value)
            from scotus_cloud.remote import Dashboard
            if not Dashboard(config['dashboard_url'],config['dispatcher_key'],'dispatcher').call('snapshot')['paused']:
                raise ValueError('Pause dashboard processing before migration')
            config['runtime_readers']=reader_map(resources)
            config['workflow_baseline_sha256']=baseline_hash
            value=json.dumps(config).encode()
        bundles[group_for(name)]['entries'][name]={'data':base64.b64encode(canonical(value)).decode(),'updated_at':live[0]['createTime']}
        policies[name]=call('secrets','get-iam-policy',name)
    for bundle in bundles.values():encode_bundle(bundle)
    # Do not overwrite a partially migrated layout with a stale legacy snapshot.
    for group in GROUPS:
        if not args.resume and call('secrets','describe',group,optional=True) is not None:raise ValueError('Credential group already exists; reconcile migration state')
    state=saved or {'project':project,'legacy_secrets':[s['name'] for s in legacy], 'resources':resources,'images':images,
                     'replacement_images':sorted(set(images.values())), 'workflow_baseline_sha256':baseline_hash, 'deployed':False}
    args.state.parent.mkdir(parents=True,exist_ok=True)
    def save():
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w',dir=args.state.parent,prefix='.secret-migration-',delete=False) as f:
            json.dump(state,f,indent=2);temporary=f.name
        os.replace(temporary,args.state)
    refresh_registry(project,region,args.gcloud,sorted(set(images.values())),apply=True)
    save()
    for group,bundle in bundles.items():
        existing=call('secrets','describe',group,optional=True)
        store=SecretStore(cloud)
        raw=encode_bundle(bundle)
        if existing is not None:
            if not args.resume:raise ValueError('Unexpected existing credential group')
            number, _ = store.pointer(group)
            if number is not None:
                store.bundle(group)  # Validate the authoritative current value; never overwrite it.
                continue
            staged=[v for v in call('secrets','versions','list',group) if v['state']=='ENABLED']
            if len(staged)>1:raise ValueError('Reconcile unactivated credential versions')
            if staged:
                created=staged[0]
                if store.raw(group,created['name'].rsplit('/',1)[1])[0]!=raw:raise ValueError('Unactivated credential payload differs')
            else:created=None
        else:
            call('secrets','create',group,'--replication-policy=automatic','--labels=scotus-layout=tripartition-v1')
            created=None
        if created is None:
            created=cloud.request('POST',f'https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{group}:addVersion',json={'payload':{'data':base64.b64encode(raw).decode()}})
        if store.raw(group,created['name'].rsplit('/',1)[1])[0]!=raw:raise RuntimeError('Bundle migration failed read-back')
        store.activate(group,created['name'])
    from urllib.parse import quote
    bucket=project+'-scotus-video-media'
    for key in (f'recovery/baselines/{baseline_hash}.json','recovery/baseline.json'):
        uri='gs://'+bucket+'/'+key
        endpoint=f'https://storage.googleapis.com/storage/v1/b/{bucket}/o/'+quote(key,safe='')
        metadata=cloud.session.get(endpoint,params={'fields':'generation'},timeout=30)
        if metadata.status_code not in (200,404):raise RuntimeError('Workflow baseline metadata unavailable')
        if metadata.status_code==200:
            existing=cloud.storage_json(uri,max_bytes=2097152)
            if digest_json(existing)==baseline_hash:continue
            if key!='recovery/baseline.json':raise RuntimeError('Immutable workflow baseline differs')
        generation=metadata.json()['generation'] if metadata.status_code==200 else '0'
        uploaded=cloud.session.post(f'https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o',
            params={'uploadType':'media','name':key,'ifGenerationMatch':generation},
            data=baseline_bytes,headers={'Content-Type':'application/json'},timeout=60)
        if uploaded.status_code not in (200,201):raise RuntimeError('Workflow baseline activation failed')
        if digest_json(cloud.storage_json(uri,max_bytes=2097152)) != baseline_hash:raise RuntimeError('Workflow baseline read-back failed')
    writer_role='scotusCredentialBundleWriter'
    permissions='secretmanager.secrets.get,secretmanager.versions.access,secretmanager.versions.get,secretmanager.versions.list,secretmanager.versions.add,secretmanager.versions.destroy'
    exists=call('iam','roles','describe',writer_role,optional=True)
    call('iam','roles','update' if exists else 'create',writer_role,'--title=SCOTUS verified credential replacement','--permissions='+permissions,'--stage=GA')
    coordinator='serviceAccount:scotus-video-control@'+project+'.iam.gserviceaccount.com'
    reads={coordinator:set(GROUPS)};writes={coordinator:set(GROUPS)}
    for group in GROUPS:grant_writer(project,group,coordinator,args.gcloud)
    for name,policy in policies.items():
        group=group_for(name)
        if group==GROUPS[0]:continue
        for binding in policy.get('bindings',[]):
            for member in binding.get('members',[]):
                if not member.startswith('serviceAccount:scotus-'):continue
                role=binding['role']
                if role in ('roles/secretmanager.secretVersionAdder','roles/secretmanager.secretVersionManager', 'projects/'+project+'/roles/scotusSpotifyCredentialRenewal'):
                    grant_writer(project,group,member,args.gcloud)
                    reads.setdefault(member,set()).add(group);writes.setdefault(member,set()).add(group)
                elif role=='roles/secretmanager.secretAccessor':
                    reads.setdefault(member,set()).add(group)
                    grant_reader(project,group,member,args.gcloud)
    for account in reader_map(resources):
        call('run','services','add-iam-policy-binding','scotus-video-control','--region='+region,
             '--member=serviceAccount:'+account,'--role=roles/run.invoker')
    upload='scotus-video-upload@'+project+'.iam.gserviceaccount.com'
    call('iam','service-accounts','add-iam-policy-binding',upload,'--member=serviceAccount:'+upload,'--role=roles/iam.serviceAccountTokenCreator')
    # Bring the broker up before workers switch to identity-authenticated config fetches.
    resources.sort(key=lambda r:r['name']!='scotus-video-control')
    for item in resources:
        flags=['--region='+item['region'],'--image='+images[item['image']],'--service-account='+item['account']]
        if item['name'] in ('scotus-video-tiktok','scotus-video-tiktok-pilot'):
            module='tiktok_pilot' if item['name'].endswith('-pilot') else 'clip_worker'
            flags.extend(['--command=python','--args=-m,scotus_cloud.'+module])
        entry=item['config_entry']
        if entry:
            member='serviceAccount:'+item['account']
            # A custom delimiter keeps comma-separated group lists in one env value.
            flags.append('--update-env-vars=^|^'+runtime_flags(entry,url,project).replace(',', '|')
                         +'|SCOTUS_CREDENTIAL_GROUPS='+','.join(sorted(reads.get(member,set())))
                         +'|SCOTUS_CREDENTIAL_WRITE_GROUPS='+','.join(sorted(writes.get(member,set()))))
            flags.append('--clear-secrets')
            if item.get('legacy_volume_names'):flags.append('--remove-volume='+','.join(item['legacy_volume_names']))
        command=['run','jobs','update'] if item['kind']=='job' else ['run','services','update']
        call(*command,item['name'],*flags)
        if item['kind']=='service':call('run','services','update-traffic',item['name'],'--region='+item['region'],'--to-latest')
        state.setdefault('updated_resources',[]).append(item['name']);save()
    refresh_registry(project,region,args.gcloud,apply=True)
    state['deployed']=True;save()
    print(json.dumps({'deployed':True,'public_controller_invocation':'restore only after credential probes','legacy_retirement':'pending explicit verification'}))


if __name__=='__main__':main()
