# Third-party data and software notices

This index accompanies the conference source tree and portable knowledge
archive. It is not a substitute for the per-item licence, source, checksum,
jurisdiction, and currency fields preserved in the governed manifests and
corpus rows.

## Redistributed knowledge and evaluation data

- **SoilWise Soil Health Knowledge Graph** — CC BY 4.0; source:
  <https://zenodo.org/records/15593868>. Derived RAG and graph files retain
  SoilWise provenance. See `data/manifests/source_licensing_matrix.json`.
- **Canadian federal and provincial public information** — redistributed only
  where the item-scope evidence recorded in
  `data/manifests/runtime_corpus_policy.json` and the source manifests permits
  it. The governed rows preserve source URL, licence, language, jurisdiction,
  currency, and checksum lineage. Ontario Publication 811/811F is excluded.
- **Manitoba 2026 scouting companions** — six manually reviewed, project-
  authored companion records derived from the Manitoba Guide to Crop
  Protection under the OpenMB Information and Data Use Licence. Product
  tables, rates, logos, images, and separately credited material are excluded;
  these records are context-only pending independent agronomic review.
- **Ontario and Statistics Canada context** — subject to the Ontario Open
  Government Licence and Statistics Canada Open Licence as identified in the
  row-level source records.
- **USDA NRCS ecological-site descriptions** — United States government public
  information; cite USDA Natural Resources Conservation Service and the source
  identifiers carried in each record.
- **AgroQA external diagnostic** — supplied under the MIT licence with
  copyright notice for Jonathan Omara (2022). The full notice is retained at
  `data/eval/public/agroqa_dataset_LICENSE.txt`.
- **Canadian geospatial layers and tabular snapshots** — each bundled file has
  an exact source/licence/lineage record in
  `data/manifests/canada_geospatial_sources.json`, its layer manifest, or the
  relevant snapshot manifest. Regional overlays are not national field truth.

Quarantined or rights-unresolved corpus bytes are not included in the portable
runtime archive. Their identifiers may remain in policy manifests so the
exclusion is auditable.

## Interactive basemaps

Connected map styles request tiles directly from the selected provider. No tile
archive is bundled or prefetched by this application.

- **OpenStreetMap Streets** — retain visible OpenStreetMap contributor attribution
  and follow the [copyright notice](https://www.openstreetmap.org/copyright) and
  [tile service policy](https://operations.osmfoundation.org/policies/tiles/).
- **Esri World Imagery** — retain the provider's service attribution. The inspected
  service metadata on 2026-09-27 credits Esri, Vantor, Earthstar Geographics, and the
  GIS User Community. Provider imagery is not project-owned or a current field
  observation. See the [service metadata](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer).

## Production and farm-business foundation cards

The nine foundation cards under `data/seed/production_foundations_v1.jsonl`
are project-authored summaries. Their seven public source pages or PDFs were
inspected and hashed; the external bytes are not redistributed. Source URLs,
snapshot hashes, locators, jurisdiction, and rights dispositions are in
`data/manifests/production_foundations_sources_v1.json`.
They remain a non-active development candidate rather than a default runtime
corpus.

Manitoba source concepts are attributed to Manitoba Agriculture under the
[OpenMB licence](https://www.gov.mb.ca/legal/copyright.html). The AAFC thermal-
time service is linked, with no AAFC page text reproduced; its site terms
restrict commercial redistribution without separate permission. Iowa State
Extension's partial-budget page is linked but its source-text redistribution
rights were not established, so only a project-authored method summary is
included. USDA ERS, NRCS, and ARS pages are attributed to their agencies;
embedded third-party material is not reused. These source links do not grant
training permission or imply the publishers endorse this project.
## Field-data research and development question seeds

The September 2026 field-data research catalog is discovery metadata, not a
runtime or training admission. Per-record rights, access limits, and source
links are recorded under `docs/reviews/artifacts/field-data-20260927/`.
Downloaded raw samples are excluded from the public package.

The source-derived examples in `sample-question-seeds.json` and the small
exposed development fixtures under `data/eval/field_data_pilot_v1/` retain
the following source terms. The latter manifest records the exact source CSV
hashes, projected columns and original row locators; project-authored gold
answers remain separate from the imported data.

- **Laurent et al., Late-season corn stalk nitrate measurements across the
  US Midwest from 2006 to 2018**, USDA Ag Data Commons,
  [DOI 10.15482/USDA.ADC/1527976](https://doi.org/10.15482/USDA.ADC/1527976),
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The project
  selected rows, drafted questions and calculated summaries; these are
  exposed development examples, not the publisher's benchmark or endorsement.
- **Topographic position index predicts within-field yield variation in a
  dryland cereal production system**, USDA Ag Data Commons,
  [record 28914434](https://agdatacommons.nal.usda.gov/articles/dataset/Data_from_Topographic_position_index_predicts_within-field_yield_variation_in_a_dryland_cereal_production_system/28914434),
  CC0. The examples preserve source hashes, record locators, moisture-basis
  limits and the distinction between sample-location and whole-field yield.

UBC Farm records are cataloged under CC BY-NC-SA 4.0 and remain a separate
local research lane; the public package does not include their raw tables.
The UBC-specific source-derived examples in the Canadian research notes are
attributed to [UBC Farm / Centre for Sustainable Food Systems](https://borealisdata.ca/dataverse/UBC_CSFS)
and retain [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
terms. They are outside the project's Apache-2.0 grant and should be excluded
from an unrestricted commercial content bundle unless separately cleared.
Their record links and restrictions remain in the Canadian research notes.
Conditional and unknown-license entries are not grants to redistribute,
train on, or commercially use the underlying data. The Apache-2.0 project
license does not replace any source-specific terms.

## Runtime dependencies and model

Direct runtime dependencies use permissive licences recorded in their package
metadata, including Agno (Apache), cryptography (Apache-2.0 or BSD-3-Clause),
React (MIT), and Leaflet (BSD-2-Clause). The installed frontend metadata also
includes `caniuse-lite` data under CC BY 4.0. Distribution should retain the
licence files supplied by packaged dependencies.

Model weights are not redistributed in this repository or portable archive.
The user downloads the pinned `mlx-community/gemma-4-e2b-it-4bit` revision
separately and remains responsible for its model licence and acceptable-use
terms.

## Project software licence

Unless otherwise noted, project-authored repository contents are licensed
under the Apache License, Version 2.0, as provided in the root `LICENSE` file.
That licence does not relicense third-party datasets, evaluation material,
dependencies, external publications, or model weights; those assets remain
subject to the terms identified above and in their governed source records.
