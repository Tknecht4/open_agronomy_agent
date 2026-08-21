# Open Agronomy Agent benchmark and internal-system review

> Implementation follow-up: see the [2026-08-13 upgrade implementation record](open-agronomy-upgrade-implementation-20260813.md) for completed internal changes, verification scope, and remaining research/publication gates.

- **Date:** 13 August 2026
- **Review type:** repository-grounded academic and architecture review
- **Benchmark snapshot:** RC1 at commit `76644dcab85ac635cb9f976ff6c769b4a6cd4da8`
- **Current implementation inspected:** commit `47f06135389b02dcf6a6f7908550d9fb586329cc`
- **Status:** development evidence; not independent agronomist validation, field validation, or a production-readiness opinion

## Executive judgment

The RC1 benchmark is a credible and unusually candid **controlled development study**. It is not yet a general benchmark of “agronomic agent ability.” Its strongest evidence concerns evidence-boundary behavior, intervention/fallback behavior, and failures in the implemented orchestration path. It does not establish agronomist equivalence, real-grower utility, field outcomes, or the current checkout's performance.

The repository still preserves the published RC1 scores and receipts, including all 2,892 response-level scalar records. It does **not** currently preserve the canonical SQLite databases, answer text, exact Luna judge prompts/outputs, or response-level rubric dimensions described by the protocol. Consequently, this review can audit the published measurements and design, but it cannot independently reread each answer or decompose each Luna score into its five stored dimension values. The database hash proves that a database existed; it does not make the present checkout fully reanalyzable.

The user's concern that the system can be “safe but vague” is supported by the available data:

- Luna High scored `97.18` with the kernel plus field context and `83.38` with the full governed system. The full arm was worse on 67 of 90 paired cases relative to the field-context arm.
- On 16 fully specified calculations, Luna answered 15 correctly in both the raw and field-context arms but 0 correctly in the governed arm. Its average answer grew from 20.8 characters raw to 358.3 characters governed, while almost all governed values became unparsable.
- Gemma 4 benefited on average from the full system, but the full arm was still worse than its field-context arm on 31 of 90 primary cases and received 15 full-arm fail dispositions.
- The full arm produced fallback or degraded outputs on 55/90 Gemma 3, 38/90 Gemma 4, and 35/90 Luna primary cases. The surfaced answer is therefore often a system artifact rather than an unmodified expression of model capability.

This is not evidence of deliberate benchmark tricks or score laundering. The repository freezes identities, separates lanes, preserves negative results, blinds the semantic judge to arm/model metadata, prohibits a single composite, and repeatedly states its claim limits. The central validity problem is narrower: the project authors designed the system, primary questions, reference criteria, and rubric around the same evidence-and-caution philosophy. All 90 primary cases require the `field_data_guard`, and many explicitly signal missing evidence or unsafe extrapolation. That is appropriate for a safety-boundary suite, but it does not represent the full distribution of benign, answerable agronomy work.

Architecturally, the project has solid provenance concepts and a useful multi-graph configuration seam, but it is not yet extension-oriented. Graph files can be added through configuration, although missing files, duplicate IDs, dangling edges, merge precedence, provenance, and licensing are not governed by a manifest contract. Tools are split across guard functions, local executors, Agno adapters, HTTP dispatch, chat-specific triggers, CLI dispatch, and tests. A tool registered in one surface is not thereby available to natural-language chat. The highest-value internal upgrade is a canonical capability registry plus one typed evidence flow shared by planning, execution, generation, verification, trace, persistence, testing, and documentation.

## Direct answers to the review questions

| Question | Finding |
|---|---|
| Are the Luna outputs still present? | **Partly.** All scalar Luna score rows and aggregate tables remain. Exact candidate answers, judge prompts/outputs, rationales, confidence, validity labels, dimensions, and row-level traces are absent. |
| Can the measurements be analyzed? | **Yes, with a boundary.** Aggregate and response-level scalar behavior can be analyzed. Exact-answer qualitative review and per-dimension reconstruction cannot be done from this checkout. |
| Is the benchmark fair? | **Fair for paired within-model comparisons on the frozen suite; not fair as a general model ranking or population estimate.** |
| Is it honest? | **Largely yes.** Negative results and limitations are explicit. Artifact retention is the main operational reproducibility gap. |
| Is it general? | **No.** It is geographically broad within Canada but construct-narrow and dominated by evidence-boundary scenarios. |
| Does it measure agronomic-agent ability? | **Only selected components.** It measures written behavior under synthetic Canadian field scenarios and the effect of governance. It does not measure the full agent loop, live tools, multi-turn diagnosis, field outcomes, or professional competence. |
| Is over-caution harming usefulness? | **Yes in important strata.** The clearest causal evidence is the Luna full-arm regression and the 0/16 governed calculation result. The current suite cannot estimate how often this happens in ordinary use because it lacks a preregistered benign-question stratum. |
| Is the current code readily extensible? | **Partly for graph data; not yet for end-to-end capabilities.** Tool and evidence integration require coordinated edits across several modules. |

## 1. Scope, method, and evidence boundary

This is a repository-internal academic-style review, not a peer review and not an agronomist adjudication. It used the frozen protocol, construct audit, public row-level results, aggregate tables, scoring implementation, benchmark contracts, current agent code, graph/tool implementations, tests, and documentation tree.

The primary evidence is:

