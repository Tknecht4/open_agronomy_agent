# Shared geospatial foundation

This package owns reusable geometry, source metadata, raster support and terrain processing. Scientific support and app policy remain explicit; a shared implementation does not imply shared authority for its outputs.

| Module | Owns | Current consumers |
|---|---|---|
| `geometry` | Complete GeoJSON topology, explicit horizontal CRS transforms, ellipsoidal measurement | Map services/analysis, vector imports, imagery validation, discovery, terrain |
| `vector_io` | Bounded GeoJSON/SHP/GPKG ingestion through GDAL/Pyogrio; source CRS and byte receipts | Boundary upload service |
| `catalog` | Raster provider definitions, metadata versus pixel access, processing support and rights references | Existing imagery provider view, source API/CLI |
| `discovery` | One bounded page from an allowlisted public endpoint; typed offline/error/empty states | Authorized saved-field API and operator CLI |
| `raster` | Fractional native-grid support, coverage mask, float64 statistics, GeoTIFF output | HLS and terrain |
| `cog` / `products` | Bounded COG ranges; shared private chip admission/publication | HLS and Sentinel-2 operators |
| `scene_quality` | Explicit index/support coverage admission and deterministic candidate ranking | Frozen scene selection operator |
| `sentinel2` | C1-specific radiometry, native multi-resolution alignment, SCL/support QA | Polygon imagery operator |
| `terrain` | Context-preserving DTM processing; SciPy focal mean, Rasterio 5 m resampling, PyFlwDir derivatives | Offline operator CLI |

Keep heavy raster/hydrology imports lazy. Those optional dependencies belong in an isolated operator/worker environment. GeoPandas/Pyogrio are serving dependencies because ZIP/GPKG upload is an existing supported product feature; native-app requirements inherit them from the container runtime list. The base service must still start and report missing raster/terrain dependencies honestly. Use Shapely/PyProj/GDAL/Rasterio/PyFlwDir for domain algorithms; app code owns limits, source roles, masks, manifests and failure states.

No automatic topology repair, multipart selection, vertical-datum conversion, DSM substitution, void filling, blanket resampling or unknown-to-zero conversion. The versioned terrain auto policy prepares actual 1 m inputs with an explicit focal mean then 5 m bilinear profile; other resolutions remain native. Native comparison and configurable focal footprint are recorded, and native source pixels are retained separately. Retain original source identity, actual raster grid, processing version and outputs separately. Hydrology uses surrounding terrain; clipping to a field is a reporting operation. Geometry support area is not a surveyed field area.

Tests: `test_geospatial_geometry.py`, `test_geospatial_vector_io.py`, `test_geospatial_discovery*.py`, `test_geospatial_raster.py`, `test_geospatial_terrain.py`, plus existing map/HLS regressions. The public operator guide is `docs/public/operations/geospatial-foundation.md`.

`imagery_selection.py` orchestrates frozen candidate plans without duplicating source processors or caches. `cog.transfer_budget` shares application-payload and request limits across an invocation; existing standalone processors retain their own limits. Selection is an operator capability, not app activation or scientific field qualification.
