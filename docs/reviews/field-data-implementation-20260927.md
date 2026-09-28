# Field data pilot implementation

Active implementation record. Base: `7c502d8065a46c14c6abb462833509e5b598f2f8`; branch `codex/field-data-pilot`.
The preceding [research plan](field-data-benchmark-research-20260927.md) and its receipts remain unchanged historical evidence.

## Goal and boundaries

Implement the first usable upload→review→persist→query→trace loop, a repeatable real-data development benchmark, and account-free imagery access. Earth Engine/HLS is an optional account-backed provider, not a prerequisite. Preserve observations/model products/interpretations, exact row lineage and rights. The larger acquisition cohort, EO predictive-model qualification and training remain gated stages, not implicit outputs of this pilot.

Working state: existing field library/events, typed production execution core, local SQLite/object store and inspected small real datasets are the foundation. Raw evaluation answers never enter runtime/shared retrieval. User files remain workspace-authorized. No new paid compute, model download, or external messages. Current disk free is approximately 700 MiB, so use bounded downloads, serial tests and an APFS-cloned temporary package; no bulk data copies or deletion of unrelated files.

Resource estimate: owner plus independent parser/storage, imagery and UI workers; integration, focused/full verification and one independent review. First checkpoint is a complete vertical slice, estimated 60–100 minutes including repairs; not a hard user budget. Reassess optional scope at failures or disk pressure. Billing unavailable. The primary checkout is reused because no suitable attached worktree exists and a second full data checkout would exceed free disk; file ownership is explicit and pre-existing research/UI plans are preserved.

## Integration contract

All field routes below use existing demo-field workspace authentication/authorization. Unknown or deleted fields fail; requests never choose another user's workspace.

- `POST /api/demo/fields/{field_id}/data/preview`: JSON `{filename, base64_content, encoding?}`; bounded bytes. Returns `{import_id, status: 'preview', profile: {filename, content_sha256, columns: string[], row_count, preview_rows: object[], encoding, delimiter, warnings}, mapping_suggestion}`. Preview stores source bytes privately but does not make them answer-visible.
- `POST /api/demo/fields/{field_id}/data/{import_id}/commit`: JSON `{mapping}` where mapping is `{filters: {column: exact_string}, record_key: string[], columns: [{column, label, unit: string|null, role: 'measurement'|'context'|'identifier', aggregation: 'none'|'mean'|'sum'|'unique', evidence_role: 'observation'|'model_output'|'interpretation'|'regional_prior'}], source: {title, url?, license?, citation?}}`. Filters must be explicit before binding a multi-field upload. Source metadata is user-asserted, not a rights approval. No guessed unit/method/date interpretation. Return `{import: manifest}`. Exact repeated commits are idempotent; changed mapping requires a new preview/import, preserving earlier snapshots.
- `GET /api/demo/fields/{field_id}/data`: `{imports: manifest[]}` (committed only).
- `POST /api/demo/fields/{field_id}/data/{import_id}/query`: `{operation: 'rows'|'count'|'mean'|'sum'|'unique', column?, filters?, limit?}`. Only committed imports, bounded outputs, declared compatible aggregation, exact locators, missing/invalid counts. No silent summing of repeated field-level values. Return the deterministic query receipt.
- `GET /api/imagery/providers`: source/access/license/capability inventory; anonymous providers first. No personal credential values exposed.
- `POST /api/demo/fields/{field_id}/imagery/search`: `{provider_id, start_date, end_date, limit?}`. Stored polygon required; explicit network mode controls; returns bounded STAC scene metadata, dates, assets, license/access and limitations. Search is not cloud-free field coverage or an imagery diagnosis.

Core parser/storage worker owns `field_data.py`, `server/storage/field_data_store.py`, minimal initialization in `server/storage/db.py`, and focused tests. Functions exposed by the standalone store: `preview_import(store, field, actor_id, filename, content, encoding=None)`, `commit_import(store, field, import_id, mapping)`, `list_imports(store, field_id)`, `query_import(store, field_id, import_id, query)`, `field_data_snapshot(store, field_id)`; these use the existing TraceStore SQLite connection/lock. Snapshot is bounded and source-hashed; full tables never enter a prompt or public trace.

Owner owns API wiring, conversational capability integration, benchmark/CLI, public manifest/docs and integration checks. Frontend worker owns a separate `FieldDataPanel` component/tests and its narrowly scoped mount in `OpenAgronomyApp.tsx`; imagery worker owns `field_imagery.py`, imagery tests/CLI and provider research receipt. Workers do not edit each other's files.

## Acceptance map

