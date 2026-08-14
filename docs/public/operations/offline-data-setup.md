# Offline Canadian data setup

The offline package has two intentionally separate layers:

1. The clone contains one cumulative, hash-bound Canadian RAG master. It needs no post-clone download.
2. The optional Prairie map layer is prepared in a user-managed state directory. It contains only the Alberta, Saskatchewan, and Manitoba Detailed Soil Survey (DSS) sources; large gridded products are not part of this setup.

Neither layer turns mapped or regional context into a current field observation, soil test, diagnosis, crop-suitability finding, or management-rate authority.

Geospatial source-catalog status describes catalogue review or external-profile
installability only. It is not proof that bytes are bundled in a public clone.
Installed map bytes are established only by the selected profile manifest,
install receipt, and passing profile validator.

## Verify the clone-contained knowledge store

The current dated release is
`data/derived/rag/curated_canada/releases/2026-08-14/`. It has one cumulative
profile, `canada-offline-master`, and two policy-segregated shards. The master
is a bounded document corpus, not a claim of even Canadian applied-guidance
coverage or current field truth.

From the repository root, verify the generated store before selecting it:

```bash
PYTHONPATH=src .venv/bin/python scripts/validate_curated_knowledge_store.py \
  --store-root data/derived/rag/curated_canada/releases/2026-08-14 \
  --expect-profile canada-offline-master
```

Select the stable product runtime for a native launch:

```bash
export AGRONOMY_AGENT_RAG_CONFIG=configs/rag_governed_runtime_v2.yaml
```

The stable runtime composes the cumulative Canadian master with the project
seed/boundary corpora, SoilWise document and graph context, the project graph,
and the sanitized NRCS compact v2 US-analogue corpus. Every corpus and graph is
explicitly hash-bound. `configs/runtime_profiles.json` is the active/default
registry; merely adding a config file cannot select it.

The generated profile-local
`profiles/canada-offline-master/rag.yaml` is available for an explicit
Canadian-document-only operator workflow. It declares no graph paths and does
not silently inherit the composite runtime. It is not the product default.
Changing the process environment does not alter a running service; restart the
API after setting it.

## Prepare the optional Prairie DSS pack

Choose an empty or dedicated state directory **outside** the Git checkout. The installer has no network side effect unless `--download` is present. Begin with a dry run:

```bash
PYTHONPATH=src .venv/bin/python scripts/setup_offline_data.py \
  --profile prairie-dss-v1 \
  --data-root /absolute/path/to/open-agronomy-state \
  --download --build --verify --dry-run
```

The profile pins the exact official AB, SK, and MB DSS archive bytes, source-registry entries, and the output location. It requires at least 1.5 GB free space. The real one-time setup is the same command without `--dry-run`:

```bash
PYTHONPATH=src .venv/bin/python scripts/setup_offline_data.py \
  --profile prairie-dss-v1 \
  --data-root /absolute/path/to/open-agronomy-state \
  --download --build --verify
```

The default retains verified raw archives so the local build can be audited and reproduced. To retain only the verified runtime databases and their lineage/receipt after the final probe passes, use `--discard-raw-after-build` with `--download --build --verify`. The installer refuses partial downloads, changed bytes, stale lineage, incomplete derived layers, or an invalid existing pack; it does not overwrite them.

After a successful setup, point the application at the exact generated pack:

```bash
export AGRONOMY_AGENT_SPATIAL_PACK_ROOT=/absolute/path/to/open-agronomy-state/spatial-pack/prairie-dss-v1

PYTHONPATH=src .venv/bin/python scripts/verify_prairie_spatial_pack.py \
  --pack-root "$AGRONOMY_AGENT_SPATIAL_PACK_ROOT" \
  --profile prairie-dss-v1
```

The verifier checks the flat pack's hashes, SQLite/RTree integrity, source/derived lineage, and three fixed offline application-path probes. It is evidence of package and map-query integrity, not confirmation of soil conditions at those sample locations.

## Record offline readiness

Build a runtime manifest for the exact selected RAG profile, then validate the clone, local model cache, and—when installed—the external DSS pack without making a network request:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_edge_runtime_manifest.py \
  --rag-config configs/rag_governed_runtime_v2.yaml \
  --output /absolute/path/to/open-agronomy-state/runtime-v2-manifest.json

PYTHONPATH=src .venv/bin/python scripts/prepare_offline_runtime.py \
  --runtime-manifest /absolute/path/to/open-agronomy-state/runtime-v2-manifest.json \
  --model-config configs/model_gemma4_e2b_interface_v2.yaml \
  --rag-config configs/rag_governed_runtime_v2.yaml \
  --spatial-pack-root "$AGRONOMY_AGENT_SPATIAL_PACK_ROOT" \
  --spatial-profile prairie-dss-v1 \
  --require-ready
```

For a RAG-only clone, omit the three spatial arguments. The receipt then records that map queries will return `not_installed`; it does not pretend a national map is available. A passing receipt proves local file presence and hash consistency. Record a separate cold launch with external connectivity disabled before making an operational offline claim.

## Deliberate exclusions and future intake

The following remain uninstalled and cannot be used as hidden fallbacks: national 100 m soil grids, crop/DEM rasters, province/ecoregion boundary packs, SLC vector data, AESD/Census context tables, and university/extension material. The metadata-only [Canadian source-admission queue](canada-offline-source-admission.md) records inspected candidates, source identities, regional uses, and rights gates. It authorizes no download, RAG admission, redistribution, runtime lookup, or fine-tuning.

To add a future document source, update/version its source record and reviewed
companion, produce a source-aware input shard, and build a new immutable dated
master release. Advance runtime v2 and the active registry only after corpus,
rights, hash, and retrieval tests pass. Do not create competing core/extended
masters or edit a released shard, receipt, or pinned source byte in place.

For an already admitted, rights-cleared document source, stage extraction outside the
checkout with the source-aware shard mode. It produces one canonical JSONL file and
one hash-bound receipt per source, plus an index only when every requested source
succeeds; it never creates a combined corpus in this mode:

```bash
PYTHONPATH=src .venv/bin/python scripts/ingest_document_sources.py \
  --manifest data/manifests/canada_agronomy_sources.json \
  --source-id <admitted-source-id> \
  --use-case distributable_bundle \
  --output-mode source-shards \
  --raw-dir /absolute/path/to/intake/raw \
  --shard-dir /absolute/path/to/intake/shards \
  --receipt-dir /absolute/path/to/intake/receipts
```

That staging output is evidence for a separate curated-store release build; it does
not itself admit a source to runtime retrieval, a portable bundle, or a training
dataset. Start with `--dry-run` to inspect selection without downloading anything.
