"""A short-lived, private Codex sign-in job. It never starts a model turn."""

import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from .google import Google
from .remote import Dashboard


class LoginError(RuntimeError):
    pass


class AppServer:
    def __init__(self, process):
        self.process = process

    async def send(self, method, parameters=None, request_id=None):
        message = {'method': method}
        if parameters is not None:
            message['params'] = parameters
        if request_id is not None:
            message['id'] = request_id
        self.process.stdin.write(json.dumps(message).encode() + b'\n')
        await self.process.stdin.drain()

    async def receive(self, timeout=15):
        line = await asyncio.wait_for(self.process.stdout.readline(), timeout)
        if not line:
            raise LoginError('sign_in_process_stopped')
        return json.loads(line)

    async def initialize(self):
        await self.send('initialize', {'clientInfo': {'name': 'scotus_video_signin', 'title': 'Scotus video sign-in', 'version': '1.0'}}, 1)
        while True:
            response = await self.receive(30)
            if response.get('id') == 1:
                if 'error' in response:
                    raise LoginError('sign_in_protocol_unavailable')
                break
        await self.send('initialized', {})


async def sign_in(settings, probe=False):
    dashboard = Dashboard(settings['dashboard_url'], settings['dashboard_key'], 'codex')
    google = Google(settings['project'])
    login_id = os.environ.get('SCOTUS_LOGIN_ID', '')
    login_token = os.environ.get('SCOTUS_LOGIN_TOKEN', '')
    if not probe and (not re.fullmatch('[a-f0-9]{32}', login_id) or not re.fullmatch('[a-f0-9]{48}', login_token)):
        raise LoginError('missing_sign_in_attempt')
    auth_lease = None; process = None
    try:
        if not probe:
            current = dashboard.call('login_check', id=login_id, token=login_token)
            if current['status'] not in ('starting', 'pending'):
                return
            auth_lease = dashboard.call('auth_claim', name='codex')
            if not auth_lease:
                raise LoginError('credential_in_use')
        with tempfile.TemporaryDirectory(prefix='scotus-cloud-login-') as folder:
            home = Path(folder); home.chmod(0o700)
            (home / 'config.toml').write_text('cli_auth_credentials_store = "file"\nforced_login_method = "chatgpt"\n')
            env = dict(os.environ, CODEX_HOME=str(home))
            for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'):
                env.pop(name, None)
            process = await asyncio.create_subprocess_exec('codex', 'app-server', cwd=home, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=262144)
            server = AppServer(process)
            await server.initialize()
            if probe:
                await server.send('account/read', {'refreshToken': False}, 2)
                while True:
                    response = await server.receive()
                    if response.get('id') == 2:
                        if response.get('error') or response.get('result', {}).get('account'):
                            raise LoginError('probe_not_isolated')
                        print(json.dumps({'protocol_ready': True, 'isolated': True,
                            'version': subprocess.check_output(['codex', '--version'], text=True).strip()}))
                        return
            await server.send('account/login/start', {'type': 'chatgptDeviceCode'}, 2)
            deadline = time.monotonic() + 780
            next_check = 0; native_login_id = None; completed = False
            while time.monotonic() < deadline:
                if time.monotonic() >= next_check:
                    dashboard.call('auth_check', name='codex', token=auth_lease)
                    current = dashboard.call('login_check', id=login_id, token=login_token)
                    if current['status'] not in ('starting', 'pending'):
                        return
                    next_check = time.monotonic() + 20
                try:
                    response = await server.receive(10)
                except asyncio.TimeoutError:
                    continue
                if response.get('id') == 2:
                    if 'error' in response:
                        raise LoginError('device_login_unavailable')
                    result = response['result']; native_login_id = result.get('loginId')
                    if result.get('type') != 'chatgptDeviceCode' or result.get('verificationUrl') != 'https://auth.openai.com/codex/device':
                        raise LoginError('unexpected_sign_in_instructions')
                    dashboard.call('login_update', id=login_id, token=login_token, status='pending',
                                   verification_url=result['verificationUrl'], user_code=result['userCode'])
                elif response.get('method') == 'account/login/completed':
                    result = response['params']
                    if result.get('loginId') != native_login_id:
                        continue
                    if not result.get('success'):
                        raise LoginError('device_login_failed')
                    completed = True
                    break
            if not completed:
                raise LoginError('device_login_expired')
            current = dashboard.call('login_check', id=login_id, token=login_token)
            dashboard.call('auth_check', name='codex', token=auth_lease)
            if current['status'] not in ('starting', 'pending'):
                return
            auth_file = home / 'auth.json'
            value = json.loads(auth_file.read_bytes())
            if value.get('auth_mode') != 'chatgpt' or not value.get('tokens', {}).get('refresh_token') or value.get('OPENAI_API_KEY'):
                raise LoginError('subscription_credential_not_saved')
            payload = json.dumps(value).encode()
            if len(payload) > 65536:
                raise LoginError('credential_too_large')
            google.add_secret_version(settings['codex_secret'], payload)
            dashboard.call('login_update', id=login_id, token=login_token, status='complete')
    except Exception:
        if not probe:
            try:
                dashboard.call('login_update', id=login_id, token=login_token, status='failed')
            except Exception:
                pass
        raise LoginError('cloud_sign_in_failed') from None
    finally:
        if process and process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), 5)
            except (asyncio.TimeoutError, ProcessLookupError):
                if process.returncode is None:
                    process.kill(); await process.wait()
        if auth_lease:
            try:
                dashboard.call('auth_release', name='codex', token=auth_lease)
            except Exception:
                pass


def main():
    if not os.environ.get('CLOUD_RUN_JOB'):
        raise LoginError('sign_in_is_cloud_only')
    os.umask(0o077)
    settings = json.loads(Path('/secrets/login/config.json').read_text())
    try:
        asyncio.run(asyncio.wait_for(sign_in(settings, os.environ.get('SCOTUS_AUTH_PROBE') == '1'), 850))
    except Exception:
        # Raw app-server responses can contain credentials; never log them or a traceback.
        print('Cloud sign-in stopped. Check the dashboard and retry.')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
