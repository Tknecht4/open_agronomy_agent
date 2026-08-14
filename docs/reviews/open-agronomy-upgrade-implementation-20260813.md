# Open Agronomy Agent upgrade implementation record

**Date:** 2026-08-13
**Status:** cross-cutting foundations and vertical slices implemented; internal, research, publication, and external-authority gates remain open
**Source plan:** [benchmark and internal-system review](open-agronomy-benchmark-system-review-20260813.md)

## Executive outcome

The repository now implements the proposed cross-cutting foundations and first production vertical slices: a canonical capability registry, typed calculator planning and evidence, governed graph manifests, consequence-calibrated answerability states, a stage-aware evaluation harness, privacy-safe benchmark retention/export paths, and a generated public documentation site. It does not yet replace every task-specific chat trigger with a general registry-driven planner.

The upgrade changes the unit of control from “is any field evidence missing?” to “which claim or action is being made, and what evidence or authority does that claim require?” Benign explanations can answer directly. A deterministic calculation uses only supplied quantities. Missing calculator input produces one specific question. Field-dependent guidance remains bounded. Product selection, label rates, irreversible calls, and other consequential actions retain explicit authority gates.

This is implementation and contract evidence, not a new agronomic-performance result. No post-upgrade model-backed benchmark, Luna judging round, independent agronomist adjudication, real-user study, GitHub publication, or professional validation was performed as part of this change.

## Phase-by-phase reconciliation

### Phase 0 — Evaluation observability and retention

Implemented:

- a content-addressed private retention bundle with schema validation, source/run identities, canonical SQLite preservation, exact-file inventories, retained builder/schema bytes, recomputed private content hashes, and database-keyed public-row commitments to both response and judgment records;
- a public-safe derivative that exports typed/range-checked measurements, pseudonymized identities, and allowlisted material-error/category codes without prompts, answers, rationales, retrieved text, arbitrary metadata, or low-entropy unsalted content hashes;
- terminal execution recording before retention, followed by a separate completion receipt that binds the immutable bundle without a self-referential hash;
- adversarial tests for answer/rationale leakage and spreadsheet-formula injection; and
- a fail-closed requirement that a declared complete run retain its canonical database.

Not performed:

- the historical RC1 databases and per-answer Luna records were not present, so they could not be reconstructed;
- a pre-change current-checkout baseline could not be created after implementation began; and
- no new model/judge run or stochastic-repeat study was authorized.

Accordingly, RC1 remains historical evidence and the upgraded checkout has no performance baseline. The retention machinery is ready for the next authorized run.

### Phase 1 — Canonical capability registry

Implemented:

- typed `ToolSpec`, `GraphSpec`, and extension protocols in one canonical registry;
- a JSON-safe catalog for router, CLI, HTTP, Agno, readiness, and documentation surfaces;
- a canonical `GET /api/tools/capabilities` endpoint consumed by the frontend status view;
- generated capability documentation and drift checks;
- registry-driven generic CLI execution and Agno/listing views;
- fail-closed declared input/output schema validation around registered executors; and
- duplicate, unknown-required, readiness-parity, schema, graph-parity, and documentation-path tests.

The registry distinguishes implemented, tested, and benchmark-exercised status. In particular, the calculator is implemented and tested but remains **not benchmark-exercised**, because RC1 exposed the route without invoking the typed calculator and no post-repair model-backed round has run.

Legacy named CLI parsers, HTTP request normalizers, and natural-language planning still require explicit integration code where their interfaces differ. The registry is the source of truth for identity and status, not a claim that every surface can be generated without adapter work.

### Phase 2 — Unified planning, execution, and evidence

Implemented:

- stable `ToolPlan`, `ToolInvocation`, and `ToolResult` contracts with version, authority, status, provenance, limitations, and hashes;
- a deterministic natural-language calculator vertical slice covering the frozen 16-case calculation suite;
- minimal one-input clarification for incomplete arithmetic;
- one result identity carried through prompt/context assembly, verifier input, the unified `EvidencePacket`, trace, and database;
- typed evidence contributions for tools, graph hits, field context, retrieved documents, and public adapters without collapsing their authority roles;
- deterministic rendering that bypasses model generation for validated arithmetic; and
- graph-result payload hashes that identify the individual record while retaining the source graph checksum separately.

For a user-supplied product-label number, the renderer performs only the unit conversion and explicitly says that it does not establish label currency, applicability, or permission. Asking the system to choose or supply the product rate still requires current authority.

Open internal gate: the general chat planner is not yet a registry-wide `QuestionFrame`/`DecisionContract` planner. It currently owns the calculator vertical slice, ignores `field_context` during calculation planning, and coexists with older task-specific trigger ladders. Adding a new natural-language capability can therefore still require a planner adapter even though typed generic CLI/HTTP execution no longer requires bespoke dispatch code.

