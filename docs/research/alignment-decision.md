# Alignment decision — October 2026

Production uses English Wav2Vec2 with `ctc-forced-aligner` on CPU. The October 12
Cloud Run comparison covered English CTC, MMS, Qwen3 and Gentle. On 339.11 seconds
of distinct audio, English CTC took 30.77 seconds on four CPUs; Gentle took
64.18 seconds on two CPUs and 58.13 seconds on four. These inference timings
exclude model loading and startup, and do not establish alignment accuracy.

A subsequent 80-minute argument validation mapped all 529 paragraphs and 372
speaker starts. Against usable Gentle references, paragraph-start agreement had
a median of 70 ms and a 95th percentile of 510 ms; five of 425 comparable starts
differed by more than one second. Word-level wildcards corrected an opening that
had been displaced by 2.3 seconds. Gentle and Oyez were comparison sources rather
than ground truth. The exploratory total was estimated at $0.60–$0.66 before
allowances; temporary benchmark resources were removed.

Production subsequently added coarse window matching, numeric/year normalization,
overlap handling and checks focused on visible paragraph/speaker transitions.
Their regression tests live in `cloud/tests`; active alignment and speech-span
code live in `cloud/scotus_cloud/alignment.py` and `vendor/speech_spans.py`.
The completed benchmark scripts and detailed intermediate results were deleted
in the October 14 repository cleanup. No active model or production code was
removed.
