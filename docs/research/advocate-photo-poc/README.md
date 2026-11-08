# Advocate photo proof of concept

Initial research on **October 11, 2026**, followed by retrieval of the larger Jones Day portrait on **October 12**, before the scheduled argument. Result: a verified, usable photograph of **Anthony J. Dick**, who did not have a matching photo filename in the repository's `advocates/` directory. The images remain research artifacts; they have not been installed in the production cache.

![Anthony J. Dick professional portrait from Jones Day](/Users/dominik/GitHub/scotus-videos/docs/research/advocate-photo-poc/anthony_j_dick.jonesday.webp)

## Identity and upcoming argument

The Court's [October 2026 hearing list](https://www.supremecourt.gov/oral_arguments/hearinglists/HearingList-October2026.pdf), page 3, lists Dick as Court-appointed amicus in **Beaird v. United States, 25-5343**, scheduled for **October 13, 2026**. It also lists Kevin Joel Page for petitioner and Eric J. Feigin for respondent. This is direct pre-argument evidence of who is scheduled to argue.

The [docket JSON](https://www.supremecourt.gov/RSS/Cases/JSON/25-5343.json), in the `Other` array, identifies Anthony J. Dick, Jones Day, Washington, D.C., with the professional email `ajdick@jonesday.com` and the party Court-appointed amicus curiae. The docket's May 6 order separately records his invitation to brief and argue the case.

His [official Jones Day biography](https://www.jonesday.com/en/lawyers/d/anthony-dick) identifies him as a Washington partner and provides the same professional email. The page explicitly attaches an image labelled `ajdick` to his biography. His [Federalist Society speaker biography](https://fedsoc.org/bio/anthony-dick) names Anthony J. Dick, Partner, Jones Day, and attaches the selected portrait to that named profile. These textual associations establish identity; no face recognition was used.

## Downloaded photo

- **Larger firm portrait, retrieved on follow-up:** [Jones Day image URL](https://www.jonesday.com/-/media/images/attorneys/d/ajdick.jpg?rev=91e306a9f7e24734816f42c1f2f61d43&hash=712BA20DA50AF264EF4EEF7124C3EEC2). Saved as `anthony_j_dick.jonesday.webp`: **1068 × 728 pixels**, 89,880 bytes. The URL ends in `.jpg`, but Chrome received WebP and correctly offered that file extension. The original received bytes were preserved. This is the recommended source for the eventual advocate avatar; its landscape composition allows a square crop when installed.
- **Original public file:** [Federalist Society source JPEG](https://fedsoc-cms-public.s3.amazonaws.com/headshots/vyBF1B0kYaN4O1vOkZ8TyeCDAAvxjnMc9ar4vFyc.jpeg), embedded in the speaker biography's image URL. Saved as `anthony_j_dick.source.jpg`: **330 × 330 pixels**, 29,255 bytes.
- **Displayed derivative:** [the biography's 320-pixel CDN image](https://fedsoc.org/cdn-cgi/image/fit%3Dscale-down%2Cwidth%3D320%2Cformat%3Djpeg/https%3A//fedsoc-cms-public.s3.amazonaws.com/headshots/vyBF1B0kYaN4O1vOkZ8TyeCDAAvxjnMc9ar4vFyc.jpeg). Saved as `anthony_j_dick.cdn-320.jpg`: **320 × 320 pixels**, 14,336 bytes.
- All three files were downloaded successfully and visually inspected. The two speaker-profile files are clear, centered, square, and usable for a small advocate avatar. The larger firm image provides more detail and room for cropping.
- The downloaded bytes are preserved unchanged. No AI editing, resizing, or image generation was performed.
- Jones Day's own portrait was discoverable, but direct script retrieval returned HTTP 403. The accessible speaker-profile image provided the initial working alternative; native Chrome subsequently retrieved the larger firm asset.

SHA-256 for `anthony_j_dick.source.jpg`: `22025a1093e5d28cb28834721ef151d6e2e98ba962591baa1cc0ad037697d079`.

SHA-256 for `anthony_j_dick.jonesday.webp`: `ebdeb9d14f6a7b3c5f58f0c48294cfeb41516f97aca47386a781ede98ed730ce`.

## Higher-resolution retrieval follow-up

The user found the Jones Day image in their ordinary browser and asked for another retrieval attempt. The URL names the same `ajdick` asset attached to his official firm biography; the existing name/firm/location/email evidence establishes the association without face recognition.

1. A normal `curl` download of the exact URL open in Chrome returned **HTTP 403**, as the initial Python requests had. A subsequent diagnostic request recorded `Server: cloudflare` and the HTML title `Attention Required! | Cloudflare`; see `jonesday-direct-fetch-diagnostic.json`. The precise Cloudflare blocking rule is unknown.
2. The in-app browser was unavailable. Chrome's extension-based `getTab` calls timed out, so those controls could not inspect `srcset` or initiate a download.
3. Native Chrome exposed the user's existing public image tab, titled `ajdick.jpg (1068×728)`. Its image URL matched the official profile asset. Using the ordinary **Save Image As** menu saved the file directly to this research directory. Chrome identified the received media as WebP despite the URL suffix, so the WebP extension was retained.
4. Local verification confirmed the WebP signature, **1068 × 728** dimensions, byte count, and SHA-256 hash. The saved file was visually inspected: clear, centered head-and-shoulders portrait with suitable detail for the project.

No Jones Day sign-in, credential extraction, CAPTCHA interaction, image editing, or changes to the production cache were used. The browser retrieval succeeds where these simple HTTP clients are blocked; this does not establish that a fresh headless cloud browser will always work. The follow-up was dominated by browser-control availability: the initial native-app binding took an unexpected roughly ten minutes before returning. It is not a throughput benchmark for image research.

## Difficult candidate tried first: Kevin Joel Page

The Court's hearing list identifies Page as the Dallas Assistant Federal Public Defender arguing for petitioner on October 13. The docket's petitioner entry and the [defender office directory](https://txn.fd.org/Offices/dallas-office) identify the same Dallas office. The [Texas Bar profile](https://www.texasbar.com/am/template.cfm?Template=%2FCustomsource%2FMemberDirectory%2FMemberDirectoryDetail.cfm&contactid=243924&section=Find_a_Lawyer) also records his informal name Joel, which helped broaden the search.

The bounded search did **not** find a verified usable Page portrait:

- Texas Bar: actual HTML uses `ProfilePhotoPlaceholder.gif` for his avatar; rejected as a placeholder.
- [Justia profile](https://lawyers.justia.com/lawyer/kevin-joel-joel-page-270779): explicitly labels its image as a profile placeholder; rejected.
- [Avvo profile](https://www.avvo.com/attorneys/75202-tx-kevin-page-85416.html): search output claims a headshot, but the page returned HTTP 403 on direct retrieval; no actual portrait could be verified, so it was not used.
- Official defender directory and seminar biographies: useful employer/name evidence, but no usable portrait found.
- [Vermont newspaper result](https://vtdigger.org/2023/02/12/last-page-prosecutor-side-judge-retires-after-four-decades/): a different Joel Page, a retired Vermont prosecutor/judge; rejected by location and career.
- [LinkedIn construction profile](https://www.linkedin.com/in/joel-page-915491234): a Missouri construction worker; rejected.
- [LinkedIn Interior Department profile](https://www.linkedin.com/in/joel-page-3b2038a): a Colorado IT professional; rejected.
- The name-based image searches mainly returned unrelated people. No image was accepted just because a search engine returned it.

Approximately **10 text searches and 2 image searches** were spent on Page; **2 text searches and 1 image search** on Dick. Together with source checking and download attempts, this took roughly **10 minutes**. The exact queries and result metadata are in `provenance.json`. No credentials, logged-in profiles, or communication with anyone were used.

## What the proof of concept shows

Codex can find a missing lawyer portrait, tie it to an upcoming argument using public Court records, download it, reject misleading namesakes/placeholders, and preserve source evidence. This one successful portrait does not establish a success rate for harder defender cases. For an automated pipeline, cap the search budget, cache verified portraits and provenance, and use the established agency-logo or initials fallback when no verified image is found. Page remains a candidate for that fallback.
