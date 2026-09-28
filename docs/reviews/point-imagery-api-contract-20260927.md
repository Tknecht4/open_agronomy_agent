# Point imagery API contract

Implementation contract for shared `codex/point-imagery`, additive to PR 9.

## Request and readiness

Existing `POST /api/demo/fields/{id}/imagery/analyze` keeps `provider_id`,
`start_date`, `end_date`, optional `scene_id` and polygon context `buffer_m`.
Add optional `sampling_mode`: `field_polygon`, `point_pixel`, or `point_buffer`;
and optional `sample_radius_m`: strict integer 15–1500, required only for buffer.
Omitted/null mode resolves to field_polygon for a saved Polygon, point_pixel for
a saved Point. Invalid geometry, mode mismatch, radius outside buffer mode,
nonzero point `buffer_m`, or point model `context_pixels` returns validation
failure before provider access. Geometry comes only from the authorized field.

`GET .../imagery/analytics` adds `sampling_modes` containing all three modes and
`sample_radius_bounds_m: {min:15,max:1500}`. Existing setup/network/storage fields
remain. Older backends without these keys support polygon UI only.
`POST .../imagery/search` keeps its existing payload and accepts saved points;
it searches at that location, independently of the analysis radius. Scene-cloud
percentage remains scene-wide. No sample pixels are computed by scene search.

## Successful point response

Statuses, source, `zonal_stats`, grid, authenticated preview URL, hashes and
cache fields remain. Point `available`/`empty_valid_area` responses MUST include:

```ts
request: {
  provider_id: string;
  scene_id: string | null; // original requested selector, not necessarily selected scene
  start_date: string | null;
  end_date: string | null;
  buffer_m: 0;
  context_pixels: null;
  sampling_mode: 'point_pixel' | 'point_buffer';
  sample_radius_m: number | null;
};
sampling: {
  schema_version: 'imagery_sampling.v1';
  mode: 'point_pixel' | 'point_buffer';
  support_kind: 'native_pixel' | 'point_buffer'; // matches mode respectively
  original_geometry: {type:'Point'; coordinates:[number,number]}; // WGS84 lon,lat
  footprint: {type:'Polygon'; coordinates:number[][][]}; // WGS84 sample support
  footprint_crs: 'EPSG:4326';
  sample_radius_m: number | null; // null for pixel; exact requested buffer radius
  native_resolution_m: 30;
  pixel_count: number;       // cells intersecting support
  valid_pixel_count: number; // subset passing cloud/nodata QA; NDVI may be undefined
  positional_uncertainty_m: null; // unknown, never inferred zero
  point_role: 'unspecified'; // saved pin is not assumed to mark crop/interior
  area_basis: 'native_grid_projected_metres';
  edge_policy: 'containing_pixel_floor';
  limitation: string;
};
qa: {
  sample_area_m2: number;
  valid_area_m2: number;
  valid_area_fraction: number | null;
  excluded_area_m2_by_reason: Record<string,number>;
  nodata_area_m2: number;
  overlap_note: string;
  // NO field_area_m2 for point modes.
};
```

Buffer statistics use fractional cell intersections in native projected metres;
the circle is a sampling footprint, not a field boundary. Pixel mode uses the
containing native HLS cell with a deterministic floor convention. Out-of-source
coverage stays unavailable/nodata, never valid zeros. Undefined index values are
null and transparent even when reflectance passes QA. No whole-field yield,
diagnosis, field-clear percentage or actual field acreage is implied.

Polygon receipts retain their existing shape/meaning and may omit `sampling`.
This compatibility rule MUST NOT apply to points: success with missing,
malformed or contradictory sampling metadata must fail closed in the UI.
Mode/radius must match the request. Request/geometry changes clear old previews.

`geometry_hash` names the original saved input. Request/chip identities separately
bind mode/radius and the actual source grid/support. Receipt integrity covers
sampling metadata. Preview delivery checks workspace and saved input geometry;
point-to-polygon upgrades cannot retrieve old point previews. Statistical
support never updates saved geometry or acreage.

The point request selector is preserved in the stored receipt, NPZ metadata and
HTTP response. It includes no token or URL; paired with the original geometry
and processing version it allows request-hash reconstruction. `grid.width` and
`grid.height` are positive integers at most 256 (both 1 in pixel mode), and its
resolution is 30 m. Pixel mode area is 900 m². Status, valid count and area must
agree, and the sample footprint covers the original point, including edges.
Buffer sample area agrees with pi times radius squared within relative 2e-4
(absolute 1e-3 m²); the 256-segment circle has about 0.0001004 relative area
deficit. Valid area cannot exceed valid-pixel count times 900 m². Each index's
defined support is bounded by QA-valid area; zero support requires null
mean/min/max, while positive support requires finite ordered min/mean/max.
Ordering tolerates float32 weighted-sum error of 1e-6 times the largest of 1 and
the absolute min/mean/max. Values are not clamped or silently replaced.

## UI requirements

- Allow saved unchanged points; block unknown/unsaved geometry.
- Default **Pixel at location**. Optional **Area around location** reveals radius;
  suggest 60 m only after selection, without presenting it as field size.
- Point labels say sample area, clear sample area and valid sample fraction.
  Polygon labels remain field-specific. Point preview captions/alt describe a
  sample with native resolution and potential neighboring land cover.
- Field ID, saved point/polygon, unsaved edits, mode/radius, provider or date
  changes clear results; keep cancellation and authenticated preview behavior.
- Scene search is discovery at the saved location, independent of sample radius.
- Preserve setup, offline miss, no-scene, empty-valid-area, unavailable, busy and
  storage refusal. Tests use fixtures and make no external requests.
