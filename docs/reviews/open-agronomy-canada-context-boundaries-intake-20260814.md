# Canadian context-boundaries intake: inspected candidate implementation

**Status:** implemented as an opt-in, local-only candidate profile; not a default spatial layer and not a DSS change

**Date:** 2026-08-14

## Purpose and scope

This implements the compact boundary-first candidate anticipated by the offline-data plan: [`canada-context-boundaries-v1`](open-agronomy-compact-offline-data-plan-20260813.md). It supplies only geographic orientation and evidence-routing context. It does not supply a soil observation, soil test, crop-suitability result, diagnosis, farm boundary, legal determination, or management-rate authority.

The profile is intentionally external state. A clone contains the contracts, installer, validators, and test fixtures, but not downloaded government source bytes or SQLite databases. The explicit installer places raw files, lineage, derived databases, and the flat runtime pack beneath a user-selected data root.

## Official source inspection and rights

| Source ID | Official resource inspected | Raw format / CRS / geometry | Raw inspection | Rights and attribution |
|---|---|---|---|---|
| `ca_statcan_2021_provinces_territories` | [2021 Census boundary files](https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm?year=21), `lpr_000a21a_e.zip` | zipped ESRI Shapefile; EPSG:3347; Polygon/MultiPolygon | 13 valid, non-empty province/territory features; fields included `PRUID`, `DGUID`, `PRENAME`, `PREABBR` | [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence); receipt attribution: “Contains information licensed under the Statistics Canada Open Licence from Statistics Canada.” |
| `ca_statcan_2021_census_agricultural_regions` | [2021 Census boundary files](https://www12.statcan.gc.ca/census-recensement/2021/geo/sip-pis/boundary-limites/index2021-eng.cfm?year=21), `lcar000a21a_e.zip` | zipped ESRI Shapefile; EPSG:3347; Polygon/MultiPolygon | 72 valid, non-empty CAR features; fields included `CARUID`, `DGUID`, `CARENAME`, `PRUID` | [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence); same required attribution |
| `ca_aafc_terrestrial_ecoregions_v2_2` | [AAFC Terrestrial Ecoregions of Canada catalogue](https://open.canada.ca/data/en/dataset/ade80d26-61f5-439e-8966-73b352811fe6), v2.2 GeoJSON | GeoJSON/WGS84 (EPSG:4326); Polygon | 218 valid, non-empty raw polygons; 194 unique ecoregion IDs after intentional multipart dissolve; 15 ecozones and 53 ecoprovinces | [Open Government Licence - Canada](https://open.canada.ca/en/open-government-licence-canada); receipt attribution: “Contains information licensed under the Open Government Licence - Canada from Agriculture and Agri-Food Canada, Canadian Soil Information Service.” |

The compact `a` cartographic StatsCan archives were deliberately selected instead of the approximately 130 MB `b` digital-boundary variants. This candidate therefore uses cartographic generalized boundaries for routing labels, not cadastral or field geometry.

The builder fails closed for a changed raw hash, missing expected archive member, unexpected CRS/schema, null/empty/invalid geometry, non-polygon geometry, duplicate output code, or a source-entry hash mismatch. It performs no automatic geometry repair. All output geometry is WGS84 rounded to six decimal places, stored in a local SQLite database with RTree bounds.

## Pinned inputs and receipts

The exact pinned raw inputs total **22,968,231 bytes**:

| Source ID | Bytes | Raw SHA-256 | Source-entry SHA-256 |
|---|---:|---|---|
| `ca_statcan_2021_provinces_territories` | 2,777,186 | `c4dd830f8a6e9b4a1d80e71bc830ae319aaab37785cc92185e830f5e3da4714e` | `b97c42ca79bfbebed9f34e73a68addd084ac4ba176b3eeebced6c8f7f47404ae` |
| `ca_statcan_2021_census_agricultural_regions` | 6,623,754 | `17f773420e6b07555f9fc7d5b67f82460594c8be0424e86b75b63860e2c571f7` | `0b2b2503cc988e6685e7b9b01d05647c5c7d4cf8761bb7fbb11b7616f95dc2b6` |
| `ca_aafc_terrestrial_ecoregions_v2_2` | 13,567,291 | `f2c7ac1cabc601c364479c4616c245c993443ac61f6842f01a12078844a71e6b` | `199eb2dc1ae77007939b10c29376ad86af52a37d2df80eee2bfce2a4c6ba2fcf` |

Each generated `*.lineage.json` records the direct download URL, canonical source URL, source record ID, fetch time, raw bytes and full SHA-256, source-registry and source-entry SHA-256, source CRS/format, licence snapshot, attribution, and context-only boundary. The profile's install receipt binds those values to the packed database hashes.

## Local SQLite/RTree contract

Each output uses the established local spatial-service schema:

```text
metadata(key, value_json)
features(fid, code, name, properties_zlib, geometry_zlib,
         min_lon, min_lat, max_lon, max_lat)
feature_bounds (SQLite RTree)
```

The model-facing intersection allowlist is deliberately narrow:

| Layer | Stable code | Fields permitted beyond ordinary layer identity/provenance |
|---|---|---|
| Province/territory | `PR_<PRUID>` | `province_uid`, `province_name`, `province_abbreviation`, `dissemination_geography_id` |
| Census Agricultural Region | `CAR_<CARUID>` | `census_agricultural_region_code`, `census_agricultural_region`, `province_uid`, `dissemination_geography_id` |
| Terrestrial ecoregion | `ECOREGION_<ECOREGION_ID>` | `ecoregion_id`, `ecoregion`, `ecozone_id`, `ecoprovince_id` |

Raw fields such as `LANDAREA`, `SHAPE_Area`, French display labels, and any unreviewed publisher property are excluded from model-visible intersection records. Each record also carries source URL, local match reason, coverage estimate, and the explicit context-only boundary.

The runtime registers the three layers as local SQLite only. If a profile is not installed, it is omitted from default local-layer selection; an explicit offline query returns no feature plus an error and makes zero external requests. It never falls back to a remote service.

## Installed profile result

The installer completed in a separate empty data root with every official input newly downloaded:

```bash
cd "$REPOSITORY_ROOT"
PYTHONPATH=src:scripts .venv/bin/python scripts/setup_offline_data.py \
  --profile canada-context-boundaries-v1 \
  --data-root "$OAA_SCRATCH_ROOT/open-agronomy-boundary-installer-final-20260814" \
  --download --build --verify --retain-raw
```

Here `REPOSITORY_ROOT`, `OAA_SCRATCH_ROOT`, and `OAA_STATE_ROOT` are operator-selected absolute paths. Result: `status: pass`; all three source rows reported `download: downloaded`; raw lineage, derived manifests, flat pack, pack validation, and application-path probe passed. The same profile was also assembled at `$OAA_STATE_ROOT/spatial-pack/canada-context-boundaries-v1`.

| Layer | Output features | SQLite bytes | SQLite SHA-256 |
|---|---:|---:|---|
| `ca_statcan_2021_provinces_territories` | 13 | 1,794,048 | `78b3229b051eeea35a14e13fd15a54b470404692257ced2d82b28742fc9c93d6` |
| `ca_statcan_2021_census_agricultural_regions` | 72 | 4,288,512 | `ac56bbb659d55bcef82a01fc0d86dc2be642520aa914d7323e2069f0a37b141a` |
| `ca_aafc_terrestrial_ecoregions_v2_2` | 194 | 2,957,312 | `49fa44bbf31ab49d1b9e1e47d6531bb504903bc7f65ee455357e6aff448491cf` |

The complete runtime pack is **9,039,872 bytes**. The offline application-path probe returned:

- Edmonton, Alberta: `PR_48` Alberta; `CAR_4850` Census Agricultural Region 5; `ECOREGION_156` Aspen Parkland.
- Brandon, Manitoba: `PR_46` Manitoba; `CAR_4602` Census Agricultural Region 2; `ECOREGION_156` Aspen Parkland.
- Guelph, Ontario: `PR_35` Ontario; `CAR_3502` Western Ontario Region; `ECOREGION_134` Manitoulin-Lake Simcoe.

These checks establish only source-to-location intersection behavior at the test bboxes. They do not validate farm boundaries, local agronomic conditions, or recommendations.

## Request and model seam

The spatial service places the safe records in `regional_intersections`, along with layer status and a source/limitation label. For an authorized saved field, the server now creates an in-process, provenance-labelled projection through `agronomy_agent.geographic_context`. It accepts only the three local boundary layers when their intersections were recomputed by the server against bundled source bytes; client-only snapshots, unknown layers, arbitrary properties, and a client-forged projection are rejected.

`ContextPacker` renders that projection once as `Trusted geographic context` immediately after the ordinary field context. It carries only codes, names, hierarchy identifiers, fixed official layer identity, and bounded coverage. The normal chat renderer and compiled field-context renderer suppress those same three raw boundary summaries when the trusted packet is present, so the model sees each identifier once. An end-to-end product-path test confirms the provincial, CAR, and ecoregion IDs appear once in the final model message.

The adapter is intentionally **not** a retrieval-routing feature. It does not add CAR or ecoregion text to query expansion, document eligibility, or evidence ranking. Geographic retrieval must wait for sources with machine-resolvable applicability metadata and positive/out-of-region controls. See [the packet receipt](open-agronomy-geographic-context-packet-20260814.md) for the exact field projection and boundaries.

## Validation performed

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/validate_canada_geospatial_sources.py \
  --manifest data/manifests/canada_geospatial_sources.json \
  --profile canada-context-boundaries-v1 \
  --profile-manifest data/manifests/offline_spatial_profiles_v1.json \
  --asset-root "$OAA_STATE_ROOT"

PYTHONPATH=src:scripts .venv/bin/python scripts/verify_canada_context_boundary_pack.py \
  --pack-root "$OAA_STATE_ROOT/spatial-pack/canada-context-boundaries-v1" \
  --profile canada-context-boundaries-v1 \
  --profile-manifest data/manifests/offline_spatial_profiles_v1.json

PYTHONPATH=src:scripts .venv/bin/python -m pytest -q \
  tests/test_canada_context_boundary_layer.py \
  tests/test_geospatial_service.py \
  tests/test_offline_spatial_profiles.py
```

All three commands passed at the time of this inspection. The focused tests include strict property allowlisting and an unavailable-local-layer/offline/no-network fallback case.
