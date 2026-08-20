# Evaluation contract

The canonical internal benchmark is `open_agronomy_canadian_performance_v1`: 241 project-owned Canadian field questions. It is a development instrument, not a certification exam and not evidence of agronomist equivalence.

## Frozen arms

| Arm | Input and behavior |
|---|---|
| `raw_model` | User question only; no kernel, retrieval, verifier, or post-processing |
| `baseline` | Shared kernel and answer contract; no retrieval or verifier |
| `kernel_field_context` | Kernel plus the same structured crop, region, jurisdiction and management context used by the full arm |
| `agronomic_rag` | Kernel plus governed retrieval/evidence intervention and configured validation |

The primary matched contrast is raw model versus the governed system.
Intermediate arms localize changes to added instruction, field-context, or
knowledge/evidence bundles; they do not isolate individual causal effects.

## What is measured

- Canadian decision-quality cases preserve reference points, material errors, missing-evidence boundaries and field context for review.
- Sixteen arithmetic cases have structured reference values, units and numeric tolerances.
- Route, retrieval, evidence, tool and output-contract traces are checked as interface capabilities.
- During a run, the runner records questions, exact messages, context packets, responses, scores and identities in a local SQLite result database. The database is a private run artifact, not a checked-in public asset.

Automated semantic judges are advisory triage. They can help find regressions but cannot substitute for blinded, calibrated agronomist review. Lexical proxy scores are reported only for lanes where their contract is defined; there is no valid single composite “agronomy intelligence” score.

## External diagnostic

`open_agronomy_external_agroqa_v1` contains 256 held-out AgroQA items. It is external transfer evidence from a different geography and task distribution. It must not be mixed into the internal suite, used for iterative prompt tuning, or presented as Canadian validation.

Historical CROP multiple-choice imports are quarantined because audit found material answer-key problems. CCA-aligned questions are project-authored coverage probes and make no professional-exam claim.

## Construct boundary

The checked-in construct audit separates the 241 rows into 90 primary semantic
field-decision cases, 31 secondary advisory cases, and 120 regression or
interface cases. The latter must not be averaged into an agronomic answer-
quality claim. The primary lane spans nine task categories with ten cases each
and balanced province-level coverage, but it currently contains no proven
real-user questions, independent agronomist adjudication, multi-turn primary
cases, or executable field geometries. These are explicit residual validity
gaps, not zero-valued capabilities.

