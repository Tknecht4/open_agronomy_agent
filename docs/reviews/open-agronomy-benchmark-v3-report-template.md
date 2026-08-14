# Open Agronomy Agent benchmark v3 report template

**Benchmark/cohort:** _insert immutable IDs_
**Source commit:** _insert commit_
**Protocol/holdout/system fingerprints:** _insert hashes_
**Run status:** _complete, incomplete, or deviated_
**Claim boundary:** exact frozen set and runtime only; no agronomist-equivalence, field-efficacy, legal-compliance, or autonomous-action claim

This template is frozen before release outcomes. Keep **observation**, **model**, and **interpretation** separate. Preserve failures and deviations; do not rewrite the protocol or holdout to make a gate pass.

## Executive result

### Observation

_Report completion counts, typed failures, primary endpoints, intervals, and whether every preregistered gate was met._

### Model

_State the exact-set estimand and statistical model. Distinguish item-family uncertainty from repeated-trial variation._

### Interpretation

_Give the narrow conclusion supported by the frozen set. List plausible rival explanations and unsupported claims._

## Immutable identities

| Identity | Value |
|---|---|
| Protocol SHA-256 | |
| Private suite commitment SHA-256 | |
| Rubric/source-package/access-log commitments | |
| Source commit and clean-checkout receipt | |
| Environment receipt and source SBOM | |
| Model IDs, revisions, backends, quantization/configuration hashes | |
| Corpus, graph, prompt, tool, policy, verifier, renderer and fallback hashes | |
| Executor, construct, cohort and system fingerprints | |
| Trial, seed, process, cache and case-order policy | |

## Data and review governance

- independent scenario authors and agronomic reviewers;
- author/reviewer role separation;
- language and construct-stratum counts;
- access/exposure log and amendments;
- blinded answer-review procedure and disagreements;
- automated-judge calibration and order-reversal results; and
- confirmation that release plaintext was not inspected by the implementation team before freeze.

## Execution accounting

Report planned, completed, failed, timed-out, parser-failed, tool-failed, verifier-failed, and interrupted cells by model, system, arm, stratum, and trial. Never impute a missing observation as zero or silently drop it.

## Model comparisons under one harness

For every preregistered endpoint, report paired counts, exact effect, scenario-family clustered 95% interval, practical-equivalence margin, and multiplicity status. Preserve model backend/configuration as part of identity.

## Harness capability experiments

Report assignment and actual activation separately. Include only contrasts where the changed component executed for eligible cases.

| Contrast | Eligible families/cases | Assigned cells | Activated cells | Effect and interval | Invalid/no-op cells |
|---|---:|---:|---:|---|---:|
| Document retrieval main effect | | | | | |
| Graph retrieval main effect | | | | | |
| Document × graph interaction | | | | | |
| Field-context contribution | | | | | |
| Typed-tool contribution | | | | | |
| Risk-intervention trade-off | | | | | |
| Verifier draft-to-final utility | | | | | |
| Fallback recovery | | | | | |

## Selective helpfulness

Report substantive-answer coverage, answerable-case coverage, false abstention, unsafe specificity, correct/minimal clarification, useful partial assistance, evidence/tool final-use continuity, and risk–coverage curves. Keep blanket refusal distinct from a useful bounded answer.

## Capability-chain diagnostics

For routing, field context, document retrieval, graph retrieval, tools, answerability, verifier, renderer, fallback, privacy, retention, and orchestration parity, report:

1. availability;
2. selection;
3. invocation;
4. successful result;
5. evidence continuity;
6. final-answer use; and
7. fault recovery.

## Reliability and resources

Report per-trial success, all-trials consistency, within-item variance, latency, token counts, peak memory, disk, timeout/parser/infrastructure failures, and local-versus-remote execution boundaries. Do not compare heterogeneous backend latency as if it were an algorithm-only effect.

## Human and automated judge agreement

Report human agreement, retained disagreements, automated-judge confusion matrices, false positive/negative rates, order flips, parse failures, self-judgment cases, and adjudication outcomes by rubric dimension.

## Deviations and negative results

List every deviation, discovered implementation defect, wrong-jurisdiction event, contamination/exposure event, unexpected fallback, invalid contrast, and failed gate. State whether it requires an amendment, cohort retirement, or a new benchmark version.

## Limitations and prohibited interpretations

Restate exact-set scope, synthetic/project-authored development boundaries, independent-review scope, jurisdictions/languages/crops covered, absent modalities and real-user evidence, and why the result does not prove agronomist equivalence, field efficacy, legal compliance, or safe autonomous action.

## Reproduction and retention

Provide the authorized operator command, stop/recovery procedure, clean-checkout/environment receipts, private retention-bundle verification, public-safe derivative verification, and a file-by-file artifact inventory. Do not publish prompts, private context, raw answers, judge rationales, or other restricted content merely to improve reproducibility.
