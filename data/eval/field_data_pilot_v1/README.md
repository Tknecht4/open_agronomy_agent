# Exposed field-data development pilot v1

This directory contains 24 **dependent field/site-season bundles** projected
from two inspected source CSVs and 96 exposed development questions. It does
not contain 24 independent farms or an agronomic validation set. Twelve Akron
bundles share one research site; twelve corn-stalk-nitrate field IDs may share
farms. The Akron values are sample-location observations, not an area-weighted
field harvest. The nitrate source contains no measured yield and county
centroids are not field geometry.

`manifest.json` contains the source SHA-256, source URL, license, attribution,
derivation, exact 1-based source CSV record locators, fixture SHA-256, and
reviewed import mapping for each bundle. `fixtures/*.csv` contains only
source-derived table cells. The separate `gold_cases.jsonl` contains questions
and expected table results. **Never admit `gold_cases.jsonl` into runtime
retrieval, training, prompt context, or a demo upload.** To try a demo, choose
one fixture CSV explicitly, preview it, inspect the mapping, then commit it in
your private field workspace. Source metadata remains user-asserted in the
product; the manifest does not grant a runtime or training permission.

Source licenses: Akron is [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/);
the corn stalk nitrate survey is [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Attribution and exact source records are in the manifest. The original raw
CSVs are local research inputs and may be supplied to the builder through
`--source-root`. No network or model download is used.

From the repository root, generate into a **new empty directory**:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_field_data_pilot.py \
  --source-root data/raw/field_data_research/20260927/us \
  --output-root /tmp/field-data-pilot-rebuild
```

Compare `manifest.json`, `gold_cases.jsonl`, and all fixture hashes to this
directory. A source checksum mismatch fails before writing. Run the isolated
three-layer check into a new directory:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_field_data_benchmark.py \
  --pilot-root data/eval/field_data_pilot_v1 \
  --output-dir /tmp/field-data-pilot-run
```

The runner verifies fixture bytes, previews and commits each case through the
direct private-store API in a fresh temporary database, checks the reviewed
deterministic query receipt, and executes `execute_agent_request` with an
offline mock generator. This exercises ingestion and the product core; it does
not send all 96 cases through HTTP or the UI. It retains every result, error,
source identity, import ID, query receipt, full production trace, hashes of
all package Python files and active configs, and observed Python/package
versions in `cases.jsonl` and `summary.json`. Installed package versions are
environment identity, not evidence that every listed library executed.

For count, mean and unique cases, an external scorer checks the executed
registered `field_table_query` result against the independent query receipt
and verifies that the final answer is exactly bound to that result. Missing
column/state cases score only the deterministic query rejection; their product
clarifications remain unscored semantic observations. The CLI exits nonzero
after retaining all cases if intake, query, exact product binding, or code
stability fails. The summary counts source groups and task types separately.
These are regression checks, not agronomic judgments or field recommendations.
