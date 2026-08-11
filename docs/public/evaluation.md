# Evaluation contract

The canonical internal benchmark is `open_agronomy_canadian_performance_v1`: 241 project-owned Canadian field questions. It is a development instrument, not a certification exam and not evidence of agronomist equivalence.

## Frozen arms

| Arm | Input and behavior |
|---|---|
| `raw_model` | User question only; no kernel, retrieval, verifier, or post-processing |
| `baseline` | Shared kernel and answer contract; no retrieval or verifier |
| `kernel_field_context` | Kernel plus the same structured crop, region, jurisdiction and management context used by the full arm |
| `agronomic_rag` | Kernel plus governed retrieval/evidence intervention and configured validation |

The primary causal comparison is raw model versus the governed system. Intermediate arms identify whether changes arise from instructions, field context, or knowledge/evidence handling.

## What is measured

- Canadian decision-quality cases preserve reference points, material errors, missing-evidence boundaries and field context for review.
- Sixteen arithmetic cases have structured reference values, units and numeric tolerances.
- Route, retrieval, evidence, tool and output-contract traces are checked as interface capabilities.
- All questions, exact messages, context packets, responses, scores and identities are stored in a local SQLite result database.

Automated semantic judges are advisory triage. They can help find regressions but cannot substitute for blinded, calibrated agronomist review. Lexical proxy scores are reported only for lanes where their contract is defined; there is no valid single composite “agronomy intelligence” score.

## External diagnostic

`open_agronomy_external_agroqa_v1` contains 256 held-out AgroQA items. It is external transfer evidence from a different geography and task distribution. It must not be mixed into the internal suite, used for iterative prompt tuning, or presented as Canadian validation.

Historical CROP multiple-choice imports are quarantined because audit found material answer-key problems. CCA-aligned questions are project-authored coverage probes and make no professional-exam claim.

## Reproducibility gates

The runner locks the suite hash, interface contract, arm-contract version, executable source snapshot, model profile, and RAG artifact identities. A partial run resumes only when those substantive identities match. Release validation requires all canonical comparison arms to share one implementation hash. Dirty-checkout experiments may be retained for development, but a public result must identify the exact committed source.
