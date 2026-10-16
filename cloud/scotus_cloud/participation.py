"""Validate Codex's docket interpretation; preserve seats for confirmed recusals."""
from datetime import date
from pathlib import Path
import json
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
SCHEMA={'type':'object','additionalProperties':False,'properties':{
 'docket':{'type':'string'},'argument_date':{'type':'string'},
 'justices':{'type':'array','maxItems':9,'items':{'type':'object','additionalProperties':False,'properties':{
  'identifier':{'type':'string'},'status':{'type':'string','enum':['recused','uncertain','participating']},
  'explanation':{'type':'string','maxLength':1500},
  'evidence':{'type':'array','maxItems':6,'items':{'type':'object','additionalProperties':False,'properties':{
   'date':{'type':'string'},'url':{'type':'string'},'excerpt':{'type':'string','maxLength':2000}},'required':['date','url','excerpt']}}},
  'required':['identifier','status','explanation','evidence']}},
 'private_notes':{'type':'array','items':{'type':'string'}}},'required':['docket','argument_date','justices','private_notes']}


def validate_participation(value,case,oyez=None):
 from jsonschema import validate
 validate(value,SCHEMA)
 if value['docket']!=case['docket'] or value['argument_date']!=case['argument_date']:raise ValueError('Participation recording identity differs')
 known=set(json.loads((ROOT/'speaker-catalog.json').read_text()))
 for court in (oyez or {}).get('heard_by') or []:
  if isinstance(court,dict):known.update(p['identifier'] for p in court.get('members',[]) if isinstance(p,dict) and p.get('identifier'))
 seen=set()
 for item in value['justices']:
  sid=item['identifier']
  if sid not in known or sid in seen:raise ValueError('Unknown or repeated participation justice')
  seen.add(sid)
  if item['status']=='recused' and not item['evidence']:raise ValueError('Confirmed recusal needs evidence')
  for evidence in item['evidence']:
   date.fromisoformat(evidence['date']);url=urlsplit(evidence['url'])
   if url.scheme!='https' or url.hostname not in ('www.supremecourt.gov','supremecourt.gov') or not evidence['excerpt'].strip():raise ValueError('Participation needs official Court evidence')
 return value


def apply_participation(data,participation,catalog):
 """Only confirmed findings affect pixels. Oyez membership is not a recusal decision."""
 recused={p['identifier'] for p in (participation or {}).get('justices',[]) if p['status']=='recused'}
 courts=data['heard_by']
 data['heard_by']=[{**courts[0],'members':[dict(p) for p in courts[0]['members']]},*courts[1:]]
 members=data['heard_by'][0]['members']
 # Restore an omitted recused justice when the supplied bench is this catalog's Court.
 if recused and {p['identifier'] for p in members}<=catalog.keys():
  existing={p['identifier'] for p in members}
  for sid in recused-existing:
   person=catalog.get(sid)
   if person and 'seniority' in person:members.append({**person,'thumbnail':{'href':person['portrait_uri']},'roles':[{'role_title':'Chief Justice of the United States' if person['seniority']==0 else 'Associate Justice'}]})
  members.sort(key=lambda p:catalog[p['identifier']].get('seniority',99))
 for person in members:
  person['recused']=person['identifier'] in recused
 return data
