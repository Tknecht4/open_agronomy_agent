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

Results will be appended after execution and source review complete.
