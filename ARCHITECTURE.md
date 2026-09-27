# Open Agronomy Agent repository architecture

This document is the shortest reliable map from a repository checkout to the
code that answers a question. It describes the current source tree, not every
historical experiment retained in Git.

## Product request path

```text
React cockpit
  -> FastAPI routes                         src/agronomy_agent/server/app.py
  -> chat/application orchestration         server/services/chat_service.py
  -> typed production request/result        execution_core.py
  -> route and decision contract             router.py, decision_contract.py
  -> field/session context                   field_context_compiler.py, query_context.py
  -> governed documents and graph            agent.py, agno_runtime/, corpus_governance.py
  -> registered deterministic capabilities  capability_registry.py, capability_planner.py,
                                             tool_planner.py, local_tools.py, tools/
  -> prompt and local generation             agent.py
  -> verification and consequence policy     answer_verifier.py, answer_safety.py,
                                             answerability.py, high_consequence.py
  -> structured response and trace           answer_renderer.py, execution_core.py
  -> persistence                             server/storage/
```

`server/services/chat_service.py::execute_agent_request` is the supported
product execution seam. The compatibility `run_turn` facade calls that seam.
The ordered 17-stage receipt in `execution_core.py` describes what the product
path observed; it is not a second agent implementation.

## Source ownership

| Area | Canonical owner | Notes |
|---|---|---|
| Product composition | `server/app.py` | HTTP/auth/configuration boundary; routes should stay thin |
| Conversational execution | `server/services/chat_service.py` | Product orchestration and stage observations |
| Agronomy kernel/model | `agent.py` | Resource loading, prompt construction, MLX generation, legacy evaluator path |
| Planning/routing | `router.py`, `decision_contract.py`, `capability_planner.py`, `tool_planner.py` | Router classifies; planners own capability selection |
| Evidence/retrieval | `evidence_*.py`, `context_packer.py`, `agno_runtime/`, `corpus_governance.py` | Preserve provenance, applicability, authority, and admission |
| Safety/verification | `answerability.py`, `answer_verifier.py`, `answer_safety.py`, `high_consequence.py` | Validation cannot create evidence or current authority |
| Deterministic tools | `agronomic_calculations.py`, `local_tools.py`, `tools/` | Supported calculations bypass model drafting |
| Public adapters | `local_tools.py`, `server/services/chat_service.py` | Network/cache/jurisdiction dependent; unavailable is a typed state |
| Persistence | `server/storage/db.py`, `server/storage/runtime.py` | SQLite product path and schema-checked Postgres boundary |
| Local runtime services | `server/rate_limit.py`, `server/storage/object_store.py` | In-memory rate limits and filesystem artifacts only; Redis/S3 selection was removed |
| Training helpers | `training/` | Offline maintainer tooling only; no current Canadian source is training-authorized |
| UI | `frontend/src/` | React cockpit, map, field state, source cards, benchmark viewer |
| Reviewed field tables | `field_data.py`, `server/storage/field_data_store.py`, `field_data_capability.py` | Bounded intake, immutable mappings, private field queries and registered result lineage |
| Anonymous imagery | `field_imagery.py`, `imagery_analytics.py`, `imagery_store.py`, `server/services/imagery_service.py`, `server/field_data_routes.py` | Polygon-bound HLS discovery, optional isolated raster worker, private content-addressed chips, observed QA/NDVI/NDMI and authenticated previews; no operational yield prediction |
| Imagery research | `imagery_assessment.py`, `imagery_models.py`, `scripts/assess_field_imagery.py`, `scripts/probe_imagery_model.py` | Frozen label/split assessments and bounded CPU/MPS encoder probes; outputs remain research evidence, not serving capability or active model profile |
| Operator workflows | `scripts/` | Thin CLIs around package contracts; generated outputs belong under ignored paths |

## Harnesses and what they prove

There are three evaluation surfaces and they must not be conflated.