- the [frozen RC1 protocol](../public/final-benchmark-20260812/source_data/protocol.md);
- the [benchmark contract](../../configs/open_agronomy_canadian_performance_v1.json) and [interface contract](../../configs/open_agronomy_canadian_performance_interface_v1.json);
- the [construct audit](../../data/eval/open_agronomy_canadian_performance_v1_construct_audit.md);
- the [response-level metrics](../public/final-benchmark-20260812/source_data/response_level_metrics.csv), [paired deltas](../public/final-benchmark-20260812/source_data/paired_semantic_deltas.csv), [orchestration summary](../public/final-benchmark-20260812/source_data/orchestration_summary.csv), and [error taxonomy](../public/final-benchmark-20260812/source_data/material_error_taxonomy.csv);
- the [semantic judge implementation](../../scripts/run_codex_semantic_answer_judge.py);
- the [benchmark paper](../public/final-benchmark-20260812/main.tex); and
- the current agent, graph, tool, evidence, routing, verification, server, and documentation code.

No new model generations or Luna judgments were run. RC1 describes commit `76644dc`; the inspected checkout has HEAD `47f0613`. The current prompt now explicitly asks for a direct answer and generally two to four compact paragraphs for a field decision, which may address some RC1 behavior, but that change has not been evaluated in a comparable frozen run. All performance findings below are therefore historical RC1 findings; current-code conclusions are static architecture findings.

### 1.1 Observation, interpretation, and recommendation

To avoid turning inference into fact, this document uses three evidence levels:

- **Observation:** directly present in committed data, code, receipts, or tests.
- **Interpretation:** the most plausible explanation of one or more observations, with alternatives retained where evidence is incomplete.
- **Recommendation:** a proposed change, not a claim that the change is already implemented or will improve field outcomes.

## 2. Luna artifact status

### 2.1 What remains

The public benchmark package retains:

- 2,892 response-level rows: 241 cases × 4 arms × 3 candidates;
- 964 Luna candidate rows;
- semantic score, pass/revise/fail disposition, `needs_source_validation`, timing, token counts, answer-character count, and judge/generator relationship for each row;
- lane-, task-, orchestration-, resource-, paired-delta-, and error-level summaries;
- a validation receipt stating that the original internal database contained 2,892 responses and 2,892 judgments; and
- the canonical database SHA-256, `6e155a7ff1e40fae34741a9a81fd96b6576886c0ed1de9ba92a1a5db0faa9c6b`.

### 2.2 What is absent

The protocol names `outputs/open_agronomy_canadian_performance_v1_rc1/full_system_benchmark.sqlite3` as the canonical internal database and a corresponding external database. Neither is present in this checkout or elsewhere found under the user's local project tree. `outputs/cockpit/phase3.sqlite3` is an application/session database, not the benchmark database. The entire `outputs/` tree is ignored by Git.

The present public package does not include:

- candidate answer text or answer hashes;
- exact judge prompts and raw judge outputs;
- response-level values for the five rubric dimensions;
- judge rationale, confidence, and question-validity labels;
- response-level material-error codes;
- row-level verifier, intervention, fallback, and answer-origin traces; or
- semantic-judge batch receipts.

The public analysis script reads the dimensions and errors from SQLite but omits dimensions from `response_level_metrics.csv`. It reduces material errors to the 20 most common free-form labels per model/arm. That means a total score cannot be uniquely decomposed after the fact, and error prevalence cannot be reconstructed reliably.

### 2.3 Academic implication

The measurements are still useful as a frozen derived dataset, but the strongest reproducibility statement in the paper is no longer operationally true for this checkout. A checksum establishes identity if the database is recovered; it is not a substitute for retaining the artifact. This should be recorded as an **artifact-retention gap**, not as evidence that the reported numbers were fabricated.

## 3. What the benchmark does

RC1 evaluated three candidate generators on the same 241 project-controlled cases using four arms, producing 2,892 answers before semantic judging.

### 3.1 Case lanes

| Lane | Cases | Intended role | Main limitation |
|---|---:|---|---|
| Canadian decision quality | 90 | Primary written-answer comparison across nine task families | Synthetic, single-turn, project-authored, no independent agronomist gold standard |
| Canadian advisory transfer | 31 | Secondary decision-contract and transfer behavior | Project-authored and not population-representative |
| Field-history lineage | 32 | Trace and source/authority regression | Interface behavior, not general answer quality |
| Official-source answer boundary | 39 | Source specificity and scope regression | Narrow source/contract behavior |
| Retrieval lineage | 33 | Expected-source retrieval regression | Retrieval correctness, not end-to-end field utility |
| Objective agronomic calculations | 16 | Numeric value/unit/tolerance anchor | Small project-authored set; natural-language tool path failed |

The 120 interface/regression cases are correctly kept separate from the semantic capability lanes. They must not be averaged into a single “agronomy intelligence” score.

### 3.2 Four conditions

| Arm | What the candidate receives | What it isolates | Important exclusion |
|---|---|---|---|
| Raw model | User question only | Standalone generator behavior | No Open Agronomy kernel, retrieval, verifier, or post-processing |
| Kernel only (`baseline`) | Shared kernel and answer contract | Instruction/formatting effect | No structured field context, retrieval, tools, intervention, or verifier |
| Kernel + field context | Kernel plus crop, region, jurisdiction, and management context when present | Value of minimal structured context | No retrieval, tools, intervention, or verifier |
| Governed agent (`agronomic_rag`) | Kernel, governed retrieval, evidence intervention, configured verifier, and output processing | Effect of the bundled governed text-agent path | Live service adapters are traced but not executed |

The interface contract explicitly labels this as `core_agent_text_only` and says service orchestration is not exercised. The “full system” label is therefore convenient but overly broad: it does not evaluate the complete deployed agent, live adapters, geometry services, or reliable natural-language calculator execution.

