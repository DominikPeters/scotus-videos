"""Submit a bounded Cloud Build with a curated, small source bundle."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('kind', choices=['worker', 'align', 'render', 'auth','pipeline'])
    cli.add_argument('--control-state', type=Path, required=True)
    cli.add_argument('--state', type=Path, required=True)
    cli.add_argument('--timeout', default='600s')
    cli.add_argument('--base-image',help='Reuse a pinned pipeline dependency image for a source-only refresh')
    cli.add_argument('--gcloud', default='gcloud')
    args = cli.parse_args()
    if args.state.exists(): raise ValueError('Build state exists; do not submit twice')
    config = json.loads(args.control_state.read_text()); source = Path(__file__).resolve().parents[1]
    image = config['region'] + '-docker.pkg.dev/' + config['project'] + '/scotus-videos/' + args.kind + ':latest'
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); shutil.copy2(source / ('Dockerfile.' + args.kind), root / 'Dockerfile')
        if args.base_image:
            import re
            if args.kind!='pipeline' or not re.fullmatch(r'us-central1-docker.pkg.dev/possible-cycle-237715/scotus-videos/pipeline@sha256:[a-f0-9]{64}',args.base_image):raise ValueError('Use a pinned existing pipeline image')
            (root/'Dockerfile').write_text('FROM '+args.base_image+'\nWORKDIR /app\nRUN rm -rf /app/scotus_cloud /app/render /app/legacy /app/presentation /app/prompts /app/schemas /app/tests\nCOPY scotus_cloud /app/scotus_cloud\nCOPY render /app/render\nCOPY presentation /app/presentation\nCOPY prompts /app/prompts\nCOPY schemas /app/schemas\nCOPY tests /app/tests\nCOPY speaker-catalog.json advocate-catalog.json editorial-profile.json /app/\nRUN python -m unittest discover -s tests -p test_*.py && node --check render/original.js\n')
        names = ('requirements-worker.txt',) if args.kind == 'auth' else ('requirements-worker.txt', 'speaker-catalog.json', 'fetch_model.py', 'model-files.json')
        for name in names:
            shutil.copy2(source / name, root / name)
        if args.kind == 'auth':
            (root / 'scotus_cloud').mkdir()
            for name in ('__init__.py', 'google.py', 'remote.py', 'codex_login.py'):
                shutil.copy2(source / 'scotus_cloud' / name, root / 'scotus_cloud' / name)
        else:
            shutil.copytree(source / 'scotus_cloud', root / 'scotus_cloud', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for name in ('render','presentation','prompts','schemas','tests'):
                shutil.copytree(source/name,root/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            for name in ('advocate-catalog.json','editorial-profile.json'):shutil.copy2(source/name,root/name)
        size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        if size > 1024 * 1024: raise ValueError('Build source exceeds small-transfer cap')
        command = [args.gcloud, 'builds', 'submit', str(root), '--project=' + config['project'],
                   '--region=' + config['region'], '--tag=' + image, '--timeout=' + args.timeout,
                   '--machine-type=e2-standard-2', '--async', '--quiet', '--format=json',
                   '--service-account=projects/' + config['project'] + '/serviceAccounts/' + config['builder'],
                   '--gcs-source-staging-dir=gs://' + config['build_bucket'] + '/source',
                   '--gcs-log-dir=gs://' + config['build_bucket'] + '/logs']
        r = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if r.returncode: raise RuntimeError(r.stderr[-1500:])
        result = json.loads(r.stdout)
        state = {'kind': args.kind, 'image': image, 'project': config['project'], 'region': config['region'],
                 'build_id': result['id'], 'source_bytes': size, 'timeout': args.timeout}
        args.state.write_text(json.dumps(state, indent=2) + '\n')
        print(json.dumps({'build_id': result['id'], 'source_bytes': size, 'timeout': args.timeout}))

if __name__ == '__main__': main()
