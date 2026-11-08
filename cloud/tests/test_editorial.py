import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.codex_auth import run_codex
from scotus_cloud.editorial import (build_title_task, generate_title, public_title,
                                    validate_title_result)


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.case = {'docket': '25-332', 'case_name': 'Example v. State',
                     'recording_kind': 'argument', 'source_refs': ['input/question-presented.txt']}
        self.history = {'schema_version': 1, 'channel_id': 'channel', 'count': 40,
                        'titles': [{'video_id': str(i), 'title': f'Oral Argument on topic {i}: Case {i}'}
                                   for i in range(40)]}
        self.candidate = {'title': 'Oral Argument on police searches: Example v. State',
                          'topic': 'police searches', 'short_case_name': 'Example v. State',
                          'private_reason': 'A private editorial explanation.',
                          'evidence_refs': ['input/question-presented.txt']}
        self.result = {'recommended': self.candidate, 'alternatives': [], 'uncertain': False,
                       'private_caveats': ['Private uncertainty that must never become public text.']}

    def test_task_supplies_full_history_and_separate_source_text(self):
        task = build_title_task(self.case, self.history, question_presented='The actual legal question.',
                                transcript='JUSTICE: Complete transcript text.')
        self.assertEqual(json.loads(task.inputs['input/title-history.json']), self.history)
        self.assertEqual(task.inputs['input/transcript.txt'], 'JUSTICE: Complete transcript text.')
        self.assertIn('Do not introduce public-facing disclaimers', task.prompt)
        self.assertIn('Read the full list', task.prompt)
        self.assertIn('Oral Argument on birthright citizenship: Trump v. Barbara', task.prompt)
        changed = copy.deepcopy(self.history); changed['titles'][-1]['title'] = 'Owner changed a title'
        self.assertNotEqual(build_title_task(self.case, changed).input_revision,
                            build_title_task(self.case, self.history).input_revision)

    def test_truncated_or_duplicate_history_is_not_silently_accepted(self):
        truncated = copy.deepcopy(self.history); truncated['titles'].pop()
        repeated = copy.deepcopy(self.history); repeated['titles'][1] = repeated['titles'][0]
        for history in (truncated, repeated):
            with self.assertRaises(ValueError): build_title_task(self.case, history)

    @patch('scotus_cloud.editorial.run_codex')
    def test_title_adapter_passes_private_inputs_and_keeps_public_selection_explicit(self, runner):
        alternative = {**self.candidate, 'title': 'Oral Argument on home privacy: Example v. State',
                       'topic': 'home privacy', 'private_reason': 'Another private explanation.'}
        self.result.update(uncertain=True, alternatives=[alternative])
        runner.return_value = self.result
        bundle = generate_title(Mock(), Mock(), 'codex-secret', self.case, self.history,
                                question_presented='The question.')
        supplied = runner.call_args.kwargs['inputs']
        self.assertEqual(json.loads(supplied['input/title-history.json'])['count'], 40)
        self.assertEqual(public_title(bundle['result']), self.candidate['title'])
        self.assertEqual(public_title(bundle['result'], 'alternative-1'), alternative['title'])
        self.assertNotIn('private', public_title(bundle['result']).casefold())
        with self.assertRaises(ValueError): public_title(bundle['result'], 'alternative-2')

    def test_invalid_choices_are_rejected_without_echoing_model_text(self):
        invalid = []
        for title in ('x' * 101, 'A title\nwith another line', 'A <title>', '  A title'):
            result = copy.deepcopy(self.result); result['recommended']['title'] = title; invalid.append(result)
        result = copy.deepcopy(self.result); result['uncertain'] = True; invalid.append(result)
        result = copy.deepcopy(self.result); result['alternatives'] = [self.candidate]; invalid.append(result)
        result = copy.deepcopy(self.result); result['public_description'] = 'Invented disclaimer'; invalid.append(result)
        for result in invalid:
            with self.assertRaises(ValueError) as error: validate_title_result(result)
            self.assertNotIn('Invented disclaimer', str(error.exception))


