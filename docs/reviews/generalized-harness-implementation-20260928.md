# Portable agronomy runtime and conversation implementation

Status: combined polish and Colab diagnostic in progress; user authorized review and merge. User authorized proceeding from the source-bound harness
review, adding model/KV/context management, useful runtime indicators, backend
performance, and separate field-linked and general conversations. Full model
benchmark suites use the Colab operator. No competence or candidate-corpus
promotion follows from implementation tests.

## Reference and resource envelope

The earlier review binds `0b967a9`; implementation starts from refreshed
`origin/main` at `d2454360f8b384f01924794c69d324b98d5f7244` on
`codex/portable-agronomy`. Main already includes general questions, workspace
redesign, bounded field-history loading and performance profilers. Reuse them.
The managed worktree attempt failed from insufficient disk and cleaned itself
up. The primary checkout is reused. Its pre-existing untracked UI review is
preserved in a named Git stash and
`outputs/portable-agronomy-preserved/ui-workspace-redesign-20260927.md`, SHA256
`205b7a08fb280cadc820c90c06ca6ae363a6f77b05563fe41e1970448f1f4a56`.

Planning envelope: owner integration plus three bounded implementation workers
(runtime/cache, conversation compilation, UI), then independent review. Expect
roughly 90–150 minutes including repairs and repository gates; this is an
estimate, not a user hard limit. Provider cost is unavailable. Model-free tests
and source-bound synthetic profiling first; no speculative downloads. Checkpoint
after component contracts integrate, before any model run or broader experiment.
On overrun, stop optional expansion and repair/verify the coherent implementation.

## Acceptance map

| Obligation | Observable failure | Controlling boundary and verification |
|---|---|---|
| General and field-linked durable chats | Field facts leak into general chat; changing field silently rebinds old chat; reload loses selection/history | Session creation/update/turn authorization, workspace selection and history tests |
| Useful multi-turn context | Follow-up loses user facts/corrections; prior model text becomes agronomic evidence; unbounded transcript | Server-owned session history, bounded compiler, same-session/scope tests and prompt receipts |
| Bounded final input and truthful indicators | Token count fabricated; output reserve omitted; mandatory current input silently truncated | Final prompt compiler, optional backend tokenizer, explicit estimated/unknown count and budget labels |
| Safe reusable KV cache | Cross-scope or incompatible KV settings share entries; mutable caches contaminate subsequent requests | Generator cache namespace/config identity, bounded cache lifecycle and deterministic fake-backend tests |
| Measured performance | Token replay presented as decode rate; latency improvements asserted without matched data | Generator phase measurements, existing profiler, UI metric semantics and performance receipts |
| General harness learning path | Runtime defaults changed based on exposed score or a bundled experiment mistaken for stage attribution | Isolated replay/diagnostic tools and frozen protocol; candidate methods remain separate |
| Integration and preservation | Regressions, stale public manifest, changed historical artifacts or unrelated work | Focused tests, full Python/docs/frontend gates, public package builder, independent exact-source review |

## Shared implementation contracts

`trace.metadata.context_budget` uses schema
`open_agronomy_agent.context_budget.v1`: `status`, `input_tokens` (nullable),
`token_count_basis` (`tokenizer`, `provider`, `estimated_characters`,
`unavailable`), `context_limit_tokens` (nullable), `limit_basis` (`configured`,
`model`, `unknown`), `reserved_output_tokens`, `remaining_tokens` (nullable),
`history_turns_available`, `history_turns_included`, `history_turns_omitted`,
and `history_policy_version`. A configured operating budget is not advertised as
the model's native capacity. Context usage describes the retained request, not
the next unsent draft or a continually full chat transcript.

Existing `trace.metadata.generation_stats` remains the source of measured
`generation_tps`, `prompt_tps`, `prompt_tokens`, `generation_tokens`, cache and
phase timing values. Unknown measurements remain null/absent. Backend optional
methods: `count_prompt_tokens(messages) -> int | None`,
`set_cache_scope(scope: str) -> None`; optional `context_window_tokens` describes
a known native model limit, never a guessed capability. Exact counting may load
the model and must occur only on a path that will generate.

