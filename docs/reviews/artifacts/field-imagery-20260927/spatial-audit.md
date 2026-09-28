# Spatial and label audit — 2026-09-27

## Observation: source and cohort

The read-only CSV `data/raw/field_data_research/20260927/us/akron_modeling_data.csv`
was inspected in the parent checkout. SHA-256:
`a1599b9c523f4ed44efd9b7f0c3ba6baf9f263f7c274415c77b4eb81d623f38b`.
Its dictionary hash is
`8d28eab66237bf0decb2da46570acefbd350b8b8a7a6732b34f2b55fffae1604`.
The source contains 721 rows, 18 management units and 2019–2022 observations.
All years of S2–S7 are excluded because those units supplied exposed field-QA
cases. No gold-case or answer file was read to create labels or features.
Remaining data: 575 rows, 246 unique sampling coordinates, 12 units and 29
field-seasons. No exact sampling coordinate occurs in multiple eligible units.
There are 16 wheat, 8 corn and 5 millet field-seasons; by year, 8/6/7/8.
Per-season support varies from 13 to 29 sample rows. Because this is a processed
yield-modeling CSV, absence of a row could reflect harvest cleaning or outcome
exclusions. The source does not establish that season-specific support was
known before the cutoff. Per-season AOIs and aggregate soil features therefore
have retrospective support-selection uncertainty in addition to publication
availability uncertainty; a prospective design should freeze support before
harvest and retain independently recorded missingness reasons.

