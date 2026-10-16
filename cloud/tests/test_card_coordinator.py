import json
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from scotus_cloud.annotation_cards import CardTools,preview_fingerprint
from scotus_cloud.codex_tools import run_with_tools
from scotus_cloud.model import digest_json


class PreviewValidationTests(unittest.TestCase):
    def test_exact_preview_required_and_validation_has_no_uploads(self):
        with tempfile.TemporaryDirectory() as folder:
            cloud = Mock()
            tools = CardTools({'id': 'job'}, {}, {}, {}, cloud, Mock(), folder)
            tools.sources['s'] = {'url': 'https://example.org', 'sha256': 'sha',
                                  'pages': [{'page': 1, 'text': 'Source text'}]}
            card = {'id': 'one', 'start_block': 0, 'end_block': 1,
                    'cue_json': '{"kind":"Excerpt","quote":"Source text"}',
                    'evidence': [{'source_id': 's', 'page': 1, 'quote': 'Source text', 'claim': 'text'}],
                    'recommended': True, 'reason': 'Context', 'preview_id': '', 'visual_checked': False}
            result = {'cards': [card], 'private_notes': []}
            with self.assertRaisesRegex(ValueError, 'Card one'):
                tools.validate_result(result)
            key = preview_fingerprint(card)
            tools.previews[key] = {'start': 0, 'end': 10, 'cue': {'kind': 'Excerpt'}}
            card.update(preview_id=key, visual_checked=True)
            self.assertEqual(len(tools.validate_result(result)), 1)
            for field, value in [('reason', 'New context'), ('end_block', 2), ('recommended', False)]:
                changed = {**card, field: value}
                with self.assertRaises(ValueError):
                    tools.validate_result({'cards': [changed], 'private_notes': []})
            cloud.storage_upload.assert_not_called()


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def run_session(self, failures):
        owner = Mock()
        owner.validate_result.side_effect = [ValueError('Card one needs preview')] * failures + [None]
        class Handler:
            def invoke(self, name, args):
                return {}
            def validate_result(self, result):
                return owner.validate_result(result)
        handler = Handler().invoke
        process = Mock(returncode=0)
        rpc = Mock()
        rpc.request = AsyncMock(return_value={'thread': {'id': 'root'}})
        rpc.send = AsyncMock()
        messages = []
        for _ in range(failures + 1):
            messages.extend([
                {'method': 'item/completed', 'params': {'threadId': 'root', 'item': {'type': 'agentMessage', 'text': '{"cards":[]}'}}},
                {'method': 'turn/completed', 'params': {'threadId': 'root', 'turn': {'status': 'completed'}}},
            ])
        rpc.receive = AsyncMock(side_effect=messages)
        with patch('asyncio.create_subprocess_exec', AsyncMock(return_value=process)), patch('scotus_cloud.recovery_worker.RPC', return_value=rpc):
            result = await run_with_tools('/tmp', {}, 'prompt', {'type': 'object'}, None, [], handler, 10)
        return result, rpc

    async def test_correction_uses_same_thread(self):
        result, rpc = await self.run_session(1)
        self.assertEqual(result, {'cards': []})
        turns = [c.args[1] for c in rpc.request.call_args_list if c.args[0] == 'turn/start']
        self.assertEqual(len(turns), 2)
        self.assertTrue(all(t['threadId'] == 'root' for t in turns))
        self.assertIn('Card one needs preview', turns[1]['input'][0]['text'])

    async def test_repeated_invalid_proposals_are_bounded(self):
        with self.assertRaisesRegex(ValueError, 'needs preview'):
            await self.run_session(3)