## 4. Measurement glossary

### 4.1 Luna semantic score

The Luna judge assigns each dimension a 0–4 value. The weighted mean is scaled to 0–100:

| Dimension | Weight | Intended construct |
|---|---:|---|
| Agronomic accuracy | 35% | Factual and causal correctness; no invented field facts |
| Decision relevance | 20% | Direct resolution of the grower's decision rather than a generic checklist |
| Completeness/actionability | 20% | Material observations, decision logic, and practical next action |
| Calibration/safety | 15% | Separation of evidence from inference; no unsupported rates, labels, diagnoses, or guarantees |
| Crop/region/source fit | 10% | Crop biology, production system, jurisdiction, terminology, and source applicability |

**Strength:** the rubric includes usefulness and directness; it does not reward caution alone. The judge instructions explicitly say not to substitute checklist length, style, or number of caveats for quality.

**Limit:** the weights are author-selected and uncalibrated against agronomists. The response-level dimension values are absent, so this review cannot determine whether a given score moved because of accuracy, relevance, actionability, safety, or regional fit.

### 4.2 Pass, revise, and fail

Disposition is a separate categorical judgment:

- **Pass:** sound and useful as written.
- **Revise:** directionally sound with a repairable omission or overgeneralization.
- **Fail:** a material error, unsafe certainty, wrong crop/source/system, irrelevant response, or failure to answer the central decision.

Disposition is not mechanically derived from the 0–100 score, so a score threshold cannot be reverse-engineered from it. It is best treated as a second advisory label, not a calibrated clinical-style category.

### 4.3 `needs_source_validation`

This marks answers containing a current local label, regulation, numeric threshold, or niche factual claim that should be checked against authority. It does not mean the whole answer is wrong. It was set on 854 of 1,080 primary judgments (79.1%). Because the primary cases were intentionally designed around source and field-evidence boundaries, this rate cannot be generalized to ordinary user questions.

### 4.4 Material-error taxonomy

The judge can emit up to five concise error labels plus a rationale. This is useful for triage, but the labels are unconstrained free text. Synonyms such as `non_answer`, `nonanswer`, `central_decision_unanswered`, and `fails_to_answer_central_decision` fragment the same construct. The public export contains only the top 20 labels per model/arm and no row-level mapping, so it supports examples, not prevalence estimates.

### 4.5 Objective calculation accuracy and parse validity

The 16 calculation cases use deterministic reference values, units, and tolerances. `objective_accuracy` measures numeric correctness. `parse_valid` reports whether the answer contains an extractable value and accepted unit. This is the benchmark's strongest criterion-valid measurement because it does not depend on an LLM judge.

### 4.6 Proxy score

Legacy deterministic keyword or answer-contract scores remain regression diagnostics. The benchmark correctly states that they are not semantic answer quality and must not be treated as ground truth. They are valid only for the narrow interface contract that created them.

### 4.7 Paired deltas and bootstrap intervals

Each arm is paired by case within a model. The reported 95% intervals resample the fixed case set 10,000 times. They show sensitivity to which frozen cases are selected; they do not capture:

- model sampling variance;
- judge variance;
- question-author or reference uncertainty;
- agronomist disagreement; or
- uncertainty about the real grower-question population.

### 4.8 Orchestration measurements

The orchestration table counts interventions and their final actions: accepted rewrite, preserved draft, fallback/degraded output, or no action. These measurements are essential because a high full-arm score can come from deterministic fallback rather than the candidate model. They measure system behavior, not just generator skill.

### 4.9 Resource measurements

Latency, prompt tokens, generation tokens, and generation throughput describe the candidate-generation environment. They are descriptive rather than quality measures. Cross-model timing is not a clean algorithmic comparison because the local MLX models and remote Luna backend use different execution environments.

### 4.10 External reference-token F1

The external diagnostic compares generated Gemma 4 answers with published Uganda-source AgroQA answers by normalized token overlap. Raw mean F1 was `0.050809`; governed mean F1 was `0.059490`; the paired change was `+0.008681` with 152 improved, 4 unchanged, and 100 worse cases.

This is a one-time transfer diagnostic, not Canadian validation. Token overlap is especially weak when multiple agronomically sound phrasings exist, and the source answers were not independently revalidated. The repository correctly prevents the same implementation from being repaired and rerun on this held-out version.

## 5. RC1 findings

### 5.1 Primary semantic lane

| Candidate | Raw | Kernel | Kernel + field | Governed | Governed − raw | Governed pass/revise/fail |
|---|---:|---:|---:|---:|---:|---:|
| Gemma 3 270M | 2.50 | 5.67 | 10.15 | 73.13 | +70.63 | 21 / 49 / 20 |
| Gemma 4 E2B | 54.71 | 66.42 | 70.61 | 77.93 | +23.22 | 20 / 55 / 15 |
| Luna High | 89.82 | 96.56 | 97.18 | 83.38 | −6.45 | 36 / 46 / 8 |

The paired full-minus-raw change for Gemma 4 was +23.22 points, fixed-suite CI `[17.60, 28.59]`, with 76 improved, 2 unchanged, and 12 worse cases. For Luna it was −6.45, CI `[−11.52, −1.18]`, with 29 improved, 11 unchanged, and 50 worse.

The more diagnostic comparison for over-governance is governed versus kernel + field:

- Gemma 4: `+7.32` points; 55 improved, 4 unchanged, 31 worse.
- Luna: `−13.81` points; 10 improved, 13 unchanged, 67 worse.

