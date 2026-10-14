"""Luna research and Sol writing for the original case-description fields.

Callable preparation only: no worker is deployed here. Private evidence/notes
remain separate from the two fields consumed by the original presentation.
"""

from dataclasses import dataclass
from datetime import date
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from .codex_auth import run_codex, _validated_inputs
from .model import digest_json


ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('facts_of_the_case', 'question')


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.hidden += 1
        if tag in ('p', 'br', 'li', 'div'): self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'li', 'div'): self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def plain_text(value):
    parser = _Text(); parser.feed(value or '')
    return ' '.join(''.join(parser.parts).split())


def word_count(value):
    return len(value.split())


def description_profile(profile=None):
    defaults = json.loads((ROOT / 'editorial-profile.json').read_text())
    if profile is not None:
        if not isinstance(profile, dict) or set(profile) - set(defaults):
            raise ValueError('Unknown editorial profile settings')
        defaults.update(profile)
    limits = defaults['word_limits']
    if (not isinstance(limits, dict) or set(limits) != {*FIELDS, 'combined'} or
            any(type(value) is not int or not 1 <= value <= 500 for value in limits.values()) or
            type(defaults['shorten_long_oyez']) is not bool or
            type(defaults['max_writer_attempts']) is not int or not 1 <= defaults['max_writer_attempts'] <= 2):
        raise ValueError('Invalid description word/rewrite limits')
    for key in ('research_timeout_seconds', 'writer_timeout_seconds'):
        if type(defaults[key]) is not int or not 1 <= defaults[key] <= 900:
            raise ValueError('Invalid editorial timeout')
    for key in ('case_research_model', 'case_description_model'):
        if not isinstance(defaults[key], str) or not defaults[key].strip():
            raise ValueError('Choose explicit editorial models')
    if defaults['schema_version'] != 1:
        raise ValueError('Unsupported editorial profile')
    return defaults


def _validate_case(case):
    if not isinstance(case, dict) or any(not isinstance(case.get(key), str) or not case[key].strip()
            for key in ('docket', 'case_name', 'argument_date')):
        raise ValueError('Description needs docket, case_name and argument_date')
    return date.fromisoformat(case['argument_date'])


def _schema(name):
    return json.loads((ROOT / 'schemas' / (name + '.schema.json')).read_text())


def _check_schema(value, name):
    if next(Draft202012Validator(_schema(name)).iter_errors(value), None) is not None:
        raise ValueError('Invalid structured case-description result')


def _source_index(sources, argument_date, *, supplied_ids=()):
    index = {}
    for source in sources:
        key = source['id']
        if not key.strip() or key in index:
            raise ValueError('Source IDs must be nonempty and unique')
        if any(not isinstance(source.get(field), str) or not source[field].strip()
               for field in ('title', 'locator', 'relevant_passage')):
            raise ValueError('Sources need a title and relevant passage/locator')
        url = source['url']
        if url is None:
            if key not in supplied_ids:
                raise ValueError('A newly discovered source needs a URL')
        else:
            parts = urlsplit(url)
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
                raise ValueError('Use public HTTPS source URLs')
            if parts.hostname in ('oyez.org', 'www.oyez.org', 'api.oyez.org') and source['kind'] != 'oyez':
                raise ValueError('Oyez provenance must be explicit')
        if source['document_date'] is not None:
            published = date.fromisoformat(source['document_date'])
            if published > argument_date and source['kind'] != 'oyez':
                raise ValueError('A source postdates the argument')
        index[key] = source
    return index


def _writer_materials(materials, sources):
    """Keep bulk reading with Luna; hand Sol bounded evidence for focused checks."""
    supplied = {item.get('id'): item for item in materials}
    excerpts = []
    for source in sources.values():
        original = supplied.get(source['id'], {}).get('text')
        passage = source['relevant_passage']
        verification = 'check_source_link'
        if isinstance(original, str):
            if len(original) <= 4000:
                passage, verification = original, 'supplied_source_text'
            elif ' '.join(passage.split()) in ' '.join(original.split()):
                verification = 'matched_supplied_text'
        if source['kind'] == 'oyez' and source['id'].startswith('oyez:'):
            verification = 'supplied_oyez_field'
        excerpts.append({**source, 'text': passage, 'excerpt_check': verification})
    return excerpts


