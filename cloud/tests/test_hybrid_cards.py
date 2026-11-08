import base64,copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
from scotus_cloud.annotation_cards import CardTools,cue_for,preview_fingerprint
from scotus_cloud.card_pipeline import Pipeline,RoleTools,GENERATOR,ACK,profile
from scotus_cloud.research_errors import ResearchUnavailable

URL='https://court.example/opinion'
CONTEXT='The court may review a judgment. The application must be timely.'

class Cloud:
 def __init__(self):
  self.current={'version':0,'checkpoint':None};self.objects={}
  self.aligned={'paragraphs':[{'speaker':'a','start':0,'text':'We discuss a legal rule.'},{'speaker':'a','start':20,'text':'Next topic.'}], 'audio':{'duration_seconds':40},'speakers':{}}
 def storage_upload(self,path,uri,*args):self.objects[uri]=Path(path).read_bytes()
 def storage_json(self,uri,**kw):return copy.deepcopy(self.aligned) if uri=='gs://owned/aligned' else json.loads(self.objects[uri])
 def storage_bytes(self,uri,**kw):return self.objects[uri]
 def request(self,*a,**kw):return {'items':[]}

class Lease:
 def __init__(self,cloud):self.cloud=cloud;self.dashboard=Mock();self.notes=[]
 def call(self,op,**args):
  if op=='research_load':return copy.deepcopy(self.cloud.current)
  if op=='research_save':
   if args['version']!=self.cloud.current['version']:raise RuntimeError('Newer checkpoint exists')
   self.cloud.current={'version':args['version']+1,'checkpoint':copy.deepcopy(args['checkpoint'])};return {'version':args['version']+1}
  self.notes.append((op,args));return True

def card():
 return {'id':'rule','start_block':0,'end_block':1,'recommended':True,'reason':'The first discussion needs context',
  'cue_json':json.dumps({'kind':'Excerpt','heading':'The opinion','source':'Official opinion','quote':CONTEXT}),
  'evidence':[],'preview_id':'','visual_checked':False}

