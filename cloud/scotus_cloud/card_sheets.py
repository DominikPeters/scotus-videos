"""Contact sheets use actual production frames, with readable card IDs and times."""
import base64
import io
import json
from PIL import Image, ImageDraw, ImageFont


def contact_sheet(tools, cards, check=lambda: None):
    if len(cards) > 40: raise ValueError('Use at most 40 cards per editorial pass')
    if not cards: return {'contentItems': [{'type': 'inputText', 'text': 'No cards proposed. Record explicit editorial omissions; no contact-sheet images are needed.'}]}
    frames = []; records = []
    for card in cards:
        check()
        result = tools.render(card)['contentItems']
        info = json.loads(result[0]['text'])
        frame = next(item['imageUrl'] for item in result if item['type'] == 'inputImage')
        data = base64.b64decode(frame.split(',', 1)[1], validate=True)
        image = Image.open(io.BytesIO(data)).convert('RGB'); image.thumbnail((960, 540))
        frames.append(image)
        records.append({'id': card['id'], 'start': info['start'], 'end': info['end'], 'metrics': info.get('metrics', {})})
    content = [{'type': 'inputText', 'text': json.dumps({'cards': records,
                'instructions': 'Inspect every full-frame tile. Shorten dense content; Sol will render and inspect your final revisions.'})}]
    try: font = ImageFont.truetype('DejaVuSans.ttf', 24)
    except OSError: font = ImageFont.load_default(size=24)
    for offset in range(0, len(frames), 4):
        page = Image.new('RGB', (1920, 1160), '#ffffff'); draw = ImageDraw.Draw(page)
        for n, frame in enumerate(frames[offset:offset + 4]):
            x = (n % 2) * 960; y = (n // 2) * 580
            record = records[offset + n]
            clock = lambda value: f'{int(value) // 60}:{int(value) % 60:02d}'
            label = f"{record['id'][:48]}   {clock(record['start'])} - {clock(record['end'])}"
            draw.text((x + 12, y + 5), label, fill='#111111', font=font)
            page.paste(frame, (x, y + 40))
        data = b''
        for quality in (75, 65, 55, 45, 35):
            output = io.BytesIO(); page.save(output, 'JPEG', quality=quality); data = output.getvalue()
            if len(data) <= 131072: break
        if len(data) > 131072: raise ValueError('Contact sheet exceeds the image budget; simplify the proposed layout')
        content.append({'type': 'inputImage', 'imageUrl': 'data:image/jpeg;base64,' + base64.b64encode(data).decode()})
    return {'contentItems': content}

