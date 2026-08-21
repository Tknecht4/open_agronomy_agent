# Canadian offline source-admission candidates

`data/manifests/canada_offline_source_admission_candidates_v1.json` is a compact, metadata-only research queue. It is intentionally **not** a download manifest, a spatial-pack manifest, a runtime-retrieval policy, a licence grant, or a model-training authorization. Every record is `candidate_not_admitted`; the validator rejects any attempt to enable fetching, local RAG, a distributable bundle, runtime lookup, or training.

The queue supports a post-clone workflow: download an explicitly selected source into a local data root, preserve byte lineage, build a compact derived store, validate it, then make a separate runtime-policy decision. No large gridded source is in scope here.

## What is covered

| Target | Official identity checked | Compact future role | Critical boundary |
|---|---|---|---|
| Province/territory boundaries | [Statistics Canada 2021 boundary files](https://open.canada.ca/data/en/dataset/ef70dc3b-1069-4037-9bce-61f47e628a1d), record `ef70dc3b-1069-4037-9bce-61f47e628a1d` | A small province/territory lookup layer | Administrative geography is not a field or legal boundary. |
| Census agricultural regions | [The same 2021 boundary record](https://open.canada.ca/data/en/dataset/ef70dc3b-1069-4037-9bce-61f47e628a1d) includes CARs | Statistical-geography routing | A CAR cannot identify a field practice, rate, or condition. |
| Ecoregions | [AAFC Terrestrial Ecoregions](https://open.canada.ca/data/en/dataset/ade80d26-61f5-439e-8966-73b352811fe6), record `ade80d26-61f5-439e-8966-73b352811fe6` | Compact ecoregion polygon/identifier lookup | Broad ecology is not local soil, weather, pest, or management truth. |
| Soil Landscapes of Canada v3.2 | [AAFC SLC v3.2](https://open.canada.ca/data/en/dataset/5ad5e20c-f2bb-497d-a2a2-440eec6e10cd), record `5ad5e20c-f2bb-497d-a2a2-440eec6e10cd` | Queryable mapped-soil prior with a reviewed compact table projection | Polygon components do not establish a point soil, current nutrient status, drainage, salinity, or a rate. |
| AESD 2021 | [Statistics Canada AESD](https://open.canada.ca/data/en/dataset/83096e57-6584-4a8c-9854-59a49e57fb28), record `83096e57-6584-4a8c-9854-59a49e57fb28` | Selected historical aggregate context tables only | Spatially allocated Census values are not farm observations or current field history. |
| Census of Agriculture linked boundaries | [Statistics Canada linked Census of Agriculture data](https://open.canada.ca/data/en/dataset/b944bd53-49e5-4a80-83e5-1048d3abf38d), record `b944bd53-49e5-4a80-83e5-1048d3abf38d` | Explicitly selected PR/CAR/CD/CCS aggregate context | The publisher documents `-1` for confidential values; it is not zero or a measurement. |
| Agricultural ecumene | [Statistics Canada 2021 agricultural ecumene](https://open.canada.ca/data/en/dataset/462c0b06-6dd8-4e9d-9016-2f02230255bd), record `462c0b06-6dd8-4e9d-9016-2f02230255bd` | Optional display/routing mask | It is not proof that any parcel is farmed, crop-producing, or eligible. |
| University/extension intake | [University of Manitoba MAKE](https://umanitoba.ca/agricultural-food-sciences/make/make-ag-food-resources), [USask Soils and Crops](https://agbio.usask.ca/soilsncrops/resources/index.php), [Field Crop News](https://fieldcropnews.com/about/), [Dalhousie Wild Blueberry fact sheets](https://www.dal.ca/sites/wild-blueberry/publications/fact_sheets.html) | Discovery of individual documents and contacts | Hub identity does not establish rights, currency, regional applicability, or recommendation authority for any item. |

The canonical candidates contain direct resource URLs only as unfetched evidence pointers. A clone does not download any of them.

## Rights and training ledger

The official AAFC ecoregion and SLC catalogue records display the [Open Government Licence - Canada](https://open.canada.ca/en/open-government-licence-canada). It permits broadly described lawful reuse subject to attribution and exclusions. The candidate queue records that observation but does not promote it to project approval: the exact resource still needs byte freezing, attribution review, and a derivative-scope review.

Statistics Canada sources use the [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence), whose terms cover use and value-added products subject to attribution and other conditions. For each candidate, the selected resource, exact source date, attribution, potential third-party material, and statistics-specific safeguards remain unfrozen, so it is still not admitted.

Every candidate has the same training status: `not_assessed_no_training_authorization`, with `source_specific_authorization: false`. A public page, a catalogue open-licence statement, downloadability, or a general right to make a value-added product is never treated by this repository as a training-data decision. Training requires its own documented human decision after source-, derivative-, and purpose-specific rights review.

The four university/extension hubs are `permission_required`: each can link to co-authored, cited, embedded, historical, image, or third-party materials. Their metadata is retained for discovery only. The validator prohibits copying or training on them until a selected individual item clears the gates.

## Provincial extension already governed elsewhere

This new queue does not re-declare or override existing provincial-source policy. The current Canadian source registry already owns these source identities and their live/retrieval boundaries:

| Existing registry ID | Official source | Intake implication |
|---|---|---|
| `ab_soil_fertility_overview` | [Alberta Soil Fertility Overview](https://www.alberta.ca/soil-fertility-overview) | Alberta web content needs a source-specific rights determination; Alberta's general [copyright terms](https://www.alberta.ca/disclaimer) prohibit commercial reproduction unless permission or a specified alternative licence applies. |
| `mb_soil_fertility_guide` | [Manitoba Soil Fertility Guide](https://www.gov.mb.ca/agriculture/crops/soil-fertility/soil-fertility-guide/) | The [OpenMB licence](https://www.gov.mb.ca/legal/copyright.html) is a potentially usable publisher-wide basis, but exact edition, third-party material, local calibration and currentness are still separate gates. |
| `sk_guide_to_crop_protection` | [Saskatchewan Guide to Crop Protection](https://www.saskatchewan.ca/business/agriculture-natural-resources-and-industry/agribusiness-farmers-and-ranchers/crops-and-irrigation/crop-guides-and-publications/guide-to-crop-protection) | The source itself says the current product label is authoritative; it remains a discovery/current-authority boundary, not offline timeless product advice. |
| `on_pub811_agronomy_guide` | [Ontario Publication 811](https://www.ontario.ca/page/publication-811-agronomy-guide-field-crops) | The existing source registry keeps it quarantined: Ontario says [OGL-covered material is clearly labelled](https://www.ontario.ca/page/open-government-licence-ontario), and this item has not supplied a source-specific OGL label or written permission. |

Keeping these rows under their existing registry avoids two manifests making contradictory rights or runtime decisions.

## Required admission sequence

1. Select one exact logical resource and record its direct URL, publisher/source record, retrieval time, file size, SHA-256, version, and source attribution. Keep raw data outside Git.
2. Review source-specific rights, derivative rights, commercial/redistribution scope, third-party exclusions, and training as independent decisions.
3. For spatial data, prove CRS, field/region lookup behavior, identifiers, scale/temporal limits, and the mapping-to-field limitation. For AESD/Census, freeze an allowlist of variables with units, year, geography, allocation method, and suppression handling.
4. Produce a deterministic compact derivative in a user-local data root. For boundaries and ecoregions, retain only geometry, minimal identifiers, an RTree, and provenance. For SLC, retain a review-approved geometry-plus-attribute projection rather than duplicating the whole raw package. For Census context, retain selected aggregate attributes keyed to the approved geography rather than a general-purpose raw database.
5. Validate hashes, schemas, source/derived lineage, representative regional intersections, field-boundary wording, and package size. Then make a separate reviewed runtime-policy admission. This candidate queue cannot satisfy that final step.

## Validation

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_offline_source_admission_candidates.py
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_offline_source_admission.py
```

The first command is deliberately metadata-only. It checks stable source identities, HTTPS evidence links, all required gates, and fail-closed use flags; it does not contact a provider or download any source bytes.
