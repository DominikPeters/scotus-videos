"""Import an explicitly supplied Studio cURL into Secret Manager, never a repo file."""

try:
    from managed_secrets import run_gcloud
except ModuleNotFoundError:
    from infra.managed_secrets import run_gcloud
import argparse,copy,json,shlex,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('curl_file',type=Path);p.add_argument('--project',required=True);p.add_argument('--gcloud',default='gcloud');a=p.parse_args()
parts=shlex.split(a.curl_file.read_text().replace('\\\n',' '));headers={};cookies={};body={}
for i,v in enumerate(parts):
 if v in ('-H','--header'):
  k,_,value=parts[i+1].partition(':');headers[k.lower()]=value.strip()
 if v in ('-b','--cookie'):
  for pair in parts[i+1].split(';'):
   k,_,value=pair.strip().partition('=');cookies[k]=value
 if v in ('--data-raw','--data','--data-binary'):body=json.loads(parts[i+1])
if not cookies.get('SAPISID') or headers.get('origin')!='https://studio.youtube.com':raise ValueError('Expected the authenticated YouTube Studio request')
context={'client':{k:v for k,v in body['context']['client'].items() if k in ('clientName','clientVersion','hl','gl','utcOffsetMinutes')},'user':copy.deepcopy(body['context'].get('user',{}))}
credential={'schema_version':1,'cookies':cookies,'context':context,'headers':{k:v for k,v in headers.items() if k in ('user-agent','x-goog-authuser','x-youtube-delegation-context','x-youtube-client-name','x-youtube-client-version')}}
secret='scotus-video-youtube-studio-session'
def run(*args,data=None):return run_gcloud([a.gcloud,*args,'--project='+a.project,'--quiet'],input=data,capture_output=True)
if run('secrets','describe',secret).returncode:
 r=run('secrets','create',secret,'--replication-policy=automatic');r.check_returncode()
r=run('secrets','versions','add',secret,'--data-file=-',data=json.dumps(credential).encode());r.check_returncode()
r=run('secrets','add-iam-policy-binding',secret,'--member=serviceAccount:scotus-video-upload@'+a.project+'.iam.gserviceaccount.com','--role=roles/secretmanager.secretAccessor');r.check_returncode()
print(json.dumps({'secret':secret,'saved':True,'worker_access':True}))
