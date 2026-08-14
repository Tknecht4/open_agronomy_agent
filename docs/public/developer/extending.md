# Extending the system

## Add a graph

1. Create a graph artifact containing stable node IDs/names and typed relations.
2. Add a manifest with graph ID/version, schema, source/licence, checksum, namespace ownership, priority/collision policy, and authority role.
3. Run validation for required fields, duplicate IDs, dangling edges, relation vocabulary, source identity, and collision policy.
4. Add the graph and manifest to the active retrieval profile.
5. Add exact-name, routed search, provenance, negative/collision, and startup tests.
6. Regenerate/check the public graph catalog.

Governed profiles fail closed when the configured graph, required manifest, checksum, declared namespaces/relations, collision policy, or edge targets are invalid. Manifest-free loading is a non-authoritative compatibility path for direct callers and fixtures, not a supported runtime-publication contract.

## Add a tool or adapter

1. Define one canonical capability specification: ID/version/kind/status, typed schemas, executor, risk/authority/freshness, offline/network/cache policy, planner requirements, verifier/renderer integration, and exposure flags.
2. Implement a bounded executor returning a typed result and stable invocation/result IDs.
3. Connect the shared result to evidence, generation, validation, rendering, persistence, and trace.
4. Confirm the generic registered dispatch, then generate or parity-check every intended CLI, HTTP, Agno, readiness, and docs surface. Add a named ergonomic parser/normalizer only when its typed arguments need one.
5. Test executor success/failure, input schema, offline/provider state, natural-language selection/execution, evidence continuity, validation, and trace persistence.

A function plus endpoint is not a chat capability. A config flag plus prompt instruction is not a tool implementation.

## Add a knowledge source

1. Record exact source bytes/URL/publisher/date/jurisdiction/rights/hash.
2. Build a deterministic derivative with row-level lineage.
3. Assign context/decisive/quarantine role and limitations.
4. Add a separate runtime-policy admission decision.
5. Validate rights, counts, hashes, leakage, retrieval behavior, and public-release scope.

Never use held-out evaluation answers as runtime retrieval or training material.

## Add an API/service domain

1. Define request/response schemas.
2. Put core/domain behavior in the appropriate package service.
3. Keep the FastAPI route thin and apply auth/workspace/network rules.
4. Add service, API, storage-side-effect, and unauthorized/offline tests.
5. Document the capability status only after the supported path is exercised.

## Add a backend

Implement the relevant retriever, graph provider, executor, validator, or storage protocol and inject it during composition. Preserve the default implementation as an oracle until parity tests pass. Unknown/unported methods must fail explicitly rather than switching stores or skipping evidence.

## Definition of done

- New tool: implementation + one capability spec + generic dispatch/evidence tests. Any optional named parser or legacy normalizer remains a thin, explicitly parity-tested adapter rather than a second capability registry.
- New graph: data + manifest + config + tests.
- The same result/source identity reaches context, verifier, trace, and persistence.
- Offline and missing-provider behavior is deterministic.
- Focused and full tests are reported accurately.
- Public status and limitations agree with the canonical registry.
