import json,sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.spotify import Spotify,SpotifyError,validate_credentials
from scotus_cloud.spotify_service import reconcile
from scotus_cloud.spotify_worker import transfer

SHOW='a'*22;EP='b'*22
class SpotifyTests(unittest.TestCase):
    def test_refresh_rotates_token_and_removes_cookies(self):
        google=Mock();google.secret.return_value=json.dumps({'refresh_token':'old','sp_dc':'private','sp_key':'private'}).encode();google.add_secret_version.return_value='version'
        dashboard=Mock();dashboard.call.return_value='lease';session=Mock();session.post.return_value.ok=True;session.post.return_value.json.return_value={'access_token':'new','refresh_token':'renewed','expires_in':3600}
        client=Spotify(google,dashboard,'secret',SHOW,session);self.assertEqual(client.authenticate(),'new')
        saved=json.loads(google.add_secret_version.call_args.args[1]);self.assertEqual(saved['refresh_token'],'renewed');self.assertNotIn('sp_dc',saved)
        google.retire_secret_versions.assert_called_once_with('secret','version');session.get.assert_not_called()
    def test_episode_matching_rejects_wrong_duration_and_ambiguity(self):
        client=Spotify(Mock(),Mock(),'secret',SHOW);client.request=Mock(return_value={'episodes':[{'id':EP,'name':'[25-735] case','releaseDate':'2026-10-05'}]});client.metadata=Mock(return_value={'name':'[25-735] case','duration':700000})
        job={'docket':'25-735','argument_date':'2026-10-05','duration_seconds':4000};self.assertIsNone(client.find_episode(job))
        client.metadata.return_value['duration']=4000000;self.assertIsNotNone(client.find_episode(job))
        client.request.return_value['episodes']*=2
        with self.assertRaises(SpotifyError):client.find_episode(job)
    def context(self,status='queued'):
        return {'id':'job','docket':'25-735','duration_seconds':4000,'spotify':{'status':status,'generation':'generation','manual':True,'upload_id':'saved','episode_id':EP}}
    def test_uploaded_waits_for_owner_publication(self):
        dashboard=Mock();dashboard.call.return_value=self.context('uploaded');client=Mock();client.upload_status.return_value={'status':'UPLOADED','spotifyEpisodeId':EP}
        reconcile('job',{},Mock(),dashboard,client);client.publish.assert_not_called()
    def test_existing_upload_is_recovered_without_worker(self):
        dashboard=Mock();dashboard.call.return_value=self.context();client=Mock();client.metadata.return_value={'id':EP,'name':'[25-735] case','duration':4000000};client.upload_status.return_value={'status':'UPLOADED','spotifyEpisodeId':EP};google=Mock()
        self.assertEqual(reconcile('job',{},google,dashboard,client)['status'],'uploaded');google.execute.assert_not_called();client.publish.assert_not_called()
    def test_missing_episode_does_not_launch_worker(self):
        dashboard=Mock();ctx=self.context();ctx['spotify'].pop('episode_id');ctx['spotify'].pop('upload_id');dashboard.call.return_value=ctx;client=Mock();client.find_episode.return_value=None;google=Mock()
        self.assertEqual(reconcile('job',{},google,dashboard,client)['status'],'waiting_episode');google.execute.assert_not_called()
    def test_stream_sends_original_bytes_and_checkpoints_first(self):
        google=Mock();google.project='p';google.request.return_value={'size':'6','generation':'123'}
        response=Mock(status_code=200);response.iter_content.return_value=[b'abc',b'def'];google.session.get.return_value=MagicMock();google.session.get.return_value.__enter__.return_value=response
        client=Mock();client.metadata.return_value={'hasVideo':False};client.reserve_upload.return_value='saved';client.headers.return_value={'Authorization':'private'}
        context={'id':'job','spotify':{'episode_id':EP},'video':{'video_uri':'gs://p-scotus-video-media/scratch/job/assemble/attempt/video.mp4'}}
        connection=Mock();connection.getresponse.return_value.status=200;connection.getresponse.return_value.read.return_value=b'{"uploadId":"saved","status":"UPLOADED"}'
        events=[]
        with patch('scotus_cloud.spotify_worker.http.client.HTTPSConnection',return_value=connection):
            self.assertEqual(transfer(context,client,google,lambda v:events.append('checkpoint') or True,lambda p:True),'saved')
        self.assertEqual(events,['checkpoint']);sent=b''.join(c.args[0] for c in connection.send.call_args_list);self.assertIn(b'\r\n\r\nabcdef\r\n',sent)
        self.assertEqual(google.session.get.call_args.kwargs['params']['generation'],'123')
        self.assertNotIn('Authorization',google.session.get.call_args.kwargs['headers'])
    def test_credentials_accept_only_private_known_fields(self):
        self.assertEqual(validate_credentials({'refresh_token':'token','url':'https://evil'}),{'refresh_token':'token'})
        with self.assertRaises(ValueError):validate_credentials({'access_token':'only'})

if __name__=='__main__':unittest.main()
