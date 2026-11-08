import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scotus_cloud.photo_discovery import ARCHIVE_URL, archive_listing, saved_portrait
from scotus_cloud.enrichment import enrich
from scotus_cloud.photos import revise_photo


def file(name):
    return {'type': 'file', 'name': name,
            'download_url': 'https://raw.githubusercontent.com/DominikPeters/scotus-videos/master/advocates/' + name}


class ArchivePortraitTests(unittest.TestCase):
    def test_finds_ferguson_without_a_catalog_entry_or_commit_pin(self):
        fetch = Mock(return_value=json.dumps([file('emily_m_ferguson.jpg')]).encode())
        saved = saved_portrait('Emily M. Ferguson', archive_listing(fetch), fetch)
        self.assertIn('/master/advocates/emily_m_ferguson.jpg', saved['uri'])
        fetch.assert_called_once_with(ARCHIVE_URL, 2097152)

    def test_case_scoped_image_keeps_its_kind_and_sources_without_hash_gate(self):
        stem = 'advocate_25_5343_kevin_joel_page'
        entries = {x['name']: x for x in [file(stem+'.jpg'), file(stem+'.source.json')]}
        fetch = Mock(return_value=json.dumps({'name': 'Kevin Joel Page', 'kind': 'logo',
            'source_url': 'https://txn.fd.org/logo.png', 'sha256': 'outdated metadata'}).encode())
        saved = saved_portrait('Kevin Joel Page', entries, fetch)
        self.assertEqual(saved['kind'], 'logo')
        self.assertEqual(saved['source_url'], 'https://txn.fd.org/logo.png')

    def test_missing_initial_is_an_alias_but_not_a_namesake_guess(self):
        entries = {'jules_lobel.jpg': file('jules_lobel.jpg')}
        self.assertIsNotNone(saved_portrait('Jules L. Lobel', entries, Mock()))
        entries = {n: file(n) for n in ('john_a_smith.jpg', 'john_b_smith.jpg')}
        self.assertIsNone(saved_portrait('John Smith', entries, Mock()))
        self.assertIn('john_a_smith.jpg', saved_portrait('John A. Smith', entries, Mock())['uri'])

    def test_unavailable_archive_is_not_reported_as_a_missing_photo(self):
        with self.assertRaisesRegex(ValueError, 'retry before searching'):
            archive_listing(Mock(return_value=b'{"message":"API rate limit exceeded"}'))

    def test_enrichment_reuses_archive_before_calling_photo_model(self):
        job = {'id': 'case', 'docket': '25-1003', 'argument_date': '2026-11-04',
               'case_name': 'Example', 'pdf_url': 'https://court.example/transcript.pdf',
               'editorial_cache_uri': 'gs://owned/editorial', 'stages': {'enrich': {}}}
        editorial = {'case_metadata': {}, 'description': {'fields': {}, 'private_caveats': [],
            'private_editorial_notes': [], 'provenance': {}}, 'titles': [{'title': 'Example'}]}
        cloud = Mock()
        cloud.storage_json.side_effect = [editorial, {'titles': []}]
        lease = Mock()
        lease.dashboard.call.return_value = {'titles': [], 'photos': {}}
        lease.call.return_value = {'needs_review': True}
        transcript = {'text': 'Example', 'speakers': {'emily': {'kind': 'advocate',
            'name': 'Emily M. Ferguson', 'identity_evidence': 'Official transcript'}}}
        def fetch(url, *args):
            if url == ARCHIVE_URL:
                return json.dumps([file('emily_m_ferguson.jpg')]).encode()
            return b'{}'
        checked = {'participation': {'docket': job['docket'], 'argument_date': job['argument_date'],
                                    'private_notes': [], 'justices': []}}
        with tempfile.TemporaryDirectory() as folder, \
             patch('scotus_cloud.enrichment.fetch', side_effect=fetch), \
             patch('scotus_cloud.enrichment.store_photo', return_value={'id': 'saved'}), \
             patch('scotus_cloud.enrichment.generate_case_description', return_value=checked), \
             patch('scotus_cloud.enrichment.run_codex') as model:
            enrich(job, transcript, {'bucket': 'owned', 'title_history_uri': 'gs://owned/titles',
                   'codex_secret': 'unused'}, cloud, lease, Path(folder))
        model.assert_not_called()
        review = next(c.kwargs['review'] for c in lease.call.call_args_list if c.args == ('enrichment_review',))
        self.assertEqual(review['photos']['emily']['approved_existing'], {'id': 'saved'})

    def test_retry_after_failed_research_uses_the_archive_without_model_or_crop(self):
        out = io.BytesIO()
        Image.new('RGB', (100, 100), 'white').save(out, 'JPEG')
        image = out.getvalue()
        job = {'id': 'case', 'review': {'photos': {'emily': {'name': 'Emily M. Ferguson', 'candidates': []}}}}
        def fetch(url, *args):
            return json.dumps([file('emily_m_ferguson.jpg')]).encode() if url == ARCHIVE_URL else image
        with tempfile.TemporaryDirectory() as folder, \
             patch('scotus_cloud.enrichment.fetch', side_effect=fetch), \
             patch('scotus_cloud.photos.run_codex') as model:
            choices = revise_photo({'person': 'emily', 'action': 'different'}, job,
                {'bucket': 'owned'}, Mock(), Mock(), Path(folder))
        model.assert_not_called()
        self.assertEqual(choices[0]['origin'], 'curated_cache')


if __name__ == '__main__':
    unittest.main()
