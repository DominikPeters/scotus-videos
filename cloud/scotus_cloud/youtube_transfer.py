"""Editable upload transport; public payloads and publication remain in youtube.py."""
import re
from urllib.parse import urlsplit


def transfer(session,url,path,lease):
    from .youtube import UploadError
    total=path.stat().st_size
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.googleapis.com', 'youtube.googleapis.com') or parsed.username:
        raise UploadError('upload_uncertain')
    response = session.put(url, data=b'', headers={'Content-Length': '0', 'Content-Range': f'bytes */{total}'},
                           allow_redirects=False, timeout=60)
    if response.status_code in (200, 201):
        video = response.json()
    elif response.status_code == 308:
        match = re.fullmatch(r'bytes=0-(\d+)', response.headers.get('Range', ''))
        offset = int(match.group(1)) + 1 if match else 0
        with path.open('rb') as source:
            source.seek(offset)
            while offset < total:
                lease.check()
                block = source.read(min(8 * 1024 * 1024, total - offset))
                response = session.put(url, data=block,
                    headers={'Content-Length': str(len(block)), 'Content-Type': 'video/mp4',
                             'Content-Range': f'bytes {offset}-{offset + len(block) - 1}/{total}'},
                    allow_redirects=False, timeout=180)
                if response.status_code in (200, 201):
                    video = response.json(); break
                if response.status_code != 308:
                    raise UploadError('auth_required' if response.status_code in (401, 403) else 'worker_failed')
                acknowledged = re.fullmatch(r'bytes=0-(\d+)', response.headers.get('Range', ''))
                if not acknowledged:
                    raise UploadError('worker_failed')
                new_offset = int(acknowledged.group(1)) + 1
                if not offset < new_offset <= total:
                    raise UploadError('worker_failed')
                offset = new_offset; source.seek(offset); lease.update(offset / total)
            else:
                raise UploadError('upload_uncertain')
    else:
        raise UploadError('upload_uncertain')
    return video


def thumbnail(session,video_id,data):
    return session.post('https://www.googleapis.com/upload/youtube/v3/thumbnails/set',
        params={'videoId':video_id,'uploadType':'media'},data=data,headers={'Content-Type':'image/jpeg'},timeout=60)
