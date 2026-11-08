"""Retry prerequisites and reservations, without launching cloud work."""
import unittest
from unittest.mock import Mock
from scotus_cloud.model import STAGES
from scotus_cloud.recovery_control import broker
from scotus_cloud.repair_policy import reserve_estimate

class RetryDependenciesTests(unittest.TestCase):
 def context(self,stage='upload'):
  job={'stages':{s:{'status':'complete'} for s in STAGES}}
  job['stages']['render']['tasks']=[
   {'status':'complete','result':{'video_deleted_at':'today'}},
   {'status':'complete','result':{'video_uri':'healthy'}},
   {'status':'failed'}]
  return {'job':job,'recovery':{'stage':stage,'error':'worker_failed','actions':{}}}
 def retry(self,context,restart):
  dashboard=Mock()
  dashboard.call.side_effect=lambda op,**kw:context if op=='recovery_context' else {'claimed':True}
  cloud=Mock();settings={'workers_enabled':True,'recovery':{'stage_resources':{s:[1,1,10] for s in STAGES}}}
  result=broker(dashboard,cloud,settings,{'recovery':'r','lease':'l','tool':'retry','call_id':'c','arguments':{'restart_from':restart}})
  self.assertFalse(cloud.execute.called)
  calls={c.args[0]:c.kwargs for c in dashboard.call.call_args_list}
  return result,calls
 def test_reassembly_restores_only_removed_or_incomplete_chunks_before_assembly(self):
  result,calls=self.retry(self.context(),'assemble')
  self.assertEqual(result['restart_from'],'render');self.assertTrue(calls['recovery_retry']['restore_render_chunks'])
  self.assertEqual(calls['recovery_action_claim']['reserve_usd'],reserve_estimate(1,1,10,tasks=2))
 def test_explicit_upstream_render_restart_reserves_for_all_render_tasks(self):
  _,calls=self.retry(self.context(),'render')
  self.assertFalse(calls['recovery_retry']['restore_render_chunks'])
  self.assertEqual(calls['recovery_action_claim']['reserve_usd'],reserve_estimate(1,1,10,tasks=3))
 def test_render_retry_preserves_completed_chunks_and_counts_missing_ones(self):
  _,calls=self.retry(self.context('render'),'render')
  self.assertEqual(calls['recovery_action_claim']['reserve_usd'],reserve_estimate(1,1,10,tasks=2))
 def test_upload_retry_reuses_final_video_without_regenerating_deleted_chunks(self):
  result,calls=self.retry(self.context(),'upload')
  self.assertEqual(result['restart_from'],'upload');self.assertFalse(calls['recovery_retry']['restore_render_chunks'])
  self.assertEqual(calls['recovery_action_claim']['reserve_usd'],reserve_estimate(1,1,10))
 def test_reassembly_with_available_chunks_uses_assembly_resources(self):
  context=self.context();context['job']['stages']['render']['tasks'][0]['result']={'video_uri':'available'}
  result,calls=self.retry(context,'assemble')
  self.assertEqual(result['restart_from'],'assemble');self.assertFalse(calls['recovery_retry']['restore_render_chunks'])
  self.assertEqual(calls['recovery_action_claim']['reserve_usd'],reserve_estimate(1,1,10))
 def test_alignment_is_an_upstream_dependency_of_enrichment(self):
  result,calls=self.retry(self.context('enrich'),'align')
  self.assertEqual(result['restart_from'],'align')
 def test_existing_upload_is_not_rewound_to_restore_chunks(self):
  context=self.context();context['job']['stages']['upload']['checkpoint']={'video_id':'existing'}
  with self.assertRaisesRegex(ValueError,'cannot be rewound'):self.retry(context,'assemble')

if __name__=='__main__':unittest.main()
