# Release evaluation foundation

`scripts/run_release_evaluation.py` is the single entry point for the versioned
engineering release suite in `configs/release_evaluation_v1.json`. It combines
instrument, capability, retrieval, field-data, product-contract and performance
checks with persisted scenarios through the application's
`execute_agent_request` boundary. These are development and regression evidence.
Neither engineering completion, automated grading, nor supplied human review
establishes field efficacy or agronomist equivalence.

Inspect execution surfaces through the same analysis entry point:

```bash
PYTHONPATH=src .venv/bin/python scripts/analyze_release_evaluation.py --inventory
```

This hashes declared runner/module/test consumers and distinguishes the current
release path, historical four-arm runner, v2 deterministic contract QA, v3
explicit-executor orchestration and question metadata inventory. It executes no
tests or inference. The v2 production causal-arm adapter and a canonical v3
real-product adapter remain unqualified; their planners and fixture tests cannot
substitute for those integrations. Historical runners retain their original
constructs and are not renamed as production competence instruments.

## Profiles and execution

| Profile | Backend | Trials per case | Component performance repeats | Purpose |
|---|---|---:|---:|---|
| `ci` | Mock | 1 | 5 | Deterministic engineering checks; no Gemma or domain-quality claim |
| `smoke` | MLX | 1 | 5 | Bounded model execution; permits a case limit and cannot earn a full release pass |
| `baseline` | MLX | 2 | 20 | Complete retained reference on a provisioned local model |
| `release` | MLX | 2 | 20 | Complete candidate plus compatible retained reference comparison |

Run from the repository root in the supported Python environment. Inspect the
plan without executing a model:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_release_evaluation.py \
  --profile baseline --run-id baseline-v1 --dry-run
```

CI needs no model download. Each execution needs a new output directory:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_release_evaluation.py \
  --profile ci --run-id ci-v1 --output-dir /tmp/open-agronomy-ci-v1

PYTHONPATH=src .venv/bin/python scripts/run_release_evaluation.py \
  --profile smoke --limit 4 --run-id smoke-v1 \
  --output-dir /tmp/open-agronomy-smoke-v1
```

MLX runs require the configured, locally provisioned snapshot and a compatible
runtime. The runner does not provision weights. Freeze executable source before
starting a full baseline; retain its complete directory privately:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_release_evaluation.py \
  --profile baseline --run-id baseline-v1 \
  --output-dir /tmp/open-agronomy-baseline-v1

PYTHONPATH=src .venv/bin/python scripts/run_release_evaluation.py \
  --profile release --run-id candidate-v1 \
  --reference /tmp/open-agronomy-baseline-v1/report.json \
  --output-dir /tmp/open-agronomy-candidate-v1
```

A release requires a complete matching baseline or release reference. A mock CI
run, limited smoke, partial ledger or incompatible report cannot substitute.
Blocking execution and comparison gates return a nonzero exit. Inspect both
`status` and `domain_status`; `engineering_pass` is an engineering disposition.
`smoke_complete` remains a bounded execution disposition.

## What is measured

The registry currently contains 36 exposed harness scenarios and 256 exposed
legacy successor-development agronomy cases. Mechanical assertions test routing,
tool binding, field/history corrections, evidence and authority boundaries,
ordered stage receipts and persistence. The instrument checks include numeric
value, unit, negation and empty-contract controls. Retrieval reports positive
recall and negative-control compliance with separate denominators. Dependent
field bundles, turns and repeated trials are counted separately from scenario
families and do not constitute independent domain evidence.

The default arm is `production_full`. The supported arm machinery also allows
raw and kernel ablations in a versioned registry; reference arms retain their own
execution boundaries and do not receive fabricated production stage receipts.
Declared synthetic backend faults are restricted to mock scenarios. Actual
model failures remain actual failed observations.

Production-turn latency and model memory measurements are separate from mock
backend/storage component profiling. The backend comparison has ten named warm
latency gates: `health_warm`, `configs_warm`, `geo_layers_warm`,
`fields_list_warm`, `sessions_list_warm`, `field_history_warm`,
`sessions_list_seeded_warm`, `full_session_history_read_warm`,
`bounded_session_history_read_warm` and `core_mock_warm`. Each needs at least 20
eligible samples in both full-model runs, matching hardware/environment identity
and no more than the registry's 1.25 p95 latency ratio. Missing cells or samples
block this comparison; a pooled mean cannot replace a named gate. CI and smoke
collect five repeats as diagnostics and cannot qualify these full comparison
gates. These mock backend/storage timings do not measure model inference.

Reports retain missing measurements and sample denominators. GPU results apply
to their recorded runtime and cannot establish native Mac latency or memory
budgets.

The full-turn timer includes native model preparation/loading, product execution,
editing and persistence; it excludes worker-process startup. Native first-token
timing starts inside generation and can exclude loading performed earlier during
prompt counting. It is not cold-request time to first token. The existing
`model.load_or_reuse` stage times lazy wrapper setup, while queue, template and
prefill stage entries can be skipped placeholders with zero duration. Read their
states in the private stage receipts; a public zero for these spans does not
establish a measured zero cost. Native load and generation statistics are retained
separately in each turn's model-execution receipt.

## Retention and resume

A run binds source bytes and commit, registry/config/case hashes, scorer version
and the dynamic hash of its scorer implementation,
model identity, sampling, runtime environment and supplied reference/review bytes
in its plan. It retains observation rows, worker specifications and logs,
component receipts, a private `report.json`, a minimized `public-summary.json`
and a `retention.json` manifest. Private artifacts may include questions,
answers, exact prompts, persisted transcripts and local paths. Keep the full
run outside the public package and inspect the aggregate projection before
sharing it. Review-file bytes are read and frozen before execution; the report
uses those retained bytes rather than a later reread of a mutable input file.
Changing a supplied review during execution cannot silently change its grades.

Resume only the same plan and artifacts:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_release_evaluation.py \
  --profile baseline --run-id baseline-v1 \
  --output-dir /tmp/open-agronomy-baseline-v1 --resume
```

