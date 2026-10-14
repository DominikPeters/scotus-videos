# Registry retention

Artifact Registry keeps one newest version per image package. Unprotected older
versions are eligible for deletion after 24 hours; Google's cleanup runs in the
background approximately daily. An initial cleanup removed existing superseded
builds and the unused standalone `render` image.

Deployed Cloud Run jobs, service revisions receiving traffic (including tagged
revisions), and running executions are protected by digest prefix. The current
repair baseline uses the deployed pipeline image and is included in this set.
Additional baseline images can be retained with `--protect IMAGE@sha256:DIGEST`.

The worker, controller, YouTube actions, and sign-in deployment scripts refresh
protections before and after deployment. For custom deployments, run:

```
python3 cloud/infra/registry_cleanup.py --project possible-cycle-237715 --apply
```

Before deploying a different image, pass it with `--protect` to protect it during
deployment. Run again after deployment to drop obsolete protections. Retained
baseline images outside live job definitions must be passed on every refresh.
Without `--apply`, this command prints the proposed policy without changing it.
No image layers or media are downloaded locally.
