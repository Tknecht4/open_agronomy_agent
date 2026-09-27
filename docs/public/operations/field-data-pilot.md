# Field uploads and public imagery

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

Scene search uses a saved WGS84 polygon and explicit dates, sending those
inputs to the selected public source. Offline mode blocks network access.
A point or county centroid is insufficient for a field imagery footprint.

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
only the saved field polygon and bounded request, runs with a narrow environment
that excludes normal application credentials, and keeps public HLS access tokens
in memory. It cannot analyze an unsaved polygon or a point. With
`AGRONOMY_AGENT_NETWORK_MODE=offline`, only an exact verified cached analysis
can be reused; online requests send polygon and dates to the public catalog.
The cache is private field-scoped state, not a public source or model profile.

In **Fields**, save a polygon, then open **Imagery analysis** to choose HLS S30
or L30 and a date interval. The panel reports missing setup, offline cache
misses, no scene, and unavailable data explicitly. The receipt shows valid
area, excluded QA area, source item and band identities, dates and hashes;
inspect these before comparing fields or seasons.

List providers without network access:

```bash
PYTHONPATH=src .venv/bin/python scripts/inspect_field_imagery.py --providers
```

For a local GeoJSON Polygon/Feature, find two HLS scenes and probe up to
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

The measured plan in the repository's
`docs/reviews/artifacts/field-imagery-20260927/storage-audit.md`
separates reusable scene pixels from field masks/results, proposes
workspace-scoped raw-upload deduplication and configurable cache quotas, and
requires a verified migration before retiring old artifacts. Those migrations
and automatic eviction are not implemented. Public repository builds already
use independent APFS copy-on-write copies where available, with ordinary-copy
fallback and unchanged output hash verification.
