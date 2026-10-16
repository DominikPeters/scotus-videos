> Historical handover: the approved renderer was integrated into the cloud pipeline
> on October 14. Its current sources are in `cloud/presentation/renderer`; the
> source manifest is `cloud/presentation/sources.json`. Integration details below
> describe the prototype at handover time.

# Handover: annotation cards for the argument videos

This note is for the agent maintaining the Google Cloud pipeline. It describes a feature that is designed, mocked up and approved in look, but **not yet integrated** into `cloud/`. Nothing under `cloud/` was changed.

The feature: at the right moments in an argument, show a small card in the left column that gives viewers the source being discussed:
- statute text, or a quoted brief passage;
- a case (holding in one sentence);
- a glossary term, a timeline of the facts, or two statutes side by side;
- a record exhibit, a circuit-split map, or the question presented.

The phrases the card refers to are marked in the transcript while the card is up.

Everything lives in uncommitted files:
- `mockup-quotes/`: the renderer mockup;
- `artifacts/cases.py`: the case-card tool;
- changes to `artifacts/pipeline.py` and `artifacts/README.md`;
- this note.

## 1. Decisions already made with Dominik

Treat these as requirements.

**Choosing cards**
- **The agent decides, not fixed automation.** Dominik does not want a fixed glossary list, timeline extractor or similar. The agent in charge of a case decides what deserves a card and writes the cues, using the tools below for the parts that can be checked: fetching sources, verifying quotes, looking up citations, rendering crops, checking timing. Do not build "detect every X" passes.
- **Show statutes as statutes.** A statute card shows the statute's own text, from the U.S. Code on govinfo, not a brief's quotation of it.
- **When cards appear:**
  - Case cards: at the case's first mention, and only if it's discussed rather than just named in a list.
  - Glossary cards: at the term's first use.
  - Circuit map: only when the split is actually being discussed, never by default.
  - QP card: when the speakers talk about what exactly was granted.

**Case cards**
- The case name is the prominent line. The reporter citation (e.g. "470 U.S. 532") is **not** printed.
- Under the name: year and vote, the vote only when Oyez records a single decision.
- Then one sentence, "The Court held that …", in the past tense.
- No "Case" label above the card.
- Holdings must be condensed from a real source: Oyez's conclusion, or the official syllabus. Never write one from memory.

**Layout and motion**
- **Keep the existing visual style.** The redesigned renderer in `artifacts/render.js`, `artifacts/player.js` and `artifacts/player.css` was rejected; do not use it. The cards are styled like transcript turns: a small label above, a flat rounded box in the transcript's light beige, the source line below, all in Myriad.
- **Compact header during the argument:**
  - the "Argued on …" line is hidden (it remains on the splash screen and thumbnail);
  - the bench of justices is left-aligned and raised;
  - the seal is a little smaller.
- **Tile grid:** each section's tile size is chosen so the rows are balanced (no nearly empty last row). Details in §3.
- **Squeeze:** while a card is up, the advocate photo and the justice tiles shrink. The tiles keep their columns and become shorter and roughly square, so nothing ever moves to another row. The squeeze is only as deep as the card needs, which is often none. A rewrapping animation with snake- or arc-shaped paths was tried and rejected; it has been removed.
- **Card to card:** the new card slides up over the old one ("stack"). The old card stays put, recedes slightly and fades. A slide-out/slide-in variant was rejected and removed.
- **Transcript marks:** a dotted gold underline on a slightly brighter patch of the bubble. The marks fade in and out with the card, and cross-fade on a swap. They cover the card's own time window plus 60 seconds before it, unless a cue sets `highlight_from`.
- **Circuit map:**
  - drawn from the U.S. Courts boundary map, which is public domain;
  - rotated 6° counterclockwise and limited to the contiguous states, to keep it short;
  - the source line says "map: U.S. Courts", without "(public domain)".

## 2. Files

| Path | What it is |
|---|---|
| `mockup-quotes/index.html`, `mockup-quotes/script.js` | Copies of the production renderer with the new layout and the card system. They were copied from the root `index.html`/`script.js`, which have the same hashes as `cloud/presentation/renderer/index.html`/`script.js`. The original code is unchanged except for small hooks; all new code is in a block at the end of `script.js` and a CSS block marked "Quote mockup additions". |
| `mockup-quotes/25A312.json` | Cues for Trump v. Cook: quotes, statute, timeline, side by side, glossary, and 15 case cards from `cases.py`. |
| `mockup-quotes/63695.json` | Cues for Stanley v. City of Sanford: QP, record exhibit, circuit map. |
| `mockup-quotes/maps/circuits.svg` | The state outlines from the U.S. Courts map (public domain, via Wikimedia Commons), each tagged with `data-circuit`. Text, district lines and the legend were removed. |
| `mockup-quotes/render-clip.js` | Renders an MP4 of a time range, with the same frame plan as `screenshot.js`, plus the audio. |
| `mockup-quotes/screenshot.js` | A copy of `screenshot.js` that passes the quote progress to the page (§4). Untested: the local Puppeteer install fails under Node 26. |
| `mockup-quotes/clips/`, `mockup-quotes/stills/card-types.png` | Current reference renders, one clip per card type. The Stanley clips are silent because its MP3 isn't local. |
| `artifacts/cases.py` | Case-reference tool (§5). |
| `artifacts/pipeline.py` | Existing prototype pipeline, with the changes listed in §5. |
| `.claude/launch.json` | Local static server on port 8002, used for previews. |