For Luna, the full system was worse than field context in all nine task families. The largest mean losses were diseases (`−31.88`), pests (`−21.75`), soils (`−18.06`), weeds (`−15.62`), and weather (`−14.12`). Gemma 4 improved in eight of nine families, with a small disease decline (`−1.06`). This is a model-capability interaction, not a universal RAG benefit.

### 5.2 Intervention and answer origin

| Candidate | Intervention triggered | Fallback/degraded | Accepted rewrite | Preserved draft | No action |
|---|---:|---:|---:|---:|---:|
| Gemma 3 270M | 55/90 | 55/90 | 0/90 | 1/90 | 34/90 |
| Gemma 4 E2B | 46/90 | 38/90 | 8/90 | 18/90 | 26/90 |
| Luna High | 54/90 | 35/90 | 19/90 | 10/90 | 26/90 |

**Interpretation:** the governed Gemma 3 result is largely a harness/fallback result. That may be useful product behavior, but it does not show that a 270M model independently acquired agronomic reasoning. The same intervention policy is too aggressive for Luna and sometimes for Gemma 4.

Forty-seven of 90 full-arm primary rows have the same answer-character count across all three models. Without answer hashes or text this does not prove identical answers, but it is consistent with common fallback templates and should be investigated when the canonical database is recovered or the benchmark is rerun.

### 5.3 Objective calculations

| Candidate | Raw | Kernel | Kernel + field | Governed | Governed parse-valid |
|---|---:|---:|---:|---:|---:|
| Gemma 3 270M | 0/16 | 0/16 | 0/16 | 0/16 | 1/16 |
| Gemma 4 E2B | 5/16 | 6/16 | 4/16 | 0/16 | 2/16 |
| Luna High | 15/16 | 13/16 | 15/16 | 0/16 | 1/16 |

The registered typed calculator was not invoked in any of the 16 traces. The calculation cases also declare no expected tool, so the evaluation contract did not require the orchestrator to demonstrate calculator selection. This is simultaneously:

1. a valid negative result about the actual text-agent path;
2. an integration defect, because a registered calculator was not connected to natural-language decisions; and
3. a benchmark-design omission, because the “full agent” condition did not require its relevant tool.

For Luna, concise mostly correct raw answers became longer, mostly unparsable governed answers. This is the clearest available evidence that general caution and fallback logic can override a benign, fully specified task.

### 5.4 Does the system merely sound vague?

The concern is not just stylistic. Public error examples for governed answers include `central_decision_unanswered`, `insufficient_direct_decision`, `does_not_answer_current_safety_directly`, `unsupported_refusal`, `no_direct_crop_recommendation`, and `nonresponsive_to_map_scale_question`. The task-family and calculation regressions show a measurable loss of decision completion, not merely shorter prose.

At the same time, the evidence is mixed rather than universally negative:

- Gemma 4 improves substantially from raw to governed on average.
- The strongest model is harmed by the same intervention intensity.
- The weak model is frequently replaced by fallback content.
- The benchmark does not contain a preregistered benign-question stratum, so it cannot estimate how often unnecessary caution occurs in normal use.

The academically defensible conclusion is therefore: **the current intervention policy is insufficiently capability- and risk-calibrated. It can improve a medium local model, rescue a weak generator through fallback, and suppress correct, direct behavior from a stronger model or deterministic task.**

## 6. Academic design review

### 6.1 Construct validity

The claimed construct must be narrowed. The primary lane has balanced task-family, jurisdiction, and question-style coverage, but every one of its 90 cases requires `field_data_guard`; 42 cases require four guards/tools. Support modes are 30 bundled-applied-guidance, 20 live-authority-required, 20 bundled-regional-product, 10 cross-jurisdiction-transfer, and 10 insufficient-evidence.

Many questions explicitly include phrases such as “no tests,” “only,” “without scouting,” “is that enough,” or “what can the agent safely do?” This is not a hidden trick; it is visible safety-boundary authoring. It makes the suite sensitive to unsafe extrapolation, but comparatively insensitive to concise factual explanation, straightforward calculations, and fully answerable low-risk decisions.

**Verdict:** good construct coverage for governed evidence-boundary behavior; poor construct coverage for general agronomic-agent ability.

### 6.2 Internal validity and causal attribution

Strengths:

- same frozen cases across arms within each model;
- answers stored before scoring;
- model/config/suite/implementation identities frozen;
- arm/model path hidden from the semantic judge;
- raw, kernel, and field-context arms prevent attributing every change to retrieval;
- deterministic calculations and interface lanes separated from semantic scores; and
- negative effects retained.

Limitations:

- the full arm bundles retrieval, evidence intervention, verification, rewriting, fallback, and post-processing, so the harmful component cannot be isolated;
- live service orchestration is not executed;
- one answer generation and one judgment per case provide no repeatability estimate; and
- the current implementation differs from the frozen implementation.

**Verdict:** reasonable causal evidence for the bundled arm effect at RC1; insufficient causal resolution inside the full arm.

### 6.3 Criterion validity and judge reliability

The judge sees the question, candidate answer, crop, region, jurisdiction, scenario, task family, project reference answer, expert points, material errors, critical evidence, safe boundary, and acceptable variants. It is blinded from the candidate identity, arm, proxy score, generation path, and verifier result. That is a good anti-bias control.

However:

- Luna High judges Luna High candidate answers (`same_exact_model`), making cross-model ranking especially vulnerable to self-preference;
- the rubric and reference criteria are project-authored and not independently adjudicated;
- weights are not calibrated against agronomist judgments;
- disposition is not tied to a validated threshold;
- material-error codes are uncontrolled; and
- no repeated judging or inter-rater agreement is reported.

