# Open Agronomy Agent compact offline knowledge and spatial-data implementation plan

**Status:** implemented and live-tested for the approved compact release boundary; candidate-source admission remains source- and geography-gated

**Date:** 2026-08-13
**Decision owner:** project maintainers, with source-rights review for every new acquisition

## 1. Decision and scope lock

The product should have two intentionally separate offline layers:

1. A compact, curated, redistributable Canadian knowledge store that is shipped in Git. A clone therefore has the reviewed text corpus without downloading it again.
2. An opt-in local spatial store that a clone prepares with a declared post-clone command. It downloads exact official inputs, builds verified local SQLite/RTree packs, and can be used wholly offline afterwards.

The first spatial profile is **Prairie DSS only**: the official Alberta, Saskatchewan, and Manitoba Detailed Soil Survey (DSS) releases. It is the source of spatial soil context for this implementation round. It is a mapped historical/regional prior, not a current field observation, soil test, diagnosis, suitability finding, or management-rate authority.

Large gridded products are explicitly out of scope for this round. This includes the candidate national 100 m Soil Landscape Grids, broad national rasters, DEMs, and crop-inventory rasters. They may be reconsidered only through a later size, coverage, uncertainty, and measured-utility gate.

The desired result is not a repository containing every source byte. It is a reproducible package boundary:

```text
Git clone (no network required for curated RAG)
  ├─ source code, tests, source registries, and profile contracts
  ├─ curated Canadian JSONL shards + hashes + rights receipts
  └─ setup/validation/release tooling

Explicit local setup (network required once per profile)
  ├─ raw official downloads in a user-selected state directory
  ├─ derived SQLite/RTree files and pack manifests
  └─ an install receipt bound to source/version/hash/build inputs

Offline runtime
  ├─ curated text retrieval from the clone
  └─ spatial intersections from a selected local pack; no remote fallback
```

## 2. Reference state observed in this checkout

The plan is designed around the current seams rather than an idealized replacement.

| Area | What exists now | Problem to resolve |
|---|---|---|
| DSS derivation | The Prairie builder can ingest AB/SK/MB DSS archives, preserve components and soil attributes, make WGS84 SQLite/RTree output, and enforce geometry/area checks. Representative app-path probes work for Edmonton, Regina, and Brandon. | Builders assume repository-relative assets and existing raw files; current derived manifests/symlinks are not a cloneable local package. |
| Spatial runtime | `AGRONOMY_AGENT_SPATIAL_PACK_ROOT` already lets the geospatial service read a flat external pack directory. | Validator, offline readiness, and portable-bundle tooling still assume databases exist under the repository. |
| Pack assembly | The existing Prairie pack builder expects AB, SK, MB DSS and erosion. | The requested DSS-only profile cannot be produced, and erosion has no complete source-to-pack path in this checkout. |
| Spatial registry | Eight sources are currently marked `bundled`. | A clean DSS-only installation is validated against layers that are deliberately not installed, so validation fails. `bundled` currently mixes source availability, release intent, and installation state. |
| Curated RAG | Multiple explicit `retrieval.corpus_paths` already work; governance requires each path to have an exact policy/hash record. | The generic document ingestor emits source shards but then recombines them. It has neither a shard-byte budget nor a store-level manifest. |
| Public release | The public-repository builder has an explicit file manifest and a 99,000,000-byte ceiling. | New shards need explicit inclusion/ignore rules and a tighter corpus-store budget. Large local spatial artifacts must remain outside Git. |

The current raw/derived DSS sizes reinforce that division. The three raw archives total about 459 MB and the derived SQLite files about 480 MB. A runtime-only pack is therefore reasonable as a local option, but it is not suitable for Git; retaining raw downloads for a reproducible rebuild needs roughly 0.9 GB plus temporary build headroom.

## 3. Target product contracts

### 3.1 Repository-managed curated knowledge store

Create one versioned, human-auditable store, initially at a path equivalent to:

```text
data/derived/rag/curated_canada/v1/
  store_manifest.json
  shards/
    decisive-0001.jsonl
    context-0001.jsonl
    context-0002.jsonl
  receipts/
    ingest_summary.json
    source_coverage.json
```

This is a **derived**, reviewable release artifact, not a raw-source archive. Raw PDFs/HTML, private overlays, model/index caches, and extraction work directories remain outside Git.

The store manifest must bind, at minimum:

- store/profile ID, release date, source-registry hash, builder/extractor version, and chunking parameters;
- every shard's relative path, SHA-256, byte count, row count, source IDs, language/jurisdiction coverage, and retrieval-policy counts;
- total unique `doc_id` and content-fingerprint counts;
- included and excluded source IDs with reasons, source-rights snapshots, and policy role;
- a statement that RAG admission does **not** grant fine-tuning or other training permission.

