Prepared-stage analysis retained for provenance. The completed same-origin result and EOS-qualified conclusions are in [the final investigation](../../portable-agronomy-residual-investigation-20260928.md) and the [raw archive catalog](../experiment-raw-archive-20260928/catalog.json), which locates the original `same-origin-gemma-active.json.gz`; pending statements below describe the earlier stage.

# Gemma active runtime receipt: prefix-state confound

This analysis reads `cache-gemma-active-partial.json`, SHA-256 `f9fcf37fc5b6c304d91254627843dc9dc30e8c45ad71a01aa707752b9a672449`. Despite its filename, it contains all seven conditions and the final comparisons. Its recorded script hash matches the current `cache_probe.py`: `700bf18f03412e214bb8969cae0e615e2b94fbfa852450de4fc57bf6b5d87399`. This is one instrumented CUDA model/cell, not a general runtime qualification. The parent executed and collected the runtime; this subtask performed local read-only analysis.

## Observation

All 320 generated token IDs and raw logits agree within each of these groups:

* `off` = `off_repeat`;
* `split_direct` = `split_manual` = `split_clone`;
* `lru_cold` = `lru_warm`.

`off` first differs from `split_direct` at generated token index 97 (zero based). `split_clone` first differs from `lru_cold` at index 23. The latter difference must **not** currently be attributed to the LRU operation: the prefix state already differs before the LRU is constructed or called.

Exact recursive comparisons:

| Comparison | Prefix receipt | Full-prompt receipt | Model-call receipt |
|---|---|---|---|
| split_direct vs split_manual | identical | identical | identical |
| split_direct vs split_clone | identical | identical | identical |
| split_clone vs lru_cold | exactly one differing leaf | exactly one differing leaf | identical |
| split_clone before/after deepcopy | identical | — | — |
| lru_cold before insertion vs after fetch | identical | — | — |
| lru_cold fetched vs lru_warm fetched | identical | identical full-prompt states | warm omits prefix computation as intended |

The sole split-clone/LRU-cold prefix difference is:

```
prefix_state[14].state[1].sha256
split_clone: 77230e1814b063aabc1e2ab2b4d62c17d627e74e3a47a3c38d93d0bdad6b21d8
lru_cold:    52ed4d2e45bae626281c892ec6faaf9b678b5a196efd9503020a6f5c5e06cf14
```

That entry is the value array of the fifteenth cache object (model layer 14), an ordinary `KVCache`, shape `[1,1,830,512]`, bfloat16, offset 830. Its key array hash, all other cache arrays, every offset and metadata field agree. At the full prompt of 1974 tokens the only differing leaf remains layer 14's value hash, now shape `[1,1,1974,512]`. Exact cache hash equality is a strong representation check; hash inequality alone does not reveal difference magnitude, affected positions, or numerical correctness.

Both `lru_cold` and `lru_warm` record `saved_prefix_unchanged=true`. Prefix state equals fetched state in both copy paths. The LRU code's deep-copy operation therefore did not introduce the **recorded** state discrepancy in this run.

All split-clone/LRU-cold model-call records match exactly, including call lengths, consumed token counts and all available before/after offsets. Their prefill lengths are `[829,1,1143,1]`. At full prompt, all fifteen offsets are 1974. Compared with off prefill `[1973,1]`, split-direct has matching layer-0 K/V hashes but changed K/V hashes in layers 1–14; physical metadata and offsets still match. Rotating-cache chronological hashes also differ for the affected sliding layers, so that comparison is not merely a different physical ring-buffer ordering.

The first differing logits precede the first differing selected tokens. At generated index 23, split-direct/clone selects token 2352 from a top-two tie (margin 0), while LRU-cold selects token 5663 with margin 0.0625. At off/split index 97, off selects 4194 with margin 0.21875 while split selects 3439 with margin 0.03125. Top-10 lists are produced with NumPy sorting and do not specify argmax tie-breaking; the recorded sampled `token` field is authoritative. In particular a tied top-10 list can display 5663 before 2352 while MLX argmax selects 2352.

## Interpretation and remaining rivals

1. The receipt supports execution-partition sensitivity in this instrumented experiment: off-repeat is exact, all three independent matched-split constructions are exact, and split versus off changes cache numerics/logits and later token selection without an observed offset error. It does not yet prove every change is harmless floating-point roundoff rather than a partition-sensitive algorithm/kernel defect.
2. The apparent additional LRU effect is confounded by **independent prefill variation**. LRU-cold's prefix was recomputed after the split-clone condition and was already different before insertion. No cache lookup/copy fault is required to explain its later divergence.
3. Exact repeated off outputs do not establish determinism for every later prefix allocation/evaluation. Order, allocation/kernel behavior, retained tensor lifetime, independent-prefix nondeterminism, or instrumentation interaction remain rivals. No particular one is measured by the receipt.
4. Installed `models/gemma4_text.py:249–266` computes separate K and V projections/normalizations; layer 14's V-only change can be localized to recorded cache representation but cannot be assigned to a specific projection or normalization operation from hashes alone. `models/gemma4_text.py:433–443` shares the final layer of each attention type with later layers, so a changed layer-14 full-attention value cache can affect later layers without changing earlier stored cache arrays. This is a plausible propagation path, not a measured kernel explanation.

