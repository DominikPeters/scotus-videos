"""Apply a checked, stage-scoped code release before importing a media worker."""
import hashlib
import json
import os
from pathlib import Path

from .secret_store import runtime_settings
from .google import Google
from .model import digest_json
from .repair_policy import file_stages,baseline_files,verify_release
from .releases import image_release,image_source


def apply_release(release, root, stage):
    root=Path(root)
    record=image_release(root)
    verify_release(image_source(root),release,record['id'] if record else None)
    if release.get('schema_version') not in (1,2):
        raise ValueError('Invalid workflow release')
    for name,text in release['files'].items():
        stages=file_stages(name)
        if stages is None:raise ValueError('Invalid workflow path')
        if stages and stage not in stages: continue
        if not isinstance(text,str) or len(text.encode())>100000: raise ValueError('Invalid workflow file')
        target=root/name
        if any(root.joinpath(*Path(name).parts[:i]).is_symlink() for i in range(1,len(Path(name).parts)+1)): raise ValueError('Unexpected workflow path')
        if release.get('schema_version')==2:
            from .repair_policy import file_hash
            actual=file_hash(target.read_text()) if target.is_file() else None
            if actual!=release['base_files'][name]:raise ValueError('Edited source changed; retest this repair')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(text)


def main():
    if not os.environ.get('CLOUD_RUN_JOB'): raise RuntimeError('Cloud workers only')
    uri=os.environ.get('SCOTUS_WORKFLOW_RELEASE_URI')
    if uri:
        settings=runtime_settings('/secrets/worker/config.json')
        google=Google(settings['project'])
        release=google.storage_json(uri,max_bytes=262144)
        if digest_json(release)!=os.environ.get('SCOTUS_WORKFLOW_RELEASE_SHA256'):
            raise ValueError('Workflow release hash differs')
        # This pointer is supplied by the controller after isolated tests pass.
        apply_release(release,'/app',os.environ['SCOTUS_STAGE'])
    from .worker import main as run_worker
    run_worker()


if __name__=='__main__': main()
