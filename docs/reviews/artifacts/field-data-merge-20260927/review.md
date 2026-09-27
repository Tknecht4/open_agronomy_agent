# Independent final acceptance review — 2026-09-27

Final review verdict: **ACCEPT the reviewed closure code, documentation, and local evidence after the repairs below.** No unresolved implementation finding remains in this scope. Final package/runtime regeneration and green remote checks, including the Mac candidate, remain merge prerequisites owned by the integrator. This review does not claim that merge or those remote gates have completed. All initial findings, failed checks, and invalidated rehearsal claims remain recorded below.

## Scope and boundary

Reference checkout supplied by owner: `codex/field-imagery-analytics`, initial HEAD `0f3d463`, rebased on main `0a942a3`. The owner supplied explicit authorization to finish closure, review, then merge. This reviewer inspects current implementation and raw tests before implementer conclusions. Only this review file is reviewer-owned. No production edit, live provider/model call, acquisition, training, or Git mutation is part of this review. Frozen research, acquisition, and imagery scores remain separate evidence.

Read AGENTS.md, README.md, ARCHITECTURE.md, source/server/scripts/tests guidance, and `docs/reviews/field-data-merge-readiness-20260927.md`. Scope includes source blobs/migration, source preparation, imagery admission/worker/service/UI integration, and preservation of current main defaults.

## Findings and repair requirements

1. **P2 — Cache reads can write before admission.** `imagery_analytics.analyze_scene` and the service lookup instantiate ordinary `ImageryStore` before the cache lock/budget check. Its constructor creates tables and performs legacy schema migration; legacy attestation can update hashes. Reproduced with an existing zero-byte `imagery-v1.sqlite3`, offline mode, and `max_cache_bytes=1`: logical cache size grew from **0 to 32,768 bytes** and the request returned `blocked_offline`. No network was involved. Missing/empty/legacy lookup must not initialize or migrate storage before admission; verified current cache hits must remain usable under the limits. Owner assigned read-only lookup mode and regression coverage.

2. **Precision correction — Migration dry-run scope.** On a closed WAL-mode database without sidecars, the mode=ro CLI preserved the 12,288-byte database contents but created a zero-byte `-wal` and 32,768-byte `-shm`. This is SQLite coordination, not a source/schema conversion. The owner is qualifying the logical-read-only guarantee and testing visibility of committed WAL rows. `immutable=1` on an active WAL database is not an acceptable shortcut.

## Independently verified observations

