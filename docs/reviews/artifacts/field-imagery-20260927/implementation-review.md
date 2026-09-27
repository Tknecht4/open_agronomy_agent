# Independent imagery implementation review

Date: 2026-09-27. Runtime reviewer: `/root/implementation_review` in the visible collaboration workflow. No model/run identity is fabricated by this file. Candidate: managed worktree `field-imagery/open_agronomy_agent`, branch `codex/field-imagery-analytics`, initial HEAD `1ec99de`, rebased on `fd590b5` with uncommitted imagery changes.

**Final scoped verdict: accept the code, exploratory scientific evidence, portable numerical diagnostic, package-copy delta and repaired storage audit.** Four reproducible reviewer P2 issues across imagery/storage and one owner-observed UI integration issue were repaired and independently checked. The original repair findings and source bindings remain below as evidence. Final package reconciliation is the owner's remaining integration gate; no broader agronomic or deployment qualification is granted.

## Independent contract and coverage

Expectations were derived from the requested boundary contract and code/tests before reading the owner's implementation conclusions. A saved field polygon and authorized workspace must control every acquisition and preview; offline misses must cause no egress; the public asset reader must have real transfer/time/shape bounds; native 30 metre pixels, QA and fractional field area must control the numerical result; caches must bind exact request, geometry, processing and retained bytes; model features must remain separately labelled offline research with pinned code/weights/preprocessing.

| Obligation | Controlling boundary inspected | Conclusion at this checkpoint |
|---|---|---|
| Saved polygon and workspace authority | `field_data_routes`, existing `_authorize_field_data`, `imagery_service` | Analyze requires write role; preview/readiness require field access. No request body geometry/cache/worker path is accepted. Analyze and preview reauthorize and compare the stored geometry after work. Existing route tests include outsider denial and mid-request boundary mutation. |
| Offline before egress | `imagery_service.analyze`, `imagery_analytics.analyze_scene`, worker environment | Exact verified cache lookup precedes the offline return. Offline miss does not launch the worker. Worker gets a minimal environment with no account credentials or proxies; serving remains separate from optional raster/model dependencies. |
| Public allowlist and bounded acquisition | `_request_identity`, `_scene_item`, `_clean_asset`, `_bounded_cog_proxy`, subprocess wrapper | Provider/scene/date/buffer validation, fixed STAC/token endpoints, fixed HTTPS asset host/path, no redirects, 256x256 maximum chip and 150-second subprocess timeout are present. Concurrent transfer reservation is repaired and reverified; see finding 2. |
| Native-grid and field-only statistics | `_source_grid`, `_grid`, `_read_assets`, `_field_weights`, `_qa_indices` | Uses the source lattice/CRS rather than guessing a UTM zone; all bands must share the grid; nearest resampling, fixed scale, fill/mask exclusions and exact polygon-cell intersections control stats. Buffer/context extent does not enlarge field weights. Projected metre units are now verified; see finding 3. |
| Missing indices remain missing | `_qa_indices`, `_png`, frontend legend | Numerical stats exclude nonfinite NDVI/NDMI. Initial PNG incorrectly made undefined NDVI opaque at the -1 color. Finite-alpha repair independently rechecked; see finding 1. |
| Private cache integrity | `ImageryStore`, per-workspace/field cache roots, preview bytes | Hash-bound NPZ/PNG/receipt reads, receipt/index consistency, restricted filenames, symlink rejection, 0700 roots/0600 files, and direct verified-byte preview avoid a returned-path race. Legacy unverified rows are retained but not silently served. Current preview-version requirement blocks old semantics. |
| Credential/path redaction | worker environment, public receipt projection, exception handling, asset metadata | SAS is held in memory and hidden from GDAL behind loopback URLs; outward errors are not rendered. HTTP receipts omit `cache_files` and local executable/cache paths. Preview is authenticated and private/no-store. |
| Frozen offline model provenance | `imagery_models`, snapshot verification, stack preparation and chip-manifest validation | Exact model code/config/weight hashes are checked before import/load; weights-only loading; four chronological dates at/before cutoff; explicit band order, native-grid consistency, missingness and padding limits; feature role is not observation or prediction. No model execution was performed by the reviewer. Unfinished assessment quality, split claims and reported performance remain outside this first verdict. |
| UI integration and stale state | `FieldImageryAnalyticsPanel`, mount/readiness in `OpenAgronomyApp` | Requires geometry equal to the saved polygon; generation counter invalidates old analysis responses when field/geometry/readiness changes. Preview URL must exactly match this field/chip; authenticated fetch, abort and object-URL cleanup are present. Observed indices, scene cloud, field valid area and unknown values are distinguished. |

