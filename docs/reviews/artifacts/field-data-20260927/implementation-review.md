# Independent field-data implementation acceptance review

Date: 2026-09-27 UTC. Reviewer runtime: the independent `/root/implementation_review` agent in the visible collaboration workflow. This record does not manufacture a model/run attestation. Candidate: `codex/field-data-pilot`, base `7c502d8065a46c14c6abb462833509e5b598f2f8`, with the uncommitted implementation and repair delta identified below.

**Technical decision: accept the repaired first functional pilot slice, including the final UI delta.** Three core defects and one subsequent UI receipt-binding defect were identified and repaired during independent review. No material blocker remains within this scope. The owner must reconcile this review with the final integrated candidate and fresh regression/benchmark/browser receipts; this is not a release, training, imagery-analysis, or agronomic-validation approval.

## Independent acceptance interpretation

I derived the obligations from the approved staged program and public operation contract before reading the owner's acceptance map. The required slice is a usable, private upload → explicit review → durable field association → deterministic query → source-bound final answer, plus a repeatable development benchmark and anonymous imagery discovery. Geometry may remain unknown. Personal Earth Engine setup must be optional. The requested cleanup must preserve historical evidence. The future large training cohort, raster interpretation, yield prediction and semantic/agronomist scoring are separate stages.

| Required property | Boundary inspected | Evidence and conclusion |
|---|---|---|
| Private field authority | HTTP field authorization; session ownership; `_authorize_demo_turn_field_context`; `_with_stored_field_data`; field/workspace SQL predicates | Independently executed the real HTTP chain below. Forged table/auth/workspace claims are replaced; a different user's own session gets 403. Store reads also bind the import to the field. |
| Reviewed, bounded intake | CSV/TSV/XLSX parser, mapping validation, source/member hashes, append-only import records | Raw bytes and mapped rows retain hashes/locators. Field-identity filters and declared roles/units prevent implicit interpretation. Preview is not queryable. Malformed-XLSX defect repaired and reverified. |
| Atomicity and retry | `BEGIN IMMEDIATE`, store lock, `_cursor` commit/rollback, committed-identity unique index | Validation precedes row insertion inside one transaction; repeated same mapping returns prior committed manifest; changed mapping requires another preview. Existing focused tests exercise rollback and immutability. No concurrent-process stress claim is made. |
| Aggregation meaning and numeric validity | `value_scope`, `record_key`, query receipts, capability selection/execution | Field-season scalars cannot mean/sum; sums require record scope and a key; unknown-scope means disclose their limit. Missing/invalid counts survive. Finite-input overflow defect repaired and reverified. |
| Honest bounded snapshots | 64 KiB snapshot budget, import/column/summary/cell truncation, query grammar | Initial omitted-import ambiguity was real. Repaired selection requires an exact retained ID if imports are omitted and declines column calculations when the column index is incomplete. Partial rows remain labeled. |
| Registered result reaches the answer | Registry, planner, executor, answerability replay, deterministic generation, renderer | Independent HTTP observation: final answer equals the registered result's answer exactly, with correct committed import ID and value. No model draft is needed for supported deterministic requests. |
| Development benchmark isolation and failure retention | Fixture/gold manifest, runner inputs, separate scorer, final-answer binding, source/runtime hashes | Source-only fixture and reviewed mapping enter isolated stores; expected answers do not enter the production request. Query exceptions and production failures are retained. The product scorer rejects a replaced final answer. Latest inspected prior run has 96 query passes, 72 exact product-binding passes and 24 unscored semantic cases; repaired source requires the owner's final rerun. |
| Anonymous imagery by default | Provider inventory, network gate, polygon/date limits, fixed endpoints, asset allowlist, signed-query stripping, byte-range probe | Anonymous Sentinel-2/HLS providers precede optional unconfigured Earth Engine. Offline blocks before request. Scene-wide cloud and unknown field clear fraction are separate. Tokens are not emitted in receipts. Source inspection and existing mocks support these claims; no additional live provider call was made by this reviewer. |
| Actual UI integration and unknown geometry | `FieldDataPanel` mount, keyed field state, review gate, query controls, saved `kind:none` path | The panel is mounted for a saved field and sends field-bound routes; unknown geometry does not invent a footprint. Reviewed frontend tests cover controls; owner is separately doing live browser verification. |

## Preserved findings and repair evidence

