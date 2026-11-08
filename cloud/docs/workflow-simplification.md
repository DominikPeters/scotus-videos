# Operating the workflow

Routine owner commands accept a case name, docket, or recording ID. Credentials
are read in memory through the three existing groups:

```sh
python3 cloud/infra/operate.py status Younge
python3 cloud/infra/operate.py refresh-sources Younge
python3 cloud/infra/operate.py import-cards Maxwell annotation-trial/25-5930/cards.json
```

The dashboard also offers card import and official-source refresh. These do not
require an image build. An import takes a JSON object containing `cards` and
optional `source_urls`, `assets`, and `private_notes`. Each card has a unique ID,
`start_block`/`end_block` (end exclusive), `cue` or `cue_json`, and sourced
`evidence` passages (`url`, `page`, `quote`, `claim`). Matching evidence already
on the case can supply its URL. The CLI also resolves local source notes and
`sources/urls.json`, and content-named JPEG exhibits; the browser accepts the
portable JSON directly. Explicit `source_urls` entries override the local manifest.

Imports persist their input before work starts. The ordinary enrichment image
renders production previews without a model call. Saved previews survive worker
restarts. Overflow, invalid quotations, bad timings, and overlaps stop the import
with a specific message; they do not launch code repair. Imports always require
owner card selections after preview preparation. Revising an uploaded case saves
proposals without replacing or publishing its existing video.

## State ownership

* A build stamps one worker release ID and the actual curated source into its
  image. One deployment record points to that image and source. Repair checks
  use this record; internal per-file preimages prevent overwriting changed code.
  Compatible saved edits survive unrelated deployments and must be retested.
* Cards, titles, and each person's portrait have separate integer review
  versions. A portrait change does not invalidate card approval. Existing hash
  approvals migrate lazily without forcing a second review of unchanged cards.
* Research belongs to the recording, with one current checkpoint in locked
  dashboard state and the latest 100 research events. Sources and exhibits are
  immutable and reused. Realignment invalidates previews, while changed text
  rebinds unchanged contiguous blocks and retains affected drafts for rechecking.
  Legacy checkpoints are read once on migration, with pagination; new saves do
  not append checkpoint objects or need a daily compaction job.
* Main pipeline, recovery, photo, portrait-publication, and job-based video-action
  launches persist an attempt before calling Cloud Run. A lost reply is reconciled
  by that attempt ID. Unknown launches need two spaced absence confirmations;
  unavailable listings never prove absence. One current receipt is retained per
  owner, rather than an unbounded attempt journal. Existing clip/Spotify/statistics
  workflows keep their service-specific receipts.
* Interrupted executions resume saved work with bounded administrative retries.
  Completed render chunks survive. Uncertain video creation requires reconciliation
  before another upload. Starting a recovery process does not spend a reasoning
  turn; reasoning is counted immediately before the model runs. All launch compute
  reservations and daily limits still apply.
* Preparation/alignment failures check the current Court audio and transcript
  listings before code repair. Identical PDF bytes at a different URL retain work.
  Changed inputs regenerate preparation and dependents, retaining title, portraits,
  and case research. Unavailable official sources wait and retry. Existing uploads
  cannot be rewound.

Legacy artifacts are retained as references; this migration does not bulk-delete
case evidence. Object hashes remain internal integrity checks, not owner inputs.

## Batched deployment

Finish local Python, PHP, and dashboard checks and freeze the source first. Submit
one control build and one pipeline build with the existing build helpers. A pinned
pipeline base can reuse dependencies. Leave machine type unspecified. Build state
includes the worker release ID and generated source-manifest path automatically.

For the first rollout, install the new PHP helpers plus `reviews.php`, then
`state.php`, using `deploy_dashboard.py --include ... --check-baseline ...` to reject
concurrent edits. Install changed remaining backend files before switching images.
The deployment helper acquires a separate hold, lets existing executions finish,
and updates pipeline jobs, the release record, related configuration in one group
write, and the controller. It never changes the owner's paused setting.

```sh
python3 cloud/infra/deploy_release.py --control-build /path/control.json \
  --pipeline-build /path/pipeline.json --state /path/deployment.json --apply
```

If it reports `waiting_for_workers`, rerun the same command after they finish.
Deploy the matching frontend source, then add `--verify-and-resume`. The isolated
test image checks its actual source/release, runs the regression suite, and verifies
credential access is denied. Active saved repairs with unchanged edited files are
rebased and retested automatically. Superseded edits are removed from dispatch
and retained as the case's previous pointer; historical recovery records remain
intact. Only successful checks release the deployment hold.
Interrupted commands resume from the same state file; do not submit new builds.
An unconfirmed isolated launch is found by its saved action ID. Temporary check
objects and the previous generated release source are removed after verification.

The dashboard deploy helper stages and syntax-checks source before replacing it,
serializes deployments, and preserves credentials, passkeys, and mutable state.
