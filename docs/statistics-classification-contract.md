# Statistics classification contract

The shared implementation is `scotusstats/data-pipeline/stats_core.py`. The cloud image copies that module, its tests and the worker's self-check command. Codex must check its complete draft with `python input/check_statistics.py` before submitting it.

Decision form is a closed category: majority, plurality opinion, per curiam, equally divided, or dismissed as improvidently granted. For ordinary majority opinions, publication derives `decision.type` from judgment vote counts. Concurrences and partial reasoning joins are not free-form facet labels. The canonical object retains `opinionForm` separately.

`voteStatus=complete` identifies one supported case-level judgment coalition. `mixed` retains separately labelled and evidenced `judgmentParts`; `unknown` retains a known disposition without inventing an exhaustive vote. Mixed and unknown objects omit case-level voter arrays and counts from publication, so existing vote charts skip them while author charts can retain a known author. Mixed judgments have the stable public category `mixed judgment`. Pending cases alone may omit the whole decision.

Opinion details retain full `joiners` and separate `{justice, parts}` partialJoiners. Author IDs use canonical surnames. These opinion details and their evidence remain private; claim-specific evidence is retained with each structured judgment part. Neither the original opinion assigner nor recusals are inferred from the final coalition.

Use the existing SCDB taxonomy conventions and worked comparators supplied in the prompt. A statute lacking a dedicated taxonomy entry uses 600 when supported; a nonstatutory common-law ground may use 900. Null means evidence is insufficient, not merely absence of a specifically named statute. Review the full issue label and its qualifications.

The 2026-10-15 migration repairs the first OT25 automated batch: 55 facet labels, three omitted decisions, six legal-provision gaps, the federal ex post facto topic, and identified partial joins. It is idempotent. Original records and model research are preserved in private canonical `migrations`; the normal publisher also retains the previous public dataset. Migration decisions are reviewed case-specific corrections, not heuristics for future cases. Every future publication validates saved Codex decisions as well as new drafts. Historical SCDB data is unchanged.
