# Transcript-linked document excerpts

This prototype detects references to specific artifacts in a complete argument,
finds the source passages in the case's docket PDFs, and displays screenshots of
the actual pages alongside the timed transcript. The existing video/player files
are unchanged. Audio times come directly from the existing transcript JSON.

The example is **Trump v. Cook**, local case ID `25A312`, argued January 21, 2026.
Its saved detections and source matches were produced by a **GPT-6 Luna
subagent**, then checked against the downloaded PDFs. They can be replayed
without an API key. The separate API path uses the same two-stage task through
the [Responses API and Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
The default model is [`gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna).

## Dependencies

Use Python 3.10+, Poppler (`pdftotext`, `pdftoppm`), FFmpeg, and Node 22 with the
repository's existing Puppeteer dependency. The old Puppeteer installation in
this checkout does not load correctly with Node 26; the prototype was verified
using the Codex bundled Node runtime.

```sh
python3 -m pip install -r artifacts/requirements.txt
npm install
# macOS, if needed:
brew install poppler ffmpeg
```

## Replay the Luna example

From the repository root:

```sh
python3 artifacts/pipeline.py fetch --case 25A312
python3 artifacts/pipeline.py resolve --case 25A312 \
  --mentions artifacts/demo/25A312.mentions.json \
  --matches artifacts/demo/25A312.matches.json
python3 artifacts/prepare_preview.py --case 25A312
python3 -m http.server 8003 --bind 127.0.0.1 \
  --directory artifacts/output/25A312/preview
```

Open [the interactive preview](http://127.0.0.1:8003/artifact-player.html?case=25A312).
The audio controls support seeking; **References** lists the source passages,
jump-to-time buttons, and unresolved references. Clicking an excerpt opens the
full PDF-page screenshot; its source link opens the official filed PDF.
The preview bundle contains only the public case's media and display assets.

```sh
# A 41-second statutory-text sample.
node artifacts/render.js --case 25A312 --start 189 --end 230 \
  --output artifacts/output/25A312/statute-demo.mp4
# A 67-second sample of the former Federal Reserve governors' amicus brief.
node artifacts/render.js --case 25A312 --start 2599 --end 2666 \
  --output artifacts/output/25A312/amicus-demo.mp4
```

Exports are local MP4 files with the original argument audio. Nothing uploads to
YouTube. Frames change at every transcript block and excerpt boundary, so a
document can appear or disappear within a transcript block without shifting
audio. Argument seconds remain unchanged; this renderer adds no splash screens.

## Run the API detector on another processed case

Set a valid `OPENAI_API_KEY` in your shell, then:

```sh
python3 artifacts/pipeline.py fetch --case 63858
python3 artifacts/pipeline.py detect --case 63858 --model gpt-6-luna --max-mentions 40
python3 artifacts/pipeline.py resolve --case 63858 --model gpt-6-luna
python3 artifacts/prepare_preview.py --case 63858
```

`fetch` reuses downloads and extracts page text plus word coordinates locally.
It uses the same official docket URL/proceedings-table approach as
`scotusstats/data-pipeline/count_amicus_briefs.py`, without importing that script
and triggering its batch processing. To reuse that pipeline's cached HTML:

```sh
python3 artifacts/pipeline.py fetch --case CASE_ID \
  --docket-cache /path/to/scotusstats/data-pipeline/docket/TERM/DOCKET.html
```

The detector reads the entire transcript plus a short document catalog. The
resolver receives only the best eight locally retrieved pages for each mention,
in batches of six. PDFs are never uploaded to the API. Structured responses and
token usage are cached by a hash of the request; `store` is false. Default limits
keep the prototype small. Actual cost depends on token usage and current model
pricing; the Luna-subagent demo does not measure API cost.

## Case references

`cases.py` builds a card for the first mention of each Supreme Court case named in
the argument, after `pipeline.py fetch` has indexed the docket PDFs:

```sh
python3 artifacts/cases.py --case 25A312 --engine codex \
  --merge-into mockup-quotes/25A312.json
```

- Citations come from the filings (311 cited cases for Trump v. Cook), so names and
  years are exact even when the transcript garbles a name.
- One model call finds the first mention of each cited case. It must disambiguate
  shared names, e.g. In re Sawyer vs. Youngstown v. Sawyer, or the Supreme Court's
  and the Court of Claims' Reagan v. United States. Evidence must be verbatim and
  contain a close match of the case name; a misspoken name falls back to the first
  exact mention.
- The summary basis is Oyez's question and conclusion where available, otherwise the
  official syllabus from the Caselaw Access Project's static U.S. Reports data. A
  second model call condenses it into one past-tense sentence that names the holding
  most relevant to the mention.
- Votes are shown only when Oyez records a single decision.
- `--engine codex` uses the local Codex CLI login; `--engine openai` uses
  `OPENAI_API_KEY`. Responses are cached under `output/CASE/llm/`.
- Output: `output/CASE/cases.json` with each card's evidence, citation, source URL and
  the basis text for review. `reviewed` starts false. Lower-court cases and cases
  only named in passing are listed as unresolved. Later history (overruling) is not
  checked.

## Review and limitations

- `manifest.json` contains every screenshot's transcript evidence, original PDF
  URL, PDF and printed page numbers, exact quotation, source PDF hash, and time
  interval. `unresolved` explains references that cannot be located reliably.
- Quotations must occur on the chosen page after normalizing PDF line breaks,
  punctuation and hyphenation. This catches invented quotations. It cannot
  establish that a model chose the correct artifact: review source identity and
  the duration of each cue before publishing. `reviewed` starts false.
- A statute quoted in a brief is labeled with the containing filing as its
  source. A paraphrase of a removal letter is not the original letter. Ambiguous
  amicus references remain unresolved rather than being silently substituted.
- Only filings dated on or before the argument enter the source corpus. This
  prototype supports one oral argument/audio clock per case, and text-based
  PDFs. OCR, external statutes/opinions, and multiple arguments are future work.
- Overlapping excerpts are kept in the unresolved list so that only one source
  panel appears at a time. Edit the saved mentions/matches and replay `resolve`
  to adjust selections; times are always derived from transcript block IDs.

```sh
python3 -m unittest discover -s artifacts -p 'test_*.py'
node artifacts/render.js --case 25A312 --check
```

The evidence checks cover docket filtering, PDF hyphenation, fabricated
quotations, invalid source IDs, and deriving time intervals from transcript data.
The browser checks cover excerpt boundaries, backward seeking, the active
transcript, loaded images, and isolation of the public preview assets.
