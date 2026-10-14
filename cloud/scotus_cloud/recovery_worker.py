"""Persistent private Codex repair turns with mediated write/test/retry tools."""
import asyncio,json,os,shutil,tempfile,time,uuid
import socket
from collections import deque
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit

from .google import Google
from .remote import Dashboard,signature
from .diagnostics import Redactor
from .repair_policy import baseline_files,validate_changes,verify_release,EDITABLE,file_hash,file_stages,changed_files
from .model import digest_json
from .control import validate_secret


ROOT=Path(__file__).resolve().parents[1]


def definitions():
    specs={
        'context':({},[],'Read current recording/checkpoint/action state, deployed image/resources and approved retry profile; credentials are redacted.'),
        'logs':({'action':{'type':['string','null']}},[],'Read bounded, redacted Cloud Run logs for this failed execution or an owned isolated action.'),
        'sync_sources':({},[],'Refresh the candidate workspace from the current deployed source snapshot. Preserve edits only if their original source files are unchanged; otherwise discard stale edits and diagnose current code.'),
        'probe':({'script':{'type':'string','maxLength':16000}},['script'],'Run a Python diagnostic in an isolated 1-CPU/1-GiB worker for at most 120 seconds, with current source and recording JSON fixtures in input/. No account secrets. Returns an action to poll or wait for.'),
        'wait':({'action':{'type':'string'}},['action'],'End this worker while tests/probe/audit runs; automatically resume the saved conversation when its report arrives. Use this rather than asking the operator to wait/restart you.'),
        'reconcile_action':({'action':{'type':'string'}},['action'],'Locate the cloud execution of an owned action after an uncertain launch response. Never relaunch while an execution exists.'),
        'read_file':({'path':{'type':'string'}},['path'],'Read a workflow source file.'),
        'write_file':({'path':{'type':'string'},'content':{'type':'string'}},['path','content'],'Change a permitted workflow file in the private candidate copy.'),
        'tests':({},[],'Run isolated regression checks on the candidate patch.'),
        'poll':({'action':{'type':'string'}},['action'],'Inspect an owned test action.'),
        'retry':({'action':{'type':['string','null']},'reusable':{'type':'boolean'},'reuse_reason':{'type':'string'},'restart_from':{'type':['string','null'],'enum':[None,'prepare','enrich','align','plan','render','assemble','upload']}},['action'],'Retry using a tested patch. Set restart_from to an upstream phase when that code caused the downstream failure. Preserve approvals, invalidate its dependent artifacts, and never rewind an existing upload. Mark general fixes reusable with a reason.'),
        'artifact':({'stage':{'type':'string'},'field':{'type':'string'},'offset':{'type':'integer','minimum':0}},['stage','field','offset'],'Inspect bounded text/JSON artifacts from this recording; no media or arbitrary URLs.'),
        'refresh_sources':({},[],'For failed preparation, refresh source links only from the official listing for this same docket and argument date.'),
        'inspect_upload':({},[],'Read matching recent channel uploads using the isolated uploader; returns an action to poll.'),
        'adopt_upload':({'action':{'type':'string'},'video_id':{'type':'string'}},['action','video_id'],'Use a verified existing video only after an operator answer to question upload-identity selects this video ID.'),
        'log':({'kind':{'type':'string','enum':['diagnosis','repair','validation','note']},'message':{'type':'string'}},['kind','message'],'Explain what happened and what you checked in the private dashboard log.'),
        'ask':({'question_id':{'type':'string'},'message':{'type':'string'},'options':{'type':'array','items':{'type':'object','properties':{'id':{'type':'string'},'label':{'type':'string'},'private_effect':{'type':'string'},'actor':{'type':'string','enum':['worker','operator']}},'required':['id','label','private_effect','actor'],'additionalProperties':False}}},['question_id','message','options'],'Ask only for a genuine owner decision or owner-only action. Each option must identify who acts and describe the actual next step. Answers resume Codex; they do not directly execute commands.')}
    return [{'type':'function','name':'repair_'+name,'description':description,
             'inputSchema':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}
            for name,(properties,required,description) in specs.items()]