Use a hard **24 MiB uncompressed shard target**. It is comfortably below the current public-release file ceiling, allows clear diffs and source-local repair, and avoids another near-limit corpus object. Pack deterministically by retrieval policy first (`decisive` and `context_only` may never be mixed), then source ID, source edition/hash, and chunk index. Split only between complete JSONL records.

Runtime must continue to receive an explicit ordered list of shard paths in each RAG configuration. Do not add dynamic directory discovery in the first implementation: the agent, corpus audit, evaluator, benchmark service, readiness checks, portable bundle, and update tooling all currently reason about explicit `corpus_paths`. Generate those lists from the store manifest and test exact agreement among manifest, config, and policy file.

Two profiles are appropriate:

- `canada-offline-core`: Canadian curated material only; the default compact clone profile.
- `canada-offline-extended`: opt-in supplements such as the near-100-MB NRCS analogue corpus, after it is sharded or retained as an explicit optional corpus. It must not silently dominate a Canada-first profile.

Separate core and extended corpus-policy manifests are preferable to a single permissive policy, because the current governance contract deliberately rejects policy rows that are not active in a configuration.

### 3.2 Local spatial-state directory

Use a user-selected state directory, never a repository data path, for downloaded/derived geospatial assets:

```text
<state-dir>/
  raw/canada_agronomy/<source-id>/source.zip
  raw/canada_agronomy/<source-id>/source.zip.lineage.json
  derived/geo_layers/
    ab_detailed_soil.sqlite3
    ab_detailed_soil_manifest.json
    sk_detailed_soil.sqlite3
    sk_detailed_soil_manifest.json
    mb_detailed_soil.sqlite3
    mb_detailed_soil_manifest.json
  spatial-pack/prairie-dss-v1/
    prairie_spatial_pack_manifest.json
    install_receipt.json
    ab_detailed_soil.sqlite3
    ab_detailed_soil_manifest.json
    sk_detailed_soil.sqlite3
    sk_detailed_soil_manifest.json
    mb_detailed_soil.sqlite3
    mb_detailed_soil_manifest.json
```

The runtime pack is flat because that matches the existing geospatial-service lookup. No symlinks are allowed in a release pack. No SQLite file is arbitrarily split: SQLite/RTree integrity, atomic copying, and a whole-file hash are the portability boundary.

Each installed pack manifest must record the selected profile; required source/layer IDs; source URL/version; raw SHA-256; source-registry-entry SHA-256; licence attribution; builder/version hash; output SHA-256; feature/component counts; source scale; CRS/geometry handling; and the mapped-prior limitations presented to the model and UI.

Raw retention is a deliberate setup choice:

- The initial safe default retains verified raw archives alongside derived databases, lineage, and hashes for local reproducible rebuilds and byte-level audit.
- `--discard-raw-after-build` removes exact verified raw archives only after a successful build and application-path verification. The pack receipt records that raw bytes are no longer retained.

In both modes, the pack receipt must make missing raw bytes explicit rather than implying they are present.

## 4. Spatial profiles and source-admission roadmap

Profiles, source registry, installation status, and public-release status must become distinct concepts. A source can be known to the registry without being installed, a candidate without being accepted, or installable without being present in a particular pack.

| Profile / stage | Contents | Product role and boundaries | Admission status |
|---|---|---|---|
| `prairie-dss-v1` — implement first | Alberta, Saskatchewan, Manitoba DSS only | Compact regional mapped-soil context; component and soil-landscape linkage; never current field truth or a rate source. | Approved implementation target; the three official DSS registry records already provide the input contract. |
| `prairie-dss-erosion` — later, optional | Existing DSS profile plus AAFC 2021 erosion context | Historical/modelled regional context only. | Deferred until there is a complete deterministic erosion downloader/builder/validation path. It must not block `prairie-dss-v1`. |
| `canada-boundaries-v1` — phase two | Province/territory boundaries plus a compact National Ecological Framework hierarchy (eco-zone, eco-province, eco-region, eco-district where officially available) | Location/applicability routing and explainable regional labels; not agronomic proof. | Candidate. Admit only after the exact official vector record, licence, version, scale, topology, simplification tolerance, and offline size are reviewed. The current National Ecological Framework *document* is not automatically permission to redistribute a derived vector pack. |
| `census-agriculture-context-v1` — phase three | A compact Statistics Canada/AAFC Census of Agriculture attribute table, keyed by an exact published regional identifier and year | Context-only regional statistics; never grower data, field observations, recommendation authority, or a proxy for a particular farm. | Candidate. Investigate AAFC's Agricultural Economic Spatial Database (AESD) and its data dictionary first. |
| `slc-context-v1` — later candidate | Soil Landscapes of Canada polygon/component context, potentially linked to the DSS `soil_landscape_id` | National/regional spatial hierarchy and location join; polygons can contain contrasting components. | Candidate, not a substitute for DSS and not a grid. Requires a separate vector-source contract and a meaningful compactness/coverage test. |
| National grids/raster products | 100 m Soil Landscape Grids, crop-inventory raster, DEMs, similar products | Potentially useful screening priors but not field truth. | Explicitly deferred. Do not download, package, or use them to satisfy national coverage in this plan. |

