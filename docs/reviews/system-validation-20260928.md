# App validation and retrieval comparison checkpoint

Date: 2026-09-28. Status: reviewed development checkpoint; corrected comparisons complete. Gemma completed 192 observations and Qwen completed 96. The first
instrument had a field-context representation defect; its completed Gemma and
stopped Qwen results remain separate, superseded partial-delivery diagnostics.
App and telemetry repairs pass their engineering gates. Active profiles are
unchanged. This is an internal development checkpoint, not agronomic validation.

## Problem and resulting behavior

An offline boot followed by a healthy API could enable chat without loading saved
fields, conversations or the active model profile. Recovery now loads the required
workspace resources and ignores delayed responses after a newer user selection.
It preserves unsent text and device-only field notes. Saved-record requests no
longer divert into calculator missing-input prompts; complete, incomplete and
invalid numeric operations retain their previous typed behavior. Missing local
model snapshots propagate through lazy tokenization, generation and editing as an
actionable setup error, without saving a substitute answer or exposing a private
exception path.

The observed-system benchmark adapter rejects hidden disabling of production
components while claiming retrieval-only fidelity. The historical
`full_minus_fallback` name is explicitly limited to generator-exception recovery;
it does not imply that verifier replacement or resource-limit handling is disabled.
Active retrieval, model, editor, METHOD and prompt-cache profiles are unchanged.

## What the customer journey established

Actual browser turns used the pinned active Gemma, an isolated synthetic workspace,
offline public sources and no private overlay. General chat, explicit unit
conversion, saving/reloading history, saved-field chat and switching back to a
general conversation worked. A synthetic field with wheat and no location or soil
test was not treated as containing those missing facts. The final offline-restart
retry restored its selected field, transcript, profile and exact unsent text.
Delayed field/chat switches during recovery also pass component regressions.

The short follow-up “What about 200 instead?” failed after a successful 100 lb/ac
conversion even though the previous exchange was present in the actual model
prompt. An explicit 200 lb/ac question succeeded. This newly exposed failure is
outside the frozen scored cohort. Generic answers can also remain unhelpful while
respecting field isolation. Cancellation during actual inference and a broad
responsive-layout sweep were not established; the retained in-app screenshot uses
a very narrow viewport and is not desktop-layout validation.

## Frozen comparison

The first runner passed legacy field keys directly, skipping the product adapter.
In 176/192 Gemma traces (22 cases across arms/trials), compiled crop/location fields
were empty; another eight retained crop but dropped province. The eight table
imports used their separate correct path. Raw aliases still reached some retrieval
and policy readers, so delivery was inconsistent rather than wholly absent.
The corrected instrument must map existing facts into the product schema and
assert their presence in the compiled receipt and actual generation prompt.
Previous scores stay separate; the original cohort, gold and traces are unchanged.

The exposed development cohort has 24 cases, four in each of six strata: general
explanation, source/table lookup, calculation, field reasoning, appropriate
clarification/abstention, and multi-turn correction. It contains 19 previously
exposed successor cases, one reviewed table pilot and four fixed synthetic history
cases. It is neither a held-out nor a representative customer distribution.

Gemma runs document/graph retrieval as neither, documents only, graph only and
both, with two trials in reversed arm order: 192 attempted observations. Each arm
uses the production execution core with the same field state, tools, risk policy,
editor and final transformations. This measures the total downstream effect of
retrieval, not an isolated retriever or the whole harness against a raw model.
The separate pinned Qwen3.5 27B contrast uses all 24 cases with neither/both and two
trials: 96 planned observations. That contrast was selected before the final
Gemma grades for interpretability, not by choosing a winning arm or favorable
case subset. Model results remain separate.

Both use temperature zero, seed 42, an 8192-token context, cache off, a 640-token
draft cap and a 220-token editor cap. Two separate setup prompts established
execution fit before each model run; their short answers do not prove that every
cohort answer is uncensored. Qwen uses its existing diagnostic 512-token prefill
step for L4 memory fit. Gold/rubrics remain local and never enter runtime retrieval,
training or the model-host capsule. Each cell has an isolated store; the registered
table count tool imports the exact reviewed 13-record fixture.