1. **P2: omitted imports made ambiguous queries appear unique.** Initially, commit 13 tables: table 0 and table 12 contain `yield_kg_ha`, with values 100 and 999; tables 1–11 use other columns. The 12-import snapshot omits table 0. `What is the mean yield_kg_ha in my uploaded data?` returned `ready` and 999.0, despite another committed matching table. The repaired result is `clarification_required` with no result; specifying table 12's exact import UUID returns 999.0. Added tests also cover repeated filenames and an omitted column sharing an alias.
2. **P2: finite source values produced an infinite aggregate.** Two rows of `1e308` initially returned `mean=inf`, which is neither a valid numerical answer nor strict JSON. The repaired mean uses a scaled finite calculation and returns `1e308`; a declared sum of those rows raises `ValueError: numeric aggregation exceeds finite range`. The snapshot retains that aggregation as blocked. Strict `json.dumps(..., allow_nan=False)` succeeds for the mean receipt.
3. **P2: malformed XLSX escaped the validation boundary.** A valid ZIP containing only `foo.txt`, named `malformed.xlsx`, initially raised uncaught `KeyError` for missing `[Content_Types].xml`. The repaired parser raises `ValueError: invalid XLSX workbook structure`; structure, XML and truncated-archive regressions were added. Expected parser failures therefore use the route's 422 boundary. The owner is adding the direct HTTP malformed-ZIP regression.

All three counterexamples were rerun independently after repair. The repair touched the relevant parser, aggregation and conservative-selection boundaries rather than widening authority or weakening the acceptance contract.

## Executed reviewer checks

Command executed after repairs:

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q -n 0 \
  tests/test_field_data.py tests/test_field_data_store.py \
  tests/test_field_data_capability.py tests/test_field_data_rendering.py \
  --basetemp=/tmp/field-review-delta-20260927