**Verdict:** useful development triage, not an independent criterion standard.

### 6.4 Statistical conclusion validity

The case-level paired design and fixed-suite bootstrap are appropriate for describing this suite. The paper correctly limits the interval to fixed-suite sensitivity. The main remaining issues are one-shot model/judge observations, small strata of ten cases per task family, ceiling/floor effects, and no hierarchical uncertainty for model, judge, author, or real-user population.

**Verdict:** adequate descriptive statistics for a frozen development experiment; inadequate uncertainty for population or professional-competence claims.

### 6.5 External validity

The suite contains zero confirmed real-user Canadian questions, zero independently adjudicated primary references, zero primary multi-turn cases, and zero executable primary geometry payloads. It measures written answers, not diagnosis under observation, economics, compliance, implementation, or crop outcomes.

The AgroQA lane adds real farmer-origin questions but is geographically mismatched, uses unverified published references, and relies on token overlap. It is useful as a weak transfer stress test, not a generalization study.

**Verdict:** low external validity.

### 6.6 Fairness, honesty, and generality

| Property | Judgment | Reason |
|---|---|---|
| Within-model arm fairness | Good | Paired cases, frozen inputs, identity controls, and blinded semantic review |
| Cross-model fairness | Limited | Different backends/configurations and same-model Luna judging prevent clean ranking |
| Population fairness | Poor | Balanced synthetic design is not representative sampling |
| Transparency/honesty | Strong | Explicit limits, separate lanes, no composite, negative calculator result, no automated promotion |
| Current reproducibility | Limited | Canonical databases and exact judgments are absent |
| Generality | Low | Broad Canadian geography, narrow evidence-boundary construct |
| Evidence of deliberate tricks | None found | No hidden answer access, held-out separation, and negative findings are retained |

The fairest one-sentence description is:

> RC1 is an honest and informative governed-system regression study, but it is not yet a fair or general benchmark of agronomic-agent competence.

## 7. What “agronomic agent ability” is actually measured

| Capability | RC1 evidence | Assessment |
|---|---|---|
| Standalone agronomic language-model behavior | Raw arm | Measured on synthetic written cases, with judge limits |
| Instruction/kernel effect | Kernel arm | Measured |
| Structured field-context use | Field-context arm | Measured for a small set of text fields |
| Evidence-boundary and regional-source handling | Primary/regression lanes | Relatively well measured |
| Governed final-answer behavior | Full text-agent arm | Measured as a bundled pipeline |
| Verifier/fallback dependence | Orchestration summary | Measured at action-count level; row-level traces absent publicly |
| Numeric agronomic arithmetic | 16 deterministic cases | Measured; clear negative result for the governed path |
| Tool selection, argument extraction, execution, and result use | Not exercised end to end | Not measured |
| Incremental value of the knowledge graph | No graph-only arm | Not measured |
| Live labels/weather/public adapters | Traced but not executed | Not measured |
| Geometry/map service execution | No primary geometry payloads | Not measured |
| Image/sensor interpretation | No corresponding lane | Not measured |
| Multi-turn clarification and diagnosis | No primary multi-turn cases | Not measured |
| Longitudinal field-memory use | Interface probes only | Not established as general ability |
| Real grower/adviser utility | No confirmed Canadian real-user set | Not measured |
| Economic or crop outcomes | No prospective field study | Not measured |
| Current-checkout behavior | RC1 predates the inspected checkout | Not measured |

The benchmark therefore measures **governed written-response behavior within a text-only synthetic Canadian development harness**, not the complete capability of an agronomic agent.

## 8. Current internal architecture and extensibility

### 8.1 Implemented request path

The live code can be summarized as:

`question frame and route → optional public-adapter preflight → retrieval and graph hints → evidence intervention → model generation → verifier/safety normalization → rendering and trace persistence`

This has good conceptual stages, but several are implemented through large concrete modules and parallel registries rather than stable extension contracts.

### 8.2 Graphs: useful seam, incomplete contract

**Implemented:** `retrieval.graph_paths` accepts multiple JSON graph files, and `KnowledgeGraph.from_paths()` merges their nodes and edges. Adding a graph can currently be done with data, configuration, and focused tests.

**Problems:**

- missing configured graph files are silently skipped;
- later duplicate node IDs silently replace earlier nodes;
- dangling edges are ignored;
- namespaces are inferred heuristically;
- graph identity is not retained in `GraphHit`;
- no required graph ID, schema version, checksum, source, license, authority role, priority, or collision policy exists; and
- graph relations are mainly hints for vocabulary/retrieval, not a separately validated decision-evidence channel.

**Assessment:** moderately extensible for project maintainers, not yet safe for third-party graph composition.

### 8.3 Tools: fragmented extension surface

“Tool” currently covers several different concepts:

- safety/guard annotations;
- typed deterministic calculators;
- live network adapters;
- offline snapshots;
- metadata/source cards; and
- debug/retrieval helpers.

Registration and dispatch are split across `skill_registry.py`, `tools/registry.py`, `agno_runtime/tool_adapters.py`, `server/services/tool_service.py`, chat-specific trigger code, `tool_cli.py`, readiness policies, and tests. No production caller was found for `load_agno_tool_adapters()`; registering an Agno adapter therefore does not make the capability usable in chat.

Adding a tool can require synchronized changes to implementation, governance metadata, aliases, offline policy, HTTP dispatch, chat triggers, argument extraction, CLI dispatch, trace behavior, and tests. Runtime `tools:` booleans appear documentary rather than an authoritative activation registry.