The benchmark Python source is commit
`2b4028560c18def902463b4da44ef2c5c69467b1`: all 147 recorded source hashes match.
The later telemetry correction is a separately tested source delta; these raw
model runs do not claim to measure that correction. The source, corpus, model
revision, fixture, input, runner and settings are bound in the run manifests.

## Grading and limitations

Two independent graders saw anonymous case/answer pairs with the frozen rubric,
field/history premises and source-availability statement, without arm or stage
identity. Numerical model configuration and revision were not supplied, but packet
filenames could reveal model family; model-family blinding was imperfect. Repeated identical answers within a case were graded once, then
mapped back to their original observations. Disagreements and flagged source claims
received a third source-based adjudication. This is automated internal triage,
not qualified agronomic validation. Concise semantically correct answers qualify;
conditional criteria apply only when relevant.

The corrected Gemma run has 89 unique case-answers across 576 stage observations.
Thirty-three exact whole-item matches reused prior semantic grades; 56 new items
were graded independently. Completion/material-error/refusal agreement was
77/89, 87/89 and 86/89. Twenty-six items received adjudication. Fresh SQLite audits
verified all 48 parsed claims across the eight table answers. Five other provenance
checks were resolved against actual prompts and retrieved records, including one
confirmed unsupported map-boundary attribution judged non-material under the
frozen task rubric. Zero open checks means each question was resolved, not that
every source claim was correct. Semantic reuse retains the earlier model-family
blinding limitation; fresh source checks were never inherited automatically.

The corrected Qwen run has 69 unique case-answers across 288 stage observations.
Whole-item semantic reuse was checked incrementally as completed prefixes arrived;
the final packet reused 55 already graded items and added 14. Completion/material-
error/refusal agreement was 62/69, 64/69 and 67/69. Thirty-eight items required source
adjudication. Fresh SQLite audits verified 24 parsed claims across four table
answers; every grading prefix matches the full run's original execution bytes.
Eight unique answers retain unresolved source checks across all stages, including
one complete draft. Final unresolved observations are 4/48 without retrieval and
2/48 with both sources. All final completed answers are source-cleared. The open
checks include satellite explanations, site-specific intervention suitability,
SLC insurance-purpose claims, sampling protocol and a yield/insurance assurance.
They remain in denominators; identified-error counts do not imply that unverified
claims are correct. No source uncertainty was silently converted into a pass.

The frozen seed-rate criterion contains a formula typo: `300×35/(95×90)` is 1.228,
not the supplied reference 122.8 kg/ha. Independent dimensional calculation gives
122.807 kg/ha. Adjudication preserves the frozen text, documents the defect, and
uses the original inputs, reference and tolerance. No frozen case was rewritten.

## Benchmark problem-setup limits

A separate audit before reading corrected model outputs found completion criteria
that extend beyond the literal user question. Examples include a complete hybrid-
selection checklist for a map-limit explanation, an extreme-stress band for a
measure/formula/direction question, and the superseded total for a request for the
corrected total. The lentil setup also says TKW is supplied without a numeric
value in any visible input. These are concrete interpretive limits; no frozen
rubric or score was revised. [The audit](artifacts/system-validation-20260928/problem-setup-audit.md)
records each exact case/criterion and its rival interpretation.

The cohort mixes source-dependent questions with arithmetic, private-table,
user-observation and missing-authority tasks. No frozen case marks a necessary
fact unique to graph retrieval. Thus pooled completion is a strict diagnostic
score, not a direct measure of general agronomic expertise or customer usefulness.
Future confirmation should separately preregister the minimum answer obligation,
optional useful additions, material errors and action-authority requirements.

## Corrected Gemma comparison

All 192 attempts completed with verified field delivery and no execution failures.
Each row has 48 observations: the same 24 cases, each repeated twice.

