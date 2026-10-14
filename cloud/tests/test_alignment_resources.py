import unittest
from unittest.mock import Mock,patch
from scotus_cloud.model import alignment_cpus,STAGES
from scotus_cloud.control import dispatch


class AlignmentResourcesTests(unittest.TestCase):
    def job(self,duration):
        stages={s:{'status':'complete' if STAGES.index(s)<2 else 'pending'} for s in STAGES}
        stages['prepare']['result']={'duration_seconds':duration}
        return {'id':'case','status':'running','run_requested':True,'stages':stages}

    def test_inclusive_100_minute_boundary(self):
        for seconds,expected in ((5999.99,4),(6000,8),(6000.01,8),(8000,8),(None,4)):
            self.assertEqual(alignment_cpus(self.job(seconds)),expected)

    def test_existing_prepared_recording_uses_saved_transcript_duration(self):
        job=self.job(None);job['stages']['prepare']['result']['transcript_uri']='gs://bucket/transcript.json'
        cloud=Mock();cloud.storage_json.return_value={'audio':{'duration_seconds':6000}}
        self.assertEqual(alignment_cpus(job,cloud),8)

    def test_dispatch_allocates_matching_job_and_threads(self):
        for duration,worker,threads in ((5999,'align-worker','4'),(6000,'align-long-worker','8')):
            with self.subTest(duration=duration):
                job=self.job(duration);dashboard=Mock();google=Mock()
                def call(op,**data):
                    if op=='snapshot':return {'paused':True,'jobs':{'case':job},'recoveries':{}}
                    if op=='dispatch':return {'job':job,'dispatch_token':'token'}
                    if op=='execution_record':return True
                    raise AssertionError(op)
                dashboard.call.side_effect=call
                with patch('scotus_cloud.notifications.drain_notifications'),patch('scotus_cloud.discovery.discover'),patch('scotus_cloud.recovery_control.dispatch_recoveries',return_value=[]):
                    dispatch(dashboard,google,{'workers_enabled':True,'region':'region','jobs':{'align':'align-worker'},'alignment_long_job':'align-long-worker'})
                self.assertEqual(google.execute.call_args.args[1],worker)
                self.assertEqual(google.execute.call_args.args[2]['SCOTUS_ALIGN_THREADS'],threads)
