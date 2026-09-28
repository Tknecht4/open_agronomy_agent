# Independent repair acceptance review

Current technical verdict: **accept** for the final source candidate
`fefcdaf935df30efbdf515aaa6be5d1130a93b8a4d539d683a17dbb9f19a4a07`.
The two earlier repair verdicts and their negative evidence are retained below.
Initial candidate digest: `ed4390afe971e840702268879f6dbada5e52bc983fb16f9365947286d1622340`.
Base: `8380b8bef305f5e5d2594c348b4f2619ce557551`.
Review date: 2026-09-28. Reviewer task: `/root/repair_acceptance`.
The runtime and test hashes in `review-candidate.json` were independently
recomputed and all matched before the owner began corrections. The manifest
file SHA-256 was `3a7cfcebc28f9987549624dfb01a39c01e0021f8ee6d30f54599bfa51b0bf9c4`.

## Independent expectations

Derived from the supplied user contract, repository instructions, candidate
diff, and source before reading the owner's checkpoint conclusions:

| Required property | Observable violation | Controlling boundary and expected evidence |
| --- | --- | --- |
| Exact numeric screening | A partial number, changed unit/sign, or unsupported new quantity passes review | Quantity lexer through `assess_claim_risk` and selective `verify_answer`; negative and preserving contrasts |
| Narrow arithmetic support | Ambiguous premises acquire a derived value, or a false total is accepted because an operand appears in the source | Container-premise admission and result identity, including repeated and conflicting premises |
| Diagnostic polarity | Uncertain/negated source text licenses an affirmative exclusion; name overlap licenses positive certainty | Diagnostic assessment, source-versus-question distinction, complete verification decision |
| Completion and audit honesty | A terminal arithmetic result is treated as a dangling item; unrelated edited sentences inherit a defect or source proof | Completion matcher, replacement audit and ledger serialization, downstream consumers |
| Requested METHOD scope | Negated/background text selects a card, or its scope consumes an explicitly requested neighboring task | Task frame, obligation projection, query fit, unchanged applicability and authority gates |
| Bounded model ownership | An old generator retains replaced weights, an active lease is evicted, or failure leaves a lease/reference behind | Public warmup/count/generate paths, global executor and locks, target/draft identity, weak references, failure/concurrency tests |
| Safe integration checkpoint | Active configuration or frozen evidence changes; required integration checks fail | Exact manifests, runtime paths, package checks and owner's source-bound full-suite/remote/CI evidence |

## Initial material findings

1. **Diagnostic exemption admits uncertain and absent evidence.** For answer
   `The diagnosis is not gray leaf spot.`, both `There is no evidence that gray
   leaf spot was ruled out by the laboratory.` and `Whether gray leaf spot was
   ruled out by the laboratory is unknown.` yield no risk reasons. Baseline
   `8380b8b` flags `unsupported_diagnostic_certainty`; the candidate's selective
   verifier preserves the unsupported answer without review. A list of absent
   negator tokens is insufficient evidence of affirmative exclusion.
2. **Equal count values collapse distinct container groups.** For `What is the
   total mass of 12 bags of barley and 12 bags of wheat? Each bag weighs 25 kg.`,
   the candidate derives and preserves `The total mass is 300 kg.` Baseline
   flags that unsupported number. A set of magnitudes loses the distinction
   between two groups and a repeated statement of the same premise.
3. **Leading-dot decimals evade the new lexer entirely.** `.5 kg/ha` and
   `-.5 cm` produce no quantity matches, no risk reason, and unchanged selective
   verifier output with no supporting quantity. Both were flagged by baseline.
4. **Explicit unit screening has an uncovered inherited hole.** With evidence
   `Mass: 20 kg.`, answers containing `20 hectares`, `20 gallons`, or
   `20 millilitres` are parsed as bare `20` and pass. The hectares case is
   also accepted by baseline, so this is a contract gap rather than an
   introduced regression.
5. **METHOD directive scope crosses an explicit new operation.** `Avoid
   mentioning liquidity and explain cash flow.` selects nothing; `Ignore the
   cash plan and explain working capital.` selects both families. `Explain why
   cash flow is not liquidity.` drops the comparison's liquidity target.
   Candidate inactivity limits current product exposure, but these are direct
   controls for the parser change's scope claim.

