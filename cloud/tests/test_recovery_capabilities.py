import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.repair_policy import validate_changes,changed_files,baseline_files
from scotus_cloud.repair_bootstrap import apply_release
from scotus_cloud.recovery_evidence import evidence
from scotus_cloud.recovery_control import broker,dispatch_recoveries
from scotus_cloud.recovery_test_worker import run_probe
from scotus_cloud.recovery_worker import definitions

class RecoveryCapabilitiesTests(unittest.TestCase):
 def test_workflow_helpers_and_new_regressions_are_permitted_but_controls_are_not(self):
  baseline={'scotus_cloud/prepare.py':'x=1'}
  release=validate_changes(baseline,{'scotus_cloud/prepare.py':'x=2','scotus_cloud/repair_ext/prepare_names.py':'x=3','tests/test_repair_case_names.py':'import unittest'})
  self.assertEqual(release['stages'],['prepare'])
  for path in ('scotus_cloud/control.py','scotus_cloud/repair_policy.py','presentation/renderer/index.html','prompts/public-output-policy.md','tests/test_secret_store.py','tests/test_recovery_capabilities.py','scotus_cloud/repair_ext/../control.py'):
   with self.assertRaises(ValueError):validate_changes(baseline,{path:'x=2'})
 def test_card_modules_and_existing_workflow_tests_can_be_repaired_together(self):
  files={'scotus_cloud/card_pipeline.py':'x=1','scotus_cloud/claude_runner.py':'x=2','tests/test_hybrid_cards.py':'import unittest'}
  self.assertEqual(validate_changes({},files)['stages'],['enrich'])
 def test_renderer_bug_fix_requires_matching_manifest(self):
  import hashlib
  name='presentation/renderer/script.js';text='// Restores intended rendering behavior\n'
  files={name:text,'presentation/sources.json':json.dumps({'renderer/script.js':{'sha256':hashlib.sha256(text.encode()).hexdigest()}})}
  self.assertEqual(validate_changes({},files)['stages'],['plan','render'])
  files[name]+='// Changed again'
  with self.assertRaisesRegex(ValueError,'manifest'):validate_changes({},files)
 def test_new_helper_and_regression_files_are_applied_and_checkpointed(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);p=root/'scotus_cloud/prepare.py';p.parent.mkdir();p.write_text('x=1')
   baseline=baseline_files(root);files={'scotus_cloud/prepare.py':'x=2','scotus_cloud/repair_ext/prepare_names.py':'x=3','tests/test_repair_case_names.py':'import unittest'}
   apply_release(validate_changes(baseline,files),root,'prepare')
   self.assertEqual(changed_files(root,baseline),files)
 def test_logs_are_bound_to_the_failed_execution_and_redacted(self):
  rec={'stage':'plan','diagnostic':{'execution':'scotus-video-plan-abc'}};job={'stages':{'plan':{}},'private_key':'private-value'}
  cloud=Mock();cloud.execution_logs.return_value=[{'text':'private-value'}]
  result=evidence('logs',{}, {'recovery':rec,'job':job},{'region':'us-central1','recovery':{},'jobs':{'plan':'scotus-video-plan'}},cloud)
  cloud.execution_logs.assert_called_once_with('scotus-video-plan','scotus-video-plan-abc');self.assertNotIn('private-value',json.dumps(result))
 def test_wrong_owned_action_cannot_read_other_logs(self):
  with self.assertRaises(ValueError):evidence('logs',{'action':'unknown'},{'recovery':{'stage':'plan'},'job':{}},{'recovery':{},'jobs':{'plan':'scotus-video-plan'}},Mock())
 def test_completed_isolated_action_resumes_recovery_without_an_owner_answer(self):
  rec={'id':'r','status':'waiting_for_tests','pending_action':'a','actions':{'a':{'kind':'tests','result':{'report_uri':'gs://bucket/report'}}}}
  dashboard=Mock();dashboard.call.side_effect=[{'r':rec}, {'status':'queued'}, {}]
  cloud=Mock();cloud.storage_json.return_value={'passed':True}
  dispatch_recoveries(dashboard,cloud,{'recovery':{'enabled':True},'region':'us-central1','jobs':{}})
  self.assertTrue(any(c.kwargs.get('action_id')=='a' and c.args[0]=='recovery_tests_ready' for c in dashboard.call.call_args_list));cloud.execute.assert_not_called()
 def test_probe_fixture_runs_without_account_environment(self):
  with tempfile.TemporaryDirectory() as folder:
   probe={'script':'import os,json; assert "OPENAI_API_KEY" not in os.environ; print(json.load(open("input/context.json"))["recording"]["docket"])','context':{'recording':{'docket':'25-498'}},'artifacts':{}}
   result=run_probe({},probe,folder,Mock())
   self.assertTrue(result['passed']);self.assertIn('25-498',result['output'])
 def test_upstream_restart_is_in_the_tool_schema_and_questions_identify_the_actor(self):
  tools={d['name']:d for d in definitions()}
  self.assertIn('restart_from',tools['repair_retry']['inputSchema']['properties'])
  self.assertIn('actor',tools['repair_ask']['inputSchema']['properties']['options']['items']['required'])

class MixedCaseSpeakerTests(unittest.TestCase):
 def test_mccloud_is_a_separate_speaker_in_both_paragraph_modes(self):
  from scotus_cloud.vendor.parser import parse_scotus_transcript
  text='PROCEEDINGS\nCHIEF JUSTICE ROBERTS: Thank you.\nMR. McCLOUD: May it please the Court.\nJUSTICE KAGAN: A question.\nMR. McCLOUD: My answer.\n(Whereupon, the case was submitted.)'
  for mode in ('layout','legacy'):
   turns=parse_scotus_transcript(text,paragraph_mode=mode)
   self.assertEqual([t['speaker'] for t in turns if isinstance(t['speaker'],str)],['MR. McCLOUD','MR. McCLOUD'])
   self.assertFalse(any('McCLOUD:' in p for t in turns for p in t['paragraphs']))
 def test_mixed_case_appearance_prefix_is_retained_and_displayed_correctly(self):
  from scotus_cloud.prepare import appearances
  people=appearances('APPEARANCES:\nCHRISTOPHER M. McCLOUD, Washington, D.C.; for respondent.\nC O N T E N T S\n')
  self.assertEqual(people[0]['name'],'Christopher M. McCloud');self.assertEqual(people[0]['last_name'],'McCloud')
 def test_split_mixed_case_speaker_label_is_joined(self):
  from scotus_cloud.vendor.parser import fix_split_speaker_names
  self.assertIn('MR. McCLOUD:',fix_split_speaker_names('MR.\nMcCLOUD: My answer.'))
