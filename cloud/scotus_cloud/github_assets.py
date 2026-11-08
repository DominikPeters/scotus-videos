"""Publish a new advocate portrait and provenance in one GitHub commit.

The enrichment agent returns data; a separate publisher obtains the repository
credential. No repository token or signing key is passed to Codex.
"""

import base64
import hashlib
import json
import re
from urllib.parse import quote, urlsplit

from .connections import GITHUB_REPOSITORY, github_headers, github_token, provider_request


def portrait_files(person_id, extension, image, provenance):
    if not re.fullmatch('[a-z][a-z0-9_]{1,100}', person_id) or extension not in ('jpg', 'png', 'webp'):
        raise ValueError('Invalid portrait path')
    valid = (extension == 'jpg' and image.startswith(b'\xff\xd8\xff') or
             extension == 'png' and image.startswith(b'\x89PNG\r\n\x1a\n') or
             extension == 'webp' and image.startswith(b'RIFF') and image[8:12] == b'WEBP')
    if not valid or not 100 <= len(image) <= 4 * 1024 * 1024:
        raise ValueError('Invalid portrait file')
    if not isinstance(provenance, dict) or provenance.get('identity_verified') is not True or not provenance.get('name'):
        raise ValueError('A verified identity record is required')
    synthetic=provenance.get('kind')=='initials' and provenance.get('synthetic',{}).get('type')=='initials'
    for field in (('identity_source_url',) if synthetic else ('source_url','identity_source_url')):
        link = urlsplit(provenance.get(field, ''))
        if link.scheme != 'https' or not link.hostname or link.username:
            raise ValueError('Document the portrait and identity sources')
    if not re.fullmatch(r'\d{2}(?:-\d+|[A-Z]\d+)', provenance.get('docket', '')):
        raise ValueError('Include the docket used to disambiguate this advocate')
    record = {**provenance, 'sha256': hashlib.sha256(image).hexdigest()}
    metadata = (json.dumps(record, indent=2, ensure_ascii=False) + '\n').encode()
    if len(metadata) > 16384:
        raise ValueError('Portrait provenance is too large')
    return {f'advocates/{person_id}.{extension}': image, f'advocates/{person_id}.source.json': metadata}


def commit_portrait(credential, person_id, extension, image, provenance, branch=None, *, approved_replacement=False):
    """Save a portrait; replacement authority comes from an owner-approved candidate."""
    files = portrait_files(person_id, extension, image, provenance)
    if credential.get('repository') != GITHUB_REPOSITORY:
        raise ValueError('Unsupported repository or branch')
    headers = github_headers(github_token(credential))
    root = 'https://api.github.com/repos/' + GITHUB_REPOSITORY
    def request(method, endpoint, **kwargs):
        return provider_request(method, root + endpoint, headers=headers, **kwargs)
    branch = branch or request('GET', '')['default_branch']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9/_-]{0,100}', branch) or '..' in branch:
        raise ValueError('Unsupported branch')
    head = request('GET', '/git/ref/heads/' + quote(branch, safe=''))['object']['sha']
    commit = request('GET', '/git/commits/' + head)
    tree = request('GET', '/git/trees/' + commit['tree']['sha'], params={'recursive': '1'},_max_response_bytes=1048576)
    if tree.get('truncated'):
        raise ValueError('Repository tree is incomplete')
    existing = {item['path']: item['sha'] for item in tree['tree']}
    blob_hash = lambda data: hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    changed = {path: data for path, data in files.items() if existing.get(path) != blob_hash(data)}
    if not changed:
        return {'commit': head, 'already_saved': True}
    if not approved_replacement and any(path in existing for path in files):
        raise ValueError('A portrait or provenance already exists; preserve it for review')
    entries = []
    for path, data in changed.items():
        blob = request('POST', '/git/blobs', json={'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
        entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
    result = request('POST', '/git/trees', json={'base_tree': commit['tree']['sha'], 'tree': entries})
    action = 'Update' if any(path in existing for path in files) else 'Add'
    created = request('POST', '/git/commits', json={'message': action + ' advocate portrait: ' + person_id,
                      'tree': result['sha'], 'parents': [head]})
    # A concurrent update rejects this non-fast-forward update; never force-push.
    request('PATCH', '/git/refs/heads/' + quote(branch, safe=''), json={'sha': created['sha'], 'force': False})
    return {'commit': created['sha'], 'url': 'https://github.com/' + GITHUB_REPOSITORY + '/commit/' + created['sha']}
