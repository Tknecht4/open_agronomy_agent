# Open Agronomy Agent benchmark RC2 readiness record

**Date:** 2026-08-14

**Branch under review:** `codex/test-suite-qaqc`

**Record status:** implementation freeze complete; release gates pending; full
benchmark execution not authorized

**Round class:** `development_rerun_nonclaim`

## Executive assessment

The branch has moved materially closer to a reproducible benchmark release
candidate. It now has a shared typed production execution core, content-bound
receipts for an ordered 17-stage product topology, a real document/graph
retrieval 2×2 for non-claim rehearsal, a versioned harness-compatibility
contract, per-trial sampling/process/cache identity, deterministic public
capability conformance, private retention/public-linkage contracts, and
fail-closed RC2/v3 preflights.

This is not yet authorization to run or publish the full matrix. RC2 reruns an
exposed internal suite through the legacy four-arm executor and therefore can
support engineering comparison only. The answer-content and stage-receipt
defects found by the pilot are closed. The final clean-checkout, complete test,
rendered-documentation, public-package, and environment gates have not yet been
recorded against the final commit. The sealed-v3
holdout, judge-calibration, and egress gates require real human-controlled
artifacts and remain deliberately blocked by templates.

## Review method and evidence language

This record separates three kinds of statement:

- **Observation** means code, a checked-in contract, a command result, or a
  retained diagnostic was directly inspected.
- **Model** means an explanation of why the observations behave as they do; it
  is a falsifiable engineering hypothesis, not a measured field fact.
- **Interpretation** states what the observation may and may not support.

The local seed pilot used already exposed project-owned OACP1 cases. It was run
from an in-development checkout and its raw artifacts remain outside Git. Its
numbers are diagnostic QA only, not a benchmark outcome, model ranking, or
estimate of agronomic ability.

## Implemented system boundary

### Observation — one typed product core

The cockpit/server answer path and the observed-system rehearsal now invoke the
same typed `AgentExecutionRequest`/`AgentExecutionResult` seam. The rehearsal
has no expected-answer or scoring input. It retains draft, post-verification,
final, persistence, and stage-observation identities, then validates ordered
content-bound receipts.

The active contract is
`open_agronomy_agent.production_stage_topology.v3` with 17 ordered,
answer-affecting stages:

1. `routing`
2. `typed_field_context`
3. `public_adapter_selection`
4. `document_retrieval`
5. `graph_retrieval`
6. `evidence_selection_packing`
7. `tool_planning`
8. `tool_execution`
9. `prompt_construction`
10. `pre_generation_answerability_risk_intervention`
11. `deterministic_bypass`
12. `draft_generation`
13. `verification`
14. `safety_normalization`
15. `high_consequence_policy`
16. `structured_rendering`
17. `fallback_origin`

Each stage requires a decision reason and stage-specific evidence fields.
Answer-bearing or identity-bearing evidence is content-addressed. Missing,
unknown, reordered, duplicated, or digest-tampered receipts fail validation.

### Model

Sharing the typed core removes an important class of test-harness drift: the
rehearsal cannot silently substitute a second answer generator for the server
path. Ordered content receipts also make stage addition, omission, and
unexpected bypass observable.

### Interpretation

This establishes parity only through the persisted server-turn seam. It does
not establish HTTP authorization/runtime-selection parity, hosted-message
augmentation, frontend rendering, image workflows, or equivalence with the
legacy `agent.generate_answer` benchmark executor. Those remain separate test
surfaces. A receipt proves the recorded stage contract was satisfied; it does
not prove the answer is agronomically correct.

## Document/graph retrieval 2×2

### Observation

The observed production adapter exposes exactly four retrieval configurations:

| Configuration | Documents | Graph | Other 15 stages |
|---|---:|---:|---|
| `retrieval_neither` | off | off | enabled and receipted |
| `retrieval_document_only` | on | off | enabled and receipted |
| `retrieval_graph_only` | off | on | enabled and receipted |
| `retrieval_both` | on | on | enabled and receipted |

The selected booleans travel in the typed production request. Document and
graph stages independently record `completed`, `completed_no_result`, or
`disabled_by_arm`, along with counts and identity digests. Non-retrieval stage
toggles are rejected by this adapter.

### Model

Holding every other stage fixed allows the four runs to detect component
reachability, disabled-arm contamination, zero-hit behavior, and answer/trace
changes associated with each retrieval source.

### Interpretation

The 2×2 is a necessary harness-isolation instrument, but a single-question
rehearsal is not a causal performance study. A future effect estimate must use
frozen cases, model/runtime/assets/sampler, matched trial identities, declared
metrics, retained failures, and suitable uncertainty analysis. Legacy v2 still
bundles retrieval and cannot acquire graph-specific meaning retroactively.

