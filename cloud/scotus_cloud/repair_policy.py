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
    **{f'scotus_cloud/{name}.py':['enrich'] for name in ('card_pipeline','card_library','card_mcp','card_ocr','card_sheets','claude_runner','research_errors','case_descriptions','editorial','photo_discovery')},
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
    'render/subscribe.js': ['plan','render'],
    'render/intro.js': ['plan','render'],
    **{f'presentation/renderer/{name}':['plan','render'] for name in ('index.html','script.js','vertical.html')},
    'presentation/sources.json':['plan','render'],
}

# Tests for authority, credentials and publication remain independent of the
# candidate patch. Ordinary workflow tests can be corrected along with the bug.
PROTECTED_TESTS = {'test_recovery_capabilities.py','test_recovery_support.py','test_managed_secrets.py',
 'test_secret_store.py','test_secret_cleanup.py','test_upload_recovery.py','test_repair_rebase.py',
 'test_recovery_evidence.py','test_recovery_policy.py','test_editorial.py','test_recovery_transport.py','test_claude_runner.py','test_recovery_media.py','test_recovery_deadline.py'}


def file_stages(name,baseline=None):
    if name in EDITABLE:return EDITABLE[name]
    if re.fullmatch(r'tests/test_[a-z][a-z0-9_]{0,70}\.(?:py|cjs|js)',name) and Path(name).name not in PROTECTED_TESTS:return []
    if re.fullmatch(r'tests/[a-z][a-z0-9_-]{0,70}\.cjs',name) and baseline and name in baseline:return []
    match=re.fullmatch(r'scotus_cloud/repair_ext/(prepare|enrich|align|plan|render|assemble|upload)_[a-z][a-z0-9_]{0,60}\.py',name)
    return [match[1]] if match else None


def changed_files(workspace,baseline):
    root=Path(workspace);names=set(EDITABLE)
    names.update(str(p.relative_to(root)) for folder in ('tests','scotus_cloud/repair_ext') for p in (root/folder).glob('*') if p.suffix in ('.py','.js','.cjs'))
    return {name:(root/name).read_text() for name in names if (root/name).is_file() and
            file_stages(name,baseline) is not None and (root/name).read_text()!=baseline.get(name)}


def file_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def baseline_files(root):
    root=Path(root)
    files={str(path.relative_to(root)):path.read_text() for directory in ('scotus_cloud','render','prompts','schemas','tests','presentation')
            for path in (root/directory).rglob('*') if path.is_file() and path.suffix in ('.py','.js','.cjs','.mjs','.json','.md','.php','.html')
            and '__pycache__' not in path.parts and path.stat().st_size<=100000}
    for name in ('editorial-profile.json','speaker-catalog.json','advocate-catalog.json'):
        if (root/name).is_file():files[name]=(root/name).read_text()
    return files


def validate_changes(baseline, changed, release_id=None):
    if not isinstance(changed,dict) or not changed:
        raise ValueError('Provide relevant workflow and regression-test files')
    for name,text in changed.items():
        if file_stages(name,baseline) is None or not isinstance(text,str) or len(text.encode())>100000:
            raise ValueError('Protected or unknown workflow file')
        if name.endswith('.py'): ast.parse(text)
    if sum(len(text.encode()) for text in changed.values())>256*1024:
        raise ValueError('Workflow patch is too large')
    presentation=[name for name in changed if name.startswith('presentation/renderer/')]
    if presentation:
        if 'presentation/sources.json' not in changed:raise ValueError('Renderer fixes need their matching presentation source manifest')
        manifest=json.loads(changed['presentation/sources.json'])
        for name in presentation:
            if manifest.get(name.removeprefix('presentation/'),{}).get('sha256')!=file_hash(changed[name]):
                raise ValueError('Renderer source manifest differs from the candidate fix')
    common={'files':changed,'stages':sorted({stage for name in changed for stage in file_stages(name,baseline)})}
    if release_id:
        return {'schema_version':2,'release_id':release_id,'base_files':{name:file_hash(baseline[name]) if name in baseline else None for name in changed},**common}
    return {'schema_version':1,'baseline_sha256':digest_json(baseline),**common}


def verify_release(baseline, release, release_id=None):
    if release.get('schema_version')==2:
        if not release_id or release['release_id']!=release_id:raise ValueError('Repair belongs to a different worker release; retest it on the current release')
        expected=validate_changes(baseline,release['files'],release_id)
    else:expected=validate_changes(baseline,release['files'])
    if release!=expected: raise ValueError('Workflow release differs from its validated snapshot')
    return release


def reserve_estimate(cpu, memory_gib, seconds, tasks=1):
    if not 1<=cpu<=8 or not 0.5<=memory_gib<=32 or not 1<=seconds<=7200 or not 1<=tasks<=1000:
        raise ValueError('Invalid repair resource profile')
    # Twice us-central1 list-rate compute, with a small service/storage allowance.
    return round(2*(cpu*.000018+memory_gib*.000002)*seconds*tasks+.01,6)
