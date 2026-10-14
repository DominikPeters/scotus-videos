"""Read-only upload reconciliation in the credential-owning job."""
import json,os,tempfile
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import AuthorizedSession
from .google import Google
from .remote import Dashboard
from .youtube import inspect_upload


def main():
    settings=json.loads(Path('/secrets/worker/config.json').read_text());cloud=Google(settings['project'])
    dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'upload')
    job=dashboard.call('upload_audit_context',job=os.environ['SCOTUS_JOB_ID'],action_id=os.environ['SCOTUS_AUDIT_ACTION'])
    token=dashboard.call('auth_claim',name='youtube')
    if not token:raise RuntimeError('YouTube credentials are in use')
    original=None;credentials=None
    try:
        original=cloud.secret(settings['youtube_secret']);credentials=Credentials.from_authorized_user_info(json.loads(original))
        report=inspect_upload(AuthorizedSession(credentials),job,settings,cloud)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'report.json';target.write_text(json.dumps(report));cloud.storage_upload(target,os.environ['SCOTUS_AUDIT_REPORT'],'application/json')
    finally:
        try:
            if credentials and json.loads(credentials.to_json())!=json.loads(original):
                dashboard.call('auth_check',name='youtube',token=token);cloud.add_secret_version(settings['youtube_secret'],credentials.to_json().encode())
        finally:dashboard.call('auth_release',name='youtube',token=token)

if __name__=='__main__':main()