class RPC:
    def __init__(self,process):self.process=process;self.counter=0;self.pending=deque()
    async def send(self,value):self.process.stdin.write(json.dumps(value).encode()+b'\n');await self.process.stdin.drain()
    async def receive(self,timeout=10):
        if self.pending:return self.pending.popleft()
        line=await asyncio.wait_for(self.process.stdout.readline(),timeout)
        if not line:raise RuntimeError('Codex process stopped')
        return json.loads(line)
    async def request(self,method,params):
        self.counter+=1;ident=self.counter;await self.send({'id':ident,'method':method,'params':params})
        deferred=[]
        while True:
            line=await asyncio.wait_for(self.process.stdout.readline(),30)
            if not line:raise RuntimeError('Codex process stopped')
            value=json.loads(line)
            if value.get('id')==ident and 'method' not in value:
                self.pending.extend(deferred)
                if 'error' in value:raise RuntimeError('Codex protocol request failed')
                return value['result']
            deferred.append(value)


class RepairTools:
    def __init__(self,settings,dashboard,cloud,rec,workspace,redactor):
        self.settings,self.dashboard,self.cloud,self.rec,self.workspace,self.redactor=settings,dashboard,cloud,rec,workspace,redactor
        self.baseline=baseline_files(ROOT);self.questions=False;self.waiting=False
    def call(self,op,**data):return self.dashboard.call(op,recovery=self.rec['id'],lease=self.rec['lease'],**data)
    def broker(self,name,args,call_id):
        path='/v1/recovery';url=self.settings['control_url']+path
        body=json.dumps({'recovery':self.rec['id'],'lease':self.rec['lease'],'tool':name,'arguments':args,'call_id':call_id}).encode()
        safe=name in ('context','logs','source_info','artifact','poll','reconcile_action')
        for attempt in range(3 if safe else 1):
            now=str(int(time.time()));nonce=uuid.uuid4().hex
            headers={'Content-Type':'application/json','X-Scotus-Time':now,'X-Scotus-Nonce':nonce,
                     'X-Scotus-Signature':signature(self.settings['recovery_key'],now,nonce,'POST',path,body)}
            try:
                with urlopen(Request(url,body,headers),timeout=15 if safe else 50) as response:result=json.loads(response.read(131073))
                if not result['ok']:raise RuntimeError('Repair broker rejected the request')
                return result['result']
            except HTTPError as error:
                if safe and error.code in (429,502,503,504) and attempt<2:time.sleep(attempt+1);continue
                if name in ('tests','probe','inspect_upload') and error.code in (502,503,504):
                    return {'action':__import__('hashlib').sha256((self.rec['id']+call_id).encode()).hexdigest(),'status':'launch_reply_unconfirmed',
                            'private_note':'Inspect context/reconcile_action before any new launch; the broker may have reserved or started it.'}
                try:detail=json.loads(error.read(32000)).get('error','Repair broker rejected the request')
                except Exception:detail='Repair broker rejected the request'
                raise RuntimeError(self.redactor.text(detail,2000)) from None
            except (URLError,TimeoutError,socket.timeout):
                if safe and attempt<2:time.sleep(attempt+1);continue
                if name in ('tests','probe','inspect_upload'):
                    return {'action':__import__('hashlib').sha256((self.rec['id']+call_id).encode()).hexdigest(),
                            'status':'launch_reply_unconfirmed','private_note':'The request may have been accepted. Inspect this action/context before any new launch; do not duplicate it.'}
                raise RuntimeError('Broker transport unavailable after bounded retries') from None
    def invoke(self,name,args,call_id):
        self.call('recovery_check')
        if name=='repair_sync_sources':
            info=self.broker('source_info',{},call_id)
            baseline=self.cloud.storage_json(info['baseline_uri'],max_bytes=1048576)
            if digest_json(baseline)!=info['baseline_sha256']:raise ValueError('Source snapshot hash differs')
            edits=changed_files(self.workspace,self.baseline)
            keep={key:text for key,text in edits.items() if baseline.get(key)==self.baseline.get(key)}
            for key in edits:
                if key not in keep and key not in baseline:(self.workspace/key).unlink(missing_ok=True)
            for key,text in {**baseline,**keep}.items():
                p=self.workspace/key;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
            self.baseline=baseline
            return {'baseline_sha256':digest_json(baseline),'preserved_edits':list(keep),'discarded_stale_edits':list(set(edits)-set(keep))}
        if name=='repair_wait':
            result=self.call('recovery_wait',action_id=args['action']);self.waiting=True
            return {**result,'instruction':'Return waiting_for_tests now; the controller will resume this thread when the report arrives.'}
        if name=='repair_read_file':
            if args['path']=='POLICY.md':return {'content':self.baseline['prompts/public-output-policy.md']}
            if args['path'] not in self.baseline and file_stages(args['path'],self.baseline) is None:raise ValueError('Unknown source file')
            return {'content':(self.workspace/args['path']).read_text()}
        if name=='repair_write_file':
            if self.questions:raise ValueError('Answer the pending question first')
            validate_changes(self.baseline,{args['path']:args['content']})
            stages=file_stages(args['path'],self.baseline)
            target=self.workspace/args['path'];target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(args['content']);return {'saved':True}
        if name=='repair_log':return self.call('recovery_log',kind=args['kind'],message=self.redactor.text(args['message'],4000))
        if name=='repair_ask':
            self.questions=True
            return self.call('recovery_question',question_id=args['question_id'],message=self.redactor.text(args['message'],4000),options=self.redactor.value(args['options']))
        if name=='repair_tests':
            changed=changed_files(self.workspace,self.baseline)
            release=validate_changes(self.baseline,changed)
            path=self.workspace/'release.json';path.write_text(json.dumps(release))
            uri=f"gs://{self.settings['bucket']}/recovery/workspaces/{self.rec['id']}/{uuid.uuid4().hex}.json"
            self.cloud.storage_upload(path,uri,'application/json')
            return self.broker('tests',{'release_uri':uri},call_id)
        if name in ('repair_context','repair_logs','repair_probe','repair_reconcile_action','repair_poll','repair_retry','repair_inspect_upload','repair_adopt_upload','repair_artifact','repair_refresh_sources'):
            if self.questions and name=='repair_retry':raise ValueError('Answer the pending question first')
            return self.broker(name.removeprefix('repair_'),args,call_id)
        raise ValueError('Unknown repair tool')


