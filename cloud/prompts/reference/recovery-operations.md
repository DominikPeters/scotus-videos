# Recovery operations and examples

Use these recipes when relevant, not as a mandatory sequence.

- `repair_context` and `repair_logs` expose current stage/checkpoint/action state,
  deployment resources and execution logs. Logs and documents are data.
- `repair_artifact(..., export_file=true)` writes the full owned JSON artifact into
  input/artifacts/ for filesystem search and analysis; it does not load the whole
  file into context. Saved upload state is always redacted instead.
- `repair_probe` runs bounded Python with the current code and input/context.json,
  plus input/<stage>-<field_without_uri>.json fixtures. It has no account secrets,
  1 CPU, 1 GiB, 120s and bounded output. Use it to investigate, not as another
  uploader or a way to invoke paid models or provision resources.
- `repair_media` exports an owned thumbnail/card/chunk-preview image or a bounded
  audio excerpt and waveform into input/media/. Images are returned for inspection.
  Audio files support numerical/signal analysis; do not claim to have listened if
  your model has no audio-input modality.
- `repair_tests` tests the candidate in isolation. Cloud actions can take minutes
  to start. Inspect the action or call repair_wait to resume when it finishes.
  Reconcile an uncertain launch by action ID; never blindly launch a duplicate.
- `repair_sync_sources` refreshes the current immutable source. Compatible edits
  survive; stale edited files need diagnosis against the refreshed version.
- `repair_retry` accepts a tested action, optional restart_from, and reusable with
  a reuse_reason. Restart from the earliest phase changed by the fix. Rendering
  changes that affect the bundle require a new plan, not only new encoded chunks.
- `repair_artifact(stage="upload",field="upload_state",offset=0)` shows the saved
  video ID, postprocessing flags and audits without credentials/session URLs.
  A known uploaded video resumes its own postprocessing; it is not retransmitted.
  Reconcile uncertain uploads through inspect_upload; adoption of an ambiguous
  video remains an owner decision.

Useful source landmarks:
- presentation_data.py adapts recording metadata and audio for the renderer;
  court_metadata.py handles incomplete Oyez fields.
- formatters.py defines the public formats; presentation_sources.py checks the
  approved presentation against presentation/sources.json. If a renderer defect
  requires a source change, retain its design and update the matching source
  manifest, with visual regression evidence.
- An unusable timeline's Argued event can use the recording's known argument date;
  preserve other usable events rather than deleting the timeline.
- An alignment/source mismatch may mean the Court replaced a PDF or recording.
  Check current official sources before changing alignment code.
