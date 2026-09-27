# Field imagery analytics and label assessment

Active implementation/research record. User requested imagery analytics, use
of local spatial data, and measured task accuracy from the real field labels.
The UI merge `fd590b57babca0666e24286315ec460877a59dac` is verified; its tree
matches reviewed tip `3cfaabd39df5bdc9a9f55f35dbc96a4b8f3bbde8`.
The first field-data slice is preserved at checkpoint `0b967a9` and its old
checkout/preview remain separate from this managed worktree.

## Working state and resource checkpoint

Goal: preserve the pilot on current main; implement bounded anonymous HLS
chips/QA/indices, a local spatial imagery catalog, and a source/split-bound
exploratory accuracy assessment with a small frozen EO encoder where feasible.
Keep measured labels, regional priors, model features and predictions distinct.
Integrate the result into the new Data/Fields UI after the backend contract is
verified. Produce a reviewable PR; do not merge or publish models.

Resource estimate: owner plus bounded specialists for imagery acquisition,
spatial/label protocol and local model inference, with a UI integration worker
and independent final reviewer where useful. Initial envelope 90–150 minutes,
at most 1 GiB new imagery/model artifacts before reassessment, CPU/MPS batch 1,
no paid/cloud jobs and no language-model fine-tuning. Use a separate optional
EO environment; do not replace serving dependencies. Pricing/total provider
usage is unavailable. Reassess at cohort, live-chip and model-forward gates;
reduce optional scope on data/device failure while preserving failures.

## Frozen initial scientific constraints

- Raw Akron source: SHA-pinned inspected CSV, 721 rows, 18 management units,
  2019–2022, wheat/corn/millet. Targets are yield-monitor derivatives extracted
  at sampled locations, not area-weighted field harvests.
- Exclude **all years** of S2, S3, S4, S5, S6 and S7 from any learned readout:
  those physical units already supply the exposed field-QA benchmark. Remaining
  candidate cohort: 575 rows, 12 management units, 29 field-seasons, one farm.
  Raw observations, never QA questions/answers, are the only potential labels.
- First label-supported tasks: crop identity and prediction of the mean yield
  at sampled locations for a management-unit/season. Stress, disease, N-status,
  optimal rates and field-harvest yield lack suitable labels here.
- Compare majority/crop-mean and simple spectral/tabular baselines against a
  **frozen** EO representation with a small fixed readout. Never call a generic
  embedding an agronomic prediction or use its pretraining score as our result.
- Assign complete physical units to groups before feature inspection; report
  grouped held-out results and crop strata. A separate forward-year contrast
  has a different estimand. Pixels, sample rows and repeat dates are dependent.
- Use only acquisition dates at/before each declared cutoff. Historical product
  publication times may be unknown: qualify retrospective acquisition-cutoff
  experiments rather than claim an operational historical forecast.
- Freeze metrics (crop accuracy/balanced accuracy/macro-F1; per-crop yield
  MAE/RMSE/bias and skill against training-only crop means), failure denominators,
  preprocessing and fixed hyperparameters before the model comparison. No
  test-driven tuning or threshold selection; retain failed/missing predictions.
- Resolve source CRS/methods where possible. A hull or buffer of sample points
  must be labelled sampled support/research AOI, never installed as a surveyed
  field boundary. The Canadian soil databases have no Colorado coverage.
- Existing soil/terrain/context SQLite assets remain read-only priors. Add an
  independent versioned imagery/feature index with geometry/time/source hashes,
  QA coverage and model lineage rather than rewriting historical map evidence.

## Acceptance gates

1. Rebase preserves data-only fields, authorization, registered table queries,
   the updated UI/race fixes and the original source/evaluation separation.
2. Chip processing proves projection/window/band/scale/nodata/QA/mask behavior
   with fixtures and a bounded live anonymous read; buffers do not enlarge
   reported field statistics. Actual transfer/latency/memory are measured or
   explicitly unavailable.
3. Cache reuse binds source/item/band/geometry/time/processing hashes; unknown
   coverage and gaps stay visible. No SAS token or credential is persisted.
4. Label/covariate roles and physical-unit splits are frozen and auditable;
   source CRS and label support limitations remain attached to every metric.
5. A local model result requires pinned code/weights/preprocessing, observed
   device and shape, finite outputs and resource receipts. MPS failure with
   successful CPU fallback remains an MPS failure.
6. UI separates observed indices, priors and experimental predictions; stale
   requests cannot display a previous field's data. Final tests, review and
   package checks control the integrated PR claims.