def saved_candidate(snapshot,baseline):
    if snapshot.get('baseline_sha256')!=digest_json(baseline):return {}
    changed=snapshot.get('changed',{})
    if changed:validate_changes(baseline,changed)
    return changed


def checkpoint_session(settings,cloud,rec,home,workspace,tools,thread_id):
    paths=list((home/'sessions').rglob('*'+str(thread_id)+'*.jsonl')) if thread_id else []
    if not paths:return
    rollout=str(paths[0].relative_to(home))
    snapshot={'thread_id':thread_id,'rollout_path':rollout,'rollout':paths[0].read_text(),'baseline_sha256':digest_json(tools.baseline),
              'tool_catalog_sha256':digest_json(definitions()),
              'changed':changed_files(workspace,tools.baseline)}
    path=workspace/'session.json';path.write_text(json.dumps(snapshot))
    if path.stat().st_size>16777216:raise ValueError('Repair session exceeds private storage limit')
    uri=f"gs://{settings['bucket']}/recovery/sessions/{rec['id']}/{uuid.uuid4().hex}.json"
    cloud.storage_upload(path,uri,'application/json')
    tools.call('recovery_checkpoint',thread_id=thread_id,rollout_path=rollout,session_uri=uri)


async def run_turn(settings,dashboard,cloud,rec,job,home,workspace,tools):
    env=dict(os.environ,CODEX_HOME=str(home))
    for key in ('OPENAI_API_KEY','CODEX_API_KEY','CODEX_ACCESS_TOKEN'):env.pop(key,None)
    process=await asyncio.create_subprocess_exec('codex','app-server',cwd=workspace,env=env,
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=2097152)
    rpc=RPC(process);final=None;thread_id=rec.get('thread_id');rollout=None
    try:
        await rpc.request('initialize',{'clientInfo':{'name':'scotus_repair','version':'1'},'capabilities':{'experimentalApi':True}})
        await rpc.send({'method':'initialized','params':{}})
        params={'model':settings.get('model','gpt-6.1-sol'),'cwd':str(workspace),'approvalPolicy':'never','sandbox':'workspace-write',
                'developerInstructions':(ROOT/'prompts/public-output-policy.md').read_text()+'\n'+(ROOT/'prompts/recovery.md').read_text()}
        if thread_id:
            params['threadId']=thread_id
            if rec.get('rollout_path'):params['path']=str(home/rec['rollout_path'])
            result=await rpc.request('thread/resume',params)
        else:
            params.update(ephemeral=False,dynamicTools=definitions());result=await rpc.request('thread/start',params)
        thread_id=result['thread']['id']
        prompt={'failure':rec.get('diagnostic'), 'recording':job,'questions':rec.get('questions',{}),
                'recent_recovery_log':rec.get('log',[])[-12:],'previous_conversation':rec.get('_prior_conversation'),
                'instructions':'Use the repair tools. Log the cause, changes and validation. A question must end this worker turn. Never claim repaired without a stage retry.'}
        await rpc.request('turn/start',{'threadId':thread_id,'input':[{'type':'text','text':json.dumps(prompt)}],
            'outputSchema':json.loads((ROOT/'schemas/recovery-result.schema.json').read_text())})
        deadline=time.monotonic()+600;next_check=0;next_checkpoint=time.monotonic()+45
        while time.monotonic()<deadline:
            if time.monotonic()>=next_check:
                tools.call('recovery_check');dashboard.call('auth_check',name='codex',token=settings['_auth_lease']);next_check=time.monotonic()+20
            if time.monotonic()>=next_checkpoint:
                await asyncio.to_thread(checkpoint_session,settings,cloud,rec,home,workspace,tools,thread_id);next_checkpoint=time.monotonic()+45
            try:message=await rpc.receive(10)
            except asyncio.TimeoutError:continue
            if message.get('method')=='item/tool/call':
                p=message['params']
                try:value=await asyncio.to_thread(tools.invoke,p['tool'],p['arguments'],p['callId']);success=True
                except Exception as error:value={'error':tools.redactor.text(error,1000)};success=False
                await rpc.send({'id':message['id'],'result':{'success':success,'contentItems':[{'type':'inputText','text':json.dumps(value)}]}})
                if tools.waiting:
                    final=json.dumps({'status':'waiting_for_tests','private_summary':'Waiting for an isolated action; the saved recovery will resume automatically.',
                        'checks':[],'workflow_patch_refs':[],'operator_messages':[]});break
            elif message.get('method')=='item/completed' and message['params']['item']['type']=='agentMessage':
                final=message['params']['item'].get('text')
            elif message.get('method')=='turn/completed':
                if message['params']['turn']['status']!='completed':raise RuntimeError('Codex turn failed; authentication or usage may need attention')
                break
            elif 'id' in message and 'method' in message:
                # Native escalation/user-input tools do not bypass the scoped broker.
                await rpc.send({'id':message['id'],'error':{'code':-32000,'message':'Use the scoped repair tools and repair_ask for operator questions.'}})
        else:raise RuntimeError('Repair turn time limit reached')
        if not final:raise RuntimeError('Repair returned no structured result')
        import jsonschema
        result=json.loads(final);jsonschema.validate(result,json.loads((ROOT/'schemas/recovery-result.schema.json').read_text()))
        if tools.waiting:result['status']='waiting_for_tests'
        return result,thread_id
    finally:
        if process.returncode is None:
            process.terminate()
            try:await asyncio.wait_for(process.wait(),5)
            except asyncio.TimeoutError:process.kill();await process.wait()
        # Keep native state after interruptions and unsuccessful turns as well.
        checkpoint_session(settings,cloud,rec,home,workspace,tools,thread_id)


