#!/usr/bin/env python3
"""Extract native Court transcript text in printed order using Poppler coordinates."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
from xml.etree import ElementTree as ET


METHOD = "poppler-coordinates"
NS = {"pdf": "http://www.w3.org/1999/xhtml"}
PROCEEDINGS = re.compile(r"^P\s*R\s*O\s*C\s*E\s*E\s*D\s*I\s*N\s*G\s*S$")
CONCLUSION = re.compile(r"\(Whereupon\b", re.IGNORECASE)


class ExtractionError(ValueError):
    """The PDF does not contain a supported native transcript layout."""


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Row:
    words: list
    number: int | None = None

    @property
    def text(self):
        return " ".join(word.text for word in self.words)

    @property
    def bbox(self):
        return [min(w.x0 for w in self.words), min(w.y0 for w in self.words),
                max(w.x1 for w in self.words), max(w.y1 for w in self.words)]


def _rows(words):
    """Ignore PDF content-stream/block order; combine words on the same baseline."""
    rows = []
    baseline = None
    for word in sorted(words, key=lambda w: (w.y0, w.x0)):
        if baseline is None or word.y0 - baseline > 1.0:
            rows.append(Row([]))
            baseline = word.y0
        rows[-1].words.append(word)
    for row in rows:
        row.words.sort(key=lambda w: w.x0)
    return rows


def _gutter(rows, width):
    """Find a left column of ascending printed line numbers, never spoken digits."""
    columns = {}
    for row in rows:
        for word in row.words:
            if word.x1 < width * 0.30 and re.fullmatch(r"[1-9]|1[0-9]|2[0-5]", word.text):
                key = round(word.x1)
                columns.setdefault(key, []).append(word)
    candidates = []
    for words in columns.values():
        words.sort(key=lambda w: w.y0)
        numbers = [int(w.text) for w in words]
        if len(numbers) >= 5 and len(set(numbers)) == len(numbers) and numbers == sorted(numbers):
            candidates.append(words)
    if not candidates:
        return None
    words = max(candidates, key=lambda ws: (len(ws), -ws[0].x1))
    return {"right": max(w.x1 for w in words), "top": min(w.y0 for w in words),
            "bottom": max(w.y1 for w in words), "numbers": len(words)}, words


def _clean_page(rows, width, height):
    detected = _gutter(rows, width)
    gutter, number_words = detected if detected else (None, [])
    number_ids = {id(word) for word in number_words}
    cleaned = []
    for row in rows:
        if gutter and not (gutter["top"] - 1 <= row.bbox[1] <= gutter["bottom"] + 1):
            continue
        # Preserve cover captions and APPEARANCES in full on unnumbered pages.
        if not gutter:
            if re.search(r"Official\s*[-–—]\s*Subject to Final Review", row.text):
                continue
            if row.bbox[1] > height * 0.90 and "Reporting" in row.text:
                continue
            if row.bbox[1] < height * 0.10 and row.bbox[0] > width * 0.65 and row.text.isdigit():
                continue
        numbers = [int(w.text) for w in row.words if id(w) in number_ids]
        words = [w for w in row.words if id(w) not in number_ids]
        if words:
            cleaned.append(Row(words, numbers[0] if numbers else None))
    return cleaned, gutter


def extract_bbox(xml):
    """Return text and audit metadata from pdftotext -bbox-layout XML.

    Blank lines encode the PDF's indented paragraphs. Form feeds preserve page
    boundaries without implying paragraph breaks. Punctuation is left unchanged.
    """
    try:
        nodes = ET.fromstring(xml).findall(".//pdf:page", NS)
    except ET.ParseError as exc:
        raise ExtractionError(f"Invalid Poppler bounding-box output: {exc}") from exc
    if not nodes:
        raise ExtractionError("No native PDF pages found; scanned PDFs need another extractor.")

    pages = []
    speech_rows = []
    started = ended = False
    for page_number, node in enumerate(nodes, 1):
        width, height = float(node.get("width")), float(node.get("height"))
        words = [Word(w.text or "", *(float(w.get(key)) for key in ("xMin", "yMin", "xMax", "yMax")))
                 for w in node.findall(".//pdf:word", NS) if w.text]
        rows, gutter = _clean_page(_rows(words), width, height)
        for row in rows:
            if PROCEEDINGS.fullmatch(row.text.strip()):
                started = True
            if started and not ended:
                if not gutter:
                    raise ExtractionError(f"Cannot identify the transcript line-number gutter on PDF page {page_number}.")
                speech_rows.append(row)
                if CONCLUSION.search(row.text):
                    ended = True
        if started and not ended and not rows:
            raise ExtractionError(f"No native transcript text on PDF page {page_number}.")
        pages.append({"number": page_number, "width": width, "height": height,
                      "gutter": gutter, "rows": rows})
    if not started or not ended:
        raise ExtractionError("Transcript must contain PROCEEDINGS and a (Whereupon ...) conclusion.")

    left_margin = min(row.bbox[0] for row in speech_rows)
    cell_width = statistics.median((w.x1 - w.x0) / len(w.text)
                                   for row in speech_rows for w in row.words if w.x1 > w.x0)
    if cell_width <= 0:
        raise ExtractionError("Cannot determine the transcript character width.")

    pieces, lines, page_info = [], [], []
    offset = 0
    in_body = finished = False
    for page in pages:
        if pieces:
            pieces.append("\f\n")
            offset += 2
        page_info.append({key: value for key, value in page.items() if key != "rows"})
        for row in page["rows"]:
            marker = bool(PROCEEDINGS.fullmatch(row.text.strip()))
            if marker:
                in_body = True
            paragraph_start = (in_body and not finished and not marker
                               and row.bbox[0] - left_margin >= 2 * cell_width)
            if paragraph_start:
                pieces.append("\n")
                offset += 1
            value = row.text
            lines.append({"page": page["number"], "line_number": row.number,
                          "bbox": row.bbox, "paragraph_start": paragraph_start,
                          "start": offset, "end": offset + len(value)})
            pieces.append(value + "\n")
            offset += len(value) + 1
            if in_body and CONCLUSION.search(value):
                finished = True
    text = "".join(pieces)
    metadata = {"schema_version": 1, "method": METHOD, "paragraph_mode": "layout",
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "body_left_margin": left_margin, "character_width": cell_width,
                "pages": page_info, "lines": lines}
    return text, metadata


def extract_pdf(pdf):
    pdf = Path(pdf)
    try:
        result = subprocess.run(["pdftotext", "-bbox-layout", "-enc", "UTF-8", str(pdf), "-"],
                                capture_output=True, check=True, timeout=180)
    except FileNotFoundError as exc:
        raise ExtractionError("pdftotext is required: brew install poppler (macOS), or install poppler-utils (Linux).") from exc
    except subprocess.CalledProcessError as exc:
        raise ExtractionError(f"Poppler failed: {exc.stderr.decode('utf-8', errors='replace').strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError("Poppler extraction exceeded 180 seconds.") from exc
    text, metadata = extract_bbox(result.stdout)
    metadata["source_pdf"] = pdf.name
    metadata["source_sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return text, metadata


def _atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="Output TXT path (defaults to PDF basename).")
    parser.add_argument("--force", action="store_true", help="Replace an existing output TXT.")
    args = parser.parse_args(argv)
    output = args.output or args.pdf.with_suffix(".txt")
    if output.resolve() == args.pdf.resolve():
        parser.error("Output must differ from the input PDF.")
    if output.exists() and not args.force:
        parser.error(f"Output exists: {output}; use --force to replace it.")
    try:
        text, metadata = extract_pdf(args.pdf)
        _atomic_write(output, text)
        _atomic_write(output.with_suffix(".extraction.json"), json.dumps(metadata, indent=2) + "\n")
    except (ExtractionError, OSError) as exc:
        parser.exit(1, f"Extraction failed: {exc}\n")
    print(f"Saved {output} ({len(metadata['pages'])} pages, {len(metadata['lines'])} text lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
