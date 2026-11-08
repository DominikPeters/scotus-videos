# 25-170 annotation trial (Claude)

Cards for *Suncor Energy v. Boulder County*, made following the cloud prompt's workflow:
a Haiku 5.5 reader scanned the full transcript and filings (`scan.json`), and Opus 5.5
selected, sourced, wrote and visually checked the cards. Validation reuses the cloud's
`cue_for`; previews use the production renderer (`cloud/render/original.js card`).

- `cards.json` — proposals with evidence (source file, physical page, exact quote) and private notes
- `renders/ID.jpg`, `renders/ID.jpg.card.jpg` — production preview frame and card crop
- `cards-sheet.jpg`, `frames-sheet.jpg` — contact sheets
- `codex/` — the Codex set from the cloud (enrichment JSON, preview images, contact sheet), for comparison
- `sources/` — fetched filings, statutes (govinfo), opinions (CAP), Oyez records, Federal Register

Re-run: `python3 annotation-trial/cards.py annotation-trial/25-170 check|render|sheet`

| Time | Shown | Type | Card | Default | Why |
|---|---|---|---|---|---|
| 0:12 | 43s | Question presented | qp-opening | yes | States the granted question as Shanmugam opens, before the argument turns to jurisdiction. |
| 2:16 | 34s | Question presented | qp-jurisdiction | yes | Explains why Thomas opens with jurisdiction: the Court itself added that question when it granted review. |
| 2:50 | 36s | Case | atlantic-richfield | yes | The jurisdiction precedent both sides argue over; shows why a state-court writ proceeding can count as a final judgment. |
| 9:23 | 33s | Statute | caa-saving-clause | yes | First mention of the Clean Air Act's saving clause, which much of the argument turns on; viewers see what it actually preserves. |
| 12:24 | 55s | Case | aep | yes | Introduces the greenhouse-gas precedent at its first substantive mention (from the Codex set). |
| 13:18 | 26s | Case | ouellette | yes | Explains the water-pollution precedent and its source/affected-state split as Shanmugam invokes it (from the Codex set). |
| 16:53 | 39s | Case | watson | yes | Sotomayor raises a case Shanmugam does not recall; the card tells viewers what it held and why it is a multi-state example. |
| 19:13 | 40s | Opinion excerpt | colorado-rule-21 | hidden | Hidden: Sotomayor asks whether the Rule 21 proceeding was an original writ or an interlocutory appeal, a disputed point; the Colorado court’s “original jurisdiction” wording could be read as answering it for petitioners. |
| 21:13 | 31s | Case | cox | yes | Explains the 'Cox strand', the fallback route to jurisdiction, which otherwise sounds like jargon. |
| 25:32 | 44s | Complaint excerpt | complaint-411 | yes | Shanmugam points the Court to paragraph 411 while Kagan presses the tobacco analogy; viewers can read the allegation itself. |
| 28:25 | 39s | Case | hyatt | yes | Shanmugam grounds his equal-sovereignty principle in this case; the card says what it actually decided. |
| 29:51 | 43s | Case | pork-producers | hidden | Shanmugam cites Pork Producers for territorial limits on state power; the holding shows the Court rejected an extraterritoriality rule under the dormant Commerce Clause. |
| 30:48 | 38s | Timeline | four-precedents | yes | Kavanaugh's 'four cases' recur throughout the argument; one compact timeline tells viewers what each held. |
| 34:08 | 38s | Statute | good-neighbor | yes | Kavanaugh asks how tort suits would upset the good neighbor provision; the card shows what that provision requires of states. |
| 37:42 | 54s | Glossary | displacement | yes | Barrett walks through displacement; the card separates it from preemption of state law (from the Codex set). |
| 45:05 | 36s | Timeline | case-history | yes | Jackson says the case is at an early stage; the timeline shows where the litigation stands. |
| 52:31 | 30s | Statute | section-1257 | yes | Thomas asks whether this is a final determination; the statute shows where the finality requirement comes from. |
| 56:40 | 40s | Opinion excerpt | aep-academic | yes | Gorsuch asks whether Boulder could have brought a federal common-law claim; Harris says AEP held that question open. The card shows the sentence they are discussing (idea from the Codex set). |
| 57:34 | 44s | Timeline | epa-2026 | yes | Gorsuch says EPA has disclaimed power over greenhouse gases from vehicles and stationary sources; the card separates the final vehicle rule from the still-proposed power-plant rule. |
| 63:02 | 42s | Opinion excerpt | aep-closing | yes | Kagan paraphrases AEP's closing paragraph; the card shows its words, which Harris then reads further. |
| 66:15 | 51s | Comparison | saving-clauses-compared | yes | Kavanaugh asks whether the two saving clauses have the same scope; side by side, viewers can see how closely they track each other. |
| 69:15 | 38s | Complaint excerpt | suncor-colorado-refinery | yes | Jackson asks whether Colorado is also a source state because of in-state refineries; the complaint's own allegation answers what was pleaded. |
| 75:09 | 34s | Comparison | baseline | yes | Kavanaugh asks which way the default runs; the parties’ opposing starting points side by side (from the Codex set). |
| 78:38 | 40s | Case | isla-petroleum | yes | Russell's precedent is garbled in the transcript ('RICO's'); the card identifies the Puerto Rico case and its point about repealed preemption. |
| 79:49 | 42s | Case | commonwealth-edison | hidden | Sotomayor offers this case as directly on point; Oyez's vote and the Court's dismissal of the Clean Air Act argument add context to her summary. |
| 87:34 | 38s | Opinion excerpt | ouellette-vermont-law | yes | Kavanaugh cites footnote 20 for the point that Vermont (affected-state) law could not apply; the card shows the footnote itself. |
| 97:26 | 37s | Case | virginia-uranium | yes | Russell cites Virginia Uranium for regulation that only indirectly affects a federally regulated activity; the card states its holding. |