The [publisher dataset](https://doi.org/10.15482/USDA.ADC/28914434.v1)
identifies CC0 data from one dryland research farm near Akron, Colorado. It
reports 18 management units of 2.6–4.3 ha, RTK-GPS topography and on-site weather.
The [source paper](https://doi.org/10.3390/agronomy15061304) studies within-field
variability; our assessment instead aggregates the available sample-location
yields per management-unit/year. These arithmetic sample means are neither
area-weighted means nor whole-field harvested yield. The source dictionary
specifies moisture bases: wheat 12.5%, corn 15.5%, millet 12%. We retain those
bases and report regression errors separately per crop; there is no pooled
cross-crop yield score or invented dry-matter conversion.

## Model: frozen protocol and geometry

`label-protocol.json` is label-free and binds sampling coordinates, exclusions,
12 leave-one-physical-unit-out folds, metrics, fixed preprocessing and models.
Protocol ID: `9714d8896c97092f81ac283d6ac2025d9460e3eed5733f85aa08776e4ce8455e`.
The initial pre-score ID `ca0161464dedafafb069cd6710760620f522239d068d7bfaa8dbb844e4ebd77b`
was amended **before any feature values or scores were inspected**, solely to
clarify actual native 224×224 context as the primary Prithvi input and padded
small chips as sensitivity. Metrics and splits were unchanged.

All crops use May 1–June 15 acquisition windows and June 15 cutoffs. Selection
must be independent of targets. Later seasonal rainfall (`P_summer_mm`) is
excluded. Nitrogen timing, other weather variables and topography have
unresolved exact availability and are excluded from this fixed tabular lane.
Only sand and carbon are admitted as source-soil covariates because the
dictionary dates their sampling to 2018. Coordinates/year are a separately
named confounding control. Historical publication times remain unknown;
these are retrospective acquisition-cutoff experiments, not operational
historical forecasts.

The dictionary identifies UTM zone 13N but does not identify the datum.
Publisher article HTML returned HTTP 429; XML fetch failed; exact searches
below did not resolve a datum. EPSG:32613 is therefore an explicit research
assumption, **not** publisher-confirmed CRS. The research AOI rule is the convex
hull of sample locations buffered 15 m. In this cohort its area ranges
1.4844–2.7111 ha; that is sampled support, not a surveyed field boundary.
Do not install it as a farmer's field boundary or infer coverage over the
unsampled management-unit area.

A local pyproj comparison of EPSG:26913 and EPSG:32613 transformed all 575
coordinates to WGS84. Their computed separations were 0.00011410–0.00011411 m,
using `Inverse of UTM zone 13N + NAD83 to WGS 84 (1)` with stated 4 m operation
accuracy and `best_available=True`. This near-zero difference reflects that
operation, not proof of the source datum or centimetre geolocation accuracy.
Imagery sensitivity should retain both CRS alternatives plus cardinal 15 m
and 30 m support shifts, without choosing an offset by label performance.
That imagery shift comparison has **not** been run by this audit.

Native HLS pixels are 30 m. A 16×16 Prithvi token spans 480 m and a 224-pixel
context spans 6.72 km, exceeding these small units. Adjacent-unit contexts
will overlap. Physical label-group holdout is therefore not strict spatially
disjoint imagery holdout. The fixed representation weights tokens by valid
sampled-support pixel counts over exactly four chronological dates; global
attention can still mix missing and contextual content. Assessment reports
exact vector duplicates and maximum pairwise cosine similarity as diagnostics,
without using them for tuning or feature selection. Cosine similarity is also
scale-sensitive for raw location controls and is not a calibrated alias score.

## Observation: local spatial SQLite and graphs

All databases were opened using SQLite URI `mode=ro`. No map database,
regional manifest, graph or active configuration was modified. The inspected
files live below the parent checkout's
`outputs/spatial_assets/data/derived/geo_layers/`. Their presence does not
prove a running server points to this directory; the geospatial service
resolves the explicit `AGRONOMY_AGENT_SPATIAL_PACK_ROOT` override or its default
`data/derived/geo_layers` path.

| Database | Bytes | Features / R-tree rows | Longitude range | Latitude range | Source CRS |
|---|---:|---:|---|---|---|
| ab_detailed_soil.sqlite3 | 59,871,232 | 28,366 | −120.00137 to −110.00482 | 48.99667 to 58.68914 | EPSG:3400 |
| sk_detailed_soil.sqlite3 | 144,310,272 | 67,166 | −110.00571 to −101.36256 | 48.99832 to 54.47357 | EPSG:4269 |
| mb_detailed_soil.sqlite3 | 276,201,472 | 168,371 | −101.88548 to −91.99999 | 48.99887 to 57.00007 | EPSG:26914 |

Each has 28 metadata records; `features` uses an integer `fid` primary key,
unique `code`, name, zlib JSON properties and geometry, and WGS84 bounding
columns. `feature_bounds` is a SQLite R-tree over
`fid,min_lon,max_lon,min_lat,max_lat`; its backing rowid/node/parent tables
are index internals. Feature and R-tree counts match. A bounding-box query
for longitude [−103.16,−103.11], latitude [40.14,40.17] returned **zero** for
all three databases. There is no Colorado coverage, not a missing soil value
to impute from the Canadian maps.

Database SHA-256 identities:

- AB: `c848c13760ab00a817cc42c13e8c29bdee598d291150a2884d54d29b9f9ae731`
- SK: `ebb306226c9e3b77d4a0419d24a231228e8425e8fe1e42b8debc4a95457d4e38`
- MB: `14535e32507e3fff0ae24272d9744d06c8827e66c23b9db95b91fd986d78eeeb`

Metadata labels these historical soil-landscape priors under the Open
Government Licence – Canada, with source-record IDs, source/archive hashes,
CRS transformation and geometry repair receipts. AB/SK intend 1:100,000
representation; MB combines multiple scales from 1:20,000 to 1:126,720.
Neither mapped components nor simplified polygons establish field-specific
current nutrients, drainage, suitability or management rates.

The existing `data/derived/rag/soilwise_knowledge_graph.json` contains 1,784
nodes and 1,450 edges, hash
`9e73db954212216241b4b77d63088d4671fa017539e5309ee71e444b086a618b`.
Its manifest declares `authority_role=vocabulary_hint`, CC-BY-4.0, source
Zenodo 15593868, and broader/narrower/related-to/exact-match relations.
`configs/rag.yaml` references it and the project-authored seed graph with
required manifests. Vocabulary edges have no sampling location, acquisition
time or measured yield authority. They must never supply missing targets.

## Interpretation: attaching context

Use the existing map service's read-only R-tree candidate lookup followed by
exact geometry intersection. Attach source ID/hash, mapped feature code,
intersection fraction, geometry support, date/scale/jurisdiction and
`regional_prior` role; distinguish outside-coverage from not-installed and
unknown. For Akron all Canadian layers return outside-coverage. Source sand
and carbon remain separate 2018 point-sample observations, never map-derived
soil claims. Graph concepts may supply vocabulary/source routing only.

Keep imagery/feature artifacts in an independent versioned catalog, binding
bundle, geometry, acquisition/cutoff, source item/band/byte hashes, QA coverage,
processing/model identity and evidence role. Connect read-only prior references
by source identity; do not rewrite map or graph records to host predictions.
Source labels stay exclusively in this offline scoring path, outside runtime
retrieval, language-model training and QA gold. No LLM/SFT is involved.

## Observation: fixed source-only readouts

`baseline-assessment.json`, `soils-assessment.json`, and
`location-time-assessment.json` contain real predictions for all 29 seasons,
all training bundle IDs, source/code/protocol/split identities, metrics and
failures. Their fixed sklearn readouts were executed once after protocol
freeze; there was no hyperparameter search or score-driven revision.

| Held-out physical-unit lane | Crop correct / eligible | Balanced accuracy | Wheat MAE kg/ha | Corn MAE kg/ha | Millet MAE kg/ha |
|---|---:|---:|---:|---:|---:|
| Training majority / crop means | 16/29 | 0.3333 | 1446.80 | 1505.69 | 1128.76 |
| Fixed 2018 sand/carbon readout | 16/29 | 0.3792 | 1519.05 | 1833.64 | 987.79 |
| Location/year control | 15/29 | 0.3125 | 1429.19 | 1612.74 | 1245.63 |

Each regression is conditioned on the **observed** crop, as is its baseline;
this is not an end-to-end predicted-crop-to-yield pipeline. The soil lane has
negative MAE skill for wheat (−0.0499) and corn (−0.2178), and positive millet
skill (0.1249) on only five millet seasons. These results do not support a
broad accuracy improvement. Source-soil and location controls are not imagery
or frozen-encoder results. The baseline-only artifact explicitly retains 29/29
unavailable feature predictions rather than inventing them.

`forward-soils-assessment.json` is a different estimand: train 2019–2021 and
test eight 2022 seasons, potentially on already observed physical units.
Soils and majority both classify 4/8 correctly. Soil MAE is wheat 2361.13,
corn 1919.89, millet 881.53 kg/ha versus baseline 2647.93/1783.86/1340.12.
The small crop strata (4/2/2) and single held-out year preclude external or
independent-site inference. Group and forward-year scores must not be pooled.

## Verification and remaining uncertainty

Twelve focused synthetic contract tests passed, covering source substitution,
all-year QA exclusion, group isolation, means/moisture, source-column leakage,
future acquisitions, duplicate/unknown bundles, missing/nonfinite features,
full failure denominators, training-only baselines and forward-year separation.
Two expected sklearn warnings describe a synthetic future-year test whose
truth includes a class absent from training. This is not agronomic validation.
Real imagery/encoder scores, shift sensitivity and external-farm validation
are outside these source-only results. The single-farm 12-group dependency,
uncertain datum and retrospective data availability remain binding limits.

Primary-source discovery queries (exact text, 2026-09-27):

```text
"Topographic position index predicts within-field yield variation" datum
"Topographic position index predicts within-field yield variation" coordinate
site.mdpi.com/2073-4395/15/6/1304 "NAD"
site:mdpi.com/2073-4395/15/6/1304 "UTM"
site:mdpi.com/2073-4395/15/6/1304 "2018" "GPS"
"agronomy15061304" "NAD83"
"agronomy15061304" "coordinate"
"Topographic Position Index Predicts Within-Field Yield Variation" "UTM"
```

The first `site.mdpi.com` string contains a search typo; its uninformative
result is retained. Source paper HTML/XML retrieval failures are negative
evidence, not proof that the publication lacks a datum.
