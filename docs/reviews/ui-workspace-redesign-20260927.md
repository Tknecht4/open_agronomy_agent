# Workspace redesign: plan and execution record

Status: implemented. Technical checks are recorded below; human PR acceptance remains outstanding. Branch: `codex/ui-workspace-redesign`.
Reference: remote `main`, `7a34111` (verified 2026-09-27 UTC).

## Working contract

Goal: turn the prototype into a coherent field/question workspace, reducing data-entry
friction while preserving every supported backend capability and evidence boundary.
The user authorized review followed by implementation, local Gemma model provisioning,
frontend/backend profiling, a measured optimization round, and documentation/showcase work.
PR acceptance remains a human decision. Historical benchmark artifacts stay frozen.

Context index: `frontend/README.md`, `frontend/src/OpenAgronomyApp.tsx`,
`frontend/src/LeafletFieldMap.tsx`, `frontend/src/fieldGeometry.ts`,
`src/agronomy_agent/server/README.md`, `docs/public/architecture.md`,
`configs/model.yaml`, `configs/rag.yaml`, `configs/runtime_profiles.json`.
`ARCHITECTURE.md` and root `server/` do not exist at this main revision; their
maintainer guidance is represented by the package/server READMEs and public architecture.

Constraints: map context is not measurement; suggested values need provenance and
confirmation; unknown data stays unknown; preserve offline drafts, field identity,
session history, source/trace inspection, supported ingestion and export paths.
Use isolated synthetic local records for browser/profiling work. Do not migrate or
delete personal runtime data. Do not change active model/corpus quality contracts
to make performance numbers look better.

## Phases and acceptance

| Phase | Deliverable | Acceptance evidence |
|---|---|---|
| 0. Inspect and baseline | Live walkthrough, backend feature inventory, field-state defects, frontend/API timings | Reproducible findings tied to source; preserve unavailable paths as gaps |
| 1. Workspace foundation | Clear primary navigation, spacious conversation, expandable map, progressive disclosure | Desktop/mobile browser inspection; keyboard and automated regressions |
| 2. Field and map flow | Guided creation, safe prefills, reversible drawing/editing, clear persistence and recovery | Create/edit/reload/switch/import/cancel checks; no cross-field leakage |
| 3. Connected capabilities | Accessible history, measurements, source inspection, private data, sync/export, runtime settings | Backend-to-UI capability matrix and exercised supported paths |
| 4. Profile and optimize | Production frontend and API/agent measurements, pinned Gemma live turn, bottleneck repairs | Comparable before/after receipts, stage latency and resource limits; no model-quality claims |
| 5. Documentation and showcase | Professional README, actual screenshot/GIF, Pages/workflow/customization documentation | Public-doc checks, strict MkDocs, package builder, asset provenance |
| 6. Integrated acceptance | Settled candidate, full checks, independent implementation review | Full required verification, repaired review findings, explicit residual risks |

Planning envelope: owner plus two bounded specialists (backend/performance and map
interaction), then one independent acceptance reviewer. Start with a 2–4 hour work
envelope and checkpoint after baseline and each integration phase; this is an estimate,
not a user-imposed limit. Use focused tests while editing and one settled full suite.
Dollar/provider token accounting is unavailable. Local disk initially reports 6.7 GiB
available; model provisioning and test temporary state must be sequenced and measured.
If the estimate is exceeded, stop optional embellishment and reassess the shortest
path through the required gates; do not claim partial work as accepted.

## Observations and decisions

- Clean initial working tree. The previous `codex/public-repo-cleanup` branch is
  preserved; its five commits are not implicitly imported into this main-based branch.
- Primary workspace is 4,699 lines and shared stylesheet 4,234 lines at baseline.
  This is evidence of concentrated ownership, not itself a runtime performance claim.
- Working design: question and selected-field workspace, expandable map, short field
  setup, and on-demand evidence/data/diagnostics. Validate against actual interactions.

## Evidence, remaining work, and memory

