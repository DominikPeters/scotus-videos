import copy,sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.repair_policy import validate_changes
from scotus_cloud.recovery_control import current_release,broker
from scotus_cloud.model import digest_json
from scotus_cloud.recovery_worker import saved_candidate

class RepairBaselineTests(unittest.TestCase):
 def test_resumed_conversation_cannot_restore_an_old_patch_over_new_source(self):
  baseline={'scotus_cloud/alignment.py':'x=3'};edits={'scotus_cloud/alignment.py':'x=2'}
  self.assertEqual(saved_candidate({'baseline_sha256':'a'*64,'changed':edits},baseline),{})
  self.assertEqual(saved_candidate({'changed':edits},baseline),{})
  self.assertEqual(saved_candidate({'baseline_sha256':digest_json(baseline),'changed':edits},baseline),edits)
 def test_prompt_only_deployment_can_safely_rebase_an_unchanged_code_file(self):
  old={'scotus_cloud/alignment.py':'x=1','prompts/photos.md':'old prompt'}
  release=validate_changes(old,{'scotus_cloud/alignment.py':'x=2'})
  current={**old,'prompts/photos.md':'new prompt'};cloud=Mock();cloud.storage_json.return_value=old
  rebased=current_release(current,release,cloud,{'bucket':'private'})
  self.assertEqual(rebased['baseline_sha256'],digest_json(current));self.assertEqual(rebased['files'],release['files'])
 def test_updated_workflow_code_cannot_be_overwritten_by_an_old_patch(self):
  old={'scotus_cloud/alignment.py':'x=1'};release=validate_changes(old,{'scotus_cloud/alignment.py':'x=2'})
  cloud=Mock();cloud.storage_json.return_value=old
  self.assertIsNone(current_release({'scotus_cloud/alignment.py':'x=3'},release,cloud,{'bucket':'private'}))
 def test_source_change_is_an_explicit_result_before_any_launch_or_reservation(self):
  old={'scotus_cloud/alignment.py':'x=1'};release=validate_changes(old,{'scotus_cloud/alignment.py':'x=2'})
  dashboard=Mock();dashboard.call.return_value={'recovery':{'stage':'align'},'job':{}}
  cloud=Mock();cloud.storage_json.side_effect=[{'scotus_cloud/alignment.py':'x=3'},release,old]
  settings={'recovery':{'bucket':'private','baseline_uri':'gs://private/current'}}
  result=broker(dashboard,cloud,settings,{'recovery':'r','lease':'l','tool':'tests','arguments':{'release_uri':'gs://private/recovery/workspaces/r/candidate.json'},'call_id':'call'})
  self.assertEqual(result['status'],'source_changed');cloud.execute.assert_not_called();self.assertEqual(dashboard.call.call_count,1)
