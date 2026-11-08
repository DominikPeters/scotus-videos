# 25-5930 annotation trial (Claude, merged with Codex ideas)

Cards for *Maxwell v. Dinis*, argued Nov. 2, 2026. A Haiku reader scanned the transcript and filings (`scan.json`); Opus read the argument, selected, sourced, wrote and visually checked the cards, then read Codex's set (`codex/`) and adopted three of its ideas (marked in each card's reason). Validation reuses the cloud's `cue_for`; previews use the production renderer.

- `cards.json` — cards with evidence (source file, physical page, exact quote) and private notes
- `renders/` — production preview frame and card crop per card; `cards-sheet.jpg`, `frames-sheet.jpg`
- `sources/` — filings, U.S. Code sections (govinfo), opinions (CAP and supremecourt.gov)
- `preview/` — local preview bundle built with the cloud's `make_bundle` (candidate portraits)

Re-run: `python3 annotation-trial/cards.py annotation-trial/25-5930 check|render|sheet`

| Time | Shown | Type | Card | Default | Why |
|---|---|---|---|---|---|
| 0:09 | 46s | Question presented | qp | yes | States the question the Court agreed to decide as Hansford opens. |
| 0:55 | 60s | Opinion excerpt | decision-below | yes | Hansford describes the Fifth Circuit’s ruling; the card shows its actual words. |
| 2:32 | 45s | Comparison | review-bar | yes | Hansford contrasts the government’s “review bar” in § 3621(b) with the First Step Act’s transfer provision; the card shows both texts side by side (idea from the Codex set). |
| 3:16 | 57s | Glossary | prerelease-custody | yes | “Prerelease custody” is the status Maxwell wants; the card says what it is. |
| 5:20 | 22s | Case | chafin | yes | Hansford invokes Chafin for why the case would not become moot. |
| 6:11 | 27s | Record excerpt | ja-17 | yes | Hansford points to Joint Appendix 17 as where Maxwell cited the First Step Act; the card shows that page. |
| 6:38 | 31s | Case | perttu | yes | Hansford cites Perttu for a jury trial on the obstruction claims; the card states its holding. |
| 7:32 | 38s | Glossary | bivens | yes | Jackson contrasts habeas with a “Bivens claim”, a term used throughout and never explained. |
| 8:59 | 26s | Comparison | two-routes | yes | Hansford mentions state prisoners’ § 1983 rights; the card lays out the two routes into court the argument is about. |
| 10:23 | 52s | Statute | four-requirements | yes | Alito and Gorsuch refer to the statute’s “four requirements”; the card lists them. |
| 13:13 | 46s | Opinion excerpt | quantum-change | yes | Sotomayor cites Justice Scalia’s “quantum change” language; the card shows the sentence. |
| 15:06 | 37s | Circuit split | circuit-split | yes | Hansford mentions a split in which two circuits send these claims out of habeas; the map shows which circuits are on each side (idea from the Codex set). |
| 16:11 | 39s | Case | preiser | yes | Both sides build on Preiser; Barber says it “squarely controls”. The card states what it decided. |
| 18:11 | 38s | Case | jones-cunningham | yes | Barber cites Jones v. Cunningham alongside Preiser; the card says what it held. |
| 18:49 | 42s | Glossary | dig | yes | “DIG” comes up repeatedly from here on; the card explains it. |
| 21:52 | 51s | Opinion excerpt | skinner | yes | Kagan says the full Court adopted Scalia’s language in Skinner; the card shows the sentence. |
| 29:57 | 33s | Timeline | case-history | yes | Jackson asks how soon Maxwell will be released; the timeline places the argument against BOP’s projected date. |
| 33:14 | 49s | Statute | early-supervised-release | yes | Barber says § 3624(g) lets credits start supervised release early but not shorten it; the card shows the provision (idea from the Codex set). |
| 34:47 | 28s | Case | jgg | yes | Kavanaugh asks about Trump v. J.G.G.; the card says what it decided. |
| 40:27 | 56s | Case | koray | yes | Barnes relies on Koray for the significance of BOP control; the card states what it held. |
| 41:24 | 34s | Glossary | parole | yes | Kagan and Barnes contrast prerelease custody with parole, which no longer exists federally; the card explains what replaced it. |
| 42:15 | 38s | Statute | escape | yes | Barnes points to the federal escape statute; the card shows its text. |
| 46:21 | 32s | Case | meachum | yes | Barnes and Sotomayor rely on Meachum for transfers between prisons; the card states its holding. |
| 52:49 | 37s | Statute | plra | yes | Barnes contrasts habeas exhaustion with the PLRA’s statutory requirement; the card shows the statute. |
| 57:39 | 45s | Case | sinochem | hidden | Barnes cites Sinochem for choosing the order of threshold issues; hidden by default as a passing reference. |
| 62:34 | 22s | Case | st-cyr | yes | Hansford invokes the “St. Cyr level of clarity”; the card explains the rule. |
| 62:56 | 42s | Comparison | medley-bonner | yes | Hansford closes with two 1890s cases the argument never explains; the card says what each decided. |
