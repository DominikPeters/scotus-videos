"""Provider sign-in exchanges. Auth values never go back to the browser."""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import time
from urllib.parse import urlencode

import requests

YOUTUBE_SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
GITHUB_REPOSITORY = 'DominikPeters/scotus-videos'
INSTAGRAM_SCOPES = ['instagram_business_basic', 'instagram_business_content_publish']


class InstagramConnectionError(ValueError):
    """Only fixed step names and numeric provider error codes; safe to log."""


def instagram_request(step, method, url, **kwargs):
    response = requests.request(method, url, timeout=20, allow_redirects=False, **kwargs)
    if len(response.content) > 262144:
        raise InstagramConnectionError(step + ': response too large')
    try: value = response.json()
    except ValueError: raise InstagramConnectionError(step + ': invalid JSON') from None
    if not 200 <= response.status_code < 300:
        error = value.get('error', {})
        code = error.get('code') if isinstance(error, dict) else None
        detail = ': code ' + str(code) if isinstance(code, int) else ''
        message = str(error.get('message', '')) if isinstance(error, dict) else ''
        for group in ('params', 'data'):
            for key in ('access_token', 'client_secret', 'code'):
                private = kwargs.get(group, {}).get(key)
                if isinstance(private, str) and private: message = message.replace(private, '[redacted]')
        message = re.sub(r'[A-Za-z0-9_-]{24,}', '[redacted]', message)[:300]
        if message: detail += ': ' + message
        raise InstagramConnectionError(step + ': HTTP ' + str(response.status_code) + detail)
    print(json.dumps({'instagram_connection_step': step, 'status': 'complete',
                     'expires_in': value.get('expires_in') if isinstance(value.get('expires_in'), int) else None}), flush=True)
    return value


def validate_instagram_client(value):
    if not isinstance(value, dict) or not re.fullmatch(r'[0-9]{5,30}', str(value.get('client_id', ''))) or not re.fullmatch(r'[a-fA-F0-9]{32}', value.get('client_secret', '')):
        raise ValueError('Use the Instagram app ID and Instagram app secret')
    return json.dumps({'client_id': str(value['client_id']), 'client_secret': value['client_secret']}).encode()


def instagram_authorize(data, settings, google):
    if not re.fullmatch('[a-f0-9]{32}', data.get('state', '')):
        raise ValueError('Invalid OAuth state')
    client = json.loads(google.secret(settings['secrets']['instagram_client']))
    return {'url': 'https://www.instagram.com/oauth/authorize?' + urlencode({
        'client_id': client['client_id'], 'redirect_uri': callback(settings, 'instagram'),
        'response_type': 'code', 'scope': ','.join(INSTAGRAM_SCOPES), 'state': data['state'],
        'enable_fb_login': '0', 'force_authentication': '1'})}


def instagram_exchange(data, settings, google):
    code = data.get('code', '')
    if not isinstance(code, str) or not 5 <= len(code) <= 4096:
        raise ValueError('Invalid authorization code')
    client = json.loads(google.secret(settings['secrets']['instagram_client']))
    short = instagram_request('code exchange', 'POST', 'https://api.instagram.com/oauth/access_token', data={
        'client_id': client['client_id'], 'client_secret': client['client_secret'],
        'grant_type': 'authorization_code', 'redirect_uri': callback(settings, 'instagram'), 'code': code})
    # Instagram Login returns the grant inside data; accept the older flat form too.
    if isinstance(short.get('data'), list) and len(short['data']) == 1:
        short = short['data'][0]
    if not short.get('access_token'):
        raise ValueError('Instagram did not return an access token')
    permissions = short.get('permissions')
    if isinstance(permissions, str): permissions = permissions.split(',')
    if permissions is not None and not set(INSTAGRAM_SCOPES) <= set(permissions):
        raise ValueError('Instagram publishing permission was not granted')
    if int(short.get('expires_in', 0)) >= 172800:
        long = short
    else:
        parameters = {'grant_type': 'ig_exchange_token', 'client_secret': client['client_secret'], 'access_token': short['access_token']}
        try:
            long = instagram_request('long-lived token', 'GET', 'https://graph.instagram.com/access_token', params=parameters)
        except InstagramConnectionError as error:
            # Meta's live endpoint can reject the documented GET method. Retry
            # only this explicit method rejection, never other token errors.
            if 'Unsupported request - method type: get' not in str(error): raise
            long = instagram_request('long-lived token', 'POST', 'https://graph.instagram.com/access_token', data=parameters)
    token = long.get('access_token')
    if not isinstance(token, str) or not token or int(long.get('expires_in', 0)) <= 0:
        raise ValueError('Instagram did not return a long-lived token')
    account = instagram_request('account identity', 'GET', 'https://graph.instagram.com/v25.0/me',
        params={'fields': 'user_id,username'}, headers={'Authorization': 'Bearer ' + token})
    if account.get('username', '').lower() != settings.get('instagram_username', 'scotus.oral.arguments').lower():
        raise ValueError('Choose the scotus.oral.arguments Instagram account')
    user_id = str(account.get('user_id', ''))
    if not user_id.isdigit(): raise ValueError('Instagram did not return the professional account ID')
    if permissions is None:
        grants = instagram_request('permission check', 'GET', 'https://graph.instagram.com/v25.0/me/permissions', headers={'Authorization': 'Bearer ' + token})
        permissions = [item['permission'] for item in grants.get('data', []) if item.get('status') == 'granted']
        if not set(INSTAGRAM_SCOPES) <= set(permissions):
            raise ValueError('Instagram publishing permission was not granted')
    return {'access_token': token, 'user_id': user_id, 'username': account['username'],
            'scopes': INSTAGRAM_SCOPES, 'expires_at': int(time.time()) + int(long['expires_in'])}