Changed source, configs, cases, model/runtime identity, reference or review
inputs require a successor run. Resume rejects identity drift and retained
artifact tampering. Failed or interrupted cells remain evidence; do not edit
rows to turn them into passes or overwrite a failed cell with a retry.

## Semantic review and reference compatibility

Independent numeric gold remains in the controller. Product workers receive
only allowlisted requests, premises and mechanical assertions. Reference
answers and semantic rubrics never enter runtime retrieval, prompts or training.
The current foundation policy explicitly requires zero semantic-review coverage.
Consequently a complete engineering run may still report `review_pending` and
unknown semantic metrics. This does not imply zero material errors or complete
required-task performance.

Supply source-bound review JSONL with `--reviews`. Each record binds
`observation_id`, `case_sha256`, `answer_sha256`, `reviewer_id`, `reviewer_type`
and `rubric_sha256`. Supported human roles are `human_agronomist` and
`human_domain_reviewer`; `automated_triage` is reported separately and excluded
from release semantic gates. Review fields distinguish `required_complete`,
`optional_usefulness`, `source_supported`, `material_error` and
`unnecessary_abstention`; missing values remain null. Binding validates supplied
records, not reviewer credentials or independent scientific qualification.

Optional `stage_labels` support editor-quality diagnostics on retained draft,
post-verification and final text. Bind each label to its retained stage receipt
and the same reviewer/rubric provenance; assess source support, completeness and
material errors separately at each stage. An editor changing text or a hash
matching a receipt does not establish an improvement. Without supplied stage
review, editor-quality effects remain unknown. Stage labels neither introduce a
hidden generation rubric nor invoke another model; they are offline review
observations and remain distinct from final-answer release labels.

Reference comparison requires matching suite, registry, cohort, scorer version
and scorer implementation hash, model and sampling identities. A version string
alone cannot establish scorer compatibility after its code changes. Source
changes are recorded independently. Performance
comparison also requires compatible recorded environments and sufficient
eligible samples. Missing required numeric, retrieval or resource measurements
block comparison. When semantic review is required by policy, missing paired
labels block that gate. Under the zero-coverage foundation policy, unassessed
semantic comparisons remain explicitly pending and cannot support domain claims.

Paired required-task completion is gated at the case and scenario-family level
as well as in aggregate. Each exact paired trial must meet the case regression
limit: a gain on another case, or another trial of the same case, cannot cancel
a loss. Each observed family's completion rate must also meet the policy limit.
Unknown pairs remain unknown and count against required review coverage; an
unchanged overall mean cannot conceal an observed local regression.

Offline reanalysis through `scripts/analyze_release_evaluation.py` verifies the
retained run and recomputes reports from observations without model execution.
For example:

```bash
PYTHONPATH=src .venv/bin/python scripts/analyze_release_evaluation.py \
  --run-dir /tmp/open-agronomy-baseline-v1 \
  --output-dir /tmp/open-agronomy-baseline-analysis-v1 \
  --export-review-packet
```

