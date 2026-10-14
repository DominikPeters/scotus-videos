import io,json,sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.control import make_app
from scotus_cloud.remote import signature,DashboardTransportError
from scotus_cloud.worker import Lease

class DashboardReadsTests(unittest.TestCase):
    def request(self,data):
        body=json.dumps({'op':'asset_data','data':data}).encode();timestamp=str(int(time.time()));nonce='a'*32
        return {'REQUEST_METHOD':'POST','PATH_INFO':'/v1/request','CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),
          'HTTP_X_SCOTUS_TIME':timestamp,'HTTP_X_SCOTUS_NONCE':nonce,'HTTP_X_SCOTUS_SIGNATURE':signature('key',timestamp,nonce,'POST','/v1/request',body)}
    def test_selected_private_preview_has_no_php_callback(self):
        google=Mock();google.storage_bytes.return_value=b'image'
        settings={'dashboard_url':'https://example.org','control_key':'key','dispatcher_key':'key','project':'p','bucket':'b'}
        app=make_app(settings,lambda _:google);status=[]
        with patch('scotus_cloud.control.Dashboard.call') as callback:
            response=json.loads(b''.join(app(self.request({'uri':'gs://b/reviews/j/person/id/preview.jpg','kind':'photo'}),lambda s,h:status.append(s))))
            callback.assert_not_called()
        self.assertEqual(status,['200 OK']);self.assertEqual(response['result']['data'],'aW1hZ2U=')
        google.storage_bytes.assert_called_once_with('gs://b/reviews/j/person/id/preview.jpg',max_bytes=8388608)
    def test_preview_cannot_access_another_bucket(self):
        google=Mock();app=make_app({'dashboard_url':'https://example.org','control_key':'key','dispatcher_key':'key','project':'p','bucket':'b'},lambda _:google)
        status=[]
        with patch('scotus_cloud.control.Dashboard.call'):
            list(app(self.request({'uri':'gs://private/secrets','kind':'photo'}),lambda s,h:status.append(s)))
        self.assertEqual(status,['400 Bad Request']);google.storage_bytes.assert_not_called()
    def test_temporary_heartbeat_outage_stays_within_confirmed_lease(self):
        lease=Lease(Mock(),'job','align','token',0);lease.last_heartbeat=100;lease.transport_error=DashboardTransportError('timeout')
        with patch('scotus_cloud.worker.time.monotonic',return_value=249):lease.check()
        with patch('scotus_cloud.worker.time.monotonic',return_value=250),self.assertRaisesRegex(RuntimeError,'renewal'):lease.check()
        lease.error=RuntimeError('Cancelled')
        with patch('scotus_cloud.worker.time.monotonic',return_value=101),self.assertRaisesRegex(RuntimeError,'cancelled'):lease.check()
    def test_heartbeat_can_recover_without_losing_work(self):
        lease=Lease(Mock(),'job','align','token',0)
        lease.stopped=Mock();lease.stopped.wait.side_effect=[False,False,True]
        lease.dashboard.call.side_effect=[DashboardTransportError('timeout'),{'cancelled':False}]
        lease.run();self.assertIsNone(lease.error);self.assertIsNone(lease.transport_error);lease.check()
