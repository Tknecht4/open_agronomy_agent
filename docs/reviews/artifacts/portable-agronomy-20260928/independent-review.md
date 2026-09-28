# Independent combined acceptance review — 2026-09-28

Status: **ACCEPT for engineering merge** at implementation commit `c90e81dae28390d471e5db64b537094ca551b899` plus the reviewed documentation/evidence delta listed below. All reproduced actionable implementation findings have verified repairs. The final packaging commit still requires identity/byte reconciliation; this acceptance does not claim that a merge has already occurred.

Reviewed initial source: `d3e8e5f96a1fdddbdaac3545963fbe1bb9051bee`, compared with explicit base `8f4c33f`. Local `main` was different at review start; the explicit base was used. Initial dirty state consisted only of the two owner-excluded untracked research paths, which were not read. No private SPCC material was used.

The review read raw contract/source before the owner's implementation conclusions, following the astra-project-orchestrator acceptance procedure. Boundaries covered: HTTP conversation scope and authorization; narrow same-session history; actual draft/editor input plus output reserve; runtime measurement semantics; MLX cache namespace, mutation and limits; diagnostic identities, partial/failure behavior and cache parity; non-active METHOD admission and merge preservation.

## Material findings

1. **P2 — Interrupted diagnostic resume mixes attempts.** In the initial runner, interruption after the child writes `worker.jsonl` but before the parent appends `cells.jsonl` causes resume to append a second child attempt into the original file. A successful one-turn rerun then reports `expected_turns=1`, `observed_turns=2`, indices `[0,0]`, status `failed`, and becomes permanently skipped. Reproduced with a one-cell public synthetic manifest and a patched subprocess that writes a completed child record then raises `KeyboardInterrupt`, followed by a successful child. Repair submitted in `a8ae6cdceb0d33eec34682b71291e9d4f61c5620`: fresh numbered attempt directories preserve orphan bytes and separate the new attempt. Delta verification pending below.

2. **P2 — Retained `/chat/stream` consumer bypasses immutable field scope.** `app.py` initial lines 5195–5227 accepts a request field B on a thread bound to field A; the new `chat_service.py` history compiler then includes field A's prior user report in field B's prompt. Reproduced with real TestClient/database/auth paths: create an org/workspace, fields A and B, a baseline `/threads` thread bound to A; send one `/chat/stream` request on A containing `FIELD_A_ONLY_MARKER`, then a second on B. Both return 200 and the second recorded generator prompt contains the marker in the prior-conversation block. Only the generator was replaced with a recording backend. Both fields were authorized, so this is within-workspace scope mixing, not a cross-workspace disclosure. Scope must be checked before message persistence, including trustworthy treatment of pre-existing mixed or unbound legacy transcripts.

3. **P2 — `/api/replay` overrides can permanently rebind a protected session.** `replay_service.py` initial lines 194–198 merges `override_session_context` into the original session without the new binding/authorization boundary. Reproduced: create `general:chat:one` and one mock turn; ordinary PATCH to `{field_context_id: "not-an-authorized-field", field_conversation_key: "field:not-an-authorized-field"}` returns 409, but `/api/replay` with `pipeline: "route_only"`, `mode: "mock"`, and the same override returns 200 and persists that nonexistent field scope. Replay overrides must not bypass immutable identity or ownership. Full replay also now sees latest history including base/future turns; its history semantics need explicit treatment, since this is no longer a same-input replay by default.

## Observations and evidence limits

