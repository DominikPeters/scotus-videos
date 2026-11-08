# October Term 2025 local preparation pass

Open `index.html` for the review gallery. `manifest.json` is the machine-readable result; `inventory.json` preserves the initial coverage audit. Rebuild the gallery after adding candidates with `python3 build_gallery.py` (Pillow required).

Scope: the 31 recordings on the official Court OT25 audio index with calendar-2026 dates. Cross-checks: current Oyez term listing (62 cases) and Court audio listing, fetched October 15, 2026. Every identified recording has local Oyez case metadata; fresh copies are in `metadata/`, official Court JSON dockets in `dockets/`. Every fresh case has facts, questions presented, and advocates; 28 have decided-by data. A missing cached transcript is not the same as missing case metadata. The cache has 26 of 31 transcripts.

The portrait search targets advocates absent from the existing local image collection/catalog. Reused 43 existing portraits; original candidate images and individual provenance sidecars are in `originals/`. New portraits are **pending owner approval**. No source images were cropped, production portraits overwritten, catalogs changed, videos started, or assets committed/published. Original dimensions and Court argument identity evidence appear in the gallery. Identity evidence comes from the Court's argued entries and matching professional profiles, rather than matching names alone. John E. Roberts is the advocate in23-1209, not the Chief Justice.

Video coverage: no local encoded video file matched the identified docket/oyez IDs. This is only a local-file observation and does not establish YouTube/cloud publication status; no authenticated channel audit was performed in this pass.

Browser fallback: several firm/agency sites returned403 to requests but loaded in the owner's Chrome. Sidley's photo was downloaded through Chrome. A browser media-download call took an unexpectedly long time; remaining downloads use direct observed image URLs. Nelson's full WordPress original returned403;819 × 1024 derivative retained. Murphy's original served400 × 400, usable at portrait display size.

Full fetched dockets include public professional contact details; the gallery displays only argument identity evidence. Case metadata and originals remain local under this preparation folder. No changes were made to the sibling scotusstats data cache.

Current first-pass result: 13 new portrait candidates. Still unresolved: Emily M. Ferguson and Aaron Z. Roper. Kenneally’s official candidate is only 160 × 160 pixels and should be reviewed for quality. No synthetic substitute selected.

## Owner selection and square portraits

The owner approved the existing candidates and supplied replacement sources for Alan Beck and Michael Kenneally, plus a LinkedIn image for Emily Ferguson. Selected replacement bytes are retained in `replacements/`; prior source images remain in `originals/`. `approvals.json` ties each of the 14 selections to its source hash. Aaron Roper is the sole unresolved advocate.

All 14 selected images have square JPEGs in `square/`. Boxes in `crop-plan.json` were chosen after visual inspection; already square images retain their full frame. Outputs are at most 1024 pixels square and are never upscaled. Regenerate with `python prepare_portraits.py` then `python build_gallery.py`. This remains a local preparation bundle; production catalog/GitHub adoption is separate.
