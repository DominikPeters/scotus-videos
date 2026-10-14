import json,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scotus_cloud.photo_access import PhotoAccess,profile_url

class PhotoAccessTests(unittest.TestCase):
 def access(self):
  cloud=Mock();cloud.secret.return_value=json.dumps({'cookies':{'li_at':'private-session-token','JSESSIONID':'ajax:123','irrelevant':'ignored'}}).encode()
  return PhotoAccess(cloud,{'linkedin_secret':'private-linkedin'})
 def response(self,status=200):
  r=Mock(status_code=status);r.headers={'Content-Type':'text/html'};r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
  r.iter_content.return_value=[b'<meta property="og:title" content="Attorney at Law Firm"><meta property="og:description" content="Austin"><meta property="og:image" content="https://media.licdn.com/dms/image/photo.jpg"><script>private-session-token; messages; account settings</script>']
  return r
 def test_cookie_is_host_mediated_and_only_profile_evidence_is_returned(self):
  access=self.access();r=self.response()
  with patch('scotus_cloud.photo_access.requests.get',return_value=r) as fetch:
   result=access.invoke('photo_fetch_authenticated',{'url':'https://linkedin.com/in/jane-lawyer/?tracking=foo'})
  self.assertEqual(result['profile_url'],'https://www.linkedin.com/in/jane-lawyer/')
  self.assertEqual(result['portrait_urls'],['https://media.licdn.com/dms/image/photo.jpg'])
  self.assertNotIn('private-session-token',json.dumps(result));self.assertNotIn('messages',json.dumps(result))
  self.assertEqual(fetch.call_args.kwargs['cookies']['li_at'],'private-session-token')
  self.assertNotIn('irrelevant',fetch.call_args.kwargs['cookies']);self.assertFalse(fetch.call_args.kwargs['allow_redirects'])
 def test_unapproved_host_and_account_pages_are_rejected_before_secret_read(self):
  for url in ('https://linkedin.com.evil.test/in/name/','http://www.linkedin.com/in/name/','https://www.linkedin.com/messaging/','https://www.linkedin.com:444/in/name/'):
   access=self.access()
   with self.assertRaises(ValueError):access.invoke('photo_fetch_authenticated',{'url':url})
   access.cloud.secret.assert_not_called()
 def test_login_redirect_is_not_followed_and_no_cookie_is_returned(self):
  access=self.access()
  with patch('scotus_cloud.photo_access.requests.get',return_value=self.response(302)) as fetch:
   value=access.invoke('photo_fetch_authenticated',{'url':'https://www.linkedin.com/in/name/'})
  self.assertEqual(value['http_status'],302);self.assertNotIn('private-session-token',json.dumps(value));fetch.assert_called_once()
 def test_fetches_are_bounded_and_tool_is_absent_without_credentials(self):
  self.assertEqual(PhotoAccess(Mock(),{}).definitions(),[])
  access=self.access()
  with patch('scotus_cloud.photo_access.requests.get',return_value=self.response()):
   for _ in range(4):access.invoke('photo_fetch_authenticated',{'url':'https://www.linkedin.com/in/name/'})
   self.assertIn('limit',access.invoke('photo_fetch_authenticated',{'url':'https://www.linkedin.com/in/name/'})['error'])
  self.assertEqual(access.cloud.secret.call_count,4)