| Obligation | Observable failure | Required evidence |
|---|---|---|
| Real upload works | Preview-only text chunks, lost rows, no persisted field association | CSV/TSV and supported XLSX parse, reviewed mapping, reload and API test |
| Source meaning preserved | Ambiguous units guessed; repeated rates summed; wrong-field rows imported | Explicit mapping/filter/aggregation controls, locators and negative tests |
| Private/atomic/idempotent | Cross-workspace reads, partial commit, duplicate application | API/store authorization, rollback and retry tests |
| Conversational integration | Imported evidence absent or unregistered bespoke arithmetic | Registered selection/execution receipt, final source-bound result and production trace test |
| Real-data benchmark | Golden answers loaded into runtime or synthetic-only score | Split-safe sample manifest, isolated inputs/scorer, retained cases and trace IDs |
| No account imagery | Personal credentials silently required or metadata called pixels | Live anonymous catalog check and bounded asset read when feasible; explicit optional requirements |
| UI usable | Unreviewed auto-commit or fabricated availability | Accessible upload/review/import/query controls and focused UI tests |
| Honest qualification | Tests or embeddings claimed as field/model quality | Explicit pilot scope, measured vs proposed results, independent review |

## Progress

The first vertical slice is implemented and independently accepted after repairs.
No source or model was admitted for training and the reference RAG corpus is unchanged.

- Intake: CSV/TSV and one-sheet XLSX; explicit encoding, field filters and units;
  private raw bytes; row/source hashes; immutable, idempotent reviewed commits.
- Column mapping additionally supports `value_scope=record|field_season|unknown`.
  Sums require record scope plus a unique nonempty row key. Field-season values
  cannot be averaged or summed. Identical numbers alone never establish grain.
- Conversation: registered field-table capability consumes a server-authorized
  bounded snapshot. Incomplete import indexes require exact import identity;
  incomplete column indexes cannot silently resolve aliases. Table results
  retain source/query identities through final rendering and the 17-stage trace.
- UI: named fields may have no location. Browser verification exercised a real
  Akron fixture through upload, review, commit, reload and a 13-row yield mean
  of 567.7894685731263 kg/ha. The result remains a sample-location mean.
- Imagery: anonymous Earth Search C1 Sentinel-2 and Planetary Computer HLS
  S30/L30 discovery and 16 KiB TIFF range probes passed. GEE remains optional,
  unconfigured and unnecessary for these access paths. Raster decoding, QA
  masks, seasonal anomaly analysis and prediction are not implemented here.
- Benchmark: 24 dependent bundles from two U.S. sources; 96 reviewed query
  contracts passed, 72 exact product-result bindings passed, 24 semantic state
  questions retained unscored. Mock generation and exposed development inputs
  do not establish model or agronomic quality. The broader Canadian/site cohort
  remains a future acquisition milestone.

The normalized pilot is deliberately a reviewed-table contract. Opaque stored
field ID plus explicit source-field/season/plot columns and exact filters bind
identity. Units, value scope, roles, source hashes and original row locators
are explicit. Sampling methods, dates, depths, planned/completed status and
experimental design remain source columns unless separately covered by the
existing typed soil-test envelope; they are not yet a complete agronomic
ontology. Reference-method cards should identify missing method/crop/season
facts instead of inventing them, and remain distinct from uploaded observations.

## Verification and retained failures

- Final reviewed Python suite: **1,093 passed**. Full frontend: **210 passed**,
  typecheck and production build passed. Strict MkDocs, public-document audit
  and active runtime corpus audit passed. Final package evidence is retained
  under `outputs/field-data-pilot-validation/`.
- The new benchmark reproduced a real sanitizer defect: a valid JSON array
  containing the crop value was removed as an evaluation regex. The repaired
  guard permits valid data arrays while still detecting evaluation markers,
  character classes and quantifiers. The earlier failed trace was retained.
- Independent review found and verified repairs for hidden ambiguity in
  truncated snapshots, finite-input aggregate overflow, malformed XLSX errors,
  and stale UI follow-up binding. The follow-up now uses the displayed receipt,
  not mutable query controls.
- An initial full-suite run put temporary data inside the checkout and caused
  12 path-policy failures, plus two package/catalog integration failures.
  The corrected run used a task-owned temporary root outside the checkout;
  manifest and generated catalog wrapper were fixed. Logs remain retained.

## User-requested ignored-output cleanup

The audit found verified duplicate copies of historical RC3 and successor
benchmarks. On APFS, 455 originals were atomically replaced by copy-on-write
clones of their exact retention copies. Every original path and SHA-256 was
preserved, with independent inodes; no benchmark record was deleted. Observed
free-space increases across the two operations totaled 1,294,225,408 bytes
(about 1.21 GiB), subject to concurrent filesystem activity. Retention bundles,
completion receipts, active model/dependency caches and potentially installed
spatial assets were preserved. The temporary 1 GiB public-package copy generated
by this task's failed test run was also removed after its log was retained.

Reproduction and cleanup receipts: `outputs/maintenance/20260927-field-data-cleanup/`.
Independent review: [implementation-review.md](artifacts/field-data-20260927/implementation-review.md).

Changed | First field-data pilot, anonymous imagery access, development benchmark,
operator docs and evidence-preserving storage compaction.

Verified | Tests and measured results above; source-bound validation artifacts.

Residual Risk | Small dependent U.S. cohort, user-asserted mappings, bounded table
grammar, one-sheet workbooks, unscored semantics and future raster/model stages.

Memory Delta | None.
