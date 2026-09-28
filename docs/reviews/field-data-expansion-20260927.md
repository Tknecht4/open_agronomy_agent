# Field-data source expansion — 2026-09-27

User follow-up: find more actual field data, retaining the local-storage
constraints. The earlier 51-entry catalog remains a dated discovery snapshot.
This batch should add source-distinct observed records, not inflate counts
with imagery tiles, modeled maps, repeated repository mirrors or adjacent
plots presented as independent farms.

## Working state and acquisition envelope

- Reference: clean `codex/field-imagery-analytics` at `a7dd7be`, draft PR 9.
- Priority: Canada and USA; plot/field yields, management, soil, phenology,
  scouting or crop labels, preferably with usable spatial and date joins.
- Deliverable: additive catalog with primary license evidence, file/access
  details, independent-group and imagery-join caveats; inspect a small set of
  real downloadable tables and retain original hashes/schema/counts.
- Approximate effort: owner plus two bounded source researchers, 20–35
  minutes with a source/size checkpoint before downloading. Monetary usage
  is unavailable. No model run, account signup, paid service or private input.
- Initial storage envelope: metadata first, at most 20 MiB new raw samples,
  with at least 1 GiB free space before each download. Large archives remain
  catalog entries unless a small separate file or bounded subset is available.
- Original files go to ignored raw storage. Public artifacts contain source
  pointers, rights/status and inspection receipts; cataloging does not admit
  a source into runtime, training or a sealed benchmark.
- Preserve the existing benchmark exclusions, acquisition failures and
  observation/model/interpretation distinction. The Akron imagery result
  motivates more independent farms and labels at appropriate spatial scale.

Acceptance: source entries deduplicated against the earlier catalog; reported
licenses/access backed by the primary repository; downloaded samples have
actual observed schemas/counts and byte hashes; promising versus acquired
data remain distinct. Negative access/rights findings remain in the batch.

## Findings

The additive [catalog](artifacts/field-data-expansion-20260927/source-catalog.csv)
contains **28 new source records**, with no DOI overlap against the earlier
51-entry snapshot. Together the two inventories contain 79 entries; this is
not a count of independent farms or ready-to-use benchmarks. Twenty-two new
records have source-declared open terms, five have restricted/conditional
reuse, and one has an unverified license. Attribution and share-alike terms
remain attached to individual records.

We acquired and inspected **26 files, 4,296,510 bytes (4.30 MB)** from eight
original datasets and one standardized derivative. Metadata and local
inspection receipts bring the batch's raw directory to approximately 4.72 MB.
No large raster archive, model or full sensor bundle was downloaded. The
original payloads remain ignored; no new source was admitted into runtime,
training or an evaluation split.

