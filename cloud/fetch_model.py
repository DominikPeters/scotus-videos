"""Cloud-build-only download; never run this on the metered desktop."""
import os
import json
import hashlib
from pathlib import Path
from huggingface_hub import snapshot_download

if not Path('/.dockerenv').exists() or os.environ.get('SCOTUS_ALLOW_MODEL_DOWNLOAD') != '1':
    raise SystemExit('Model download is allowed only inside the cloud image build.')
manifest = json.loads(Path('/app/model-files.json').read_text())
root = Path('/opt/english-model')
snapshot_download(manifest['model'], revision=manifest['revision'], local_dir=root,
                  allow_patterns=[item['file'] for item in manifest['files']])
for item in manifest['files']:
    file = root / item['file']; digest = hashlib.sha256()
    with file.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''): digest.update(chunk)
    if file.stat().st_size != item['bytes'] or digest.hexdigest() != item['sha256']:
        raise SystemExit('Pinned checkpoint hash differs: ' + item['file'])