### Phase 3 — Governed graph composition

Implemented:

- a versioned JSON Schema and checksum-bound manifests for active seed and SoilWise graphs;
- source, license, namespace, relation-vocabulary, authority-role, merge-priority, and collision-policy declarations;
- fail-closed validation of missing files, malformed manifests, checksum drift, duplicate or dangling identities, undeclared relations, and unsafe collisions;
- graph/source identity and relation paths on every `GraphHit` and downstream evidence record;
- portable/offline/update packaging of graph manifests; and
- a generated graph catalog checked against the active RAG configuration.

Legacy fixture loading remains available only as non-authoritative test compatibility. Production configurations require governed manifests.

### Phase 4 — Consequence-calibrated intervention

Implemented:

- versioned domain rule packs and universal safety invariants;
- explicit answerability states: direct answer, bounded answer, one discriminating question, authority required, and unsafe-action refusal;
- regulated-action precedence over broad conceptual or calculation wording;
- typed authority receipts requiring the exact authority, validated status, current freshness, and complete applicability rather than accepting generic supporting guidance;
- separate draft, post-verification, and final outputs with hashes and defect-linked replacement records; and
- matched benign, calculation, field-decision, regulated-action, and paraphrase regression tests.

This closes observed failure modes in which benign explanations were over-guarded, calculation questions were left to prose generation, conceptual phrasing bypassed label controls, or an unrelated applied guide could satisfy a current-label requirement.

Open internal gate: replacement audits now bind stable rule IDs, failed-claim excerpts, and evidence IDs, but the legacy verifier still treats any detected reason as review-worthy. Risk adds a high-consequence reason rather than applying an empirically selected risk-dependent score threshold. Selecting those thresholds without a fresh untouched evaluation would be tuning by assertion, so this remains a measured-policy gate rather than an invented constant.

### Phase 5 — Evaluation harness

Implemented:

- 30 matched project-authored cases across six agronomic topic groups and five response strata;
- nine component-isolation arms and an injected executor contract;
- separate, denominator-aware measurements for directness, unnecessary abstention, clarification quality, tools, numeric accuracy, verifier behavior, stage utility, origin/fallback, and risk calibration;
- model/revision/arm-separated reporting and within-model paired contrasts;
- a frozen harness feature handshake with separate construct, cohort, and system fingerprints; a construct-semantic profile for tools, evidence, answerability, and verifier decisions; component-specific receipt state machines; complete model/run/executor identity; fail-closed unknown-stage and unknown-semantic handling; and explicit `comparable`, `migration_required`, or `new_benchmark_required` outcomes;
- a deterministic dry executor that exercises the 270 case-arm topology as harness contract QA while marking unsupported real execution unavailable; and
- content-addressed design, schema, manifest, audit, runner, and integration tests.

Important methodological correction: all 30 exact questions were inspected and probed during implementation, and their failures informed planner and answerability changes. Benchmark v2 is therefore an **exposed development regression suite**, not an untouched preregistered evaluation. An append-only exposure amendment preserves that fact. Its dry-run output is not model performance, its results are claim-ineligible, and independent review cannot restore holdout status. Any future evaluative claim requires a freshly authored untouched successor (v3), preferably with independent authorship and adjudication.

Harness stability is distinct from holdout validity. Continued development may remain comparable when the frozen construct and harness semantics match and the changed implementation is recorded as the system under comparison. New tool or evidence implementations can map into an existing semantic class and remain a distinct comparable system; raw IDs are preserved while metrics use the frozen family and operation. Additive trace representation requires a declared migration that preserves raw observations; v2 currently declares no production migration adapter. A changed arm meaning, scoring denominator, stage topology, authority vocabulary, verifier decision unit, or unisolated answer-affecting feature requires a new benchmark version. Unknown active features and unknown semantic classes fail before scoring rather than disappearing into the full-system arm. Answerability states are bound to observable intervention behavior, component receipts are bound to actual artifacts/configuration, and pooling requires complete identical model, run/sample, executor, cohort, and system identity rather than a negotiation label alone.

Still external/human-gated:

- independent multi-agronomist authorship and adjudication;
- reported disagreement and judge calibration;
- consented real-user, multi-turn, executable-geometry, image, cache/live, and field-history lanes;
- repeated model/judge samples and a post-upgrade retained performance run; and
- prospective usability or field evidence.

### Phase 6 — Documentation and GitHub Pages

Implemented:

