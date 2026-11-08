"""Small subscription CLI check: Sol delegates one host tool call to Luna."""
import json,os
from pathlib import Path
from .secret_store import runtime_settings
from .google import Google
from .remote import Dashboard
from .codex_auth import run_codex

class Handler:
 def __init__(self):self.events=[];self.calls=0
 def record_event(self,event):self.events.append(event)
 def invoke(self,name,args):
  if name!='card_sample' or args:raise ValueError('Unexpected sample call')
  self.calls+=1;return {'value':'source-verified'}

def main():
 settings=runtime_settings('/secrets/worker/config.json');google=Google(settings['project']);dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'enrich');handler=Handler();os.environ['SCOTUS_PRIVATE_CODEX_WORKER']='1'
 schema={'type':'object','additionalProperties':False,'properties':{'value':{'type':'string'}},'required':['value']}
 result=run_codex(dashboard,google,settings['codex_secret'],'Spawn exactly one fresh gpt-6-luna subagent. Instruct it to call card_sample exactly once and return the value from that tool. Do not call the tool yourself or browse the web. Wait for the subagent and output its value in the requested schema.',schema,model='gpt-6.1-sol',subagent_model='gpt-6-luna',tools=[{'name':'card_sample','description':'Return the test source value.','inputSchema':{'type':'object','additionalProperties':False,'properties':{},'required':[]}}],tool_handler=handler.invoke,timeout_seconds=180)
 child_tool=any(e['item_type']=='item/tool/call' and e['thread_id'] and e['thread_id']!=e['root_id'] for e in handler.events);spawned=child_tool or any(e.get('tool')=='spawnAgent' for e in handler.events)
 print(json.dumps({'delegated':spawned,'child_host_tool':child_tool,'tool_calls':handler.calls,'correct_result':result.get('value')=='source-verified','result_value':result.get('value'),'tools_seen':[e.get('tool') for e in handler.events if e.get('tool')]}),flush=True)
 if not spawned or not child_tool or handler.calls!=1 or result.get('value')!='source-verified':raise RuntimeError('Native annotation delegation check failed')

if __name__=='__main__':main()
