"""Deployment CLI adapter for the three-bundle layout; legacy until migrated.

Preserves gcloud subprocess return types. Secret payloads never enter command
arguments, logs, images, or environment variables. Commands unrelated to secret
configuration go directly to gcloud.
"""
from functools import lru_cache
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.secret_store import GROUPS, SecretStore, group_for


def cli_cloud(project, gcloud='gcloud'):
    import requests
    from scotus_cloud.google import Google
    token = subprocess.run([gcloud, 'auth', 'print-access-token'], capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    cloud = Google.__new__(Google)
    cloud.project = project
    cloud.session = requests.Session()
    cloud.session.headers['Authorization'] = 'Bearer '+token
    return cloud


def flag(parts, key, default=None):
    for index, part in enumerate(parts):
        if part.startswith(key+'='): return part.split('=', 1)[1]
        if part == key and index+1 < len(parts): return parts[index+1]
    return default


@lru_cache(maxsize=8)
def enabled(project, gcloud):
    forced = os.environ.get('SCOTUS_SECRET_BUNDLES')
    if forced == '1': return True
    if forced not in (None, '0'): raise ValueError('Unknown credential layout flag')
    r = subprocess.run([gcloud, 'secrets', 'describe', GROUPS[0], '--project='+project, '--format=json'],
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        if 'NOT_FOUND' in r.stderr: return False
        raise RuntimeError('Cannot determine deployed credential layout')
    return json.loads(r.stdout).get('labels', {}).get('scotus-layout') == 'tripartition-v1'


def grant_writer(project, group, member, gcloud='gcloud'):
    bucket = project+'-scotus-video-media'
    commands = [
        ['secrets','add-iam-policy-binding',group,'--member='+member,'--role='+role,'--condition=None']
        for role in ('roles/secretmanager.secretAccessor', 'projects/'+project+'/roles/scotusCredentialBundleWriter')]
    condition = "expression=resource.name == 'projects/_/buckets/"+bucket+"/objects/secret-bundles/locks/"+group+"' || resource.name == 'projects/_/buckets/"+bucket+"/objects/secret-bundles/current/"+group+"',title=secret-bundle-state"
    commands.append(['storage','buckets','add-iam-policy-binding','gs://'+bucket,'--member='+member,
                     '--role=roles/storage.objectUser','--condition='+condition])
    for command in commands:
        r = subprocess.run([gcloud, *command, '--project='+project, '--quiet'], capture_output=True, timeout=90)
        if r.returncode: raise RuntimeError('Credential writer permission update failed')


def grant_reader(project, group, member, gcloud='gcloud'):
    bucket = project+'-scotus-video-media'
    condition = "expression=resource.name == 'projects/_/buckets/"+bucket+"/objects/secret-bundles/current/"+group+"',title=secret-bundle-pointer"
    for command in (["secrets","add-iam-policy-binding",group,"--member="+member,"--role=roles/secretmanager.secretAccessor","--condition=None"],
                    ["storage","buckets","add-iam-policy-binding","gs://"+bucket,"--member="+member,"--role=roles/storage.objectViewer","--condition="+condition]):
        r = subprocess.run([gcloud,*command,'--project='+project,'--quiet'],capture_output=True,timeout=90)
        if r.returncode: raise RuntimeError('Credential reader permission update failed')


def runtime_flags(entry, control_url, project):
    values = {'SCOTUS_SECRET_BUNDLES':'1', 'SCOTUS_RUNTIME_CONFIG':entry, 'SCOTUS_CONTROL_URL':control_url, 'GOOGLE_CLOUD_PROJECT':project}
    return ','.join(k+'='+v for k, v in values.items())


def register_reader(store, account, entry):
    if entry == 'scotus-video-control-config': return
    def patch(raw):
        value = json.loads(raw)
        readers = value.setdefault('runtime_readers', {})
        readers[account] = sorted(set(readers.get(account, [])) | {entry})
        return json.dumps(value).encode()
    store.update('scotus-video-control-config', patch)


def run_gcloud(command, **kwargs):
    gcloud, *parts = command
    project = flag(parts, '--project')
    relevant = parts[:1] == ['secrets'] or any(p.startswith(('--set-secrets=', '--update-secrets=')) for p in parts)
    if not relevant: return subprocess.run(command, **kwargs)
    if not project: raise ValueError('Managed secret operations require an explicit --project')
    if not enabled(project, gcloud): return subprocess.run(command, **kwargs)
    store = SecretStore(cli_cloud(project, gcloud))
    out = None
    if parts[:1] == ['secrets']:
        op = parts[1:3]
        if parts[1:2] == ['list']: return subprocess.run(command, **kwargs)
        name = (flag(parts, '--secret') or parts[3]) if parts[1:2] == ['versions'] else parts[2]
        if name in GROUPS: return subprocess.run(command, **kwargs)
        group = group_for(name)
        if op[:1] in (['describe'], ['create']):
            out = {'name':'projects/'+project+'/secrets/'+group}
        elif op == ['versions','access']:
            if parts[3] != 'latest': raise ValueError('Logical credentials support current version only')
            out = store.read(name)
        elif op == ['versions','add']:
            path = flag(parts, '--data-file')
            raw = kwargs.get('input') if path == '-' else Path(path).read_bytes()
            if isinstance(raw, str): raw = raw.encode()
            if group == GROUPS[0]:
                configuration=json.loads(raw);configuration.setdefault('project',project)
                if configuration['project'] != project:raise ValueError('Runtime configuration belongs to another project')
                raw=json.dumps(configuration).encode()
            if name == 'scotus-video-control-config':
                desired = json.loads(raw)
                def preserve_readers(previous):
                    return json.dumps({**desired, 'runtime_readers':{**json.loads(previous or b'{}').get('runtime_readers', {}),
                                                                 **desired.get('runtime_readers', {})}}).encode()
                version = store.update(name, preserve_readers)
            else: version = store.replace(name, raw)
            out = {'name':version}
        elif parts[1] == 'add-iam-policy-binding':
            # Runtime configs are delivered by the controller, not shared with workers.
            if group == GROUPS[0]: out = {}
            else:
                member, role = flag(parts, '--member'), flag(parts, '--role')
                if role in ('roles/secretmanager.secretVersionAdder', 'projects/'+project+'/roles/scotusSpotifyCredentialRenewal'):
                    grant_writer(project, group, member, gcloud); out = {}
                elif role == 'roles/secretmanager.secretAccessor':
                    grant_reader(project, group, member, gcloud); out = {}
                else:
                    replaced = [group if p == name else p for p in parts]
                    return subprocess.run([gcloud, *replaced], **kwargs)
        else: raise ValueError('Use managed credential replacement instead of legacy version commands')
    elif parts[:3] == ['run','jobs','deploy'] or parts[:2] == ['run','deploy']:
        updated = []
        entry = None
        for part in parts:
            if part.startswith(('--set-secrets=', '--update-secrets=')):
                mount = part.split('=',1)[1]
                if ',' in mount: raise ValueError('Review mixed secret mounts before deployment')
                path, reference = mount.split('=',1)
                entry, version = reference.rsplit(':',1)
                if group_for(entry) != GROUPS[0] or version != 'latest': raise ValueError('Expected current runtime configuration')
                updated.append('--clear-secrets')
            else: updated.append(part)
        if entry:
            control = json.loads(store.read('scotus-video-control-config'))
            account = flag(parts, '--service-account')
            if not account: raise ValueError('Runtime configuration requires an explicit service account')
            register_reader(store, account, entry)
            if entry != 'scotus-video-control-config':
                granted = subprocess.run([gcloud,'run','services','add-iam-policy-binding','scotus-video-control',
                    '--region='+control['region'],'--project='+project,'--member=serviceAccount:'+account,
                    '--role=roles/run.invoker','--quiet'],capture_output=True,timeout=90)
                if granted.returncode: raise RuntimeError('Runtime configuration invocation grant failed')
            extra = runtime_flags(entry, control['control_url'], project)
            for index, part in enumerate(updated):
                if part.startswith('--update-env-vars='):
                    if part.split('=',1)[1].startswith('^'): raise ValueError('Review custom environment delimiter')
                    updated[index] = part+','+extra; break
            else: updated.append('--update-env-vars='+extra)
        return subprocess.run([gcloud, *updated], **kwargs)
    else: return subprocess.run(command, **kwargs)
    if not isinstance(out, bytes): out = json.dumps(out).encode()
    if kwargs.get('text') or kwargs.get('encoding'): out = out.decode()
    return subprocess.CompletedProcess(command, 0, out, '' if isinstance(out,str) else b'')
