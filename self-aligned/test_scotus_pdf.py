"""Regression checks for native text fidelity, paragraphs and the headless workflow."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from scotus_pdf import ExtractionError, extract_bbox, extract_pdf


HERE = Path(__file__).resolve().parent
FULL_CASE_PDF = next((HERE / "25-332").glob("*.pdf"), None)
spec = importlib.util.spec_from_file_location("scotus_parser", HERE / "scotus-parser.py")
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


def fixture_xml(pages, numbered=True):
    """A realistic numbered, monospaced transcript with scrambled PDF word order."""
    root = ET.Element("html", xmlns="http://www.w3.org/1999/xhtml")
    body = ET.SubElement(root, "body")
    for content in pages:
        page = ET.SubElement(body, "page", width="612", height="792")
        words = []
        rows = [(480, 60, "17"), (190, 16, "Official - Subject to Final Review"),
                (150, 764, "Heritage Reporting Corporation")]
        if numbered:
            rows += [(112 if n > 9 else 119, 102 + (n - 1) * 24, str(n)) for n in range(1, 26)]
        rows += [(x, 102 + (n - 1) * 24, text) for n, x, text in content]
        for x, y, text in rows:
            for value in text.split():
                word = ET.Element("word", xMin=str(x), yMin=str(y),
                                  xMax=str(x + 7 * len(value)), yMax=str(y + 9))
                word.text = value
                words.append(word)
                x += 7 * (len(value) + 1)
        # Source-stream order must not determine reading or speaker order.
        for word in reversed(words):
            page.append(word)
    return ET.tostring(root)


class NativeTranscriptTests(unittest.TestCase):
    def test_paragraphs_numbers_punctuation_and_page_continuation(self):
        xml = fixture_xml([
            [(1, 273, "P R O C E E D I N G S"),
             (2, 398, "(10:04 a.m.)"),
             (3, 217, "CHIEF JUSTICE ROBERTS: We will hear"),
             (4, 154, "argument in Case 18-123."),
             (5, 210, "ORAL ARGUMENT OF JOHN O’CONNOR"),
             (6, 210, "ON BEHALF OF THE PETITIONER"),
             (7, 217, "GENERAL O’CONNOR: First sentence."),
             (8, 154, "Second sentence in the same printed paragraph."),
             (9, 217, "new paragraph starts in lowercase."),
             (10, 217, "This paragraph continues"),
             (11, 154, "across a page")],
            [(1, 154, "boundary with the spoken number"),
             (2, 154, "42"),
             (3, 154, "and 18 U.S.C. § 924(c), said “yes” -- twice."),
             (4, 217, "JUSTICE KAVANAUGH: What do you --"),
             (5, 217, "GENERAL O’CONNOR: I’m answering."),
             (6, 217, "(Whereupon, the case was submitted.)"),
             (7, 154, "INDEX MUST NOT BECOME SPOKEN TEXT")],
        ])
        text, metadata = extract_bbox(xml)
        turns = parser.parse_scotus_transcript(text, paragraph_mode="layout")
        self.assertEqual(turns[1]["speaker"], "GENERAL O’CONNOR")
        self.assertEqual(turns[1]["paragraphs"], [
            "First sentence. Second sentence in the same printed paragraph.",
            "new paragraph starts in lowercase.",
            "This paragraph continues across a page boundary with the spoken number 42 and 18 U.S.C. § 924(c), said “yes” -- twice.",
        ])
        self.assertEqual(turns[2]["speaker"]["last_name"], "Kavanaugh")
        self.assertEqual(turns[2]["paragraphs"], ["What do you --"])
        self.assertEqual(turns[3]["paragraphs"], ["I’m answering."])
        self.assertEqual(turns[0]["section"], "ORAL ARGUMENT OF JOHN O’CONNOR ON BEHALF OF THE PETITIONER")
        self.assertNotIn("Subject to Final Review", text)
        self.assertNotIn("Heritage Reporting Corporation", text)
        for line in metadata["lines"]:
            value = text[line["start"]:line["end"]]
            self.assertTrue(value)
            self.assertNotIn("\n", value)

    def test_cover_names_are_not_cropped(self):
        root = ET.fromstring(fixture_xml([[
            (1, 273, "P R O C E E D I N G S"),
            (2, 217, "CHIEF JUSTICE ROBERTS: Thank you."),
            (3, 217, "(Whereupon, the case was submitted.)"),
        ]]))
        ns = {"p": "http://www.w3.org/1999/xhtml"}
        body = root.find("p:body", ns)
        cover = ET.Element("{http://www.w3.org/1999/xhtml}page", width="612", height="792")
        for i, value in enumerate(["DONALD", "J.", "TRUMP"]):
            word = ET.SubElement(cover, "{http://www.w3.org/1999/xhtml}word",
                                 xMin=str(108 + i * 60), xMax=str(150 + i * 60), yMin="234", yMax="243")
            word.text = value
        body.insert(0, cover)
        text, metadata = extract_bbox(ET.tostring(root))
        self.assertTrue(text.startswith("DONALD J. TRUMP\n"))
        self.assertIsNone(metadata["pages"][0]["gutter"])

    def test_unsupported_layout_and_missing_conclusion_fail(self):
        body = [[(1, 273, "P R O C E E D I N G S"),
                 (2, 217, "CHIEF JUSTICE ROBERTS: Thank you."),
                 (3, 217, "(Whereupon, the case was submitted.)")]]
        with self.assertRaisesRegex(ExtractionError, "gutter"):
            extract_bbox(fixture_xml(body, numbered=False))
        with self.assertRaisesRegex(ExtractionError, "conclusion"):
            extract_bbox(fixture_xml([body[0][:-1]]))
        with self.assertRaisesRegex(ExtractionError, "No native PDF pages"):
            extract_bbox(b"<html/>")

    def test_scaled_pages_do_not_depend_on_fixed_crop_coordinates(self):
        xml = fixture_xml([[
            (1, 273, "P R O C E E D I N G S"),
            (2, 217, "CHIEF JUSTICE ROBERTS: A sentence."),
            (3, 154, "Another sentence in the same paragraph."),
            (4, 217, "A new indented paragraph."),
            (5, 217, "(Whereupon, the case was submitted.)"),
        ]])
        original, _ = extract_bbox(xml)
        root = ET.fromstring(xml)
        for node in root.iter():
            for key in ["width", "height", "xMin", "yMin", "xMax", "yMax"]:
                if key in node.attrib:
                    node.set(key, str(2 * float(node.get(key))))
        scaled, _ = extract_bbox(ET.tostring(root))
        self.assertEqual(original, scaled)

    def test_existing_adobe_text_keeps_legacy_paragraphs(self):
        text = """P R O C E ED I N G S
