# Pinned field-source preparation, 2026-09-27

Status: source-only preparation for explicit review. The new offline adapter
uses the previously acquired files; it makes no downloads and modifies no
original. This record is separate from frozen benchmark cases and gold answers.

| Source profile | Study-unit groups | Prepared records | Dispositions and limits |
|---|---:|---:|---|
| Ontario common bean | 4 environment codes | 1,936 | 484 records each; two trailing blank rows excluded; six derived traits excluded |
| Holland Marsh grower tissue | 36 field/year/method partitions | 402 | 18 field-years across 16 field labels, two methods; paired leaves do not represent independent observations across methods |
| Bradford trial tissue | 4 year/method partitions | 265 | CSV record 100 held: Year 2025 conflicts with Date 2026-07-29; no date correction |
| Bradford trial harvest | 2 year partitions | 48 | Literal grade weights/counts; scaled yields, totals, percentages and disease indices excluded |
| Arkansas soybean P | 39 source trial IDs | 1,357 | All 6,183 formula cells excluded without reading cached results; 81 dictionary records retained as metadata dispositions |

These 85 partitions contain 4,008 prepared records, not 85 independent farms.
No geometry was guessed or imported. The onion trial README describes a
22-column schema with plot identifiers, while the acquired CSV has 18 columns
and no Trt_ID; the adapter preserves that absence and does not invent joins.
Partial dates and date windows remain source text, ineligible for exact time
windows. The bean codebook contains an Elora 2016 end-date typo, and grower
sampling windows differ between README and literal table; neither is silently
repaired.

Bean yield/seed weight retain the publisher's 18% moisture adjustment. SGS lab
nutrients are observations; Picketa device values are conservatively mapped as
model output. The Arkansas dictionary calls Actual Yield an average, so that
column is conservatively derived and mapped to the product's `interpretation`
role. Literal plant P/K/Ca/Mg/S concentrations are observations. Soil replicate
averages, predicted SoyMAP dates, formula-derived tissue stage/fraction, and
micronutrients with dictionary/header unit conflicts are excluded. These role
choices preserve uncertainty and do not validate sensor accuracy.

## Reproduction and review interface

From the repository root, with acquired originals already present:

```sh
PYTHONPATH=src .venv/bin/python scripts/prepare_field_sources.py \
  --raw-root data/raw/field_data_research/20260927-expansion \
  --output-dir outputs/field-source-preparation-new
```

The destination must not exist. All seven raw input/dictionary SHA-256 pins
are checked before output creation. File, archive expansion, worksheet, row,
column and cell limits bound the adapters. Only the five explicit profiles
are supported; this is not an arbitrary spreadsheet executor.

`index.json` lists every group's CSV, mapping template, row count, raw and
transformation SHA-256, and source-table diagnostics (counts, missing counts,
means). For product import, preview the referenced CSV, review the referenced
mapping, then commit through the existing field-bound API. No commit occurs
in this script. The mapping uses only supported source metadata fields. Its
citation carries raw and transformation hashes. `source_row` holds the raw
hash, original sheet and record; each transformation manifest binds original
column number/name to output aliases and assigns a disposition to every
original record, including headers, dictionary rows, blanks and the hold.
`.` / `-9999` / `NA` / empty cells become empty output cells plus explicit JSON
null dispositions with original markers; none becomes zero. Original
formulas are located but never copied into importable cells or evaluated.

Generated bundles remain ignored under `outputs/`; the compact
[receipt](preparation-receipt.json) preserves every group/output hash without
publishing source rows. The source bytes remain in ignored raw storage.

## Verification

Six focused tests passed. Mandatory synthetic tests cover changed-input hash
refusal before output, row/column lineage and study groups, all missing markers,
date-conflict hold, a formula with a poisonous cached numeric result, deterministic
outputs, refusal to overwrite, worksheet bounds and existing storage
preview/commit/query behavior. The local acquired-source test additionally
validated all 85 mappings, counts, formula/metadata dispositions and a nitrogen
mean independently recomputed from the original grower CSV. That last test
explicitly skips if ignored acquired source files are absent. Original hashes
were rechecked after preparation. Passing these contracts is not agronomic
validation, RAG/training admission, or imagery evaluation.