```

Observed: **53 passed in 2.09s**. The direct counterexample script separately observed `XLSX ValueError`, unqualified omitted-import clarification, exact-ID result 999.0, finite mean `1e+308`, and sum `ValueError`.

The leak-guard adjustment was inspected and included in that run: ordinary valid JSON arrays such as `["Wheat"]` survive final rendering; explicit evaluation keys, non-JSON regex classes, quantified arrays and a later real regex on the same line remain detectable. This is a narrow exception to the regex-fragment false positive, not removal of leak checking.

HTTP reproduction used a temporary SQLite/artifact directory, `build_settings(network_mode="offline", allow_model_id_override=True)`, `TestClient(create_app(settings))`, and local-development header `X-Agronomy-User-Email: review-owner@example.test`:

1. POST `/api/demo/fields` with `{name:"Review field", field:{}, geometry:{kind:"none"}}`.
2. POST its `/data/preview` with `review.csv`, base64 of `id,yield_kg_ha\na,2\nb,4\n`.
3. Commit with empty filters, key `["id"]`, source title `Review records`, and `yield_kg_ha` declared measurement/mean/observation/record/`kg/ha`.
4. Create an owned `/api/sessions` session with title and empty consent object.
5. POST the session's `/turns` with the mean question, `mode:"agronomic_rag"`, `model_id:"mock"`, `max_tokens:100`, and that field ID. Inject `field_access_authorized:false`, `field_access_workspace_id:"forged"`, and nested `field_data:{fabricated:true}`.
6. Observe HTTP 200, `generation_path=deterministic_tool_result`, exact equality between final answer and executed `field_table_query.payload.answer`, value 3.0, expected import ID, and no fabricated marker in the trace.
7. Create a separate session as `review-outsider@example.test`; submit the same field context. Observe HTTP **403**.

This traverses the HTTP authorization and final-answer boundary. It uses an offline mock generator and does not demonstrate a language model's agronomic skill.

## Final UI delta review

The later UI delta formats numbers to ten significant digits while retaining the exact value in the element title/API, moves row locators into a disclosure, and replaces an unsupported explanatory prompt with a supported import-ID query. The filter guard correctly inspects the completed receipt's filters.

**P2, repaired and reverified:** `questionFromReceipt` initially used mutable `operation`, `queryColumn` and `selectedImport` UI state rather than the displayed receipt. Source-level counterexample: run the mean for column A, change the column selector to B without running again, then click “Ask about this result.” The result for A remains displayed but the callback asks for B. In-flight responses can similarly become detached from changed controls. The owner repaired the callback to use only the completed receipt's operation, column and import ID, withholding the button for unbindable or filtered receipts. The result also labels its recorded operation/column. The added regression changes the selected form column after a nitrate result and verifies that the callback still asks for nitrate in the original import. I reran `npm test -- src/FieldDataPanel.test.tsx`: **4 passed**, 504 ms total. The numeric formatting and provenance disclosure do not change API evidence or authority. This delta is accepted.

## Reviewed source identity

The review snapshot hashes all `src/agronomy_agent/**/*.py` plus the explicit frontend/config/dependency/CLI/pilot-manifest files and tests selected below. It is a mutable-checkout content binding, not an immutable attestation.

- File count: `145`.
- SHA-256 of sorted compact JSON path→SHA map: `323e6b4bb17a1f627f822fc9781ef2187788410cef0238471f2c0a1d1e822629` (supersedes initial core-review identity `c935db2c59ed3e57bfef825c7397619941d06639320cc32cc4c154aac667a020` after the UI/test delta).

| Repaired/critical boundary | SHA-256 |
|---|---|
| `src/agronomy_agent/field_data.py` | `ce2b09d2a31653e245a3369a2a7b9663d915e4bdce3f3c840a084f202aa56778` |
| `src/agronomy_agent/server/storage/field_data_store.py` | `c1f66388ffdaf3b8cabf6e7fa49eb77112804e03c98d82f73c29c4442d332faa` |
| `src/agronomy_agent/field_data_capability.py` | `07b8fa315808d93f7b9080c6044b59d5627e1f82dbdd2a8882f9aac0e99f6e76` |
| `src/agronomy_agent/field_data_benchmark.py` | `80542bc2859b2e165f2260d671cbe96f4440affd85c2f148fe0a73df64932e91` |
| `src/agronomy_agent/leak_guard.py` | `36752d33cad6525a354385bce9519342e681cc46fe11fb0ef217cfd64aa99ea5` |
| `frontend/src/FieldDataPanel.tsx` | `e0ebd5a1ee8be129cd5c82ea790e8136e387df85e69314308708b07aeceecb51` |
| `frontend/src/FieldDataPanel.test.tsx` | `bc6fcf2a6596d9e2db04ae40f5af0e2cc6a40476d98c6f253dd196d86004a98d` |

Reproduce from the repository root:

```python
import hashlib, json
from pathlib import Path
paths = sorted(Path('src/agronomy_agent').rglob('*.py'))
paths += [Path(n) for n in [
    'frontend/src/FieldDataPanel.tsx', 'frontend/src/FieldDataPanel.css',
    'frontend/src/OpenAgronomyApp.tsx', 'configs/model.yaml', 'configs/rag.yaml',
    'configs/runtime_profiles.json', 'requirements.txt', 'pyproject.toml',
    'scripts/build_field_data_pilot.py', 'scripts/run_field_data_benchmark.py',
    'scripts/inspect_field_imagery.py', 'data/eval/field_data_pilot_v1/manifest.json',
]]
paths += sorted(Path('tests').glob('test_field_data*.py'))
paths += [Path(n) for n in [
    'tests/test_field_imagery.py', 'frontend/src/FieldDataPanel.test.tsx',
    'frontend/src/openAgronomyMapWorkflow.test.tsx',
]]
identity = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
print(len(identity), hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
```

A later changed boundary needs a review delta or owner reconciliation.

## Limits and final reconciliation

Final core receipts independently inspected: `outputs/field-data-pilot-validation/pytest-reviewed.log` reports **1093 passed in 108.23s**; `benchmark-reviewed/summary.json` reports **96 cases, zero failed cases, 72 exact product-binding passes, 24 unscored semantic cases, stable code/environment** (summary SHA-256 `05b610024578c92e38bbe003be44c783e83b9dd6e0424678c3621c83373ae02d`). All benchmark `code_sha256_end` entries were compared with current files: **zero differences**. The owner reports a live browser upload/review/commit/mean check over 13 Akron rows yielding 567.7894685731263; I did not perform that browser interaction myself. Full frontend/typecheck/build checks after the final UI repair and final documentation/package reconciliation remain owner work. I did not duplicate the full suites. The request's first-slice acceptance does not require the future 300–500 reviewed questions, independent farms, semantic grading, training or raster/model qualification, and the public scope explicitly preserves those limits.

The cleanup was reported as manifest-verified APFS clones preserving 455 historical file paths and SHA values, with receipts under `outputs/maintenance/20260927-field-data-cleanup`. I did not independently repeat the filesystem clone/hash audit; acceptance here is the code/contract pilot review, not a new cleanup attestation. The owner must retain those receipts and the distinction between logical retained bytes and physical-space savings.

Changed | This independent review artifact only; implementation repairs were made by their owners.

Verified | Three initial core defects and one UI binding defect repaired; 53 focused Python tests and 4 focused UI tests; actual HTTP authorization → source-bound final-answer trace; outsider denial; source inspection of remaining pilot boundaries.

Residual Risk | Owner final integrated frontend/documentation/package reconciliation remains required. No agronomic, language-model, imagery-analysis, training, hosted-deployment or exhaustive parser/security claim.

Memory Delta | None. Memory was used only to index the established product-path and non-claim boundaries, then checked against current code.