The expected future spatial hierarchy is deliberately simple and inspectable:

```text
field geometry
  -> province / territory
  -> ecological hierarchy (when the boundary profile is installed)
  -> SLC identifier (when installed or carried by a DSS record)
  -> DSS map unit and components (Prairie v1)
  -> optional Census-of-Agriculture regional context
```

Every returned spatial fact should retain source ID, source version/date, source scale, geographic coverage, matched identifier, installed-profile ID, and a `mapped_prior` / `context_only` boundary. The answer system must be able to say `not_installed` or `out_of_coverage`; it must not replace either result with an invented national result.

The present DSS builder already retains a soil-landscape identifier (`SLC_V3R2` exposed as `soil_landscape_id`). That creates a promising **future** compact join to AESD without shipping a duplicate national polygon file, but it must be tested against the exact AESD identifier/version before adoption.

## 5. Ingestion, local setup, and repackaging design

### 5.1 One explicit post-clone entry point

Add a single orchestrator, proposed as `scripts/setup_offline_data.py`, rather than asking a user to run several undocumented builders. Its conceptual interface is:

```bash
PYTHONPATH=src .venv/bin/python scripts/setup_offline_data.py \
  --profile prairie-dss-v1 \
  --data-root <state-dir> \
  --download --build --verify
```

It should support `--dry-run`, `--download`, `--build`, `--verify`, `--retain-raw`, and a deliberately named `--profile`. It must never initiate network traffic implicitly while merely starting the application or checking readiness.

For a selected profile, the orchestrator must:

1. Read only registry-declared source URLs and profile-declared source IDs.
2. Check licence and use-policy eligibility before download.
3. Stream each download into a temporary `.part` path, record publisher metadata/content length when available, compute SHA-256, and atomically promote only after verification.
4. Write immutable source-lineage sidecars binding URL, retrieval time, source record/version, raw hash, and source-registry-entry hash.
5. Invoke the existing province derivation logic with explicit source, lineage, output, and manifest paths under the selected state directory.
6. Run existing/raw integrity, feature-count, geometry, SQLite, RTree, and representative-intersection checks.
7. Assemble a flat runtime pack and its manifest only after all required layers validate.
8. Emit an install receipt and the exact `AGRONOMY_AGENT_SPATIAL_PACK_ROOT` value needed by the offline runtime.

Reruns are idempotent: an exact verified asset is skipped; changed publisher bytes, stale manifests, an unregistered URL, insufficient disk space, or a partial build fails closed. A failed build may leave diagnostics in a temporary area but never promotes a partial database or a new manifest over a known-good one.

### 5.2 Refactors required for the DSS profile

1. Add a versioned `offline_spatial_profiles_v1.json` (name subject to normal project naming review). `prairie-dss-v1` contains exactly the AB/SK/MB source and layer IDs.
2. Make the Prairie DSS builders state-directory aware. Paths recorded in their manifests must be relative to the selected asset root/package, not the repository root.
3. Make the Prairie pack builder profile-driven. Preserve a compatibility profile if useful, but do not require erosion in the DSS-only path.
4. Change spatial-registry semantics. Replace the overloaded `runtime.status=bundled` test with profile membership and a separately recorded install/release state. A global registry audit must not fail because a profile intentionally omits another valid candidate layer.
5. Teach `validate_canada_geospatial_sources.py`, offline readiness, portable-bundle preparation, and the public packaging path to accept `--profile` and an external pack root/manifest.
6. Treat `AGRONOMY_AGENT_SPATIAL_PACK_ROOT` plus a verified pack manifest as the source of truth for an installed local profile. Repository-resident databases remain unsupported after this migration.

This yields three clear distribution modes:

- **Clone:** curated text knowledge, source/profile contracts, and installer; no local spatial pack required.
- **Prepared local offline runtime:** clone plus verified selected pack in the user's state directory.
- **Optional handoff bundle:** a separately verified pack may be moved alongside a clone for air-gapped transfer, but it is not committed to the public repository and retains its receipt/attribution.

### 5.3 Curated-text ingestion and repository repackaging

Keep the generic `ingest_document_sources.py` as the source-aware extractor. Give it a store-output mode that emits source shards and receipts without requiring a combined JSONL. Add a deterministic release builder, proposed as `scripts/build_curated_knowledge_store.py`, that:

1. Accepts only admitted source IDs from `canada_agronomy_sources.json`.
2. Reuses extraction/chunking logic, but stages raw/extraction work outside Git.
3. Validates source lineage, licence snapshot, currency, unique document IDs, and duplicate content fingerprints.
4. Refuses a source not authorized for `distributable_bundle`; it also refuses to imply that retrieval permission authorizes training.
5. Packs policy-segregated fixed-size Git shards and writes the store manifest and intake receipts.
6. Generates the core/extended RAG configurations and exact runtime-policy manifests from that store manifest.

