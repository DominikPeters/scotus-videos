# Annotation cards: lessons from the 25-170 comparison

For Codex. In October 2026, two card sets were made for *Suncor Energy v. Boulder County* (No. 25-170):

- **The Codex set:** 14 cards, from the cloud pipeline. It is stored in
  `gs://possible-cycle-237715-scotus-video-media/enrichment/2026-10-05-25-170-argument-1/6f01158a0f9d4445b7f445ea005d8d68.json`.
- **The Claude set:** 22 cards, made locally with a Haiku reader and an Opus editor, following the same prompt.

Both Codex and Claude judged the Claude set the better starting point. The two sets were then merged and edited into the version described in the last section, which should replace the cloud version.

Everything is in `annotation-trial/25-170/`:

| Path | Contents |
|---|---|
| `cards.json` | The current merged set |
| `README.md` | A table of every card with its reason |
| `codex/` | The Codex set, with previews and a contact sheet |
| `sources/` | Every source cited in the evidence |
| `sources/urls.json` | The original URL of each source file |

The workbench is `annotation-trial/cards.py`. It reuses the cloud's `cue_for` and renders with the production renderer.

## 1. Selection: what earns a card

**Cards go where a viewer is lost.** The highest-value moments in 25-170 were things named in the argument that a viewer cannot decode:

- a case an advocate cites, or one a Justice raises that the advocate cannot recall (*Watson*);
- a name the transcript garbles ("RICO's regulation" is *Puerto Rico v. Isla Petroleum*);
- a record citation ("paragraph 411 of the complaint");
- a statute named without its text;
- "four precedents" that a Justice keeps returning to.

Codex skipped most of these, and spent cards on doctrine glossaries instead (displacement, proximate cause). Prefer the concrete reference over the abstract concept. A glossary is warranted only when a term of art is used undefined and repeatedly. Don't add one when an advocate defines the term on the spot.

**Neutrality: background, or the thing under discussion. Never a referee.** A card may do either of two things:

- give background a viewer needs, such as what a cited case held or where a case stands procedurally;
- show the very thing being discussed, such as the sentence of AEP that Harris says "held open" a question, or the footnote Kavanaugh cites.

A card must not bring in outside material that bears on a point the two sides are disputing. That reads as the video taking sides. Three examples were removed or hidden:

- **Codex, "The relief Boulder seeks" (91:02).** Barrett asks whether a tort suit regulates just as a statute would. Russell says no, the suit only seeks damages. The card quoted the Colorado Supreme Court saying Boulder seeks no injunction. Nobody was discussing that opinion, and the card backed one side's characterization exactly when it was being challenged.
- **Claude, Colorado Rule 21 excerpt (19:13).** Sotomayor asks whether the state proceeding was an "original writ or just an interlocutory appeal", a disputed jurisdictional point. The Colorado court's own words ("original jurisdiction") would look like an answer in petitioners' favour. Now hidden.
- **Claude, Commonwealth Edison.** The card quoted the opinion saying the Clean Air Act argument "merits little discussion", which supports Sotomayor's point. The quote was cut; the card now gives only the holding.

The test to apply: is this exact source being discussed at this moment? If it is not, does the card only supply background, or does it bear on the disagreement?

**Show what is cited, not something similar.** When a speaker cites a specific passage, such as "Ouellette, footnote 20", the card must show that passage. The Claude set first used a main-text substitute because the Caselaw Access Project text lacked the footnote, which made the card confusing. The official U.S. Reports PDF on govinfo has it: `USREPORTS-479-481.pdf`, physical page 19. The govinfo PDFs also have the syllabi and footnotes that the Caselaw Access Project lacks.

**Timelines are fine when the argument is about sequence.** Codex added no timeline "because the argument turns on legal rules". But three moments are about order:

- Kavanaugh's four precedents (Milwaukee I and II, Ouellette, AEP);
- Jackson's "we're really early in this case";
- Gorsuch's reference to the EPA's 2026 actions.

Keep timelines to five events or fewer, because eight events were unreadable at video size. Keep each label to about five words.

**Factual premises: give the status, don't correct.** Gorsuch says the EPA has disclaimed power over stationary sources. The Federal Register shows that as a *proposed* rule (91 FR 59002). The card simply labels it "Proposed rule" and comments neither on the question nor on the Justice.

**Coverage.** Codex left a 19-minute stretch without a card (37:42–56:40), plus 16- and 9-minute gaps. Look for material across the whole argument, but don't pad. A gap with nothing that needs explaining is fine.

**Skip anything read aloud.** If a speaker reads a passage verbatim, a card repeating it adds nothing. Examples: Kavanaugh quoting Milwaukee's "implicit corollary", and Shanmugam reading the trial court's causation ruling.

## 2. Writing the card