## Reproduced findings

### 1. P2: undefined NDVI was displayed as an observed -1 pixel — repaired

Initial `_png` converted NaN to -1 for color and used only QA validity plus positive field weights for opacity. A clear pixel with red=NIR=0 has undefined NDVI; the existing numerical test explicitly acknowledges that denominator case. Direct local reproduction with NDVI `[[NaN, -1.0]]`, valid `[[True, True]]`, and weights `[[1, 1]]` produced identical RGBA `[185,60,95,255]` for both cells.

The repair adds finite NDVI to alpha, introduces `PREVIEW_VERSION = ndvi-preview-v2-finite-alpha` in request/processing identity, and requires the current preview version when serving a PNG. Scientific native-v2 arrays and historical artifacts remain distinct. Direct recheck now yields `[185,60,95,0]` for undefined NDVI and `[185,60,95,255]` for true -1. UI legend/alt text includes undefined index. Final regression receipt remains part of the integration delta.

### 2. P2: concurrent ranges exceed the declared total transfer cap — repaired

The handler initially checked `state['bytes'] + Content-Length` under a lock but did not reserve bytes for an in-flight response. Two responses can pass that check before either body arrives. A socket-free deterministic reproduction set total/single caps to 4 bytes, supplied two concurrent 3-byte responses and synchronized their first body chunks. Observed state: `{'bytes':6,'requests':2,'rejected':0}` at a 4-byte cap. One handler closes only after bytes already exceeded the cap.

Reproduction replaces `ThreadingHTTPServer` with a no-op server that captures the real Handler class, and `httpx.Client` with a context-manager fixture returning status206, `Content-Length:3`, `Content-Range:bytes 0-2/3`; `iter_bytes` waits on a two-party barrier then yields `b'abc'`. Instantiate two captured handlers via `__new__`, with path `/B02.tif`, Range `bytes=0-2`, BytesIO output and no-op HTTP-header methods; invoke `_forward(head=False)` concurrently. No socket, provider or credential is involved. The first attempted local-socket variant was sandbox-blocked before execution; the socket-free reproduction above succeeded.

Repair: atomic reservation covers the advertised body plus one bounded raw chunk; in-flight reservations count against the aggregate cap. Outward requests explicitly require identity encoding, other encodings are rejected, and raw response chunks are counted and checked against the declared remainder. The socket-free concurrency regression now accepts one 3-byte body and rejects the competing range with429 at a 4-byte test budget; reservations return to zero. This regression ran in the independently executed test set below.

### 3. P2: degree/foot grids can satisfy the purported 30 metre contract — repaired

`_source_grid` initially checked affine pixel dimensions 30/-30 and a non-null CRS, but not CRS units. Direct local fixture: a 4x4 single-band int16 GeoTIFF with `crs='EPSG:4326'`, `from_origin(-120,60,30,30)`, nodata -9999 and all-one pixels. `_source_grid` accepted it, reporting `is_projected=False`, linear units `unknown`, pixel size30. Downstream weights/areas assume 900 square metres per cell, which would be false for that accepted grid.

Repair: the source grid now must be projected with metre conversion factor1, in addition to the existing lattice checks. Geographic and projected-feet fixtures fail closed; EPSG32612/32613 native-grid fixtures continue to pass. These regressions ran in the independently executed test set below.

## Additional integration finding reported by owner

The owner independently observed in the live browser that a saved polygon may omit a derived `acres` property while hydration adds it. `JSON.stringify` of the full saved/current geometry then differs despite identical coordinates, disabling imagery analysis. This was not a reviewer-executed browser reproduction. The repaired comparison uses ordered finite lon/lat coordinates, permits an optional repeated closing point, ignores derived acreage/key order, and still disables analysis after unsaved coordinates change. Hydration computes missing derived acreage. I inspected the repair and independently ran the app regression covering enabled saved/no-acreage and disabled unsaved-change states in the 53-test frontend run below.

## First-review source binding

The following 20-file path→SHA-256 map binds this **repair** verdict to the inspected mutable checkout. SHA-256 of Python `json.dumps(map, sort_keys=True, separators=(',', ':')).encode()` is `f4665dd2d16d9cc919950fc35d8cd8513c7326bdb1cc3ec62db75346cf437404`. This is content identity, not a signature or immutable execution attestation. Scientific assessment code/results are intentionally excluded until the requested final delta.