Regenerate the audit with:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_canadian_field_benchmark.py
```

The expected output status is `development_construct_only`. A change that
silently upgrades this status or collapses the three reporting tiers is a
release blocker.

## Reproducibility gates

The runner locks the suite hash, interface contract, arm-contract version, executable source snapshot, model profile, and RAG artifact identities. A partial run resumes only when those substantive identities match. Release validation requires all canonical comparison arms to share one implementation hash. Dirty-checkout experiments may be retained for development, but a public result must identify the exact committed source.

Each model-by-trial invocation also records `trial_id`, sample index, generation,
verification, case-order and judge seeds, process and cache policy, ordered-case
digest, run/process/cache identities, observation IDs, and matched-arm keys. MLX
generation applies the requested seed inside the serialized generation lock and
records whether the seed reached the backend. A completed trial is not silently
rerun; resume requires substantive identity equality, and duplicate trial or
pair keys fail closed. A temperature-zero trial is described as a repeated
trial unless backend determinism has actually been demonstrated.

The current runner requires a verified, content-addressed private retention
bundle before marking a new round complete. That bundle contains the canonical
database and supplied experiment files; its separately generated public-safe
CSV contains database-keyed linkage commitments and allowlisted structured
measurements but excludes prompts, answer text, retrieved context, judge
rationales, private field context, and raw private identifiers. Stored answer,
question, and context hashes are recomputed before the bundle is accepted. This
contract retains regular zero-byte evidence files, but excludes the reserved
`.eval_run.lock` process-coordination file because it is not experiment evidence.
Inputs containing symbolic links or other non-regular filesystem entries fail
closed, and a complete staged bundle is verified before atomic publication. This
retention path has focused automated tests and was exercised by all nine
completed RC3 model-by-trial runs. It has not recovered the missing RC1
artifacts.

## Completed RC3 development checkpoint — 2026-08-15

RC3 completed the declared three-candidate by three-trial by four-arm by
241-case matrix: 8,676 canonical observations in 36 isolated arm executions.
All nine trials have completion receipts and verified content-addressed
retention bundles. The frozen identity remains
`development_rerun_nonclaim`: the Canadian suite was exposed and used during
system tuning, and the run did not exercise a sealed v3 holdout, the v3
component matrix, or a representative product/service cohort. AgroQA v1 stayed
retired and was not rerun.

Only 49 of 241 cases per arm have a defined deterministic score: 16 objective
calculation cases and 33 official-source lexical-contract cases. The other 192
cases are trace-only or await independent human review. RC3 executed **zero
automated semantic judgments**, so the 90-case Canadian decision-quality lane
and 31-case advisory-transfer lane have no answer-quality result.

| Candidate | Objective raw / kernel / field / full (%) | Lexical proxy raw / kernel / field / full (%) |
|---|---:|---:|
| Gemma 3 270M | 0.00 / 0.00 / 0.00 / 87.50 | 43.33 / 36.63 / 38.94 / 48.91 |
| Gemma 4 E2B | 31.25 / 37.50 / 18.75 / 87.50 | 60.65 / 53.36 / 59.93 / 62.34 |
| Luna High | 97.92 / 89.58 / 93.75 / 87.50 | 72.11 / 75.92 / 77.10 / 68.69 |

These are separate deterministic regression measures, not a composite score or
model leaderboard. In particular, the full-system calculation result is the
frozen parser score of 14/16. A post-run audit found the typed calculator
payload within numeric tolerance on 16/16 cases; the two false negatives used
the correct generic unit `kg product/ha`, which the frozen product-specific
alias set rejected. The 16/16 audit is parser sensitivity, not a replacement
benchmark outcome.

The run is especially useful as a harness checkpoint. Per trial, the full arm
produced 163 model generations, 16 deterministic tool results, 58
evidence-sufficiency holds, and 4 missing-input clarifications. Retrieval
surfaced the expected source in 22/26 positive probes and matched 46/50 required
patterns. Expected local guards were complete on 134/154 eligible case routes,
and French was preserved on 9/12 eligible cases. These are reachability,
lineage, and output-contract observations; they do not show that retrieval,
verification, holding, or rewriting improved agronomic answers.

The public-safe [RC3 checkpoint package](development-benchmark-rc3-20260815/README.md)
contains the paper, scientific figures, answer-free measurement table,
analysis-ready summaries, claim-to-evidence map, and deterministic regeneration
script. Raw answers, prompts, retrieved context, SQLite databases, logs, model
weights, and machine-local paths remain outside the public package. The
fixed-suite sensitivity intervals use case resampling to describe sensitivity
to this exposed case set; arm contrasts are paired within case. These are not
population confidence intervals.

The completed execution contract remains byte-for-byte frozen in
`configs/final_benchmark_round_rc3.json`. Its append-only completion record in
`configs/benchmark_round_lifecycle_v1.json` has status
`completed_frozen_nonclaim`; current readiness combines the two records and
rejects the completed identity for new execution.
Its egress receipt bound the exact suite, application-message, runtime-artifact,
static-prompt, phase/arm, and payload-class contracts. Private knowledge was
disabled for every arm; deterministic tools stayed local; the declared judge
seed was inert with `judge_seed_application=not_requested`; and no judge or
tool-result payload class was authorized. A future run with changed source,
configuration, model identity, cohort, or answer-affecting topology requires a
new benchmark identity and new release receipts rather than silently extending
RC3.

## Final RC1 result — 2026-08-12

The completed run receipt reports 2,892 responses and 2,892 advisory
judgments: three candidates by four arms by 241 cases. On the 90-case primary
Canadian decision-quality lane, the frozen raw-versus-governed comparison was:

| Candidate | Raw model | Governed system | Paired change (95% interval) |
|---|---:|---:|---:|
| Gemma 3 270M 4-bit | 2.50 | 73.13 | +70.63 (+65.46 to +75.71) |
| Gemma 4 E2B 4-bit | 54.71 | 77.93 | +23.22 (+17.60 to +28.59) |
| Luna High | 89.82 | 83.38 | -6.45 (-11.52 to -1.18) |

These are automated development scores, not agronomist ratings. The negative
Luna result and intermediate-arm analysis show that system intervention must
be calibrated to generator capability rather than assumed to help every model.
The benchmark path also failed to call the typed calculator, leaving all three
governed candidates at 0/16 objective calculation cases. That failure is
preserved as an RC1 orchestration defect. RC3 later reached the typed calculator
for all 16 full-arm calculation cases per trial; its frozen parser scored 14/16,
with the separate 16/16 typed-payload audit bounded as parser sensitivity.

The one-time held-out AgroQA diagnostic used the frozen Gemma 4 full-system
finalist. Normalized reference-token F1 changed from 0.0508 raw to 0.0595 with
the governed system. Because the source questions are Ugandan and the answers
were not revalidated for Canadian practice, this is geographic transfer
evidence only and the exposed implementation must not be tuned and rerun on the
same set version.

The [technical paper and public evidence package](final-benchmark-20260812/README.md)
contain the published interpretation, task-family summaries, paired intervals,
orchestration diagnostics, frozen finalist receipt, and plotting inputs. The
current repository does **not** retain the exact answers, per-dimension Luna
judgments, or canonical SQLite databases. Checksums and counts identify those
historical artifacts if recovered but do not make the checkout independently
reanalyzable. See the repository's
[academic benchmark and system review](https://github.com/Tknecht4/open_agronomy_agent/blob/main/docs/reviews/open-agronomy-benchmark-system-review-20260813.md)
for the artifact audit and Benchmark v2 upgrade plan.

## Measurement boundary

RC1 is unusually candid development evidence, but its primary lane is a
synthetic safety/evidence-boundary suite rather than a representative sample of
agronomy work. All 90 primary cases expect the field-data guard. Live adapters,
multi-turn diagnosis, and executable field geometry were not exercised by the
reported text interface. Luna also served as candidate and semantic judge, and
question/reference/rubric design came from the project. Consequently:

- within-model paired arm comparisons on the frozen suite are informative;
- cross-model rankings and population-level estimates are not calibrated;
- the result measures governed written behavior, not general agronomic-agent
  ability or agronomist equivalence; and
- the 0/16 governed calculation result and Luna regression are important
  negative evidence about orchestration/intervention.

## Benchmark v2 status — exposed development regression

The repository contains a formerly preregistered development design for 30
project-authored matched cases: six agronomic topic groups, each represented by
a benign explanation, fully specified calculation, fully specified action
plan, one-critical-input-missing case, and high-consequence authority case. A
nine-arm interface isolates kernel, field context, retrieval, typed tools,
risk intervention, verifier, and fallback contributions.

The v2 metrics code reports direct answering, unnecessary abstention,
clarification precision/recall and burden, tool selection/execution,
verifier false positives/negatives, draft-to-final utility, fallback, and risk
calibration separately with eligible denominators and model/revision/arm
separation. The design audit and focused metric/tool-contract tests pass. A bounded v2 orchestrator can execute
the full case-arm topology through an injected arm executor and provides a
deterministic dry path for contract testing; unsupported real components must
report unavailable instead of borrowing the legacy four-arm behavior. This is
implementation evidence for the **evaluation harness**, not agronomic-agent
performance evidence: no model-backed v2 outcomes are attached, no independent
agronomist review or consented real-user lane exists, and all artifacts set
`claim_eligible: false`.

The exact 30 cases and expectations were inspected and used to tune planner and
answerability matchers. V2 is therefore an exposed internal regression suite,
not an untouched evaluation. Its append-only exposure amendment preserves that
fact, and the audit fails if v2 is relabeled pristine. Exact all-case tests show
contract conformance only; they do not measure post-tuning generalization.

Future evaluative work requires a freshly authored, untouched v3 with
independent authorship and review. Claim-bearing work also needs cross-judge
calibration, multi-turn and executable-geometry cases, and a consented
real-user confirmation lane.

V2's historical `retrieval` component bundles document and graph retrieval, so
no graph-specific effect may be inferred from a v2 result. The newer observed
production rehearsal described below implements a separate document/graph 2×2
for instrumentation QA, but that does not retroactively change v2's arm meaning
or create a v3 performance result.

## Stability as the agent harness evolves

Benchmark v2 now negotiates a frozen harness contract before executing any
case. The contract enumerates stage topology, component semantics, feature
versions, receipt state machines, observation and metric schemas, and the
implementation identities needed to interpret an arm. Its construct-semantic
profile also freezes tool family/operation/authority classes, evidence
modalities and authority classes, answerability states, and the verifier's
policy, decision unit, and outcomes. Unknown active stages, answer-affecting
features, semantic classes, observation fields, or unreceipted components fail
before scoring; they are not silently ignored inside `production_full`.

Compatibility has three explicit outcomes:

- `comparable`: the case/scoring construct and harness semantics match. Different
  system implementations may be contrasted, but their observations are kept in
  separate exact-system slices and are never pooled;
- `migration_required`: the construct is unchanged but a declared, tested
  adapter is required to map an additive observation or trace representation.
  Raw records remain immutable beside the migrated view. V2 currently declares
  no production migration adapter, so such a change remains blocked until a
  real lossless adapter and its implementation/test receipts are added; and
- `new_benchmark_required`: cases, denominators, arm meaning, stage topology, or
  an answer-affecting feature contract changed. The old and new results must not
  share an evaluation cohort.

Every observation carries separate construct, cohort, and system fingerprints.
Measurements retain run, observation, and sample identity; model ID, revision,
backend, and configuration; and executor ID, version, result class, and
capability hash. Summaries and pairs require those exact identities. A
negotiation receipt can authorize comparison, but it cannot authorize pooling;
pooling is possible only at the measurement layer with complete identical model,
run, cohort, executor, and system identity. Duplicate pair keys fail rather than
silently overwriting a sample.

A component receipt may say `not_applicable` only under its declared case/state
predicate; generic `available_not_used` receipts cannot make an answer-affecting
arm look complete. Answerability labels are bound to behavior—for example,
`require_authority` must actually prevent generation—and tool-plan states are
bound to their invocation, clarification, and result records.

Repository development does not by itself invalidate a historical comparison.
A newly available capability can remain outside the frozen benchmark profile;
if it is inactive and leaves no observation contamination, the old construct can
still run. A changed implementation of an existing component is a distinct
system under comparison and receives a distinct system fingerprint. A new tool
or evidence implementation may map into an existing frozen semantic class; its
raw implementation ID is retained while tool scoring uses the canonical family
and operation. An unknown semantic class, or an active answer-affecting feature
without an existing isolated component contract, changes what the arm means and
requires a successor benchmark.

This protects comparability only to the extent that an executor truthfully
binds its actual orchestrator, prompt/configuration, evidence assets, tools,
verifier, and fallback implementation into the capability receipt. The checked-
in deterministic executor is contract QA, not proof that a future production
adapter has done so correctly. New production adapters therefore require
adversarial receipt and contamination tests before their runs can be compared.

## V3 protocol status

The public v3 protocol freezes a 17-stage production topology, in order:
`routing`, `typed_field_context`, `public_adapter_selection`,
`document_retrieval`, `graph_retrieval`, `evidence_selection_packing`,
`tool_planning`, `tool_execution`, `prompt_construction`,
`pre_generation_answerability_risk_intervention`, `deterministic_bypass`,
`draft_generation`, `verification`, `safety_normalization`,
`high_consequence_policy`, `structured_rendering`, and `fallback_origin`.
Every stage is answer-affecting, and each receipt requires stage-specific
evidence plus content digests. Adding, removing, reordering, or changing the
meaning of an active stage requires a topology-version and compatibility
decision; it must not be absorbed silently into an old cohort.

The protocol and its audit are public, but no sealed v3 cohort is present in the
repository. The model-free audit is expected to block when it receives the
checked-in holdout and judge templates:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_open_agronomy_benchmark_v3_readiness.py \
  --commitment configs/open_agronomy_benchmark_v3_holdout_commitment.template.json \
  --judge-calibration configs/benchmark_judge_calibration.template.json
```

