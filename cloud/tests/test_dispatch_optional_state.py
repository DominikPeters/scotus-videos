"""Optional integration state must not stop unrelated video dispatch."""
import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.control import _dispatch_work

class DispatchOptionalStateTests(unittest.TestCase):
    def test_null_spotify_does_not_block_video_dispatch(self):
        stages={name:{'status':'complete'} for name in ('prepare','enrich','align','plan','render','assemble','upload')}
        stages['enrich']={'status':'pending'}
        job={'id':'case','status':'queued','run_requested':True,'stages':stages,'spotify':None}
        snapshot={'jobs':{'case':job},'paused':False}
        dashboard=Mock()
        def call(op,**kwargs):
            if op=='snapshot':return snapshot
            if op=='launch_prepare':return {'id':'run-1','claimed':True}
            if op=='dispatch':return {'job':job,'dispatch_token':'test-token'}
            return None
        dashboard.call.side_effect=call
        google=Mock();google.execute.return_value='owned-operation'
        settings={'project':'test','region':'us-central1','workers_enabled':True,'spotify':{'enabled':True},'jobs':{'enrich':'enrich-job'}}
        with patch('scotus_cloud.recovery_control.dispatch_recoveries',return_value=[]),patch('scotus_cloud.discovery.discover'),patch('scotus_cloud.podcast.publish_alignments'),patch('scotus_cloud.chunk_cleanup.cleanup_completed_chunks'):
            result=_dispatch_work(dashboard,google,settings)
        self.assertEqual(result['launched'][0]['stage'],'enrich')
        google.execute.assert_called_once()
        google.invoke_action_service.assert_not_called()

if __name__=='__main__':unittest.main()
