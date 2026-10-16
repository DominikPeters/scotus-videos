# Justice participation

Enrichment asks Codex to interpret official docket proceedings for the recording’s docket and argument date. It reuses the description research task and already fetched docket. When case-description research is unnecessary, Luna performs a compact docket-only check and leaves the description untouched. Resumed enrichment and editorial caches without a matching participation assessment also receive the check.

The private enrichment artifact stores `participation`: recording identity, justice identifiers, recused/participating/uncertain decisions, explanations, dated Court evidence, and private notes. Codex interprets the evidence; the application validates its structure, identity and official sources. It does not infer recusal with regular expressions or from silence/Oyez membership alone. The prompt covers Clerk letters, direct recusal notices, repeated procedural nonparticipation, changes over time, and companion-docket traps such as Loper Bright/Relentless and Harvard/UNC.

Only confirmed `recused` findings change the bench. Uncertainty continues normally and appears in private review notes. The metadata adapter preserves all seats for the current Court and restores a confirmed recused justice omitted from Oyez’s membership list. The video renderer uses grayscale with 50% opacity and a dark `Alito recused`-style surname label on a light background without text glow. Other justices retain their positions and styling. No caveats are added to case descriptions or YouTube descriptions.

The square podcast artwork currently uses its approved static bench assets; this treatment applies to the video renderer. Completed videos are not automatically rerendered or replaced when the workflow is updated.

Validation covers evidence/identity checks, restored bench order, uncertainty retaining the normal portrait, and checking a docket while preserving short Oyez HTML exactly. The production renderer was inspected at 1920×1080 and reports opacity `0.5`, label `Alito recused` and text shadow `none`.
