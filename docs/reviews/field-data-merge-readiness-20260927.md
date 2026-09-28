# Field data and imagery merge closure

User authorization: complete the next steps/residuals, obtain review, then
merge PR 9. Reference research head `8c77e70`; latest main is `0a942a3`,
including map/field insights and desktop deployment. Earlier research,
source catalogs, failed attempts and model scores remain frozen evidence.

## Scope and checkpoint

Expected effort: owner plus bounded storage/source-preparation specialists and
an independent final reviewer, approximately 60–100 minutes. First checkpoint
is integrated focused tests; final checkpoint is the reviewed candidate,
full verification ladder and merge. Monetary usage is unavailable. No new
model training, imagery acquisition, paid job or bulk dataset download.
Reassess optional scope if effort grows; never convert missing evidence to a
pass to meet the estimate.

| Residual | Merge closure and evidence |
|---|---|
| Latest UI/deployment integration | Rebase preserving current map/insights, data-only fields, calculator/seed contracts and desktop defaults; focused then full checks |
| Repeated raw uploads | Workspace-scoped compressed source blobs, byte-hash verification, explicit reversible migration of existing inline imports; unchanged query/manifest identities |
| Unbounded imagery cache growth | Operator-configured cache and free-space admission before egress/new writes, concurrent reservation and typed refusal; cached reads still work; no automatic eviction of evidence |
| New dataset ingestion | Hash-pinned preparation of Canadian beans/onions and Arkansas soybean tables into reviewable tables/group manifests, original-row lineage and explicit row dispositions; no formula execution or guessed geometry |
| Dataset utility | Import representative prepared groups through the existing reviewed product path, verify deterministic questions/receipts and show fields in an isolated local UI workspace |
| Unresolved source facts | Keep uncertain group identity, date conflicts, modeled/derived values, missing geometry and restricted sources held with concrete reasons; never silently repair observations |
| Historical raster duplication | Retain frozen NPZ/receipt references. Pixel-block CAS/eviction requires a separate resolver/reference migration; admission caps make current growth bounded without deleting history |
| Release | Update documentation/manifests, run public package and relevant desktop/optional-worker checks, independent source-bound review, green remote checks, then merge the tested head |

The operational improvements do not expand the one-farm imagery-accuracy
claim, convert plot counts into farms, grant dataset rights, or admit gold
answers into runtime/training. Newly prepared records remain a reviewed
source-only development lane, separate from frozen evaluation questions.

## Integrated closure evidence

- Rebased onto main `0a942a3`, retaining its map/field-insight and desktop
  implementation. The sole frontend integration repair updated an existing
  data-only map assertion to main's current "No location selected" wording.
- Prepared 85 source study groups and 4,008 rows from seven pinned originals
  and dictionaries. Independent review compared 60,417 selected source cells.
  Groups remain research partitions with unknown geometry, not farms.
- The final offline HTTP rehearsal imported nine representative units and
  exercised nine deterministic answers with all 17 production stages, explicit
  count/mean receipts and outsider authorization denials. A Picketa mean stayed
  a clarification. Failed development attempts and source/column-scope guards
  are retained in the [rehearsal record](artifacts/field-data-merge-20260927/product-rehearsal.md).
  A live UI check then exposed four erased answers despite correct tool
  receipts: the leak guard treated literal `source_*` columns as internal IDs.
  Exact replay against separately authorized stored context now preserves these
  names while genuine prompt/evaluation leakage remains detectable. Run 08
  verifies the actual HTTP, structured and persisted answer against the exact
  registered payload for all nine groups; runs 06/07 retain their invalidated
  complete-answer claims and rendering-failure audits.
- Nine imports use six verified source blobs: 1,004,085 bytes if repeated raw
  sources were stored independently, 321,858 unique raw bytes and 235,890
  compressed payload bytes. These are logical payload sizes, not measured
  physical SQLite/APFS space reclaimed. Existing databases are not silently
  migrated or vacuumed.
- Full integrated Python after the rendering repair: 1,317 passed, two skipped; optional EO: 89 passed;
  frontend: 281 passed plus typecheck/build. Public docs, strict MkDocs, runtime
  corpus and 96 pilot cases passed. The pilot retains 72 exact product bindings
  and 24 unscored semantic cases. See the
  [source-bound verification receipt](artifacts/field-data-merge-20260927/verification.json).