- Initial focused command: `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_conversation_scope.py tests/test_conversation_context.py tests/test_editor_prompt_budget.py tests/test_mlx_runtime_contract.py tests/test_harness_intervention_replay.py tests/test_portable_harness_diagnostic.py tests/test_method_transfer_candidate.py tests/test_query_context.py` observed **116 passed, one worker abort**. The abort was native Metal import in a mock worker test, independently matching the owner's full-suite failure. It was not counted as a pass.
- The owner's test-only repair mocks device reporting in that CPU contract test. A subsequent independent runner-test command observed **7 passed** before the orphan regression was added.
- Source inspection followed the installed MLX `LRUPromptCache` implementation: fetching returns deep copies; stable-prefix prefill with `max_tokens=0` materializes input state without generating a retained output token. Active caching remains disabled. Real-model equivalence and rates still require model receipts.
- Merge `9e1a49542d05a9b06c9ad9d86e9d58cab09cb02a` has parents `2f484d4` and `f4dc97c`; the reviewed METHOD/query/candidate/seed files preserve the corpus parent bytes. Active `rag.yaml` is unchanged, and runtime registry change binds only the updated model context-budget config. METHOD rows are still non-active. The failed finance efficacy result and removed answer appendix remain distinct historical evidence.
- Owner-reported full gates and live UI checks are awaiting their final source-bound receipt for reconciliation. This review did not duplicate the broad suites or independently render the UI.
- Colab's initial run had an incomplete public transfer closure, per owner report, and is being preserved as a failed/interrupted attempt. The final frozen real-model diagnostic and blind semantic results are not yet available. No agronomic benefit or promotion conclusion is supported at this point.

Changed: review artifact only; no product edits or commits by reviewer.
Verified: boundary source inspection, focused tests, and three independent failure probes above.
Residual Risk at final reconciliation: required completed real-model evidence and semantic grading, cache equivalence, and broad final gate receipts. The scope findings below were subsequently repaired.
Memory Delta: none; no durable memory write. Memory was used only as an index to the project's retained local/private and evidence-boundary conventions, then checked against current source.

## Bounded repair review

- `a8ae6cdceb0d33eec34682b71291e9d4f61c5620`: orphan diagnostic attempts now get separate numbered directories; interrupted files survive. Independent runner tests observed **8 passed**. Initial finding 1 is resolved.
- `d16255836a788c69b8f4f081e5d832c7aaef2fe1`: `/chat/stream` compares supplied field against immutable thread scope before saving the user message. New bridge sessions carry server-bound scope; untrusted older bridge transcripts are retained and quarantined from active history. Replay reauthorizes saved fields, rejects scope changes, and passes ephemeral context without changing original-session context. Independent affected selection observed **52 passed**. The original replay probe now returns **409**, with unchanged stored context and exactly one original turn. Initial findings 2 and 3 are resolved.
- The first replay-cutoff repair still admitted original/future turns when replaying a replay. Independent storage probe showed first replay history `['earlier']` versus second replay history `['earlier', 'base', 'future']`; this was sent to the owner before model execution.
- `277c8360d60f61fb53e4dee8f158ba2c58325df9` resolves replay ancestry to its original same-session root, preserves the immediate parent as lineage, and rejects missing/foreign/cyclic chains. Independent repeat probe now resolves the original base and returns only `['earlier']`. Source review also confirmed the stable cutoff receipt and exclusion of replay outputs from normal chat history. The final independent scope/context/runner selection observed **33 passed in 22.70 seconds** on this exact commit.

No new actionable implementation finding remains from the bounded repair review. This statement is not final task acceptance: the required corrected Colab diagnostic, semantic result interpretation, broad final gates, and any final source delta still require reconciliation. Current product caching and METHOD candidate activation remain off.


## Exact-loader and disposition repair

Source `7b41a189298251e0f61bc977c3f6758d67150ee6` adds isolated exact-product-loader preflight under the same offline GPU worker environment before matrix execution. The receipt requires a resolved pinned snapshot, nonempty output, measured generated tokens and an MLX GPU. Runner rows separate executor completion from backend unavailability/fallback, deterministic bypass, measured model generation, and unknown disposition. Independent bounded review and **12 focused runner tests passed**; synthetic fallback/missing-receipt probes remained ineligible. Per-condition caught cache errors preserve earlier returned outputs. A process killed before its cache row is written still has unavailable conditions; these cannot be converted into failed parity or zero cost.

