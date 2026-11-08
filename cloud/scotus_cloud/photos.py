"""Vision-selected square assets; retained originals and owner feedback."""
import hashlib,io,json
from pathlib import Path
from urllib.error import HTTPError,URLError
from PIL import Image,ImageOps,ImageDraw,ImageFont
from .codex_auth import run_codex

ROOT=Path(__file__).resolve().parents[1]

def decoded(data):
    Image.MAX_IMAGE_PIXELS=40000000
    im=Image.open(io.BytesIO(data))
    if im.width*im.height>40000000:raise ValueError('Image exceeds the 40-megapixel portrait limit')
    # JPEG decoding can reduce resolution before allocating the full pixel array.
    # Retain the original bytes separately; crops need at most a 1024px output.
    im.draft('RGB',(2048,2048))
    im.load();im=ImageOps.exif_transpose(im);im.thumbnail((4096,4096))
    return im.convert('RGB')

def jpeg(im,edge=1024):
    im=im.copy();im.thumbnail((edge,edge));out=io.BytesIO();im.save(out,'JPEG',quality=90,optimize=True);return out.getvalue()

def crop_pixels(im,box,preview_size):
    pw,ph=preview_size
    x,y,side=(box[k] for k in ('x','y','size'))
    if any(type(v) is not int for v in (x,y,side)) or min(x,y)<0 or side<1 or x+side>pw or y+side>ph:
        raise ValueError('Crop box is outside the supplied image')
    scale=min(im.width/pw,im.height/ph);size=max(1,round(side*scale))
    left=min(round(x*im.width/pw),im.width-size);top=min(round(y*im.height/ph),im.height-size)
    if min(left,top)<0:raise ValueError('Invalid source crop')
    return im.crop((left,top,left+size,top+size)),{'x':left,'y':top,'size':size,'source_width':im.width,'source_height':im.height}

def square_asset(data,evidence,context,folder,*,previous=None,hint='',rejected_preview=None):
    from .enrichment import store_photo
    dashboard,cloud,settings,job,person=context
    im=decoded(data);source_preview=im.copy();source_preview.thumbnail((640,640))
    source_sha=hashlib.sha256(data).hexdigest();base=f'gs://{settings["bucket"]}/reviews/{job["id"]}/{person}/sources/{source_sha}'
    for name,value in [('original.bin',data),('preview.jpg',jpeg(source_preview))]:
        path=folder/name;path.write_bytes(value)
        try:cloud.storage_upload(path,base+'/'+name,'application/octet-stream' if name.endswith('.bin') else 'image/jpeg')
        except RuntimeError:
            if cloud.storage_bytes(base+'/'+name,max_bytes=4194304)!=value:raise
    if evidence.get('kind')=='photo':
        schema={'type':'object','additionalProperties':False,'properties':{
            'usable':{'type':'boolean'},'x':{'type':'integer','minimum':0},'y':{'type':'integer','minimum':0},
            'size':{'type':'integer','minimum':1},'private_note':{'type':'string'}},'required':['usable','x','y','size','private_note']}
        inputs={'input/photo.jpg':jpeg(source_preview),'input/crop.json':json.dumps({'name':evidence.get('name'),
            'width':source_preview.width,'height':source_preview.height,'previous_crop':previous,'owner_hint':hint})}
        images=['input/photo.jpg']
        if rejected_preview:
            inputs['input/rejected.jpg']=jpeg(ImageOps.fit(decoded(rejected_preview),(640,640)));images.append('input/rejected.jpg')
        policy=(ROOT/'prompts/public-output-policy.md').read_text()
        result=run_codex(dashboard,cloud,settings['codex_secret'],policy+'\n'+(ROOT/'prompts/crop.md').read_text(),schema,
            model='gpt-6.1-sol',inputs=inputs,images=images,timeout_seconds=120)
        if not result['usable']:raise ValueError('No usable square crop: '+result['private_note'][:250])
        cropped,crop=crop_pixels(im,result,(source_preview.width,source_preview.height))
        crop.update(method='codex-vision',model='gpt-6.1-sol',preview_box={k:result[k] for k in ('x','y','size')},preview_width=source_preview.width,preview_height=source_preview.height)
        note=result['private_note']
    else:
        cropped=ImageOps.pad(im,(1024,1024),color='#f1f1f1');crop={'method':'fit-square','source_width':im.width,'source_height':im.height};note='Full graphic fitted inside a square.'
    metadata={**evidence,'source_uri':base+'/original.bin','source_preview_uri':base+'/preview.jpg','source_sha256':source_sha,
              'crop':crop,'crop_note':note,'square_asset':True}
    return store_photo(cloud,settings['bucket'],job['id'],person,jpeg(cropped),metadata,folder)

def synthetic_initials(text):
    if not isinstance(text,str) or not 1<=len(text)<=4 or not text.isalpha():raise ValueError('Invalid initials')
    im=Image.new('RGB',(1024,1024),'#ededed');draw=ImageDraw.Draw(im)
    font=None
    for path in ('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf','DejaVuSans.ttf'):
        try:font=ImageFont.truetype(path,240 if len(text)<4 else 200);break
        except OSError:pass
    if font is None:font=ImageFont.load_default(size=200)
    box=draw.textbbox((0,0),text.upper(),font=font);draw.text(((1024-(box[2]-box[0]))/2-box[0],(1024-(box[3]-box[1]))/2-box[1]),text.upper(),fill='#444444',font=font)
    return jpeg(im)

