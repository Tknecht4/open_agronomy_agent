# Geospatial preprocessing and scientific QA development round

Reference: merged geospatial foundation at `f2fb44ab468ab57deb2416b71a36b8d758a93688`. This is a processing implementation and qualification plan, not evidence of agronomic accuracy. Private evaluation coordinates, pixels and raw receipts remain outside the public package.

## Implemented scope

The terrain operator now defaults to a configurable 5×5 focal mean on actual 1 m DEM inputs, followed by bilinear 5 m resampling before slope, conditioning, D8 routing, contributing area and optional TWI. SciPy and Rasterio perform these operations. Other resolutions remain native; an explicit native override supports comparisons. Full real-data halos, no-void admission, native/output cell budgets, source-anchored grids and versioned provenance prevent padded borders or missing data from being interpreted as terrain. Native pixels, prepared elevations, conditioned elevations and the smoothing delta on a common 5 m grid remain distinct artifacts.

The HLS development slice checks actual raster radiometry and QA encoding, separates clear support from index eligibility, and keeps processing/cache identities versioned. New v4 chips also retain pre-QA encoded source windows and source-invalid masks, bound to chip identity, so revised QA can inspect previously excluded pixels within those windows. The [satellite audit](satellite-preprocessing-audit-20260929.md) accompanies the final candidate. Atmospheric correction, nadir BRDF normalization and HLS bandpass harmonization already happen upstream; repeating them locally would change the meaning of the product. See [NASA HLS atmospheric correction](https://hls.gsfc.nasa.gov/atmospheric-correction/) and [BRDF normalization](https://hls.gsfc.nasa.gov/brdf-adjustment/).

Optional terrain/imagery dependencies are explicitly installed in backend CI so scientific raster regressions no longer silently skip for lack of the optional environment. The production service retains lazy imports; this does not enable imagery processing or alter a live deployment.

## Staged foundation plan

| Priority | Gap and consequence | Next implementation and acceptance evidence |
| --- | --- | --- |
| Now | High-resolution DEM noise contaminates every derivative | Focal preparation before derivatives; source retained, analytic/noisy/void/edge regressions and paired seeded AOI runs |
| Now | Catalog declarations alone do not establish HLS pixel encoding; QA-clear area is not usable index area | Actual-header validation, source-specific QA decoding, explicit index eligibility and support reporting, receipt/cache versioning |
| Next | Source quality, processing baseline, radiometric offsets, resolution and masks differ between sensors | Separate Sentinel-2 L2A adapter on the shared acquisition/raster core; metadata-derived scale/offset, SCL and defect masks, validated cloud/shadow policy, explicit 10/20/60 m band roles and one controlled continuous-data resampling step; never interpolate class masks |
| Next | Small fields and field edges can be dominated by mixed pixels or registration error | Record effective spatial support and valid interior support; test grid/subpixel shifts on surveyed boundaries. Assess AROSICS only on sufficiently large, stable, cloud-free context; do not fit registration to a tiny uniform crop chip |
| Next | Scene cloud percentage does not select the best field observation | Rank bounded candidate scenes by actual field clear/index support and acquisition date; preserve no-scene and rejected-scene reasons. Freeze minimum-support policies by task and validate missingness bias |
| Next | Temporal means compare different clear pixels and may mix sensors/processing generations | Preserve observation dates, sensor, baseline, common-support comparisons, radiometric QA and uncertainty; add explicit compositing and gap-fill products distinct from observations. Never smooth away a management event or label an imputation as measured |
| Qualification | TWI depends strongly on grid, slopes, routing, outlets and complete catchments | Compare windows and focal footprints; then qualified MFD/breaching alternatives, vertical uncertainty, culvert/ditch/tile-drain evidence and observed wetness. DTM hydro-flattening does not imply hydro-enforcement |
| Qualification | Evaluation hulls are not surveyed boundaries or independent sites | Admit surveyed Canadian/US fields under source/rights/provenance contracts; use independent regions/seasons, field data and sensor QA audits before model or anomaly claims |
| Later | Radar and aerial imagery require different physics | A separate SAR path for calibration, noise masks, terrain normalization, layover/shadow and justified speckle treatment; aerial RGB imagery remains uncalibrated unless calibration evidence is supplied |
| Shared infrastructure | Recipes and products can drift across app consumers | One versioned processing specification, immutable acquisition/product hashes, per-band/per-pixel QA and support, reproducible libraries, cancellable bounded jobs and a private product index over existing storage |

The sequence prioritizes correct input semantics and validated task-specific methods. More correction stages are not automatically more accurate. No new paid service or API key is needed for this implemented round. Library candidates for later phases include PySTAC Client for catalog conformance, Rasterio/rioxarray for grids, odc-stac or stackstac/Dask for justified cubes, and AROSICS for measured registration problems; each enters only with a qualified workload and regression evidence.

## Source-specific scientific anchors

- [NASA HLS v2 guide, April 2026](https://lpdaac.usgs.gov/documents/1698/HLS_User_Guide_V2.pdf): encoded reflectance, fill, QA bit meanings and product processing.
- [Copernicus Sentinel-2 product specification overview](https://sentiwiki.copernicus.eu/web/s2-products): BOA_ADD_OFFSET and processing-baseline-dependent quality masks. An HLS multiplier cannot be reused as a generic Sentinel-2 radiometry rule.
- [GFZ AROSICS documentation](https://danschef.git-pages.gfz-potsdam.de/arosics/doc/usage/global_coreg.html): measured shifts against a suitable reference, not assumed subpixel agreement.
- [USGS hydro-flattening reference](https://www.usgs.gov/ngp-standards-and-specifications/lidar-base-specification-appendix-2-hydro-flattening-reference): topographic versus hydrologically enforced/conditioned surfaces and culvert limitations.
- [Copernicus Sentinel-1 products](https://documentation.dataspace.copernicus.eu/Data/Sentinel1.html): source product/processing semantics must be checked before adding radar correction or speckle stages.

## Observed development evidence

Terrain-focused regressions: 41 passed in the isolated optional environment. The paired data exercise used the same seed-selected five research AOIs and retained USGS 1 m windows as the earlier foundation evaluation, without new acquisition or outcome-based replacement. Native, 5×5 and 9×9 profiles at an explicit 80 m context completed 15/15 runs, with source/output hashes and downstream edge masks verified. The reduced context left room for a real preprocessing halo inside the previously acquired windows; it is not a claim of complete catchments.

One initial metadata assertion incorrectly expected a standalone TIFF tag rather than the shared writer's `metadata_json` field. The test was corrected to inspect the existing metadata contract; the failed log is retained privately. Field comparisons are software/sensitivity evidence only: one site/tile, sampled-support hulls, an unresolved original geometry datum assumption, no surveyed vertical truth and no wetness calibration. Final integration and independent review outcomes are recorded below when observed.

### Integration observations before final review repairs

The full local backend suite passed 1,736 tests with 31 skips in the base environment; optional raster contracts were exercised in the isolated geospatial environment. The frontend passed typecheck, 378 tests and production build. Public documentation audit, strict MkDocs build and curated public-package assembly passed. The first broad optional-only selection also pulled in two unchanged serving-adapter geometry tests; those failed for absent PyYAML in the deliberately narrow environment and passed in the full base suite. A subsequent raster-only run required loopback-server permission for its existing COG transport test. Failures remain in the private verification logs; they were not algorithm failures.

Three exact previously selected public USDA-ARS research S30 scenes were reacquired through the v4 pipeline with 786,432 COG payload bytes each. All returned available, retained int16 raw DN and boolean source-invalid masks, and passed exact offline reuse. Two prior no-scene outcomes remained without replacement. This is limited live provider compatibility evidence, not general L30/S30 or field scientific validation. Public dataset provenance was reverified before egress; no private farmer boundaries or records were sent.

Independent review identified a contradiction that per-field QA bounds alone did not reject: an index could simultaneously report full valid support and full exclusion for negative reflectance. Backend and frontend now require each index's valid support plus its disjoint undefined-area reasons to equal QA-clear area. Direct regressions reject contradictory, missing and malformed v4 reason partitions. The repaired slice passed 43 HLS raster tests, 52 point/storage/API tests, frontend typecheck and 80 imagery component tests; final integrated acceptance is recorded in the source-bound review/CI evidence.
