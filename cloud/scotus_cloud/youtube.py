"""Resumable, unlisted uploads with durable sessions and credential write-back."""

import json
import re
from urllib.parse import urlsplit


class UploadError(RuntimeError):
    def __init__(self, category,detail=None):
        self.detail=detail
        super().__init__(category if not detail else f"{detail['operation']}: HTTP {detail['status']} ({', '.join(detail['reasons']) or 'unspecified'})")
        self.category = category


def response_error(response,operation,category='worker_failed'):
    # Keep only bounded reason codes, never raw response bodies or request URLs.
    try:errors=response.json().get('error',{}).get('errors',[])
    except (ValueError,AttributeError):errors=[]
    if not isinstance(errors,list):errors=[]
    reasons=[entry['reason'] for entry in errors if isinstance(entry,dict) and
             isinstance(entry.get('reason'),str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',entry['reason'])][:5]
    return UploadError(category,{'operation':operation,'status':response.status_code,'reasons':reasons})


def upload_video(path, job, settings, cloud, lease):
    saved = job['stages']['upload'].get('checkpoint', {})
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    from google.auth.exceptions import RefreshError
    token = lease.dashboard.call('auth_claim', name='youtube')
    if not token:
        raise UploadError('auth_required')
    lease.auth = ('youtube', token)
    original = None
    credentials = None
    secret = settings['youtube_secret']
    try:
        original = cloud.secret(secret)
        credentials = Credentials.from_authorized_user_info(json.loads(original))
        session = AuthorizedSession(credentials)
        if saved.get('video_id'):
            return postprocess(session, saved['video_id'], job, settings, cloud, lease, saved)
        interactions = cloud.storage_json(job['stages']['plan']['result']['interactions_uri'], max_bytes=1048576)
        total = path.stat().st_size
        url = saved.get('session_url')
        if not url and saved.get('creation_pending'):
            raise UploadError('upload_uncertain')
        if not url:
            # If the POST is accepted but its response is lost, do not create a
            # second video automatically on retry.
            lease.call('checkpoint', checkpoint={'creation_pending': True})
            response = session.post('https://www.googleapis.com/upload/youtube/v3/videos',
                params={'uploadType': 'resumable', 'part': 'snippet,status'},
                headers={'X-Upload-Content-Length': str(total), 'X-Upload-Content-Type': 'video/mp4'},
                json={'snippet': {'title': job.get('selected_title') or interactions['youtube_title'], 'categoryId': '25',
                                  'description': interactions['youtube_description']},
                      'status': {'privacyStatus': 'unlisted', 'selfDeclaredMadeForKids': False}}, timeout=60)
            if response.status_code not in (200, 201):
                raise UploadError('auth_required' if response.status_code in (401, 403) else 'upload_uncertain')
            url = response.headers['Location']
            lease.call('checkpoint', checkpoint={'session_url': url})
        from .youtube_transfer import transfer
        video = transfer(session,url,path,lease)
        video_id = video['id']
        # Persist identity before any later thumbnail/playlist operation.
        lease.call('checkpoint', checkpoint={'session_url': url, 'video_id': video_id})
        return postprocess(session, video_id, job, settings, cloud, lease, {'session_url': url, 'video_id': video_id})
    except RefreshError:
        raise UploadError('auth_required') from None
    finally:
        try:
            if credentials:
                updated = credentials.to_json().encode()
                if json.loads(updated) != json.loads(original):
                    lease.dashboard.call('auth_check', name='youtube', token=token)
                    cloud.add_secret_version(secret, updated)
        finally:
            lease.auth = None
            lease.dashboard.call('auth_release', name='youtube', token=token)


def api(session, method, resource, *, params=None, body=None, data=None, headers=None):
    response=session.request(method,'https://www.googleapis.com/youtube/v3/'+resource,
        params=params,json=body,data=data,headers=headers,timeout=60)
    if response.status_code>=400:
        raise UploadError('auth_required' if response.status_code in (401,403) else 'worker_failed')
    return response.json() if response.content else {}


def owned_channel(session, settings):
    channels=api(session,'GET','channels',params={'part':'id','mine':'true'})['items']
    expected=settings['youtube_channel_id']
    if expected not in {c['id'] for c in channels}:raise UploadError('auth_required')
    return expected


def pages(session,resource,params):
    while True:
        result=api(session,'GET',resource,params=params)
        yield from result.get('items',[])
        if not result.get('nextPageToken'):break
        params={**params,'pageToken':result['nextPageToken']}


def postprocess(session, video_id, job, settings, cloud, lease, checkpoint):
    """Reconcile side effects before inserts so interrupted retries stay idempotent."""
    from .formatters import timestamp_comment
    channel=owned_channel(session,settings)
    videos=api(session,'GET','videos',params={'part':'snippet,status','id':video_id}).get('items',[])
    if len(videos)!=1 or videos[0]['snippet']['channelId']!=channel:raise UploadError('upload_uncertain')
    interactions=cloud.storage_json(job['stages']['plan']['result']['interactions_uri'],max_bytes=1048576)
    def save(**fields):
        checkpoint.update(fields);lease.call('checkpoint',checkpoint=checkpoint.copy());lease.check()
    if not checkpoint.get('thumbnail_done'):
        thumbnail=cloud.storage_bytes(job['stages']['plan']['result']['thumbnail_uri'],max_bytes=2097152)
        from .youtube_transfer import thumbnail as send_thumbnail
        response=send_thumbnail(session,video_id,thumbnail)
        if response.status_code>=400:
            error=response_error(response,'thumbnail')
            save(last_error=error.detail)
            raise error
        save(thumbnail_done=True)
    term=str(interactions['term'])
    playlist=settings.get('playlists',{}).get(term)
    if not playlist:
        matches=[item for item in pages(session,'playlists',{'part':'snippet','mine':'true','maxResults':50}) if item['snippet']['title']=='OT '+term]
        if len(matches)>1:raise UploadError('worker_failed')
        if matches:playlist=matches[0]['id']
        else:
            # Same names, description and visibility as create_playlists.py.
            created=api(session,'POST','playlists',params={'part':'snippet,status'},body={'snippet':{'title':'OT '+term,'description':'Supreme Court oral arguments from October Term '+term},'status':{'privacyStatus':'public'}})
            playlist=created['id']
        save(playlist_id=playlist)
    if playlist and not checkpoint.get('playlist_done'):
        entries=list(pages(session,'playlistItems',{'part':'snippet','playlistId':playlist,'videoId':video_id,'maxResults':50}))
        if not entries:
            api(session,'POST','playlistItems',params={'part':'snippet'},body={'snippet':{'playlistId':playlist,'resourceId':{'kind':'youtube#video','videoId':video_id}}})
        save(playlist_done=True)
    elif not playlist:save(playlist_done=True,playlist_skipped=True)
    if not checkpoint.get('comment_done'):
        text=timestamp_comment(interactions)
        entries=pages(session,'commentThreads',{'part':'snippet','videoId':video_id,'maxResults':100,'textFormat':'plainText'})
        found=next((item for item in entries if item['snippet']['topLevelComment']['snippet'].get('authorChannelId',{}).get('value')==channel and item['snippet']['topLevelComment']['snippet'].get('textOriginal')==text),None)
        if not found:
            found=api(session,'POST','commentThreads',params={'part':'snippet'},body={'snippet':{'videoId':video_id,'topLevelComment':{'snippet':{'textOriginal':text}}}})
        save(comment_done=True,comment_id=found['id'])
    save(postprocessing_complete=True)
    return {'video_id':video_id,'video_url':'https://www.youtube.com/watch?v='+video_id,
            'privacy':'unlisted','postprocessing_complete':True,'title':videos[0]['snippet'].get('title',job.get('selected_title') or interactions['youtube_title']),'playlist_skipped':not bool(playlist)}


def apply_video_action(session,job,action,settings):
    if job['stages']['upload']['result']['video_id']!=action['video_id']:raise UploadError('upload_uncertain')
    if not job['stages']['upload']['result'].get('postprocessing_complete'):raise UploadError('worker_failed')
    if action['kind']=='publish':
        # YouTube enforces ownership on the write; no preliminary API reads needed.
        api(session,'PUT','videos',params={'part':'status'},body={'id':action['video_id'],'status':{'privacyStatus':'public','selfDeclaredMadeForKids':False}})
    elif action['kind']=='title':
        video=api(session,'GET','videos',params={'part':'snippet','id':action['video_id']})['items'][0]
        if video['snippet']['channelId']!=settings['youtube_channel_id']:raise UploadError('upload_uncertain')
        snippet=video['snippet']
        api(session,'PUT','videos',params={'part':'snippet'},body={'id':video['id'],'snippet':{'title':action['title'],'categoryId':snippet['categoryId'],'description':snippet.get('description',''),'tags':snippet.get('tags',[])}})
    else:raise ValueError('Unknown video action')


def video_action(job, action, settings, cloud, dashboard):
    """Only explicit owner requests may publish or replace a title."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    token=dashboard.call('auth_claim',name='youtube')
    if not token:raise UploadError('auth_required')
    credentials=None;original=None
    try:
        original=cloud.secret(settings['youtube_secret'])
        credentials=Credentials.from_authorized_user_info(json.loads(original));session=AuthorizedSession(credentials)
        apply_video_action(session,job,action,settings)
    finally:
        try:
            if credentials and json.loads(credentials.to_json())!=json.loads(original):
                dashboard.call('auth_check',name='youtube',token=token)
                cloud.add_secret_version(settings['youtube_secret'],credentials.to_json().encode())
        finally:dashboard.call('auth_release',name='youtube',token=token)


def inspect_upload(session, job, settings, cloud):
    """Read recent uploads; never infer identity merely from an upload error."""
    channel=owned_channel(session,settings)
    channels=api(session,'GET','channels',params={'part':'contentDetails','id':channel})['items']
    uploads=channels[0]['contentDetails']['relatedPlaylists']['uploads']
    ids=[]
    for item in pages(session,'playlistItems',{'part':'contentDetails','playlistId':uploads,'maxResults':50}):
        ids.append(item['contentDetails']['videoId'])
        if len(ids)>=200:break
    expected=cloud.storage_json(job['stages']['plan']['result']['interactions_uri'],max_bytes=1048576)
    candidates=[]
    for start in range(0,len(ids),50):
        result=api(session,'GET','videos',params={'part':'snippet,status,contentDetails','id':','.join(ids[start:start+50])})
        for video in result.get('items',[]):
            if video['snippet']['channelId']==channel and video['snippet'].get('description')==expected['youtube_description']:
                candidates.append({'video_id':video['id'],'title':video['snippet']['title'],'privacy':video['status']['privacyStatus'],
                    'published_at':video['snippet']['publishedAt'],'duration':video['contentDetails']['duration'],'matching_description':True})
    return {'candidates':candidates,'searched_uploads':len(ids),'recording':job['id']}