The owner's first incomplete public-source transfer and second partial-model-snapshot attempt remain failed/interrupted infrastructure evidence. The second attempt's conservative fallback rows are not model-quality results. The reviewed v3 capsule inventory binds 248 public files to exact source `7b41a189298251e0f61bc977c3f6758d67150ee6`, with an empty dirty-path list. No private files were needed.

## Interim real-model cache observation

This subsection is an observation from `outputs/portable-colab-20260928/gemma-live-cells-3.jsonl` (SHA-256 `e3f953f45e0f031cc6d6a3dc8d5c0eab3b2025f77c219e6a00b20f6d8f0d34df`), not the final benchmark result. Run `portable-gemma-20260928-v3`, unit `cache/active/PFMH3-01`, reports MLX GPU with MLX 0.32.2 / mlx-lm 0.31.3 and pinned Gemma snapshot `238767527555cb75a05732a84dff5d6ba0dd6809`.

- All three conditions share exact prompt hash `548d0c226f02070d308618e8c4eb2025a199b1504f572ae6cfd57600c51e6b4f`, argmax sampling and seed 42. Cold/warm token accounting is 1,974 total = 830 cached + 1,144 uncached. Statuses truthfully distinguish disabled, prepared this request, and reused saved prefix.
- Disabled produces 187 tokens/hash `345d9baf079c4a32078bcc3928323cb3367f22c96147705fe0702835a4a15927`; cold and warm both produce 188 tokens/hash `f4ee1226a96747d6ec595174fab4f61b31798a8565a832ca806417155f94b812`. **Exact answer parity fails.** First text divergence occurs at character 550, singular versus plural “condition”; a later sentence also differs.
- Source review against the matching installed mlx-lm version finds no reproduced lost/duplicated-token or shared mutable cache defect: `generate_step(max_tokens=0)` consumes the stable prefix without retaining a generated token, and cache fetch returns a deep copy. It changes prefill partitions from 1,973+1 tokens to 829+1 then 1,143+1. Numerical/kernel batching divergence is a plausible interpretation, not an established cause. Causal diagnosis requires aligned logits/cache-state evidence at the first divergent generated token.
- This direct-generator probe compares the same captured product prompt, not the verifier's final product answer. The failed parity result prevents an exact-equivalence claim. One sample does not establish a speed benefit, cross-model reliability, or agronomic efficacy. Active caching remains off; no code or prompt tuning was performed during the frozen run.


## Larger-model resource qualification interruption

The interim `outputs/portable-colab-20260928/qwen-live-cells-1.jsonl` (SHA-256 `d41bf48f049c24bb4ef2959f074dedaefb1aebb767e24c9e3c69eca5af0119ad`) records product prompts of 1,930 and 1,803 tokens failing CUDA graph instantiation/allocation from out-of-memory errors after the small exact-loader preflight had passed. A third 1,659-token prompt generated 320 tokens. The first two rows correctly report `backend_fallback_or_unavailable`, null generation stats and both quality/generation eligibility false, despite executor `completed` status. These rows are infrastructure failures, not model-quality results. The small preflight proves loader/device viability only; it does not qualify the complete context envelope.

The owner stopped this run and is separately qualifying a smaller prefill batch while retaining the frozen questions, context and output budgets. Any replacement must have its own configuration/run identity and denominator; the partial OOM ledger must remain preserved. No product repair or default change follows automatically from this device-specific limit.


## Completed small-model ledger reconciliation

`outputs/portable-colab-20260928/gemma-complete-cells.jsonl` binds run `portable-gemma-20260928-v3` and has SHA-256 `83a8fa1e3d2db58ab3aa6f71e7d2150642edd12c69dd27a99fb9fb11478a136e`. Independent parsing confirms **44 unique units, 44 executor-completed**: 24 exposed paired cases, 4 three-turn continuity units, 2 two-turn long-context units, 2 cache units and 12 direct references. Per product arm the main set has 11 model-generated turns and one deterministic bypass; continuity has four model-generated and two bypass turns; both long-context turns generate. No product backend-fallback disposition is present.

