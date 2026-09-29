# Conversation integrity and the benchmark learning loop

Status: engineering repair record and proposed experiments; no new model-quality experiment or agronomic validation. Reference is main `f5abc27fa1a59452274573070b9ed92694123817`. Original benchmark cases, rubrics, grades and negative/superseded results remain unchanged. Raw prompts and answers remain private research artifacts, outside runtime retrieval and training.

## What the benchmark audit actually establishes

The post hoc audit joined 288 answer-stage occurrences from 96 executions against 72 whole semantic items, verified 20 representative raw executions and bound 38 input identities. These reuse 24 exposed cases; they are not 288 independent questions. The separate 12-case METHOD diagnostic is not pooled with them. See the [public aggregate](artifacts/benchmark-scrutiny-20260928.json), [system validation](system-validation-20260928.md), [accepted repair comparison](residual-polish-checkpoint-20260928.md), and [METHOD diagnostic](portable-agronomy-diagnostic-20260928.md).

| Pattern | Observation | Engineering consequence |
| --- | --- | --- |
| Completion criteria exceed the question | Known optional checklists reject some direct, supported answers. One gold calculation expression omits a factor; another task claims to supply a value that is absent. | Freeze old scores. Future required criteria must cite the request or a necessary safety obligation; optional usefulness is a separate metric. Check numerical gold with executable units/formulas. |
| Typed work accounts for most completions | Four arithmetic cases and a table-count case account for five of Gemma's eight and Qwen's six final completions. | Preserve deterministic tools and their receipts. Improve task resolution before adding model-generated reasoning. This exposed cohort does not establish population utility. |
| Delivered history does not guarantee retrieval | A corrected crop reaches the prompt, but retrieval loses the earlier named product and packs generic boundary guidance. | Test user-authored entity carryover before retrieval, separately from history transport; do not use prior assistant claims as evidence. |
| Safety intervention can lose the task | A fully specified arithmetic correction and bounded explanations receive generic pesticide refusals. A prior broad bypass introduced an unsupported zero-rate recommendation. | A generic bypass is rejected. Compare explanation/action pairs, explicit arithmetic and zero-dose endpoints under the existing guard before considering a narrow repair. |
| Correct context does not repair contradictory prose | METHOD material reaches the model but incorrect financial relationships remain alongside correct appended material. | Do not activate the appendix or infer answer quality from retrieval hit rate. Test contradiction removal in the final answer. |

The frozen accepted-candidate completion counts remain **8/24 Gemma and 6/24 Qwen**. A conservative, selected-case minimum-obligation sensitivity adds five outputs in three cases, giving conditional counts of **11/24 and 8/24** (source-supported: 10 and 8). This is post hoc interpretation, not a blinded regrade, a harness improvement, or an exhaustive replacement rubric. Unresolved source claims and the conflicted Qwen draft judgment remain unresolved.

## The repair boundary

The current package addresses mechanical integrity: recover typed references after a newly completed explicit request following a hosted-message gap; order same-session execution and identify duplicate submissions; reject stale client responses after chat/field changes; correct timing labels; preserve formula operands and distinguish rounded results from exact equality. These behaviors are covered by conversation integrity and frontend workflow regressions; repository CI and the accompanying review govern integration.

The transcript remains durable while the model sees a bounded recent window. An oversized newest prior turn may exclude older context rather than silently create a discontinuous history. That policy is conservative, but it does not guarantee long-lived corrections. Generated summaries, new KV policies and prompt caching are not activated by this package. Active cache behavior remains disabled pending matched quality, latency and memory measurements.

A disconnected stream is not proof that generation or persistence stopped. Cancelling an awaiting thread wrapper is not cooperative model cancellation. The hosted bridge retains an app-owned completion task and its ordering guard across ordinary request cancellation while the process remains alive; process shutdown or crash is not a durable task queue. Saved-session context binding, authorization and context updates must use the same execution ordering boundary, including context PATCH requests. Rejected or replayed operations must not change saved context. Retry handling reconciles a durable operation identity and receipt; late UI events must not mutate the newly selected conversation. Ordering is process-local in the supported single-process SQLite runtime. The retained Postgres store does not implement saved conversations and returns an explicit unavailable response. Client unresolved-operation IDs are bounded to eight during one page lifetime; after a full reload, inspect the saved conversation before resubmitting an in-flight question. In-flight conflicts on an already-open stream are SSE errors, while known conflicts before opening return HTTP 409.

