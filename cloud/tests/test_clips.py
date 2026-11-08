import base64,unittest
from unittest.mock import Mock,patch
from scotus_cloud.clip_control import dispatch_clip,download_url
class ClipControlTests(unittest.TestCase):
 def test_dispatch_is_claimed_before_execution(self):
  d=Mock();d.call.side_effect=[{'clip':{'status':'render_queued'}},{'token':'token'},True];g=Mock();g.execute.return_value='operation'
  dispatch_clip(d,g,{'clip_job':'clips','region':'us-central1'},'recording','clip')
  g.execute.assert_called_once_with('us-central1','clips',{'SCOTUS_JOB_ID':'recording','SCOTUS_CLIP_ID':'clip','SCOTUS_CLIP_TOKEN':'token'})
 def test_live_job_is_not_launched_twice(self):
  d=Mock();d.call.return_value={'clip':{'status':'rendering','operation':'op'}};g=Mock();g.operation_status.return_value={'done':False}
  dispatch_clip(d,g,{'clip_job':'clips'},'recording','clip');g.execute.assert_not_called()
 def test_download_is_bound_to_selected_clip(self):
  d=Mock();d.call.return_value={'clip':{'result':{'video_uri':'gs://bucket/clips/recording/clip/version/video.mp4'}}};g=Mock();g.request.return_value={'signedBlob':base64.b64encode(b'signature').decode()}
  result=download_url(d,g,{'bucket':'bucket','clip_signer':'signer@example.com'},'recording','clip')
  self.assertIn('/bucket/clips/recording/clip/version/video.mp4?',result['url']);self.assertIn('X-Goog-Expires=900',result['url']);self.assertNotIn('access_token',result['url'])
  d.call.return_value={'clip':{'result':{'video_uri':'gs://bucket/private/credentials.json'}}}
  with self.assertRaises(ValueError):download_url(d,g,{'bucket':'bucket'},'recording','clip')
class ClipUploadTests(unittest.TestCase):
 def test_expired_credentials_explain_reconnect_without_creating_upload(self):
  from google.auth.exceptions import RefreshError
  from scotus_cloud.clip_worker import upload
  credentials=Mock();credentials.to_json.return_value='{}';session=Mock();cloud=Mock();cloud.secret.return_value=b'{}';lease=Mock();lease.dashboard.call.return_value='auth-token'
  with patch('google.oauth2.credentials.Credentials.from_authorized_user_info',return_value=credentials),patch('google.auth.transport.requests.AuthorizedSession',return_value=session),patch('scotus_cloud.youtube.owned_channel',side_effect=RefreshError('private provider detail')):
   with self.assertRaisesRegex(ValueError,'Reconnect YouTube in Settings') as error:
    upload(None,{}, {}, {'youtube_secret':'secret'},cloud,lease)
  self.assertNotIn('private provider detail',str(error.exception))
  session.post.assert_not_called();lease.call.assert_not_called();cloud.add_secret_version.assert_not_called()
  self.assertIsNone(lease.auth)
  lease.dashboard.call.assert_any_call('auth_release',name='youtube',token='auth-token')
 def test_upload_is_unlisted_and_checkpoints_identity(self):
  import tempfile
  from pathlib import Path
  from scotus_cloud.clip_worker import upload
  credentials=Mock();credentials.to_json.return_value='{}';session=Mock();session.post.return_value=Mock(status_code=200,headers={'Location':'https://www.googleapis.com/upload/session'})
  cloud=Mock();cloud.secret.return_value=b'{}';lease=Mock();lease.dashboard.call.return_value='auth-token'
  with tempfile.TemporaryDirectory() as temp,patch('google.oauth2.credentials.Credentials.from_authorized_user_info',return_value=credentials),patch('google.auth.transport.requests.AuthorizedSession',return_value=session),patch('scotus_cloud.youtube.owned_channel',return_value='channel'),patch('scotus_cloud.youtube.api',return_value={'items':[{'snippet':{'channelId':'channel'},'status':{'privacyStatus':'unlisted'}}]}),patch('scotus_cloud.youtube_transfer.transfer',return_value={'id':'video'}):
   path=Path(temp)/'clip.mp4';path.write_bytes(b'fixture')
   result=upload(path,{'case_name':'Case','docket':'25-459','stages':{}},{'title':'Clip','start':30,'end':40},{'youtube_secret':'secret'},cloud,lease)
  self.assertEqual(session.post.call_args.kwargs['json']['status']['privacyStatus'],'unlisted')
  self.assertEqual(result['video_id'],'video')
  checkpoints=[c.kwargs['checkpoint'] for c in lease.call.call_args_list if c.args[0]=='checkpoint']
  self.assertEqual(checkpoints,[{'creation_pending':True},{'session_url':'https://www.googleapis.com/upload/session'},{'video_id':'video'}])
 def test_uncertain_creation_cannot_create_another_video(self):
  from scotus_cloud.clip_worker import upload
  credentials=Mock();credentials.to_json.return_value='{}';session=Mock();cloud=Mock();cloud.secret.return_value=b'{}';lease=Mock()
  with patch('google.oauth2.credentials.Credentials.from_authorized_user_info',return_value=credentials),patch('google.auth.transport.requests.AuthorizedSession',return_value=session),patch('scotus_cloud.youtube.owned_channel',return_value='channel'):
   with self.assertRaisesRegex(ValueError,'unconfirmed'):
    upload(None,{}, {'upload':{'creation_pending':True}}, {'youtube_secret':'secret'},cloud,lease)
  session.post.assert_not_called()

