"""Native PDF extraction and speaker preparation, without interactive prompts."""

import hashlib
from pathlib import Path
import re
import subprocess
import json

from .vendor.pdf import extract_pdf
from .vendor.parser import parse_scotus_transcript, validate_turns


def one_edit_apart(first, second):
    if len(first) == len(second): return sum(a != b for a, b in zip(first, second)) == 1
    if abs(len(first) - len(second)) != 1: return False
    longer, shorter = (first, second) if len(first) > len(second) else (second, first)
    for index in range(len(longer)):
        if longer[:index] + longer[index+1:] == shorter: return True
    return False


def appearance_name(raw):
    # Court capitals sometimes retain a lowercase family-name prefix (McCLOUD).
    canonical=re.sub(r"\b(?:Mc|Mac|De|Di|Du|La|Le)(?=[A-Z])",lambda m:m[0].upper(),raw)
    return canonical.isupper()


def display_name_part(part):
    if len(part)<=2 and part.endswith('.'):return part
    match=re.match(r'^(Mc|Mac)(?=[A-Z])',part)
    return match[0]+part[len(match[0]):].title() if match else part.title()


def appearances(text):
    match = re.search(r'APPEARANCES:(.*?)(?:C\s*O\s*N\s*T\s*E\s*N\s*T\s*S|ORAL ARGUMENT)', text, re.S | re.I)
    entries = []
    if match:
        lines = match[1].splitlines()
        names = []
        for index, line in enumerate(lines):
            found = re.match(r'^\s*([^,]+),', line)
            if not found: continue
            raw = found.group(1).strip()
            if not appearance_name(raw): continue
            if index and ',' not in lines[index-1] and appearance_name(lines[index-1].strip()):
                prior = lines[index-1].strip()
                if prior not in ('ESQUIRE', 'PETITIONER', 'RESPONDENT'):
                    raw = prior + ' ' + raw
            raw = re.sub(r'^(?:GEN\.|GENERAL|MR\.|MS\.)\s+', '', raw)
            if len(raw.split()) < 2: continue
            names.append((index, raw))
        for position, (index, raw) in enumerate(names):
            stop = names[position+1][0] if position+1 < len(names) else len(lines)
            evidence = ' '.join(' '.join(lines[index:stop]).split())
            name = ' '.join(display_name_part(p) for p in raw.split())
            party = re.search(r';\s*(?:on\s+behalf\s+of|for)\s+(.+?)\.?$', evidence, re.I)
            entries.append({'name': name, 'last_name': name.split()[-1], 'source': 'official appearances',
                            'identity_evidence': evidence, 'role': 'for ' + party.group(1).rstrip('.') if party else 'Advocate'})
    return entries


def prepare_transcript(pdf, catalog=None, docket=None):
    text, extraction = extract_pdf(Path(pdf))
    cover_docket = re.search(r'\bNos?\.\s*(\d{2}(?:-\d+|[A-Z]\d+))', text[:4000])
    docket = docket or (cover_docket.group(1) if cover_docket else Path(pdf).parent.name)
    alias_path = Path(__file__).with_name('speaker_aliases.json')
    known_aliases = json.loads(alias_path.read_text()).get(docket, {}) if alias_path.exists() else {}
    turns = parse_scotus_transcript(text, paragraph_mode='layout')
    warnings = validate_turns(turns)
    candidates = appearances(text)
    flat, paragraphs, speakers = '', [], {}
    catalog = catalog or {}
    for ti, turn in enumerate(turns):
        speaker = turn['speaker']
        if isinstance(speaker, dict):
            person = {**speaker, 'kind': 'justice', 'role': 'Chief Justice' if speaker['identifier'] == 'john_g_roberts_jr' else 'Justice'}
        else:
            surname = re.sub(r'^(MR\.|MS\.|GENERAL)\s*', '', speaker).strip().casefold()
            alias = known_aliases.get(speaker)
            if alias: surname = alias['appearance_surname']
            choices = [p for p in candidates if p['last_name'].casefold() == surname]
            corrected = False
            if not choices:
                choices = [p for p in candidates if one_edit_apart(p['last_name'].casefold(), surname)]
                corrected = bool(choices)
            if len(choices) != 1:
                raise ValueError(f'Advocate identity needs resolution: {speaker}')
            person = dict(choices[0])
            person['transcript_label'] = speaker
            if alias:
                person['identity_match'] = alias['source']
                person['identifier_aliases'] = [alias['legacy_id']]
            if corrected:
                person['identity_match'] = 'unique one-character surname difference in this PDF appearances list'
            person['identifier'] = re.sub(r'[^a-z0-9]+', '_', person['name'].lower()).strip('_')
            person['kind'] = 'advocate'
            person.setdefault('role', 'Advocate')
        entry = catalog.get(person['identifier'], {})
        if isinstance(speaker, dict):
            person.update(entry)
        else:
            docket = docket or Path(pdf).parent.name
            # Names alone cannot identify lawyers across unrelated dockets.
            if docket in entry.get('dockets', []):
                person.update(entry)
            else:
                person['identifier'] = 'advocate_' + re.sub(r'[^a-z0-9]+', '_', docket.casefold()) + '_' + person['identifier']
        sid = person['identifier']
        previous = speakers.get(sid, {})
        label = speaker.get('name') if isinstance(speaker, dict) else speaker
        person['transcript_labels'] = list(dict.fromkeys(previous.get('transcript_labels', []) + [label]))
        aliases = list(dict.fromkeys(previous.get('identifier_aliases', []) + person.get('identifier_aliases', [])))
        if aliases: person['identifier_aliases'] = aliases
        if previous.get('identity_match') and not person.get('identity_match'): person['identity_match'] = previous['identity_match']
        corrections = previous.get('identity_corrections', [])
        if person.get('identity_match') and label not in corrections: corrections = corrections + [label]
        if corrections: person['identity_corrections'] = corrections
        speakers[sid] = person
        for pi, paragraph in enumerate(turn['paragraphs']):
            paragraphs.append({'text': paragraph, 'speaker': sid, 'turn': ti, 'paragraph': pi,
                               'section': turn['section'], 'turn_start': pi == 0,
                               'start_offset': len(flat), 'end_offset': len(flat) + len(paragraph)})
            flat += paragraph + '\n'
    appearance_surnames=[p['last_name'] for p in candidates if p.get('role')!='Advocate']
    spoken={re.sub(r'\W','',p['last_name']).casefold() for p in speakers.values() if p['kind']=='advocate'}
    missing=[name for name in appearance_surnames if re.sub(r'\W','',name).casefold() not in spoken]
    if missing:raise ValueError('Advocate appearance has no parsed speaking turn: '+', '.join(missing))
    return {'schema_version': 1, 'text': flat.rstrip('\n'), 'paragraphs': paragraphs,'appearance_surnames':appearance_surnames,
            'speakers': speakers, 'extraction': {'method': extraction['method'], 'sha256': extraction['source_sha256']},
            'warnings': warnings}


def audio_duration(path):
    output = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)])
    return float(json.loads(output)['format']['duration'])


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()
