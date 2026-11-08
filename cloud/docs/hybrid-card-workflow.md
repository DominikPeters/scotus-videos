# Claude editing with independent readers and Sol review

The implementation is opt-in. The default remains `annotation_cards_backend=codex`.
The code and filesystem library were deployed in worker-20261103-75c411f7 on
3 November. This deployment did not enable a provider switch or import Claude
credentials. Dedicated subscription setup and bounded live provider smoke checks
remain prerequisites to activation. Existing imported card sets keep their
existing review/approval flow.

## Filesystem reference library

All four roles receive a `reference/` directory in their temporary workspace.
Claude has native Read/Grep/Glob tools; Codex uses its existing read-only file and
shell tools. A small `input/library.json` gives paths rather than inserting the
archive or source documents into the initial context. The full argument and the
role's required case/reader inputs are still supplied as before; those inputs are
also staged as files for Claude, as they already were for Codex.

- `reference/archive/templates.json`: supported card shapes, retrieved as needed.
- `reference/archive/README.md`: searchable index of historical trial designs.
  The initial archive has 71 cards from three trial sets. Each run excludes its
  own docket. These are examples, not a claim of owner approval or legal evidence.
  Private trial notes, evidence logs, previews and assets are not exported.
- `reference/sources/index.json`: URLs, source IDs, page counts and directories.
- Each source has `source.json` (original provenance and physical page labels),
  `text.txt` (complete searchable text), `pages/NNNNN.txt` and, for PDFs, the original
  `original.pdf`. OCR updates the exported page text without changing PDF identity.

`cards_source` with page 0 and an empty query returns these file paths rather than
the complete source text. Explicit page/query requests still return targeted text.
Downloads and OCR update the same shared reference tree while models are running.
Atomic file replacement avoids partially written pages. Resume rebuilds the tree
from the current checkpoint; stored original PDFs are checked against their digest.
The card tools still verify packet and displayed quotations against the source
cache. Reading an arbitrary file does not turn it into verified evidence.

The shared tree contains no current reader scans, checkpoints, tool logs or
credentials. Claude's input directory is separate from its configuration/auth and
MCP files. Read tools are confined to the input and reference working directories;
explicit deny rules cover its private config/output files. File-edit and shell
tools remain absent from Claude's native catalog. Codex retains its existing
read-only sandbox. The reference files themselves are read-only to model tools;
the trusted host exports updates. These are tool permissions, not a new OS-level
container isolation boundary.

Refresh the curated archive from the trial files with
`python3 cloud/infra/refresh_card_archive.py`; it is included automatically in the
next pipeline source batch under `prompts/`. No new bucket, credential, persistent
history or cleanup job is needed. The image installer also supplies ripgrep for
native filesystem search.

## Normal sequence

1. Python prepares case identity, speaker names and the entire numbered, aligned
   argument. Completed description/title/portrait work is checkpointed first.
2. Haiku and Terra independently read the argument and research sources online.
   Both can search the web, fetch primary sources, and OCR selected scanned pages.
   They share downloaded source bytes but not each other's current candidate scan.
3. Opus receives the argument, concise candidate indexes and an evidence index.
   `cards_evidence` supplies selected complete source units without re-opening
   filings. `cards_search` searches cached sources for passages a reader did not
   packet; `cards_source` supplies complete page context. Web search/fetch and OCR
   remain available for focused evidence gaps, with instructions to trust the
   readers and avoid repeating broad research. Opus selects, writes, renders and inspects **one full-set production
   contact sheet within this same editing session**, then returns its corrections.
4. Sol independently verifies sources and context, checks neutrality/density,
   renders final revisions, inspects full frames/crops and performs final validation.
   It preserves Opus's selected IDs, types and show/hide presets. Timing ranges may
   change only to repair a current timing-validator failure (for example, overlap
   or an over-60-second range after alignment changes). Other moves are proposals.
   Substantive additions, deletions and moves become private owner proposals.
5. Validated cards enter the existing dashboard review. A material unresolved
   defect holds the set for an owner decision. No automatic Sol-to-Opus call exists.

The readers save progress after each third of the argument. Complete reader
reports, source packets, the editing result and final review use the existing
single case checkpoint. A lost final CLI reply after a finish-tool commit does
not repeat the model call. Timing-only changes retain the editor's work and
invalidate the final visual review; changed transcript blocks require a fresh
scan while retaining sources and previous research.

Each role calls its finish tool with the complete result, then replies only
`{"saved":true}`. The finish payload is authoritative; a confirmation without a
saved result cannot complete a phase. Models never repeat a saved card set in
their final reply. Opus gives decisions for each reader's `top` list, legacy
pending designs, additional selections and significant other omissions. The host
records ordinary non-top omissions as not selected without asking Opus for prose.

## Evidence packets

Each packet has a source ID/URL/original byte digest, physical page range, exact
supporting quote, precise locator, private caution and the complete relevant unit:

- Rule/statute: the full relevant subsection, including material conditions,
  exceptions and cross-references.