The optional review packet is private answer-level context. Add `--reviews` and
`--reference` when supplied review records or a compatible comparison are needed.
A retained reviewed analysis can itself serve as `--reference`, and its directory
can be the `--run-dir` of a subsequent analysis. The loader verifies the chain's
review bytes, reports, analysis-source hashes and original raw-run lineage. Keep
the original raw directory at its bound location, along with every referenced
parent analysis; moving only a derived report breaks those bindings. Derived
outputs must remain outside the immutable raw and reference directories.

Reanalysis preserves recorded numeric scores; it does not silently rescore raw
answers with today's numeric implementation. Numeric rescoring with a changed
instrument is a separate evaluation identity and requires a new compatible
baseline before regression comparison. New analysis preserves original
observations, plan, reviewer bindings and negative results.

## Descriptive model metrics and private fixture panels

The same analyzer accepts optional `--model-rubrics`, `--criterion-reviews` and
`--model-policy` with a retained `--run-dir`. These add private model-metric
sidecars; they preserve the recorded release report, gates and numeric scores.
Rubrics bind the original case hash; reviews also bind the answer and rubric.
Useful completion, restraint, numeric/unit accuracy, evidence support and
applicability remain separate dimensions. Tool correctness is reported
separately; an explicitly inapplicable manual/no-attempt observation differs
from an unassessable attempt or missing evidence.

Supply an explicit versioned project policy for domain/dimension weights,
failure, truncation, missingness and sensitivity profiles. Hash equality binds
the policy to a plan but does not prove prospective preregistration. Unknown
labels preserve fixed denominators and bounds. Fatal conditions and unknown
safety remain visible; descriptive aggregates grant no promotion or ranking
authority. Contrasts require recorded matching facts, criterion masks and cohort,
with configuration/source/runtime and each arm's recipe identities retained.
Hardware and timing comparability need their own evidence.

`configs/model_scoring_development_v1.json` supplies a provisional policy for
the ten exposed agronomic development domains. Each domain has weight 0.1;
each of the five common outcome dimensions has weight 0.2. Clusters receive
equal weight within a domain, observations equal weight within a cluster,
and criterion weights come from the reviewed rubric. Tool correctness remains
separate. Two supplied sensitivity profiles emphasize numeric/useful completion
or restraint/applicability without changing domain coverage. These are project
choices, not expert consensus. Freeze the exact policy and rubric bytes before
future authorized execution; applying them to retained evidence is retrospective.

Missing criterion labels retain unknowns and fixed-denominator bounds. Failed
and truncated observations receive a descriptive outcome penalty of zero,
while their semantic and safety labels can remain unknown. Report fatal failures
and missing safety review separately; neither a high average nor complete
synthetic labels authorize a ranking, rollout or promotion. Complete scores
require every planned weighted domain/cluster/label or the declared execution
penalty. Contrasts additionally require matching facts, criterion masks and
recorded compatible conditions. This policy does not admit cases, run a model,
or replace the release gate.

Exercise the same CLI with the public, project-authored instrument example:

```bash
PYTHONPATH=src .venv/bin/python scripts/analyze_release_evaluation.py \
  --development-panel tests/fixtures/development_scoring_v1 \
  --model-policy configs/model_scoring_development_v1.json \
  --output-dir /tmp/open-agronomy-scoring-example-v1
```

Use a new output path. This example deliberately exits 1 with `partial_unknown`:
its 40 imposed fixture observations include failure and unknown-label controls.
No model, tool or evaluation worker executes. Every question uses the same
supplied 2 kg + 3 kg arithmetic; the ten domain IDs test weighting coverage,
not ten agronomic skills. Its symbolic arm names describe fixtures only.

| Instrument output | Expected result |
|---|---|
| `raw_model` descriptive composite | 0.5; all ten domain means 0.5; ten explicit failures penalized zero |
| `production_full` composite | Unknown; fixed-denominator bounds [0.375, 0.875]; ten completed fixtures lack labels |
| Safety | One imposed fatal failure; ten unknown safety reviews in each group |
| Tool correctness | Explicit no-attempt N/A, outside the composite |
| Ranking and promotion | Unauthorized, including when synthetic labels are completed |

`model-metrics.json` contains group composites, per-domain means, cell dimensions,
unknown statuses, failed/missing/truncated counts, safety counts and blocked
contrasts. `fixture-reviews.private.json` retains individual USE, CAL, NUM, ENT
and APP criterion scores and their bindings. For the first synthetic fixture
all five imposed scores are 1; the unknown control stores null. These outputs
remain controller-only even though this example's inputs are public-safe.
They are instrument checks, never actual model grades or independent labels.

A sealed six-cell closeout can use `--diagnostic-closeout` instead of `--run-dir`:

