"""Independent readers -> one Opus editing session/contact sheet -> Sol review.

All mutations pass through one locked host. Readers share cached bytes, never
each other's scans. Opus can search cached sources or fill a specific evidence gap; Sol cannot call it back.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
from pathlib import Path
import re
import threading
import time
import jsonschema
from .annotation_cards import CardTools, CARD, SCHEMA, cue_for, normalized, preview_fingerprint, timing_failures
from .card_sheets import contact_sheet
from .card_library import CardLibrary
from .claude_runner import run_claude, claude_access
from .codex_auth import run_codex
from .research_errors import ResearchUnavailable

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = 'claude-opus-sol-v1'


def obj(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}


TEXT = {'type': 'string', 'maxLength': 2000}
STRINGS = {'type': 'array', 'items': TEXT, 'maxItems': 60}
CANDIDATE = obj({'id': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,80}$'},
    'start_block': {'type': 'integer', 'minimum': 0}, 'end_block': {'type': 'integer', 'minimum': 1},
    'anchor': TEXT, 'kind': TEXT, 'pitch': TEXT, 'caution': TEXT, 'uncertain': {'type': 'boolean'},
    'packet_ids': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 8}})
SCAN = obj({'top': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 30},
            'candidates': {'type': 'array', 'items': CANDIDATE, 'maxItems': 60},
            'read_aloud': STRINGS, 'notes': STRINGS})
DRAFT = copy.deepcopy(SCHEMA); DRAFT['properties']['cards']['maxItems'] = 40
DECISIONS = {'type': 'array', 'maxItems': 120, 'items': obj({'id': TEXT, 'status': {'enum': ['selected', 'omitted']}, 'reason': TEXT})}
EDITOR = obj({**DRAFT['properties'], 'decisions': DECISIONS})
ACK = obj({'saved': {'const': True}})
PROPOSALS = {'type': 'array', 'maxItems': 40, 'items': obj({'card': TEXT, 'action': {'enum': ['add', 'drop', 'move', 'substantive']}, 'reason': TEXT})}
REVIEW = obj({**DRAFT['properties'], 'editorial_proposals': PROPOSALS,
              'blocking_issues': {'type': 'array', 'maxItems': 40, 'items': obj({'card': TEXT, 'reason': TEXT})}})
PACKET = obj({'id': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,80}$'}, 'source_id': TEXT,
    'page': {'type': 'integer', 'minimum': 1}, 'end_page': {'type': 'integer', 'minimum': 1},
    'kind': {'enum': ['rule', 'statute', 'opinion', 'record', 'other']}, 'locator': TEXT,
    'quote': {'type': 'string', 'minLength': 1, 'maxLength': 8000},
    'context': {'type': 'string', 'minLength': 1, 'maxLength': 30000},
    'context_complete': {'const': True}, 'caution': TEXT})


def definition(name, description, schema):
    return {'name': name, 'description': description, 'inputSchema': schema}


def profile(settings):
    result = {'haiku_model': 'haiku', 'terra_model': 'gpt-6.1-terra', 'opus_model': 'opus',
              'review_model': 'gpt-6.1-sol', 'terra_enabled': True, 'reader_seconds': 1200,
              'editor_seconds': 1200, 'review_seconds': 1200, 'claude_max_turns': 128, 'editor_max_turns': 64}
    supplied = settings.get('annotation_cards_profile') or {}
    if set(supplied) - set(result): raise ValueError('Unknown card workflow profile field')
    result.update(supplied)
    for name in ('reader_seconds', 'editor_seconds', 'review_seconds'):
        if type(result[name]) is not int or not 60 <= result[name] <= 1200: raise ValueError('Card phase exceeds its time budget')
    if type(result['terra_enabled']) is not bool: raise ValueError('Invalid Terra reader setting')
    for name in ('claude_max_turns', 'editor_max_turns'):
        if type(result[name]) is not int or not 8 <= result[name] <= 200: raise ValueError('Invalid Claude turn limit')
    for name in ('haiku_model', 'terra_model', 'opus_model', 'review_model'):
        if not isinstance(result[name], str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,80}', result[name]): raise ValueError('Invalid card model ID')
    return result


class Pipeline:
    def __init__(self, job, transcript, enrichment, settings, cloud, lease, folder, *, claude=run_claude, codex=run_codex):
        self.job = job; self.transcript = transcript; self.settings = settings; self.cloud = cloud; self.lease = lease
        self.claude = claude; self.codex = codex; self.profile = profile(settings)
        self.deadline = getattr(lease, 'card_deadline', time.monotonic() + 2400)
        self.tools = CardTools(job, transcript, enrichment, settings, cloud, lease, folder)
        if self.tools.history is None: raise ValueError('Hybrid cards require the current case checkpoint')
        alignment = job.get('stages', {}).get('align', {})
        if alignment.get('status') != 'complete' or not alignment.get('result', {}).get('transcript_uri'):
            raise ResearchUnavailable('decision', 'Card research requires completed alignment before starting readers', 3600)
        self.tools.aligned = cloud.storage_json(alignment['result']['transcript_uri'], max_bytes=2097152)
        if [normalized(p['text']) for p in self.tools.aligned['paragraphs']] != [normalized(p['text']) for p in transcript['paragraphs']]:
            raise ResearchUnavailable('decision', 'The prepared transcript and aligned blocks differ; refresh the recording inputs', 3600)
        self.lock = threading.RLock(); plan = self.tools.history.plan
        state = plan.setdefault('hybrid', {})
        if state and state.get('generator') != GENERATOR:
            raise ResearchUnavailable('decision', 'The saved card workflow needs an explicit migration before resuming', 86400)
        if state: self.profile = profile({'annotation_cards_profile': state['profile']})
        if not state:
            state.update(generator=GENERATOR, profile=self.profile, readers={}, packets={}, calls={}, tool_calls={}, usage={})
            state['legacy_pending'] = [copy.deepcopy(d) for d in plan.get('decisions', []) if d.get('status') == 'pending' and d.get('draft')]
        self.state = state
        self.library = CardLibrary(self.tools.folder, job['docket'], cloud)
        self.library.sync(self.tools.sources)

    def save(self):
        self.tools.history.save(self.tools)
        self.library.sync(self.tools.sources)

    def checkpoint(self, key, value):
        with self.lock:
            self.state[key] = copy.deepcopy(value); self.save()

    def need_time(self, phase):
        seconds = self.profile[phase + '_seconds']
        if time.monotonic() + seconds + 30 > self.deadline:
            raise ResearchUnavailable('yield', 'Saved card research will continue in a fresh worker before starting ' + phase, 60, phase)

    def start(self, role):
        with self.lock:
            limit = 1 if role == 'editor' else 3
            if self.state['calls'].get(role, 0) >= limit:
                raise ResearchUnavailable('decision', 'The ' + role + ' phase reached its call budget; saved work needs an explicit retry decision', 86400, role)
            self.state['calls'][role] = self.state['calls'].get(role, 0) + 1; self.save()

    def usage(self, role, value):
        with self.lock:
            self.state['usage'][role] = value; self.save()

    def source_packet(self, role, args):
        jsonschema.validate(args, PACKET)
        source = self.tools.sources.get(args['source_id'])
        if not source or not args['page'] <= args['end_page'] <= args['page'] + 4:
            raise ValueError('Use a fetched source and at most five consecutive physical pages')
        pages = [p['text'] for p in source['pages'] if args['page'] <= p['page'] <= args['end_page']]
        if len(pages) != args['end_page'] - args['page'] + 1: raise ValueError('Source page is unavailable')
        if not normalized(args['context']) or not normalized(args['quote']) or normalized(args['context']) not in normalized(' '.join(pages)) or normalized(args['quote']) not in normalized(args['context']):
            raise ValueError('The exact quote and complete unit must match the fetched source pages')
        identifier = role + '/' + args['id']
        packet = {**args, 'id': identifier, 'reader': role, 'url': source['url'], 'sha256': source['sha256']}
        prospective = {**self.state['packets'], identifier: packet}
        if len(json.dumps(prospective).encode()) > 500000: raise ValueError('Evidence packet budget reached; retain full relevant units for the strongest candidates')
        self.state['packets'][identifier] = packet
        return {'packet_id': identifier, 'saved': True}

    def validate_scan(self, role, scan):
        jsonschema.validate(scan, SCAN); ids = set()
        for candidate in scan['candidates']:
            if candidate['id'] in ids: raise ValueError('Duplicate reader candidate')
            ids.add(candidate['id'])
            a, b = candidate['start_block'], candidate['end_block']
            if not 0 <= a < b <= len(self.transcript['paragraphs']): raise ValueError('Reader candidate needs a current transcript range')
            if not normalized(candidate['anchor']) or normalized(candidate['anchor']) not in normalized(' '.join(p['text'] for p in self.transcript['paragraphs'][a:b])):
                raise ValueError('Reader anchor must occur in its stated transcript blocks')
            for key in candidate['packet_ids']:
                if key not in self.state['packets'] or self.state['packets'][key]['reader'] != role:
                    raise ValueError('Use this reader’s verified evidence packets')
            if not candidate['packet_ids'] and not candidate['uncertain']: raise ValueError('An unsourced idea must be marked uncertain')
        if set(scan['top']) - ids: raise ValueError('Top candidate list contains unknown IDs')

    def indices(self):
        return {role: {'top': scan['top'], 'candidates': [{**c, 'anchor': c['anchor'][:200],
                 'pitch': c['pitch'][:320], 'caution': c['caution'][:320]} for c in scan['candidates']],
                 'read_aloud': [v[:320] for v in scan['read_aloud']], 'notes': [v[:320] for v in scan['notes']]}
                for role, scan in self.state['readers'].items()}

    def allowed_packets(self):
        return {key for scan in self.state['readers'].values() for c in scan['candidates'] for key in c['packet_ids']}

    def draft(self, result):
        jsonschema.validate({k: result[k] for k in ('cards', 'private_notes')}, DRAFT)
        ids = set(); spans = []
        for card in result['cards']:
            if card['id'] in ids: raise ValueError('Duplicate card ID')
            ids.add(card['id']); cue = cue_for(card, self.tools.aligned_transcript())
            self.tools.verify(card['evidence']); self.tools.verify_display(cue, card['evidence'])
            spans.append((cue['start'], cue['end'], card['id']))
        spans.sort()
        if any(a[1] > b[0] + .001 for a, b in zip(spans, spans[1:])): raise ValueError('Card timings overlap')

    def editorial_finish(self, result):
        jsonschema.validate(result, EDITOR); self.draft(result)
        if result['cards'] and not self.state.get('contact_sheet_issued'): raise ValueError('Inspect the production contact sheet before finalizing the editorial pass')
        candidates = {role + '/' + c['id'] for role, scan in self.state['readers'].items() for c in scan['candidates']}
        legacy = {'legacy/' + d['id'] for d in self.state.get('legacy_pending', [])}
        required = {role + '/' + key for role, scan in self.state['readers'].items() for key in scan['top']} | legacy
        decisions = result['decisions']; actual = [d['id'] for d in decisions]
        if not required <= set(actual) or set(actual) - candidates - legacy or len(actual) != len(set(actual)):
            raise ValueError('Record one decision for each top-list or legacy opportunity; additional known candidates are optional')
        if not result['cards'] and any(d['status'] == 'selected' for d in decisions):
            raise ValueError('An empty set cannot have selected decisions')
        # Ordinary non-top omissions cost no model output; fill them on the host.
        recorded = copy.deepcopy(decisions) + [{'id': key, 'status': 'omitted', 'reason': ''}
                    for key in sorted(candidates - set(actual))]
        self.tools.history.plan.update(phase='design',
            opportunities=[{**c, 'id': role + '/' + c['id']} for role, scan in self.state['readers'].items() for c in scan['candidates']],
            decisions=recorded)
        self.checkpoint('editor_final', result)
        return {'saved': True, 'next': 'Sol review; no further Opus call'}

    def review_finish(self, result):
        jsonschema.validate(result, REVIEW)
        if result['blocking_issues']:
            self.state.pop('review_final', None); self.checkpoint('review_blocked', result)
            return {'saved': True, 'held': True, 'next': 'Owner decision; no automatic Opus return'}
        self.draft(result)
        original = self.state['editor_final']['cards']; revised = result['cards']
        if [c['id'] for c in original] != [c['id'] for c in revised]: raise ValueError('Suggest additions/deletions privately; preserve Opus’s selected card set')
        failures = timing_failures(original, self.tools.aligned_transcript())
        for before, after in zip(original, revised):
            if before['recommended'] != after['recommended'] or json.loads(before['cue_json'])['kind'] != json.loads(after['cue_json'])['kind']:
                raise ValueError('Inclusion and card-type changes are editorial proposals, not automatic edits')
            if any(before[k] != after[k] for k in ('start_block', 'end_block')):
                if before['id'] not in failures:
                    raise ValueError('Timing changes require a current validator failure; suggest other moves privately')
                note = 'Mechanical timing repair (' + before['id'] + '): ' + '; '.join(failures[before['id']])
                if note not in result['private_notes']: result['private_notes'].append(note)
        self.tools.validate_result({k: result[k] for k in ('cards', 'private_notes')})
        self.state.pop('review_blocked', None); self.checkpoint('review_final', result)
        return {'saved': True}

    def inputs(self, role):
        paragraphs = self.tools.aligned_transcript()['paragraphs']
        argument = [{'id': i, 'speaker': p.get('speaker'), 'start': p.get('start'), 'text': p['text']} for i, p in enumerate(paragraphs)]
        result = {'input/case.json': json.dumps({k: self.job[k] for k in ('id', 'docket', 'case_name', 'argument_date', 'pdf_url')}),
                  'input/argument.json': json.dumps(argument, ensure_ascii=False),
                  'input/speakers.json': json.dumps(self.transcript.get('speakers', {})),
                  'input/library.json': json.dumps({'root': 'reference', 'guide': 'reference/README.md',
                      'templates': 'reference/archive/templates.json', 'archive': 'reference/archive/README.md',
                      'sources': 'reference/sources/index.json',
                      'instruction': 'Search and read relevant files using native filesystem tools. The archive is examples, not evidence. Read the whole supplied argument.'})}
        if role in ('haiku', 'terra'):
            result['input/progress.json'] = json.dumps(self.state.get('reader_progress', {}).get(role, {}))
            result['input/prior-research.json'] = json.dumps({k: self.tools.history.plan.get(k, []) for k in ('opportunities', 'decisions')})
        else:
            result['input/readers.json'] = json.dumps(self.indices(), ensure_ascii=False)
            result['input/evidence-index.json'] = json.dumps([{**{k: p[k] for k in ('id', 'kind', 'locator')},
                 'quote_preview': p['quote'][:240], 'caution': p['caution'][:320]} for key, p in self.state['packets'].items() if key in self.allowed_packets()])
            result['input/legacy-pending.json'] = json.dumps(self.state.get('legacy_pending', []))
        if role in ('editor', 'review'):
            result['input/sources.json'] = json.dumps(self.tools.source_index())
        if role == 'review':
            result['input/editor.json'] = json.dumps(self.state['editor_final'], ensure_ascii=False)
            result['input/timing-failures.json'] = json.dumps(timing_failures(self.state['editor_final']['cards'], self.tools.aligned_transcript()))
        return result

    def prompt(self, role):
        name = 'reader' if role in ('haiku', 'terra') else role
        return (ROOT / 'prompts/public-output-policy.md').read_text() + '\n' + (ROOT / ('prompts/annotation-' + name + '.md')).read_text()

    def reader_finish(self, role, result):
        self.validate_scan(role, result)
        self.state['readers'][role] = copy.deepcopy(result); self.save()
        return {'saved': True}

    def reader(self, role):
        with self.lock:
            if role in self.state['readers']: return
        endpoint = RoleTools(self, role)
        try:
            if role == 'haiku':
                self.claude(self.lease.dashboard, self.cloud, self.settings['claude_secret'], self.prompt(role), ACK,
                    self.profile['haiku_model'], inputs=self.inputs(role), tools=endpoint.definitions(), tool_handler=endpoint.invoke,
                    web=True, timeout_seconds=self.profile['reader_seconds'], max_turns=self.profile['claude_max_turns'],
                    on_start=lambda: self.start(role), on_usage=lambda usage: self.usage(role, usage), references=self.library.root)
            else:
                self.start(role)
                self.codex(self.lease.dashboard, self.cloud, self.settings['codex_secret'], self.prompt(role), ACK,
                    model=self.profile['terra_model'], inputs=self.inputs(role), tools=endpoint.definitions(), tool_handler=endpoint.invoke,
                    timeout_seconds=self.profile['reader_seconds'], references=self.library.root)
            if role not in self.state['readers']: raise ValueError('Save the completed scan with cards_reader_finish before confirming')
        except Exception:
            if role not in self.state['readers']: raise

    def run(self):
        roles = ['haiku', 'terra'] if self.profile['terra_enabled'] else ['haiku']
        if any(role not in self.state['readers'] for role in roles): self.need_time('reader')
        # Do not start a paid reader when the subsequent Claude phases cannot run.
        if self.claude is run_claude and ('editor_final' not in self.state or any(role not in self.state['readers'] for role in roles)):
            claude_access(self.cloud, self.settings['claude_secret'])
        if self.codex is run_codex and 'review_final' not in self.state:
            from .control import validate_secret
            try: validate_secret('codex', json.loads(self.cloud.secret(self.settings['codex_secret'])))
            except Exception: raise ResearchUnavailable('auth', 'Configure Codex subscription access before starting card research', 3600) from None
        with ThreadPoolExecutor(max_workers=len(roles)) as pool:
            futures = {pool.submit(self.reader, role): role for role in roles}
            failures = []
            for future in as_completed(futures):
                try: future.result()
                except Exception as error:
                    role = futures[future]; failure = phase_error(error, role)
                    if isinstance(failure, ResearchUnavailable) and self.state['calls'].get(role, 0) >= 3: failure.kind = 'decision'
                    failures.append(failure)
            if failures: raise failures[0]
        if 'editor_final' not in self.state:
            self.need_time('editor')
            self.lease.call('note', message='Reader research is saved. Opus is selecting cards and inspecting one production contact sheet.')
            endpoint = RoleTools(self, 'editor')
            try:
                result = self.claude(self.lease.dashboard, self.cloud, self.settings['claude_secret'], self.prompt('editor'), ACK,
                    self.profile['opus_model'], inputs=self.inputs('editor'), tools=endpoint.definitions(), tool_handler=endpoint.invoke,
                    web=True, timeout_seconds=self.profile['editor_seconds'], max_turns=self.profile['editor_max_turns'],
                    on_start=lambda: self.start('editor'), on_usage=lambda usage: self.usage('editor', usage), references=self.library.root)
                if 'editor_final' not in self.state: raise ValueError('Save the edited set with cards_editor_finish before confirming')
            except Exception as error:
                # A finish tool can commit before the CLI's final reply is lost.
                if 'editor_final' not in self.state:
                    failure = phase_error(error, 'editor')
                    if isinstance(failure, ResearchUnavailable) and self.state['calls'].get('editor', 0):
                        failure = ResearchUnavailable('decision', 'Opus did not finish its editing pass. Saved research and drafts are retained; another Opus pass requires an explicit owner decision.', 86400, 'editor')
                    raise failure
        if 'review_final' not in self.state:
            self.need_time('review')
            self.lease.call('note', message='Sol is reviewing sources, neutrality and production previews. Editorial suggestions remain private.')
            self.start('review'); endpoint = RoleTools(self, 'review')
            try:
                result = self.codex(self.lease.dashboard, self.cloud, self.settings['codex_secret'], self.prompt('review'), ACK,
                    model=self.profile['review_model'], inputs=self.inputs('review'), tools=endpoint.definitions(), tool_handler=endpoint.invoke,
                    timeout_seconds=self.profile['review_seconds'], references=self.library.root)
                if 'review_final' not in self.state and 'review_blocked' not in self.state: raise ValueError('Save the reviewed set with cards_review_finish before confirming')
            except Exception as error:
                if 'review_final' not in self.state and 'review_blocked' not in self.state: raise phase_error(error, 'review')
        if 'review_final' not in self.state:
            issues = self.state['review_blocked']['blocking_issues']
            raise ResearchUnavailable('decision', 'Card review needs a decision: ' + '; '.join(p['card'] + ': ' + p['reason'] for p in issues)[:500], 86400, 'review')
        final = copy.deepcopy(self.state['review_final'])
        final['private_notes'] += ['Editorial proposal (' + p['action'] + ', ' + p['card'] + '): ' + p['reason'] for p in final['editorial_proposals']]
        result = self.tools.finish({k: final[k] for k in ('cards', 'private_notes')})
        result['generator'] = GENERATOR
        result['workflow'] = {'models': {key: self.profile[key] for key in ('haiku_model', 'terra_model', 'opus_model', 'review_model')},
                              'calls': self.state['calls'], 'usage': self.state['usage'], 'editor_contact_sheet': bool(self.state.get('contact_sheet_issued')) and bool(final['cards']),
                              'editorial_proposals': final['editorial_proposals']}
        return result


class RoleTools:
    def __init__(self, pipeline, role):
        self.pipeline = pipeline; self.role = role
        phase = 'reader' if role in ('haiku', 'terra') else role
        self.deadline = time.monotonic() + pipeline.profile[phase + '_seconds']

    def check(self):
        if time.monotonic() > self.deadline: raise ValueError('This card phase reached its time budget; retain the saved work')
        self.pipeline.lease.check() if hasattr(self.pipeline.lease, 'check') else None

    def definitions(self):
        common = {tool['name']: tool for tool in self.pipeline.tools.definitions()}
        common['cards_source']['description'] = ('Download/cache a primary source and export its text, physical pages and original PDF to reference/sources/. '
            'With page=0 and query empty, returns file paths without loading the full source into context. '
            'Search/read files natively, or specify a page/query for a targeted text response. URL and source_id remain available for verified evidence.')
        source_tools = [common['cards_source'],
            definition('cards_sources', 'List cached sources and physical page counts without downloading or reading whole filings.', obj({})),
            definition('cards_search', 'Search cached source text, including sources and passages absent from reader packets. Returns bounded exact excerpts and page locators; read full units through cards_source when needed. Empty source_id searches all cached sources.', obj({'source_id': TEXT, 'query': TEXT})),
            definition('cards_ocr', 'OCR a selected scanned PDF page if no accessible text-layer copy exists; inspect the original image. At most eight distinct pages per case.', obj({'source_id': TEXT, 'page': {'type': 'integer', 'minimum': 1}}))]
        if self.role in ('haiku', 'terra'):
            return source_tools + [definition('cards_packet', 'Save a complete relevant subsection (rules/statutes) or key paragraph (opinions), not only the short quote. Copy contiguous source text and include exceptions. Use physical PDF pages.', PACKET),
                    definition('cards_checkpoint', 'Save this reader’s partial scan after each third; other readers cannot see it.', SCAN),
                    definition('cards_reader_finish', 'Save this reader’s COMPLETE final scan once, then reply only {"saved":true}.', SCAN)]
        evidence = definition('cards_evidence', 'Read verified reader packets, including complete subsections or paragraphs. Request only packets needed for editorial decisions.', obj({'packet_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 4}}))
        if self.role == 'editor':
            return source_tools + [evidence, common['cards_exhibit'], common['cards_render'],
                    definition('cards_validate', 'Validate draft sources, display text and timing before the contact sheet; visual_checked can remain false.', DRAFT),
                    definition('cards_contact_sheet', 'Render the complete proposed set and inspect the labeled full-frame contact sheets ONCE, before Sol review. Return editorial corrections in this same session.', DRAFT),
                    definition('cards_editor_finish', 'Durably save the final editorial set, with decisions for reader top lists and significant other omissions. Then reply only {"saved":true}; never repeat the cards.', EDITOR)]
        return source_tools + [evidence, common['cards_exhibit'], common['cards_render'], common['cards_validate'],
                definition('cards_review_finish', 'Save final visually checked cards, or blocking issues. Preserve editorial choices; timing may change only to fix a current validator failure. Then reply only {"saved":true}. No editor callback exists.', REVIEW)]

    def record_event(self, event): pass  # No raw transcripts in the current checkpoint/event log.

    def invoke(self, name, arguments):
        result = self._invoke(name, arguments)
        remaining = self.deadline - time.monotonic()
        if remaining <= 200 and not name.endswith('_finish'):
            notice = 'About ' + str(max(0, int(remaining))) + ' seconds remain before the hard cutoff. Please wrap up soon: save completed work, prioritize validation and the finish tool. Do not repeat the saved JSON in your final reply.'
            if isinstance(result, dict) and set(result) == {'contentItems'}:
                return {'contentItems': [*result['contentItems'], {'type': 'inputText', 'text': notice}]}
            return {**result, 'workflow_notice': notice}
        return result

    def _invoke(self, name, arguments):
        p = self.pipeline
        with p.lock:
            self.check()
            catalog = {t['name']: t for t in self.definitions()}
            if name not in catalog: raise ValueError('Tool is not available in this role')
            jsonschema.validate(arguments, catalog[name]['inputSchema'])
            used = p.state['tool_calls'].get(self.role, 0)
            if used >= (180 if self.role in ('haiku', 'terra') else 160) and not (name.endswith('_finish') or name == 'cards_checkpoint'):
                raise ValueError('This phase reached its tool-call budget; save completed work with the finish tool or report specific blocking issues')
            p.state['tool_calls'][self.role] = used + 1
            try:
                if name == 'cards_sources': return {'sources': p.tools.source_index()}
                if name == 'cards_search': return p.tools.search(arguments['source_id'], arguments['query'])
                if name == 'cards_reader_finish': return p.reader_finish(self.role, arguments)
                if name == 'cards_source':
                    result = p.tools.source(arguments['url'], arguments['query'], arguments['page'])
                    p.library.sync(p.tools.sources)
                    result.update(p.library.source_paths(result['source_id']))
                    if not arguments['query'] and not arguments['page']:
                        result['page_count'] = len(p.tools.sources[result['source_id']]['pages'])
                        result['pages'] = []
                        result['note'] = 'Source files are ready. Search/read the exported text and physical pages; source.json has the evidence identifiers.'
                    return result
                if name == 'cards_packet': return p.source_packet(self.role, arguments)
                if name == 'cards_ocr':
                    from .card_ocr import ocr_page
                    pages = p.state.setdefault('ocr_pages', []); key = arguments['source_id'] + ':' + str(arguments['page'])
                    if key not in pages:
                        if len(pages) >= 8: raise ValueError('The case OCR page budget is exhausted; preserve other candidates as uncertain')
                        pages.append(key); p.save()
                    return ocr_page(p.tools, arguments['source_id'], arguments['page'])
                if name == 'cards_checkpoint':
                    p.state.setdefault('reader_progress', {})[self.role] = copy.deepcopy(arguments); return {'saved': True}
                if name == 'cards_evidence':
                    if set(arguments['packet_ids']) - p.allowed_packets(): raise ValueError('Use the frozen reader evidence index')
                    return {'packets': [p.state['packets'][key] for key in arguments['packet_ids']]}
                if name == 'cards_contact_sheet':
                    if p.state.get('contact_sheet_issued'):
                        if arguments['cards'] == p.state['editor_draft']['cards']: return contact_sheet(p.tools, arguments['cards'], self.check)
                        raise ValueError('The one editorial contact-sheet inspection is already complete; return corrections for Sol to render')
                    p.draft(arguments); p.state['editor_draft'] = copy.deepcopy(arguments); p.save()
                    result = contact_sheet(p.tools, arguments['cards'], self.check); p.state['contact_sheet_issued'] = True; return result
                if name == 'cards_editor_finish': return p.editorial_finish(arguments)
                if name == 'cards_review_finish': return p.review_finish(arguments)
                if name == 'cards_validate' and self.role == 'editor':
                    p.draft(arguments); return {'valid': True, 'visual_review': 'Inspect the complete contact sheet before finishing'}
                if name == 'cards_render': return p.tools.render(arguments['card'])
                if name == 'cards_exhibit': return p.tools.exhibit(arguments['source_id'], arguments['page'], arguments['quote'], arguments.get('highlight'))
                if name == 'cards_validate': return p.tools.validate(arguments)
                raise ValueError('Unknown role tool')
            finally: p.save()


def generate_hybrid_cards(job, transcript, enrichment, settings, cloud, lease, folder):
    if not settings.get('claude_secret'): raise ResearchUnavailable('setup', 'Configure Claude subscription access before enabling hybrid card generation', 3600)
    pipeline = Pipeline(job, transcript, enrichment, settings, cloud, lease, folder)
    try: return pipeline.run()
    finally:
        with pipeline.lock: pipeline.save()


def phase_error(error, role):
    if isinstance(error, ResearchUnavailable):
        error.phase = role; return error
    if isinstance(error, (ValueError, jsonschema.ValidationError)):
        return ResearchUnavailable('decision', 'The ' + role + ' result did not pass card checks; saved work needs review', 86400, role)
    if isinstance(error, RuntimeError) and any(word in str(error).casefold() for word in ('credential', 'codex', 'research coordinator', 'gpt-', 'model', 'quota', 'rate limit', 'usage limit')):
        return ResearchUnavailable('provider', 'The ' + role + ' provider could not complete its turn; saved work is retained', 900, role)
    return error
