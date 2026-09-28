# Independent acceptance review: residual-risk investigation

Verdict: **accept**, scoped to the bounded investigation and its stated negative findings. This is not approval of active METHOD retrieval, prompt caching, a verifier repair, model efficacy, laptop qualification, release, or publication.

Reviewed on 2026-09-28 in the independent `residual_acceptance_review` task. Reference HEAD: `3ff64813ce14833f3c819044b96ebda738a60cbe`, branch `codex/residual-risk-investigation`. The reviewed candidate is `review-candidate.json`, SHA-256 `5bb90c6791fc99ee97358fe1cff81f59df25a2c5abf9282991e44eaa43bee3c3`. All **57** listed files matched their byte counts and SHA-256 digests. Git showed only the declared tracked public/container manifest changes; runtime source and active configuration were unchanged. Unrelated private untracked research was left untouched.

This review follows the orchestrator acceptance procedure. I derived the coverage expectations below from the assigned investigation contract, read the raw fixtures, probe implementations, runtime consumers and receipts first, and then reconciled the owner report and analysis notes. Model/run identity is supplied by the task runtime; this document is not independent authentication of that identity.

## Independent coverage map and reconciliation

| Obligation | Independent acceptance expectation | Observed evidence and limit |
|---|---|---|
| Cache divergence | Identify exact input/state/partition boundaries, distinguish common token history from diverged history, retain EOS and instrumentation limits, avoid attributing independent prefix variation to LRU | Four seven-arm receipts and raw first-divergence arrays support the report. The same-origin follow-up exposes repeat variation independent of LRU lookup. Numerical correctness and a specific kernel cause remain unresolved. |
| Method-family selection | Evaluate requested operation separately from incidental/negated vocabulary; trace an incorrect selection into actual consumer contracts | Independently replayed 47 selector cases and six `build_context` checks. Wrong-family propagation to obligations/cards and `ADEQUATE` method coverage is reproduced. Scope remains authored development evidence, not population accuracy or answer benefit. |
| Verifier removal of explanations | Separate local assessment defects, historical intervention observations, missing historical evidence and semantic quality; preserve safety controls | Independently replayed all 12 local assessments and the retained Qwen reconstruction. Substring, arithmetic, terminal-number and negation defects are supported. Exact historical evidence/editor replay and successful claim-local repair are not claimed. |
| Output-cap confounding | Match prompt/backend/settings, confirm truncation versus EOS, compare baseline historical text and continuation, avoid treating completion as quality | All four 320-token baselines exactly match retained texts. Twelve recorded outputs retain identical messages within each prompt and form the reported prefix continuations. Reconstructed tree-draft assessments reproduce; no new editor or answer-quality result is inferred. |
| 27B laptop resources | Distinguish CUDA allocation, disk size, physical memory, model lifecycle and Metal qualification | Qwen weight-file sum and reported allocation values match receipts; model cache source supports retention without automatic eviction. No laptop inference, OOM, latency or universal 27B infeasibility is claimed. |
| Missing live UI observation | Report exactly which synthetic live transitions were observed; keep missing pointer transitions explicit | Desktop image visibly supports synthetic saved-chat/context details. The UI receipt records focus, Escape, pin/blur, reset and measured dimensions, while explicitly excluding independently observed hover/exit. Screenshots do not independently establish transition history; the review did not reopen the browser. |
| Provenance and non-activation | Preserve raw evidence and failed attempts; bind source and avoid changing runtime/corpus or overwriting historical grades | Candidate hashes, source bindings, ZIP consistency and manifest diff support this scope. Final public-package inventory after review documents is still an owner integration step. |

## Executed independent checks

