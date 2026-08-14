# Developer guide

The code is organized around a governed answer loop, but several historical modules still cross stage boundaries. New work should strengthen the stable contracts instead of adding another parallel registry or service-specific implementation.

## Code map

| Area | Location | Ownership |
|---|---|---|
| Agent kernel | `src/agronomy_agent/agent.py` | Resource/context/generation/intervention composition |
| Routing and decisions | `src/agronomy_agent/router.py`, `decision_*`, `route_*` | Intent, risk, namespace and capability requirements |
| Evidence/validation | `evidence_*`, `answer_verifier.py`, `high_consequence.py` | Typed provenance, coverage, claim/action boundaries |
| Runtime/retrieval/graphs | `src/agronomy_agent/agno_runtime/` | Active Agno adapters and local knowledge paths |
| Capabilities | `src/agronomy_agent/tools/`, `local_tools.py`, capability registry | Contracts, executors, planner/evidence integration |
| Application services | `src/agronomy_agent/server/` | HTTP, auth/network, orchestration, storage |
| Frontend | `frontend/src/` | Map-first React client and local/offline UX |
| Configuration | `configs/` | Active, candidate, frozen and benchmark contracts |
| Data governance | `data/manifests/` | Source identity, rights, admission and lineage |
| Tests and workflows | `tests/`, `scripts/` | Contract checks, builders, audits, operations |

Read the README beside each subsystem before modifying it.

## Development setup

Use the repository [native setup](../operations/native-setup.md). For a Python-only focused change, activate the virtual environment and run the narrow test first. Before a system claim, run the full Python and frontend gates listed in the root README.

## Extension principles

- Preserve stable identities and typed inputs/outputs across stages.
- Keep source, observation, model output, and interpretation distinguishable.
- Inject backend/capability implementations through contracts rather than concrete class checks.
- Fail startup/preflight on missing required capabilities, collisions, invalid graph/source manifests, and schema drift.
- Add an integration test through the claimed user interface; component registration alone is insufficient.
- Generate/check public capability claims from the same canonical registry.

Continue with [adding a graph, tool, source, or service](extending.md) and [testing and claims](testing.md).
