"""Load checksum-verified presentation sources retained from the local workflow."""
import hashlib,json
from pathlib import Path

PRESENTATION_ROOT=Path(__file__).resolve().parents[1]/'presentation'
RENDERER_ROOT=PRESENTATION_ROOT/'renderer'


def verified_source(name):
    records=json.loads((PRESENTATION_ROOT/'sources.json').read_text())
    text=(PRESENTATION_ROOT/name).read_text()
    if hashlib.sha256(text.encode()).hexdigest()!=records[name]['sha256']:
        raise ValueError('Presentation source checksum differs')
    return text
