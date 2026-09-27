# Current-code two-Gemma assessment

## Decision

The QA/QC branch is suitable to merge as an engineering and governance
upgrade. This assessment does **not** approve a production competence claim.
Gemma 4 E2B remains the production candidate; Gemma 3 270M is not recommended
for promotion because its verifier relied on fallback or degraded handling in
148 of 241 full-system cases in every trial.

The run evaluated commit `d43ade76967644f6d4d3fc09176c45537b9b12af`
against the frozen 241-case runtime-v2 Canadian development suite. Both pinned
MLX models ran raw, kernel-only, kernel-plus-field, and full-system arms under
three fixed trials on NVIDIA A100-SXM4-40GB Colab runtimes. The six intended
trials produced 5,784 responses and six independently reverified retention
bundles.

## Results

| Endpoint | Gemma 3 270M | Gemma 4 E2B |
|---|---:|---:|
| Full-system objective calculations | 100% | 100% |
| Full-system official-source lexical proxy | 49.90 | 58.07 |
| Raw-model official-source lexical proxy | 43.60 | 61.23 |
| Exact full-system repeatability across three trials | 241/241 | 214/241 |
| Full-system fallback/degraded cases per trial | 148 | 98–100 |
| French preservation per full-system trial | 12/12 | 12/12 |
| Complete guard traces per full-system trial | 154/154 | 154/154 |

The lexical proxy is a narrow exposed regression measure, not semantic answer
quality. Gemma 4's full system improved deterministic calculations from 25% in
the raw arm to 100%, while its official-source proxy was lower than raw. These
separate endpoints cannot be collapsed into an overall quality claim without
calibrated semantic judging and independent review.

Gemma 4's 27 non-repeatable cases were confined to the full-system arm and
concentrated in official-source boundaries and verifier preserve/rewrite paths.
Its raw, kernel-only, and kernel-plus-field arms were each 241/241 repeatable.
This is a full evidence/intervention-path reproducibility issue, not evidence
that base generation itself was unstable in this run.

## System and release gates

- Backend: 992 tests passed.
- Frontend: 205 tests passed; typecheck and production build passed.
- Documentation source, strict build, and rendered-site audits passed.
- Clean-checkout release audit passed.
- Current-code production replay passed 154/154 required guard routes with all
  17 stages present.
- Retrieval measured Recall@1 0.810, Recall@3 0.857, Recall@7 0.905, and
  nDCG@7 0.860, with 100% source-locator and jurisdiction-authority compliance.
- All 221,344 successor-corpus rows retained complete locators and quality
  ledgers.

## Operational record

The controller briefly began a duplicate Gemma 4 trial after the 270M matrix
because the original combined remote script still contained both models. It
was detected and cancelled before acceptance. It is excluded from the six
intended archives and every metric above; none of the intended trial
identities was retried or replaced.

The public-safe machine-readable receipt is retained in the repository at
[`docs/reviews/artifacts/two-gemma-colab-assessment-20260926.json`](https://github.com/Tknecht4/open_agronomy_agent/blob/main/docs/reviews/artifacts/two-gemma-colab-assessment-20260926.json).

## Claim boundary

This is exposed development-regression and system-interface evidence. It is
not sealed-v3, independent agronomist adjudication, field validation,
deployment approval, autonomous-action approval, or a population-level
competence claim. Before such a decision, investigate the 27 Gemma 4
repeatability failures, reduce or explain fallback dependence, pass the
preregistered semantic controls, and complete independent agronomist review.
