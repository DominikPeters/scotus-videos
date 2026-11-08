"""Submit a bounded Cloud Build with a curated, small source bundle."""
import argparse
import json
from pathlib import Path
import shutil
import io
import tarfile
import subprocess
import tempfile
import uuid
from datetime import datetime,timezone

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('kind', choices=['worker', 'align', 'render', 'auth','pipeline','statistics','assets','clips','tiktok'])
    cli.add_argument('--statistics-repo',type=Path,help='Sibling scotusstats checkout supplying the shared core and taxonomies')
    cli.add_argument('--control-state', type=Path, required=True)
    cli.add_argument('--state', type=Path, required=True)
    cli.add_argument('--timeout', default='600s')
    cli.add_argument('--base-image',help='Reuse a pinned pipeline dependency image for a source-only refresh')
    cli.add_argument('--flatten-base',action='store_true',help='Flatten an existing pipeline dependency image that is near the layer-depth limit')
    cli.add_argument('--gcloud', default='gcloud')
    args = cli.parse_args()
    if args.flatten_base and (args.kind!='pipeline' or not args.base_image):raise ValueError('Flattening requires a pinned pipeline base')
    if args.state.exists(): raise ValueError('Build state exists; do not submit twice')
    config = json.loads(args.control_state.read_text()); source = Path(__file__).resolve().parents[1]
    image = config['region'] + '-docker.pkg.dev/' + config['project'] + '/scotus-videos/' + args.kind + ':latest'
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); shutil.copy2(source / ('Dockerfile.' + ('clips' if args.kind=='tiktok' else args.kind)), root / 'Dockerfile')
        if args.base_image:
            import re
            if args.kind!='pipeline' or not re.fullmatch(r'us-central1-docker.pkg.dev/possible-cycle-237715/scotus-videos/pipeline@sha256:[a-f0-9]{64}',args.base_image):raise ValueError('Use a pinned existing pipeline image')
            base=('FROM '+args.base_image+' AS dependencies\nFROM scratch\nCOPY --from=dependencies / /\nENV PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin PYTHONUNBUFFERED=1 PUPPETEER_SKIP_DOWNLOAD=true PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium OMP_NUM_THREADS=4 HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1\n' if args.flatten_base else 'FROM '+args.base_image+'\n')
            (root/'Dockerfile').write_text(base+'WORKDIR /app\nCOPY . /source-refresh/\nRUN rm -rf /app/scotus_cloud /app/render /app/legacy /app/presentation /app/prompts /app/schemas /app/tests /app/infra && cp -a /source-refresh/. /app/ && rm -rf /source-refresh && python infra/install_research_tools.py && python -m scotus_cloud.releases stamp /app && python -m unittest discover -s tests -p test_*.py && node --check render/original.js && node --check render/podcast.js\nENTRYPOINT [\"python\",\"-m\",\"scotus_cloud.repair_bootstrap\"]\n')
        names = () if args.kind in ('assets','clips','tiktok') else ('requirements-worker.txt',) if args.kind == 'auth' else ('requirements-worker.txt', 'speaker-catalog.json', 'fetch_model.py', 'model-files.json')
        for name in names:
            shutil.copy2(source / name, root / name)
        if args.kind in ('clips','tiktok'):
            (root/'scotus_cloud').mkdir();(root/'render').mkdir()
            for name in ('__init__.py','google.py','secret_store.py','remote.py','youtube.py','youtube_transfer.py','clip_worker.py','tiktok.py','instagram_clip.py','youtube_studio.py','clip_control.py','model.py','tiktok_pilot.py'):
                shutil.copy2(source/'scotus_cloud'/name,root/'scotus_cloud'/name)
            for name in ('original.js','progress.js','subscribe.js','intro.js','vertical.js','tiktok-draft.cjs'):shutil.copy2(source/'render'/name,root/'render'/name)
            shutil.copy2(source/'presentation/renderer/vertical.html',root/'vertical.html')
        elif args.kind == 'assets':
            (root/'scotus_cloud').mkdir()
            for name in ('__init__.py','google.py','secret_store.py','remote.py','connections.py','github_assets.py','asset_publisher.py'):
                shutil.copy2(source/'scotus_cloud'/name,root/'scotus_cloud'/name)
        elif args.kind == 'statistics':
            if args.statistics_repo is None:raise ValueError('Supply --statistics-repo for the shared statistics core')
            pipeline=args.statistics_repo/'data-pipeline'
            shutil.copy2(source/'requirements-control.txt',root/'requirements-control.txt')
            shutil.copytree(source/'scotus_cloud',root/'scotus_cloud',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            for name in ('stats_core.py','test_stats_core.py'):shutil.copy2(pipeline/name,root/name)
            shutil.copy2(source/'tests/test_statistics_worker.py',root/'test_statistics_worker.py')
            (root/'statistics').mkdir()
            for name in ('issues.json','legal-provisions.json'):shutil.copy2(pipeline/'scdb'/name,root/'statistics'/name)
            shutil.copy2(source/'prompts/statistics-opinions.md',root/'statistics/opinion-prompt.md')
            shutil.copy2(source/'prompts/reference/statistics-taxonomy.md',root/'statistics/statistics-taxonomy.md')
        elif args.kind == 'auth':
            (root / 'scotus_cloud').mkdir()
            for name in ('__init__.py', 'google.py','secret_store.py', 'remote.py', 'codex_login.py'):
                shutil.copy2(source / 'scotus_cloud' / name, root / 'scotus_cloud' / name)
        else:
            shutil.copytree(source / 'scotus_cloud', root / 'scotus_cloud', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for name in ('render','presentation','prompts','schemas','tests'):
                shutil.copytree(source/name,root/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            for name in ('advocate-catalog.json','editorial-profile.json'):shutil.copy2(source/name,root/name)
        if args.kind == 'pipeline':
            shutil.copy2(source/'claude-code-version.txt',root/'claude-code-version.txt')
            # Isolated runtime checks also exercise the deployment adapters.
            # Only source files are included; private profiles/state are excluded.
            (root/'infra').mkdir()
            for file in (source/'infra').glob('*.py'):shutil.copy2(file,root/'infra'/file.name)
        release_id='worker-'+datetime.now(timezone.utc).strftime('%Y%m%d')+'-'+uuid.uuid4().hex[:8]
        if args.kind=='pipeline':(root/'.workflow-release-id').write_text(release_id)
        manifest_path=None
        if args.kind=='pipeline':
            import sys
            sys.path.insert(0,str(source))
            from scotus_cloud.repair_policy import baseline_files
            manifest_path=args.state.with_suffix('.source.json').resolve()
            manifest_path.write_text(json.dumps(baseline_files(root),ensure_ascii=False))
        size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        if size > 3 * 1024 * 1024: raise ValueError('Build source exceeds uncompressed size cap')
        compressed=io.BytesIO()
        with tarfile.open(fileobj=compressed,mode='w:gz') as archive:archive.add(root,arcname='source')
        if len(compressed.getvalue())>1024*1024:raise ValueError('Compressed build source exceeds metered-transfer cap')
        command = [args.gcloud, 'builds', 'submit', str(root), '--project=' + config['project'],
                   '--region=' + config['region'], '--tag=' + image, '--timeout=' + args.timeout,
                   '--async', '--quiet', '--format=json',
                   '--service-account=projects/' + config['project'] + '/serviceAccounts/' + config['builder'],
                   '--gcs-source-staging-dir=gs://' + config['build_bucket'] + '/source',
                   '--gcs-log-dir=gs://' + config['build_bucket'] + '/logs']
        r = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if r.returncode: raise RuntimeError(r.stderr[-1500:])
        result = json.loads(r.stdout)
        state = {'kind': args.kind, 'image': image, 'project': config['project'], 'region': config['region'],
                 'build_id': result['id'], 'source_bytes': size, 'release_id':release_id if args.kind=='pipeline' else None, 'timeout': args.timeout,'source_manifest_path':str(manifest_path) if manifest_path else None}
        args.state.write_text(json.dumps(state, indent=2) + '\n')
        print(json.dumps({'build_id': result['id'], 'source_bytes': size, 'release_id':release_id if args.kind=='pipeline' else None, 'timeout': args.timeout}))

if __name__ == '__main__': main()