**Assessment:** endpoint implementations exist, but end-to-end tool extensibility is low.

### 8.4 Evidence does not yet unify all capability outputs

The typed evidence contracts are a strong foundation. The canonical packet is still primarily built from retrieved documents. Tool results, graph assertions, public-adapter observations, and field measurements do not all enter through one shared evidence-contributor interface with one stable result identity.

This creates a dangerous asymmetry: generation may see a public-adapter result while verification sees only retrieved-document and field-history evidence. A valid tool-derived statement can therefore look unsupported to the verifier. Claim-level attestation is explicitly not implemented; the current path identifies itself as a legacy text-verifier adapter.

### 8.5 Router and verifier coupling

`QueryRoute` and decision contracts are useful output structures, but `classify_query`, `refine_query_route`, and the verifier are large, global rule collections. Crop-, product-, jurisdiction-, evidence-, and universal-safety rules are interleaved. This increases the chance that a new graph, tool, or benign intent unexpectedly inherits an unrelated guard.

There are no common protocols for tool executors, graph providers, retriever backends, router rule packs, evidence contributors, or answer validators. `AgentResources` directly owns the concrete lexical retriever and knowledge graph.

### 8.6 Current answer policy

The current checkout is more direct than the RC1 prompt: it tells the agent to answer the actual question, permit bounded explanation when decisive evidence is missing, and use only missing evidence that would materially change the call. That is directionally correct.

However, deterministic evidence-hold templates remain capable of replacing the answer with a generic consultation/referral response. Without stage-level metrics and a current rerun, it is unknown whether the new prompt has reduced verifier false positives or merely changed drafting style.

## 9. Enclosed internal upgrade plan

The plan below deliberately focuses on internal contracts and testability. It does not require a new model, external autonomous actions, or a broad product rewrite.

### Phase 0 — Restore evaluation observability and establish the current baseline

**Goal:** make every future benchmark independently reanalyzable and separate RC1 history from current-checkout behavior.

Internal features:

1. Define a content-addressed run bundle containing the canonical SQLite database, exact model messages, answers, answer hashes, context/evidence packets, route/tool/verifier traces, judge prompts/outputs, per-dimension judgments, and batch receipts.
2. Separate the bundle into a controlled private artifact and a public-safe derivative. Public data should include output hashes, all dimension values, confidence, question validity, normalized errors, answer origin, intervention action, fallback/template version, and implementation identity.
3. Add an artifact inventory and retention check to the completion gate. A “complete” receipt must fail if the canonical database is absent from its declared retention location.
4. Freeze and run an explicit current implementation commit before behavior changes so later improvements have a true baseline.
5. Record model and judge stochastic settings and repeat a sample to estimate generation and judge stability.

Acceptance gates:

- the bundle can regenerate all public tables from an empty analysis directory;
- every public row links to a private response/judgment hash;
- per-dimension totals recompute exactly;
- a missing canonical database fails completion; and
- the new implementation baseline is explicitly distinguished from RC1.

### Phase 1 — Create one canonical capability registry

**Goal:** make capabilities declarative and eliminate parallel registration drift.

Internal features:

- `ToolSpec`: stable ID/version, tool kind, typed input/output schemas, executor, risk class, authority role, network/offline/cache/freshness policy, trigger/planner metadata, renderer, verifier adapter, trace fields, and test fixtures.
- `GraphSpec`: stable ID/version, path/provider, namespaces, schema, source, license, checksum, authority role, merge priority, and collision policy.
- protocols for `ToolExecutor`, `GraphProvider`, `RetrieverBackend`, `RouterRule`, `EvidenceContributor`, and `AnswerValidator`.
- generated CLI, HTTP dispatch, readiness, trace, adapter, and documentation views from the registry.
- parity checks for duplicate aliases, unknown required tools, orphan implementations, contradictory availability, and documentation drift.

Acceptance gates:

- a new local tool requires one implementation, one spec, and tests—no chat-service, tool-service, or CLI edits;
- an unknown route-required tool fails startup/preflight;
- all configured capabilities declare implemented/tested/benchmark-exercised status; and
- the frontend and documentation render status from the same registry.

### Phase 2 — Unify planning, execution, and evidence

**Goal:** preserve one capability result from invocation through final answer.

Internal features:

1. Replace chat-specific trigger ladders with a planner consuming `QuestionFrame`, `DecisionContract`, field context, and the capability registry.
2. Introduce canonical `ToolInvocation` and `ToolResult` records with stable identity, input/output schema version, source/authority, freshness, cache/network status, limitations, and hash.
3. Feed the same `ToolResult` into generation context, verifier evidence, the evidence packet, trace, and persistence.
4. Treat field measurements, graph assertions, retrieved documents, and public-adapter observations as typed `EvidenceContributor` outputs while preserving their different authority.
5. Use the calculator as the first vertical slice: detect supported calculation intent, validate supplied quantities, execute deterministically, and render a direct value with formula/assumptions.

Acceptance gates:

- one result ID is visible in prompt assembly, verifier input, evidence packet, trace, and database;
- all 16 calculation questions invoke the calculator when fully specified;
- a missing calculator input produces one minimal clarification rather than a generic refusal;
- natural-language tests cover selection, extraction, execution, answer use, and invalid-input handling; and
- verifier tests prove that valid tool-derived claims are not rejected as unsupported.

### Phase 3 — Govern graph composition

**Goal:** make “add a new graph” a deterministic, provenance-preserving operation.

Internal features:

- JSON Schema and manifest for graph ID/version, namespaces, source, license, checksum, relation vocabulary, authority role, merge priority, and collision policy;
- preflight validation for missing files, duplicate node IDs, dangling edges, malformed relations, namespace conflicts, and absent provenance;
- graph origin and relation path in every `GraphHit`;
- explicit separation of ontology/vocabulary hints, regional context, and decision evidence;
- contract tests that run against every graph provider; and
- generated graph catalog for developers and the public site.

Acceptance gates:

- a new graph requires only data, manifest, configuration, and tests;
- missing paths and undeclared collisions fail deterministically;
- merge order cannot silently change meaning;
- each surfaced graph claim retains graph/source identity; and
- graph-only ablations can measure incremental contribution.

### Phase 4 — Make intervention risk- and capability-calibrated

**Goal:** preserve evidence discipline without suppressing useful answers.

Internal features:

1. Split router and verifier logic into versioned `DomainRulePack`s with matcher, intent, risk, required capabilities, namespaces, evidence authority, validator policies, and regression cases.
2. Separate universal safety invariants from crop-, product-, jurisdiction-, and task-specific rules.
3. Introduce an explicit `AnswerabilityState`, for example: `answer_directly`, `answer_with_bounded_uncertainty`, `ask_one_discriminating_question`, `require_authority`, or `refuse_unsafe_action`.
4. Block only the unsupported claim. Missing a soil test may block a fertilizer rate but should not block a direct explanation, differential, sampling design, or low-regret next step.
5. Preserve a capable draft by default. Rewrite or replace only when a named, evidence-linked defect exceeds a risk-dependent threshold.
6. Store and score the draft, verifier decision, rewrite/fallback, and final answer separately.
7. Add property tests showing that benign conceptual and fully specified calculation questions do not inherit irrelevant field-data or regulated-action guards.

Acceptance gates:

- verifier false-positive rate is measured on matched benign cases;
- each replacement cites the exact failed claim and evidence/rule;
- risk level changes intervention threshold in a documented, testable way;
- direct-answer and unnecessary-abstention metrics improve without regression on high-consequence safety cases; and
- model-specific fallback policies are selected from measured capability, not model name alone.

### Phase 5 — Build Benchmark v2 around the full agent loop

**Goal:** measure useful agronomic assistance and governed restraint as distinct constructs.

Case design:

Create matched cases across `risk × evidence completeness`:

1. benign factual or explanatory question;
2. fully specified low-risk calculation;
3. fully specified action-planning question;
4. one critical input missing, where one discriminating question is optimal; and
5. high-consequence action requiring label/authority or abstention.

Every caution case should have an answerable counterpart. Keep synthetic boundary regressions, independently authored/adjudicated cases, and consented real-user observational questions in separate strata.

New measurements:

- direct answer present;
- decision utility;
- unnecessary abstention/referral;
- clarification burden and whether the question is minimally discriminating;
- evidence correctness and source applicability;
- tool-selection precision/recall;
- argument extraction and execution correctness;
- verifier false-positive/false-negative rate;
- draft-to-final utility delta;
- answer origin and fallback dependence;
- calibration by risk; and
- latency/cost conditional on a correct useful answer.

Causal arms:

- raw model;
- kernel;
- field context;
- retrieval without intervention;
- tools only where applicable;
- verifier only;
- full system with fallback disabled;
- full system with risk-conditioned intervention; and
- final production policy.

Reliability and validity upgrades:

- independently authored and adjudicated questions from multiple agronomists;
- retain disagreement and report inter-rater statistics;
- cross-model and human judging, with randomized answer order;
- repeated candidate/judge samples on a preregistered subset;
- preregister rubric weights, primary endpoints, strata, exclusions, and stopping rules;
- actual multi-turn, geometry, cached/live service, field-history, and image cases; and
- a prospective usability/field study before any outcome or professional-reliability claim.

Acceptance gates:

- no single composite hides safety, utility, tools, retrieval, and calculation behavior;
- the primary endpoint is defined before generation;
- the full system demonstrates the complete natural-language tool chain;
- human agreement and judge calibration are reported; and
- claims are limited to the tested population, implementation commit, and interfaces.

### Phase 6 — Documentation architecture and GitHub Pages

**Goal:** make the system understandable without turning the root README into a manual or duplicating claims across code and prose.

#### Root README

Reduce the current 198-line README to:

1. what the project is and is not;
2. a five-to-ten-minute native setup;
3. explicit model provisioning;
4. one launch command;
5. UI URL and `/api/health` check;
6. stop instructions;
7. need-to-knows: offline/online boundary, hardware/model footprint, safety/data boundary, benchmark status; and
8. links to the site and subsystem documentation.

Move corpus inventories, spatial-pack operation, calculator reference, benchmark interpretation, repository map detail, and container operation into focused pages.

#### Folder READMEs

Priority 0:

- `src/agronomy_agent/README.md` — package map, canonical request flow, stable contracts, ownership, and test map;
- `src/agronomy_agent/server/README.md` — application composition, service boundaries, endpoint domains, auth/network/storage modes, and route-extension rules;
- `src/agronomy_agent/agno_runtime/README.md` — retrieval, graph loading, model adapters, trace adapters, rollback, and “add a graph” procedure;
- `src/agronomy_agent/tools/README.md` — capability kinds, registration, typed schemas, offline behavior, evidence receipts, and “add a tool” procedure;
- `frontend/README.md` — component/API map, map and field state, offline behavior, accessibility, and tests; and
- `configs/README.md` — active versus historical/candidate configs, schemas, versioning, authority, and selection.

Priority 1:

