# Independent point imagery acceptance review — 2026-09-27

Status: **accept** for the source-bound, saved-point imagery implementation reviewed below. No open code finding remains. This is technical acceptance, not merge, publication, release, model or agronomic approval.

Candidate: `codex/point-imagery`, base `d2454360f8b384f01924794c69d324b98d5f7244`, shared managed worktree. Reviewer: independent `/root/point_imagery_review` acceptance task; actual model/run identity belongs to the parent tool receipt, not a self-asserted artifact.

The review derived the acceptance obligations from `point-imagery-api-contract-20260927.md`, the implementation plan and actual code before consuming owner conclusions. The supported result is a saved-point native HLS pixel or explicit fractional circular sample. It is not an inferred field, whole-field prediction, model admission, diagnosis or release qualification.

## Findings preserved through repair

1. **Outside-source zeros with missing nodata metadata.** A local 2×2 north-up 30 m GeoTIFF with no nodata tag, sampled 90 m east, made `_read_assets` return zero reflectance/Fmask with `invalid=False`; QA counted 900 m² clear and zero nodata. The original out-of-tile regression used a declared nodata tag and did not discriminate this failure. The repair adds a point-only native source-extent mask, versions point processing to `hls-point-sample-v2-native-grid-fractional-circle-source-extent`, and retains polygon identity. New whole-pixel and partial-buffer regressions pass. No external imagery was requested.
2. **Contradictory UI point receipts passed.** Direct execution of the actual TypeScript validator with the existing fixture accepted a native pixel declaring 100000 m², `empty_valid_area` with one valid pixel, a missing grid and a footprint around `[0,0]` for the saved Alberta point. The first repair rejects all four; bounded point-in-polygon, grid/cardinality, area and status checks were inspected. A subsequent check found an empty sample could still retain a finite index; that related index-support repair now rejects the contradiction in both Python and TypeScript, with regression coverage. Final direct execution rejected all original mutations while accepting valid pixel and buffer receipts.
3. **HTTP request provenance omitted.** Disk receipt and NPZ preserved the original nullable requested scene and dates, but `public_receipt` omitted the `request` selector. The public allowlist and contract now include it, allowing request-hash reconstruction without guessing the requested scene from the selected scene. The final HTTP regression and an independent public-receipt check reconstruct the request hash with requested scene `null`; private cache paths remain omitted.
4. **Declared buffer radius did not constrain sample area.** The analytic worker computes the right circle, but both receipt boundaries initially permitted an arbitrary smaller support under the requested radius. A backend mutation retaining radius 1500 while changing sample/valid area and index support to 900 m², with one sampled pixel, was accepted. Both validators now check circle area against the requested radius within relative tolerance `2e-4`, covering the measured polygonal-circle approximation, and constrain valid area by valid pixel support. The same mutation is now rejected. This is a receipt-consistency issue, not a request for model or agronomic validation.

5. **Float32 area reduction rejected a valid sample.** A full local analysis on a 50×50 tile used native point `(ORIGIN_X+612.032118333, ORIGIN_Y-619.100343629)`, radius 204, and cloud bits only in bounding-box cells with zero sample weight. Every sampled cell was clear. Total float32 weight was **145.25265502929688**, while the positive/clear subset summed to **145.25267028808594**; the resulting fraction was **1.0000001050499838** and apparent clear-area excess **0.01373291015625 m²**. Strict point receipt validation caused the analytic request to return `unavailable` / `ValueError`. This was reproduced through `analyze_scene`, not only by editing a receipt. The final v3 point path retains float32 stored weights, uses float64 QA/statistical reductions over positive support, and binds the accumulator type into process/NPZ metadata. The exact reproduction now returns `available`, area **130727.39413349214 m²** and valid fraction **1.0**. The added regression passes; Polygon processing and cache identity remain unchanged.

## Independent numerical observation and final correction

Before the v3 reduction repair, a local nonuniform 6×6 raster with cloud, nodata and an undefined index was sampled with a 38 m radius at an off-centre location. The result was weighted NDVI **0.28692567348480225**, matching the sample-weighted calculation and differing from the unweighted rival **0.28867626190185547**. QA-valid support was **3737.10036277771 m²**; NDVI-defined support was **2959.2183351516724 m²**. Counts agreed with the NPZ masks and positive weights. This discriminates fractional weighting and undefined-index support from a constant-value happy path.

The 1500 m maximum radius occupied **101×101** cells, with **8059** positive-weight cells; projected circle-area relative deficit was **0.00010036623921716448**. Local elapsed processing was **0.204 s** in this synthetic check, not a provider-latency or product-performance claim.

