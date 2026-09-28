# Local frozen Prithvi EO probe

Observed 2026-09-27 UTC. Technical inference evidence only; no yield/crop accuracy claim.

## Identity and execution

Model `ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL`, revision `335eadc2c45ad5abe7bd307223e1c48c5b60c41b`. Official card declares Apache-2.0; `prithvi_mae.py` contains IBM's Apache-2.0 header. No repository LICENSE file was listed. Card, config, inference and model code were inspected before import. Public files were downloaded anonymously with `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`; no credentials or HF writes. Code/config/weight SHA-256 allowlist is enforced before import and `torch.load(weights_only=True)`. Only the 5,634,050-parameter encoder is instantiated; decoder weights are read from the full checkpoint and discarded. Parameters are frozen, eval mode, inference mode. No TerraTorch training stack, GGUF or MLX conversion. No serving profile changed.

Primary sources opened exactly (no search query expansion):
- `https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL/raw/main/README.md`
- `https://huggingface.co/api/models/ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL` (web open failed; authenticated-free HF CLI metadata succeeded)
- `hf models info ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL`
- `hf download ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL README.md config.json inference.py prithvi_mae.py requirements.txt --revision 335eadc2c45ad5abe7bd307223e1c48c5b60c41b --local-dir outputs/prithvi-tiny-tl`
- Same revision-bound command for `Prithvi_EO_V2_tiny_TL.pt`.

Model/card source: [pinned card](https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL/blob/335eadc2c45ad5abe7bd307223e1c48c5b60c41b/README.md), [pinned inference](https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL/blob/335eadc2c45ad5abe7bd307223e1c48c5b60c41b/inference.py), [pinned encoder](https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-tiny-TL/blob/335eadc2c45ad5abe7bd307223e1c48c5b60c41b/prithvi_mae.py).

## Input interpretation and limitations

Six ordered bands: blue, green, red, narrow NIR, SWIR1, SWIR2. Four distinct chronological acquisition dates, each at/before explicit cutoff. Shape `[1,6,4,224,224]`; float32. Source reflectance is scaled by `.0001`, while config means/stds use raw HLS DN-scale values. Adapter scales those statistics by `.0001` before normalization. This resolves a discrepancy between card prose ('reflectance units') and config/inference numeric statistics; feeding 0–1 reflectance directly against means around 1000 is incorrect.

Official inference replaces raw `-9999` with normalized `.0001`; adapter extends this documented sentinel to QA-invalid cloud/fill pixels, explicitly retaining external valid/field masks. There is **no validity attention mask** in this encoder. Sentinel pixels influence attention and are never asserted to be observed reflectance. Readout weights final normalized, non-CLS spatial tokens by valid sampled-support pixel count in each 16×16 patch, across four dates. A 16×16 patch covers 480×480 m; attention mixes the whole context. These are contextual features, not spatially isolated field measurements.

The official encoder's LocationEncoder documents `[latitude,longitude]`; official inference obtains `rasterio.lnglat()` and passes it without reversal. Adapter deliberately follows encoder's documented latitude-first order and records this discrepancy. Time encoding is calendar year and 1-based day-of-year.

Primary real-image path requires actual 224×224 native 30 m context (6.72 km square) and a separate sampled-support mask. Overlapping context across nearby management units is a scientific dependency, not cured by a split label. The adapter also supports an explicit `--allow-center-padding` sensitivity with `.0001` missing sentinel; it never resizes pixels or fabricates dates. Mostly padded chips must not be promoted to a qualified primary model result. Official code technically accepts smaller spatial dimensions divisible by 16, but bicubic-interpolates its fixed pretrained spatial position embeddings; this alternative is not the measured fixed-224 protocol.

## Measured synthetic smoke

`model-probe.json` contains complete cells, five timed warm forwards and failures if any. Both CPU and explicit MPS float32 succeeded, with `PYTORCH_ENABLE_MPS_FALLBACK=0`, 192 finite features. Synthetic seed 72491, full spatial support, four dates; this is not a labelled accuracy experiment.

