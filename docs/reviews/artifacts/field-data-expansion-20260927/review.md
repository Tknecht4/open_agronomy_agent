# Independent acquisition review — 2026-09-27

Verdict: **ACCEPT the catalog/acquisition artifacts and final results narrative
as bounded research evidence.** No runtime, training, benchmark, or agronomic
qualification follows. Final narrative reconciliation is complete; this review
is frozen to the artifact identities below.

## Scope and reference

Read repository AGENTS.md, README.md, ARCHITECTURE.md, data/README.md, the
working-state report and final Findings onward, discovery notes, both catalogs, acquisition receipts,
inspection/group profiles, primary metadata snapshots and selected original
bytes. Checkout: `codex/field-imagery-analytics`, HEAD
`a7dd7be332e4c06368dad2abef84149bcd23039d`. Existing 51-entry CSV is byte-identical
to HEAD. This reviewer changed only this review, made no network requests,
downloads, model runs, source admissions, or application/test-suite changes.
No web search queries were issued by this reviewer.

## Verified observations

- 28 new catalog records have distinct DOIs, and none of those DOIs occurs in
  the baseline CSV (case-insensitive comparison). Title/source review found
  no obvious mirror counted as an additional source. This establishes source
  identity, not physical farm independence or zero overlap of observations.
- All 26 successful payloads matched their receipt SHA-256 and exact byte size
  against retained raw files: 25 publisher payloads from eight dataset sources,
  plus one Carob standardized derivative. Total: **4,296,510 bytes**. The raw
  directory contains **57 files / 4,715,913 bytes**, including local metadata,
  profiles and receipts. Receipt and catalog totals agree. Twenty failed Dryad
  attempts remain recorded. The 20 MiB payload envelope was respected; free
  space before every past request was not independently reconstructed.
- Source-specific stored metadata confirms acquired Canadian bean/onion data
  use CC-BY-4.0 and carrot/soil-health data use CC0-1.0. Stored metadata for
  Bronson, Arkansas, Iowa stover and Texas cane specifies U.S. Public Domain.
  Soybean/legume DataCite snapshots specify CC0. Zenodo 15367284 separately
  has `access_right=restricted` and a CC-BY metadata license flag; restricted
  access remains blocked in the catalog. Unacquired source license claims
  were screened against discovery records, not independently re-fetched.
- Independent openpyxl/CSV/ZIP parsing confirms bean **1,936 data rows**, four
  `Location` values ERS15/ERS16/WRS15/WRS16, 484 distinct Plot labels and 121
  cultivar labels. The `.tab` payload is XLSX. Three deposit geographies are
  not three stations represented by this acquired field table.
- Onion: **402 grower rows / 16 raw Field labels**, **266 nutrient-trial rows**,
  and **48 separate trial yield/disease rows**. Nutrient CSV line 100 contains
  `Year=2025, Date=2026-07-29`; preserve the contradiction. Some other dates
  are yearless ranges, which require contextual parsing rather than treating
  their first four characters as a year. Grower records cannot be directly
  joined to trial yield as if they were the same plots.
- Soil health: **63 raw rows / 30 average rows**. Carrot disease: **96 harvest
  rows / 92 midseason rows**. Repetition/averaging is not new farms.
- Arkansas: **1,357 rows**, 28 Site ID labels and 39 Site-ID2 labels. Iowa
  stover: **88 plot rows**, two Field labels and grain/stover headers through
  2020 although the filename ends 2021. Texas cane: **4,824 rows**, eight Test
  labels, four SERIES values, six YEAR values and four CROP values. These
  labels are not verified independent farms. Ratooning indices, predicted
  dates, aggregates and other derived columns remain separately qualified.
- Carob soybean: **350 rows / 349 nonmissing yield values / 14 location labels**,
  all `trial_id=1` and all country values United States. This is explicitly
  a derivative; it does not establish a reconstruction of the publisher's
  349 plots / 17 trials or access to the original blocked Dryad workbook.
