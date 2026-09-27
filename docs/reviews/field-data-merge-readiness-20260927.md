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