| Measurement | CPU | MPS |
|---|---:|---:|
| Constructor/hash-check cold load seconds | 10.470 | 1.581 |
| First forward seconds | 0.0558 | 1.0856 |
| Five warm forwards range ms | 47.8–57.7 | 21.0–25.8 |
| Sampled peak RSS MiB (100ms sampling) | 530.23 | 610.999 |
| MPS allocated / driver bytes after run | n/a | 23,139,584 / 67,846,144 |
| Observed system swap growth | 0 | 0 |

CPU ran first, warming OS caches; cold-load numbers are not an unbiased device comparison and exclude initial torch import. RSS is sampled and can miss transient peaks. MPS allocation counters are final snapshots, not an asserted peak. Unified memory RSS and MPS counters overlap and must not be summed. Baseline system swap was approximately 5.36GiB, so this does not establish an unloaded-host result. CPU/MPS pooled-feature maximum absolute difference `4.768e-7`, mean `1.006e-7`; cosine `0.9999999999999843`.

Supervisor enforces 120 seconds per import/load/forward stage, process RSS 8GiB, and system swap growth over 64MiB. The swap trigger is system-wide and may reflect unrelated processes. The environment is isolated at `outputs/imagery-env`, Python3.12.13, torch2.14.0, timm1.0.30, numpy2.5.3, einops0.8.2. Its installed footprint was 849 MiB; the model snapshot 123 MiB, separately accounted from the 1GiB imagery/model artifact allowance. Free disk after setup was 2.7GiB, above the 1GiB reserve. The environment also contains the imagery worker's rasterio/pyproj/shapely/httpx/Pillow dependencies and fixed-readout sklearn. It is optional and not a serving requirement.

Focused tests: `PYTHONPATH=src outputs/imagery-env/bin/python -m pytest -o addopts='' -q tests/test_imagery_models.py`: **16 passed**. A first attempt without `-o addopts=''` failed before collection because the minimal EO environment does not include repository-wide pytest-xdist (`-n`) options. This is retained as an environment limitation, not a passing full-suite claim.

Additional provenance tests reject mismatched acquisition dates and shifted grids, and retain source hashes and explicit padding-sensitivity labels. Probe outputs require fresh paths to preserve earlier failed or successful receipts. Final pre-score label protocol ID: `9714d8896c97092f81ac283d6ac2025d9460e3eed5733f85aa08776e4ce8455e`. No real four-date primary-context bundle had reached this worker at the synthetic-probe checkpoint; real-feature success remains unverified until a separate receipt exists.


## Shared-context reuse

`FrozenPrithvi.encode_tokens` exposes the 784 final normalized non-CLS tokens from exactly the same frozen forward. `pool_shared_context` separately pools each management unit's valid support pixel counts. Identical input arrays, valid masks, dates, location and model identity allow one station context per four-date stack to be reused; unit masks do not enter the encoder. Per-unit field-mask, validity and token-support hashes remain in receipts. The alias test demonstrates that two distinct ROIs inside the same patch can produce identical vectors, while an adjacent patch changes the readout. Global self-attention and nearby units' common context remain dependent. Protocol owner confirmed this common-grid clarification conforms to the existing pre-score representation, without changing protocol ID. No real labelled imagery features were scored at that checkpoint.

Real-chip location comes from the native-grid center transformed to EPSG:4326, then passed as `[latitude,longitude]`; caller coordinates cannot override source-grid identity. The public four-date real-image technical probe remains a distinct gate from Akron label accuracy. An acquisition auto-review rejection on transmitting Akron-derived geometry is handled by the owner; this worker has not retried through a coarsened query or another provider.

Final local checkpoint: 14 focused tests pass. Isolated environment occupied 912 MiB after imports/tests (initial installation 849 MiB), snapshot 123 MiB, and free disk 2.6 GiB. Owner paused all new remote location queries and raster acquisitions, including alternate public AOIs, pending explicit provider/geometry approval. No real four-date input reached this worker; actual-image feature validation and label accuracy remain pending, not failed model accuracy.


