# Independent post-rebase integration review

Date: 2026-09-27. Reviewer runtime: `/root/implementation_review` in the visible collaboration workflow. No model/run attestation is fabricated here.

**Scoped verdict: accept the rebase and bounded disclosure delta.** No material regression was identified in the reviewed integration. Rebased code checks are complete; final artifact/public-package reconciliation remains with the owner. This is not a new agronomic or deployment qualification.

## Reference states

- Frozen reviewed checkpoint: `bb9a26ee7938246c95ca3c6684902d4cfefe92a0`.
- New main: `393b07185f5dc7ff2b62e56e30928fb44de25ba9`, the merged foundations/calculator work.
- Rebased candidate at review: `d539502a43577f0e73bdb261baed0d7763d76fc0`, following rebased field-data commit `0ba063a`.
- The previously frozen `implementation-review.md` remains byte-identical with SHA-256 `756795e7d0914d56f36c23b18bc7702798d60c44521e6483b5c8e804d0b67047`. Its evidence, limitations and earlier negative findings have not been rewritten.

The acceptance obligation is to preserve the accepted field/imagery behavior while retaining new main's farm calculation, seed and version contracts. The review compares the candidate to both reference states. It does not independently requalify the upstream foundations experiment, retrain anything, reacquire imagery or rerun a model.

## Reconciliation and observed evidence

| Obligation | Inspection or executed observation | Result |
|---|---|---|
| Preserve imagery/scoring/storage semantics | Exact byte comparison against the frozen checkpoint for `imagery_analytics`, `imagery_store`, `imagery_models`, `imagery_assessment`, imagery service/routes/settings, storage-audit CLI and package builder | All identical. No scientific result or model input needs regeneration because of this rebase. |
| Preserve field-data authority and evidence | Exact comparison for `field_data`, field store, field capability, benchmark, server app/storage/context compiler, agent and leak guard; source inspection of the merged chat-service additions | Existing HTTP authorization, client snapshot stripping, field/workspace binding, bounded snapshots and final-result replay are retained. |
| Retain new main's calculator implementation | Exact byte comparison to main for `calculator_contracts`, `foundation_math_parser`, `agronomic_calculations`, `answer_safety`, Agno tool adapters; exact source comparison of `_parse_calculation` and every downstream function in `tool_planner` | Identical to main. The field-query branch is added ahead of the preserved calculator path; calculator semantics and ambiguity guards are not replaced. |
| Retain model seed and fail-closed configuration | `_build_mlx_generator` is byte-identical to main, including seed propagation and removal of the permissive TypeError fallback; independently executed the two revision/seed contract tests | **2 passed in 3.61s**. This used capturing mocks, not a model load or generation call. |
| Bind planner selection to the right capability | Inspected conflict resolution in `capability_planner`: registry lookup uses each invocation's tool ID, version and selector; independently executed both branches | Calculator selector is `explicit_arithmetic_parser_v2`; field table selector is `reviewed_field_table_parser_v1`. |
| Preserve calculation version and replay guards | Independent deterministic calls for legacy GDD, break-even price and published-factor imperial seed mass; mutate planner version and result tool version | GDD retains calculator v1/value10; break-even and seed mass use v2/values300 and129.76827094474154. Valid current replay passes; stale/forged replay fails. Conflicting upper GDD caps produce clarification. |
| Preserve field snapshot/result replay | Independent temporary store: import reviewed values2 and4, calculate mean, validate replay, omit trusted snapshot and mutate answer | Value3.0 passes only with the trusted snapshot; missing snapshot and forged answer are rejected. |
| Preserve source/evaluation identities | Exact comparison of the pilot manifest/gold and paired scientific result plus spectral/Prithvi final feature artifacts against the frozen checkpoint | Identical bytes. Evaluation answers remain outside runtime retrieval/training. |
| Preserve active profiles and publication union | Active model/RAG/runtime-profile files are byte-identical to main; manifest set-union comparison; notices diffs inspected against both parents | No active-profile change. Neither parent's public paths or source-attribution sections were lost. Main's non-active candidate description is retained. |

The independent deterministic check initially supplied an incomplete temporary field payload without `region_text` and stopped with KeyError after the three calculator checks. The field-only check was rerun with the documented complete field payload and passed. That fixture setup error is not reported as a production regression or as a successful first field check.

## Current-code development benchmark

The owner reran the field-data development benchmark after rebase. I inspected `outputs/imagery-validation/field-benchmark-rebased/summary.json` and compared every `code_sha256_end` entry with current source bytes: **zero drift**.

Observed receipt: **96 cases, zero failed cases, stable code/environment, 72 exact registered-result/final-answer binding passes, and 24 explicitly unscored semantic cases**. These remain exposed development contracts using a mock generator, not a new language-model/field competence result. The previous imagery/label assessment artifacts are unchanged and retain their original identities and limitations.

