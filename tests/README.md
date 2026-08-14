# Test and evaluation contracts

## Purpose and status

`tests/` contains deterministic unit, contract, service, storage, security, routing, retrieval, tool, UI-boundary, and release-readiness tests. Benchmarks and tests answer different questions: a passing test proves its asserted contract for the exercised code path; it does not establish agronomic correctness, field utility, provider uptime, or professional equivalence.

## Contract map

| Concern | Representative tests |
|---|---|
| Retrieval/corpus | `test_retrieval.py`, `test_corpus_governance.py`, `test_nrcs_compact.py` |
| Tools/evidence | `test_agronomic_calculations.py`, `test_tool_planner_end_to_end.py`, `test_public_tool_adapters.py`, `test_evidence_handshake.py` |
| Extension contracts | `test_capability_registry.py`, `test_knowledge_graph_contracts.py`, `test_public_docs.py` |
| Field state/context | `test_field_events.py`, `test_field_measurements.py`, `test_field_context_compiler.py` |
| Chat/answer path | `test_chat_service_field_context.py`, `test_agent_context_reservation.py` |
| Execution parity | `test_execution_core.py`, `test_retrieval_component_arms.py`, `test_regional_context_admission.py`, `test_tool_planner_end_to_end.py` |
| Models/evaluation | `test_model_profile_controls.py`, `test_evals.py`, `test_codex_app_server_egress.py`, `test_final_benchmark_readiness.py`, `test_eval_replication_contract.py`, v2 audit/metrics/runner/runtime-contract tests, v3 readiness and capability-conformance tests |
| Geometry/offline | `test_geospatial_service.py`, `test_field_lan_launch.py` |
| Security/release | `test_security_evidence.py`, `test_validate_conference_release_authority.py` |

Frontend tests live beside the React code under `frontend/src/*.test.*`.

## Invariants

- Tests use isolated temporary state and must not depend on a user's private database, cache, or credentials.
- Network behavior uses explicit fixtures/mocks unless the test is clearly marked as an authorized live smoke.
- Retain negative/regression cases; do not weaken an assertion solely to make a gate pass.
- Frozen benchmark/evaluation identity is distinct from unit-test fixtures.
- A focused selection is reported as focused, with named files/cases.
- Unknown/unavailable optional artifacts are not treated as zero capability or a pass.

## Add a test

1. Name the contract and expected failure mode.
2. Use the narrowest stable public seam and deterministic fixture.
3. Assert provenance/status/identity as well as the happy-path value.
4. Cover invalid, missing, offline, or collision behavior for extension points.
5. For a new tool or graph, add both component tests and a natural-language/startup integration test.

## Commands

Full Python suite:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Focused example:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_agronomic_calculations.py \
  tests/test_evidence_handshake.py
```

Frontend:

```bash
cd frontend
npm run typecheck
npm test
npm run build
```

## Failure modes and claim boundary

Test collection errors, leaked global state, hidden network use, nondeterministic timing, platform-only assumptions, and fixture/evaluation leakage are defects. Report exact counts and commands. “Focused tests passed” must never be rewritten as “the full system passed,” and neither automated tests nor an LLM judge support an agronomist-equivalence claim.
