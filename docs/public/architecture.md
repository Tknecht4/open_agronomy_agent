# Architecture

Open Agronomy Agent is a local-first evidence system. The language model is one component inside a governed pipeline; it is not the authority layer.

## Request path

1. The question frame binds the request to available field identity, crop, jurisdiction, time, management history, geometry, and observations.
2. The router selects retrieval and tool capabilities. Missing context remains explicit rather than being converted to a default value.
3. Corpus policy removes quarantined files before indexing. Retrieval then produces evidence capsules with source, role, scope, currency, applicability, and limitations.
4. Structured tools add deterministic facts. Network adapters declare online/offline status and cache provenance. The calculator executor accepts typed inputs; a bounded planner may extract only explicit supported arithmetic requests and must not infer an agronomic target.
5. The context packer gives the selected model a bounded evidence packet and the stable Open Agronomy kernel.
6. Answer validation checks evidence use, high-consequence boundaries, missing inputs, and required escalation. It may request revision or abstention; it cannot turn weak evidence into strong evidence.
7. The trace store preserves the question, exact model input, retrieval/tool records, answer, field linkage, and implementation identity.

## Model independence

Model profiles own generation limits and model-specific formatting controls. Evidence governance, tool schemas, answer contracts, and trace schemas are shared. Benchmark arms separate raw-model ability, kernel effects, structured field context, and the governed knowledge path so a model upgrade is not confused with a harness upgrade.

## Trust boundary

The system distinguishes:

- **field truth:** grower records, measurements, observations, laboratory results, and verified geometry;
- **decisive guidance:** current, applicable authority that can support an action within stated limits;
- **context:** regional statistics, classifications, historical descriptions, and conceptual relationships;
- **quarantined material:** useful for provenance or research but excluded from model context.

The interface should expose the direct answer first, then evidence, assumptions, missing inputs, tool receipts, and history progressively. A long trace is valuable for audit but should not become noise in the primary conversation.

## Persistence

Fields, sessions, answers, evidence packets, and tool runs use stable identifiers. A later question can therefore reuse verified field history while retaining the original source and time. Updated evidence creates a new version; it does not rewrite the historical answer.

## Implementation status

| Layer | Implemented | Tested | RC1 exercised | Known limit |
|---|---|---|---|---|
| Question/field framing | Yes | Field context and route contracts | Structured field-context arm | Primary RC1 cases were single-turn and had no executable geometry |
| Retrieval | Yes | Corpus, retrieval, and evidence tests | Governed text arm | Concrete resource composition is still being moved behind backend contracts |
| Graph search | Yes, manifest-bound multi-path JSON composition | Manifest, checksum, collision, provenance, exact-name, and routed retrieval tests | Relationship hints in governed arm | Graph relationships remain vocabulary/context rather than field or decision evidence |
| Capability execution | Mixed by capability/surface; calculator has a bounded chat planner | Calculator executor/service/registry and natural-language end-to-end tests; adapter fixtures | Live adapters not executed; RC1 calculator route failed | The repaired calculator path has no post-RC1 benchmark outcome; registration alone does not prove every capability is chat-available |
| Validation/intervention | Yes | Evidence/safety regressions | Fully exercised | RC1 showed model-dependent over-intervention |
| Trace/persistence | Yes locally | Storage, field-event, and trace tests | Regression/interface lanes | Public RC1 exports no longer retain exact answer/judgment records |

See [Capabilities](capabilities.md) for status vocabulary and the repository's
[academic benchmark and system review](https://github.com/Tknecht4/open_agronomy_agent/blob/main/docs/reviews/open-agronomy-benchmark-system-review-20260813.md)
for detailed evidence and the upgrade plan.