def _oyez_sources(oyez):
    href = oyez.get('href')
    return [{'id': 'oyez:' + field, 'title': 'Supplied Oyez ' + field,
             'url': href, 'kind': 'oyez', 'document_date': None,
             'locator': 'input/oyez.json#' + field,
             'relevant_passage': plain_text(oyez.get(field))[:2000]}
            for field in FIELDS if plain_text(oyez.get(field))]


def _actions(oyez, profile):
    counts = {field: word_count(plain_text(oyez.get(field))) for field in FIELDS}
    actions = {field: 'keep' if counts[field] else 'missing' for field in FIELDS}
    if profile['shorten_long_oyez']:
        over_combined = sum(counts.values()) > profile['word_limits']['combined']
        for field in FIELDS:
            if counts[field] and (counts[field] > profile['word_limits'][field] or over_combined):
                actions[field] = 'shorten'
    return actions


@dataclass(frozen=True)
class DescriptionTask:
    prompt: str
    schema: dict
    inputs: dict
    input_revision: str


def build_description_task(stage, case, oyez, materials, actions, profile, *, research=None, revision=None, sources=None):
    if stage not in ('case-research', 'case-description'):
        raise ValueError('Unknown description task')
    _validate_case(case)
    if not isinstance(materials, list) or any(not isinstance(item, dict) for item in materials):
        raise ValueError('Description materials must be a list of source records')
    request = {'field_actions': actions, 'word_limits': profile['word_limits']}
    policy = (ROOT / 'prompts/public-output-policy.md').read_text()
    prompt = policy + '\n\n' + (ROOT / 'prompts' / (stage + '.md')).read_text()
    inputs = {'POLICY.md': policy, 'input/case.json': json.dumps(case, ensure_ascii=False),
              'input/request.json': json.dumps(request), 'input/oyez.json': json.dumps(oyez, ensure_ascii=False),
              'input/materials.json': json.dumps(materials, ensure_ascii=False),
              'input/source-index.json': json.dumps(list((sources or {}).values()), ensure_ascii=False)}
    if research is not None: inputs['input/research.json'] = json.dumps(research, ensure_ascii=False)
    if revision is not None: inputs['input/revision.json'] = json.dumps(revision, ensure_ascii=False)
    _validated_inputs(inputs)
    schema = _schema(stage)
    return DescriptionTask(prompt, schema, inputs, digest_json({'prompt': prompt, 'schema': schema, 'inputs': inputs}))


def validate_case_research(research, case, oyez):
    _check_schema(research, 'case-research')
    supplied = _oyez_sources(oyez)
    sources = _source_index(research['sources'], _validate_case(case), supplied_ids=[s['id'] for s in supplied])
    for item in research['background'] + research['issues']:
        if not set(item['source_ids']) <= sources.keys():
            raise ValueError('Research refers to an unknown source')
    return research


class DescriptionTooLong(ValueError):
    def __init__(self, counts):
        super().__init__('Case description exceeds its word budget')
        self.counts = counts


def _validate_writer(result, sources, oyez, actions, profile):
    _check_schema(result, 'case-description')
    counts = {}
    for field in FIELDS:
        value = result[field]
        if actions[field] == 'keep':
            if value['text'] is not None or value['source_ids']:
                raise ValueError('Writer tried to replace a retained Oyez field')
            counts[field] = word_count(plain_text(oyez[field]))
            continue
        text = value['text']
        if (not isinstance(text, str) or not text.strip() or text != text.strip() or
                any(ord(char) < 32 and char not in '\n\t' for char in text) or
                not value['source_ids'] or not set(value['source_ids']) <= sources.keys()):
            raise ValueError('Description needs valid text and supporting sources')
        if actions[field] == 'shorten' and 'oyez:' + field not in value['source_ids']:
            raise ValueError('Condensed Oyez content needs its source credit')
        counts[field] = word_count(text)
    if any(actions[field] != 'keep' and counts[field] > profile['word_limits'][field] for field in FIELDS):
        raise DescriptionTooLong(counts)
    # An explicit preserve-long-Oyez override must not force a missing field to
    # be truncated. The default profile shortens those originals instead.
    if profile['shorten_long_oyez'] and sum(counts.values()) > profile['word_limits']['combined']:
        raise DescriptionTooLong(counts)
    return result


