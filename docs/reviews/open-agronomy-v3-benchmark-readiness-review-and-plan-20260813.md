# Open Agronomy Agent v3 benchmark readiness review and release-candidate plan

**Date:** 2026-08-13
**Branch reviewed:** `codex/test-suite-qaqc`
**Reference commit:** `47f06135389b02dcf6a6f7908550d9fb586329cc`
**Status:** review complete; v3 design proposed; benchmark release candidate not yet ready
**Decision:** do not start the next major model run until the release-candidate gates in this document pass

## Executive assessment

The branch is substantially stronger than the repository at the start of the upgrade. It now has typed capability and evidence contracts, governed graph composition, a deterministic calculator path, consequence-calibrated answerability, stage-aware verification, privacy-tested retention, generated capability documentation, and a fail-closed benchmark compatibility handshake. The complete Python suite and frontend suite pass in the current worktree.

The branch is **not yet ready for a major v3 benchmark run**. The principal blocker is not the number of questions. It is that the checked-in v2 executor is synthetic contract QA, while the cockpit and the legacy evaluator still use distinct orchestration paths. A benchmark adapter cannot yet demonstrate that it executed the same router, context, retrieval, tool, answerability, verifier, output-policy, and fallback behavior as the product. The configured MLX `seed` is also not consumed or explicitly receipted, so the current runner cannot honestly call repeated executions a multi-seed experiment.

V3 should therefore be a release protocol with four separate layers:

1. deterministic instrument and harness conformance;
2. an exposed public development suite for tuning and variance pilots;
3. controlled harness-capability ablations on eligible development scenarios; and
4. a sequestered, independently authored release holdout for model and full-system comparison.

The evaluation target should be stated narrowly as **governed agronomic assistance under the frozen evidence, tool, policy, and runtime environment**. V3 can compare models, measure component effects, test selective helpfulness, and expose orchestration failures. It cannot by itself establish agronomist equivalence, field validity, legal compliance, or population-wide agronomic ability.

## Review scope and evidence

This review used:

