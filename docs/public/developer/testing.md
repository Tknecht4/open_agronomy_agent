# Testing and claims

## Test layers

1. **Unit:** schema, arithmetic, parser, matcher, and pure policy behavior.
2. **Contract:** registry parity, corpus/graph manifests, evidence IDs, auth/network, serialization.
3. **Integration:** natural-language question through planner/tool/retrieval, validation, trace, and persistence.
4. **UI/API:** independent health/API and browser workflow checks.
5. **Benchmark:** preregistered frozen cases and causal arms with full artifacts.
6. **Field/professional study:** separately governed evidence for usability, decisions, or outcomes.

Passing a lower layer does not imply a higher layer.

## Standard gates

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/check_public_docs.py

cd frontend
npm run typecheck
npm test
npm run build
```

Build the documentation site with `mkdocs build --strict` after installing `requirements-docs.txt`.

## Reporting

Record the exact command, checkout identity, test count, failures/skips, optional assets, and whether the check was offline, fixture-backed, or live. Use “focused tests passed” for a subset. Reserve “full suite passed” for the entire configured suite. Neither supports agronomist equivalence.

## Benchmark changes

Questions, reference criteria, arms, primary endpoints, exclusions, and judge policy should be frozen before generation. Preserve answer text, per-dimension judgment, prompts/outputs, stage traces, and hashes in a content-addressed run bundle. Public exports may redact private content while retaining a verifiable manifest and declared artifact-access boundary.
