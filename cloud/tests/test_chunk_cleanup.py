import sys,unittest,copy
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.chunk_cleanup import cleanup_completed_chunks

def fixture():
    prefix='gs://bucket/scratch/job/'
    return {'id':'job','stages':{'assemble':{'status':'complete','result':{'video_uri':prefix+'assemble/attempt-1/'+'a'*32+'/video.mp4','sha256':'a'*64,'verification':'mp4_header','frames':20}},'plan':{'result':{'frames':20}},'render':{'status':'complete','tasks':[{'result':{'video_uri':prefix+'render/attempt-1/'+'b'*32+'/chunk.mp4','preview_uri':'kept-preview','frames':20}}]}}}
class CleanupTests(unittest.TestCase):
    def setup_cloud(self,job):
        dashboard=Mock();dashboard.call.side_effect=lambda op,**kw:({'job':job,'cleanup':{'lease':'owned','final_uri':job['stages']['assemble']['result']['video_uri'],'deleted_indices':[]}} if op=='chunk_cleanup_claim' else True)
        cloud=Mock();cloud.session.get.return_value=Mock(status_code=200,json=lambda:{'size':'100','generation':'1'});cloud.session.delete.return_value=Mock(status_code=204)
        return dashboard,cloud
    def run_cleanup(self,job,dashboard,cloud):cleanup_completed_chunks(dashboard,cloud,{'bucket':'bucket','chunk_cleanup_enabled':True},{'job':job})
    def test_only_exact_receipt_chunk_deleted_after_final_exists(self):
        j=fixture();d,c=self.setup_cloud(j);self.run_cleanup(j,d,c);url=c.session.delete.call_args.args[0];self.assertIn('render%2Fattempt-1',url);self.assertTrue(url.endswith('chunk.mp4'));self.assertEqual(d.call.call_args.kwargs['indices'],[0])
    def test_missing_final_or_invalid_scope_keeps_chunks(self):
        for mutate in ('missing','scope','unverified'):
            j=fixture();d,c=self.setup_cloud(j)
            if mutate=='missing':c.session.get.return_value.status_code=404
            elif mutate=='scope':j['stages']['render']['tasks'][0]['result']['video_uri']='gs://bucket/scratch/other/render/attempt-1/'+'b'*32+'/chunk.mp4'
            else:j['stages']['assemble']['result']['verification']=None
            self.run_cleanup(j,d,c);c.session.delete.assert_not_called();self.assertTrue(d.call.call_args.kwargs['error'])
    def test_already_deleted_chunk_is_idempotent(self):
        j=fixture();d,c=self.setup_cloud(j);c.session.delete.return_value.status_code=404;self.run_cleanup(j,d,c);self.assertIsNone(d.call.call_args.kwargs['error']);self.assertEqual(d.call.call_args.kwargs['indices'],[0])
    def test_legacy_successful_upload_is_validated_without_new_verification_field(self):
        j=fixture();j['stages']['assemble']['result']['verification']=None;j['stages']['upload']={'status':'complete','result':{'postprocessing_complete':True}}
        d,c=self.setup_cloud(j);self.run_cleanup(j,d,c);c.session.delete.assert_called_once();self.assertIsNone(d.call.call_args.kwargs['error'])
    def test_incomplete_assembly_never_claims_cleanup(self):
        j=fixture();j['stages']['assemble']['status']='running';d,c=self.setup_cloud(j);self.run_cleanup(j,d,c);d.call.assert_not_called();c.session.delete.assert_not_called()
