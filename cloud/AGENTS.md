# Cloud build workflow

- Batch related implementation changes and finish appropriate local checks before
  submitting one Cloud Build per affected container image.
- Do not build or redeploy after every small edit, commit, or push. If a build
  fails, fix the cause before retrying.
- Leave the Cloud Build machine type unspecified. Do not reintroduce an explicit
  machine override without a concrete need and a billing review: October 2026
  explicit E2_STANDARD_2 builds were charged while default-machine builds used
  the free build-time SKU.
- Use the next necessary deployment to verify billing; do not launch a build just
  to validate a reversible script or documentation change.
- The hybrid Haiku/Terra -> Opus -> Sol card workflow is deployed in the pipeline
  image but remains opt-in. Keep the current generator as the default until
  dedicated Claude subscription access and bounded live provider smoke checks
  are ready. Opus gets one contact-sheet inspection within its editing session;
  another Opus invocation requires an explicit owner decision. See
  `docs/hybrid-card-workflow.md` and `docs/hybrid-card-implementation-2026-11-03.json`.
- The 3 November Younge Claude-card import exposed a large-source paging error.
  The local `annotation_cards.py` now returns a bounded source index when the
  complete document would exceed the tool response limit; page reads and evidence
  validation remain intact. This fix was isolated-tested and applied to the import
  execution and deployed in worker-20261103-75c411f7. See
  `docs/younge-claude-cards-2026-11-03.json` for the import audit.
- The 2 November stage-dependency and subscribe-reminder batch is deployed with
  one control build and one pipeline build. Full PHP restart invalidation,
  control execution order and alignment-bound previews are live together.
  See `docs/stage-dependencies.md` and `docs/release-2026-11-02.json` for checks
  and immutable deployment references.
- Pipeline builds stamp their actual source and one worker release ID into the
  image. Deploy with `infra/deploy_release.py` using the two build receipts; it
  publishes the current release and updates configuration together. Do not copy
  whole-tree baseline hashes between worker configurations. See
  `docs/workflow-simplification.md` for the coordinated host/container rollout.
- Validate saved repairs against the running image's embedded source, including
  `repair_bootstrap.apply_release` on a clean copy. Rebase only when edited files
  retain their preimages, then rerun isolated checks before retrying a recording.
- Before changing alignment code for a source/audio mismatch, recheck the Court's
  current listing for a replacement transcript or recording URL. Compare the
  current official source with the prepared input. A changed source requires
  regeneration from preparation and downstream invalidation; keep the normal
  timing, compute and repair-budget guards.

# Credential lifecycle

- The tripartition is internal, research, and publishing. Only the trusted
  controller reads the internal bundle; workers fetch their own configuration
  using their Google identity and an explicit allowlist.
- Route credential writes through `scotus_cloud.secret_store.SecretStore` and
  deployment/import commands through `infra.managed_secrets.run_gcloud`. Do not
  add direct legacy secret-version writers after the migration.
- Keep one committed version per group. Skip unchanged values, serialize group
  writes, verify before activation, then destroy superseded versions. Do not
  add rollback history, age windows, or daily cleanup jobs.
- The three-group layout is deployed. Finish isolated-source regression checks
  before submitting a build batch. Documentation and host deployment-tool fixes
  do not require rebuilding runtime images.

# Agent and rendering updates

- Research/repair outcome contracts, searchable lessons, scoped artifact file/media
  access and the broader tested repair scope are documented in
  `docs/agent-autonomy.md`. Keep credential/publication controls independent.
- Opening splash timing must use the complete first block, including its animation
  frameInfo. Never use only the first 0.05-second card/scroll frame. Preserve the
  full audio timeline and verify a card at time zero in the production harness.
- Render-only revisions preserve uploaded video identity and approvals. They
  produce a new downloadable MP4; replacement upload/publication is a separate
  owner action.

# Dashboard preview and portrait fixes

- Card previews use authenticated binary reads, private ETag revalidation and
  read-only state resolution. Keep the legacy JSON endpoint for compatibility.
- Desktop previews must observe the scrolling detail pane rather than the window;
  viewport margins cannot preload beyond an intermediate pane's clipping edge.
- Large portrait sources are bounded at 40 megapixels and downsampled before
  cropping. A bare owner-provided HTTPS URL goes directly to the crop step through
  the existing public-network fetch guard. Do not turn a decoder/download failure
  into a generic request for another hint.
