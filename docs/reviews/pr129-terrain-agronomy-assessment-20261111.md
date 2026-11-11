# PR 129 terrain and agronomy assessment

November 11, 2026, Edmonton time.

## Provider observations

Live anonymous metadata requests used synthetic rectangles in Quebec and Iowa.
Canadian HRDEM 1 m and 2 m mosaics, acquisition projects, USGS project 1 m DEMs,
and Copernicus GLO-30 returned catalog records. The inspected USGS seamless 1 m
query returned an empty page. The catalog responses preserve unverified pixel
coverage and acquisition intervals. Copernicus remains a surface model.

MAPAQ's live index returned 3,706,830 bytes and 613 tile footprints. Its SHA256
was `62c33000018abb718f4d651a461cd3a2db723a99facca79cb9f75fbd917d2411`.
One 96 MiB official archive passed the existing archive, hash, vector geometry
and projected metre-based CRS checks. A synthetic 200 m square around a mapped
feature produced 684.43 m² of clipped depression area and 1,145.52 m of clipped
flow-path length. An independent GeoPandas clip calculation matched both values.
A separate synthetic rectangle returned zero vector intersections. These are
calculations on mapped source features. Source completeness, drainage design
and present field conditions require additional evidence. The slope raster was
unprocessed.

The exercised checkout lacked the source manifest and preparation command
referenced by the UI. The repair supplies a current source pin, a thin operator
CLI around the existing preparation functions, a setup guide and a readable
missing-index message. A regression also corrected missing-index errors to the
API's setup-required disposition. Downloading changed index bytes preserves
the previous verified index.

MAPAQ describes coverage within declared agricultural parcels and retains its
source acquisition period separately from publication dates. Preserve those
limits when interpreting an empty clip or a mapped depression.
[Official MAPAQ source](https://www.donneesquebec.ca/recherche/dataset/relief-agricole-issu-du-lidar).

## Agronomic answer assessment

The assessment uses the maintained release runner and the production
`execute_agent_request` path, with isolated synthetic records. Raw Kaggle
diagnostics from the earlier assessment retain their original scope and are
reviewed separately. Automated review is recorded as `automated_triage`.
Independent human agronomist review remains a separate qualification.

The first additional execution could not locate the primary checkout's cached
model from the isolated worktree. Its failed observations are retained. The
corrected invocation names the existing read-only cache explicitly.

The first provisioned run completed all 50 product cells. Its nine numeric cases
included two failures. Supplied nitrogen percentage, target and area were
replaced with a missing-input prompt, and a volumetric soil-water question was
misclassified as a simple unit conversion with missing units. The repairs add
two typed v2 operations with shared input validators for readiness and execution.
Field-total arithmetic composes the existing nutrient-product and area-total
calculators. Soil-water storage returns the dimensional result with its uniform
layer assumption and plant-available-water limit. Operational requests remain
outside these arithmetic selectors.

The terrain question also reached an erosion fallback that suggested practices
without first answering whether mapped data proved a current problem. Its
replacement leads with the evidence limit and requires current local assessment
before selecting a practice or design.

## Execution and review results

The 50-case product run at `36e73a5` completed all cells, with 24 verified
generated turns and six passing foundation components. Its original evaluator
retained one numeric failure because it read `kg N/ha` and `kg product/ha` in
the formula as standalone kilogram totals. The original report and answers are
retained with that failure.

The evaluator repair rejects qualified compound-unit prefixes while retaining
contradictory-total and negation checks. All other functions in that module
retain identical syntax trees. A fresh nine-case numeric run at `1b010ca`
passed **9/9** numeric contracts, all six foundation components and every
execution check. Its status is `smoke_complete`, with `source_stable: true`.
These are repeated exposed cases. The evaluator correction adds no model
generation evidence.

The maintained analyzer bound automated reviews to all **33** review-required
answers from the 50-case run. Those reviews marked **18 complete** and
**15 incomplete** for the requested task. Seven source-support labels and three
material-error labels remain unknown. The analyzer preserves
`domain_status: review_pending` and excludes automated triage from qualified
semantic metrics. Human agronomist review and field validation remain pending.

| Workflow | Automated assessment |
| --- | --- |
| Explicit arithmetic | Supplied-input calculations return parseable values and units. The two repaired requests also passed the built chat UI, readiness and persisted API checks without model construction. |
| Soil methods and records | The product answers preserve extraction-method/depth limits and distinguish collection date from report issue date. |
| Suspected disease and pests | Treatment and rate authorization are generally withheld. Several answers omit the requested differential, representative counts, or useful scouting procedure. The clubroot answer omits the explicit answer about a one-year break. |
| Nutrients and weather | Rescue-rate and spray decisions retain missing-evidence boundaries. Useful affected-normal/root comparisons appear in nutrient answers, while some weather answers need a clearer explanation of regional versus current local evidence. |
| Terrain and imagery | The repaired erosion fallback preserves mapped-data limits. The empty MAPAQ clip explanation still omits source parcel coverage and acquisition age. The NDVI answer needs a stronger QA/valid-pixel comparison before interpreting crop vigor. |
| Basic explanations | Crop rotation and soil texture receive definitions. The single-pin area explanation leaves the boundary or two-dimensional shape requirement incomplete. The vegetable-guide/haskap answer misses the requested crop-applicability comparison. |

The earlier pinned Kaggle GPU diagnostics remain raw-model observations.
Their completion, soil-water saturation wording, and report-date/analysis-date
confusion reinforce the need to assess the delivered product answer separately.
The fast profile's 35-token ceiling frequently leaves explanations unfinished.
This round retains the serving model pins and budgets.

## Verification scope

The terrain repair passed synthetic analytic area/length checks, real-provider
acquisition and clipping, saved-field authorization checks, and Chromium
prepared/missing/recovered-index flows. Both new calculations passed API
readiness/execution tests with the generator constructor forbidden, and the
built browser returned 2,086.957 kg and 72 mm through ordinary chat submission.
All 19 declared calculator operations have canonical conformance fixtures.
The source revision preceding the arithmetic extension passed 3,709 local
backend tests with 58 skips. Later arithmetic, scorer and integration checks
passed their focused suites. Final PR CI supplies the full composed-source
verification. Frontend verification passed 505 tests, typecheck and build.

Raw provider responses, frozen source/archive hashes, synthetic geometry,
execution plans, failed attempts, observations, review bindings, browser
captures and analyzer lineage remain in private assessment artifacts.

The source references used for automated review include provincial sampling
and soil-test guidance, public crop guidance, and satellite QA documentation.
[Alberta sampling guidance](https://www.alberta.ca/manure-management-planning),
[Manitoba soil-test methods](https://www.gov.mb.ca/agriculture/crops/soil-fertility/soil-fertility-guide/fertilizer-recommendation-guidelines.html),
[soil-water definitions](https://extension.umn.edu/natural-resources/conservation/agricultural-soil-and-water/how-agricultural-drainage-works),
[Canola Council clubroot guidance](https://www.canolacouncil.org/canola-encyclopedia/diseases/clubroot/),
[New Brunswick potato storage](https://www2.gnb.ca/content/gnb/en/departments/10/agriculture/content/crops/potatoes/storage.html),
[HLS QA documentation](https://lpdaac.usgs.gov/documents/1698/HLS_User_Guide_V2.pdf).
