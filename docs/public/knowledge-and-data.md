# Knowledge and data governance

The runtime knowledge base is selected by an explicit policy manifest and an operator-selected RAG configuration. Presence on disk is not admission.

## Cumulative clone-contained Canadian master

The active Canadian document release is
`data/derived/rag/curated_canada/releases/2026-08-14/`. Its sole profile,
`canada-offline-master`, contains 969 rows from 20 admitted sources in two
SHA-bound shards: 955 `context_only` rows and 14
`requires_live_authority` rows. It replaces the former core/extended operator
choice with one cumulative public corpus. The store is a deterministic derived
release, not an archive of the raw documents and not a training dataset.

The profile, store manifest, source-coverage receipt, ingest receipt, source
registry, dated source-aware inputs, and reviewed semantic companions preserve
the release lineage. Semantic companions are versioned by review date. A
recovery receipt identifies companions reconstructed from hash-bound derived
rows and does not claim recovery of missing original byte streams.

The former `curated_canada/v1` through `v4` development payloads are removed
from the current tree/package; compact manifests, review records, and Git
history preserve their milestones. `configs/rag_governed_runtime_v1.yaml` and
`configs/rag_final_mvp.yaml` remain only as frozen RC1/RC2 identity inputs; they
are not selectable and may reference historical payloads intentionally absent
from a current public checkout.

## Active governed runtime composition

`configs/rag_governed_runtime_v2.yaml` composes six explicitly hash-admitted
corpora totaling 35,419 rows and two governed graphs totaling 1,794 nodes and
1,458 edges. `configs/runtime_profiles.json` is the product-selection registry;
adding a YAML file does not activate it.

| Artifact | Rows | Runtime role | Boundary |
|---|---:|---|---|
| Canadian offline master | 969 | 955 context-only; 14 require live authority | Uneven Canadian coverage; no row becomes current field truth by retrieval |
| SoilWise RAG + KG | 1,784 RAG rows; 1,784 graph nodes | Context only | Soil-health concepts and relations, not a soil test |
| NRCS ESD compact v2 | 32,624 | Context only | Sanitized projection of 8,300 USDA EDIT sites; explicit US analogue only |
| Project seed and boundary corpora | 42 | 36 context-only; 6 decisive project safety rows | Project-authored synthesis/policy, not independent agronomic evidence |
| Project and SoilWise graphs | 1,794 nodes; 1,458 edges | Relationship context | A graph route is not a measurement, diagnosis, or source-authority promotion |

The master source-coverage receipt records source-declared crop, topic, and
jurisdiction applicability. This is routing metadata, not proof of a field
condition. Five bounded Manitoba canola-insect semantic rows are admitted after
source-specific OpenMB review; product tables and third-party material remain
excluded. Discovery or a file on disk does not make content model-visible.

The NASS QuickStats snapshot is not a RAG corpus. It is a typed, dated static
tool snapshot with its own manifest and freshness boundary. It must not be
described as live data or as Canadian evidence.

See [offline data setup](operations/offline-data-setup.md) for validation and
external-map preparation.

### Prairie applied-guidance coverage

The Canadian master is not provincially balanced. Its largest historical
applied-guidance component has the following row-level jurisdiction counts:

| Jurisdiction | Rows | Practical interpretation |
|---|---:|---|
| Alberta | 511 | Strongest Prairie depth, but most historical publications remain context-only and require current local calibration for rates or thresholds |
| Manitoba | 119 | Useful soil-fertility coverage, still bounded by date, method and current-authority checks |
| Canada/federal | 78 | Cross-provincial context and federal material; not a substitute for provincial recommendations |
| Saskatchewan | 10 | Detailed-soil-survey specification context, not sufficient province-specific applied crop guidance |

SoilWise adds useful soil-process concepts across all three provinces, but it does not repair the Saskatchewan applied-guidance gap and must not be presented as if it does. The conference interface therefore treats Saskatchewan mapping as a regional prior and asks for current Saskatchewan guidance before locally calibrated decisions.

Every admitted Canadian row carries source and lineage fields. The runtime v2
policy records the byte hash, evidence tier, rights status, admission reason,
and runtime role for every configured corpus.

The maintainer-only retention audit can reverify governed rows against exact
raw-source bytes when the source archive is mounted. The portable receipt
records which observations are current hash/store validation and which raw-byte
checks were carried forward from an earlier observed audit or source-intake
receipt. It also binds NRCS compact v2 to the prior full/reference projection.
Passing a receipt is necessary but never sufficient for deletion: deletion
requires a separate path- and hash-specific approval manifest.

## Why processed material can be absent from runtime

Processing proves that bytes can be extracted; it does not prove that they should influence an answer or be redistributed. The following remain excluded before index construction:

- forum posts without redistribution permission or verified authorship;
- OCR/document expansions whose item-level licence snapshot or lineage is incomplete;
- copied certification competency objectives;
- answer-gap and benchmark-shaped synthesis that could leak evaluation targets;
- discovered or historical source material not admitted by the active master policy.

Ontario Publication 811 is the material exception inside the historical Canadian builds: its extracted rows remain quarantined while the original source bytes and rights-review record are preserved. Those historical files must not be removed until that separate receipt is bound into an explicitly approved archive or deletion plan.

The exclusion is intentional and auditable. Quarantined byte files are not required in a portable release even when their identifiers remain in the policy.

## Exam and benchmark questions

Evaluation data is not agronomic knowledge. `cca_aligned_eval.jsonl` and `cca_local_style_eval.jsonl` contain 28 project-authored questions based on topic coverage; they are neither copied certification questions nor evidence sources. The frozen 241-case internal suite and held-out AgroQA diagnostic are kept in a separate evaluation partition and never configured as RAG corpora.

## Geospatial data

Regional soil and crop layers are useful for locating priors, not for replacing soil sampling or grower records. Large generated SQLite indexes and raw downloads are excluded from Git. The `prairie-dss-v1` external pack consolidates only Alberta, Saskatchewan, and Manitoba Detailed Soil Survey SQLite/RTree layers. Its pack and install receipts bind every database and derivation manifest by hash; a runtime probe checks installed-layer discovery and fixed offline field intersections in all three provinces. It is installed post-clone, never inferred from repository files.

The Saskatchewan DSS integration preserves all 67,166 source map polygons and their component tables. Source geometries are repaired before simplification, simplification occurs in EPSG:3347 metres rather than geographic degrees, and the build fails if aggregate area changes by more than 0.01%. The layer remains a historical 1:100,000 mapped prior. It cannot establish a point soil, current nutrient supply, salinity, compaction, drainage performance, crop suitability, or a rate.

The 2025 national 100 m Soil Landscape Grids of Canada are tracked as a candidate, not an installed authority layer. The federal record describes the product as under evaluation and review. Promotion therefore requires cropland tiling/size measurements, uncertainty handling, province-edge and northern-coverage tests, and a demonstrated retrieval or decision-quality benefit over the survey layers. Boundary, ecoregion, SLC, AESD/Census, and university-extension candidates are separately fail-closed in the source-admission queue until source bytes, rights, identifiers, and compactness tests are reviewed.

## Admission checklist

A source is eligible only after confirming item-level reuse rights, exact source URL, publisher, retrieval date, byte hash, language, jurisdiction, currency/review date, extraction lineage, evidence role, field-action boundary, and a reproducible build. High-consequence regulatory or label content should ordinarily require live authority even if a local copy exists.
