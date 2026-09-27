# Bounded map experience follow-up

## Contract and reference

The user requested at least two major map/UX features plus cleanup, with review
and merge authorized after acceptance. Base is merged main `fd590b5`; work uses
`codex/map-insights` in the existing isolated UI checkout. Other active branches
and their data/imagery work remain separately owned.

## Phase and resource envelope

Owner implements map controls and insight presentation. One bounded backend
specialist implements deterministic geometry/overlap analysis; a fresh independent
reviewer checks the settled candidate. Planning estimate: 90–150 minutes including
integration, native Safari desktop/narrow QA, online/offline checks, profiling,
full tests/docs/package, CI and review repairs. Reassess after the two feature
slices work; defer additional analytical modes instead of expanding the pass.
Token/dollar usage is unavailable. No model training, paid services, imagery
acquisition pipeline, corpus activation, or new large data download is required.

## Acceptance map

| Obligation | Controlling boundary | Acceptance evidence |
|---|---|---|
| Map explorer with visual style/layer controls | Leaflet lifecycle, provider definitions, menu focus, layer state | Style switching preserves view/geometry; offline makes no tile requests; source attribution and errors visible; Safari narrow/desktop controls fit |
| Useful on-demand field insights | Validated geometry, existing official layer adapters, bounded spatial analysis, async UI state | Known geometry fixtures; geometric overlap not vertex-sampling percentages; units/method/source retained; gaps distinct from zero; stale field responses cannot replace current results |
| Clean, concise main view | Workspace/map CSS and dialogs | Features open on demand; concise labels and tooltips; detailed provenance behind disclosure; keyboard and touch-sized actions |
| Backend capabilities and performance | Existing layer catalog/intersections, new deterministic service | Installed/unavailable modes explicit; no model needed for geometry; bounded payloads/work; measured cold/warm analysis and UI load/cancel paths |
| Safe integration | Active configs, public manifest, independent review, CI | Runtime/corpus authority unchanged; full verification ladder and public package; reviewed commit equals merged tree |

Existing layer overlap values are vertex/midpoint samples, not area percentages.
They must not be relabelled as field-area statistics. New area breakdowns require
actual clipped geometry; unavailable spatial dependencies remain explicit.


## Implemented slices and measured checkpoint

Map & layers provides satellite, OpenStreetMap street, and no-tile Simple display,
a bounded catalog selection, source details, shading, scale, and text-safe feature
tooltips/popups. Layer requests include explicit IDs; an empty selection makes no
viewport query. Style changes preserve view/geometry. Inspect mode suppresses
vertex handles, and Escape closes the chooser before cancelling a drawing.

Field insights is lazy-loaded and uses a separate read endpoint. It reports WGS84
area/perimeter/location plus actual clipped mapped-zone coverage, preserving
partial, missing, offline and zero states. Unmatched layers are collapsed. Recorded
acreage and calculated area remain distinct, including an explicit mismatch note.
The backend handles validated holes/multipart boundaries; the existing editor's
single-exterior-ring boundary remains unchanged. Spatial runtime dependencies are
included in native/container requirements; older environments fail explicitly.

Observed native Safari: Streets tiles rendered with attribution while preserving
the point location; the chooser height initially clipped and was repaired with
measured canvas height and scrolling. Connected point analysis returned the Prairie
ecozone with no invented area; the example polygon returned 94.975182 ha,
234.688786 ac, and 3914.141 m perimeter, with complete ecozone coverage. The example
record's 160 ac is separate supplied data. No model was used for these results.

Four local HTTP analysis samples took 36.075, 15.143, 10.039, and 10.359 ms. The provider
cache could already be populated by Safari; this is not uncached provider latency.
Source-bound raw fixture/API samples and build sizes are summarized in
`artifacts/map-insights-performance-20260927.json`. A shading-only regression
reproduced redundant GeoJSON reconstruction (1 object became 2); after optimization
it updates vector styles in place and retains 1 construction. No timing speedup is
inferred from that operation-count check.

First full frontend validation: 263 tests plus typecheck/build passed. The initial
Python run retained 1,041 passes and 2 packaging failures caused by registering the
performance receipt before its file was written. The receipt is now materialized;
validation is being repeated on the settled tree. Failed evidence is retained in
`outputs/map-insights/python-full-initial.log`. Final QA/review/CI receipts will bind
the delivered candidate; this checkpoint is not merge acceptance.


## Independent review repair

Independent probes found that a legacy intersection roundtrip could lose a second
multipart component or a boundary point before clipping, discarded source transfer
limits/malformed features could become false complete coverage, and string or
malformed coordinates could bypass the input cap or return HTTP 500. The original
review and probes remain retained.

Local analysis now queries bounded raw envelope candidates and tests the original
geometry precisely. Remote calls preserve the existing guarded intersection path;
that path now propagates compact raw collection integrity and truncation metadata
before normalization. An automatic approval review rejected a proposed direct
online provider-query implementation because it could bypass the field-data egress
boundary. That implementation was abandoned; the guarded-path alternative succeeded
without new destinations or changed online payloads. Legacy remote multipart/holed
requests remain partial with unknown total coverage. Strict numeric shape/position
validation runs before the legacy parser or quadratic ring check.

The repaired service passed 32 focused tests, including actual local SQLite and raw
remote adapter seams. Final source-bound profiling is retained in
`outputs/map-insights/candidate-profile-final.json`; the public summary is updated
to those observations. The four connected local API samples were 117.344, 6.955, 4.617,
and 3.737 ms with potentially warm provider cache. These do not establish provider
latency or map accuracy. Earlier measured samples retain their original evidence.

