# Release evaluation foundation

Status: final executable source `afcc5af` completed a retained, verified Gemma GPU engineering baseline; semantic review pending; PR CI, merge and post-merge verification pending. Base: `d9bb2547d5b3b2bcf246ebeae88eb6270b4c8bba`.

## Working state

Goal: one expandable, fail-closed release evaluation system combining instrument,
domain, harness, retrieval, conversation/product, and resource evidence. Establish
a retained Gemma 4 E2B GPU baseline through the Colab CLI before PR/merge.
Existing exposed cohorts and historical scores stay immutable; unknown semantic
judgments stay unknown. Evaluation answers never enter runtime context/training.
Primary checkout research artifacts are outside this isolated worktree.

## Definition of done and acceptance map

| Obligation | Required evidence |
|---|---|
| Expandable suites | Versioned registry, validated case schemas, explicit scenario/family IDs and exposure/review roles |
| Trustworthy instruments | Unit/value/negation/empty-contract controls; positive retrieval and negative controls use separate denominators |
| Product fidelity | Real `execute_agent_request` execution, persisted turns, ordered stage receipts, exact prompt/source/model/runtime identities |
| Harness coverage | Deterministic tool binding, field/history corrections, authority/missing evidence, retrieval controls, backend faults and recovery |
| Honest analysis | Required/optional usefulness and errors separate; missing labels/failures retained; paired comparisons and resource compatibility gates |
| Release operation | Single CLI, CI deterministic profile, baseline/release profiles, reference comparison, immutable/resumable receipts and nonzero blocking exits |
| Validation | Focused and full Python/frontend/docs/public-package checks plus independent exact-source review |
| Baseline and integration | Bounded Colab Gemma run on final executable candidate, verified raw retention, public-safe baseline, PR/CI/merge/post-merge verification |

## Ownership and resources

Owner: registry, runner, analysis/comparison gates, integration and GPU operations.
Bounded specialists: scorer/retrieval repairs; product executor and synthetic harness
cases. Each has disjoint file ownership. Fresh Astra xhigh review at acceptance.
Estimate: several hours including owner, specialists, repairs and GPU execution;
provider token costs unavailable. No optional model search or remote paid judge.
GPU choice starts at L4; provisioning waits until implementation is frozen.
GPU envelope is finalized after live usage/capacity and a short throughput pilot;
checkpoint before extending a job, hard process timeout, retain all failed cells,
download/hash evidence, stop only task-owned sessions.

First checkpoint: integrated deterministic runner and evaluator controls. Second:
full local validation and independent review. Third: final-source Gemma baseline.
On overrun, stop optional expansion and pursue the smallest remaining required
check without dropping any acceptance obligation. The user's PR/merge instruction
authorizes those steps after evidence passes; it does not authorize domain claims
or activation of experimental profiles.

Memory delta: none.

## Deterministic integration checkpoint

All six components and all 36 scenarios completed with no failed mechanical
checks in the first integration run. Its source-drift gate correctly blocked
acceptance because implementation was still changing. Frontend typecheck,
401 tests, and production build passed under Node 24.19.0. The initial full
Python run observed 1971 passed, 33 skipped, seven failures and four setup errors:
nine socket-proxy checks were denied loopback binding by the filesystem/network
sandbox; one public-package check found a forbidden literal in a new test;
one offline-analysis fixture wrongly expected an all-mock baseline to pass.
The literal and fixture were repaired. Final full validation runs with local
socket access, preserving the original failures as evidence. At that checkpoint no model run had
started. Reviewer and final GPU baseline remained required.

Optional arms now have explicit arm-specific mechanical assertions; production
thresholds apply to production responses, while independently scored diagnostic
responses and failed attempts remain retained. Optional source-bound stage
reviews measure verifier gains and introduced errors without treating unknown
labels as passes. Inherited agronomy environment overrides are discarded for
child execution, and native model loading is offline after explicit provisioning.

## Independent review repair checkpoint

The first exact-source Astra xhigh review requested five repairs. Owned process
groups now receive a bounded termination and kill sweep even after their leader
exits. Review bytes are frozen once before execution. Paired completion checks
operate per case and family so an aggregate cannot hide a local regression.
Retained reviewed analyses can serve as comparison references and chain without
mutating raw runs. Ten backend and storage warm cells have separate environment,
sample coverage and latency gates. Scorer implementation hashes are part of
comparison compatibility.

The initial frozen candidate passed 1994 Python tests with 33 skips under local
socket access. Focused repair checks passed, including process cleanup controls,
and final full validation is required on the repaired candidate. Colab allocated
a task-owned L4 (23 GB, driver 580.82.07, CUDA 12.8). The first connection attempt
failed before setup; reconnecting produced a retained successful hardware probe.
No Gemma answers have been generated at this checkpoint.

