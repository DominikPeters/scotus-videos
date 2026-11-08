# 25-352 annotation trial (Claude)

Cards for *Younge v. Fulton Judicial Circuit District Attorney's Office*, argued Nov. 2, 2026. A Haiku reader scanned the transcript and filings and downloaded the rules, statutes and cited opinions (`scan.json`, `sources/`). Opus read the argument, then selected, wrote and checked the cards, relying on Haiku's research. Opus then compared Codex's cloud set (`codex/`) and adopted three of its ideas, marked in each card's reason.

Re-run: `python3 annotation-trial/cards.py annotation-trial/25-352 check|render|sheet`

| Time | Shown | Type | Card | Why |
|---|---|---|---|---|
| 0:00 | 38s | Question presented | qp | States the question the Court agreed to decide as Schnapper opens, shortened (wording from the Codex set); the full text appears at 50:26. |
| 0:38 | 29s | Opinion excerpt | hassan | Schnapper attacks the Eleventh Circuit’s Hassan rule; the card shows how the decision below states it. |
| 1:07 | 47s | Comparison | rules-15-16 | Schnapper names Rules 15(a)(2) and 16(b)(4) as the standards that should govern; the card shows both side by side. They come up throughout. |
| 3:24 | 48s | Glossary | personal-staff | Thomas and Schnapper discuss whether Younge was “personal staff” under a “six-part test”; the card explains the exemption and lists the factors. |
| 5:01 | 53s | Opinion excerpt | foman | Barrett invokes Foman; its list of reasons for denying leave to amend (“the Foman factors”) recurs all argument. |
| 7:29 | 38s | Opinion excerpt | ahmad | Barrett asks about “the Tenth Circuit’s rule”; the card shows the Tenth Circuit’s own statement of it. |
| 12:00 | 37s | Rule | rule-61 | Gorsuch likens the Eleventh Circuit’s test to “the first sentence of Rule 61”; the card shows it. |
| 15:31 | 52s | Glossary | affirmative-defense | Alito contrasts an affirmative defense with an element of the claim; the card defines the term, which the whole case turns on, and notes that the Eleventh Circuit only assumed the exemption is one. |
| 21:07 | 37s | Circuit split | approaches | Sotomayor says there are “three different approaches”; the map shows the three courts of appeals discussed and their rules. |
| 26:54 | 39s | Rule | rule-56 | Petrany opens on raising a defense “at summary judgment on an undisputable record”; the card shows the summary-judgment standard (idea from the Codex set). |
| 36:49 | 36s | Statute | gera | Sotomayor asks about an alternative remedy and Petrany cites the EEOC route and a 180-day limit; the card shows the statute that provides both. |
| 40:25 | 37s | Timeline | case-history | Jackson mentions “two years litigating this case” before the defense appeared; the timeline shows when the answer was filed and when the exemption was first raised. |
| 42:33 | 25s | Comparison | consent-relief | Petrany cites Rules 15(b)(2) and 54 as rules that reach matters outside the pleadings; the card shows both. The 15(b)(2) column includes its last sentence (idea from the Codex set). |
| 42:58 | 42s | Opinion excerpt | wood | Petrany cites Day and Wood v. Milyard for treating an unpleaded defense as forfeited rather than waived; the card shows how Wood draws that distinction. |
| 49:52 | 34s | Statute | staff-statute | Petrany says amending would only add “seven words” invoking 2000e(f); the card shows the provision. |
| 50:26 | 54s | Question presented | qp-again | Alito goes back to “the actual question on which review was granted” and paraphrases it; the card shows its text. |
| 54:54 | 24s | Rule | rule-12b | Schnapper reads the “but” in the second sentence of Rule 12(b) as an exception; the card shows the text, which says “every defense”. |

## Uploading to the cloud

`cards.json` has 17 cards, all recommended. Publish it as a new enrichment version for job `2026-11-02-25-352-argument-1` and keep the Codex version (`bf396ad677634329b1a80f0a20eaccd3.json`); follow § 5 of `docs/annotation-cards-lessons.md`:

1. Fetch each evidence source through `cards_source`, using the URLs in `sources/urls.json`. Each `page` is a physical PDF page; for single-page sources (rules, statutes, CAP opinions) it is 1.
   - The Eleventh Circuit opinion is cited from the petition's appendix (`petition.pdf`, which has a text layer). The separately filed opinion PDF is a scan.
   - CAP pin cites in the card source lines (Foman 182, Ahmad 1202, Wood 470) come from the briefs.
2. Run `cards_render` on each card to get its `preview_id`. There are no Record exhibits, so `cards_exhibit` isn't needed.
3. Run `cards_validate`, then publish. Carry over `private_notes`.
4. Excerpt cards use the "Opinion excerpt" label, which the cloud's `cue_for` allows.
5. Don't put a `<mark>` directly against an em-dash; it fails the displayed-text check (lessons doc, § 4.2).

Cards from Codex's set: the shorter opening question (`qp`), `rule-56`, and the last sentence of Rule 15(b)(2) in `consent-relief`.

## Cloud import — 3 November 2026

All 17 cards were imported through the case-name card importer and received new
production previews. The card wording, timing, recommendations and private notes
were preserved. The original 11-card Codex enrichment remains available. The set
is ready for card-selection review on the dashboard. No image build was needed.

The importer now resolves `sources/urls.json` automatically:

```sh
python3 cloud/infra/operate.py import-cards Younge annotation-trial/25-352/cards.json
```

See `cloud/docs/younge-claude-cards-2026-11-03.json` for verification and the
isolated-tested source-paging fix used for this execution.
