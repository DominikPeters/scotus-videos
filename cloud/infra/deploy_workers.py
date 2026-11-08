"""Review/create idle worker jobs. This does not build images or execute jobs.

Private profile adds worker_keys and real pinned image digests to the example.
Run without --apply to review resource names, hardware and permissions first.
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
import tempfile

from sys import path
path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.model import STAGES


HARDWARE = {'prepare': ('2', '2Gi', '900s'), 'enrich': ('1','2Gi','2700s'), 'align': ('4', '8Gi', '1800s'),
            'plan': ('1', '1Gi', '900s'), 'render': ('4', '8Gi', '3600s'),
            'assemble': ('2', '8Gi', '1800s'), 'upload': ('1', '2Gi', '3600s')}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--profile', type=Path, required=True)
    cli.add_argument('--apply', action='store_true')
    cli.add_argument('--gcloud', default='gcloud')
    args = cli.parse_args()
    p = json.loads(args.profile.read_text())
    plan = [{'stage': s, 'job': 'scotus-video-' + s, 'cpu': HARDWARE[s][0],
             'memory': HARDWARE[s][1], 'timeout': HARDWARE[s][2],
             'parallelism': p.get('parallelism', 16) if s == 'render' else 1,
             'retries': 0, 'image': p['images'][s]} for s in STAGES]
    plan.append({**next(item for item in plan if item['stage']=='align'),
                 'job':'scotus-video-align-long','cpu':'8','identity_job':'scotus-video-align'})
    if p.get('delivery_job'):plan.append({**next(item for item in plan if item['stage']=='assemble'),'job':p['delivery_job'],'identity_job':'scotus-video-upload','timeout':'5400s'})
    if p.get('research_job'):plan.append({**next(item for item in plan if item['stage']=='prepare'),'job':p['research_job'],'identity_job':'scotus-video-enrich','timeout':'3600s'})
    if not args.apply:
        print(json.dumps({'region': p['region'], 'bucket': p['bucket'], 'jobs': plan,
                          'executions_started': 0}, indent=2)); return
    if any('@sha256:' not in p['images'][s] for s in STAGES):
        raise ValueError('Every image must use an immutable @sha256: digest')
    if any(not p.get('worker_keys', {}).get(s) for s in STAGES):
        raise ValueError('Private worker keys are required; never commit the private profile')

    def call(*command, optional=False):
        if command[:3]==('storage','buckets','add-iam-policy-binding') and not any(c.startswith('--condition=') for c in command):command=(*command,'--condition=None')
        r = run_gcloud([args.gcloud, *command, '--project=' + p['project'], '--quiet'],
                           capture_output=True, text=True, timeout=180)
        if r.returncode and not optional: raise RuntimeError(r.stderr[-1200:])
        return r.returncode == 0

    if not call('storage', 'buckets', 'describe', 'gs://' + p['bucket'], optional=True):
        call('storage', 'buckets', 'create', 'gs://' + p['bucket'], '--location=' + p['region'],
             '--uniform-bucket-level-access', '--public-access-prevention', '--soft-delete-duration=0s')
    refresh_registry(p['project'], p['region'], args.gcloud, [item['image'] for item in plan], apply=True)
    for item in plan:
        print('Provisioning '+item['job'],flush=True)
        stage = item['stage']; identity=item.get('identity_job',item['job']);sa = identity + '@' + p['project'] + '.iam.gserviceaccount.com'
        if not call('iam', 'service-accounts', 'describe', sa, optional=True):
            call('iam', 'service-accounts', 'create', item['job'])
        secret = item['job']+'-config' if item['job'] in (p.get('delivery_job'),p.get('research_job')) else identity + '-config'
        if not call('secrets', 'describe', secret, optional=True): call('secrets', 'create', secret, '--replication-policy=automatic')
        config = {k: p[k] for k in ('project', 'region', 'bucket', 'dashboard_url', 'youtube_secret', 'chunk_seconds')}
        config['worker_key'] = p['worker_keys'][stage]
        if item['job']==p.get('delivery_job'):
            config['upload_worker_key']=p['worker_keys']['upload']
        if item['job']==p.get('research_job'):
            config['enrich_worker_key']=p['worker_keys']['enrich']
        config.update({k:p[k] for k in ('codex_secret','title_history_uri','youtube_channel_id','playlists','linkedin_secret','annotation_cards_enabled') if k in p and (k!='linkedin_secret' or stage=='enrich' or item['job']==p.get('research_job'))})
        if stage=='enrich' or item['job']==p.get('research_job'):
            config.update({k:p[k] for k in ('claude_secret','annotation_cards_backend','annotation_cards_profile') if k in p})
        with tempfile.NamedTemporaryFile(mode='w') as file:
            json.dump(config, file); file.flush()
            call('secrets', 'versions', 'add', secret, '--data-file=' + file.name)
        call('secrets', 'add-iam-policy-binding', secret, '--member=serviceAccount:' + sa, '--role=roles/secretmanager.secretAccessor')
        call('storage', 'buckets', 'add-iam-policy-binding', 'gs://' + p['bucket'],
             '--member=serviceAccount:' + sa, '--role=roles/storage.objectViewer')
        call('storage', 'buckets', 'add-iam-policy-binding', 'gs://' + p['bucket'],
             '--member=serviceAccount:' + sa, '--role=roles/storage.objectCreator')
        if stage=='enrich':
            for role in ('roles/secretmanager.secretAccessor','roles/secretmanager.secretVersionAdder'):
                call('secrets','add-iam-policy-binding',p['codex_secret'],'--member=serviceAccount:'+sa,'--role='+role)
        if stage == 'upload':
            for role in ('roles/secretmanager.secretAccessor', 'roles/secretmanager.secretVersionAdder'):
                call('secrets', 'add-iam-policy-binding', p['youtube_secret'], '--member=serviceAccount:' + sa, '--role=' + role)
        call('run', 'jobs', 'deploy', item['job'], '--region=' + p['region'], '--image=' + item['image'],
             '--service-account=' + sa, '--cpu=' + item['cpu'], '--memory=' + item['memory'],
             '--task-timeout=' + item['timeout'], '--tasks=' + str(item['parallelism']), '--parallelism=' + str(item['parallelism']),
             '--max-retries=0','--command=python','--args=-m,scotus_cloud.repair_bootstrap', '--set-secrets=/secrets/worker/config.json=' + secret + ':latest',
             *(['--update-env-vars=SCOTUS_ALIGN_THREADS='+item['cpu']] if stage=='align' else []))
        control = 'scotus-video-control@' + p['project'] + '.iam.gserviceaccount.com'
        call('run', 'jobs', 'add-iam-policy-binding', item['job'], '--region=' + p['region'],
             '--member=serviceAccount:' + control, '--role=roles/run.jobsExecutorWithOverrides')
    refresh_registry(p['project'], p['region'], args.gcloud, apply=True)
    print(json.dumps({'jobs': {s: 'scotus-video-' + s for s in STAGES},
                      'alignment_long_job':'scotus-video-align-long','executions_started': 0}))


if __name__ == '__main__': main()
