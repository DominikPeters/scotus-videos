"""Private scheduled Cloud Run job; its service account launches video stages."""
import json
import os
from pathlib import Path
from .control import dispatch
from .secret_store import runtime_settings
from .google import Google
from .remote import Dashboard

def main():
    if not os.environ.get('CLOUD_RUN_JOB'):
        raise SystemExit('The scheduled dispatcher runs on Cloud Run.')
    settings = runtime_settings('/secrets/control/config.json')
    dashboard = Dashboard(settings['dashboard_url'], settings['dispatcher_key'], 'dispatcher')
    result = dispatch(dashboard, Google(settings['project']), settings)
    print(json.dumps({'launched': len(result['launched'])}))

if __name__ == '__main__': main()
