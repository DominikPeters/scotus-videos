import base64,hashlib,json,unittest
from unittest.mock import Mock,patch
from scotus_cloud import asset_publisher

class AssetPublisherTests(unittest.TestCase):
    def test_owner_approved_candidate_authorizes_archive_replacement(self):
        image=b'\xff\xd8\xffapproved';person='advocate_25_1003_william_r_peterson'
        candidate={'origin':'upload','kind':'photo','portrait_uri':'gs://private/new.jpg','sha256':hashlib.sha256(image).hexdigest(),'source_url':'https://law.example/photo.jpg'}
        job={'id':'case','docket':'25-1003','approved_photos':{person:candidate},'review':{'photos':{person:{'name':'William R. Peterson'}}}}
        dashboard=Mock();dashboard.call.side_effect=lambda op,**kw:{'job':job,'lease':'lease'} if op=='asset_publish_claim' else 'auth-lease'
        cloud=Mock();cloud.storage_bytes.return_value=image;cloud.secret.return_value=b'{}'
        cfg={'dashboard_url':'https://example.test','worker_key':'key','project':'project','github_secret':'private-github'}
        with patch.object(asset_publisher,'runtime_settings',return_value=cfg),patch.object(asset_publisher,'Google',return_value=cloud),patch.object(asset_publisher,'Dashboard',return_value=dashboard),patch.object(asset_publisher,'commit_portrait',return_value={'commit':'saved'}) as commit,patch.dict('os.environ',{'CLOUD_RUN_JOB':'assets','SCOTUS_JOB_ID':'case','SCOTUS_ASSET_TOKEN':'dispatch'}):
            asset_publisher.main()
        self.assertTrue(commit.call_args.kwargs['approved_replacement'])
        self.assertEqual(commit.call_args.args[1],person)
    def test_curated_portrait_is_exported_without_github_credentials(self):
        image=b'\xff\xd8\xffapproved';person='advocate_25_459_paul_d_clement'
        job={'id':'case','approved_photos':{person:{'origin':'curated_cache','portrait_uri':'gs://private/portrait.jpg','sha256':hashlib.sha256(image).hexdigest()}}}
        dashboard=Mock();dashboard.call.side_effect=lambda op,**kw: {'job':job,'lease':'lease'} if op=='asset_publish_claim' else True
        cloud=Mock();cloud.storage_bytes.return_value=image
        cfg={'dashboard_url':'https://example.test','worker_key':'key','project':'project'}
        with patch.object(asset_publisher,'runtime_settings') as settings,patch.object(asset_publisher,'Google',return_value=cloud),patch.object(asset_publisher,'Dashboard',return_value=dashboard),patch.dict('os.environ',{'CLOUD_RUN_JOB':'assets','SCOTUS_JOB_ID':'case','SCOTUS_ASSET_TOKEN':'dispatch'}):
            settings.return_value=cfg;asset_publisher.main()
        dashboard.call.assert_any_call('asset_portrait_export',job='case',lease='lease',person=person,image_base64=base64.b64encode(image).decode())
        dashboard.call.assert_any_call('asset_publish_finish',job='case',lease='lease',success=True,results=[])
        self.assertFalse(any(call.args[0]=='auth_claim' for call in dashboard.call.call_args_list));cloud.secret.assert_not_called()

if __name__=='__main__':unittest.main()
