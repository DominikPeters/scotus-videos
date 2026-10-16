"""Immutable repair boundaries and small workflow releases, without model-chosen commands."""
import ast
import hashlib
import json
import re
from pathlib import Path

from .model import digest_json


EDITABLE = {
    'scotus_cloud/prepare.py': ['prepare'],
    'scotus_cloud/source_io.py':['prepare'],
    'scotus_cloud/vendor/pdf.py': ['prepare'],
    'scotus_cloud/vendor/parser.py': ['prepare'],
    'scotus_cloud/alignment.py': ['align'],
    'scotus_cloud/vendor/speech_spans.py':['align'],
    'scotus_cloud/enrichment.py':['enrich'],
    'scotus_cloud/card_history.py':['enrich'],
    'scotus_cloud/annotation_cards.py':['enrich','plan'],
    'scotus_cloud/codex_tools.py':['enrich'],
    'scotus_cloud/photos.py':['enrich'],
    'scotus_cloud/photo_access.py':['enrich'],
    'scotus_cloud/bundle.py':['plan'],
    'scotus_cloud/youtube_transfer.py':['upload'],
    'scotus_cloud/model.py': ['plan'],
    'scotus_cloud/court_metadata.py':['plan'],
    'scotus_cloud/participation.py':['enrich','plan'],
    'scotus_cloud/presentation_data.py':['plan'],
    'scotus_cloud/assembly.py':['assemble'],
    'render/original.js': ['plan','render'],
    'render/progress.js': ['plan','render'],
}


def file_stages(name,baseline=None):
    if name in EDITABLE:return EDITABLE[name]
    if re.fullmatch(r'tests/test_repair_case_[a-z][a-z0-9_]{0,60}\.py',name) and (baseline is None or name not in baseline):return []
    match=re.fullmatch(r'scotus_cloud/repair_ext/(prepare|enrich|align|plan|render|assemble|upload)_[a-z][a-z0-9_]{0,60}\.py',name)
    return [match[1]] if match else None


def changed_files(workspace,baseline):
    root=Path(workspace);names=set(EDITABLE)
    names.update(str(p.relative_to(root)) for folder in ('tests','scotus_cloud/repair_ext') for p in (root/folder).glob('*.py'))
    return {name:(root/name).read_text() for name in names if (root/name).is_file() and
            file_stages(name,baseline) is not None and (root/name).read_text()!=baseline.get(name)}


def file_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def baseline_files(root):
    root=Path(root)
    files={str(path.relative_to(root)):path.read_text() for directory in ('scotus_cloud','render','prompts','schemas','tests','presentation')
            for path in (root/directory).rglob('*') if path.is_file() and path.suffix in ('.py','.js','.json','.md','.php','.html')
            and '__pycache__' not in path.parts and path.stat().st_size<=100000}
    for name in ('editorial-profile.json','speaker-catalog.json','advocate-catalog.json'):
        if (root/name).is_file():files[name]=(root/name).read_text()
    return files


def validate_changes(baseline, changed):
    if not isinstance(changed,dict) or not changed or len(changed)>12:
        raise ValueError('Provide one to twelve workflow files and new regression tests')
    for name,text in changed.items():
        if file_stages(name,baseline) is None or not isinstance(text,str) or len(text.encode())>100000:
            raise ValueError('Protected or unknown workflow file')
        if name.endswith('.py'): ast.parse(text)
    if sum(len(text.encode()) for text in changed.values())>256*1024:
        raise ValueError('Workflow patch is too large')
    return {'schema_version':1,'baseline_sha256':digest_json(baseline),'files':changed,
            'stages':sorted({stage for name in changed for stage in file_stages(name,baseline)})}


def verify_release(baseline, release):
    expected=validate_changes(baseline,release['files'])
    if release!=expected: raise ValueError('Workflow release differs from its validated snapshot')
    return release


def reserve_estimate(cpu, memory_gib, seconds, tasks=1):
    if not 1<=cpu<=8 or not 0.5<=memory_gib<=32 or not 1<=seconds<=7200 or not 1<=tasks<=1000:
        raise ValueError('Invalid repair resource profile')
    # Twice us-central1 list-rate compute, with a small service/storage allowance.
    return round(2*(cpu*.000018+memory_gib*.000002)*seconds*tasks+.01,6)
