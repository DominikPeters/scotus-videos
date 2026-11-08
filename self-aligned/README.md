# Self-aligned transcripts

Run `python3 scotus-tool.py` in this directory for the existing interactive
workflow. **Convert PDF to text** now uses Poppler's native PDF coordinates;
Adobe Reader is an explicitly selected fallback. Install Poppler first:

```sh
# macOS
brew install poppler
# Debian/Ubuntu, including a Linux worker image
apt-get install poppler-utils
```

The PDF extraction step is also available without the interactive tool or any
extra Python packages:

```sh
python3 self-aligned/scotus_pdf.py /path/to/transcript.pdf \
  --output /path/to/25-332/25-332.txt
python3 self-aligned/scotus-parser.py /path/to/25-332
```

The standalone extractor refuses to replace an existing TXT unless `--force` is
supplied. Selecting conversion in the interactive tool replaces that case's TXT,
as before. Existing saved extracts are not migrated automatically.

After re-converting an existing case, run **Parse transcript**, **Run gentle
aligner**, and **Line up** in that order so word offsets and timestamps match the
new text and paragraph boundaries.

The extractor finds the printed line-number column and its vertical extent,
removes that gutter and page furniture, and reconstructs words in visual row
order. It preserves cover captions and appearances without a fixed horizontal
crop. Native punctuation is retained, including double dashes, apostrophes and
spoken numbers. It does not use OCR or rewrite the transcript.

Blank lines indicate indented paragraphs in the printed proceedings. Page breaks
do not end paragraphs. The `.extraction.json` sidecar records input/output hashes,
page dimensions, detected gutters and line coordinates/offsets. The parser uses
these explicit paragraph breaks automatically when the sidecar matches the TXT.
This avoids splitting a paragraph just because an uppercase sentence starts on
a new printed line.

TXT files without coordinate metadata retain the existing sentence-based parser
heuristics. If a coordinate TXT is edited by hand, choose
`--paragraph-mode layout` to keep its blank-line boundaries, or
`--paragraph-mode legacy` to use the older heuristics; automatic mode refuses stale
metadata. Re-extraction also refreshes the metadata. The layout parser stops at the
submission notice so the word index cannot enter the alignment text.

Unsupported/scanned PDFs, missing proceedings/conclusion markers, and undetected
body gutters fail with a diagnostic before the existing output is replaced.
For an exception on macOS, select **Convert PDF to text with Adobe (fallback)**.
That action removes coordinate metadata so the resulting Adobe text uses the
legacy parser. The remaining Gentle and speaker-resolution steps are unchanged.

Run regression checks from the repository root:

```sh
python3 -m unittest discover -s self-aligned -p 'test_*.py'
```

Synthetic fixtures exercise reading order, punctuation, spoken numbers, paragraph
indents, page continuations and metadata checks. The full PDF integration check
also runs when its local transcript fixture and Poppler are available.

Validation on the local archive extracted and parsed all 13 PDFs. The twelve
comparable saved Adobe exports still differ by only 36 normalized word-token
edits across 260,142 tokens: eleven joined-word instances and the previously
identified reordered interruption exchange. The punctuation audit found 1,924
gap differences, all involving hyphens/dashes, with no character changes in
matched words after Unicode/apostrophe normalization. Representative paragraphs
and unusual dash placements were checked against rendered PDF pages.

Paragraph counts intentionally differ from the legacy heuristic: for example,
Slaughter has 793 printed-layout paragraphs rather than 874 heuristic blocks.
The uppercase `Respondent now proposes...` line after a period remains in the
same paragraph, as printed; new indents begin new paragraphs, and ordinary page
continuations do not. The original saved TXT files and their legacy parsing
outputs were preserved. Per-case results and hashes are in
[the validation record](../docs/research/transcript-extraction-validation.json).
