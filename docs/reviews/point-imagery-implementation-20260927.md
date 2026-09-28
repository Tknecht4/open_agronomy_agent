# Point imagery implementation and coordination

Goal: saved point locations can support an explicitly scoped satellite sample,
without becoming field boundaries. User authorized backend implementation here,
frontend implementation in the "Plan a UI redesign" chat and communication on
one shared branch. Base: `d245436` (PR 9 merge), branch `codex/point-imagery`.

## Ownership and resource checkpoint

The owner controls backend, tests, API contract, operator docs and generated
inventories. The UI chat owns `frontend/**` only and reports focused checks;
the owner integrates and commits. One optional bounded raster specialist may
own the analytic core with explicit file ownership. A fresh independent review
checks the stable implementation before acceptance. Estimate: 60–100 minutes
including integration/review, excluding unpredictable remote CI. No new model
training, account setup, bulk download or external imagery request is needed.
Reassess scope if implementation exposes unrelated defects; preserve failures.

## Binding decisions

- The saved Point or Polygon is the input geometry. A computed sampling support
  is separate and never overwrites that saved geometry, acreage or source labels.
- Existing polygon processing/cache identities remain readable. Point sampling
  has a distinct version and includes mode/radius in request identity.
- Point pixel mode uses the containing native HLS 30 m cell, with deterministic
  grid-edge selection. Buffer mode uses an explicit 15–1,500 metre radius in the
  source projected metre CRS and fractional cell intersections. Neither is
  interpreted as whole-field coverage or an inferred boundary.
- Point modes reject polygon context `buffer_m` and 224-pixel model contexts;
  those have different purposes. Statistical support, display context and model
  input context must not be silently interchanged.
- The original coordinate, footprint, native grid, radius, pixel counts, QA and
  unknown positional uncertainty remain in the receipt. A farm entrance is not
  assumed to be a georeferenced crop sample.
- Existing auth, saved-geometry rechecks, offline behavior, bounded transfer,
  disk admission and integrity-checked previews remain binding. Tests use local
  synthetic rasters and mocked discovery, not new public/private location egress.
- Source-only field records and benchmark labels remain separate. This work
  does not establish point-to-field-yield accuracy, current-year monitoring,
  model inference, diagnosis or boundary reconstruction.

## Acceptance map

| Obligation | Check |
|---|---|
| Saved point usable | HTTP/UI point request reaches one native pixel or chosen sampling buffer |
| No invented field | Point receipt contains sample area and explicit limitation, never field acreage/coverage |
| Correct support | Synthetic gradients/clouds/nodata verify selected pixels, fractional weighting and edge convention |
| Stable cache | Mode/radius/moved-point identities differ; old polygon cache stays usable; no stale preview after geometry change |
| Private boundary | Workspace denial precedes access; no caller geometry override; worker narrow environment unchanged |
| Storage bounds | Existing admission still precedes imagery work; exact verified cached reads work below disk reserve |
| Honest labels | UI wording/preview follows returned scope; unset geometry remains unavailable |
| Integration | Focused tests, optional EO tests, full settled Python/frontend/docs/package gates and independent review |

Changes and observed results will be appended here. Historical PR 9 research
receipts remain frozen.

## Systems review and implementation findings

The persisted field remains the input record; sampling footprint/radius, source
grid and uncertainty belong to the imagery receipt. The existing imagery
SQLite/RTree index can index the actual footprint while `geometry_hash` binds
the original point, so this change does not require another spatial database
or a destructive schema migration. Point requests preserve nullable requested
scene/date selectors separately from the selected scene, and reconstruct their
request hash before cache/preview reuse. Old polygon processing identities
remain unchanged. Observation, model output and interpretation stay separate.

Point discovery uses GeoJSON `intersects`, supported by the
[OGC STAC API Item Search specification](https://docs.ogc.org/cs/25-005/25-005.html).
Public research lookup query: `site.github.com/radiantearth/stac-api-spec
item-search intersects GeoJSON geometry Point`. This lookup sent no field data;
all implementation acquisition tests use local synthetic rasters/mocked STAC.

Review identified and retained these repairs rather than treating every
successful numeric calculation as a valid user result:

- Source COGs without nodata metadata can fill out-of-tile reads with zeros.
  Point support now checks the native source extent explicitly; missing tile
  coverage remains nodata and can never become a clear zero observation.
- Receipt boundaries must check mode/grid/area/count/status, footprint
  containment, radius versus circle area, and per-index defined support. The UI
  must not display a value beside an empty-observation status.
- Float32 weighted sums can put a mean just outside uniform extrema, or a valid
  area slightly above total support when only zero-weight corners are excluded.
  Point reductions use a separately versioned numerical contract; realistic
  numerical tolerance is required for extrema without clamping source values.
- Client and server receipt checks duplicated assumptions. Shared conformance
  fixtures are a useful later maintenance improvement; the current gate uses
  identical required fields and explicit matching negative cases on both sides.

Boundary inference, point-location purpose/accuracy intake, multi-tile mosaics,
seasonal time series, model/yield evaluation and automatic agent use of imagery
remain separate work. They require their own support/availability/label
contracts; a point buffer is not an adequate substitute for those decisions.

## Settled validation

The [validation receipt](artifacts/point-imagery-20260927/validation.json) binds
1,372 passing Python tests (three optional skips), 107 optional EO tests,
358 frontend tests, typecheck/build, public docs and strict MkDocs. All new
imagery acquisition in this phase used synthetic local rasters. The browser
confirmed the default native pixel, an explicit 60 m buffer, sample-specific
QA/indices and authenticated previews; changing to 61 m cleared the old result
and returned an offline cache miss. Restoring 60 m reused its own receipt.
Both API responses reconstruct their original request hash and leave the saved
point unchanged; another actor cannot retrieve the previews.

Implementation and UI ownership stayed separate in the shared branch. The
independent review retains initial failures and their corrections. Final public
packaging and exact-commit remote checks remain release gates; local tests do
not establish real-world point accuracy or field representativeness.
