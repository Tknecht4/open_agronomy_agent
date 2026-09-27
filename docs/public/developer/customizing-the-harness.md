# Customize the agent and research harness

This repository can be forked as a field workspace or as a governed agent research base. Start from the supported product path, change one contract at a time, and keep candidate configurations and historical receipts distinct from the active runtime. The [architecture](../architecture.md), [extension contract](extending.md), and subsystem READMEs give the fuller ownership map.

## Find the supported seams

| Change | Start here | Required follow-through |
|---|---|---|
| Workspace and API presentation | `frontend/src/OpenAgronomyApp.tsx`, `FieldSetupDialog.tsx`, `LeafletFieldMap.tsx`, `api.ts`, `types.ts` | Preserve empty, offline, unauthorized, and unavailable states; test desktop/mobile and keyboard flows. |
| Product request execution | `src/agronomy_agent/server/app.py`, `server/services/chat_service.py::execute_agent_request`, `execution_core.py` | Keep auth/workspace checks at the API edge and the ordered production-stage receipt intact. |
| Intent, risk, and capability selection | `router.py`, `decision_contract.py`, `capability_registry.py`, `capability_planner.py`, `tool_planner.py` | Router classifies; registry-driven planners select. Add a named natural-language integration test. |
| Local model | `configs/model.yaml`, `configs/runtime_profiles.json`, `scripts/download_model.py`, `agent.py` | Pin a revision, provision explicitly, test generation and model identity, then evaluate quality under a new run identity. |
| Documents and graphs | `configs/rag.yaml`, `data/manifests/runtime_corpus_policy.json`, `data/derived/rag/`, `agno_runtime/` | Bind source bytes, rights, jurisdiction, locators, graph manifests, hashes, and admission before runtime use. |
| Typed tools and adapters | `capability_registry.py`, `tools/`, `local_tools.py`, `agno_runtime/tool_adapters.py` | One canonical specification, typed result and invocation IDs, offline/failure behavior, planner, evidence, renderer, and trace tests. |
| Persistence and private state | `server/storage/db.py`, `server/storage/runtime.py`, field-event and export services | Preserve actor/workspace checks, append history, receipt lineage, and explicit migration. |

The active model, RAG, and runtime-profile registry are `configs/model.yaml`, `configs/rag.yaml`, and `configs/runtime_profiles.json`. A newer-looking candidate file is not active by filename. Frozen benchmark configurations and artifacts are evidence; a fork should give new experiments new identities rather than editing them.

## Bring in data without crossing authority boundaries

| Input path | How to use it | What it does not do |
|---|---|---|
| Field geometry | Workspace pin/draw or `/api/geo/boundary-upload` for GeoJSON, JSON, ZIP, or GPKG | A boundary or map layer does not establish a soil test or make a source model-visible. |
| Field records and soil tests | **Fields → Records & soil tests**, append-only field events, import/export sync | A measurement is a dated user observation, not a source document or a model-training row. |
| Private reference | **Data** and `/api/private-knowledge/inspect` for bounded PDF/text/Markdown/JSON | Inspection is ephemeral, context-only, and not a governed public-corpus admission. |
| Workspace attachment or source | Authenticated attachment/data-source routes, ingestion job status, storage | Availability and use depend on workspace policy and configured services; a queued job is not completed ingestion. |
| Image observation and image RAG | Attachment/image jobs and `/image-rag/query` service path | A visual model observation is not a field diagnosis, representative sample, or admitted public document. |
| Shared document corpus | Source manifest/receipt → `scripts/ingest_document_sources.py` or a source-specific builder → active-store builder → runtime-policy audit | Extracted bytes are not automatically licensed, admitted, or training-authorized. |
| Agno source intake | `scripts/ingest_agno_sources.py` and `agno_runtime/source_ingest.py` with explicit source IDs and rights | A source registry entry or download alone does not activate retrieval. |
| U.S. NRCS analogue | `scripts/ingest_nrcs_esd_json.py`, release builder and manifests | U.S. context remains on-demand for explicit U.S./MLRA comparison, never Canadian decisive authority. |
| Spatial layers and snapshots | `scripts/setup_offline_data.py`, geospatial builders, and typed snapshot builders | A regional layer or dated statistic is not an on-field measurement or live provider result. |
| Evaluation cases | `data/eval/` and benchmark runners | Cases and answers never enter runtime retrieval or training. |

