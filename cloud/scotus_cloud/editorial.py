"""Prepare a private title task; public output is only the chosen title string.

This is a callable adapter, not a deployed enrichment stage. It uses the existing
subscription-only CLI runner and does not change the rendering/upload templates.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .codex_auth import run_codex
from .model import digest_json


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class TitleTask:
    prompt: str
    schema: dict
    inputs: dict
    input_revision: str
    history_revision: str


def build_title_task(case, history, *, question_presented=None, transcript=None):
    """Snapshot the full history and source inputs, including trusted policies."""
    if not isinstance(case, dict) or any(
            not isinstance(case.get(key), str) or not case[key].strip()
            for key in ('docket', 'case_name', 'recording_kind')):
        raise ValueError('Title task needs docket, case_name and recording_kind')
    if not isinstance(history, dict) or history.get('schema_version') != 1:
        raise ValueError('Unsupported title history')
    titles = history.get('titles')
    if (not isinstance(titles, list) or not titles or
            type(history.get('count')) is not int or history['count'] != len(titles) or
            not isinstance(history.get('channel_id'), str) or not history['channel_id'].strip()):
        raise ValueError('Supply the complete title history with count and channel ID')
    ids = set()
    for item in titles:
        if not isinstance(item, dict) or any(
                not isinstance(item.get(key), str) or not item[key].strip()
                for key in ('video_id', 'title')):
            raise ValueError('Invalid history entry')
        if item['video_id'] in ids:
            raise ValueError('Duplicate video in title history')
        ids.add(item['video_id'])

    policy = (ROOT / 'prompts/public-output-policy.md').read_text()
    task_prompt = (ROOT / 'prompts/title.md').read_text()
    schema = json.loads((ROOT / 'schemas/title-result.schema.json').read_text())
    inputs = {
        'POLICY.md': policy,
        'input/case.json': json.dumps(case, ensure_ascii=False, indent=2),
        'input/title-history.json': json.dumps(history, ensure_ascii=False, indent=2),
    }
    for name, value in (('question-presented', question_presented), ('transcript', transcript)):
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Optional title context must be nonempty text')
            inputs['input/' + name + '.txt'] = value
    prompt = policy + '\n\n' + task_prompt
    revision = digest_json({'prompt': prompt, 'schema': schema, 'inputs': {
        name: hashlib.sha256(value.encode('utf-8')).hexdigest()
        for name, value in inputs.items()}})
    return TitleTask(prompt, schema, inputs, revision, digest_json(history))


def validate_title_result(result):
    """Reject malformed/ambiguous choices before a dashboard or uploader sees them."""
    schema = json.loads((ROOT / 'schemas/title-result.schema.json').read_text())
    errors = list(Draft202012Validator(schema).iter_errors(result))
    if errors:
        # Do not echo arbitrary model text in exceptions or public worker logs.
        raise ValueError('Title result does not conform to its schema')
    if result['uncertain'] and not result['alternatives']:
        raise ValueError('An uncertain title needs one or two alternatives')
    seen = set()
    for candidate in [result['recommended'], *result['alternatives']]:
        title = candidate['title']
        if (title != title.strip() or any(ord(char) < 32 or ord(char) == 127 for char in title)
                or '<' in title or '>' in title):
            raise ValueError('Invalid YouTube title text')
        key = ' '.join(title.casefold().split())
        if key in seen:
            raise ValueError('Title alternatives must be distinct')
        seen.add(key)
        if any(not candidate[field].strip() for field in ('topic', 'short_case_name', 'private_reason')):
            raise ValueError('Title candidate needs its topic, caption and private reason')
        if any(not ref.strip() for ref in candidate['evidence_refs']):
            raise ValueError('Title candidate needs source references')
    return result


def public_title(result, choice='recommended'):
    """Select a public field explicitly; never append private notes or caveats."""
    validate_title_result(result)
    candidates = {'recommended': result['recommended']}
    candidates.update({f'alternative-{i + 1}': candidate
                       for i, candidate in enumerate(result['alternatives'])})
    if choice not in candidates:
        raise ValueError('Unknown title choice')
    return candidates[choice]['title']


def generate_title(dashboard, cloud, secret_name, case, history, *,
                   question_presented=None, transcript=None, model=None):
    task = build_title_task(case, history, question_presented=question_presented,
                            transcript=transcript)
    result = run_codex(dashboard, cloud, secret_name, task.prompt, task.schema,
                       model=model, inputs=task.inputs)
    return {'schema_version': 1, 'input_revision': task.input_revision,
            'history_revision': task.history_revision, 'result': validate_title_result(result)}
