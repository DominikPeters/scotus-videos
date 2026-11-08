"""Accept a portable card file; production workers prepare its owner review."""
import json,uuid,tempfile,re
from pathlib import Path
from .model import digest_json

def resolve_case(dashboard,query):
 jobs=(dashboard.call('snapshot').get('jobs') or {}).values();query=query.casefold()
 exact=[j for j in jobs if j['id'].casefold()==query or j['docket'].casefold()==query]
 matches=exact or [j for j in jobs if query in j.get('case_name','').casefold()]
 if len(matches)!=1:raise ValueError('Choose one recording: '+', '.join(j['id'] for j in matches))
 return matches[0]

def create(dashboard,google,settings,query,spec):
 job=resolve_case(dashboard,query)
 if not isinstance(spec,dict) or not isinstance(spec.get('cards'),list) or not 0<len(spec['cards'])<=100:raise ValueError('Provide a card file with one to 100 cards')
 if any(not isinstance(c,dict) for c in spec['cards']):raise ValueError('Each card must be a JSON object')
 ids=[c.get('id') for c in spec['cards']]
 if any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):raise ValueError('Cards need unique IDs')
 for card in spec['cards']:
  if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',card['id']):raise ValueError('Card IDs must use letters, numbers, underscores or hyphens')
  if any(type(card.get(k)) is not int for k in ('start_block','end_block')) or not 0<=card['start_block']<card['end_block']:raise ValueError('Each card needs a valid transcript block range')
  if not isinstance(card.get('evidence'),list) or not card['evidence'] or any(not isinstance(e,dict) for e in card['evidence']):raise ValueError('Each card needs source evidence')
 spec=json.loads(json.dumps(spec))
 known=[s for c in (job.get('review') or {}).get('cards',[]) for s in c.get('sources',[])]
 notes=spec.get('private_notes',[])
 if isinstance(notes,str):notes=[notes]
 if not isinstance(notes,list) or any(not isinstance(n,str) for n in notes):raise ValueError('Private notes must be text or a list of text notes')
 spec['private_notes']=notes
 for card in spec['cards']:
  for e in card.get('evidence',[]):
   url=e.get('url') or spec.get('source_urls',{}).get(e.get('source'))
   if not url:
    matches={(s['url'],s['page']) for s in known if ' '.join(s.get('quote','').split())==' '.join(e.get('quote','').split()) and s.get('claim')==e.get('claim')}
    if len(matches)==1:url,e['page']=next(iter(matches))
   if not isinstance(url,str) or not url.startswith('https://'):raise ValueError('Provide evidence.url or a source_urls entry for '+str(e.get('source','this passage')))
   e['url']=url
 if len(json.dumps(spec).encode())>1572864:raise ValueError('Card file is too large; reduce exhibit image sizes')
 identity='cards-'+uuid.uuid4().hex[:12];uri=f'gs://{settings["bucket"]}/reviews/{job["id"]}/imports/{identity}.json'
 request_hash=digest_json(spec)
 record=dashboard.call('card_import_create',job=job['id'],import_id=identity,spec_uri=uri,request_hash=request_hash,alignment_uri=job['stages']['align'].get('result',{}).get('transcript_uri'),card_count=len(ids))
 if record['status']!='uploading':return {k:v for k,v in record.items() if k!='spec_uri'}
 uri=record['spec_uri'];identity=record['id']
 with tempfile.TemporaryDirectory() as folder:
  path=Path(folder)/'cards.json';path.write_text(json.dumps(spec))
  try:google.storage_upload(path,uri,'application/json')
  except RuntimeError as error:
   if 'HTTP 412' not in str(error) or digest_json(google.storage_json(uri,max_bytes=1572864))!=request_hash:raise
 return dashboard.call('card_import_ready',job=job['id'],import_id=identity,request_hash=request_hash)

def dispatch_import(dashboard,google,settings,job):
 from .attempts import launch
 item=job.get('card_import') or {}
 if item.get('status')=='uploading':
  spec=google.storage_json(item['spec_uri'],max_bytes=1572864)
  if spec is None:return None
  if digest_json(spec)!=item['request_hash']:raise ValueError('Imported card file differs')
  item=dashboard.call('card_import_ready',job=job['id'],import_id=item['id'],request_hash=item['request_hash'])
 if item.get('status')!='queued':return None
 claim=dashboard.call('card_import_dispatch',job=job['id'])
 if not claim:return None
 operation=launch(dashboard,google,settings,{'kind':'import','job':job['id']},settings['jobs']['enrich'],{'SCOTUS_JOB_ID':job['id'],'SCOTUS_STAGE':'enrich','SCOTUS_CARD_IMPORT_ID':claim['id'],'SCOTUS_CARD_IMPORT_TOKEN':claim['dispatch_token']})
 return {'job':job['id'],'stage':'card_import','operation':operation}
