# Frozen final-round protocol

- Benchmark round: `preconference_rc1_20260811`
- Final source commit: `76644dcab85ac635cb9f976ff6c769b4a6cd4da8`
- Final branch: `codex/final-benchmark-rag-identity-fix-20260811`
- Merged `origin/main` commit: `6a0674790ac03a16978fe5192371b08a25d9056f`
- Parent release checkpoint: `ce2821dc3c7889322c74c10ca6bd4c446d383b40`
- Readiness receipt: `outputs/pre_demo_core/final_benchmark_readiness_post_rag_identity_fix.json`
- Internal suite: 241 cases, SHA-256 `5c3ce59195ac603d2dd8ec5f36f3672b3ee0c20227cdb4fd301dfe3848a83c63`
- External diagnostic: 256 AgroQA cases, SHA-256 `d15888bb4cf0ea339380a71abecdb5a5fa770829e67e616765d2d140c9365e93`
- Arms: `raw_model`, `baseline`, `kernel_field_context`, `agronomic_rag`
- Candidate profiles: Gemma 3 270M 4-bit, Gemma 4 E2B 4-bit, and Luna High
- Semantic judge: Luna High, high reasoning, `semantic_answer_quality` only
- Judge status: advisory triage; no automated promotion authority
- External-use rule: run once on the frozen finalist after internal selection; do not repair and retest this version

## Construct boundary

The internal suite contains 90 primary Canadian decision-quality cases, 31 secondary Canadian advisory-transfer cases, and 120 interface/regression cases. The latter comprise field-history lineage (32), source-answer boundaries (39), retrieval lineage (33), and objective agronomic calculations (16). These strata are reported separately. The suite has no independently adjudicated agronomist answers and no confirmed real-user Canadian questions.

## Runtime environment

- Host: Mac mini `Mac16,10`
- Processor: Apple M4, 10 CPU cores (4 performance, 6 efficiency)
- Unified memory: 16 GB
- Operating system: macOS 27.0, build 26A5388g
- Architecture: arm64
- Python: 3.12.0
- MLX: 0.31.2
- MLX-LM: 0.31.3

## Artifact contract

Every response is stored before scoring together with the exact messages, field context, context packet where applicable, implementation and model identity, timing, route/verification trace, and SHA-256 digest. Semantic judgments retain their exact prompts, outputs, per-batch receipts, and egress accounting. The canonical local database is `outputs/open_agronomy_canadian_performance_v1_rc1/full_system_benchmark.sqlite3` relative to the repository checkout.

## Pre-round repair

The first attempted final run exposed a release-path defect before any governed-RAG answer was generated: artifact identity binding evaluated every configured corpus before the corpus-governance policy removed quarantined, non-redistributable paths. The public checkpoint correctly omitted those files, causing a false missing-artifact failure. Commit `76644dc` applies the same governance partition before identity binding while preserving fail-closed behavior for any admitted missing corpus. Two regression tests discriminate those cases. The pre-fix outputs are retained in a separately labelled superseded directory and are excluded from every final table and database.

## Completion receipts

- Internal database: `outputs/open_agronomy_canadian_performance_v1_rc1/full_system_benchmark.sqlite3` (local artifact; not distributed through Git)
- Internal database SHA-256: `6e155a7ff1e40fae34741a9a81fd96b6576886c0ed1de9ba92a1a5db0faa9c6b`
- Internal canonical responses and judgments: 2,892 and 2,892
- External finalist freeze: `source_data/external_finalist_freeze.json`, written before external exposure
- External database: `outputs/open_agronomy_external_agroqa_v1_rc1/full_system_benchmark.sqlite3` (local artifact; not distributed through Git)
- External database SHA-256: `8a2acb8ebc8bf01a3d81006a899bb3edd76bf5c35fbcceeb04be5a69a066bf4b`
- External canonical responses: 512, comprising 256 raw and 256 governed responses
- External rule after exposure: no repair or retest of this implementation on the same external-set version
- Paper: four pages, compiled with Tectonic 0.16.9 and visually inspected page by page

The governed calculation result is a preserved negative finding. The registered typed calculator did not appear in any of the 16 calculation traces, so the round evaluates the actual benchmark orchestration path, not hypothetical calculator-backed behavior.
