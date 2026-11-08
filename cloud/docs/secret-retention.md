# Secret groups and version lifecycle

Status: deployed and verified on **2026-11-02**. Three services and 21 jobs use
the new images. The 26 legacy secret objects were permanently deleted after
consumer checks; only the three groups remain, each with one current version.
The earlier one-time cleanup destroyed 118 superseded versions. See the
[deployment audit](cost-cleanup-2026-11-02.json) for pinned images and build receipts.

## Layout

| Physical secret | Logical contents | Access |
| --- | --- | --- |
| `scotus-internal` | Controller and individual runtime configurations, internal authentication keys | Trusted controller; workers receive only their assigned configuration |
| `scotus-research` | Codex authentication and research browser sessions | Research/sign-in workers and trusted controller |
| `scotus-publishing` | YouTube, Spotify, Instagram, TikTok and GitHub account credentials and OAuth clients | Publishing services and trusted controller |

Existing logical names such as `scotus-video-youtube` remain application field
names inside these bundles. They no longer represent individual physical secrets
after migration. Each bundle has schema version 1 and named entries containing
base64-encoded credential bytes and a per-entry update timestamp.

The controller is trusted to manage all groups. Workers authenticate to
`/v1/runtime-config` using a Google ID token for the controller audience. The
controller checks the verified email against an explicit configuration allowlist;
a worker cannot request another worker's configuration or controller keys. No
worker receives the entire internal bundle. Configuration payloads are never
embedded in images, environment variables, command arguments, or logs.

The Instagram clip job moves from the controller account to the upload account.
It signs its own private media URLs with that publishing identity. Research
workers do not receive publishing credentials. Ordinary media processing workers
receive their scoped configuration and no external-account bundle access.

Three current versions fit within Secret Manager's six-version monthly storage
allowance. Access operations and Cloud Storage operations retain their separate
allowances. The bundle contents must each fit Secret Manager's 64 KiB limit.

## Replacement

All runtime writers use `SecretStore` through `Google.add_secret_version`.
Deployment/import scripts use `managed_secrets.run_gcloud`, which automatically
recognizes the migrated layout and routes logical reads/writes to those same
bundles. Existing deployment commands remain usable; deployment helpers register
worker configuration readers and replace old config mounts with nonsecret
bootstrap references. New deployment scripts must use this helper too.

1. Acquire an exclusive lock for the affected group in the existing private media
   bucket, using `ifGenerationMatch=0`.
2. Read the current bundle while holding that lock. Preserve all unrelated entries.
3. Compare canonical JSON bytes. An unchanged value creates no version.
4. Create a replacement only when needed, then read it back by numeric version
   and compare its complete payload.
5. Activate the verified numeric version through a generation-guarded Cloud
   Storage pointer, then read it through that pointer before retiring its
   predecessor. Failed verification leaves the working pointer unchanged and
   removes the uncommitted candidate when possible.
6. Destroy superseded enabled **and disabled** versions. Keep no rollback history
   or age window. Remove temporary state when it has served its purpose.
7. Release only this writer's lock generation.

