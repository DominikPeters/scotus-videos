"""Launch explicitly selected clip work and issue short-lived private downloads."""
import base64,hashlib
from datetime import datetime,timezone
from urllib.parse import quote,urlencode
from .google import split_gs


def dispatch_clip(dashboard,google,settings,job,clip):
    if not settings.get('clip_job'):raise ValueError('Clip worker is not configured')
    context=dashboard.call('clip_context',job=job,clip=clip);item=context['clip']
    tiktok=item['status'].startswith('tiktok_') or (item.get('mode','').startswith('tiktok_') and item['status'] in ('starting','uploading'))
    instagram=item['status'].startswith('instagram_') or (item.get('mode')=='instagram_publish' and item['status'] in ('starting','uploading'))
    worker=settings.get('instagram_clip_job') if instagram else settings.get('tiktok_job') if tiktok else settings['clip_job']
    if not worker:raise ValueError('Clip destination worker is not configured')
    if item.get('operation') and item['status'] in ('starting','rendering','uploading'):
        if google.operation_status(item['operation'])['done']:dashboard.call('clip_closed',job=job,clip=clip,operation=item['operation'])
        return {'status':'active'}
    claim=dashboard.call('clip_dispatch',job=job,clip=clip)
    if not claim:return {'status':item['status']}
    operation=google.execute(settings['region'],worker,{'SCOTUS_JOB_ID':job,'SCOTUS_CLIP_ID':clip,'SCOTUS_CLIP_TOKEN':claim['token']})
    dashboard.call('clip_dispatched',job=job,clip=clip,operation=operation)
    return {'status':'starting'}


def download_url(dashboard,google,settings,job,clip):
    item=dashboard.call('clip_context',job=job,clip=clip)['clip']
    uri=item.get('result',{}).get('video_uri')
    if not uri:raise ValueError('Clip is not ready')
    bucket,key=split_gs(uri)
    if bucket!=settings['bucket'] or not key.startswith(f'clips/{job}/{clip}/'):raise ValueError('Unexpected clip object')
    return signed_media_url(google,settings['clip_signer'],uri,900,clip+'.mp4')


def signed_media_url(google,signer,uri,expires=3600,filename=None):
    bucket,key=split_gs(uri)
    now=datetime.now(timezone.utc);date=now.strftime('%Y%m%d');stamp=now.strftime('%Y%m%dT%H%M%SZ');scope=date+'/auto/storage/goog4_request'
    params={'X-Goog-Algorithm':'GOOG4-RSA-SHA256','X-Goog-Credential':signer+'/'+scope,'X-Goog-Date':stamp,'X-Goog-Expires':str(expires),'X-Goog-SignedHeaders':'host'}
    if filename:params['response-content-disposition']=f'attachment; filename="{filename}"'
    query=urlencode(sorted(params.items()),quote_via=quote,safe='');pathname='/'+quote(bucket+'/'+key,safe='/')
    canonical='GET\n'+pathname+'\n'+query+'\nhost:storage.googleapis.com\n\nhost\nUNSIGNED-PAYLOAD'
    signed='GOOG4-RSA-SHA256\n'+stamp+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()
    result=google.request('POST','https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/'+quote(signer,safe='')+':signBlob',json={'payload':base64.b64encode(signed.encode()).decode()})
    return {'url':'https://storage.googleapis.com'+pathname+'?'+query+'&X-Goog-Signature='+base64.b64decode(result['signedBlob']).hex(),'expires_seconds':expires}
