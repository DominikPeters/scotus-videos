import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.error import URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.worker import Lease
from scotus_cloud.google import Google


class WorkerClaimTests(unittest.TestCase):
    def test_transient_timeout_reuses_one_claim_identity(self):
        dashboard=Mock();dashboard.call.side_effect=[URLError('timed out'),{'lease':'owned'}]
        lease=Lease(dashboard,'job','render','dispatch',12)
        with patch('scotus_cloud.worker.time.sleep'):
            self.assertEqual(lease.claim(),{'lease':'owned'})
        ids=[call.kwargs['claim_id'] for call in dashboard.call.call_args_list]
        self.assertEqual(len(ids),2);self.assertEqual(ids[0],ids[1]);self.assertEqual(len(ids[0]),32)

    def test_claim_retries_are_bounded_and_permission_errors_are_not_retried(self):
        for error,count in ((URLError('timed out'),3),(RuntimeError('HTTP 403'),1)):
            dashboard=Mock();dashboard.call.side_effect=error
            with patch('scotus_cloud.worker.time.sleep'),self.assertRaises(type(error)):
                Lease(dashboard,'job','render','dispatch',12).claim()
            self.assertEqual(dashboard.call.call_count,count)

    def test_cloud_operation_reader_is_project_scoped(self):
        google=Google.__new__(Google);google.project='project';google.request=Mock(return_value={'done':True,'error':{'code':10}})
        result=google.operation_status('projects/project/locations/us-central1/operations/owned')
        self.assertEqual(result,{'done':True,'failed':True})
        google.request.reset_mock()
        for operation in ('https://example.org','projects/other/locations/us-central1/operations/owned','projects/project/secrets/key'):
            with self.assertRaises(ValueError):google.operation_status(operation)
        google.request.assert_not_called()


if __name__=='__main__':unittest.main()
