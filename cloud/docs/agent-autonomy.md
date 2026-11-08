# Research and repair agents

Agents receive the product goal, their authority, relevant files and the result
contract. They choose the investigation and resolve routine technical decisions.
The worker code enforces credential, publication and resource boundaries; prompts
explain the owner's preferences and the intended output instead of treating every
technical choice as a request for approval.

Research starts from supplied primary materials, follows consequential gaps and
preserves disputed framing privately. The writing pass reuses completed source
collection and text checks, concentrating on claims that determine the description.
Participation and statistics comparators live in searchable reference files rather
than the initial instructions. The card workflow has its own shared source/example
library; see hybrid-card-workflow.md.

Repair owns restoring the recording. Its initial message gives a case name, failed
phase, recent findings and paths to the full failure/recording files. It can search
the source checkout, experiment locally, export complete owned JSON artifacts,
inspect owned images, and analyze bounded audio excerpts/waveforms. The current
Codex tool transport does not provide native audio listening; the prompt explicitly
avoids claiming otherwise. Cloud probes/tests remain available when the actual
image or recording fixtures are needed.

Ordinary workflow modules, including the new card/Claude integration, and ordinary
workflow tests are repairable. A renderer bug fix can change its presentation
source with the matching source manifest and visual evidence. Public formatting,
credentials, authority/publishing controls, and their independent tests remain
protected. A candidate still has to pass isolated tests and the real phase's normal
checks. File-count micromanagement is removed; the existing byte/resource budgets
remain. Agents preserve test coverage and explain changed expectations.

Repair reasoning has 1200 seconds inside a 1320-second job envelope. A same-turn
wrap-up warning arrives about 200 seconds before cutoff. Conversation and edits
are checkpointed every 45 seconds and on exit; important findings should also be
logged as they are established. Cloud actions are launched once and reconciled by
identity. Waiting for a cloud action yields the worker and resumes automatically.
Owner questions are reserved for preferences, missing account access and changes
to the authorized scope.

# Render-only revisions

`python3 cloud/infra/operate.py rerender Younge` regenerates plan, encoded chunks
and the assembled MP4 from completed, approved preparation/alignment/editorial
inputs. It retains the existing YouTube upload, its checkpoint and privacy. It
creates a new upload only through the separate owner action `Upload corrected MP4 to YouTube`. That action reuses the finished MP4 and approvals, preserves the earlier video link, and starts a new unlisted upload with its own durable checkpoint. Repeated requests reuse that upload. The dashboard labels the new
MP4 separately and provides a short-lived authenticated download. The latest
revision keeps one previous assembly pointer, not an expanding revision history.

The 3 November opening-frame fix is in render/intro.js and render/original.js.
A first-block card/scroll animation may make the first returned frame only 0.05s.
The splash now borrows min(5s, whole first-block duration), consumes hidden
animation steps, and preserves the overall audio/video timeline. Unit tests cover
animated and short first blocks. Younge's approved bundle was checked in a browser
at 0, 4.95, 5 and 5.5 seconds, with an encoded 4K/20fps proof.

Deployed as worker-20261103-75c411f7. Younge's corrected render completed with all
12 chunks and 66,875 frames; frames extracted from the finished cloud MP4 confirm
the splash at 4.95 seconds and the first card at 5.5 seconds. The original unlisted
YouTube upload and approved inputs are unchanged. See
`agent-autonomy-younge-2026-11-03.json` for the build, validation and render audit.
