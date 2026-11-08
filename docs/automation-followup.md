# Automation follow-up: measured extraction and research results

Prepared October 11, 2026; updated October 12 with the completed [Cloud Run alignment benchmark](/Users/dominik/GitHub/scotus-videos/docs/research/alignment-decision.md) and larger Jones Day portrait. This supplements the [cloud design](/Users/dominik/GitHub/scotus-videos/docs/cloud-automation.md). It incorporates the preference for Cloud Run Jobs, one initial processing policy for all cases, and Codex CLI using the existing ChatGPT subscription. The PDF research below describes the initial comparison; native extraction has subsequently become the default in the self-aligned tool, with paragraph/punctuation validation in the [workflow notes](/Users/dominik/GitHub/scotus-videos/self-aligned/README.md). The advocate cache and YouTube channel were not changed.

**Advance advocate discovery works**

The Court publishes a monthly Hearing List alongside its argument calendar. It names the scheduled arguing attorneys, with their sides and locations, including arguing amici. This is substantially more useful for advance portrait work than guessing from counsel-of-record entries. On October 11, the [October hearing list](https://www.supremecourt.gov/oral_arguments/hearinglists/HearingList-October2026.pdf) already provided the following for next week:

| Argument date | Case | Scheduled advocates |
| --- | --- | --- |
| October 13 | Beaird v. United States, 25-5343 | Kevin Joel Page, petitioner; Eric J. Feigin, respondent in support of vacatur; Anthony J. Dick, Court-appointed amicus |
| October 14 | Salazar v. Paramount Global, 25-459 | Joshua I. Hammack, petitioner; Paul D. Clement, respondent |

The [October calendar](https://www.supremecourt.gov/oral_arguments/argument_calendars/MonthlyArgumentCalOctober2026.pdf) lists October 12 as a legal holiday, with those two arguments on October 13–14. The [October 13 Day Call](https://www.supremecourt.gov/oral_arguments/daycall/Day%20Call_10-13-26.pdf) was already available and assigns Beaird's three advocates 20 minutes each. Follow the [index page](https://www.supremecourt.gov/oral_arguments/calendarsandlists.aspx), refresh amended publications and reconcile the final transcript appearances. Lists can change; this is direct evidence of the scheduled speakers, not a guarantee that everyone appears.

**Docket JSON is the right identity supplement**

I fetched and inspected the [25-332](https://www.supremecourt.gov/RSS/Cases/JSON/25-332.json), [25-5343](https://www.supremecourt.gov/RSS/Cases/JSON/25-5343.json) and [25-459](https://www.supremecourt.gov/RSS/Cases/JSON/25-459.json) JSON records. Important fields are:

| Fields | Use |
| --- | --- |
| `PetitionerTitle`, `RespondentTitle`, `RelatedCaseNumber`, `LowerCourt`, `QPLink` | Caption, consolidated cases, posture and question-presented source |
| `ProceedingsandOrder[].Date`, `.Text`, optional `.Links` | Argument dates, divided-argument orders, appointed amici and linked documents |
| `Petitioner[]`, `Respondent[]`, `Other[]` | Attorney records, including written amici |
| `Attorney`, `IsCounselofRecord`, `Title`, `Address`, `City`, `State`, `PartyName` | Full names and firm/agency/city evidence for matching identities |

Trim strings, allow null and missing fields, and treat HTML in proceeding text as data. Do not interpret every `Other` attorney as a speaker. Do not infer the argument term from `sJsonTerm`: a 2025 docket can be argued in October Term 2026.

The distinction between counsel of record and arguing counsel is concrete here: Beaird's respondent attorney entry identifies D. John Sauer, while the hearing list identifies Eric J. Feigin as the scheduled speaker. Slaughter's respondent record uses **Amitabh Agarwal**, while its argument proceeding uses **Amit Agarwal**. Store source names as aliases, then assign a persistent local person ID; Oyez IDs need not remain mandatory. Match uppercase transcript appearances against those aliases with firm/city evidence, and surface ambiguous matches.

**Photo proof of concept succeeded, with a useful difficult example**

At the user's request, a subagent researched an upcoming lawyer missing from the local cache. It first tried Kevin Joel Page, the Dallas federal defender in Beaird. Ten text searches and two image searches found placeholders or unrelated people; it did not find a verified usable portrait within that budget.

It then found **Anthony J. Dick**, another Beaird advocate missing from the cache. The docket and his [Jones Day biography](https://www.jonesday.com/en/lawyers/d/anthony-dick) agree on his name, employer, Washington location and professional email. His named [professional speaker biography](https://fedsoc.org/bio/anthony-dick) supplies an accessible portrait. Jones Day's own image URL returned HTTP 403; the alternative source downloaded successfully.

![Anthony J. Dick](/Users/dominik/GitHub/scotus-videos/docs/research/advocate-photo-poc/anthony_j_dick.source.jpg)

The unchanged original is **330 × 330 pixels**, clear and suitable for a small advocate avatar. This was identified from the named profile's association with the image, not facial recognition. Two text searches and one image search were spent on Dick; roughly ten minutes were spent overall, including the unsuccessful Page search, verification and downloads. This was a research feasibility test in the current Codex session, not a benchmark of a deployed headless CLI worker.

The follow-up retrieved Jones Day's **1068 × 728** portrait through native Chrome's ordinary Save Image As action. It is now the preferred [research image](/Users/dominik/GitHub/scotus-videos/docs/research/advocate-photo-poc/anthony_j_dick.jonesday.webp). Direct Python/curl requests still returned Cloudflare 403; success in the existing browser session does not establish that a fresh cloud browser will work. The research record preserves both sources and the retrieval diagnostics.

The [research record](/Users/dominik/GitHub/scotus-videos/docs/research/advocate-photo-poc/README.md) and [machine-readable provenance](/Users/dominik/GitHub/scotus-videos/docs/research/advocate-photo-poc/provenance.json) preserve sources, queries, rejected candidates, original image URL, dimensions and hash. Production should retain this evidence and use a bounded search with agency-logo/initials fallback. One successful lawyer does not establish the success rate for federal defenders or other hard cases.

**YouTube title pattern verified using the refreshed credential**

Read-only YouTube API calls returned **332 uploads** for Supreme Court Oral Argument Transcripts. Credential refresh occurred only in memory; no credential file or channel content was modified. The complete [retrieved title list](/tmp/scotus-automation-evaluation-20261011/youtube-titles.md) remains in the local scratch research directory because it may include unlisted entries. The default recent pattern is:

```text
Oral Argument on {plain-English topic}: {short case name}
```

Twenty-six of the latest thirty entries matched that form. Representative titles retrieved from the channel:

- `Oral Argument on birthright citizenship: Trump v. Barbara`
- `Oral Argument on firing a Federal Reserve governor: Trump v. Cook`
- `Oral Argument on mutual funds and activist investors: FS Credit. v. Saba Capital Master Fund`
- `Oral Argument on preaching outside the designated protest area: Olivier v. Brandon, Mississippi`

Matching topic phrases had a median length of five words and a range of one to ten. Preserve this natural descriptive style rather than enforcing a 1–3-word cap or introducing a pipe-separated title. Historical landmark-case and argument-plus-opinion videos use distinct conventions and should be separate templates. Generate a factual topic from the question presented and argument, shorten the caption as the existing channel does, and validate the complete title length in code.

**Native PDF extraction can match or improve on the saved Adobe text**

I tested Poppler default/layout/raw extraction and a bounding-box reconstruction against the saved PDF/TXT pairs. I also tested pypdf, pdfminer, pdfplumber and PDFium on four complete cases. The full [metrics JSON](/Users/dominik/GitHub/scotus-videos/docs/research/transcript-extraction-metrics.json) records individual results and parser structure comparisons.

| Method | Comparable cases | Reference word tokens | Differing tokens | Difference rate |
| --- | ---: | ---: | ---: | ---: |
| Poppler default with basic cleanup | 12 | 260,142 | 36,728 | 14.1184% |
| Poppler `-raw` with cleanup | 12 | 260,142 | 49 | 0.0188% |
| Poppler `-layout` with cleanup | 12 | 260,142 | 36 | 0.0138% |
| Poppler native coordinates, reconstructed rows | 12 | 260,142 | 36 | 0.0138% |
| pypdf with cleanup | 4 | 90,979 | 28 | 0.0308% |
| pdfminer with cleanup | 4 | 90,979 | 54 | 0.0594% |
| pdfplumber with coordinate crop | 4 | 90,979 | 12 | 0.0132% |
| PDFium with coordinate crop | 4 | 90,979 | 12 | 0.0132% |

These are normalized ordered word-token differences from `difflib.SequenceMatcher`, **not a ground-truth error rate, formal word-error rate or alignment accuracy**. Comparison covers the spoken proceedings body, ignores punctuation/whitespace, and normalizes Unicode, case and apostrophes. Saved TXT files may contain manual edits. Six of the twelve coordinate extracts matched the normalized Adobe token sequence exactly. The saved `63689` pair was excluded: its TXT/PDF page counts differ and its TXT retains gutter artifacts, making it an unsuitable reference pair.

The useful improvement is **layout-aware cleanup**, not a more expensive model. The current Court PDFs contain native words. Remove the left line-number gutter, top heading/page number and footer by coordinates, then sort actual transcript rows from top to bottom and their words from left to right. Poppler's default block ordering can scatter numbers or rearrange nearby text. A simple regex that deletes leading digits can also swallow spoken numbers, as the current parser already notes.

The prototype used a crop of `x >= 140 pt`, `80 <= y <= 730 pt` on the sampled 612 × 792 pt pages, grouped baselines within 0.1 pt, and preserved newline-separated page boundaries. This fixed crop is appropriate to the fixtures, not yet a production layout detector. Preserve indentation, page/line references and word boxes for paragraphs; parse front matter and appearances separately. Keep punctuation and capitalization verbatim in display text, with a separate normalized alignment representation and offset map.

Most observed token differences came from the Adobe text joining words adjacent to dashes: for example `andswitch`, `viewpointand` and `ofpowers`. One substantive difference was visible on printed page 24 of [24-43_n6io.pdf](/Users/dominik/GitHub/scotus-videos/self-aligned/24-43/24-43_n6io.pdf): Adobe merged/reordered short Sotomayor and Kavanaugh interjections, while coordinate reconstruction followed their actual printed order. That was checked visually against the PDF. It explains the coordinate parser producing 437 speaker turns instead of Adobe's 435 for that case.

With the existing parser, eleven of twelve coordinate extracts preserved the reference speaker sequence. Eight preserved the exact paragraph count; three had one fewer paragraph, and the remaining case was the corrected speaker-order example. This establishes a strong starting point, but paragraph boundaries and verbatim punctuation still need focused validation before replacing the current export step. Local coordinate extraction took seconds per argument; this was not a controlled cloud-performance benchmark.

**Adobe can be used from Linux through its API if needed**

[Adobe PDF Extract API](https://developer.adobe.com/document-services/docs/overview/pdf-extract-api/) is a cloud REST service with supported SDKs; it returns structured text, reading order and bounds without a desktop Acrobat installation. It is a plausible fallback for PDFs that fail native-layout validation, but it has not been tested here and should not be assumed identical to Reader's “Save as Text” output.

Adobe currently provides **500 Document Transactions/month** on the free tier; Extract consumes **one transaction per five pages**. A 150-page transcript therefore consumes 30 transactions, so the free allowance covers sixteen such transcripts, not 500. Native Extract supports up to 400 pages and a 100 MB input. Paid pricing requires a separate purchase arrangement. These are the current [usage limits](https://developer.adobe.com/document-services/docs/overview/limits) and [pricing terms](https://developer.adobe.com/document-services/pricing/). If native extraction proves adequate, reserve Adobe for exceptions; compare its API on the same fixtures before committing to it.

**Modern forced-alignment candidates**

The [October 12 benchmark](/Users/dominik/GitHub/scotus-videos/docs/research/alignment-decision.md) installed and exercised CTC with MMS and English Wav2Vec2 checkpoints, plus Qwen3, on Cloud Run CPUs and one L4. All four configurations completed successfully under the $1 exploratory budget. NeMo and MFA remain additional candidates; they were not benchmarked.

| Candidate | Why evaluate it | Main consideration for this project |
| --- | --- | --- |
| [NeMo Forced Aligner](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/tools/nemo_forced_aligner.html) | Maintained NVIDIA tool; accepts supplied reference text; emits token/word/segment timestamps; documents long-recording options | Additional candidate if full-case CTC validation reveals a limitation. Use a compatible CTC model; local attention or supported buffered inference can bound inference memory. |
| [Qwen3-ForcedAligner-0.6B](https://github.com/QwenLM/Qwen3-ASR) | Recent dedicated aligner; direct official-text alignment; supports batching | Documented maximum input is five minutes. Long arguments need matched audio/text windows before fine alignment. |
| [ctc-forced-aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner) | Lightweight reference alignment with CPU/CUDA support and windowed acoustic emissions | Useful CPU/GPU cost comparison. Pin a tested revision; emission windows do not eliminate all long-sequence alignment memory costs. |
| [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/en/latest/user_guide/workflows/alignment.html) | Maintained CPU baseline; pronunciation/G2P support for names | Worth measuring on conversational material. Dictionary/G2P and segmentation need attention; it is not an automatic speed guarantee. |
| [WhisperX](https://github.com/m-bain/whisperX) | Widely used ASR-plus-alignment pipeline; alignment component can consume prepared text segments | Optional coarse timing/anchoring helper. Keep official transcript as the display/reference text; numbers and overlapping speech remain difficult. |

The measured first pilot is **ctc-forced-aligner with the English Wav2Vec2 checkpoint on CPU**, compared with MMS and retaining L4 as a fast option. On 339.11 seconds of distinct audio, English CTC took 30.77 seconds on four CPUs; MMS took 85.01 seconds on four CPUs and 3.82 seconds on L4. These exclude loading and startup. Their agreement with saved Gentle timings was similar, which does not establish accuracy. CTC produced one zero-duration spoken token out of 904, the numeric expression “2020”; Qwen produced 45–46, consistent with its coarser 80 ms bins and some boundary effects. The [subsequent full-argument validation](/Users/dominik/GitHub/scotus-videos/docs/research/alignment-decision.md) now exercises 32 overlapping windows across an 80-minute recording. Word-level wildcards fixed an opening displaced by 2.3 seconds under the original edge-only setting; all 529 paragraphs and 372 speaker starts mapped. Paragraph agreement had a median of 70 ms and a 95th percentile of 510 ms, with five of 425 comparable starts differing by more than a second. Independent coarse matching and numeric normalization still need implementation checks. MFA remains an unmeasured CPU candidate; its [3.4.3 release](https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner/releases/tag/v3.4.3) was published October 8, 2026.

The added [Gentle cloud comparison](/Users/dominik/GitHub/scotus-videos/docs/research/alignment-decision.md) completed in 64.18 seconds on two CPUs and 58.13 seconds on four, leaving 22 of its 914 spoken units untimed. Its acoustic-model and vocabulary hashes exactly match the installed Mac app. The published Docker image uses a 2017 runtime, and recreating the same verified-source windows with its old FFmpeg produced different PCM hashes. CPU hosts also varied. These are useful observed cloud timings, with those limits on controlled accuracy comparisons. Gentle remains a viable CPU baseline/fallback. The archived full-case English CTC validation supports proceeding with the CPU adapter, while preserving Gentle fixtures for comparisons. The cumulative estimate including Gentle and both full validations is $0.60–$0.66 before allowances, within the original $1 limit, and all temporary resources were removed and verified.

Use one alignment adapter whose output maps reference-word offsets to absolute audio times. For chunked approaches, obtain coarse anchors, match the approximate recognized text to the official text, create corresponding audio/reference windows, fine-align in batches and reconcile overlaps. Never split audio and text independently by equal proportions. Preserve the official text even if coarse ASR recognizes something different. Normalize citations, numbers and abbreviations only in the aligner representation, with a reversible display mapping.

Measure speaker-change/paragraph anchors, interruption boundaries, untimed spans, accumulated drift, long-case memory and total allocated runtime. The display's 20 fps resolution is 50 ms; dependable paragraph and speaker boundaries matter more than phonetic precision. A low count of untimed words is not proof of accurate times. Compare ordinary, long and interruption-heavy samples with saved Gentle outputs and manually checked audio boundaries.

**Cloud Run remains suitable, including GPU alignment**

[Cloud Run Jobs supports GPUs](https://docs.cloud.google.com/run/docs/configuring/jobs/gpu). An L4 job requires at least four vCPUs and 16 GiB RAM, one GPU per instance, and non-zonal-redundant configuration. Iowa is supported, subject to quota. Keep enrichment and rendering on CPU; allocate the GPU only to alignment.

For this project, the automatic quota grant failed in Iowa but succeeded in Northern Virginia and Belgium: the API reported three L4s in each after diagnostic job creation. No quota application was needed. The measured GPU execution ran in Northern Virginia. Keep registry, model cache and workers in one region in production. Fetch weights and Court media inside the cloud; the operator's connection is metered. The successful benchmark cached weights via a capped Cloud Build step after shared Cloud Run IP downloads hit Hugging Face HTTP 429.

At the current Iowa [job rates](https://cloud.google.com/run/pricing), four CPU cores cost $0.000072/second, 16 GiB RAM $0.000032/second, and the non-zonal L4 $0.0001867/second: **$1.04652/hour** together before allowances. Five allocated minutes are **$0.08721**; ten are **$0.17442**. These figures describe billed runtime, including applicable startup/model-loading time, not a claim that a full argument aligns in five minutes. Benchmark a real argument including cold start and model loading.

Start one ordinary queue for all cases. Five-minute discovery polling on argument days, advance portrait preparation and 4–8 CPU render tasks are sensible initial settings. The latency tradeoffs are polling delay, alignment time, render concurrency, upload bandwidth and YouTube processing. Use identical source hashes and frame manifests regardless of eventual capacity choices. Keep the existing parallel-render design: independent complete display state, exact integer frame ranges, local chunk encoding, video concat without re-encoding and one continuous audio mux.

**Codex CLI subscription use is feasible, with private auth handling**

Codex supports [ChatGPT sign-in](https://learn.chatgpt.com/docs/auth) and [noninteractive structured output](https://learn.chatgpt.com/docs/non-interactive-mode). Use `codex exec`, a pinned output schema, bounded live search and a private task workspace containing Court data and trusted instructions. The worker needs research tools and portrait storage; publication remains an application stage with separate YouTube credentials. Included usage is subject to the account's [subscription limits](https://learn.chatgpt.com/docs/pricing); exhausted allowance should queue work rather than trigger API billing.

OpenAI's [advanced account-auth automation guide](https://learn.chatgpt.com/docs/auth/ci-cd-auth) documents built-in token refresh and requires keeping the refreshed auth file for subsequent runs. It permits a trusted private serialized workflow and explicitly excludes public/open-source repository workflows. This repo is public: put the account-auth worker and its deployment configuration in a separate private control project; pass it source data rather than running this public checkout with the credential. That separation is the proposed application design, not an exception granted by the documentation.

For ephemeral Cloud Run workers, I would implement a global auth lease: read the latest Secret Manager version, copy it to a writable private auth directory, run Codex, persist any updated auth file as a new secret version, then release the lease. A read-only mounted secret alone cannot support auth-file write-back. Acquire the lease across job executions; task `parallelism=1` by itself does not prevent two executions from overlapping. Use one dedicated cloud auth stream instead of sharing the desktop's rotating auth file. Renderer jobs can still run concurrently. A failed write-back needs reconciliation before restoring an older token copy.

The Cloud Run implementation, Codex sandbox compatibility and refresh/write-back path have not yet been exercised. These belong in the deployment proof of concept. The completed portrait search demonstrates research capability and identity handling, independently of those deployment details.

**Next implementation decisions**

Native coordinate extraction is now the default, with an explicit Adobe desktop fallback; all 13 archived PDFs passed extraction/parsing, and the twelve comparable references passed the word and punctuation audit. Continue with the Cloud Run architecture, monthly-hearing-list prefetch and JSON docket matching. Implement the compatibility adapter for English CTC CPU with word-level wildcards, using the completed caption/full-case validation. Reuse the archived recordings to test independent coarse anchors, overlap reconciliation, numeric normalization and difficult display boundaries before replacing Gentle. The default MMS weights carry a [noncommercial licence](https://huggingface.co/MahmoudAshraf/mms-300m-1130-forced-aligner), which the operator accepted for this nonmonetized channel. Preserve the observed channel title format. Then connect the private Codex worker to the deterministic pipeline, validate historical cases and durable upload retries, and enable scheduled production once the output checks pass.