class HybridTests(unittest.TestCase):
 def setUp(self):
  self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
  self.cloud=Cloud();self.lease=Lease(self.cloud);self.calls=[];self.terra_failures=0;self.lose_editor_reply=False
  self.fetch=patch('scotus_cloud.enrichment.fetch',return_value=('<p>'+CONTEXT+'</p>').encode()).start();self.addCleanup(patch.stopall)
  image=io.BytesIO();Image.new('RGB',(1920,1080),'beige').save(image,'JPEG');self.image=image.getvalue()
  image_data=self.image;cloud=self.cloud
  def render(tools,c):
   key=preview_fingerprint(c)
   if key in tools.rendered:return {'contentItems':tools.rendered[key]}
   cue=cue_for(c,cloud.aligned)
   p={'frame_uri':'gs://owned/'+key+'/frame','card_uri':'gs://owned/'+key+'/card','cue':cue,'start':cue['start'],'end':cue['end']}
   tools.previews[key]=p
   tools.rendered[key]=[{'type':'inputText','text':json.dumps({'start':cue['start'],'end':cue['end'],'preview_id':key,'metrics':{'visible':True,'overflow':False}})},
     *[{'type':'inputImage','imageUrl':'data:image/jpeg;base64,'+base64.b64encode(image_data).decode()} for _ in range(2)]]
   for uri in (p['frame_uri'],p['card_uri']):cloud.objects[uri]=image_data
   return {'contentItems':tools.rendered[key]}
  patch.object(CardTools,'render',render).start()
 def pipeline(self):
  job={'id':'case','docket':'25-352','case_name':'Example','argument_date':'2026-11-02','pdf_url':'https://court.example/transcript.pdf','stages':{'align':{'status':'complete','result':{'transcript_uri':'gs://owned/aligned'}}}}
  return Pipeline(job,self.cloud.aligned,{}, {'bucket':'owned','claude_secret':'claude','codex_secret':'codex'},self.cloud,self.lease,self.directory.name,claude=self.claude,codex=self.codex)
 def scan(self,handler,role):
  source=handler('cards_source',{'url':URL,'query':'','page':1})
  packet=handler('cards_packet',{'id':'unit','source_id':source['source_id'],'page':1,'end_page':1,'kind':'opinion','locator':'The complete key paragraph','quote':'The court may review a judgment.','context':CONTEXT,'context_complete':True,'caution':''})
  result={'top':['idea'],'candidates':[{'id':'idea','start_block':0,'end_block':1,'anchor':'a legal rule','kind':'Excerpt','pitch':'Explain the named rule','caution':'','uncertain':False,'packet_ids':[packet['packet_id']]}],'read_aloud':[],'notes':[]}
  handler('cards_checkpoint',result);return result
 def claude(self,*args,**kw):
  role='haiku' if args[5]=='haiku' else 'editor';self.calls.append(role);kw['on_start']();h=kw['tool_handler']
  self.assertTrue(kw.get('web',False));self.assertEqual(args[4],ACK);self.assertEqual(kw['timeout_seconds'],1200)
  self.assertTrue((kw['references']/'archive/templates.json').exists());self.assertFalse((kw['references']/'archive/25-352').exists())
  self.assertNotIn('input/examples.json',kw['inputs']);self.assertIn('input/library.json',kw['inputs'])
  if role=='haiku':
   self.assertNotIn('input/readers.json',kw['inputs']);h('cards_reader_finish',self.scan(h,role));return {'saved':True}
  inputs=kw['inputs'];self.assertNotIn('input/filings.json',inputs)
  self.assertTrue({'cards_source','cards_search','cards_sources','cards_ocr'} <= {t['name'] for t in kw['tools']})
  packets=h('cards_evidence',{'packet_ids':['haiku/unit']})['packets'];self.assertEqual(packets[0]['context'],CONTEXT)
  c=card();c['evidence']=[{'source_id':packets[0]['source_id'],'page':1,'quote':CONTEXT,'claim':'The complete rule and its condition'}]
  draft={'cards':[c],'private_notes':[]};h('cards_validate',draft)
  sheet=h('cards_contact_sheet',draft)
  image=Image.open(io.BytesIO(base64.b64decode(sheet['contentItems'][1]['imageUrl'].split(',')[1])))
  self.assertEqual(image.size,(1920,1160))
  # Opus makes its editorial density change in the same invocation, after the sheet.
  cue=json.loads(c['cue_json']);cue['heading']='Opinion';c['cue_json']=json.dumps(cue)
  result={**draft,'decisions':[{'id':'haiku/idea','status':'selected','reason':'Named reference'},{'id':'terra/idea','status':'omitted','reason':'Same opportunity already selected'}]}
  h('cards_editor_finish',result)
  if self.lose_editor_reply:raise ResearchUnavailable('provider','Final CLI reply lost')
  kw['on_usage']({'usage':{'input_tokens':100,'output_tokens':20}});return {'saved':True}
 def codex(self,*args,**kw):
  role='terra' if kw['model']=='gpt-6.1-terra' else 'review';self.calls.append(role);h=kw['tool_handler'];self.assertEqual(args[4],ACK)
  self.assertTrue((kw['references']/'archive/templates.json').exists());self.assertNotIn('input/examples.json',kw['inputs'])
  if role=='terra':
   self.assertNotIn('input/readers.json',kw['inputs'])
   if self.terra_failures:
    self.terra_failures-=1;raise ResearchUnavailable('provider','Temporary quota wait')
   h('cards_reader_finish',self.scan(h,role));return {'saved':True}
  self.assertNotIn('cards_editor_finish',[t['name'] for t in kw['tools']]);self.assertNotIn('cards_contact_sheet',[t['name'] for t in kw['tools']])
  editor=json.loads(kw['inputs']['input/editor.json']);cards=copy.deepcopy(editor['cards'])
  for c in cards:
   v=h('cards_render',{'card':c});c['preview_id']=json.loads(v['contentItems'][0]['text'])['preview_id'];c['visual_checked']=True
  result={'cards':cards,'private_notes':['Sources and full frames checked'],'editorial_proposals':[{'card':'rule','action':'move','reason':'Optional earlier placement for owner consideration'}],'blocking_issues':[]}
  self.assertTrue(h('cards_validate',{'cards':cards,'private_notes':[]})['valid'])
  h('cards_review_finish',result);return {'saved':True}
 def test_complete_one_way_workflow_and_restart_reuses_all_model_work(self):
  first=self.pipeline().run();self.assertEqual(first['generator'],GENERATOR)
  self.assertEqual(set(self.calls),{'haiku','terra','editor','review'});self.assertEqual(len(self.calls),4)
  self.assertTrue(first['cards'][0]['visual_checked']);self.assertTrue(any('Editorial proposal' in note for note in first['private_notes']))
  second=self.pipeline().run();self.assertEqual(len(self.calls),4);self.assertEqual(first['cards'],second['cards'])
  self.assertFalse(any('/checkpoints/' in key for key in self.cloud.objects))
 def test_lost_editor_reply_after_finish_does_not_call_opus_again(self):
  self.lose_editor_reply=True;result=self.pipeline().run()
  self.assertEqual(self.calls.count('editor'),1);self.assertEqual(result['workflow']['calls']['editor'],1)
 def test_retry_keeps_the_reader_that_finished_independently(self):
  self.terra_failures=1
  with self.assertRaises(ResearchUnavailable):self.pipeline().run()
  self.assertIn('haiku',self.cloud.current['checkpoint']['plan']['hybrid']['readers'])
  result=self.pipeline().run();self.assertEqual(self.calls.count('haiku'),1);self.assertEqual(self.calls.count('terra'),2);self.assertEqual(result['workflow']['calls']['editor'],1)
 def test_incomplete_or_unfaithful_packets_are_rejected(self):
  p=self.pipeline();h=RoleTools(p,'haiku').invoke;source=h('cards_source',{'url':URL,'query':'','page':1})
  args={'id':'unit','source_id':source['source_id'],'page':1,'end_page':1,'kind':'rule','locator':'Rule subsection','quote':'may review','context':CONTEXT,'context_complete':True,'caution':''}
  import jsonschema
  with self.assertRaises(jsonschema.ValidationError):h('cards_packet',{**args,'context_complete':False})
  with self.assertRaisesRegex(ValueError,'match'):h('cards_packet',{**args,'context':'Invented text'})
  with self.assertRaisesRegex(ValueError,'match'):h('cards_packet',{**args,'quote':' ','context':' '})
 def test_reader_cannot_use_another_readers_packet(self):
  p=self.pipeline();scan=self.scan(RoleTools(p,'haiku').invoke,'haiku')
  with self.assertRaisesRegex(ValueError,'this reader'):p.validate_scan('terra',scan)
 def test_sheet_replay_is_safe_but_second_editorial_sheet_is_blocked(self):
  p=self.pipeline();p.run();h=RoleTools(p,'editor').invoke;saved=copy.deepcopy(p.state['editor_draft'])
  self.assertIn('contentItems',h('cards_contact_sheet',saved))
  saved['cards'][0]['reason']='Different proposal'
  with self.assertRaisesRegex(ValueError,'one editorial'):h('cards_contact_sheet',saved)
 def test_sol_cannot_move_drop_or_add_cards_as_mechanical_edits(self):
  p=self.pipeline();p.run();original=copy.deepcopy(p.state['review_final'])
  moved=copy.deepcopy(original);moved['cards'][0].update(start_block=1,end_block=2)
  with self.assertRaisesRegex(ValueError,'Timing'):p.review_finish(moved)
  added=copy.deepcopy(original);extra=copy.deepcopy(added['cards'][0]);extra.update(id='extra',start_block=1,end_block=2);added['cards'].append(extra)
  with self.assertRaisesRegex(ValueError,'selected card set'):p.review_finish(added)
  p.state['editor_final']['cards'].append(extra)
  with self.assertRaisesRegex(ValueError,'selected card set'):p.review_finish(original)
 def test_editor_cannot_finalize_before_contact_sheet_or_launch_second_session(self):
  p=self.pipeline();p.start('editor')
  with self.assertRaisesRegex(ResearchUnavailable,'call budget'):p.start('editor')
  self.assertEqual(p.state['calls']['editor'],1)
 def test_missing_claude_precondition_starts_no_reader(self):
  from scotus_cloud.claude_runner import run_claude
  p=self.pipeline();p.claude=run_claude
  with patch('scotus_cloud.card_pipeline.claude_access',side_effect=ResearchUnavailable('auth','Missing token')):
   with self.assertRaises(ResearchUnavailable):p.run()
  self.assertEqual(self.calls,[])
 def test_material_issue_is_held_without_an_automatic_opus_return(self):
  p=self.pipeline();p.run();blocked=copy.deepcopy(p.state['review_final']);blocked['blocking_issues']=[{'card':'rule','reason':'The proposed summary omits a material condition'}]
  self.assertTrue(p.review_finish(blocked)['held']);self.assertNotIn('review_final',p.state)
  self.assertEqual(self.calls.count('editor'),1)
 def test_reader_reports_and_finished_editor_survive_timing_only_change(self):
  p=self.pipeline();p.run();self.cloud.aligned['paragraphs'][1]['start']=21
  job=copy.deepcopy(p.job);job['stages']['align']['result']['transcript_uri']='gs://owned/new-alignment'
  self.cloud.storage_json=lambda uri,**kw:copy.deepcopy(self.cloud.aligned) if uri.startswith('gs://owned/new-alignment') else json.loads(self.cloud.objects[uri])
  resumed=Pipeline(job,self.cloud.aligned,{},p.settings,self.cloud,self.lease,self.directory.name,claude=self.claude,codex=self.codex)
  self.assertIn('editor_final',resumed.state);self.assertEqual(resumed.state['calls']['editor'],1);self.assertNotIn('review_final',resumed.state)
 def test_execution_yields_before_starting_a_phase_it_cannot_finish(self):
  import time
  p=self.pipeline();p.deadline=time.monotonic()+60
  with self.assertRaises(ResearchUnavailable) as stopped:p.run()
  self.assertEqual(stopped.exception.kind,'yield');self.assertEqual(self.calls,[])
 def test_no_useful_cards_does_not_force_filler_or_an_empty_contact_sheet(self):
  p=self.pipeline();scan=self.scan(RoleTools(p,'haiku').invoke,'haiku');p.state['readers']['haiku']=scan
  result={'cards':[],'private_notes':['No card adds helpful context'],'decisions':[{'id':'haiku/idea','status':'omitted','reason':'The speaker explains the term immediately'}]}
  self.assertTrue(p.editorial_finish(result)['saved']);self.assertEqual(p.state['editor_final']['cards'],[])

 def test_short_confirmation_without_finish_does_not_complete_a_phase(self):
  p=self.pipeline();p.claude=lambda *args,**kw: {'saved':True}
  with self.assertRaisesRegex(ResearchUnavailable,'did not pass card checks'):p.run()
  self.assertNotIn('haiku',p.state['readers']);self.assertNotIn('editor_final',p.state)
 def test_reader_finish_survives_lost_final_confirmation(self):
  p=self.pipeline();original=p.claude
  def lose(*args,**kw):
   result=original(*args,**kw)
   if args[5]=='haiku':raise ResearchUnavailable('provider','Lost final acknowledgement')
   return result
  p.claude=lose;result=p.run()
  self.assertEqual(self.calls.count('haiku'),1);self.assertEqual(result['workflow']['calls']['editor'],1)
 def test_only_top_decisions_are_required_and_other_omissions_are_filled_by_host(self):
  p=self.pipeline();p.run();scan=p.state['readers']['haiku'];extra=copy.deepcopy(scan['candidates'][0]);extra['id']='non_top';scan['candidates'].append(extra)
  edited=copy.deepcopy(p.state['editor_final']);self.assertEqual(len(edited['decisions']),2)
  p.editorial_finish(edited)
  automatic=next(d for d in p.tools.history.plan['decisions'] if d['id']=='haiku/non_top')
  self.assertEqual(automatic,{'id':'haiku/non_top','status':'omitted','reason':''})
  self.assertEqual(len(p.state['editor_final']['decisions']),2)
  edited['decisions']=edited['decisions'][:1]
  with self.assertRaisesRegex(ValueError,'top-list'):p.editorial_finish(edited)
 def test_editor_can_search_and_quote_a_cached_passage_absent_from_reader_packets(self):
  p=self.pipeline();p.run();h=RoleTools(p,'editor').invoke
  source=p.tools.sources[next(iter(p.tools.sources))];source['pages'][0]['text']+=' A distinct extra sentence missing from packets.'
  found=h('cards_search',{'source_id':'','query':'distinct extra sentence'})
  self.assertEqual(found['total_matches'],1);hit=found['matches'][0]
  self.assertIn('missing from packets',hit['text']);self.assertEqual(hit['page'],1)
  edited=copy.deepcopy(p.state['editor_final']);c=edited['cards'][0];cue=json.loads(c['cue_json']);cue['quote']='A distinct extra sentence missing from packets.';c['cue_json']=json.dumps(cue)
  c['evidence']=[{'source_id':hit['source_id'],'page':1,'quote':cue['quote'],'claim':'The additional sentence'}]
  self.assertTrue(h('cards_validate',{'cards':[c],'private_notes':[]})['valid'])
 def test_cached_search_finds_late_passage_after_large_whitespace_without_fetching(self):
  p=self.pipeline();p.tools.sources['cached']={'sha256':'cached-fixture','url':'https://court.example/cached','pages':[{'page':1,'text':('Preface. '+(' '*50))*400+'Waiver is intentional relinquishment; forfeiture is a failure to assert.'}]}
  fetched=self.fetch.call_count
  result=RoleTools(p,'editor').invoke('cards_search',{'source_id':'cached','query':'Waiver is intentional relinquishment'})
  self.assertIn('Waiver is intentional',result['matches'][0]['text']);self.assertEqual(self.fetch.call_count,fetched)
 def test_source_download_returns_paths_and_publishes_live_searchable_files(self):
  p=self.pipeline();h=RoleTools(p,'haiku').invoke;source=h('cards_source',{'url':URL,'query':'','page':0})
  self.assertEqual(source['pages'],[]);self.assertEqual(source['page_count'],1)
  root=p.library.root
  text_file=root/source['text_file'].removeprefix('reference/')
  self.assertEqual(text_file.read_text(),'=== PHYSICAL PAGE 1 ===\n'+CONTEXT)
  self.assertTrue((root/'sources'/source['source_id']/'pages/00001.txt').exists())
  self.assertIn('source_id',json.loads((root/'sources'/source['source_id']/'source.json').read_text()))
  targeted=h('cards_source',{'url':URL,'query':'','page':1})
  self.assertEqual(targeted['pages'][0]['text'],CONTEXT)
 def test_reader_can_save_its_result_even_after_reaching_tool_budget(self):
  p=self.pipeline();endpoint=RoleTools(p,'haiku');scan=self.scan(endpoint.invoke,'haiku');p.state['tool_calls']['haiku']=180
  self.assertTrue(endpoint.invoke('cards_reader_finish',scan)['saved']);self.assertIn('haiku',p.state['readers'])
 def test_sol_can_repair_a_current_duration_failure_without_a_new_opus_call(self):
  p=self.pipeline();p.run();p.state['editor_final']['cards'][0]['end_block']=2
  p.tools.aligned['audio']['duration_seconds']=90
  reviewed=copy.deepcopy(p.state['review_final'])
  self.assertTrue(p.review_finish(reviewed)['saved']);self.assertTrue(any('Mechanical timing repair' in n for n in reviewed['private_notes']))
  self.assertEqual(self.calls.count('editor'),1)
 def test_wrap_up_notice_is_delivered_in_tool_response_near_deadline(self):
  import time
  p=self.pipeline();endpoint=RoleTools(p,'editor');endpoint.deadline=time.monotonic()+199
  reply=endpoint.invoke('cards_sources',{})
  self.assertIn('wrap up soon',reply['workflow_notice']);self.assertEqual(reply['sources'],[])
  endpoint.deadline=time.monotonic()+400
  self.assertNotIn('workflow_notice',endpoint.invoke('cards_sources',{}))
 def test_profile_accepts_generous_budgets_and_rejects_over_execution_cap(self):
  self.assertEqual(profile({})['editor_seconds'],1200)
  self.assertEqual(profile({'annotation_cards_profile':{'claude_max_turns':160}})['claude_max_turns'],160)
  with self.assertRaises(ValueError):profile({'annotation_cards_profile':{'editor_seconds':1201}})

class WorkerWaitTests(unittest.TestCase):
 def test_subscription_wait_is_saved_without_a_code_failure_or_recovery(self):
  from scotus_cloud.worker import run_sequence
  lease=Mock();lease.data={};job={'id':'case'}
  with patch('scotus_cloud.worker.stage_run',side_effect=ResearchUnavailable('decision','Review needs an owner decision',phase='review')):
   run_sequence('enrich',{'job':job,'lease':'lease'},{},Mock(),lease)
  lease.call.assert_called_once_with('research_defer',kind='decision',message='Review needs an owner decision',retry_after=900,phase='review')
 def test_unexpected_code_exception_still_uses_normal_failure_reporting(self):
  from scotus_cloud.worker import run_sequence
  lease=Mock();lease.data={}
  with patch('scotus_cloud.worker.stage_run',side_effect=TypeError('implementation bug')),patch('scotus_cloud.worker.failure_report',return_value={}):
   with self.assertRaises(SystemExit):run_sequence('enrich',{'job':{'id':'case','stages':{}},'lease':'lease'},{},Mock(),lease)
  self.assertEqual(lease.call.call_args.args[0],'fail')

if __name__=='__main__':unittest.main()
