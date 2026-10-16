"""Private case research, title selection and portrait review, with resumable results."""
import hashlib,io,json,re,socket,ipaddress,uuid
from pathlib import Path
from urllib.request import Request,urlopen,HTTPRedirectHandler,build_opener
from urllib.parse import urlsplit

from .case_descriptions import generate_case_description
from .editorial import generate_title
from .codex_auth import run_codex
from .model import digest_json


ROOT=Path(__file__).resolve().parents[1]


def public_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError('Use a public HTTPS URL')
    for item in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(item[4][0]).is_global:raise ValueError('Private network URL rejected')
    return url


class Redirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch(url,limit=2097152):
    public_url(url)
    with build_opener(Redirect()).open(Request(url,headers={'User-Agent':'Scotus video research'}),timeout=30) as response:
        data=response.read(limit+1)
        if len(data)>limit:raise ValueError('Research response too large')
        return data


def jpeg_preview(data,edge=640):
    from PIL import Image,ImageOps
    Image.MAX_IMAGE_PIXELS=16000000
    image=Image.open(io.BytesIO(data))
    if image.width*image.height>16000000:raise ValueError('Image dimensions exceed the research limit')
    image.load();image=ImageOps.exif_transpose(image).convert('RGB')
    portrait=image.copy();portrait.thumbnail((1024,1024))
    full=io.BytesIO();portrait.save(full,'JPEG',quality=90,optimize=True)
    portrait.thumbnail((edge,edge));preview=io.BytesIO();portrait.save(preview,'JPEG',quality=75,optimize=True)
    return full.getvalue(),preview.getvalue()


def store_photo(cloud,bucket,job,person,data,evidence,folder,*,preserve=False):
    full,preview=jpeg_preview(data)
    if preserve:full=data
    sha=hashlib.sha256(full).hexdigest();cid=sha[:24]
    base=f'gs://{bucket}/reviews/{job}/{person}/{cid}'
    for name,value in [('portrait.jpg',full),('preview.jpg',preview)]:
        path=folder/name;path.write_bytes(value)
        try:cloud.storage_upload(path,base+'/'+name,'image/jpeg')
        except RuntimeError:
            # Content-addressed objects are reused on repeat research.
            existing=cloud.storage_bytes(base+'/'+name,max_bytes=4194304)
            if existing!=value:raise
    return {'id':cid,'portrait_uri':base+'/portrait.jpg','preview_uri':base+'/preview.jpg','sha256':sha,**evidence}


