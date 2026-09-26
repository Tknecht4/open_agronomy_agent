# Two-Gemma current-code Colab assessment

## Decision

The QA/QC branch is suitable to merge as an engineering and governance upgrade, provided the PR describes this round as exposed development-regression evidence. It is not sufficient to approve either model as agronomist-equivalent or deployment-ready.

Gemma 4 E2B remains the production candidate. Gemma 3 270M should not be promoted: its full-system verifier produced a fallback or degraded result in 148 of 241 cases in every trial. Gemma 4 reduced that dependence to 98–100 cases, but this is still too high for a production-quality claim.

## Execution identity

The run evaluated commit `d43ade76967644f6d4d3fc09176c45537b9b12af` on the frozen 241-case runtime-v2 Canadian benchmark. Both pinned MLX models ran four arms under three fixed trials on NVIDIA A100-SXM4-40GB Colab runtimes. The six intended trials produced 5,784 responses and six independently verified private/public retention bundles.

No automated semantic judge or independent agronomist adjudication was run. The suite is exposed and was previously used during development, so its results cannot be represented as sealed-v3 evidence.

## Findings

| Finding | Gemma 3 270M | Gemma 4 E2B |
|---|---:|---:|
| Full-system objective calculations | 100% | 100% |
| Full-system official-source lexical proxy | 49.90 | 58.07 |
| Raw-model official-source lexical proxy | 43.60 | 61.23 |
| Full-system exact three-trial repeatability | 241/241 | 214/241 |
| Full-system fallback/degraded cases per trial | 148 | 98–100 |
| French preservation per full-system trial | 12/12 | 12/12 |
| Complete required-guard traces per full-system trial | 154/154 | 154/154 |

All six full-system executions preserved generation-input lineage, field-context binding, route traces, context-admission traces, and evidence lineage at 100%. Every full-system trial completed the 16 deterministic calculation cases correctly.

Gemma 4's 27 non-repeatable full-system cases are concentrated in official-source answer boundaries and verifier preserve/rewrite paths; its raw, kernel-only, and kernel-plus-field arms were each 241/241 repeatable. This isolates the remaining reproducibility concern to the full evidence/intervention path rather than base generation alone.

The lexical proxy is a narrow exposed regression measure, not answer quality. Gemma 4's full-system value was below its raw-model value, while deterministic calculations improved from 25% raw to 100% full system. Without calibrated semantic judging or human review, these endpoints cannot be collapsed into a claim that the full system is better overall.

## QA/QC gates

- Backend: 992 passed.
- Frontend: 205 passed; typecheck and production build passed.
- Documentation source, strict build, and rendered-site audits passed.
- Clean-checkout release audit passed against a fresh environment receipt.
- Current-code guard replay passed 154/154 with all 17 stages present.
- Retrieval remained Recall@1 0.810, Recall@3 0.857, Recall@7 0.905, and nDCG@7 0.860, with 100% source-locator and jurisdiction-authority compliance.
- The 221,344-row successor corpus retained complete source locators and quality ledgers.
- All six benchmark retention bundles reverified locally after download.

## Operational note

The controller briefly began a duplicate Gemma 4 trial after the 270M sequence because the original combined remote script still contained both models. The duplicate was cancelled as soon as detected, before acceptance, and is excluded from all six intended trial archives and metrics. The intended trial identities were neither retried nor replaced.

## Remaining gates

Before a production competence decision, investigate the 27 Gemma 4 full-system repeatability failures, reduce or explain verifier fallback dependence, pass the preregistered semantic controls, and complete independent agronomist review. Sealed-v3, deployment compliance, autonomous action, field outcomes, and population generalization remain unfulfilled.

The machine-readable public-safe receipt is in [two-gemma-colab-assessment-20260926.json](artifacts/two-gemma-colab-assessment-20260926.json).
