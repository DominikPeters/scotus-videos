"""Keep one recent image per package and protect deployed/running image digests.

Run with --apply after deployments to refresh protections. --protect accepts
additional pinned repair baseline images, or a new image before deployment.
Only metadata is fetched; no image layers are downloaded.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def refresh(project, region, gcloud='gcloud', protect=(), apply=False):
    def call(*args):
        result = subprocess.run([gcloud, *args, '--project='+project, '--format=json'],
                                capture_output=True, text=True, timeout=180)
        if result.returncode: raise RuntimeError(result.stderr[-2000:])
        return json.loads(result.stdout or 'null')

    prefix = f'{region}-docker.pkg.dev/{project}/scotus-videos/'
    images = set(protect)

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'image' and isinstance(item, str): images.add(item)
                else: collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)

    collect(call('run', 'jobs', 'list', '--region='+region))
    services = call('run', 'services', 'list', '--region='+region)
    collect(services)
    for service in services:
        for traffic in service.get('status', {}).get('traffic', []):
            if traffic.get('percent', 0) or traffic.get('tag'):
                revision = traffic.get('revisionName')
                if revision:
                    collect(call('run', 'revisions', 'describe', revision, '--region='+region))
    for execution in call('run', 'jobs', 'executions', 'list', '--region='+region):
        if not execution.get('status', {}).get('completionTime'): collect(execution)
    protected = sorted(image for image in images if image.startswith(prefix))
    if not protected or any('@sha256:' not in image for image in protected):
        raise ValueError('Expected deployed images pinned to immutable digests')
    policies = [
        {'name': 'delete-old', 'action': {'type': 'Delete'},
         'condition': {'tagState': 'any', 'olderThan': '86400s'}},
        {'name': 'keep-one-recent', 'action': {'type': 'Keep'},
         'mostRecentVersions': {'keepCount': 1}},
        {'name': 'keep-deployed-and-baselines', 'action': {'type': 'Keep'},
         'condition': {'tagState': 'any', 'versionNamePrefixes':
                       # Registry prefixes are limited to 64 characters. This
                       # retains 57 hexadecimal digest characters after sha256:.
                       sorted({image.split('@')[1][:64] for image in protected})}},
    ]
    if apply:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as file:
            json.dump(policies, file); file.flush()
            call('artifacts', 'repositories', 'set-cleanup-policies', 'scotus-videos',
                 '--location='+region, '--policy='+file.name, '--no-dry-run', '--quiet')
    return {'protected_images': protected, 'policies': policies, 'applied': apply}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--region', default='us-central1')
    parser.add_argument('--gcloud', default='gcloud')
    parser.add_argument('--protect', action='append', default=[])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(refresh(args.project, args.region, args.gcloud, args.protect, args.apply), indent=2))