## Turn benchmark evidence into a repair decision

Keep an offline normalized join, with separate case, observation, judgment, finding and cohort records. The existing evaluation audit is the starting point; avoid a second runtime knowledge system. Each observation binds question/context/history/rubric hashes, source commit, model revision, arm/trial/stage, execution/prompt/answer hashes and source delivery. Preserve null judgments and original rows. Identical answer bytes under different questions do not justify grade reuse. Superseded apparatus, failed setup and rejected interventions remain visible but are excluded from efficacy counts.

For each finding, record observation, interpretation, rival explanation, smallest repair and falsifier. No case text or answer is promoted to runtime memory, retrieval, graph or training. A prospective successor should freeze before implementation: required obligations with request/safety rationale, optional usefulness, necessary authority, unit-aware oracle where applicable, independent case family and exposure status. Calibrate judges against expert review before scientific or advisory claims.

Next distinguishing experiment: bounded user-authored product/operand resolution before routing, using unseen correction chains plus topic switch, explicit deletion, wrong earlier assistant claims, ambiguous referents, failed turn, restart and field-scope controls. Baseline is the current product path; candidate changes only resolution. Report supported minimum completion, introduced material error, unnecessary refusal, source delivery, time to first useful result, generation tokens, prompt tokens and peak memory separately. Stop on any introduced authority violation or stale-field carryover. Do not use the exposed 24-case score as the sole promotion gate. Any full model suite uses the authorized Colab workflow with a fresh source/input/run identity.

## Workspace assistance and the tiny Cua model

The user-mentioned [CUA-S1 Forms](https://huggingface.co/cua-ai/cua-s1-forms) is a 706,048-parameter MIT-licensed option scorer. It chooses among supplied form values/actions rather than generating text or planning arbitrary desktop work. Its validation is concentrated on forms, largely synthetic; it does not establish agronomic or workspace-management competence. The [Core ML conversion](https://huggingface.co/FluidInference/cua-s1-forms-coreml) reports a roughly 1.5 MB package with no text-generation KV cache; model-call timings are not end-to-end app timings. These are publisher claims inspected on 2026-09-28, not measurements on this laptop. No weights, runtime or new dependency has been installed.

A plausible use is selecting among already extracted, validated candidates: suggest a matching imported column, select an existing evidence card, or choose a display action. It cannot supply missing evidence, invent field geometry or grant permission. Measure it against simple rules and the existing model selecting the same finite choices; count extraction, candidate construction, loading, errors and user corrections in the comparison. Model size alone is not a reason to bundle it.

The simplest app seam is a bounded result-to-view adapter, initially using existing typed result records without a new model:

| Proposed display action | Existing target | Required boundary |
| --- | --- | --- |
| Open evidence card | Verified saved turn and admitted card ID | Resolve within the current conversation; reject missing or invalid receipts. |
| Focus current field | Authorized saved field ID and current geometry | Reject stale field snapshots; preserve user pan/zoom and offer restore. |
| Reveal existing map layer | Available catalog layer and admitted map context | Respect layer count/offline constraints; label regional context and allow dismiss. |

These are **proposals**, not implemented capabilities. Pass short IDs outside conversational memory, never model-generated JavaScript, HTML, URLs, coordinates or record edits. The client resolves authorized geometry and owns rendering. An explicit request to show a field could dispatch a validated display action; incidental suggestions should leave viewport control with the user. Start with evidence-card focus, keyboard/Escape behavior and stale-response tests before map automation. A later tiny scorer earns inclusion only through a preregistered improvement over the simpler candidate selector, with no additional wrong-target or stale-field actions.

## Current-stage limits

Engineering tests can close reproduced ordering, persistence and presentation defects. They cannot establish general agronomic expertise, expert-calibrated judgment, reliable long-context correction recall or local-model speedups. The next semantic and UI experiments above remain unperformed; they are not hidden inside a green test-suite claim.
