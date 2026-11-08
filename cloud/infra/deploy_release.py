"""Resume one tested control/pipeline deployment from its build receipts.

The image owns source identity. This command owns publication and configuration;
operators do not calculate or copy hashes between services.
"""
import argparse,base64,json,subprocess,sys,time,hashlib,uuid
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from infra.managed_secrets import cli_cloud,run_gcloud
from infra.registry_cleanup import execution_active,refresh as retain_images
from infra.migrate_secrets import resource_plan
from scotus_cloud.secret_store import SecretStore
from scotus_cloud.remote import Dashboard

def running_pipeline_executions(resources, executions):
 jobs={r['name'] for r in resources if r['kind']=='job' and '/scotus-videos/pipeline@' in r['image']}
 return [e['metadata']['name'] for e in executions if execution_active(e)
         and e['metadata'].get('labels',{}).get('run.googleapis.com/job') in jobs]

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--control-build',type=Path,required=True);parser.add_argument('--pipeline-build',type=Path,required=True)
 parser.add_argument('--state',type=Path,required=True);parser.add_argument('--apply',action='store_true')
 parser.add_argument('--verify-and-resume',action='store_true',help='Run the isolated image checks and release this deployment hold')
 args=parser.parse_args();pipeline=json.loads(args.pipeline_build.read_text());control=json.loads(args.control_build.read_text())
 project=pipeline['project'];region=pipeline['region'];identity=pipeline['release_id']
 if control['project']!=project or control['region']!=region:raise ValueError('Build projects differ')
 def g(*command):
  r=run_gcloud(['gcloud',*command,'--project='+project,'--quiet','--format=json'],capture_output=True,text=True,check=True,timeout=180)
  return json.loads(r.stdout or 'null')
 images={}
 for kind,build in [('pipeline',pipeline),('control',control)]:
  receipt=g('builds','describe',build['build_id'],'--region='+region)
  if receipt['status']!='SUCCESS':raise ValueError(kind+' build has not succeeded')
  images[kind]=build['image'].rsplit(':',1)[0]+'@'+receipt['results']['images'][0]['digest']
 if not args.apply:print(json.dumps({'release':identity,'pipeline_image':images['pipeline'],'control_image':images['control'],'applied':False}));return
 cloud=cli_cloud(project);store=SecretStore(cloud);settings=json.loads(store.read('scotus-video-control-config'));dashboard=Dashboard(settings['dashboard_url'],settings['dispatcher_key'],'dispatcher')
 state=json.loads(args.state.read_text()) if args.state.exists() else {'release':identity,'updated_jobs':[]}
 if state['release']!=identity:raise ValueError('Deployment state belongs to a different release')
 def save():args.state.write_text(json.dumps(state,indent=2)+'\n')
 if not state.get('configured'):
  dashboard.call('deployment_hold',release_id=identity);state['held']=True;save()
  # Active workers finish against their original image before job templates move.
  resources=resource_plan(g('run','services','list','--region='+region),g('run','jobs','list','--region='+region))
  running=running_pipeline_executions(resources,g('run','jobs','executions','list','--region='+region))
  if running:print(json.dumps({'release':identity,'status':'waiting_for_workers','executions':running}));return
  retain_images(project,region,protect=images.values(),apply=True)
  for item in resources:
   if item['kind']=='job' and '/scotus-videos/pipeline@' in item['image'] and item['name'] not in state['updated_jobs']:
    g('run','jobs','update',item['name'],'--region='+region,'--image='+images['pipeline'],*(['--task-timeout=1320s'] if item['name']==settings.get('recovery',{}).get('job') else []))
    state['updated_jobs'].append(item['name']);save();print('Updated '+item['name'],flush=True)
  source=Path(pipeline['source_manifest_path']);uri=f'gs://{settings["bucket"]}/releases/{identity}/source.json'
  expected=json.loads(source.read_text());old=cloud.storage_json(uri,max_bytes=3145728)
  if old is None:cloud.storage_upload(source,uri,'application/json')
  elif old!=expected:raise ValueError('Worker release source changed')
  record={'schema_version':1,'id':identity,'image':images['pipeline'],'source_uri':uri}
  url=f'https://storage.googleapis.com/storage/v1/b/{settings["bucket"]}/o/'+quote('releases/current.json',safe='')
  response=cloud.session.get(url,params={'fields':'generation'},timeout=30)
  if response.status_code==404:generation='0'
  else:response.raise_for_status();generation=response.json()['generation']
  if generation!='0' and not state.get('previous_release'):
   previous=cloud.storage_json(f'gs://{settings["bucket"]}/releases/current.json')
   if previous and previous.get('id')!=identity:state['previous_release']=previous;save()
  response=cloud.session.post(f'https://storage.googleapis.com/upload/storage/v1/b/{settings["bucket"]}/o',params={'uploadType':'media','name':'releases/current.json','ifGenerationMatch':generation},headers={'Content-Type':'application/json'},data=json.dumps(record).encode(),timeout=30);response.raise_for_status()
  if cloud.storage_json(f'gs://{settings["bucket"]}/releases/current.json')!=record:raise RuntimeError('Release publication was not confirmed')
  bundle,_=store.bundle('scotus-internal');transforms={}
  for name,entry in bundle['entries'].items():
   if not name.endswith('-config'):continue
   config=json.loads(base64.b64decode(entry['data']))
   if 'workflow_baseline_sha256' not in config and name!='scotus-video-control-config':continue
   def update(raw,name=name):
    value=json.loads(raw);value.pop('workflow_baseline_sha256',None)
    if name=='scotus-video-control-config':
     value['worker_release_uri']=f'gs://{settings["bucket"]}/releases/current.json';value.get('recovery',{}).pop('baseline_uri',None)
    return json.dumps(value).encode()
   transforms[name]=update
  store.update_many(transforms)
  g('run','services','update','scotus-video-control','--region='+region,'--image='+images['control'])
  g('run','services','update-traffic','scotus-video-control','--region='+region,'--to-latest')
  state['images']=images;state['deployment_record']=record;state['configured']=True;save()
  print(json.dumps({'release':identity,'status':'ready_for_verification','pipeline_jobs':len(state['updated_jobs'])}),flush=True)
 if not args.verify_and_resume:return
 from scotus_cloud.repair_policy import validate_changes
 from scotus_cloud.model import digest_json
 source=json.loads(Path(pipeline['source_manifest_path']).read_text())
 def check(release,label):
  prefix=f'gs://{settings["bucket"]}/releases/{identity}/'+label
  source_uri=prefix+'/source.json'
  report_uri=f'gs://{settings["bucket"]}/recovery/tests/releases/{identity}/'+label+'/result.json'
  probe=state.setdefault('checks',{}).get(label)
  if probe and probe.get('passed'):return probe
  if not probe:
   file=args.state.with_suffix('.probe.json');file.write_text(json.dumps(release))
   old=cloud.storage_json(source_uri,max_bytes=262144)
   if old is None:cloud.storage_upload(file,source_uri,'application/json')
   elif old!=release:raise ValueError('Deployment check source changed')
   action=hashlib.sha256((identity+label+report_uri).encode()).hexdigest();probe={'source':source_uri,'result':report_uri,'action':action,'requested_at':time.time()};state['checks'][label]=probe;save()
   probe['operation']=cloud.execute(region,settings['recovery']['test_job'],{'SCOTUS_PROJECT':project,'SCOTUS_TEST_SOURCE_URI':source_uri,'SCOTUS_TEST_RESULT_URI':report_uri,'SCOTUS_REPAIR_ACTION_ID':action},tasks=1);save()
  while True:
   report=cloud.storage_json(report_uri,max_bytes=65536)
   if report:break
   found=cloud.find_repair_execution(region,settings['recovery']['test_job'],probe['action'])
   if found and found['done']:raise RuntimeError('Deployment test ended without a report; processing remains held')
   if not found and time.time()-probe['requested_at']>300:raise RuntimeError('Deployment check launch unconfirmed; processing remains held')
   print('Waiting for isolated release checks: '+label,flush=True);time.sleep(20)
  if not report.get('passed') or report.get('release_sha256')!=digest_json(release):raise RuntimeError('Isolated release checks failed; processing remains held')
  probe['verification']=report;probe['passed']=True;save();return probe
 if not state.get('verified'):
  code=f'''import unittest
from scotus_cloud.releases import image_release,image_source
from scotus_cloud.model import digest_json
from scotus_cloud.repair_policy import baseline_files
from scotus_cloud.google import Google
class ReleaseDeploymentTests(unittest.TestCase):
 def test_actual_worker_release(self):
  self.assertEqual(image_release('/app')['id'],{identity!r})
  self.assertEqual(len(image_source('/app')),{len(source)!r})
  self.assertEqual(digest_json(image_source('/app')),{digest_json(source)!r})
  self.assertEqual(image_source('/app'),baseline_files('/app'))
 def test_isolated_identity_cannot_read_credentials(self):
  c=Google({project!r})
  for group in ('scotus-internal','scotus-research','scotus-publishing'):
   r=c.session.get('https://secretmanager.googleapis.com/v1/projects/{project}/secrets/'+group+'/versions/1:access',timeout=30)
   self.assertEqual(r.status_code,403)
'''
  release=validate_changes(source,{'scotus_cloud/repair_ext/prepare_deployment.py':'# Isolated deployment check only\n','tests/test_repair_case_release_deployment.py':code},identity)
  check(release,'check');state['verified']=True;save()
 if not state.get('compatibility_applied'):
  from scotus_cloud.recovery_control import current_release
  snapshot=dashboard.call('snapshot');pointers={}
  def collect(pointer):
   if pointer and pointer.get('uri') and pointer.get('sha256'):pointers[pointer['uri']+'#'+pointer['sha256']]=pointer
  for job in (snapshot.get('jobs') or {}).values():
   collect(job.get('workflow_release'))
   for pointer in (job.get('workflow_releases') or {}).values():collect(pointer)
  for entries in (snapshot.get('reusable_repairs') or {}).values():
   for pointer in entries.values():collect(pointer)
  replacements={}
  for key,pointer in pointers.items():
   supplied=cloud.storage_json(pointer['uri'],max_bytes=262144)
   if digest_json(supplied)!=pointer['sha256']:raise ValueError('Saved repair source differs')
   updated=current_release(source,supplied,cloud,{'bucket':settings['bucket']},identity)
   if updated is None:replacements[key]=None;continue
   probe=check(updated,'compatibility/'+digest_json(updated))
   replacements[key]={'uri':probe['source'],'sha256':digest_json(updated),'release_id':identity,'test_report_uri':probe['result']}
  state['compatibility']=dashboard.call('deployment_rebase',release_id=identity,replacements=replacements);state['compatibility_applied']=True;save()
 if not state.get('released'):
  dashboard.call('deployment_release',release_id=identity);state['released']=True;save()
  retain_images(project,region,apply=True)
 # Delete this check's temporary objects and the superseded generated snapshot.
 # Legacy repair baselines and case artifacts are outside this owned namespace.
 def remove(uri):
  bucket,name=uri[5:].split('/',1);url=f'https://storage.googleapis.com/storage/v1/b/{bucket}/o/'+quote(name,safe='')
  r=cloud.session.get(url,params={'fields':'generation'},timeout=30)
  if r.status_code==404:return
  r.raise_for_status();generation=r.json()['generation'];r=cloud.session.delete(url,params={'ifGenerationMatch':generation},timeout=30);r.raise_for_status()
 if not state.get('cleaned'):
  for uri in (state['checks']['check']['source'],state['checks']['check']['result']):remove(uri)
  old=state.get('previous_release') or {}
  if old.get('source_uri')==f'gs://{settings["bucket"]}/releases/{old.get("id")}/source.json' and old.get('id')!=identity:remove(old['source_uri'])
  state['cleaned']=True;save()
 print(json.dumps({'release':identity,'status':'deployed','processing_hold_released':True}),flush=True)

if __name__=='__main__':main()
