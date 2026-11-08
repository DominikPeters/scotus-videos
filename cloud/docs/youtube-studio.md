# Native related-video links for Shorts

The official OAuth API still uploads clips. Once a video ID is saved and channel
ownership is confirmed, the worker sets the Short's native Related video field
to the recording's full YouTube argument and independently reads it back.
Studio is accessed directly over HTTPS; no local Chrome or cloud browser is
needed for the tested requests. These private endpoints can change.

The owner-supplied Studio cURL revealed `videoLinkageShortsAttribution` and
`targetExternalVideoId`. Reads use `creator/get_creator_videos`; the narrow
`video_manager/metadata_update` request changes only the related-video field.
Both videos must belong to the configured channel. An already matching link
requires no write, and retries always read current state first. No publication,
title, description or other metadata is changed by this adapter.

`scotus-video-youtube-studio-session` stores cookies, client version and channel
delegation context. The importer reads the explicitly supplied cURL as data
(with shlex, never executes it) and writes directly to Secret Manager. It does
not retain the cURL, cookie values, captured Authorization hashes or attestation
responses in repository files. The upload service account gets read access to
this one secret. Per-request cookie authorization hashes use a fresh timestamp.
Cookie renewal can be imported with `cloud/infra/import_youtube_studio.py`.
The regeneration scheme is also used by the yt-dlp project:
https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_base.py

Upload callbacks record `related_video_id` and `related_video_verified`. If the
Studio session expires or the request fails, the completed upload stays intact;
its dashboard entry shows the error and offers “Link full argument”. This queues
a `youtube_link` task that changes metadata only and downloads no video. Normal
upload retries also skip downloading the MP4 once its YouTube video ID exists.
Cookie values, auth headers and raw Studio responses never go to logs or the UI.

Deploy pinned worker/controller images with `deploy_youtube_studio.py`, after
importing the session. It enables `youtube_studio_secret` in the existing upload
configuration and starts no media work. Reconnect the Studio session when it
expires; the OAuth upload credential remains separate and unchanged.

Validation on October 16: direct local reads and a metadata update succeeded
without captured attestation. During the Cloud Run test, the stored session
returned HTTP 401; a subsequent local read also returned 401, and a cloud
browser redirected to Google sign-in. A fresh owner session and an authentication-adapter check are required before
cloud authentication can be considered verified. Uploads remain successful and
the separate linking result reports that the session needs attention.


## Session investigation (October 16)

A fresh reload in the owner's local Chrome still opens the signed-in channel's
Studio page. Thus a failed exported credential is not evidence that the browser
session itself expired.

The supplied read and write cURLs both use authorization values with the `_u`
suffix. The current adapter instead builds the simpler two-component signature
and imports no user-session ID. yt-dlp's implementation documents the `_u`
variant: include the user-session ID before the timestamp in the hash input,
and append `_u` to the resulting timestamp/hash pair. Merely appending a suffix
is incorrect. This discrepancy must be resolved before attributing all HTTP 401s
to cookie expiry. It is not yet proven to be the cause: the earlier direct
request succeeded, and the exported cookies may also have rotated.

The adapter currently retains response cookie updates only inside one execution,
not in Secret Manager for subsequent jobs. Its rotation handling also accepts
only names already present and does not model cookie expiry/removal. This is not
a complete persistent cookie jar. The timestamped authorization hash alone does
not renew a Google login.

Recommended progression:

1. Correct and verify the browser-compatible authorization/bootstrap information
   using a fresh, isolated session, initially with read-only requests.
2. Export from a dedicated session, separate from the owner's daily Chrome
   session. yt-dlp recommends an incognito export followed by closing that
   session, to prevent open tabs from rotating the exported cookies. Its advice
   concerns YouTube downloading; Studio lifetime still needs measurement.
3. Keep a domain/path-aware cookie jar and atomically persist valid rotations,
   expiry/removal and bootstrap changes under the existing credential lease.
   This requires an explicitly scoped write path, not broad secret permissions.
4. Verify across separate worker executions and over time before declaring the
   session reliable. Stop and request reconnection on sign-in challenges.