```bash
PYTHONPATH=src .venv/bin/python scripts/analyze_release_evaluation.py \
  --diagnostic-closeout /absolute/path/to/private-closeout \
  --output-dir /absolute/path/to/new-private-analysis
```

This reads only the pinned closeout children, preserving six observed answers,
original helper failures, model-identity limits and zero expert labels. It does
not follow external archives, rerun a model or establish full-suite/JLens
completion. Missing policy or review produces blocked/partial metrics and a
nonzero exit, while retaining reviewable evidence.

`--development-panel /absolute/path/to/private-panel` binds a sealed panel's
synthetic QA fixtures through `normalize_case`, the actual worker allowlist and
the same rubric/review scorer. It accepts an optional explicit `--model-policy`.
Its output is labelled synthetic fixture analysis, with no model or worker
execution. Questions, rubrics, Decimal oracles and source support stay private;
no packet code is executed, no vector extractor or expert gold is implied, and
the default runtime or release registry is unchanged. Scientific review and
prospective execution admission remain separate steps. Do not interpret a
hand-authored fixture's grade as an observed model answer.

Model-metric files, retained private labels/policy, source bindings and fixture
plans remain controller-only. They have no automatic public projection. Use a
new output directory outside every immutable input directory. A later ordinary
reanalysis does not silently inherit these optional criterion labels.

Workspace feedback aggregation is a review summary, not executed regression
evidence. An ideal answer or approved feedback cannot qualify a rollout-review
gate. Read actual execution status and source-bound reports separately.

## Current execution surfaces

| Surface | Current status |
|---|---|
| `frontend/src/main.tsx` → `OpenAgronomyApp`, `server/app.py` → `execute_agent_request` | Wired production workspace and answer path; source tests do not qualify an installed native package |
| `run_release_evaluation.py`, `analyze_release_evaluation.py` | Maintained engineering runner and one offline analyzer; exposed development evidence, with model execution requiring separate authorization/provisioning |
| Public instrument fixture and privately sealed agronomic panel | Synthetic scoring/worker-isolation QA; scientific review, labels and prospective admission remain separate |
| RC1–RC3, frozen model runs and earlier four-arm records | Historical evidence under their original source/prompt/arm identities |
| v2/v3 production adapters, remaining complete-calculator readiness, alternate frontend shell retirement | Deferred; fixture coverage and import reachability alone do not qualify adapters or justify deleting a shell |

The v3 candidate CLI accepts an explicitly supplied executor only with current,
matrix-bound authorization. Its process runner checks observation identity; it
does not independently qualify that executor as a production-core adapter.
An importable callable, a completed ledger or a dry run therefore cannot
establish production parity or a model-performance claim.

Unknown review, authority, source coverage or comparability remains unknown.

## Expanding the suite

1. Add a versioned case file and registry entry with explicit suite/case/family
   IDs, exposure, lane, required profile coverage and review role. Preserve old
   cohorts and historical scores.
2. Use exposed mechanical assertions for deterministic product contracts. Put
   independent numeric gold and private semantic rubrics in controller inputs;
   never expose answers to generation or retrieval.
3. Add positive and negative instrument controls and tests for the smallest new
   contract. Distinguish source availability from recommendation correctness.
4. For semantic competence, establish a prospective source-distinct cohort,
   qualified review policy and required coverage before execution. Exposed
   development success cannot become independent confirmation retrospectively.
5. Run focused tests, deterministic CI and the repository validation ladder;
   establish a complete compatible model baseline before comparing a release.

The `.github/workflows/release-evaluation.yml` job runs focused foundation tests
and the mock profile. It protects this engineering foundation and does not
replace complete model execution, semantic review or external validation.
The job retains its synthetic, exposed development observations and logs for
14 days, including blocked runs. Private knowledge overlays are disabled; the
CI artifacts contain no production farmer records or privately supplied gold.
Artifact retention is a debugging receipt, not a release promotion.

Optional ablations use the same questions and independent controller scoring.
`assertions` apply to `production_full`; `assertions_by_arm` supplies explicit
expectations for a diagnostic arm. Its disabled-component and persistence
invariants still run. Numeric diagnostic scores are retained without imposing
the production answer threshold on the raw model. All planned cells must complete.

For a Linux NVIDIA Colab runtime, install
`requirements-release-evaluation-colab.txt` and the editable project. The runner
discards inherited agronomy environment overrides, selects the native MLX
transport, and uses offline model loading after explicit snapshot provisioning.
The recorded GPU environment is its performance reference; it does not measure
native Mac latency.