- the current worktree and Git state;
- the [original benchmark and system review](open-agronomy-benchmark-system-review-20260813.md);
- the [upgrade implementation record](open-agronomy-upgrade-implementation-20260813.md);
- the v2 suite, interface, harness contract, preregistration, exposure receipts, runner, metrics, and audit;
- current capability, graph, evidence, planner, answerability, verifier, server, retention, export, and documentation code;
- the complete backend and frontend test suites;
- three deterministic v2 harness replays;
- a small local Gemma 4 repeated-trial diagnostic on exposed development cases; and
- primary papers and official evaluation guidance listed under [Research basis](#research-basis).

Observations, interpretations, and proposed decisions are kept separate. The local pilot was diagnostic and used exposed cases. It is not a v3 outcome and is not evidence of general agronomic quality.

## Current branch state

| Area | Current observation | Readiness interpretation |
|---|---|---|
| Git state | The branch and `main` both point to `47f0613`. The upgrade exists as 60 modified tracked files plus 127 untracked files. The tracked diff is 5,079 insertions and 981 deletions. | P1 release blocker. A clean checkout does not contain the reviewed system. |
| Backend | `677 passed`, with four existing Starlette/httpx deprecation warnings. | Strong implementation regression evidence for this worktree, not clean-checkout evidence yet. |
| Frontend | 202 tests across 31 files, TypeScript checking, and production build pass. | Healthy current UI state. |
| V2 design audit | 93 checks pass; all 19 manifested artifacts match byte and SHA-256 receipts; `claim_eligible` remains false. | Strong frozen-contract integrity. |
| V2 execution | Only a deterministic expectation-derived executor is checked in. It performs no model inference, retrieval, or judging. | Tests the harness contract, not the agent. |
| Capability registry | 57 declared capabilities; 57 marked implemented/tested; 11 marked benchmark-exercised. The calculator is not benchmark-exercised. | Registry and schema validation are useful, but status claims need evidence-derived reconciliation. |
| Product parity | The cockpit uses `server/services/chat_service.py::run_turn`; legacy evals use `agent.generate_answer`. Both contain answer-affecting orchestration. | P1 benchmark-validity blocker until one core execution path is shared. |
| Sampling control | Model profiles contain `seed: 42`, but eval construction does not consume it, `MLXGenerator` has no seed parameter, and run identity has no explicit seed. | P1 repeatability and statistical-design blocker. |
| Retrieval attribution | V2 combines document and graph retrieval as one component. | Cannot measure graph incremental value or document-graph interaction. |
| Scientific payload | V2 is exposed, project-authored, exact-case tuned, and not independently adjudicated. | Correctly usable only as a development regression suite. |
| Documentation | The source documentation audit passes across 20 public Markdown files. | Good source consistency; a clean CI rendered-site build remains an RC gate. |

### What the branch has introduced successfully

The branch has implemented meaningful foundations:

- a canonical capability registry with schema-validated execution and API/frontend status parity;
- stable tool plan, invocation, result, evidence, graph-hit, authority, and answer-stage identities;
- deterministic calculator execution and minimal missing-input clarification;
- checksum-bound graph manifests, governed multi-graph composition, provenance, relation paths, and collision failure;
- answerability states that distinguish benign explanation, bounded assistance, one discriminating question, current authority, and unsafe-action refusal;
- structured authority receipts bound to question, field context, product, crop, jurisdiction, target, site/use, method, registration, label identity, and currency;
- adversarial export redaction and content-addressed benchmark retention;
- a v2 semantic profile and compatibility handshake that fail closed on unknown stages, constructs, or unreceipted components; and
- a generated documentation site, subsystem READMEs, a public-repository manifest, and a protected Pages workflow.

These are implementation and conformance achievements. They should not be collapsed into a claim that all 57 capabilities are natural-language reachable, that the graph improves answers, or that the agent is scientifically validated.

## The present benchmark boundary

### What v2 now does well

V2 is valuable as an exposed regression and harness-contract corpus. It provides:

- 30 matched cases across six topic groups and five response strata;
- nine declared component configurations;
- separate metrics for directness, unnecessary abstention, clarification, tool selection and execution, numeric accuracy, authority behavior, verifier behavior, stage utility, origin, and fallback;
- complete model, executor, system, semantic-profile, run, sample, and observation identities;
- component-specific receipt state machines and artifact linkage;
- `comparable`, `migration_required`, and `new_benchmark_required` compatibility outcomes; and
- adversarial tests that reject no-op components, contradictory answerability behavior, invalid tool plans, stale tool/verifier IDs, forged construct profiles, stale system fingerprints, duplicate pairs, and claim-class relabeling.

Its append-only exposure receipt correctly records that exact questions informed implementation fixes. That honesty is a strength.

### What v2 cannot establish

V2 does not currently establish:

- any model-backed v2 performance;
- product-path execution parity;
- graph-only contribution;
- repeatability across applied random seeds;
- independent agronomic content validity;
- generality beyond its exposed wording and topic set;
- calibrated human or judge scoring;
- real-user, multi-turn, image, executable-geometry, or live-adapter performance; or
- post-upgrade improvement relative to a retained pre-change baseline.

Two v2 preregistered multimetric estimands are intentionally not computable in the synthetic dry path. Synthetic completion of 270 cells must not be interpreted as a successful system outcome.

## Bounded mini-pilots

### Pilot A — deterministic harness repeatability

The v2 deterministic contract executor was run three times. Each trial completed all 270 observations: 30 exposed cases by nine arms. All runs remained `claim_eligible: false` and `synthetic_contract_qa_not_system_performance`.

With the same explicit run identity, the following artifacts were byte-identical across the three isolated output directories:

| Artifact | SHA-256 |
|---|---|
| observations | `e93c639c2a88e5cba35068ec721da6061acd16056be413505d05fa410a888a5e` |
| measurements | `bf88178b2efa18f40e29bc9c71638990d03d50f5df1a8573135f35c1c9d3fe58` |
| summary | `df41656e99bff2fe46224b2f43d91ca4087f780f6493f6b3172de94271b8352e` |
| estimands | `fbb570d5944ed12dbb768a3abf311b7d40e57a9b95c228cfc55516d34224abb9` |

This verifies deterministic serialization and harness topology for the synthetic executor. It says nothing about model variability or agronomic performance.

### Pilot B — local Gemma 4 repeated trials

The local pilot used only six already-exposed `open_agronomy_canadian_performance_v1` cases. It ran three fresh-process trials of `raw_model` and three of `agronomic_rag`, producing 36 answers in total.

Frozen runtime identity:

- model: `mlx-community/gemma-4-e2b-it-4bit`;
- revision: `238767527555cb75a05732a84dff5d6ba0dd6809`;
- temperature/top-p/top-k: `0.0 / 0.9 / 0`;
- maximum generation: 180 tokens;
- prompt cache: disabled;
- model-config SHA-256: `48647c02fc9a06ffba40ca7037b8758b33faf8e42b2e18220cad516df0826896`;
- RAG-config SHA-256: `6b13caa1fd56c7b59afd05df5a8d4ea7f6b3985c47f9079aa88c79a72b7f650a`; and
- suite SHA-256: `5c3ce59195ac603d2dd8ec5f36f3672b3ee0c20227cdb4fd301dfe3848a83c63`.

All raw answers were byte-identical across the three trials, as were all governed answers. Governed retrieval IDs, graph nodes, tool plans/results, prompt messages, context admission, and verifier traces were also identical. Raw answers averaged 3.545 seconds; governed answers averaged 2.424 seconds overall. The governed average is not a fair model-speed comparison because six governed observations used deterministic tool or hold paths; model-generated governed observations averaged 3.612 seconds, while deterministic paths averaged 0.050 seconds.

These were **repeated trials, not multi-seed trials**. Code inspection confirmed that the YAML seed is never applied to the MLX RNG. Installed `mlx_lm` supports explicit seeding, so this is an implementable harness gap rather than a backend impossibility.

### Manual diagnostic observations

No aggregate score was computed from this tiny exposed subset. Manual review found:

- a P1 wrong-jurisdiction defect: an Alberta clubroot response instructs the user to follow Saskatchewan clubroot guidance because `answer_verifier.py` contains a hard-coded province;
- a regulated lentil/herbicide hold that is safe but unnecessarily generic and does not use the route's known weed identity/stage, crop stage, and history requirements;
- an SLC yield interpretation that omits the supplied `2,780 kg/ha`, SLC identity, and useful provenance detail;
- a precise deterministic seed-rate calculation of `122.807 kg/ha` with a bound tool receipt; and
- verifier intervention or fallback on three of the four governed model-generated answers.

The first item is a release blocker. The other observations support the user's concern: safety can be preserved while directness and useful partial assistance degrade. V3 must measure that trade-off explicitly rather than rewarding caution without regard to coverage or utility.

### Pilot reproduction receipt

The pilot remained outside the repository at `/tmp/oaa_v3_pilot` and used these exposed IDs:

- `oacp1::objective_agronomic_calculation::ca_calc_seed_rate_01`;
- `oacp1::official_source_answer_boundary::crop_health_answer_stress_definition`;
- `oacp1::canadian_decision_quality::ca_v2_canada_nutrition_03`;
- `oacp1::canadian_decision_quality::ca_v2_canada_weeds_10`;
- `oacp1::canadian_decision_quality::ca_v2_alberta_diseases_01`; and
- `oacp1::official_source_answer_boundary::v12_slc_yield_field_truth`.

The exact raw command, with `{N}` replaced by `1`, `2`, and `3`, was:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python scripts/run_eval.py \
  --mode raw_model \
  --suite data/eval/open_agronomy_canadian_performance_v1.jsonl \
  --output-dir /tmp/oaa_v3_pilot/raw_rep{N} \
  --model-config configs/model_gemma4_e2b_interface_v2.yaml \
  --eval-ids 'oacp1::objective_agronomic_calculation::ca_calc_seed_rate_01,oacp1::official_source_answer_boundary::crop_health_answer_stress_definition,oacp1::canadian_decision_quality::ca_v2_canada_nutrition_03,oacp1::canadian_decision_quality::ca_v2_canada_weeds_10,oacp1::canadian_decision_quality::ca_v2_alberta_diseases_01,oacp1::official_source_answer_boundary::v12_slc_yield_field_truth' \
  --max-tokens 180 \
  --capture-context-packets \
  --rubric mixed_capability \
  --answer-profile benchmark
```

The governed command was:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 AGRONOMY_AGENT_PRIVATE_KNOWLEDGE=auto \
  .venv/bin/python scripts/run_eval.py \
  --mode agronomic_rag \
  --suite data/eval/open_agronomy_canadian_performance_v1.jsonl \
  --output-dir /tmp/oaa_v3_pilot/governed_rep{N} \
  --model-config configs/model_gemma4_e2b_interface_v2.yaml \
  --rag-config configs/rag_governed_runtime_v1.yaml \
  --eval-ids 'oacp1::objective_agronomic_calculation::ca_calc_seed_rate_01,oacp1::official_source_answer_boundary::crop_health_answer_stress_definition,oacp1::canadian_decision_quality::ca_v2_canada_nutrition_03,oacp1::canadian_decision_quality::ca_v2_canada_weeds_10,oacp1::canadian_decision_quality::ca_v2_alberta_diseases_01,oacp1::official_source_answer_boundary::v12_slc_yield_field_truth' \
  --max-tokens 180 \
  --use-eval-field-context \
  --capture-context-packets \
  --rubric mixed_capability \
  --answer-profile benchmark
```

The v2 topology replay used:

```bash
.venv/bin/python scripts/run_open_agronomy_benchmark_v2.py \
  --output-dir /tmp/oaa_v3_pilot/v2_contract_trial{N} \
  --run-id oab2_v3_readiness_probe
```

The commands are recorded to make the observation reproducible, not to promote this subset into a release benchmark.

## What v3 should look like

### Four permanent evaluation layers

| Layer | Purpose | Data status | Permitted use |
|---|---|---|---|
| Instrument conformance | Prove loaders, stages, tools, graphs, scorers, receipts, redaction, retention, and failure handling work. | Public deterministic fixtures and mutations. | Every PR; harness claims only. |
| Development regression | Tune routing, prompts, policies, metrics, and judges; run repeat/seed pilots. | Public and explicitly exposed. | Engineering diagnosis; never release-performance claims. |
| Harness capability experiment | Estimate component effects with a fixed model and controlled eligible-case ablations. | Exposed or synthetic scenarios with frozen expectations. | Causal engineering evidence within the frozen harness. |
| Sequestered release holdout | Compare models and complete deployed systems after freeze. | Independently authored, privately held, committed by hashes, access logged. | Exact-set release comparison with declared limits. |

The same question must never quietly move from development into the release holdout. Exposure retires it to the development suite and requires a fresh replacement.

### Separate questions, estimands, and claims

V3 should answer six different questions without combining them into one score:

1. **Model effect:** which model performs better under the exact same frozen harness?
2. **Harness effect:** what changes when one harness component is disabled or replaced while the model is fixed?
3. **Model × harness interaction:** does the same intervention help a smaller model but hinder a stronger one?
4. **System effect:** how does one particular model-harness-asset configuration behave as deployed?
5. **Reliability:** how often does the same system produce the required result across repeated trials?
6. **Selective utility:** does caution reduce unsafe commitments without suppressing benign, answerable, or partially answerable help?

A raw-model versus full-system contrast is a system comparison, not a pure estimate of retrieval, graph, verifier, or base-model quality.

### Proposed v3 content architecture

The exact case count should be frozen only after independent authorship and a development-set precision simulation. A practical planning envelope is 12–16 scenario families with six controlled near-neighbours each, yielding 72–96 sealed text cases. This is a planning target, not a sample-size claim.

Each family should contain:

1. a benign explanation answerable without a field sample;
2. a fully specified calculation or action-support case;
3. a case missing one truly decisive input;
4. a case missing only an irrelevant input, where clarification or abstention is wrong;
5. a current-authority or high-consequence case;
6. a conflicting, wrong-jurisdiction, unavailable-capability, or provenance fault variant.

Across families, include naturalistic paraphrases, irrelevant context, concise wording, Canadian English and a professionally reviewed French subset, and deliberately similar benign-versus-regulated pairs. Explicit safety cues should not dominate the authority lane.

Recommended construct strata:

- benign scientific explanation;
- evidence-grounded interpretation;
- field-context sufficiency and clarification;
- typed calculation and unit conversion;
- tool selection and result use;
- document retrieval and claim support;
- graph retrieval, relation-path use, and contradiction handling;
- label/current-authority boundaries;
- diagnosis or action planning that truly requires observation or sampling;
- unavailable capability and fault recovery; and
- directness, specificity, useful partial assistance, and calibrated caution.

Multi-turn, executable geometry, images, live/cache behavior, and consented real-user cases should be separately reported lanes. They should enter the main release construct only after the product and evaluator execute them faithfully.

## Using the benchmark to test the harness

Final-answer quality alone cannot distinguish a weak model from a route that never exposed a tool, retrieval that returned the wrong jurisdiction, a verifier that discarded a good draft, or a renderer that removed the useful result. V3 should score the complete capability chain.

| Capability | Positive condition | Negative/control condition | Required trace evidence | Outcome measures |
|---|---|---|---|---|
| Routing | Applicable intent and paraphrases. | Benign near-neighbours and unrelated rate words. | Route ID/version, confidence/policy, required capabilities. | Selection precision/recall; unsafe miss; false guard. |
| Field context | Complete relevant context. | Partial, stale, contradictory, and irrelevant context. | Typed snapshot, field/question hashes, admitted slots. | Useful context use; irrelevant-context resistance; minimal clarification. |
| Calculator/tools | All supported operations with supplied inputs. | Missing input, malformed input, wrong unit, unrelated tool. | Plan, invocation, result IDs; schema/version; payload hash; result use. | Selection P/R, execution, numeric tolerance, clarification burden. |
| Document retrieval | Decisive governed source is available. | No result, wrong jurisdiction, stale or boundary-only source. | Source IDs, retrieval rank, authority/applicability, claim links. | Evidence recall/precision, claim support, wrong-source substitution. |
| Knowledge graph | Relation path genuinely resolves the question. | Collisions, unsupported relation, document-only/null cases. | Graph ID/version/hash, node origin, relation path. | Increment over no graph; contradiction handling; silent-merge failure. |
| Answerability | Benign, bounded, missing-input, authority, and unsafe cases. | Paired wording controls. | Rule pack, state, requirement receipt, observable action. | Coverage, false abstention, unsafe specificity, clarification quality. |
| Verifier | Draft with a known material defect. | Concise correct draft and safe useful partial answer. | Draft hash, stable rule IDs, evidence IDs, decision artifact, replacement hash. | False positive/negative; draft-to-final utility; information loss. |
| Fallback | Controlled model/verifier/tool failure. | Normal successful generation. | Failure class, fallback policy/version, answer origin. | Recovery success; unexpected fallback; provenance continuity. |
| Privacy/retention | Complete valid trace. | Canary secrets, malformed DB, stale hashes, CSV formulas, interrupted run. | Private/public inventories and verification receipt. | Leak detection, tamper rejection, recoverability. |
| Orchestration parity | Same deterministic request through cockpit and benchmark adapter. | Hidden stage, no-op component, altered renderer. | Exact stage topology and component receipts. | Receipt equivalence; contamination rejection. |

Every capability claim should distinguish availability, selection, invocation, successful result, evidence continuity, final-answer use, and fault recovery. Merely listing a capability or recording an expected tool is not benchmark exercise.

## Proposed arm design

A full Cartesian product of all components would be expensive and difficult to interpret. Use a common core plus eligible-case contrasts.

| Arm/contrast | Cases | Purpose |
|---|---|---|
| `raw_model` | All sealed cases | Model-only reference; not product behavior. |
| `kernel_only` | All sealed cases | Prompt/kernel contribution. |
| `production_full` | All sealed cases | Deployed system configuration. |
| `full_minus_field_context` | Field-context and irrelevant-context cases | Context contribution and contamination. |
| document/graph 2×2 | Retrieval-eligible cases | No retrieval, document only, graph only, both; estimates main effects and interaction. |
| `full_minus_typed_tools` | Tool-eligible cases | Planner/tool/result contribution. |
| `full_minus_risk_intervention` | Authority and benign matched controls, offline only | Safety-helpfulness trade-off. Unsafe drafts remain private. |
| `full_minus_verifier` | Cases with generated drafts | Verifier benefit and damage. |
| `full_minus_fallback` | Controlled failure scenarios | Fallback recovery and origin. |

The primary harness contrast should be enabled versus disabled by assignment. A secondary activation-aware report may show whether the component actually fired, but it is diagnostic because activation can depend on the case and prior stages. A contrast is invalid when receipts show that the changed component did not execute where applicable.

Raw, kernel, and production-full should run for every candidate model. Critical risk, verifier, and tool contrasts should also cover every candidate if model × harness interaction is an intended claim. Other expensive ablations may use a preregistered anchor model and must not be generalized to the other models.

## Repeat, seed, and process contract

Before any development pilot is called multi-seed, v3 must implement:

- `trial_id`, `sample_index`, `generation_seed`, case-order seed, and judge seed as separate typed fields;
- explicit backend seed application immediately before each serialized generation;
- a seed-application receipt containing requested seed, applied seed, backend, sampler, temperature, and implementation identity;
- fresh-process or explicitly frozen cache/model-lifetime policy per model-arm-trial block;
- matched trial keys across causal arms;
- deterministic-tool cases that do not pretend to have model-sampling variance;
- resume logic that cannot duplicate or pool a completed sample; and
- same-seed replay and different-seed variation tests at nonzero temperature.

Temperature-zero executions should still be called repeated trials unless determinism is proven for the exact backend. Best-of-n selection is prohibited unless it is the declared deployment behavior.

The first proper development pilot should use 12–20 exposed scenario families, one frozen model, production-full plus two genuinely isolated contrasts, and five trials per cell. Five is a variance-discovery pilot, not an automatically adequate release sample. The final trial count should follow a preregistered precision or power simulation using observed development variance and the desired interval width or practical-equivalence margin.

## Scoring and selective helpfulness

Deterministic scoring should be authoritative where possible:

- numeric results and units;
- schema and identity validity;
- route/tool/graph selection;
- source and question-hash binding;
- current-authority scope;
- forbidden actions;
- component activation and failure recovery; and
- retention and privacy invariants.

Semantic review is needed for usefulness, agronomic applicability, directness, evidence fidelity, and whether a clarification is genuinely discriminating. V3 should report, at minimum:

- substantive-answer coverage;
- selective risk among substantively answered cases;
- answerable-case coverage;
- false abstention on benign and complete cases;
- unsafe specificity where evidence or authority is insufficient;
- correct clarification and one-question minimality;
- useful partial-answer rate;
- tool and evidence result utilization, not invocation alone;
- verifier false-positive/false-negative and draft-to-final utility;
- answer origin and unexpected fallback;
- per-trial success and all-trials consistency; and
- latency, token, memory, timeout, parser, and infrastructure failure counts.

A short, useful explanation followed by a relevant limitation is not the same outcome as blanket refusal. Likewise, asking for one decisive sample is different from a generic checklist. These labels must be separate before scoring begins. A risk–coverage curve or preregistered utility matrix should show the cost of caution; accuracy alone can reward an agent that answers almost nothing.

No single composite “agronomic intelligence” score should be reported.

## Human review and LLM judges

Independent agronomic review remains necessary for the release holdout. Recommended role separation:

- scenario authors define the intended decision and source package;
- independent agronomist reviewers validate realism, answerability, jurisdiction, and rubric before exposure;
- blinded answer reviewers score model/system outputs without model or arm identity;
- disagreements are preserved and adjudicated by a reviewer who did not author the response; and
- the implementation team receives only development-suite findings until the release run is frozen.

For semantic LLM judges:

- freeze model, revision, prompt, rubric, parser, sampling settings, and role;
- blind candidate and arm identity;
- randomize pair order and repeat with reversed order;
- calibrate on a stratified human-reviewed development set;
- include concise-correct versus verbose-vague, useful-caution versus blanket-refusal, supported versus cosmetic-citation, and actionable-unsafe versus bounded pairs;
- report confusion matrices, disagreement, parse failure, and dimension-level agreement; and
- keep human adjudication authoritative for disputed release-critical cases.

The same candidate model must not serve as the sole judge for a claim about itself. Historical Luna judgments remain advisory development evidence.

## Statistical analysis plan

The defensible primary estimand is performance on the **exact frozen v3 set**. A broader population claim requires a defined target population and sampling frame that this repository does not currently have.

Recommended analysis:

- pair by scenario family, case, model, harness, and trial key;
- preserve model ID, revision, backend, quantization/configuration hash, and executor/system fingerprints;
- report exact counts, effect sizes, and 95% intervals by construct stratum;
- use a scenario-family clustered paired bootstrap as the transparent primary uncertainty analysis;
- consider a preregistered mixed-effects model as a sensitivity analysis for model, harness, interaction, stratum, item/family, and repeated-trial variation;
- predeclare practical equivalence or non-inferiority margins;
- limit primary endpoints and adjust or clearly label secondary multiplicity;
- never impute missing observations as zero or silently discard timeouts, parser failures, tool failures, or interrupted runs; and
- report cost-performance profiles when systems consume different resources.

Repeated trials estimate completion variability. Cases estimate item variability. They are not interchangeable, and neither establishes field validity.

## Harness evolution and comparability

The v2 compatibility work should become the base of a v3 protocol, not be discarded. Preserve three identities:

- **construct fingerprint:** cases, labels, strata, estimands, denominators, and semantic vocabularies;
- **cohort fingerprint:** the frozen evaluation release and exposure state; and
- **system fingerprint:** model, executor, code, prompt, field serializer, corpora, graph assets, tools, policies, verifier, renderer, fallback, and runtime configuration.

Compatibility decisions should remain:

- `comparable`: the construct and harness semantics match; distinct implementations remain separate system slices;
- `migration_required`: a declared, lossless, tested representation adapter preserves immutable raw observations; and
- `new_benchmark_required`: arm meaning, case construct, denominator, stage topology, authority vocabulary, verifier decision unit, or another answer-affecting semantic changes.

V3 must expand the stage inventory to include the real product path: route, public-adapter selection, typed field context, document retrieval, graph retrieval, evidence selection, planning, tool execution, pre-generation answerability, deterministic bypass, draft generation, verification, output safety/normalization, structured rendering, and fallback/origin. Unknown active stages must continue to fail closed.

## Holdout governance

The release holdout should not be committed as plaintext in this repository before execution. The repository should contain only:

- the case schema;
- strata and count commitments;
- cryptographic commitments to the private suite, rubric, and source package;
- the preregistered analysis and stopping rules;
- the access/exposure policy; and
- an append-only amendment template.

A human custodian should keep the plaintext cases, labels, and rubrics outside the development workspace and record every authorized exposure. A negative text-overlap scan is useful but cannot prove absence of contamination. Once release outputs are inspected for implementation tuning, the holdout version is retired and a successor is required.

The full run should use a clean committed source identity. Raw responses, traces, judgments, and private field context remain in the verified private retention bundle. Only the typed, privacy-audited derivative and bounded report should enter the PR.

## Development plan to benchmark release candidate

### Phase 0 — Corrective stabilization and reviewable Git state

Deliverables:

- fix the Alberta/Saskatchewan clubroot fallback and add paired jurisdiction tests;
- reconcile capability `implemented`, `tested`, `natural_language_enabled`, and `benchmark_exercised` statuses with executable evidence;
- classify the 16 MB of new curated derived data as source, receipted distributable artifact, or rebuild output;
- split the current worktree into coherent, reviewable commits without rewriting prior history;
- freeze or lock release dependencies sufficiently for a clean environment and retain an environment/SBOM receipt; and
- document the exact clean-checkout validation command set.

Acceptance gate:

- no untracked release files;
- no wrong-jurisdiction fallback in the paired suite;
- public manifest contains every intended release artifact and no generated leakage;
- a fresh checkout installs, collects, and passes backend/frontend/docs/package gates; and
- the PR diff can be reviewed phase by phase.

### Phase 1 — One product execution core and a truthful benchmark adapter

Deliverables:

- extract a typed `AgentExecutionRequest` and `AgentExecutionResult` used by both cockpit and benchmark;
- make server history, map state, public-adapter payloads, and UI rendering explicit inputs or adapters around that core;
- record every answer-affecting and trace-only stage;
- implement an `observed_system_execution_nonclaim` adapter that calls the real core rather than reconstructing it; and
- retain exact raw stage outputs plus the final response.

Acceptance gate:

- the cockpit and benchmark adapter produce equivalent component/stage receipts for the same deterministic request;
- no hidden active feature or post-verifier transformation is accepted;
- deliberately disabled or no-op components fail their arm contract; and
- a small retained product-path run completes without borrowing synthetic expectations.

### Phase 2 — Seed, repeat, isolation, and recovery contract

Deliverables:

- implement and receipt backend RNG application;
- add trial/sample/process/cache/order identities;
- enforce the frozen process-isolation policy;
- update resume, duplicate detection, pairing, and summary aggregation; and
- add adversarial same-seed, different-seed, interruption, and concurrency tests.

Acceptance gate:

- the same seed is characterized under the exact backend;
- different seeds at nonzero temperature are demonstrably applied;
- repeated trials cannot collide, disappear, or pool across systems; and
- deterministic tool results remain identical and are analyzed separately from sampled text.

### Phase 3 — Capability certification and ablation completeness

Deliverables:

- split document and graph retrieval components;
- add route, evidence selection, deterministic bypass, output policy, renderer, and public-adapter stages to the harness profile;
- exercise all 12 current calculator operations or narrow the claimed operation set;
- add positive, negative, irrelevant-context, unavailable, malformed, timeout, wrong-jurisdiction, and provenance-fault fixtures;
- bind final claims to evidence/tool results where the response makes a checkable claim; and
- add verifier and fallback mutation corpora with known draft defects and known acceptable drafts.

Acceptance gate:

- every advertised benchmark-exercised capability has an executed result and final-answer-use receipt;
- document-only, graph-only, both, and neither configurations are distinguishable;
- all deliberately broken fixtures are detected; and
- capability coverage is generated from the canonical registry and harness contract.

### Phase 4 — V3 development suite and proper multi-trial pilot

Deliverables:

- create an explicitly exposed matched development suite with naturalistic boundary cases;
- run 12–20 families, five trials, one anchor model, production-full, and two isolated contrasts;
- analyze route/output flips, activation, within-item and between-item variation, failure rate, latency, and resource use; and
- run judge-order and self-consistency probes on development outputs only.

Acceptance gate:

- every planned cell completes or has an explicit typed failure;
- component activations match eligibility;
- variance and runtime support a documented release trial count and budget; and
- no v3 holdout content has been exposed.

### Phase 5 — Independently authored and sequestered v3 release set

Deliverables:

- define the target construct and claim boundary;
- commission independent agronomic authorship and review;
- build matched near-neighbour families, a reviewed French subset, source packages, private labels, and rubrics;
- record reviewer disagreement and adjudication;
- create public hashes/counts plus a private access log; and
- freeze exposure, amendment, missing-data, stopping, and retirement policies.

Acceptance gate:

- every case is realistic, answerable under its declared evidence state, jurisdiction-checked, and independently reviewed;
- no author is the sole release judge of their own case;
- all primary estimands are executable before model outputs exist; and
- the implementation team has not inspected plaintext holdout cases.

### Phase 6 — Analysis and judge calibration freeze

Deliverables:

- freeze deterministic scorers, semantic rubric, human review forms, judge models/prompts/parsers, ordering, and appeal path;
- predeclare primary endpoints, equivalence margins, clustered uncertainty, mixed-model sensitivity, multiplicity, and failure treatment;
- calibrate automated judges against a stratified human development set; and
- create the final report template before outcomes.

Acceptance gate:

- judge bias probes and human agreement meet preregistered gates;
- order reversal and parse failures are retained;
- no composite score obscures construct trade-offs; and
- the report template separates observation, model, interpretation, and unsupported claims.

### Phase 7 — Benchmark release candidate

Deliverables:

- a clean release commit with immutable suite/protocol/model/asset/executor/scorer receipts;
- full backend, frontend, docs, public-package, privacy, retention, and recovery verification;
- a retained non-holdout production-adapter rehearsal;
- resource and storage budget confirmation;
- operator runbook, stop/recovery procedure, and authorization receipts; and
- a signed RC checklist with no open P1 items.

Acceptance gate:

- the release commit uniquely identifies code, models, quantization, prompts, corpora, graphs, tools, policies, seeds, executor, schemas, scorers, and environment;
- CI and local clean-checkout results agree;
- restart/resume rehearsal preserves identities; and
- the holdout is still sealed.

### Phase 8 — Authorized full run and PR closure

Sequence:

1. run the frozen internal v3 matrix once from the RC commit;
2. build the blinded review packet before semantic scoring identities are revealed;
3. complete deterministic scoring, blinded automated triage, and independent human review;
4. verify the private retention bundle and public-safe derivative;
5. publish per-model, per-system, per-stratum, per-trial, and component-effect results with uncertainty;
6. record all failures, deviations, and amendments; and
7. add the bounded report and public-safe receipts to the PR before merge.

No implementation repair and rerun on the same sealed v3 version is allowed. A discovered implementation defect is reported, the run is retained, and any corrected evaluative run uses a new holdout/cohort version.

## Release-blocker register

| Priority | Blocker | Closure evidence |
|---|---|---|
| P1 | Upgrade remains an uncommitted worktree. | Clean committed branch and clean-checkout verification. |
| P1 | Cockpit and evaluator do not share one product execution core. | Receipt-equivalence and production-adapter tests. |
| P1 | No real observed-system v2/v3 executor. | Retained nonclaim product-path rehearsal. |
| P1 | Configured seed is inert and absent from run identity. | Applied-seed receipts and nonzero-temperature tests. |
| P1 | Alberta clubroot fallback names Saskatchewan guidance. | Paired province regression and corrected runtime output. |
| P1 | V2 omits active answer-affecting stages. | Expanded stage profile with fail-closed unknowns. |
| P1 | No independent, sequestered v3 scientific payload. | Private suite commitments, access log, and review receipts. |
| P2 | Documents and graph are one retrieval component. | Retrieval 2×2 contract and tests. |
| P2 | Planner is calculator-specific while broad NL status is declared. | General planner integration or narrowed truthful status. |
| P2 | Verifier thresholds and semantic judges are uncalibrated. | Development calibration and frozen gates. |
| P2 | Only half of calculator operations appear in v2. | Complete operation coverage or claim reduction. |
| P2 | Strict rendered docs and public package need clean-checkout rerun. | RC build receipts. |

## Benchmark-RC checklist

Do not unseal v3 until every item is true:

- [ ] branch is committed, reviewable, and clean;
- [ ] clean environment install and full test matrix pass;
- [ ] cockpit and benchmark use one execution core;
- [ ] production executor truthfully implements every arm;
- [ ] all active stages and capability semantics are frozen;
- [ ] seed/trial/process/cache/order fields are applied and receipted;
- [ ] development multi-trial pilot determines the release trial count;
- [ ] document and graph effects are separately measurable;
- [ ] wrong-jurisdiction, false-guard, vague-hold, and verifier-damage controls pass;
- [ ] deterministic mutations prove scorer and trace integrity;
- [ ] independent agronomists review the sealed construct and rubric;
- [ ] LLM judge calibration and order-bias probes pass declared gates;
- [ ] primary estimands, margins, uncertainty, exclusions, and stopping are frozen;
- [ ] holdout hashes exist and plaintext remains sequestered;
- [ ] retained product-path rehearsal and recovery drill pass;
- [ ] private/public artifact boundaries pass adversarial privacy tests; and
- [ ] no open P1 blocker remains.

## Permitted claims after a successful v3 run

A successful v3 run could support:

- exact-set comparisons between frozen models under the same harness;
- exact-set comparisons between frozen harness configurations with the same model;
- measured model × harness interactions included in the preregistration;
- reliability across the declared trials;
- component reachability, execution, trace integrity, and fault recovery; and
- selective-helpfulness trade-offs on the frozen scenario families.

It would still not, without additional evidence, support:

- agronomist equivalence;
- legal or label compliance in deployment;
- safe autonomous field action;
- causal agronomic efficacy;
- generalization to all crops, regions, languages, farms, or users; or
- prospective real-world benefit.

## Research basis

The design recommendations draw on the following primary or authoritative sources:

- [NIST AI 800-2, *Practices for Automated Benchmark Evaluations of Language Models*](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-2.ipd.pdf): define intended construct and use, separate uncertainty sources, bind scaffolding and environment, and validate benchmark implementation. This is an initial public draft and should be cited as such.
- [NIST AI 800-3, *Expanding the AI Evaluation Toolbox with Statistical Models*](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.800-3.pdf): distinguish exact-set from population estimands, use paired comparisons and uncertainty, and model item/trial dependencies.
- [NIST AI Technology Evaluation](https://pages.nist.gov/ai-technology-evaluation/) and [TrojAI evaluation design](https://pages.nist.gov/trojai/docs/overview.html): sequestered evaluation and separation of development data from final holdouts.
- [NIST, *Practices for detecting and preventing cheating in AI agent evaluations*](https://www.nist.gov/caisi/cheating-ai-agent-evaluations/4-practices-detecting-and-preventing-evaluation-cheating): deterministic solutions, transcript/error-path review, versioning, and grader-gaming controls.
- [Yao et al., *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains*](https://openreview.net/forum?id=roNSXZpUDN): multi-trial agent consistency and state/tool-policy evaluation. Its customer-service setting is not direct agronomy evidence.
- [Deng et al., NAACL 2024](https://aclanthology.org/2024.naacl-long.482/) and [Sainz et al., EMNLP 2023](https://aclanthology.org/2023.findings-emnlp.722/): benchmark contamination can evade simple overlap checks.
- [Benchmark Inflation](https://arxiv.org/abs/2410.09247): exposed tests can differ materially from fresh matched retro-holdouts.
- [Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*](https://arxiv.org/abs/2306.05685) and [Chen et al., EMNLP 2024](https://aclanthology.org/2024.emnlp-main.474/): position, verbosity, self-enhancement, and other judge biases motivate blindness, order reversal, and human calibration.
- [El-Yaniv and Wiener, JMLR 2010](https://jmlr.org/papers/v11/el-yaniv10a.html) and [Xin et al., ACL 2021](https://aclanthology.org/2021.acl-long.84/): abstention is a risk-coverage trade-off rather than an unqualified success.
- [Dror et al., ACL 2018](https://aclanthology.org/P18-1128/): statistical tests should match the dependency structure and hypothesis; paired resampling is appropriate for many matched NLP comparisons.

These sources inform protocol design. None validates this benchmark's agronomic content. That authority remains with independent domain review and, for real-world claims, prospective evidence.

## Final recommendation

Proceed with Phase 0, not with the full benchmark. The branch has a strong contract foundation, and the mini-pilots show that deterministic paths can be stable. They also expose exactly why v3 is needed: the current seed is inert, the product and evaluation paths can diverge, safe fallbacks can become vague, and one hard-coded jurisdiction can survive broad regression success.

The best v3 is not the largest suite. It is the smallest independently reviewed, sequestered set that cleanly separates model effects, harness effects, interaction, reliability, and selective utility while the public conformance suite continuously proves that the measurement instrument itself still works.
