# Manual Spotify video delivery

Automatic transfers are disabled. Completed YouTube recordings have a **Transfer to Spotify** control in the dashboard's Recordings table. This queues a separate delivery task; it does not change the YouTube pipeline or its publication state.

The small private Spotify service finds the existing RSS episode by docket, argument date and audio duration. When Spotify has not indexed the episode yet, the controller checks again every five minutes without keeping a transfer worker alive. An ambiguous match stops for review, with an optional episode ID override that still checks the show, docket and duration.

The transfer job streams the assembled MP4 directly from its pinned Cloud Storage generation to Spotify. It does not download media to the owner's computer, re-encode audio/video or alter podcast metadata. An upload ID is saved before transmitting media; retries reconcile that identity and resume an incomplete transfer rather than create another upload. Existing episodes with video are left alone.

After uploading, the owner must click **Publish on Spotify** and confirm replacement of the audio-only Spotify player. The RSS podcast remains unchanged. The service checks Spotify's processing status, reports errors privately and sends dashboard notifications. A failed publication can be retried using the saved upload. There are no automatic transfers or publications after YouTube uploads.

## Credentials

Spotify credentials live in `scotus-spotify-auth` in Secret Manager. Routine authentication uses a renewable refresh token. The dashboard's Spotify reconnect form accepts `sp_dc` and `sp_key` cookies from a signed-in browser session; they are exchanged for a refresh token and removed from the saved credential once exchanged. Credentials never enter model prompts, dashboard state, logs or build contexts. Renewals disable older secret versions so active versions do not accumulate.

The `scotus-spotify-delivery` account can read the private video bucket and its own configuration/credential secrets, rotate its credential and launch only `scotus-spotify-transfer`. The private service accepts Cloud Run IAM-authenticated calls from the controller. PHP independently fences owner requests, worker generations and leases. No new public-facing wording is generated.

Deploy with `cloud/infra/deploy_spotify.py` (setup, build, deploy), deploy the updated controller with `deploy_control.py`, and publish PHP/JS source with `deploy_dashboard.py`. These commands do not run transfers. The private config explicitly stores `spotify.automatic=false`; the dispatcher only processes manual requests. The unofficial Spotify endpoints may change and are isolated from the video workflow.
