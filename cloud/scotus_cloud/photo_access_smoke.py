"""Bounded cloud-only protocol/profile probe; no photo approval or job mutations."""
import json,os
from pathlib import Path
from .secret_store import runtime_settings
from .google import Google
from .remote import Dashboard
from .codex_auth import run_codex
from .photo_access import PhotoAccess

def main():
 if not os.environ.get('CLOUD_RUN_JOB'):raise RuntimeError('Cloud-only profile probe')
 os.environ['SCOTUS_PRIVATE_CODEX_WORKER']='1'
 settings=runtime_settings('/secrets/worker/config.json');cloud=Google(settings['project'])
 dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'enrich');access=PhotoAccess(cloud,settings);observed=[]
 def invoke(name,args):
  value=access.invoke(name,args);observed.append(value);return value
 schema={'type':'object','properties':{'complete':{'type':'boolean'}},'required':['complete'],'additionalProperties':False}
 run_codex(dashboard,cloud,settings['codex_secret'],
  'Call photo_fetch_authenticated exactly once with https://www.linkedin.com/in/aimee-brown-4564b316/. This is a read-only tool connectivity check. Do not use shell or web search. Do not approve, edit, or download an image. Whether the profile is accessible or blocked, return complete=true after the tool returns.',
  schema,model='gpt-6-luna',timeout_seconds=120,tools=access.definitions(),tool_handler=invoke)
 if len(observed)!=1:raise RuntimeError('Probe did not exercise exactly one authenticated tool call')
 value=observed[0];print(json.dumps({'tool_protocol_worked':True,'http_status':value.get('http_status',200),'portrait_urls_found':len(value.get('portrait_urls',[])),'profile_title_available':bool(value.get('title'))}))
if __name__=='__main__':main()