## 3. The renderer mockup

### Running it

- Serve the repository root on port 8002, for example with `python3 -m http.server 8002`.
- Interactive preview, with audio and buttons to jump to each cue: open `http://localhost:8002/mockup-quotes/?case=25A312&preview=1&t=188`.
- A still frame at a given time: add `&still=1`.
- A still mid-transition: also add `&q=0.5`.
- A clip:

```sh
/opt/homebrew/opt/node@18/bin/node mockup-quotes/render-clip.js 25A312 1420 1458 out.mp4
```

The repository's `puppeteer@22` loads with Node 18 but not with Node 26.

### Layout

- **Compact header:** `setUpSection` adds the `compact` class to `div.frame`, and sets `--main-height` to 1080 minus the header height. The transcript and the left column use that height. The bench portraits get a fixed 3:2 box so the header height doesn't depend on image loading.
- **Balanced tile grid:** `sizeInteractionTiles(container, count)` picks the fewest rows such that tiles stay at least 75px wide (maximum 100px), and spreads the tiles evenly over those rows. It sets `--tile` (the scale) and `--cols` (the column count) on the container. Examples: 15 tiles become 8+7 (previously 7+7+1); 25 become 9+9+7. **This changes videos without cards too.**
- **Squeeze variables:** `--q` (0 to 1) is the eased transition progress. `--squeeze` (0 to 1) is how deep this card needs the squeeze. `--sq = q × squeeze` drives the sizes: the advocate photo goes from 245 to 160px; tile width ×(1 − 0.2·sq), tile height ×(1 − 0.43·sq); the turn-number badges scale with their tile.

### Cue format

Each case has a file with a list of cues: `{ "cues": [ … ] }`. Common fields:

```json
{
  "id": "g-inm",
  "start": 1439.9,
  "end": 1452.0,
  "kind": "Glossary",
  "heading": "",
  "label": "",
  "source": "…",
  "date": "",
  "highlight": ["INM"],
  "highlight_from": 1400
}
```

- `start` and `end` are argument-audio seconds. `start` must be the start of a transcript text block.
- A card appears at the first text block whose start is ≥ `start` (within 0.05 s), and leaves at the first block starting ≥ `end`.
- The label line above the card shows "`kind` · `heading`". `label` overrides `kind`; case cards set `label: ""`, which hides the label line when there is no heading either.
- `date`, if set, adds "· filed DATE" to the source line.
- `highlight` lists the phrases to mark in the transcript (case-insensitive). `highlight_from` is optional; by default, marks start 60 s before `start`.

The body depends on which of these fields the cue has; the renderer checks them in this order:

| Field | Card |
|---|---|
| `case: {name, details}` with `text` | Case: the name (HTML, party names in italics), a small line like "1985 · decided 8–1", then the holding |
| `glossary: {term, expansion}` with `text` | Glossary term with its expansion, then an explanation |
| `compare: [{title, cite, text}, {…}]` | Two columns side by side; use `<mark>` for the key words |
| `timeline: {current, events: [{date, label, gap?}]}` | Horizontal timeline with the current event highlighted. `gap: true` draws a dashed line before that event. Keep it to about 8 events or fewer. |
| `image` (a path) | Record exhibit: a PDF crop rendered by `render_excerpt` |
| `map: {groups: [{label, color, circuits: ["2", "3"]}], below: "11"}` | Circuit map with a legend; `below` outlines the circuit whose decision is under review |
| `text` alone | Primary text, e.g. a statute, with `<mark>` on the relevant clause |
| `before`, `quote`, `after` | Excerpt from a filing: grey surrounding sentences around the highlighted quote. `after` starting with `<sup>` is shown as a footnote. When space is short, the text shrinks first, then the surrounding sentences are dropped. |

Sizing: the card's height is the space left once the sidebar is fully squeezed (at most 480px). The text shrinks until it fits. A short card shrinks to its content. Then `--squeeze` is found by binary search, as the smallest squeeze that still fits the card.

### Animation and the frame protocol