Update the following surfaces together in the implementation change set, rather than partially updating one of them:

- `.gitignore`: unignore only the approved store manifest, receipts, and exact shard paths;
- `configs/public_repository_manifest.json`: include the store manifest/shards explicitly and enforce a total-store budget as well as the per-file ceiling;
- governed RAG configuration(s): list the exact core or extended shards in a deterministic order;
- runtime corpus policy manifest(s): one exact SHA-bound policy record per active shard;
- portable bundle and knowledge-update tooling: consume the generated explicit config, not a directory scan;
- public repository builder: prove raw files, databases, private overlays, temporary work, and local install receipts do not escape.

The current generic ingestor's combined corpus may remain as a legacy/internal artifact only while migration is in progress. It is not the future canonical portable Canadian store.

## 6. Canadian knowledge expansion and geographic linkage

The first implementation should build the packaging/rights/provenance machinery before admitting a large new document wave. Source expansion then becomes repeatable rather than a collection of untracked PDFs.

### 6.1 Admission pipeline for every document or dataset

For each candidate, collect and freeze a source record before extraction:

- publisher, canonical landing page, stable download URL, edition/date, jurisdiction, language, crop/topic coverage, and geographic applicability;
- licence snapshot and explicit decisions for local RAG, redistribution, commercial reuse, adaptation, and training;
- raw/extracted/chunk hashes, extractor version, access date, and source-specific limitations;
- authority type and intended retrieval role (`decisive`, `context_only`, live-only, or excluded);
- location metadata at the narrowest truthful published unit: Canada, province/territory, ecological unit, SLC/DSS identifier, municipality/county, or another named official geography;
- falsifiers: condition/date/version limits, missing coverage, conflicting guidance, and conditions requiring local advice or current field data.

Geographic metadata should route applicability, not manufacture precision. A document associated with an ecoregion or province may be surfaced as regional guidance; it does not become evidence that a particular field has the associated soil, weather, pest, or management condition.

### 6.2 Initial source queue

Prioritize official and permission-clear Canadian sources by crop/topic and province, then bind them to the geographic hierarchy above. The current active Canadian corpus is comparatively strong for Manitoba fertility/scouting and historical Alberta material; it has no university-published Canadian extension source installed. The next source review should therefore be systematic, not simply additive:

1. **Federal and provincial open-government material.** Continue with AAFC/Canadian Soil Information Service product specifications and official provincial agriculture publications where the record establishes redistribution/adaptation rights. This is the safest first source class for distributable RAG.
2. **Prairie field agronomy.** Build a gap matrix for crop fertility, rotations, residue/tillage, soil-water, salinity, drainage, crop protection, and economics across Alberta, Saskatchewan, and Manitoba. Assign each document province plus, where published, ecological/SLC/DSS applicability.
3. **Eastern, Quebec, British Columbia, and Atlantic regional guidance.** Add only source-by-source after rights review; this should reduce the current regional imbalance before expanding the extended profile.
4. **University and extension material.** Investigate University of Manitoba, University of Saskatchewan, University of Alberta, University of Guelph/OMAFRA-adjacent publications, Dalhousie/Atlantic resources, and similar regional extension work. Many public pages are readable but do not grant redistribution/adaptation rights by default. Treat them as `permission_required` or live-reference/discovery records until written permission or a precise open licence is recorded.
5. **Census and landscape context.** Admit a compact AESD/SLC-keyed context table only after its data dictionary, release/version, licence, identifier compatibility, and value allowlist are reviewed. It belongs in spatial context, not the decisive agronomic document corpus.

Known rights cautions from the current source survey remain hard gates: Field Crop News/OMAFRA material, several university sites, Perennia material, and pest-network content must not be copied into a distributable corpus merely because it is publicly accessible. A local or private overlay may use separately authorized material, but it must remain physically and policy-separated from the public curated store.

### 6.3 Fine-tuning dataset boundary

The information expansion may later support a fine-tuning dataset, but that is a distinct product with an explicit rights and provenance review. Each training row must cite its permitted source set, transformation method, curriculum/prompt purpose, and split membership. Do not create training examples from a RAG shard merely because the shard is redistributable; `training: false` remains effective unless separately changed with evidence and human approval.

## 7. Implementation sequence

### Phase 0 — freeze contracts and repair the existing soil-package semantics

- Add profile schema and `prairie-dss-v1` source/layer membership.
- Define pack/install-receipt schemas and the precise distinction among registry candidate, profile member, locally installed, and public-release artifact.
- Reconcile the current AB/SK/MB derived manifest paths/hashes against a fresh deterministic build; do not bless the existing symlinked outputs as a distributable pack.
- Record source byte/space estimates and source limitations in the profile manifest.

**Exit gate:** a profile can say exactly which three sources are required, and no global validator mistakes intentionally absent layers for missing `prairie-dss-v1` dependencies.

### Phase 1 — make local DSS preparation reproducible

