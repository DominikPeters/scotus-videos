"""Owner commands using case names and JSON files; credentials stay in memory.

  python cloud/infra/operate.py status Younge
  python cloud/infra/operate.py refresh-sources Younge
  python cloud/infra/operate.py import-cards Maxwell annotation-trial/25-5930/cards.json
"""
import argparse,base64,hashlib,json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def portable(file):
 file=Path(file);root=file.parent.resolve();spec=json.loads(file.read_text());manifest=root/'sources/urls.json'
 urls=json.loads(manifest.read_text()) if manifest.is_file() else {}
 if not isinstance(urls,dict) or not isinstance(spec.get('source_urls',{}),dict):raise ValueError('Source URLs must be a mapping of filenames to URLs')
 urls={**urls,**spec.get('source_urls',{})};spec['source_urls']=urls;assets=dict(spec.get('assets',{}))
 for card in spec['cards']:
  sources=card.get('sources',[])
  for e in card['evidence']:
   url=e.get('url') or urls.get(e.get('source'))
   if not url:
    found=[s['url'] for s in sources if hashlib.sha256(s['url'].encode()).hexdigest()==e.get('source_id') or (s.get('quote')==e['quote'] and s.get('page')==e['page'])]
    if len(set(found))==1:url=found[0]
   if not url and isinstance(e.get('source'),str):
    name=e['source'];path=(root/'sources'/name).resolve()
    if name.startswith('https://'):url=name
    elif path.is_relative_to(root/'sources') and path.suffix=='.txt' and path.is_file():
     with path.open() as stream:first=stream.readline(8192).strip()
     if first.startswith('https://'):url=first
   # The server can also reuse matching evidence already researched for this case.
   if url:e['url']=url
  cue=card.get('cue') or json.loads(card['cue_json']);image=cue.get('image')
  if image and image not in assets:
   candidates=[root/'preview'/image,root/image]
   path=next((p.resolve() for p in candidates if p.resolve().is_relative_to(root) and p.is_file()),None)
   if not path:raise ValueError('Missing exhibit '+image)
   data=path.read_bytes()
   if len(data)>1048576 or not data.startswith(b'\xff\xd8\xff') or image!='cards/assets/'+hashlib.sha256(data).hexdigest()+'.jpg':raise ValueError('Use a verified JPEG exhibit smaller than 1 MB')
   assets[image]={'data_base64':base64.b64encode(data).decode()}
 spec['assets']=assets;return spec

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--project',default='possible-cycle-237715')
 sub=parser.add_subparsers(dest='command',required=True)
 for command in ('status','refresh-sources','import-cards','rerender','download'):
  item=sub.add_parser(command);item.add_argument('case')
  if command=='import-cards':item.add_argument('file',type=Path)
 args=parser.parse_args()
 from infra.managed_secrets import cli_cloud
 from scotus_cloud.secret_store import SecretStore
 from scotus_cloud.remote import signature
 import requests
 settings=json.loads(SecretStore(cli_cloud(args.project)).read('scotus-video-control-config'))
 op={'status':'case_status','refresh-sources':'refresh_sources','import-cards':'card_import','rerender':'case_rerender','download':'video_download'}[args.command];data={'job':args.case}
 if args.command=='import-cards':data['spec']=portable(args.file)
 body=json.dumps({'op':op,'data':data},separators=(',',':')).encode();stamp=str(int(time.time()));nonce=uuid.uuid4().hex
 response=requests.post(settings['control_url']+'/v1/request',data=body,headers={'Content-Type':'application/json','X-Scotus-Time':stamp,'X-Scotus-Nonce':nonce,'X-Scotus-Signature':signature(settings['control_key'],stamp,nonce,'POST','/v1/request',body)},timeout=60)
 value=response.json()
 if not value.get('ok'):raise SystemExit(value.get('error','Operation failed'))
 response.raise_for_status()
 print(json.dumps(value['result'],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