- Verified the candidate manifest digest and all 57 file byte counts/hashes; inspected branch, HEAD, dirty state and both tracked diffs.
- Parsed all 15 investigation Python scripts without executing GPU code.
- Replayed all 47 `requested_methods` inputs against current unchanged source: 19 exact sets, 24 true-positive memberships, 24 false-positive memberships, 8 false-negative memberships; precision 0.50, recall 0.75.
- Replayed all 12 `assess_claim_risk` fixtures: exact serialized assessments match; 6 authored-label agreements, 3 false negatives and 3 false positives.
- Replayed all six method consumer checks: family sets, admitted card IDs, obligations and method-coverage rows match the retained receipt. Verified current source hashes for the method, verifier and budget bindings.
- Reconstructed the retained Qwen tree-draft evidence; its evidence-text hash and full assessment match the retained reconstruction. Independently reassessed all six tree-draft budget outputs and matched the reported assessments. This does not recover the absent historical full evidence.
- Checked all 49 ZIP members for CRC errors; none were found. All seven compressed cache/budget/follow-up JSON receipts equal their corresponding JSON inside the raw ZIP.
- Recomputed first divergent token indices for all cache comparison rows. For every retained first-divergence NPZ, checked finite values, maximum absolute logit difference and that the selected token attains the maximum recorded raw logit. Tied top-token sorting was not substituted for the recorded sampled token.
- Recomputed the same-origin prefix-array differences: repeat 1 changes 1,536 elements at positions 805–807, maximum absolute difference 2.765625; repeat 2 is equal. Recomputed every per-token maximum logit difference for the four same-origin arm pairs; all eight selected tokens agree.
- Checked the four baseline output texts against their historical ledgers, message identity, per-prompt token-ID hashes, text hashes and shorter-to-longer prefix relations. Recomputed the Qwen safetensor sum: 16,054,546,159 bytes.
- Inspected `method_context.py`, method obligations in `decision_contract.py`, assessment/repair/ledger logic in `answer_verifier.py`, MLX model/prefix lifecycle in `agent.py`, `model_prompt_budget.py`, active model configuration and the relevant report/analysis scripts.

Two initial reviewer helper attempts had representation assumptions: one treated a scalar source hash as a mapping; another compared Python tuples directly to their JSON list form. Both were corrected and rerun successfully. Neither changed retained evidence or exposed a candidate defect.

The owner's 25 focused tests, docs audit, strict MkDocs and pre-review public-package check are retained in `engineering-checks.json`; this reviewer did not rerun those suites or independently witness the earlier remote execution. The raw driver receipts show six successful fixed tasks and a successful approximately 25-second follow-up under the 180-second external bound. Stop/accounting claims are accepted as retained operator observations, not independently refreshed account state or provider billing.

## Ranked findings and remaining limits

No blocking report defect or materially unsupported conclusion was found. The following are **disclosed runtime/evidence risks**, not reasons to reject an investigation that establishes and preserves them:

1. **Verifier correctness remains a product risk.** Numeric substring support can miss wrong values; source-number presence does not validate a calculation, and negation/output-shape rules can flag warranted text. The report distinguishes these reproduced local defects from untested end-to-end repairs. A passing lexical assessment cannot establish factual support.
2. **Cache numerical behavior remains unqualified.** Qwen's measured boundary is prefill partitioning; Gemma also varies across identical recorded starting states. Array/hash observations do not distinguish instrumentation effects, allocation/evaluation order, finite precision or a runtime defect. Only first-divergence NPZ vectors and the follow-up full vectors were independently numerically recomputed; other full-vocabulary maxima are retained probe observations. Cache remains disabled.
3. **METHOD task selection remains incorrect on exposed contrasts.** Some labels, especially underspecified requests, involve judgment. Stronger negation/topic examples and reproduced consumer propagation establish a real interface weakness without establishing a population error rate or a causal answer-quality effect. The candidate remains inactive.
4. **Output and hardware qualification remain incomplete.** Longer output fixes observed clipping but does not establish better answers; Qwen's cash-plan reference still hits 1,024. CUDA allocator/disk observations do not qualify this 16 GiB Metal laptop, nor prove that every alternative 27B profile is infeasible.
5. **UI coverage remains partial.** Synthetic focus/click/Escape observations do not validate generated model answers, field data or independently observed pointer hover/exit. The mobile capture is strongly scaled/cropped; the report appropriately relies on its separate DOM dimensions and does not claim screenshot-only geometry proof.

These limits do not defeat the assigned scope: source-bound investigation, explicit unresolved causes, and no runtime activation. Any later behavior change needs fresh independent controls and product-path validation. The proposed task/claim frames are design hypotheses, not accepted implementations.

## Integration boundary

The frozen report still says review pending, and its package receipt explicitly describes a pre-review inventory. The owner must add this review (and any check receipt) to the public manifest as appropriate, update status, regenerate the container inventory and perform the final public-package check. Those mechanical additions are outside the 57-file freeze and must be reconciled before claiming an integrated final package. A substantive change to the reviewed claims or controlling evidence requires a review delta; this verdict does not automatically cover changed bytes.

Changed | This independent review only. Verified | Frozen candidate, model-free replays, source consumers and retained numerical evidence as listed. Residual Risk | Runtime correctness, numerical cause, independent efficacy, full UI pointer observation and laptop qualification remain open. Memory Delta | None.
