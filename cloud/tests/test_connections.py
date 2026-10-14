import io
import json
from pathlib import Path
import sys
import subprocess
import shutil
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.connections import (GITHUB_REPOSITORY, YOUTUBE_SCOPES, github_install,
    github_token, validate_web_client, youtube_authorize, youtube_exchange)
from scotus_cloud.control import make_app
from scotus_cloud.github_assets import portrait_files, commit_portrait
from scotus_cloud.remote import signature


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'project': 'test', 'dashboard_url': 'https://scotusstats.com/youtube/',
            'control_key': 'controller-key', 'dispatcher_key': 'dispatcher-key',
            'secrets': {'youtube': 'yt-secret', 'youtube_client': 'web-client', 'github': 'github-secret', 'codex': 'codex-secret'}}
        self.client = {'client_id': 'client', 'client_secret': 'private-client-secret'}
        self.google = Mock(); self.google.secret.return_value = json.dumps(self.client).encode()
        self.provenance = {'name': 'Test Counsel', 'identity_verified': True, 'docket': '25-332',
            'source_url': 'https://firm.example/photo.jpg', 'identity_source_url': 'https://www.supremecourt.gov/docket'}
        self.image = b'\xff\xd8\xff' + b'x' * 150

    def test_web_client_requires_exact_registered_callback(self):
        for value in ({'installed': self.client}, {'web': {**self.client, 'redirect_uris': ['https://evil.example/callback']}}):
            with self.assertRaises(ValueError): validate_web_client(value, self.settings)
        value = validate_web_client({'web': {**self.client, 'redirect_uris': ['https://scotusstats.com/youtube/oauth-callback.php?provider=youtube'],
            'token_uri': 'https://evil.example/steal'}}, self.settings)
        self.assertNotIn(b'evil.example', value)

    def test_youtube_browser_flow_uses_pkce_offline_consent_and_keeps_secret_private(self):
        result = youtube_authorize({'state': 'a' * 32, 'code_challenge': 'b' * 43}, self.settings, self.google)
        url = urlsplit(result['url']); params = parse_qs(url.query)
        self.assertEqual(url.hostname, 'accounts.google.com')
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertEqual(params['access_type'], ['offline'])
        self.assertEqual(params['scope'], [' '.join(YOUTUBE_SCOPES)])
        self.assertNotIn('private-client-secret', result['url'])

    @patch('scotus_cloud.connections.provider_request')
    def test_youtube_does_not_accept_partial_scope_or_wrong_channel(self, request):
        self.settings['youtube_channel_id'] = 'expected-channel'
        request.return_value = {'refresh_token': 'refresh-secret', 'access_token': 'access-secret', 'scope': 'openid'}
        with self.assertRaises(ValueError): youtube_exchange({'code': 'code1234', 'verifier': 'b' * 64}, self.settings, self.google)
        request.side_effect = [{'refresh_token': 'refresh-secret', 'access_token': 'access-secret', 'scope': ' '.join(YOUTUBE_SCOPES)},
            {'items': [{'id': 'wrong-channel', 'snippet': {'title': 'Other channel'}}]}]
        with self.assertRaises(ValueError): youtube_exchange({'code': 'code1234', 'verifier': 'b' * 64}, self.settings, self.google)
        self.google.add_secret_version.assert_not_called()

    @patch('scotus_cloud.connections.github_jwt', return_value='private-jwt')
    @patch('scotus_cloud.connections.provider_request')
    def test_github_accepts_additional_selected_repositories_with_narrow_validation_token(self, request, jwt):
        request.side_effect = [{'id': 123, 'repository_selection': 'selected', 'permissions': {'contents': 'write'},
            'account': {'login': 'DominikPeters'}}, {'token': 'short-lived-token'},
            {'id': 5, 'full_name': GITHUB_REPOSITORY}]
        saved = github_install({'app_id': 1, 'private_key': 'test'}, '123')
        self.assertEqual(saved['installation_id'], 123)
        self.assertEqual(saved['repository_id'], 5)
        self.assertEqual(request.call_args_list[1].kwargs['json'], {'repositories': ['scotus-videos'], 'permissions': {'contents': 'read'}})
        self.assertEqual(request.call_args_list[2].args[1], 'https://api.github.com/repos/' + GITHUB_REPOSITORY)

    @patch('scotus_cloud.connections.github_jwt', return_value='private-jwt')
    @patch('scotus_cloud.connections.provider_request')
    def test_github_still_requires_video_repository(self, request, jwt):
        request.side_effect = [{'id': 123, 'repository_selection': 'selected', 'permissions': {'contents': 'write'},
            'account': {'login': 'DominikPeters'}}, {'token': 'short-lived-token'}, {'id': 6, 'full_name': 'DominikPeters/scotusstats'}]
        with self.assertRaises(ValueError): github_install({'app_id': 1, 'private_key': 'test'})

    @patch('scotus_cloud.connections.github_jwt', return_value='private-jwt')
    @patch('scotus_cloud.connections.provider_request')
    def test_github_rejects_wrong_or_suspended_installation(self, request, jwt):
        installation = {'id': 123, 'repository_selection': 'selected', 'permissions': {'contents': 'write'}, 'account': {'login': 'DominikPeters'}}
        for result, expected_id in ((installation, '456'), ({**installation, 'suspended_at': '2026-10-12'}, None),
            ({**installation, 'account': {'login': 'someone-else'}}, None), ({**installation, 'permissions': {'contents': 'read'}}, None)):
            request.return_value = result
            with self.assertRaises(ValueError): github_install({'app_id': 1, 'private_key': 'test'}, expected_id)

    @patch('scotus_cloud.connections.github_jwt', return_value='private-jwt')
    @patch('scotus_cloud.connections.provider_request', return_value={'token': 'short-lived-token'})
    def test_github_tokens_are_restricted_to_configured_repository(self, request, jwt):
        value = {'app_id': 1, 'private_key': 'test', 'repository': GITHUB_REPOSITORY, 'installation_id': 3, 'repository_id': 5}
        self.assertEqual(github_token(value), 'short-lived-token')
        self.assertEqual(request.call_args.kwargs['json'], {'repository_ids': [5], 'permissions': {'contents': 'write'}})
        with self.assertRaises(ValueError): github_token({**value, 'repository': 'somebody/other'})

    def test_asset_publisher_rejects_traversal_fake_images_and_unverified_identity(self):
        for person, image, evidence in (('../bad', self.image, self.provenance), ('lawyer', b'<html>' * 100, self.provenance),
            ('lawyer', self.image, {**self.provenance, 'identity_verified': False})):
            with self.assertRaises(ValueError): portrait_files(person, 'jpg', image, evidence)
        files = portrait_files('test_counsel', 'jpg', self.image, self.provenance)
        self.assertEqual(set(files), {'advocates/test_counsel.jpg', 'advocates/test_counsel.source.json'})

    @patch('scotus_cloud.github_assets.github_token', return_value='private-token')
    @patch('scotus_cloud.github_assets.provider_request')
    def test_asset_commit_preserves_existing_files_and_never_force_pushes(self, request, token):
        credential = {'repository': GITHUB_REPOSITORY}
        request.side_effect = [{'object': {'sha': 'head'}}, {'tree': {'sha': 'tree'}},
            {'tree': [{'path': 'advocates/test_counsel.jpg', 'sha': 'existing'}]}]
        with self.assertRaises(ValueError): commit_portrait(credential, 'test_counsel', 'jpg', self.image, self.provenance, branch='main')
        self.assertTrue(all(call.args[0] == 'GET' for call in request.call_args_list))
        request.reset_mock(); request.side_effect = [{'object': {'sha': 'head'}}, {'tree': {'sha': 'tree'}}, {'tree': []},
            {'sha': 'image'}, {'sha': 'source'}, {'sha': 'new-tree'}, {'sha': 'new-commit'}, {}]
        result = commit_portrait(credential, 'test_counsel', 'jpg', self.image, self.provenance, branch='main')
        self.assertEqual(result['commit'], 'new-commit')
        self.assertEqual(request.call_args.kwargs['json'], {'sha': 'new-commit', 'force': False})

    @patch('scotus_cloud.control.Dashboard.call', return_value='lease-token')
    @patch('scotus_cloud.control.youtube_exchange', return_value={'client_id': 'c', 'client_secret': 'private-secret', 'refresh_token': 'refresh-secret'})
    def test_controller_saves_credentials_without_returning_them(self, exchange, dashboard):
        body = json.dumps({'op': 'youtube_exchange', 'data': {'code': 'auth-code'}}).encode()
        timestamp = str(int(time.time())); nonce = 'a' * 32
        environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/v1/request', 'CONTENT_LENGTH': str(len(body)),
            'wsgi.input': io.BytesIO(body), 'HTTP_X_SCOTUS_TIME': timestamp, 'HTTP_X_SCOTUS_NONCE': nonce,
            'HTTP_X_SCOTUS_SIGNATURE': signature('controller-key', timestamp, nonce, 'POST', '/v1/request', body)}
        app = make_app(self.settings, lambda project: self.google); status = []
        result = b''.join(app(environ, lambda code, headers: status.append(code)))
        self.assertEqual(status, ['200 OK']); self.assertEqual(json.loads(result)['result'], {'saved': True})
        self.assertNotIn(b'private-secret', result); self.assertNotIn(b'refresh-secret', result)
        self.google.add_secret_version.assert_called_once()

    @patch('scotus_cloud.control.youtube_exchange', return_value={'client_id': 'c', 'client_secret': 'private-secret', 'refresh_token': 'refresh-secret'})
    def test_expired_credential_lease_prevents_secret_write(self, exchange):
        def call(operation, **data):
            if operation == 'auth_check': raise RuntimeError('Lease expired')
            return 'lease-token'
        body = json.dumps({'op': 'youtube_exchange', 'data': {'code': 'auth-code'}}).encode()
        timestamp = str(int(time.time())); nonce = 'a' * 32
        environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/v1/request', 'CONTENT_LENGTH': str(len(body)),
            'wsgi.input': io.BytesIO(body), 'HTTP_X_SCOTUS_TIME': timestamp, 'HTTP_X_SCOTUS_NONCE': nonce,
            'HTTP_X_SCOTUS_SIGNATURE': signature('controller-key', timestamp, nonce, 'POST', '/v1/request', body)}
        app = make_app(self.settings, lambda project: self.google)
        with patch('scotus_cloud.control.Dashboard.call', side_effect=call):
            result = b''.join(app(environ, lambda code, headers: None))
        self.assertFalse(json.loads(result)['ok'])
        self.google.add_secret_version.assert_not_called()

    @unittest.skipUnless(shutil.which('php') and (Path(__file__).resolve().parents[1]/'dashboard/private/connections.php').is_file(), 'PHP callback check runs on the dashboard host')
    @patch('scotus_cloud.control.Dashboard.call', return_value='lease-token')
    @patch('scotus_cloud.control.github_install', return_value={'slug': 'scotus-assets', 'installation_id': 123})
    def test_php_check_installation_request_is_accepted_by_controller(self, install, dashboard):
        source = Path(__file__).resolve().parents[1] / 'dashboard/private/connections.php'
        body = subprocess.check_output(['php', '-r', 'require $argv[1]; echo control_body("github_install");', str(source)])
        timestamp = str(int(time.time())); nonce = 'a' * 32
        environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/v1/request', 'CONTENT_LENGTH': str(len(body)),
            'wsgi.input': io.BytesIO(body), 'HTTP_X_SCOTUS_TIME': timestamp, 'HTTP_X_SCOTUS_NONCE': nonce,
            'HTTP_X_SCOTUS_SIGNATURE': signature('controller-key', timestamp, nonce, 'POST', '/v1/request', body)}
        app = make_app(self.settings, lambda project: self.google); status = []
        result = b''.join(app(environ, lambda code, headers: status.append(code)))
        self.assertEqual(status, ['200 OK'])
        self.assertTrue(json.loads(result)['result']['configured'])
        install.assert_called_once()


if __name__ == '__main__': unittest.main()