## Small disclosure delta

The owner additionally added one sentence displayed only in online mode: analysis sends the saved polygon and selected dates to Microsoft Planetary Computer to locate public HLS imagery, without requiring an account. I inspected the one-line component change and corresponding existing-test assertion. The disclosure matches the already reviewed outbound request path; offline behavior and request/persistence logic are unchanged. The owner reports four focused panel tests and typecheck passing, with the full frontend run retained separately.

## Final gate condition

The completed `pytest-rebased.log` was independently inspected: **1212 passed, 2 skipped, 26 synthetic class-label metric warnings in 328.31s**. Public-doc audit and strict MkDocs logs were inspected and passed. The owner reports **267 frontend tests, typecheck/build and active corpus audit passing** after the bounded disclosure change. The registered field-data benchmark evidence is recorded above. The final runtime inventory, manifest, review/validation documentation and new package receipt remain the owner's artifact reconciliation; a pre-rebase package receipt cannot substitute for that final build.

This new review should be explicitly included in the public manifest before the final package build. Do not edit the frozen earlier implementation review to imply that it already covered the new main merge.

## Source binding at review freeze

This 17-file binding covers the integrated planner/version/seed and disclosure boundaries plus unchanged active profiles. The unchanged imagery/scoring/storage sources retain their earlier review and checkpoint identities. SHA-256 of the sorted compact JSON path-to-SHA map is `531cd6e6c4bb684bc5e1def8ce978cb73ff1ba27051858fa807a4f50b80caf9e`. This binds observed source bytes, not an immutable or signed runtime attestation. Generated package metadata and review inclusion remain the owner's final reconciliation.

```json
{
  "configs/model.yaml": "8cd880ac68b3631a4eccc11bd9716be3e1768b1a5d49653ac13acc7ec6aeba10",
  "configs/rag.yaml": "8f45880dbadf368848d52251aaafb24e25b17d9baa7923aa7707f6880fc04b91",
  "configs/runtime_profiles.json": "e868d50cc9634dba0205bdb1b4b3a387c75c0dacc3b994f19c07055de8e94156",
  "frontend/src/FieldImageryAnalyticsPanel.test.tsx": "3c7a14da92eafe1e20599863143aabdfb3d87da2d6cb1f6f3a30799f984a4935",
  "frontend/src/FieldImageryAnalyticsPanel.tsx": "20d9c087da745c8df2901e1eac5843b101acae9d04b261b2c37636c187c0b742",
  "src/agronomy_agent/agent.py": "0dc0b64a37580c4b7133225e6fac0a21e17f4501b9104de4c3009f650faea283",
  "src/agronomy_agent/agronomic_calculations.py": "97be4e716744a3e1e9b9d9cdb86d15b6f5192669dad508056768375304fdb137",
  "src/agronomy_agent/answer_safety.py": "dd5a7f47efa17913e9a0a7abb9fad3bab0695ec8eebac657f16a717ddaaa22bb",
  "src/agronomy_agent/answerability.py": "566275863c1030315b42096664e990e27ef03d43a96d0e04534db5742381fc4f",
  "src/agronomy_agent/calculator_contracts.py": "cef4e50383d8ec5b8e78d3415725372ce83ce84a10b2c19643ffb97c495644d7",
  "src/agronomy_agent/capability_planner.py": "b6b9a30ddaa67e5cb5977abe66c54dbf782c334cee317267b369a9598650cf10",
  "src/agronomy_agent/capability_registry.py": "4fe78768512e20a31b6bc100fe1fb992a0a8a15e0401af0cd9d09a365b350d49",
  "src/agronomy_agent/field_data_capability.py": "07b8fa315808d93f7b9080c6044b59d5627e1f82dbdd2a8882f9aac0e99f6e76",
  "src/agronomy_agent/foundation_math_parser.py": "240a60f72dafa3bb903f6a8816236301b0f0c382af4d210aa395f023122733d3",
  "src/agronomy_agent/server/services/chat_service.py": "0af45d3e978d9e05156a7ec019548d8af9747bce3b300eb32fd914661fe64183",
  "src/agronomy_agent/tool_planner.py": "01b7add61c563daf4ba215aae9c50d74ff5d4a38aa06190fd1693e20ec39973b",
  "tests/test_model_profile_controls.py": "e7da84c6325140a54b7ab1661dff5c30024a510da9e1a0cd1d14dd3aec970b47"
}
```

Changed | This independent integration review only; no production changes by the reviewer.

Verified | Both-parent source preservation, per-tool selectors, seed/version guards, deterministic calculator and trusted-field replay, source-bound 96-case benchmark, active-profile and public-manifest union.

Residual Risk | Final artifact/public-package reconciliation remains with the owner. Prior one-farm, datum, numerical-warning and non-deployment limits remain binding.

Memory Delta | None.