```json
{
  "frontend/src/FieldImageryAnalyticsPanel.css": "d28f46269afd9bdddc7fd4d65855d414b23892adb851077e2ba7321412b2c67e",
  "frontend/src/FieldImageryAnalyticsPanel.test.tsx": "a4ba47aa40275d6b28d1767d9032b528a1691498079de8c1930073a1f0ce609d",
  "frontend/src/FieldImageryAnalyticsPanel.tsx": "4ee051f62f3e89af2137f3aaf7874f1261fa2088c771a17f84ab8e000dc65514",
  "frontend/src/OpenAgronomyApp.tsx": "9161b18f1b09d22afd8d74f75c885c85c49cca6fb03b205f4c837e667daea471",
  "requirements-imagery-models.txt": "7e7f55d87a57e9a9ed4e4ed697ab68f47887a7d0a5c5f980240ee3f9f2dff9ae",
  "requirements-imagery.txt": "d42928d1f57ac713591098a1dd48793872ac01d705efd0d2744e9fa2a6b48720",
  "scripts/analyze_field_imagery.py": "aff4d68bd765abfc3587c2e5b2cb19c10184ab7c1f1db4cb28ade58fbbe583b6",
  "scripts/probe_imagery_model.py": "cffc661e495d2ce3ffa727b0a2a2e200393677a121efb9b9663aff9f84747ea2",
  "src/agronomy_agent/field_imagery.py": "869fa14d29a0a4ab74681297b5f941f2487209f3aaac50a297c7b1fd2f4f0a9f",
  "src/agronomy_agent/imagery_analytics.py": "c2ef7548dea0601d354713a6f3b827611b99eba78f6dd4ba320a00278e79c0d0",
  "src/agronomy_agent/imagery_models.py": "bfea8aa302f28119ace43b7dd2da23f49d0e66e2d83b7b6f3e0e6f44ae8d8b6b",
  "src/agronomy_agent/imagery_store.py": "791413c697f771f0a791534521e7320ba07fd373771332b5114b1146c49fa595",
  "src/agronomy_agent/server/app.py": "680959d88f49cf655b54bf3b174c5afe50cbf8b63e2216c786b3429e3a0dcca4",
  "src/agronomy_agent/server/field_data_routes.py": "7b34da36bc89e4529079aafa51f8fea6f9eedf5953e77b714d429d7d6d45fd9a",
  "src/agronomy_agent/server/services/imagery_service.py": "e37527010fdbe9938f3ba149cf87b556727cc03e35a1b53e2c1fdc7faff12c9a",
  "src/agronomy_agent/server/settings.py": "55b4dd5773937fbbef54740b54a5298dce943722ae0249ec30e3f8af3a4c9657",
  "tests/test_imagery_analytics.py": "771a0081d8883688bf4672860a23ffc1301f3ec7362d0e9f3544cd958d85a2ad",
  "tests/test_imagery_models.py": "17d34ae04976b6103cbedc0251164935ad3dae322123747bb0fec7a81249d230",
  "tests/test_imagery_routes.py": "bf5f92e3995e5cec5ef406cd8f6306d11d6675a5d048bcdaa662161e45142e47",
  "tests/test_imagery_store.py": "e3da79b82f9d0e2befc4ad3935704ae7f5154de927b470bf7b693ca5378ac4a3"
}
```

## Repair verification and model-loader delta

Independently executed, without provider/model calls:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src outputs/imagery-env/bin/python -m pytest \
  -o addopts='' -p no:cacheprovider -q tests/test_imagery_analytics.py \
  tests/test_imagery_store.py tests/test_imagery_models.py \
  -k 'not test_cog_proxy_counts_ranges_and_rejects_redirects' \
  --basetemp=/tmp/imagery-review-delta-20260927
