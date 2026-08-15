# Evaluation contract

The canonical internal benchmark is `open_agronomy_canadian_performance_v1`: 241 project-owned Canadian field questions. It is a development instrument, not a certification exam and not evidence of agronomist equivalence.

## Frozen arms

| Arm | Input and behavior |
|---|---|
| `raw_model` | User question only; no kernel, retrieval, verifier, or post-processing |
| `baseline` | Shared kernel and answer contract; no retrieval or verifier |
| `kernel_field_context` | Kernel plus the same structured crop, region, jurisdiction and management context used by the full arm |
| `agronomic_rag` | Kernel plus governed retrieval/evidence intervention and configured validation |

The primary causal comparison is raw model versus the governed system. Intermediate arms identify whether changes arise from instructions, field context, or knowledge/evidence handling.

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
retention path has focused automated tests against a synthetic database. It has
not recovered the missing RC1 artifacts and has not yet been exercised by a new
complete benchmark round.

## Current RC3 development-rerun boundary

`configs/final_benchmark_round_rc1.json` and
`configs/final_benchmark_round_rc2.json` are frozen historical identities. The
current orchestration candidate is `configs/final_benchmark_round_rc3.json`.
RC3 is explicitly classified `development_rerun_nonclaim`: it reruns the
exposed-and-used-for-system-tuning 241-case Canadian suite through the legacy
four-arm executor under the active cumulative runtime-v2 knowledge contract.
It does not exercise the sealed v3 holdout, full v3 component matrix, or
observed product/service orchestration. AgroQA v1 is retired after RC1 exposure,
so the RC3 preflight emits no external-diagnostic command.

From a clean committed checkout, first create the exact public package and
same-commit environment receipt described in
[Release-candidate checkout gates](developer/release-readiness.md). Then run the
model-free RC3 preflight:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_final_benchmark_readiness.py \
  --plan configs/final_benchmark_round_rc3.json \
  --hub-cache /absolute/path/to/huggingface/hub \
  --egress-authorization /absolute/path/to/authorized_egress_receipt.json \
  --public-release-root /absolute/path/to/public-release \
  --environment-receipt outputs/release/release_environment.json
```

The checked-in egress file is a non-authorizing template for benchmark ID
`open_agronomy_canadian_performance_v1_runtime_v2`. A real human-issued
schema-v4 receipt must be bound to that benchmark, exact suite hash, exact
241-case application-message contract, active public runtime-artifact contract,
and static-prompt contract. It must be currently valid in UTC and reproduce
the frozen phase/arm map. Its exact
authorized class list is:

- `project_owned_frozen_benchmark_questions`
- `benchmark_system_and_answer_contract_prompts`
- `synthetic_eval_field_context`
- `selected_public_release_runtime_document_source_excerpts`
- `public_release_runtime_graph_evidence`
- `candidate_drafts_for_verification`
- `verifier_evidence`

The corresponding map is candidate raw = question only; baseline = question
and prompt; kernel = question, prompt, and synthetic context; RAG candidate =
question, prompt, synthetic context, selected public document excerpts, and
public graph evidence; and RAG verification = question, prompt, selected public
document excerpts, candidate draft, and verifier evidence. Verification has no raw, baseline, or
kernel entry. The exact excluded classes are `farmer_records`,
`private_field_history`, `credentials`, and
`whole_local_knowledge_corpus_files`.

For candidate generation, authorization v4 freezes the exact application-layer
message hash for every suite case and arm. The transport independently rebuilds
that message shape before the App Server call, so appended text or a changed
prompt invalidates authorization. App Server's text-only control remains a
separate transport receipt; no tokenizer-level equivalence with local MLX is
claimed. Runtime envelope and hash-only receipt semantics are versioned as v2.
Deterministic tools stay local and bypass Luna, and RC3 authorizes no tool-result
or semantic-judge payload class.

Private knowledge is disabled for every arm: the runner forces
`AGRONOMY_AGENT_PRIVATE_KNOWLEDGE=disabled` and invokes each child evaluation
with `--private-knowledge-policy disabled`. Private knowledge is neither an
authorized payload nor an optional benchmark feature. RC3 also has no judge
payload class and rejects `--judge-calibration`; every emitted command omits
`--judge`. The declared `judge_seed` remains an inert replication-identity
field with `judge_seed_application=not_requested` and grants no judge authority.
Deterministic calculation and interface checks retain their contract-defined
scorers.

The preflight validates the exact source, suite/model profiles, local snapshots,
environment and public-package receipts, corpus/source retention, payload
authority, interface probes, free disk, and fresh per-model/per-trial outputs.
It performs no generation or judging. A `ready` result emits nine internal
commands: three model candidates by three declared trials, each with its own
output and invocation receipt. Every command carries both
`--resume-partial-runs` and `--reuse-complete-runs`; reuse still requires exact
substantive identity and a valid completion receipt. The preflight authorizes
only that non-claim development
rerun; it is not a benchmark outcome, a v3 readiness result, or permission to
publish.

The template egress receipt is deliberately unauthorized and expired. The
checked-in judge calibration and v3 holdout commitment are also non-authorizing
templates. RC3 rejects judge calibration entirely; the separate sealed-v3
protocol still has its own human judge-calibration gate. Human egress
authorization and an independently authored/reviewed sealed v3 commitment must
never be inferred from a passing code test or filled in by an implementation
agent.

The public-safe [RC2 implementation and readiness record](https://github.com/Tknecht4/open_agronomy_agent/blob/main/docs/reviews/open-agronomy-benchmark-rc2-readiness-record-20260814.md)
separates implemented contracts, diagnostic observations, interpretations, and
the gates inherited by RC3. It remains historical evidence, not a claim that
the current runtime-v2 rerun has executed.

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
preserved as an orchestration defect for the next development round.

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
  --rag-config configs/rag_governed_runtime_v2.yaml \
  --retrieval-configuration retrieval_both
```

The deterministic capability-conformance runner is another non-model gate. It
executes the declared public calculator fixtures and malformed controls through
the canonical capability registry. A pass proves registry/executor/scorer
agreement for those fixtures, not natural-language selection, model behavior,
or field correctness.
