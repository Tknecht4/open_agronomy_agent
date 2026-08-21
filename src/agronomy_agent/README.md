# `agronomy_agent` package

## Purpose and status

This package owns the local agent kernel, routing, evidence contracts, retrieval integration, model adapters, validation, traces, persistence-facing services, and deterministic capabilities. It is active development code. Public behavior should be described from executable contracts and tests, not from a filename or historical phase label alone.

## Canonical request flow

The supported cockpit composes the system through `server/app.py`. A normal answer follows these conceptual stages:

1. bind the question to available field and session context;
2. classify intent, risk, namespaces, and capability needs;
3. collect governed retrieval, graph hints, field history, and eligible capability results;
4. pack bounded context for the configured local model;
5. generate a draft;
6. validate evidence use and consequence-sensitive boundaries;
7. render the answer, source cards, and trace; and
8. persist immutable observations and answer lineage.

`agent.py` still coordinates several of these stages directly. The stage list is an architectural contract, not a claim that each stage is already independently replaceable.

## Package map

| Area | Entry points | Responsibility |
|---|---|---|
| Kernel | `agent.py`, `context_packer.py` | Resource loading, context construction, prompts, generation, intervention |
| Routing | `router.py`, `decision_route.py`, `route_decision_v2.py` | Question type, risk, namespaces, tools, decision contracts |
| Evidence | `evidence_contracts.py`, `evidence_handshake.py`, `evidence_authority.py` | Typed provenance, applicability, coverage, and validated-answer records |
| Validation | `answer_verifier.py`, `answer_safety.py`, `high_consequence.py` | Evidence and action-boundary checks |
| Execution receipts | `execution_core.py`, `benchmark_rehearsal.py` | Typed production-path requests/results, fail-closed stage receipts, and claim-ineligible rehearsals |
| Capabilities | `skill_registry.py`, `tools/`, `local_tools.py`, `agronomic_calculations.py` | Guard notes, deterministic calculations, and public adapters |
| Runtime adapters | `agno_runtime/` | Local retrieval/graph/model/tool/trace adapters |
| Application | `server/` | FastAPI composition, services, auth/network settings, storage |
| Field state | `field_events.py`, `field_measurements.py`, `query_context.py` | Append-oriented field observations and usable question context |

## Inputs and outputs

- Inputs: a question, optional field/session identity, model and RAG configuration, admitted corpus/graph artifacts, and authorized capability inputs.
- Outputs: an answer, source/evidence records, route and validation state, tool receipts, model identity, and a persisted trace.
- Unknown field facts remain unknown. Absence must not silently become `0`, `false`, a diagnosis, or a locally calibrated recommendation.

## Invariants

- Preserve source identity, scope, time, jurisdiction, rights, and limitations through every transformation.
- Keep observations, model output, and system interpretation distinguishable.
- Evaluation questions and answers never become retrieval knowledge.
- Network use is explicit and blocked before execution in offline modes.
- A map or graph relationship is context, not field measurement or decision authority.
- High-consequence outputs require current applicable authority; validation cannot promote weak evidence.
- New versions append or supersede records; they do not rewrite historical traces.

## Extension procedure

- Add a capability through the canonical capability contract, executor, evidence contribution, and parity tests; see [`tools/README.md`](tools/README.md).
- Add graph data through a governed graph manifest and configured path; see [`agno_runtime/README.md`](agno_runtime/README.md).
- Add an API domain through a service boundary and thin route; see [`server/README.md`](server/README.md).
- Add a new evidence type by extending the typed contracts and every serialization/validation boundary. Do not inject untyped prompt text as a shortcut.

## Configuration

Runtime selection starts in `configs/`.
`configs/model.yaml` and `configs/rag.yaml` are the active release profiles;
`configs/runtime_profiles.json` is the selectable/default registry. Adding a
config file does not activate it. See [`configs/README.md`](../../configs/README.md)
before changing an active profile.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m compileall -q src scripts
```

Use focused tests while iterating, then run the full suite before making a system-wide claim. Benchmark results are bound to their exact implementation identity and do not automatically validate current code.

The cockpit's `run_turn` compatibility facade and the non-claim benchmark
rehearsal both call `execute_agent_request`. The shared result validates an
ordered, content-addressed receipt for routing, field context, public adapters,
document and graph observations, typed tools, prompt construction, risk
intervention, generation, verification, safety policy, high-consequence policy,
and final rendering. The rehearsal currently supports only the complete
production configuration. Document and graph observations are separate, but
their execution switches remain coupled inside `build_context`; attempted
component ablations fail instead of being reported as implemented.

This seam covers the persisted server answer pipeline. HTTP authorization and
configuration selection, hosted-message copying and metrics, image-research
routes, frontend presentation, and the legacy `agent.generate_answer` evaluator
remain outside it. Their parity requires separate integration evidence.

## Failure modes

The intended failure mode is explicit: setup-required model, blocked-offline adapter, excluded corpus, missing authority, insufficient evidence, failed validation, or persisted error trace. Silent graph omission, registry drift, untyped capability output, and fallback text presented as model reasoning are defects.
