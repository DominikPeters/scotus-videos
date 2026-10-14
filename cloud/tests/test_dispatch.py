from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.control import dispatch
from scotus_cloud.model import STAGES


class DispatchTests(unittest.TestCase):
    def run_dispatch(self,jobs,paused=True,photos=False):
        dashboard=Mock();google=Mock();google.operation_status.return_value={'done':False,'failed':False}
        def call(op,**data):
            if op=='snapshot':return {'paused':paused,'jobs':{j['id']:j for j in jobs},'recoveries':[]}
            if op=='dispatch':return {'job':next(j for j in jobs if j['id']==data['job']),'dispatch_token':'test-token'}
            if op=='photo_dispatch':return {'dispatch_token':'photo-token'}
            if op=='execution_record':return True
            self.fail('Unexpected dashboard operation '+op)
        dashboard.call.side_effect=call
        with patch('scotus_cloud.notifications.drain_notifications'),patch('scotus_cloud.discovery.discover'),patch('scotus_cloud.recovery_control.dispatch_recoveries',return_value=[]):
            result=dispatch(dashboard,google,{'workers_enabled':True,'region':'test','jobs':{s:s+'-worker' for s in STAGES},'photo_job':'photos-worker' if photos else None})
        return dashboard,google,result

    def job(self,id='selected',**values):
        return {'id':id,'status':'queued','created_at':'2026-10-05','stages':{s:{'status':'pending'} for s in STAGES},**values}

    def test_paused_queue_launches_nothing_without_explicit_start(self):
        _,google,result=self.run_dispatch([self.job()])
        google.execute.assert_not_called();self.assertEqual(result['launched'],[])

    def test_manual_start_only_dispatches_selected_case(self):
        selected=self.job(run_requested=True)
        _,google,result=self.run_dispatch([self.job('other'),selected])
        self.assertEqual(len(result['launched']),1)
        self.assertEqual(google.execute.call_args.args[2]['SCOTUS_JOB_ID'],'selected')

    def test_manual_start_continues_after_reviews_and_through_all_stages(self):
        for stage in STAGES:
            with self.subTest(stage=stage):
                selected=self.job(run_requested=True,status='running' if stage!='enrich' else 'queued')
                for earlier in STAGES[:STAGES.index(stage)]:selected['stages'][earlier]['status']='complete'
                if stage=='enrich':selected['stages']['align']['status']='complete'
                if stage=='render':selected['stages'][stage]['tasks']=[{'status':'complete'},{'status':'pending'}]
                _,google,result=self.run_dispatch([selected,self.job('other',status='running')])
                self.assertEqual(result['launched'][0]['stage'],stage)
                self.assertEqual(google.execute.call_count,1)
                if stage=='render':self.assertEqual(google.execute.call_args.args[2]['SCOTUS_RENDER_TASKS'],'[1]')

    def test_review_and_cancelled_jobs_do_not_run(self):
        for status in ('needs_review','cancelled','failed'):
            with self.subTest(status=status):
                _,google,_=self.run_dispatch([self.job(status=status,run_requested=True)])
                google.execute.assert_not_called()

    def test_automatic_queue_keeps_one_recording_at_a_time(self):
        _,google,_=self.run_dispatch([self.job('one'),self.job('two')],paused=False)
        self.assertEqual(google.execute.call_count,1)

    def test_photo_hold_allows_alignment_but_blocks_plan(self):
        held=self.job(status='needs_review',run_requested=True)
        held['stages']['prepare']['status']='complete';held['stages']['enrich']['status']='needs_review'
        _,google,result=self.run_dispatch([held,self.job('other')])
        self.assertEqual(result['launched'][0]['stage'],'align');self.assertEqual(google.execute.call_count,1)
        for status in ('starting','running','complete'):
            with self.subTest(align=status):
                held['stages']['align']['status']=status
                _,google,_=self.run_dispatch([held]);google.execute.assert_not_called()

    def test_approval_resumes_enrichment_in_parallel_with_alignment(self):
        job=self.job(status='running',run_requested=True)
        job['stages']['prepare']['status']='complete';job['stages']['align']['status']='running'
        _,google,_=self.run_dispatch([job]);self.assertEqual(google.execute.call_args.args[1],'enrich-worker')
        job['stages']['align']['status']='complete'
        _,google,result=self.run_dispatch([job]);self.assertEqual(result['launched'][0]['stage'],'enrich')

    def test_photo_worker_runs_independently_of_active_alignment(self):
        job=self.job(status='needs_review',run_requested=True)
        job['stages']['prepare']['status']='complete';job['stages']['enrich']['status']='needs_review';job['stages']['align']['status']='running'
        job['photo_requests']={'request':{'id':'request','status':'queued'}}
        _,google,result=self.run_dispatch([job],photos=True)
        self.assertEqual(result['launched'][0]['stage'],'photo_revision')
        self.assertEqual(google.execute.call_args.args[1],'photos-worker')
        self.assertEqual(google.execute.call_args.args[2]['SCOTUS_PHOTO_REQUEST'],'request')

    def test_closed_execution_with_unclaimed_task_is_reconciled(self):
        job=self.job(status='running',run_requested=True)
        operation='projects/test/locations/test/operations/owned'
        job['stages']['render'].update(status='running',cloud_operation=operation)
        dashboard=Mock();google=Mock();google.operation_status.return_value={'done':True,'failed':True}
        def call(op,**data):
            if op=='snapshot':return {'paused':True,'jobs':{'selected':job},'recoveries':[]}
            if op=='execution_closed':job['status']='failed';job['stages']['render']['status']='failed';return True
            self.fail(op)
        dashboard.call.side_effect=call
        with patch('scotus_cloud.notifications.drain_notifications'),patch('scotus_cloud.discovery.discover'),patch('scotus_cloud.recovery_control.dispatch_recoveries',return_value=[]):
            dispatch(dashboard,google,{'workers_enabled':True,'jobs':{}})
        self.assertIn(unittest.mock.call('execution_closed',job='selected',stage='render',operation=operation),dashboard.call.call_args_list)
        google.execute.assert_not_called()

    def test_active_cloud_operation_is_not_failed_or_restarted(self):
        job=self.job(status='running',run_requested=True)
        job['stages']['render'].update(status='running',cloud_operation='owned')
        dashboard,google,_=self.run_dispatch([job])
        google.execute.assert_not_called()
        self.assertFalse(any(call.args[0]=='execution_closed' for call in dashboard.call.call_args_list))

    def test_postprocessing_retry_has_a_short_enforced_timeout(self):
        job=self.job(run_requested=True)
        for earlier in STAGES[:-1]:job['stages'][earlier]['status']='complete'
        job['stages']['upload']['checkpoint']={'video_id':'abcdefghijk'}
        _,google,_=self.run_dispatch([job])
        self.assertEqual(google.execute.call_args.kwargs['timeout_seconds'],300)


if __name__=='__main__':unittest.main()