if __name__=='__main__':unittest.main()

class InstagramClipTests(unittest.TestCase):
 def test_dispatch_uses_instagram_job(self):
  d=Mock();d.call.side_effect=[{'clip':{'status':'instagram_publish_queued'}},{'token':'token'},True];g=Mock();g.execute.return_value='operation'
  dispatch_clip(d,g,{'clip_job':'clips','instagram_clip_job':'instagram','region':'us-central1'},'recording','clip')
  self.assertEqual(g.execute.call_args.args[1],'instagram')
 def test_instagram_publishes_and_checkpoints_media(self):
  from scotus_cloud.instagram_clip import publish
  state={};order=[]
  def checkpoint(**values):state.update(values);order.append(values)
  replies=[{'id':'container'},{'status_code':'FINISHED'},{'id':'media'},{'id':'media','permalink':'https://www.instagram.com/reel/example/'}]
  with patch('scotus_cloud.instagram_clip.api',side_effect=replies) as api:
   result=publish(None,{'access_token':'private','user_id':'account'},state,checkpoint,'caption','private-url',lambda:None)
  self.assertTrue(result['published']);self.assertEqual(result['media_id'],'media')
  self.assertEqual(order,[{'creation_pending':True},{'container_id':'container','creation_pending':False},{'publish_pending':True},{'media_id':'media','publish_pending':False,'published':True}])
 def test_uncertain_instagram_posts_cannot_duplicate(self):
  from scotus_cloud.instagram_clip import publish
  credential={'access_token':'private','user_id':'account'}
  with patch('scotus_cloud.instagram_clip.api') as api:
   with self.assertRaisesRegex(ValueError,'creation is unconfirmed'):
    publish(None,credential,{'creation_pending':True},Mock(),'caption',None,lambda:None)
   api.assert_not_called()
  with patch('scotus_cloud.instagram_clip.api',return_value={'status_code':'FINISHED'}) as api:
   with self.assertRaisesRegex(ValueError,'publication is unconfirmed'):
    publish(None,credential,{'container_id':'existing','publish_pending':True},Mock(),'caption',None,lambda:None)
   self.assertTrue(all(call.args[2]=='GET' for call in api.call_args_list))
 def test_existing_instagram_media_only_gets_permalink(self):
  from scotus_cloud.instagram_clip import publish
  with patch('scotus_cloud.instagram_clip.api',return_value={'permalink':'https://instagram.com/reel/example/'}) as api:
   publish(None,{'access_token':'private','user_id':'account'},{'media_id':'existing'},Mock(),'caption',None,lambda:None)
  self.assertEqual(api.call_args.args[2:4],('GET','existing'))

class InstagramLocationTests(unittest.TestCase):
 def test_location_is_sent_on_container_creation(self):
  from scotus_cloud.instagram_clip import publish
  state={}
  def checkpoint(**values):state.update(values)
  with patch('scotus_cloud.instagram_clip.api',side_effect=[{'id':'container'},{'status_code':'FINISHED'},{'id':'media'},{'permalink':'https://instagram.com/reel/example/'}]) as api:
   publish(None,{'access_token':'private','user_id':'account'},state,checkpoint,'caption','video-url',lambda:None,location_id='123456789')
  self.assertEqual(api.call_args_list[0].kwargs['location_id'],'123456789')
  self.assertEqual(state['location_id'],'123456789')
 def test_existing_container_does_not_gain_a_new_location(self):
  from scotus_cloud.instagram_clip import publish
  with patch('scotus_cloud.instagram_clip.api',side_effect=[{'status_code':'FINISHED'},{'id':'media'},{'permalink':'https://instagram.com/reel/example/'}]) as api:
   publish(None,{'access_token':'private','user_id':'account'},{'container_id':'existing'},Mock(),'caption',None,lambda:None,location_id='123456789')
  self.assertFalse(any('location_id' in call.kwargs for call in api.call_args_list))
