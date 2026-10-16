# Dashboard notifications

Install the dashboard on the iPhone Home Screen, sign in with the existing
passkey, then open Settings and choose Turn on notifications. On the Mac the
same button works in a supported browser or installed web app. Send a test from
Settings after registering each device. Tapping a notice opens its case screen;
case/card/photo/publication decisions remain behind passkey authentication.

The private VAPID key is in the control configuration in Secret Manager; the
public key is in the webhost's private config.php and returned to the signed-in
app. Existing keys and subscriptions must be preserved during redeployment.
Device endpoints and encryption keys never appear in public dashboard state.

Each notification tracks successful deliveries by device. A retry sends only
to devices that failed; expired endpoints are removed. Sends run in parallel
with short network timeouts. Worker wake-ups drain push notices through a
dedicated controller call after the creating transaction/HTTP reply, without
waiting for discovery/reconciliation. This also covers Spotify and recovery
question events, independent of the worker-operation wake-up whitelist. Scheduled dispatch
also drains the outbox as a fallback. The test button selects its own notice
and delivers synchronously, reporting acceptance instead of promising a
queued arrival. Missing
devices retain pending notices without consuming their retry allowance.
Recovery stops and daily-budget pauses generate actionable notices; obsolete
alerts are suppressed when their condition has cleared. Badge counts include
Spotify decisions and recovery attention alongside card/photo/publication work.

`ntfy_fallback_enabled` defaults to false and is disabled in this deployment.
Web Push is the delivery path; notifications never contain approval tokens.
The app shell is cached for poor connectivity, while API responses remain
network-only. Native iPhone notification permission and actual delivery must
be confirmed on the owner's device.
