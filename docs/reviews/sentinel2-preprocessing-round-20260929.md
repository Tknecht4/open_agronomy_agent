# Sentinel-2 C1 L2A preprocessing development round

Reference: merged preprocessing foundation `3f0091f2a7b4283ae6140b742f302a964c844471`. This round adds a bounded polygon operator; it does not activate a new chat/training source, alter live configuration, qualify field diagnoses or expose a new app control. Precise evaluation geometry, raw pixels and local receipts remain outside the public package.

## Shared system and implemented policy

HLS and Sentinel-2 use one bounded range transport, admission/locking policy, integrity-indexed `ImageryStore`, artifact publication function, fractional support calculation, float64 statistics and index preview renderer. Provider-specific adapters own radiometry, masks, native band roles and source admission. HLS processing/cache versions remain unchanged by the shared-code extraction; Sentinel-2 has an independent process identity. There is no second cache, silent eviction or full-scene download.

The initial Sentinel-2 path accepts only the existing anonymous Earth Search `sentinel-2-c1-l2a` provider, a WGS84 polygon, and one exact scene or bounded date interval. It defaults offline and can reuse only an intact exact request. Changes to geometry, dates, cloud buffer or interior margin change identity. Date discovery requests one latest scene; no failed/empty scene is silently replaced and no field-quality ranking is claimed yet. The optional operator uses the existing imagery CLI. Point support and app UI controls remain separate next integrations.

The common analysis grid is anchored to the source 20 m SCL/NIR/SWIR lattice. Blue, green and red use their native 10 m windows, with a single area-average reduction and full contributor validity; B8A, B11, B12 and SCL remain 20 m. Categorical classes are never interpolated. No 20/60 m band is upsampled to imply finer information. NDVI is explicitly the **B8A narrow-NIR variant**, and NDMI uses B8A/B11. Neither is claimed to equal B8 NDVI or harmonized HLS across sensors/dates.

STAC band roles, processing baseline, product identity, source sun angle, dtype, nodata, scale/offset and grids are checked against actual COG headers. Nodata (DN 0) and XML-confirmed saturation (DN 65535) are masked before decoding and before averaging; reflectance is `DN × scale + offset`, once. The sampled C1 distribution encodes scale 0.0001 and offset −0.1 in STAC and TIFF headers; its product XML records quantification 10000 and BOA_ADD_OFFSET −1000 DN. Unknown/contradictory encodings are rejected instead of inheriting HLS assumptions. Quantitative processing rejects mean solar zenith above 70°. Source metadata and native per-band DN/validity windows are retained and hashed separately from processed arrays.

SCL vegetation, bare surface and water are candidate clear classes; water support is reported separately. No-data, defective pixels, shadows, unclassified pixels, clouds, cirrus and snow are excluded. The default cloud/shadow adjacency buffer is 60 m on the 20 m QA grid, with real source context and explicit missing-context exclusions. This configurable screening policy is not a calibrated universal cloud mask. Each normalized index additionally requires nonnegative reflectance pairs and a positive denominator; undefined support reasons remain separate from QA-clear area. Whole-polygon and interior statistics are reported separately; the default field-interior margin is 20 m.

## Source observations and unresolved limitations

- [Element 84 Earth Search documentation](https://github.com/Element84/earth-search) describes C1 COG assets and per-asset scale/offset semantics. An absent `earthsearch:boa_offset_applied` flag does not imply an already corrected asset.
- [Copernicus S2 products](https://sentiwiki.copernicus.eu/web/s2-products) documents baseline-dependent offsets, SCL limitations, high-solar-zenith restrictions, missing packets and swath-edge artifacts. [S2 processing](https://sentiwiki.copernicus.eu/web/s2-processing) describes upstream Sen2Cor processing. Atmospheric correction is not repeated here.
- Bounded metadata/header probes sampled baselines 05.00, 05.09, 05.10 and 05.11. Their observed scale/offset and XML special values (0 nodata, 65535 saturation) agreed; one public sample exceeded the solar-zenith threshold. These probes qualify those representations, not every granule in the provider.
- The Earth Search collection label alone does not prove every asset belongs to ESA's reprocessed Collection-1 generation. Processing baseline/product identity is recorded explicitly.
- For baselines before 05.13, Copernicus documents artificial nonzero 10 m swath-edge pixels and recommends per-band detector-footprint masks. Those masks are absent from the inspected STAC assets. Observed source-validity edge screening cannot be presented as complete detector-defect correction; this limitation travels with the product.
- SCL errors, aerosol retrieval quality, residual BRDF/topographic effects, registration and cross-date/sensor comparability remain unqualified. Source-screened output is not crop/management truth. Small fields may have no valid interior support; that result stays null.

## Verification record

Existing HLS regressions after shared-code extraction: 43 raster tests and 58 storage/API/admission tests passed. The initial extraction had a test import error; it was repaired and the failed log retained. Sentinel-2 orchestration initially passed 15 identity/offline/cache/resource/CLI tests. The source adapter passed 15 analytic grid/radiometry/QA tests, including saturation with clear SCL, four-contributor validity, cloud halo outside the polygon, invalid headers and empty interior support. Final integration and independent review remain separate gates.

The retained seed-20260928 sample contains five public USDA-ARS research support hulls, not surveyed boundaries. Source/geometry hashes were reverified before field-query egress. With each original date window and no replacements, C1 metadata returned two scene matches and three no-scene outcomes. Both matched AOIs produced bounded chips (5,226,496 COG payload bytes each), verified retained-array hashes and exact offline reuse. A subsequent saturation repair changed the processing identity to v2 so older premerge caches cannot satisfy current requests. No saturated pixels occurred in these two windows; an offline replay from verified native windows reproduced all prior arrays/statistics exactly under v2 and added zero-valued saturation masks. Synthetic regressions exercise the positive saturation case. The three no-scene outcomes remain unchanged. One site/tile, an unresolved original geometry datum and no field calibration limit the interpretation.

## Next foundation stages

1. Rank bounded scene candidates using actual valid field/interior support and freeze task-specific minimum coverage policies; retain selection/rejection reasons and missingness bias.
2. Measure registration and grid-shift sensitivity on surveyed boundaries, then introduce a library correction only where stable reference context supports it.
3. Add common-support temporal comparisons, explicit sensor/baseline effects, and composites/gap filling as products distinct from observations.
4. Qualify native 10 m NDVI as a separate product with its own support; do not silently combine its spatial detail with 20 m SWIR-derived indices.
5. Continue surveyed elevation/feature/wetness qualification for terrain. A coherent data plane does not make optical and hydrological interpretation interchangeable.

Changed: shared acquisition/publication and Sentinel-2 polygon processing. Verified: analytic tests and the bounded live/replay observations above; final acceptance is bound separately to exact candidate bytes and CI. Residual risk: source/field scientific qualification and later stages remain open. Memory delta: none.
