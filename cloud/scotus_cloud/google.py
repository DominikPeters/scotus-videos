"""Google APIs using the runtime's service account, without exported keys."""

import base64
import json
from pathlib import Path
from urllib.parse import quote


class Google:
    def __init__(self, project):
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
        self.session = AuthorizedSession(credentials)
        self.project = project

    def request(self, method, url, **kwargs):
        r = self.session.request(method, url, timeout=60, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f'Google API request failed: HTTP {r.status_code}')
        return r.json() if r.content else {}

    def secret(self, name):
        result = self.request('GET', f'https://secretmanager.googleapis.com/v1/projects/{self.project}/secrets/{name}/versions/latest:access')
        return base64.b64decode(result['payload']['data'])

    def add_secret_version(self, name, value):
        return self.request('POST', f'https://secretmanager.googleapis.com/v1/projects/{self.project}/secrets/{name}:addVersion',
                            json={'payload': {'data': base64.b64encode(value).decode()}})['name']

    def retire_secret_versions(self,name,keep):
        """Spotify token rotation keeps only its newest version active/billable."""
        prefix=f'projects/{self.project}/secrets/{name}/versions/'
        if '/secrets/'+name+'/versions/' not in keep:raise ValueError('Wrong credential version')
        result=self.request('GET','https://secretmanager.googleapis.com/v1/'+prefix.rstrip('/'),
                            params={'pageSize':100,'filter':'state:ENABLED'})
        for version in result.get('versions',[]):
            if version['name']!=keep:self.request('POST','https://secretmanager.googleapis.com/v1/'+version['name']+':disable',json={})

    def secret_status(self, name):
        result = self.request('GET', f'https://secretmanager.googleapis.com/v1/projects/{self.project}/secrets/{name}/versions',
                              params={'pageSize': 10, 'filter': 'state:ENABLED'})
        versions = result.get('versions', [])
        return {'configured': bool(versions), 'updated_at': max((v.get('createTime', '') for v in versions), default=None)}

    def execute(self, region, job, env, tasks=1,timeout_seconds=None):
        overrides={'taskCount':tasks,'containerOverrides':[{'env':[{'name':k,'value':str(v)} for k,v in env.items()]}]}
        if timeout_seconds:overrides['timeout']=str(timeout_seconds)+'s'
        result=self.request('POST',f'https://run.googleapis.com/v2/projects/{self.project}/locations/{region}/jobs/{job}:run',json={'overrides':overrides})
        return result['name']

    def operation_status(self,operation):
        import re
        if not re.fullmatch(r'projects/'+re.escape(self.project)+r'/locations/[a-z0-9-]+/operations/[a-zA-Z0-9-]+',operation):
            raise ValueError('Unowned cloud operation')
        result=self.request('GET','https://run.googleapis.com/v2/'+operation)
        name=(result.get('response') or {}).get('name') or (result.get('metadata') or {}).get('target','')
        status={'done':bool(result.get('done')),'failed':bool(result.get('error'))}
        if '/executions/' in name:status['execution']=name.rsplit('/',1)[-1]
        return status

    def job_profile(self,region,job):
        value=self.request('GET',f'https://run.googleapis.com/v2/projects/{self.project}/locations/{region}/jobs/{job}')
        template=value.get('template',{});task=template.get('template',{});container=(task.get('containers') or [{}])[0]
        return {'image':container.get('image'),'resources':container.get('resources',{}).get('limits',{}),
                'parallelism':template.get('parallelism'),'timeout':task.get('timeout')}

    def find_repair_execution(self,region,job,action):
        import re
        if not re.fullmatch('[a-f0-9]{64}',action):raise ValueError('Invalid action identity')
        value=self.request('GET',f'https://run.googleapis.com/v2/projects/{self.project}/locations/{region}/jobs/{job}/executions',params={'pageSize':50})
        for execution in value.get('executions',[]):
            env=[v for c in execution.get('template',{}).get('containers',[]) for v in c.get('env',[])]
            if any(v.get('name')=='SCOTUS_REPAIR_ACTION_ID' and v.get('value')==action for v in env):
                return {'name':execution['name'],'done':bool(execution.get('completionTime')),
                        'failed':bool(execution.get('failedCount'))}
        return None

    def execution_logs(self,job,execution=None):
        import re
        if not re.fullmatch('scotus-video-[a-z-]+',job) or (execution and not re.fullmatch(re.escape(job)+'-[a-z0-9]+',execution)):
            raise ValueError('Invalid execution identity')
        filters=['resource.type="cloud_run_job"','resource.labels.job_name='+json.dumps(job)]
        if execution:filters.append('labels."run.googleapis.com/execution_name"='+json.dumps(execution))
        value=self.request('POST','https://logging.googleapis.com/v2/entries:list',json={
            'resourceNames':['projects/'+self.project],'filter':' AND '.join(filters),
            'orderBy':'timestamp desc','pageSize':30})
        return [{'at':v.get('timestamp'),'severity':v.get('severity'),
                 'text':str(v.get('textPayload') or v.get('jsonPayload') or v.get('protoPayload',{}).get('status',{}))[:1500]}
                for v in value.get('entries',[])][:30]

    def invoke_action_service(self,url,payload):
        from urllib.parse import urlsplit
        from google.auth.transport.requests import Request
        from google.oauth2.id_token import fetch_id_token
        import requests
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not (parsed.hostname or '').endswith('.run.app') or parsed.path not in ('','/'):
            raise ValueError('Invalid action service')
        token=fetch_id_token(Request(),url.rstrip('/'))
        response=requests.post(url.rstrip('/')+'/action',json=payload,headers={'Authorization':'Bearer '+token},timeout=30)
        if response.status_code!=200:raise RuntimeError('Cloud action service unavailable')
        return response.json()

    def storage_download(self, uri, path,expected_sha256=None):
        import hashlib
        fingerprint=hashlib.sha256() if expected_sha256 else None
        bucket, key = split_gs(uri)
        url = f'https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(key, safe="")}'
        with self.session.get(url, params={'alt': 'media'}, timeout=60, stream=True) as r:
            if r.status_code != 200:
                raise RuntimeError(f'Cloud object unavailable: HTTP {r.status_code}')
            with Path(path).open('wb') as target:
                for block in r.iter_content(1024 * 1024):
                    target.write(block)
                    if fingerprint:fingerprint.update(block)
        if fingerprint and fingerprint.hexdigest()!=expected_sha256:raise ValueError('Cloud artifact differs from its recorded content')

    def storage_json(self, uri, max_bytes=262144):
        import json
        bucket,key=split_gs(uri)
        url=f'https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(key,safe="")}'
        with self.session.get(url,params={'alt':'media'},timeout=30,stream=True) as response:
            if response.status_code==404: return None
            if response.status_code!=200: raise RuntimeError('Private object unavailable')
            data=bytearray()
            for block in response.iter_content(16384):
                data.extend(block)
                if len(data)>max_bytes: raise ValueError('Private object exceeds its read limit')
        return json.loads(data)

    def storage_bytes(self,uri,max_bytes=196608):
        bucket,key=split_gs(uri)
        url=f'https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(key,safe="")}'
        with self.session.get(url,params={'alt':'media'},timeout=30,stream=True) as response:
            if response.status_code!=200:raise RuntimeError('Private asset unavailable')
            data=bytearray()
            for block in response.iter_content(16384):
                data.extend(block)
                if len(data)>max_bytes:raise ValueError('Asset exceeds preview limit')
        return bytes(data)

    def storage_upload(self, path, uri, content_type='application/octet-stream'):
        bucket, key = split_gs(uri)
        size = Path(path).stat().st_size
        result = self.session.post(f'https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o',
                                   params={'uploadType': 'resumable', 'name': key, 'ifGenerationMatch': '0'},
                                   json={'contentType': content_type}, timeout=60)
        if result.status_code not in (200, 201):
            raise RuntimeError(f'Object upload could not start: HTTP {result.status_code}')
        with Path(path).open('rb') as source:
            response = self.session.put(result.headers['Location'], data=source,
                                        headers={'Content-Length': str(size)}, timeout=600)
        if response.status_code not in (200, 201):
            raise RuntimeError(f'Object upload failed: HTTP {response.status_code}')
        return response.json()


def split_gs(uri):
    if not uri.startswith('gs://') or '/' not in uri[5:]:
        raise ValueError('Expected a gs://bucket/object URI')
    bucket, key = uri[5:].split('/', 1)
    if not bucket or not key or '..' in key.split('/'):
        raise ValueError('Invalid cloud object URI')
    return bucket, key
