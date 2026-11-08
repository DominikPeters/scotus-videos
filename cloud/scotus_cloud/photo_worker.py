"""Dedicated, bounded photo revisions that can run alongside alignment."""
import json,os,tempfile,threading
from pathlib import Path
from .secret_store import runtime_settings
from .google import Google
from .remote import Dashboard
from .photos import revise_photo

def main():
    if not os.environ.get('CLOUD_RUN_JOB'):raise RuntimeError('Cloud photo worker only')
    os.environ['SCOTUS_PRIVATE_CODEX_WORKER']='1'
    settings=runtime_settings('/secrets/worker/config.json')
    dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'enrich');cloud=Google(settings['project'])
    data={'job':os.environ['SCOTUS_JOB_ID'],'request':os.environ['SCOTUS_PHOTO_REQUEST'],'dispatch_token':os.environ['SCOTUS_PHOTO_TOKEN']}
    claim=dashboard.call('photo_claim',**data)
    if not claim:return
    data['lease']=claim['request']['lease'];stop=threading.Event();errors=[]
    def heartbeat():
        while not stop.wait(30):
            try:
                if dashboard.call('photo_heartbeat',**data) is not True:raise RuntimeError('Photo request cancelled')
            except Exception as error:errors.append(error);return
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='photo-revision-') as folder:
            candidates=revise_photo(claim['request'],claim['job'],settings,cloud,dashboard,Path(folder))
        if errors:raise RuntimeError('Photo request lease lost')
        dashboard.call('photo_finish',**data,candidates=candidates)
    except Exception as error:
        message=str(error)[:400] if isinstance(error,ValueError) else 'Photo revision could not be completed. Retry or add a hint.'
        try:dashboard.call('photo_fail',**data,message=message)
        except Exception:pass
        raise SystemExit('photo_revision_failed') from None
    finally:stop.set();thread.join(timeout=5)

if __name__=='__main__':main()