Raw local observations and timing outputs will live under
`outputs/ui-redesign/`; only synthetic, public-safe summaries/media may be published.
All phases remain pending until their evidence is recorded here. No durable memory
update is authorized or made.

## Executed review and implementation

The review confirmed that the default map pushed the conversation below the fold,
example facts were implicitly loaded into new-user context, field setup and history
competed in one long form, and drawing lacked explicit completion/undo. The live
calculator exercise additionally exposed mixed typed/legacy tool records crashing
the entire UI. This was reproduced with the actual synthetic API response and fixed
at the rendering boundary; the original failed observation is retained locally.

| Obligation | Controlling boundary and delivered change | Evidence |
|---|---|---|
| Spacious coherent workspace | Conversation first, Conversation/Together/Map modes, sidebar/header at appropriate breakpoints | Browser DOM at 1440 × 1000 and 390 × 843; no horizontal document overflow; responsive regressions |
| Low-friction field entry | Isolated three-step dialog; name plus pin sufficient; coordinates, drawing, multi-feature upload; crop/region optional | Real create/reload, upload/select/review and drawing/undo/finish exercised; wizard regressions |
| Safe prefills | Area calculated from polygon, explicit previous-region reuse, crop suggestions; reviewed file labels; empty metadata preserved | Backend create/list/reload unknown-value regression; unsupported multipart/holes rejected |
| Reliable chat/history | No automatic resubmit after stream interruption; earlier messages accessible; per-scope conversation selection and drafts survive reload; async refresh/bootstrap guards | Workflow regressions including StrictMode and delayed responses; real calculator and Gemma answer |
| Backend capabilities | Field events, soil tests, corrections, answer history and sync under Records; private references/Public knowledge/Connections under Data; evidence/export per answer | Existing backend contracts and adapted integration tests; optional hosted/image/research APIs documented as extensions rather than implied available |
| Map usability and safety | Undo/Finish/Cancel, stable vertex editing, fit selected field, resize observer, abort/debounce viewport lookups, offline imagery gate, text-only tooltips | Leaflet tests, hostile-label test, StrictMode fit test; real phone drawing; controls moved below canvas after visual inspection |
| Performance optimization | Deferred map/setup/adapter diagnostics, summary session listing and selected-session hydration, filtered field-history detail loads | Paired browser profile and matched synthetic API measurements; source-bound backend/model receipts |
| Docs and showcase | Expanded README, Pages workspace/customization guides, actual JPEG captures of synthetic UI | Public-doc checker, strict MkDocs, public-package builder |
| Independent acceptance | Fresh Astra review found and drove lifecycle/state/security repairs | Review retained in local outputs; final verdict pending at this edit |

The new UI retains explicit failures and unknowns. Offline basemaps remain blank;
regional priors do not populate crop, sampling results, or a jurisdiction guess.
Boundary area is labelled calculated. A file does not become admitted runtime
knowledge merely because it is uploaded. Hosted administration, image research and
bulk governed ingestion retain their existing API/operator boundaries; the fork
and ingestion guides explain those extension seams.

## Profiling and optimization results

Three alternating production-browser pairs used the same 1440 × 1000 CSS viewport,
same offline API and same synthetic one-field/two-turn database. The main baseline
was built from 7a34111 with byte-identical opt-in instrumentation. Initial API fetches
fell from 12 to 4 and decoded API bytes from 429,795 to 21,157; initial script decoding fell from 556,456 to 414,061.
The comparison includes the intentional change from an implicit example/map to a
neutral general-question start. Median FCP/LCP was 92 ms baseline and 108 ms candidate;
no paint-speed improvement is claimed. The recorded runs had no observed long tasks,
layout shifts or browser errors. These small local observations are not INP, a p95,
a field-device benchmark, or a population-level performance claim.