## Harness stability and compatibility

### Observation

The v2 harness contract freezes construct/cohort/system fingerprints; stage and
feature semantics; receipt state machines; observation and metric schemas;
canonical tool/evidence/authority classes; and executor identities. Negotiation
has three outcomes:

- `comparable`: construct and harness semantics match; different systems remain
  separate exact-system slices;
- `migration_required`: the construct is unchanged but a declared, lossless,
  tested observation adapter is required; raw records remain immutable; or
- `new_benchmark_required`: cases, denominators, arm meaning, stage topology, or
  answer-affecting semantics changed.

Unknown active stages/classes/fields, unreceipted components, invalid
`not_applicable` states, duplicate pair keys, and identity-incomplete
observations fail before scoring. No production migration adapter is silently
assumed.

### Model

This separates two common changes that should not be conflated. A new inactive
tool can coexist with an old frozen benchmark profile. A changed implementation
of an existing component is a new system slice. A new active semantic class or
stage changes the benchmark meaning and normally requires a successor cohort.

### Interpretation

The contract is resilient only if an executor truthfully binds its actual
orchestrator, prompts/configuration, evidence assets, tools, verifier, fallback,
and renderer. Compatibility metadata cannot repair an adapter that fabricates
or omits observations. Every new production adapter therefore needs adversarial
receipt and cross-arm contamination tests.

## Replication and trial identity

### Observation

The legacy benchmark runner now retains explicit trial and sampling identity:
`trial_id`, run/process/cache execution IDs, sample index, observation ID,
matched-trial key, generation/verification/case-order/judge seeds, ordered-case
digest, process-isolation policy, and cache policy. MLX applies the requested
seed inside the serialized generation lock before sampler construction and
reapplies it on speculative fallback. A durable invocation receipt is written
per model and trial. Completed trials are not rerun unless explicitly reused;
resume requires matching substantive identity and duplicate trials fail.

RC2 declares three trials per model, `fresh_process_per_run`,
`no_prompt_cache`, temperature `0.0`, top-p `0.9`, and top-k `0`. The audit emits
one unique output/invocation path for each of three candidates by three trials.
Temperature-zero runs are described as repeated trials, not independent
stochastic samples unless the backend's observed behavior justifies that
stronger label.

### Model

Separating generation, verification, ordering, and judging seeds makes variance
sources inspectable. Fresh processes and cache epochs reduce accidental state
carryover. They do not make correlated prompts/cases statistically independent.

### Interpretation

These controls support exact rerun diagnosis and within-suite variance
reporting. They do not create external validity, compensate for an exposed
suite, or justify pooling different models/systems/trials without the declared
pairing keys.

## Deterministic capability conformance

### Observation

The public capability-conformance contract exercises all 12 declared calculator
operations plus four malformed controls through the canonical registry,
executor, and scorer. The diagnostic pass observed all declared valid fixtures
and all malformed controls behaving as specified. The result is explicitly
`claim_eligible: false`.

### Interpretation

This proves deterministic contract agreement for those fixtures. It does not
prove natural-language tool selection, tool-result use in a generated answer,
field suitability of an operator-selected target, or general model ability.

## RC2 orchestration and human authority

### Observation

`configs/final_benchmark_round_rc2.json` freezes the exposed 241-case Canadian
suite, four legacy arms, exact Gemma 3/Gemma 4/Luna profiles, three declared
trials, output layout, replication policy, and non-claim boundary. It explicitly
sets both v3 performance and harness-component effect claims false. AgroQA v1
is `retired_after_rc1_exposure`; RC2 permits no rerun and emits no AgroQA
command.

The model-free RC2 audit checks source/branch state, suite/config/model hashes,
local model snapshots, the same-commit environment receipt, exact public
package, source retention and runtime corpus, construct/separation status,
fresh model-by-trial destinations, interface probes, disk, egress authority,
and optional judge calibration. A pass would emit nine internal commands and
perform no generation or judging.

Three human-controlled gates remain exact and separate:

1. **Egress:** the checked-in schema-v2 receipt is a deliberately unauthorized,
   expired template. A currently valid human receipt must bind the suite and
   exact allowed/excluded payload classes.
2. **Judge calibration:** the checked-in calibration has placeholder digests
   and failing observed values. A real human-labeled, blinded, disagreement-
   preserving package must bind prompts/rubric/parser and pass preregistered
   quality and order-reversal thresholds. Automated judging remains advisory.
3. **Sealed v3:** the checked-in holdout commitment is a placeholder. A private,
   independently authored and reviewed, hash-committed cohort with an access log
   and no plaintext in Git is required.

### Interpretation

