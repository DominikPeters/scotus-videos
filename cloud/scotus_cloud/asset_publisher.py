"""Publish owner-approved portraits separately from private Codex research."""
import hashlib,json,os
from pathlib import Path
from .google import Google
from .remote import Dashboard
from .github_assets import commit_portrait


def main():
    if not os.environ.get('CLOUD_RUN_JOB'):raise RuntimeError('Cloud asset publisher only')
    settings=json.loads(Path('/secrets/assets/config.json').read_text())
    dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'assets');cloud=Google(settings['project'])
    context=dashboard.call('asset_publish_claim',job=os.environ['SCOTUS_JOB_ID'],dispatch_token=os.environ['SCOTUS_ASSET_TOKEN'])
    if not context:return
    job=context['job'];token=dashboard.call('auth_claim',name='github')
    if not token:raise RuntimeError('GitHub credentials are in use')
    results=[];success=False
    try:
        credential=json.loads(cloud.secret(settings['github_secret']))
        for person,candidate in job.get('approved_photos',{}).items():
            if candidate.get('origin')=='curated_cache':continue
            image=cloud.storage_bytes(candidate['portrait_uri'],max_bytes=4194304)
            if hashlib.sha256(image).hexdigest()!=candidate['sha256']:raise ValueError('Approved image changed')
            if not candidate.get('source_url') and candidate.get('kind')!='initials':continue
            name=job['review']['photos'][person]['name']
            provenance={'identity_verified':True,'name':name,'docket':job['docket'],'source_url':candidate.get('source_url',''),
                'identity_source_url':candidate.get('identity_source_url') or f'https://www.supremecourt.gov/docket/docketfiles/html/public/{job["docket"]}.html',
                'kind':candidate['kind'],'approval':'owner dashboard approval','recording':job['id']}
            provenance.update({key:candidate[key] for key in ('source_sha256','crop') if key in candidate})
            if candidate['kind']=='initials':provenance['synthetic']={'type':'initials','text':candidate['initials'],'renderer':'deterministic typography'}
            extension='jpg' if image.startswith(b'\xff\xd8') else 'png'
            result=commit_portrait(credential,person,extension,image,provenance)
            results.append({'person':person,**result})
        success=True
    finally:
        dashboard.call('auth_release',name='github',token=token)
        dashboard.call('asset_publish_finish',job=job['id'],lease=context['lease'],success=success,results=results)

if __name__=='__main__':main()
