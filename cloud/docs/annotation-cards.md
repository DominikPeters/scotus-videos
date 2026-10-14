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
