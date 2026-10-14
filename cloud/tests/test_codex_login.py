import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.codex_login import sign_in


class CodexLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_login_cache_is_saved_privately_and_api_key_is_removed(self):
        cloud = Mock(); dashboard = Mock(); process = Mock(returncode=None)
        process.wait = AsyncMock(return_value=0)
        status = {'status': 'starting'}
        def call(op, **data):
            if op == 'login_check': return dict(status)
            if op == 'auth_claim': return 'private-auth-lease'
            if op == 'login_update': status['status'] = data['status']
            return True
        dashboard.call.side_effect = call
        async def spawn(*args, **kwargs):
            self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
            home = Path(kwargs['env']['CODEX_HOME'])
            self.assertEqual(home.stat().st_mode & 0o777, 0o700)
            (home / 'auth.json').write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {'refresh_token': 'private-refresh-token'}}))
            return process
        server = Mock(); server.initialize = AsyncMock(); server.send = AsyncMock()
        server.receive = AsyncMock(side_effect=[{'id': 2, 'result': {'type': 'chatgptDeviceCode', 'loginId': 'native-id',
            'verificationUrl': 'https://auth.openai.com/codex/device', 'userCode': 'ABCD-1234'}},
            {'method': 'account/login/completed', 'params': {'loginId': 'native-id', 'success': True}}])
        output = io.StringIO()
        with patch.dict(os.environ, {'SCOTUS_LOGIN_ID': 'a'*32, 'SCOTUS_LOGIN_TOKEN': 'b'*48, 'OPENAI_API_KEY': 'must-not-be-used'}), \
            patch('scotus_cloud.codex_login.Google', return_value=cloud), patch('scotus_cloud.codex_login.Dashboard', return_value=dashboard), \
            patch('scotus_cloud.codex_login.asyncio.create_subprocess_exec', side_effect=spawn), \
            patch('scotus_cloud.codex_login.AppServer', return_value=server), contextlib.redirect_stdout(output):
            await sign_in({'project': 'test', 'dashboard_url': 'https://scotusstats.com/youtube/', 'dashboard_key': 'test', 'codex_secret': 'codex-secret'})
        self.assertEqual(status['status'], 'complete')
        cloud.add_secret_version.assert_called_once()
        self.assertIn(b'private-refresh-token', cloud.add_secret_version.call_args.args[1])
        self.assertEqual(output.getvalue(), '')
        process.terminate.assert_called_once()

    async def test_cancelled_attempt_never_starts_native_login_or_saves_a_secret(self):
        cloud = Mock(); dashboard = Mock(); dashboard.call.return_value = {'status': 'cancelled'}
        with patch.dict(os.environ, {'SCOTUS_LOGIN_ID': 'a'*32, 'SCOTUS_LOGIN_TOKEN': 'b'*48}), \
            patch('scotus_cloud.codex_login.Google', return_value=cloud), patch('scotus_cloud.codex_login.Dashboard', return_value=dashboard), \
            patch('scotus_cloud.codex_login.asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            await sign_in({'project': 'test', 'dashboard_url': 'https://scotusstats.com/youtube/', 'dashboard_key': 'test'})
        spawn.assert_not_called(); cloud.add_secret_version.assert_not_called()
