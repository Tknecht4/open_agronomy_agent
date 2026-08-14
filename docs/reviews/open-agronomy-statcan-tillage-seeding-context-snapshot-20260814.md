# Statistics Canada tillage and seeding context snapshot — 2026-08-14

## Decision

**Admit only as an optional local aggregate historical-context snapshot.**

Statistics Canada table 32-10-0367-01, *Tillage and seeding practices,
Census of Agriculture, 2021*, is authoritative, geographically compatible
with the installed 2021 Statistics Canada Province/Territory and Census
Agricultural Region (CAR) layers, and distributed under the Statistics Canada
Open Licence.  Its values are nevertheless aggregate 2021 Census results,
not field or farm observations.  It is therefore excluded from RAG, the
default runtime configuration, generic field context, training, and any
recommendation path.

The only admitted derived artifact is a local SQLite snapshot that can be
looked up by a **published exact 2021 DGUID** after an explicitly authorized
future context-composer integration.  There is no fuzzy name, geometry,
province, partial-code, or nearest-region fallback.

## Inspected source and licence

| Item | Verified value |
| --- | --- |
| Publisher | Statistics Canada, Census of Agriculture |
| Table | [32-10-0367-01 — Tillage and seeding practices, Census of Agriculture, 2021](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210036701) |
| Frequency / release | Every five years; released 2022-05-11 |
| Staged raw archive | External-only `ca_statcan_tillage_seeding_2021/source.zip` |
| Archive source | [Official CSV download](https://www150.statcan.gc.ca/n1/tbl/csv/32100367-eng.zip) |
| Raw bytes / SHA-256 | 383,321 bytes; `0fe0a2f9d3dcd02fa68ef2207da8932b5a3f631c29a624f8f1f8593bf0f2d216` |
| Main CSV member | `32100367.csv`, 5,078,624 bytes; `14c842e5765d075c761037b2302e7d087a9893441bc04ff484b10cd69a128fa0` |
| Metadata member | `32100367_MetaData.csv`, 166,591 bytes; `e23363ba8be16b5ba47702f0c7ecdafe9d3493493094bd2451738171777a1b55` |
| Licence | [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence): reviewed local copy permits use, reproduction, distribution, adaptation, and sublicensing, subject to source acknowledgement and its other terms |
| Required attribution | “Adapted from Statistics Canada, Tillage and seeding practices, Census of Agriculture, 2021. This does not constitute an endorsement by Statistics Canada of this product.” |

The source page describes the available geography levels as Canada, province
or territory, census division, CAR, and census consolidated subdivision.  The
snapshot intentionally retains only the exact published provincial and CAR
records.

## Schema and data inspection

The raw table has 25,356 rows.  Geographic-class row counts are 48 Canada,
120 province, 828 CAR, 3,396 census division, and 20,964 census consolidated
subdivision.  The snapshot retains 948 rows: twelve published combinations
(four tillage practice categories × three units) for each of 10 provinces and
69 CARs.

The retained categories are the source's four practice rows and these units:
`Number of farms reporting`, `Acres`, and `Hectares`.  The builder stores the
original `VALUE`, `STATUS`, `SYMBOL`, vector, coordinate, scalar, and unit
fields without interpreting them.  Among the retained rows, source `STATUS`
counts are A=252, B=372, C=144, D=48, E=56, and F=76.  `SYMBOL` is blank on
every retained row.  Seventy-six source `VALUE` fields are blank (six
province and 70 CAR rows); they are stored as a missing published value with
the exact source status retained.  A blank `VALUE` or a status letter is
**not** relabelled as suppression or assigned a new meaning by this project.

## Exact spatial join result

The installed 2021 boundary pack exposes the official
`dissemination_geography_id` (DGUID) field.  Every retained source geography
matches that field byte-for-byte:

| Layer | Source IDs retained | Boundary IDs available | Result |
| --- | ---: | ---: | --- |
| Province/Territory | 10 provinces | 13 (the three territorial records are not in this source table) | 10/10 exact DGUID matches |
| Census Agricultural Region | 69 CARs | 72 (three territorial CAR records are not in this source table) | 69/69 exact DGUID matches |

For example, source `PR480000000` maps only to DGUID `2021A000248` and the
boundary feature `PR_48`; source `CAR481000000` maps only to DGUID
`2021S05014810` and boundary feature `CAR_4810`.  The builder rejects a
misformatted published code, inconsistent DGUID, wrong boundary source,
wrong boundary feature code, or a source DGUID absent from the installed
layer before it creates output.

## Derived local artifact

The verified local output is outside the Git checkout:

| Artifact | Verified value |
| --- | --- |
| SQLite snapshot | `$OAA_STATE_ROOT/derived/census_agriculture_context/ca_statcan_2021_tillage_seeding_context_v1.sqlite3` |
| Receipt | `$OAA_STATE_ROOT/derived/census_agriculture_context/ca_statcan_2021_tillage_seeding_context_v1.manifest.json` |
| Snapshot size / SHA-256 | 602,112 bytes; `cfa8169b3292c8ccf8a2386050718f9438e3d75c4704f5438009f1e5cd61677e` |
| Exact geography keys | `geographies.geography_dguid` (primary key) and `published_geography_code` (unique) |
| Observation key | `(geography_dguid, tillage_practice, unit_of_measure)` |
| Context role | `aggregate_historical_regional_context_only` |
| Validation | 79 geographies / 948 observations / zero errors |

`scripts/build_statcan_tillage_seeding_context_snapshot.py` creates and
validates the snapshot.  It pins the raw archive and both CSV members,
requires the installed province and CAR boundary databases, writes only to an
external local-state destination, and refuses to replace an existing result
without `--replace`.  Its focused tests include successful exact joins,
published blank/status preservation, a missing valid CAR DGUID, and a
noncanonical published CAR code.

## Model and product boundary

The snapshot is **not currently delivered to the model**.  The safe future
flow, if separately approved, is:

1. a field geometry intersects the installed 2021 CAR boundary;
2. the service returns its cited DGUID and boundary provenance;
3. a context composer makes an exact local lookup in this SQLite table; and
4. an explicitly labelled, historical aggregate context capsule is shown to
   the user and, only where answer policy permits, to the model.

The capsule must carry the reference year, source table and URL, DGUID, unit,
published status/symbol, context role, and the boundary that it is not field
or farm truth.  It may help a user understand a historical regional pattern
or decide which local information to collect.  It must not claim what a
specific field did, infer a grower's practice, supply a target or rate, or
override current field evidence, scouting, soil tests, labels, regulations,
or provincial agronomic guidance.

This receipt does not add a source-manifest entry, install a default profile,
authorize values for RAG or fine-tuning, or approve a model-context API.
