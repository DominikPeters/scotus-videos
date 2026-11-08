# Accepted workflow requirements

This document records decisions from the owner. It is the output contract for
future pipeline work, not a claim that the features below are already deployed.
The dashboard, credentials and controller are live; the video/research/recovery
workflow is still being connected.

## Preserve the existing product

Use the current working tree's index.html, script.js, Myriad fonts, seal,
subscribe image, justice/advocate images and other existing assets. Preserve
layout, text sizing, highlight behavior, scroll frames, interaction display,
thumbnail, splash, conclusion and supported argument/opinion transitions.
Parallelization belongs in screenshot/render scheduling and other workflow code.
Do not replace the presentation with cloud/render's simplified prototype.

The owner approved replacing the old section-triggered subscribe image with
Claude's reminder pill: once, for eight seconds, in the first card-free gap of at
least fifteen seconds after ten minutes; skip it if no such gap exists. This is
an explicit exception to preserving the old subscribe overlay. See
`docs/subscribe-reminder.md` for deterministic capture and rollout status.

Reuse the existing preprocess.py / self-aligned-preprocess.py data shapes and
YouTube formatters, upload-video.py thumbnail/playlist behavior, and
add_timestamp_comment.py formatting. Keep title style, description sections,
chapters, thumbnail design/compression, category and other upload conventions.
The reduced cloud uploader is not the final publication implementation.
Conditional truthful source credit is an explicitly requested wording change.

Keep original Court transcript text separate from the aligner's normalized text.
Use official Court audio/PDFs and English CTC CPU alignment. Use Oyez case metadata
when available; Codex supplies missing fields from grounded sources.

## Case descriptions

Use Luna for bulk research and Sol for final writing, with explicit model IDs in
editorial-profile.json. The prepared defaults are gpt-6-luna and gpt-6.1-sol;
availability must be checked when the private model worker is enabled. Use the
subscription-only CLI path, with no API-key fallback.

Fill the existing facts_of_the_case and question fields. Preserve short Oyez
entries verbatim. Shorten overly long Oyez entries while preserving their originals
privately and crediting their content. Missing fields require research; shortening
available Oyez fields can go directly to the writer.

Bias toward about 80–100 words of background and 20–35 words for the question,
or less. Initial configurable ceilings are 120 and 60 words, with 160 combined.
Never pad to a target or mechanically truncate prose. A bounded extra writing pass
can condense an overlong draft; it must retain essential distinctions and granted
issues. Actual font fit still needs checking in the original renderer.

Official questions presented may be tendentious. Identify and neutralize loaded
language, contested premises and implied answers while preserving the actual
granted question and limitations. Check the opposing party's position and relevant
lower-court decision. Distinguish background, allegations and party positions;
describe the case as it stood at argument, without hindsight from a later decision.

Luna supplies a compact evidence packet with source IDs, relevant passages,
locators, neutral issues and private framing notes. Sol receives selected passages
and links for focused checking, not the whole bulk reading input. Excerpts matched
to supplied text are marked; unverified research excerpts require a source check.
Keep primary-source verification accessible rather than treating Luna's synthesis
as authority. Final prose, source provenance and private notes remain separate.

Prompts/case-research.md and prompts/case-description.md describe the tasks. The
case_descriptions adapter returns escaped paragraph HTML for the original fields,
keeps Oyez provenance on condensed content, rejects unknown source references and
provides a bounded word-budget rewrite. It is not connected to live jobs yet.

## Discovery and review

Backfill missing arguments from the current term. Import/index existing channel
uploads and legacy records before enqueueing so backfill does not duplicate them.
Handle related dockets, rearguments, revised inputs and the existing supported
combined-recording workflows explicitly.

A missing photo/logo requires review. Monthly local preparation is the preferred
first path: derive an advocate inventory from the Court hearing schedule, match
it to the existing image cache, and use the owner's local Chrome for discovery
and cropping where fresh cloud HTTP/browser sessions receive 403s.

The dashboard should display proposed portraits and, when relevant, firm/agency
logos, initials or SVG alternatives. Show identity evidence, source links, crop
and preview. Synthetic choices are operator-approved alternatives, not automatic
substitutes for an unresolved missing portrait. Existing owner-curated assets are
approved; approval of a new asset should be reusable for that verified identity.
An identity conflict or missing approved alternative holds only that recording.

## Title task

The title task must consult the full private title-history file and receive
illustrative real examples in its prompt. Refresh history after successful uploads
or title changes. Keep owner-only/unlisted title history out of the public repo.

Titles should be descriptive, distinctive, interesting and accessible to
non-experts. Choose a legitimately interesting angle, without clickbait,
invented stakes or a misleading account of the issue before the Court.
Mirror the existing channel style; do not enforce an artificial 1–3-word cap.
Return a recommended title and, when genuinely uncertain, one or two alternatives
with private explanations. Use the recommendation by default; the dashboard can
switch to a backup before publication or update the existing unlisted video's
metadata. A title change should not require rerendering the video if its visual
inputs are unchanged.

Prepared trusted instructions are in prompts/title.md and
prompts/public-output-policy.md. The result schema separates public titles from
private reasons/caveats. Work/input paths are assembled by the application,
not selected from untrusted web-page instructions.

## Failure recovery and asynchronous conversation

