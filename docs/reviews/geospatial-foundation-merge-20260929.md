# Geospatial foundation integration review

Status: candidate integrated with main `923ce93b5e2de7ec9495b4ebbb0d442304b268d4`; merge checks pending. This is a public-safe summary. Detailed local research receipts, precise AOIs and source raster windows remain outside the public change, in accordance with the contributor policy.

## Change and review scope

Geometry, CRS transforms, geodesic measurements and vector imports now share one package using Shapely, PyProj and GeoPandas/Pyogrio. Existing map, imagery and local-tool consumers use the shared implementation. HLS and terrain share native-grid support, source-extent masks and float64 statistics. Polygon processing has a new process identity; unauthenticated legacy cache reads do not re-attest historical bytes.

The allowlisted, keyless-first source catalog and discovery API/CLI distinguish metadata access from pixel access. The local terrain CLI uses Rasterio and PyFlwDir on an explicitly qualified bare-earth DTM and surrounding context, retaining source elevation, conditioned elevation, fill delta, slope, flow direction, contributing area, optional TWI and validity masks. There is no automatic DEM acquisition/mosaic service, terrain UI, source activation or training admission.

Independent review accepted the original 39-file implementation with aggregate source digest `cfa5dac041267f4773bf0fb3a9e1d9496d11b27e2e45822e94381ef295536a60`. It found and verified a repair: vector drivers needed by existing ZIP/GPKG uploads now belong to the supported serving dependencies. Raster/hydrology dependencies remain optional. This integration preserves main's newer security dependency bounds and combines both public-manifest additions; it does not revert the upstream repository/release workflow.

## Retained observations

Before this main integration, the accepted implementation passed 1,711 Python tests with 26 skips, 80 optional raster/terrain tests, frontend typecheck/377 tests/build, public-doc checks, strict MkDocs and curated-package assembly. Earlier failed checks were retained locally and were superseded only after their causes were repaired. These results apply to the recorded pre-integration candidate, not automatically to a new checkout.

A fixed random sample selected five distinct evaluation research units, with one season per unit and no outcome-based replacement. All five passed geometry, application-interface and synthetic analytic-plane controls. All five also processed native 1 m public USGS source windows; three had HLS observations and two returned no scene. Independent review reproduced the draw and checked all 247 evidence files, source/output hashes, imagery reductions and edge-unknown masks. Its local evidence manifest digest is `3ab8ee32ce52ecaab832e939ace69cedc26a598ba74dec29973c3a061cb3561f`.

The AOIs were derived from sampled locations, not surveyed boundaries; their source datum remains assumed. All units share one research site, and the terrain uses one source project. Missing strict PROJ transformation grids were explicitly provisioned in the isolated experiment; no weaker transformation fallback or global installation change was used. Low-disk denials and two unavailable imagery outcomes remain recorded. A briefly overlapping retry violated planned single-worker concurrency, so serial performance and whole-run resource conformance are not claimed.

## Sources and authority

Domain algorithms come from the existing third-party libraries, not copied implementations. The local evaluation geometry source declares CC0; USGS elevation metadata and the official NOAA PROJ grid metadata declare public-domain data. Those raw data and exact locations are not included here. The source catalog retains official source and license URLs for operational checks; metadata access does not establish analytical asset access, source quality or agronomic authority.

No runtime corpus, graph, model profile, training authorization or benchmark promotion changes. A green software gate does not validate drainage anomalies, ponding depth, field wetness, source positional/vertical accuracy or catchment completeness. Canadian pixel processing, cross-site qualification, source acquisition dates, terrain sensitivity and field observation comparisons remain future work. The [operator guide](../public/operations/geospatial-foundation.md) describes supported behavior and the phased foundation plan.

## Integrated verification

Local public-documentation audit, strict MkDocs, rendered-site audit and curated-package assembly passed on the integrated source. The package contained 1,304 files. The full local Python run exhausted host disk space and is inconclusive; its log was retained. An optional-suite attempt had 79 passes and one SQLite disk-I/O failure during fixture setup; the retry is recorded separately. Only disposable package copies from this merge turn were removed to recover space. The local base environment still has cryptography 46.0.7 and datasets 4.8.5, older than main's new dependency bounds, so it does not qualify that dependency set. Protected PR CI must freshly install and test those requirements and verify source-distribution reconstruction. Independent integration review and remote CI remain required before merge.

Changed: shared geospatial foundation and its application consumers, local terrain processing, source discovery and operator guidance. Verified: prior source-bound checks and qualified sample observations above; integrated checks pending. Residual risk: acquisition automation, scientific validation and environment qualification remain distinct gates. Memory delta: none.