| Retrieval | Draft complete | Final complete | Final material error | Final unnecessary refusal |
|---|---:|---:|---:|---:|
| Neither | 10/48 | 14/48 | 6/48 | 18/48 |
| Documents | 14/48 | 16/48 | 6/48 | 14/48 |
| Graph | 10/48 | 14/48 | 6/48 | 18/48 |
| Both | 14/48 | 16/48 | 6/48 | 14/48 |

Document retrieval adds one completed case on both trials: the Crop Stress Index
definition. It also removes unnecessary refusals in that case and the crop-stage
explanation. The paired neither/both final comparison has two completion gains,
zero losses and no material-error change across 48 case/trial pairs. Graph adds
no completion gain to either document setting here. This small exposed cohort
contains no predeclared graph-dependent necessary fact, so it cannot establish
that graph retrieval is generally dispensable.

With both retrieval sources, draft-to-final processing gains one completion case
(the incomplete lentil seeding request), creates a material crop-inventory versus
suitability-map error, removes one unnecessary refusal, and adds another on a
farm-yield-record correction. Each change repeats across the two trials. Editing
therefore has both benefits and harms; its removal is not established by these
shared-draft observations. The map error is more specific: all eight case-04 cells
reject an edited explanation for missing variety-selection checklist facets, then
install a deterministic fallback whose variety-selection branch treats any
non-atlas map as a regional suitability map. Their editor outputs use 162–186 tokens, below the 220-token cap,
and do not contain that suitability claim. This source-bound mechanism implicates
the fallback's product/task assumptions rather than truncation for these cells. Five of the eight completed cases are deterministic
calculation/table results. None of the four multi-turn cases completes under the
frozen rubric, whose limitations remain explicit above.

The corrected Gemma driver took 573.807 seconds; summed cell time was 442.944 and
product-core time 427.971 seconds. There were 112 draft calls, 48 editor calls and
80 bypasses. Draft generation used 273.707 seconds, editing 92.308 seconds, with
15.807 seconds of initial model loading outside generation. Median cell time was
1.494/1.836/1.676/2.077 seconds for neither/documents/graph/both. These are whole-cell
observations, not isolated retrieval cost or UI streaming latency.

No draft reached the 640-token cap; four of 48 editor calls reached exactly 220.
Stop reason is unknown, so these are cap-adjacent outputs rather than confirmed
length stops. No generated history or editor-evidence clipping was recorded. All
80 bypass statistics are stale in the frozen source and excluded from model cost
totals. Five of 96 repeated final-answer hash pairs differ: four from fresh table
IDs and one graph-only case with the same draft but different editor output.
Its cause is unproven. No during-run peak memory is available.

## Corrected Qwen 27B comparison

All 96 attempts completed with verified field delivery and no execution failures.
Each row again has 48 observations: 24 cases repeated twice. Error counts below
are identified material errors; the source uncertainties above remain explicit.

| Retrieval | Draft complete | Final complete | Final identified material error | Final unnecessary refusal |
|---|---:|---:|---:|---:|
| Neither | 14/48 | 12/48 | 8/48 | 14/48 |
| Both | 14/48 | 12/48 | 4/48 | 12/48 |

The no-retrieval draft count includes two observations of one source-unresolved
answer: source-cleared draft completion is 12/48, versus 14/48 with both sources.
Final completed observations are all source-cleared.

Equal final completion hides a loss and a gain: retrieval loses the erosion
explanation and gains the Crop Stress Index definition, each on both trials.
The identified material-error reductions are the Crop Stress Index definition and
the composite-soil-sampling case, again each repeated twice. Retrieval removes
unnecessary refusals for crop-stage and crop-code explanations but adds one for
the corrected farm-yield record. These paired case transitions are more informative
than the pooled completion tie. Five of six completed cases in either arm are
deterministic calculations or the table count. None of four multi-turn cases
completes under the frozen rubric. These results do not establish a general ranking
between models.