## Subsequent existing-file real-image probe

After the remote-acquisition pause, the imagery worker delivered **four already acquired local** public Saskatchewan AOI chips, July 3, 8, 25, and 28, 2025, all actual 224×224 30 m context. Only local files were used; no new location query/acquisition occurred in this worker. `model-probe-real-public.json` records source chip hashes, grids, masks/coverage, model identity and execution code hashes; raw device cells are retained alongside it. This supersedes the earlier pending *real-input technical* gate, while Akron label accuracy remains pending.

Both CPU and explicit MPS float32 passed with 192 finite features, no fallback and zero observed swap growth. CPU constructor/hash load 1.725 s, first forward 84.35 ms, five warm forwards 43.29–56.27 ms; MPS load 1.248 s, first forward 816.06 ms, warm forwards 21.18–24.39 ms. Sampled peak RSS was 530,235,392 bytes on CPU and 637,566,976 bytes on MPS. MPS final allocated memory was 23,139,584 bytes and driver allocation 67,862,528 bytes; these overlap unified memory and are not asserted peaks. CPU/MPS maximum absolute pooled-feature difference 2.235e-6, mean 4.306e-7, cosine 0.9999999999997976. Prior imports/caches were warm, so constructor numbers are not cold-machine timings.

Field valid fractions were 99.8896%, 99.8896%, 98.6755%, and 28.4768%; across the full context and four dates, 71.1226% were valid. The low final-date coverage and all source missing masks are preserved. Passing this intentionally incomplete real input proves numerical execution/adapter compatibility, not robustness to clouds, agronomic usefulness, labelled task accuracy, or suitability of the normalization/coordinate discrepancy resolution for deployment.


### Grid correction retained

The imagery worker subsequently identified that the four existing Sask chips used `hls-chip-v1`, which warped source UTM12 imagery onto AOI-derived UTM13. Their measurements remain real decoded raster adapter/device evidence, but **do not qualify the frozen source-native primary grid**. The earlier phrase 'native 30 m context' describes the supplied 30m chip and must not be read as source-lattice identity. `model-probe-real-public.json.grid_correction` preserves this contradiction explicitly. No accuracy metrics used these chips. The primary cohort extractor now requires `hls-chip-v2-native-asset-grid-fmask-v1` plus an explicit verified source-native-grid metadata flag; old/reprojected/unknown inputs fail closed. A v2 source-native real-input gate remains pending acquisition.


Primary cohort execution is prepared through `scripts/probe_imagery_model.py --cohort-input <contexts.json> --protocol <label-protocol.json> --snapshot <pinned-snapshot> --output <new-output.json>`. The local contexts manifest contains `contexts:[{year,manifest,status,error}]`; each successful year's manifest lists four NPZ paths/dates and cutoff. A supervised MPS worker encodes each year's common context once, derives each management unit's sampled-support hull plus 15 m mask locally, and retains all frozen bundle successes/errors. Outputs include exact source, grid, unit-mask, validity, token-support and model hashes, actual device and dependency identities. Datum remains the protocol's EPSG:32613 assumption. The feature file can be passed directly to `assess_field_imagery.py --features`; extraction does not fit readouts or inspect labels/scores.

Final optional-dependency check: untouched serving environment **15 passed, 1 skipped** (rasterio-dependent support-mask test); isolated EO environment **16 passed**. This does not activate torch or EO inference in serving.


## Finalized source-native 2021 gate

After explicit acquisition authorization, the separate acquisition worker delivered finalized v2 native-grid chips for June 2, 5, 7 and 12, 2021. This worker made no remote requests. `model-probe-primary-2021.json` passed CPU and MPS with source-native flags true and finite 192-dimensional output. CPU warm forwards were 23.37–24.89 ms, MPS 24.41–27.97 ms; maximum absolute feature difference 2.146e-6. This case does not show an MPS speed advantage. Sampled peak RSS was 520,781,824 bytes on CPU and 641,941,504 bytes on MPS, with zero observed system swap growth.