| Acquired source | Actual file inspection | What it adds | Declared terms |
|---|---|---|---|
| [Arkansas soybean phosphorus trials](https://agdatacommons.nal.usda.gov/articles/dataset/Soybean_Yield_Response_to_Fertilizer-Phosphorus_Rate_on_Soils_having_different_Mehlich-3_Phosphorus_Values_in_Arkansas/24667830) | 1,357 table rows; 39 trial IDs and 28 site labels; 2004–2018 with gaps | Yield, fertilizer rates, soil/tissue chemistry and site coordinates; promising multi-site source | U.S. Public Domain |
| [Ontario common bean phenotyping](https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/FD81LR) | 1,936 rows, 121 cultivar labels, four environment codes: ERS15/16 and WRS15/16 | Yield, phenology, plant traits and genotype/plot/block joins | CC BY 4.0 |
| [Holland Marsh onion nutrition and disease](https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/YJTMRB) | 402 grower-sampling rows with 16 field labels; separate 266-row nutrient trial and 48-row yield/disease table | Real multi-file field records with methods, repeated sampling and trial outcomes | CC BY 4.0 |
| [Texas sugarcane clonal trials](https://agdatacommons.nal.usda.gov/articles/dataset/Data_from_Sugarcane_Genotype_by_Environment_interaction_G_E_in_Clonal_Trials_in_the_U_S_Texas_Rio_Grande_Valley/28074515) | 4,824 rows, eight test-location labels, 2015–2020; separate derived ratooning-index workbook | Perennial crop cycles, genotype × environment and cane/sugar yield | U.S. Public Domain |
| [Iowa stover/tillage experiment](https://agdatacommons.nal.usda.gov/articles/dataset/Thirteen-year_Stover_Harvest_and_Tillage_Effects_on_Corn_Agroecosystem_Sustainability_in_Iowa/24856419) | 88 plot rows; two field labels; 22 treatment labels; grain/stover columns for 2008–2020 | Longitudinal yield, changing plot treatments and depth-specific soil tests | U.S. Public Domain |
| [Bronson cotton Field 113](https://agdatacommons.nal.usda.gov/articles/dataset/The_Bronson_Files_Dataset_8_Field_113_2016/25213130) | Activities, dictionary, workbook, documentation and plot-map PDF acquired; workbook inspection explicitly capped | Yield, nitrogen/irrigation treatments, proximal spectra and plot geometry documentation | U.S. Public Domain |
| [Holland Marsh soil-health tests](https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/FHKKIF) | 63 sample rows and a separate 30-row average table | Lab methods, units, repeat samples and observed-versus-averaged records | CC0 |
| [Carrot cavity-spot field trials](https://borealisdata.ca/dataset.xhtml?persistentId=doi:10.5683/SP3/JK5M8I) | 96 harvest and 92 midseason records, 2020–2022 | Actual disease-incidence/severity labels and cultivar comparisons | CC0 |
| [U.S. soybean soil/management study](https://datadryad.org/dataset/doi:10.5061/dryad.hx3ffbgrk), via [Carob's published derivative](https://carob-data.org/reports/agronomy/doi_10.5061_dryad.hx3ffbgrk.html) | 350 standardized rows, 349 nonmissing yields, 14 location labels; original workbook not acquired | A compact multi-location yield/soil/management example, subject to transformation and trial-identity review | Original data and derivative metadata identify CC0; Carob script GPL ≥3, not copied or executed |

Row counts include repeated measurements and nested plots. They must not be
added together as independent fields. The bean deposit lists three geographic
stations in its metadata, but the acquired field workbook contains only two
station-code prefixes across four environments. Holland Marsh deposits can
share sites and plots. The sugarcane ratooning indices reuse observations.

## Ingestion cases uncovered

- **Original formats differ from catalog formats.** Borealis lists several
  files as `.tab`, while `format=original` returns XLSX or CSV with a different
  content-disposition filename and byte size. Retain both representations and
  verify MIME/magic bytes before selecting a parser.
- **Workbook structure matters.** The Arkansas raw table contains thousands
  of formula cells. Bronson has 781 declared columns and extensive formatting
  and formula-only rows far below the observations; 18,862 declared worksheet
  rows are not 18,862 samples. Do not execute formulas or assume rectangular
  worksheet dimensions equal observations. The current restricted intake
  correctly requires further review/adapters for these files.
- **Real records contain contradictions.** One onion micronutrient row
  (CSV line 100) has `Year=2025` and `Date=2026-07-29`; other dates are ranges
  or month/day strings. Preserve the discrepancy and ask for a resolution
  before time-window evaluation.
- **Reshaping and joins need receipts.** Iowa yields are wide by year, while
  plot status/treatment changes and soil depths live in other sheets. Its
  yield filename mentions 2021, but that CSV's yield columns stop in 2020.
- **Missingness and transformations are explicit.** Files use `.` and
  `-9999`; these are not zero yields. The Carob soybean file has one missing
  yield and a constant `trial_id`, so its 14 location labels cannot reproduce
  the publisher's 17-trial grouping without more source work.

These are useful future benchmark cases: identify the correct sheet and
units; link a lab result to the right field/year; distinguish replicated
samples from averages; reconstruct treatment history; flag conflicting dates;
and explain why a yield or imagery conclusion is not identifiable.

## Promising sources not yet acquired

The catalog also covers Ohio corn nitrogen trials (publisher: 431 trial
site-years), additional soybean disease/cover-crop studies, maize robotic
phenotyping, Colorado water-productivity plots, Ontario oats and cover crops,
and a global grain-legume relational database. These remain separate from
the acquired counts. The previous Bowles rotation record was revisited and
its file URL resolved, but it is not a new source and no raw CSV was obtained.

Dryad metadata was accessible, but its API download route required a bearer
token and the advertised website file streams returned HTTP 403 in this
environment. Earlier HTTP 429 responses triggered a pause and serialized
requests. No account or credential was used. Preserve those failures rather
than label the original files acquired; the soybean Carob derivative is a
separately identified representation.

The [Iowa spatial-yield record](https://zenodo.org/records/15367284) has public
metadata but restricted files, with confidentiality and written-permission
conditions. Its CC BY metadata flag does not override those conditions.
Two Canadian long-term deposits likewise require author permission. No data
requests or messages were sent.

The shifted wheat yield GIS is useful for geometry ingestion but cannot be
joined honestly to real satellite locations. Another precision-yield methods
deposit mixes donated real data, generated data and a correlation matrix;
the components and actual country remain unresolved.

Two additional leads are kept outside the 28 new field-data records:
[YieldSAT](https://yieldsat.github.io/) advertises combine-harvester data for
2,173 fields in Argentina, Brazil, Uruguay and Germany, but uses an access
form and its dataset terms were not verified here. It is a future geographic
extension. [CYPRESS](https://arxiv.org/html/2510.26609v1), although relevant to
Prithvi/canola, describes upsampling county yields into pixel labels. Those
labels are not observed subfield yields and cannot validate our field-level
accuracy claim.

## Recommended next intake

Start with the Canadian bean/onion tables and Arkansas/Texas yield records.
They add crop diversity, repeated field observations and multiple site or
environment labels in a few megabytes. Freeze source/site grouping and
variable roles before authoring questions. Add Iowa's longitudinal joins and
Bronson's formula-rich workbook as harder ingestion cases. Acquire more
surveyed field extents before expanding imagery-accuracy claims; plot or site
coordinates alone do not resolve the earlier HLS spatial-support limitations.
