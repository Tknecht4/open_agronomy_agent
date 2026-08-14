# Tools and capabilities

## Purpose and status

This package contains query-triggered guard tools and participates in the wider capability system. Deterministic calculations and public-data adapters also live in `agronomic_calculations.py`, `local_tools.py`, `skill_registry.py`, `agno_runtime/tool_adapters.py`, and server services. That historical fragmentation is why the canonical capability registry is the extension authority going forward.

## Capability kinds

| Kind | Example | Authority boundary |
|---|---|---|
| Guard | field-data or label guard | Adds decision checks; does not supply missing facts |
| Deterministic tool | agronomic calculator | Computes from supplied typed inputs; does not choose a target or legal rate |
| Public adapter | weather, statistics, soil survey, label metadata | Adds dated provider context; availability and jurisdiction remain explicit |
| Local data capability | field history or packaged spatial prior | Reads authorized local state; map output is not a sample |
| Administrative probe | route/retrieval debug | Diagnostics only; not a user-facing agronomic capability |

## Canonical contract

A capability definition should own:

- stable ID and semantic version;
- kind, display name, owner, and status;
- typed input and output schemas;
- executor identity;
- network/offline/cache policy and credentials declaration;
- evidence authority, jurisdiction, freshness, risk, and limitations;
- planner trigger/requirements metadata;
- verifier and renderer adapters;
- CLI/HTTP/Agno exposure flags; and
- focused, parity, natural-language, and failure-mode tests.

CLI, HTTP, readiness, trace, and documentation surfaces should be derived from or checked against this contract. A capability is not “implemented in chat” merely because a function, adapter, endpoint, or config flag exists.

## Add a tool

1. Define the capability contract and typed schemas.
2. Implement a side-effect-bounded executor returning a typed invocation result and stable result ID.
3. Declare offline/network/cache, evidence authority, risk, freshness, and error states.
4. Connect the planner, evidence packet, verifier, renderer, trace, and persistence through the shared result—not custom prompt text.
5. Expose only the declared CLI/HTTP/Agno surfaces.
6. Add parity tests, deterministic executor tests, natural-language selection/execution tests, verifier tests, and offline/provider-failure tests.
7. Regenerate or check the public capability table.

A compliant addition should require one implementation, one contract, and tests—not manual edits to every registry.

## Calculator exemplar

The calculator takes an operation and a typed input object, uses decimal arithmetic, validates units/ranges, and returns formula, value, unit, assumptions, and boundary. It verifies arithmetic only. A natural-language request is complete only when the planner invokes it, the same result identity reaches evidence/validation/trace, and the final answer contains the parseable result.

```bash
PYTHONPATH=src python -m agronomy_agent.tool_cli calculate unit_conversion \
  --inputs-json '{"value":100,"from_unit":"kg/ha","to_unit":"lb/ac"}'
```

## Invariants

- Never infer omitted numeric inputs.
- Never turn a map, cached response, or regional statistic into field measurement.
- Network access is declared and checked before execution.
- Provider errors and stale/unavailable caches remain visible.
- Current labels/regulations require current applicable authority.
- Every invocation/result identity is shared across generation, validation, rendering, persistence, and evaluation.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_agronomic_calculations.py \
  tests/test_public_tool_adapters.py \
  tests/test_evidence_handshake.py
```

Unit tests prove executor behavior. Add a conversational path test before claiming the capability is available to user questions.

## Failure modes

Expected statuses include invalid input, missing input, unsupported operation, blocked offline, provider not configured, provider unavailable, stale cache, out-of-scope jurisdiction, and verifier rejection. Unknown required capabilities and duplicate aliases should fail startup/preflight rather than disappear.