Post-processing has mixed effects here too. Without retrieval it removes three
case-level draft errors while introducing the crop-inventory/suitability-map error.
With retrieval it introduces that map error without a corresponding identified
error reduction. Both settings lose completion on the lab-result correction;
the no-retrieval draft had an unresolved sampling-protocol claim, while the
retrieval draft was source-cleared. Removing the entire verifier is not tested by
these shared-draft transitions. Its specific failures are candidates for repair.

The Qwen driver took 2805.426 seconds. Summed cell time was 2737.437 and product-core
time 2729.980 seconds. There were 56 actual draft calls, 24 editor calls and 40
bypasses. Draft generation used 2194.920 seconds, editing 488.633, and initial model
loading 22.052 seconds outside generation. Median cell time was 32.195 seconds
without retrieval and 38.581 with both sources. These descriptive totals include
changed prompts, generated answers and policy paths; they do not isolate retrieval
cost. No draft or editor call reached its recorded output cap. Actual draft history
was not clipped; four bypasses omitted history without making a draft call. All
40 stale bypass statistics remain in raw traces but are excluded from model-call
cost totals. Forty-six of 48 repeated draft/final hash pairs match; only the two
table pairs differ through fresh import IDs. No peak-memory or laptop-throughput
claim follows from this L4 run.

## Superseded Gemma v1 partial-delivery diagnostic

All 192 attempts completed. Each row below has 48 observations from the same
24 cases repeated twice; it does not represent 48 independent cases.

| Retrieval | Draft complete | Final complete | Final material error | Final unnecessary refusal |
|---|---:|---:|---:|---:|
| Neither | 10/48 | 14/48 | 6/48 | 14/48 |
| Documents | 12/48 | 14/48 | 8/48 | 14/48 |
| Graph | 10/48 | 14/48 | 6/48 | 16/48 |
| Both | 14/48 | 14/48 | 8/48 | 14/48 |

All four settings complete the same seven cases on both trials. Five of those
seven are deterministic calculation/table results, one is an erosion explanation,
and one is a missing-seeding-input clarification. Full retrieval completes two additional draft cases on both trials (four
observations) relative to neither, but no final completion gain survives.
The paired final contrast contains 14 complete-to-complete and 34 incomplete-to-
incomplete observations, with zero completion gains or losses. Material error is
introduced in one additional case under document retrieval, repeated twice.
A null completion difference on this small exposed set is not equivalence evidence.

Shared-draft analysis is mixed. With both retrieval sources, later transformations
gain completion on one case and lose it on another (two observations each).
All four settings replace the crop-inventory explanation with a suitability-map
answer, creating a material product-identity error. Editing also improves some
answers and clarifications. Wholesale removal of verification is not supported.

## Superseded v1 measured performance

Gemma's driver took 633.336 seconds. Summed cell elapsed time was 503.529 seconds;
product-core time was 489.219 seconds. There were 112 actual draft calls, 54 editor
calls and 80 generation bypasses. Actual draft generation used 266.240 seconds and
editor generation 162.005 seconds; the first model load added 15.632 seconds outside
generation elapsed. These boundaries are not interchangeable with user-visible
streaming latency or pure retrieval latency.

| Retrieval | Median cell seconds | Total cell seconds | Editor calls |
|---|---:|---:|---:|
| Neither | 1.533 | 114.512 | 14 |
| Documents | 1.857 | 168.447 | 16 |
| Graph | 1.675 | 98.657 | 12 |
| Both | 1.979 | 121.913 | 12 |

The document-only total includes one 44.312-second editor call, mostly time to
first token, with no model reload recorded. It should not be read as a stable
retrieval cost estimate. No during-run peak-memory or isolated retrieval timer
is available. All draft/editor budgets that were counted stayed within context.
No draft reached 640 tokens; 11 of 54 editor calls reached exactly 220 tokens and
four editor evidence packs were clipped. Stop reasons were not recorded, so an
exact-cap observation is not a confirmed length stop. Editor budget remains a
rival explanation for some incomplete outputs.

