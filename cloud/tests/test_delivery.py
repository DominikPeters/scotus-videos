import os,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.worker import run_sequence
class DeliveryTests(unittest.TestCase):
    def test_same_local_movie_crosses_checkpointed_phase_boundary(self):
        job={'id':'j','stages':{'assemble':{},'upload':{}}};first=Mock();first.data={};second=Mock();second.data={};first.call.return_value={'next':{'job':job,'dispatch_token':'next'}};second.claim.return_value={'lease':'upload-lease','job':job};second.call.return_value=True
        seen=[]
        def stage(name,job,settings,cloud,lease,folder,task,local_video=None,local_transcript=None):
            seen.append(name)
            if name=='assemble':(folder/'video.mp4').write_bytes(b'movie');self.assertIsNone(local_video)
            else:self.assertEqual(local_video.read_bytes(),b'movie')
            return {'saved':name}
        with patch.dict(os.environ,{'SCOTUS_CONTINUE_UPLOAD':'1'},clear=True),patch('scotus_cloud.worker.Dashboard') as dashboard,patch('scotus_cloud.worker.Lease',return_value=second),patch('scotus_cloud.worker.stage_run',side_effect=stage):
            run_sequence('assemble',{'job':job,'lease':'first'},{'dashboard_url':'https://example.org','upload_worker_key':'upload-key'},Mock(),first)
        self.assertEqual(seen,['assemble','upload']);self.assertTrue(first.call.call_args.kwargs['continue_upload']);dashboard.assert_called_once_with('https://example.org','upload-key','upload')
    def test_preparation_continues_enrichment_with_local_transcript(self):
        job={'id':'j','stages':{'prepare':{},'enrich':{}}};first=Mock();first.data={};second=Mock();second.data={}
        first.call.return_value={'next':{'stage':'enrich','job':job,'dispatch_token':'next'}};second.claim.return_value={'lease':'owned','job':job};second.call.return_value=True;seen=[]
        def stage(name,job,settings,cloud,lease,folder,task,local_video=None,local_transcript=None):
            seen.append(name)
            if name=='prepare':(folder/'transcript.json').write_text('prepared')
            else:
                self.assertEqual(local_transcript.read_text(),'prepared');self.assertEqual(os.environ['SCOTUS_PRIVATE_CODEX_WORKER'],'1')
            return {}
        with patch.dict(os.environ,{'SCOTUS_CONTINUE_ENRICH':'1'},clear=True),patch('scotus_cloud.worker.Dashboard') as dashboard,patch('scotus_cloud.worker.Lease',return_value=second),patch('scotus_cloud.worker.stage_run',side_effect=stage):
            run_sequence('prepare',{'lease':'owned','job':job},{'dashboard_url':'https://example.org','enrich_worker_key':'key'},Mock(),first)
        self.assertEqual(seen,['prepare','enrich']);self.assertTrue(first.call.call_args.kwargs['continue_enrich']);dashboard.assert_called_once_with('https://example.org','key','enrich')

    def test_standalone_or_repaired_assembly_does_not_chain(self):
        for env in ({},{'SCOTUS_CONTINUE_UPLOAD':'1','SCOTUS_WORKFLOW_RELEASE_URI':'gs://release'}):
            lease=Mock();lease.data={};lease.call.return_value=True
            with patch.dict(os.environ,env,clear=True),patch('scotus_cloud.worker.stage_run',return_value={}),patch('scotus_cloud.worker.Lease') as following:
                run_sequence('assemble',{'lease':'owned','job':{'id':'j'}},{'upload_worker_key':'key'},Mock(),lease)
            following.assert_not_called();self.assertNotIn('continue_upload',lease.call.call_args.kwargs)
