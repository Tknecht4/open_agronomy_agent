# Governance manifests

## Purpose and status

`data/manifests/` is the repository's governance index for source identity, rights, runtime admission, evaluation separation, geospatial lineage, and retention evidence. Manifests describe evidence and policy; they do not by themselves prove live provider availability, field validity, or human approval.

## Main contracts

- `runtime_corpus_policy_v2.json` is the active product policy deciding which configured corpus rows/artifacts may enter runtime retrieval; the unversioned policy is historical.
- `curated_canada_offline_master_v1.json` specifies the cumulative dated Canadian release and sole `canada-offline-master` profile.
- `source_licensing_matrix.json` and source-specific manifests preserve rights and redistribution state.
- `rag_sources.json` and Canadian supplement/source manifests preserve retrieval lineage.
- `canada_geospatial_sources.json` preserves source/derivation boundaries for map layers.
- `eval_benchmark_sources.json` records evaluation-source identity and separation.
- `source_retention_receipt.json` is path-sanitized evidence that distinguishes current release/hash validation from carried-forward raw-source observations; it is not standing deletion authority.

## Required source fields

Use the schema appropriate to the manifest, but preserve at least stable source/item ID, publisher, canonical URL, retrieval date, jurisdiction, language, rights/licence status, byte/content hash, derivation lineage, currency/review date, runtime/evidence role, limitations, and status. Unknown values must be represented as unknown/pending—not omitted as if satisfied.

## Invariants

- Source facts and project decisions are separate fields.
- Licence or admission changes create reviewable versioned records.
- Evaluation material cannot be admitted to runtime retrieval.
- Context-only evidence cannot be promoted to decisive guidance by a loader.
- Hashes identify exact bytes; URLs and titles alone are insufficient.
- No manifest stores secrets or private absolute paths.

## Extend a manifest

1. Use or version a schema; do not change the meaning of an existing status in place.
2. Add the record with exact provenance and explicit unknowns.
3. Run the owning audit and corpus/release tests.
4. Update runtime policy only as a separate, reviewable admission decision.
5. Rebuild derived indexes; do not edit them to force a gate.

## Validation

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_canada_agronomy_sources.py
PYTHONPATH=src .venv/bin/python scripts/audit_runtime_corpus.py
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_corpus_governance.py
```

## Failure modes

Fail or quarantine on missing rights, hash drift, contradictory status, unknown schema, stale decisive authority, evaluation overlap, or untraceable derivation. A retained historical receipt may be useful evidence without being current proof; preserve its date and activation boundary.
