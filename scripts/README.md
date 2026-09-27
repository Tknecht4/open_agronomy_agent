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
| Workspace profiling | `profile_workspace_backend.py`, `profile_workspace_model.py`, `profile_frontend_build.mjs` | Synthetic local timing and build receipts; never agronomic quality, provider availability, or a release latency budget |
| Packaging/release | `audit_release_candidate_checkout.py`, `capture_release_environment.py`, `build_public_repository.py`, edge manifest/container/SBOM scripts | Curated scope only; no private/generated state; the Python environment receipt observes range resolution and is not a portable lock |
| Recovery | Transaction-safe backup primitives in `server/storage/backup.py` | Programmatic maintenance boundary; no supported standalone recovery CLI is currently published |

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

## Workspace profiling

`profile_workspace_backend.py` creates an isolated synthetic SQLite database in a
new output directory. It measures cold/warm API calls and a mock production-core
turn, captures cProfile summaries and stage spans, hashes controlling inputs,
and retains failed cells. It makes no model or public-provider calls. `--help`
lists adjustable synthetic session/turn counts and warm repeats.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python \
  scripts/profile_workspace_backend.py \
  --output-dir /tmp/open-agronomy-backend-profile-new
```

`profile_workspace_model.py` requires `--execute-local-pinned` and a separately
provisioned revision-pinned snapshot. It forces Hugging Face offline mode,
executes two synthetic questions through the typed core, and retains timing,
stage, selected token, and local memory measurements without answer text in its
receipt. A parent process enforces the worker deadline, kills the worker process
group on expiry, and preserves the last receipt with interrupted cells. Both
workspace profilers disable inherited private-knowledge overlays and record that
policy, so synthetic diagnostics cannot read machine-local private references.
A Metal-capable host is required for model profiling; no cloud provider is contacted.

```bash
HF_HUB_CACHE=/absolute/local/hf-cache/hub HF_HUB_OFFLINE=1 \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python \
  scripts/profile_workspace_model.py --execute-local-pinned \
  --output-dir /tmp/open-agronomy-model-profile-new \
  --max-tokens 120 --deadline-seconds 900
```

`profile_frontend_build.mjs` reports raw and gzip bytes plus SHA-256 for the
completed `frontend/dist` JS/CSS files. Run it after `npm run build` with
`node scripts/profile_frontend_build.mjs` from the repository root, or pass a
different build directory as its positional argument. See the [workspace customization guide](../docs/public/developer/customizing-the-harness.md)
and the [bounded backend findings](../docs/reviews/artifacts/ui-backend-findings-20260927.md).
## Production foundations candidate

`build_production_foundations_supplement.py` builds the nine-card, source-linked
context release from `data/seed/production_foundations_v1.jsonl` and its
external-source registry. The external snapshots are inspected and hash
recorded but not copied into the public package. The builder refuses a
nonempty output directory; save a prior candidate before rebuilding.
`build_production_foundations_profile.py` composes an ignored candidate profile
by default. The checked-in `configs/rag_production_foundations_candidate.yaml`
and companion policy are nonselectable development artifacts. Writing the
builder outputs to `configs/rag.yaml` and the active policy would be a separate
admission step requiring a qualified answer-quality result, updated
`runtime_profiles.json` hashes, and full validation; this comparison did not
authorize that step.

The exposed development probes are:

```bash
PYTHONPATH=src .venv/bin/python scripts/evaluate_production_foundations_retrieval.py \
  --config configs/rag_production_foundations_candidate.yaml \
  --output outputs/production-foundations-retrieval.json
PYTHONPATH=src .venv/bin/python scripts/run_production_foundations_development.py \
  --rag-config configs/rag_production_foundations_candidate.yaml \
  --max-tokens 320 \
  --output-dir outputs/production-foundations-model
```

The second command requires the pinned local Gemma snapshot and Metal access.
Both are development diagnostics; compare against an independently captured
baseline and inspect saved answers rather than treating a numeric substring
proxy as a correctness score. Output destinations must be new and empty. The
separate `data/eval/production_foundations_confirmation_v1.jsonl` probes the
versioned typed-calculation follow-up through this same runner. The current
deterministic registry/executor gate is:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_benchmark_capability_conformance.py \
  --contract configs/benchmark_capability_conformance_v2.json
```

The v1 contract is retained as historical evidence and intentionally fails
current-version conformance. The [follow-up record](../docs/reviews/production-foundations-benchmark-20260927.md)
distinguishes calculator gain from corpus gain and records interrupted model
runs as incomplete.

The [source-distinct efficacy audit](../docs/reviews/production-foundations-efficacy-audit-20260927.md)
uses the same runner with `--cases data/eval/production_foundations_transfer_v1.jsonl`
or `--cases data/eval/production_foundations_topic_confirmation_v1.jsonl`.
Run matched active and candidate profiles in separate empty output directories
at `--max-tokens 320`, then inspect every answer and the selected document
IDs. In an isolated worktree, point `HF_HOME` and `HF_HUB_CACHE` at an already
provisioned model cache explicitly; no answer run downloads weights. These
exposed cases and nonblinded reports are development diagnostics.

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
  --rag-config configs/rag.yaml
```

`prepare_v3_competence_candidate.py` downloads or accepts the revision-pinned
AI71 CSV, verifies its exact bytes and schema, retains all 800 row
dispositions, derives the exposed 72-case regional lane, and writes ignored
local input receipts. It never modifies or satisfies the sealed-v3 holdout.

`run_v3_competence_candidate.py` deterministically expands those inputs into
the frozen 17,640-observation Gemma/Luna matrix and emits its identity manifest.
Its deterministic dry run exercises the complete append/resume matrix without
making model claims. Real `--execute` requires an importable production-core
executor, an append-only ledger, a current matrix-bound authorization, and runs
every observation in a separately killable child process. Planning or dry
running the matrix does not generate or judge the cohort.

`audit_guard_route_replay.py` replays the 154 guard-eligible exposed Canadian
cases through the production execution core with the mock model, retains each
17-stage trace, and fails if any required local guard is absent. It measures
routing and trace completeness only, not answer quality.

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

`audit_final_benchmark_readiness.py` validates the frozen RC3 development-rerun
plan without generation or judging. The completed checkpoint used a clean
committed checkout, matching
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

The runner forced private knowledge disabled in its environment and in every
child evaluation. RC3 had no judge payload class, rejected judge calibration,
and never emitted `--judge`; `judge_seed` was inert identity with application
`not_requested`. Each completed run command included both
`--resume-partial-runs` and `--reuse-complete-runs`, which remain bound to exact
run identity and durable receipts. The preflight authorized only the declared
exposed-and-tuned-suite `development_rerun_nonclaim`; it is not authorization to
append observations to the completed identity. RC1, RC2, and RC3 now remain
frozen historical identities.

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