Code, tests, model availability, or replacing template strings cannot supply
human authority. RC2 may eventually support only a new development comparison
on the exposed internal set. It cannot become a v3 claim by passing its own
preflight.

## Gemma 3 270M local preparation

### Observation

The pinned local candidate is
`mlx-community/gemma-3-270m-it-4bit` at revision
`ff1143e3a10547c9f2129e94ca37059b096b23f4`. The local Hub verification checked
12 snapshot files against the remote repository. Following symlinks, the
verified snapshot occupied approximately 181 MiB in the exercised cache. Model
inference and the diagnostic pilot ran through MLX on Apple Metal; the cache is
ignored and is not part of the public package.

### Interpretation

Snapshot presence, checksum verification, and a successful generation path
establish local provisioning for this device. They do not establish throughput
for the full matrix, answer quality, or portability to a different host.

## Gemma 3 seed pilot — diagnostic QA only

### Frozen diagnostic design

The pilot selected six already exposed OACP1 development cases spanning one
objective calculation, Canadian decision quality, official-source answer
boundaries, and regional-context interpretation. It ran four trial conditions
for each of `raw_model` and `agronomic_rag`: two repeat trials with generation
seed `314159`, then seeds `271828` and `161803`. All used case-order seed
`424242`, temperature `0.7`, top-p `0.95`, top-k `40`, maximum 120 tokens,
fresh-process execution, no prompt cache, and a separately recorded
verification seed equal to generation seed plus 10,000.

This produced 24 case observations per arm, 48 total. The two same-seed runs
were a repeatability check; the three distinct generation seeds were a narrow
sensitivity probe. The pilot was intentionally not scored as a benchmark.

### Observation — repeatability and variation

- Same-seed normalized answers matched exactly for all 6/6 raw cases and all
  6/6 governed cases.
- For the governed arm, the retained route/retrieval/tool/intervention/verifier
  trace subset also matched for 6/6 same-seed cases.
- Across the three distinct seeds, raw normalized answers varied for 6/6 cases
  and produced three unique answers per case. Governed normalized answers
  varied for 1/6 cases; five cases were stable, including deterministic/policy
  paths.

Normalized aggregate answer digests were:

| Trial condition | Raw digest | Governed digest |
|---|---|---|
| seed 314159, repeat A | `e83f0da132a194f217f0caef555aea9e0df0121dc7c758f396111e1e02ca2418` | `4198b0d183900506ce1ee4e1aa4c28ae4d6b508e059dedd20e92bc4e43f160da` |
| seed 314159, repeat B | `e83f0da132a194f217f0caef555aea9e0df0121dc7c758f396111e1e02ca2418` | `4198b0d183900506ce1ee4e1aa4c28ae4d6b508e059dedd20e92bc4e43f160da` |
| seed 271828 | `e8659081c27423a7cade62af49a8dc39c10d1e4ddc4855eeec86cfbe04183908` | `4198b0d183900506ce1ee4e1aa4c28ae4d6b508e059dedd20e92bc4e43f160da` |
| seed 161803 | `dba237c8488ada88629e68496cef07f9087b7956edfe978423ae875b18f31987` | `36a01b224b0cc88af6c379e70ba9c9688ef7922b1b9142f6071ea41fb0d42463` |

Observed mean wall time per case, in the same trial order, was approximately
`1.0548`, `0.8688`, `0.8007`, and `0.8412` seconds for raw; and `0.9432`,
`0.9465`, `1.0542`, and `0.7917` seconds for governed. These are six-case local
diagnostics without warm/cold decomposition or uncertainty intervals.

### Model

The exact same-seed repeats are consistent with the seed reaching the sampled
generation path under the exercised local conditions. Lower governed variation
is consistent with deterministic tool bypasses and policy/verifier replacement
stabilizing some outputs. The pilot is too small and too exposed to distinguish
beneficial stabilization from repeated generic fallback.

### Interpretation

The pilot validates receipt plumbing and motivates targeted fault inspection.
It does not establish that governed answers are better, that the harness is
deterministic on every backend, or that the latency relationship will hold at
241 cases, three models, or longer answers. Variation is not quality; stability
can preserve either a useful answer or a defect.

## Product-path defects found by the pilot

### Closed — regional-context evidence admission and SLC replacement

One seed exposed an answer that treated a regional Soil Landscapes of Canada
historical product as if it described the user's current field and introduced
unsupported crop examples. Inspection showed that context-only evidence was
being removed before verification even when the user explicitly requested
interpretation of the named regional product.

