import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.recovery_control import broker
from scotus_cloud.worker import stage_run
from scotus_cloud.youtube import response_error,postprocess,UploadError
from scotus_cloud.recovery_worker import seed_workspace


class UploadRecoveryTests(unittest.TestCase):
    def context(self):
        return {'recovery':{'stage':'upload','actions':{}},'job':{'stages':{'upload':{'checkpoint':{
            'video_id':'abcdefghijk','session_url':'https://private/session?token=secret','access_token':'secret'}}}}}

    def settings(self):return {'recovery':{'bucket':'bucket','baseline_uri':'gs://private/baseline'}}

    def test_upload_context_retains_video_identity_without_session_or_credentials(self):
        dashboard=Mock();dashboard.call.return_value=self.context();cloud=Mock()
        result=broker(dashboard,cloud,self.settings(),{'recovery':'rid','lease':'lease','tool':'artifact','arguments':{'stage':'upload','field':'upload_state','offset':0}})
        saved=json.loads(result['text']);self.assertEqual(saved['checkpoint'],{'video_id':'abcdefghijk'});self.assertTrue(saved['session_saved'])
        self.assertNotIn('secret',result['text']);self.assertEqual(saved['audit_actions'],[]);cloud.storage_json.assert_not_called();cloud.execute.assert_not_called()

    def test_lost_audit_launch_reply_can_be_reconciled_without_another_execution(self):
        dashboard=Mock();context=self.context();key='a'*64
        context['recovery']['actions']={key:{'kind':'upload_audit','status':'reserved'}};dashboard.call.return_value=context
        cloud=Mock();cloud.storage_json.return_value={'recording':'job','candidates':[]}
        result=broker(dashboard,cloud,self.settings(),{'recovery':'rid','lease':'lease','tool':'poll','arguments':{'action':key}})
        self.assertEqual(result['status'],'complete');cloud.storage_json.assert_called_once_with(f'gs://bucket/recovery/audits/rid/{key}.json',max_bytes=65536);cloud.execute.assert_not_called()

    def test_saved_video_resumes_without_downloading_the_mp4(self):
        job=self.context()['job'];cloud=Mock();lease=Mock()
        job['id']='job';job['stages']['upload']['attempt']=2
        with tempfile.TemporaryDirectory() as folder,patch('scotus_cloud.youtube.upload_video',return_value={'done':True}) as uploader:
            self.assertEqual(stage_run('upload',job,{'bucket':'bucket'},cloud,lease,Path(folder),0),{'done':True})
            self.assertIsNone(uploader.call_args.args[0]);cloud.storage_download.assert_not_called()

    def test_thumbnail_reason_codes_are_kept_but_raw_response_secrets_are_not(self):
        response=Mock(status_code=400);response.json.return_value={'error':{'message':'secret raw message','errors':[{'reason':'invalidImage'},{'reason':'secret with spaces'}]}}
        error=response_error(response,'thumbnail');self.assertEqual(error.category,'worker_failed');self.assertIn('invalidImage',str(error));self.assertIn('400',str(error));self.assertNotIn('secret',str(error))

    def test_thumbnail_uses_set_endpoint_and_saves_structured_failure(self):
        session=Mock();session.post.return_value.status_code=400;session.post.return_value.json.return_value={'error':{'errors':[{'reason':'invalidImage'}]}}
        cloud=Mock();cloud.storage_bytes.return_value=b'jpeg';lease=Mock();checkpoint={'video_id':'abcdefghijk'}
        job={'stages':{'plan':{'result':{'thumbnail_uri':'gs://bucket/thumb','interactions_uri':'gs://bucket/meta'}}}}
        video={'snippet':{'channelId':'owner'}}
        with patch('scotus_cloud.youtube.owned_channel',return_value='owner'),patch('scotus_cloud.youtube.api',return_value={'items':[video]}),self.assertRaises(UploadError):
            postprocess(session,'abcdefghijk',job,{},cloud,lease,checkpoint)
        self.assertEqual(session.post.call_args.args[0],'https://www.googleapis.com/upload/youtube/v3/thumbnails/set')
        self.assertEqual(checkpoint['video_id'],'abcdefghijk');self.assertEqual(checkpoint['last_error']['reasons'],['invalidImage'])

    def test_resumed_postprocessing_reports_actual_public_privacy(self):
        job={'stages':{'plan':{'result':{'interactions_uri':'gs://bucket/meta'}}}}
        cloud=Mock();cloud.storage_json.return_value={'term':2026,'youtube_title':'Title'};lease=Mock()
        video={'snippet':{'channelId':'owner','title':'Title'},'status':{'privacyStatus':'public'}}
        saved={'thumbnail_done':True,'playlist_done':True,'comment_done':True}
        with patch('scotus_cloud.youtube.owned_channel',return_value='owner'),patch('scotus_cloud.youtube.api',return_value={'items':[video]}) as api:
            result=postprocess(Mock(),'abcdefghijk',job,{'playlists':{'2026':'playlist'}},cloud,lease,saved)
        self.assertEqual(result['privacy'],'public')
        self.assertTrue(all(call.args[1]=='GET' for call in api.call_args_list))

    def test_recovery_workspace_has_the_canonical_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            seed_workspace(Path(folder),{'prompts/public-output-policy.md':'Canonical policy'},{'stages':{'upload':{}}},'upload',Mock())
            self.assertEqual((Path(folder)/'POLICY.md').read_text(),'Canonical policy')


if __name__=='__main__':unittest.main()