Both active and METHOD cache probes fail exact uncached/cached parity; cold and warm match each other. Long current prompts measure 5,592/5,743 input tokens within the 8,192-token configured limit after allowing the 320-token output reserve, and subsequent turns truthfully omit their oversized prior history. Ordinary correction turns include one and then two prior turns. These are infrastructure observations; useful correction behavior needs semantic grading.

All 12 direct-reference turns carry positive generation-token measurements and the pinned snapshot. These direct rows use direct-generator receipts rather than the product `model_execution` object. Eleven reach the 320-token output cap; any incomplete answer remains part of the fixed-budget quality result. Executor completion, model execution, task correctness and agronomic validity remain distinct.


## Non-active resource delta and frozen Gemma grading

Exact source `1aa7d137bc0d503c706f3f4dabbb5f9b6292b21e` changes only the non-active Qwen diagnostic prefill from 2,048 to 512, public/review documentation and the generated container manifest. The Python tree and active profiles are unchanged from `7b41a18`. The retained fit receipt observes 5,548 input and 320 generated tokens, 18,005,080,104 peak allocation bytes, and 86.099 seconds including model load. It qualifies that prompt/output/resource condition, not all inputs through 8,192 tokens or the base diagnostic profile's 640-token output ceiling. The new v4 ledger has a separate identity; final reconciliation is pending.

The frozen Gemma grading files in `outputs/portable-colab-20260928/blind-phase1/` independently reconcile to 46 unique answer keys and grades, 84 unique stage occurrences, matching packet SHA-256 values and 12/12 shared primary-grade agreement. Recomputing the final-answer labels gives active 11 partial/1 unsafe, METHOD 10 partial/2 unsafe, and minimal direct reference 9 partial/3 unsafe, each over 12 questions; no complete answers. The original grades remain intact, and two ambiguous judgments retain explicit unsafe sensitivity interpretations. This verifies scoring joins and honest reporting, not independent agronomist calibration or the truth of every grader judgment. These exposed fixed-budget results support neither METHOD promotion nor cache activation.

The owner's proposed follow-up experiment remains a proposal. It does not silently tune the frozen run, change active policy, or convert bundled direct-reference comparisons into causal stage attribution. No new actionable implementation finding arises from the bounded configuration/report delta.


## Additional diagnostic validity finding

**P2 — Editor backend failure remains eligible for final-product quality.** At source `1aa7d137bc0d503c706f3f4dabbb5f9b6292b21e`, `scripts/run_portable_harness_diagnostic.py::model_execution_disposition` examines draft generation failure but ignores `metadata.answer_verification.rejection_reasons`. The verifier catches `RuntimeError`/`ValueError` during the editor call and emits `("editor_error", exception_type)` plus a deterministic fallback (`answer_verifier.py` lines 1837–1851). A CUDA OOM at that stage therefore can enter product-quality scoring if the draft generated successfully.

Reproduction is an isolated function call with metadata `{"generation_stats":{"generation_tokens":17},"answer_verification":{"triggered":true,"rejection_reasons":["editor_error","RuntimeError"],"fallback_applied":true}}` and execution `{"stage_receipts":[{"stage_id":"draft_generation","evidence":{"model_call_executed":true,"fallback_used":false}}]}`. The observed result is `disposition=model_generated`, `product_quality_eligible=true`, `model_generation_eligible=true`. A measured draft should remain separately identifiable, but a failed editor must not qualify the final product answer as an intact model/harness observation. Budget-triggered deterministic policy paths are a different, intended condition and need not be excluded automatically.