## Implemented result and retained findings

The local imagery sidecar has a SQLite RTree over chip footprints, exact
geometry/request/scene/processing identities, QA, and source metadata. Its
private raster cache verifies NPZ, PNG and receipt hashes before reuse. Existing
Prairie soil databases stay read-only regional priors; none covers Akron.
The optional EO subprocess is configured by the operator, receives no inherited
Google/Hugging Face credentials, and returns field-authorized results to the
new Fields workspace. Offline mode reuses exact verified chips. Changed saved
boundaries invalidate an in-flight result and its preview.

The approved public-data transfer produced four-date native HLS contexts for
2020–2022. All 29 seasons retain dispositions; eight 2019 cases had no catalog
scenes in the frozen window. Observed COG payload was 83,182,141 bytes including
superseded attempts; the conservative reservation tally was 161,913,592 bytes.
The authenticated production API separately processed a 25 × 26 chip in
22.52 seconds, transferred 786,432 bytes and served a verified PNG. The browser
then displayed the same result offline: NDVI 0.337 and NDMI −0.068 for the
public research support. It is not a surveyed field or a diagnosis.

The [paired assessment](artifacts/field-imagery-20260927/paired-primary-assessment.md)
reports fixed spectral crop accuracy 20/21 versus frozen Prithvi 8/21 and
training-majority 12/21. Across all 29 eligible seasons, counting missing
imagery as unsuccessful, these EO results are 20/29 and 8/29. Prithvi produced
three exact-vector alias groups spanning different crops. Its final MPS
extraction peaked at about 512 MiB RSS with zero observed swap growth; this
does not measure simultaneous operation with the language model. No model
was promoted into production yield prediction or fine-tuned on QA answers.

Important limits remain in the receipts: one farm and overlapping imagery
contexts; unknown historical publication time; retrospective sample support;
unresolved source datum and a narrowly reviewed HLS numeric-grid assumption;
material support changes under 15/30 m shifts; unstable millet regression;
and unexplained numerical warnings despite independent arithmetic checks of
the reported predictions and Ridge solutions. The warnings and negative
yield predictions remain retained.

Independent implementation review found and repaired undefined-NDVI preview
coloring, concurrent byte-budget reservation, projected-metre grid validation,
and saved polygons whose derived acreage was absent. Native-v2 scientific
arrays remain unchanged; corrected previews have a separate version and cache
identity. The old v1 and partial-v2 attempts remain historical failures.

## Validation resource checkpoint

The first integrated Python run was interrupted after 652 passes, one skip,
two failures and two setup errors when a concurrent project validation filled
the disk. Those errors were SQLite disk-full/open failures, and the full log
is retained under the ignored imagery-validation output. This is not a pass.
The clean retry and final release checks are recorded in the validation receipt.
SHA-verified APFS copies recovered about 1.03 GB in the managed corpus and
1.02 GB in an existing project package while preserving every path, byte hash,
timestamp and independent inode. No historical benchmark or acquisition
receipt was deleted. No paid compute or remote model job was used.

The clean full Python run passed 1,150 tests with two optional skips. The
isolated EO suite passed 39 tests; frontend passed 267 tests plus typecheck
and build. The later storage/package delta passed all 14 affected tests.
Public docs, strict MkDocs, active corpus audit, live API/PNG and offline
browser reuse passed. Exact logs, warnings and limits are bound in
`artifacts/field-imagery-20260927/validation.json`.

## Storage optimization checkpoint

The user requested a deliberate local storage design. The read-only bounded
audit measured 1,110,849,540 logical bytes across six explicit roots, dominated
by the optional environment and model snapshot. It found 61,634,006 candidate
compressed bytes of repeated band payloads inside NPZ files. The larger
member-level candidate and whole-file duplicate totals overlap; they are not
additive physical savings. APFS extent sharing remains unknown to `st_blocks`.

Implemented now: a bounded audit that never follows symlinks, canonicalizes
and rejects overlapping roots, refuses existing/in-root output destinations,
and records incomplete work; plus independent APFS copy-on-write public-package
builds with ordinary-copy fallback and unchanged hash verification.

The [storage lifecycle plan](artifacts/field-imagery-20260927/storage-audit.md)
proposes workspace-scoped raw source blobs shared by field mappings, reusable
scene/grid/band pixels with separate field masks and results, reference-aware
cache quotas, low-free-space admission and eviction only for unpinned
rebuildable data. These require migrations and are not active policies.
Frozen benchmark inputs, source uploads and historical receipts stay pinned.