def provider_request(method, url, **kwargs):
    limit=kwargs.pop('_max_response_bytes',262144)
    response = requests.request(method, url, timeout=25, allow_redirects=False, **kwargs)
    if not 200 <= response.status_code < 300 or len(response.content) > limit:
        raise ValueError('Provider rejected the connection')
    return response.json()


def callback(settings, provider):
    if provider == 'instagram':
        return settings['dashboard_url'].rstrip('/') + '/instagram-callback.php'
    return settings['dashboard_url'].rstrip('/') + '/oauth-callback.php?provider=' + provider


def validate_web_client(value, settings):
    client = value.get('web') if isinstance(value, dict) else None
    if not isinstance(client, dict) or not all(isinstance(client.get(k), str) and client[k] for k in ('client_id', 'client_secret')):
        raise ValueError('Use a Web application OAuth client')
    if callback(settings, 'youtube') not in client.get('redirect_uris', []):
        raise ValueError('The dashboard callback must be registered')
    # Use fixed Google endpoints; an imported file cannot change our destinations.
    return json.dumps({'client_id': client['client_id'], 'client_secret': client['client_secret']}, separators=(',', ':')).encode()


def youtube_authorize(data, settings, google):
    if not re.fullmatch('[a-f0-9]{32}', data.get('state', '')) or not re.fullmatch('[A-Za-z0-9_-]{43}', data.get('code_challenge', '')):
        raise ValueError('Invalid OAuth state')
    client = json.loads(google.secret(settings['secrets']['youtube_client']))
    parameters = {'client_id': client['client_id'], 'redirect_uri': callback(settings, 'youtube'),
                  'response_type': 'code', 'scope': ' '.join(YOUTUBE_SCOPES), 'access_type': 'offline',
                  'prompt': 'consent select_account', 'state': data['state'],
                  'code_challenge_method': 'S256', 'code_challenge': data['code_challenge']}
    return {'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(parameters)}


def youtube_exchange(data, settings, google):
    code, verifier = data.get('code', ''), data.get('verifier', '')
    if not isinstance(code, str) or not 5 <= len(code) <= 4096 or not re.fullmatch('[A-Za-z0-9_-]{43,128}', verifier):
        raise ValueError('Invalid authorization code')
    client = json.loads(google.secret(settings['secrets']['youtube_client']))
    value = provider_request('POST', 'https://oauth2.googleapis.com/token', data={
        'code': code, 'code_verifier': verifier, 'client_id': client['client_id'], 'client_secret': client['client_secret'],
        'redirect_uri': callback(settings, 'youtube'), 'grant_type': 'authorization_code'})
    if not value.get('refresh_token') or not value.get('access_token') or not set(YOUTUBE_SCOPES) <= set(value.get('scope', '').split()):
        raise ValueError('YouTube offline permission was not granted')
    # Confirm the selected YouTube channel before replacing any usable credential.
    channels = provider_request('GET', 'https://www.googleapis.com/youtube/v3/channels',
        params={'part': 'snippet', 'mine': 'true'}, headers={'Authorization': 'Bearer ' + value['access_token']})
    items = channels.get('items', [])
    if len(items) != 1:
        raise ValueError('Choose the channel account to connect')
    expected = settings.get('youtube_channel_id')
    if expected and items[0]['id'] != expected:
        raise ValueError('This is a different YouTube channel')
    return {'type': 'authorized_user', 'client_id': client['client_id'], 'client_secret': client['client_secret'],
            'refresh_token': value['refresh_token'], 'token': value['access_token'], 'token_uri': 'https://oauth2.googleapis.com/token',
            'scopes': YOUTUBE_SCOPES, 'expiry': (datetime.now(timezone.utc) + timedelta(seconds=int(value.get('expires_in', 3600)))).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'channel_id': items[0]['id'], 'channel_title': items[0]['snippet']['title']}


def github_headers(token=None):
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'scotus-video-assets'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return headers


def github_jwt(value):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    encoded = lambda part: base64.urlsafe_b64encode(part).rstrip(b'=')
    now = int(time.time())
    signing = encoded(b'{"alg":"RS256","typ":"JWT"}') + b'.' + encoded(json.dumps({
        'iat': now - 60, 'exp': now + 480, 'iss': str(value['app_id'])}, separators=(',', ':')).encode())
    key = serialization.load_pem_private_key(value['private_key'].encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError('Invalid GitHub App private key')
    return (signing + b'.' + encoded(key.sign(signing, padding.PKCS1v15(), hashes.SHA256()))).decode()


def github_exchange(data, settings):
    code = data.get('code', '')
    if not re.fullmatch('[A-Za-z0-9_-]{10,256}', code):
        raise ValueError('Invalid app registration code')
    result = provider_request('POST', 'https://api.github.com/app-manifests/' + code + '/conversions', headers=github_headers())
    if result.get('owner', {}).get('login', '').lower() != GITHUB_REPOSITORY.split('/')[0].lower() or result.get('permissions', {}).get('contents') != 'write':
        raise ValueError('Use an app owned by the repository owner with Contents write permission')
    if any(permission not in ('contents', 'metadata') and level != 'none' for permission, level in result.get('permissions', {}).items()):
        raise ValueError('The app has unnecessary permissions')
    slug = result.get('slug', '')
    if not re.fullmatch('[a-z0-9-]{1,100}', slug):
        raise ValueError('Invalid app identifier')
    value = {'app_id': int(result['id']), 'slug': slug, 'private_key': result['pem'], 'repository': GITHUB_REPOSITORY}
    github_jwt(value)  # Validate the key before saving it. Discard OAuth client secrets and webhook secrets.
    return value


def github_install(value, installation_id=None):
    headers = github_headers(github_jwt(value))
    installation = provider_request('GET', 'https://api.github.com/repos/' + GITHUB_REPOSITORY + '/installation', headers=headers)
    if installation_id and str(installation['id']) != str(installation_id):
        raise ValueError('The callback refers to a different installation')
    if (installation.get('suspended_at') or installation.get('repository_selection') != 'selected' or
        installation.get('permissions', {}).get('contents') != 'write' or
        installation.get('account', {}).get('login', '').lower() != GITHUB_REPOSITORY.split('/')[0].lower()):
        raise ValueError('Select repositories including scotus-videos and allow Contents write permission')
    # The installation may include other operator-selected repositories. This
    # connection checks only the video repository, with a token narrowed at issue.
    token = provider_request('POST', f"https://api.github.com/app/installations/{installation['id']}/access_tokens", headers=headers,
                             json={'repositories': [GITHUB_REPOSITORY.split('/')[1]], 'permissions': {'contents': 'read'}})['token']
    repository = provider_request('GET', 'https://api.github.com/repos/' + GITHUB_REPOSITORY, headers=github_headers(token))
    if repository.get('full_name', '').lower() != GITHUB_REPOSITORY.lower():
        raise ValueError('The video repository must be included in the installation')
    return {**value, 'installation_id': int(installation['id']), 'repository_id': int(repository['id'])}


def github_token(value,repository=GITHUB_REPOSITORY):
    if value.get('repository') != GITHUB_REPOSITORY:
        raise ValueError('Unsupported repository')
    if repository not in (GITHUB_REPOSITORY,'DominikPeters/scotus-podcast'):raise ValueError('Unsupported repository')
    scope={'repository_ids':[int(value['repository_id'])]} if repository==GITHUB_REPOSITORY else {'repositories':['scotus-podcast']}
    return provider_request('POST', f"https://api.github.com/app/installations/{int(value['installation_id'])}/access_tokens",
        headers=github_headers(github_jwt(value)), json={**scope,'permissions': {'contents': 'write'}})['token']
