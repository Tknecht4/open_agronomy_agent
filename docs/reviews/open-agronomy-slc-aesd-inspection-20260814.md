# SLC v3.2 and 2021 AESD inspection receipt

**Status:** inspection complete; neither source is activated in a spatial profile, RAG profile, runtime lookup, distributable bundle, or training set.

**Decision:** the current Prairie DSS package has a verified exact identifier relationship to SLC v3.2. This permits a later, separate, context-only SLC prototype. The full AESD geodatabase is **not admitted**: it is a broad aggregate-statistics source with source-method variation by variable and province. A future compact AESD index must contain no values until an explicit variable allowlist is approved.

## 1. Official source identity and frozen inspection bytes

| Candidate | Official record and resource | Licence observed in catalogue API | Frozen raw inspection artifact |
| --- | --- | --- | --- |
| Soil Landscapes of Canada (SLC) v3.2 | Open Government dataset `5ad5e20c-f2bb-497d-a2a2-440eec6e10cd`; GPKG resource `e4bbe76e-20e2-4c5f-b29b-1e9b331715aa`; [GPKG](https://agriculture.canada.ca/atlas/data_donnees/soilLandscapesOfCanada3_2/data_donnees/gpkg/soil_landscapes_of_canada_v3r2.gpkg) | Open Government Licence - Canada, `ca-ogl-lgo` | Temporary inspection workspace file `soil_landscapes_of_canada_v3r2.gpkg`; 52,809,728 bytes; SHA-256 `aa5279de511b629f5668cb6bbbec5293289b9bd23a794e12913461106311cee3` |
| SLC v3.2 attribute suite | Same dataset; [official CSV directory](https://agriculture.canada.ca/atlas/data_donnees/soilLandscapesOfCanada3_2/data_donnees/csv/) | Open Government Licence - Canada, `ca-ogl-lgo` | Temporary inspection workspace directory `slc_csv/`; ten CSV files, 16,699,717 bytes total; per-file SHA-256 values were frozen during inspection |
| SLC v3.2 specification | Same dataset; resource `710ba2a6-d7e4-4151-98d3-c1560a7e9a34`; [English PDF](https://agriculture.canada.ca/atlas/data_donnees/soilLandscapesOfCanada3_2/supportdocument_documentdesupport/en/ISO_19131_Soil_Landscapes_of_Canada_Data_Product_Specification.pdf) | Open Government Licence - Canada, `ca-ogl-lgo` | Temporary inspection workspace file `ISO_19131_Soil_Landscapes_of_Canada_Data_Product_Specification.pdf`; 689,904 bytes; SHA-256 `5c83b3ad272cd2352f2a032a348c738a087d46eee221abb7a2c75834cb102f62` |
| 2021 Census of Agriculture AESD | Open Government dataset `83096e57-6584-4a8c-9854-59a49e57fb28`; AESD GDB resource `ff3451d3-43d1-4208-b93f-f8aae4cb65fe`; [GDB ZIP](https://ftp.maps.canada.ca/pub/statcan_statcan/Agriculture_Agriculture/AESD-DSAE/2021_AESD_DSAE.gdb.zip) | Open Government Licence - Canada, `ca-ogl-lgo` | Temporary inspection workspace file `2021_AESD_DSAE.gdb.zip`; 91,787,325 bytes; SHA-256 `1e0a04a223e078512953f0308b751f8845f40ab44446f7f75ac687509ceee631` |
| AESD user guide | Same dataset; resource `de8907aa-f2f5-4491-9e8a-cc9d35bcebee`; [English PDF](https://ftp.maps.canada.ca/pub/statcan_statcan/Agriculture_Agriculture/AESD-DSAE/AESD2021_UserGuide_FINAL_EN.pdf) | Open Government Licence - Canada, `ca-ogl-lgo` | Temporary inspection workspace file `AESD2021_UserGuide_FINAL_EN.pdf`; 549,837 bytes; SHA-256 `2bb10d49830d37c3c89cd2044bb9499d0eb047cdb411f1fe2eef23afd2c92038` |

Frozen catalogue API responses are stored beside these files as `slc_catalogue.json` (SHA-256 `1dcbd7225cf03891c619dbea92ecf509e9cffc7105b6aad797b55a80ec585a59`) and `aesd_catalogue.json` (SHA-256 `6ac0d9643c4e628ff03492fec8ad3146ab5f9849cb6fd84db80826ad2180d299`). Catalogue records do not provide resource checksums; the raw byte hashes above are therefore required for any reproducible later installation.

The exact CSV checksum set is:

| Official CSV | Bytes | SHA-256 |
| --- | ---: | --- |
| `ca_all_slc_v3r2.csv` | 654,587 | `32a30c303cfa4743a4c311eca0c6aa83b55884b03746459bdce9fee9202d8768` |
| `ca_all_slc_v3r2_cmp.csv` | 1,561,929 | `43f4a43eba1651a845d70d6c1266490cc584f1efa948a3b616c0b7f0d02c8e8c` |
| `ca_all_slc_v3r2_crt.csv` | 730,109 | `bfea22e69ab8a48f40fe4d7d81f26f737c819620eada7e015de0dbf5871fe7b9` |
| `ca_all_slc_v3r2_eft.csv` | 25,682 | `79a97fab1eb6417e936586ca2dc162687669c96180124238db55078f571cace8` |
| `ca_all_slc_v3r2_lat.csv` | 439,650 | `1cc4aad7bbc1bc26f5ae415b41c0b22f2526a6561f830a69905bab37dadbb823` |
| `ca_all_slc_v3r2_ldt.csv` | 5,974 | `5986b944176ab3918ce629a042c392b38acac119fd1c435f7f29c02eff5bac7a` |
| `ca_all_slc_v3r2_let.csv` | 199,361 | `ad22b7ce09e2fb8d24a69b391b60da173c8f3c16cc62b0b750d94d1c4dd1f1c5` |
| `ca_all_slc_v3r2_lst.csv` | 2,764,500 | `23f8049e0be8522ff56118bdae1c275361ef4f84d5354a6c8fe9c91d019636dc` |
| `ca_all_slc_v3r2_slt.csv` | 8,957,879 | `d07c4a01605c587f4f201d132fc713638242d9fe714ddf14225230f5f0df8da6` |
| `ca_all_slc_v3r2_snt.csv` | 1,360,046 | `8c1ae90a9675ce2300c416165d759a4c592e17559c045e5bcc3e5e7df66c3ca8` |

The 2021 AESD guide is labelled December 2022 and updated March 2026. The current server reports April 2026 file timestamps for the GDB and guide. The raw byte pin, not a filename or server timestamp, is the operative source identity for a later installer.

## 2. Observed data structure

### SLC v3.2

The GPKG is an EPSG:4269 `MULTIPOLYGON` layer named `ca_all_slc_v3r2`, with 12,353 polygon features and 12,353 distinct `POLY_ID` values. It contains only `OBJECTID`, `Shape`, geometry statistics, `POLY_ID`, and `ECO_ID`. It is not a self-contained soil-attribute database.

The linked official CSVs supply the required relational context:

- `ca_all_slc_v3r2_cmp.csv`: 20,425 component rows keyed by `POLY_ID` and `CMP_ID`.
- `ca_all_slc_v3r2_snt.csv`: 14,062 soil-name rows keyed by `SOIL_ID`.
- `ca_all_slc_v3r2_slt.csv`: 61,904 soil-layer rows keyed by `SOIL_ID`.
- `ca_all_slc_v3r2_eft.csv`: 1,027 ecological-framework rows keyed by `ECO_ID`.
- `crt`, `lat`, `ldt`, `let`, and `lst` supply ratings, area, landform, and segmentation relationships.

The official specification describes SLC as a 1:1,000,000 compilation. `SLC_ID` is the 1- to 4-digit ecodistrict identifier followed by a three-digit SLC polygon number. More than one spatial polygon may share an SLC ID in the source model, so any later installer must validate actual release cardinality rather than assume the current release's one-to-one `POLY_ID` result. Most importantly, the specification says that component locations inside a polygon are not defined. A point or field intersection cannot select a component or turn it into field truth.

### AESD 2021

The GDB archive is valid and expands to 108 MB. It has two `MULTIPOLYGON` layers in Canada Albers equal-area coordinates:

- `AESD21Data_BySLCV32_Final`: 3,889 rows, with 3,889 non-null and unique `SLCUIDV32` strings.
- `AESD21Data_ByWShedv5_Final`: 577 sub-sub-drainage-area rows.

The SLC AESD layer exposes both `SLCUIDV32` (string) and `SLC` (float64). `SLCUIDV32` is the only candidate join key: every one of its 3,889 values exactly matched an SLC v3.2 `POLY_ID`; `SLC` has `.0` numeric representation and requires coercion. A future runtime must reject numeric coercion, zero padding, truncation, prefix/suffix matching, and any arbitrary spatial fallback.

The guide says AESD uses Census of Agriculture values and alternative datasets chosen per variable and province. It describes 3,889 SLC regions and 577 drainage regions. It also says that the source chosen for an individual value may vary and is not disclosed in release data. Crop and land-use values have different treatment from land-input values; the guide specifically says that land-input values were not redistributed using alternative data. These facts block raw AESD use as crop- or field-level evidence.

## 3. Current DSS join test

The test read an installed `prairie-dss-v1` build from the operator-managed state root, decompressed each feature's published `soil_landscape_id`, and compared its **exact string** to the downloaded SLC `POLY_ID` and AESD `SLCUIDV32` sets.

| Current DSS source | Distinct nonempty `soil_landscape_id` values | Exact SLC v3.2 matches | Exact AESD `SLCUIDV32` matches |
| --- | ---: | ---: | ---: |
| Alberta | 637 | 637 / 637 | 622 / 637 (97.64%) |
| Saskatchewan | 799 | 799 / 799 | 794 / 799 (99.37%) |
| Manitoba | 357 | 356 / 357 | 242 / 356 valid SLCs (67.98%) |
| Union | 1,735 | 1,734 valid SLCs | 1,600 / 1,734 valid SLCs (92.27%) |

The only Manitoba nonmatch is the literal string `"0"`. It is not an SLC identity and must become `not_available`, not numeric zero, empty regional context, or an inferred alternative. Valid IDs have 4 to 7 digits and no leading-zero cases were observed. Cross-province duplicate SLC IDs occur in the source union, so a later context receipt must retain the original DSS source/layer and matched ID rather than treating `slc_id` as a province identity.

Frozen controls:

- Positive: `757004` occurs in 299 Manitoba DSS features, exactly one current SLC polygon, and exactly one AESD SLC row. The SLC component table has seven components for it; the largest is 45%, then two at 20%. This is a concrete demonstration that the region does not identify a component at a field point.
- Negative: `72700631` matches neither downloaded SLC nor AESD. Do not truncate it to a superficially plausible six-digit identifier.
- Negative: `"0"` matches neither source and must remain unavailable.

The relationship is therefore **lossless only where an exact key exists and AESD has coverage**. It is not a claim of national or field coverage.

## 4. Admission decision and safe model role

### SLC v3.2: conditional local-prototype candidate

SLC may later be installed as a separate `slc-context-v1` profile, after a builder stores a compact relational projection or spatial database with raw hashes, CSV-set hashes, source ID, release metadata, scale, coverage, and explicit `mapped_prior` boundary. It must not be added to the agronomic document corpus or treated as a current field observation.

At most, a field packet may say that a field/DSS polygon has an exact matched SLC identifier and present a regional, multi-component context summary with the source date/scale and a statement that component locations are not spatially resolved. SLC can help route regional documents or plan field observations and sampling; it cannot diagnose a field, assert a drainage class at a point, establish nutrient status, or set a management rate.

### AESD 2021: hard no-go for raw ingestion or immediate v3 use

Do not ship, retrieve, or expose the raw AESD feature layer or its 184 aggregate crop, livestock, practice, and land-input value fields (plus two identifier fields). This would create a false impression of field/farm specificity and silently combine values with undisclosed variable/province source methods. It also risks direct use of historical, aggregate land-input and crop values as recommendations.

No AESD value is admitted now. Training remains prohibited. The only permissible next artifact is an **empty-value availability index** that proves exact spatial compatibility and makes missing coverage visible.

## 5. Proposed compact context table, no values admitted

The initial derived table should be named `slc_aesd_context_index_v1` and be separate from the RAG store. It is a lookup index, not a source of agronomic recommendations.

| Column | Type / permitted value | Purpose |
| --- | --- | --- |
| `slc_uid_v32` | `TEXT PRIMARY KEY`; exact byte-for-byte `AESD21Data_BySLCV32_Final.SLCUIDV32` | Sole join key; do not derive from `SLC` float or normalize any supplied DSS value. |
| `source_id` | constant `ca_statcan_2021_aesd` | Explicit identity. |
| `source_resource_id` | constant `ff3451d3-43d1-4208-b93f-f8aae4cb65fe` | Binds the selected raw source. |
| `reference_year` | integer `2021` | Prevents present-tense interpretation. |
| `source_release_label` | constant `2021_AESD_DSAE` | Human-readable release identity. |
| `raw_sha256` | pinned 64-character hash | Requires raw-byte identity. |
| `join_contract` | constant `exact_string_slcuidv32_only` | Makes zero padding, numeric coercion, truncation, prefix matching, and spatial fallback invalid. |
| `coverage_status` | `available` only for physically present AESD IDs; caller emits `not_available` otherwise | Keeps incomplete AESD coverage explicit. |
| `context_role` | constant `aggregate_historical_regional_context_only` | Prohibits field/farm/management interpretation. |
| `method_limit` | constant source-method warning | States that AESD source choice varies by variable/province and is not disclosed in the released row. |
| `value_selection_state` | constant `no_values_admitted` | Prevents raw numerical attribute use before a variable contract. |
| `field_truth_boundary` | constant `not_field_observation_or_prescription` | Travels with every runtime result. |

The index contains no crop, practice, livestock, land-input, yield, area, or manure values. A later value table is blocked until a human approves a source-specific variable contract specifying every variable code, unit, 2021 reference semantics, geographic aggregation, missing/suppression behaviour, source-method warning, permitted question types, answer boundary, and a retrieval/answer A/B evaluation proving incremental benefit without unsupported prescriptions.

## 6. Required implementation gates

1. Freeze the raw source set in a user-owned local data root, not Git, with the hashes above and an installer receipt.
2. Build a deterministic SLC relational projection that validates the current release's identifier/cardinality rules and emits `not_available` for `"0"`, unmatched IDs, and absent profiles.
3. Add a lookup-only context packet section; show source, source date, matched ID, coverage state, scale, and the `mapped_prior`/`context_only` boundary before the model sees any prose summary.
4. Keep the AESD raw GDB and its values excluded. Permit only `slc_aesd_context_index_v1` until a separate value allowlist and evaluation gate pass.
5. Test three frozen controls in CI: positive `757004`, malformed/nonexistent `72700631`, and sentinel `"0"`.

This receipt does not approve a runtime profile, default configuration change, public-release manifest entry, downstream source-derived RAG content, or training use.