The version-number pointer contains **no credential data**. Numeric Secret
Manager access and private Cloud Storage object reads are strongly consistent;
Secret Manager's `latest` and version aliases are not. Readers reload the pointer
if a concurrent replacement retired the version they just selected. This allows
immediate retirement without a fixed grace period or a second usable version.
See [Secret Manager consistency](https://docs.cloud.google.com/secret-manager/docs/reference/consistency)
and [Cloud Storage preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions).

Locks deliberately do not expire automatically. A killed writer can leave a lock
behind; writes then fail closed while reads keep using the committed version.
Inspect the recorded job/time, current pointer and staged versions, ensure no
writer remains active, reconcile uncommitted versions, and remove only the
observed lock generation before retrying. Do not apply an automatic TTL or a
scheduled cleanup task: a stale writer must never overwrite a newer refresh.
Normal completion handles version retirement at write time. A failed retirement
is surfaced; the next write, including an unchanged-value write, retries pruning.

The unused Instagram short-lived-token staging write has been removed; it is
never consumed by the application. Existing per-provider authentication leases
remain in place, in addition to the per-group lock. This prevents both competing
refreshes of one provider and lost updates between different providers.

## Deployment batch and migration

Finish the entire cost-saving batch and local checks first. Build each affected
image package once, using the default machine type and existing pinned dependency
bases when appropriate. Multiple job/revision source digests can map to one new
image per package. No build command is run by the migration tool.

`python3 cloud/infra/migrate_secrets.py --project possible-cycle-237715` produces a
metadata-only plan: resource identities, logical entries, and image digests. It
reads no credential payloads and changes no resources by default. Planning also
recognizes duplicate historical volume definitions for the same configuration.

For an installation that still uses the legacy layout:

1. Prepare a JSON image map from each old pinned image digest in the plan to its
   already-built replacement digest. Replacements must be new, immutable images
   in this project's Artifact Registry.
2. Pause processing in the dashboard and wait for all Cloud Run executions and
   credential writers to finish. Temporarily remove public invocation on the
   controller, confirm unauthenticated requests are rejected, and drain existing
   HTTP requests. Keep it quiesced through migration. Tagged service revisions
   require explicit reconciliation first.
3. Run `migrate_secrets.py --project PROJECT --image-map IMAGE_MAP --state STATE
   --workflow-baseline BASELINE_JSON --quiesced --apply`. The state file is private and atomically updated; it
   contains metadata, not credentials. The tool reads legacy credentials into
   memory, constructs and verifies three bundles, assigns group permissions and
   per-object storage access, activates the exact new pipeline source baseline, deploys the broker first, and updates the remaining
   jobs/services to their pinned replacement images. Both obsolete mounts and
   unused secret-volume definitions are removed; unmounting alone leaves stale
   volume definitions in Cloud Run. IAM propagation may require
   waiting before startup probes succeed. Interrupted deployment can be resumed
   with `--state STATE --workflow-baseline BASELINE_JSON --quiesced --resume --apply`; existing committed bundles
   are validated and never overwritten with stale legacy values.
4. Exercise the controller credential-status endpoint and each service's safe
   readiness probe. Run each configured job once with execution override
   `SCOTUS_CREDENTIAL_PROBE=1`. Its configuration loader exits before any media
   claim, AI turn, sign-in, upload or publication. The probe checks assigned group
   reads, unchanged-value writes for writer groups, and denied reads of other
   groups. It prints only group/configuration names and the zero-new-version
   result. The isolated recovery-test job has no config or account credentials;
   verify it separately using its existing isolated test path. Inspect failures
   without printing payloads; verify all three bundles retain one enabled version.
5. After explicit verification of every deployed consumer, retire the exact
   remaining legacy-secret scope using `--state STATE --retire-legacy --verified
   --apply`. This is permanent. The tool rejects changed resource scope, old
   runtime mounts, old images, active executions, or old revisions still receiving
   traffic. Restore the saved public controller invocation policy and the owner's
   previous processing state after readiness and credential checks succeed.

Configuration writes supply the nonsecret project identifier when absent and
reject a different project. This keeps every runtime configuration compatible with
the shared credential probe, including statistics.

The CLI helper's layout detection also fails closed on an unexpected permission
error rather than silently creating old per-stage secrets. IAM writer permissions
are scoped to one credential group; storage write permissions are scoped to that
group's pointer and lock, not the whole bucket.

## Local verification

Run `PYTHONPATH=cloud python3 -m unittest discover -s cloud/tests -p 'test_*.py'`.
Tests cover concurrent account updates, failed activation/read-back, disabled
version retirement, conditional locking, read-versus-retire races, configuration
isolation, logical deployment operations, and migration preconditions. Curated
build-context imports and source-size caps can be checked locally without
submitting a cloud build. The isolated source snapshot includes CommonJS/ES module
helpers. Recovery tests copy immutable deployment helpers from the image into their
temporary test directory; those helpers remain outside the editable workflow
boundary. Workflow-baseline reads are bounded to 2 MiB.

## Deployed verification

All 20 configured jobs passed real credential access, unchanged-write and negative
access checks. Their log markers confirmed zero versions created by unchanged
writes. The isolated recovery suite ran 277 tests successfully (four skipped),
including an exact deployed-image/baseline comparison and denial of credential
access to the isolated test identity. All three services passed post-retirement
checks, including Spotify authentication. Final metadata checks found three secret
objects, one usable version per group, no legacy runtime references and no leftover
credential writer locks at verification. Public controller access, automatic
processing and the timer were restored to their previous settings.

The batch used 12 build submissions for nine image packages: one pipeline attempt
failed at Docker's layer-depth limit, a flattened dependency image was reused for
the final pipeline source, and the controller was rebuilt for the baseline read
limit. The final pipeline has five layers rather than 124. All submissions used
the default build machine. Deployment-tool and configuration corrections required
no further runtime builds.