## Checks and retained failures

- Reviewer EO command initially failed before collection because the optional environment lacks pytest-xdist while repository defaults include `-n`; reran with `-o addopts=''`.
- Reviewer command: `PYTHONPATH=src outputs/imagery-env/bin/python -m pytest -q -o addopts='' tests/test_point_imagery_analytics.py tests/test_imagery_analytics.py tests/test_imagery_budget.py tests/test_imagery_store.py` → **40 passed, 1 environment failure**. The unchanged proxy test could not bind loopback under the reviewer sandbox (`PermissionError: Operation not permitted`). No assertion in repaired point processing failed. Pytest also could not update its cache in the managed worktree.
- Owner raw `outputs/point-imagery-validation/eo-extent-fixed.log` was read: **41 passed**, including that proxy test, resolving the loopback-only gap for this source-extent correction. The later v3 source is covered by the final integration evidence below.
- Earlier raw owner logs read after deriving independent expectations: `boundary-initial.log` **52 passed**; `routes.log` **49 passed**; these are preliminary, not substituted for final frozen-candidate checks.

## Coverage and holds

Inspection traced authorized saved geometry through discovery/request identity, isolated worker arguments and environment, native grid selection, fractional weights, QA/NDVI/NDMI, separate sample NPZ keys, chip/receipt/index hashes, exact read-only cache reuse and authenticated preview geometry revalidation. UI inspection covered saved/edited/unknown geometry, point mode/radius defaults, old-backend holds, scene search independent of radius, stale-request/preview invalidation and sample-specific labels.

Existing Polygon process/request/chip shapes and field NPZ names remain unchanged. Storage admission, bounded transfer and writer locking remain common dependencies; exact verified reads still precede new-write admission. Downstream research loaders require the old field mask/version, so point samples do not silently enter model cohorts. No cache eviction, runtime-data deletion, external provider call, credential use, live server operation, training or model invocation occurred in this review.

Remaining intended limits: synthetic rasters establish deterministic software semantics, not live STAC/provider availability, real field utility, positional accuracy or agronomic validity. A single selected tile can leave part of a buffer without source coverage; that support must remain nodata. Shared receipt conformance fixtures could reduce future Python/TypeScript schema drift, but no automatic boundary reconstruction, model/yield promotion or release gate is introduced here.

## Final reconciliation

The final candidate satisfies the independently derived obligations:

| Obligation | Observed acceptance evidence |
|---|---|
| Original input remains separate from support | Saved point preserved in request/sampling receipt; sample NPZ keys and area labels differ from Polygon; rehearsal keeps saved geometry unchanged |
| Native pixel and explicit radius are meaningful | Source-grid floor selection; fractional native-metre circle weights; valid/nodata/undefined-index distinction; bounds, radius-area and index-support guards |
| No false validity outside the tile or from rounding | Missing-nodata source-extent regression and exact zero-weight-corner reproduction pass on point v3 |
| Request and artifact provenance survive | Nullable requested scene/date selectors reconstruct the request hash; source/grid/sampling bind chip identity; NPZ metadata and indexed receipt agree; checksums protect stored artifacts |
| Polygon compatibility and cache isolation | Legacy Polygon request/process/NPZ contract passes; mode/radius/moved-point identities differ; exact verified cache reads precede admission |
| Authorization and stale state hold | Workspace denial and saved-geometry rechecks remain; preview uses authenticated field-scoped access; UI drops pending/stale geometry/mode/radius/provider/date results |
| Resources and egress stay bounded | Existing capped range proxy, admission lock/capacity and worker timeout/environment remain; max-radius sample observed at 101×101; offline miss performs no provider work |
| Failure and unsupported states remain honest | UI rejects malformed/contradictory point success; setup/offline/no-scene/empty/storage states remain distinct; unknown geometry remains unavailable |
| Integration and packaging | Final Python, optional EO, frontend, documentation and public-package evidence below is positive |

Reviewer rerun on the frozen source: `PYTHONPATH=src outputs/imagery-env/bin/python -m pytest -q -o addopts='' -p no:cacheprovider tests/test_point_imagery_analytics.py` → **10 passed**. Direct execution of the real TypeScript validator rejected the original oversized-area, contradictory-status, missing-grid, displaced-footprint, finite-empty-index and wrong-circle-area cases, while accepting baseline pixel and buffer receipts. Independent Python checks reject the matching radius/index contradictions. The exact real-raster radius-204 failure is repaired, and public request selectors independently reconstruct their hash. An attempted combined EO/API script first failed on absent FastAPI in the intentionally isolated EO environment; the numerical check was rerun there and public-receipt check in the serving environment. No install was needed.