For a new shared source, record publisher, URL or exact bytes, retrieval date, rights, jurisdiction, checksum, extraction method, and row-level locator. Build deterministic derivatives, review duplicates and exclusions, assign a context/decisive/quarantine role, then update runtime policy and active profile only after validation. Run `scripts/audit_runtime_corpus.py`, source-specific quality gates, retrieval probes, and leakage checks. [Knowledge and data governance](../knowledge-and-data.md) explains the current corpus and the [Canadian admission procedure](../operations/canada-offline-source-admission.md) covers a concrete queue. Private browser context should stay on its separate path.

Graphs require a stable graph ID, version, source and licence, namespace/relation ownership, checksum, and collision policy in a manifest. The runtime must fail closed on an invalid required graph. A capability requires a canonical registry specification and typed executor before adding an API button or chat trigger; see [extending the system](extending.md).

## Measure before changing answer behavior

Use a fresh output directory for each run. The mock workspace profiler creates a synthetic SQLite database, measures cold/warm API paths and the production core, emits cProfile summaries, and retains failures without a model or provider call:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python \
  scripts/profile_workspace_backend.py \
  --output-dir /tmp/open-agronomy-backend-profile-new \
  --warm-repeats 7 --sessions 20 --turns-per-session 8
```

For a bounded local Gemma run, provision the exact model first. The explicit profiler checks that the pinned snapshot exists locally, forces Hugging Face offline mode, and executes two synthetic production-core questions with no remote provider call:

```bash
HF_HUB_CACHE=/absolute/local/hf-cache/hub HF_HUB_OFFLINE=1 \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python \
  scripts/profile_workspace_model.py --execute-local-pinned \
  --output-dir /tmp/open-agronomy-model-profile-new \
  --max-tokens 120 --deadline-seconds 900
```

The [observed backend profile](https://github.com/Tknecht4/open_agronomy_agent/blob/main/docs/reviews/artifacts/ui-backend-findings-20260927.md) includes stage timing, retained contrary timing, and memory observations. It found a field-history full-turn loading issue; generation and verification dominated two local model turns. The production stage tracer currently cannot separate lazy model load, tokenizer template, and time to first token. A synthetic or two-turn profile cannot establish a latency budget, concurrency limit, agronomic quality, or benefit from a model change.

Keep evaluation arms separate. `scripts/run_observed_system_rehearsal.py` exercises the typed product core with a mock model and is useful for parity; historical four-arm benchmark scripts retain their own identities and claim limits. Before a repository-wide claim, run the full Python suite, public-doc checker, strict MkDocs build, frontend typecheck/tests/build, and any corpus, retrieval, model, or release gates affected by the change. [Testing and claims](testing.md) and [release readiness](release-readiness.md) describe the gates.

## Publish a fork safely

`configs/public_repository_manifest.json` selects the public package. `src`, `frontend`, `container`, and `docs/public` are included as trees; new explicit scripts, root files, and public-safe review artifacts need manifest entries. Keep runtime databases, raw answers, model weights, credentials, and private overlays outside the package. After documentation changes, run:

```bash
PYTHONPATH=src .venv/bin/python scripts/check_public_docs.py
PYTHONPATH=src .venv/bin/mkdocs build --strict
PYTHONPATH=src .venv/bin/python scripts/build_public_repository.py \
  --destination /tmp/open-agronomy-public-package-new
```

Inspect the builder's output and receipt before treating the package as publishable. A clean package and passing software tests still do not establish field or model competence.
