"""Rebuild the local gallery from provenance, owner approvals and square crops."""
import html,json
from pathlib import Path
from prepare_portraits import selected_sources

ROOT=Path(__file__).resolve().parent
inventory=json.loads((ROOT/'inventory.json').read_text())
sources=selected_sources()
approvals=json.loads((ROOT/'approvals.json').read_text()) if (ROOT/'approvals.json').exists() else {}
plans=json.loads((ROOT/'crop-plan.json').read_text()) if (ROOT/'crop-plan.json').exists() else {}
unresolved={}
for path in (ROOT/'originals').glob('*.source.json'):
    value=json.loads(path.read_text())
    if value.get('status')=='unresolved':unresolved[path.name.removesuffix('.source.json').replace('-','_')]=value.get('notes','')
people=[]
for slug,person in inventory['advocates'].items():
    if person['existing_image']:continue
    source=sources.get(slug);evidence=[]
    for docket in person['cases']:
        path=ROOT/'dockets'/(docket.strip()+'.json')
        if path.exists():
            docket_data=json.loads(path.read_text())
            evidence.extend({'docket':docket.strip(),'text':event['Text']} for event in docket_data.get('ProceedingsandOrder',[]) if event.get('Text','').startswith('Argued.'))
    approved=bool(source and approvals.get(slug,{}).get('source_sha256')==source['sha256'])
    crop=plans.get(slug) if source and plans.get(slug,{}).get('source_sha256')==source['sha256'] else None
    if source:source={**source,'name':person['name'],'approval':'approved' if approved else 'pending'}
    people.append({'id':slug,**person,'status':'approved' if approved else 'candidate_for_review' if source else 'unresolved',
                   'candidate':source,'crop':crop,'private_notes':unresolved.get(slug,'') if not source else '', 'docket_evidence':evidence})
counts={'cases':len(inventory['cases']),'unique_advocates':len(inventory['advocates']),
        'existing_portraits':sum(bool(p['existing_image']) for p in inventory['advocates'].values()),
        'new_candidates':sum(bool(p['candidate']) for p in people),'approved':sum(p['status']=='approved' for p in people),
        'square_crops':sum(bool(p['crop']) for p in people),'unresolved':sum(not p['candidate'] for p in people)}
report={'term':2025,'scope':'Calendar-2026 OT25 arguments; coverage checked against the Court audio index and current Oyez listing.',
        'counts':counts,'metadata_summary':'Fresh Oyez metadata and official Court dockets are saved for all 31 arguments. All have case descriptions, questions presented and advocate information; 28 have decision metadata.',
        'advocates':people,'approval':'Owner approvals are tied to source-image hashes. Crops use visually selected boxes; originals are preserved.'}
(ROOT/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
escape=lambda value:html.escape(str(value),quote=True)
parts=['''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>OT25 advocate preparation</title><style>
body{font:16px/1.45 system-ui;max-width:1280px;margin:32px auto;padding:0 20px;color:#222;background:#fafafa}h1{font-size:26px}h2{font-size:19px;margin:12px 0 4px}p{margin:8px 0}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}article{padding:18px;border:1px solid #ccc;background:white}img{width:100%;aspect-ratio:1;object-fit:contain;background:#eee}small{color:#555}details{margin:12px 0}a{color:inherit}.links{display:flex;flex-wrap:wrap;gap:8px 16px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}.inventory{overflow-x:auto}
</style></head><body><h1>OT25 advocate preparation</h1>''']
parts+=['<p>'+escape(report['metadata_summary'])+'</p>', '<p>'+escape(' · '.join(str(counts[key])+' '+label for key,label in [('cases','arguments'),('existing_portraits','existing portraits'),('approved','approved images'),('square_crops','square crops'),('unresolved','unresolved')]))+'</p>', '<main>']
for person in people:
    source=person['candidate'];crop=person['crop']
    parts+=['<article><h2>'+escape(person['name'])+'</h2><p>'+escape(', '.join(person['cases']))+'</p>']
    if source:
        preview=crop['output_file'] if crop else source['original_file']
        dimensions=(crop['width'],crop['height']) if crop else (source['width'],source['height'])
        parts+=['<a href="'+escape(preview)+'"><img src="'+escape(preview)+'" alt="'+escape(person['name'])+'"></a>',
                '<p><small>'+escape(f"{dimensions[0]} × {dimensions[1]} · "+('square crop · ' if crop else '')+person['status'].replace('_',' '))+'</small></p>',
                '<p class="links"><a href="'+escape(source['original_file'])+'">Source image</a><a href="'+escape(source['source_url'])+'">Source website</a></p>',
                '<details><summary>Source and crop details</summary><p>'+escape(source.get('identity_evidence',''))+'</p>']
        if source.get('notes'):parts+=['<p>'+escape(source['notes'])+'</p>']
        parts+=['<p>'+escape(f"Source: {source['width']} × {source['height']}")+'</p>']
        if crop:parts+=['<p>'+escape('Crop box: '+str(crop['box']))+'</p>']
        parts+=['</details>']
    else:parts+=['<p>Photo still unresolved.</p><p>'+escape(person['private_notes'])+'</p>']
    parts+=['<details><summary>Official identity evidence</summary>'+''.join('<p>'+escape(e['docket']+': '+e['text'])+'</p>' for e in person['docket_evidence'])+'</details></article>']
parts+=['</main><h2>Case inventory</h2><div class="inventory"><table><tr><th>Date</th><th>Case</th><th>Metadata</th><th>Cached transcript</th></tr>']
for case in inventory['cases']:
    docket=case['docket'].strip()
    parts+=['<tr><td>'+escape(case['dates'][0])+'</td><td>'+escape(case['name']+' ('+docket+')')+'</td><td><a href="metadata/'+escape(docket)+'.json">Oyez</a> · <a href="dockets/'+escape(docket)+'.json">Docket</a></td><td>'+('Available' if case['transcript_cache'] else 'Missing')+'</td></tr>']
parts+=['</table></div></body></html>']
(ROOT/'index.html').write_text('\n'.join(parts))
print(counts)
