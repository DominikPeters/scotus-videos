"""Bounded cloud integration probes; no uploads or public video are created."""
import asyncio,json,os,tempfile,uuid
from pathlib import Path
from .google import Google
from .remote import Dashboard


def native(settings,cloud,folder):
    from .recovery_worker import RPC,definitions
    dashboard=Dashboard(settings['dashboard_url'],settings['dashboard_key'],'recovery')
    token=dashboard.call('auth_claim',name='codex')
    if not token:raise RuntimeError('Codex credentials are in use')
    home=folder/'auth';home.mkdir();original=cloud.secret(settings['codex_secret']);(home/'auth.json').write_bytes(original)
    (home/'config.toml').write_text('cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n')
    async def probe():
        env=dict(os.environ,CODEX_HOME=str(home));env.pop('OPENAI_API_KEY',None);env.pop('CODEX_API_KEY',None)
        process=await asyncio.create_subprocess_exec('codex','app-server',env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        rpc=RPC(process)
        try:
            await rpc.request('initialize',{'clientInfo':{'name':'scotus_integration_check','version':'1'},'capabilities':{'experimentalApi':True}});await rpc.send({'method':'initialized','params':{}})
            models=await rpc.request('model/list',{'limit':100,'includeHidden':True})
            thread=await rpc.request('thread/start',{'cwd':str(folder),'approvalPolicy':'never','sandbox':'read-only','ephemeral':False,'dynamicTools':definitions()})
            ids=[item['id'] for item in models.get('data',[])]
            print(json.dumps({'available_models':ids}),flush=True)
            await rpc.request('turn/start',{'threadId':thread['thread']['id'],'input':[{'type':'text','text':'This is an integration check. Call repair_log once with kind note and message Integration check. Then return {"checked":true}. Do nothing else.'}],'outputSchema':{'type':'object','properties':{'checked':{'type':'boolean'}},'required':['checked'],'additionalProperties':False}})
            deadline=asyncio.get_running_loop().time()+90;called=False;final=None
            while asyncio.get_running_loop().time()<deadline:
                try:message=await rpc.receive(10)
                except asyncio.TimeoutError:continue
                dashboard.call('auth_check',name='codex',token=token)
                if message.get('method')=='item/tool/call':
                    called=message['params']['tool']=='repair_log'
                    await rpc.send({'id':message['id'],'result':{'success':called,'contentItems':[{'type':'inputText','text':'Integration check recorded.'}]}})
                elif message.get('method')=='item/completed' and message['params']['item']['type']=='agentMessage':final=message['params']['item']['text']
                elif message.get('method')=='turn/completed':break
            if not called or not final or json.loads(final)!={'checked':True}:raise RuntimeError('Native dynamic-tool turn did not complete')
            # An empty new thread has no resumable rollout. Check a real saved turn
            # in a fresh process, as the asynchronous repair worker does.
            process.terminate();await process.wait()
            process=await asyncio.create_subprocess_exec('codex','app-server',env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            rpc=RPC(process);await rpc.request('initialize',{'clientInfo':{'name':'scotus_integration_resume','version':'1'},'capabilities':{'experimentalApi':True}});await rpc.send({'method':'initialized','params':{}})
            paths=list((home/'sessions').rglob('*'+thread['thread']['id']+'*.jsonl'))
            if not paths:raise RuntimeError('Native rollout was not saved')
            resumed=await rpc.request('thread/resume',{'threadId':thread['thread']['id'],'path':str(paths[0]),'cwd':str(folder),'approvalPolicy':'never','sandbox':'read-only'})
            return {'native_initialize':True,'dynamic_tool_thread':True,'dynamic_tool_invoked':True,'thread_resume':resumed['thread']['id']==thread['thread']['id'],'models':ids,'model_turns':1}
        finally:
            process.terminate();await process.wait()
    try:return asyncio.run(probe())
    finally:
        try:
            updated=(home/'auth.json').read_bytes()
            if updated!=original:dashboard.call('auth_check',name='codex',token=token);cloud.add_secret_version(settings['codex_secret'],updated)
        finally:dashboard.call('auth_release',name='codex',token=token)


def rendering(settings,cloud,folder):
    from .bundle import make_bundle
    from .enrichment import fetch,store_photo
    from .model import digest_json
    from .diagnostics import run_command
    root=Path('/app');catalog=json.loads((root/'advocate-catalog.json').read_text());entry=catalog['aaron_l_nielson']
    photo=store_photo(cloud,settings['bucket'],'integration-check','aaron_l_nielson',fetch(entry['uri'],4194304),{'origin':'curated_cache'},folder,preserve=True)
    speakers={'john_g_roberts_jr':{'name':'John G. Roberts, Jr.','last_name':'Roberts','identifier':'john_g_roberts_jr','kind':'justice','role':'Chief Justice'},'aaron_l_nielson':{'name':'Aaron L. Nielson','last_name':'Nielson','identifier':'aaron_l_nielson','kind':'advocate','role':'for the petitioner'}}
    transcript={'speakers':speakers,'audio':{'duration_seconds':20},'paragraphs':[{'text':'We will hear argument this morning. Mr. Nielson.','speaker':'john_g_roberts_jr','section':0,'turn':0,'start':0},{'text':'Mr. Chief Justice, and may it please the Court. This is a workflow check using the original presentation.','speaker':'aaron_l_nielson','section':0,'turn':1,'start':6}]}
    job={'id':'integration-check','case_name':'Workflow v. Check','docket':'25-735','argument_date':'2026-10-05','approved_photos':{'aaron_l_nielson':photo}}
    enrichment={'case_metadata':{},'description':{'fields':{'facts_of_the_case':'<p>A short test description.</p>','question':'<p>Does the original presentation render correctly?</p>'}},'titles':[{'title':'Oral Argument on a workflow check: Workflow v. Check'}],'oyez_content_used':False}
    bundle=folder/'bundle';make_bundle(bundle,job,transcript,enrichment,cloud)
    plan=folder/'plan.json';run_command(['node','/app/render/original.js','plan',str(bundle),job['id'],str(plan)],timeout=45)
    data=json.loads(plan.read_text());data['chunks']=[{'index':0,'first_frame':80,'end_frame':120},{'index':1,'first_frame':120,'end_frame':160}];plan.write_text(json.dumps(data))
    receipts=[]
    for index in range(2):
        out=folder/f'chunk-{index}.mp4';run_command(['node','/app/render/original.js','chunk',str(bundle),str(plan),str(index),str(out)],timeout=90)
        receipts.append(json.loads(Path(str(out)+'.receipt.json').read_text()))
    return {'renderer':'original','frames':sum(item['frames'] for item in receipts),'chunks':2,'source_hashes_checked':True,'encoded_geometry_checked':True,'model_turns':0}


def main():
    if not os.environ.get('CLOUD_RUN_JOB'):raise RuntimeError('Cloud-only probes')
    kind=os.environ['SCOTUS_SMOKE_KIND'];mount='recovery' if kind=='native' else 'worker'
    settings=json.loads(Path('/secrets/'+mount+'/config.json').read_text());cloud=Google(settings['project'])
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp);report=(native if kind=='native' else rendering)(settings,cloud,folder)
        path=folder/'report.json';path.write_text(json.dumps(report));cloud.storage_upload(path,os.environ['SCOTUS_SMOKE_REPORT'],'application/json');print(json.dumps(report))

if __name__=='__main__':main()