- a concise root README with setup, pinned model provisioning, launch, API health, shutdown, footprint, safety, privacy, offline, and benchmark boundaries;
- subsystem READMEs for the Python package, server, Agno runtime, tools, frontend, configurations, data/manifests, scripts, tests, and containers;
- a MkDocs public site covering architecture, capability and graph catalogs, evidence/data, tools, evaluation, development, operation, and governance;
- generated catalog drift checks, internal-link checks, private-scope checks, rendered-site inspection, and a fail-closed public-repository inventory;
- a GitHub Pages workflow that builds on pull requests and permits deployment only from the default branch through the Pages environment, with pinned actions and least privilege; and
- reliable cockpit cleanup so normal exit and interruption stop both API and frontend processes.

The site was built and audited locally. It was not deployed: publishing requires an intentional reviewed commit, default-branch workflow execution, and repository-owner approval.

## Cross-cutting defects found and repaired

The implementation audit identified several issues not obvious from the original plan:

- answer stages and verifier drafts leaked through the supposedly redacted export modes;
- valid-looking private values could hide under structural-looking keys inside extension metadata;
- benchmark public CSVs could carry arbitrary judge text or spreadsheet formulas;
- the retained experiment was snapshotted before its terminal invocation receipt;
- graph evidence reused the whole-graph checksum as if it were a per-result payload hash;
- deterministic clarification was incorrectly labeled as a validated typed result on one interface;
- generic source support could satisfy a current-label authority check;
- product-rate requests could hide behind conceptual or calculation phrasing;
- the public repository builder could introduce unreceipted bytecode while regenerating manifests;
- a quarantined missing corpus could break governed knowledge-update packaging; and
- clean test collection needed both the repository root and `src` layout on `sys.path`.

Each repaired defect has a focused regression test. Redacted modes now recursively sanitize nested traces, events, data sources, prompts, tool/graph payloads, evidence records, and all three answer stages before any export projection.

## Claim boundary and remaining gates

The implementation supports the claim that Open Agronomy Agent now has stronger, testable foundations for extensibility, evidence provenance, graph composition, deterministic tools, consequence-calibrated intervention, privacy-safe artifacts, and documentation drift. The claim is strongest for governed graphs and the calculator vertical slice; it is not yet a claim that every capability is automatically natural-language plannable.

It does **not** yet support claims of general agronomic-agent ability, agronomist equivalence, field reliability, improved post-upgrade answer quality, independent validation, or production safety. Those claims remain blocked by the research gates in the source review and by the absence of a retained, independent, model-backed successor evaluation.

## Verification record

Verification is intentionally reported by contract rather than collapsed into a quality score. The final repository reconciliation includes:

- full backend test collection from the repository root;
- the complete 30-case planner/answerability matrix;
- the 16-case calculator result-identity path;
- benchmark v2 schema, hash, design, metric, runner, exposure, and dry-topology checks;
- graph, capability, evidence, retention, export-redaction, public-package, startup/shutdown, API, and documentation checks;
- strict MkDocs source and rendered-site audits under Python 3.12; and
- frontend unit, type, and production-build checks.

Final handoff snapshot on 2026-08-13:

- the complete repository-root Python suite passed **664 tests** with four existing Starlette/httpx deprecation warnings;
- the focused v2 harness/design selection passed **94 tests**, and the model-free design audit passed **93 checks** while byte/hash-verifying all **19** manifested artifacts;
- the deterministic, claim-ineligible v2 dry run completed **270/270 observations** across **30 cases × 9 arms**;
- the frontend passed **202 tests** across **31 files**, TypeScript checking, and a production build;
- the strict documentation build and source/rendered audits passed across **20 Markdown sources** and **71 rendered files**; and
- the fail-closed public repository builder produced **656 receipted files** with no bytecode or egg-info leakage.

These counts describe this exact handoff and will naturally become historical as tests are added. A focused result demonstrates only its named contract, and the dry topology is harness QA rather than a model-performance result.

## Final assessment

Every phase has an implemented artifact and executable acceptance evidence, but not every original acceptance gate is closed. The principal internal remainder is migration from the calculator-specific planner and legacy task triggers to a general registry-driven `QuestionFrame`/`DecisionContract` planner. The exposed v2 evaluation contract still combines document and graph retrieval in one component, so v2 cannot measure the graph's incremental contribution and must not be retrofitted after exposure. The newer observed production-path rehearsal implements four explicit controls—neither, document only, graph only, and both—through the typed server execution core and independently receipts both retrieval stages. That 2×2 is valuable harness-isolation QA and a prerequisite for a future v3 experiment, but it is not a completed v3 model-backed ablation or performance result. The principal measured-policy remainder is selecting risk-dependent verifier thresholds from fresh evidence. External remainders are new data collection, independent scientific review, authorized model/judge execution, owner-controlled publication, and prospective evidence. Keeping those categories separate prevents a strong foundation from being misreported as a completed scientific validation or a fully generic agent architecture.
