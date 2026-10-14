"""Bounded English CTC fine alignment with its own greedy coarse anchors.

Acoustic inference is windowed; the global transcript is NEVER backtracked in
one quadratic lattice. Greedy recognized phrases locate matching windows first.
"""

import bisect
import difflib
import math
import re
import unicodedata


LEXICAL = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


class AlignmentReview(ValueError):
    pass


def normalized(text):
    return unicodedata.normalize('NFKC', text).casefold().replace('’', "'")


def find_windows(text, recognized, duration, max_seconds=150, max_unanchored_seconds=35):
    """Use coarse matches to bound work, not to reject imperfect recognition."""
    words = list(re.finditer(r'\S+', text))
    lexical = list(LEXICAL.finditer(text))
    starts = [w.start() for w in words]
    source = [normalized(w.group()) for w in lexical]
    target = [normalized(w['text']) for w in recognized]
    matcher = difflib.SequenceMatcher(None, source, target, autojunk=False)
    anchors = {}
    for run in matcher.get_matching_blocks():
        if run.size < 4:
            continue
        for offset in range(run.size):
            source_word = lexical[run.a + offset]
            wi = bisect.bisect_right(starts, source_word.start()) - 1
            time = recognized[run.b + offset]['start']
            anchors.setdefault(wi, time)
    ordered=[];warnings=[]
    for wi,timestamp in sorted(anchors.items()):
        if not math.isfinite(timestamp) or not 0<=timestamp<duration or (ordered and timestamp<=ordered[-1][1]):
            warnings.append({'kind':'discarded_coarse_anchor','source_word':wi});continue
        ordered.append((wi,timestamp))
    if len(ordered)<8:
        raise AlignmentReview(f'Only {len(ordered)} usable coarse anchors; cannot bound fine alignment')
    for a,b in zip([(0,0.0),*ordered],[*ordered,(len(words),duration)]):
        if b[1]-a[1]>max_unanchored_seconds:
            warnings.append({'kind':'sparse_coarse_region','source_start':a[0],'source_end':b[0],
                             'audio_start':a[1],'audio_end':b[1],'seconds':round(b[1]-a[1],3)})
    if ordered[0][0]>150 or len(words)-ordered[-1][0]>150:
        warnings.append({'kind':'unmatched_transcript_end','prefix_words':ordered[0][0],
                         'suffix_words':len(words)-ordered[-1][0]-1})
    cores = [0]
    cursor = 0
    while cursor < len(words):
        current = next((a for a in ordered if a[0] >= cursor), None)
        if current is None:
            break
        later=[a for a in ordered if a[0]>cursor]
        target=(current[1] if cursor else 0.0)+max_seconds
        if not later or duration<=target:
            break
        within=[a for a in later if a[1]<=target]
        following=within[-1] if within else later[0]
        cores.append(following[0]); cursor = following[0]
    cores.append(len(words))
    windows = []
    for index, (begin, end) in enumerate(zip(cores, cores[1:])):
        left = max(0, begin - 12); right = min(len(words), end + 12)
        left_anchor = next((a for a in reversed(ordered) if a[0] <= left), ordered[0])
        right_anchor = next((a for a in ordered if a[0] >= right), ordered[-1])
        left = left_anchor[0] if left else 0
        right = min(len(words), right_anchor[0] + 1) if right < len(words) else len(words)
        audio_start = max(0, left_anchor[1] - .5) if left else 0
        audio_end = min(duration, right_anchor[1] + 1) if right < len(words) else duration
        if audio_end - audio_start > max_seconds + 2 * max_unanchored_seconds + 15:
            raise AlignmentReview(f'Fine-alignment window {audio_start:.2f}–{audio_end:.2f}s '
                                  f'({audio_end-audio_start:.2f}s), source words {left}–{right}, exceeds '
                                  f'the {max_seconds+2*max_unanchored_seconds+15}s compute bound')
        windows.append({'index': index, 'core_start': begin, 'core_end': end,
                        'context_start': left, 'context_end': right,
                        'audio_start': audio_start, 'audio_end': audio_end,
                        'text': text[words[left].start():words[right - 1].end()]})
    return windows, words, {'coarse_anchored_words': len(anchors), 'source_words': len(words),
                            'largest_anchor_gap_seconds': max(b[1] - a[1] for a, b in zip(ordered, ordered[1:])),
                            'warnings':warnings}


