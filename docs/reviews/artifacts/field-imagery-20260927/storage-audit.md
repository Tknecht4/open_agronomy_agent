# Field imagery storage audit and bounded lifecycle plan

Status: measured local inventory and design proposal, 2026-09-27. The machine's
reported free space was about **608 MiB** at this audit. No file was deleted,
vacuumed, migrated, or rewritten by the audit. The JSON companion is a
path-free aggregate receipt from `scripts/audit_imagery_storage.py`; its six
explicit input roots were labelled `hls-final`, `hls-previous`, `assessment`,
`eo-env`, `model`, and `public-smoke`. File and hash scans completed under
100,000-file, 20,000-directory, 4 GiB logical-byte, and 2 GiB hash-byte caps.
Symlinks were skipped. Local file paths, scene IDs, field geometry, and payload
hashes are absent from the shareable receipt.

## Observed bytes

| Root role | Logical bytes | What dominates |
| --- | ---: | --- |
| Final HLS cache | 10,047,589 | 23 compressed NPZ chips: 9,106,646 bytes; 23 PNGs: 648,667 bytes |
| Earlier HLS cache | 5,756,009 | 9 chips, receipts, previews, SQLite index |
| Acquisition and assessment outputs | 64,638,564 | 106 NPZ files: 63,283,493 bytes, including retained attempts and copies |
| Optional EO Python environment | 898,188,051 | Dependencies and 59,508,649 bytes of Python bytecode |
| Pinned Prithvi snapshot | 129,354,923 | One weight file: 129,258,736 bytes |
| Public smoke cache | 2,864,404 | Seven earlier public chip artifacts |
| **Combined observed roots** | **1,110,849,540** | 24,554 regular files; 2,043 directories |

The sum of filesystem `st_blocks × 512` was **1,169,068,032 bytes**. It is a
per-file allocation sum, not unique physical space: APFS clones, shared extents,
compression, and snapshot retention were not measured. The optional environment
and model snapshot are local runtime assets, separate from per-field imagery
growth. This inventory excludes unspecified user databases, uploads, global
model caches, node modules, build products, and other projects.

Requested SHA-256 verification found **14,905,451 redundant logical bytes**
across identical whole files, including **8,969,453 bytes** among NPZs. Within
NPZ containers, identical member payloads repeated **184,367,476 uncompressed
bytes**. The compressed member sizes suggest **64,541,492 candidate bytes** of
reuse, of which **61,634,006** are repeated six-band arrays. These two savings
figures overlap and must not be added. Repacking, ZIP overhead, index design,
and APFS sharing determine any physical savings. The receipt records exact
duplicate groups and member categories without exposing payload digests.

The 36 recognized 224×224 context chips had a **708,033-byte median compressed
NPZ**. At four dates per field-season, matching the frozen **model benchmark
stack** rather than a whole-season dashboard, a deliberately naive one-context-
per-season projection is **283,213,200 bytes for 100** and **2,832,132,000 bytes
for 1,000** field-seasons. If 12 management units can reuse the same dated
context, the illustrative figures become **25,489,188** and **237,899,088**
bytes. The latter assumes true common source/grid/date support; it is not a
claim that unrelated farms can share context. Both projections exclude
previews, indexes, private masks, derived features, model/environment files,
source transfer, and retention copies. This cohort had 33 distinct scene IDs
and two distinct geometry hashes in retained chip receipts; recorded COG
payload transfer summed to 84,399,125 bytes, with 37 receipts having unknown
transfer (including invalid or older receipts). Unknown is not zero.
The audit measures whole-file JSON duplication, but does not hash individual
feature vectors nested inside JSON; their incremental reuse is unknown.

## Current duplication outside imagery

`field_data_imports.source_bytes` stores the complete uploaded CSV/XLSX bytes
for each import. `field_data_rows` also retains parsed field rows. Applying 18
field filters to one file can therefore store the raw source up to 18 times,
before row and index overhead. This is a code-path observation; no private
application database was scanned, so its present byte cost is unknown. Raw
uploads and frozen benchmark evidence are source records, not disposable cache.

The public-package builder now attempts APFS `clonefile` and falls back to
`copy2`; its final hash verification remains. That implemented change can
avoid another ordinary roughly-gigabyte data copy on a compatible filesystem,
but this audit did not measure physical clone sharing. It does not replace the
imagery or upload storage plan below.

## Proposed lifecycle and caps (not yet implemented)

1. **Admission and pins.** Keep uploaded source bytes, original checksums,
   committed field mappings, frozen benchmark inputs/results, source receipts,
   and model checkpoint identities pinned. Mark only exact rebuildable imagery
   derivatives as eviction candidates. A signed URL is never a durable source
   artifact. Preserve failed, cloudy, missing and superseded observations.
2. **Workspace-scoped immutable blobs.** Put one raw upload blob per
   `(workspace, source_sha256)` and let each field import reference it with its
   own mapping, admission status and original import ID. Lossless compression
   may be tested, but verify decompressed bytes against the original SHA-256.
   Do not share private blobs or field geometry across workspaces merely to
   improve deduplication.
3. **Separate imagery identities.** Store public HLS source/grid/date/six-band
   pixels once per eligible context within a workspace; keep Fmask and source
   metadata with that observation. Store geometry-bound field weights/masks
   separately by geometry/grid hash, indices and zonal statistics by their
   processing hash, preview PNGs by preview version, and model embedding or
   pooled-token references by pinned model/preprocessing/ROI identity. A field
   view should compose these references rather than copy six bands into every
   field-season NPZ. A broader public-pixel cache needs a separate privacy and
   side-channel review before cross-workspace sharing.
   A future light index-only path could read Red, narrow NIR, SWIR1 and Fmask;
   the frozen encoder still needs all six bands. Changing band selection or
   band-specific QA requires a new processing identity and independent checks.
4. **Quotas and free-space gate.** A candidate policy is a 2 GiB soft and
   4 GiB hard rebuildable-imagery quota per workspace, with an operator-visible
   low-space block when free space is below `max(1 GiB, 2 × the bounded new
   download budget plus temporary write allowance)`. Count reserved in-flight
   transfers, temp files, and retained pins. The observed ~608 MiB free would
   block new downloads under that candidate rule. Evict only unpinned,
   verified-rebuildable least-recently-used derivatives after references and
   active jobs are checked; never automatically delete raw uploads, frozen
   evidence, or model weights. Current benchmark NPZs and receipts remain
   pinned until a versioned resolver and parity-verified migration exist.
5. **Migration without historical rewrite.** Build a sidecar mapping each old
   chip hash and receipt to new source-pixel, QA, geometry-mask, preview and
   feature hashes. Verify old file SHA-256, new blob byte parity, grid/QA/stat
   parity, and reference counts before atomically switching one workspace at
   a time. Retain original NPZs and receipts as pinned evidence through a
   defined review window; no silent rehashing of frozen assessments. The upload
   migration likewise preserves source SHA, import ID, mapping hash and query
   receipt identity while replacing repeated `source_bytes` with blob refs.
   Roll back by the old reference map if any parity check fails.
6. **Shared optional runtime.** Reuse one pinned EO worker environment and one
   read-only model snapshot per installation when compatible; keep those
   dependencies outside the serving environment. Inventory active consumers
   before changing or retiring either. Existing local symlinks already avoid
   some copies; this plan does not authorize cleanup of those targets.

The quota/CAS design requires implementation, migrations, reference tracking,
and failure tests before it can be an operator policy. The measured audit is
read-only evidence, not proof that the proposed savings are reclaimable now.