Every terminal fetching, preparation, alignment, rendering, assembly or upload
failure creates or resumes a private Codex recovery thread for that recording.
Lease expiry/execution failure also counts even if the worker could not report it.
A short, ordinary network retry need not create a separate thread for each log line.
Deduplicate repeated failures by recording, stage, input revision and failure
fingerprint; supervise existing recovery instead of spawning unlimited workers.

Persist thread IDs, rollouts/context, relevant artifacts, attempts, diagnostic
summaries and operator replies in private storage. A fresh worker restores the
same thread and latest Codex auth cache. The current --ephemeral launcher cannot
provide this behavior; recovery needs a persistent runner. These are cloud CLI
threads represented in the dashboard, not automatically desktop-app sidebar chats.

Give recovery meaningful tools: sanitized exception/traceback and stderr, cloud
logs, job/image IDs, input hashes, stage checkpoints, relevant workflow source,
bounded probes, permitted workflow patches/tests, and affected-stage retries.
The current fixed error category alone is insufficient for diagnosis. Allow
repairs autonomously within configured profiles and budgets. Protect the original
presentation/assets, public templates, auth controls and publication boundary.
Publishers/brokers keep credential values out of model/tool output.

When an operator decision is needed, store a plain-text question with choices
and optional free text. Bind it to the thread, recording and relevant revision.
End the current worker turn. The passkey-authenticated answer atomically creates
one continuation task; a new worker resumes the same Codex thread. Reject stale
or duplicate answers. Notes that do not require a decision should not block work.
Prompts/recovery.md and schemas/recovery-result.schema.json describe this contract.

Preserve useful completed artifacts. Reconcile uncertain uploads before retries
that could duplicate a video. A workflow-code repair should have a tested patch
and provenance; automatic deployment must honor protected-file hashes and limits.
If Codex subscription usage is exhausted or auth needs renewal, queue/notify
rather than falling back to API billing.

## Public text policy

No new public-facing disclaimers without the owner's explicit approval. This
covers videos, titles, descriptions, thumbnails and comments, including defensive
statements about AI, edited metadata/transcripts, alignment or photo discovery.
Caveats go to the owner and normally permit continuation. The explicit photo
review, invalid-output and resource-limit exceptions above remain in effect.
Existing owner-authored disclaimers form the approved baseline. Only the operator
can approve new wording for an exact output revision.

Keep generated public fields structurally separate from private model notes and
questions. The application should compose public outputs from existing templates
and approved data, not concatenate arbitrary model prose. Check generated fields
for unapproved disclaimer additions before output; official verbatim transcript
content is not a generated disclaimer and must not be silently rewritten.

Credit Oyez if and only if its content contributed. Track provenance per field
and asset; use that evidence for conditional source credit. Do not imply the
Court transcript, CTC alignment or Codex fallback facts came from Oyez.

## Dashboard and phone actions

Keep the dashboard maximally sober: no marketing copy, eyebrows, uppercase
styling, accent colors or accent italics. The attractive title is the video's
content, not a change to dashboard copy/design.

Add review cards for titles, photos, private model notes/questions and recovered
errors, plus a publish action for completed unlisted videos. Publication remains
a user action after the existing thumbnail, playlist and comment steps finish.
Approvals should refer to the exact artifact/revision shown; an old approval must
not silently authorize a different portrait, title or unfinished video.

Notifications may use ntfy.sh/scotus_youtube_alerts_dp. Notify actionable review,
questions and recordings ready for publication; put routine attempts/progress in
the dashboard. Deduplicate notifications with a persisted outbox. Notifications
open the relevant passkey-protected review card by default; opening a GET URL
must not publish or approve anything. Until topic privacy is configured, send
only generic notices, without private notes, logs, credentials or approval tokens.

The owner uses an iPhone. ntfy's current documentation lists iOS support for
click links and action buttons. Direct mutation buttons need an authenticated
callback and revision/expiry/replay handling. A Telegram bot is another option
for inline choices and photo cards, bound to the owner's verified user/chat ID.
The mobile dashboard remains the authoritative review surface.

## Validation before enabling automation

First demonstrate output parity using existing inputs and the existing rendering
and upload code. Compare representative frames, scroll/section boundaries,
thumbnail pixels and generated description/chapter/comment/playlist payloads.
Then validate complete Court-PDF + automatic CTC + metadata/title paths. Exercise
one recoverable failure and one delayed operator answer, including a fresh worker
resume. Test retries around upload/post-processing so they do not duplicate videos,
comments or playlist entries. Measure runtime/cost and set limits before scheduling.

## Current preparation

- Complete title history has been refreshed privately under work/editorial/.
- Title, public-text and recovery prompts and structured result schemas are drafted.
- The title adapter stages the full history/source inputs, validates choices and
  keeps selection of a public title separate from private notes. It is not deployed.
- A two-stage case-description adapter and prompts are prepared, with Luna research,
  Sol writing, source provenance, brevity budgets and long-Oyez condensation.
- These contracts do not yet launch model tasks, recovery workers, notifications,
  photo approvals or dashboard publication.

Primary references:
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/app-server
- https://docs.ntfy.sh/publish/#action-buttons
- https://docs.ntfy.sh/publish/#click-action
- https://docs.ntfy.sh/config/#access-control
- https://core.telegram.org/bots/api#inlinekeyboardmarkup
