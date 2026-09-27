# Field uploads and public imagery pilot

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
| HLS S30/L30 v2, Planetary Computer mirror | No | Discovery and COG access using a public short-lived SAS token |
| HLS, Google Earth Engine | Required | Optional declaration; credentials and execution are not configured |

Source rights and hosting access are separate. The catalog preserves license
links and hosting `proprietary` labels where present. Tokens are not saved in
traces. This pilot shows acquisition dates and **scene-wide** cloud percentage.
It does not decode chips, calculate clear field fraction/NDVI, diagnose stress
or predict yield. A byte-range probe proves access only.

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
