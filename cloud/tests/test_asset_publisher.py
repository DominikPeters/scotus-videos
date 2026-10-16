import base64,hashlib,json,unittest
from unittest.mock import Mock,patch
from scotus_cloud import asset_publisher

class AssetPublisherTests(unittest.TestCase):
    def test_curated_portrait_is_exported_without_github_credentials(self):
        image=b'\xff\xd8\xffapproved';person='advocate_25_459_paul_d_clement'
        job={'id':'case','approved_photos':{person:{'origin':'curated_cache','portrait_uri':'gs://private/portrait.jpg','sha256':hashlib.sha256(image).hexdigest()}}}
        dashboard=Mock();dashboard.call.side_effect=lambda op,**kw: {'job':job,'lease':'lease'} if op=='asset_publish_claim' else True
        cloud=Mock();cloud.storage_bytes.return_value=image
        cfg={'dashboard_url':'https://example.test','worker_key':'key','project':'project'}
        with patch.object(asset_publisher,'Path') as path,patch.object(asset_publisher,'Google',return_value=cloud),patch.object(asset_publisher,'Dashboard',return_value=dashboard),patch.dict('os.environ',{'CLOUD_RUN_JOB':'assets','SCOTUS_JOB_ID':'case','SCOTUS_ASSET_TOKEN':'dispatch'}):
            path.return_value.read_text.return_value=json.dumps(cfg);asset_publisher.main()
        dashboard.call.assert_any_call('asset_portrait_export',job='case',lease='lease',person=person,image_base64=base64.b64encode(image).decode())
        dashboard.call.assert_any_call('asset_publish_finish',job='case',lease='lease',success=True,results=[])
        self.assertFalse(any(call.args[0]=='auth_claim' for call in dashboard.call.call_args_list));cloud.secret.assert_not_called()

if __name__=='__main__':unittest.main()