- Opinion: the key paragraph with its qualifications; a separate packet can carry
  a relevant footnote on another page.
- Record: the full relevant paragraph and attribution/procedural context.

Readers attest `context_complete=true`; the host verifies the quoted unit against
the fetched pages. Sol still reviews semantic completeness. This is not proof that
a reader's legal boundary choice is correct. Packets are never silently truncated.
Opus sees short index entries and requests complete packets by ID. All card roles
can list/search cached sources; targeted full-page reads and focused web research
are available when packets omit a needed passage. The editor/reviewer prompts incorporate the neutrality,
timing, headings, source-scope and layout lessons in `docs/annotation-cards-lessons.md`.
Readers explicitly flag source misstatements and unverified claims privately,
distinguishing a contradiction from missing verification. Before spending OCR
pages they look for a text-layer copy, such as an opinion in a petition appendix.

## Limits and failure behavior

- Default phase limits: reader, editor and reviewer 1200s each; Haiku 128 turns,
  Opus 64 turns (configurable up to 200). Claude's native web search is capped at
  60 searches per invocation.
- About 200s before the hard cutoff, Codex receives a same-turn `turn/steer`
  warning. Claude receives a wrap-up notice with its next card-tool response.
  The Claude CLI's streamed user messages can queue another turn, so this path
  does not inject a queued message that could start another Opus round. A warning
  is advisory and never extends the hard deadline or starts a new model turn.
- A phase yields before starting if insufficient execution time remains. A fresh
  worker resumes saved results; the worker's 40-minute application deadline leaves
  margin inside the existing enrichment job timeout.
- Reader tool budget: 180 calls per reader; editor/reviewer: 160 each.
- At most 60 candidates and 30 top IDs per reader; at most 40 final proposals.
  These are upper resource bounds, not targets or spacing quotas.
  An empty set is allowed with explicit omission decisions; it needs no contact sheet.
- Complete packets: up to 30,000 characters each, five adjacent pages, 500 KB total.
- OCR: at most eight distinct selected pages per case, each subprocess bounded.
- The production subscribe reminder is scheduled once in a gap with no cards,
  after ten minutes. The obsolete section-opening/two-block restriction does not
  apply; the planner includes card entry/exit frames when finding that gap.
- One Opus invocation. Readers/reviewer have at most three calls including retries.
  An unfinished Opus pass holds immediately. The dashboard labels an additional
  invocation **Authorize another Opus pass**; the backend requires that explicit
  flag. Ordinary resume does not bypass the budget.
- Missing alignment or credentials starts no reader. Quota/provider waits retain
  work and defer; setup and material-review decisions hold. Expected subscription
  waits do not launch code recovery. Unexpected implementation exceptions still do.
- Application checkpoints are the durable record; native Claude session history
  is disabled. No new checkpoint-history objects or cleanup schedule are added.

The per-case model/profile is frozen when research starts. Configuration changes
apply to new recordings, rather than silently re-running an active editorial pass.

## Credential setup and activation

Use a dedicated Claude subscription token generated interactively on a machine
with a browser. The import helper reads it at a hidden prompt and keeps one current
version in the existing `scotus-research` group; no fourth physical secret is added.

```sh
claude setup-token
python3 cloud/infra/import_claude_auth.py
```

Do not put the token in a command argument, checkout, build context or chat.
The worker uses `CLAUDE_CODE_OAUTH_TOKEN`, a clean per-run Claude configuration,
fixed role tools and authenticated loopback MCP. It omits `--bare` because bare mode
disables subscription OAuth. No API-key or cloud-provider billing fallback is used.
MCP request/idle timeouts match the phase budget and automatic backgrounding is
disabled, so the one contact-sheet result is not dropped after a short HTTP timeout.
For subscription-only operation, keep account usage credits disabled. CLI dollar
estimates are diagnostic; wall time, turn/tool limits and saved call counts are
the application guards.

After the implementation batch and real provider smoke checks are ready, build
the pipeline image once. Both full and pinned-base build paths install Claude Code
**2.1.317** and bounded OCR tooling at image-build time, never on worker startup.
Deploy the matching PHP/frontend changes before enabling the worker profile:

```json
{
  "annotation_cards_backend": "hybrid",
  "claude_secret": "scotus-video-claude",
  "annotation_cards_profile": {
    "haiku_model": "haiku",
    "terra_model": "gpt-6.1-terra",
    "opus_model": "opus",
    "review_model": "gpt-6.1-sol",
    "terra_enabled": true
  }
}
```

Write configuration through `SecretStore` and use the coordinated release helper.
Do not enable hybrid on an image without the pinned CLI or before the dedicated
Claude credential and exact requested Codex models are verified. Test image/text
MCP delivery and usage-limit behavior in a bounded live smoke run before rollout.

References: [Claude authentication](https://code.claude.com/docs/en/authentication),
[headless CLI](https://code.claude.com/docs/en/headless),
[CLI options](https://code.claude.com/docs/en/cli-reference),
[official OpenAI App Server documentation](https://learn.chatgpt.com/docs/app-server).
