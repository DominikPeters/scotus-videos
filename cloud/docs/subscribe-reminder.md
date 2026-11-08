# Subscribe reminder

The landscape video planner schedules the reminder once, at or after 10:00, in the
first interval with at least 15 seconds free of annotation cards. A gap already
open at 10:00 qualifies if at least 15 seconds remain. Without a qualifying gap,
the reminder is omitted.

The planner records actual card visibility during presentation replay, including
entry, exit and replacement transitions. It therefore schedules against the
selected cards as rendered, rather than only their nominal cue ranges. The
reminder lasts eight seconds including its 0.4-second entry and exit fades.
Explicit 20-fps operations make it independent of wall-clock browser animation
and allow a separate render chunk to reconstruct it midway through the reminder.

The presentation uses the cream pill, text and filled like/bell icons from
Claude's latest local animation mockup. Section changes no longer show a separate
subscribe overlay. Vertical clips do not schedule a reminder. The card workbench
uses the current approved presentation when regenerating local previews.

## Verification and rollout

The local Maxwell plan using Claude's 26 recommended cards schedules the reminder
at **10:00–10:08**. Local checks covered six captured states, no card overlap,
sidebar bounds, identical reminder pixels in independent replay, gap/skip edge
cases and continuous frame coverage. The original presentation replay also passed.
The Python suite passed 284 tests (three skipped).

These changes were deployed in the owner-approved combined control/pipeline batch
on 2 November 2026. Claude's revised 26 recommended Maxwell cards were uploaded
and selected, preserving existing portrait approvals. The first production plan
also schedules the reminder at **10:00–10:08**, with 76,921 frames in 13 chunks.
The isolated deployment
suite passed 286 tests (4 skipped). See `release-2026-11-02.json` for immutable
build and image references. Future clips/TikTok image builds include the new shared
helper; those images need no rebuild solely to introduce the landscape reminder.

Review images and validation metadata are in
`artifacts/subscribe-reminder-2026-11-02/`.
