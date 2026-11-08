import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from scotus_cloud.card_library import CardLibrary, mount_references


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name); self.cloud = Mock()

    def source(self, **extra):
        return {'url': 'https://court.example/opinion.pdf', 'sha256': hashlib.sha256(b'%PDF fixture').hexdigest(),
                'pages': [{'page': 1, 'printed_page': '17a', 'text': 'Complete original paragraph.'}], **extra}

    def test_archive_excludes_current_case_and_contains_no_private_trial_notes(self):
        library = CardLibrary(self.folder, '25-352', self.cloud); library.sync({})
        self.assertFalse((library.root / 'archive/25-352').exists())
        examples = list((library.root / 'archive').glob('*/*.json'))
        self.assertEqual(len(examples), 54)
        for file in examples:
            data = json.loads(file.read_text())
            self.assertNotIn('private_notes', data); self.assertNotIn('evidence', data); self.assertNotIn('reason', data)
            self.assertEqual(file.stat().st_mode & 0o222, 0)
        self.assertTrue((library.root / 'archive/templates.json').exists())
        self.assertEqual(json.loads((library.root / 'sources/index.json').read_text()), [])

    def test_downloaded_text_and_physical_pages_update_in_an_already_mounted_workspace(self):
        library = CardLibrary(self.folder, 'example', self.cloud); library.sync({})
        workspace = self.folder / 'worker'; workspace.mkdir(); mount_references(workspace, library.root)
        source = self.source(); library.sync({'opinion': source})
        page = workspace / 'reference/sources/opinion/pages/00001.txt'
        self.assertEqual(page.read_text(), source['pages'][0]['text'])
        source['pages'][0].update(text='A corrected OCR paragraph.', ocr=True)
        library.sync({'opinion': source})
        self.assertEqual(page.read_text(), 'A corrected OCR paragraph.')
        meta = json.loads((page.parent.parent / 'source.json').read_text())
        self.assertEqual(meta['pages'][0]['physical_page'], 1); self.assertEqual(meta['pages'][0]['printed_page'], '17a')
        self.assertTrue(meta['pages'][0]['ocr'])
        self.assertIn('=== PHYSICAL PAGE 1 ===', (page.parent.parent / 'text.txt').read_text())

    def test_original_pdf_survives_resume_and_is_checked_against_its_provenance(self):
        library = CardLibrary(self.folder, 'example', self.cloud)
        source = self.source(pdf_uri='gs://private-cached-source')
        self.cloud.storage_download.side_effect = lambda uri, path: Path(path).write_bytes(b'%PDF fixture')
        library.sync({'opinion': source})
        original = library.root / 'sources/opinion/original.pdf'
        self.assertEqual(original.read_bytes(), b'%PDF fixture'); library.sync({'opinion': source})
        self.cloud.storage_download.assert_called_once()
        self.assertEqual(library.source_paths('opinion')['pdf_file'], 'reference/sources/opinion/original.pdf')

    def test_changed_original_bytes_and_traversal_source_ids_are_rejected(self):
        library = CardLibrary(self.folder, 'example', self.cloud)
        self.cloud.storage_download.side_effect = lambda uri, path: Path(path).write_bytes(b'wrong PDF')
        with self.assertRaisesRegex(ValueError, 'provenance'): library.sync({'opinion': self.source(pdf_uri='gs://original')})
        self.assertFalse((library.root / 'sources/opinion/original.pdf').exists())
        with self.assertRaisesRegex(ValueError, 'source ID'): library.sync({'../private-checkpoint': self.source()})

    def test_replaced_pdf_with_identical_text_updates_bytes_and_page_metadata(self):
        library = CardLibrary(self.folder, 'example', self.cloud)
        pdf = self.folder / 'source.pdf'; pdf.write_bytes(b'%PDF fixture')
        source = self.source(pdf=pdf); library.sync({'opinion': source})
        pdf.write_bytes(b'%PDF replacement')
        source['sha256'] = hashlib.sha256(pdf.read_bytes()).hexdigest()
        source['pages'][0].update(printed_page='18a', ocr=True)
        library.sync({'opinion': source})
        directory = library.root / 'sources/opinion'
        self.assertEqual((directory / 'original.pdf').read_bytes(), b'%PDF replacement')
        metadata = json.loads((directory / 'source.json').read_text())
        self.assertEqual(metadata['sha256'], source['sha256'])
        self.assertEqual(metadata['pages'][0]['printed_page'], '18a')
        self.assertTrue(metadata['pages'][0]['ocr'])

    def test_regenerated_library_does_not_retain_an_excluded_case_from_previous_export(self):
        CardLibrary(self.folder, 'example', self.cloud)
        self.assertTrue((self.folder / 'reference/archive/25-352').exists())
        library = CardLibrary(self.folder, '25-352', self.cloud)
        self.assertFalse((library.root / 'archive/25-352').exists())


if __name__ == '__main__': unittest.main()
