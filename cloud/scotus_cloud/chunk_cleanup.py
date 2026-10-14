"""Remove receipt-listed encoded chunks only after a durable assembly checkpoint."""
import re,time,uuid
from urllib.parse import quote
from .google import split_gs


def object_url(uri):
    bucket,key=split_gs(uri)
    return f'https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(key,safe="")}'


def checked_uri(uri,bucket,job,stage,filename):
    actual,key=split_gs(uri)
    if actual!=bucket or not re.fullmatch(r'scratch/'+re.escape(job)+'/'+stage+r'/attempt-\d+/[a-f0-9]{32}/'+re.escape(filename),key):
        raise ValueError('Artifact outside the permitted cleanup scope')
    return object_url(uri)


def cleanup_completed_chunks(dashboard,google,settings,jobs):
    if not settings.get('chunk_cleanup_enabled'):return
    for job in jobs.values():
        if job['stages']['assemble']['status']!='complete' or job['stages']['render']['status']!='complete':continue
        saved=job['stages']['assemble'].get('result',{});record=job.get('chunk_cleanup',{})
        if record.get('final_uri')==saved.get('video_uri') and (record.get('status')=='complete' or record.get('retry_after',0)>time.time()):continue
        if not job['stages']['render'].get('tasks'):continue
        claim=dashboard.call('chunk_cleanup_claim',job=job['id'],claim_id=uuid.uuid4().hex)
        if not claim:continue
        job=claim['job'];record=claim['cleanup'];indices=[];error=None
        try:
            saved=job['stages']['assemble']['result']
            uploaded=job['stages'].get('upload',{})
            verified=saved.get('verification') or (uploaded.get('status')=='complete' and uploaded.get('result',{}).get('postprocessing_complete'))
            if not re.fullmatch('[a-f0-9]{64}',saved.get('sha256','')) or not verified or saved.get('frames')!=job['stages']['plan']['result'].get('frames'):
                raise ValueError('Verified assembly checkpoint required')
            url=checked_uri(saved['video_uri'],settings['bucket'],job['id'],'assemble','video.mp4')
            response=google.session.get(url,params={'fields':'size,generation'},timeout=5)
            if response.status_code!=200 or int(response.json().get('size',0))<=0:raise ValueError('Saved finished MP4 is unavailable')
            tasks=job['stages']['render']['tasks'];remaining=[(i,checked_uri(t['result']['video_uri'],settings['bucket'],job['id'],'render','chunk.mp4')) for i,t in enumerate(tasks) if i not in record.get('deleted_indices',[])]
            started=time.monotonic()
            for index,url in remaining[:64]:
                if time.monotonic()-started>=4:break
                response=google.session.delete(url,timeout=5)
                if response.status_code not in (204,404):raise RuntimeError('Chunk deletion HTTP '+str(response.status_code))
                indices.append(index)
        except Exception as failure:error=type(failure).__name__+': '+str(failure)[:200]
        result=dashboard.call('chunk_cleanup_result',job=job['id'],lease=record['lease'],final_uri=record['final_uri'],indices=indices,error=error)
        # Bound each controller pass; remaining chunks resume on the next pass.
        return {'job':job['id'],'batch_deleted':len(indices),'state':result}
