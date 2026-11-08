"""Prune obsolete SCOTUS secret versions without reading secret payloads.

One-time migration, dry-run by default. Keeps only the current enabled version.
Older explicit references must be migrated first. All discovery must succeed
before any destruction. No scheduled cleanup or rollback history.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess


def protected_versions(value, pins=None, aliases=None):
    pins = set() if pins is None else pins
    aliases = {} if aliases is None else aliases
    def add(secret, version):
        secret = secret.rsplit('/', 1)[-1]
        if version != 'latest':
            if not str(version).isdigit():
                raise ValueError('Unresolved Cloud Run secret alias: ' + str(version))
            pins.add((aliases.get(secret, secret), str(version)))
    if isinstance(value, dict):
        # Cloud Run places aliases in metadata, alongside the pod spec.
        if isinstance(value.get('metadata'), dict):
            for entry in value['metadata'].get('annotations', {}).get('run.googleapis.com/secrets', '').split(','):
                if entry:
                    alias, secret = entry.split(':', 1)
                    aliases = {**aliases, alias: secret.rsplit('/', 1)[-1]}
        annotation = value.get('annotations', {}).get('run.googleapis.com/secrets', '')
        local_aliases = dict(aliases)
        for entry in annotation.split(','):
            if entry:
                alias, secret = entry.split(':', 1)
                local_aliases[alias] = secret.rsplit('/', 1)[-1]
        ref = value.get('secretKeyRef')
        if ref:
            secret = ref.get('name') or ref.get('secret')
            add(secret, ref.get('key') or ref.get('version'))
        if 'secretName' in value:
            for item in value.get('items', []): add(value['secretName'], item['key'])
        for child in value.values(): protected_versions(child, pins, local_aliases)
    elif isinstance(value, list):
        for child in value: protected_versions(child, pins, aliases)
    return pins


def candidates(secret, versions, pins, empty=False):
    ordered = sorted(versions, key=lambda v: int(v['name'].rsplit('/', 1)[-1]), reverse=True)
    live = [v for v in ordered if v['state'] != 'DESTROYED']
    if not live:
        return []
    if empty:
        name = secret['name'].rsplit('/', 1)[-1]
        if (any(v['state'] == 'ENABLED' for v in live) or secret.get('versionAliases')
                or any(s == name for s, _ in pins)):
            raise ValueError('Cannot remove referenced or enabled temporary state: ' + name)
        return live
    current = ordered[0]
    if current['state'] != 'ENABLED':
        raise ValueError('Newest version is not enabled: ' + secret['name'])
    number = current['name'].rsplit('/', 1)[-1]
    name = secret['name'].rsplit('/', 1)[-1]
    referenced = {str(v) for v in secret.get('versionAliases', {}).values()}
    referenced.update(v for s, v in pins if s == name)
    if referenced - {number}:
        raise ValueError('Migrate older explicit references before cleanup: ' + name)
    return [v for v in live if v['name'] != current['name']]


def refresh(project, apply=False, gcloud='gcloud', empty_secrets=(), approved_plan=None):
    def call(*args):
        r = subprocess.run([gcloud, *args, '--project='+project, '--format=json', '--quiet'],
                           capture_output=True, text=True, timeout=180)
        if r.returncode:
            # Do not print command output, which may contain configuration values.
            raise RuntimeError('Cloud metadata/cleanup command failed: ' + ' '.join(args[:3]))
        if 'unreachable' in r.stderr.lower():
            raise RuntimeError('Cloud resource inventory is incomplete')
        return json.loads(r.stdout or 'null')
    if call('config', 'list').get('run', {}).get('region'):
        raise RuntimeError('Unset run/region before auditing all regions')
    services = call('run', 'services', 'list')
    jobs = call('run', 'jobs', 'list')
    regions = {r['metadata']['labels']['cloud.googleapis.com/location'] for r in services + jobs}
    pins = protected_versions(services + jobs)
    for region in sorted(regions):
        pins.update(protected_versions(call('run', 'revisions', 'list', '--region='+region)))
        executions = call('run', 'jobs', 'executions', 'list', '--region='+region)
        # Protect running executions, including jobs subsequently updated/deleted.
        pins.update(protected_versions([e for e in executions if not e.get('status', {}).get('completionTime')]))
    secrets = [s for s in call('secrets', 'list') if s['name'].rsplit('/', 1)[-1].startswith('scotus-')]
    def inventory(secret):
        return secret, call('secrets', 'versions', 'list', secret['name'].rsplit('/', 1)[-1])
    with ThreadPoolExecutor(max_workers=4) as pool:
        inventory_rows = list(pool.map(inventory, secrets))
    plan = []
    active = 0
    for secret, versions in inventory_rows:
        active += sum(v['state'] != 'DESTROYED' for v in versions)
        for version in candidates(secret, versions, pins, secret['name'].rsplit('/', 1)[-1] in empty_secrets):
            plan.append({'secret': secret['name'].rsplit('/', 1)[-1],
                         'version': version['name'].rsplit('/', 1)[-1], 'etag': version['etag']})
    summary = {'active_before': active, 'obsolete_versions': len(plan),
               'active_after': active-len(plan), 'pinned_versions': sorted(pins),
               'plan': plan, 'applied': apply}
    print(json.dumps(summary, indent=2), flush=True)
    if apply:
        if approved_plan is None:
            raise ValueError('Apply requires the reviewed --approved-plan JSON')
        approved = {(v['secret'], v['version'], v['etag']) for v in approved_plan['plan']}
        actual = {(v['secret'], v['version'], v['etag']) for v in plan}
        if actual != approved:
            raise ValueError('Inventory changed since approval; no versions destroyed')
        # ETags make concurrent state changes fail instead of destroying changed versions.
        for item in plan:
            call('secrets', 'versions', 'destroy', item['version'], '--secret='+item['secret'], '--etag='+item['etag'])
        print(json.dumps({'destroyed': len(plan)}), flush=True)
    return summary


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--project', required=True)
    cli.add_argument('--gcloud', default='gcloud')
    cli.add_argument('--apply', action='store_true')
    cli.add_argument('--approved-plan', help='Reviewed dry-run JSON required for --apply')
    cli.add_argument('--empty-secret', action='append', default=[], help='Explicitly retired temporary secret; must have no enabled versions or references')
    args = cli.parse_args()
    approved = None
    if args.approved_plan:
        with open(args.approved_plan) as file: approved = json.load(file)
    refresh(args.project, args.apply, args.gcloud, args.empty_secret, approved)
