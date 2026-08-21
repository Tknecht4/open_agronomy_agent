# Agno runtime adapters

## Purpose and status

This package adapts local retrieval, knowledge graphs, models, capabilities, and traces to the active Agno runtime. `resolve_agent_runtime` currently accepts only `agno`. The adapters do not make every registered capability part of the live chat path; execution and evidence integration must be verified end to end.

## Entry points

- `runtime.py` resolves the active runtime.
- `local_index.py` supplies the local lexical index and `RetrievedDoc` records.
- `knowledge_factory.py` builds the local Agno knowledge facade.
- `knowledge_graph.py` loads/searches configured graph JSON.
- `model_adapter.py` adapts model generation.
- `tool_adapters.py` exposes capability executors to Agno-facing code.
- `trace_adapter.py` creates the Agno trace projection.
- `profile.py` supports benchmark/runtime profiles.
- `source_ingest.py` and `source_manifest.py` govern source ingestion.

## Inputs and outputs

Inputs are versioned RAG/model configuration plus admitted corpus, graph, and source manifests. Outputs are retrieval hits, graph hits, capability results, model messages, and trace projections. Every result should retain the identity needed to reconnect it to its source artifact or invocation.

## Invariants

- Runtime selection is explicit; removed runtimes do not revive through fallback.
- Corpus policy is applied before indexing. Presence on disk is not admission.
- Graph output is vocabulary/relationship context, not field truth or action authority.
- Model adapters receive bounded evidence and do not own corpus or safety policy.
- Tool adapters expose an executor; they do not by themselves prove planner, verifier, renderer, and persistence parity.
- Rollback checks preserve identity and fail when a requested transition is unsupported.

## Add a graph

The loader accepts multiple paths under `retrieval.graph_paths`; governed runtime profiles set `require_graph_manifests: true`. The extension contract is:

1. create the graph JSON under an admitted `data/` location;
2. add a graph manifest declaring stable graph ID/version, schema, source and licence, checksum, namespace ownership, priority, collision policy, and authority role;
3. validate node IDs, required fields, relations, dangling edges, and cross-graph collisions;
4. add the path/manifest to the active RAG configuration;
5. add exact-name, routed search, provenance, collision, and missing-file tests; and
6. update the generated graph catalog/public docs only after validation.

Current graph JSON uses `nodes` and `edges`; node records require at least `id` and `name`, while edges use `source`, `target`, and an optional `relation`. Governed composition verifies the manifest/schema/checksum, declared namespaces and relation vocabulary, duplicate graph and node identities, collision precedence, and dangling edges before use. Manifest-free loading remains only as a non-authoritative compatibility path for direct callers and fixtures.

## Add a retriever or model backend

Implement the shared backend contract, preserve stable result fields, inject it during resource composition, and run parity tests against the default local implementation. Do not branch behavior throughout `agent.py` or chat services based on concrete backend classes.

## Configuration

The active governed profile is `configs/rag.yaml`, admitted
by `configs/runtime_profiles.json`. Frozen and candidate profiles are not
selectable by file presence. The public v1/final-MVP files are historical
benchmark identity inputs and may point to intentionally absent legacy payloads.
Relative configured artifacts resolve through repository/config artifact roots
and must be included in identity hashing.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_retrieval.py \
  tests/test_query_context.py \
  tests/test_public_tool_adapters.py
```

Add a startup/preflight test for every new graph or backend. A search-unit test alone does not prove live chat or evidence use.

## Failure modes

Missing/corrupt artifacts, graph collisions, dangling edges, policy exclusion, stale cache identity, unsupported runtime, and incompatible backend output must be explicit. Network-backed ingestion never gains egress merely because an adapter exists.
