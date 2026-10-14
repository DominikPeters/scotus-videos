import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.case_descriptions import (DescriptionTooLong, description_profile,
    generate_case_description, public_case_fields, plain_text, validate_case_research)


class CaseDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.case = {'docket': '25-332', 'case_name': 'Example v. Agency',
                     'argument_date': '2026-10-12'}
        self.source = {'id': 'qp', 'title': 'Granted question', 'kind': 'court_question',
                       'url': 'https://www.supremecourt.gov/test-question.pdf',
                       'document_date': '2026-06-01', 'locator': 'Page 1',
                       'relevant_passage': 'Whether landowners may seek damages for the agency use of their property.'}
        self.research = {'sources': [self.source],
                         'background': [{'statement': 'Landowners seek damages for agency use of their land.',
                                         'status': 'party_position', 'source_ids': ['qp']}],
                         'issues': [{'neutral_issue': 'Can landowners seek damages?',
                                     'petitioner_position': 'Damages are available.',
                                     'respondent_position': 'They are not available here.',
                                     'essential_limitations': ['The available remedy is at issue.'],
                                     'private_framing_notes': 'Do not call the agency rogue or assume unlawful conduct.',
                                     'source_ids': ['qp']}],
                         'private_caveats': ['Private research uncertainty.']}
        self.result = {'facts_of_the_case': {'text': 'Landowners sued a federal agency over its use of their land. They seek damages.',
                                           'source_ids': ['qp']},
                       'question': {'text': "Can landowners seek damages for the agency's use of their property?",
                                    'source_ids': ['qp']},
                       'additional_sources': [],
                       'private_editorial_notes': ['Replaced rhetorical labels with a neutral issue.'],
                       'private_caveats': ['Private writer uncertainty.']}
        self.oyez = {'href': 'https://api.oyez.org/cases/2026/25-332',
                     'facts_of_the_case': '<p>Short existing facts with a <i>legal term</i>.</p>',
                     'question': '<p>Can the landowners seek damages?</p>'}
        self.materials = [{'id': 'qp', 'title': self.source['title'], 'url': self.source['url'],
                           'text': self.source['relevant_passage']}]

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_short_oyez_entries_keep_exact_html_without_model_calls(self, runner):
        bundle = generate_case_description(Mock(), Mock(), 'secret', self.case, oyez=self.oyez)
        runner.assert_not_called()
        self.assertEqual(public_case_fields(bundle), {key: self.oyez[key] for key in ('facts_of_the_case', 'question')})
        self.assertEqual(bundle['models_used'], {'research': None, 'writer': None})
        self.assertEqual(bundle['provenance']['question']['method'], 'oyez')

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_missing_descriptions_use_luna_then_sol_with_evidence_and_private_notes(self, runner):
        runner.side_effect = [self.research, self.result]
        bundle = generate_case_description(Mock(), Mock(), 'secret', self.case, materials=self.materials)
        self.assertEqual([call.kwargs['model'] for call in runner.call_args_list], ['gpt-6-luna', 'gpt-6.1-sol'])
        writer_inputs = runner.call_args_list[1].kwargs['inputs']
        self.assertEqual(json.loads(writer_inputs['input/research.json']), self.research)
        self.assertEqual(json.loads(runner.call_args_list[0].kwargs['inputs']['input/materials.json']), self.materials)
        writer_materials = json.loads(writer_inputs['input/materials.json'])
        self.assertEqual(writer_materials[0]['text'], self.source['relevant_passage'])
        self.assertEqual(writer_materials[0]['excerpt_check'], 'supplied_source_text')
        self.assertEqual(json.loads(writer_inputs['input/source-index.json']), [self.source])
        public = public_case_fields(bundle)
        self.assertEqual(set(public), {'facts_of_the_case', 'question'})
        self.assertNotIn('Private', ' '.join(public.values()))
        self.assertEqual(len(bundle['private_caveats']), 2)
        self.assertEqual(bundle['provenance']['question']['sources'][0]['id'], 'qp')
        self.assertTrue(all(item['kind'] != 'oyez' for entry in bundle['provenance'].values() for item in entry['sources']))

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_partial_oyez_data_preserves_available_field(self, runner):
        oyez = {**self.oyez, 'question': None}
        output = copy.deepcopy(self.result)
        output['facts_of_the_case'] = {'text': None, 'source_ids': []}
        runner.side_effect = [self.research, output]
        bundle = generate_case_description(Mock(), Mock(), 'secret', self.case, oyez=oyez)
        self.assertEqual(bundle['fields']['facts_of_the_case'], self.oyez['facts_of_the_case'])
        self.assertEqual(bundle['provenance']['facts_of_the_case']['method'], 'oyez')
        self.assertEqual(bundle['provenance']['question']['method'], 'codex')

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_long_oyez_is_condensed_by_sol_and_keeps_oyez_provenance(self, runner):
        oyez = {**self.oyez, 'facts_of_the_case': '<p>' + 'background ' * 220 + '</p>'}
        output = copy.deepcopy(self.result)
        output['facts_of_the_case']['source_ids'] = ['oyez:facts_of_the_case']
        output['question']['source_ids'] = ['oyez:question']
        runner.return_value = output
        bundle = generate_case_description(Mock(), Mock(), 'secret', self.case, oyez=oyez)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.kwargs['model'], 'gpt-6.1-sol')
        self.assertEqual(bundle['provenance']['facts_of_the_case']['method'], 'condensed_oyez')
        self.assertEqual(bundle['provenance']['facts_of_the_case']['sources'][0]['kind'], 'oyez')
        self.assertEqual(json.loads(runner.call_args.kwargs['inputs']['input/oyez.json']), oyez)

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_one_brevity_rewrite_receives_the_full_draft_without_truncation(self, runner):
        long = copy.deepcopy(self.result)
        long['facts_of_the_case']['text'] = 'background ' * 120 + 'lastword'
        runner.side_effect = [self.research, long, self.result]
        bundle = generate_case_description(Mock(), Mock(), 'secret', self.case)
        self.assertEqual(runner.call_count, 3)
        correction = json.loads(runner.call_args.kwargs['inputs']['input/revision.json'])
        self.assertEqual(correction['previous_draft'], long)
        self.assertEqual(correction['word_counts']['facts_of_the_case'], 121)
        self.assertIn('Landowners sued', bundle['fields']['facts_of_the_case'])

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_repeated_overlength_is_bounded_and_never_silently_truncated(self, runner):
        long = copy.deepcopy(self.result); long['facts_of_the_case']['text'] = 'word ' * 120 + 'lastword'
        runner.side_effect = [self.research, long, long]
        with self.assertRaises(DescriptionTooLong): generate_case_description(Mock(), Mock(), 'secret', self.case)
        self.assertEqual(runner.call_count, 3)

    def test_research_rejects_unknown_sources_future_documents_and_disguised_oyez_credit(self):
        unknown = copy.deepcopy(self.research); unknown['issues'][0]['source_ids'] = ['unread-source']
        future = copy.deepcopy(self.research); future['sources'][0]['document_date'] = '2026-10-13'
        wrong_credit = copy.deepcopy(self.research); wrong_credit['sources'][0]['url'] = self.oyez['href']
        for research in (unknown, future, wrong_credit):
            with self.assertRaises(ValueError): validate_case_research(research, self.case, {})

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_writer_cannot_overwrite_kept_fields_or_invent_evidence(self, runner):
        oyez = {**self.oyez, 'question': None}
        runner.side_effect = [self.research, self.result]
        with self.assertRaises(ValueError): generate_case_description(Mock(), Mock(), 'secret', self.case, oyez=oyez)
        output = copy.deepcopy(self.result); output['question']['source_ids'] = ['invented']
        runner.side_effect = [self.research, output]
        with self.assertRaises(ValueError): generate_case_description(Mock(), Mock(), 'secret', self.case)

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_generated_text_is_escaped_for_existing_html_fields(self, runner):
        output = copy.deepcopy(self.result)
        output['facts_of_the_case']['text'] = '<img src=x onerror=alert(1)> A & B disputed a fee.'
        runner.side_effect = [self.research, output]
        bundle = generate_case_description(Mock(), Mock(), 'secret', self.case)
        self.assertNotIn('<img', bundle['fields']['facts_of_the_case'])
        self.assertIn('&lt;img', bundle['fields']['facts_of_the_case'])
        self.assertEqual(plain_text('<p>A &amp; B</p><p>disputed a fee.</p>'), 'A & B disputed a fee.')

    def test_invalid_budget_or_rewrite_profile_cannot_start_work(self):
        for profile in ({'max_writer_attempts': 100}, {'writer_timeout_seconds': 901},
                        {'word_limits': {'facts_of_the_case': 0, 'question': 60, 'combined': 160}}):
            with self.assertRaises(ValueError): description_profile(profile)

    @patch('scotus_cloud.case_descriptions.run_codex')
    def test_bulk_materials_are_read_by_luna_and_only_matching_passage_goes_to_sol(self, runner):
        materials = copy.deepcopy(self.materials)
        materials[0]['text'] = 'Unrelated procedural material. ' * 300 + self.source['relevant_passage']
        runner.side_effect = [self.research, self.result]
        generate_case_description(Mock(), Mock(), 'secret', self.case, materials=materials)
        research_input = json.loads(runner.call_args_list[0].kwargs['inputs']['input/materials.json'])
        writer_input = json.loads(runner.call_args_list[1].kwargs['inputs']['input/materials.json'])
        self.assertEqual(research_input, materials)
        self.assertEqual(writer_input[0]['text'], self.source['relevant_passage'])
        self.assertEqual(writer_input[0]['excerpt_check'], 'matched_supplied_text')
        self.assertLess(len(json.dumps(writer_input)), len(json.dumps(research_input)))


if __name__ == '__main__': unittest.main()