- Implement the state-root-aware DSS builder changes and the single `setup_offline_data.py` entry point.
- Parameterize pack assembly by profile and install a flat DSS-only pack.
- Bind source lineage, raw/derived hashes, output counts, and provenance text into the pack and install receipt.
- Update runtime/readiness/portable validation to consume the external pack manifest.

**Exit gate:** a clean clone plus an empty user state directory can produce and validate the three-DSS pack with the explicit command, then serve the three representative offline intersections through the application path.

### Phase 2 — create the sharded curated Canadian knowledge release

- Add source-shard/store-manifest output to ingestion and the deterministic curated-store builder.
- Generate core/extended configuration and policy manifests from the store manifest.
- Update release packaging and ignore rules as one atomic release change.
- Make the compact Canada core the documented default; retain broader analogue material only through an explicit extended profile.

**Exit gate:** a fresh clone retrieves from the entire approved core store with no network, every shard is hash/policy/rights bound, and the public release contains neither raw/private data nor a near-limit monolith.

### Phase 3 — boundary foundation

- Conduct an official-source admission review for province/territory boundaries and the National Ecological Framework vector hierarchy.
- Prototype a compact `canada-boundaries-v1` SQLite/RTree package with published identifiers retained and geometry simplification only under explicit topology/area tolerance tests.
- Surface matched ecological labels as context and document the limitation of each scale.

**Exit gate:** the boundary profile can be independently installed and queried, shows coverage/version/source transparently, and does not increase advice specificity beyond the source's stated resolution.

### Phase 4 — Census of Agriculture context and SLC decision

- Inspect AESD documentation/data dictionary, confirm licence/release/version, and choose a small variable allowlist with agricultural interpretation and date labels.
- Test the published AESD geographic key against DSS `soil_landscape_id`; use only a verified lossless/versioned relationship.
- If the join is valid, build a small context-only SQLite table. If it is not, keep Census statistics at their published coarser geography rather than inventing a join.
- Separately inspect the SLC vector release for size, IDs, components, and right-to-package; admit it only if it improves coverage/routing beyond the DSS and boundary profiles.

**Exit gate:** Census/SLC data is visibly regional and dated, joins only on verified identifiers, and cannot become decisive management evidence or field truth.

### Phase 5 — source expansion and training-readiness review

- Execute the regional/university source gap matrix under the admission pipeline.
- Produce a source-coverage report by province, crop/topic, policy role, and geographic applicability.
- Maintain separate public, permission-pending, live-reference, and private-overlay queues.
- Only then open a separate fine-tuning data-design review, using an explicit training-rights ledger.

**Exit gate:** every shipped source is rights-bound and geographically labelled; no private/permission-pending item is present in the distributable corpus or training material.

## 8. Required tests and release gates

| Gate | Required evidence |
|---|---|
| Download safety | Registered URL only; temporary path; hash-before-promotion; idempotent matching rerun; explicit failure on changed bytes, bad hash, insufficient space, or partial download. |
| DSS derivation | Fixture builds for AB/SK/MB; source/archive checks; geometry and area tolerance; feature/component parity; SQLite/RTree integrity; raw-to-derived hash/lineage binding. |
| Spatial pack | Empty state directory -> install -> validate -> app-path query for three fixed Prairie fields; verified external pack-root precedence; clear `not_installed`/`out_of_coverage` results. |
| Offline behavior | Prepared runtime makes no external request for a spatial intersection; a missing selected pack fails clearly rather than falling back silently. |
| Curated store | Each listed shard exists, is below 24 MiB, has matching hash/rows/source IDs/policy role; no duplicate `doc_id` or content fingerprint; config order exactly matches store manifest. |
| Governance | Core and extended corpus profiles audit independently; context-only rows cannot become decisive solely through sharding or packaging. |
| Public release | All approved shards and store receipts are present; raw downloads, SQLite files, symlinks, local install receipts, caches, private overlays, and temporary data are absent. |
| Boundaries/Census | Published ID/version and licence tests; spatial join test; context-only enforcement; coverage/unknown state tests. |
| Documentation | A fresh-clone guide documents space requirements, explicit setup commands, environment variable, verification command, pack update/removal behavior, attributions, and limitations. |

`prepare_offline_runtime.py` should become a meaningful final verifier for both layers: it validates the clone's curated-store contract and, when selected, the external profile manifest. `build_portable_agent_bundle.py` should include profile/source contracts and verifier logic, never presume repo-resident spatial databases. A future user-facing guide belongs under `docs/public/operations/` and should be added to the documentation navigation when the commands actually exist; this design record should not masquerade as completed operational documentation.

## 9. Decisions that require review before implementation

