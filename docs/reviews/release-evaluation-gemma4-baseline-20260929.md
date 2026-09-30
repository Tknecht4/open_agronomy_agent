# Release foundation Gemma 4 baseline

Status: complete, retained and locally verified **engineering baseline**.
The native run returned `engineering_pass`; semantic status remains
`review_pending`. This exposed development cohort is not claim-eligible.
PR CI, merge and post-merge verification were pending when this baseline record
was written; their subsequent receipts are separate integration evidence.

The [public aggregate record](artifacts/release-evaluation-gemma4-baseline-20260929.json)
binds source, instruments, measurements, raw retention and cleanup. The
[operator guide](../public/operations/release-evaluation.md) defines the gates.

## Identity and execution

Run `gemma4-foundation-20260929-v2` executed source
`afcc5af147618fb721b68317d9a2d4020a93c1a2`, core SHA-256
`fab64688605f95371165f60ba31196be4fcdd020147d9a9cff07ade0e815b714`.
The model was `mlx-community/gemma-4-e2b-it-4bit`, revision
`238767527555cb75a05732a84dff5d6ba0dd6809`, with a 640-token output limit,
temperature zero and trial seeds 42/43. The two trials used fresh scenario
processes, disabled prompt caches and source-bound compiled retrieval indexes.
Evaluation gold remained controller-only.

The task-owned Linux NVIDIA L4 runtime recorded driver 580.82.07,
Python 3.13.15, MLX 0.32.2 and MLX-LM 0.31.3. The JSON
record preserves the observed package versions and performance-environment hash.
Execution ran from September 30, 2026, 00:04:46 UTC to 02:57:10 UTC
(10,344.56 seconds), exited zero and stayed within its 10,800-second suite
deadline and 11,040-second supervisor limit.

## Observed results

| Measurement | Observed result |
|---|---|
| Scenario coverage | 292 cases across 67 recorded families; 584/584 trial observations completed |
| Execution checks | Zero failed observations, missing observations or failed mechanical checks |
| Required components | Instrument, capability, retrieval, field data, product contracts and performance all passed |
| Native generation | 366 verified generated MLX turns among 592 observed MLX turns; 360 observations contained generation |
| Numeric instrument | 46/46 independently scored numeric observations passed; mean accuracy 1.0, no missing numeric scores |
| Semantic review | 506 review-required observations; zero supplied review coverage; correctness, completion and material-error metrics remain unknown |
| Exact final repeatability | 284/292 eligible cases repeated exactly; eight differed across trials |
| Backend/storage profiling | All ten required warm cells completed with 20 samples each |

The cohort includes 36 exposed harness/conversation scenarios and 256 exposed
legacy agronomy cases. Six trial cells used declared synthetic mock faults;
these do not establish real backend outage behavior. Trials, turns and dependent
field bundles are not independent scientific observations.

Retrieval recorded positive recall@7 of 1.0 across 19 positive controls and
nDCG@7 of 0.9700, with two negative controls and one blocked case reported
separately. Locator validity, authority compliance and negative-control
compliance were each 1.0 on their exercised denominators. The field-data
component completed 96 dependent cases without failure. Product contracts ran
six registered test files successfully. These are component contracts, not
complete-answer agronomic qualification.

Production-turn elapsed time had p50 19,224.49 ms and p95 24,092.85 ms across
592 MLX turns, including loading, editor work and persistence as defined by the
instrument. The internal generation first-token metric had 366 samples and 226 missing values: p50
1,377.85 ms and p95 1,448.29 ms. Recorded peak memory had 366 samples, 226
missing values and maximum 3,749,790,488 bytes. The ten backend/storage warm
cells are a separate synthetic mock profile; their individual distributions
are retained in the JSON. These GPU measurements do not establish Mac latency,
whole-system memory budgets or field usefulness.

The full-turn elapsed boundary includes native model preparation/loading and
product/model/editor/persistence work, excluding child-process startup. The
named `model.load_or_reuse` span records lazy generator wrapper construction or
reuse, rather than actual native weight loading. Named queue/template/prefill
spans are skipped placeholders; their zero values mean skipped or unobserved,
not measured zero cost. Raw timing records retain these states and native
`model_load_ms`; public stage projections omit the states. The first-token
metric starts inside generation and can exclude earlier loading during prompt
counting, so it is not cold-request time to first token.

## Retention, comparison and predecessor

The downloaded private archive is 295,382,726 bytes, SHA-256
`4d04ecf3f1c85b1b19a88cc640152449ffb20679a748a9ff82b0e7e6028ffc5f`.
Local verification checked 3,374 bundled files, run retention, matrix bindings
and answer-stage hashes. Public-summary, private-report and retention-manifest
hashes are recorded without publishing private paths or answer-level content.

Offline self-comparison returned `engineering_pass`, comparison `pass`, and
semantic `review_pending_not_assessed`, without inference. This verifies the
retained analysis/reference plumbing against the same run; it is not evidence
of a candidate gain or independently reviewed semantic quality. Its derived
retention manifest is sealed and hash-bound in the JSON record.

The interrupted predecessor remains retained separately: 38 observations,
29 failed observations, 281 verified files, archive SHA-256
`d9d2b91d96d685dee2dea4d294daf162629a6bc6a8e408afcec6ebda1b1f71e2`.
It failed after the narrow transfer omitted the Canadian source registry. The
input-closure repair and a fresh source/run superseded that attempt; its failed
and interrupted evidence was preserved rather than overwritten.

## Compute cleanup and limits

Colab confirmed termination of the task-owned session, no active sessions,
zero active assignments and zero current usage rate. The account balance moved
from 160.86 to 154.41 compute units over the task window, a 6.45-unit account
aggregate delta. The task-owned L4 rate was 1.54 units/hour; the balance delta
is not independently metered task cost. Currency cost was not measured.

Required-task completion, optional usefulness, source-supported answer quality,
material errors, unnecessary abstention and editor-quality benefit remain
unassessed without source-bound review. Automated mechanical success and an
exposed numeric cohort cannot establish agronomic competence, target-user
utility or field efficacy. Integration is complete only after its separately
observed PR CI, merge and post-merge gates.