## Final executable freeze and baseline checkpoint

Executable source is frozen at `5cba71b`. Final local validation recorded 2032
Python tests passed and 33 skipped, plus frontend typecheck, 401 tests passed and
production build. The immutable deterministic CI run completed all six required
components and 36 scenario cells, including seven numeric observations at 100%
accuracy: `engineering_pass`, with semantic `review_pending`. This is mock
engineering evidence and does not establish Gemma or agronomic competence.

The independent Astra xhigh acceptance recorded 253 focused tests passed and
50 native cancellation checks passed, with disposition
`accepted_code_ready_for_baseline`. It accepted the repaired case/family
completion gates, dynamic scorer identity, frozen review bytes, chained retained
analyses and ten independently gated warm backend/storage latency cells. The
original raw directory remains a required location-bound source of any derived
analysis; numeric rescoring belongs to a new instrument and compatible baseline.

The task-owned L4 passed its actual MLX runtime probe. The pinned model snapshot
was explicitly provisioned (3.583 GB), with SHA-bound weights. A 641-file source
capsule was transferred and hash-verified after retaining a chunked-transfer
server error; its SHA-256 is
`8b0add0ed125af153017c31bcf67f470ade714cfdc50744ae086bcab156a476b`.
The executable source core SHA-256 remains
`3f127fcf645a0ba9498c3a9f9ef1297062bd02f8c05be42dbee41d57d374bdc1`,
verified locally after these documentation-only edits. Four real product-path
pilot cells are underway before the planned complete 584-cell baseline. The
pilot is a throughput and execution check, not a completed baseline.

Full GPU results and private raw retention verification, a public-safe baseline
record, PR CI, merge and post-merge verification remain pending. No release-pass,
domain competence, field efficacy or completed-integration claim is made at this
checkpoint. These checkpoint counts and GPU status are the integration owner's
reported observations; the operator guide documents the checked-in contracts.

Memory delta: none.

## Runtime input closure repair

The first full GPU attempt passed all six components, then repeatedly failed
Canadian case execution because its narrow transfer omitted the Canadian source
registry consumed by provincial coverage checks. The owner interrupted this
attempt, retaining failed and interrupted cells rather than retrying in place.
This was a transfer/input-binding defect. The registry is now a required hashed
controlled input, so a missing transferred copy blocks plan construction before
model execution. A regression reproduces the missing-file boundary and verifies
the isolated positive consumer after copying the bound bytes.

A separate isolated audit added only that registry to the same source capsule:
292 mock product-seam cases completed with zero failed mechanical checks in
38.46 seconds, without importing MLX. The mock backend closure check completed
all ten warm cells with one sample each; this is not performance qualification.
Public adapters are disabled throughout the current cohort, and optional spatial
databases and geographic caches are absent. Future enabled adapters or installed
spatial cases require their own explicit input closure and measurement policy.
A new frozen source and fresh Gemma baseline directory are required.


## Verified final-source native baseline

The fresh final executable source is
`afcc5af147618fb721b68317d9a2d4020a93c1a2`, core SHA-256
`fab64688605f95371165f60ba31196be4fcdd020147d9a9cff07ade0e815b714`.
Its retained Gemma run completed 584/584 observations across two 292-case
trials, with zero failed observations, missing cells or failed checks. All six
components passed. Actual native evidence comprises 366 verified generated MLX
turns among 592 observed MLX turns, across 360 observations with generation.
All 46 numeric observations passed; all ten warm backend/storage cells retained
20 samples. Semantic status remains `review_pending` for 506 review-required
observations, and external claims remain ineligible.

Local harvest verified the 295,382,726-byte private archive and all 3,374 files,
run retention, matrix and answer-stage hashes. The interrupted predecessor's
38 observations, including 29 failures, remain separately retained and verified.
Offline retained self-comparison passed without inference; it validates the
comparison plumbing, not a candidate improvement. Colab session termination and
no-active-session/assignment/usage state were observed. The task-window account
balance delta was 6.45 compute units; it is account aggregate usage, not an
independent task-cost meter.

The [final baseline record](release-evaluation-gemma4-baseline-20260929.md) and
[public aggregate receipt](artifacts/release-evaluation-gemma4-baseline-20260929.json)
contain the identities, measurements, archive bindings and limitations. The
historical checkpoint source identities above remain unchanged. PR CI, merge
and post-merge verification are still pending; no domain or field-efficacy claim
is established by this baseline.
