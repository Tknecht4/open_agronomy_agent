# Knowledge and data governance

The runtime knowledge base is selected by `data/manifests/runtime_corpus_policy.json` and loaded by `configs/rag_governed_runtime_v1.yaml`. Presence on disk is not admission.

## Admitted release knowledge

| Artifact | Rows | Runtime role | Boundary |
|---|---:|---|---|
| Canadian distributable v13 | 718 | 706 context-only; 12 require live authority | No row is currently admitted as standard applied authority; uneven provincial depth; Ontario Publication 811/811F excluded |
| Ontario context v1 | 234 | Context only | Regional statistics, not field truth or calibration |
| Canadian supplements v1/v2/v3 | 62 | Context only | Historical/regional, data-product, and six current Manitoba scouting companion records; the scouting rows remain non-decisive pending independent agronomic review |
| Canadian regional context v1 | 38 | Context only | Data-product descriptions, not local applied guidance |
| SoilWise RAG + KG | 1,784 RAG rows | Context only | Soil-health concepts and relations, not a soil test |
| Compact NRCS ESD | 32,624 | Context only | Section-balanced projection of all 8,300 recovered USDA EDIT sites; explicit US analogue use only, never Canadian field truth or authority |
| Project seed/boundary corpora | 42 | Context and safety policy | Project-authored synthesis, not independent evidence |

### Prairie applied-guidance coverage

The main 718-row Canadian corpus is not provincially balanced. Its row-level jurisdiction counts are:

| Jurisdiction | Rows | Practical interpretation |
|---|---:|---|
| Alberta | 511 | Strongest Prairie depth, but most historical publications remain context-only and require current local calibration for rates or thresholds |
| Manitoba | 119 | Useful soil-fertility coverage, still bounded by date, method and current-authority checks |
| Canada/federal | 78 | Cross-provincial context and federal material; not a substitute for provincial recommendations |
| Saskatchewan | 10 | Detailed-soil-survey specification context, not sufficient province-specific applied crop guidance |

SoilWise adds useful soil-process concepts across all three provinces, but it does not repair the Saskatchewan applied-guidance gap and must not be presented as if it does. The conference interface therefore treats Saskatchewan mapping as a regional prior and asks for current Saskatchewan guidance before locally calibrated decisions.

Every admitted Canadian row carries source and lineage fields. The policy manifest also records a byte hash, evidence tier, rights status, admission reason, and runtime role for every configured corpus.

The maintainer-only retention audit verifies the governed rows against their exact raw-source byte hashes before any historical corpus can be considered redundant. It also compares the compact NRCS projection with the retained full corpus by site, exact source text, and section facet. Its path-sanitized evidence is committed as `data/manifests/source_retention_receipt.json`. Passing that audit is necessary but not sufficient for deletion: deletion requires a separate path- and hash-specific approval manifest.

## Why processed material can be absent from runtime

Processing proves that bytes can be extracted; it does not prove that they should influence an answer or be redistributed. The following remain excluded before index construction:

- forum posts without redistribution permission or verified authorship;
- OCR/document expansions whose item-level licence snapshot or lineage is incomplete;
- copied certification competency objectives;
- answer-gap and benchmark-shaped synthesis that could leak evaluation targets;
- candidate corpus versions superseded by the rights-repaired v13 release.

Ontario Publication 811 is the material exception inside the historical Canadian builds: its extracted rows remain quarantined while the original source bytes and rights-review record are preserved. Those historical files must not be removed until that separate receipt is bound into an explicitly approved archive or deletion plan.

The exclusion is intentional and auditable. Quarantined byte files are not required in a portable release even when their identifiers remain in the policy.

## Exam and benchmark questions

Evaluation data is not agronomic knowledge. `cca_aligned_eval.jsonl` and `cca_local_style_eval.jsonl` contain 28 project-authored questions based on topic coverage; they are neither copied certification questions nor evidence sources. The frozen 241-case internal suite and held-out AgroQA diagnostic are kept in a separate evaluation partition and never configured as RAG corpora.

## Geospatial data

Regional soil and crop layers are useful for locating priors, not for replacing soil sampling or grower records. Large generated SQLite indexes and raw downloads are excluded from Git. The portable Prairie pack consolidates Alberta, Saskatchewan, and Manitoba Detailed Soil Survey SQLite/RTree layers with the national 2021 soil-erosion-risk layer. Its pack manifest binds every database and derivation manifest by hash; a runtime probe checks installed-layer discovery and fixed offline field intersections in all three provinces.

The Saskatchewan DSS integration preserves all 67,166 source map polygons and their component tables. Source geometries are repaired before simplification, simplification occurs in EPSG:3347 metres rather than geographic degrees, and the build fails if aggregate area changes by more than 0.01%. The layer remains a historical 1:100,000 mapped prior. It cannot establish a point soil, current nutrient supply, salinity, compaction, drainage performance, crop suitability, or a rate.

The 2025 national 100 m Soil Landscape Grids of Canada are tracked as a candidate, not an installed authority layer. The federal record describes the product as under evaluation and review. Promotion therefore requires cropland tiling/size measurements, uncertainty handling, province-edge and northern-coverage tests, and a demonstrated retrieval or decision-quality benefit over the survey layers.

## Admission checklist

A source is eligible only after confirming item-level reuse rights, exact source URL, publisher, retrieval date, byte hash, language, jurisdiction, currency/review date, extraction lineage, evidence role, field-action boundary, and a reproducible build. High-consequence regulatory or label content should ordinarily require live authority even if a local copy exists.
