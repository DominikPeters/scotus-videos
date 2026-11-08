"""Release compatibility, durable launches and portable owner operations."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from scotus_cloud.releases import stamp,image_source,image_release
from scotus_cloud.repair_policy import validate_changes,verify_release
from scotus_cloud.repair_bootstrap import apply_release
from scotus_cloud.recovery_control import current_release
from scotus_cloud.recovery_worker import saved_candidate
from scotus_cloud.attempts import launch,reconcile
from scotus_cloud.maintenance import current_sources,refresh,audio_digest,maintain
from scotus_cloud.card_import import create,resolve_case

class ReleaseTests(unittest.TestCase):
 def baseline(self):return {'scotus_cloud/prepare.py':'value=1\n','prompts/unrelated.md':'notes'}
 def test_unrelated_content_is_not_an_extra_compatibility_identity(self):
  baseline=self.baseline();release=validate_changes(baseline,{'scotus_cloud/prepare.py':'value=2\n'},'worker-test-1')
  self.assertNotIn('baseline_sha256',release)
  verify_release({**baseline,'prompts/unrelated.md':'different notes'},release,'worker-test-1')
  with self.assertRaises(ValueError):verify_release(baseline,release,'worker-test-2')
 def test_rebase_retains_unchanged_edits_but_rejects_changed_source(self):
  baseline=self.baseline();release=validate_changes(baseline,{'scotus_cloud/prepare.py':'value=2\n'},'worker-old')
  updated=current_release(baseline,release,Mock(),{},'worker-new')
  self.assertEqual(updated['release_id'],'worker-new')
  self.assertIsNone(current_release({**baseline,'scotus_cloud/prepare.py':'value=3\n'},release,Mock(),{},'worker-new'))
 def test_image_manifest_and_real_edited_file_are_checked_before_apply(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'scotus_cloud').mkdir();file=root/'scotus_cloud/prepare.py';file.write_text('value=1\n')
   stamp(root,'worker-test');baseline=image_source(root);release=validate_changes(baseline,{'scotus_cloud/prepare.py':'value=2\n'},'worker-test')
   self.assertEqual(image_release(root)['id'],'worker-test');apply_release(release,root,'prepare');self.assertEqual(file.read_text(),'value=2\n')
   with self.assertRaisesRegex(ValueError,'Edited source changed'):apply_release(release,root,'prepare')
 def test_saved_edits_survive_unrelated_deployment_changes(self):
  baseline=self.baseline();release=validate_changes(baseline,{'scotus_cloud/prepare.py':'value=2\n'},'worker-old')
  snapshot={'changed':release['files'],'base_files':release['base_files']}
  self.assertEqual(saved_candidate(snapshot,{**baseline,'prompts/unrelated.md':'new'}),release['files'])
  self.assertEqual(saved_candidate(snapshot,{'scotus_cloud/prepare.py':'changed'}),{})

class LaunchTests(unittest.TestCase):
 def test_lost_cloud_reply_is_not_a_failed_stage_or_duplicate_launch(self):
  dashboard=Mock();dashboard.call.side_effect=lambda op,**kw:({'claimed':True,'id':'run-12'} if op=='launch_prepare' else True)
  google=Mock();google.execute.side_effect=TimeoutError('acknowledgement lost')
  self.assertIsNone(launch(dashboard,google,{'region':'test'},{'kind':'stage','job':'case','stage':'align'},'scotus-video-align',{'SCOTUS_DISPATCH_TOKEN':'private'}))
  self.assertEqual(google.execute.call_args.args[2]['SCOTUS_ATTEMPT_ID'],'run-12')
  self.assertTrue(any(c.args[0]=='launch_uncertain' for c in dashboard.call.call_args_list))
  self.assertFalse(any(c.args[0]=='dispatch_failed' for c in dashboard.call.call_args_list))
  dashboard.call.side_effect=lambda op,**kw:{'claimed':False,'id':'run-12'}
  launch(dashboard,google,{'region':'test'},{'kind':'stage','job':'case','stage':'align'},'scotus-video-align',{'SCOTUS_DISPATCH_TOKEN':'private'})
  self.assertEqual(google.execute.call_count,1)
 def snapshot(self):return {'jobs':{'case':{'stages':{'align':{'status':'starting','_launch':{'id':'run-12','owner':{'kind':'stage','job':'case','stage':'align'},'cloud_job':'scotus-video-align'}}}}}}
 def test_existing_execution_is_adopted_after_controller_crash(self):
  google=Mock();google.find_attempt_execution.return_value={'name':'projects/test/locations/test/jobs/scotus-video-align/executions/scotus-video-align-owned','done':False}
  dashboard=Mock();reconcile(dashboard,google,{'region':'test'},self.snapshot())
  self.assertEqual(dashboard.call.call_args.args[0],'launch_record');google.execute.assert_not_called()
 def test_unavailable_listing_does_not_prove_a_missing_execution(self):
  google=Mock();google.find_attempt_execution.side_effect=TimeoutError();dashboard=Mock()
  reconcile(dashboard,google,{'region':'test'},self.snapshot());dashboard.call.assert_not_called()

class SourceRefreshTests(unittest.TestCase):
 def test_same_url_replaced_audio_restarts_preparation_but_identical_bytes_do_not(self):
  job={'id':'case','pdf_url':'pdf','audio_url':'audio','stages':{'prepare':{'result':{'transcript_uri':'gs://owned/prepared.json'}}}}
  dashboard=Mock();dashboard.call.side_effect=lambda op,**kw:job if op=='source_refresh_claim' else kw
  google=Mock();google.storage_json.return_value={'inputs':{'pdf_sha256':'same'},'audio':{'sha256':'original-audio'}}
  with patch('scotus_cloud.maintenance.current_sources',return_value={'pdf_url':'pdf','audio_url':'audio'}),patch('scotus_cloud.maintenance.pdf_digest',return_value='same'),patch('scotus_cloud.maintenance.audio_digest',return_value='replacement-audio') as digest:
   self.assertTrue(refresh(dashboard,google,{},'case',manual=True)['changed'])
   digest.return_value='original-audio'
   self.assertFalse(refresh(dashboard,google,{},'case',manual=True)['changed'])
   digest.side_effect=TimeoutError()
   self.assertEqual(refresh(dashboard,google,{},'case',manual=True)['status'],'waiting_for_source')
 def test_audio_digest_streams_official_bytes_and_rejects_redirects_and_empty_audio(self):
  import hashlib,io
  url='https://www.supremecourt.gov/media/audio/mp3files/case.mp3'
  class Response(io.BytesIO):pass
  response=Response(b'ID3audio');response.url=url
  with patch('scotus_cloud.maintenance.urlopen',return_value=response):self.assertEqual(audio_digest(url),hashlib.sha256(b'ID3audio').hexdigest())
  for final,data in [('https://untrusted.example/file',b'audio'),(url,b'')]:
   response=Response(data);response.url=final
   with patch('scotus_cloud.maintenance.urlopen',return_value=response):
    with self.assertRaises(ValueError):audio_digest(url)
 def test_normal_maintenance_does_not_download_audio_for_healthy_cases(self):
  with patch('scotus_cloud.maintenance.audio_digest') as digest:
   maintain(Mock(),Mock(),{}, {'jobs':{'case':{'id':'case','status':'ready','stages':{}}}})
  digest.assert_not_called()
 def test_transcript_index_replacement_wins_over_stale_audio_detail_link(self):
  job={'docket':'25-352','argument_date':'2026-11-02'}
  pages={
   'https://www.supremecourt.gov/oral_arguments/argument_audio/2026':'<tr><td>25-352 Younge 11/02/26</td><td><a href="/oral_arguments/audio/2026/25-352">Audio</a></td></tr>',
   'https://www.supremecourt.gov/oral_arguments/audio/2026/25-352':'<a href="/media/audio/mp3files/25-352.mp3">Audio</a><a href="/oral_arguments/argument_transcripts/2026/25-352_old.pdf">PDF</a>',
   'https://www.supremecourt.gov/oral_arguments/argument_transcript/2026':'<tr><td><a href="/oral_arguments/argument_transcripts/2026/25-352_new.pdf">25-352</a> Younge 11/02/26</td></tr>'}
  self.assertTrue(current_sources(job,pages.__getitem__)['pdf_url'].endswith('_new.pdf'))
 def test_identical_pdf_with_a_new_url_keeps_existing_work(self):
  job={'id':'case','pdf_url':'old','audio_url':'audio','stages':{'prepare':{'result':{'transcript_uri':'gs://owned/prepared.json'}}}}
  dashboard=Mock();dashboard.call.side_effect=lambda op,**kw:job if op=='source_refresh_claim' else kw
  google=Mock();google.storage_json.return_value={'inputs':{'pdf_sha256':'same'}}
  with patch('scotus_cloud.maintenance.current_sources',return_value={'pdf_url':'new','audio_url':'audio'}),patch('scotus_cloud.maintenance.pdf_digest',return_value='same'):
   result=refresh(dashboard,google,{},'case')
  self.assertFalse(result['changed'])
 def test_source_check_outage_is_a_wait_not_a_code_repair(self):
  dashboard=Mock();dashboard.call.return_value={'id':'case','stages':{}}
  with patch('scotus_cloud.maintenance.current_sources',side_effect=TimeoutError()):result=refresh(dashboard,Mock(),{},'case')
  self.assertEqual(result['status'],'waiting_for_source');self.assertEqual(dashboard.call.call_args.args[0],'source_refresh_wait')

class ImportTests(unittest.TestCase):
 def job(self):return {'id':'2026-case','docket':'25-352','case_name':'Younge','stages':{'align':{'result':{'transcript_uri':'gs://owned/aligned.json'}}},'review':{'cards':[{'sources':[{'url':'https://court.example/opinion.pdf','page':8,'quote':'Exact passage','claim':'Supports text'}]}]}}
 def test_case_name_and_existing_research_replace_hash_and_uri_inputs(self):
  job=self.job();dashboard=Mock();created={}
  def call(op,**kw):
   if op=='snapshot':return {'jobs':{job['id']:job}}
   if op=='card_import_create':created.update(kw);return {'id':kw['import_id'],'status':'uploading','spec_uri':kw['spec_uri'],'card_count':kw['card_count']}
   return {'id':kw['import_id'],'status':'queued','card_count':1}
  dashboard.call.side_effect=call
  google=Mock();spec={'cards':[{'id':'first','start_block':0,'end_block':1,'evidence':[{'source':'opinion.txt','page':1,'quote':'Exact passage','claim':'Supports text'}]}]}
  result=create(dashboard,google,{'bucket':'private'},'Younge',spec)
  self.assertEqual(created['job'],job['id']);self.assertTrue(result['id'].startswith('cards-'));self.assertNotIn('release_sha256',result)
  self.assertEqual(created['alignment_uri'],'gs://owned/aligned.json');self.assertNotIn('url',spec['cards'][0]['evidence'][0])
 def test_unknown_source_is_actionable_before_creating_import(self):
  job=self.job();dashboard=Mock();dashboard.call.return_value={'jobs':{job['id']:job}};google=Mock()
  with self.assertRaisesRegex(ValueError,'source_urls'):create(dashboard,google,{'bucket':'private'},'Younge',{'cards':[{'id':'x','start_block':0,'end_block':1,'evidence':[{'source':'new.pdf','quote':'Unknown','claim':'New','page':1}]}]})
  google.storage_upload.assert_not_called()
 def test_ambiguous_case_requires_a_recording_choice(self):
  dashboard=Mock();dashboard.call.return_value={'jobs':{'a':self.job(),'b':self.job()}}
  with self.assertRaisesRegex(ValueError,'Choose one recording'):resolve_case(dashboard,'Younge')

class ImportPreviewTests(unittest.TestCase):
 def test_rendered_cards_resume_and_require_owner_review(self):
  from scotus_cloud.card_import_worker import prepare
  from scotus_cloud.annotation_cards import CardTools,preview_fingerprint
  spec={'cards':[{'id':'one','start_block':0,'end_block':1,'cue':{'kind':'Excerpt','quote':'The Court may review the judgment.','heading':'Review','source':'Official opinion'},'evidence':[{'url':'https://court.example/opinion','page':1,'quote':'The Court may review the judgment.','claim':'Review is available'}]}]}
  job={'id':'fixture','stages':{'align':{'result':{'transcript_uri':'gs://owned/aligned'}}}}
  cloud=Mock();cloud.storage_json.return_value={'paragraphs':[{'start':10,'text':'The judgment'},{'start':20,'text':'Next'}],'audio':{'duration_seconds':30}}
  calls=[]
  def source(tools,url,query,page):
   tools.sources['source']={'url':url,'sha256':'public-document','pages':[{'page':1,'text':'The Court may review the judgment.'}]}
   return {'source_id':'source'}
  def render(tools,card):
   calls.append(card['id']);tools.previews[preview_fingerprint(card)]={'frame_uri':'gs://owned/frame','card_uri':'gs://owned/card','start':10,'end':20,'cue':{}}
   return {'contentItems':[{'text':json.dumps({'metrics':{'overflow':False,'visible':True}})}]}
  with tempfile.TemporaryDirectory() as folder,patch.object(CardTools,'source',source),patch.object(CardTools,'render',render):
   first=prepare(spec,job,{}, {'bucket':'owned'},cloud,Mock(),folder)
   again=prepare(spec,job,{}, {'bucket':'owned'},cloud,Mock(),folder,prepared=first['cards'])
  self.assertEqual(calls,['one']);self.assertEqual(first,again)
  self.assertFalse(first['cards'][0]['visual_checked']);self.assertTrue(first['cards'][0]['owner_review_required'])
  self.assertEqual(first['cards'][0]['preview_id'],preview_fingerprint(first['cards'][0]))
