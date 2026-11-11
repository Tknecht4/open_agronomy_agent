# Grower answer completion review

November 11, 2026.

All 15 previously incomplete answers now complete their requested task in a
bounded, source-referenced automated review. All 33 review-required answers in
the repeated 50-case assessment are marked complete, preserving the original
18 complete answers. Eight additional exposed paraphrases are also complete.
These are product-answer completion observations. Human agronomic review and
field validation remain pending.

The original gaps are retained in the
[PR 129 assessment](pr129-terrain-agronomy-assessment-20261111.md). A fresh main
baseline at `0cacde7` reproduced all 50 original answers exactly, allowing the
original reviews to be rebound only after case and answer hashes matched.

## Grower-facing changes

The repair preserves useful next observations when a consequential action lacks
evidence or authority. It does not supply a pesticide rate, diagnose from a map,
or turn a general method into locally calibrated guidance.

| Workflow | Completed explanation or next check |
| --- | --- |
| Paired scouting and yellow crop after rain, two answers | Compare patch margins and representative normal areas, inspect intact roots/crowns and soil moisture, keep samples separately labelled and revisit marked locations. |
| Collapsing potato tops | Keep late blight and lookalikes in the differential, inspect foliage/stems/roots/tubers and seek prompt local diagnostic advice before a spray decision. |
| Suspected clubroot | Separate suspicion from confirmation, limit soil movement and explain that one nonhost year does not eradicate persistent spores. |
| Unspecified herbicide rates, two answers | Recover crop/weed stages, identity, pressure, product, application and resistance history; include conditional nonchemical options. Pesticide questions no longer inherit fertilizer soil-test and yield-goal demands. |
| Flowering peas with edge aphids | Sample representative interior and edge locations with matching units, trends and beneficial counts; retain current threshold, label and pollinator restrictions. |
| Regional anomaly and tomorrow's spray | Distinguish the regional reference period from near-application field weather, with on-site wind, inversion, rainfast and label checks. |
| Crop-health map and nitrogen or blueberry disease, two answers | Preserve the non-specific regional signal, compare plants/roots/water and alternative causes, and require field evidence before diagnosis or changing inputs. |
| Vegetable table and haskap | Answer the perennial-fruit scope question, include mature layout/access and pollinizers, and avoid transferring vegetable rates. Haskap/honeyberry identity now excludes the incompatible vegetable/potato live reference. |
| One water EC/SAR sample | Repeat source-water and root-zone tests as conditions change; interpret EC/SAR jointly with soil, infiltration, stage, uniformity and drainage. |
| NDVI decline | Check QA, valid coverage, comparable spatial support/processing and crop stage before attributing a difference to crop condition. |
| One GPS pin and area | Require a closed planted boundary or both dimensions of a known shape; a scale or one distance alone is insufficient. |
| Empty terrain clip | Distinguish true absence from missing coverage, check source parcel coverage/acquisition age and ground-truth current field conditions. |

The [field observation guide](../public/operations/field-observations.md) links
the public method sources and their applicability limits. No evaluation
questions, references or reviewer labels were admitted to runtime retrieval or
training. The serving model pins, generation budgets and active corpus remain
unchanged.

## Underlying defects and verification

The initial composed candidate passed its execution checks but still had four
incomplete answers in the 33-answer review, and two incomplete paraphrases.
Those negative observations are retained. Direct answer inspection found:

- correct coverage words appended to an unsupported low-risk terrain inference;
- a boundary instruction appended to a false one-dimensional area claim;
- legitimate `source-water samples` prose mistaken for an internal source ID,
  causing the rendered water explanation to disappear; and
- an unrecognized crop name allowing a mismatched live vegetable guide.

Six focused regression cases failed before those repairs. The new checks reject
the concrete contradictions, preserve ordinary water-sampling prose while still
detecting real identifiers, and use canonical crop identity for compatibility.
Incomplete bounded methods can select a reviewed procedural answer before model
editing, subject to normal safety and requested-record preservation checks.
Complete answers retain the existing risk thresholds. These lexical checks do
not constitute a general scientific correctness verifier.

| Retained execution/review | Completed cells | Automated required-task completion |
| --- | ---: | ---: |
| Fresh main baseline | 50/50 | 18/33 |
| Initial composed candidate at `3d0d877` | 50/50 | 29/33 |
| Final candidate at `c6d6134` | 50/50 | 33/33 |
| Initial exposed paraphrases | 8/8 | 6/8 |
| Final repeated paraphrases at `c6d6134` | 8/8 | 8/8 |

The maintained release runner exercised `execute_agent_request` with isolated
synthetic records and retained persisted answers and stage receipts. Both final
runs report `smoke_complete`, `source_stable: true`, zero failed or missing cells,
zero failed execution checks and six passing foundation components. The nine
numeric contracts passed **9/9**. All original case hashes matched the baseline;
34 of the 50 final answers were unchanged, and the one additional changed
previously complete pest answer retained its requested task.

The executed runtime source commit was
`c6d6134bf056feffeb29a10f79972fed9710b7b7`, with source fingerprint
`af82a59749e9ce41ca654c8660e4815c3ba1c1fe199ce31977d8519d7ce0775c`.
The pinned native MLX model was `mlx-community/gemma-4-e2b-it-4bit`, revision
`238767527555cb75a05732a84dff5d6ba0dd6809`; the active model configuration SHA256
was `02311ba0dca40e33abf0efa396c7f17593d87b42a4f01d8c2e0af786f1fa8946`.
A subsequent scope guard keeps satellite pixel and declared buffer footprints
on their existing sampling-support interpretation path, rather than applying
the bare field-pin method. Two reproduced selector regressions cover that
boundary. The completed study above remains bound to `c6d6134`; subsequent
current-source confirmation and exact-head checks are retained with the PR.

Local verification passed 3,776 backend tests with 58 skips, 607 focused
source/context/renderer regressions, and 505 frontend tests plus typecheck and
build using Node 24 and an existing dependency tree matching the lockfile.
Public scope checks and strict documentation checks passed. PR CI supplies a
separate exact-head source gate; its terminal results are recorded with the PR.

## Interpretation and retained limits

All 15 repaired answers were delivered through existing authority holds or
reviewed procedural fallbacks: six deterministic holds and nine verifier
fallbacks. This improves what the grower receives when evidence is missing; it
does not demonstrate improved parametric agronomic reasoning.

The canonical analyzer binds the reviews as `automated_triage`, with zero human
expert labels, and excludes them from qualified semantic metrics. It retains
`domain_status: review_pending`. Three original source-support labels and one
material-error label remain unknown. Required-task completion is distinct from
scientific accuracy, diagnosis, current product authority or field efficacy.

The questions and paraphrases are exposed development cases, including repeated
cases used during repair. They are not an independent holdout. Concurrent local
testing and small performance samples do not establish a latency improvement.
An installed native release and real-farm outcomes remain separate qualifications.

Private artifacts retain original raw answers, the exact review bindings,
controller-only references and criteria, source rationale, negative and
interrupted attempts, test logs and current-source receipts. Earlier reports and
numeric scores were not rewritten or silently rescored.
