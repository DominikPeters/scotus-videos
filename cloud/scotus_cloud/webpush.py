"""Web Push (RFC 8291 aes128gcm payloads, RFC 8292 VAPID) using only `cryptography`."""
import base64
import hashlib
import hmac
import json
import os
import struct
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _raw(public_key):
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _hkdf(salt, ikm, info, length):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b'\x01', hashlib.sha256).digest()[:length]


def generate_keys():
    """Return (private, public) VAPID keys as base64url strings for config files."""
    key = ec.generate_private_key(ec.SECP256R1())
    return b64(key.private_numbers().private_value.to_bytes(32, 'big')), b64(_raw(key.public_key()))


def _private_key(value):
    return ec.derive_private_key(int.from_bytes(unb64(value), 'big'), ec.SECP256R1())


def encrypt(payload, p256dh, auth, salt=None, sender=None):
    """Encrypt one record for a subscription's keys (RFC 8291 section 3.4)."""
    receiver = unb64(p256dh)
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    sender_raw = _raw(sender.public_key())
    secret = sender.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver))
    ikm = _hkdf(unb64(auth), secret, b'WebPush: info\x00' + receiver + sender_raw, 32)
    key = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    body = AESGCM(key).encrypt(nonce, payload + b'\x02', None)
    return salt + struct.pack('!IB', 4096, len(sender_raw)) + sender_raw + body


def vapid_header(endpoint, private_key, subject, now=None):
    parts = urlsplit(endpoint)
    claims = {'aud': f'{parts.scheme}://{parts.netloc}', 'exp': int(now or time.time()) + 12 * 3600, 'sub': subject}
    key = _private_key(private_key)
    signing = b64(json.dumps({'typ': 'JWT', 'alg': 'ES256'}).encode()) + '.' + b64(json.dumps(claims, separators=(',', ':')).encode())
    r, s = decode_dss_signature(key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
    token = signing + '.' + b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return f'vapid t={token}, k={b64(_raw(key.public_key()))}'


def send(subscription, payload, settings, ttl=86400, timeout=3):
    """POST one notification. Returns 'sent', 'gone' (subscription expired) or 'failed'."""
    body = encrypt(json.dumps(payload).encode(), subscription['p256dh'], subscription['auth'])
    headers = {'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream', 'TTL': str(ttl), 'Urgency': 'high',
               'Authorization': vapid_header(subscription['endpoint'], settings['private_key'], settings['subject'])}
    try:
        with urlopen(Request(subscription['endpoint'], body, headers, method='POST'), timeout=timeout) as response:
            return 'sent' if 200 <= response.status < 300 else 'failed'
    except HTTPError as error:
        return 'gone' if error.code in (404, 410) else 'failed'
    except OSError:
        return 'failed'
