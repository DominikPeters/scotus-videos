"""Deploy manually selected TikTok clip transfers; starts no transfers."""
import argparse, json, re, subprocess


def controller_configuration(raw):
    config = json.loads(raw)
    if not {'dashboard_url', 'dispatcher_key', 'control_key'} <= config.keys():
        raise ValueError('Incomplete controller configuration; refusing to replace it')
    return config | {'tiktok_job': 'scotus-video-tiktok'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--region', default='us-central1')
    parser.add_argument('--gcloud', default='gcloud')
    parser.add_argument('--worker-image', required=True)
    parser.add_argument('--controller-image', required=True)
    args = parser.parse_args(); project = args.project
    for kind, image in [('tiktok', args.worker_image), ('control', args.controller_image)]:
        if not re.fullmatch(re.escape(f'{args.region}-docker.pkg.dev/{project}/scotus-videos/{kind}')+r'@sha256:[a-f0-9]{64}', image):
            raise ValueError('Use a pinned image in this project registry')

    def call(*parts, data=None):
        result = subprocess.run([args.gcloud, *parts, '--project='+project, '--quiet', '--format=json'],
                                input=data, capture_output=True, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else None

    control = call('run', 'services', 'describe', 'scotus-video-control', '--region='+args.region)
    signer = control['spec']['template']['spec']['serviceAccountName']
    uploader = call('run', 'jobs', 'describe', 'scotus-video-upload', '--region='+args.region)
    identity = uploader['spec']['template']['spec']['template']['spec']['serviceAccountName']
    call('run', 'jobs', 'deploy', 'scotus-video-tiktok', '--image='+args.worker_image,
         '--region='+args.region, '--service-account='+identity, '--cpu=2', '--memory=2Gi',
         '--task-timeout=600s', '--tasks=1', '--parallelism=1', '--max-retries=0',
         '--set-secrets=/secrets/worker/config.json=scotus-video-upload-config:latest')
    call('run', 'jobs', 'add-iam-policy-binding', 'scotus-video-tiktok', '--region='+args.region,
         '--member=serviceAccount:'+signer, '--role=roles/run.jobsExecutorWithOverrides')
    # `--format=json` formats gcloud's response wrapper, not the secret payload.
    raw = subprocess.run([args.gcloud, 'secrets', 'versions', 'access', 'latest',
                          '--secret=scotus-video-control-config', '--project='+project],
                         capture_output=True, check=True).stdout
    config = controller_configuration(raw)
    call('secrets', 'versions', 'add', 'scotus-video-control-config', '--data-file=-', data=json.dumps(config).encode())
    call('run', 'services', 'update', 'scotus-video-control', '--region='+args.region, '--image='+args.controller_image)
    print('TikTok worker and dispatch configured. No transfer started.')


if __name__ == '__main__': main()