def _paragraph_html(text):
    return ''.join('<p>' + escape(paragraph.strip()) + '</p>'
                   for paragraph in text.split('\n\n') if paragraph.strip())


def public_case_fields(bundle):
    """Only the two legacy fields; no research, provenance or operator notes."""
    return {field: bundle['fields'][field] for field in FIELDS}


def generate_case_description(dashboard, cloud, secret_name, case, *, oyez=None, materials=None, profile=None):
    settings = description_profile(profile)
    argued = _validate_case(case)
    oyez = {} if oyez is None else oyez
    materials = [] if materials is None else materials
    if not isinstance(oyez, dict) or any(oyez.get(field) is not None and not isinstance(oyez[field], str) for field in FIELDS):
        raise ValueError('Oyez description fields must be text or null')
    if not isinstance(materials, list) or any(not isinstance(item, dict) for item in materials):
        raise ValueError('Description materials must be a list of source records')
    actions = _actions(oyez, settings)
    base_sources = _oyez_sources(oyez)
    known = _source_index(base_sources, argued, supplied_ids=[s['id'] for s in base_sources])
    research, result, tasks = None, None, []
    if 'missing' in actions.values():
        task = build_description_task('case-research', case, oyez, materials, actions, settings, sources=known)
        research = run_codex(dashboard, cloud, secret_name, task.prompt, task.schema,
                             model=settings['case_research_model'], inputs=task.inputs,
                             timeout_seconds=settings['research_timeout_seconds'])
        validate_case_research(research, case, oyez)
        tasks.append(task.input_revision)
        for key, source in _source_index(research['sources'], argued, supplied_ids=known).items():
            if key in known and (source['kind'], source['url']) != (known[key]['kind'], known[key]['url']):
                raise ValueError('Research changed a supplied source identity')
            known.setdefault(key, source)
    if any(action != 'keep' for action in actions.values()):
        revision = None
        writer_materials = _writer_materials(materials, known)
        for attempt in range(settings['max_writer_attempts']):
            task = build_description_task('case-description', case, oyez, writer_materials, actions, settings,
                                          research=research, revision=revision, sources=known)
            result = run_codex(dashboard, cloud, secret_name, task.prompt, task.schema,
                               model=settings['case_description_model'], inputs=task.inputs,
                               timeout_seconds=settings['writer_timeout_seconds'])
            _check_schema(result, 'case-description')
            extra = _source_index(result['additional_sources'], argued, supplied_ids=known)
            combined = dict(known)
            for key, source in extra.items():
                if key in combined:
                    raise ValueError('Writer supplied a duplicate source ID')
                combined[key] = source
            tasks.append(task.input_revision)
            try:
                _validate_writer(result, combined, oyez, actions, settings)
                known = combined
                break
            except DescriptionTooLong as error:
                if attempt + 1 == settings['max_writer_attempts']: raise
                revision = {'previous_draft': result, 'word_counts': error.counts}
    fields, provenance = {}, {}
    for field in FIELDS:
        kept = actions[field] == 'keep'
        fields[field] = oyez[field] if kept else _paragraph_html(result[field]['text'])
        refs = ['oyez:' + field] if kept else result[field]['source_ids']
        provenance[field] = {'method': {'keep': 'oyez', 'missing': 'codex', 'shorten': 'condensed_oyez'}[actions[field]],
                             'sources': [known[key] for key in dict.fromkeys(refs)]}
    notes = result['private_editorial_notes'] if result else []
    caveats = (research['private_caveats'] if research else []) + (result['private_caveats'] if result else [])
    return {'schema_version': 1, 'fields': fields, 'provenance': provenance,
            'input_revision': digest_json({'case': case, 'oyez': oyez, 'materials': materials,
                                          'profile': settings, 'task_revisions': tasks}),
            'models_used': {'research': settings['case_research_model'] if research else None,
                            'writer': settings['case_description_model'] if result else None},
            'private_research': research, 'private_editorial_notes': notes, 'private_caveats': caveats}
