# Field uploads and public imagery

The [geospatial foundation and terrain guide](geospatial-foundation.md) describes shared GIS/raster contracts, additional keyless source discovery, and the optional local DTM terrain processor. HLS polygon processing now uses v3 source-extent masking and float64 support; historical research v2 gates are unchanged.

Reviewed tables now connect to persisted fields, deterministic queries,
conversational answers and evidence traces. Supported files are CSV, TSV,
delimited `.tab` files and one-sheet XLSX workbooks up to 8 MiB. Scanned
reports, multi-sheet workbooks and automatic column interpretation remain
future work.

## Import and query

1. In **Fields**, create and save a named field. A location is optional;
   leave it unknown when the source has no real geometry.
2. In **Field data**, choose a table. Review columns, row counts and source
   locators. Choose Latin-1 explicitly if UTF-8 decoding fails.
3. Review source title/license/citation, exact field/season filters, row key,
   units and column roles. Source claims remain user-supplied metadata, not
   independent rights or measurement verification.
4. Set aggregation and value scope. Values applying to a whole field/season
   may be listed uniquely, but cannot be summed or averaged as independent
   measurements. Sums require record scope and a unique nonempty row key.
5. Confirm the mapping and import. Preview-only uploads are not answer-visible.
   Committed mappings are immutable; preview again to change them. Exact
   repeated commits are idempotent.

The query panel supports exact filters, rows, counts, means, sums and unique
values when the mapping permits them. Results preserve missing/invalid counts
and source coordinates. Means are unweighted record means, not automatically
area-weighted field yields. Formula cells and malformed tables fail validation.

Conversation supports narrow unfiltered requests with exact column names:

```text
How many records in my uploaded data?
What is the mean yield_kg_ha in my uploaded data?
List unique crop in my uploaded data
Show rows from my uploaded data
```

Name a filename or import ID when multiple imports match. Ambiguous columns,
unknown units, undeclared aggregation, weighting, compound questions and
natural-language filters require clarification or an explicit table query.
Only a bounded snapshot reaches the agent; source tables stay in private
SQLite. Truncation remains visible. Uploaded model outputs and regional
priors cannot become observed field evidence through answer generation.

## Imagery without a personal account

Scene search uses a saved WGS84 point or polygon and explicit dates, sending
those inputs to the selected public source. Offline mode blocks network access.
A point locates a sample; it does not establish a field boundary or acreage.

| Provider | Personal account | Current capability |
|---|---|---|
| Sentinel-2 C1 L2A, Earth Search/AWS | No | Discovery and anonymous COG access |
| HLS S30/L30 v2, Planetary Computer mirror | No | Discovery, COG access and optional single-scene QA/NDVI/NDMI using a public short-lived SAS token |
| HLS, Google Earth Engine | Required | Optional declaration; credentials and execution are not configured |

Source rights and hosting access are separate. The catalog preserves license
links and hosting `proprietary` labels where present. Tokens are not saved in
traces. Scene search shows acquisition dates and **scene-wide** cloud
percentage. The optional HLS worker reads bounded native 30 m imagery over a
saved field polygon, applies the HLS quality mask, and reports field clear-area
coverage plus observed NDVI and NDMI with source and processing hashes. Its
authenticated preview shows field-only NDVI. A visual/context buffer does not
expand the polygon used for field statistics. These spectral observations are
not diagnoses, treatment effects, yield estimates or predictions. Empty valid
area remains an explicit result.

For a saved point, choose **Pixel at location** to inspect its containing native
30 m HLS cell. **Area around location** uses an explicit 15–1,500 m radius and
weights intersecting cells by their overlap with that sampling circle in the
native projected CRS. The selected pixel or circle can include other crops,
roads or uncropped ground. Point results report sample area and valid sample
fraction; they never report field area or whole-field coverage. Positional
uncertainty and the point's role remain unknown rather than being guessed.

The receipt preserves the original point separately from its actual sampling
footprint, radius, grid, quality mask and pixel counts. Counts passing QA can
still have an undefined index denominator; such indices remain unavailable and
transparent. A point-to-polygon upgrade creates a different analysis identity.
Moving or editing geometry, mode, radius, provider or date clears the displayed
result. Save geometry edits before asking for new imagery.

### Optional isolated HLS worker

Install the raster worker in a separate Python 3.12 environment outside the
checkout; the normal serving environment does not need raster/model packages:

