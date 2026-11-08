# Write a short, neutral case description

Follow POLICY.md. This is the final writing stage, normally run with Sol. Fill
only the fields requested in input/request.json; return null text and an empty
source_ids array for every field marked keep. The application will preserve those
Oyez fields itself. Output the supplied schema, not a whole YouTube description.

Read input/case.json, input/oyez.json, input/materials.json, input/source-index.json
and, when present, input/research.json. Use the supplied source IDs. Reuse the completed research. Distinguish verified source passages from the researcher’s interpretations and open questions. Focus your own checks on claims that determine the public description, disputed framing and unresolved gaps; do not repeat the bulk reading. You remain responsible for the final claims.
The materials file contains selected passages, not the full bulk research input.
excerpt_check indicates whether an excerpt matched supplied text or needs a
focused source-link check. Do not treat a research-model excerpt as independently
verified merely because it is present in the packet.
Treat `supplied_source_text`, `matched_supplied_text` and `supplied_oyez_field`
as completed text/provenance checks; those passages need no blanket re-fetch.
`check_source_link` identifies a passage still needing verification. Background
summaries and legal characterizations are the researcher's interpretations;
`private_caveats` identifies open questions. Check consequential meaning and scope
without repeating the completed source collection.
Further focused browsing may verify those sources. Do not silently base the final
text on a new, unrecorded source; record any newly used source with a unique ID
and supporting passage in additional_sources.

Write two kinds of content for the existing intro and description slots:

- facts_of_the_case: usually one short paragraph, about 80–100 words or fewer.
  Explain the concrete dispute and the procedural step that brings it to this
  Court. Include only details a non-expert needs to understand the question.
- question: usually one short sentence, about 20–35 words or fewer. Explain the
  actual issue before the Court in ordinary language. Separate genuinely distinct
  granted issues if necessary, while staying within the supplied budget.

These are ceilings to aim below, not minimums. Do not pad a simple case. The
request supplies hard per-field and combined word limits. The existing renderer
shrinks text to fit; shortening content is preferable to making that font tiny.
Do not change HTML, CSS, fonts, paragraph styling or the renderer to fit prose.
Return plain text; the application creates escaped paragraph HTML.

Prefer Oyez content where available. A shorten action means condense that content
without changing its factual substance, keeping Oyez among the actual sources.
A missing action means write the field from the researched evidence. Avoid long
chronologies, citations in the displayed text, quotations, unnecessary full party
names, statutory subsection numbers and legal jargon. Retain a legal distinction
when removing it would misstate what the Court must decide.

Questions presented, including official ones, may be written tendentiously. Do
not reproduce rhetorical labels, contested premises or an implied answer. Decide
what is established background, what a party alleges and what is actually open
for decision. Preserve the granted issue while making its wording neutral and
shorter. Do not replace loaded rhetoric with an equally misleading oversimplification.

Invented wording examples, demonstrating style rather than facts about any case:

- Loaded: "Whether a rogue agency may evade accountability by unlawfully
  destroying the property rights of hardworking Americans."
- Neutral, after verifying the underlying issue: "Can landowners seek damages
  for the agency's use of their property?"
- Procedural issue: "Can the company challenge the regulation before the agency
  brings an enforcement action?" Avoid turning that into whether the regulation
  is lawful if that issue is not before the Court.

Describe the case as it stood at the argument date. Do not forecast a result or
insert a later Supreme Court decision. Give each written field the IDs of sources
that actually support it. Use private_editorial_notes to explain condensation or
neutralization, and private_caveats for uncertainty. Those notes and citations do
not become public prose. No unsolicited disclaimers about AI, research, accuracy
or the work performed. Default to the shortest useful supported description.

If input/revision.json is supplied, the previous draft exceeded a word budget.
Rewrite it more concisely from the same evidence; do not mechanically truncate
sentences or drop an essential limitation just to pass a word count.
