"""Export only validated public recording data; podcast publication stays in Actions."""
from datetime import datetime,timezone
import hashlib,json,math,re,time
from .connections import github_token,github_headers


def recording_export(job,transcript):
    audio=transcript['audio'];duration=float(audio['duration_seconds'])
    if not math.isfinite(duration) or duration<=0:raise ValueError('Invalid recording duration')
    speakers={sid:{key:person.get(key,'') for key in ('identifier','name','last_name','kind','role')}
              for sid,person in transcript['speakers'].items()}
    sections=[];paragraphs=transcript['paragraphs'];previous=-1
    for i,p in enumerate(paragraphs):
        start=float(p['start']);stop=float(paragraphs[i+1]['start']) if i+1<len(paragraphs) else duration
        if not previous<=start<=stop<=duration or p['speaker'] not in speakers:raise ValueError('Invalid paragraph timing or speaker')
        previous=start;person=speakers[p['speaker']]
        if person['kind'] not in ('justice','advocate') or not person['name']:raise ValueError('Unknown speaker')
        if not sections or sections[-1]['source_section']!=p['section']:
            sections.append({'source_section':p['section'],'start':start,'stop':stop,'turns':[]})
        section=sections[-1]
        if not section['turns'] or section['turns'][-1]['source_turn']!=p['turn']:
            section['turns'].append({'source_turn':p['turn'],'start':start,'stop':stop,'speaker':person,'text_blocks':[]})
        turn=section['turns'][-1];turn['text_blocks'].append({'start':0 if i==0 else start,'stop':stop,'text':p['text']});turn['stop']=stop;section['stop']=stop
    if not sections or any(not any(t['speaker']['kind']=='advocate' for t in s['turns']) for s in sections):
        raise ValueError('Argument section has no advocate; resolve transcript attribution before export')
    date=datetime.fromisoformat(job['argument_date']);term=str(date.year-(date.month<10))
    return {'schema_version':1,'recording_id':job['id'],'term':term,'docket':job['docket'],
            'argument_date':job['argument_date'],'case_name':job['case_name'],
            'audio':{'url':job['audio_url'],'sha256':audio['sha256'],'duration_seconds':duration},
            'pdf_url':job['pdf_url'],'alignment_source':'scotus_ctc','sections':sections}


def dispatch_podcast(google,settings,recording,revision):
    import requests
    value=json.loads(google.secret(settings['secrets']['github']))
    token=github_token(value,repository='DominikPeters/scotus-podcast')
    response=requests.post('https://api.github.com/repos/DominikPeters/scotus-podcast/dispatches',
        headers=github_headers(token),json={'event_type':'scotus_alignment_ready',
        'client_payload':{'recording_id':recording,'revision':revision}},timeout=15)
    if response.status_code!=204:raise RuntimeError('Podcast dispatch HTTP '+str(response.status_code))


def publish_alignments(dashboard,google,settings,jobs):
    if not settings.get('podcast_enabled'):return
    ordered=sorted(jobs.values(),key=lambda j:j.get('podcast_alignment',{}).get('source_uri')==j['stages']['align'].get('result',{}).get('transcript_uri'))
    for job in ordered:
        if job['status']=='cancelled' or job['stages']['align']['status']!='complete':continue
        uri=job['stages']['align'].get('result',{}).get('transcript_uri')
        if not uri:continue
        saved=job.get('podcast_alignment',{})
        if saved.get('error_source_uri')==uri and saved.get('retry_after',0)>time.time():continue
        if saved.get('source_uri')==uri and saved.get('dispatched'):continue
        try:
            if saved.get('source_uri')!=uri:
                payload=json.dumps(recording_export(job,google.storage_json(uri,max_bytes=2097152)),ensure_ascii=False,separators=(',',':'))
                revision=hashlib.sha256(payload.encode()).hexdigest()
                saved=dashboard.call('podcast_export',job=job['id'],source_uri=uri,payload=payload,revision=revision)
            dispatch_podcast(google,settings,job['id'],saved['revision'])
            dashboard.call('podcast_export_status',job=job['id'],revision=saved['revision'],dispatched=True)
        except Exception as error:
            dashboard.call('podcast_export_status',job=job['id'],source_uri=uri,error=type(error).__name__+': '+str(error)[:200])
        # Bound controller latency; remaining exports are picked up at next tick.
        break
