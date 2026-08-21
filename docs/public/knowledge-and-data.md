# Knowledge and data governance

The runtime knowledge base is selected by an explicit policy manifest and an operator-selected RAG configuration. Presence on disk is not admission.

## Active clone-contained offline corpus

`configs/rag.yaml` selects the stable `offline-agronomy` profile. Its direct
startup store at `data/derived/rag/offline_agronomy/active/` contains 3,086
source-exact rows: Canadian raw-page and table evidence, project policy, and
SoilWise context. Every record has a raw/source-record hash, locator,
jurisdiction, rights, policy, and quality-ledger fields. It is a deterministic
derived release, not an archive of raw documents or a training dataset.

The active store manifest, source receipt, duplicate-cluster receipt, and
quality ledger are required evidence. A row that cannot be rebuilt with a
source-exact locator is excluded from this active profile rather than admitted
under a historical exception.

The former `curated_canada/v1` through `v4` development payloads are not
active runtime inputs. Frozen receipt material and Git history preserve their
milestones. `configs/rag_governed_runtime_v1.yaml` and
`configs/rag_final_mvp.yaml` remain only as frozen RC1/RC2 identity inputs; they
are not selectable and may reference historical payloads intentionally absent
from a current public checkout.

## Active governed runtime composition

`configs/rag.yaml` composes five direct, explicitly hash-admitted corpus shards
and two governed graphs totaling 1,794 nodes and 1,458 edges.
`configs/runtime_profiles.json` is the product-selection registry; adding a
YAML file does not activate it.

| Artifact | Rows | Runtime role | Boundary |
|---|---:|---|---|
| Canadian source-exact evidence | 1,261 | 863 context-only; 398 require live authority | Canadian evidence remains bounded by source date and current-authority controls |
| SoilWise + KG | 1,783 RAG rows; 1,784 graph nodes | Context only | Soil-health concepts and relations, not a soil test |
| U.S. NRCS ESD full pack | 218,258 | Explicit U.S./NRCS/MLRA requests only | Source-exact U.S. analogue context; never Canadian decisive authority |
| Project policy | 42 | 36 context-only; 6 decisive project safety rows | Project-authored synthesis/policy, not independent agronomic evidence |
| Project and SoilWise graphs | 1,794 nodes; 1,458 edges | Relationship context | A graph route is not a measurement, diagnosis, or source-authority promotion |

The master source-coverage receipt records source-declared crop, topic, and
jurisdiction applicability. This is routing metadata, not proof of a field
condition. Five bounded Manitoba canola-insect semantic rows are admitted after
source-specific OpenMB review; product tables and third-party material remain
excluded. Discovery or a file on disk does not make content model-visible.

The NASS QuickStats snapshot is not a RAG corpus. It is a typed, dated static
tool snapshot with its own manifest and freshness boundary. It must not be
described as live data or as Canadian evidence.

## U.S. analogue pack and retrieval baseline

The active profile preserves Canadian evidence as the highest-priority
authority and includes 218,258 hash-bound historical USDA NRCS records in 51
deterministic JSONL shards (each capped at 16 MiB). The full U.S. pack is
**not** loaded into ordinary Canadian startup retrieval: it is verified and
opened on demand only for an explicit U.S./NRCS request that names an MLRA
identifier. This keeps bounded shard loading available without crowding Canadian
evidence or silently changing Canadian authority.

The U.S. release carries a deterministic exact-token BM25 statistics index.
The index stores document lengths and per-shard document frequencies, not a
second copy of source text; policy selects the relevant shard before source
JSONL is opened.

Every successor U.S. row has a raw-source hash, portable archive path, source
URL, extraction recipe, chunk index, exact text hash, duplicate disposition,
jurisdiction, rights status, and `context_only` policy. For Canadian questions,
it is labelled U.S. analogue context and cannot establish a Canadian label,
law, rate, threshold, calibration, or field condition. Raw archive and spatial
bytes remain separate hash-bound optional packs.

The fixed retrieval baseline is evaluated by a source-grounded suite before any
hybrid, dense, or reranking profile can be promoted. The repository records its
protocol in `configs/offline_corpus_retrieval_preregistration.json`, its result
in `data/manifests/offline_corpus_retrieval_evaluation.json`, and its
primary-source methods review in
`docs/reviews/offline-corpus-retrieval-methods-20260819.md`.

The measured baseline is locator- and authority-compliant, but it is not a
claim that a more complex retriever improves performance. Promotion requires a
frozen held-out comparison and zero authority, jurisdiction, privacy, duplicate,
or source-locator violations.

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

Every admitted runtime row carries source and lineage fields. The active policy
records the byte hash, evidence tier, rights status, admission reason, and
runtime role for every configured corpus.

The historical maintainer-only retention receipt remains evidence for the
former compact-NRCS profile; it is not a gate for this active profile. The
current gate is the active-store source receipt plus the successor quality audit,
which bind every runtime row to source-exact locator, rights, jurisdiction,
policy, and quality fields. Passing either receipt is necessary but never
sufficient for deletion: deletion requires a separate path- and hash-specific
approval manifest.

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