Raw reproduction rows are retained locally in
`outputs/residual-repair-20260928/reviewer-initial-probes.json` and
`outputs/residual-repair-20260928/reviewer-baseline-comparison.json`.
The latter executes the baseline verifier loaded from `git show 8380b8b:src/agronomy_agent/answer_verifier.py`
and the candidate against identical inputs. It also exercises the active
`risk_conditioned_selective_v3` selection policy, not only the quantity helper.

## Executed evidence and limits

Initial focused command:

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q -o addopts='' tests/test_mlx_model_residency.py tests/test_method_task_frame.py tests/test_verifier_quantity_contract.py
```

Observed: **61 passed in 0.42 seconds**. This does not override the independent
negative findings above.

Source tracing confirmed public model operations use the single MLX executor,
release managed references in `finally`, invalidate KV namespaces on pair change,
and refuse replacement while a lease remains. Product draft/editor generators
are separate objects; response metadata is copied before editor invocation.
The lifecycle tests include weak-reference eviction, draft-load failure,
tokenizer failure, generation failure, same-target/different-revision pairs,
draft identity and concurrent public requests. This supports bounded Python
ownership only; allocator peaks, cancellation, hostile thread-name spoofing,
and device fit are not qualified by these model-free tests.

The v2 audit distinguishes lexical localization from semantic proof; no strict
v1 consumer of the emitted replacement audit was found. The synthetic benchmark
executor's own v1 feature declarations are a separate synthetic contract, not
evidence of a live v2 consumer. Whole-sentence change detection remains lexical.

Both METHOD obligation generation and card fit use `requested_methods`.
Active `configs/rag.yaml` has no method release, `configs/model.yaml` keeps
prompt caching disabled, and the runtime profile registry still selects only
the active RAG profile. Existing method authority and country checks remain in
the execution path. No agronomic efficacy, source authority promotion, cache
qualification, or Metal byte-fit claim follows from this review.

Changed | Review artifact and local probe outputs only.
Verified | Initial hash binding, 61 focused tests, source tracing and independently reproduced failures.
Residual Risk | Initial candidate is unaccepted; repair delta and integrated evidence remain pending.
Memory Delta | None.

## Repair delta review

First corrected candidate:
`6de0dc02b02c374f5a062811aaad957b8edbe97a6f27d538ed30589471fca806`.
All manifest source hashes matched. The original counterexamples were repaired:
diagnostic support now requires an affirmative full clause and rejects repeated
condition/correction evidence; arithmetic operands must be bound together in an
explicit question phrase; leading-dot decimals and the tested unit suffixes are
screened; METHOD imperative boundaries and predicate negation are distinguished.

The reviewer ran 102 focused tests successfully in 3.68 seconds. A further
material issue was found in the newly expanded spelled-quantity path: raw source
substring lookup accepted `twenty kg` from `one hundred and twenty kg` and from
`minus twenty kg`, and accepted `twenty kg/ha` from `twenty kg`. This is quantity
identity, not a request for digit/spelled equivalence. That candidate therefore
also required repair. The raw negative rows remain in
`outputs/residual-repair-20260928/reviewer-spelled-probes.json`.

Second corrected candidate:
`fefcdaf935df30efbdf515aaa6be5d1130a93b8a4d539d683a17dbb9f19a4a07`.
Its helper compares whole matched spelled-quantity phrases and includes rate
suffixes; other named-value checks retain their existing default behavior.
The reviewer independently verified every listed source hash and executed the
reproducible 47-case contrast script:

```sh
PYTHONPATH=src .venv/bin/python outputs/residual-repair-20260928/reviewer-delta-probe.py
```

Observed: **47/47 passed**. The source-bound result is
`outputs/residual-repair-20260928/reviewer-delta-fefcdaf9.json`.
It covers original failures and preserving controls for quantity identities,
signs, leading-dot decimals, units, ambiguous arithmetic premises, diagnostic
uncertainty and contradiction, spelled quantities, METHOD scope, and numeric
completion. These are exposed engineering contrasts, not held-out efficacy.

The final focused command covered `test_verifier_quantity_contract.py`,
`test_method_task_frame.py`, `test_method_transfer_candidate.py`,
`test_mlx_model_residency.py`, `test_mlx_runtime_contract.py`, and
`test_risk_conditioned_selective_v3.py` with `-o addopts=''`.
Observed: **107 passed in 2.92 seconds**.

## Final reconciliation and verdict

**Accept the bounded engineering repair candidate**
`fefcdaf935df30efbdf515aaa6be5d1130a93b8a4d539d683a17dbb9f19a4a07`.
No unresolved material defect was found in the inspected repair contract after
the two correction passes. This accepts source for integration; it does not
declare the subsequent public-package freeze, remote CI, or main merge complete.
The owner must finish and reconcile those gates before reporting the overall
user task complete. A changed runtime/test digest reopens affected review.

The owner supplied `outputs/residual-repair-20260928/integrated-checks.json`,
binding the full suite to this exact candidate before and after execution:
**1,527 passed, 4 skipped, 26 warnings in 99.93 seconds**. The reviewer checked
the recorded log SHA-256 against `full-python-accepted-source.log` and rechecked
every candidate source hash. The earlier failed public-package test remains in
the initial full-suite log; the corrected package tests passed 5/5. Frontend
366 tests, typecheck/build, public-doc audit and strict MkDocs results were
reported by the owner for unchanged frontend inputs. The reviewer also read the
successful public-package log: 1,209 files, receipt
`4af0f5054fde79afad5a8e346174e8953a730d2780f94e2a753b0b9eac4257f3`.
Packaging must be refreshed after the review/report metadata freeze; CI and
merge verification remain owner integration gates.

The reviewer inspected the retained real-backend answers and lifecycle records
in `gpu-summary.json` / `remote-results.zip`, verified the bundle hash, and
verified the second capsule hash against its run. Both L4 runs completed 24
baseline/candidate cells without backend errors. Each Gemma/Qwen/Gemma sequence
performed three loads, released generator references after counting and
generation, and ended each operation with zero leases. The first run's L02
spelled-number bypass is preserved. The second run repaired wrong mass/total
drafts, preserved the supported total, and used fallback for L02 after detecting
the unsupported spelled value. Diagnosis and regulated controls still held;
broader route rules also retained fallback on a supported negative diagnosis.

The second remote capsule `c7e52cdcbc7f99ba846b38b0352c280704d15bf731eff410e82c6b93ff5ff610`
contains the preceding verifier revision, not the final whole-phrase helper.
The reviewer independently reran `replay_final_verifier.py` with reviewer-owned
output paths: **12/12 candidate records exactly matched retained records**, and
all computed editor-message bytes matched between the prior and final verifier.
All other runtime source files matched the real-run capsule. The replay result
exactly equals the public `final-decision-replay.json`; its final verifier hash
is `f33ec835e1b184428cde0a45934e0207130d5a515fcd40a1d6a55fcbd60d4304`.
This is adequate for the small deterministic helper delta together with the
new adversarial tests. It reuses captured editor output and recorded token
counts; it is explicitly **not fresh generation or tokenizer measurement**.
The independent hash/replay reconciliation is retained in
`outputs/residual-repair-20260928/reviewer-final-reconciliation.json`.
A first wrapper invocation completed replay but failed while printing a shadowed
variable; the isolated-namespace rerun passed and retains that wrapper failure.

Coverage limits remain material to future claims, but do not defeat this safe
checkpoint: quantity screening is not full semantic entailment, arbitrary
arithmetic, cross-entity reasoning, or digit/spelled-number equivalence; METHOD
parsing is not broad language or agronomic qualification and its corpus remains
inactive; lexical audit attribution is not proof that an edited sentence was
false; one cached pair bounds Python ownership rather than GPU peak bytes.
The real switch test has no speculative draft model, while model-free tests
cover paired target/draft identity and failure. Cancellation and Metal behavior
were not newly qualified. Those features were not activated or claimed by this
repair. Prompt caching remains disabled, model/source profiles remain unchanged,
and the existing unqualified-model and METHOD evidence boundaries remain intact.

Changed | Independent review and reviewer-owned local evidence only.
Verified | Final digest; 107 focused tests; 47 contrasts; full-suite log binding;
remote bundle/capsule hashes; independently reproduced 12-cell final replay.
Residual Risk | Bounded screening and backend limits above; final package, CI,
and main-merge verification remain owner work.
Memory Delta | None.