The owner validation artifact [`artifacts/point-imagery-20260927/validation.json`](artifacts/point-imagery-20260927/validation.json), SHA-256 `4ed62e719c20e86f2a7184b1ae2943be5e18cb18f16d2ca85b55626d6e4891a3`, records exact commands and 19 source bindings. The reviewer independently hashed those 19 files, all seven final logs and the synthetic rehearsal receipt; every recorded hash matched. Raw logs were read, not only summarized owner conclusions:

- Main Python: **1372 passed, 3 skipped**, 191.90 s. Skips remain skips; the separate EO run explicitly covers the optional raster cases. No new live acquired-source claim is made.
- Optional EO and imagery regression selection: **107 passed**, 5.96 s, including numeric, cache, storage, research-isolation and range-proxy checks.
- Frontend: **358 passed** across 40 files; typecheck and production build passed.
- Public-doc audit: **pass**, no errors; strict MkDocs build completed. Existing dependency deprecation/advisory warnings are retained in logs.
- Owner synthetic API/browser rehearsal receipt SHA-256 `bd9c8affd0177428570c4293c815a29f5058338451c7f8a7601abcd75f9d7cb2`: both modes use exact cached v3 receipts and authenticated previews; outsiders receive 403; geometry is unchanged; 61 m misses the saved 60 m request. This was owner-operated and source-bound; the reviewer read/hash-verified its evidence rather than operating that browser or server.
- Public builder completed with **1060 files**, **1053978258 logical bytes**, manifest SHA-256 `14d75da97f13618c2e1133c7ccbef4b4c165759cfd9c68236c0099283942f872`. The reviewer verified the actual package receipt SHA-256 `4105637a7a3d51607728f38516e86254189c5f7030edf9998320a041c0ecd1cc` and compared all 19 bound implementation/test files in the package to the reviewed source. The owner will refresh the public copy after this review text changes; that is a document/inventory refresh, not a new runtime candidate.

Both Python environments report **3.12.13**; Node reports **v20.20.2**. The dependency manifests below bind the package pins. This record does not claim remote CI, live provider availability, actual satellite accuracy, model competence or release readiness.

Changed: review artifact only. Verified: frozen-source corrections, focused independent reproductions, hash-consistent integrated logs and packaged source. Residual Risk: synthetic-only acquisition evidence; unknown position/point role; partial single-tile coverage; remote/release gates remain separate. These limits do not defeat the requested bounded sample feature. Memory Delta: none.


## Final source binding

Base commit pins unchanged dependencies. The following 38-file scope binds all final changed source, tests, public contract/docs and generated inventories plus directly relevant unchanged dependency/test manifests. The review itself and append-only implementation chronology are excluded to avoid a self-reference and permit recording the outcome. Concatenate each line below with a trailing LF in this sorted order and hash the UTF-8 bytes: SHA-256 **`e24cd5f49d8c32fb514bde9ba7122c93d711164c5cd79b78cc3e4315a343c702`**. Source changes in this scope reopen the affected review; an inventory/document-only refresh should be reconciled explicitly.

