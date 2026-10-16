import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.connections import INSTAGRAM_SCOPES, InstagramConnectionError, instagram_authorize, instagram_exchange, instagram_request, validate_instagram_client


class InstagramConnectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'dashboard_url': 'https://scotusstats.com/youtube/', 'secrets': {'instagram_client': 'client'}}
        self.google = Mock()
        self.google.secret.return_value = json.dumps({'client_id': '2748057315624132', 'client_secret': 'a' * 32}).encode()

    def test_authorize_has_exact_scopes_callback_state_and_no_secret(self):
        result = instagram_authorize({'state': 'b' * 32}, self.settings, self.google)
        parsed = urlsplit(result['url']); query = parse_qs(parsed.query)
        self.assertEqual(parsed.hostname, 'www.instagram.com')
        self.assertEqual(query['scope'], [','.join(INSTAGRAM_SCOPES)])
        self.assertEqual(query['redirect_uri'], ['https://scotusstats.com/youtube/instagram-callback.php'])
        self.assertEqual(query['state'], ['b' * 32])
        self.assertNotIn('a' * 32, result['url'])
        with self.assertRaises(ValueError): instagram_authorize({'state': 'bad'}, self.settings, self.google)

    @patch('scotus_cloud.connections.instagram_request')
    def test_exchange_verifies_identity_and_grants_without_publishing(self, request):
        request.side_effect = [
            {'data': [{'access_token': 'short', 'permissions': INSTAGRAM_SCOPES}]},
            {'access_token': 'long', 'expires_in': 5184000},
            {'user_id': '123456', 'username': 'scotus.oral.arguments'}]
        value = instagram_exchange({'code': 'test-code'}, self.settings, self.google)
        self.assertEqual(value['user_id'], '123456')
        self.assertEqual(value['access_token'], 'long')
        self.assertTrue(all('/media' not in call.args[2] for call in request.call_args_list))
        request.side_effect = [
            {'access_token': 'short', 'permissions': INSTAGRAM_SCOPES},
            {'access_token': 'long', 'expires_in': 5184000},
            {'user_id': '123456', 'username': 'personal-account'}]
        with self.assertRaisesRegex(ValueError, 'Choose'): instagram_exchange({'code': 'test-code'}, self.settings, self.google)
        request.side_effect = [{'access_token': 'short', 'permissions': ['instagram_business_basic']}]
        with self.assertRaisesRegex(ValueError, 'publishing'): instagram_exchange({'code': 'test-code'}, self.settings, self.google)

    @patch('scotus_cloud.connections.instagram_request')
    def test_missing_grants_are_checked_and_declined_grants_rejected(self, request):
        request.side_effect = [{'access_token': 'short'}, {'access_token': 'long', 'expires_in': 60},
            {'user_id': '123456', 'username': 'scotus.oral.arguments'},
            {'data': [{'permission': name, 'status': 'declined'} for name in INSTAGRAM_SCOPES]}]
        with self.assertRaisesRegex(ValueError, 'publishing'): instagram_exchange({'code': 'test-code'}, self.settings, self.google)

    def test_client_input_rejects_arbitrary_values(self):
        with self.assertRaises(ValueError): validate_instagram_client({'client_id': 'wrong', 'client_secret': 'a' * 32})
        self.assertEqual(json.loads(validate_instagram_client({'client_id': '2748057315624132', 'client_secret': 'a' * 32}))['client_id'], '2748057315624132')

    @patch('scotus_cloud.connections.instagram_request')
    def test_explicit_get_method_rejection_falls_back_to_post(self, request):
        request.side_effect = [{'access_token': 'short', 'permissions': INSTAGRAM_SCOPES},
            InstagramConnectionError('long-lived token: HTTP 400: code 100: Unsupported request - method type: get'),
            {'access_token': 'long', 'expires_in': 5184000}, {'user_id': '123456', 'username': 'scotus.oral.arguments'}]
        value = instagram_exchange({'code': 'test-code'}, self.settings, self.google)
        self.assertEqual(value['access_token'], 'long')
        self.assertEqual(request.call_args_list[2].args[1], 'POST')

    @patch('scotus_cloud.connections.requests.request')
    def test_provider_diagnostics_exclude_response_text_and_credentials(self, request):
        request.return_value = Mock(status_code=400, content=b'private response')
        request.return_value.json.return_value = {'error': {'code': 190, 'message': 'Invalid private-test-token'}}
        with self.assertRaisesRegex(ValueError, r'^code exchange: HTTP 400: code 190: Invalid \[redacted\]$'):
            instagram_request('code exchange', 'POST', 'https://api.instagram.com/oauth/access_token', data={'access_token': 'private-test-token'})
