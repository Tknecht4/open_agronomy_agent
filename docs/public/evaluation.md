# Evaluation contract

Open Agronomy Agent separates product checks from evaluation claims. A passing
test, retrieval trace, or benchmark receipt does not establish agronomist
equivalence, field-outcome validity, or a grower recommendation.

The canonical internal benchmark is `open_agronomy_canadian_performance_v1`:
241 project-authored Canadian field questions. It is a development instrument,
not a certification exam or a representative sample of agronomy work.

`open_agronomy_successor_development` is the separate 256-case regression
suite for the active source-exact corpus. It retains the 241 exposed
project-authored cases and adds U.S. NRCS MLRA retrieval probes, an Ontario
structured-table control, and community/jurisdiction boundary controls. It is
exposed and non-claim-eligible: it detects source-trace, authority-boundary,
and orchestration regressions rather than unbiased model performance.

## Frozen arms

| Arm | Input and behavior |
|---|---|
| `raw_model` | User question only; no kernel, retrieval, verifier, or post-processing |
| `baseline` | Shared kernel and answer contract; no retrieval or verifier |
| `kernel_field_context` | Kernel plus the structured crop, region, jurisdiction, and management context used by the full arm |
| `agronomic_rag` | Kernel plus governed retrieval, evidence intervention, and configured validation |

The primary matched contrast is raw model versus the governed system.
Intermediate arms localize changes to added instruction, field context, or
knowledge/evidence bundles; they do not isolate individual component effects.

## What the harness measures

- Canadian decision-quality cases retain reference points, material-error
  boundaries, and field context for independent review.
- Sixteen arithmetic cases have structured reference values, units, and numeric
  tolerances.
- Source identity, retrieval, evidence, tool, language, and route traces are
  interface capabilities, not answer-quality scores.
- The runner records exact messages, context packets, outputs, scores, and
  identities in a private local SQLite database. That database is not a public
  source artifact.

Lexical-contract diagnostics are reported only where their contract is defined;
they are not agronomic accuracy. Automated semantic judges are advisory triage
only and cannot substitute for blinded, calibrated agronomist review. There is
no valid single composite score.

## Retrieval and corpus checks

The source-grounded retrieval suite is run separately from model generation.
It checks expected-source Recall@1/3/7, nDCG@7, source-locator validity,
jurisdiction/authority compliance, duplicate leakage, table fidelity, latency,
and reproducibility. Exact BM25 is the fixed baseline; hybrid, dense, or
reranking changes require a separately frozen held-out comparison and zero
authority, jurisdiction, privacy, or source-locator violations.

The active U.S. NRCS pack is evaluated as explicit U.S. analogue context. It
may explain a U.S. MLRA/ecological-site comparison but cannot establish a
Canadian label, law, rate, threshold, calibration, diagnosis, or field
condition. A public Canadian table can be interpreted with its source and
coordinates; it is not field truth or a prescription.

Run the current corpus checks from the repository root:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_runtime_corpus.py
PYTHONPATH=src .venv/bin/python scripts/audit_offline_corpus_successor_quality.py --fail-on-gap
PYTHONPATH=src .venv/bin/python scripts/evaluate_offline_corpus_retrieval.py \
  --config configs/rag.yaml
```

## Reproducible runs

The runner binds suite hash, interface contract, arm contract, executable source
snapshot, model profile, and RAG artifact identities. A partial run resumes only
when those substantive identities match. Canonical comparison arms must share
one implementation hash; a changed answer-affecting configuration requires a
new benchmark identity.

Each model-by-trial invocation also records trial ID, sample index, generation,
verification, case-order and judge seeds, cache/process policy, ordered-case
digest, observation IDs, and matched-arm keys. A completed trial is never
silently rerun. The current retention workflow requires a verified,
content-addressed private bundle before an invocation is marked complete. It
excludes only the `.eval_run.lock` coordination file and rejects symlinks and
other non-regular inputs.

## Historical checkpoints and development suites

Benchmark outputs are evidence packages, not product documentation. The public
packages preserve their contracts, measurements, limits, and regeneration
instructions without converting an exposed development result into a product
claim:

- [RC3 development checkpoint](development-benchmark-rc3-20260815/README.md):
  completed 241-case Canadian development matrix; frozen and non-claim-eligible.
- [RC1 evidence package](final-benchmark-20260812/README.md): historical
  development evidence; its advisory judge measurements do not evaluate the
  current runtime.

The former Benchmark v2 fixture is likewise an exposed internal regression
suite. Its deterministic executor and metric contracts support implementation
testing, but its cases are not untouched evaluation data.

## Claim boundary

The internal suites contain no proven real-user cohort, independent agronomist
adjudication, representative product/service sample, or field-outcome
validation. Live adapters, multi-turn diagnosis, and executable field geometry
must be evaluated separately. Do not make population-level, professional-exam,
field-performance, or agronomist-equivalence claims from these fixtures.

Future claim-bearing work requires an independently authored and reviewed,
untouched cohort; a sealed cohort commitment; predeclared reporting; and,
where semantic judging is used, a human-calibrated judge record that passes its
order-, length-, and candidate-sensitivity checks.
