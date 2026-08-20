# Offline corpus and retrieval methods review — 2026-08-19

## Status

This is a design and preregistration input for the successor offline-corpus
release. It does not change the interpretation of the frozen RC3 development
benchmark or promote an LLM judge to agronomist-equivalent measurement.

## Verified repository baseline

- The active 2026-08-14 profile contains the Canadian master, project safety
  and conceptual corpora, SoilWise, two graph artifacts, and a compact NRCS
  U.S. ecological-site reference projection.
- Historical NRCS full-corpus records had document identity but no portable
  record-level locator in the current runtime representation. The successor
  release adds a raw-source hash, portable archive path, source URL, extractor
  identity, chunk index, and exact text hash; it does not invent unavailable
  page or character offsets.
- The archive inventory is evidence of historical bytes, not a licence grant,
  currentness confirmation, or source-quality result.

## Primary research and resulting choices

| Source | Relevant result | Adopted control |
| --- | --- | --- |
| [BEIR (Thakur et al., 2021)](https://arxiv.org/abs/2104.08663) | Lexical, dense, late-interaction, and reranking approaches should be compared across heterogeneous tasks; BM25 is a robust baseline. | Keep BM25 as a fixed baseline and require a source-grounded held-out comparison before adding hybrid retrieval or reranking. |
| [RAGChecker (Ru et al., 2024)](https://arxiv.org/abs/2408.08067) | Retrieval and generation failure modes need separate diagnostics. | Report retrieval location/authority metrics separately from answer or judge metrics; no composite score. |
| [T²-RAGBench (Strich et al., 2026)](https://aclanthology.org/2026.eacl-long.8/) | Text-and-table retrieval needs realistic retrieval-before-reasoning evaluation. | Preserve table structure and source locations; include table/layout cases in the successor suite. |
| [TableRAG (Yu et al., 2025)](https://aclanthology.org/2025.emnlp-main.710/) | Flattening heterogeneous tables loses structural information relevant to retrieval and reasoning. | Store table title, headers, units, row/cell coordinates, and rendered evidence separately from plain prose chunks. |
| [Dolma (Soldaini et al., 2024)](https://arxiv.org/pdf/2402.00159) | Dataset curation needs documented, inspectable stages rather than opaque aggregate quality claims. | Retain raw and derivative hashes, extraction recipes, duplicate decisions, quality ledgers, and admission receipts. |

## Non-negotiable data controls

1. A runtime row needs a source ID, rights disposition, jurisdiction,
   retrieval policy, source URL, raw SHA-256, exact text SHA-256, and a
   documented extraction locator. Missing evidence is a release failure, not a
   default value.
2. Exact normalized duplicates are retained once in deterministic source order.
   Near-duplicate candidates are clustered and receive an explicit disposition.
3. Canadian official/provincial evidence is the default authority for Canadian
   questions. U.S. material is clearly marked analogue context; community
   material is non-decisive and requires separate redistribution and privacy
   admission before runtime loading.
4. Citation lists, page markers, navigation, and repeated headers remain
   provenance metadata unless a source-specific review declares them answer
   evidence.

## Evaluation and promotion protocol

The successor suite is source-grounded and fixed before retriever tuning. It
contains Canadian official retrieval, explicit U.S.-analogue retrieval,
community-boundary negatives, table/layout records, negative retrieval, and
spatial-context cases. It reports Recall@1/3/7, nDCG@7, exact source-locator
validity, jurisdiction/authority compliance, duplicate leakage, table fidelity,
and deterministic rebuild identity.

A hybrid or reranking method may become selectable only if it improves the
predeclared held-out retrieval endpoints over BM25 under paired case
resampling, causes no source-locator or jurisdiction/authority violation, and
does not weaken the Canadian-authority boundary. These are development
measurements, not population estimates or agronomist-equivalence evidence.

## Model and judge boundary

Models remain pinned within a release. New models are assessed only at major
release review, through the same frozen successor retrieval suite and a
recorded model/configuration receipt. The post-hoc Luna semantic judge is
reported as an advisory instrument: order, response length, self-preference,
rubric-consistency, and candidate-output sensitivity are audited before any
paper visualization, and its scores have no promotion authority.
