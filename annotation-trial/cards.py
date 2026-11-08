"""Local annotation-card workbench: validate, check evidence, render production previews.

    python3 annotation-trial/cards.py CASE_DIR check            # validate all cards + evidence
    python3 annotation-trial/cards.py CASE_DIR render [ID ...]  # production preview frames
    python3 annotation-trial/cards.py CASE_DIR sheet            # contact sheets of all renders

CASE_DIR contains cards.json, cloud/aligned.json, preview/ (cloud bundle + card renderer)
and sources/. Validation reuses the cloud's cue_for (timing, fields, underline rules).
"""
import json, re, subprocess, sys, unicodedata, html
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'cloud'))
from scotus_cloud.annotation_cards import cue_for  # noqa: E402

NODE = '/opt/homebrew/opt/node@18/bin/node'


def normalized(value):
    value = html.unescape(re.sub('<[^>]+>', ' ', value))
    value = unicodedata.normalize('NFKC', value)
    value = value.translate(str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'", '–': '-', '—': '-', '­': ''}))
    value = value.replace("''", '"').replace('``', '"')
    value = re.sub(r'-\s*', '', value)  # line-break hyphens and real hyphens compare equal
    value = re.sub(r'\s+([,.;:])', r'\1', value)  # tag stripping leaves 'Hall , 440'
    return ' '.join(value.casefold().split())


_pages = {}
def pages(path):
    if path not in _pages:
        if path.suffix == '.pdf':
            text = subprocess.run(['pdftotext', str(path), '-'], capture_output=True, text=True, check=True).stdout
            _pages[path] = [normalized(p) for p in text.split('\f')]
        else:
            _pages[path] = [normalized(path.read_text())]
    return _pages[path]


def check_evidence(case, card):
    errors = []
    for e in card['evidence']:
        source = case / 'sources' / e['source']
        if not source.exists():
            errors.append(f"missing source {e['source']}")
            continue
        p = pages(source)
        if not 1 <= e['page'] <= len(p) or normalized(e['quote']) not in p[e['page'] - 1]:
            hits = [i + 1 for i, text in enumerate(p) if normalized(e['quote']) in text]
            errors.append(f"quote not on {e['source']} p.{e['page']}" + (f" (found on {hits})" if hits else ' (not found)'))
    cue = card['cue']
    shown = cue.get('quote') or (cue.get('text') if cue['kind'] in ('Statute', 'Rule') else '')
    if shown:
        passages = [pages(case / 'sources' / e['source'])[e['page'] - 1] for e in card['evidence'] if (case / 'sources' / e['source']).exists()]
        for segment in re.split(r'\.{3}|…', shown):
            if normalized(segment) and not any(normalized(segment) in p for p in passages):
                errors.append(f'displayed text differs from source: {segment.strip()[:60]!r}')
    return errors


def load(case):
    data = json.loads((case / 'cards.json').read_text())
    transcript = json.loads((case / 'cloud' / 'aligned.json').read_text())
    return data, transcript


def cues(case, data, transcript, verbose=True):
    out, ok = [], True
    for card in data['cards']:
        errors = []
        try:
            # Trial: Excerpt/Record cards may name what is excerpted ("Opinion excerpt");
            # the cloud's cue_for still only allows an empty label or the card type.
            label = card['cue'].get('label') if card['cue']['kind'] in ('Excerpt', 'Record') else None
            plain = {k: v for k, v in card['cue'].items() if not (label and k == 'label')}
            cue = cue_for({**card, 'cue_json': json.dumps(plain)}, transcript)
            if label:
                cue['label'] = label
            out.append((card, cue))
        except ValueError as error:
            errors.append(str(error))
        errors += check_evidence(case, card)
        paragraphs = transcript['paragraphs']
        window = ' '.join(p['text'] for p in paragraphs[max(0, card['start_block'] - 3):card['end_block']])
        for phrase in card['cue'].get('highlight', []):
            if not re.search(re.escape(phrase).replace(r'\ ', r'\s+'), window, re.I):
                errors.append(f'underline phrase not spoken here: {phrase!r}')
        if errors:
            ok = False
        if verbose:
            span = f"{out[-1][1]['start']:.0f}-{out[-1][1]['end']:.0f}s" if out and out[-1][0] is card else ''
            print(f"{card['id']:28} {span:12} {'OK' if not errors else '; '.join(errors)}")
    ordered = sorted(out, key=lambda c: c[1]['start'])
    for (a, ca), (b, cb) in zip(ordered, ordered[1:]):
        if ca['end'] > cb['start'] + .001:
            ok = False
            print(f"OVERLAP {a['id']} / {b['id']}")
    return out, ok


def job_id(case):
    return next((case / 'preview' / 'json').glob('*-audio.json')).name[:-len('-audio.json')]


def render(case, ids):
    data, transcript = load(case)
    out, _ = cues(case, data, transcript, verbose=False)
    jid = job_id(case)
    # Keep the workbench on the same approved presentation as the next cloud build.
    from scotus_cloud.presentation_sources import verified_source
    for name in ('index.html', 'script.js'):
        (case / 'preview' / name).write_text(verified_source('renderer/' + name))
    target = case / 'preview' / 'json' / f'{jid}-cards.json'
    (case / 'renders').mkdir(exist_ok=True)
    for card, cue in out:
        if ids and card['id'] not in ids:
            continue
        target.write_text(json.dumps({'cues': [cue]}))
        image = case / 'renders' / f"{card['id']}.jpg"
        result = subprocess.run([NODE, str(REPO / 'cloud/render/original.js'), 'card', str(case / 'preview'), jid, str(card['start_block']), str(image)],
                                capture_output=True, text=True, env={'NODE_PATH': str(REPO / 'node_modules'), 'PATH': '/usr/bin:/bin:/opt/homebrew/bin'})
        print(card['id'], 'rendered' if result.returncode == 0 else 'FAILED ' + result.stderr.strip()[-300:])
    # leave all cues in place for clip rendering
    target.write_text(json.dumps({'cues': [c for _, c in sorted(out, key=lambda c: c[1]['start'])]}))


def sheet(case):
    data, _ = load(case)
    ids = [c['id'] for c in data['cards'] if (case / 'renders' / f"{c['id']}.jpg").exists()]
    renders = case / 'renders'
    inputs = sum([['-i', str(renders / f'{i}.jpg.card.jpg')] for i in ids], [])
    pads = ''.join(f'[{n}]scale=1100:-2,pad=1100:ih+16:0:0:white[v{n}];' for n in range(len(ids)))
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', *inputs, '-filter_complex', pads + ''.join(f'[v{n}]' for n in range(len(ids))) + f'vstack=inputs={len(ids)}', str(case / 'cards-sheet.jpg')], check=True)
    cols = 2
    inputs = sum([['-i', str(renders / f'{i}.jpg')] for i in ids], [])
    scale = ''.join(f'[{n}]scale=960:540[f{n}];' for n in range(len(ids)))
    layout = '|'.join(f'{(n % cols) * 960}_{(n // cols) * 540}' for n in range(len(ids)))
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', *inputs, '-filter_complex', scale + ''.join(f'[f{n}]' for n in range(len(ids))) + f'xstack=inputs={len(ids)}:layout={layout}:fill=white', '-frames:v', '1', str(case / 'frames-sheet.jpg')], check=True)
    print('wrote cards-sheet.jpg and frames-sheet.jpg')


def exhibit(case, source, number, quote, mark=None):
    """Crop a PDF page to the paragraph(s) containing quote, highlighting it (as the cloud's cards_exhibit)."""
    import hashlib, io
    from xml.etree import ElementTree as ET
    from PIL import Image, ImageDraw
    pdf = case / 'sources' / source
    bbox = subprocess.run(['pdftotext', '-bbox', '-f', str(number), '-l', str(number), str(pdf), '-'], capture_output=True, text=True, check=True).stdout
    node = ET.fromstring(bbox).find('.//{*}page')
    words = [{'text': w.text or '', 'box': [float(w.attrib[k]) for k in ('xMin', 'yMin', 'xMax', 'yMax')]} for w in node.findall('.//{*}word')]
    width, height = float(node.attrib['width']), float(node.attrib['height'])
    combined, ranges = '', []
    for w in words:
        start = len(combined)
        combined += normalized(w['text']) + ('' if w['text'].endswith('-') else ' ')
        ranges.append((start, len(combined)))
    needle = normalized(quote)
    start = combined.find(needle)
    if start < 0:
        raise SystemExit('quote not found on page')
    chosen = [w for w, (a, b) in zip(words, ranges) if b > start and a < start + len(needle)]
    marked = chosen
    if mark:
        m = combined.find(normalized(mark), start)
        marked = [w for w, (a, b) in zip(words, ranges) if b > m and a < m + len(normalized(mark))]
    stem = case / 'renders' / f'page-{number}'
    subprocess.run(['pdftoppm', '-f', str(number), '-l', str(number), '-scale-to', '3600', '-singlefile', '-png', str(pdf), str(stem)], check=True)
    image = Image.open(str(stem) + '.png').convert('RGB')
    sx, sy = image.width / width, image.height / height
    draw = ImageDraw.Draw(image, 'RGBA')
    for w in marked:
        x0, y0, x1, y1 = w['box']
        draw.rectangle((x0 * sx, y0 * sy, x1 * sx, y1 * sy), fill=(255, 204, 48, 65))
    top = max(0, min(w['box'][1] for w in chosen) - 3)
    bottom = min(height, max(w['box'][3] for w in chosen) + 7)
    left = max(0, min(w['box'][0] for w in words) - 30)
    right = min(width, max(w['box'][2] for w in words) + 30)
    image = image.crop((int(left * sx), int(top * sy), int(right * sx), int(bottom * sy)))
    buf = io.BytesIO()
    image.save(buf, 'JPEG', quality=93)
    data = buf.getvalue()
    path = 'cards/assets/' + hashlib.sha256(data).hexdigest() + '.jpg'
    target = case / 'preview' / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    Path(str(stem) + '.png').unlink()
    print(path, image.size)


if __name__ == '__main__':
    case = Path(sys.argv[1]).resolve()
    command = sys.argv[2]
    if command == 'check':
        data, transcript = load(case)
        print('valid' if cues(case, data, transcript)[1] else 'INVALID')
    elif command == 'render':
        render(case, set(sys.argv[3:]))
    elif command == 'sheet':
        sheet(case)
    elif command == 'exhibit':  # exhibit SOURCE PAGE QUOTE
        exhibit(case, sys.argv[3], int(sys.argv[4]), sys.argv[5], sys.argv[6] if len(sys.argv) > 6 else None)