`prithvi-primary-2021-gate.json` is a gate-only feature file: 7 successful 2021 units, 22 explicit missing-year rows. One shared MPS token forward took 0.1652 s; worker sampled peak RSS was 679,837,696 bytes with no observed swap growth. The four declared chip hashes were independently verified after the run, before acceptance. The final extraction adapter additionally rejects declared hash mismatches before NPZ decoding and requires declared hashes for primary cohort input; 17 focused EO tests pass.

**Observed spatial alias:** `akron-SCD5-2021`, `akron-SCD6-2021`, and `akron-SCD7-2021` have exactly identical 192-dimensional features despite distinct ROI masks. Their sampled supports pool the same coarse spatial patch across four dates. This is preserved as a limitation of the representation. It is not corrected through label-driven feature selection. Final cohort scoring must use the final feature file and paired common-date spectral baseline, not this incomplete one-year gate.


## Final primary feature handoff

Frozen acquisition index: `contexts-e8917e40783353ebbb5100d21eb88d1429f7d423e292205e94869975fea89c32.json`, verified SHA-256 `e8917e40783353ebbb5100d21eb88d1429f7d423e292205e94869975fea89c32`. The final reviewed extractor ran once against this immutable index. Output `prithvi-primary-final-features.json` SHA-256 is `f4b8768f87008196f4aa53ffed8dede4889b8b939c9bf2620c7ad8b87dc517df`. It contains all 29 dispositions: 21 successes in 2020–2022 and eight explicit 2019 failures (`no_catalog_scenes_in_frozen_window`). No dates or labels were imputed. The protocol owner received this exact payload for paired, frozen scoring; this worker did not fit readouts or inspect task scores.

The final float32 MPS worker encoded each available shared context once: 2020 first forward 2.4618 s, 2021 0.0454 s, 2022 0.0805 s. Sampled peak RSS was 536,952,832 bytes (512.08 MiB), zero observed system swap growth. These are sequential context-forward timings, not five-repeat warm benchmarks. Shared tokens and validity masks are retained under ignored `outputs/imagery-assessment-acquisition/prithvi-final-tokens/` for authorized label-free geometry sensitivities; each token NPZ hash is bound in the feature provenance.

Exactly identical feature groups in the final output are SCD4/SCD5 in 2020, SCD4/SCD6 in 2022, and SCD5/SCD6/SCD7 in 2021. The corresponding normalized pooling weights also match within their shared contexts. Thus 21 successful field-seasons have only 17 distinct encoder vectors. Original unit-mask hashes and supported token indices remain recorded so these aliases cannot be mistaken for independent fine-scale measurements.

### Qualified mixed-header grid interpretation

The 2020 and 2022 chips mix explicit EPSG:32613 and one exact SHA-allowlisted HLS WKT with an unspecified datum based on the WGS84 ellipsoid. They are **not formally CRS-equal** (`pyproj.CRS.equals=False`); PROJ's available transform is a ballpark no-op with unknown accuracy. The official HLS guide establishes common 30 m MGRS UTM tiles for L30/S30, not general datum equivalence. Admission is a narrowly reviewed research inference: same HLS MGRS tile, finalized native-v2 processing, exact affine/shape, exact UTM13 conversion parameters, WGS84 ellipsoid and east/north metre axes, plus the known raw WKT SHA. No pixels were reprojected or resampled by the adapter. Unknown datum, original CRS and formal non-equality remain in every affected context receipt and must accompany resulting metrics. `model-crs-grid-review.json` records this pre-score reasoning. Other WKT variants, datums, zones, tiles, changed affine/ellipsoid/units or non-native processing are rejected.

Independent implementation review reran **18 focused EO tests**, all passing, and qualified this scoped numeric-lattice assumption without claiming formal datum equivalence. Serving environment verification was **17 passed, one explicit optional rasterio skip**. Code is frozen for integrated review; no serving model profile or dependency environment was changed.
