"""Private, resumable annotation research checkpoints and bounded session records."""
import json,time,uuid
from pathlib import Path
from urllib.parse import quote
from .model import digest_json
from .diagnostics import Redactor

class CardHistory:
 def __init__(self,job,transcript,settings,cloud,folder):
  self.cloud=cloud;self.folder=Path(folder);self.redactor=Redactor(settings)
  self.prefix=f'gs://{settings["bucket"]}/card-research/{job["id"]}/{digest_json(transcript)}/v1'
  self.last_uri=None;self.source_refs={};self.pdf_refs={};self.asset_refs={};self.events=[];self.plan={'phase':'scan','opportunities':[],'decisions':[]}
 def upload(self,value,name,content_type='application/json'):
  file=self.folder/('saved-'+uuid.uuid4().hex);file.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode())
  uri=self.prefix+'/'+name+'/'+uuid.uuid4().hex;self.cloud.storage_upload(file,uri,content_type);file.unlink();return uri
 def event(self,event):
  # Only explicit public-research fields reach this record; never image blobs or auth.
  self.events.append({'at_ns':time.time_ns(),**self.redactor.value(event)});self.events=self.events[-300:]
 def load(self,tools):
  bucket,key=self.prefix[5:].split('/',1)
  listing=self.cloud.request('GET',f'https://storage.googleapis.com/storage/v1/b/{bucket}/o',params={'prefix':key+'/checkpoints/','maxResults':1000,'fields':'items(name),nextPageToken'})
  if listing.get('nextPageToken'):raise ValueError('Research history needs compaction before continuing')
  names=sorted(item['name'] for item in listing.get('items',[]))
  if not names:return
  self.last_uri='gs://'+bucket+'/'+names[-1];saved=self.cloud.storage_json(self.last_uri,max_bytes=2097152)
  self.plan=saved['plan'];self.events=saved['events'];self.source_refs=saved['sources'];self.pdf_refs=saved['pdfs'];self.asset_refs=saved['assets']
  tools.previews=saved['previews'];tools.proposals=saved['proposals']
  for key,uri in self.source_refs.items():
   tools.sources[key]=self.cloud.storage_json(uri,max_bytes=33554432)
   if key in self.pdf_refs:tools.sources[key]['pdf_uri']=self.pdf_refs[key]
  for path,uri in self.asset_refs.items():tools.assets[path]=self.cloud.storage_bytes(uri,max_bytes=12582912)
 def save(self,tools):
  for key,source in tools.sources.items():
   if key not in self.source_refs:
    self.source_refs[key]=self.upload({k:v for k,v in source.items() if k not in ('pdf','pdf_uri')},'sources')
   if key not in self.pdf_refs and source.get('pdf'):
    self.pdf_refs[key]=self.upload(Path(source['pdf']).read_bytes(),'pdfs','application/pdf')
  for path,data in tools.assets.items():
   if path not in self.asset_refs:self.asset_refs[path]=self.upload(data,'exhibits','image/jpeg')
  state={'plan':self.plan,'events':self.events,'sources':self.source_refs,'pdfs':self.pdf_refs,'assets':self.asset_refs,'previews':tools.previews,'proposals':tools.proposals}
  self.last_uri=self.upload(state,'checkpoints/'+f'{time.time_ns():020d}');return self.last_uri
 def resume(self,tools):
  return {'plan':self.plan,'proposals':list(tools.proposals.values()),'sources':[{'source_id':key,'url':s['url']} for key,s in tools.sources.items()], 'recent_events':self.events[-30:]}