1. Resolved: use a user-selected state directory outside the checkout; retain raw archives by default and require the explicit `--discard-raw-after-build` option after a successful verification to remove them.
2. Approve the exact official boundary source records and acceptable simplification/coverage tolerances before `canada-boundaries-v1` is acquired.
3. Review AESD user documentation and select a deliberately small Census variable set; approve the exact SLC/geographic identifier contract before a join is built.
4. Approve the curated core/extended shard profile and total Git budget after the first deterministic store build.
5. Make source-by-source legal decisions for university, provincial, and industry-extension material. Public accessibility is not a redistribution or training grant.
6. Decide, separately, whether an air-gapped handoff pack is a supported release artifact and what signature/transfer verification it requires.

## 10. Completion definition

This plan is complete when the implementation delivers a deterministic, independently verifiable path from a clean clone to:

- a Git-contained, hash/rights/policy-bound compact Canadian RAG core;
- an explicitly selected and externally stored `prairie-dss-v1` pack built from official source bytes;
- an offline runtime that accurately distinguishes installed mapped context, no coverage, and no installed profile; and
- release/documentation tests that prevent raw, private, oversized, unlicensed, or unverified artifacts from leaking into the repository.

It does not claim national spatial coverage, current field characterization, agronomist equivalence, permission to train, or readiness of deferred grids, boundaries, SLC, Census, or university-source content.

## 11. Execution log

### 2026-08-13 — implementation started

- Re-read this plan against the current checkout before changing any contract.
- Confirmed the focused baseline: `tests/test_geospatial_service.py`, `tests/test_corpus_governance.py`, and `tests/test_public_repository_builder.py` passed (14 tests).
- Began separate implementation tracks for the external Prairie DSS profile, the sharded curated Canadian store, and the boundary/Census/source-admission work.
- Did not download the large DSS archives or any deferred gridded product during this baseline. The installer and its fixture tests, not a one-off developer asset, are the required proof for a cloneable setup.

### 2026-08-13 — Phase 0 and Phase 1 contracts implemented

- Added `data/manifests/offline_spatial_profiles_v1.json` with exactly the pinned Alberta, Saskatchewan, and Manitoba DSS source records for `prairie-dss-v1`; erosion, national grids, boundaries, Census, and SLC remain explicitly deferred.
- Added the external-state `scripts/setup_offline_data.py` entry point. It has no implicit network path; its `--download` phase writes `.part` files, validates pinned bytes before promotion, writes source lineage, derives SQLite/RTree layers, assembles a profile-bound flat pack, and verifies fixed application-path probes.
- Updated profile-scoped source validation, pack assembly, runtime probing, offline readiness, and portable-bundle selection so a DSS-only external pack is not confused with absent legacy layers. The portable bundle now carries spatial source/profile contracts and installer logic, not developer-local SQLite databases.
- Resolved the raw-retention decision in favour of the safe default: retain raw archives unless an explicit verified `--discard-raw-after-build` operation is requested.
- Verified fixture-level state-root, source-pin, atomic-pack, profile-scoped validation, and readiness-validator paths. No live DSS download or full real-source re-derivation was performed; that remains a required operator-run activation gate.

### 2026-08-13 — Phase 2 compact Canadian store released

- Added deterministic curated-store build/validation tooling, a source-profile specification, a 24 MiB shard cap, source/rights/policy receipts, and generated explicit core/extended RAG configurations.
- Added `ingest_document_sources.py --output-mode source-shards` for future admitted-source intake. It emits canonical per-source JSONL and provenance/training-boundary receipts with an all-success index, refuses a combined corpus in that mode, and preserves the legacy combined mode only as an explicit compatibility path.
- Built `data/derived/rag/curated_canada/v1/` from the existing admitted Canadian rows: 952 unique rows in three policy-segregated shards (5,496,439 bytes). `canada-offline-core` contains 630 selected Alberta/Manitoba rows; `canada-offline-extended` adds 322 explicit federal/Saskatchewan/Ontario context rows.
- The builder records 100 rows excluded because their source IDs are not selected by the profile spec; it does not promote those rows or imply training permission. Every selected source retains `training: false`.
- The source-coverage receipt now records per-source publisher, declared crop/topic/jurisdiction metadata, policy role, geographic applicability, and profile membership plus clearly bounded aggregate gap counts. The current row-jurisdiction counts are Alberta 511, Manitoba 119, Saskatchewan 10, Ontario 234, and Canada 78; this is a coverage signal, not field-level authority.
- Made explicit `graph_paths: []` a supported runtime contract so these generated profiles do not inherit the legacy seed graph. The live loader, portable-bundle selector, profile manifest builder, and validator now agree on that declared scope.
- Updated Git ignore/public-release rules to include only the exact store files and to enforce a 24 MiB total budget for this release prefix as well as the 99 MB per-file ceiling.

### 2026-08-13 — Phases 3 through 5 admission boundary implemented

