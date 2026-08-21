# Canadian offline knowledge inputs

This directory contains manually reviewed semantic companions. Each companion
filename includes its review date, and each source registry record pins the
file's exact SHA-256. Never rewrite a companion in place. A changed review is a
new file and a new source-record binding.

`semantic_companion_recovery_receipt_v1.json` distinguishes five companions
recovered from committed, hash-bound derived rows from companions whose exact
prior byte streams were available. Recovery preserves reviewed row content but
does not claim byte identity with the missing originals.

The active Canadian corpus is one cumulative profile,
`canada-offline-master`, selected by
`data/manifests/curated_canada_offline_master_v1.json`. Its immutable release
payload is under
`data/derived/rag/curated_canada/releases/2026-08-14/`.

## Adding documentation

1. Admit or update the source in `data/manifests/canada_agronomy_sources.json`.
   Keep `use_policy.training` false and verify local-RAG and redistribution
   rights independently.
2. Ingest the source into a source-aware JSONL delta. If a reviewed semantic
   companion is required, give it a new review-dated filename and pin its
   SHA-256 in `ingest_policy`.
3. Add the source ID to the single master profile. Do not create a competing
   core/extended product profile.
4. Build a new immutable dated release. Use the previous master shards plus
   new or replaced source deltas as explicit inputs; never overwrite a promoted
   release directory.
5. Validate the new store, its runtime corpus policy, and focused retrieval
   behavior. Advance the stable runtime config only after those checks pass.

The builder's semantic-rebind option is only for repairing legacy path/hash
metadata. It requires exact title, text, source pages, source ID, and parent raw
hash agreement and cannot be used to change reviewed content.

## Rebuilding the 2026-08-14 release

Run from the repository root into a new, absent output directory:

```bash
.venv/bin/python scripts/build_curated_knowledge_store.py \
  --store-id curated-canada-2026-08-14 \
  --release-date 2026-08-14 \
  --profile-spec data/manifests/curated_canada_offline_master_v1.json \
  --input-jsonl data/derived/rag/canada_agronomy_distributable_v13.jsonl \
  --input-jsonl data/derived/rag/canada_agronomy_ontario_context_v1.jsonl \
  --input-jsonl data/derived/rag/curated_canada/inputs/2026-08-14/mb_2026_crop_disease_scouting.jsonl \
  --input-jsonl data/derived/rag/curated_canada/inputs/2026-08-14/mb_2026_canola_insect_scouting.jsonl \
  --input-jsonl data/derived/rag/curated_canada/inputs/2026-08-14/mb_2023_crop_rotation_context.jsonl \
  --input-jsonl data/derived/rag/curated_canada/inputs/2026-08-14/ab_tame_pasture_range_health_2017.jsonl \
  --output-root /tmp/curated-canada-2026-08-14-rebuild \
  --repository-root . \
  --rebind-semantic-companions
```

Then validate the rebuilt store and its standalone policy:

```bash
.venv/bin/python scripts/validate_curated_knowledge_store.py \
  --store-root /tmp/curated-canada-2026-08-14-rebuild \
  --expect-profile canada-offline-master

.venv/bin/python scripts/audit_runtime_corpus.py \
  --root /tmp/curated-canada-2026-08-14-rebuild \
  --rag-config profiles/canada-offline-master/rag.yaml
```

The rebuilt tree must be byte-identical to the promoted release. The committed
ingest receipt pins every input path, size, row count, and SHA-256.