1. `run_open_agronomy_benchmark.py` and `evals.py` execute the historical
   four-arm development harness through `agent.generate_answer`. It retains
   rich paired outputs and remains useful for exposed regression evidence, but
   it is not the complete persisted cockpit topology.
2. `execute_agent_request` plus `benchmark_rehearsal.py` exercise the same
   typed execution core as the cockpit and emit 17-stage receipts. This is the
   parity surface for product-path QA.
3. `run_v3_competence_candidate.py` freezes a larger candidate matrix and
   process/ledger contracts. A real production executor and current authority
   are still required; its dry run is orchestration QA, not model evidence.

The September two-Gemma assessment used the first surface because it is the
complete retained model-comparison harness. Its results therefore support the
QA/QC merge and model-specific diagnostics, not a product-parity or sealed-v3
claim.

## What helps the small models

The most effective components are deterministic and selective:

- typed calculations bypass generation and reached 16/16 in every full-system
  trial;
- 60 evidence-sufficiency holds, 16 deterministic tool results, and four
  discriminating clarifications reduce the number of cases that require a
  draft;
- explicit field context and governed retrieval improve source availability
  without allowing regional priors to become field truth;
- guard planning reached 154/154 trace completeness; and
- claim/action-level verification can preserve supported text instead of
  suppressing an entire answer.

The remaining cost is excessive fallback dependence: 148/241 full-system
cases for Gemma 3 270M and 98–100/241 for Gemma 4 E2B. Gemma 4 also varied in
27 full-system cases across otherwise deterministic trials. Improving those
two boundaries is more valuable than adding another broad trigger ladder or
larger prompt.

## Configuration and data authority

- Active defaults: `configs/model.yaml`, `configs/rag.yaml`, and
  `configs/runtime_profiles.json`.
- Historical benchmark/config bytes remain immutable evidence; presence does
  not make them selectable.
- Runtime corpus authority comes from policy/manifests, not directory names.
- `data/eval/` never becomes retrieval or training material.
- The repository currently tracks about 988 MiB of data. Moving the large NRCS
  release to an external, content-addressed distribution is a packaging
  project, not an ordinary deletion.

## Test layers

| Layer | Command | Purpose |
|---|---|---|
| Python contracts | `PYTHONPATH=src .venv/bin/python -m pytest -q` | Unit, service, storage, governance, benchmark, and release contracts |
| Frontend | `npm test`, `npm run typecheck`, `npm run build` in `frontend/` | UI behavior and buildability |
| Documentation | `scripts/check_public_docs.py`; `mkdocs build --strict` | Link, publication-scope, generated-contract, and rendering checks |
| Runtime corpus | `audit_runtime_corpus.py`; successor quality/retrieval audits | Rights, hashes, locators, admission, and retrieval baselines |
| Product trace | `audit_guard_route_replay.py` | Current-code routing and 17-stage receipt completeness |

Delete a test only after identifying the contract it protects and proving that
another test exercises the same public seam and failure mode. Test-file count
is not a useful cleanup target by itself.

## Known structural debt

- `server/app.py`, `server/storage/db.py`, `answer_verifier.py`, `agent.py`, and
  `chat_service.py` are large ownership boundaries that should be split by
  stable domain interfaces, not mechanically by line count.
- The legacy four-arm evaluator and product execution core remain distinct.
- Model-backed v3 execution has a frozen matrix/ledger but no canonical real
  executor adapter.
- Active, historical, candidate, and template configs share a mostly flat
  directory because frozen hashes constrain moves.
- Large runtime data dominates clone size and should eventually be distributed
  as a verified release asset or dataset package.
- Redis/S3 scale-out code and its standalone queue worker were removed after
  the local-private product decision. Retired namespaced environment variables
  fail closed instead of silently implying remote persistence.

See `AGENTS.md` for safe repository work and
`docs/reviews/repository-cleanup-investigation-20260926.md` for the current
cleanup backlog and evidence status.