- Added a fail-closed, metadata-only candidate registry and public admission guide for eleven inspected boundaries, ecoregion, SLC, AESD/Census, agricultural-ecumene, and university/extension targets. Every candidate has runtime/RAG/bundle/download/training use disabled.
- Recorded official catalogue identities, applicable regional role, source/right review state, and the specific missing gates. Existing governed provincial-source records were referenced rather than re-declared with potentially conflicting policy.
- Completed the separate fine-tuning data-design review. It observes zero currently training-eligible Canadian sources and creates no dataset, rows, adapter, or model artifact; its future ledger, split, provenance, revocation, and human-review gates remain a separate approval path.
- No boundary, Census, SLC, or university-source bytes were downloaded or packaged. Their profile prototypes and any join are blocked pending source-specific byte, rights, identifier, schema, compactness, and field-boundary review.

### 2026-08-13 — integration and documentation completed

- Added profile-aware runtime-manifest construction and readiness verification for the generated compact RAG configuration plus an optional external DSS pack.
- Added the public compact offline setup guide, updated offline/native/knowledge governance documentation, and added the guide to documentation navigation.
- Focused validation is recorded in the implementation handoff; it proves contracts and fixtures, not a live 459 MB DSS source download, national coverage, or source admission beyond the existing reviewed Canadian corpus.

### 2026-08-13 — final contract verification

- Re-ran the curated-store validator: 952 rows, three shards, both explicit profiles, and 5,496,439 shard bytes passed hash/policy/store validation.
- Re-ran the RAG-only readiness path with `canada-offline-core`: the generated runtime manifest and local model snapshot passed all five checks with zero network requests; the receipt correctly records the optional map pack as `not_installed`.
- Re-ran the DSS installer in `--dry-run` mode against an empty external state path: it planned only the pinned AB/SK/MB archives, required 1.5 GB free space, created no files, and made no actual network request.
- Re-ran `ingest_document_sources.py --output-mode source-shards --dry-run` for an admitted Manitoba source: it planned one source shard and receipt, created no files, and explicitly reported `combined_corpus_created: false`.
- The compact/offline focused suite passed 39 tests, including source-shard intake, curated-store, spatial-profile, source-admission, corpus-governance, public-documentation, public-release, and geospatial-service contracts. A fresh manifest-selected public build passed with 656 files and 153,977,465 bytes.
- The broader suite passed 617 tests but has six unrelated existing failures in the Benchmark V2 audit because its frozen artifact-hash manifest does not match concurrent benchmark files in this in-development checkout. Those benchmark artifacts were neither refreshed nor altered by this compact-data implementation; preserving the mismatch is safer than silently rebinding evaluation evidence.

### 2026-08-13 — live Prairie DSS installation exercised

- Ran the real, lock-protected `prairie-dss-v1` installer against a separate user-selected state directory. It retained the pinned official Alberta, Saskatchewan, and Manitoba DSS archives; rebuilt the three SQLite/RTree layers; and assembled a hash-bound `480,382,976`-byte runtime pack outside the repository.
- An independent pack verifier passed all layer, manifest, and application-path checks: Alberta has 28,366 features and two probe intersections, Saskatchewan 67,166 and one, and Manitoba 168,371 and five. The probes establish package/application-path behavior only; they do not establish current field properties, a soil test, or a management recommendation.
- An early accidental concurrent invocation exposed an empty/mismatched Manitoba derived SQLite output. The inconsistent derived pair was quarantined without deleting source raw archives. The installer now holds an exclusive state-root lock across every real phase; subsequent focused lock/profile/geospatial checks passed, followed by a clean single-writer rebuild and verification.
- `prepare_offline_runtime.py` then reported `ready` for the generated compact RAG profile plus the installed DSS pack: all five checks passed and it performed zero network requests. A fresh empty-root one-shot download/build/verify under the new lock remains the strongest remaining operational replication of the Phase 1 exit gate.

### 2026-08-13 — first verified new-source intake and candidate-store rebuild

- Re-read the admission pipeline and the geographic-routing limits before accepting a new document. Two Alberta PDFs were reviewed but not activated: a nominally 2026 portal item was a 2016 irrigation guide, and a current Bow River phosphorus guide could not be safely scoped to a runtime-enforceable plan boundary. Both remain external-intake evidence rather than corpus rows.
- Selected the Manitoba 2026 Plant Disease Control guide for a narrower path because its province-wide applicability is enforceable by the current retrieval boundary. The staged 145-page PDF was hash-pinned; only pages 1–3 were visually/textually reviewed; raw document chunks were disabled. Four manually authored semantic-only records retain qualitative scouting, diagnostic-confirmation, weather-risk, and biosecurity context while excluding product, label, rate, threshold, legal, and procedural content.
- Added `expected_raw_sha256` support to governed document intake. It validates staged/downloaded bytes before promotion, carries the pin into lineage and receipts, and refuses raw-byte drift even when a source shard already exists.
- Ran real `source-shards` ingestion from the verified Manitoba raw file: it produced four `context_only` rows, a hash-bound source receipt, and a complete source-shard index. A deterministic `curated-canada-v2` rebuild then produced 956 rows in three policy-segregated shards (5,521,926 bytes); the existing v1 store was not edited in place.
- The generated `canada-offline-extended` v2 profile passed store validation, edge-runtime-manifest generation, and all five offline-readiness checks with the verified Prairie DSS pack and zero network requests. A cache-free application-path retrieval admitted the Manitoba clubroot context only for a Manitoba field and rejected an Alberta control at `jurisdiction_mismatch`; no prohibited product/rate/unit terms appeared in the four records.
- The v2 profile is deliberately a candidate rather than a silent default-runtime change. The legacy supplemental Manitoba disease rows remain a separate remediation/promotion decision; because the revised companion reuses their document IDs, promotion must switch profiles and exclude the old supplemental corpus rather than append a fourth path. The signed knowledge-update flow also needs an artifact-root-aware generated-profile check. New sources continue to require their own rights, content, currency, and geographic-scope gates.

