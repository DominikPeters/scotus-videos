# Cloud workflow readiness

Checked October 14, 2026. The workflow and dashboard are wired.
Automatic work and current-term discovery are enabled. The controller ticks every ten minutes; scheduled argument days receive ten-minute Court polling from 13:00 through 18:00 Washington time until all scheduled recordings are discovered.

| Feature | Implementation and verification |
| --- | --- |
| Original presentation | Original HTML/JavaScript copied with SHA records; original fonts, seal, subscription graphic and curated images. Local pixel comparisons passed; cloud encoded two 4K chunks with 80 verified frames. |
| Preparation and alignment | Official PDF/audio, native extraction, appearances-based identity resolution, English CTC CPU. Sparse preliminary matches produce warnings and bounded fine alignment. Source mapping, the 235-second window bound, invalid paragraph times and backward boundaries exceeding 0.25 seconds remain blockers. Leading stage directions and tiny backward discrepancies are handled deterministically. |
| Titles and descriptions | Private corpus of 326 earlier titles plus subsequent workflow uploads; Luna research, Sol short neutral writing and titles. Oyez reused/condensed when available, with field provenance and private notes. |
| Photo review | Codex vision crop boxes applied to retained originals; exact square asset preview/full-source toggle. LinkedIn/news portraits explicitly allowed; authenticated LinkedIn fallback is host-mediated with Secret Manager cookies and bounded profile-only access. Find another image, recrop or request initials/logo with an optional hint; dedicated async photo worker and fresh approval. Missing portraits hold planning; alignment continues. Separate publisher saves approved assets and provenance to GitHub without exposing its App credential to Codex. |
| Dashboard | Passkeys, per-recording Start while automatic work is paused, queue/progress, private repair logs, title/photo review, previews and explicit publication. Consistent grayscale type/spacing, mobile date placement and delayed-action spinners. Queue, credentials, recent activity and resolved recoveries start collapsed. |
| YouTube | Original formatter and timestamp comment; durable resumable upload, original thumbnail compression, reconciled playlist/comment steps and OT playlist creation using the existing template. Johnson completed upload and postprocessing. Unlisted until owner publication. Publication/title edits now use a private, scale-to-zero HTTP service instead of starting an upload job; authenticated cold probe took 8.8 seconds. |
| Notifications | Durable generic ntfy notices with protected dashboard links for photo review, questions, closed-execution recovery and publication readiness. |
| Repairs | Persistent native Codex threads, private explanatory logs/questions, asynchronous answer/resume, isolated tests and stage-scoped GCS releases. Input-independent fixes become defaults after tests and normal phase checks pass on the same source baseline; no automatic GitHub code commits. Recording-aware metadata/audio adapters are separately editable, with public formatters protected. Year normalization, null court rosters and missing argument dates have source fixes and regression coverage. |
| Budget | Conservative daily repair reservations capped at $1; fixed job hardware/timeouts, no GPUs, no paid API fallback. This is application accounting, not a Google Billing account spending cap. |
| Discovery | Current-term official listings, paired audio/PDF links, stable recording identities, backfill and duplicate queue suppression. Live-page check found four recordings after correcting relative-link handling. |
| Credentials | Guided YouTube/Codex/GitHub sign-in and renewal; separate worker access through Secret Manager. Passkeys/config/state preserved during deployment. |

No large media or model files were transferred to the operator's computer.
The controller reconciles closed Cloud Run operations as well as heartbeat leases;
worker claim retries are bounded and idempotent. This closes the unclaimed-task
blind spot found when 13 of Johnson's 14 render chunks completed overnight.
Implementation checks used bounded CPU jobs; native protocol validation consumed
subscription model turns. Johnson completed alignment, full rendering, assembly,
YouTube postprocessing and owner-requested publication.

Johnson v. United States Congress (25-735), argued October 5, 2026, is prepared
using the official listing's audio/PDF links. Kevin J. Barber has a curated image;
Jeffrey W. Chen's vision crop followed the research and approval path. Do not
bypass photo review or publish automatically. Public caveats/disclaimers require owner
approval; private caveats normally allow continuation.