- Initial independent focused command: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_field_source_blobs.py tests/test_field_source_preparation.py tests/test_imagery_budget.py tests/test_field_data_store.py tests/test_imagery_routes.py` → **40 passed in 42.30s**. This precedes the review repairs.

- Blob review checks source bytes against their SHA-256 on insertion/read, verifies both compressed and original identity with bounded decompression, keys deduplication by workspace plus original hash, and adds format markers without automatically converting legacy inline rows. One explicit transaction covers migration and restoration. Tests exercise rollback after later corruption, exact query-receipt parity, idempotence, old-schema CLI dry-run, corruption, size/framing rejection, and bounded Python memory across 64 duplicate payloads.

- A separate real subprocess attempted the same cache lock while the parent held it: observed `busy imagery_cache_writer_busy`. After the parent released it, a new subprocess observed `admitted`. This establishes cross-process exclusion in this local environment; it is additional to the same-process unit test.

- All **7 source pins** match frozen acquisition receipts. Independent standard CSV and openpyxl reads, separate from the adapter parser, directly compared **60,417 selected cells across 4,008 rows / 85 groups** with prepared values and original-record locators. No mismatch. The actual selected columns contained no formula cells; the synthetic poisoned-cache test covers formula exclusion in selected measurements. Initial helper attempts encountered `dataset` versus `dataset_id` receipt keys; the corrected complete audit passed.

- Raw soybean dictionary independently confirms Actual Yield is an average and P/K/Ca/Mg/S tissue concentrations use g/kg. Conservative derived/interpretation and observation roles follow those source meanings. Unknown geometry/farm independence, bean date typo, partial date windows, missing markers, and onion record 100 date/year conflict remain explicit; no geometry or date was inferred. The preparation module is used only by its CLI and tests, not runtime retrieval/training.

## Pending final acceptance

Re-read repair diff/tests, independently rerun affected contracts, inspect source-bound integrated verification and product rehearsal, then bind the final verdict to hashes below. Full-suite, documentation/package, frontend, desktop/optional-worker, and remote-merge claims are not yet established by this reviewer.

## Initial reviewed file identities

| File | SHA-256 |
|---|---|
| `src/agronomy_agent/server/storage/field_source_blobs.py` | `8a27f39e383874814ca93677ba4acc3e436bf656629335c8bc512ddaaf19ac55` |
| `src/agronomy_agent/server/storage/field_data_store.py` | `2b46f9f75cec38d600d2254b44878e26e98bf0dcf693920dd041113bda9b1c89` |
| `src/agronomy_agent/server/storage/db.py` | `d2a05f192948f15b740ba6073952a033bf49508f998394e92e3ae82f79c7bcf8` |
| `scripts/migrate_field_source_blobs.py` | `721799144ae8be2b780dacde90205639c9e989bd6acc5c9b8ac90315790d8077` |
| `src/agronomy_agent/field_source_preparation.py` | `aefc5dac51067ca2037a33185b1c57c63cd6688a24cadad2083f8a7832d253be` |
| `scripts/prepare_field_sources.py` | `ec9b4b457c58410914ec21ce8bab8b49805a90a5886ae47fd6875adc3699abe6` |
| `src/agronomy_agent/imagery_budget.py` | `44221209a25fdc27deffd47cf119e3d45903602f88db362a81cf903eda1b9164` |
| `src/agronomy_agent/imagery_worker.py` | `dd969e1c0303cc179bbc93dae9a8e0d5d4f03fa000b9338651dcea182674228b` |
| `src/agronomy_agent/imagery_analytics.py` | `3f35bb093079e29ea09bd2c91e064060392937eaf791caf834ed9bbcc5b77a31` |
| `src/agronomy_agent/imagery_store.py` | `0954acb940e11c3c835e721a65b5a8735fdb0a052b37f86d08e071f51b0d5016` |
| `src/agronomy_agent/server/services/imagery_service.py` | `4be523cd43e53e6e8c19cc9714db2825543f6fe643fa1caf09d8e7dbaadfa307` |
| `src/agronomy_agent/server/settings.py` | `5bc86513df2457af95db84cc9ca4cac37667eedc051624067b9aa12e5013e761` |
| `src/agronomy_agent/server/app.py` | `d4b4033e9b42c81bad45e6f26c5f7b3fc4751d22503f9f6b38d9c658bb6c5c66` |
| `frontend/src/FieldImageryAnalyticsPanel.tsx` | `f19d4eef3f932cb10d35998cc9c58b9804f5562b73f6ba986a3ca623aed7668f` |
| `tests/test_field_source_blobs.py` | `7b4c537133825dea69b5f8998983592c0df264219be80186ddce6bbb902e0806` |
| `tests/test_field_source_preparation.py` | `e497e02336d8b1b7da3422f1c1d30d0f7da39c5bd362410f7f094419b7ab31f8` |
| `tests/test_imagery_budget.py` | `609e8b026b8e35d17bbe46de052c20177e2fb8a37f29b0863985ca1d31c7d482` |
| `tests/test_imagery_routes.py` | `febb9a3999ae2a45ae963ade7a5001251537591074e1040a5684ebe3050a6b06` |


Changed: this review only. Verified: bounded observations and initial tests above. Residual Risk: cache pre-admission writes need repair; final integration and rehearsal are pending; scientific unknowns remain holds. Memory Delta: none.

## Repair inspection checkpoint

The source migration wording now accurately promises logical data/schema/source preservation while allowing SQLite WAL/SHM coordination sidecars. The new CLI regression reads a committed WAL row, checks its inventory hash, and verifies schema/source state. This precision correction is resolved.

The imagery store now implements `read_only=True` with non-WAL header preflight, SQLite `mode=ro` plus `query_only`, and no schema initialization, permission change, or legacy hash attestation. It does not use `immutable=1`. Missing/empty/schema-v1 indexes produce no hit; corrupt/WAL indexes refuse; current fully hashed chips remain usable. Code inspection confirms analytics/service/preview lookups use this mode.

Independent repair checkpoint command: the initial six-file selection plus `tests/test_imagery_store.py`, using `-n 0` for serial execution. Result: **52 passed, 1 failed in 20.41s**. The retained failure is `test_corrupt_index_fails_closed_without_processing`: read-only corrupt-header validation raises `ValueError`, while the analytics wrapper did not yet catch that type. The expected repair is to map the storage error to `storage_unavailable` inside the already validated request boundary. This remains part of finding 1, not a weakened assertion.

The initial hash table is an interim snapshot taken while repairs were being integrated, not an assertion that every listed hash was the input of the earlier 40-case run. Final acceptance will bind a stable reviewed snapshot after the repair rerun.

## Scoped code acceptance after repair

The analytics storage try-block now catches the read-only preflight `ValueError` after request/path/policy validation, preserving caller validation errors while returning typed `storage_unavailable` for corrupted cache storage. The independent serial six-file selection completed **53 passed in 18.22s**. No assertion was relaxed.

The original offline reproduction now leaves the existing zero-byte index at **0 bytes before and after**, with no cache schema write, while returning `blocked_offline`. This closes finding 1. Fully verified cached reads under exhausted capacity remain covered by the passing suite; legacy unhashed/index-v1 entries and WAL-mode indexes remain held.

Two actual packaged-module worker subprocesses also completed locally without a provider call: offline miss returned exit 2 / `blocked_offline` with no cache files; an online-flag request with a 1-byte maximum returned exit 2 / `storage_limit` with only the zero-byte coordination lock and no imagery index. This checks CLI argument propagation and typed refusal at the module entry point. It is not a live-provider or installed-app qualification.

The source-migration precision correction is resolved by accurate wording plus a passing committed-WAL visibility regression. The migration remains logically read-only on dry run; SQLite coordination sidecars are explicitly allowed and no immutable read shortcut was introduced.

Accepted source/test SHA-256 snapshot (before final documentation/rehearsal delta):

| File | SHA-256 |
|---|---|
| `src/agronomy_agent/server/storage/field_source_blobs.py` | `8a27f39e383874814ca93677ba4acc3e436bf656629335c8bc512ddaaf19ac55` |
| `src/agronomy_agent/server/storage/field_data_store.py` | `2b46f9f75cec38d600d2254b44878e26e98bf0dcf693920dd041113bda9b1c89` |
| `src/agronomy_agent/server/storage/db.py` | `d2a05f192948f15b740ba6073952a033bf49508f998394e92e3ae82f79c7bcf8` |
| `scripts/migrate_field_source_blobs.py` | `721799144ae8be2b780dacde90205639c9e989bd6acc5c9b8ac90315790d8077` |
| `src/agronomy_agent/field_source_preparation.py` | `aefc5dac51067ca2037a33185b1c57c63cd6688a24cadad2083f8a7832d253be` |
| `scripts/prepare_field_sources.py` | `ec9b4b457c58410914ec21ce8bab8b49805a90a5886ae47fd6875adc3699abe6` |
| `src/agronomy_agent/imagery_budget.py` | `44221209a25fdc27deffd47cf119e3d45903602f88db362a81cf903eda1b9164` |
| `src/agronomy_agent/imagery_worker.py` | `dd969e1c0303cc179bbc93dae9a8e0d5d4f03fa000b9338651dcea182674228b` |
| `scripts/analyze_field_imagery.py` | `73633acfdf29aae4639e4be118980dc5f0fa3fb02aa390dde046b8519da81326` |
| `src/agronomy_agent/imagery_analytics.py` | `3e5c9aba9acb76023b22871f7036e63262f6ec9a0480d70e02d87a056b9304c7` |
| `src/agronomy_agent/imagery_store.py` | `98794b4d1d258dd7a79a26c223201a0f0a8e05f1d3fded2fbf242068623730e7` |
| `src/agronomy_agent/server/services/imagery_service.py` | `4be523cd43e53e6e8c19cc9714db2825543f6fe643fa1caf09d8e7dbaadfa307` |
| `src/agronomy_agent/server/settings.py` | `5bc86513df2457af95db84cc9ca4cac37667eedc051624067b9aa12e5013e761` |
| `src/agronomy_agent/server/app.py` | `d4b4033e9b42c81bad45e6f26c5f7b3fc4751d22503f9f6b38d9c658bb6c5c66` |
| `frontend/src/FieldImageryAnalyticsPanel.tsx` | `f19d4eef3f932cb10d35998cc9c58b9804f5562b73f6ba986a3ca623aed7668f` |
| `tests/test_field_source_blobs.py` | `7b4c537133825dea69b5f8998983592c0df264219be80186ddce6bbb902e0806` |
| `tests/test_field_source_preparation.py` | `e497e02336d8b1b7da3422f1c1d30d0f7da39c5bd362410f7f094419b7ab31f8` |
| `tests/test_imagery_budget.py` | `609e8b026b8e35d17bbe46de052c20177e2fb8a37f29b0863985ca1d31c7d482` |
| `tests/test_field_data_store.py` | `e5f43e3c96effe51befb2741018ef25910dcd4a0caf71b4c950cb3580160bea4` |
| `tests/test_imagery_routes.py` | `febb9a3999ae2a45ae963ade7a5001251537591074e1040a5684ebe3050a6b06` |
| `tests/test_imagery_store.py` | `66c333d2d10cd3df9d7f1bc7ff226c71f8ebb387ac29e25f3deb78dbb8da4c46` |

Changed: this review only. Verified: scoped code acceptance, repaired negative cases, 53 focused tests, original source-cell lineage, and real local subprocess refusal/locking. Residual Risk: final integrated gates and product rehearsal are pending; source-only diagnostics and scientific holds remain binding. Memory Delta: none.

## Final product contradiction — acceptance held

The owner UI inspection of the new `-07` default-identity source rehearsal showed a generic request for field details where a bean mean should appear. Independent inspection of the saved SQLite `turns.answer` confirms a real renderer defect, not a UI summary mismatch. Four prepared means are affected: bean ERS15, SGS onion nitrogen, onion trial bulb weight, and soybean crop moisture. Four original-column YD means and the Picketa record count retain the correct text.

**P1 — Validated source-column identifiers erase deterministic answers.** Each affected executed `field_table_query` payload contains the correct numeric answer and source receipt, but `server/services/answer_renderer.py` calls the generic prompt-leak scan before rendering. The `raw_source_id` pattern in `leak_guard.py` matches legitimate imported names such as `source_yd` and `source_nitrogen`; `_strip_leaking_lines` removes the entire one-line deterministic answer. The four persisted answers become `Please provide the field details and I will answer from the agronomic evidence.` Their structured-rendering receipts correctly expose differing input/final hashes; the shared generic final hash is `dca6e1e8a1ebb84100c14375f1236d79b76c34edde13b2425befe179c89af791`.

The rehearsal script checked generation path and numeric receipt values, but omitted final answer equality. Thus its `verified_deterministic_binding` status does not establish successful rendered answers. Preserve `-06`/`-07` as diagnostic attempts, add returned-and-persisted answer equality with the executed payload (the existing pilot judge already enforces this), repair legitimate identifier handling without disabling real prompt-leak detection, and rerun into a new destination. Renaming the prepared aliases alone would hide the general user-column defect.

Before this contradiction, independent delta checks verified all 14 verification control hashes, the retained 1306-pass/2-skip Python log, the 89-pass optional-EO log and runtime-corpus log hashes, passing final public-doc/MkDocs logs, and nine imported source hashes with six verified decompressed blobs. Public rehearsal fields match raw `-07`, all five earlier failed-attempt hashes and the previous `-06` hash verify, and nine saved 17-stage/query receipts match the exported receipt. Those storage/trace observations remain valid; none substitutes for the missing rendered-answer contract. Frontend 281-pass/typecheck/build and browser observations are owner-reported tool evidence, not independently repeated by this reviewer.

Changed: review only. Verified: the new rendered-answer defect and preceding local storage/trace evidence. Residual Risk: final product acceptance is blocked by deterministic answer erasure; refreshed rehearsal, relevant gates, package/runtime inventories and remote CI remain required. Memory Delta: none.

## Final delta acceptance

The rendered-answer finding is closed. The renderer exempts exact literal column identifiers only after replaying the current registered planner and deterministic result against a separately supplied, authorized server-loaded table snapshot. It checks the question, complete result, registered result identity, and exact answer before applying that narrow identifier allowance. Trace-only context, a deterministic label, modified result/value, changed question, missing context, or appended answer text does not qualify. Other raw identifiers and real prompt/evaluation leak markers remain detected on the same line. `LEAK_GUARD_VERSION` advances to v4; the ordinary unbound detector remains conservative.

Independent reviewer checks:

- Replayed all nine frozen `-07` tool answers through the repaired renderer using fresh snapshots read from that database with SQLite `mode=ro`: all nine now reproduce the exact answer, including the four previously erased means. Original database/receipt answers were not changed.
- Focused rendering/capability/planner tests: **49 passed in 3.92s**. An initial iteration had 42 passes and seven new-fixture setup errors because `region_text` was absent; the fixture was corrected, and no production assertion was relaxed. The negative cases cover missing and trace-only context, changed question/payload/result identity/answer, and same-line source/prompt/regex leakage.
- New rehearsal `-08` has **nine complete answer bindings**, not merely numeric receipts. Independently read every persisted answer and structured answer/Markdown, matched each to the executed result payload, verified its HTTP/payload answer hashes and all binding checks, matched all 17-stage/query receipts, and verified all decompressed source hashes. Nine imports still use six workspace blobs. Picketa's observational-mean request remains a hold.
- `-06` and `-07` remain frozen and explicitly invalidated for complete-answer claims, with four failed answer bindings retained for each. Their table/storage observations remain usable only at that narrower scope. All five earlier failure-receipt hashes, current script/renderer hashes, and the new raw `-08` receipt hash verify.
- Refreshed pilot: **96 cases, zero failures**, consisting of 72 exact product-contract passes and 24 explicitly unscored semantic cases. Every recorded end-of-run code hash matches the current source tree; runtime code was stable during the run. These are development contracts, not agronomic validation.

Integrated evidence inspected, without independently repeating the whole suite: the final Python raw log reports **1,317 passed, two skipped, 26 warnings in 277.87s**, and its hash matches `verification.json`. All **20** verification control hashes match the current files. The earlier 1,306-pass run is preserved separately. The optional EO raw log verifies **89 passed / 46 warnings**; runtime-corpus evidence passes. Final public-doc and strict MkDocs raw logs pass. Frontend typecheck/build and **281 tests** are owner-observed tool evidence recorded in the verification receipt; the only rebase repair changes the data-only map wording assertion to current main's `No location selected`, and new panel tests cover typed storage refusals plus authenticated cached preview behavior. This reviewer did not rebuild a native Mac binary or independently repeat the browser session.

The remaining four phase5 audit events are explicitly preserved. Independently matched each event's `matched_text_hash` to its literal column: `source_yd`, `source_nitrogen`, `source_jumbo_bulb_weight_kg`, and `source_crop_moisture_content`. They are known false positives from the later unbound audit, not confirmed prompt disclosures and not a clean leak-rate result. They do not alter the now-correct saved answers. A future audit-context refinement is distinct from weakening leak detection or rewriting historical events.

Documentation accurately preserves logical versus physical storage claims, the migration's possible WAL/SHM coordination sidecars, no automatic eviction, legacy/untrusted imagery holds, explicit source methods/derived roles, unknown geometry/farm independence, and the unchanged scientific limits. The desktop default does not automatically configure the optional EO worker. No release or agronomic qualification follows from this review.

Final source-bound delta snapshot:

| File | SHA-256 |
|---|---|
| `scripts/rehearse_field_source_imports.py` | `886a9aaf7a8bd0d63ccf07143096366a417d475de4960f084b87ec0b13923dd6` |
| `src/agronomy_agent/leak_guard.py` | `cbd0dcd6faf2a43236f03cdb5800470b7638e53cc0d07af5029c2c6ed789184a` |
| `src/agronomy_agent/server/services/answer_renderer.py` | `0f966caca7832e6b0bed3fb23356058a475fd1c57cec3b1d78be6ec28032247e` |
| `src/agronomy_agent/server/services/chat_service.py` | `cacc613e0c0c6b1966226ed47756dddf0964a0108bb4f06c5196a61ccebd1b2a` |
| `tests/test_field_data_rendering.py` | `415cff8a0ff28a9b469c65356e587bd63b84f46a74916155249c31c182887b87` |
| `tests/test_field_data_routes.py` | `20ef8dce3d4310d5df703dd09c37a28be7ff6fde093569061788a2ecfde2eb7c` |
| `frontend/src/FieldImageryAnalyticsPanel.test.tsx` | `6a4c8b5d8dd359f79703fb87fa58c97b373c105c88367b5b3d6b0d25a8b43bcd` |
| `frontend/src/openAgronomyMapWorkflow.test.tsx` | `5b6d3cdd9e725604ec096320e879ebacbc900eccd605c681a6577f7939fe2ac1` |
| `docs/reviews/artifacts/field-data-merge-20260927/verification.json` | `875036fb29a01243c8200adb472487e1b3fa3469bbba2c610e8b0c6246ec067f` |
| `docs/reviews/artifacts/field-data-merge-20260927/product-rehearsal.json` | `39a717094147cf61bb1741d3f617eaf4eab8063d90df56c7efa76deb727ce419` |
| `docs/reviews/artifacts/field-data-merge-20260927/product-rehearsal.md` | `8af49a211d3e0deef063d3e79c3b7cb8cd18d37d37c01255be4c1a1b2825dfa4` |
| `docs/reviews/field-data-merge-readiness-20260927.md` | `1a1b89c8c23c89e74e18a8b58eb76ab0dc42acc993bdb2b4d43b2fccfbc15b03` |
| `docs/public/operations/field-data-pilot.md` | `272c13f1f2f045b7de8d750a9c674927e96a0a92cc6a6bda4c88e59a5d2fe6ce` |
| `ARCHITECTURE.md` | `2fff5c54bfb2883a1549719d71fbb5e1e87436c117e4177ffd123befc4c59715` |
| `scripts/README.md` | `51e4f44f5a8b5949b8e0947929649635995300c0b474d81fbd74b8fd294bffc0` |
| `configs/public_repository_manifest.json` | `12d84f615487fd6f198c6454a8042f3eb41163e2b819362fcdfab4fdf0a4f3a2` |
| `outputs/field-source-rehearsal-20260927-08/receipt.json` | `d45688c539ab7d389f249e55cde54d49716d098a753849a0c664f3b49b707c0a` |
| `outputs/field-data-merge-validation/python-render-final.log` | `96b4cf69b5969a020323b499eb447ee7b7c8ec74716c505ea6062574bd98be1c` |
| `outputs/field-data-merge-validation/pilot-render-final/summary.json` | `96b568695eaca077f6ca678e44b15e8a04dd08bd26c18698514d715190f2eb5b` |

The accepted production closure sources from the earlier hash table are unchanged except for the explicitly bound renderer/guard/chat additions above. The verification receipt binds the current controls. Refresh the final public copy and runtime inventory after this review is frozen; do not treat a package containing the earlier review as the final reviewed package. The integrator must check source-exact generated artifacts and green remote CI/Mac candidate checks before merging the tested head.

Changed: this review only. Verified: repaired admission, byte/source/workspace contracts, complete rendered-answer binding, negative boundaries, and source-bound local verification evidence. Residual Risk: four documented conservative audit false positives; final generated-artifact/remote checks remain prerequisites; scientific/source-rights/geometry holds and historical raster-reference limits remain binding. Memory Delta: none.

## CI dependency-only delta — accepted, remote rerun required

**ACCEPT** the addition of `scikit-learn==1.9.1` and its synthetic-assessment comment to `requirements-phase4-ci.txt`. The Ubuntu Python workflow installs that file before running the complete backend suite. Retained run `36327015486` on candidate `4cda266` reports **six failures, 1,310 passes and three skips**; every failure is `ModuleNotFoundError: No module named 'sklearn'` from `test_imagery_assessment.py`. This is a missing CI dependency, not evidence that the scientific or numerical assertions passed.

The pin matches the existing optional imagery-model requirements and macOS constraints, and the installed local version. Root `requirements.txt` instead declares the broader compatible `scikit-learn>=1.5.0`. Installed package metadata requires Python >=3.11 and NumPy >=1.24.1, consistent with CI Python 3.12 and its NumPy 2.0.2 pin; the exercised local environment also uses NumPy 2.0.2. The affected local synthetic assessment rerun completed **17 passed, 26 warnings in 2.69s**. No runtime implementation, fixture assertion, test skip, provider request, or model-weight activation changed. All 20 prior verification control hashes still match.

| Delta/evidence | SHA-256 |
|---|---|
| `requirements-phase4-ci.txt` | `71fd6a358ba6cfdb203574e899a58343bbb78df3b4c1f916fda798d1ff39f717` |
| `outputs/field-data-merge-validation/ci-python-failure.log` | `a049f44ee9e1aaf1d3ef0202617281f5f05c4d900beac1546ae63188b7b98fc5` |
| `outputs/field-data-merge-validation/ci-dependency-local.log` | `bdeadbb1281524c99bcdbaf93c947e0b6c5a16ddc0471c019f03e0ae4cf9dccf` |

Preserve the failed remote run. The local rerun and dependency metadata do not establish a successful clean Ubuntu installation or green replacement CI. Refresh generated artifacts/public packaging for this delta, then require all remote checks on the new candidate, including the Mac candidate workflow, before merge.

Changed: this review appendix only. Verified: targeted CI dependency delta, raw six-failure diagnosis, compatible declared dependency bounds, and 17 passing local assessment tests. Residual Risk: clean remote rerun and final-head release checks remain pending; earlier documented scientific and audit limits are unchanged. Memory Delta: none.
