# Stage dependency fixes — 2 November 2026

Execution order is preparation → alignment → enrichment (including annotation
previews) → planning → rendering → assembly → upload. The historical dashboard
stage ordering is retained for compatibility; recovery uses the execution order.

The source fixes and regression checks cover:

- Alignment restarts invalidate enrichment and its dependent artifacts and card
  approval. Existing titles, approved portraits and reusable editorial research
  remain. Superseded downstream recoveries are cancelled.
- Research checkpoints retain sources, designs and exhibits across realignment,
  but discard preview images and visual approval tied to the previous alignment.
- Assembly cannot start with chunks recorded as deleted. An explicit manual retry
  regenerates missing chunks while retaining available completed chunks. The new
  recovery broker selects rendering first and reserves for the actual render task
  count before requesting automatic restoration.
- Enrichment, recovery, portrait revision and statistics share a reservation made
  atomically during dispatch. Starting workers reserve the slot before they obtain
  the credential lease; waiting and finished workers release it.

## Deployment status

The owner approved the combined build batch after revising Maxwell's cards.
One **control** and one **pipeline** build succeeded, with no explicit machine-type
override. All 13 pipeline jobs use the new immutable image; the controller serves
the new revision with 100% traffic. Full PHP restart invalidation, control execution
order/render-budget corrections, and alignment-bound preview caching are deployed
together. The immutable baseline and all four configuration pointers were updated.

Validation: 284 Python tests passed locally, all 23 PHP fixtures passed, and the
deployed isolated recovery execution passed 286 tests (4 skipped), including exact
baseline equality and denial of account-credential access. Six relevant fixtures
also passed against the deployed PHP handlers using isolated state. Each of the
three credential groups still has exactly one live version.

Younge's alignment subsequently recovered on 3 November after refreshing the
Court's replaced transcript PDF and regenerating preparation. The original
matcher passed with all 10,338 source words preserved and 416 ordered paragraph
times; annotation preparation resumed. The audio checksum was unchanged. The
unsuccessful matching candidate was retired and was not promoted. No further
image builds or resource/validation-limit changes were needed. See
`younge-repair-2026-11-03.json` for the source hashes and acoustic comparison.

Build, image, card-import and deployment references are recorded in
`release-2026-11-02.json`.