5. If HTTP-only renewal remains unreliable, use a dedicated persistent browser
   profile on a small cloud VM, with one interactive sign-in and occasional
   reauthentication. This avoids dependence on the owner's Mac. It does not
   guarantee permanent access or bypass Google sign-in challenges.

A local Chrome bridge is a workable fallback while the Mac is awake, but does
not meet the independent-cloud requirement. Normal OAuth uploads remain separate;
linking failures must continue to preserve the uploaded video.

Sources:
- https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies
- https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube/_base.py


### Follow-up read-only test

A fresh request was captured through local Chrome DevTools, without printing its
credentials. Exact captured authorization, regenerated simple authorization, and
regenerated user-session-aware (`_u`) authorization all returned HTTP 200 locally
for `creator/get_creator_videos`. A Studio bootstrap GET also returned 200 and
provided the user-session ID. Therefore omission of `_u` did not explain the
observed local failure with the old export. The old export independently
redirected a Studio page GET to Google sign-in.

The fresh credential was saved to the existing Secret Manager secret. A separate
local process using the production adapter read back the existing full-video
link successfully. The first Cloud Run execution using that same fresh
credential returned HTTP 403, rather than the old HTTP 401. Signature comparison
from Cloud Run and the alternative-host test are recorded in the local test
artifacts. The credential still shares the owner's daily Chrome session; this is
not a dedicated-session lifetime test.


The second independent Cloud Run execution also returned 403. A third execution
then succeeded with both the simple and user-session-aware signature. Thus the
cloud failure is intermittent, not demonstrated to be a permanent network block
or fixed by `_u`. The existing web host independently returned 200 twice using
the same fresh credential, without persisting credentials there. No video
metadata was changed by these tests. This is evidence for a possible fallback,
not proof of a long-lived session or of permanent web-host reliability.


The fourth cloud execution returned 403 with the simple signature and 401 with
`_u`. Immediate local and web-host rechecks both then returned 401 too. The
fresh daily-Chrome export therefore stopped working across all tested hosts
within this test run. A persistent web-host route alone does not fix renewal.
Browser cookie rotation is consistent with the observations but not conclusively
proven. A separate incognito sign-in, exported and then closed, is the next
controlled test; it requires the owner to complete sign-in. All requests in this
run were reads. The temporary Cloud Run diagnostic job was removed. No
production authentication logic or video metadata was changed.


### Response-cookie audit

Instrumented requests recorded cookie names, scope, expiry and equality/change
flags only. Values and response bodies were not logged. With the expired saved
export, two API 401 responses and the Studio-page 302 supplied no Set-Cookie
headers. With a fresh Chrome export, two successful API reads also supplied no
Set-Cookie headers. A successful Studio-page GET supplied six Set-Cookie headers;
the parsed jar showed new values for SIDCC, __Secure-1PSIDCC and
__Secure-3PSIDCC, while the two visitor-cookie values remained unchanged.
The prior diagnostic GET did discard these refreshed session-control values.

Both the original export and the page-updated cookie set subsequently succeeded
in read-only API calls, including a separate local process. Thus response-cookie
loss is a demonstrated gap in the page-load diagnostics, but this comparison did
not prove it caused the rapid invalidation. No lifetime improvement is established.
The production adapter performs no page-bootstrap GET and has no persistent jar;
its successful API responses in this audit offered no renewal cookies at all.
No production changes were deployed from this audit.


### Reference-client trial

Inspected sstani-bgv/yt-studio at commit
`00ae1ee951c7241df50d23bcc7bcb1fe07948a99` in an isolated temporary environment.
All 84 offline pytest tests passed. Its actual `fetch_studio_bootstrap` also
rejected our saved export as redirected to login/account selection. This library
cannot renew an already invalid login from cookies alone. Its complete direct
transport additionally expects a separately captured security token.

The client's native `auth-open` prepared a dedicated Chrome profile at
`/private/tmp/scotus-yt-studio-profile`, outside both repositories and the owner's
normal Chrome profile. The owner must sign in to the SCOTUS channel and close
that separate window before capture. No video mutations or production changes
were made. Test setup and credential-free results are under
`artifacts/output/youtube-reference-test/`. The checkout and profile are temporary
trial resources; durable cloud setup is not yet implemented.


### Dedicated-session trial (October 17)

