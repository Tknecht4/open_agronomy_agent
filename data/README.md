# Data layout and authority

## Purpose and status

`data/` separates small source material, governed derivatives, manifests, snapshots, evaluation sets, and ignored raw/private artifacts. Location conveys workflow role; manifests and runtime policy convey authority. A file being committed or locally present does not make it admissible evidence.

## Layout

| Directory | Role | Runtime authority |
|---|---|---|
| `seed/` | Small project-authored corpora/graphs and boundaries | Only when admitted by active policy/config |
| `derived/rag/` | Reproducible retrieval and graph derivatives | Only policy-admitted rows/artifacts |
| `derived/geo_layers/` | Checked-in derivation manifests; large indexes ignored | Optional mapped priors when separately installed and verified |
| `snapshots/` | Governed static provider snapshots | Dated context, never silently current |
| `manifests/` | Source, rights, retention, policy, and evaluation lineage | Governance records; see `manifests/README.md` |
| `eval/` | Internal and explicitly separated external evaluation material | Never runtime retrieval or training evidence |
| `raw/` | Ignored source bytes with narrow lineage exceptions | Not automatically redistributable or admissible |

## Active offline corpus

The active clone-contained document corpus is
`data/derived/rag/offline_agronomy/active/`. It contains 3,086 source-exact
rows in policy-segregated shards. Its store manifest, source receipt,
duplicate-cluster receipt, quality ledger, and shard hashes form one immutable
release unit.

Canadian PDF records are reconstructed from raw page text with exact spans;
Ontario workbook records retain structured table coordinates. Seed, boundary,
and SoilWise records preserve exact source-record locators. Source receipts bind
raw/source-record hashes, rights, jurisdiction, extraction methods, and use
limits.

The former `curated_canada/v1` through `v4` development stores are no longer
current payload directories. Their milestones survive in compact profile
manifests, review records, and Git history rather than as competing runtime
copies. Frozen evidence never activates a profile.
The Manitoba canola-insect companion is admitted only as five bounded semantic
rows after source-specific OpenMB review; product tables and third-party
material remain excluded. Discovery alone never makes content model-visible.

The full `offline_agronomy/us_nrcs/` pack contains 218,258 U.S. NRCS records in
51 bounded JSONL shards plus persisted exact-token BM25 statistics. It is loaded
only for an explicit MLRA-scoped U.S. analogue request and cannot establish
Canadian decisive authority. Community and spatial archive candidates remain
outside runtime until source-specific review.

To add documents, update the source receipt and extraction adapter, rebuild the
stable active store, then advance `configs/rag.yaml` and
`configs/runtime_profiles.json` only after validation, policy generation,
licensing checks, and tests pass.

## Inputs and outputs

Ingestion begins with source bytes plus publisher, URL, retrieval time, rights, jurisdiction, and checksum. It produces content-addressed derivatives and manifests. Runtime loaders then apply corpus policy before indexing. Evaluation builders consume their own partition and produce ignored run artifacts plus deliberately curated public summaries.

The checked-in Benchmark v2 suite is project-authored and has been exposed and
used for deterministic behavior tuning. It is now an internal development
regression suite, not an untouched evaluation. Its exposure amendment records
that lineage; a freshly authored untouched v3 is required for future
evaluation. V2 has no model-backed outcome evidence, independent agronomist
approval, or real-user validation lane.

## Invariants

- Preserve source identity and exact-byte lineage.
- Separate observation, derivative/model output, and interpretation.
- Record rights per item; processing success does not grant redistribution or runtime admission.
- Never train on or retrieve from held-out evaluation answers.
- Maps/statistics are regional priors, not measurements at a field.
- Private overlays, farmer records, raw answers, and generated indexes remain outside public Git/site scope.
- Deletion requires explicit path/hash authority; a derived copy does not automatically authorize source deletion.

## Add a source or derivative

1. Record the source, retrieval time, rights, jurisdiction, currency, and byte hash.
2. Use an existing ingestion/build script or add a deterministic one.
3. Emit row/artifact lineage and validate counts/hashes.
4. Assign evidence role and limitations in the relevant manifest.
5. Explicitly admit or quarantine it in runtime policy.
6. Add corpus, rights, retrieval, and leakage tests.

Do not edit generated/public derivatives by hand when a source registry or build script owns them.

## Validation

```bash
PYTHONPATH=src .venv/bin/python scripts/audit_runtime_corpus.py
PYTHONPATH=src .venv/bin/python scripts/audit_offline_corpus_successor_quality.py --fail-on-gap
PYTHONPATH=src .venv/bin/python scripts/evaluate_offline_corpus_retrieval.py
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_corpus_governance.py
```

`audit_source_retention.py` remains a historical compact-NRCS retention tool;
run it only against its named legacy profile and mounted maintainer archive.
Some archival audits require maintainer-only raw bytes and will report
unavailable in a curated public checkout. That is not the same as pass or fail.

## Failure modes

Missing rights, missing hashes, unresolved jurisdiction, stale authority, evaluation leakage, row-count drift, malformed geometry, absent optional packs, and policy exclusion must remain explicit. Unknown is not approval.
