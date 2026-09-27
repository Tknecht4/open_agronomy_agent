# Source imports through the product HTTP path

Status: complete answer and source binding verified in new run `-08`,
2026-09-27, after the runtime renderer repair. All nine HTTP answers now equal
the registered result payload exactly, and so do their structured answer,
public Markdown and persisted SQLite answer/structured fields. Result
registration, invocation linkage, question SHA, source identity and all
pilot-judge-equivalent oracle receipt fields passed explicit checks.

Runs `-06` and `-07` remain invalidated for complete-answer claims: their
original checks verified table/source/storage receipts but omitted exact
answer comparison. Read-only later audits found four affected groups in each
run because leakguard erased valid `source_*` column answers. Frozen receipts
and databases remain unchanged, and the public JSON retains every failed
binding. Their numeric/storage findings do not establish answer integrity.
This is a source-only development rehearsal, not an agronomic quality score.

The [receipt](product-rehearsal.json) records nine successful imports through
FastAPI TestClient's HTTP create-field, preview, commit and explicit query
routes. Each import then reached the real session-turn route and production
core with all 17 ordered stage receipts and `deterministic_tool_result`.
`model_id=mock` and offline settings were explicit; no model inference,
download, external service or private-knowledge overlay was used. Research
and training export consent were false. Expected counts/means were computed
in the rehearsal script from original workbook records or prepared CSVs using
`math.fsum`; no expected values were placed in runtime prompts or retrieval.

| Research study unit | Imported records | Explicit mean variable | Evidence role |
|---|---:|---|---|
| Bean ERS15 plot 1001 | 1 | YD | observation |
| Bean ERS16 plot 1001 | 1 | YD | observation |
| Bean WRS15 plot 1001 | 1 | YD | observation |
| Bean WRS16 plot 1002 | 1 | YD | observation |
| Bean ERS15 environment | 484 | source_yd | observation |
| Davis onion 2024 SGS | 15 | source_nitrogen | observation |
| Davis onion 2024 Picketa | 15 | source_nitrogen | model_output |
| Onion trial harvest 2024 | 24 | source_jumbo_bulb_weight_kg | observation |
| Arkansas soybean trial 1 | 18 | source_actual_yield_kg_ha | interpretation |

All geometry is `none`. These labels identify source study partitions, not
farms. The four bean plot imports use identical original XLSX bytes (the
acquired `.tab` is XLSX, imported with an honest `.xlsx` filename). The
unmodified mapping guard correctly refuses Location-only filtering because
Plot also identifies source scope. Location+Plot filters create four small
plot units; the separate prepared ERS15 import represents the full environment.
The original WRS16 plot 1001 has missing YD; it remains recorded in a failed
attempt, and the numeric-mean representative is plot 1002. No missing yield
was converted to zero.

For wide prepared tables, the rehearsal explicitly selected source
identifiers/context and queried measurements into mappings of at most 16
columns. The full source CSV and transformation manifest remain unchanged.
The broader preparation mapping correctly triggers a natural-language hold
when its complete column index cannot fit the bounded snapshot. All explicit
HTTP means and counts matched independently recomputed source values,
including missing/invalid counts.

Picketa's explicit table mean remains labelled `model_output`. Its natural
language count succeeds; a separate natural language mean request correctly
returns `deterministic_tool_clarification` without generation. Arkansas's
source-reported average yield remains `interpretation`; its successful chat
mean uses observed crop moisture instead. The role boundary was preserved
rather than relabelled to make the planner answer.

Every source-list and explicit-query request by the other workspace returned
403. Every attempted turn in an owner session by that outsider returned 404,
concealing the private session identity. Source content hashes, mapping
hashes, query receipts, field/session/turn IDs, and ordered execution-stage
receipts are retained. All seven original raw/dictionary hashes were
rechecked unchanged after the successful run.

## Storage observation

Nine imports use six workspace-scoped source blobs. The four original bean
imports reference exactly one blob with the original raw SHA-256. Storing each
upload separately would hold 1,004,085 source bytes; unique raw blobs total
321,858 bytes and their compressed payloads total 235,890 bytes. Inline source
bytes total zero. These figures describe source payloads only, not the total
SQLite file, row indexes, traces or filesystem use. XLSX is already compressed,
so the largest gain here comes from sharing the repeated workbook.

## Reproduction and retained attempts

```sh
PYTHONPATH=src .venv/bin/python scripts/rehearse_field_source_imports.py \
  --prepared-root outputs/field-source-preparation-20260927 \
  --output-dir outputs/field-source-rehearsal-new
```

The destination must not exist. The successful isolated database is
`outputs/field-source-rehearsal-20260927-08/demo.sqlite3`; it belongs to
`local-demo@open-agronomy.local`. This is the default local UI identity, so a separately launched
local UI can immediately browse its fields. Existing preview databases were untouched.

The earlier table-only runs remain at suffixes `-06` and `-07`; their
complete-answer claims are invalidated as described above.
Earlier attempts remain at the base output path and suffixes `-02` through
`-05`, with failure receipts and hashes recorded in the public receipt. They
capture an unsupported settings keyword, an internal-versus-HTTP trace shape
assumption, expected session-privacy 404 behavior, the missing-yield source
row, and the full-width snapshot guard. None is silently replaced by the
successful result. The checked script reflects the verified contracts; no
production route or mapping guard was changed for this rehearsal.
