# Operator and maintenance scripts

## Purpose and status

`scripts/` contains user launch/setup commands, deterministic builders, audits, benchmark runners, packaging tools, ingestion workflows, and narrow recovery utilities. Script names reflect workflow history; read `--help` and the owning contract before execution. Many scripts write ignored artifacts under `outputs/`.

## Workflow groups

| Group | Representative entry points | Boundary |
|---|---|---|
| User/native | `run_cockpit.py`, `download_model.py` | Local setup and launch; model download requires network |
| Operator readiness | `audit_runtime_corpus.py`, `audit_final_benchmark_readiness.py`, `audit_open_agronomy_benchmark_v3_readiness.py`, `run_offline_cold_start_audit.py` | Audits/preflights do not equal performance proof or human authorization |
| Tools/data | `smoke_*`, `build_prairie_spatial_pack.py`, `verify_prairie_spatial_pack.py` | Fixture/provider and package contracts, not field truth |
| Ingestion/build | `ingest_*`, `build_*corpus*`, geospatial builders | Require source, rights, hashes, deterministic outputs |
| Evaluation | `run_open_agronomy_benchmark.py`, `run_open_agronomy_benchmark_v2.py`, `run_observed_system_rehearsal.py`, `run_benchmark_capability_conformance.py`, v2/v3 audits, model matrix, judges, analyzers | Preserve identities and separation; v2 dry execution, capability conformance, and observed-system rehearsal are harness QA, not performance evidence |
| Packaging/release | `audit_release_candidate_checkout.py`, `capture_release_environment.py`, `build_public_repository.py`, edge manifest/container/SBOM scripts | Curated scope only; no private/generated state; the Python environment receipt observes range resolution and is not a portable lock |
| Recovery | Security recovery/readiness tools | Narrow incident contracts; never promotion by recovery alone |

## Inputs and outputs

Scripts should accept explicit paths/identities, resolve repository-relative defaults through `_path_bootstrap.py`/package helpers, and write receipts next to outputs. Never rely on an ambiguous current directory for destructive or release work.

## Invariants

- Builders are deterministic where source bytes/config are fixed.
- Preflights and audits do not generate, judge, mutate authority, or claim readiness beyond their stated gate.
- Benchmark runners preserve exact questions, responses, identities, and traces in ignored run bundles.
- External diagnostics are frozen once and are not iteratively tuned.
- Network use and credentials are explicit.
- Recovery tools never overwrite canonical input or promote their output.
- Public-package builders include only manifest-selected paths and reject forbidden prefixes.

## Add a script

1. Prefer a thin CLI over package logic; put reusable behavior in `src/agronomy_agent/`.
2. Provide a module docstring, `--help`, typed arguments, explicit defaults, and non-zero failure exit.
3. Fail before partial writes where possible; write to a new target and emit a receipt.
4. Preserve source/config/version/hash identity and minimize absolute paths in shareable output.
5. Add unit tests for argument validation and core contracts.
6. Document network, mutations, output location, resume/idempotency, and recovery.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q scripts
PYTHONPATH=src .venv/bin/python scripts/check_public_docs.py
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Run a script-specific fixture/preflight before any expensive, networked, or release execution.

`build_public_repository.py` materializes only the explicit public manifest
allowlist, rejects forbidden paths and machine-local path literals, and honors
`SOURCE_DATE_EPOCH` for a reproducible receipt timestamp. It never treats the
whole `configs/` or `data/` tree as public by default.

`build_edge_runtime_manifest.py` regenerates the container runtime inventory
for the selected active RAG profile. Because its contract hashes governed
runtime trees, regenerate it only after the final code/config/data/docs inputs
are stable; do not edit `container/runtime_manifest.json` by hand. An unchanged
contract retains its prior generated timestamp.

## Observed-system rehearsal

`run_observed_system_rehearsal.py` executes one question through the same typed
production core used by the cockpit and retains its SQLite trace plus a JSON
result. It does not load case expectations, score an answer, or emit a
claim-eligible result. The smallest offline deterministic rehearsal is:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_observed_system_rehearsal.py \
  --output-dir /tmp/open-agronomy-observed-rehearsal \
  --question "Convert a fertilizer rate of 100 lb/ac to kg/ha." \
  --mode agronomic_rag \
  --model-id mock \
  --rag-config configs/rag_governed_runtime_v2.yaml
```

Supported product modes are `baseline`, `agronomic_rag`, and `mock` when both
retrieval components are enabled. `agronomic_rag` additionally supports the
four named retrieval configurations `retrieval_neither`,
`retrieval_document_only`, `retrieval_graph_only`, and `retrieval_both`. These
are real controls on the typed production request, and each retrieval stage
records whether it completed, completed with no result, or was disabled by the
arm. All other stages in the 17-stage production topology remain enabled and
receipted.

The 2×2 supports reachability, isolation, and contamination QA; it is not a v3
performance result. Raw-model, kernel-only, and non-retrieval component
ablations remain deliberately unsupported by this adapter. The script exercises
the server answer pipeline, not HTTP/auth wrappers, hosted-message augmentation,
frontend presentation, image-research routes, or the legacy
`agent.generate_answer` evaluation path.

## Benchmark release scripts

`audit_final_benchmark_readiness.py` validates the RC3 development-rerun plan
without generation or judging. It requires a clean committed checkout, matching
environment/public-package receipts, model snapshots, source/corpus gates,
fresh per-model/per-trial destinations, and a real suite-bound egress receipt.
The checked-in egress template cannot pass. RC3 requires the schema-v4 exact
global taxonomy and phase/arm payload map plus exact suite-case,
runtime-artifact, and static-prompt contract hashes: raw gets only the frozen
question; baseline adds the prompt; kernel adds synthetic field context; the
RAG candidate adds selected public document excerpts and public graph evidence;
only RAG verification is admitted, with question, prompt, selected documents,
candidate draft, and verifier evidence. Deterministic tools stay local and
bypass Luna. Farmer records, private field
history, credentials, and whole local corpus files remain forbidden.

The runner forces private knowledge disabled in its environment and in every
child evaluation. RC3 has no judge payload class, rejects judge calibration,
and never emits `--judge`; `judge_seed` is inert identity with application
`not_requested`. Each planned run command includes both
`--resume-partial-runs` and `--reuse-complete-runs`, which remain bound to exact
run identity and durable receipts. A passing preflight authorizes only the
declared exposed-and-tuned-suite
`development_rerun_nonclaim`. RC1 and RC2 remain frozen historical identities.

`audit_open_agronomy_benchmark_v3_readiness.py` validates the public v3
protocol, exact 17-stage production topology, absence of plaintext holdout
material, private holdout commitment, and judge calibration. The checked-in
commitment and calibration templates are expected to block. The audit does not
create human authority, read private cases, run models, or score answers.

`build_benchmark_retention_bundle.py` creates a content-addressed private bundle
and a minimized public-safe linkage export. `run_benchmark_capability_conformance.py`
executes deterministic capability fixtures through the canonical registry.
Neither tool establishes model quality or agronomic correctness.

Retention accepts regular zero-byte evidence, excludes only the reserved
`.eval_run.lock` coordination file, rejects symbolic links and non-regular
experiment entries, and verifies the staged content-addressed bundle before it
is atomically published.

## Failure modes

Missing inputs, identity mismatch, non-empty destination, insufficient authority, unavailable network/provider, dirty release state, checksum drift, and insufficient disk should stop with a diagnostic. Do not automatically delete or overwrite evidence to make a rerun pass.
