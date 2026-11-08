# Registry retention

Artifact Registry keeps one newest version per image package. Unprotected older
versions are eligible for deletion after 24 hours; Google's cleanup runs in the
background approximately daily. An initial cleanup removed existing superseded
builds and the unused standalone `render` image.

Deployed Cloud Run jobs, service revisions receiving traffic (including tagged
revisions), and running executions are protected by digest prefix. The current
repair baseline uses the deployed pipeline image and is included in this set.
Additional baseline images can be retained with `--protect IMAGE@sha256:DIGEST`.

All image deployment scripts, including clips, Instagram, TikTok, Spotify and
the three-group credential migration, refresh protections before and after
deployment. Replacement images are protected before cutover. Failed image imports
are terminal executions even when Cloud Run omits their completion timestamp. For custom deployments, run:

```
python3 cloud/infra/registry_cleanup.py --project possible-cycle-237715 --apply
```

Before deploying a different image, pass it with `--protect` to protect it during
deployment. Run again after deployment to drop obsolete protections. Retained
baseline images outside live job definitions must be passed on every refresh.
Without `--apply`, this command prints the proposed policy without changing it.
No image layers or media are downloaded locally.

Build source archives and logs in the dedicated control-build bucket expire after
30 days. This rule does not apply to the media bucket. Despite its name, `scratch/`
also contains finished videos and current plan/audio artifacts used by clips,
reviews and Spotify. Do not apply an age-based deletion rule to that prefix.
An audited cleanup must preserve current dashboard artifact references.

Pipeline images that approach Docker's layer limit can be flattened with
`build_image.py pipeline --base-image IMAGE@sha256:DIGEST --flatten-base ...`.
This copies the installed filesystem into a fresh stage without downloading models
or reinstalling dependencies. Prefer a stable dependency base over repeatedly
stacking source refreshes on the last application image.