class CodexInputTests(unittest.TestCase):
    def setUp(self):
        self.dashboard, self.cloud = Mock(), Mock()
        self.dashboard.call.return_value = 'lease-token'
        self.auth = {'auth_mode': 'chatgpt', 'tokens': {'refresh_token': 'original-private-token'}}
        self.cloud.secret.return_value = json.dumps(self.auth).encode()

    @patch.dict(os.environ, {'SCOTUS_PRIVATE_CODEX_WORKER':'1'})
    def test_reference_files_are_available_without_being_added_to_input_context(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Path(folder);(library/'archive').mkdir();(library/'sources').mkdir()
            (library/'sources/exact.txt').write_text('Exact cached source')
            def execute(command,*,cwd,**kwargs):
                self.assertEqual((Path(cwd)/'reference/sources/exact.txt').read_text(),'Exact cached source')
                self.assertEqual(list((Path(cwd)/'input').iterdir()),[Path(cwd)/'input/case.json'])
                self.assertEqual(command[-1],'Read supplied case and retrieve source files as needed')
                (Path(cwd)/'result.json').write_text('{"saved":true}')
            with patch('scotus_cloud.codex_auth.subprocess.run',side_effect=execute):
                self.assertEqual(run_codex(self.dashboard,self.cloud,'auth','Read supplied case and retrieve source files as needed',{},inputs={'input/case.json':'{}'},references=library),{'saved':True})

    @patch.dict(os.environ, {'SCOTUS_PRIVATE_CODEX_WORKER':'1'})
    def test_vision_cli_attaches_private_image_bytes(self):
        def execute(command,*,cwd,**kwargs):
            path=Path(command[command.index('--image')+1])
            self.assertEqual(path.read_bytes(),b'image fixture');self.assertEqual(path.parent.name,'input')
            self.assertEqual(command[-2: ],['--','Inspect the image'])
            (Path(cwd)/'result.json').write_text('{"usable":true}')
        with patch('scotus_cloud.codex_auth.subprocess.run',side_effect=execute):
            self.assertEqual(run_codex(self.dashboard,self.cloud,'auth','Inspect the image',{},inputs={'input/photo.jpg':b'image fixture'},images=['input/photo.jpg']),{'usable':True})

    @patch.dict(os.environ, {'SCOTUS_PRIVATE_CODEX_WORKER': '1'})
    def test_invalid_paths_and_oversized_inputs_fail_before_credentials_are_read(self):
        for inputs in ({'../auth/auth.json': 'bad'}, {'input/../auth/auth.json': 'bad'},
                       {'schema.json': '{}'}, {'result.json': '{}'},
                       {'input/file': 'one', 'input/file/child': 'two'},
                       {'input/huge.txt': b'x' * (2 * 1024 * 1024 + 1)}):
            with self.assertRaises(ValueError):
                run_codex(self.dashboard, self.cloud, 'codex-secret', 'prompt', {}, inputs=inputs)
        self.dashboard.call.assert_not_called()
        self.cloud.secret.assert_not_called()

    @patch.dict(os.environ, {'SCOTUS_PRIVATE_CODEX_WORKER': '1', 'OPENAI_API_KEY': 'unused', 'CODEX_API_KEY': 'unused'})
    def test_cli_receives_complete_private_files_and_no_api_key_fallback(self):
        observed = []

        def execute(command, *, cwd, env, **kwargs):
            root = Path(cwd)
            observed.append(root)
            self.assertEqual((root / 'input/title-history.json').read_text(), '{"titles": ["one", "two"]}')
            self.assertEqual((root / 'POLICY.md').read_text(), 'Trusted policy')
            self.assertEqual((root / 'input/title-history.json').stat().st_mode & 0o777, 0o600)
            self.assertNotIn('OPENAI_API_KEY', env); self.assertNotIn('CODEX_API_KEY', env)
            self.assertIn('--sandbox', command); self.assertIn('read-only', command)
            auth_path = Path(env['CODEX_HOME']) / 'auth.json'
            updated = copy.deepcopy(self.auth); updated['tokens']['refresh_token'] = 'refreshed-private-token'
            auth_path.write_text(json.dumps(updated))
            (root / 'result.json').write_text('{"result": "ok"}')

        with patch('scotus_cloud.codex_auth.subprocess.run', side_effect=execute):
            result = run_codex(self.dashboard, self.cloud, 'codex-secret', 'prompt', {},
                               inputs={'input/title-history.json': '{"titles": ["one", "two"]}',
                                       'POLICY.md': 'Trusted policy'})
        self.assertEqual(result, {'result': 'ok'})
        self.cloud.add_secret_version.assert_called_once()
        self.dashboard.call.assert_any_call('auth_release', name='codex', token='lease-token')
        self.assertFalse(observed[0].exists())

    @patch.dict(os.environ, {'SCOTUS_PRIVATE_CODEX_WORKER': '1'})
    def test_failed_cli_run_still_saves_refreshed_subscription_auth(self):
        def fail(command, *, cwd, env, **kwargs):
            updated = copy.deepcopy(self.auth); updated['tokens']['refresh_token'] = 'renewed-private-token'
            (Path(env['CODEX_HOME']) / 'auth.json').write_text(json.dumps(updated))
            raise subprocess.CalledProcessError(1, ['codex'])

        with patch('scotus_cloud.codex_auth.subprocess.run', side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                run_codex(self.dashboard, self.cloud, 'codex-secret', 'prompt', {})
        self.cloud.add_secret_version.assert_called_once()
        self.dashboard.call.assert_any_call('auth_release', name='codex', token='lease-token')


if __name__ == '__main__': unittest.main()
