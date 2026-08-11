# Public verification data

This directory is evaluation-only. Its contents must not be copied into model
training, retrieval corpora, prompt examples, answer-repair rules, or internal
benchmark sources.

`crop_benchmark_english_180_v3_source.jsonl` is the active deterministic 180-question
English subset of `AI4Agr/CROP-benchmark`, revision
`1b569e9fec64fc7ad868e6e383fa9846b00ce69d`. It contains 60 questions from
each published difficulty level. Selection holds the correct option's word-length
rank counts to 44/45/45/46, and options are deterministically permuted so the
correct Roman-numeral position is exactly balanced. Question and option text
are otherwise preserved. See the adjacent source manifest for the import receipt.

Public v1 and v2 are retained only as retired development evidence. Four v1 rows
were used in an MLX execution/parser smoke. The entire labelled v2 source profile
was exposed during developer-side inspection without a model run. All 220 source
rows are permanently excluded from v3 and must not be reported as held-out results.

The source benchmark is licensed CC BY-NC 4.0. Cite:

> Hang Zhang et al. “Empowering and Assessing the Utility of Large Language
> Models in Crop Science.” NeurIPS 2024 Datasets and Benchmarks Track.
> DOI: 10.52202/079017-1669.

This derived profile measures objective crop-science multiple-choice transfer.
It does not validate Canadian jurisdictional advice, field diagnosis, product
labels, agronomic safety, or grower usefulness.
