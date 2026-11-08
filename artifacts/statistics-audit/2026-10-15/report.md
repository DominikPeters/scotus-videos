# OT25 classification quality audit — 15 October 2026

The published output was not ready as-is. The basic decision extraction fares substantially better than its conversion into the website's classification fields. This audit did not modify public data.

## Scope and checks

- Canonical snapshot: 754 cases; 58 OT25 cases, of which 55 have a case-level decision object and three do not.
- OT24 comparison: 57 decision objects from SCDB retain the site's established labels. OT25's 55 objects all come from Codex.
- All 58 recorded OT25 decision dates match dated official Court docket announcements.
- All 55 recorded principal opinion writers match those announcements.
- Oyez decision data was available for 38 cases in the local metadata. In 37 both sources have a comparable case-level decision. Principal writers and dissent-writing authors match in all 37. Majority/minority rosters match exactly in 35. The remaining two discrepancies are duplicate/missing justice errors in Oyez: Enbridge repeats Jackson and omits Barrett; Hencely repeats Jackson and omits Gorsuch. The official announcements support our rosters in both cases.
- The other 18 stored case-level coalitions were reviewed against their official announcements; no definite incorrect judgment coalition was identified. Partial concurrence/dissent requires separate treatment and consistent definitions.
- Opinion-author sets match all 56 usable multi-document Court XML packages. Callais's archive XML is an older single-document opinion; its current docket and PDF support the model's authorship coding. The three null case-level decisions also retain detailed opinion authorship.

These findings support the extraction of dates, writers and votes. They do not certify every issue/legal-provision choice or every part-specific joining relationship.

## Confirmed defects

### Uncontrolled decision labels: all 55 OT25 decision objects

`decision.type` was allowed to be any string, even though the website uses it as a facet with a stable vocabulary. The checker accepted strings such as `majority`, `unanimous`, and whole descriptions of partial joins. None of the 55 uses the site's expected numeric/special-case labels. For ordinary decisions the label should be derived from supported counts, such as `9-0` or `6-3`. Opinion form and part-specific qualifications should be structured separately. Established special labels such as `plurality opinion`, `per curiam` and `equally divided` need a closed vocabulary and a consistent priority rule.

This was an implementation/schema failure. Asking the model to self-check was insufficient because the checker did not encode the actual interface contract.

### Three decided cases omitted from the case-level decision field

- **Hamm v. Smith (24-872):** the official docket explicitly records a DIG on May 21, 2026, issued per curiam. The model recognized this in its notes and opinion details but returned `decision: null` because it could not enumerate every individual vote. A known disposition must remain classifiable even when vote identities are unknown.
- **Cisco v. Doe I (24-856):** its different claims have different coalitions (6-3 for ATS and 8-1 for TVPA). The detail was retained but the entire public decision object was omitted.
- **West Virginia v. B.P.J. (24-43):** part-specific concurrence/dissent likewise caused omission. The data model needs an explicit, consistent representation of mixed judgments rather than silent absence.

