# Gemma field-v2 retrieval 2×2: mechanical audit

**Mechanical status: pass, with no reported audit failures.** The collected run has 192/192 planned attempts and 192 completed executions; 24 cases × four arms × two trials are present. The separate table audit linked all 48 parsed claims across eight `sv24-08` answers to each cell’s committed SQLite import, stored source blob, rows, and recomputed receipts. This document does not grade answer quality.

## Identity and delivery

Run `193f5acd1959b1d75b1957ec43046b5d971ce945795fbd1eb6f9aa934e12cb61` binds field-v2 runner `84e64d8d045d156cc17ceb7bad1d1b90e607974bc316d623dbbfa1c2c6c069ec` through the collected runner-delta receipt. All 147 source hashes match frozen Git commit `2b4028560c18def902463b4da44ef2c5c69467b1` and the capsule inventory; all 14 corpus artifacts and the exposed table inputs match. The per-cell plan, case, answer-stage, prompt, control, and field-delivery checks reported zero mismatches. All 192 loader identities say `verified_direct_loader` for `mlx-community/gemma-4-e2b-it-4bit` revision `238767527555cb75a05732a84dff5d6ba0dd6809`. The provisioning receipt records `model.safetensors` SHA-256 `038e39a37a7667373d2c3991375446b10c96ae1d717a68674870343db376b76e`; the model weights were not rehashed from this transferred result.

The transferred result archive SHA-256 `1ac58bf8ba865b8a8bf27ab13867ea2edff0fe03028c6441cbdd1af3182a3db9` matches its collection receipt.

The collected runtime probe reports an NVIDIA L4. All 184 non-table cells delivered canonical crop and jurisdiction through the field compiler; the eight table cells used the reviewed helper. The 112 draft-generation cells passed actual stored-prompt field-block checks. The other 80 cells bypassed generation, so no model-prompt delivery is claimed for them. No fallback or unavailable rows occurred. The 80 bypass rows contain stale `generation_stats` from the reused backend in the frozen product source; they are excluded from model-call and model-time totals.

## Time and calls

| Boundary | Count | Total s | Median s |
|---|---:|---:|---:|
| Driver wall | 1 run | 573.807 | — |
| Ledger cell execution | 192 cells | 442.944 | 1.836 |
| Product core latency | 192 turns | 427.971 | 1.752 |
| Draft generation | 112 calls | 273.707 | 2.405 |
| Editor generation | 48 calls | 92.308 | 1.944 |

One actual draft call records 15.807s of model loading. Excluding the first cell, ledger median is 1.832s. Driver minus ledger is 130.863s; ledger minus core is 14.973s; core minus recorded draft/editor generation is 61.956s. These are gaps between measured boundaries, not isolated retrieval durations. The cold model load is outside the recorded generation elapsed interval.

| Arm | Cells | Draft | Editor | Bypass | Doc hits | Graph hits | Ledger total s | Ledger median s | Core total s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| retrieval_neither | 48 | 28 | 12 | 20 | 0 | 0 | 117.798 | 1.494 | 114.289 |
| retrieval_document_only | 48 | 28 | 12 | 20 | 158 | 0 | 114.524 | 1.836 | 110.608 |
| retrieval_graph_only | 48 | 28 | 12 | 20 | 0 | 84 | 91.969 | 1.676 | 88.365 |
| retrieval_both | 48 | 28 | 12 | 20 | 158 | 84 | 118.653 | 2.077 | 114.709 |

| Stratum | Cells | Draft | Editor | Bypass | Ledger total s | Ledger median s |
|---|---:|---:|---:|---:|---:|---:|
| clarification_abstention | 32 | 8 | 0 | 24 | 17.042 | 0.246 |
| deterministic_calculation | 32 | 0 | 0 | 32 | 7.103 | 0.219 |
| field_reasoning | 32 | 32 | 20 | 0 | 142.938 | 4.450 |
| general_explanation | 32 | 24 | 8 | 8 | 120.904 | 3.411 |
| multi_turn_correction | 32 | 24 | 8 | 8 | 66.227 | 2.205 |
| source_table_lookup | 32 | 24 | 12 | 8 | 88.730 | 2.075 |

## Prompt budgets, caps, and repeated trials

All 112 draft budgets and all 48 editor budgets are `within_budget`; no actual draft prompt clipped prior history, and no editor evidence truncation was recorded. Eight bypass cells with fixed history have omitted history in their no-generation budget receipts, which is not draft prompt clipping. No draft call reports the 640-token cap (maximum 341); 4/48 editor calls report exactly 220 tokens. The receipts do not record stop reason, so exact-cap counts do not prove a length stop.

Across 96 case-arm trial pairs, 5 final-answer hashes and 4 draft hashes differ. Four differing pairs are `sv24-08`: each table cell has a fresh import ID and derived receipt hashes. The one other final difference is `sv24-13:retrieval_graph_only`: both trials have the same draft hash, then different accepted editor outputs. This localizes the byte difference after the draft; its cause is not established by the receipt alone. The other 91 non-table final-answer pairs match by hash.

## Evidence boundary

The collected driver status reports `completed`, exit code 0, 192 observed cells, and no failed cells. No standalone driver log was collected, so the final drift result is inferred from that exit code and the frozen runner return contract; there is no directly observed end-drift log line. The worker log has no traceback and the audit rechecked collected manifest, capsule, source, corpus, and per-cell identities. The result package does not provide during-run peak memory, a live post-run model-weight rehash, a retrieval-only time measure, or answer correctness/safety grades. The JSON report retains per-cell observations and all missing/failure denominators.