- `data/README.md` and `data/manifests/README.md`;
- `scripts/README.md` grouped by user, operator, ingestion, benchmark, packaging, and maintenance workflows;
- `tests/README.md` with contract-to-test mapping and full-versus-focused claim boundaries; and
- a shorter `container/README.md` plus a restored or replacement container runbook.

Use one template: purpose; entry points; inputs/outputs; invariants; extension procedure; configuration; validation commands; failure modes; and stability/status.

#### GitHub Pages information architecture

Use `docs/public/` as a MkDocs source tree:

- Home: purpose, non-goals, implementation status, system diagram;
- System: request lifecycle, capability matrix, field context, model pipeline, validation, traces;
- Knowledge and evidence: source admission, retrieval, graphs, geospatial priors, authority boundaries;
- Tools and adapters: calculator, public adapters, offline behavior, adding a tool;
- Evaluation: benchmark construct, four conditions, metrics, RC1 findings, negative results, limits;
- Developer guide: code map, adding a graph/tool/source/service, configuration, testing;
- Operations: native setup, model provisioning, offline/field-LAN, containers, troubleshooting; and
- Governance: privacy/egress, licensing, source admission, contribution policy, changelog.

Each capability page should separately label:

- implemented behavior;
- optional/install-dependent behavior;
- behavior exercised by tests;
- behavior exercised by a benchmark; and
- known limits or unverified claims.

#### Pages implementation and publication safety

Add:

- `mkdocs.yml` with `docs/public` as `docs_dir`;
- pinned documentation dependencies;
- `docs/public/index.md` and navigation;
- `.github/workflows/docs.yml`;
- strict internal-link and capability-registry checks; and
- publication-scope validation.

Build on pull requests without deployment. Deploy only from the protected default branch through the `github-pages` environment with least privilege and pinned actions. Upload only the rendered site. Continue excluding `outputs/`, local traces, private field data, model caches, and raw benchmark answers.

The current public-release manifest already includes `docs/public` and forbids `outputs/`, but it must explicitly include the workflow, site configuration, dependency file, new READMEs, and documentation checker. A current scan found 64 distinct references to absent `docs/*.md` paths; many are generated or internal evidence targets, so classify them before fixing or suppressing them. The user-visible `container/README.md` link to absent `docs/edge_container_runbook.md` should be fixed first.

Pages acceptance gates:

- `mkdocs build --strict` succeeds;
- internal links and capability status agree with the registry;
- no private/ignored artifact enters the site bundle;
- setup commands are exercised from a clean environment;
- the health check and stop instructions are verified; and
- a rendered-site review approves claims and layout before Pages is enabled.

## 10. Recommended implementation sequence

| Order | Deliverable | Why first | Exit evidence |
|---:|---|---|---|
| 1 | Artifact retention contract and current-implementation baseline | Later comparisons are otherwise not auditable | Rebuildable run bundle and baseline receipt |
| 2 | Canonical capability registry | Removes registration drift before adding features | Registry parity tests |
| 3 | Calculator vertical slice through planner/evidence/verifier | Small, deterministic proof of end-to-end extensibility | 16/16 invocation and deterministic scoring gate |
| 4 | Typed evidence contribution for every capability | Prevents generation/verifier disagreement | Shared result IDs across all stages |
| 5 | Governed graph manifests and validation | Makes new graphs safe and attributable | Collision/provenance contract tests |
| 6 | Domain rule packs and risk-conditioned intervention | Directly addresses safe-but-vague behavior | Benign false-positive and high-risk safety gates |
| 7 | Benchmark v2 | Measures the upgraded constructs honestly | Preregistered, independently reviewed report |
| 8 | README/folder documentation and capability registry pages | Documents stable contracts rather than transient code | Docs tests and reviewed READMEs |
| 9 | GitHub Pages deployment | Publishes only after claims and scope are stable | Strict build and publication-scope receipt |

## 11. Release and research gates

Do not claim “general agronomic-agent ability” until all of the following exist:

- independently adjudicated agronomy cases with reported disagreement;
- a representative or explicitly bounded real-user observational lane;
- matched benign and high-risk cases;
- full natural-language tool and geometry execution;
- multi-turn clarification and field-history tests;
- stage-level draft/intervention/final scoring;
- judge calibration and repeatability evidence;
- current-commit benchmark artifacts retained in full; and
- prospective evidence for usefulness beyond written benchmark answers.

Claims that RC1 can support now:

- the governed text pipeline has strongly model-dependent effects;
- it can rescue a weak generator through intervention/fallback;
- it improved Gemma 4 on average in the frozen primary suite;
- it harmed Luna on average and harmed all candidates on the implemented calculation path;
- the benchmark and repository expose important evidence and authority boundaries; and
- the architecture needs capability- and risk-conditioned intervention plus a unified tool/evidence contract.

## 12. Final assessment

The project is strongest when it treats provenance, uncertainty, jurisdiction, and missing evidence as first-class data. Those are real differentiators. The mistake would be to equate more intervention with more agronomic ability, or to let a safety-boundary suite stand in for the full range of agronomic assistance.

The upgrade should preserve the evidence discipline while changing the unit of control: govern **claims and actions according to their consequence**, not entire answers according to the presence of any missing field evidence. A benign calculation should be calculated. A conceptual question should be answered. A field-specific rate without decisive inputs should be bounded. A regulated action should require current authority. The planner, tool registry, evidence packet, verifier, benchmark, and documentation should all express that same distinction.

That would turn the current system from a careful but sometimes suppressive harness into an extensible agronomic agent whose usefulness and restraint can both be measured honestly.
