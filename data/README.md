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

## Cumulative Canadian master store

The active clone-contained document corpus has one cumulative release:
`data/derived/rag/curated_canada/releases/2026-08-14/`. Its sole profile,
`canada-offline-master`, contains 969 source-bound rows from 20 admitted sources
in two policy-segregated shards: 955 `context_only` rows and 14
`requires_live_authority` rows. The store manifest, profile, source-coverage
receipt, ingest receipt, and shard hashes form one immutable release unit.

The release is built from source-aware inputs under
`data/derived/rag/curated_canada/inputs/2026-08-14/` plus reviewed semantic
companions under `data/curated/canada_agronomy/`. Companion filenames are
review-date versioned; the companion README and recovery receipt distinguish
reconstructed reviewed content from recovery of an original byte stream.
Source registry records bind upstream raw hashes, rights, jurisdiction, and use
limits. The raw PDFs themselves remain maintainer/operator evidence and are not
required in the public runtime package.

The former `curated_canada/v1` through `v4` development stores are no longer
current payload directories. Their milestones survive in compact profile
manifests, review records, and Git history rather than as competing runtime
copies. Frozen evidence never activates a profile.
The Manitoba canola-insect companion is admitted only as five bounded semantic
rows after source-specific OpenMB review; product tables and third-party
material remain excluded. Discovery alone never makes content model-visible.

To add documents, append or version the source registry and semantic companion,
produce source-aware input shards, then build a new immutable dated release.
Advance `configs/rag_governed_runtime_v2.yaml` and
`configs/runtime_profiles.json` only after store validation, corpus-policy
generation, licensing checks, and tests pass. Never edit an existing release
shard or receipt in place.

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
PYTHONPATH=src .venv/bin/python scripts/audit_source_retention.py
PYTHONPATH=src .venv/bin/python scripts/validate_curated_knowledge_store.py \
  --store-root data/derived/rag/curated_canada/releases/2026-08-14 \
  --expect-profile canada-offline-master
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_corpus_governance.py
```

Some audits require maintainer-only raw bytes and will report unavailable in a curated public checkout. That is not the same as pass or fail.

## Failure modes

Missing rights, missing hashes, unresolved jurisdiction, stale authority, evaluation leakage, row-count drift, malformed geometry, absent optional packs, and policy exclusion must remain explicit. Unknown is not approval.