Conversation compilation owns `server/services/chat_service.py` and a dedicated
context module; runtime worker owns generator/cache changes in `agent.py` and
new runtime modules; UI worker owns frontend files. Owner owns HTTP/session
authorization, storage query boundaries, active config/public docs and the
experimental replay seam. Workers do not edit each other's owned files.

## Phases

1. Implement server-authoritative conversation context, compatible cache
   isolation/measurements, and clear chat selection/history/runtime indicators.
2. Integrate profiling and harness intervention diagnostics with explicit source,
   model, prompt and draft identity. Do not enable new methods or promote a
   benchmark result from implementation checks.
3. Run focused then full integration gates, exercise the UI/API with synthetic
   data, preserve negative evidence, independently review the exact candidate,
   and prepare a reviewable branch/PR.

The separate corpus chat is still completing its METHOD candidate and reports
removal of its answer appendix after evaluation. It owns its own corpus and
admission changes; this task does not modify or promote that candidate.

## Integrated decisions and observed checks

The current candidate implements conversation state and infrastructure first.
General, saved-field and example conversations have stable identities. Sessions
with no declared scope can bind on their first turn for legacy compatibility;
used unbound sessions are general. Field facts reload through the authorized
field store when the client omits a snapshot. New requests use indexed, narrow
recent-turn reads instead of loading all trace/prompt/evidence JSON.

History is a delimited JSON block in the final user prompt, with a non-evidence
policy in the initial system message, preserving strict chat-template role
alternation. First-turn prompt text is unchanged when no history is included.
The eight-turn / 2,048-token active window is subordinate to current evidence and
the inclusive 8,192-token operating budget. The draft and editor each reserve
their actual output allowance, count exact templates when available, and retain
separate budget receipts. Estimate labels are not hard provider-fit guarantees.
Rejected assistant text is excluded and user feedback remains unverified.

Compatibility decision: retain the existing 17-stage topology and bind the new
conversation policy, included turn IDs and budget hash within existing evidence
selection/prompt assembly records. This changes prompt policy and active model
config identity; it requires new evaluation run identities. Frozen historical
configs/results are untouched. Multi-turn context currently reaches prompt
assembly after routing/retrieval: this does not implement conversational query
rewriting, learned memory, or the proposed model-directed evidence loop.

KV entries bind session/role, model revision and resolved snapshot, prefill and
KV configuration. Namespace and aggregate-byte caps prevent unbounded saved
prefix growth. Active caching remains off: no new cache speed/quality claim is
made. The runtime records queue/load/tokenization/cache/decode timing where it
can measure the boundary. The UI shows saved measurements, explicit unavailable
values, and the configured-versus-model limit distinction.

The offline replay CLI compares captured answer-stage text and can shadow the
current claim-risk assessor only with exact retained verifier evidence. Historical
samples lacking those bytes remain unavailable. It is an attribution inspection
seam, not a complete intervention factorial or a semantic judge. The corpus and
METHOD candidate remains owned by the separate corpus work; this change does not
promote it or assert an expertise gain.

Observed checks so far: 33 focused scope/history/config tests passed; 293 frontend
tests, typecheck and build passed; public docs audit and strict MkDocs passed.
The final integrated Python gates and independent review are recorded below.
The synthetic matched storage profile (3 sessions, 64 turns each, 7 repeats)
measured full-history median 1.468 ms and bounded-eight median 0.026 ms; see the
source-bound storage receipt. These are warm storage operations, not a request
or model speed comparison. Measurements predate later verifier documentation/
receipt refinements, whose source is not covered by that timing receipt.

Live preview attempt: isolated synthetic SQLite data, offline configuration,
loopback-only server. The initial sandbox disallowed binding; the escalated
preview server started successfully. In-app browser navigation returned
`net::ERR_BLOCKED_BY_CLIENT`; no warning or browser restriction was bypassed.
UI visual inspection is therefore not verified. Component/workflow tests and
production compilation are observed separately.

## Next discriminating model experiment

