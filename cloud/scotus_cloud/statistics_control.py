"""Reuse the controller tick: daily opinion checks and immediate alignment updates."""
import hashlib,json,requests

def dispatch_statistics(dashboard,google,settings):
    snapshot=dashboard.call('snapshot');saved=snapshot.get('statistics') or {}
    if saved.get('status') in ('starting','running') and saved.get('operation'):
        status=google.operation_status(saved['operation'])
        if status['done']:dashboard.call('stats_execution_closed',operation=saved['operation'])
    response=requests.get('https://scotusstats.com/podcast/alignment/index.json',timeout=10);response.raise_for_status()
    revision=hashlib.sha256(json.dumps(response.json(),sort_keys=True).encode()).hexdigest()
    claim=dashboard.call('stats_dispatch',index_revision=revision)
    if not claim:return
    try:
        operation=google.execute(settings['region'],settings['statistics_job'],{'SCOTUS_STATS_TOKEN':claim['token']})
        dashboard.call('stats_dispatched',token=claim['token'],operation=operation)
    except Exception as error:
        dashboard.call('stats_dispatch_failed',token=claim['token'],message=str(error)[:300]);raise
