"""Recording-aware data adapters for the unchanged video/public formatters."""
from datetime import datetime,timezone
from html import escape
import json
from pathlib import Path
from .court_metadata import normalized_case_source

ROOT=Path(__file__).resolve().parents[1]


def usable_timestamp(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):return False
    try:datetime.fromtimestamp(value,tz=timezone.utc)
    except (ValueError,OverflowError,OSError):return False
    return True


def recording_timeline(events,argued_timestamp):
    # Preserve supplied events without mutating Oyez's private source artifact.
    timeline=[]
    for event in events if isinstance(events,list) else []:
        if not isinstance(event,dict) or not isinstance(event.get('event'),str):continue
        if event['event']=='Argued':
            dates=event.get('dates')
            if not isinstance(dates,list) or not dates or not usable_timestamp(dates[0]):
                event={**event,'dates':[argued_timestamp]}
        timeline.append(event)
    if not any(event['event']=='Argued' for event in timeline):
        timeline.append({'event':'Argued','dates':[argued_timestamp]})
    return timeline


def presentation_audio(transcript):
    paragraphs=transcript['paragraphs'];duration=transcript['audio']['duration_seconds']
    sections=[]
    for index,p in enumerate(paragraphs):
        sid=p['speaker'];person=transcript['speakers'][sid]
        speaker={**person,'description':person.get('role','')}
        if not sections or sections[-1]['source_section']!=p['section']:
            sections.append({'source_section':p['section'],'start':p['start'],'stop':duration,'turns':[]})
        section=sections[-1]
        if not section['turns'] or section['turns'][-1]['source_turn']!=p['turn']:
            section['turns'].append({'source_turn':p['turn'],'start':p['start'],'stop':duration,'speaker':speaker,'text_blocks':[]})
        stop=paragraphs[index+1]['start'] if index+1<len(paragraphs) else duration
        section['turns'][-1]['text_blocks'].append({'start':0 if index==0 else p['start'],'stop':stop,'text':escape(p['text'])})
    for section in sections:
        for turn in section['turns']: turn['stop']=turn['text_blocks'][-1]['stop']
        section['stop']=section['turns'][-1]['stop']
    return {'transcript':{'sections':sections}}


def case_metadata(job,transcript,enrichment):
    original=enrichment.get('case_metadata') or {}
    data=normalized_case_source(original)
    data.update(ID=job['id'],name=original.get('name') or job['case_name'],docket_number=job['docket'])
    argued=datetime.fromisoformat(job['argument_date']).replace(tzinfo=timezone.utc)
    data['timeline']=recording_timeline(data.get('timeline'),int(argued.timestamp()))
    data.setdefault('term',str(argued.year if argued.month>=10 else argued.year-1))
    data.setdefault('first_party_label','Petitioner');data.setdefault('second_party_label','Respondent')
    parties=data['name'].split(' v. ',1)
    data.setdefault('first_party',parties[0]);data.setdefault('second_party',parties[-1] if len(parties)>1 else '')
    data.setdefault('href','');data.setdefault('justia_url','');data.setdefault('conclusion',None)
    if enrichment.get('description'): data.update(enrichment['description']['fields'])
    data.setdefault('facts_of_the_case',None);data.setdefault('question','')
    catalog=json.loads((ROOT/'speaker-catalog.json').read_text())
    if not data.get('heard_by'):
        members=[]
        for person in sorted([p for p in catalog.values() if 'seniority' in p],key=lambda p:p['seniority']):
            members.append({**person,'thumbnail':{'href':person['portrait_uri']},
                'roles':[{'role_title':'Chief Justice of the United States' if person['seniority']==0 else 'Associate Justice'}]})
        data['heard_by']=[{'members':members}]
    from .participation import apply_participation
    apply_participation(data,enrichment.get('participation'),catalog)
    data['advocates']=[{'advocate':{**p,'description':p.get('role','')}} for p in transcript['speakers'].values() if p['kind']=='advocate']
    return data


