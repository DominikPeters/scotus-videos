import tempfile,unittest
from scotus_cloud.recovery_test_worker import test_release
from scotus_cloud.repair_policy import validate_changes

class RecoverySupportTests(unittest.TestCase):
    def test_isolated_tests_receive_immutable_deployment_support(self):
        baseline={'tests/test_support.py':"import unittest\nfrom pathlib import Path\nfrom infra.registry_cleanup import execution_active\nclass Check(unittest.TestCase):\n def test_support(self):\n  self.assertTrue((Path(__file__).resolve().parents[1]/'infra/deploy_instagram_clips.py').is_file())\n  self.assertFalse(execution_active({'status':{'completionTime':'done'}}))\n"}
        release=validate_changes(baseline,{'scotus_cloud/prepare.py':'# unchanged trusted workflow probe\n'})
        with tempfile.TemporaryDirectory() as folder:result=test_release(baseline,release,folder)
        self.assertTrue(result['passed'],result)
