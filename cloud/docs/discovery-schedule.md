# Discovery schedule

The Cloud Scheduler controller tick runs every ten minutes. Worker callbacks and dashboard actions continue to trigger immediate controller requests.

Court discovery normally runs once per thirty-minute clock interval, including current-term backfill. It reads the Court's monthly argument calendars once per Washington calendar date and caches the scheduled docket groups in dashboard state. Current, previous and next month's calendars cover sessions spanning month boundaries. Holidays and months without published argument sessions do not enable faster polling.

On a scheduled argument day, from 13:00 through the 18:00 check in `America/New_York`, discovery runs every ten minutes while any scheduled argument lacks both audio and PDF links. Consolidated dockets count as one argument; discovering a recording under any docket in that group satisfies it. Once all groups are discovered, it returns to normal backfill polling. Daylight-saving changes are handled by the timezone database.

A PHP transaction rate-limits both timer and callback requests by clock interval, preventing repeated scans during frequent worker callbacks. Known recording detail pages are skipped. Pausing automatic work pauses discovery. If calendar parsing or retrieval fails, normal discovery continues and a private dashboard event records the problem; the calendar is retried after an hour.
