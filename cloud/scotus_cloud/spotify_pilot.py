"""One-off cloud upload trial for an existing externally hosted Spotify episode.

Does not publish, create episodes, or alter metadata. Credentials are mounted
from Secret Manager; video transfers stay in Google Cloud. The nonhosted API
was verified against the current Spotify upload-page implementation.
"""
import http.client
from .secret_store import runtime_settings
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import time
import uuid

import requests
from scotus_cloud.google import Google


def sanitize(value):
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()
                if not any(s in k.lower() for s in ('url', 'token', 'cookie', 'authorization'))}
    if isinstance(value, list): return [sanitize(v) for v in value]
    if isinstance(value, str): return re.sub(r'https?://\S+', '[private URL]', value)[:1500]
    return value


def main():
    if not os.environ.get('CLOUD_RUN_JOB'): raise RuntimeError('Cloud execution required')
    config = runtime_settings('/secrets/spotify/session.json')
    google = Google(config['project'])
    root = Path('/tmp/spotify-pilot'); root.mkdir(exist_ok=True)
    headers = {'Authorization': 'Bearer '+config['bearer'], 'Accept': 'application/json',
               'Origin': 'https://creators.spotify.com', 'Referer': 'https://creators.spotify.com/'}
    base = 'https://generic.wg.spotify.com/podcasters/v0'

    def report(step, value):
        value = sanitize(value)
        path = root / (step+'.json'); path.write_text(json.dumps(value))
        google.storage_upload(path, config['output_prefix']+'/'+step+'.json', 'application/json')
        print(json.dumps({'step': step, 'result': value}), flush=True)

    def api(method, path, **kwargs):
        response = requests.request(method, base+path, headers=headers, timeout=30, **kwargs)
        if not response.ok:
            report('api-failure-'+str(time.time_ns()), {'status': response.status_code,
                   'path': path, 'body': response.text[:1500]})
            raise RuntimeError('Spotify API HTTP '+str(response.status_code))
        return response.json() if response.content else {}

    episode = config['episode_id']
    metadata = api('GET', '/episodes/'+episode+'/metadata')
    if (metadata.get('id') != episode or metadata.get('show', {}).get('id') != config['show_id']
            or metadata.get('name') != config['expected_name'] or metadata.get('hasVideo')):
        raise RuntimeError('Episode identity or existing-video check failed')
    report('identity', {k: metadata.get(k) for k in ('id','name','duration','hasVideo','mediaProcessingStatus')})
    source = root/'source.mp4'
    print('Downloading finished MP4 inside Google Cloud', flush=True)
    google.storage_download(config['video_uri'], source, expected_sha256=config.get('source_sha256'))
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(source)]))
    report('source-format', {'streams': [{k:s.get(k) for k in ('codec_name','codec_type','profile','width','height','channels','sample_rate','bit_rate','r_frame_rate')} for s in probe['streams']], 'bytes':source.stat().st_size,'duration':probe['format'].get('duration')})
    audio = [s for s in probe['streams'] if s['codec_type']=='audio']
    if len(audio)!=1 or len([s for s in probe['streams'] if s['codec_type']=='video'])!=1:
        raise RuntimeError('Expected one audio and one video stream')
    target = source
    filename = config.get('filename', 'episode.mp4')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+\.mp4',filename): raise ValueError('Invalid filename')
    keep_original = config.get('keep_original', False)
    if keep_original:
        if audio[0]['codec_name'] != 'mp3': raise RuntimeError('Unchanged MP3 test requires MP3 audio')
        report('unchanged-media', {'audio':'MP3','reencoded':False,'remuxed':False,'source_sha256':config.get('source_sha256'),'bytes':source.stat().st_size})
    elif audio[0]['codec_name']!='aac' or audio[0].get('channels')!=2 or int(audio[0].get('bit_rate',0))<192000:
        target = root/filename
        start = time.monotonic()
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(source),'-map','0:v:0','-map','0:a:0',
                        '-c:v','copy','-c:a','aac','-aac_coder','fast','-b:a','192k','-ac','2','-movflags','+faststart',str(target)],check=True,timeout=600)
        report('audio-conversion', {'video':'stream copy','audio':'AAC-LC stereo 192 kbps','seconds':round(time.monotonic()-start,2),'bytes':target.stat().st_size})
    generated = api('POST', '/episodes/'+episode+'/generateUploadId',
                    json={'episodeId':episode,'showId':config['show_id'],'episodeUri':'spotify:episode:'+episode})
    upload_id = generated['uploadId']
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',upload_id): raise RuntimeError('Unexpected upload ID')
    report('upload-reserved', {'upload_id': upload_id, 'episode_id': episode, 'bytes': target.stat().st_size})
    boundary = 'scotus'+uuid.uuid4().hex
    prefix = ('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+filename+'"\r\nContent-Type: video/mp4\r\n\r\n').encode()
    suffix = ('\r\n--'+boundary+'--\r\n').encode()
    connection = http.client.HTTPSConnection('media-importer.spotify.com',timeout=120,context=ssl.create_default_context())
    connection.putrequest('POST', '/v1/uploadfile/'+upload_id)
    for name,value in headers.items(): connection.putheader(name,value)
    connection.putheader('Content-Type','multipart/form-data; boundary='+boundary)
    connection.putheader('Content-Length',str(len(prefix)+target.stat().st_size+len(suffix)))
    connection.endheaders(); connection.send(prefix)
    start = time.monotonic()
    with target.open('rb') as source_file:
        while block := source_file.read(1024*1024): connection.send(block)
    connection.send(suffix)
    response = connection.getresponse(); body = response.read(65536)
    try: result = json.loads(body)
    except ValueError: result = {'body':body.decode(errors='replace')[:1500]}
    report('upload-response', {'status':response.status,'seconds':round(time.monotonic()-start,2),'response':result})
    connection.close()
    if response.status!=200: raise RuntimeError('Spotify rejected upload: HTTP '+str(response.status))
    report('ready-for-review', {'upload_id':upload_id,'episode_id':episode,'published':False,
                               'preview_available':bool(result.get('previewUrl'))})


if __name__ == '__main__': main()
