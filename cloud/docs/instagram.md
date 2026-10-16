# Instagram connection

The Meta app is `SCOTUS uploader` (2192213732176883); its Instagram client is
`SCOTUS uploader-IG` (2748057315624132). These are different IDs. Use the
Instagram client ID and secret for Instagram Login.

The app is published. Meta's Instagram App Review documentation says Standard
Access for the operator's own account does not require App Review:
https://developers.facebook.com/documentation/instagram-platform/app-review
Its Business Login documentation also requires those accounts to have been
added in the App Dashboard. Publishing alone does not establish that association.

The dashboard's Settings → Connections → Instagram starts authorization with
only `instagram_business_basic` and `instagram_business_content_publish`.
Register this exact redirect URI in the Instagram business-login settings:

    https://scotusstats.com/youtube/instagram-callback.php

The callback checks a single-use state and a separate SameSite=Lax browser
cookie. The dashboard's main authenticated session keeps its normal policy.
The controller is designed to exchange the code, obtain a long-lived token, check the
granted scopes and verifies the account is `scotus.oral.arguments` before
saving the token. A personal account cannot replace the intended account.
Tokens and app secrets are never returned to the browser by the controller.

Secret Manager configuration keys:

- `instagram_client`: `scotus-video-instagram-client`; controller can read and
  write this credential for the code exchange.
- `instagram`: `scotus-video-instagram`; controller can add versions and read
  version metadata. Saved JSON contains `access_token`, `user_id`, `username`,
  `scopes`, and `expires_at`.

The privacy page is public at https://scotusstats.com/youtube/privacy.html.
Bounded callback diagnostics in private `connection-diagnostics.json` record
only the failing step and an allowlisted reason, with no authorization data.

This adds account connection only. It does not publish clips, schedule posts,
or automatically refresh tokens. Reconnect through Settings when needed;
Meta's long-lived tokens normally last about 60 days. Future Reels publishing
also needs an export at a supported frame rate; the current clip renderer
produces 20 fps, below Meta's documented 23–60 fps range.

## Verified connection (October 16, 2026)

After the operator added `scotus.oral.arguments` as an Instagram Tester, the
normal dashboard OAuth flow succeeded: long-token conversion, account identity
and permissions checks passed, and the credential was saved in Secret Manager.
Before that association, authorization and short-token exchange succeeded but
Graph requests failed with error 100, “Unsupported request - method type: get”.
Publishing the app alone was insufficient for this account.

The temporary `instagram_pending` diagnostic configuration has been removed;
its saved short-token versions are disabled. No Instagram posts were published.

## Manual publishing test (October 16, 2026)

With separate operator authorization, a 10-second Salazar excerpt was converted
from 20 to 30 fps (H.264, 1080×1920, AAC 48 kHz) and published successfully:
https://www.instagram.com/reel/DejJhnIAGuO/
The API container reached `FINISHED` before `media_publish`; the returned media
ID is `17887527897685960`. This was a one-off test, not an enabled automatic
Instagram uploader. The receipt is in generated output under
`artifacts/vertical-cloud-test/instagram-upload.json`.

Instagram Login rejected `upload_type=resumable` without `video_url`. A
one-hour Cloud Storage URL worked. The operator's local Google identity lacks
signing permission; a temporary Cloud Run task signed with the existing
controller service account instead, with no IAM changes. Future integration
should sign URLs in the controller, as clip downloads already do.

Unpublished API containers are not native Instagram drafts. Do not describe
container creation as saving an editable draft in the Instagram app.