The completed Gemma ledger contains zero `editor_error` verification reasons, so this does not invalidate its current scores. The ongoing Qwen ledger must be audited for the same condition. Raw rows already preserve verification reasons; any post-run eligibility correction can be recorded in a source-bound derived artifact while leaving the original ledger unchanged. Repair and final delta review are pending.


The bounded editor-failure repair is independently verified in the working tree atop `1aa7d137bc0d503c706f3f4dabbb5f9b6292b21e`: **14 runner tests passed in 1.04 seconds**. The original probe now yields final-product ineligibility and explicit `editor_backend_failure`, while preserving measured draft eligibility. Additional probes retain intentional budget/content fallbacks as eligible and preserve both failure receipts when draft and editor fail. No product-runtime source or remote frozen driver was changed. Final commit identity and derived full-ledger reclassification remain to reconcile. Reviewed working-tree hashes:

- `scripts/run_portable_harness_diagnostic.py`: `041cd532042840a12a8add74d843aa2e863331583f1ca2293c5816ec206baf47`

- `tests/test_portable_harness_diagnostic.py`: `60d86cd6a86bbd7c29c4c0be7038e30b8018dccf90ebf1836075906da4413ff6`


The repaired classifier is now committed as `c90e81dae28390d471e5db64b537094ca551b899`; its runner/test bytes match the independently tested hashes above. Review of `outputs/portable-colab-20260928/assemble_analysis.py` confirms that it reconstructs classification inputs from retained generation, verification and stage receipts, writes separate derived analysis ledgers, and records original/derived eligibility plus the raw-ledger and classifier hashes. It does not rewrite raw ledgers. The blind-packet builder preserves eligible draft text separately when final-product eligibility fails. Final execution/audit outputs remain pending.


## Candidate method-selection limitation

The post-hoc family audit in `outputs/portable-colab-20260928/method-delivery.json` keeps its interpretation distinct from the frozen quality metric. Both models retrieve and place a METHOD card on all seven positive questions and none of five controls, but the post-hoc expected family matches only five of seven. The balance-sheet case PFMH3-05 selects cash-flow content instead of liquidity; cash-plan case PFMH3-06 selects enterprise-budget content instead of cash flow. The Gemma raw prompts independently show the reported cards in packed evidence. “Card delivered” therefore does not establish relevant method selection or successful use. This is a retained non-active candidate defect, not a reason to tune the exposed cases or change active policy during the run. Final paired scoring remains to reconcile.


## Completed full-ledger reconciliation

The completed Qwen ledger at `outputs/portable-colab-20260928/v4/outputs/qwen27b/cells.jsonl` has SHA-256 `46395fb5f901748cb34ab293b6f605ab5da45c57f667c56cf54d951f1258dc60`. Both it and the completed Gemma ledger contain 44 unique planned units and 54 ordered turns, with exact expected/observed turn counts and executor completion. Each model has 36 measured product draft generations, six deterministic product bypass turns, and 12 directly generated references. Neither completed ledger contains a draft/backend fallback or an editor-error receipt. The interrupted Qwen run is separate. All 12 Qwen direct references reach the 320-token ceiling.

Independent reconciliation verified:

- Every unit matches its frozen manifest plan/run ID; both canonical manifest hashes match. Both runs use the same frozen case-file hash.
- All 144 runtime-source hashes per capsule match Git blobs at the respective source pins (`7b41a18` for Gemma, `1aa7d13` for Qwen); runner and model-config hashes also match. The copied capsules correctly have no embedded Git repository (`git_commit=null`), so the source binding is the verified content hashes plus capsule inventory rather than an invented in-capsule Git identity.
- Draft and editor input counts agree with their corresponding generation statistics. Every measured within-budget request satisfies input plus output reserve at or below its limit; remaining-token arithmetic and history available/included/omitted totals are consistent. No violation was found.
- The separate c90 classifier audit covers all 84 product turns, binds each original row to the exact raw-ledger hash and the verified classifier hash, and reports zero product-eligibility changes and zero editor failures. Raw ledgers are unchanged.
- All four direct cache probes use matching prompt hashes within their triplet, valid answer hashes, and correct cached-plus-uncached token totals. Cold and warm outputs match; **all four fail exact uncached parity**. This is not a cache-equivalence or speed qualification.