- A transition is 30 frames of 0.04 s (1.2 s) with a sine ease. If a text block is too short to hold it, the transition waits for the next block.
- `nextTextBlock()` still returns `{duration, frameInfo, …}`. `frameInfo` entries are now `[scrollAmount, duration, quoteProgress]`. `quoteProgress` is either a number from 0 to 1 (a card appearing or leaving) or `{swap: t}` (one card replacing another). The renderer must call `scrollTranscript(amount)` and then, if `quoteProgress` is not null, `setQuoteProgress(quoteProgress)` before capturing each frame.
- Scroll steps are put on the same frame grid as the quote frames, and the durations still add up exactly to the text block's length.
- Global state lives in `activeQuoteCue` and `quoteSwap`. The marked phrases are `<span class="card-reference new|old">` elements in the transcript, faded through `--reference-new` and `--reference-old` on `#transcript`.
- All font variants (regular, semibold, bold, italic) are loaded before the page signals `#loading-finished`. Otherwise a variant first used mid-video renders as blank text for its first frames. This is a real bug class for any style used for the first time mid-video.

## 4. Integrating into `cloud/`

None of this is done or tested.

1. **New renderer sources.** `bundle.make_bundle` writes `index.html` and `script.js` through `presentation_sources.verified_source`, which checks them against SHA-256 hashes in `cloud/presentation/sources.json`. The mockup versions would need to replace the files in `cloud/presentation/renderer/` (without the mockup-only parts listed below), with new hashes registered, as a deliberate approved change. The layout changes (compact header, balanced tiles) affect every video.

2. **Frame rate.** `render/original.js` plans at **20 fps**, with frame indices `Math.round(cursor*20)`. The mockup's 0.04 s quote frames would round badly on that grid. Set `QUOTE_FRAME_DURATION = 0.05` and use 24 frames (1.2 s) for the cloud, or switch the plan to 25 fps.

3. **Planner and chunk ops.** In `plan`, the loop `for (const [amount, duration] of response.frameInfo)` must also run an op `setQuoteProgress` with the third element, when it's present, before `save(duration)`. Add `setQuoteProgress` to the `allowed` ops in `action()`. Chunks rebuild state by replaying all ops from the start, so card state, swaps and marks are reproduced as long as every call goes through ops. `{swap: t}` is plain JSON.

4. **Cue data and assets in the bundle.** The page only allows requests to `http://localhost:8002/` and `data:` URLs. The mockup fetches `mockup-quotes/${case}.json`, `mockup-quotes/maps/circuits.svg`, and exhibit images by relative path. In the bundle, the cue file should be part of the frozen case inputs (e.g. `json/{id}-cards.json`, with its hash recorded in the job/manifest), and the SVG and exhibit crops copied in. Adjust the URLs in `loadQuoteCues` and the cues' `image` paths to match.

5. **Mockup-only code to drop or keep out of production.** In `script.js`: the preview player (`setUpPreviewControls`, `seekTo`, `advanceTo`, `nextBlockStart`, `formatPreviewTime`). In `index.html`: the `mockup-controls` element and the `<base href="/">` tag. `seekTo`/`advanceTo` could still be useful for a review UI.

6. **4K exhibits.** `render_excerpt` renders the page at 1800 px on its long side. At 3840×2160 the crop is upscaled, so use about 3600 px for production.

7. **Review.** Cards should go through the existing approval flow before a video is published. `cases.py` writes `reviewed: false` and keeps the basis text next to each card. Card types written by the agent should carry their evidence the same way (source URL, page, the quote as it appears in the source).

8. **Model engine.** In the cloud, Codex runs through `codex_auth` with credential leasing. The new `ask_codex` in `pipeline.py` calls `codex exec` with the **local** login and is meant for development. In the cloud, route these calls through the existing `codex_auth` wrapper, which already supports `--output-schema`.

## 5. Tools available to the agent

### `artifacts/pipeline.py` (existing prototype, with changes)

**What it provides:**
- `fetch --case ID`: downloads the docket and its PDFs (only filings dated up to the argument) and indexes the words on each page.
- `index_document`: per-page text, word boxes and the printed page label.
- `quote_word_indices`: a quote must occur verbatim on the page, after normalising line breaks, hyphenation and punctuation. This catches invented quotations.
- `render_excerpt`: crops the PDF page and highlights the quote. This is what the record-exhibit card uses.

**Changes in this session:**
- `parse_docket` now also keeps the **Petition** and **Appendix** links. Cert petitions were missed before, and they're needed for questions presented and circuit splits.
- `printed_page_label` reads appendix numbers in the "-App. 17a-" header style, including on booklet-size pages centred on letter paper.
- `ask_model(..., engine="openai"|"codex")`. `ask_codex` runs `codex exec --output-schema` read-only, with the prompt on stdin. Responses are cached under `output/CASE/llm/`, and cache keys for the OpenAI engine are unchanged.