CHIEF JUSTICE ROBERTS: First sentence.
Second sentence.
ORAL ARGUMENT OF JANE DOE
ON BEHALF OF THE PETITIONER
MS. DOE: Thank you.
(Whereupon, the case was submitted.)
"""
        turns = parser.parse_scotus_transcript(text)
        self.assertEqual(turns[0]["paragraphs"], ["First sentence.", "Second sentence."])
        self.assertEqual(turns[1]["paragraphs"], ["Thank you."])

    def test_edited_text_requires_explicit_paragraph_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            txt = Path(directory) / "case.txt"
            txt.write_text("original", encoding="utf-8")
            self.assertEqual(parser.paragraph_mode_for_file(txt), "legacy")
            metadata = {"method": "poppler-coordinates", "text_sha256": hashlib.sha256(txt.read_bytes()).hexdigest()}
            txt.with_suffix(".extraction.json").write_text(json.dumps(metadata))
            self.assertEqual(parser.paragraph_mode_for_file(txt), "layout")
            txt.write_text("edited", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "TXT differs"):
                parser.paragraph_mode_for_file(txt)
            self.assertEqual(parser.paragraph_mode_for_file(txt, "layout"), "layout")

    def test_failed_extraction_does_not_replace_existing_text(self):
        from scotus_pdf import main
        with tempfile.TemporaryDirectory() as directory:
            txt = Path(directory) / "case.txt"
            txt.write_text("previous export", encoding="utf-8")
            with patch("scotus_pdf.extract_pdf", side_effect=ExtractionError("unsupported PDF")):
                with self.assertRaises(SystemExit) as result:
                    main(["input.pdf", "-o", str(txt), "--force"])
            self.assertEqual(result.exception.code, 1)
            self.assertEqual(txt.read_text(), "previous export")

    def test_missing_poppler_has_installation_guidance(self):
        with patch("scotus_pdf.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ExtractionError, "poppler-utils"):
                extract_pdf("example.pdf")

    @unittest.skipUnless(shutil.which("pdftotext") and FULL_CASE_PDF,
                         "Full transcript fixture is only available in the local case archive")
    def test_real_pdf_cli_and_parser(self):
        self._real_cli(FULL_CASE_PDF)

    def _real_cli(self, pdf):
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / "25-332"
            txt = case_dir / "25-332.txt"
            result = subprocess.run([sys.executable, str(HERE / "scotus_pdf.py"), str(pdf), "-o", str(txt)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, str(HERE / "scotus-parser.py"), str(case_dir)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            turns = json.loads((case_dir / "25-332.json").read_text())
            self.assertEqual(len(turns), 571)
            self.assertIn("General Sauer.", turns[0]["paragraphs"])
            self.assertNotIn("Whereupon", (case_dir / "25-332.flat.txt").read_text())
            self.assertTrue(txt.with_suffix(".extraction.json").exists())


if __name__ == "__main__":
    unittest.main()