That fail-closed result is the honest current state. A valid release requires a
private independently authored and reviewed hash commitment with no plaintext
holdout in Git, plus a non-placeholder human-calibrated judge receipt that
passes preregistered quality and order-sensitivity thresholds. Neither gate is
implemented by replacing template strings.

## Observed production-path rehearsal

The repository also contains a claim-ineligible
`observed_system_benchmark_adapter`. It invokes the typed production execution
core used by the cockpit and retains the exact draft, post-verification, final
answer, persisted turn, and an ordered receipt for every declared production
stage. Missing, reordered, unknown, or hash-tampered stage receipts fail
validation. The adapter has no expected-answer input and performs no scoring.

This is a parity and instrumentation rehearsal, not the v3 executor. It supports
the product modes `baseline`, `agronomic_rag`, and `mock` with both retrieval
components enabled. In `agronomic_rag` mode it also exposes an explicit 2×2:
`retrieval_neither`, `retrieval_document_only`, `retrieval_graph_only`, and
`retrieval_both`. The selected booleans are carried in the typed production
request and the document/graph stages independently report `completed`,
`completed_no_result`, or `disabled_by_arm`. Every non-retrieval production
stage remains enabled and receipted. This supports component reachability and
contamination checks; it is not by itself a causal performance estimate.

The adapter still rejects raw-model, kernel-only, and non-retrieval component
ablations. A four-run 2×2 is interpretable only when question, model, code,
assets, field context, sampler, and non-retrieval components are held fixed and
the retained receipts validate. A zero-hit arm is an observed outcome, not a
missing run.

The shared seam ends at the persisted server turn. HTTP authorization and
runtime-selection wrappers, hosted-message augmentation and metrics, the
frontend, image-research routes, and the legacy `agent.generate_answer`
evaluation runner remain separate and require their own parity tests.

```bash
PYTHONPATH=src .venv/bin/python scripts/run_observed_system_rehearsal.py \
  --output-dir /tmp/open-agronomy-observed-rehearsal \
  --question "Convert a fertilizer rate of 100 lb/ac to kg/ha." \
  --mode agronomic_rag \
  --model-id mock \
  --rag-config configs/rag.yaml \
  --retrieval-configuration retrieval_both
```

The deterministic capability-conformance runner is another non-model gate. It
executes the declared public calculator fixtures and malformed controls through
the canonical capability registry. A pass proves registry/executor/scorer
agreement for those fixtures, not natural-language selection, model behavior,
or field correctness.