The narrow repair admits context-only evidence to the verifier for an explicit
`regional_context` interpretation request while retaining weak-evidence
rejection for field action or diagnosis. The verifier then replaces the draft
with the named historical SLC decision capsule, preserving the distinction
between regional historical context and current field truth. Focused regional-
context and conceptual-routing regressions cover both the allowed
interpretation and the still-blocked action boundary. The seed-specific
governed rerun verified the replacement path. This closes the observed defect
as an implementation regression; it does not validate SLC as a field
measurement or make the pilot claim-eligible.

### Closed — topic-gated conceptual fallback

A subsequent product-path rerun exposed a separate defect: the generic
`exam_review` fallback could return a nutrient-management capsule for an
unrelated benign conceptual question. The repair gates fallback by topic and
provides an appropriate crop-rotation capsule without weakening high-consequence
or missing-evidence behavior.

The repair now dispatches the conservative conceptual fallback by recognized
topic, includes a bounded crop-rotation mechanism capsule, retains the nutrient
capsule only for nutrient questions, and degrades honestly when no supported
topic-specific capsule exists. Focused tests preserve regulated product-label
and field-diagnosis fallbacks. The exact real Gemma 3 rerun returned the bounded
crop-rotation mechanism capsule with `claim_eligible: false`. This closes the
unrelated-content answer defect; it does not make the answer a benchmark result.

### Closed — fallback-origin receipt consistency

The same successful answer-content rerun exposed a receipt contradiction. The
verification observation reports `fallback_applied: true`, while the final
`fallback_origin` stage reports a configured-model origin with
`fallback_used: false`. The final answer is therefore better than the draft,
but the 17-stage trace does not truthfully identify which stage supplied it.

The topology repair now reconciles verifier replacement with final-answer
origin. In the final exact real Gemma 3 rerun, `fallback_origin` reports
`verifier_conservative_fallback`, `fallback_used: true`, and
`verification_action: conservative_fallback`. The receipt binds exact draft,
post-verification, final-answer, and verification-receipt hashes. All 17
topology-v3 stages were present once, in order, and the run remained
`claim_eligible: false`. This closes the provenance contradiction for the
exercised path; it is still a rehearsal, not answer-quality or field evidence.

A public-safe digest projection of that exact full receipt is retained at
[`artifacts/gemma3-270m-observed-system-rehearsal-nonclaim-20260814.json`](artifacts/gemma3-270m-observed-system-rehearsal-nonclaim-20260814.json).
The projection binds the full private receipt by SHA-256 and preserves the
model identity, claim boundary, ordered stage-receipt hashes, and answer-origin
hash chain while excluding prompt, draft, final-answer, retrieved-content,
field-context, tool-payload, session, and local-path content.

## Verification snapshot and remaining release gates

The following are implementation observations accumulated during development,
not one final clean-commit gate:

- replication-contract tests passed in focused and broader selections;
- RC2 plan/preflight tests passed with expected blocking on dirty/missing-human
  artifacts and emitted only nine internal commands, never AgroQA v1;
- v3 protocol and capability-conformance focused checks passed, while the
  sealed release audit correctly remained blocked on holdout/judge templates;
- retrieval-component and production-receipt focused checks passed;
- the exact real Gemma 3 conceptual rehearsal returned the topic-relevant
  bounded capsule with a truthful verifier-fallback origin and 17 unique,
  ordered topology-v3 receipts; and
- source documentation, strict MkDocs rendering, rendered-site scope, and the
  curated public-package builder passed at this documentation freeze. The
  source audit covered 21 Markdown files, the rendered audit covered 72 files,
  and a focused docs/public/product-receipt selection passed 66 tests.

Before the full benchmark matrix, the final commit must have a new consolidated
receipt for all of the following:

1. full Python suite;
2. frontend tests, typecheck, and production build;
3. source docs audit, strict MkDocs build, and rendered-site audit;
4. curated public-package build with forbidden private/cache/output scope;
5. clean committed checkout and same-commit environment receipt;
6. exact Gemma 3 and Gemma 4 local snapshot verification;
7. deterministic capability conformance and retention/privacy/recovery checks;
8. RC2 model-free preflight using a real currently valid human egress receipt;
9. owner review of the nine emitted internal commands before generation.

Judge calibration is not required to run deterministic or non-judged RC2 lanes;
it is required before enabling semantic judging. A sealed-v3 holdout is not an
RC2 input and remains a separate future release gate.

## Release decision

**Current decision: not ready to start the full benchmark matrix.** The branch
contains the intended internal contracts and has successfully used small,
falsifiable diagnostics to find and close real product-path and provenance
defects. That is evidence the benchmark infrastructure can test the harness as
well as compare generators. The honest next step is to run the complete final
verification from one clean commit, obtain the required human egress authority,
and only then execute the nine RC2 development commands. No v3 or
agronomic-ability claim is authorized by that sequence.
