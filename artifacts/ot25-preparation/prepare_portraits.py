"""Apply visually selected square boxes, preserving every source image."""
from pathlib import Path
import json,hashlib
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parent

def selected_sources():
    sources={}
    for folder in ('originals','replacements'):
        for p in (ROOT/folder).glob('*.source.json'):
            value=json.loads(p.read_text())
            if value.get('status')=='unresolved':continue
            slug=p.name.removesuffix('.source.json').replace('-','_')
            value.setdefault('original_file','originals/'+Path(value.get('path',p.stem+'.jpg')).name)
            image=ImageOps.exif_transpose(Image.open(ROOT/value['original_file']))
            value.update(width=image.width,height=image.height)
            sources[slug]=value
    return sources

def prepare():
    sources=selected_sources();plans=json.loads((ROOT/'crop-plan.json').read_text());approvals=json.loads((ROOT/'approvals.json').read_text());(ROOT/'square').mkdir(exist_ok=True)
    for slug,plan in plans.items():
        source=sources[slug];path=ROOT/source['original_file'];sha=hashlib.sha256(path.read_bytes()).hexdigest()
        if sha!=plan['source_sha256'] or sha!=approvals[slug]['source_sha256']:raise ValueError('Source changed: '+slug)
        image=ImageOps.exif_transpose(Image.open(path)).convert('RGB');left,top,right,bottom=plan['box']
        if not (0<=left<right<=image.width and 0<=top<bottom<=image.height and right-left==bottom-top):raise ValueError('Invalid square box: '+slug)
        crop=image.crop(plan['box']);crop.thumbnail((1024,1024),Image.Resampling.LANCZOS)
        output=ROOT/'square'/(slug+'.jpg');crop.save(output,quality=95,subsampling=0,optimize=True)
        plan.update(output_file=str(output.relative_to(ROOT)),width=crop.width,height=crop.height,sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    (ROOT/'crop-plan.json').write_text(json.dumps(plans,indent=2)+'\n');print('Prepared',len(plans),'square portraits')

if __name__=='__main__':prepare()
