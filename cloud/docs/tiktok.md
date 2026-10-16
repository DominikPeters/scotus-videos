# TikTok clip delivery

The dashboard offers Save TikTok draft and Publish on TikTok under rendered
clips. Publication requires confirmation. It uses our Chromium/Puppeteer clip
image, not a browser on the
operator's Mac. No third-party uploader package or browser stealth plugin is
installed.

The operator authorized storing the supplied session in Secret Manager as
`scotus-video-tiktok-session` in `possible-cycle-237715`. Only the existing
`scotus-video-upload` runtime identity was granted access. Cookie values are
never copied into images, job arguments, source files or browser console logs.
The initial secret contains session and routing cookies, not every advertising
or tracking cookie from the captured request.

`scotus_cloud.tiktok_pilot` downloads an explicitly supplied private GCS video,
reads the credential into a temporary file, and runs `render/tiktok-draft.cjs`.
The browser script uploads the file, fills the caption, clicks **Save draft**,
and verifies the caption on the drafts page. Production mode can instead
publish after checking that public visibility is selected. Existing drafts
are reopened for publication without uploading the video again.
Do not automatically rerun a failed/uncertain save without checking the drafts
list first. Task retries are disabled.

The pilot job is `scotus-video-tiktok-pilot` in `us-central1`, with 2 CPUs,
2 GiB RAM and a six-minute limit. Its environment names only source/output
URIs, caption and project, never credentials. A result JSON and screenshot are
saved privately under the job's `SCOTUS_TIKTOK_OUTPUT` prefix. Do not enable
network-header, cookie, browser-storage, HAR or console capture with this
session.

Local Chrome test: the 10-second Salazar example uploaded successfully and was
saved as a real TikTok Studio draft. Studio says web drafts are private,
accessible across computers, and expire after 60 days. This does not establish
that drafts appear in the mobile app.

Cloud test verified October 16, 2026: execution
`scotus-video-tiktok-pilot-pr66t` saved the caption “Cloud upload test: 10-second
excerpt from Salazar v. Paramount Global. Justice portraits: Oyez.org” and
verified it on the drafts page. Login, video transfer, draft creation, reopening
and caption editing all worked from Cloud Run without the operator's Chrome.
There are two sample drafts: the original local test and this cloud test.
Nothing was published.

Puppeteer's coordinate clicks raced Studio's animated scrolling. Explicitly
focusing the editable, clearing through native keyboard events, verifying the
field, and invoking the exact Save draft button fixed this. Caption entry is
checked before saving; the saved caption is checked again on the drafts page.

For recovery, `SCOTUS_TIKTOK_EDIT_DRAFT` names an existing draft to edit instead
of uploading again. Matching must be unique. The current pilot job is left in
that test-edit configuration; do not launch it blindly for a new clip. Give
each explicit run a new private output prefix. There is no scheduler attached.

The supplied session worked from a data-center IP, but future sessions or
network conditions may differ. Challenges must be surfaced to the operator,
not solved or bypassed by the worker. Expired sessions require replacing the
secret. There is no scheduled uploading or automatic session refresh.


## Production worker

`scotus-video-tiktok` uses the existing upload service account and config with
2 CPUs, 2 GiB RAM, a ten-minute limit and zero automatic retries. Deploy with
`infra/deploy_tiktok.py`, supplying pinned TikTok and controller images. It
starts no transfers. The controller dispatches explicit clip actions
immediately; the periodic dispatcher also reconciles queued/running work.

Production transfer state lives in each clip's `tiktok` field, separately from
its rendered MP4 and YouTube upload. Before Save draft or Post, the browser
waits for an acknowledged durable checkpoint through the PHP state lock. A
retry after an uncertain action only reads the appropriate Studio list; it
does not upload or post again. A global TikTok credential lease serializes
transfers to this account and is renewed with the clip heartbeat. Completion
and failures use the existing immediate dashboard push notifications.

The existing successful cloud test draft is linked to the original 10-second
Salazar clip. Production publication is enabled, but no TikTok video was
published during implementation. Publish confirmation, queue transitions,
duplicate guards, media preservation and uncertain-operation reconciliation
are tested; the live public-post action has not yet been exercised.