```bash
python3.12 -m venv /absolute/path/to/imagery-venv
/absolute/path/to/imagery-venv/bin/python -m pip install -r requirements-imagery.txt
export AGRONOMY_AGENT_IMAGERY_CACHE_ROOT=/absolute/path/to/private-imagery-cache
export AGRONOMY_AGENT_IMAGERY_PYTHON=/absolute/path/to/imagery-venv/bin/python
```

Create the cache directory on private local storage outside the repository.
Both settings are required for the workspace analysis panel. The worker gets
only the saved input geometry and bounded request, runs with a narrow environment
that excludes normal application credentials, and keeps public HLS access tokens
in memory. It cannot analyze unsaved geometry or invent a missing location. With
`AGRONOMY_AGENT_NETWORK_MODE=offline`, only an exact verified cached analysis
can be reused; online requests send point/polygon and dates to the public catalog
and request the required raster byte ranges.
The cache is private field-scoped state, not a public source or model profile.

In **Fields**, save a point or polygon, then open **Observed satellite indices**
to choose HLS S30 or L30 and a date interval. The panel reports missing setup, offline cache
misses, no scene, and unavailable data explicitly. The receipt shows valid
area, excluded QA area, source item and band identities, dates and hashes;
inspect these before comparing fields or seasons.

List providers without network access:

```bash
PYTHONPATH=src .venv/bin/python scripts/inspect_field_imagery.py --providers
```

For a local GeoJSON Point/Polygon/Feature, find two HLS scenes and probe up to
16 KiB of the first red-band COG:

```bash
PYTHONPATH=src .venv/bin/python scripts/inspect_field_imagery.py \
  --geometry field.geojson --provider hls-s30-planetary-computer \
  --start-date 2025-06-01 --end-date 2025-06-15 --limit 2 --online --probe B04
```

For a separate command-line analysis of one HLS scene, use the isolated worker
Python and an outside-checkout cache. `--online` is an explicit network choice;
without it, the command only reuses an exact cached result:

```bash
PYTHONPATH=src /absolute/path/to/imagery-venv/bin/python scripts/analyze_field_imagery.py \
  --geometry field.geojson --provider hls-s30-planetary-computer \
  --start-date 2025-06-01 --end-date 2025-06-15 \
  --cache-root /absolute/path/to/private-imagery-cache --online
```

For a Point, the same command defaults to its containing pixel. Add
`--sampling-mode point_buffer --sample-radius-m 60` for a 60 m radius sample.
`--buffer-m` remains polygon display context and is rejected for point modes;
`--context-pixels` is a separate polygon research-model context, also rejected
for points. Neither option can silently substitute for point sample radius.
Changing point sampling does not rewrite or evict existing polygon analyses.

## Development benchmark

`data/eval/field_data_pilot_v1/` contains 24 dependent field-season slices from
two sources, separate gold answers and exact source-row lineage. This is
exposed development evidence, not 24 independent farms or a sealed holdout.
CC0 Akron and CC BY corn-nitrate attributions remain in its manifest and
third-party notices.

```bash
PYTHONPATH=src .venv/bin/python scripts/run_field_data_benchmark.py \
  --output-dir outputs/field-data-pilot-run
```

Use a new/empty output directory. The runner uses isolated temporary stores,
verifies hashes, executes reviewed queries and the production core, and
retains every case/trace. It scores query contracts and exact registered-result
binding; semantic state questions remain unscored. The generator is an offline
mock, so this tests ingestion/tools, not language-model or agronomic competence.
HTTP authorization and UI behavior have separate tests.

Never upload gold answers or admit evaluation files into shared retrieval or
training. Explicitly select a source-only fixture CSV for an isolated
development field; answers remain outside that workspace. Future training
requires separately admitted fields and rights.

## Research-only imagery assessment

`requirements-imagery-models.txt` describes the separately exercised EO/model
environment. It adds frozen Prithvi encoder and fixed-readout dependencies to
the HLS worker stack; installing it does not activate a serving model or field
prediction. `scripts/assess_field_imagery.py` freezes or applies a source-bound
label/split protocol to an explicitly supplied research CSV and writes a new
receipt. `scripts/probe_imagery_model.py` checks a pinned local model snapshot
on CPU and MPS under supervised batch-one limits: 120 seconds per stage, 8 GiB
process RSS and 64 MiB observed system-swap growth. An MPS failure remains a
failure even if CPU succeeds. Device timing, finite features and dependency
identities are diagnostics, not accuracy. The current research receipts are
under `docs/reviews/artifacts/field-imagery-20260927/`; their grouped results
apply only to the recorded source, splits, dates and task. No research labels,
scores or encoder features enter the normal field-answer path.

