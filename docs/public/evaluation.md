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

## Construct boundary

The checked-in construct audit separates the 241 rows into 90 primary semantic
field-decision cases, 31 secondary advisory cases, and 120 regression or
interface cases. The latter must not be averaged into an agronomic answer-
quality claim. The primary lane spans nine task categories with ten cases each
and balanced province-level coverage, but it currently contains no proven
real-user questions, independent agronomist adjudication, multi-turn primary
cases, or executable field geometries. These are explicit residual validity
gaps, not zero-valued capabilities.

Regenerate the audit with:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_canadian_field_benchmark.py
```

The expected output status is `development_construct_only`. A change that
silently upgrades this status or collapses the three reporting tiers is a
release blocker.

## Reproducibility gates

The runner locks the suite hash, interface contract, arm-contract version, executable source snapshot, model profile, and RAG artifact identities. A partial run resumes only when those substantive identities match. Release validation requires all canonical comparison arms to share one implementation hash. Dirty-checkout experiments may be retained for development, but a public result must identify the exact committed source.

## Final-round readiness

`configs/final_benchmark_round_rc1.json` is the orchestration contract for the
current development round. It freezes the internal and external suite hashes,
four arms, Gemma 3 270M and Gemma 4 local profiles, Luna High remote profile,
semantic-judge role, output location, claim boundary, and promotion policy.

Run the model-free gate from a clean checkout before any final generation:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_final_benchmark_readiness.py \
  --hub-cache /absolute/path/to/huggingface/hub \
  --egress-authorization /absolute/path/to/egress_authorization.json
```

The authorization receipt must be suite-bound and may cover only project-owned
benchmark questions, benchmark field context, candidate answers, and the
reference/rubric needed for judging. Farmer records, private field history,
credentials, and local corpus files remain excluded. Luna judging is advisory
semantic triage only; deterministic calculation and interface checks retain
their own scorers.

The canonical output directory must also be absent or empty at this gate. This
prevents an old response database or identity lock from being mistaken for the
new final round; resume is allowed only after the round has started and the
runner confirms substantive identity equality.

The gate must report `ready` and emit exact commands for all three candidates.
Run the internal matrix first, build the blinded raw-model versus full-system
review packet, freeze a finalist, and only then run the 256-item external
diagnostic once. Do not use that external result to repair and rerun the same
benchmark version.

## Final RC1 result — 2026-08-12

The completed internal database contains 2,892 responses and 2,892 advisory
judgments: three candidates by four arms by 241 cases. On the 90-case primary
Canadian decision-quality lane, the frozen raw-versus-governed comparison was:

| Candidate | Raw model | Governed system | Paired change (95% interval) |
|---|---:|---:|---:|
| Gemma 3 270M 4-bit | 2.50 | 73.13 | +70.63 (+65.46 to +75.71) |
| Gemma 4 E2B 4-bit | 54.71 | 77.93 | +23.22 (+17.60 to +28.59) |
| Luna High | 89.82 | 83.38 | -6.45 (-11.52 to -1.18) |

These are automated development scores, not agronomist ratings. The negative
Luna result and intermediate-arm analysis show that system intervention must
be calibrated to generator capability rather than assumed to help every model.
The benchmark path also failed to call the typed calculator, leaving all three
governed candidates at 0/16 objective calculation cases. That failure is
preserved as an orchestration defect for the next development round.

The one-time held-out AgroQA diagnostic used the frozen Gemma 4 full-system
finalist. Normalized reference-token F1 changed from 0.0508 raw to 0.0595 with
the governed system. Because the source questions are Ugandan and the answers
were not revalidated for Canadian practice, this is geographic transfer
evidence only and the exposed implementation must not be tuned and rerun on the
same set version.

The [technical paper and public evidence package](final-benchmark-20260812/README.md)
contain the full interpretation, task-family summaries, paired intervals,
orchestration diagnostics, frozen finalist receipt, and plotting inputs. Exact
answers and SQLite databases remain local, with checksums and counts retained
for separately transferred artifact verification.
