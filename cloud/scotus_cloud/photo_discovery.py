"""Find saved advocate portraits in the repository's current default branch."""
import json
import re
import unicodedata
from pathlib import PurePosixPath

REPOSITORY = 'DominikPeters/scotus-videos'
ARCHIVE_URL = f'https://api.github.com/repos/{REPOSITORY}/contents/advocates'


def name_key(name, omit_initials=False):
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    words = re.findall(r'[a-z0-9]+', name)
    if omit_initials:
        words = [word for i, word in enumerate(words) if i in (0, len(words)-1) or len(word) != 1]
    return ''.join(words)


def archive_listing(fetch):
    # Omitting ref asks GitHub for the current default branch, not a build-time pin.
    entries = json.loads(fetch(ARCHIVE_URL, 2097152))
    if not isinstance(entries, list) or len(entries) >= 1000:
        raise ValueError('The advocate archive listing is unavailable or incomplete; retry before searching for new photos.')
    return {entry['name']: entry for entry in entries if entry.get('type') == 'file'}


def saved_portrait(name, entries, fetch, excluded_urls=()):
    matches = []
    for filename, entry in entries.items():
        path = PurePosixPath(filename)
        if path.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            continue
        stem = re.sub(r'^advocate_\d{2}_(?:\d+|[a-z]\d+)_', '', path.stem)
        label = stem.replace('_', ' ')
        if name_key(label) == name_key(name):
            rank = 0
        elif name_key(label, True) == name_key(name, True):
            rank = 1
        else:
            continue
        matches.append((rank, filename.startswith('advocate_'), filename, label))
    if not matches:
        return None
    matches.sort()
    # Missing middle initials are useful aliases only when they identify one name.
    if matches[0][0] and len({name_key(m[3]) for m in matches}) > 1:
        return None
    for _, _, filename, _ in matches:
        entry = entries[filename]
        uri = entry['download_url']
        sidecar = entries.get(PurePosixPath(filename).stem + '.source.json')
        metadata = json.loads(fetch(sidecar['download_url'], 65536)) if sidecar else {}
        if metadata.get('name') and name_key(metadata['name'], True) != name_key(name, True):
            continue
        source = metadata.get('source_url') or uri
        if uri in excluded_urls or source in excluded_urls:
            continue
        return {'name': name, 'uri': uri, 'kind': metadata.get('kind', 'photo'),
                'source_url': source, 'identity_source_url': metadata.get('identity_source_url') or
                f'https://github.com/{REPOSITORY}/blob/HEAD/advocates/{filename}'}
    return None
