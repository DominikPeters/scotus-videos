"""Private, recording-scoped recovery evidence and isolated diagnostic probes."""
import hashlib,json,tempfile
from pathlib import Path
from .diagnostics import Redactor
from .model import digest_json,alignment_cpus
from .repair_policy import reserve_estimate
from .releases import repair_source,current as current_deployment


def evidence(tool,args,context,settings,google):
    rec,job=context['recovery'],context['job'];profile=settings['recovery']
    redactor=Redactor(settings,job,rec)
    stage_job=settings['jobs'][rec['stage']]
    resource=profile.get('stage_resources',{}).get(rec['stage'])
    actual_job=rec.get('diagnostic',{}).get('cloud_job') or job.get('stages',{}).get(rec['stage'],{}).get('cloud_job')
    if rec['stage'] in ('prepare','enrich') and settings.get('research_job') and actual_job==settings['research_job']:
        stage_job=settings['research_job']
    if rec['stage'] in ('assemble','upload') and settings.get('delivery_job') and actual_job==settings['delivery_job']:
        stage_job=settings['delivery_job']
    if tool in ('context','logs') and rec['stage']=='align' and settings.get('alignment_long_job'):
        cpus=alignment_cpus(job,google)
        if cpus==8:stage_job=settings['alignment_long_job']
        if resource:resource=[cpus,*resource[1:]]
    if tool=='source_info':
        record=current_deployment(google,settings)
        if record:return {'release_id':record['id'],'source_uri':record['source_uri']}
        baseline,release_id=repair_source(google,settings)
        digest=digest_json(baseline)
        return {'baseline_sha256':digest,'baseline_uri':f"gs://{profile['bucket']}/recovery/baselines/{digest}.json"}
    if tool=='context':
        return {'recording':redactor.value(job),'failure':redactor.value(rec.get('diagnostic',{})),
                'actions':redactor.value(rec.get('actions',{})),
                'stage_resources':resource,
                'deployment':google.job_profile(settings['region'],stage_job),
                'instructions':'Inspect checkpoints and existing actions before creating side effects. Use source_info/sync_sources after a deployment change.'}
    if tool=='logs':
        execution=rec.get('diagnostic',{}).get('execution');job_name=stage_job
        if args.get('action'):
            action=rec.get('actions',{}).get(args['action'])
            if not action or action['kind'] not in ('tests','probe','upload_audit'):raise ValueError('Unknown owned action')
            job_name=profile['test_job'] if action['kind'] in ('tests','probe') else settings['jobs']['upload']
            operation=action.get('result',{}).get('operation');execution=google.operation_status(operation).get('execution') if operation else None
            if not execution:
                found=google.find_repair_execution(settings['region'],job_name,args['action'])
                if found:execution=found['name'].rsplit('/',1)[-1]
        if not execution:
            operation=job['stages'][rec['stage']].get('cloud_operation') if not args.get('action') else None
            if operation:execution=google.operation_status(operation).get('execution')
        if not execution:return {'status':'execution_identity_unavailable','failure':redactor.value(rec.get('diagnostic',{}))}
        return {'execution':execution,'entries':redactor.value(google.execution_logs(job_name,execution)),'untrusted_source_data':True}
    raise ValueError('Unknown recovery evidence tool')


def media_locator(args,context,settings):
    """Select only a known artifact of this recovery's own recording."""
    job=context['job'];kind=args['kind'];stages=job['stages']
    if kind=='thumbnail':uri=stages.get('plan',{}).get('result',{}).get('thumbnail_preview_uri')
    elif kind=='frame':uri=next((t.get('result',{}).get('preview_uri') for t in stages.get('render',{}).get('tasks',[]) if t.get('result',{}).get('preview_uri')),None)
    elif kind=='card':uri=next((c.get('frame_uri') for c in job.get('review',{}).get('cards',[]) if c['id']==args.get('card_id')),None)
    elif kind=='audio':uri=stages.get('prepare',{}).get('result',{}).get('audio_uri')
    else:raise ValueError('Unknown recording media kind')
    if not uri or not uri.startswith('gs://'+settings['recovery']['bucket']+'/') or '/'+job['id']+'/' not in uri:
        raise ValueError('No owned recording artifact is available for this selection')
    start=args.get('start',0);duration=args.get('duration',20)
    import math
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (start,duration)) or start<0 or not 1<=duration<=60:
        raise ValueError('Use a nonnegative audio start and a 1–60 second excerpt')
    return {'kind':kind,'uri':uri,'start':start,'duration':duration}


def launch_probe(dashboard,google,settings,context,data):
    args=data['arguments'];script=args['script']
    if not isinstance(script,str) or not 1<=len(script.encode())<=16000:raise ValueError('Probe script must be bounded Python source')
    compile(script,'probe.py','exec')
    rec,job=context['recovery'],context['job'];rid=data['recovery'];lease=data['lease'];profile=settings['recovery']
    key=hashlib.sha256((rid+data['call_id']).encode()).hexdigest()
    baseline,release_id=repair_source(google,settings)
    redactor=Redactor(settings,job,rec)
    probe={'script':script,'context':redactor.value({'recording':job,'failure':rec.get('diagnostic')}),
           'artifacts':{}}
    for stage,entry in job['stages'].items():
        for field in ('transcript_uri','plan_uri','interactions_uri','enrichment_uri'):
            uri=entry.get('result',{}).get(field)
            if uri and uri.startswith('gs://'+profile['bucket']+'/') and uri.endswith('.json'):
                probe['artifacts'][stage+'-'+field.removesuffix('_uri')]=uri
    uri=f"gs://{profile['bucket']}/recovery/workspaces/{rid}/{key}-probe.json"
    out=f"gs://{profile['bucket']}/recovery/tests/{rid}/{key}.json"
    claim=dashboard.call('recovery_action_claim',recovery=rid,lease=lease,action_id=key,
        request_hash=digest_json(args),kind='probe',reserve_usd=reserve_estimate(1,1,180),seconds=180)
    if 'existing' in claim:return {'action':key,**claim['existing']}
    if claim.get('budget_exhausted'):return {'budget_exhausted':True}
    with tempfile.TemporaryDirectory() as folder:
        p=Path(folder)/'probe.json';p.write_text(json.dumps(probe));google.storage_upload(p,uri,'application/json')
    result={'report_uri':out,'probe_uri':uri,'operation':None}
    dashboard.call('recovery_action_result',recovery=rid,lease=lease,action_id=key,result=result)
    operation=google.execute(settings['region'],profile['test_job'],{'SCOTUS_PROJECT':settings['project'],
        'SCOTUS_PROBE_URI':uri,'SCOTUS_TEST_RESULT_URI':out,
        'SCOTUS_REPAIR_ACTION_ID':key,**({'SCOTUS_TEST_BASELINE_URI':f"gs://{profile['bucket']}/recovery/baselines/{digest_json(baseline)}.json"} if not release_id else {})})
    result['operation']=operation
    dashboard.call('recovery_action_result',recovery=rid,lease=lease,action_id=key,result=result)
    return {'action':key,**result}
