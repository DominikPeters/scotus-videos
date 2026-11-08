"""Render imported cards for explicit owner review; never invent visual approval."""
import base64,hashlib,json,os,tempfile,threading,io
from pathlib import Path
from types import SimpleNamespace
from .secret_store import runtime_settings
from .remote import Dashboard
from .google import Google
from .annotation_cards import CardTools,CARD_WORKFLOW_VERSION,preview_fingerprint,cue_for
from .model import digest_json

def prepare(spec,job,base,settings,cloud,dashboard,folder,progress=lambda *_:None,prepared=()):
 tools=CardTools(job,{},base,{},cloud,SimpleNamespace(dashboard=dashboard),folder);tools.settings=settings
 tools.aligned=cloud.storage_json(job['stages']['align']['result']['transcript_uri'],max_bytes=2097152)
 for name,asset in spec.get('assets',{}).items():
  data=base64.b64decode(asset['data_base64'],validate=True)
  if len(data)>12582912 or name!='cards/assets/'+hashlib.sha256(data).hexdigest()+'.jpg':raise ValueError('Exhibit image name must identify its JPEG content')
  from PIL import Image
  image=Image.open(io.BytesIO(data))
  if image.format!='JPEG' or image.width*image.height>20000000:raise ValueError('Use a JPEG exhibit under 20 megapixels')
  image.verify()
  tools.assets[name]=data
 cards=[];resumed={c['id']:c for c in prepared}
 for n,raw in enumerate(spec['cards']):
  evidence=[]
  for e in raw['evidence']:
   url=e.get('url') or spec.get('source_urls',{}).get(e.get('source'))
   if not isinstance(url,str) or not url.startswith('https://'):raise ValueError('Every evidence passage needs a public source URL')
   source=tools.source(url,'',0);evidence.append({'source_id':source['source_id'],**{k:e[k] for k in ('page','quote','claim')}})
  card={k:raw[k] for k in ('id','start_block','end_block')};card.update(recommended=raw.get('recommended',True),reason=raw.get('reason','Imported proposal'),evidence=evidence,cue_json=raw.get('cue_json') or json.dumps(raw['cue']),preview_id='',visual_checked=False)
  identifier=preview_fingerprint(card);saved=resumed.get(card['id'])
  if saved and saved.get('preview_id')==identifier:preview={k:saved[k] for k in ('frame_uri','card_uri','start','end','cue')}
  else:
   rendered=tools.render(card);info=json.loads(rendered['contentItems'][0]['text']);metrics=info.get('metrics',{})
   if metrics.get('overflow') or metrics.get('visible') is False:raise ValueError('Card '+card['id']+' does not fit its production preview')
   preview=tools.previews[identifier]
  cue=cue_for(card,tools.aligned);tools.verify(card['evidence']);tools.verify_display(cue,evidence)
  preview={**preview,'cue':cue,'start':cue['start'],'end':cue['end']}
  cards.append({**card,**preview,'preview_id':identifier,'revision':identifier,'visual_checked':False,'owner_review_required':True,'sources':[{'url':tools.sources[e['source_id']]['url'],'sha256':tools.sources[e['source_id']]['sha256'],**{k:e[k] for k in ('page','quote','claim')}} for e in evidence]})
  progress((n+1)/len(spec['cards']),cards)
 for a,b in zip(sorted(cards,key=lambda c:c['start']),sorted(cards,key=lambda c:c['start'])[1:]):
  if a['end']>b['start']+.001:raise ValueError('Cards '+a['id']+' and '+b['id']+' overlap')
 assets={}
 for name,data in tools.assets.items():
  path=Path(folder)/Path(name).name;path.write_bytes(data);uri=f'gs://{settings["bucket"]}/reviews/{job["id"]}/cards/assets/{path.name}';tools.upload_preview(path,uri,data);assets[name]={'uri':uri,'sha256':hashlib.sha256(data).hexdigest()}
 return {'workflow_version':CARD_WORKFLOW_VERSION,'cards':cards,'assets':assets,'private_notes':spec.get('private_notes',[]),'imported':True,'oyez_content_used':any('oyez.org' in s['url'] for c in cards for s in c['sources'])}

def main():
 settings=runtime_settings('/secrets/worker/config.json');cloud=Google(settings['project']);dashboard=Dashboard(settings['dashboard_url'],settings['worker_key'],'enrich')
 claim=dashboard.call('card_import_claim',job=os.environ['SCOTUS_JOB_ID'],import_id=os.environ['SCOTUS_CARD_IMPORT_ID'],dispatch_token=os.environ['SCOTUS_CARD_IMPORT_TOKEN'])
 if not claim:return
 job=claim['job'];item=claim['import'];stopped=threading.Event();lost=threading.Event();value=[0]
 def call(op,**kw):return dashboard.call(op,job=job['id'],import_id=item['id'],lease=item['lease'],**kw)
 def heartbeat():
  while not stopped.wait(30):
   try:call('card_import_heartbeat',progress=value[0])
   except Exception:lost.set();return
 thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
 try:
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);spec=cloud.storage_json(item['spec_uri'],max_bytes=1572864);base=cloud.storage_json(job['stages']['enrich']['result']['enrichment_uri'],max_bytes=1048576)
   if digest_json(spec)!=item['request_hash']:raise ValueError('Imported card input differs from the received file')
   uri=f'gs://{settings["bucket"]}/enrichment/{job["id"]}/import-{item["id"]}.json'
   existing=cloud.storage_json(uri,max_bytes=1048576)
   if existing:
    annotations=existing['annotations'];provenance=annotations.get('import_provenance',{})
    if provenance.get('request_hash')!=item['request_hash'] or provenance.get('alignment_uri')!=item['alignment_uri'] or any(c['preview_id']!=preview_fingerprint(c) for c in annotations['cards']):raise ValueError('The presentation changed after this import; prepare the file again')
    call('card_import_finish',enrichment_uri=uri,cards=annotations['cards'],private_notes=annotations['private_notes']);return
   def progress(x,cards):
    if lost.is_set():raise RuntimeError('Card import lease was interrupted; saved input can be retried')
    value[0]=x
    call('card_import_heartbeat',progress=x,prepared_cards=cards)
   annotations=prepare(spec,job,base,settings,cloud,dashboard,root,progress,item.get('prepared_cards',[]))
   annotations['import_provenance']={'id':item['id'],'request_hash':item['request_hash'],'alignment_uri':item['alignment_uri']};base['annotations']=annotations
   file=root/'enrichment.json';file.write_text(json.dumps(base))
   try:cloud.storage_upload(file,uri,'application/json')
   except RuntimeError as e:
    if 'HTTP 412' not in str(e):raise
   call('card_import_finish',enrichment_uri=uri,cards=annotations['cards'],private_notes=annotations['private_notes'])
 except Exception as error:call('card_import_fail',message=str(error)[:600])
 finally:stopped.set();thread.join(timeout=1)
