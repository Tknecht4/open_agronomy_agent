# Repository map

Open Agronomy Agent has one supported product path and several deliberately
separate research/evaluation paths.

## From question to answer

1. `server/app.py` validates the HTTP request and product configuration.
2. `server/services/chat_service.py` creates a typed execution request.
3. `router.py` and `decision_contract.py` classify the question, consequence,
   evidence obligations, and retrieval query.
4. `capability_planner.py` and `tool_planner.py` select registered guards,
   calculators, and deterministic capabilities.
5. `agent.py`, `agno_runtime/`, and `context_packer.py` load admitted evidence
   and construct the bounded model input.
6. `answerability.py`, `answer_verifier.py`, `answer_safety.py`, and
   `high_consequence.py` control unsupported claims and regulated actions.
7. `answer_renderer.py` and `execution_core.py` produce the answer, lineage,
   and ordered 17-stage receipts.
8. `server/storage/` persists the turn and trace.

The React cockpit lives in `frontend/src/`. Deterministic agronomy operations
live in `agronomic_calculations.py`, `local_tools.py`, and `tools/`.

## Evaluation surfaces

| Surface | Use | Limitation |
|---|---|---|
| Historical four-arm runner | Retained model/regression comparisons | Uses the legacy text-agent evaluator, not the complete persisted product topology |
| Production execution rehearsal | Cockpit-core parity and 17-stage trace QA | Claim-ineligible and normally deterministic/mock |
| V3 candidate matrix | Frozen cohort, arm, process, timeout, and ledger identity | Real executor/authority and independent review remain separate gates |

The frozen September 26 two-Gemma assessment of commit `d43ade7` is exposed
development evidence, not a measurement of the present checkout. Its strongest
small-model improvements came from deterministic calculations, selective holds,
clarifications, field context, and trace-complete guards. High verifier fallback
dependence and Gemma 4 full-system repeatability remained open at that checkpoint.

## Where things belong

| Path | Contents |
|---|---|
| `src/agronomy_agent/` | Reusable domain and runtime implementation |
| `src/agronomy_agent/server/` | Application, services, settings, storage |
| `scripts/` | Thin operator/build/audit entry points |
| `configs/` | Active, candidate, template, and frozen contracts |
| `data/` | Governed sources, derivatives, manifests, snapshots, evaluation sets |
| `tests/` | Deterministic contract/regression tests |
| `docs/public/` | Supported public documentation site |
| `docs/reviews/` | Dated review records and public-safe evidence |

## Local-private infrastructure and training boundaries

The product runtime uses in-memory request limiting, database-recorded ingest
work (SQLite by default), and a permission-restricted filesystem artifact root. The earlier
Redis queue/rate-limit and S3-compatible storage alternatives, their preflight
commands, and the standalone queue worker were removed after the project chose
the local-private deployment model. Retired `AGRONOMY_AGENT_*` backend
environment variables fail closed so an old deployment cannot silently write
somewhere different than its operator expects.

The schema-checked Postgres and identity-provider compatibility interfaces are
separate boundaries. This removal neither qualifies them for deployment nor
misreports their database identity as SQLite.

`src/agronomy_agent/training/` is offline maintainer tooling, not part of the
answer path. No current Canadian source is admitted for model training;
retrieval or redistribution permission must never be treated as training
authorization.

For a more detailed maintainer map, see
[`ARCHITECTURE.md`](https://github.com/Tknecht4/open_agronomy_agent/blob/main/ARCHITECTURE.md).
