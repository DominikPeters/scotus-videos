import unittest
from unittest.mock import Mock,patch
from scotus_cloud.youtube_studio import Studio,authorization,link_for_clip

SHORT='STr6IuBQYss';TARGET='RVlud1nKiXY'
class StudioTests(unittest.TestCase):
 def client(self):return Studio({'cookies':{'SAPISID':'private'},'context':{'client':{}},'headers':{'authorization':'stale','x-youtube-client-name':'62'}},Mock())
 def video(self,id,target=None,channel='channel'):
  return {'videoId':id,'channelId':channel,'videoLinkageShortsAttribution':{'links':[{'targetExternalVideoId':target}] if target else []}}
 def test_existing_link_never_writes(self):
  c=self.client();c.read=Mock(side_effect=[self.video(SHORT,TARGET),self.video(TARGET)]);c.call=Mock()
  result=c.link(SHORT,TARGET,'channel');self.assertTrue(result['related_video_verified']);c.call.assert_not_called()
 def test_update_is_narrow_and_read_back(self):
  c=self.client();c.read=Mock(side_effect=[self.video(SHORT),self.video(TARGET),self.video(SHORT,TARGET)]);c.call=Mock();checkpoint=Mock()
  c.link(SHORT,TARGET,'channel',checkpoint)
  operation,body=c.call.call_args.args
  self.assertEqual(operation,'video_manager/metadata_update');self.assertEqual(body['videoLinkageShortsAttribution'],{'targetExternalVideoId':[TARGET]})
  self.assertEqual(set(body),{'encryptedVideoId','flowType','videoReadMask','videoLinkageShortsAttribution'})
  self.assertTrue(checkpoint.call_args.kwargs['related_video_verified'])
 def test_foreign_channel_cannot_be_modified(self):
  c=self.client();c.read=Mock(side_effect=[self.video(SHORT),self.video(TARGET,channel='other')]);c.call=Mock()
  with self.assertRaisesRegex(ValueError,'configured channel'):c.link(SHORT,TARGET,'channel')
  c.call.assert_not_called()
 def test_failed_read_back_never_claims_success(self):
  c=self.client();c.read=Mock(side_effect=[self.video(SHORT),self.video(TARGET)]+[self.video(SHORT)]*4);c.call=Mock();checkpoint=Mock()
  with patch('scotus_cloud.youtube_studio.time.sleep'),self.assertRaisesRegex(ValueError,'not yet confirmed'):c.link(SHORT,TARGET,'channel',checkpoint)
  self.assertFalse(any(x.kwargs.get('related_video_verified') for x in checkpoint.call_args_list))
 def test_request_refreshes_auth_and_never_sends_captured_attestation(self):
  c=self.client();c.session.post.return_value=Mock(status_code=200);c.session.post.return_value.json.return_value={}
  c.call('creator/get_creator_videos',{'videoIds':[SHORT]})
  request=c.session.post.call_args.kwargs
  self.assertNotEqual(request['headers']['Authorization'],'stale');self.assertNotIn('attestationResponseData',request['json']);self.assertFalse(request['allow_redirects'])
  self.assertNotEqual(authorization({'SAPISID':'private'},1),authorization({'SAPISID':'private'},2))
 def test_link_failure_preserves_successful_upload_and_hides_raw_error(self):
  cloud=Mock();cloud.secret.side_effect=RuntimeError('private credential value')
  job={'stages':{'upload':{'result':{'video_id':TARGET}}}}
  result=link_for_clip(job,{}, {'youtube_studio_secret':'secret'},cloud,Mock(),SHORT)
  self.assertEqual(result['related_video_status'],'needs_attention');self.assertNotIn('private',str(result))

if __name__=='__main__':unittest.main()
