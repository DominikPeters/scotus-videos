"""Small signed requests to the PHP dashboard; secrets never enter URLs."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.error import URLError
import uuid

class DashboardTransportError(RuntimeError):
    """A temporary failure, distinct from a rejected lease or command."""


def signature(key, timestamp, nonce, method, path, body):
    digest = hashlib.sha256(body).hexdigest()
    message = '\n'.join((str(timestamp), nonce, method, path, digest)).encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


class Dashboard:
    def __init__(self, url, key, role):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost'):
            raise ValueError('The dashboard connection requires HTTPS')
        self.url = url.rstrip('/') + '/api.php?action=worker'
        self.key, self.role = key, role

    def call(self, op, **data):
        if op in ('auth_claim','recovery_claim'):data.setdefault('claim_id',uuid.uuid4().hex)
        retryable=op in {'snapshot','card_context','discovery_context','recoveries','recovery_context','recovery_check','auth_check','editorial_library',
            'upload_audit_context','review_context','execution_record','checkpoint','auth_claim','recovery_claim','heartbeat'}
        retryable=retryable or op in {'spotify_context','spotify_heartbeat','spotify_update','spotify_claim'}
        retryable=retryable or (op=='finish' and (data.get('continue_upload') or data.get('continue_enrich')) and data.get('handoff_id'))
        attempts=3 if retryable else 1
        for attempt in range(attempts):
            try:return self._send(op,data)
            except HTTPError as error:
                if error.code not in (429,502,503,504):raise RuntimeError(f'Dashboard rejected {op}: HTTP {error.code}') from None
            except (URLError,TimeoutError):
                if op=='claim':raise # Lease.claim owns its idempotent retry loop.
            if attempt+1==attempts:raise DashboardTransportError(f'Dashboard {op} transport failed after {attempts} attempt(s); outcome may be unconfirmed') from None
            time.sleep(attempt+1)

    def _send(self,op,data):
        body = json.dumps({'op': op, **data}, separators=(',', ':')).encode()
        parsed = urlsplit(self.url)
        path = parsed.path + ('?' + parsed.query if parsed.query else '')
        now, nonce = int(time.time()), uuid.uuid4().hex
        headers = {'Content-Type': 'application/json', 'X-Scotus-Time': str(now),
                   'X-Scotus-Nonce': nonce, 'X-Scotus-Role': self.role,
                   'X-Scotus-Signature': signature(self.key, now, nonce, 'POST', path, body)}
        with urlopen(Request(self.url, body, headers), timeout=10) as response:
            value = json.loads(response.read(2 * 1024 * 1024 + 1))
        if not value.get('ok'):
            raise RuntimeError(value.get('error', 'Dashboard request failed'))
        return value.get('result')