Recovery now has scoped live evidence/logs, isolated probes, refreshed source,
new regression tests/helpers, editable upload transport, upstream restarts that
preserve approvals/editorial, and asynchronous continuation after isolated actions.
Its turn limit is six within the same daily budget. New question options state
whether Codex or the owner acts. The mixed-case McCLOUD cue/appearance fix has
regression coverage in both parser modes. Kevin Joel Page's owner-approved
defender seal and provenance are committed; the cloud catalog pins its image SHA.

October 13: podcast exports and scoped App dispatches are enabled. The podcast
consumer passed seven tests and a real three-case GitHub dry run; a live run
published Johnson, Anderson and Suncor chapters/VTTs with stable GUIDs/audio URLs.
Photos and rendering do not gate the exports. Metadata-only Oyez updates preserve
our alignment; media revisions control uploads, and feed replacement is atomic.

Beaird exposed transient dashboard transport failures during alignment heartbeat,
enrichment claim and repair claim. Heartbeats now retry temporary transport
failures and stay within the confirmed 180-second lease with a 30-second margin.
Owner requests release PHP session locks before cloud work. Selected immutable
preview URIs use an authenticated callback-free cloud read and private disk cache;
client image requests are deduplicated and limited to two. State loads independently
of credential checks. Backend outages return 503, authentication failures retain
401/403. One real thumbnail read completed in 1.31 seconds. 125 Python tests passed.

Assembly and upload now share one normal Cloud Run delivery execution (2 CPU,
8 GiB), under the existing upload service identity with unchanged YouTube-secret
permissions. Assembly is checkpointed and upload is reserved atomically before
continuation. Dashboard phase labels and retries remain separate; a standalone
upload retry reuses the saved MP4/video ID. Patched phases retain their isolated
worker paths. The combined execution owns both stages for failure/log recovery.
127 Python checks and PHP atomic handoff/checkpoint checks passed.

Preparation and enrichment now share a normal 2-CPU/2-GiB research worker under
the existing enrichment identity. The preparation checkpoint atomically reserves
enrichment; its completion prompts alignment dispatch. Alignment can run alongside
enrichment, including photo review holds, using the existing 4/8-CPU threshold.
Planning joins both completed branches. Independent retries preserve a healthy
active branch and photo holds; photo review cannot conceal an alignment failure.
Standalone workers remain available for repair releases and retries. 128 Python
checks, all PHP workflow checks and desktop/mobile phase-label checks passed.

Encoded render chunks are now removed after the verified finished MP4 is saved
and its assembly checkpoint is complete. Cleanup checks the final object's
metadata, deletes only receipt-listed scratch render chunk.mp4 objects, retains
receipts/previews, and records resumable progress in dashboard state. Cleanup
failures do not fail video processing. The controller has delete-only permission
conditioned on scratch paths ending /chunk.mp4; final MP4s, audio, PDFs and
images are excluded. Legacy completed uploads also qualify after frame-count
and checkpoint checks. 133 Python checks and PHP cleanup-state checks passed.

## Spotify delivery

Manual transfer and separate owner-approved publication are available for completed YouTube recordings. Automatic transfers remain disabled. The cloud streams the existing MP4, waits for RSS episode discovery, renews Spotify credentials and preserves upload checkpoints for retries. See [Spotify delivery](docs/spotify-delivery.md).

## Annotation cards

Sol-led enrichment and native Luna research delegation are implemented, with
production-frame inspection, source-bound quotations, record excerpts and the
approved card templates. Dashboard card presets and sign-off share a case review
with advocate photos. Alignment proceeds while review is pending; final rendering
requires both approvals. See [Annotation cards](docs/annotation-cards.md).

Card output now has an agent-callable, side-effect-free `cards_validate` tool
with specific per-card errors. Final validation also feeds errors back to the
same Sol thread for at most two corrective turns within its existing timeout.
This incorporates the Salazar recovery worker’s tested correction approach and
preserves fetched sources and previews during correction. 155 Python checks pass.