def enrich(job,transcript,settings,cloud,lease,folder):
    lease.call('note',message='Checking case metadata and approved images.');lease.update(.05)
    prior=job['stages']['enrich'].get('result',{}).get('enrichment_uri')
    if prior:
        result=cloud.storage_json(prior,max_bytes=1048576)
        if job.get('review'):result['photos']=job['review']['photos']
    else:
        editorial=cloud.storage_json(job['editorial_cache_uri'],max_bytes=1048576) if job.get('editorial_cache_uri') else None
        case={'docket':job['docket'],'case_name':job['case_name'],'argument_date':job['argument_date'],'recording_kind':'argument'}
        term=int(job['argument_date'][:4])-(int(job['argument_date'][5:7])<10)
        if editorial:oyez=editorial.get('case_metadata',{})
        else:
            try:oyez=json.loads(fetch(f'https://api.oyez.org/cases/{term}/{job["docket"]}'))
            except Exception:oyez={}
        if not isinstance(oyez,dict) or not oyez.get('name') or oyez.get('error'):oyez={}
        docket_url=f'https://www.supremecourt.gov/docket/docketfiles/html/public/{job["docket"]}.html'
        try:docket=fetch(f'https://www.supremecourt.gov/RSS/Cases/JSON/{job["docket"]}.json').decode()
        except Exception:docket=fetch(docket_url).decode()
        materials=[{'id':'docket','title':'Official Court docket','url':docket_url,'text':docket},
                   {'id':'transcript','title':'Official argument transcript','url':job['pdf_url'],'text':transcript['text']}]
        history=cloud.storage_json(settings['title_history_uri'],max_bytes=1048576)
        library=lease.dashboard.call('editorial_library')
        entries={item['video_id']:item for item in history['titles']}
        entries.update({item['video_id']:item for item in library['titles']});history['titles']=list(entries.values());history['count']=len(entries)
        if editorial:
            description=editorial['description']
            titles=editorial['titles'];title_notes=[n for n in editorial.get('private_notes',[]) if n not in description.get('private_caveats',[])+description.get('private_editorial_notes',[])]
            lease.call('note',message='Reusing case editorial content and checking the refreshed advocate list.');lease.update(.65)
        else:
            lease.call('note',message='Researching or shortening the case description.');
            description=generate_case_description(lease.dashboard,cloud,settings['codex_secret'],case,oyez=oyez,materials=materials,check_participation=True)
            lease.update(.35);lease.call('note',message='Choosing a title using the full channel title history.');
            case.update(description['fields'])
            title=generate_title(lease.dashboard,cloud,settings['codex_secret'],case,history,question_presented=case['question'],transcript=transcript['text'],model='gpt-6.1-sol')
            lease.update(.65);lease.call('note',message='Checking advocate portraits.');
            titles=[title['result']['recommended'],*title['result']['alternatives']]
            title_notes=title['result']['private_caveats']
        photos={};registry=json.loads((ROOT/'advocate-catalog.json').read_text())
        for sid,person in transcript['speakers'].items():
            if person['kind']!='advocate':continue
            cached=next((entry for entry in registry.values() if re.sub(r'\W','',entry['name']).casefold()==re.sub(r'\W','',person['name']).casefold()),None)
            candidates=[];photo_notes=[]
            approved=next((candidate for name,candidate in library['photos'].items() if re.sub(r'\W','',name).casefold()==re.sub(r'\W','',person['name']).casefold()),None)
            if approved:candidates.append(approved)
            elif cached:
                image=fetch(cached['uri'],4194304)
                if cached.get('sha256') and hashlib.sha256(image).hexdigest()!=cached['sha256']:raise ValueError('Approved catalog image changed')
                candidate=store_photo(cloud,settings['bucket'],job['id'],sid,image,
                    {'source_url':cached.get('source_url',cached['uri']),'identity_source_url':cached.get('identity_source_url',docket_url),'kind':cached.get('kind','photo'),'name':person['name'],'origin':'curated_cache'},folder,preserve=True)
                candidates.append(candidate)
            else:
                candidate_schema={'type':'object','additionalProperties':False,'properties':{
                    'candidates':{'type':'array','maxItems':3,'items':{'type':'object','additionalProperties':False,
                        'properties':{k:{'type':'string'} for k in ('url','source_url','identity_source_url','kind','private_note')},
                        'required':['url','source_url','identity_source_url','kind','private_note']}},
                    'private_notes':{'type':'array','items':{'type':'string'}}},'required':['candidates','private_notes']}
                from .photo_access import PhotoAccess
                access=PhotoAccess(cloud,settings);tools=access.definitions()
                research=run_codex(lease.dashboard,cloud,settings['codex_secret'],(ROOT/'prompts/public-output-policy.md').read_text()+'\n'+(ROOT/'prompts/photos.md').read_text(),
                    candidate_schema,model='gpt-6-luna',inputs={'input/advocate.json':json.dumps(person),'input/docket.txt':docket},timeout_seconds=240,
                    tools=tools,tool_handler=access.invoke if tools else None)
                photo_notes.extend(research['private_notes'])
                for candidate in research['candidates']:
                    try:
                        from .photos import square_asset
                        candidates.append(square_asset(fetch(candidate['url'],4194304),{**candidate,'name':person['name'],'origin':'research'},
                            (lease.dashboard,cloud,settings,job,sid),folder))
                    except Exception as error:photo_notes.append(str(error)[:300] if isinstance(error,ValueError) else 'An image source or crop could not be prepared.')
            photos[sid]={'name':person['name'],'identity_evidence':person['identity_evidence'],'candidates':candidates,
                         'private_notes':photo_notes,
                         'approved_existing':candidates[0] if (cached or approved) and candidates else None}
        result={'case_metadata':oyez,'description':description,'titles':titles,'photos':photos,
                'participation':description.get('participation'),
                'oyez_content_used':bool(oyez),'private_notes':description['private_caveats']+description['private_editorial_notes']+title_notes}
    participation=result.get('participation')
    if not participation or participation.get('docket')!=job['docket'] or participation.get('argument_date')!=job['argument_date']:
        # Older resumable/editorial caches still need the new participation check.
        case={'docket':job['docket'],'case_name':job['case_name'],'argument_date':job['argument_date']}
        docket_url=f'https://www.supremecourt.gov/docket/docketfiles/html/public/{job["docket"]}.html'
        if prior:
            try:docket=fetch(f'https://www.supremecourt.gov/RSS/Cases/JSON/{job["docket"]}.json').decode()
            except Exception:docket=fetch(docket_url).decode()
        checked=generate_case_description(lease.dashboard,cloud,settings['codex_secret'],case,
            oyez=result['description']['fields'],materials=[{'id':'docket','title':'Official Court docket','url':docket_url,'text':docket}],
            profile={'shorten_long_oyez':False},check_participation=True)
        result['participation']=checked['participation']
    from .annotation_cards import CARD_WORKFLOW_VERSION
    if settings.get('annotation_cards_enabled',False) and result.get('annotations',{}).get('workflow_version')!=CARD_WORKFLOW_VERSION:
        from .annotation_cards import generate_cards
        lease.call('note',message='Sol is selecting annotation cards, delegating research to Luna and inspecting production previews.')
        result['annotations']=generate_cards(job,transcript,result,settings,cloud,lease,folder)
    annotations=result.get('annotations',{'cards':[],'assets':{},'private_notes':[]})
    participation=result.get('participation') or {}
    participation_notes=participation.get('private_notes',[])+[p['explanation'] for p in participation.get('justices',[]) if p['status'] in ('recused','uncertain')]
    review={'id':hashlib.sha256(job['id'].encode()).hexdigest()[:32],'revision':digest_json(result),
            'titles':result['titles'],'description':result['description']['fields'],'photos':result['photos'],
            'private_notes':result['private_notes']+annotations['private_notes']+participation_notes,'provenance':result['description']['provenance'],
            'cards':annotations['cards'],'card_revision':digest_json(annotations['cards'])}
    path=folder/'enrichment.json';path.write_text(json.dumps(result))
    uri=f'gs://{settings["bucket"]}/enrichment/{job["id"]}/{uuid.uuid4().hex}.json';cloud.storage_upload(path,uri,'application/json')
    saved={'enrichment_uri':uri,'title':job.get('selected_title') or result['titles'][0]['title']}
    state=lease.call('enrichment_review',review=review,result=saved)
    if state['needs_review']:return None
    return saved