Before changing the active harness, freeze a fresh paired diagnostic packet:
identical questions, field facts, admitted evidence, drafts, output allowances,
and backend identities; vary one intervention at a time. Score supported content
lost, unsupported action introduced/prevented, task completion, unnecessary
refusal, unit correctness and factual support with calibrated blind labels.
Include mechanism explanation, worked arithmetic, production/business planning,
diagnosis, authority-sensitive actions and multi-turn corrections. Test a small
reference and a qualified larger model on matched budgets, then an oracle-source
condition to distinguish retrieval from evidence use. The original proposed
retrieval/intervention 2x2 remains a separate offline experiment to implement and
validate; the existing frozen document/graph matrix must not be relabelled.

Full model suites use the requested Colab operator and narrow public/synthetic
transfers with source/model/device/usage receipts. No Colab session or model
benchmark was started in this implementation. Actual agronomic gains, local
Metal throughput and cross-model cache parity remain open measurements.

Initial full Python gate: 1,364 passed, 3 skipped, one packaging-manifest failure
because the new test files were not yet allowlisted. The manifest was repaired;
this failure is retained in the local gate log. The final run below supersedes
that attempt. No application test failed in that run.

Integration refreshed onto `origin/main` at `8f4c33f` after the saved-point
imagery work landed. Both additions to the public manifest were retained;
the generated runtime manifest was rebuilt from the combined source. The
point-imagery feature is outside this task and was preserved.

## Independent review and repairs

The first independent Astra review, bound to `55e2a384b2c27f73c8824f34276292c0d8001acc`,
returned repair for three reproducible P2 findings despite green integration
tests. All three have focused regressions in the candidate:

- An empty unretained-prompt placeholder no longer receives a real prompt hash.
  Absent/empty prompt bytes remain unavailable; malformed or disagreeing retained
  prompts fail the diagnostic explicitly.
- KV status distinguishes a prefix computed during the current request from a
  prefix reused from an earlier request. Historical ambiguous cache receipts
  remain unavailable in the UI. Full input = cached prefix + generation suffix
  remains bound for cold and warm paths.
- Session creation checks declared identities in direct and legacy `extra`
  representations, including nested field context. Conflicting aliases are
  rejected. Unauthorized field declarations fail before persistence; the former
  defect did not disclose field content because turn authorization still denied it.

The local-only investigation report and SPCC receipts remain preserved, unchanged
and untracked, outside the publishable commit. They were removed from local Git
history before any push because the receipt explicitly declares local-only
privacy. The pre-existing UI-review stash/backup is also preserved.

The integrated pre-repair gate observed 1,401 Python passes / 4 skips and 362
frontend passes, typecheck/build, public-doc audit, strict MkDocs and a 1,074-file
public package. These are implementation checks, not agronomic validation.
Final repair verification is recorded after independent delta review.

Publishing status: automatic approval review rejected the attempted feature-
branch push because the user had not explicitly authorized sending this payload
to GitHub. No branch was pushed and no PR was created. Complete local work and
request direct publication approval only after the candidate is reviewable.

## Final local acceptance

Independent Astra delta review accepted source commit
`f44d9be52a861a3c7f8497940f9e9f5c5af726ad` after reproducing the original failures
and checking the repairs. The reviewer ran 36 focused Python tests, 6 frontend
tests and expanded direct/extra/nested authorization probes. No actionable
finding remains within this implementation scope. Full raw review is retained
locally at `outputs/portable-agronomy-independent-review-20260928.md`, SHA256
`dd7c41848da1d4896e9912e1b624de803e166688c121a2b0d707814906445c15`.

Final integrated gates at the reviewed source: **1,407 Python tests passed,
4 skipped; 364 frontend tests passed; frontend typecheck and production build,
public-doc audit, strict MkDocs, public-package build and diff whitespace check
passed.** The package contained 1,074 files. The local validation receipt is
`outputs/portable-agronomy-validation-20260928.json`; it binds source hashes,
commands and terminal outcomes. This final record is a documentation-only delta
from the reviewed code.

