"""One case-owned checkpoint. Research survives new processing attempts."""
import difflib,hashlib,json,re,uuid
from pathlib import Path
from .diagnostics import Redactor
from .model import digest_json

class CardHistory:
 def __init__(self,job,transcript,settings,cloud,folder,store=None):
  self.cloud=cloud;self.store=store;self.folder=Path(folder);self.job=job
  self.redactor=Redactor(settings);self.prefix=f'gs://{settings["bucket"]}/card-research/{job["id"]}/v2'
  self.blocks=[[p.get('speaker'),' '.join(p.get('text','').split())] for p in transcript.get('paragraphs',[])]
  self.legacy_digest=digest_json(transcript);self.source_hashes={};self.asset_hashes={}
  self.alignment_uri=job.get('stages',{}).get('align',{}).get('result',{}).get('transcript_uri')
  self.version=0;self.last_uri=None;self.source_refs={};self.pdf_refs={};self.asset_refs={};self.events=[];self.hashes={}
  self.plan={'phase':'scan','opportunities':[],'decisions':[]}
 def upload(self,value,name,content_type='application/json'):
  data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,sort_keys=True).encode()
  key=hashlib.sha256(data).hexdigest();uri=self.prefix+'/'+name+'/'+key
  if uri in self.hashes:return uri
  file=self.folder/('saved-'+uuid.uuid4().hex);file.write_bytes(data)
  try:
   try:self.cloud.storage_upload(file,uri,content_type)
   except RuntimeError as error:
    if 'HTTP 412' not in str(error):raise
    if self.cloud.storage_bytes(uri,max_bytes=len(data)+1)!=data:raise ValueError('Saved research artifact differs')
  finally:file.unlink(missing_ok=True)
  self.hashes[uri]=key;return uri
 def event(self,event):
  self.events.append(self.redactor.value(event));self.events=self.events[-100:]
 def legacy(self):
  # One-time migration. Normal loading never lists historical checkpoints.
  prefix=self.prefix.rsplit('/',1)[0]+'/'
  bucket,key=prefix[5:].split('/',1);names=[];page=None
  while True:
   params={'prefix':key,'maxResults':1000,'fields':'items(name),nextPageToken'}
   if page:params['pageToken']=page
   listing=self.cloud.request('GET',f'https://storage.googleapis.com/storage/v1/b/{bucket}/o',params=params)
   names.extend(x['name'] for x in listing.get('items',[]) if re.search(r'/checkpoints/\d{20}/[^/]+$',x['name']))
   page=listing.get('nextPageToken')
   if not page:break
  if not names:return None
  latest=max(names,key=lambda n:n.rsplit('/',2)[-2]);saved=self.cloud.storage_json('gs://'+bucket+'/'+latest,max_bytes=2097152)
  if self.legacy_digest not in latest:saved['blocks']=[]
  return saved
 def load(self,tools):
  if self.store is None:raise ValueError('Research checkpoint store is required')
  current=self.store.call('research_load');self.version=current['version'];saved=current.get('checkpoint')
  if saved is None:saved=self.legacy()
  if not saved:return
  self.plan=saved['plan'];self.events=saved['events'][-100:];self.source_refs=saved['sources'];self.pdf_refs=saved['pdfs'];self.asset_refs=saved['assets']
  tools.previews=saved['previews'];tools.proposals=saved['proposals']
  changed=saved.get('blocks') is not None and saved['blocks']!=self.blocks
  if changed:
   old=[json.dumps(b,ensure_ascii=False) for b in saved['blocks']];new=[json.dumps(b,ensure_ascii=False) for b in self.blocks]
   mapping={b.a+i:b.b+i for b in difflib.SequenceMatcher(None,old,new,autojunk=False).get_matching_blocks() for i in range(b.size)}
   for identifier,card in list(tools.proposals.items()):
    indices=[mapping.get(i) for i in range(card['start_block'],card['end_block'])]
    if indices and None not in indices and indices==list(range(indices[0],indices[0]+len(indices))):card.update(start_block=indices[0],end_block=indices[-1]+1)
    else:
     self.plan.setdefault('decisions',[]).append({'id':identifier,'status':'pending','reason':'Transcript changed; recheck this saved design against current blocks','draft':card})
     del tools.proposals[identifier]
   self.plan['phase']='scan'
  if changed or saved.get('alignment_uri')!=self.alignment_uri:
   tools.previews={}
   for card in list(tools.proposals.values())+[d.get('draft') for d in self.plan.get('decisions',[])]:
    if isinstance(card,dict):card.update(visual_checked=False,preview_id='')
   hybrid=self.plan.get('hybrid')
   if hybrid:
    hybrid.pop('review_final',None)
    if changed:
     # Keep source packets and one previous scan, but never reuse stale block IDs.
     hybrid['previous_readers']=hybrid.get('readers',{})
     for key in ('editor_final','editor_draft','contact_sheet_issued','reader_progress'):hybrid.pop(key,None)
     hybrid.update(readers={},calls={},tool_calls={})
  for key,uri in self.source_refs.items():
   tools.sources[key]=self.cloud.storage_json(uri,max_bytes=33554432)
   self.source_hashes[key]=digest_json(tools.sources[key])
   if key in self.pdf_refs:tools.sources[key]['pdf_uri']=self.pdf_refs[key]
  for path,uri in self.asset_refs.items():
   tools.assets[path]=self.cloud.storage_bytes(uri,max_bytes=12582912);self.asset_hashes[path]=hashlib.sha256(tools.assets[path]).hexdigest()
  self.last_uri=f'research:{self.job["id"]}:{self.version}'
 def save(self,tools):
  for key,source in tools.sources.items():
   public={k:v for k,v in source.items() if k not in ('pdf','pdf_uri')};fingerprint=digest_json(public)
   if self.source_hashes.get(key)!=fingerprint:self.source_refs[key]=self.upload(public,'sources');self.source_hashes[key]=fingerprint
   if source.get('pdf'):self.pdf_refs[key]=self.upload(Path(source['pdf']).read_bytes(),'pdfs','application/pdf')
  for path,data in tools.assets.items():
   fingerprint=hashlib.sha256(data).hexdigest()
   if self.asset_hashes.get(path)!=fingerprint:self.asset_refs[path]=self.upload(data,'exhibits','image/jpeg');self.asset_hashes[path]=fingerprint
  state={'plan':self.plan,'events':self.events,'sources':self.source_refs,'pdfs':self.pdf_refs,'assets':self.asset_refs,'previews':tools.previews,'proposals':tools.proposals,'alignment_uri':self.alignment_uri,'blocks':self.blocks}
  result=self.store.call('research_save',version=self.version,operation_id=uuid.uuid4().hex,checkpoint=state)
  self.version=result['version'];self.last_uri=f'research:{self.job["id"]}:{self.version}';return self.last_uri
 def resume(self,tools):
  return {'plan':self.plan,'proposals':list(tools.proposals.values()),'sources':[{'source_id':key,'url':s['url']} for key,s in tools.sources.items()],'recent_events':self.events[-30:]}