Native Safari was exercised for desktop styles, point results and polygon metrics.
The user was actively using Safari later, so narrow QA used the in-app browser. Its
requested viewport required calibration; rendered DOM dimensions were 391 by 783 CSS
pixels. The chooser measured 320 px wide with an internal scroll region; document
scrollWidth equalled clientWidth, and keyboard access reached its lower controls.
The insights dialog showed boundary estimates, the recorded-acreage difference,
and source details without horizontal overflow. Full-page capture scaling was
inconsistent, so viewport captures and DOM geometry are the narrow-layout evidence.
No physical touch-device or universal browser claim is made.


The repaired frontend passes all 263 tests, typecheck and build. The pre-repair
full Python retry passed 1,043 tests. The subsequent repaired full local run was
interrupted by actual disk exhaustion while creating packaging fixtures; its
failed log and storage inventory are retained. Only this task's disposable package
and failed temporary fixture copies were removed. The final exact-candidate full
Python gate runs on GitHub's clean runner; no local full-suite pass is claimed for
that interrupted run. Public packaging uses independent APFS copy-on-write clones
to avoid another full physical duplicate, followed by the unchanged builder's
content hashes, scope checks and runtime-inventory regeneration.


## Integration with current main

Main advanced to `393b071` (the accepted foundations/typed-calculation PR) while
this pass was being validated. The map branch integrates that main before final
acceptance. Both sets of third-party notices are retained, and the generated
runtime inventory is rebuilt from the combined source. The map analysis service,
its provider boundaries and user-facing feature scope are unchanged by this
integration. The final review and CI bind the merged candidate rather than the
older base snapshot.


## Compact workspace repair pass

User feedback: the accepted insights UI still consumes too much space; continue
repairing the experience and exposing the existing backend usefully. Reference is
current main `0a942a3`; branch `codex/compact-field-workspace`, same isolated UI
checkout. Existing deployment, corpus and field-ingestion work remain separately
owned.

Scope: replace tall insight cards with a compact measurement strip and mapped-zone
rows; return boundary measurements independently of slower source lookups using the
existing geometry-only endpoint. Make the records page history-first, with focused
record/soil-test entry and contextual append-only correction actions. Preserve
source/method/partial states, record provenance, error recovery, and field isolation.
No new provider destination, calculation authority, model profile or data activation.

Owner handles insights, browser QA, integration and release; one bounded frontend
worker owns the records section and its tests. Fresh independent acceptance follows
a frozen candidate. Whole-phase estimate: 60–100 minutes including workers, repair,
frontend/backend/docs/package checks and CI; token/dollar usage unavailable. At the
first complete UI checkpoint, stop optional expansion and focus on observed defects.

Acceptance: smaller measured dialog footprint at 391px and desktop without shrinking
readable type or touch targets; geometry remains useful during slow/failed source
requests; stale requests cannot replace current field state; adding/correcting typed
records retains payload semantics and provenance; failed saves retain input and
pending saves cannot duplicate or land on a newly selected field. Browser evidence,
focused regressions, full integrated gates and source-bound review decide acceptance.


The compact implementation checkpoint is complete: large metric/location cards
become a two-value readout; location and method move into Boundary details, and
coverage rows expand into actual per-zone areas and provenance. Geometry-only and
source requests run independently, so delayed, failed or timed-out map sources do
not erase boundary metrics. Units do not refetch; selecting another layer reuses
the current geometry result. Refresh is a labelled icon beside the unit control.

Field history leads the records view. Focused record/soil-test dialogs retain input
on failure, guard pending submissions, and scope completion to the selected field.
Corrections preselect the original record and append a new event. Soil sampling
time remains explicit rather than borrowing entry time; original-report retention
is a user assertion, not an automatic assumption. Typed measurement metadata and
answer provenance remain available behind compact disclosures.

The unchanged backend's synthetic offline profile completed all cells: cold app
creation 5,925 ms, warm seeded history median 13.711 ms, and warm mock-core median
9.689 ms (five samples each). This includes no new local-model or answer-quality
claim. Five concurrent local HTTP geometry/source pairs completed with potentially
warm provider caches; these are diagnostics, not uncached provider latency or a
speedup. Final source-bound receipts and UI dimensions are retained with the phase.
Optional expansion stops here; remaining work is integrated validation, browser
repair if observed, public packaging and independent acceptance.


Browser QA measured the final collapsed insights dialog at 478 px high in a
391×783 CSS viewport, and 560×492 px in a 1200×800 viewport. Both fit without
internal or horizontal scrolling; expanded source details scroll vertically.
Native Safari also exercised the compact view against the online synthetic
Alberta example. The records flow saved an observation, a linked correction and
a typed 12.5 ppm / 0–15 cm synthetic soil result, then reloaded the history.

QA caught stacked entry buttons, secondary controls above history, and a six-pixel
soil-form overflow from a legacy input margin. Actions now share a toolbar;
secondary controls follow history in DOM order. The repaired soil dialog and form
both measure clientWidth=scrollWidth=356 px; only the dialog scrolls. The local
full backend run passed 1,147 tests; the final layout-only frontend delta receives
its own full rerun and final CI binding. Physical touch-device validation remains
outside this desktop browser pass. Public/private source authority is unchanged.


Independent review reproduced a stalled-write modal that could not close, and an
unknown sampling date being replaced by the backend's generic event timestamp in
model-facing field history. Both are repair findings, not accepted exclusions.
Modal dismissal now leaves an explicitly pending, deduplicated request running;
lost confirmation is labelled unknown and requires checking the timeline before
manual retry. The sampling repair adds explicit unknown/user-supplied provenance
and carries the distinction into UI history and bounded product context without
rewriting existing event hashes. This narrow backend correction expands the
original frontend-only scope; focused date-boundary checks and exact-source full
CI must pass before renewed acceptance. Original failing probes remain retained.
