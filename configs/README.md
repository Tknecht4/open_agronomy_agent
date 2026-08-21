# Configuration contracts

## Purpose and status

`configs/` contains runtime, model, retrieval, benchmark, evaluation, and historical/candidate contracts. File presence is not activation. A config becomes authoritative only when selected by an entry point or referenced by a higher-authority release/evaluation contract.

## Active native profiles

| Purpose | Default or documented profile | Notes |
|---|---|---|
| Native quick-start model | `model.yaml` | Exact model/revision; local weights separately provisioned |
| Governed runtime retrieval | `rag.yaml` | Active source-exact Canadian evidence plus explicit, bounded U.S. NRCS analogue access |
| Product-selection registry | `runtime_profiles.json` | Sole active/default model and RAG admission surface; file presence is not activation |
| RC3 development checkpoint | `final_benchmark_round_rc3.json` | Completed and frozen exposed-and-tuned, three-trial `development_rerun_nonclaim` under runtime v2; not claim-eligible and not a Benchmark v3 result |
| Successor corpus development | `open_agronomy_successor_development.json` | Exposed 256-case four-arm regression using active `rag.yaml`; covers U.S. analogue retrieval, Ontario-table handling, and authority boundaries. Any answer-affecting change requires a new run identity; it is not sealed or claim-eligible evaluation. |
| Benchmark lifecycle registry | `benchmark_round_lifecycle_v1.json` | Append-only completion status and checkpoint receipts; keeps frozen launch-plan bytes unchanged |
| RC1 orchestration | `final_benchmark_round_rc1.json` | Frozen historical benchmark contract, not current-code validation |
| RC2 development rerun | `final_benchmark_round_rc2.json` | Frozen historical planning/evidence identity; not the current default |
| Benchmark v2 regression | `open_agronomy_benchmark_v2.json` | Exact cases were exposed and used for tuning; contract QA only, never claim-eligible; fresh untouched v3 required for evaluation |
| Benchmark v3 protocol | `open_agronomy_benchmark_v3_protocol.json` | Public 17-stage protocol only; no sealed holdout is present or implied |
| Capability conformance | `benchmark_capability_conformance_v1.json` | Deterministic registry/executor fixture contract, not model or field performance |

`rag_governed_runtime_v1.yaml` and `rag_final_mvp.yaml` remain public solely as
frozen RC1/RC2 identity inputs. They are nonselectable and may reference legacy
payloads intentionally absent from the public package. `benchmark_models/`,
`frozen/`, numbered candidates, feasibility profiles, and old interface
versions are evaluation or historical artifacts. Do not switch production
behavior because a newer-looking filename exists.

## RC3 egress and completed execution boundary

The completed RC3 run was governed by `final_benchmark_round_rc3.json`, which requires
`open_agronomy_agent.benchmark_egress_authorization.v4`. The checked-in
`benchmark_egress_authorization.template.json` is deliberately unauthorized and
is bound to benchmark ID
`open_agronomy_canadian_performance_v1_runtime_v2`. A human authorization must
match the exact global class taxonomy, the exact
`payload_classes_by_phase_and_arm` mapping, and the plan's suite-case,
runtime-artifact, and static-prompt contract hashes. Raw receives only the
frozen question; baseline adds the system/answer-contract prompt; kernel adds
synthetic field context; the RAG candidate additionally receives selected
public runtime document excerpts and public runtime graph evidence. RAG
verification receives question, prompt, selected public document excerpts,
candidate draft, and verifier evidence. No other verification arm is admitted.
Deterministic tool results remained local and bypassed Luna; governed guard notes
are frozen prompt components, not a tool-result payload class.

The plan is retained byte-for-byte as frozen launch evidence. Completion is
recorded separately in `benchmark_round_lifecycle_v1.json`, which binds the
plan hash, measured commit, public checkpoint receipts, nine trials, 36 arm
executions, and 8,676 observations. Readiness combines those two records and
fails closed; neither authorizes appending observations or reusing the completed
identity for a successor run.

The exact forbidden classes are `farmer_records`, `private_field_history`,
`credentials`, and `whole_local_knowledge_corpus_files`. RC3 forces private
knowledge off for all four arms through
`AGRONOMY_AGENT_PRIVATE_KNOWLEDGE=disabled` and child
`--private-knowledge-policy disabled`. Its judge is `disabled_for_rc3`; there is
no judge payload class, a supplied judge calibration is rejected, and generated
commands never contain `--judge`. The declared judge seed is identity-only and
has `judge_seed_application=not_requested`.

## Inputs and outputs

Inputs are YAML/JSON records consumed by launchers, resource loaders, audits, or benchmark runners. Outputs are deterministic runtime identities and selected artifacts. Exact config bytes and referenced artifact hashes must be bound into benchmark/release receipts.

## Invariants

- Pin model IDs and revisions for reproducible runs.
- Keep active runtime corpus admission in `data/manifests/runtime_corpus_policy.json`; paths alone do not authorize use.
- Admit an active profile through `runtime_profiles.json` only after corpus and configuration audits pass; a candidate/frozen file is never selectable by presence.
- Separate internal evaluation, external diagnostics, runtime retrieval, and training material.
- Version schemas/contracts when meaning changes; do not silently repurpose a field.
- Relative paths resolve from the documented repository/artifact root.
- Unknown required capabilities and missing active artifacts fail preflight.
- Secrets and machine-local absolute paths never enter committed configs.

## Add or change configuration

1. Identify the consumer and whether the file is active, candidate, frozen, or historical.
2. Reuse a schema under `configs/schemas/` or add/version one.
3. Keep defaults explicit and reject unknown high-impact values.
4. Update identity hashing and receipts if the configuration affects behavior.
5. Add loader/preflight tests and a migration note for changed meaning.
6. Update public documentation only after the active selection is verified.

Graph additions also require a graph manifest and composition tests; tool additions require the canonical capability registry. A YAML boolean alone does not implement either feature.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_model_profile_controls.py \
  tests/test_retrieval.py \
  tests/test_final_benchmark_readiness.py
```

Use the relevant preflight/audit before a model, corpus, benchmark, or release run. A syntax-valid YAML file is not a readiness result.

The v2 design audit is model-free:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_open_agronomy_benchmark_v2.py
```

A passing design audit validates frozen structure and separation, not runtime execution or agronomic performance.

The v3 governance audit is also model-free and deliberately blocks on the
checked-in non-authorizing templates:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_open_agronomy_benchmark_v3_readiness.py \
  --commitment configs/open_agronomy_benchmark_v3_holdout_commitment.template.json \
  --judge-calibration configs/benchmark_judge_calibration.template.json
```

The template status is evidence that human-controlled work remains, not a file
to edit until it passes. A real holdout commitment must bind an independently
authored/reviewed private cohort. A real judge-calibration receipt must bind its
human labels, prompts, rubric, parser, order probes, and observed acceptance
metrics. The egress template likewise grants no authority.

The active product execution contract is
`open_agronomy_agent.production_stage_topology.v3`, with 17 ordered,
answer-affecting stages. The v3 protocol must match that exact version and
order. A stage addition, removal, reorder, or semantic change requires an
explicit compatibility and cohort decision.

## Failure modes

Reject malformed schemas, unpinned required models, missing active artifacts, hash drift, evaluation/retrieval overlap, unknown capability IDs, and unsupported runtime modes. Historical configs may reference artifacts intentionally absent from a public checkout; label that state rather than silently selecting them.
