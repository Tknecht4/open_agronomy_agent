# Repository guidance for coding agents

## Read first

1. `README.md` for supported setup and claim limits.
2. `ARCHITECTURE.md` for code ownership and execution paths.
3. The nearest subsystem README (`src/agronomy_agent/`, `server/`, `tools/`,
   `scripts/`, `configs/`, `data/`, or `tests/`).
4. The active config and tests that control the requested behavior.

## Active boundaries

- Product answers enter through `server/app.py` and
  `server/services/chat_service.py::execute_agent_request`.
- The router classifies intent/risk/query shape. Capability selection belongs
  to the registry-driven planners.
- Active profiles are selected by `configs/model.yaml`, `configs/rag.yaml`,
  and `configs/runtime_profiles.json`.
- Historical/frozen benchmark artifacts are evidence. Do not rewrite, move, or
  activate them because a filename looks newer.
- Evaluation cases and answers must never enter runtime retrieval or training.

## Change rules

- Establish branch, dirty state, active consumers, and tests before editing.
- Search imports, CLI entry points, dynamic registry references, configs,
  container commands, and documentation before calling code unused.
- Prefer removal of a complete unused island over leaving compatibility shims
  for undocumented pre-1.0 internals.
- Do not delete runtime data or historical receipts solely to reduce size;
  provide a content-addressed replacement and migration first.
- Preserve observations, model output, and interpretation as distinct records.
- Unknown capability, authority, jurisdiction, or evidence is not a pass.

## Verification ladder

Use focused tests while iterating. Before a repository-wide claim run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python scripts/check_public_docs.py
PYTHONPATH=src .venv/bin/mkdocs build --strict
cd frontend && npm run typecheck && npm test && npm run build
```

Run corpus, retrieval, release, or model gates when their controlling inputs
change. A passing test suite is not agronomic validation.

## Documentation

- Human overview: `README.md` and `docs/public/`.
- Maintainer architecture: `ARCHITECTURE.md`.
- Historical reviews and evidence: `docs/reviews/`.
- Operator procedures: `scripts/README.md` and `docs/public/operations/`.
- Update the public manifest when adding an explicit file outside an included
  tree, and run the public-package builder before committing.
