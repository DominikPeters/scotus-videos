import copy
import io
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.alignment import find_windows, AlignmentReview
from scotus_cloud.control import make_app, validate_secret
from scotus_cloud.model import plan_video, recording_id
from scotus_cloud.remote import signature
from scotus_cloud.prepare import appearances, one_edit_apart


class PipelineTests(unittest.TestCase):
    def test_appearances_include_wrapped_roles_amici_and_accented_names(self):
        text = 'APPEARANCES:\nJ. BENJAMIN AGUIÑAGA, Solicitor General, Baton Rouge; on\nbehalf of Louisiana.\nHASHIM M. MOOPPAN, Principal Deputy Solicitor General; for the\nUnited States, as amicus curiae.\nC O N T E N T S\n'
        people=appearances(text)
        self.assertEqual([p['last_name'] for p in people], ['Aguiñaga','Mooppan'])
        self.assertIn('United States',people[1]['role'])
        self.assertTrue(one_edit_apart('moopan','mooppan'))
        self.assertFalse(one_edit_apart('davis','rice'))
    def manifest(self):
        return {'audio': {'duration_seconds': 7.031}, 'render': {'fps': 20},
                'speakers': {'speaker': {}}, 'paragraphs': [
                    {'speaker': 'speaker', 'start': .024},
                    {'speaker': 'speaker', 'start': 1.024},
                    {'speaker': 'speaker', 'start': 2.026}]}

    def test_parallel_frames_cover_audio_once(self):
        plan = plan_video(self.manifest(), chunk_seconds=2)
        self.assertEqual(plan['total_frames'], 141)
        self.assertEqual([(c['first_frame'], c['end_frame']) for c in plan['chunks']], [(0,40),(40,80),(80,120),(120,141)])
        self.assertEqual([e['frame'] for e in plan['events']], [0,20,41])

    def test_invalid_timeline_and_missing_speaker(self):
        manifest = self.manifest(); manifest['paragraphs'][2]['start'] = .5
        with self.assertRaises(ValueError): plan_video(manifest)
        manifest = self.manifest(); manifest['paragraphs'][2]['speaker'] = 'unknown'
        with self.assertRaises(ValueError): plan_video(manifest)

    def test_recording_identity_distinguishes_reargument(self):
        self.assertNotEqual(recording_id('23-1038', '2024-12-02'), recording_id('23-1038', '2024-12-02', 'argument-2'))
        with self.assertRaises(ValueError): recording_id('../../credentials', '2024-12-02')

    def test_coarse_windows_preserve_core_and_context(self):
        sequence = ['alpha','bravo','charlie','delta','echo','foxtrot'] * 80
        text = ' '.join(sequence)
        recognized = [{'text': word.upper(), 'start': i+.2} for i,word in enumerate(sequence)]
        windows, words, audit = find_windows(text, recognized, 480)
        self.assertEqual(len(words), 480)
        self.assertEqual(windows[0]['core_start'], 0)
        self.assertEqual(windows[-1]['core_end'], 480)
        for a,b in zip(windows,windows[1:]): self.assertEqual(a['core_end'],b['core_start'])
        for w in windows:
            self.assertLessEqual(w['context_start'], w['core_start'])
            self.assertGreaterEqual(w['context_end'], w['core_end'])
        with self.assertRaises(AlignmentReview): find_windows(text, recognized[100:200], 480)

    def test_secret_validation_rejects_api_billing_and_external_token_endpoint(self):
        with self.assertRaises(ValueError): validate_secret('codex', {'OPENAI_API_KEY':'test'})
        with self.assertRaises(ValueError): validate_secret('youtube', {'client_id':'a','client_secret':'b','refresh_token':'c','token_uri':'https://example.com/steal'})

    def test_control_rejects_unsigned_request_before_external_calls(self):
        config={'dashboard_url':'https://scotusstats.com/youtube/','control_key':'test','dispatcher_key':'test','project':'test'}
        app=make_app(config)
        environ={'REQUEST_METHOD':'POST','PATH_INFO':'/v1/request','CONTENT_LENGTH':'2','wsgi.input':io.BytesIO(b'{}')}
        status=[]
        with patch('scotus_cloud.control.Dashboard.call') as call:
            value=b''.join(app(environ,lambda code,headers:status.append(code)))
            call.assert_not_called()
        self.assertEqual(status,['401 Unauthorized'])
        self.assertNotIn(b'test',value)


if __name__ == '__main__': unittest.main()