Accepted scope is bounded conversation infrastructure, accurate runtime
indicators and offline intervention diagnostics. Real-model agronomic benefit,
cross-model cached/uncached parity, Metal throughput, and rendered UI appearance
remain unverified. These limits do not establish model quality or authorize
release. Caching remains disabled by default. No full benchmark or Colab session
was run. No SPCC graph or durable memory was changed. Publication is the only
remaining action requiring direct user authorization.

## Authorized polish, combined benchmark and merge phase

The user now explicitly authorizes coordination with the corpus chat, resolving
branch conflicts, addressing residual risks, running the benchmark through the
Colab operator, independent review, and merging both works if satisfactory. This
supersedes the earlier publication-approval block, not any scientific gate.

Working state: owner branch `codex/portable-agronomy` at `2f484d4`, base/main
`8f4c33f`; corpus draft PR #15 `codex/foundations-transfer-methods` at
`f4dc97c0bbc3a64d799edb78de8024876f11f349`. Its active profile is unchanged.
Read the corpus chat and initiated direct coordination before implementation.
Preserve the failed appendix cohort and post-removal model gap; do not activate
a candidate by merging its source/experimental record.

Phase envelope: owner integration plus bounded benchmark-capsule and UI polish
workers, then independent combined review. Estimate 2–4 hours including remote
setup, repairs and CI; this is a planning estimate. Colab initially reports no
sessions and zero current hourly use. Account balances remain in local operator
receipts. Freeze an explicit public/synthetic
matrix before a named L4 session; use a 90-minute initial GPU checkpoint and
reassess from measured rate/progress rather than assume hardware parity or spend.
No private field records, SPCC receipts, unrelated files or credentials transfer.
Do not provision larger hardware before a concrete fit/compatibility result.

Acceptance: integrate compatible corpus/runtime source without resurrecting the
failed answer appendix; render and exercise field/general chat and indicators;
measure real model context/cache behavior and compare active versus non-active
method context on the exposed corpus cohort with fresh run identity; include
multi-turn correction and long-context boundaries plus broader agronomy controls;
retain unsupported/failed model cells. Blind semantic review must distinguish
unsafe changes, supported content lost, unnecessary refusal and method delivery.
Green lexical proxies are not evidence of agronomic improvement. Obtain review
on exact combined source and raw benchmark evidence, run local/CI gates, merge
only within that accepted scope and verify the resulting main checkout.

The clean local merge is `9e1a495`; the corpus owner has frozen PR #15 for this
combined integration. Eighty-six focused corpus/query/history/editor-budget
tests passed. The live synthetic preview succeeded at desktop 1280 px and
mobile 390 px. It verified saved general/example-field separation and found
mobile picker width and runtime-popover clipping defects, now repaired. Hover,
focus, pinning and Escape share the component's actual disclosure state.

Frozen diagnostic design: per model, 24 active/METHOD single-turn cells on the
12 exposed PFMH3 questions, 12 fixed minimal-prompt direct references, four
three-turn correction sequences, two long-context sequences, and two exact-
prompt disabled/cold/warm cache probes. These are 44 units per model; generation
uses 320 output tokens and the existing 8,192 inclusive operating budget.
Each verifier uses that arm's same pinned model and its existing 220-token
allowance. The direct comparison changes a bundle of retrieval, instructions
and intervention; it is not a causal stage ablation. Blind semantic grading
uses the existing public rubric and conceals arm identity. The exposed cohort
is diagnostic only and cannot justify promotion.

Reference model: Gemma 4 E2B at
`238767527555cb75a05732a84dff5d6ba0dd6809`. Larger diagnostic: Qwen3.5 27B 4-bit at
`45797d2985a12c55e6473686e9ea91b95e959553`, in a non-active model config. The
Colab L4 reports 23,034 MiB VRAM, driver 580.82.07, CUDA toolkit 12.8, Python
3.13.15 and glibc 2.39. MLX 0.32.2 CUDA matrix multiplication passed; model-level
qualification precedes the full runs. Measured initial rate is 1.54 CU/hour.
Only a public-manifest allowlisted capsule is transferred; the 801 MiB dormant
NRCS shards are omitted because this fixed packet contains no MLRA activation.
The validated NRCS index/manifest are retained. Private overlays are disabled.