def seed_workspace(workspace,baseline,job,stage,cloud):
    for name,text in baseline.items():
        path=workspace/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    if 'prompts/public-output-policy.md' in baseline:
        (workspace/'POLICY.md').write_text(baseline['prompts/public-output-policy.md'])
    pointer=job['stages'][stage].get('workflow_release') or job.get('workflow_releases',{}).get(stage) or job.get('workflow_release')
    if pointer:
        release=cloud.storage_json(pointer['uri'],max_bytes=262144)
        if digest_json(release)!=pointer['sha256']:raise ValueError('Active workflow release hash differs')
        verify_release(baseline,release)
        for name,text in release['files'].items():
            stages=file_stages(name)
            if not stages or stage in stages:
                p=workspace/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)


def main():
    if not os.environ.get('CLOUD_RUN_JOB'):raise RuntimeError('Repair workers run only on Cloud Run')
    settings=json.loads(Path('/secrets/recovery/config.json').read_text());os.umask(0o077)
    dashboard=Dashboard(settings['dashboard_url'],settings['dashboard_key'],'recovery');cloud=Google(settings['project'])
    claim=dashboard.call('recovery_claim',recovery=os.environ['SCOTUS_RECOVERY_ID'],dispatch_token=os.environ['SCOTUS_RECOVERY_TOKEN'])
    if not claim:return
    rec=claim['recovery'];job=claim['job'];auth_lease=None
    try:
        auth_lease=dashboard.call('auth_claim',name='codex')
        if not auth_lease:raise RuntimeError('Codex credentials are in use')
        settings['_auth_lease']=auth_lease
        with tempfile.TemporaryDirectory(prefix='repair-') as folder:
            root=Path(folder);home=root/'auth';workspace=root/'workflow';home.mkdir();workspace.mkdir()
            original=cloud.secret(settings['codex_secret']);validate_secret('codex',json.loads(original))
            (home/'auth.json').write_bytes(original);(home/'config.toml').write_text('cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\nweb_search = "live"\n')
            baseline=baseline_files(ROOT)
            seed_workspace(workspace,baseline,job,rec['stage'],cloud)
            if rec.get('session_uri'):
                snapshot=cloud.storage_json(rec['session_uri'],max_bytes=16777216)
                if snapshot.get('tool_catalog_sha256')!=digest_json(definitions()):
                    rec['_prior_conversation']=Redactor(settings,json.loads(original)).text(snapshot.get('rollout',''),32000)
                    previous=rec.pop('thread_id',None);rec.pop('rollout_path',None)
                    dashboard.call('recovery_log',recovery=rec['id'],lease=rec['lease'],kind='note',
                        message='Recovery capabilities upgraded. Starting a thread with the new tool catalog and retained prior conversation/context; the previous native history remains saved.')
                relative=Path(snapshot['rollout_path'])
                if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='sessions':raise ValueError('Invalid session path')
                path=home/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(snapshot['rollout'])
                edits=saved_candidate(snapshot,baseline)
                if edits:
                    for name,text in edits.items():(workspace/name).write_text(text)
                elif snapshot.get('changed'):
                    dashboard.call('recovery_log',recovery=rec['id'],lease=rec['lease'],kind='note',
                        message='Workflow source was updated since the saved turn. Conversation retained; old candidate edits were not restored. Inspect current source before making another patch.')
            tools=RepairTools(settings,dashboard,cloud,rec,workspace,Redactor(settings,json.loads(original)))
            try:result,thread_id=asyncio.run(run_turn(settings,dashboard,cloud,rec,job,home,workspace,tools))
            finally:
                updated=(home/'auth.json').read_bytes()
                if updated!=original:dashboard.call('auth_check',name='codex',token=auth_lease);cloud.add_secret_version(settings['codex_secret'],updated)
            for message in result['operator_messages']:
                if message['kind']=='question':tools.invoke('repair_ask',{'question_id':message['question_id'],'message':message['message'],'options':message['options']},'final')
                else:tools.call('recovery_log',kind='note',message=tools.redactor.text(message['message'],4000))
            tools.call('recovery_finish',status=result['status'],summary=tools.redactor.text(result['private_summary'],4000))
    except Exception as error:
        try:dashboard.call('recovery_finish',recovery=rec['id'],lease=rec['lease'],status='waiting_for_resource',summary=Redactor(settings).text(error,2000))
        except Exception:pass
    finally:
        if auth_lease:
            try:dashboard.call('auth_release',name='codex',token=auth_lease)
            except Exception:pass


if __name__=='__main__':main()