Completed-run raw evidence is reconciled. Final anonymous-grade joins, final public artifact closure and final source/documentation delta remain pending.


## Final acceptance decision

**ACCEPT** the combined engineering/corpus merge with the active METHOD candidate and prompt cache remaining disabled as reviewed. No unresolved P1/P2 implementation or evidence-accounting defect remains in the accepted scope. This does not promote model quality, candidate efficacy, cache equivalence, supported larger-model portability, or a release. The branch preserves the corpus source and failed finance evidence; the removed answer appendix has not been reactivated.

The public compressed ledgers decode byte-for-byte to the raw Gemma/Qwen ledgers. The three public failed-attempt records retain the exact original cells and hashes, are ineligible for quality comparison, and show final counts of 9 completed/6 failed (first Gemma attempt), 30 completed/1 failed (second Gemma attempt), and four completed executor rows in the interrupted original Qwen resource condition. Completed executor rows in those interrupted attempts are not reclassified as successful quality evidence.

All 84 anonymous answer keys and 168 distinct stage occurrences bind to the exact retained answer text. Every public frozen packet/grade payload and its recorded file hash matches its local original. Primary agreement is 37/38; source-adjudicated agreement is separately 38/38. Source-adjudicated final grades reproduce the report: Gemma active 11 partial/1 unsafe, METHOD 10/2, direct 9/3; Qwen active 12 partial, METHOD 12 partial, direct 9 partial/3 unsafe. Every denominator is 12 and there are no complete final/reference answers. Qwen direct originally had 10 partial/2 unsafe; its single source-adjudication change is separately retained. Complete Qwen tree-mulch drafts lost in both product arms and unsafe drafts removed are preserved rather than averaged away.