Sources: [Hamm docket](https://www.supremecourt.gov/docket/docketfiles/html/public/24-872.html), [Cisco docket](https://www.supremecourt.gov/docket/docketfiles/html/public/24-856.html), [B.P.J. docket](https://www.supremecourt.gov/docket/docketfiles/html/public/24-43.html).

### Six blank legal-provision classifications

Galette, Hunter, Montgomery, Cox Communications, Hikma and T.M. have no legal-provision classification. Some need a policy decision about common law/structural constitutional doctrines. Several explicit statutory cases were left blank simply because there is no dedicated named code.

Two strong counterexamples to that behavior are **Cox Communications** and **Hikma**. The local SCDB snapshot codes Grokster's copyright case and Global-Tech's patent-inducement case as `600` (Infrequently litigated statutes). The new model instead left the analogous Copyright Act and 35 U.S.C. §271(b) fields null. Beaird's generic-code resolution should become a documented coding rule, supported by historical examples, rather than a one-off owner intervention. Montgomery's 49 U.S.C. §14501(c) omission also needs correction under a consistent statutory fallback rule.

### Part-specific joins lack a consistent machine-readable contract

The detailed `joiners` array sometimes includes partial joiners and sometimes only full joiners, with qualifications placed in free-text `parts`. For example Pung includes Thomas in the lead-opinion detail's joiners while correctly excluding him from `decision.majorityJoiners`; the free text explains that he did not join Part II-B. The details are valuable but unsafe to aggregate without structured full/partial joining records.

### Issue classifications need consistency review

Membership in the closed taxonomy was checked, but a valid code is not necessarily the best comparable historical code. For example Ellingburg's federal Ex Post Facto question was assigned the taxonomy's state-labeled ex-post-facto category; the model explicitly rationalized that mismatch. Peugh supplies a relevant historical federal-sentencing comparator with a different issue code. This is a review flag, not a demonstrated universal rule: the old taxonomy and SCDB itself contain irregularities. Existing SCDB examples should guide both topic and provision decisions, with targeted review of the new coding.

## Recommended repair

1. Separate constrained opinion form from the public decision label; derive ordinary vote labels in code. Preserve nuanced detail outside the facet.
2. Represent known dispositions without requiring known individual votes. Represent mixed judgments explicitly and retain their issue-level coalitions.
3. Extend the same local checker used by Codex to enforce those contracts, including fixed examples for unanimous judgments with separate opinions, pluralities, DIGs and mixed cases.
4. Supply selected historical SCDB comparators for issue/provision coding; distinguish code 600, code 900 (No Legal Provision), and genuinely unknown information.
5. Repair the existing snapshot from retained counts/evidence where possible. Only genuinely ambiguous cases need another research run. Do not rerun the entire backfill simply to repair labels.
6. Add an integration check against the flattened dataset and actual website facet, plus a substantive spot check, before treating a batch as publication-ready.

## Case inventory

| Case | Current label | Votes | Writer | Legal provision present |
|---|---|---|---|---|
| Landor v. Louisiana Department of Corrections (23-1197) | majority | 6-3 | Gorsuch | yes |
| M & K Employee Solutions, LLC v. Trustees of the IAM National Pension Fund (23-1209) | unanimous | 9-0 | Jackson | yes |
| Galette v. New Jersey Transit  Corp. (24-1021) | unanimous | 9-0 | Sotomayor | **no** |
| Wolford v. Lopez (24-1046) | majority | 6-3 | Alito | yes |
| Rico v. United States (24-1056) | majority | 8-1 | Gorsuch | yes |
| Hunter v. United States (24-1063) | majority | 8-1 | Kagan | **no** |
| Monsanto Company v. Durnell (24-1068) | majority | 7-2 | Kavanaugh | yes |
| Louisiana v. Callais (24-109) | majority | 6-3 | Alito | yes |
| United States v. Hemani (24-1234) | unanimous judgment | 9-0 | Gorsuch | yes |
| Montgomery v. Caribe Transport II, LLC (24-1238) | majority | 9-0 | Barrett | **no** |
| Watson v. Republican National Committee (24-1260) | majority | 5-4 | Barrett | yes |
| Learning Resources, Inc. v. Trump (24-1287) | majority in part; plurality in part | 6-3 | Roberts | yes |
| Cox Communications, Inc. v. Sony Music Entertainment (24-171) | Unanimous judgment with concurrence in the judgment | 9-0 | Thomas | **no** |
| FS Credit Opportunities Corp. v. Saba Capital Master Fund, Ltd. (24-345) | majority | 6-3 | Barrett | yes |
| United States Postal Service v. Konan (24-351) | majority | 5-4 | Thomas | yes |
| Little v. Hecox (24-38) | majority | 6-3 | Kavanaugh | yes |
| West Virginia v. B.P.J. (24-43) | **missing** | — | — | yes |
| Berk v. Choy (24-440) | Unanimous judgment with separate concurrence in the judgment | 9-0 | Barrett | yes |
| Ellingburg v. United States (24-482) | unanimous | 9-0 | Kavanaugh | yes |
| Chiles v. Salazar (24-539) | majority | 8-1 | Gorsuch | yes |
| Bowe v. United States (24-5438) | majority | 5-4 | Sotomayor | yes |
| Fernandez v. United States (24-556) | majority | 8-1 | Barrett | yes |
| Villarreal v. Texas (24-557) | Unanimous judgment with concurrence in the judgment | 9-0 | Jackson | yes |
| Bost v. Illinois State Board of Elections (24-568) | majority | 7-2 | Roberts | yes |
| Barrett v. United States (24-5774) | unanimous judgment; opinion of the Court except Part IV-C | 9-0 | Jackson | yes |
| National Republican Senatorial Committee v. Federal Election Commission (24-621) | majority | 6-3 | Kavanaugh | yes |
| Case v. Montana (24-624) | unanimous | 9-0 | Kagan | yes |
| Exxon Mobil Corp. v. Corporación Cimex, S.A. (Cuba) (24-699) | majority | 6-3 | Kavanaugh | yes |
| Hain Celestial Group, Inc. v. Palmquist (24-724) | unanimous | 9-0 | Sotomayor | yes |
| Pitchford v. Cain (24-7351) | majority | 5-4 | Kavanaugh | yes |
| The GEO Group, Inc. v. Menocal (24-758) | majority | 9-0 | Kagan | yes |
| Urias-Orellana v. Bondi (24-777) | unanimous | 9-0 | Jackson | yes |
| First Choice Women's Resource Centers, Inc. v. Platkin (24-781) | unanimous | 9-0 | Gorsuch | yes |
| Enbridge Energy, LP v. Nessel (24-783) | unanimous | 9-0 | Sotomayor | yes |
| Coney Island Auto Parts Unlimited, Inc. v. Burton (24-808) | Unanimous judgment with separate concurrence in the judgment | 9-0 | Alito | yes |
| Chevron USA Inc. v. Plaquemines Parish, Louisiana (24-813) | majority | 8-0 | Thomas | yes |
| Rutherford v. United States (24-820) | majority | 6-3 | Barrett | yes |
| Cisco Systems, Inc. v. Doe I (24-856) | **missing** | — | — | yes |
| Hamm v. Smith (24-872) | **missing** | — | — | yes |
| Hikma Pharmaceuticals USA Inc. v. Amarin Pharma, Inc. (24-889) | unanimous | 9-0 | Jackson | **no** |
| Hencely v. Fluor Corporation (24-924) | majority | 6-3 | Thomas | yes |
| Flower Foods, Inc. v. Brock  (24-935) | unanimous | 9-0 | Gorsuch | yes |
| Havana Docks Corporation v. Royal Caribbean Cruises, Ltd. (24-983) | majority | 8-1 | Thomas | yes |
| Olivier v. City of Brandon, Mississippi (24-993) | unanimous | 9-0 | Kagan | yes |
| Mullin v. Doe (25-1083) | majority in part; plurality in part | 6-3 | Alito | yes |
| Chatrie v. United States (25-112) | majority | 6-3 | Kagan | yes |
| T. M. v. University of Maryland Medical System Corporation (25-197) | majority | 5-4 | Sotomayor | **no** |
| Trump v. Slaughter (25-332) | majority | 6-3 | Roberts | yes |
| Trump v. Barbara (25-365) | majority | 6-3 | Roberts | yes |
| Federal Communications Commission v. AT&T, Inc. (25-406) | majority | 8-1 | Roberts | yes |
| Blanche v. Lau  (25-429) | majority | 6-3 | Thomas | yes |
| Sripetch v. SEC (25-466) | unanimous | 9-0 | Gorsuch | yes |
| Noem v. Al Otro Lado (25-5) | majority | 6-3 | Alito | yes |
| Abouammo v. United States (25-5146) | unanimous | 9-0 | Kagan | yes |
| Keathley v. Buddy Ayers Construction, Incorporated (25-6) | unanimous | 9-0 | Jackson | yes |
| Jules v. Andre Balazs Properties (25-83) | unanimous | 9-0 | Sotomayor | yes |
| Pung v. Isabella County (25-95) | unanimous judgment; majority opinion with partial concurrence | 9-0 | Alito | yes |
| Trump v. Cook (25A312) | majority | 5-4 | Roberts | yes |

Detailed machine-readable checks are in `official-announcement-comparison.json`, `oyez-comparison.json` and `xml-authors-comparison.json`. The immutable canonical snapshot and its archived official-source documents are retained alongside this report for reproducibility. No new cloud processing or publication was triggered by this audit.