After the owner signed into the separate profile, the reference client's
`auth-capture` verified channel UCuXmeHbNM_2q_z2jPZH6GCA. Its `security-capture`
also succeeded using the normal Studio flow. Two independent local processes
then used its actual DirectStudioTransport, including fresh bootstrap,
channel guard, locked persistent cookie jar and captured security token. Both
returned HTTP 200 and read back the existing pet-snail Short's related-video ID
RVlud1nKiXY. No metadata was modified. This establishes immediate cross-process
reuse locally, not long-term lifetime or cloud portability. The dedicated
credentials remain only in the private temporary profile; production secrets
and workers were not updated by this trial.

Repeat the read-only test without reopening the profile with:
`/tmp/scotus-yt-studio-venv/bin/python artifacts/output/youtube-reference-test/read-session.py`.
A missing/expired separate security token may need `security-capture` again;
that does not by itself mean the Google login expired. The profile is under
/private/tmp and needs a deliberate durable location before production use.


### Cloud portability and renewal trial (October 17)

With explicit owner authorization, the dedicated session was copied to a separate
private test secret, accessible only by the existing upload worker identity and
existing project administrators. Temporary Cloud Run jobs ran the inspected
reference transport. Two independent executions returned HTTP 200, verified the
channel, and read the existing related-video link. A headless cloud Chromium
probe did not confirm authentication or obtain a new ars/grst security token.
The final cloud probe redirected to accounts.google.com; an immediate local
reference-client recheck also redirected to login/account selection.

This was not a complete single-owner persistent-session deployment: each cloud
execution started from the original secret snapshot, and cloud jar updates were
not saved back across jobs. Local and cloud copies also used the same login.
Thus immediate portability is established, unattended renewal is not, and the
cause of subsequent invalidation remains unresolved. Do not conclude either
that the library solved renewal or that it caused invalidation. A dedicated
persistent cloud browser with one authoritative profile is the next controlled
architecture to test. No videos were edited and no production worker changed.
The test job, test-secret access grant, secret and uploaded code bundles are
removed after the test. Local credential-free results are in
artifacts/output/youtube-reference-test/cloud-results.json.


### Persistent cloud browser trial

**Current status (November 1, 2026):** the owner approved permanent removal of
this unused experiment. The stopped `scotus-studio-browser` VM and its attached
20 GB balanced boot disk have been deleted. The connection instructions below
are historical; no persistent cloud browser is currently deployed. The startup
script remains available if a future experiment is explicitly requested.

The owner requested a dedicated cloud-resident profile. VM `scotus-studio-browser`
in `us-central1-a` uses Debian 12, e2-medium and a 20 GB persistent boot disk.
It has no attached service account or cloud API scopes. The `scotus-studio-browser`
network tag permits only IAP SSH at priority 800, then denies other ingress at
priority 900, overriding the default network's broad SSH/RDP/internal rules.
Desktop services bind to loopback. Setup is in `cloud/infra/studio_browser_startup.sh`.
The browser profile is `/var/lib/studio/profile`, owned by the dedicated `studio`
Unix user with mode 0700. User sign-in is performed directly in the cloud browser.
No prior local session was copied to it. Production Studio linking is unchanged.

To reconnect the owner's desktop, keep this tunnel running:
`gcloud compute ssh scotus-studio-browser --zone=us-central1-a --tunnel-through-iap --project=possible-cycle-237715 -- -N -L 127.0.0.1:8769:127.0.0.1:6080 -o ExitOnForwardFailure=yes -o ServerAliveInterval=30`
Then open `http://127.0.0.1:8769/vnc.html?autoconnect=1&resize=scale`.
The loopback web/VNC service uses the authenticated SSH/IAP connection as its
access boundary; do not expose ports 5900 or 6080 publicly. Stop the VM when the
trial is finished if it is not serving ongoing work; its disk retains the profile.


The owner raised concern about entering a primary Google password into the remote
desktop. The trial VM was stopped and sign-in testing was put on hold. The noVNC page is
a view into a VM, not a Google-origin page verifiable by the local browser/password
manager. A dedicated Google identity limited to the YouTube channel is a possible
alternative; no channel invitations or account grants have been made. The VM and disk have since been permanently removed, as recorded above.
Production Studio linking remains on the earlier adapter.