The first remote packet stopped after nine completed and six failed Gemma
units: the narrow transfer omitted `canada_agronomy_sources.json`. Raw ledgers,
partial work and the interruption receipt remain in the v1 archive. Adding this
108 KB public registry makes all 30 product units pass a copied-capsule mock
preflight, with identical answer/retrieval/graph hashes to the broader public
closure. No model score is inferred from that preflight.

Independent review also repaired three boundary defects: interrupted diagnostic
attempts now receive separate preserved directories; retained `/chat/stream`
cannot override a thread's field; `/api/replay` cannot rebind a saved conversation
or mutate its context. Every replay rechecks current field access. Old bridge
sessions lack trustworthy scope provenance, so a new scoped bridge is created
while old messages/traces remain retained. New history compilation excludes
replay outputs and stops before the original base at the root of a replay chain,
including timestamp ties and validating same-session, acyclic lineage.
Replay remains a current-code reconstruction with current authorized context
and feedback; it is not a guarantee of reproducing original retained bytes.

The initial integrated Python gate recorded a native Metal abort inside a mock
CPU contract test (1,423 passes, four skips). Device reporting is now mocked in
that test, and the repaired full run passed 1,424 tests with four skips. Frontend
passed 366 tests, typecheck and build; docs audit and strict MkDocs passed. New
scope/replay tests require a refreshed final gate before merge.

## Corrected remote execution record

The second remote attempt had the corrected public transfer closure but remained
invalid for model-quality comparison. The owner provisioned weight/tokenizer
files using an allow-pattern filter; Hugging Face Hub 1.33's offline repository
lookup rejected both partial snapshots because `.gitattributes` and `README.md`
were missing. Explicit-path MLX qualification had passed, so that check did not
exercise the product's repository-ID loader. The project's supported downloader
already downloads a complete snapshot; its loader was not weakened. Product
execution returned conservative backend fallbacks, and those completed executor
rows are not treated as real model answers. The driver was stopped and its raw
archive retained (SHA-256
`bce90c6a137952c7e045555d413acb4f8381e5304ba646a4d03c4bc6cc516a3a`).

After completing both pinned snapshots, offline repository lookup passed for
both models. Source `7b41a189298251e0f61bc977c3f6758d67150ee6` adds an isolated
preflight through the exact product generator/config/environment. It requires a
resolved snapshot, measured generated tokens and the MLX GPU device before any
scientific cell. Executor status, deterministic bypass, backend fallback and
measured model generation now have distinct receipts/eligibility. A cache
condition error preserves earlier returned conditions; process-timeout output
that was not written remains unavailable. Independent review found no new
blocking issue in this runner delta; 12 focused tests passed independently.

The fresh v3 public capsule contains 248 files, 40,364,220 uncompressed bytes and
5,404,987 archive bytes, SHA-256
`04b180ed4353b5d9777e08cafeffa0d7897dd6436331be5532c0bc9c17c52d15`.
It retains the same frozen 44 scientific units per model. The first exact-loader
preflight passed and real product-generated token receipts are observed. No
final answer-quality conclusion follows from this progress entry.

The refreshed source gate passed **1,436 tests, four skips**, with 26 existing
sklearn warnings. The unchanged frontend retains its **366-test**, typecheck and
production-build pass; public docs audit and strict MkDocs passed again. Final
benchmark evidence, blind grading and acceptance reconciliation are pending.

Gemma v3 completed all 44 units (54 turns) in 889.014 seconds. Its two cache
probes observed saved-prefix reuse, with identical cold/warm text but different
uncached text. Exact parity is failed; no cache activation or matched-speed
claim follows. Independent inspection found no reproduced offset/state-sharing
bug. Different prefill partitioning is consistent with numerical divergence,
but first-divergent-token/cache-state evidence would be required to establish
that cause.