A matched synthetic two-session payload test measured 305,483 bytes / two full turn loads
versus 1,211 bytes / zero turnloads for summary listing (five calls per path). Selected
conversations load on demand with stale-response guards. Field history detail loads
fell from 160 to 8 in the separate 20-session case; the first after-run slowed under host
contention and is preserved. Model drafting and verification remain dominant:
37.52 s cold and 18.27 s warm for the capped 120-token diagnostic turns, with 17/17
stage receipts. A separate real UI turn used the normal 640-token request limit and
completed. Model/corpus/verifier quality settings were unchanged. First-token and
precise lazy model-load split were unavailable; cold corpus admission audit remains
intentional work. See `artifacts/ui-workspace-performance-20260927.json` and the
separate backend artifact for exact source bindings and limits.

Total downloaded-on-demand code grew as functionality was added; initial work and
total bundle size are different measurements. Fresh production build byte totals
and hashes are retained in `outputs/ui-redesign/production-build.json` locally.

## Verification and retained negative evidence

- Full Python: 995 passed with serial execution and temporary fixtures outside Git.
- Frontend: 239 tests, typecheck and production build passed before final visual-only
  drawing-control polish; final rerun/review reconciliation is recorded at handoff.
- Strict MkDocs and the public documentation checker passed with actual screenshot assets.
- The first clean-checkout Python run found one existing test dependent on an ignored
  benchmark input. Its matrix assertions now use isolated synthetic IDs; frozen inputs
  and claims were not altered.
- A later attempt put pytest temporary files inside Git, violating twelve tests'
  deliberate outside-checkout contracts. Its failed log was retained and the full
  suite was rerun outside Git: 995 passed. This was a test invocation error, not a
  reason to weaken those contracts.
- Independent review repairs covered StrictMode upload and map remounts, stale refresh,
  persisted conversation selection, same-field draft restoration, superseded bootstrap,
  tooltip HTML injection, and silent device-field truncation.

Raw local logs, baseline source/build records, profiler receipts and failed attempts
remain under `outputs/ui-redesign/` and the explicitly named temporary profile bundles.
Only minimized synthetic summaries and screenshots are in the public manifest.
Temporary test/package copies may be removed after retaining their receipts; no
personal runtime state or frozen benchmark record was deleted.

## Remaining boundaries and next decision

Live external providers/imagery, physical touch devices, assistive-technology user
studies and slow-network distributions remain unexercised. The hosted/image research
extensions are not silently promoted into ordinary field advice. The human still
accepts the PR and decides deployment. This work did not publish GitHub Pages or
change model/corpus authority. No durable memory update was requested or made.

## Integration with the updated main branch

The branch was initially created from `7a34111` before any implementation. During
work, main advanced through repository cleanup and local-backend removal. The UI
candidate was saved as `d93953a`, then explicitly integrated with pinned main
`7c502d8`. Removed Redis/S3 and disconnected scaffolding remain removed; the
architecture, repository map, optional spatial setup, dependency lock and CI fixes
from main are retained. Both independent versions of the hermetic matrix test kept
the original assertions; the integrated tree uses main's fixture implementation.

The merged dependency install reports zero npm vulnerabilities. The frontend passes
241 tests plus typecheck and build on Vitest 4.1.11. Post-merge mock and actual pinned
Gemma profiles confirm the integrated source without changing prior receipts:
field-history calls load eight selected turns; the two capped model turns completed
with 17/17 stages in 17.75 s and 15.65 s. These are integration observations, not a
speedup comparison or a quality claim. Exact hashes and limits are in
`artifacts/ui-post-merge-profile-20260927.json`.

The final review also found a storage-bootstrap race. Creating or saving a field is
now gated until storage mode resolves, and superseded initial field-list responses
cannot replace a subsequently created field. Both deferred-response cases pass in
the 43-case workflow suite.

An extra disposable public-package copy exhausted temporary disk space. The failed
log was retained; only this task's regenerable package trees were removed after
retaining available receipts. The package retry passed before the integration
commit. No model cache, personal data, or historical benchmark was removed.

Final integrated validation: **1,019 Python tests passed**, **241 frontend tests passed**, frontend typecheck/build passed, strict MkDocs passed, and the public documentation checker passed. The container runtime inventory was regenerated from the integrated source. The final public-package receipt and independent review bind the delivered merge candidate; human PR acceptance remains separate.