For the materiality check, this reviewer independently obtained official Revisor source text after direct-fetch failures: [Chapter7030 concerns noise control](https://www.revisor.mn.gov/rules/7030/) and [Part7020.2225 covers manure land application](https://www.revisor.mn.gov/rules/7020.2225/). The answer uses the wrong chapter as mandatory governing authority to assure compliance, which supports the retained unsafe adjudication under the broader false-authority rule. The asserted Act name remains unverified. This is a narrow source check, not complete-answer or expert legal/agronomic validation. Exact public queries and failed-fetch observations are retained separately in `outputs/combined-acceptance-source-check-20260928.json`; no private SPCC trace is included.

The public artifact allowlist is explicit. Inspection and decoded-content scans found no private machine-home path, credential form, account-balance value or private trace in the selected packet; its questions/field contexts are the declared public/synthetic material. Compute accounting exposes only net task usage (3.24 CU), the observed resource rate, and stopped-session state. Unknown controller/worker billing remains unknown. These checks are scoped to the selected package, not an assertion about every local output.

Supplied CI logs match the recorded hashes and show 1,438 Python tests passed with four skips and 366 frontend tests passed at c90e81d. Owner receipts additionally record typecheck/build, documentation, macOS smoke, 15 final docs/package tests and the 1,114-file candidate public build. This reviewer did not rerun broad suites. Final live UI interaction remains explicitly unavailable; earlier layout checks and automated component evidence are not relabelled as a final live pass.

Residual limits: all four exact cache-parity probes fail; METHOD family selection is only 5/7 despite delivery7/7; the fixed-budget automated grades are exposed and uncalibrated; correction retention does not guarantee useful retrieval or answers; long indivisible history is omitted; Qwen is qualified only for observed prompt/resource conditions, not the entire advertised context window or a16GiB laptop. These are retained research/product limitations with the experimental defaults off, not hidden implementation passes.

Changed: reviewer report and public-source-check receipt only; no product edit, commit, publication or merge by this reviewer.
Verified: repaired boundary probes and focused regressions; exact runtime source, manifests, raw ledgers, budgets, classifications, grade joins, original/adjudicated scoring and public evidence closure.
Residual Risk: the limits above; final packaging commit byte identity and final CI remain integration-owner steps.
Memory Delta: none. Memory was used only as an index to conventions and current repository evidence controlled the decision.

### Reviewed documentation/evidence bytes

The following hashes bind the reviewed delta before adding this acceptance receipt. Expected subsequent changes are publication of the receipt and mechanical manifest regeneration; any substantive code, policy or scoring delta requires another review.

- `docs/reviews/portable-agronomy-diagnostic-20260928.md`: `6e8ab906c480f943201986fb5b3c00c2e758ac7d7599d38586330a4164d81e47`

- `docs/reviews/generalized-harness-implementation-20260928.md`: `ee0115a79fc4871ed7e3ab2c0460e32cbc2a570c8ff246935f1709c7bac887cf`

- `configs/public_repository_manifest.json`: `b51aa7f916cad168698c5fa43788c28ffca762d4d62f99d3963ffd48178d6adb`

- `container/runtime_manifest.json`: `b38c2981f87454433615d4456707f77cd19ecf28dc05e6e529601fb22690ca8e`

- `docs/reviews/artifacts/portable-agronomy-20260928/compute-accounting.json`: `6a84cc54f5e1cb0f4da6af2d50d26d26bcd25e44bb7081f2d7dd30e76d5d9961`

- `docs/reviews/artifacts/portable-agronomy-20260928/engineering-validation.json`: `c9e4b177656709823a9465c30e4dc4e583bfc85556f493154c9b2a4a0c18613d`

- `docs/reviews/artifacts/portable-agronomy-20260928/failed-attempts.json.gz`: `7c117f0e914d463a2f7f704e687675764c77fa4d0e642c559121c1f55f610bbb`

- `docs/reviews/artifacts/portable-agronomy-20260928/gemma-v3-cells.jsonl.gz`: `ae198d19800d188bfc2b542d6477e2e2de555db835f6942b38e5671d9347443e`

- `docs/reviews/artifacts/portable-agronomy-20260928/method-delivery.json`: `794a81410e9177ddd420e06114600f00b6dcb191971a3ddaa3318d494b85c0ea`

- `docs/reviews/artifacts/portable-agronomy-20260928/quality-eligibility.json`: `ef2097eb6a4ed332b044e2139a6a79749172e2b5d256b28c36b099cea7829c0a`

- `docs/reviews/artifacts/portable-agronomy-20260928/qwen27b-v4-cells.jsonl.gz`: `24aa97a34ea88b995f71cd0aafbd17a60625064c99a788a711a1a8e4370f0039`

- `docs/reviews/artifacts/portable-agronomy-20260928/run-manifests.json`: `c37088d9fc2aa684f04b68657362de5661d8e49c5dba3c4daa3ecf94d6ba7c2c`

- `docs/reviews/artifacts/portable-agronomy-20260928/runtime-analysis.json`: `b4d1a772f0f7146e553a569e65744e9e840375bbe9907b232b10e669f4b2b21c`

- `docs/reviews/artifacts/portable-agronomy-20260928/runtime-qualification.json`: `966e19b76359ed29bdf71c9cd33c3d5e14ce013dc9c698ac746fcc0c7c21db3c`

- `docs/reviews/artifacts/portable-agronomy-20260928/semantic-grades.json`: `25b51e85dd5a7d2ecfbbc88141372a2c541106f03687a8feaa2c7d11196c8345`

- `docs/reviews/artifacts/portable-agronomy-20260928/storage-profile.json`: `d23f30f6186793b9d29fc4cb89bfe07eea9df2cb03d560a1ddfbd9b49ba55cab`