```text
549f31064d8767ed4304ff1fda20d82fa1acdc09de3983d88c3f73b4d4acdf54  ARCHITECTURE.md
14d75da97f13618c2e1133c7ccbef4b4c165759cfd9c68236c0099283942f872  configs/public_repository_manifest.json
b589b3a2ffa360189af68f7d945829bcb76f195b8fb92983ffda15ace17aaada  container/runtime_manifest.json
a21011fe6b00a063853e00057ae95179400c7965f7911302a8c16a644ca859cd  docs/public/operations/field-data-pilot.md
4ed62e719c20e86f2a7184b1ae2943be5e18cb18f16d2ca85b55626d6e4891a3  docs/reviews/artifacts/point-imagery-20260927/validation.json
9171fc92d0f1f0121a10fe1f258ac35a56cd9df90cd82e79143da25003901684  docs/reviews/point-imagery-api-contract-20260927.md
79c91afc79428d4f2160f46a9f9adac605a94aec5f94dc802fe62be80dcb33cb  frontend/README.md
07597bd8800dc8335a05385e790a3a0dfe1c81a71bf46d18ed25abfba5bb1241  frontend/package-lock.json
c8586e3e458f599ef16be3614b1dcf30ecd08d5808ce7ae74c7b2a4dde5670ae  frontend/package.json
383df0d02682d50d6cb1da295d447c6b27af049dbebe7f9cfa46e7460e256743  frontend/src/FieldDataPanel.test.tsx
1d2b42a60f305903fd3c837464ee13fb1c1769005fdfdca4c8d314ca518435e1  frontend/src/FieldDataPanel.tsx
9d385bc6696dd205f6f40fab3a41c3cad5a061c5af1b112a78cb74a5a02793f2  frontend/src/FieldImageryAnalyticsPanel.css
d636df16c01d2c39813f2f46a4735e6c43c89314c9c625d87dad8dd2dcea8672  frontend/src/FieldImageryAnalyticsPanel.test.tsx
0382f9d1c5621ce9a36e25b2766f43c0d506d9f2f90588c3883e780db5ed3841  frontend/src/FieldImageryAnalyticsPanel.tsx
59c0735272eda44441f8636a0c60e8ffd99c336596bbae364f7da0a554334f0c  frontend/src/OpenAgronomyApp.tsx
d71db7e3beac1ef47f71f1f02ba040ddca14074d8f648c62cde13de45d081a02  frontend/src/openAgronomyMapWorkflow.test.tsx
9150d6d46360f3d6c8771c75df5ae0874ff6f794ec638efc043aa275be25aad4  pyproject.toml
d42928d1f57ac713591098a1dd48793872ac01d705efd0d2744e9fa2a6b48720  requirements-imagery.txt
726c21bb50ecf158450020662ca860a4ad59f8e3b19feed43348c619240ad6b7  requirements.txt
a1af8438299656bdbb47c6d685cbc9387fd1e65f7751a10fec7c4665ea858901  scripts/README.md
ce6c18e0ae90f909e801f0f936aada69865fa704d2b24bfc81b29be4b4a2e450  scripts/inspect_field_imagery.py
59498a333b184351367c085fb1a00e2fd332ec6a0c7ab90f5df7a7aa13af93b1  src/agronomy_agent/field_imagery.py
44d167d0d3aa48475caca5220567c38233e5e865e88fb830a2539cd600856436  src/agronomy_agent/imagery_analytics.py
44221209a25fdc27deffd47cf119e3d45903602f88db362a81cf903eda1b9164  src/agronomy_agent/imagery_budget.py
00def233bd0ce0eef7e927018a7ea8f865d9d0780ce4d755c76db16b5adb93a5  src/agronomy_agent/imagery_models.py
74e18e8d2db4e182a1c6914f0ebd2607b7c6a6b70766455a53dcec351e72b3bf  src/agronomy_agent/imagery_receipts.py
9c24a1f972118d9db31a4413b8f8311ef5808898dbfd60790b495759356bae24  src/agronomy_agent/imagery_sampling.py
d7a2f0bdc82fc6ab4c6280c1ade81164f4e7390a96db36963500e2a6c4981e1a  src/agronomy_agent/imagery_store.py
7f0a97316c454c91b9db72d2a6cc3a12afe9378f3f0bf33671b1b9563d816477  src/agronomy_agent/imagery_worker.py
0c2e65f2fb09ea6bcb6df5bff54ac1b65dc3b14c6065330b1cab2367ea4efb27  src/agronomy_agent/server/field_data_routes.py
e89fabdf36a071db23c98b93300309196cae44c257a36617ce3ef8b2659aea82  src/agronomy_agent/server/services/imagery_service.py
c3d84529f4e57717469c99c2cc5b602de363cc41c154e6526b14366d508e3e8e  tests/test_field_imagery.py
2981f0c406142afb19018c2b0be03981984b91c2a2948f1f2b8c797e0e4769ef  tests/test_imagery_analytics.py
ea92b16da390b83ee0a796c30585a9c3e5c586e3dc030cada7c18929c6b12762  tests/test_imagery_budget.py
febb9a3999ae2a45ae963ade7a5001251537591074e1040a5684ebe3050a6b06  tests/test_imagery_routes.py
66c333d2d10cd3df9d7f1bc7ff226c71f8ebb387ac29e25f3deb78dbb8da4c46  tests/test_imagery_store.py
45e185aed24a61df940b2db324a36e0b44f9a55cb79d520c451d2878158f4e4b  tests/test_point_imagery_analytics.py
2ccd001de3b0277641f7f83dc80c45227b8bd7307ccb0a26419bb3319210c460  tests/test_point_imagery_routes.py
```
