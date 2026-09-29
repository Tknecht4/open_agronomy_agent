# Coordinated dependency PR reconciliation — 2026-09-29

The maintainer requested merging all open dependency PRs before new architecture work. This candidate retains the ancestry of PRs #22 and #24–#30 and reconciles their combined dependency graph. A merged PR does not mean every proposed version became active.

| PR | Disposition |
| --- | --- |
| #22 cryptography | Superseded by main security replacement 50.0.1; preserve >=50.0.1,<51 and exact native 50.0.1. Do not downgrade to 50.0.0. |
| #24 Actions | Adopt new commit-pinned releases. Repair the floating-action negative test to mutate the current SHA and assert that the mutation occurred. |
| #25 frontend group | Adopt Leaflet types 1.9.22, Lucide 1.48.0, Testing Library React 16.3.3. |
| #26 jest-dom | Adopt 7.0.1 with a supported Node toolchain. |
| #27 Vitest | Adopt 5.0.2; align Node types and active CI/container/developer instructions on Node 24. Regenerate the lockfile without forced peer resolution. |
| #28 Python group | Adopt JSON Schema 4.26.0 and native NumPy 2.4.6/Matplotlib 3.11.2. Preserve frozen benchmark-analysis pins and imagery NumPy 2.5.3. Retain pydantic-core 2.46.5 required by Pydantic 2.13.5, and fsspec 2026.2.0 compatible with datasets 5.0.1. |
| #29 Agno | Adopt packaging dependency 3.0.11 and permitted range <3.1. Align only active RAG metadata and its registered hash. The local knowledge facade does not call the Agno SDK; this is not a new retrieval implementation. Frozen/candidate configs remain unchanged. |
| #30 Hugging Face Hub | Defer Hub 2 in native/training: current Transformers 5.17.0 and datasets 5.0.1 require Hub <2. Preserve native Hub 1.33.0 and training <2. Original branch ancestry is integrated with this compatibility resolution. |

The native constraint file is an updated candidate, not an unchanged historical environment receipt. No model identity, source authority, benchmark answer or historical result is changed.

Automatic deletion of merged branches is enabled on GitHub and recorded in repository policy. Existing main protection remains in force.

## Verification

Observed locally: the native Mac constraints resolve together; Node 24.21.0 typechecking, all 401 frontend tests and the production build pass. Product types remain ES2020 while Node-hosted tests use a separate ES2022 configuration. The public-doc checker, strict MkDocs build, runtime corpus audit and curated public-package builder pass.

Acceptance additionally requires the full Python suite, fresh GitHub Python/frontend/documentation/Mac checks and independent review bound to the final candidate. The pull request records those final outcomes; this document does not substitute for them. Local Python validation reuses existing test dependencies with changed packages isolated; GitHub performs fresh dependency installation. Failed historical CI runs remain evidence.
