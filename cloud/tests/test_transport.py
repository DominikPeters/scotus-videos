import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from urllib.error import URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.remote import Dashboard
from scotus_cloud.google import Google


class TransportTests(unittest.TestCase):
    def test_read_retries_use_fresh_signatures_but_claim_identity_is_stable(self):
        dashboard=Dashboard('https://example.org','key','recovery')
        response=Mock();response.read.return_value=b'{"ok":true,"result":"lease"}'
        manager=Mock();manager.__enter__=Mock(return_value=response);manager.__exit__=Mock(return_value=False)
        with patch('scotus_cloud.remote.urlopen',side_effect=[URLError('timeout'),manager]) as send,patch('scotus_cloud.remote.time.sleep'):
            self.assertEqual(dashboard.call('auth_claim',name='codex'),'lease')
        requests=[call.args[0] for call in send.call_args_list]
        self.assertEqual(json.loads(requests[0].data)['claim_id'],json.loads(requests[1].data)['claim_id'])
        self.assertNotEqual(requests[0].headers['X-scotus-nonce'],requests[1].headers['X-scotus-nonce'])

    def test_mutating_operations_are_not_blindly_replayed(self):
        with patch('scotus_cloud.remote.urlopen',side_effect=URLError('timeout')) as send:
            with self.assertRaisesRegex(RuntimeError,'finish transport failed'):Dashboard('https://example.org','key','render').call('finish')
        self.assertEqual(send.call_count,1)

    def test_checksum_is_verified_during_download_without_reopening_the_file(self):
        data=b'first second';google=Google.__new__(Google);google.session=Mock()
        response=Mock(status_code=200);response.iter_content.return_value=iter([b'first ',b'second'])
        manager=Mock();manager.__enter__=Mock(return_value=response);manager.__exit__=Mock(return_value=False);google.session.get.return_value=manager
        with tempfile.TemporaryDirectory() as folder:
            google.storage_download('gs://bucket/file',Path(folder)/'file',expected_sha256=hashlib.sha256(data).hexdigest())
            self.assertEqual((Path(folder)/'file').read_bytes(),data)


if __name__=='__main__':unittest.main()
