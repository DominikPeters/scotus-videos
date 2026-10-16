import unittest
from scotus_cloud.tiktok import browser_mode
from scotus_cloud.clip_control import dispatch_clip
from unittest.mock import Mock


class TikTokTests(unittest.TestCase):
    def test_checkpoint_acknowledgements_and_clean_shutdown(self):
        import json, os, shutil, subprocess
        from pathlib import Path
        if not shutil.which('node'): self.skipTest('Node is not installed')
        module = str(Path(__file__).resolve().parents[1]/'render'/'tiktok-draft.cjs')
        code = "const {checkpoint,closeCheckpointChannel}=require(process.argv[1]);(async()=>{await checkpoint({draft_pending:true});await checkpoint({saved:true});closeCheckpointChannel()})()"
        process = subprocess.Popen(['node', '-e', code, module], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                   env=dict(os.environ, SCOTUS_TIKTOK_CHECKPOINTS='1'))
        try:
            self.assertEqual(json.loads(process.stdout.readline()), {'checkpoint': {'draft_pending': True}})
            self.assertIsNone(process.poll())
            process.stdin.write('ok\n'); process.stdin.flush()
            self.assertEqual(json.loads(process.stdout.readline()), {'checkpoint': {'saved': True}})
            process.stdin.write('ok\n'); process.stdin.flush()
            self.assertEqual(process.wait(timeout=3), 0)
        finally:
            if process.poll() is None: process.kill(); process.wait()
            process.stdin.close(); process.stdout.close()

    def test_deploy_preserves_config_and_rejects_gcloud_wrapper(self):
        import importlib.util, json
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('deploy_tiktok', Path(__file__).resolve().parents[1]/'infra'/'deploy_tiktok.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        original = {'dashboard_url': 'https://example.com', 'dispatcher_key': 'fixture', 'control_key': 'fixture', 'secrets': {'youtube': 'existing'}}
        self.assertEqual(module.controller_configuration(json.dumps(original)), original | {'tiktok_job': 'scotus-video-tiktok'})
        with self.assertRaises(ValueError): module.controller_configuration('{"name":"version","payload":{"data":"encoded"}}')

    def test_uncertain_publish_is_read_only_even_when_draft_requested(self):
        self.assertEqual(browser_mode('tiktok_draft', {'publish_pending': True}), 'reconcile_publish')
        self.assertEqual(browser_mode('tiktok_publish', {'publish_pending': True}), 'reconcile_publish')
        self.assertEqual(browser_mode('tiktok_publish', {'published': True}), 'reconcile_publish')

    def test_uncertain_draft_is_reconciled_before_publication(self):
        self.assertEqual(browser_mode('tiktok_publish', {'draft_pending': True}), 'reconcile_draft')

    def test_publish_requires_explicit_mode(self):
        self.assertEqual(browser_mode('tiktok_draft', {}), 'draft')
        self.assertEqual(browser_mode('tiktok_publish', {}), 'publish')

    def test_tiktok_uses_separate_browser_worker(self):
        dashboard = Mock()
        dashboard.call.side_effect = [{'clip': {'status': 'tiktok_publish_queued'}}, {'token': 'token'}, True]
        google = Mock()
        dispatch_clip(dashboard, google, {'clip_job': 'clips', 'tiktok_job': 'tiktok', 'region': 'us-central1'}, 'recording', 'clip')
        self.assertEqual(google.execute.call_args.args[:2], ('us-central1', 'tiktok'))

    def test_missing_tiktok_worker_does_not_consume_dispatch(self):
        dashboard = Mock(); dashboard.call.return_value = {'clip': {'status': 'tiktok_draft_queued'}}
        with self.assertRaisesRegex(ValueError, 'not configured'):
            dispatch_clip(dashboard, Mock(), {'clip_job': 'clips'}, 'recording', 'clip')
        dashboard.call.assert_called_once_with('clip_context', job='recording', clip='clip')