The reused backend exposes stale `generation_stats` on all 80 bypasses. Original
receipts are preserved; those rows are excluded from model timing/token totals.
The app normally constructs a fresh generator per turn, so this establishes the
reused/injected backend defect rather than widespread live-UI misreporting.

## Decision and next distinguishing repair

Retain the present active profiles for this checkpoint. The comparison does not
support promoting extra corpus machinery, adding a memory layer, enabling caching,
or removing a component merely because its small-cohort completion difference is
zero. Repair the demonstrated app and telemetry contracts, then focus the next
matched experiment on intent and evidence interpretation. Document retrieval has
shown specific value: one added Gemma completion case and two fewer identified
Qwen error cases. Those benefits argue against deleting retrieval wholesale.

The highest-priority mechanisms are generalized contracts, not more question
phrases: (1) distinguish reporting a supplied measurement or performing an explicit
calculation from choosing a field action; (2) preserve product identity and user
corrections when resolving a conversational reference; (3) compare quantity value,
unit and provenance across display formats without admitting a changed unit or
unproved derivation; (4) require a localized demonstrated defect before replacing
an otherwise useful claim. The post-hoc probes reproduce a harmless yield question
becoming `numeric_rate` solely through “should”, and an unchanged quantity becoming
unsupported when wrapped in LaTeX. Wrong-value and wrong-unit controls remain
unsupported. A stateless full-reference/follow-up routing contrast, together with
the real history-in-prompt failure, motivates a bounded reference-resolution test;
it does not by itself establish a complete causal repair.

The next first repair should preserve a source product's identity and require a
localized demonstrated defect before a verifier fallback replaces its answer.
Compare the current and repaired transformation on the same saved drafts, then
confirm on fresh questions and both models. A minimal-prompt comparison must hold
the supplied facts and evidence fixed; neither-retrieval is not that control.

Before changing the active policy, freeze new contrastive scenarios with both
answerable and genuinely unanswerable controls. Compare the current path with one
repair at a time, preserve draft/editor/final stages, and test whether an adequate
editor allowance changes the result. Require useful-answer improvement without a
material-error regression, followed by fresh confirmation cases. General and field
chats should share these contracts; their data scopes and source authority remain
distinct.

## Verification and retained evidence

The pre-telemetry integrated source passed 1,582 Python tests (four skips), all
371 frontend tests, typecheck, production build, public-doc checks and strict
MkDocs. The public-package builder passed; the regenerated inventory passed the
19 focused package/profile checks. Earlier interrupted, failed planner, setup and
capsule attempts remain retained in the local evidence tree. The earlier 20-test
planner failure was repaired against the existing contracts, not by changing gold.
The final telemetry source passed 1,585 Python tests (four skips), with strict
documentation checks and the public-package builder also passing. Independent
review accepted that exact source, both corrected mechanical audits, and the
instrument/raw reconstruction boundaries. After adding the exact public evidence
scope, 12 package/profile tests, public-doc checks, strict MkDocs and runtime
inventory regeneration passed. Independent review also reproduced both corrected quality summaries and grade
files exactly from the public archives in a fresh directory. The curated public-
package builder passed with the evidence package. Repository CI supplies the
commit-bound integration results.

The task-owned Colab L4 session is stopped; the final listing reported no active
sessions or assignments. The observed account balance delta was 3.19 compute units
at 0.01-unit display precision, including setup, superseded runs, corrected runs
and idle time. This is an account-wide measurement rather than a per-job invoice;
unrelated account activity cannot be separately excluded. Provider currency and
owner/grader/reviewer token costs are unavailable, not zero. Corrected runs fit the
40–80-minute planning estimate. No pre-existing user session was stopped.

[Independent review](artifacts/system-validation-20260928/independent-review.md)
records accepted source and artifact hashes, negative probes, and scope limits.

Artifact directory: [system-validation-20260928](artifacts/system-validation-20260928/).
The instrument contains evaluation material; it is not an admitted runtime source.
Raw stages, grades, provenance, mechanics and failures remain separately identified.

Memory delta: none.