- Bronson's full workbook read finds **60 rows with Plot_no** (15 distinct raw
  Plot_no labels repeated across replicates), plus 59 sparse formula-only rows
  farther down the sheet. Its declared 18,862-row dimension is not a count of
  field observations. The published inspection profile correctly marks its
  scan capped, and does not present that dimension as observed record count.

## Finding repaired during review

The merged catalog initially retained discovery-only claims such as “contents
not downloaded” on acquired sources. The owner added explicit publisher-access
and local-acquisition fields, synchronized CSV acquired-file/byte totals, and
clarified that publisher inventory sizes may differ from `format=original`
payload sizes and representations. Re-read confirms this repair. Initial
metadata-only researcher notes are historical and must be read with that scope.

## Final narrative reconciliation

The final Findings onward matches the reviewed artifacts: 28 new sources plus
51 unchanged prior entries equals 79 inventory entries; reuse screening totals
are 22 source-declared-open, five conditional/restricted and one unknown. The
26 payloads and 4,296,510 bytes are correctly presented as eight original
datasets plus one standardized derivative. The acquired-source table retains
verified record/group counts without promoting them to independent farms,
and the ingestion discussion preserves format, formula, date, missingness,
derivative, grouping and blocked-access distinctions. JSON and CSV acquisition
counts/bytes agree for every corresponding source; their reviewed hashes are
unchanged. Public profiles retain schema/count summaries. The two background
YieldSAT/CYPRESS leads are expressly outside the 28-entry acquisition count;
those external leads were not independently fetched in this bounded review.
No additional correction is required.

## Residual limits

Country counts must follow source geography, not the researcher's bucket or
ID prefix: the anonymized precision-yield source has Canadian affiliations but
unknown field country; the legume compilation is global; robotic maize spans
United States/Canada. Canadian candidate discovery is concentrated in Ontario
and includes overlapping Holland Marsh/UBC sites. New DOIs do not establish new
independent farms. Geometry, trial identity, derivative transforms, date issues
and source overlaps still need resolution before imagery joins or splits.
Source licenses on unacquired datasets were not independently revisited online;
public access and stated license are not runtime/training admission.

## Reproduction and reviewed identities

Use Python hashlib over every successful receipt's retained payload; sum
`bytes` only for statuses beginning `downloaded`, and sum actual file sizes
recursively for raw storage. Parse tabular text with `csv.DictReader`, using
cp1252 for carrot midseason, and openpyxl in read-only/data-only mode for XLSX
payloads. Count nonempty data records after headers, not sheet dimensions.
For Bronson call `reset_dimensions()` before the full scan, then distinguish
rows with Plot_no from sparse formula output. ZIP member counts are read
without extraction. Inspect normalized DOI membership against the baseline;
compare baseline bytes with `git show HEAD:<path>`.

Reviewed artifact SHA-256:

- ../../field-data-expansion-20260927.md: `8b01f7de6c646ae06bb5ec923264a132a645ec259a75450418b283d4c7932306`

- source-catalog.json: `6faa3125a2c68d0b54583469317667ef8b8fdaa7894e333186a34f4dc233f574`
- source-catalog.csv: `256921c05f3c43c03bac1eca1fead69599efdf81b8ea8e00cf8f5acbb4a46450`
- acquisition-receipts.json: `f878e34c57a032eaa35f0ac68a7c3af18dcd15d0ebf69cd71d3dd9fb9691e33a`
- group-profiles.json: `ae201bb4fd672df54459e0357cf5b06aab804c45fe4cae6e6d32bec0f8dcf0e9`
- inspection-profiles.json: `5ce586cf6352ba01c7441034701b7ad9fd0a23ef4fb7cef58ffbc99bd16acf55`

Changed: review only. Verified: identities, hashes, counts, selected rights and
representation/grouping claims above. Residual Risk: unverified site grouping,
geometry and unacquired background leads; source restrictions remain binding. Memory Delta:
none.