## Smallest useful follow-up

If further runtime attribution is required, avoid another independent-prefill 320-token comparison. Prefill the stable prefix **once**, preserve that immutable origin, and create two arms from it: direct `deepcopy(origin)` and actual LRU insertion/fetch of that same origin. Compare full-prompt state and eight generated-token logit vectors; repeat a direct clone after the LRU arm. Confirm identical origin hashes before branching and immutable saved state after each branch. This removes the demonstrated starting-state confound.

Separately, three prefix-only repetitions of identical token IDs/settings can test layer-14 V reproducibility, saving that one tensor (rather than hashes alone) to quantify maximum absolute error, changed-element count and affected token positions. If identical origin states still diverge, capture layouts/strides/evaluation readiness and counterbalance arm order before accusing the LRU. If independent prefixes vary first, investigate that boundary before changing cache defaults.

The earlier “no output yet” concern did not establish a runtime deadlock. This complete receipt supersedes that uncertainty about completion; it does not establish a performance rate because instrumentation forces host synchronization and retains logits.

Changed: this analysis only. Verified: exact recursive receipt comparisons, source hash, model-call equality, prefix/fetch equality, immutable saved-prefix receipts, first-divergence margins. Residual Risk: origin of the layer-14 V discrepancy and numerical correctness remain unresolved. Memory Delta: none.

## Method-candidate receipt follow-up

Additional receipt `cache-gemma-method-candidate.json`, SHA-256 `f0d0a57b6ba13344c8087259a86e8d3bcc3a6feafe11e2818043ab522c76cc62`, changes the picture. Off-repeat is exact, but split-direct differs from split-manual/clone in its **pre-insertion** layer-14 V hash; clone and LRU-cold prefix states, full-prompt states and entire call receipts agree. This is further evidence that independently produced prefix state varies before lookup/copy operations.

LRU-cold and LRU-warm have **identical fetched prefix receipts** and both report unchanged saved prefix. Their suffix model-call receipts are identical after removing cold's two prefix calls. Nevertheless their full-prompt states differ: layer 7 V, then K/V in layers 8–14. All offsets and physical metadata agree. Including temporal representations gives 26 differing hash leaves; the representation-only mismatch does not explain why continuation numerics changed. Their tokens first diverge at index 53: cold token 38069 with top-two margin 0.125, warm token 12828 with a top-two tie. Thus equality of cold/warm outputs from the old historical run is not a general determinism guarantee, and the new run cannot be collapsed into a single partition-only explanation.

There is no observed stored-prefix mutation or wrong consumed-token offset in either Gemma receipt. Identical *recorded* prefix arrays do not capture memory strides, allocation, backend algorithm selection, or complete live-model execution state; those remain possible boundaries. Numeric instability, runtime implementation faults and instrumentation interaction are still distinct rivals.

## Bounded same-origin probe prepared

`cache_same_origin_probe.py` is a standalone 12.6 KB script accepting a prior exact runtime receipt, an existing pinned local snapshot, and a fresh output directory:

```bash
python cache_same_origin_probe.py \
  --receipt /existing/prior/cache-runtime.json \
  --snapshot /existing/snapshots/238767527555cb75a05732a84dff5d6ba0dd6809 \
  --output /new/same-origin-result \
  --execute --max-tokens 8 --timeout-seconds 180
```

It validates exact prompt token IDs and small snapshot-file digests against the prior receipt, records tokenizer EOS IDs, repeats only the prefix three times, and then runs direct clone/LRU/direct clone/LRU from one preserved origin. It stores all state hashes, raw last-owned-layer V arrays and their elementwise differences, all eight raw-logit vectors per arm, per-token top-two margins, origin/LRU immutability, stage progress and periodic stack traces. Each real arm begins with identical origin-state hashes or fails closed. Prefix repeats retain separate state observations and do not silently replace the selected origin.

Syntax and CLI parsing passed. A complete CPU NumPy fake-model execution passed the three-prefix/four-arm orchestration and cache/logit/immutability assertions; this does **not** validate model/runtime numerical behavior. No GPU work was performed by this subtask. The script's alarm is a 180-second intended bound; an external driver timeout must enforce the wall limit if a blocking native call delays Python signal delivery. Default 8 tokens (maximum 16), including EOS, are enough to inspect the already-observed immediate logit differences but cannot certify long-generation parity. EOS metadata is retained so earlier fixed-320-token results can be annotated separately for divergence before versus after product stopping.

Changed: appended method-receipt analysis and added the bounded probe. Verified: exact receipt comparisons and model-free orchestration. Residual Risk: real same-origin result and original numerical cause remain pending. Memory Delta: none.
