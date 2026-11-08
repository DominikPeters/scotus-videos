"""Bounded OCR of a reader-selected PDF page; keep the original PDF provenance."""
import base64
import csv
import io
import json
from pathlib import Path
import shutil
import subprocess
from PIL import Image


def ocr_page(tools, source_id, number):
    source = tools.sources.get(source_id)
    if not source or not 1 <= number <= len(source['pages']): raise ValueError('Use a fetched PDF and a physical page number')
    page = source['pages'][number - 1]
    if not page.get('width') or not page.get('height'): raise ValueError('OCR requires an original PDF page')
    if len(page.get('words', [])) >= 20: return {'source_id': source_id, 'page': number, 'text': page['text'], 'cached': True, 'extraction': 'Existing PDF text layer retained'}
    if page.get('ocr'): return {'source_id': source_id, 'page': number, 'text': page['text'], 'cached': True}
    if not shutil.which('tesseract'): raise ValueError('OCR is unavailable in this worker image; flag this source as uncertain')
    pdf = source.get('pdf')
    if not pdf:
        if not source.get('pdf_uri'): raise ValueError('Original PDF is unavailable')
        pdf = tools.folder / (source_id + '.pdf'); tools.cloud.storage_download(source['pdf_uri'], pdf); source['pdf'] = pdf
    stem = tools.folder / (source_id + '-ocr-' + str(number)); image_path = Path(str(stem) + '.png')
    try:
        subprocess.run(['pdftoppm', '-f', str(number), '-l', str(number), '-scale-to', '2400', '-singlefile', '-png', str(pdf), str(stem)],
                       capture_output=True, check=True, timeout=45)
        raster = Image.open(image_path).convert('RGB')
        result = subprocess.run(['tesseract', str(image_path), 'stdout', 'tsv'], capture_output=True, check=True, timeout=45)
        if len(result.stdout) > 2097152: raise ValueError('OCR page exceeds the text budget')
        words = []
        for row in csv.DictReader(io.StringIO(result.stdout.decode()), delimiter='\t'):
            if not row.get('text', '').strip() or float(row['conf']) < 0: continue
            x, y, w, h = (int(row[key]) for key in ('left', 'top', 'width', 'height'))
            words.append({'text': row['text'], 'box': [x * page['width'] / raster.width, y * page['height'] / raster.height,
                            (x + w) * page['width'] / raster.width, (y + h) * page['height'] / raster.height]})
        text = ' '.join(w['text'] for w in words)
        if not text.strip() or len(text) > 60000: raise ValueError('OCR produced no bounded, readable text; retain the uncertainty')
        page.update(words=words, text=text, ocr=True)
        raster.thumbnail((1200, 1600))
        for quality in (75, 60, 45, 30):
            output = io.BytesIO(); raster.save(output, 'JPEG', quality=quality); data = output.getvalue()
            if len(data) <= 196608: break
        if len(data) > 196608: raise ValueError('OCR page preview exceeds the image budget')
        return {'contentItems': [{'type': 'inputText', 'text': json.dumps({'source_id': source_id, 'page': number,
                    'text': text, 'extraction': 'OCR; inspect the original page image for recognition errors'})},
                    {'type': 'inputImage', 'imageUrl': 'data:image/jpeg;base64,' + base64.b64encode(data).decode()}]}
    finally: image_path.unlink(missing_ok=True)
