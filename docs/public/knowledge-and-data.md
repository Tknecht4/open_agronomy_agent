# Knowledge and data governance

The runtime knowledge base is selected by `data/manifests/runtime_corpus_policy.json` and loaded by `configs/rag_governed_runtime_v1.yaml`. Presence on disk is not admission.

## Admitted release knowledge

| Artifact | Rows | Runtime role | Boundary |
|---|---:|---|---|
| Canadian distributable v13 | 718 | Decisive where row policy, jurisdiction and currency allow | Uneven provincial depth; Ontario Publication 811/811F excluded |
| Ontario context v1 | 234 | Context only | Regional statistics, not field truth or calibration |
| Canadian supplements v1/v2 | 56 | Context only | Historical/regional and data-product context |
| Canadian regional context v1 | 38 | Context only | Data-product descriptions, not local applied guidance |
| SoilWise RAG + KG | 1,784 RAG rows | Context only | Soil-health concepts and relations, not a soil test |
| Compact NRCS ESD | 24,396 | Context only | United States regional profiles; never Canadian soil authority |
| Project seed/boundary corpora | 42 | Context and safety policy | Project-authored synthesis, not independent evidence |

Every admitted Canadian row carries source and lineage fields. The policy manifest also records a byte hash, evidence tier, rights status, admission reason, and runtime role for every configured corpus.

## Why processed material can be absent from runtime

Processing proves that bytes can be extracted; it does not prove that they should influence an answer or be redistributed. The following remain excluded before index construction:

- forum posts without redistribution permission or verified authorship;
- OCR/document expansions whose item-level licence snapshot or lineage is incomplete;
- copied certification competency objectives;
- answer-gap and benchmark-shaped synthesis that could leak evaluation targets;
- candidate corpus versions superseded by the rights-repaired v13 release.

The exclusion is intentional and auditable. Quarantined byte files are not required in a portable release even when their identifiers remain in the policy.

## Exam and benchmark questions

Evaluation data is not agronomic knowledge. `cca_aligned_eval.jsonl` and `cca_local_style_eval.jsonl` contain 28 project-authored questions based on topic coverage; they are neither copied certification questions nor evidence sources. The frozen 241-case internal suite and held-out AgroQA diagnostic are kept in a separate evaluation partition and never configured as RAG corpora.

## Geospatial data

Regional soil and crop layers are useful for locating priors, not for replacing soil sampling or grower records. Large generated SQLite indexes and raw downloads are excluded from Git. Small manifests and lineage receipts define what can be rebuilt or packaged in a separately verified offline bundle.

## Admission checklist

A source is eligible only after confirming item-level reuse rights, exact source URL, publisher, retrieval date, byte hash, language, jurisdiction, currency/review date, extraction lineage, evidence role, field-action boundary, and a reproducible build. High-consequence regulatory or label content should ordinarily require live authority even if a local copy exists.