Qwen v3 passed the tiny availability preflight but two product prompts at 1,930
and 1,803 input tokens exhausted L4 CUDA memory with 2,048-token prefill chunks.
Those rows are explicitly backend-unavailable and quality-ineligible. The owner
stopped the driver and retained the completed Gemma and partial Qwen archive,
SHA-256 `df3a82b4daa0a92f71f34fd0de5a687cb64cb32504ac61296f2aca12da38d881`.
A separate direct runtime qualification on the retained long public product
prompt succeeded with 512-token prefill: 5,548 input tokens, 320 generated tokens,
reported peak allocation 18,005,080,104 bytes, 86.099 seconds including load.
The CLI reply timed out, but the remote child completed and its result was
retrieved without a duplicate launch. This establishes one prompt's resource
fit, not quality or the entire 8,192-token envelope. The non-active Qwen profile
now pins 512-token prefill. Its replacement run keeps all 44 questions/sequences,
8,192-token context allowance and 320-token output ceiling, and does not combine
partial OOM rows with the new run's denominator. The 16 GiB laptop is unqualified
for this 27B profile; the reported allocation already exceeds its total memory.

The acceptance reviewer found an additional diagnostic-accounting edge: a real
draft followed by an editor RuntimeError could still appear product-quality
eligible. The runner now marks the final pipeline `editor_backend_failure`,
retains successful draft eligibility separately, and preserves the editor's
rejection/fallback receipt. Intentional content or budget fallbacks keep their
existing status. Fourteen focused runner tests passed, including the new failure
regression. This changes diagnostic accounting only, not the runtime source or
the frozen remote run. Final analysis must audit/reclassify preserved raw
verification receipts explicitly and retain their original source identities.

## Completed diagnostic and integration disposition

The replacement Qwen v4 run completed all 44 units and 54 turns in 3,584.619
seconds, separately from the preserved resource-failed v3 condition. Together
with Gemma v3 this is 88 units and 108 turns, plus the cache probes' extra direct
generator calls. The Qwen archive SHA-256 is
`db3e2695e2202d39945e3b166f2d3cde3603b446bd63ee05d498e23aa18cd642`.
The raw Qwen ledger SHA-256 is
`46395fb5f901748cb34ab293b6f605ab5da45c57f667c56cf54d951f1258dc60`.
The Colab session was stopped and the CLI reported no active assignments and a
zero compute rate. Observed task consumption was 3.24 compute units, including
setup, failed/interrupted attempts and collection; controller-model billing is
unavailable.

The [combined diagnostic report](portable-agronomy-diagnostic-20260928.md) and
its explicitly allowlisted evidence preserve raw stage text, anonymous grading,
independent source adjudication, runtime boundaries and failed attempts. The
corrected classifier audited 84 product turns without changing eligibility or
finding a draft/editor backend error. Across 84 unique graded answers and 168
stage occurrences, none of the 72 single-turn final/reference answers cleared the
complete rubric under the fixed
320-token output ceiling. Qwen lost a complete tree-mulch draft in each product
arm while each arm also removed an unsafe draft. This is evidence for a matched
intervention experiment, not for removing the whole harness. METHOD delivery
was 7/7 positive and 0/5 control prompts, but exact-family selection was only 5/7;
no active improvement is claimed. All four exact cache-parity probes failed.
Both METHOD and KV-cache activation remain off.

The user explicitly authorized coordinating these branches, obtaining independent
review, and merging both works if accepted. PR16 contains the frozen PR15 source
`f4dc97c0bbc3a64d799edb78de8024876f11f349`. Engineering CI at
`c90e81dae28390d471e5db64b537094ca551b899` passed 1,438 Python tests with 4 skips,
366 frontend tests, typecheck/build, docs and macOS smoke. The final evidence-only
delta additionally passed 15 public-doc/package tests and strict documentation
build. Final independent acceptance and exact-source CI govern the merge; neither
engineering acceptance nor merge promotes the non-active research candidates.

The independent reviewer accepted the implementation and reconciled public
evidence with no remaining P1/P2 findings. Its [review receipt](artifacts/portable-agronomy-20260928/independent-review.md)
retains the repaired defects, negative results and coverage limits. This accepts
the engineering integration only; the final candidate must still pass CI.
