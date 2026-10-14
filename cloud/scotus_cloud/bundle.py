"""Assemble the original presentation with frozen case inputs, inside the cloud."""
import hashlib,json,shutil
from pathlib import Path
from urllib.request import urlopen

from .presentation_sources import RENDERER_ROOT,verified_source
from .presentation_data import presentation_audio,case_metadata
from .formatters import format_interactions


def make_bundle(folder,job,transcript,enrichment,cloud):
    root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    for name in ('index.html','script.js'):(root/name).write_text(verified_source("renderer/"+name))
    assets=json.loads((RENDERER_ROOT/'assets.json').read_text())
    for name,record in assets.items():
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        with urlopen(record['uri'],timeout=30) as response:data=response.read(4194305)
        if len(data)>4194304 or hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('Original asset hash differs')
        target.write_bytes(data)
    (root/'maps').mkdir(exist_ok=True);shutil.copy2(RENDERER_ROOT/'maps/circuits.svg',root/'maps/circuits.svg')
    metadata=case_metadata(job,transcript,enrichment);audio=presentation_audio(transcript)
    interactions=format_interactions(metadata,audio,transcript['audio']['duration_seconds'],oyez_content_used=enrichment['oyez_content_used'])
    if enrichment['description'].get('provenance',{}).get('facts_of_the_case',{}).get('method')=='codex':
        interactions['youtube_description']=interactions['youtube_description'].replace('*Facts of the case (from oyez.org)*','*Facts of the case*')
    interactions['youtube_title']=job.get('selected_title') or enrichment['titles'][0]['title']
    for sid,person in transcript['speakers'].items():
        if person['kind']=='advocate':
            choice=job.get('approved_photos',{}).get(sid)
            if not choice:raise ValueError('Advocate photo approval is missing')
            target=root/'advocates'/f'{sid}.jpg';target.parent.mkdir(exist_ok=True)
            cloud.storage_download(choice['portrait_uri'],target)
            if hashlib.sha256(target.read_bytes()).hexdigest()!=choice['sha256']:raise ValueError('Approved portrait changed')
    catalog=json.loads((RENDERER_ROOT.parent.parent/'speaker-catalog.json').read_text())
    portrait_credit=False
    for justice in metadata['heard_by'][0]['members']:
        target=root/'justices'/justice['thumbnail']['href'].split('/')[-1];target.parent.mkdir(exist_ok=True)
        local=catalog.get(justice['identifier'])
        uri=local['portrait_uri'] if local else justice.get('portrait_uri') or justice['thumbnail']['href']
        portrait_credit=portrait_credit or bool(local and 'oyez.org' in local.get('portrait_source',''))
        if uri.startswith('gs://'):cloud.storage_download(uri,target)
        else:
            with urlopen(uri,timeout=30) as response:data=response.read(4194305)
            if len(data)>4194304:raise ValueError('Justice asset too large')
            target.write_bytes(data)
    (root/'json').mkdir(exist_ok=True)
    for suffix,value in [('',metadata),('-audio',audio),('-interactions',interactions)]:
        (root/'json'/f'{job["id"]}{suffix}.json').write_text(json.dumps(value,ensure_ascii=False))
    annotations=enrichment.get('annotations',{})
    cards=annotations.get('cards',[]);selected=job.get('card_selections',{})
    if cards and job.get('cards_approved_revision')!=job.get('review',{}).get('card_revision'):raise ValueError('Annotation cards need owner sign-off')
    cues=[]
    for card in cards:
        if not selected.get(card['id'],False):continue
        from .annotation_cards import cue_for
        cue=cue_for(card,transcript);cues.append(cue)
        asset=annotations.get('assets',{}).get(cue.get('image'))
        if asset:
            target=root/cue['image'];target.parent.mkdir(parents=True,exist_ok=True);cloud.storage_download(asset['uri'],target,expected_sha256=asset['sha256'])
    (root/'json'/f'{job["id"]}-cards.json').write_text(json.dumps({'cues':cues},ensure_ascii=False))
    cards_oyez=any('oyez.org' in source.get('url','') for card in cards if selected.get(card['id']) for source in card.get('sources',[]))
    # Attribution is a data-driven text slot; the original source files are unchanged.
    if cards_oyez and not enrichment['oyez_content_used']:
        interactions['youtube_description']+='\nAnnotation sources include Oyez.org, licensed under CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/).'
        (root/'json'/f'{job["id"]}-interactions.json').write_text(json.dumps(interactions,ensure_ascii=False))
    credit='Case information: Oyez.org' if enrichment['oyez_content_used'] or cards_oyez else ('Justice portraits: Oyez.org' if portrait_credit else '')
    if portrait_credit and not enrichment['oyez_content_used']:
        interactions['youtube_description']=interactions['youtube_description'].replace('Not affiliated with oyez.org or the Supreme Court.', 'Justice portraits from oyez.org, licensed under a CC-BY-NC License (https://creativecommons.org/licenses/by-nc/4.0/).\nNot affiliated with oyez.org or the Supreme Court.')
        (root/'json'/f'{job["id"]}-interactions.json').write_text(json.dumps(interactions,ensure_ascii=False))
    (root/'credit.json').write_text(json.dumps({'text':credit}))
    return interactions