### `artifacts/cases.py` (new)

```sh
python3 artifacts/cases.py --case 25A312 --engine codex --merge-into mockup-quotes/25A312.json
```

1. `authorities(case)`: reads every case citation in the indexed filings, using a regex for names and reporters, cleans up the names, and keys each case by its citation. Trump v. Cook has 311.
2. Detection (one model call): the first mention of each cited case in the transcript, with disambiguation of shared names (In re Sawyer vs. Youngstown v. Sawyer; the Supreme Court's vs. the Court of Claims' Reagan v. United States) and of garbled names. Each answer is validated:
   - the evidence must be verbatim in the named block;
   - the authority ID must exist;
   - the evidence must contain a close match of the case name. If the speaker misnamed the case ("Drago" for Delgado), it falls back to the first exact mention.
3. Summary basis:
   - Oyez: term listings, matched by citation, or by volume plus party name when Oyez has no page number;
   - otherwise the official syllabus from the Caselaw Access Project's static files (`static.case.law/us/VOL/…`).
4. Holdings (one model call): one past-tense sentence of at most 35 words, using only the basis text. When a case decided several questions, it states the part relevant to the excerpt where the case is mentioned.
5. Output: `output/CASE/cases.json` with cards, unresolved cases and rejected detections, plus the evidence and basis for review. `highlight` is filled with the spoken name, preferring the full form ("Trump against United States").
6. `--merge-into` replaces the case cards in a cue file. Cards may abut (they stack); a card that would start while another is still showing is skipped.

For the agent workflow, treat steps 1, 3 and 5 as tools. Treat step 2's choices as suggestions the agent can override.

### Other sources (checked in this session)

| Source | Use |
|---|---|
| supremecourt.gov dockets | Filings, grant entries ("Petition GRANTED", or a grant limited to some questions), application deferrals |
| `https://www.govinfo.gov/link/uscode/{title}/{section}?link-type=html` | Official U.S. Code text (2024 edition); used for 12 U.S.C. 242, 29 U.S.C. 153(a) and 15 U.S.C. 41 |
| Oyez API (`api.oyez.org/cases?filter=term:…`) | Case summaries and votes. Older cases are grouped into ranges such as "1900-1940"; recent cases often have no page number. Some records have an empty conclusion (e.g. Dalton v. Specter). |
| Caselaw Access Project (`static.case.law`) | U.S. Reports with the reporter's syllabus ("head matter"); public domain; no key needed |
| CourtListener | Opinion text needs a free API key; the website is protected against bots. Not used yet. |
| Justia | Returns a bot challenge to scripts; do not try to get around it |
| Wikipedia | Infobox "Holding" field: patchy coverage and CC BY-SA. Use only as a cross-check. |

## 6. How each card type was sourced in the mockups

These are worked examples to follow.

- **Statute (Cook 3:15):** 12 U.S.C. 242 from govinfo. Only the relevant sentence is shown, with "unless sooner removed for cause by the President" marked.
- **Timeline (Cook 19:29):** every date was confirmed in the filings: the application, the response, the D.C. Circuit order of Sep 15, and the docket entries.
- **Side by side (Cook 21:30):** the Federal Reserve Act's "for cause" against NLRA § 153(a)'s "upon notice and hearing", both from govinfo.
- **Glossary (Cook 24:00):** INM is "inefficiency, neglect of duty, or malfeasance in office". The FTC Act wording was checked on govinfo.
- **Question presented (Stanley 4:19):** the petition's page i, plus the docket's "Petition GRANTED" entry dated Jun 24, 2024.
- **Record exhibit (Stanley 28:11):** petition appendix page 17a, where the Eleventh Circuit acknowledges the split. Made with `render_excerpt` and the verified quote.
- **Circuit map (Stanley 31:18):** the sides come from the petition's "reasons for granting the petition" (2nd and 3rd Circuits vs. 6th, 7th, 9th and 11th). The petition lists the circuits explicitly, so a cert petition is the place to look.

## 7. Known limitations

- `pipeline.transcript()` supports only a single oral argument per case. Scanned PDFs would need OCR.
- `cases.py`:
  - cases from the early nominative reporters ("12 Wheat. 19") are not mapped to U.S. Reports volumes;
  - lower-court and state cases get no card;
  - later history (overruling, narrowing) is not checked. Humphrey's Executor is the obvious example to handle carefully.
- Map label positions are worked out from each circuit's largest state, with one fixed correction (`MAP_LABEL_OFFSETS`, for the 11th Circuit). Alaska, Hawaii and the territories are dropped.
- The timeline gets crowded above about 8 events. Long side-by-side texts force a full squeeze.
- Opinion-announcement mode never shows cards.
