"""Validate recording identities and compile exact video frame ranges."""

from datetime import date
import hashlib
import json
import math
import re


STAGES = ('prepare', 'enrich', 'align', 'plan', 'render', 'assemble', 'upload')


def alignment_cpus(job, cloud=None):
    """Use measured recording duration; 100 minutes is an inclusive boundary."""
    prepared=job.get('stages',{}).get('prepare',{}).get('result',{})
    duration=prepared.get('duration_seconds')
    if duration is None and cloud is not None and prepared.get('transcript_uri'):
        duration=cloud.storage_json(prepared['transcript_uri'],max_bytes=2097152).get('audio',{}).get('duration_seconds')
    try:duration=float(duration)
    except (TypeError,ValueError):return 4
    return 8 if math.isfinite(duration) and duration>=6000 else 4


def recording_id(docket, argument_date, recording='argument-1'):
    if not re.fullmatch(r'\d{2}(?:-\d+|[A-Z]\d+)', docket):
        raise ValueError('Invalid docket number')
    date.fromisoformat(argument_date)
    if not re.fullmatch(r'[a-z0-9-]{1,40}', recording):
        raise ValueError('Invalid recording identifier')
    return f'{argument_date}-{docket}-{recording}'


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def plan_video(manifest, chunk_seconds=300):
    """Quantize once; all shards cover nonoverlapping, contiguous frame ranges."""
    fps = manifest.get('render', {}).get('fps', 20)
    if fps != 20:
        raise ValueError('The first cloud renderer uses the existing 20 fps timeline')
    duration = manifest['audio']['duration_seconds']
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Invalid audio duration')
    if not manifest['paragraphs']:
        raise ValueError('No transcript paragraphs')
    events = []
    previous = -1
    for index, paragraph in enumerate(manifest['paragraphs']):
        start = paragraph['start']
        if not math.isfinite(start) or start < 0 or start >= duration or start < previous:
            raise ValueError('Paragraph starts must be ordered and within the recording')
        if paragraph['speaker'] not in manifest['speakers']:
            raise ValueError('Unresolved transcript speaker')
        frame = min(math.floor(start * fps + .5), math.ceil(duration * fps) - 1)
        if events and events[-1]['frame'] == frame:
            # One display state per output frame; preserve paragraphs in manifest.
            events[-1]['paragraph'] = index
        else:
            events.append({'frame': frame, 'paragraph': index})
        previous = start
    total = math.ceil(duration * fps)
    chunk_frames = max(1, round(chunk_seconds * fps))
    chunks = [{'index': i, 'first_frame': first, 'end_frame': min(first + chunk_frames, total)}
              for i, first in enumerate(range(0, total, chunk_frames))]
    return {'schema_version': 1, 'fps': fps, 'total_frames': total, 'events': events,
            'chunks': chunks, 'manifest_sha256': digest_json(manifest)}