## Inspect local storage

The read-only audit reports logical bytes, summed filesystem allocation,
verified duplicate payloads and a bounded four-date storage estimate. Supply
distinct, non-overlapping roots and a new output file outside those roots:

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_imagery_storage.py \
  --root imagery=/absolute/local/imagery-cache \
  --root acquisition=/absolute/local/research-acquisition \
  --verify-duplicates --output /absolute/local/storage-audit-new.json
```

It does not follow symlinks, delete data, change a cache, or evict evidence.
Incomplete scans and hashing limits remain explicit. APFS shared extents mean
summed allocation is not uniquely occupied space; whole-file and internal NPZ
duplicate estimates overlap and must not be added together.

New uploads retain their original bytes in compressed, SHA-256-addressed blobs
within the private SQLite database. Repeated uploads in the same workspace
share one blob; imports, reviewed mappings and row locators remain separate.
Different workspaces do not share blob identities. Reads verify both stored and
original hashes and enforce the 8 MiB decoded-source limit. Existing inline
imports remain readable without an automatic startup conversion.

For an existing SQLite workspace, stop its writers and create and verify a
backup using `server/storage/backup.py::create_backup` before migration. Inspect
the default dry run first:

```bash
PYTHONPATH=src .venv/bin/python scripts/migrate_field_source_blobs.py \
  --database /absolute/private/state.sqlite3
PYTHONPATH=src .venv/bin/python scripts/migrate_field_source_blobs.py \
  --database /absolute/private/state.sqlite3 --apply
```

The migration verifies source bytes and preserves import/mapping identities in
one transaction. Dry run preserves logical data, schema and payloads, but SQLite
may create WAL/SHM coordination sidecars. `--restore-inline --apply` restores
verified inline bytes while retaining blob history. Neither direction deletes
source history or runs `VACUUM`; fewer logical payload bytes do not promise an
immediately smaller database file. This CLI supports SQLite only.

Imagery writers default to a **2 GiB logical cache limit** and **1 GiB free-disk
reserve**. Set `AGRONOMY_AGENT_IMAGERY_CACHE_MAX_BYTES` and
`AGRONOMY_AGENT_IMAGERY_MIN_FREE_BYTES` before starting the source-checkout
server to change these bounds. One cross-process lock covers all field caches
under the configured root. Admission reserves up to 16 MiB before remote reads
or processing and checks again before saving. Capacity refusal returns
`storage_limit`; corrupt or unsupported cache state returns
`storage_unavailable`. Verified cache reads remain available without new-write
admission. Read-only lookups never migrate or attest legacy entries, and refuse
WAL indexes rather than mutating SQLite sidecars. These are cooperating-writer
checks, not an operating-system disk quota: unrelated processes can still
consume free space. No evidence is automatically evicted.

The historical plan in
`docs/reviews/artifacts/field-imagery-20260927/storage-audit.md` remains a record
of the initial measurements. Sharing raster pixels across field masks and
retiring old NPZ references still require a separate verified migration. Public
repository builds use independent APFS copy-on-write copies where available,
with ordinary-copy fallback and unchanged output hash verification.

## Preparing additional research tables

`scripts/prepare_field_sources.py` accepts the separately acquired, hash-pinned
Canadian bean/onion and Arkansas soybean source files. It writes a new output
directory containing source manifests, every row's disposition, study-group
CSVs and explicit import mappings. It performs no network requests or formula
evaluation. Formula cells and contradictory dates stay excluded and recorded;
missing geometry stays unknown. Group labels are source research units, not
claims of independent farms. For example:

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_field_sources.py \
  --raw-root /absolute/private/acquired-sources \
  --output-dir /absolute/private/prepared-new
```

Review the generated source, mapping and unit notes before preview/commit.
Onion laboratory measurements, Picketa model outputs and derived soybean yield
remain separate evidence roles. Preparation does not grant redistribution or
training rights; consult the source-specific catalog and original license.
The prepared source-only development lane is separate from benchmark answers.

The default Mac desktop launcher isolates inherited server environment
variables. Its bundled application does not provision this optional EO worker
or enable an imagery cache. The configured native server above is the exercised
optional-imagery path.