### 2026-08-13 — second verified source intake and portable candidate packaging

- Continued the source queue only with province-enforceable, rights-cleared candidates. The Alberta water- and wind-erosion guides were retained as historical external evidence rather than admitted because their 2019/2017 PDFs mix obsolete/current-sensitive operations, products, numeric/engineering content, legal framing, photos, and official marks. A current Saskatchewan soil-health article was not downloaded for the distributable store because its published rights require written commercial-reuse permission.
- Reviewed and hash-pinned Manitoba's two-page 2023 Crop Rotation Planning note. Its MASC tables, aggregate numbers, image, and branding were excluded; four manually authored records retain only prior-crop/stubble field history, possible disease-carryover investigation, water/residue establishment context, and the boundary against treating aggregate history as a field prediction or crop-sequence prescription.
- Ran real source-shard ingestion from the official rotation PDF; the exact raw hash passed and the output contained four `context_only`, historical-current-validation rows. Rebuilt a fresh `curated-canada-v3` extended candidate with both Manitoba semantic-only sources: 960 rows, three policy-segregated shards, and 5,543,475 bytes. Earlier v1/v2 artifacts remain immutable.
- Store validation, source-manifest validation, cache-free Manitoba-positive/Alberta-negative retrieval controls, edge-runtime-manifest generation, and all five offline-readiness checks passed. The locally installed Prairie DSS pack remained valid during the v3 readiness run, with zero network requests.
- Made the signed knowledge-update builder artifact-root aware, then built/extracted/validated an unsigned v3 local package. Its three configured corpus shards resolve beneath the packaged nested `curated_canada/v3` artifact root. This proves portability mechanics only; it is not a signed or default-runtime release.

### 2026-08-14 — compact boundaries, Census context, and successor-source review

- Performed another rights/content/geography review. One Alberta-wide Government of Alberta OGL source, the 2017 tame-pasture range-health worksheet, passed only as four manually reviewed historical `context_only` companion records. The raw worksheet remains excluded because it mixes scoring, named plants, legal content, images, and management direction. A deterministic `curated-canada-v4` extended successor was built with 964 rows in three shards (5,567,808 bytes); v3 remains immutable and the new source is not a default profile.
- Rejected a 2003 Manitoba saline-forage document as old/redundant and kept high-value Saskatchewan extension material out of the distributable store because the reviewed reuse terms require commercial permission. No university or rights-unclear source was silently promoted.
- Installed and independently verified the opt-in `canada-context-boundaries-v1` profile from compact official inputs: Statistics Canada 2021 provinces/territories, Statistics Canada 2021 Census Agricultural Regions, and AAFC terrestrial ecoregions v2.2. The hash-bound external runtime pack is 9,039,872 bytes and its offline probe returned the expected Alberta/Manitoba/Ontario province, CAR, and ecoregion hierarchy. It supplies geographic organization only, not a field boundary or agronomic conclusion.
- Built a separate external-only Statistics Canada 2021 tillage/seeding snapshot keyed by exact published 2021 DGUIDs. All 10 source provinces and 69 source CARs match the installed boundary IDs exactly; it preserves every published status and blank value. It remains excluded from RAG, generic model context, training, and recommendation paths pending an explicit aggregate-context composer.
- Inspected SLC v3.2 and AESD 2021 with exact source/resource pins. The DSS-to-SLC string join is promising but AESD coverage is incomplete (especially Manitoba) and its many aggregate values have variable/province-specific lineage. Raw AESD and its values remain blocked from model/RAG use. A future SLC/AESD availability-only index requires a distinct profile and versioned join gate.
- Added a server-authorized trusted-geographic-context adapter. It presents only the three installed boundary layer identifiers/names/hierarchy to the model once, labels them `CONTEXT ONLY`, and explicitly states that they do not alter retrieval eligibility. The server rejects client-only snapshots and forged JSON projections; no CAR/ecoregion document routing has been enabled.
- Focused source, spatial, store, and prompt-path validation passed (62 tests); source registry validation, v4 store validation, and installed-boundary offline verification also passed. These checks establish package/provenance behavior, not field truth, current regional advice, training authorization, or national data completeness.