- Restarted the configured native preview and reused the existing public
  June 12, 2021 HLS scene offline through the updated Fields UI. It displayed
  the authenticated field-only preview, NDVI 0.337 and NDMI -0.068 with a
  cached marker. No additional imagery acquisition occurred.

The independent [closure review](artifacts/field-data-merge-20260927/review.md)
retains the initial repair findings and their verification. Final public
packaging, exact candidate Git identity and remote CI are release gates; their
live outcomes belong to the PR. The local native Mac binary was not rebuilt
with less than its required 8 GiB free scratch space. Desktop source contracts
passed locally; the remote Mac candidate workflow must pass before merge.

Remaining scientific and source-rights holds are substantive: the one-farm
imagery comparison is exploratory; overlapping contexts, unresolved source
datum and retrospective availability prevent broad accuracy claims. New source
licenses and missing geometry are not repaired by ingestion. Pixel sharing
across old raster references remains a separate migration; configured capacity
admission now bounds cooperating writers without deleting historical evidence.
The later, unbound phase5 audit remains conservative: it can flag a literal
`source_*` column as `raw_source_id` even after the validated renderer preserves
it. These flags are known false positives in this rehearsal and must not be
interpreted as confirmed prompt leakage or counted as a clean leak-rate result.

## Subsequent UI merge integration

Before release, UI PR 12 advanced main to `210c553`. The field-data branch is
rebased onto that change. Named field-sync/soil-entry exports, the compact
history-first records layout, modal draft recovery and progressive map insights
remain intact; the table and imagery disclosures sit within the updated field
timeline. The integration continuation is bounded to relevant replay, full
local gates, renewed independent review and remote CI, approximately 15–30
minutes including CI. No source acquisition or new scientific experiment is
included.

Table imports retain source dates as literal source columns and original-row
lineage; they do not create typed soil events or treat import/commit timestamps
as sampling dates. The new event path keeps unknown/user-supplied sampling-time
provenance separate from event/recorded timestamps and requires matching,
timezone-aware `sampled_at` for a known sampling time. Date-only research values
and partial windows must not be promoted into that event contract by guessing a
time or timezone. Earlier successful runs remain evidence for their recorded
base; the final integration receipt and PR checks bind the later candidate.

On the PR 12 base, the full Python suite passed 1,328 tests with two skips;
frontend typecheck, all 289 tests and the production build passed. Public docs,
strict MkDocs, all 96 pilot cases and nine complete source-answer bindings
passed again. The [integration receipt](artifacts/field-data-merge-20260927/pr12-integration.json)
binds the current source bytes and keeps earlier results attached to their
original bases. Optional EO source modules are unchanged from their 89-test
verification. Remote checks must run against the final rebased head.

## SQLite concurrency repair and final main

The live browser mounted field history, tables and imagery concurrently. A
bounded reproduction returned 32 successful responses, two 500 errors, one
incorrect 403 and one incorrect 404 from 36 requests; sequential requests all
succeeded. Independent tests reproduced cross-thread transaction interference
and a separate first-workspace creation race. Earlier sequential test passes do
not establish concurrent request correctness.

The local SQLite store now holds one reentrant connection lock through cursor
creation, execution and transaction finalization. Nested cursors cannot commit
an outer write, and a swallowed nested failure makes the outer transaction
rollback-only. Commit failures roll back before connection reuse. SQLite
personal workspace creation encloses its lookup, organization and workspace
in one transaction. Postgres continues through its separate existing backend;
this fix does not establish new Postgres or multi-process authentication claims.
Database work is serialized per local connection, not whole agent/model runs.

The final base also includes PR 13 at `7d6f1bd`, which only wraps field-insight
controls in narrow panes and updates the generated inventory. Original research
payloads, prior failed receipts and earlier databases remain retained. The final
concurrency receipt, renewed review, live requests and remote checks must bind
the completed repair before merge.

Final local verification passed 1,337 Python tests with two skips, 289 frontend
tests plus typecheck/build, all 96 pilot cases and nine exact source-answer
bindings. The real preview returned 96/96 successful concurrent reads with the
correct import identities; its table query and offline cached HLS result were
also checked in the browser. The low-disk fixture failure is retained and fixed
by controlling test free-space input, without changing runtime admission.
The [final integration receipt](artifacts/field-data-merge-20260927/sqlite-final-integration.json)
binds source hashes, tests, live checks and content-addressed retention of four
redundant package copies. Remote checks and final package identity remain
release gates, visible on the PR.