def spoken_year(text):
    """Alignment-only pronunciation; keep the official year label unchanged."""
    match=re.fullmatch(r'(1[0-9]{3}|20[0-9]{2})[?.!,;:]*',text.strip().strip('\"\'“”‘’'))
    if not match:return None
    number=int(match[1])
    small=('zero one two three four five six seven eight nine ten eleven '
           'twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen').split()
    tens=('','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety')
    def under_hundred(value):
        return small[value] if value<20 else tens[value//10]+(' '+small[value%10] if value%10 else '')
    century,remainder=divmod(number,100)
    if century==20 and remainder<10:return 'two thousand'+(' '+small[remainder] if remainder else '')
    return under_hundred(century)+(' hundred' if remainder==0 else ' oh '+small[remainder] if remainder<10 else ' '+under_hundred(remainder))


def year_alignment_tokens(tokens,labels,source_words,preprocess_text):
    """Expand year targets, retaining one label/span per original source token."""
    indices=[i for i,label in enumerate(labels) if label!='<star>']
    if len(indices)!=len(source_words):raise AlignmentReview('Year target source mapping changed')
    for word,index in zip(source_words,indices):
        year=spoken_year(word)
        if year is not None:
            converted,spoken_labels=preprocess_text(year,romanize=True,language='eng',split_size='word',star_frequency='segment')
            tokens[index]=' '.join(token for token,label in zip(converted,spoken_labels) if label!='<star>')
    return tokens


def greedy_words(emissions, tokenizer, stride):
    vocabulary = {v: k for k, v in tokenizer.get_vocab().items()}
    # Ignore any synthetic wildcard channel without dropping a real letter.
    ids = emissions[:, :max(vocabulary) + 1].argmax(-1).tolist()
    previous, characters, first, words = -1, [], 0, []
    for frame, index in enumerate(ids):
        if index == previous:
            continue
        previous = index
        if index == tokenizer.pad_token_id:
            continue
        character = vocabulary.get(index, '')
        if character == '|':
            if characters:
                words.append({'text': ''.join(characters), 'start': first * stride / 1000})
                characters = []
        elif not character.startswith('<'):
            if not characters:
                first = frame
            characters.append(character)
    if characters:
        words.append({'text': ''.join(characters), 'start': first * stride / 1000})
    return words


def display_paragraphs(transcript,original_words,output,stage_paragraphs,duration):
    starts = [w.start() for w in original_words]
    paragraphs, warnings = [], []
    for pi, paragraph in enumerate(transcript['paragraphs']):
        first = bisect.bisect_left(starts, paragraph['start_offset'])
        end = bisect.bisect_left(starts, paragraph['end_offset'])
        index = next((i for i in range(first, end) if not output[i]['target_empty']), None)
        if pi in stage_paragraphs:
            preceding = next((i for i in range(first - 1, -1, -1) if not output[i]['target_empty']), None)
            following = next((i for i in range(end, len(output)) if not output[i]['target_empty']), None)
            boundary = output[preceding]['end'] if preceding is not None else (output[following]['start'] if following is not None else 0.0)
            if following is not None: boundary = min(boundary, output[following]['start'])
            paragraphs.append({**paragraph, 'start': max(paragraphs[-1]['start'] if paragraphs else 0.0, boundary), 'timing_policy': 'preceding_speech_end' if preceding is not None else 'following_speech_start'})
            warnings.append({'kind': 'stage_direction', 'paragraph': pi})
            continue
        if index is None:
            raise AlignmentReview('Paragraph has no usable spoken anchor')
        if re.match(r'^\s*[\[(]', paragraph['text']):
            warnings.append({'kind': 'stage_direction', 'paragraph': len(paragraphs)})
        paragraphs.append({**paragraph, 'start': output[index]['start']})
    for i,paragraph in enumerate(paragraphs):
        timestamp=paragraph['start']
        if not math.isfinite(timestamp) or not 0<=timestamp<=duration:
            raise AlignmentReview(f'Invalid displayed paragraph time at paragraph {i}: {timestamp}')
        if i and timestamp<paragraphs[i-1]['start']:
            backwards=paragraphs[i-1]['start']-timestamp
            if backwards>.25:
                raise AlignmentReview(f'Paragraph {i} starts {backwards:.3f}s backwards across windows')
            warnings.append({'kind':'paragraph_boundary_clamped','paragraph':i,'seconds':backwards})
            paragraph['start']=paragraphs[i-1]['start']
    return paragraphs,warnings


def align_recording(audio_path, transcript, model_path, progress=lambda *_: None, cpu_threads=4):
    import torch
    from ctc_forced_aligner import (load_alignment_model, load_audio, generate_emissions,
                                    preprocess_text, get_alignments, get_spans, postprocess_results)
    from .vendor.speech_spans import unpadded_spans
    if cpu_threads not in (1,2,4,8):raise ValueError('Unsupported alignment CPU thread count')
    torch.set_num_threads(cpu_threads)
    model, tokenizer = load_alignment_model('cpu', str(model_path), dtype=torch.float32)
    waveform = load_audio(str(audio_path), model.dtype, model.device)
    duration = len(waveform) / 16000
    progress(.02)
    emissions, stride = generate_emissions(model, waveform, window_length=30, context_length=2, batch_size=2)
    del waveform
    progress(.65)
    recognized = greedy_words(emissions, tokenizer, stride)
    windows, original_words, audit = find_windows(transcript['text'], recognized, duration)
    source_starts = [w.start() for w in original_words]
    alignment_words = [w.group() for w in original_words]
    stage_paragraphs = set()
    for pi, paragraph in enumerate(transcript['paragraphs']):
        if re.fullmatch(r'\s*\((?:Laughter\.?|No response\.?|Pause\.?|Inaudible\.?)\)\s*', paragraph['text'], re.I):
            stage_paragraphs.add(pi)
            first = bisect.bisect_left(source_starts, paragraph['start_offset'])
            last = bisect.bisect_left(source_starts, paragraph['end_offset'])
            for wi in range(first, last): alignment_words[wi] = '--'
    output, previous, seams = [None] * len(original_words), {}, []
    for index, window in enumerate(windows):
        frame_start = max(0, math.floor(window['audio_start'] * 1000 / stride))
        frame_end = min(len(emissions), math.ceil(window['audio_end'] * 1000 / stride))
        part = emissions[frame_start:frame_end]
        alignment_text = ' '.join(alignment_words[window['context_start']:window['context_end']])
        tokens, labels = preprocess_text(alignment_text, romanize=True, language='eng', split_size='word', star_frequency='segment')
        tokens=year_alignment_tokens(tokens,labels,alignment_words[window['context_start']:window['context_end']],preprocess_text)
        segments, scores, blank = get_alignments(part, tokens, tokenizer)
        spans = unpadded_spans(get_spans(tokens, segments, blank), blank)
        aligned = postprocess_results(labels, spans, stride, scores, 0.0)
        empty = [not tokens[i].strip() for i, label in enumerate(labels) if label != '<star>']
        if len(aligned) != window['context_end'] - window['context_start']:
            raise AlignmentReview('Fine-alignment source mapping changed')
        mapping = {}
        for n, word in enumerate(aligned):
            wi = window['context_start'] + n
            if normalized(word['text']) != normalized(alignment_words[wi]):
                raise AlignmentReview('Aligned text differs from original source')
            mapping[wi] = {'start': float(word['start']) + frame_start * stride / 1000,
                           'end': float(word['end']) + frame_start * stride / 1000,
                           'target_empty': empty[n]}
        shared = [i for i in mapping.keys() & previous.keys() if not mapping[i]['target_empty'] and not previous[i]['target_empty']]
        seams.append({'chunk': index, 'max_start_difference': max((abs(mapping[i]['start'] - previous[i]['start']) for i in shared), default=0)})
        for wi in range(window['core_start'], window['core_end']):
            output[wi] = mapping[wi]
        previous = mapping
        progress(.65 + .3 * (index + 1) / len(windows))
    paragraphs, warnings = display_paragraphs(transcript,original_words,output,stage_paragraphs,duration)
    warnings=list(audit.get('warnings',[]))+warnings
    for seam in seams:
        if seam['max_start_difference'] > .5:
            warnings.append({'kind': 'overlap_disagreement', **seam})
    return {'schema_version': 1, 'paragraphs': paragraphs, 'words': output,
            'duration_seconds': duration, 'coarse_audit': audit, 'seams': seams, 'warnings': warnings,
            'configuration': {'model': 'facebook/wav2vec2-base-960h', 'cpu_threads':cpu_threads,
                              'revision': '22aad52d435eb6dbaf354bdad9b0da84ce7d6156', 'star_frequency': 'segment'}}