```

Observed **36 passed, 1 deselected in0.97s**. The deselected test binds localhost sockets, which this review sandbox disallows; the new socket-free concurrent-budget test ran. Twenty Rasterio pending-deprecation warnings concern affine multiplication syntax, not failed assertions.

`npm test -- src/FieldImageryAnalyticsPanel.test.tsx src/openAgronomyMapWorkflow.test.tsx` from `frontend/`: **53 passed in7.05s**.

A subsequent model-loader change introduced `compare_hls_grid_crs`: equal native affine/shape may use one explicitly qualified HLS unknown-datum WKT (exact SHA-256), paired with EPSG32613, the same HLS MGRS tile, exact projected metre axes, projection parameters and WGS84 ellipsoid. Original CRS strings, `formal_crs_equal:false`, `resampling_performed:false`, unknown PROJ accuracy and unresolved-datum condition are retained. This is acceptable as a narrowly declared research lattice assumption, **not evidence of formal datum equality or operational positional accuracy**. The final scientific metric receipts must retain that limitation. No serving imagery CRS is rewritten by the exception.

After that change, independently reran `tests/test_imagery_models.py` with the same optional environment, no cache provider and `/tmp/imagery-model-review-delta-20260927`: **18 passed in1.33s**. Negatives cover wrong/altered WKT, different ellipsoid/units/zone/datum/tile, old process, false native flag, geographic axes, shifted affine and declared hash mismatch.

## Accepted-code source binding

This 21-file binding supersedes the earlier repair checkpoint after the three backend repairs, saved-polygon UI repair and qualified model-loader delta. Compact sorted JSON map SHA-256: `9b8096776d2587334d1ea104d77a7f247a5d3ab4d59b683bb97e0d47e2422514`. The active assessment code/results remain outside this code-only acceptance.

```json
{
  "frontend/src/FieldImageryAnalyticsPanel.css": "d28f46269afd9bdddc7fd4d65855d414b23892adb851077e2ba7321412b2c67e",
  "frontend/src/FieldImageryAnalyticsPanel.test.tsx": "a4ba47aa40275d6b28d1767d9032b528a1691498079de8c1930073a1f0ce609d",
  "frontend/src/FieldImageryAnalyticsPanel.tsx": "4ee051f62f3e89af2137f3aaf7874f1261fa2088c771a17f84ab8e000dc65514",
  "frontend/src/OpenAgronomyApp.tsx": "9161b18f1b09d22afd8d74f75c885c85c49cca6fb03b205f4c837e667daea471",
  "frontend/src/openAgronomyMapWorkflow.test.tsx": "cbb69972fe471574617c4e34c90dbfc488a7b347d04c3b0a73bbc6b861ea0c00",
  "requirements-imagery-models.txt": "7e7f55d87a57e9a9ed4e4ed697ab68f47887a7d0a5c5f980240ee3f9f2dff9ae",
  "requirements-imagery.txt": "d42928d1f57ac713591098a1dd48793872ac01d705efd0d2744e9fa2a6b48720",
  "scripts/analyze_field_imagery.py": "aff4d68bd765abfc3587c2e5b2cb19c10184ab7c1f1db4cb28ade58fbbe583b6",
  "scripts/probe_imagery_model.py": "8d8f99017b2fc95589d6235e05beb69152f459df43df350b2d068c12a2a6b320",
  "src/agronomy_agent/field_imagery.py": "869fa14d29a0a4ab74681297b5f941f2487209f3aaac50a297c7b1fd2f4f0a9f",
  "src/agronomy_agent/imagery_analytics.py": "9ef2252ce8b8deb475533948bdea78391149027e2872b087f31b709b6f0c12c7",
  "src/agronomy_agent/imagery_models.py": "00def233bd0ce0eef7e927018a7ea8f865d9d0780ce4d755c76db16b5adb93a5",
  "src/agronomy_agent/imagery_store.py": "791413c697f771f0a791534521e7320ba07fd373771332b5114b1146c49fa595",
  "src/agronomy_agent/server/app.py": "680959d88f49cf655b54bf3b174c5afe50cbf8b63e2216c786b3429e3a0dcca4",
  "src/agronomy_agent/server/field_data_routes.py": "7b34da36bc89e4529079aafa51f8fea6f9eedf5953e77b714d429d7d6d45fd9a",
  "src/agronomy_agent/server/services/imagery_service.py": "e37527010fdbe9938f3ba149cf87b556727cc03e35a1b53e2c1fdc7faff12c9a",
  "src/agronomy_agent/server/settings.py": "55b4dd5773937fbbef54740b54a5298dce943722ae0249ec30e3f8af3a4c9657",
  "tests/test_imagery_analytics.py": "d3fa50936f4f8139234f38c28483ba28a5379527371531bdff5512bcc0c1cd09",
  "tests/test_imagery_models.py": "25b28e411c9884952a037893fbd3853cacaeacf8ad473ecb2ee92c3a16605094",
  "tests/test_imagery_routes.py": "bf5f92e3995e5cec5ef406cd8f6306d11d6675a5d048bcdaa662161e45142e47",
  "tests/test_imagery_store.py": "e3da79b82f9d0e2befc4ad3935704ae7f5154de927b470bf7b693ca5378ac4a3"
}
```

## Scientific evidence delta

**Scientific evidence verdict: accept as the explicitly bounded exploratory assessment described in `paired-primary-assessment.md`. Code, scientific evidence and the repaired storage-audit delta are accepted; final integration still awaits the actual final package receipt.** No provider, encoder forward, readout fit or prediction call was made during this delta. The reviewer inspected the frozen contract, scoring implementation and tests, then audited retained data/predictions with independent arithmetic.

Observed checks:

- The raw CSV SHA-256 matches the pinned source. Independent grouping confirms721 source rows,575 eligible rows,29 seasons and12 physical units after excluding S2–S7 in every year. Saved prediction labels and sample counts match direct crop checks and `math.fsum` sample means from those source records.
- The immutable context index hash matches `e8917e40783353ebbb5100d21eb88d1429f7d423e292205e94869975fea89c32`. All12 selected native chip files (four each in2020/2021/2022) match their declared SHA-256. Source files, full chronological date lists, acquisition cutoffs, ROI masks and valid-mask identities agree between the21 successful spectral/encoder cases. All8 missing cases are2019 and remain explicit failures.
- Every saved training set is a subset of the same common-success cohort; physical-group folds exclude the held-out physical unit, and forward-year folds train only before2022. No raw QA answers are read by the feature/scoring path.
- Independent pure-Python recomputation of all12 common metric sets (three representations × two splits × baseline/features) agrees with crop accuracy, balanced accuracy, macro-F1, per-crop MAE/RMSE/bias and coverage. Physical-group crop counts are spectral20/21, encoder8/21, location/year11/21, majority12/21. Forward counts are6/8,3/8,2/8 and4/8 respectively. All29 versus common21 denominators are kept distinct.
- Exact Prithvi feature tuples reproduce the three reported alias groups: SCD4/SCD5-2020; SCD4/SCD6-2022; SCD5/SCD6/SCD7-2021. This is a concrete limitation of the retained representation, not a reason to discard those cases or change folds.
- The spatial-sensitivity artifact retains21 successful nominal cases,8 failures and189 successful alternatives. Independent aggregation agrees with minimum Jaccard0.5135135/0.4736842 and maximum component change0.1600534/0.254211 for15m/30m shifts. The code performs no label fitting or outcome-selected shift. These checks do not establish the source datum or shifted prediction accuracy.
- Assessment source bytes match every saved result's `code_sha256`; the current model adapter matches the feature producer's `adapter_sha256`. Original feature-payload hashes recompute exactly. Both representation provenance records retain original CRS and the qualified formal-false/unknown-datum comparisons, including when copied into per-lane result provenance.

The inference supported by these checks is narrow: the fixed spectral pipeline obtained better observed crop classification than the particular frozen Prithvi/readout pipeline on this exposed, dependent one-farm cohort. The report correctly avoids external-farm/general EO rankings, whole-field harvest yield, operational historical forecasting, stress diagnosis and tuned post-evaluation model selection. Yield regression receives the observed crop, uses distinct moisture bases, and reports failures/negative predictions rather than clipping or hiding them. The overlap of6.72km contexts,480m tokens, unresolved sampling datum, small per-crop groups and unknown historical publication times remain material limitations.

### Numerical contradiction retained

The first scoring warnings remain present. I inspected the independent audit implementation and verified its exact script hash `5f4b0480f4ae6f9bbe1d3ca75716441ceccd55f3b99cc4bf10734e6b241b42a6` and full-audit hash `dd7d34ae2af60542cfe172b6794fe19c6a2f92d53efe09a64a460e3ca42eef39` against retained files. The script independently evaluates fitted prediction arithmetic using `math.fsum` and Ridge normal equations, then compares saved metrics. Its summary reports168 prediction checks,114 Ridge fits, all finite values/classes exact, maximum absolute difference1.82e-12 and relative Ridge residual7.39e-15. I did not rerun those fits.

This supports the reported numerical predictions and Ridge solutions. It does not independently establish the logistic optimizer trajectory, and the cause of NumPy/Accelerate warnings remains unresolved. The report makes that distinction correctly. Repeated agreement is not presented as evidence that the warnings disappeared.

The exact diagnostic source initially existed only under ignored `outputs/imagery-assessment-numerics/`, with local input/tmp paths. That reproducibility gap is now closed by `audit_imagery_numerics.py`, `numerical-audit-source-lineage.json` and `numerical-audit-reproduction.md` beside this review. I independently compiled and invoked `--help`, verified the six retained artifact hashes, scanned for machine-local paths, and compared the Ridge-fit/prediction wrappers plus metrics/summary construction with the original using Python AST equality. The numerical operations match exactly; paths, output preflight, main guard and analysis-only metadata are the declared differences. Portable script SHA-256 is `705c9b4a7f0fbd15dde4e1ad0f983254a05bc18cf7ec6a3fe7b6a647fae2f55e`. No scoring or fitting was repeated. The earlier inline warning probe's missing standalone source is stated honestly rather than reconstructed as historical evidence.

### Integration evidence and remaining gate

I inspected `outputs/imagery-validation/live-api.json`: HTTP200, available native HLS observation, current finite-alpha preview version,14 ranges/786432 COG payload bytes, and authenticated PNG200 with retained hash. This is an owner-executed live check, not a new reviewer provider call. The final bounded20rem/pixelated preview and explicit30m-source-pixel caption are a display-only delta; the original PNG and numerical receipt remain unchanged.

The initial full-suite log is an interrupted failure: **2 failed,652 passed,1 skipped,2 errors**, with SQLite disk-full/unable-to-open errors and KeyboardInterrupt. It is not a completed regression gate. The owner reports concurrent test activity exhausted disk; that causal attribution was not independently traced by this reviewer. The subsequent `pytest-full-clean.log` was independently inspected and reports **1150 passed,2 skipped,26 warnings in193.03s**. Its warnings are synthetic-assessment class-label metric warnings, distinct from the retained real scoring numerical warnings. Inspected final focused receipts separately show39 optional-EO tests and12 routes/store tests passing; public-doc audit passes. Full frontend267/typecheck/build and browser cache display were reported by the owner, and the build log was inspected. The new read-only storage-audit request and final package build are separate pending deltas.

## Scientific-delta source binding

The following18-file binding covers the final scientific inputs/results/code inspected in this delta and the three display-only files changed since the accepted21-file code checkpoint. Remaining files in that earlier code map are unchanged. Compact sorted JSON map SHA-256: `cdbee61a6ea5c80fbebea905a0988774051be25f7fb6b9445a599ec133c06653`. Portable diagnostic source and storage/package deltas receive separate later bindings.

```json
{
  "docs/reviews/artifacts/field-imagery-20260927/acquisition-summary.json": "191a623455f548f9495c6594a30bc9153f62fb92589d47301766ba35bc16f331",
  "docs/reviews/artifacts/field-imagery-20260927/label-protocol.json": "2975f8a158b056715eecf226aedb7fa2dd3eae1e9ae063794447a4265584799e",
  "docs/reviews/artifacts/field-imagery-20260927/model-crs-grid-review.json": "a1dcad61aa627d2b02b49ee5500f380d50f9ded06e0ddfa76a5f909cd59aa986",
  "docs/reviews/artifacts/field-imagery-20260927/numerical-independent-audit-summary.json": "3f026a7e56c868f0a2d9e4fef1acfef11ac00901836d79a9a9df4f3c8c1503d6",
  "docs/reviews/artifacts/field-imagery-20260927/numerical-warning-audit.json": "92d6e0b05ae0cdd711c5ed0bce66c9d02798d7196a8706df953e8717967a097b",
  "docs/reviews/artifacts/field-imagery-20260927/paired-primary-assessment.json": "dda5b6fea6de3035ee9eb6f5abe9ae02e52786f7e59cf345c11ee91f7912a674",
  "docs/reviews/artifacts/field-imagery-20260927/paired-primary-assessment.md": "a8c5b9c29338b574c0e4d3a5e041c515e74c67edaaaaf594eb6cc7fa67c94ff3",
  "docs/reviews/artifacts/field-imagery-20260927/prithvi-primary-final-features.json": "f4b8768f87008196f4aa53ffed8dede4889b8b939c9bf2620c7ad8b87dc517df",
  "docs/reviews/artifacts/field-imagery-20260927/spectral-primary-final-features.json": "a3ee0caa99c4db67251ef898ad430b53c6e009a866eee70cda6b3d5f9c2462c9",
  "docs/reviews/artifacts/field-imagery-20260927/spectral-protocol.json": "0e2e4b99ea833921c0cb176dcd844c51a8d21ea2e1acbadc1f88e90ce9b19d55",
  "docs/reviews/artifacts/field-imagery-20260927/spectral-spatial-sensitivity.json": "0378da9af4933e5dd107ef1517fbd3e4489fc87e900694637f1ee7344dc9c936",
  "frontend/src/FieldImageryAnalyticsPanel.css": "dda30ba92fdd582930f877903f29de6b272674602efe7946466220da6398c2ef",
  "frontend/src/FieldImageryAnalyticsPanel.test.tsx": "fd61fc5cc228d0004bbabfbe46941da1706494d5def99611d49bde32721fe723",
  "frontend/src/FieldImageryAnalyticsPanel.tsx": "ee70c5ca74fe72e06bb5748f0adf8c93937aeaa171c7289435679324c03f361b",
  "scripts/assess_field_imagery.py": "c9a012ed92cb5e09f38ee9e5d21738d0c35dad7a6094f8b42935d1a1b2977dcf",
  "scripts/collect_imagery_assessment.py": "8ea189de0feff6f8803f28e917023d6765564b0bef6f5fb96b2646b92e758f2c",
  "src/agronomy_agent/imagery_assessment.py": "e6ec92a9ea0670652c87c606ff8a1791cde7bb3f67885ad6b8e95cb03bcf7b3d",
  "tests/test_imagery_assessment.py": "0de4968aee39627001d600c69c8af96e33a5007ec5989ff8e41476b18d52d8dc"
}
```

## Public-package clone delta

The later `scripts/build_public_repository.py` change attempts Darwin `clonefile` through ctypes, preserves file metadata, and falls back to `shutil.copy2` on unsupported platforms/filesystems. Existing package byte hashing and destination inventory validation remain in place. This changes package copy storage behavior, not runtime cache schemas, retention or retrieval.

The reviewer inspected the small delta and independently ran `tests/test_public_repository_builder.py::test_package_copy_has_independent_writes_on_clone_and_fallback`: **1 passed in 0.36s**. A separate local temporary-file call returned `clonefile_succeeded:true` and distinct inodes; changing the destination preserved the source. This proves independent copy-on-write behavior on the exercised host. It does not establish a particular physical-space saving for the complete package; the owner must retain the actual final package receipt. No source/data file was deleted or hardlinked by this delta.

## Portable-audit and package-copy source binding

The five files reviewed for these two deltas have compact sorted JSON map SHA-256 `29e6adde5c2f9ecfd7274b059edf2564b7e215824cd0c5cace01635cd2d6adfc`.

```json
{
  "docs/reviews/artifacts/field-imagery-20260927/audit_imagery_numerics.py": "705c9b4a7f0fbd15dde4e1ad0f983254a05bc18cf7ec6a3fe7b6a647fae2f55e",
  "docs/reviews/artifacts/field-imagery-20260927/numerical-audit-reproduction.md": "3a803d6a04c0f5eea9b0bbf62418385c7efc2666df1a79e8586405e67a4df50b",
  "docs/reviews/artifacts/field-imagery-20260927/numerical-audit-source-lineage.json": "f5ffb40d724be9078156aee9b9994d9a04059bb9b82e6cea53ee10bb1857b8b2",
  "scripts/build_public_repository.py": "2b21c1adaac9bad353299ce853b11ad66f44dd89c4db845d39069b2e9f7aef6f",
  "tests/test_public_repository_builder.py": "b69899de42c080be61f05fe0e47161854ee775aa8a4f8f0e60060e890b084cab"
}
```

## Storage-audit delta — accepted after repair

The new storage audit reads explicit root inventories, compressed NPZ member metadata, bounded receipts and optional SHA-256 duplicate checks. Its measured receipt and plan correctly distinguish logical byte redundancy, summed `st_blocks` allocation and unknown unique APFS physical bytes. The proposed CAS/quota/eviction policy remains a proposal; no live cache migration or automatic deletion is implemented.

**P2, repaired: unnormalized root aliases defeated the read-only output guard.** Independently reproduced with temporary files: create `root/child`, put `original source` in `root/existing.json`, and invoke `--root example=/absolute/root/child/.. --output /absolute/root/existing.json`. The initial CLI returned 0 and overwrote the scanned source because it compared resolved output against an unresolved root. A second reproduction passed the same physical directory under two labels to `audit_roots`; it counted four regular files where only two existed and reported false redundant bytes. Neither reproduction modified project data.

The repair canonicalizes roots before traversal/containment, rejects duplicate/ancestor-overlapping roots, refuses existing output destinations before scanning, and writes with O_EXCL/O_NOFOLLOW. The reviewer independently ran all nine storage-audit tests: **9 passed in 0.45s**. A separate check used a nonexistent output inside a dotdot-aliased root; the repaired CLI rejected it with `output must be outside scanned roots` and created no file. The owner confirms the six measured roots are disjoint, so their original inventory counts are retained rather than silently regenerated.

The measured receipt reports 24,554 files, 1,110,849,540 logical bytes, 14,905,451 redundant whole-file logical bytes and 64,541,492 candidate compressed member bytes, including 61,634,006 repeated band-member bytes. Whole-file/member estimates overlap and are not added. The 708,033-byte median contextual NPZ supports only the explicit four-date scaling scenario (2,832,132,000 bytes for 1,000 independent field-seasons), excluding previews/indexes/masks/environment/retention and without a claim of equivalent physical reclaim. The lifecycle/CAS/quota proposal remains unimplemented. This evidence and the read-only inventory are accepted within those stated limits.

## Accepted storage-audit source binding

The repaired audit and retained measurement/plan have compact sorted JSON map SHA-256 `bf8b2eb214a12cc9d46ad2c466d7839171d3f71a3e1cc0f174b96f4dab37fda6`.

```json
{
  "docs/reviews/artifacts/field-imagery-20260927/storage-audit.json": "411bac81e91bc5828fc24aeea3a75a77c0f95d35c89f3e4547dcca4c8a08e0c8",
  "docs/reviews/artifacts/field-imagery-20260927/storage-audit.md": "e391b1fa2f474f240b05a76b50bc895fcfe5a8ee44067c7ed855ce04cd57d806",
  "scripts/audit_imagery_storage.py": "3a5a1e3f0082a255a98f0a59f55c746691badfe9c917d4b95065693323198fbf",
  "tests/test_imagery_storage_audit.py": "afa853e0792a855b096319efa2824a5d3ee4149826c766f9da26292a1ba7dde8"
}
```

## Final package checkpoint and review freeze

The reviewer inspected the completed first package receipt: 962 files and 1,051,826,975 bytes; its internal receipt identity is `3c5983484fd3dd1876a8c2eb99e186cb6aec0dcf17b74ab88c2bf62b0823a7b8`, while the saved `public-package-receipt.json` file SHA-256 is `a0c615c7dded987302b64411b6450531c4cacd66e93e3ef90bc1226365a772ca`. This distinction avoids conflating the package identity with receipt-file bytes. The first build predates final review/docs reconciliation and cannot stand in for the final rebuild.

Immediately before this review freeze, all 45 unique files covered by the successive accepted source maps were compared with current bytes: **zero drift**. The owner will run and retain final package validation against this frozen review plus the final manifest/documentation. This record deliberately does not claim that future operation already passed. The storage measurements are read-only evidence; implemented APFS package copying is distinct from the proposed CAS/quota migration.

## Scope limits and remaining delta

No live provider, credential service, model forward, training or prediction call was made by this reviewer. The three reproductions used local arrays/files or mocks. The repaired code now has sufficient evidence for this scoped engineering verdict; no unreviewed scientific outcome is promoted by it.

The code and scientific-evidence reviews above do not relabel reported checks as reviewer-executed checks. Full integration still requires the actual final package receipt. No broader performance, deployment or agronomic qualification is granted.

Changed | Independent review artifact only; no production files edited.

Verified | Four reviewer counterexamples repaired; 36 initial focused Python tests, 18 model-loader delta tests, 53 frontend tests, nine storage-audit tests and one package-copy test; source/feature/fold identity, raw sample-mean labels, all 12 saved metric sets, failure denominators, aliases and sensitivity summaries independently checked. Portable numerical diagnostic and package-copy independence verified; clean full-suite completion and first package receipt inspected.

Residual Risk | Final package reconciliation remains open; unresolved numerical-warning cause and datum assumption remain explicit. Scientific results are exposed, dependent one-farm evidence only. Proposed CAS/quota/eviction is not implemented.

Memory Delta | None. Prior memory supplied only an index to product/provenance boundaries, checked against this worktree.