- **Headings say what the card is, not tease it.** For example: "Displacement vs. preemption", not "Congress replaces judge-made rules"; and "*American Electric Power Co.* v. *Connecticut* (2011)", not "A separate question left unresolved".
- **Labels.**
  - Leave `label` out, so the card type shows. The only exception is Case cards, whose label is empty by design.
  - Codex set `label: ""` on every card. That hides the type and renders a stray leading "·" before the heading.
  - Excerpt and Record cards should say what is excerpted: "Opinion excerpt", "Complaint excerpt", "Brief excerpt". This needs the code change in section 4.
- **Case summaries:** one sentence giving the holding in plain words, scoped exactly. For AEP, the scope is "power-plant greenhouse-gas emissions", not "CO₂" in general. Codex's AEP and Ouellette summaries are good models.
- **Comparisons of the two sides** are fine when they are balanced and a Justice frames the choice. Codex's "The disputed starting point", at Kavanaugh's "what burden is on Congress", was kept.
- **Underline phrases:** the speaker's words that point at the card's subject ("held open under AEP", "paragraph 411 of the complaint"). The phrase must be spoken in the card's window.
- **Record images:**
  - Crop tightly to the paragraph: full text width, about 3 pt above and 7 pt below.
  - Highlight the key phrase, not the whole crop.
  - Codex abandoned its record crop because the type was small. A tight crop fixes that; see `exhibit` in `annotation-trial/cards.py`.
- **Prefer official sources** (U.S. Reports, the U.S. Code, docket PDFs) over Oyez. Use Oyez only for facts the official sources lack, such as vote counts.

## 3. Process

- Splitting the work into a reader and an editor works. The reader scans every block and lists opportunities; the editor verifies, sources, decides and writes. The reader should save its scan incrementally: the Haiku reader stalled once and only resumed via a message.
- Check every evidence quote against the physical page it claims. Check every displayed statute or quote segment against the source text.
- Inspect the full video frame, not only the card crop. Density problems such as the eight-event timeline only show at frame size.
- Keep the omission decisions in the private notes. Codex did this well: 26 opportunities considered, with reasons.

## 4. Code changes needed in `cloud/`

1. **`cue_for` labels.** Allow `label` on Excerpt and Record cards from an allowlist: "Opinion excerpt", "Complaint excerpt", "Brief excerpt", "Record excerpt", "Transcript excerpt". Update the prompt to match. The local workbench already accepts these (`annotation-trial/cards.py`, `cues()`).
2. **`normalized()` hyphens.** Line-break hyphens and real hyphens should compare equal; otherwise quotes that cross a line break fail to verify. The local fix is `re.sub(r'-\s*', '', value)`. Also collapse `'Hall , 440'` to `'Hall, 440'`, since stripping tags leaves a space before punctuation.
3. **`cards_exhibit`.** Take a separate highlight phrase, so the crop can show a whole paragraph while only the key words are marked.
4. **The prompt.** Add:
   - the neutrality rule and its test;
   - "show what is cited";
   - permission for timelines when the argument is about sequence (five events or fewer);
   - descriptive headings;
   - the label rules above;
   - the priority on things named in the argument over concept glossaries.

   The 25-170 examples above work as counter-examples.

## 5. Uploading the merged set to the cloud

`annotation-trial/25-170/cards.json` has 27 cards, 24 recommended. Each card has `id`, `start_block`, `end_block`, `recommended`, `reason`, `cue` and `evidence`. Evidence entries are `{source, page, quote, claim}`, where `source` is a file in `sources/`, mapped to its URL by `sources/urls.json`, and `page` is the physical PDF page.

To publish it as a new enrichment version for job `2026-10-05-25-170-argument-1`:

1. Apply code change 1 first; three Excerpt cards and two Record cards use the new labels.
2. For each card, fetch its sources through `cards_source` (URLs from `urls.json`), so evidence gets the cloud's `url` and `sha256` form. Then run `cards_render` to get a cloud `preview_id`.
3. Recreate the two record images with `cards_exhibit`:
   - ¶411: JA p. 105, physical page 107 of `ja.pdf`.
   - ¶92: JA p. 27, physical page 29.

   The local assets are in `annotation-trial/25-170/preview/cards/assets/`. The paragraph and highlight phrase for each are in that card's `evidence`.
4. Run `cards_validate`, write the result as a new enrichment JSON, and point the job at it as the pipeline normally does. Keep the Codex version; don't overwrite it.
5. Carry over `private_notes` from `cards.json`. They record the omissions and the neutrality decisions.

The Codex-derived cards in the merged set:

- `aep`
- `ouellette`
- `displacement`
- `baseline`
- `aep-academic`, whose wording is new
- the shorter question wording in `qp-opening`

All other cards come from the Claude set.
