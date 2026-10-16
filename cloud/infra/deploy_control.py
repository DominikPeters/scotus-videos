"""Deploy the small control service; never upload media, models or auth files.

Private runtime config is added directly to Secret Manager, outside build context.
The expensive video-worker images are separate and are not launched here.
"""

from registry_cleanup import refresh as refresh_registry
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('phase', choices=['setup', 'build', 'status', 'deploy'])
    cli.add_argument('--config', type=Path, required=True)
    cli.add_argument('--state', type=Path, required=True)
    cli.add_argument('--gcloud', default='gcloud')
    args = cli.parse_args()
    config = json.loads(args.config.read_text())
    project = config['project']; region = config['region']
    state = json.loads(args.state.read_text()) if args.state.exists() else {}
    name = 'scotus-video-control'; repo = 'scotus-videos'; bucket = project + '-scotus-control-build'
    service = name + '@' + project + '.iam.gserviceaccount.com'
    builder = 'scotus-video-builder@' + project + '.iam.gserviceaccount.com'
    image = region + '-docker.pkg.dev/' + project + '/' + repo + '/control:latest'

    def save():
        args.state.write_text(json.dumps(state, indent=2) + '\n')

    def call(*command, parse=False, optional=False):
        result = subprocess.run([args.gcloud, *command, '--project=' + project, '--quiet',
                                 *(['--format=json'] if parse else [])], capture_output=True, text=True, timeout=180)
        if result.returncode:
            if optional: return None
            raise RuntimeError('gcloud operation failed: ' + result.stderr[-1500:])
        return json.loads(result.stdout) if parse else result.stdout

    if args.phase == 'setup':
        call('services', 'enable', 'run.googleapis.com', 'cloudbuild.googleapis.com',
             'artifactregistry.googleapis.com', 'secretmanager.googleapis.com')
        for account in ('scotus-video-control', 'scotus-video-builder'):
            email = account + '@' + project + '.iam.gserviceaccount.com'
            if call('iam', 'service-accounts', 'describe', email, optional=True) is None:
                call('iam', 'service-accounts', 'create', account)
        if call('artifacts', 'repositories', 'describe', repo, '--location=' + region, optional=True) is None:
            call('artifacts', 'repositories', 'create', repo, '--location=' + region, '--repository-format=docker')
        if call('storage', 'buckets', 'describe', 'gs://' + bucket, optional=True) is None:
            call('storage', 'buckets', 'create', 'gs://' + bucket, '--location=' + region,
                 '--uniform-bucket-level-access', '--public-access-prevention', '--soft-delete-duration=0s')
        for role in ('roles/storage.objectAdmin', 'roles/storage.legacyBucketReader'):
            call('storage', 'buckets', 'add-iam-policy-binding', 'gs://' + bucket,
                 '--member=serviceAccount:' + builder, '--role=' + role)
        call('artifacts', 'repositories', 'add-iam-policy-binding', repo, '--location=' + region,
             '--member=serviceAccount:' + builder, '--role=roles/artifactregistry.writer')
        for secret in ('scotus-video-control-config', *config['secrets'].values()):
            if call('secrets', 'describe', secret, optional=True) is None:
                call('secrets', 'create', secret, '--replication-policy=automatic')
        call('secrets', 'versions', 'add', 'scotus-video-control-config', '--data-file=' + str(args.config.resolve()))
        call('secrets', 'add-iam-policy-binding', 'scotus-video-control-config',
             '--member=serviceAccount:' + service, '--role=roles/secretmanager.secretAccessor')
        for secret in config['secrets'].values():
            for role in ('roles/secretmanager.viewer', 'roles/secretmanager.secretVersionAdder'):
                call('secrets', 'add-iam-policy-binding', secret, '--member=serviceAccount:' + service, '--role=' + role)
        for name in ('youtube_client', 'github', 'instagram_client'):
            if name in config['secrets']:
                call('secrets', 'add-iam-policy-binding', config['secrets'][name], '--member=serviceAccount:' + service,
                     '--role=roles/secretmanager.secretAccessor')
        state.update({'project': project, 'region': region, 'image': image, 'service': name,
                      'build_bucket': bucket, 'builder': builder, 'service_account': service})
        save(); print('Control resources ready; no video jobs started.')
    elif args.phase == 'build':
        if state.get('build_id'): raise ValueError('Build already submitted; use status')
        with tempfile.TemporaryDirectory(prefix='scotus-control-context-') as directory:
            context = Path(directory); source = Path(__file__).resolve().parents[1]
            shutil.copy2(source / 'Dockerfile.control', context / 'Dockerfile')
            shutil.copy2(source / 'requirements-control.txt', context)
            (context / 'scotus_cloud').mkdir()
            for file in ('__init__.py', 'control.py', 'google.py', 'model.py', 'remote.py', 'connections.py','notifications.py','webpush.py','clip_control.py','statistics_control.py','recovery_control.py','recovery_evidence.py','diagnostics.py','repair_policy.py','discovery.py','enrichment.py','case_descriptions.py','editorial.py','codex_auth.py','podcast.py','chunk_cleanup.py','spotify.py'):
                shutil.copy2(source / 'scotus_cloud' / file, context / 'scotus_cloud' / file)
            size = sum(p.stat().st_size for p in context.rglob('*') if p.is_file())
            if size > 192 * 1024: raise ValueError('Control build source exceeds metered-transfer cap')
            result = call('builds', 'submit', str(context), '--tag=' + image, '--region=' + region,
                          '--timeout=300s', '--machine-type=e2-standard-2', '--async',
                          '--service-account=projects/' + project + '/serviceAccounts/' + builder,
                          '--gcs-source-staging-dir=gs://' + bucket + '/source',
                          '--gcs-log-dir=gs://' + bucket + '/logs', parse=True)
            state['build_id'] = result['id']; state['source_bytes'] = size
            save(); print(json.dumps({'build_id': result['id'], 'source_bytes': size, 'build_spend_cap_estimate_usd': .03}))
    elif args.phase == 'status':
        receipt = call('builds', 'describe', state['build_id'], '--region=' + region, parse=True)
        state['build_receipt'] = receipt; save(); print('Build:', receipt['status'])
    else:
        receipt = call('builds', 'describe', state['build_id'], '--region=' + region, parse=True)
        if receipt['status'] != 'SUCCESS': raise ValueError('Build not successful')
        refresh_registry(project, region, args.gcloud, [image.split(':')[0]+'@'+receipt['results']['images'][0]['digest']], apply=True)
        call('run', 'deploy', name, '--image=' + image.split(':')[0]+'@'+receipt['results']['images'][0]['digest'], '--region=' + region, '--service-account=' + service,
             '--cpu=1', '--memory=256Mi', '--min-instances=0', '--max-instances=1', '--concurrency=4',
             '--timeout=60s', '--cpu-throttling', '--allow-unauthenticated',
             '--set-secrets=/secrets/control/config.json=scotus-video-control-config:latest')
        refresh_registry(project, region, args.gcloud, apply=True)
        info = call('run', 'services', 'describe', name, '--region=' + region, parse=True)
        state['url'] = info['status']['url']; state['build_receipt'] = receipt; save()
        print(json.dumps({'control_url': state['url'], 'workers_enabled': config.get('workers_enabled', False)}))


if __name__ == '__main__': main()
