# Release evaluation foundation

Status: implementation frozen for final validation and GPU baseline. Base: `d9bb2547d5b3b2bcf246ebeae88eb6270b4c8bba`.

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
socket access, preserving the original failures as evidence. No model run has
started. Reviewer and final GPU baseline remain required.

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
