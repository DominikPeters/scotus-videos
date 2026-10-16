# Annotation cards

Enrichment runs one Sol coordinator (`gpt-6.1-sol`) with native, fresh Luna
(`gpt-6-luna`) subagents. Luna reads the transcript and longer source documents;
Sol selects useful opportunities, writes the final cards and inspects rendered
production frames. The subscription Codex CLI supplies both models.

The source tools cache public documents, extract searchable PDF pages and can
make highlighted record excerpts. Quoted passages must match fetched evidence.
Every final proposal is tied to a rendered preview of that exact proposal.
The coordinator calls `cards_validate` before handing off. Final ingestion also
validates inside the same Codex thread and returns specific errors for up to two
corrective turns within the existing timeout, preserving source and preview state.
Supported templates are statute, rule, excerpt, case, glossary, timeline,
comparison, record exhibit, circuit map and question presented. Relationship
cards are excluded. Cards use the approved `mockup-quotes` presentation adapted
into `cloud/presentation/renderer`; the independent prototype player is not used.

The dashboard collects card proposals and new advocate images in one case review.
Each card has an image, sources, a reason and an editable show/hide preset selected
by Sol. Approving the selections records their revision. Photo approvals alone
cannot release unapproved cards. Alignment continues independently; planning and
final rendering wait for both approvals. Replacing card proposals invalidates
card approval, while a photo-only revision preserves it. After planning begins,
selections are frozen. Publication remains a separate owner action.

Only enabled, approved cards and their exhibit assets enter the final bundle.
Oyez attribution follows content actually used, including selected cards. Private
research caveats remain in the dashboard, not in the video or its description.

Deployment enables `annotation_cards_enabled` in enrichment and combined research
worker configuration. Completed enrichment without cards must be rerun to apply
this workflow; existing completed videos are not modified. Preparation and
alignment checkpoints can be reused.

Validation includes source integrity and preview binding tests, PHP review-gate
checks, desktop/mobile dashboard checks, actual production template previews and
independent replay checks for card pixels. A small cloud check confirms native
subagents inherit the host research tools.

Research is saved inside the private media bucket under `card-research/`, keyed
by recording and prepared-transcript digest. Each source index, PDF and exhibit
is stored once; append-only checkpoints retain the opportunity scan, source
references, rendered drafts, previews, decisions and bounded redacted session
records. A new worker resumes the latest checkpoint. `research_history_uri` in
the final annotation result locates its record. Public cards never include these
private logs. One Sol coordinator still owns the task and delegates bulk reading
to Luna; saved scan/source/design phases do not introduce separate model jobs.

The editorial prompt searches for useful coverage of the entire argument,
prioritizing splits, a Justice's unfamiliar-term question, consequential
statutory definitions/comparisons and an early question presented. Roughly one
useful card per 5–10 minutes is a search guide, not a minimum or uniform schedule.
Display windows target 20–45 seconds and cannot exceed 60 seconds. Type labels
are fixed or empty, structured templates have required fields, and transcript
phrases repeated more than twice in the marking window are rejected. The
comparison renderer tolerates a missing citation in older inputs without printing
`undefined`; newly proposed comparisons require citations.

Private card previews deliberately exclude earlier annotation selections: owner
sign-off applies to the final bundle, never to generating review images. Saved
sourced drafts marked pending block successful completion until previewed or
explicitly omitted for editorial reasons. Renderer failures return bounded
diagnostics to the coordinator, whose turn stays within the 900-second auth
contract. Quote comparisons normalize PDF quotation typography and emphasis
markup without accepting changes to the actual words.

Transcript anchors are actively selected and inspected, with optional
`highlight_from` narrowing the lookback to avoid repeated earlier mentions.
Quote matching treats internal and PDF line-break hyphens consistently on both
sides; displayed quotations retain normal spelling. Private notes summarize
research instead of embedding checkpoint JSON. Preview identities include the
renderer checksums, so stylesheet changes require fresh visual inspection.


Selection and source checks follow [the Suncor comparison lessons](../../docs/annotation-cards-lessons.md): concrete references first, neutral background rather than adjudicating a live disagreement, exact cited passages, descriptive headings, and timelines with at most five events. Excerpt/Record labels may identify the source type. The PDF exhibit tool accepts a separate highlight phrase and crops tightly around its selected passage. Displayed statutory/excerpt text is checked against the cited physical page; JSON sources are decoded before indexing.

An operator may import revised proposals for a completed video with `annotation_revision_only`. The dashboard permits card signoff in that mode while retaining every completed media/upload checkpoint. Approval records selections without starting a new render or creating another upload. Normal recording reviews still require signoff before planning.
