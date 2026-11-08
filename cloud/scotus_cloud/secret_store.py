"""Three credential domains, serialized replacement, and one current version.

Locks intentionally never expire: an interrupted writer needs explicit operator
reconciliation instead of allowing a stale writer to overwrite newer credentials.
No payload or authentication token is logged.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import re
import time
from urllib.parse import quote

GROUPS = ('scotus-internal', 'scotus-research', 'scotus-publishing')
RESEARCH = {'scotus-video-codex', 'scotus-video-linkedin', 'scotus-video-claude'}
PUBLISHING = {'scotus-spotify-auth', 'scotus-video-github', 'scotus-video-instagram',
              'scotus-video-instagram-client', 'scotus-video-instagram-pending',
              'scotus-video-tiktok-session', 'scotus-video-youtube',
              'scotus-video-youtube-client', 'scotus-video-youtube-studio-session'}


def group_for(name):
    if name in RESEARCH: return GROUPS[1]
    if name in PUBLISHING: return GROUPS[2]
    if re.fullmatch(r'scotus-[a-z0-9-]+-config', name): return GROUPS[0]
    raise ValueError('Unknown logical secret')


def canonical(value):
    if not isinstance(value, bytes): raise TypeError('Secret values must be bytes')
    try: return json.dumps(json.loads(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    except (ValueError, UnicodeError): return value


def decode_bundle(raw):
    value = json.loads(raw)
    if value.get('schema_version') != 1 or not isinstance(value.get('entries'), dict):
        raise ValueError('Invalid credential bundle')
    return value


def encode_bundle(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    if len(raw) > 65536: raise ValueError('Credential bundle exceeds Secret Manager size limit')
    return raw


class SecretStore:
    def __init__(self, cloud, bucket=None):
        self.cloud = cloud
        self._status_cache = {}
        self.bucket = bucket or os.environ.get('SCOTUS_SECRET_LOCK_BUCKET', cloud.project+'-scotus-video-media')

    def pointer(self, group):
        key = 'secret-bundles/current/'+group
        response = self.cloud.session.get(f'https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/{quote(key, safe="")}',
                                          params={'alt':'media'}, timeout=30)
        if response.status_code == 404: return None, '0'
        if response.status_code != 200: raise RuntimeError('Credential pointer unavailable')
        value = response.json().get('version')
        if not isinstance(value,str) or not value.isdecimal(): raise ValueError('Invalid credential pointer')
        return value, response.headers['x-goog-generation']

    def raw(self, group, version=None):
        # Numeric Secret Manager reads are strongly consistent; latest and aliases
        # are not. GCS provides a strongly consistent pointer with no secret data.
        selected = version
        for attempt in range(3):
            if version is None:
                selected, _ = self.pointer(group)
                if selected is None: raise RuntimeError('Credential group has not been activated')
            try:
                result = self.cloud.request('GET', f'https://secretmanager.googleapis.com/v1/projects/{self.cloud.project}/secrets/{group}/versions/{selected}:access')
                return base64.b64decode(result['payload']['data']), result['name']
            except RuntimeError:
                if version is not None or attempt == 2: raise
                # A writer may have retired the version between our pointer read
                # and payload read. Reload the pointer instead of retaining history.
                current, _ = self.pointer(group)
                if current == selected: raise
        raise RuntimeError('Credential read needs retry')

    def bundle(self, group):
        raw, version = self.raw(group)
        return decode_bundle(raw), version

    def read(self, name):
        bundle, _ = self.bundle(group_for(name))
        try: return base64.b64decode(bundle['entries'][name]['data'], validate=True)
        except KeyError: raise ValueError('Credential is not configured') from None

    def status(self, name):
        group = group_for(name)
        if group not in self._status_cache: self._status_cache[group] = self.bundle(group)[0]
        item = self._status_cache[group]['entries'].get(name)
        return {'configured': item is not None, 'updated_at': item.get('updated_at') if item else None}

    @contextmanager
    def lock(self, group):
        if group not in GROUPS: raise ValueError('Unknown credential group')
        key = 'secret-bundles/locks/'+group
        url = f'https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o'
        deadline = time.monotonic()+30
        while True:
            response = self.cloud.session.post(url, params={'uploadType':'media', 'name':key, 'ifGenerationMatch':'0'},
                data=json.dumps({'at':datetime.now(timezone.utc).isoformat(), 'job':os.environ.get('CLOUD_RUN_JOB', 'deployment'),
                                 'execution':os.environ.get('CLOUD_RUN_EXECUTION'), 'service':os.environ.get('K_SERVICE'),
                                 'revision':os.environ.get('K_REVISION')}).encode(),
                headers={'Content-Type':'application/json'}, timeout=30)
            if response.status_code in (200, 201):
                generation = response.json()['generation']; break
            if response.status_code not in (409, 412): raise RuntimeError('Credential write lock unavailable')
            if time.monotonic() >= deadline: raise RuntimeError('Credential write is locked; inspect interrupted writer before retrying')
            time.sleep(1)
        try: yield
        finally:
            response = self.cloud.session.request('DELETE', f'https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/{quote(key, safe="")}',
                                                 params={'ifGenerationMatch':generation}, timeout=30)
            if response.status_code not in (200, 204): raise RuntimeError('Credential lock release needs reconciliation')

    def activate(self, group, keep, previous=None):
        if not re.fullmatch(r'projects/[^/]+/secrets/'+re.escape(group)+r'/versions/[0-9]+',keep):
            raise ValueError('Wrong credential activation')
        current, generation = self.pointer(group)
        if previous is not None and current != previous.rsplit('/',1)[1]:
            raise RuntimeError('Credential activation changed concurrently')
        key = 'secret-bundles/current/'+group
        response = self.cloud.session.post(f'https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o',
             params={'uploadType':'media','name':key,'ifGenerationMatch':generation},
             headers={'Content-Type':'application/json'}, data=json.dumps({'version':keep.rsplit('/',1)[1]}).encode(),timeout=30)
        if response.status_code not in (200,201): raise RuntimeError('Credential activation failed')

    def discard(self, version):
        url = 'https://secretmanager.googleapis.com/v1/'+version
        metadata = self.cloud.request('GET', url)
        if metadata['state'] != 'DESTROYED': self.cloud.request('POST', url+':destroy', json={'etag':metadata['etag']})

    def prune(self, group, keep):
        prefix = f'projects/{self.cloud.project}/secrets/{group}/versions/'
        # API names may contain the numeric project identifier instead of its ID.
        if not re.fullmatch(r'projects/[^/]+/secrets/'+re.escape(group)+r'/versions/[0-9]+', keep):
            raise ValueError('Wrong credential version')
        _, latest = self.raw(group)
        if latest != keep: raise RuntimeError('Credential changed during replacement')
        versions, token = [], None
        while True:
            params = {'pageSize':100}
            if token: params['pageToken'] = token
            result = self.cloud.request('GET', 'https://secretmanager.googleapis.com/v1/'+prefix.rstrip('/'), params=params)
            versions.extend(result.get('versions', [])); token = result.get('nextPageToken')
            if not token: break
        for version in versions:
            if version['state'] != 'DESTROYED' and version['name'] != keep:
                self.cloud.request('POST', 'https://secretmanager.googleapis.com/v1/'+version['name']+':destroy', json={'etag':version['etag']})

    def replace(self, name, value=None):
        return self.update(name, lambda previous: value)

    def update(self, name, transform):
        return self.update_many({name:transform})

    def update_many(self, transforms):
        """Commit related fields once, preserving the one-version group lifecycle."""
        groups={group_for(name) for name in transforms}
        if len(groups)!=1:raise ValueError('A configuration update must use one credential group')
        group=groups.pop()
        with self.lock(group):
            bundle, keep = self.bundle(group)
            entries=bundle['entries'];changed=False
            for name,transform in transforms.items():
                previous=entries.get(name)
                value=transform(base64.b64decode(previous['data']) if previous else None)
                data=base64.b64encode(canonical(value)).decode() if value is not None else None
                different=(previous is not None) if value is None else (not previous or previous['data']!=data)
                if not different:continue
                changed=True
                if value is None:entries.pop(name,None)
                else:entries[name]={'data':data,'updated_at':datetime.now(timezone.utc).isoformat()}
            previous_version = keep
            if changed:
                raw = encode_bundle(bundle)
                result = self.cloud.request('POST', f'https://secretmanager.googleapis.com/v1/projects/{self.cloud.project}/secrets/{group}:addVersion',
                                            json={'payload':{'data':base64.b64encode(raw).decode()}})
                staged = result['name']
                try:
                    verified, _ = self.raw(group, staged.rsplit('/', 1)[1])
                    if verified != raw: raise RuntimeError('Credential replacement failed read-back verification')
                    self.activate(group, staged, previous=keep)
                except Exception:
                    # Activation may have succeeded despite a transport error. Never
                    # destroy a version selected by the authoritative current pointer.
                    _, selected = self.raw(group)
                    if selected != staged: self.discard(staged)
                    raise
                keep = staged
                selected, _ = self.raw(group)
                if selected != raw: raise RuntimeError('Credential activation needs reconciliation')
            if changed: self.discard(previous_version)
            self.prune(group, keep)
            self._status_cache.clear()
            return keep


def runtime_settings(path):
    """Only the controller reads the internal bundle; workers request their slice."""
    from pathlib import Path
    name = os.environ.get('SCOTUS_RUNTIME_CONFIG')
    if not name: return json.loads(Path(path).read_text())
    if name == 'scotus-video-control-config':
        from .google import Google
        return json.loads(SecretStore(Google(os.environ['GOOGLE_CLOUD_PROJECT'])).read(name))
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import fetch_id_token
    import requests
    url = os.environ['SCOTUS_CONTROL_URL'].rstrip('/')
    token = fetch_id_token(Request(), url)
    response = requests.post(url+'/v1/runtime-config', json={'name':name},
                             headers={'Authorization':'Bearer '+token}, timeout=30)
    if response.status_code != 200: raise RuntimeError('Runtime configuration unavailable')
    settings = response.json()['result']
    if os.environ.get('SCOTUS_CREDENTIAL_PROBE') == '1':
        credential_probe(settings)
        raise SystemExit(0)
    return settings


def credential_probe(settings):
    """Read/no-op-write and negative IAM checks, before any business action."""
    if not os.environ.get('CLOUD_RUN_JOB'): raise RuntimeError('Credential probes run only in Cloud Run jobs')
    from .google import Google
    cloud = Google(settings['project']);store = SecretStore(cloud)
    allowed = set(filter(None, os.environ.get('SCOTUS_CREDENTIAL_GROUPS', '').split(',')))
    writable = set(filter(None, os.environ.get('SCOTUS_CREDENTIAL_WRITE_GROUPS', '').split(',')))
    if not writable <= allowed or not allowed <= set(GROUPS): raise ValueError('Invalid credential probe scope')
    for group in GROUPS:
        if group in allowed:
            bundle, before = store.bundle(group)
            if group in writable:
                entry = next(iter(bundle['entries']))
                after = store.replace(entry, base64.b64decode(bundle['entries'][entry]['data']))
                if after != before: raise RuntimeError('No-op credential probe unexpectedly created a version')
        else:
            response = cloud.session.get(f'https://secretmanager.googleapis.com/v1/projects/{cloud.project}/secrets/{group}/versions/1:access',timeout=30)
            if response.status_code != 403: raise RuntimeError('Credential separation probe failed')
    print(json.dumps({'credential_probe':True, 'configuration':os.environ['SCOTUS_RUNTIME_CONFIG'],
                      'read_groups':sorted(allowed),'write_groups':sorted(writable),'versions_created':0}),flush=True)
