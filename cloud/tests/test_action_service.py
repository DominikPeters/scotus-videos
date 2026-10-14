import io,json,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.action_service import make_app
from scotus_cloud.control import dispatch_video_action
from scotus_cloud.youtube import apply_video_action,UploadError


class ActionServiceTests(unittest.TestCase):
    def test_publish_uses_one_metadata_write_for_the_saved_id(self):
        job={'stages':{'upload':{'result':{'video_id':'saved','postprocessing_complete':True}}}}
        with patch('scotus_cloud.youtube.api') as api:
            apply_video_action(Mock(),job,{'kind':'publish','video_id':'saved'}, {})
        self.assertEqual(api.call_count,1);self.assertEqual(api.call_args.args[1:3],('PUT','videos'))
        self.assertEqual(api.call_args.kwargs['body']['status']['privacyStatus'],'public')
        with patch('scotus_cloud.youtube.api') as api,self.assertRaises(UploadError):
            apply_video_action(Mock(),job,{'kind':'publish','video_id':'other'}, {})
        api.assert_not_called()

    def test_dispatch_uses_private_service_instead_of_job_start(self):
        dashboard=Mock();dashboard.call.return_value={'id':'action','dispatch_token':'private'};google=Mock();google.invoke_action_service.return_value={'complete':True}
        result=dispatch_video_action(dashboard,google,{'youtube_action_service':'https://private.run.app'},'job')
        self.assertTrue(result['complete']);google.execute.assert_not_called()

    def test_service_requires_a_claim_and_records_completion(self):
        dashboard=Mock();dashboard.call.side_effect=[{'job':{'id':'job'},'action':{'id':'action','lease':'lease'}},True]
        body=json.dumps({'job':'job','action':'action','token':'private'}).encode();statuses=[]
        with patch('scotus_cloud.action_service.Dashboard',return_value=dashboard),patch('scotus_cloud.action_service.video_action') as action:
            app=make_app({'dashboard_url':'https://site','worker_key':'key','project':'project'},lambda project:Mock())
            reply=app({'REQUEST_METHOD':'POST','PATH_INFO':'/action','CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body)},lambda status,headers:statuses.append(status))
        self.assertEqual(statuses,['200 OK']);self.assertTrue(json.loads(reply[0])['complete']);action.assert_called_once()
        self.assertEqual(dashboard.call.call_args.kwargs['success'],True)


if __name__=='__main__':unittest.main()
