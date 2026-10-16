# Statistics automation

The existing controller dispatches `scotus-statistics` when a shared alignment changes, daily for official opinion discovery, when a batch has more work, or when the owner sends an answer. It runs independently of video approvals. The dashboard Settings page shows progress, recent updates and questions.

## Data

The seed contains 748 existing cases, repaired from the checked-in SCDB snapshots and cached argument/docket data in an isolated directory. Canonical records, per-recording revisions, source documents and coding evidence live privately in the media bucket under `statistics/`. Immutable source objects use content hashes. The dashboard retains a compressed previous public dataset before publication.

The worker consumes the existing public paragraph/speaker exports at `/podcast/alignment/index.json`; no separate transcript copy or word timings are needed. A replacement recording revision replaces its statistics. Separate hearings are aggregated once each. Advocate speaking time and time at the lectern are separate fields. Old timing data that measured the lectern period is retained only under the latter name.

Publication atomically replaces `/data/flattened_records.json` and `/data/status.json` on the PHP host through a signed worker request. It does not overwrite website source or credentials. The browser uses the newest available term. Evidence, source pointers and private notes stay out of the public chart dataset.

## Opinions and Codex

The Court's current/recent slip-opinion listing rows are checked daily. Changed entries and recent cases lacking coding are queued. Docket JSON, opinion XML and PDF fallback supply relevant passages. Existing SCDB topics remain authoritative where present. Opinion word counts are deterministic where Court XML is available.

Codex CLI uses the existing Secret Manager subscription login and dashboard credential lease. Each case gets a fresh private data workspace, the supplied SCDB taxonomies and `statistics-opinions.md`. The worker handles at most four cases per execution, with a 180-second model timeout per case; the job has one CPU, 1 GiB and a 900-second timeout. Ambiguous decisions or failed checks become private dashboard questions; unrelated data can still publish. Answers are prioritized in the next batch. The structured result distinguishes judgment votes, full joins and partial opinion joins; it never infers the original opinion assigner.

Validation checks taxonomy membership, justice identities, vote counts, disjoint coalitions and evidence presence. These checks cannot establish that a model's interpretation is correct. Same-URL opinion edits that do not change the listing row may not be detected. Opinion discovery currently covers terms from 2024 onward; older records retain the repaired SCDB data. New argued cases enter through alignment exports, not a separate ongoing Oyez case crawler.

Before handing off, Codex must run `python input/check_statistics.py` with its complete draft JSON on stdin. The worker supplies this read-only helper, the exact shared `stats_core.py`, taxonomies and output schema. It exercises the same publication checks locally, including dates, so formatting and vote-list mistakes can be corrected within the existing session. The final pipeline repeats those inexpensive checks. Known failures caused by the earlier empty-Oyez adapter and unconstrained justice-name schema are retried once under the corrected coding revision, without inventing an owner response.

## Deployment

Build with `cloud/infra/build_image.py statistics --statistics-repo /path/to/scotusstats` and the normal control/build state arguments. This copies only the shared statistics core/tests and taxonomies from the sibling repository. `cloud/Dockerfile.statistics` avoids installing the renderer or alignment model. Deploy by digest to `scotus-statistics`.

The `scotus-statistics-config` secret contains `dashboard_url`, `dashboard_key`, `bucket`, `seed_uri`, `codex_secret`, `model` and `max_cases_per_run`. Configure the same private key as `worker_keys.stats` on the PHP host. Never put that configuration in Git. The job's environment needs `GOOGLE_CLOUD_PROJECT` and `SCOTUS_PRIVATE_CODEX_WORKER=1`. The controller supplies a per-execution `SCOTUS_STATS_TOKEN` override.

The statistics service account needs access to that configuration, the existing Codex secret and media objects. The controller service account needs `roles/run.jobsExecutorWithOverrides` on the statistics job. Add `statistics_job: scotus-statistics` to the controller configuration. Deploy the dashboard backend, including `statistics.php`, before enabling dispatch. Execution operations are recorded and reconciled so a startup crash cannot leave a permanent running status. The normal ten-minute controller schedule provides a fallback; successful batches and owner actions also request immediate dispatch.
