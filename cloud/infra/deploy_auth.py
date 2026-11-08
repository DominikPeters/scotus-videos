"""Deploy the idle Codex sign-in job with a dedicated service account.

This does not start a login. The dashboard starts it only after a passkey sign-in
and an explicit click. The job has no model-turn or video permissions.
"""

try:
    from managed_secrets import run_gcloud
except ModuleNotFoundError:
    from infra.managed_secrets import run_gcloud
from registry_cleanup import refresh as refresh_registry
import argparse
import json
from pathlib import Path
import subprocess


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--build-state', type=Path, required=True)
    cli.add_argument('--config', type=Path, required=True)
    cli.add_argument('--gcloud', default='gcloud')
    args = cli.parse_args()
    build = json.loads(args.build_state.read_text()); config = json.loads(args.config.read_text())
    project = config['project']; region = build['region']; job = 'scotus-codex-signin'
    account = job + '@' + project + '.iam.gserviceaccount.com'
    controller = 'scotus-video-control@' + project + '.iam.gserviceaccount.com'
    def call(*command, optional=False, parse=False):
        result = run_gcloud([args.gcloud, *command, '--project=' + project, '--quiet', *(['--format=json'] if parse else [])],
                                capture_output=True, text=True, timeout=180)
        if result.returncode:
            if optional: return None
            raise RuntimeError(result.stderr[-1500:])
        return json.loads(result.stdout) if parse else result.stdout
    receipt = call('builds', 'describe', build['build_id'], '--region=' + region, parse=True)
    if receipt['status'] != 'SUCCESS': raise ValueError('Auth image build is not successful')
    digest = receipt['results']['images'][0]['digest']
    if call('iam', 'service-accounts', 'describe', account, optional=True) is None:
        call('iam', 'service-accounts', 'create', job)
    secret = 'scotus-codex-signin-config'
    if call('secrets', 'describe', secret, optional=True) is None:
        call('secrets', 'create', secret, '--replication-policy=automatic')
    call('secrets', 'versions', 'add', secret, '--data-file=' + str(args.config.resolve()))
    call('secrets', 'add-iam-policy-binding', secret, '--member=serviceAccount:' + account, '--role=roles/secretmanager.secretAccessor')
    call('secrets', 'add-iam-policy-binding', config['codex_secret'], '--member=serviceAccount:' + account, '--role=roles/secretmanager.secretVersionAdder')
    image = build['image'].split(':')[0] + '@' + digest
    refresh_registry(project, region, args.gcloud, [image], apply=True)
    call('run', 'jobs', 'deploy', job, '--image=' + image, '--region=' + region, '--service-account=' + account,
         '--tasks=1', '--parallelism=1', '--max-retries=0', '--task-timeout=900s', '--cpu=1', '--memory=512Mi',
         '--set-secrets=/secrets/login/config.json=' + secret + ':latest')
    refresh_registry(project, region, args.gcloud, apply=True)
    call('run', 'jobs', 'add-iam-policy-binding', job, '--region=' + region, '--member=serviceAccount:' + controller,
         '--role=roles/run.jobsExecutorWithOverrides')
    build.update({'image_digest': digest, 'job': job, 'service_account': account, 'build_receipt': receipt})
    args.build_state.write_text(json.dumps(build, indent=2) + '\n')
    print(json.dumps({'job': job, 'deployed': True, 'executed': False, 'max_runtime_seconds': 900}))


if __name__ == '__main__': main()