def revise_photo(request,job,settings,cloud,dashboard,folder):
    from .enrichment import fetch, store_photo
    person=request['person'];item=job['review']['photos'][person]
    context=(dashboard,cloud,settings,job,person)
    if request['action']=='recrop':
        candidate=next(c for c in item['candidates'] if c['id']==request['candidate'])
        uri=candidate.get('source_uri') or candidate['portrait_uri'];data=cloud.storage_bytes(uri,max_bytes=4194304)
        expected=candidate.get('source_sha256') or candidate['sha256']
        if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Source image changed')
        evidence={k:v for k,v in candidate.items() if k in ('source_url','identity_source_url','kind','name','url','private_note')};evidence['origin']='research'
        rejected=cloud.storage_bytes(candidate['portrait_uri'],max_bytes=4194304)
        result=square_asset(data,evidence,context,folder,previous=candidate.get('crop'),hint=request.get('hint',''),rejected_preview=rejected)
        if result['sha256']==candidate['sha256']:raise ValueError('Codex returned the rejected crop again; provide a more specific hint.')
        return [result]
    hint=request.get('hint','').strip()
    if request['action']=='different' and hint.startswith('https://') and not any(c.isspace() for c in hint):
        # An explicit source supplied by the owner needs cropping, not rediscovery.
        # fetch retains the existing public-network and bounded-transfer checks.
        try:data=fetch(hint,4194304)
        except HTTPError as error:raise ValueError('Supplied image URL returned HTTP '+str(error.code)) from None
        except (URLError,TimeoutError):raise ValueError('Supplied image URL could not be downloaded; retry or upload the image file.') from None
        evidence={'url':hint,'source_url':hint,'identity_source_url':'','kind':'photo','name':item['name'],
                  'origin':'owner_url','private_note':'Portrait source explicitly supplied by the owner.'}
        return [square_asset(data,evidence,context,folder,hint=hint)]
    if request['action']=='different':
        from .photo_discovery import archive_listing, saved_portrait
        rejected=[c for c in item['candidates'] if c.get('rejected')]
        excluded={c.get(key) for c in rejected for key in ('url','source_url')}
        saved=saved_portrait(item['name'],archive_listing(fetch),fetch,excluded)
        if saved:
            data=fetch(saved['uri'],4194304)
            if not any(hashlib.sha256(data).hexdigest() in (c.get('source_sha256'),c.get('sha256')) for c in rejected):
                return [store_photo(cloud,settings['bucket'],job['id'],person,data,
                    {**saved,'origin':'curated_cache','square_asset':True},folder,preserve=True)]
    schema={'type':'object','additionalProperties':False,'properties':{'candidates':{'type':'array','maxItems':3,'items':{'type':'object','additionalProperties':False,
        'properties':{k:{'type':'string'} for k in ('url','source_url','identity_source_url','kind','initials','private_note')},
        'required':['url','source_url','identity_source_url','kind','initials','private_note']}},'private_note':{'type':'string'}},'required':['candidates','private_note']}
    docket_url=f'https://www.supremecourt.gov/RSS/Cases/JSON/{job["docket"]}.json'
    docket=fetch(docket_url).decode()
    from .photo_access import PhotoAccess
    access=PhotoAccess(cloud,settings);tools=access.definitions()
    result=run_codex(dashboard,cloud,settings['codex_secret'],(ROOT/'prompts/public-output-policy.md').read_text()+'\n'+(ROOT/'prompts/photos.md').read_text()+'\n'+(ROOT/'prompts/photo-feedback.md').read_text(),schema,
        model='gpt-6-luna',inputs={'input/request.json':json.dumps({k:request.get(k) for k in ('action','hint','candidate')}),'input/advocate.json':json.dumps({'name':item['name'],'identity_evidence':item.get('identity_evidence'),
            'rejected_candidates':[{k:c.get(k) for k in ('source_url','url','private_note','rejection')} for c in item['candidates'] if c.get('rejected')]}),'input/docket.txt':docket},timeout_seconds=240,
        tools=tools,tool_handler=access.invoke if tools else None)
    candidates=[];failures=[]
    for c in result['candidates']:
        if request['action']=='synthetic' and c['kind'] not in ('initials','logo'):continue
        if request['action']=='different' and c['kind'] not in ('photo','logo'):continue
        if request['action']=='different' and any(c['url'] in (old.get('url'),old.get('source_url')) for old in item['candidates'] if old.get('rejected')):continue
        try:
            data=synthetic_initials(c['initials']) if c['kind']=='initials' else fetch(c['url'],4194304)
            evidence={**c,'name':item['name'],'origin':'research'}
            choice=square_asset(data,evidence,context,folder,hint=request.get('hint',''))
            if request['action']=='different' and any(choice['source_sha256']==(old.get('source_sha256') or old.get('sha256')) for old in item['candidates'] if old.get('rejected')):continue
            candidates.append(choice)
        except Exception as error:
            failures.append(str(error)[:250] if isinstance(error,ValueError) else type(error).__name__)
    if not candidates:
        detail='; '.join(dict.fromkeys(failures)) or result.get('private_note','')[:250]
        raise ValueError('No usable replacement was found.'+(' '+detail if detail else ' Add a hint or choose another action.'))
    return candidates
