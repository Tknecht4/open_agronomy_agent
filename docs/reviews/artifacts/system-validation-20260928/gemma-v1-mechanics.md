# Gemma retrieval 2×2: mechanical audit

Run `1b462845b341872493f9b5cd3979e77e43e40ee0ce11104f4dfcf2f555523e31`: **pass** mechanical validity, 192/192 completed cells, 8/8 table setup receipts, 0 audit failures. No answer grading was performed.

## Identity and execution

The capsule and local checkout match 147 source and 14 corpus hashes in the run manifest. All 192 identity receipts report `verified_direct_loader` for pinned `mlx-community/gemma-4-e2b-it-4bit` revision `238767527555cb75a05732a84dff5d6ba0dd6809`. The 80 bypass cells have no response model ID; the 112 draft calls bind a response model ID. The driver exited 0 and reported no end drift. The provision receipt binds the model weight SHA-256 `038e39a37a7667373d2c3991375446b10c96ae1d717a68674870343db376b76e`; the transferred result contains no model weights to rehash.

All 192 cells have 17 stage receipts. 112 cells made a draft model call; 54 made an editor call; 80 bypassed generation. No generation fallback or unavailable rows were recorded. The 80 bypass rows retain the immediately preceding draft `generation_stats`; those fields are stale and excluded from model-call timing. All 112 actual draft calls report applied seed 42 and disabled prompt cache.

## Timing boundaries

| Boundary | Total seconds | Mean seconds per recorded unit |
|---|---:|---:|
| Driver wall (one run) | 633.336 | — |
| Ledger cell elapsed (192) | 503.529 | 2.623 |
| Product core latency (192) | 489.219 | 2.548 |
| Draft generation elapsed (112 calls) | 266.240 | 2.377 |
| Editor generation elapsed (54 calls) | 162.005 | 3.000 |

The first call recorded 15.632s of model loading; the other 191 draft-stat receipts say `already_loaded` (including stale bypass receipts). Excluding the first cell, ledger median is 1.790s. Driver minus ledger is 129.807s; ledger minus core is 14.310s; core minus draft/editor generation elapsed is 60.974s. These are boundary gaps, not retrieval-only measurements. The cold load sits outside generation elapsed. The slowest editor call took 44.312s, including 42.476s to first token, with no new model load recorded; this one cell materially raises the document-only total. No during-run peak memory measure is available.

## Arms

| Arm | Cells | Draft calls | Editor calls | Bypasses | Doc hits | Graph hits | Ledger total s | Ledger median s | Core total s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| retrieval_neither | 48 | 28 | 14 | 20 | 0 | 0 | 114.512 | 1.533 | 111.061 |
| retrieval_document_only | 48 | 28 | 16 | 20 | 158 | 0 | 168.447 | 1.857 | 164.746 |
| retrieval_graph_only | 48 | 28 | 12 | 20 | 0 | 84 | 98.657 | 1.675 | 95.199 |
| retrieval_both | 48 | 28 | 12 | 20 | 158 | 84 | 121.913 | 1.979 | 118.213 |

## Strata

| Stratum | Cells | Draft calls | Editor calls | Bypasses | Ledger total s | Ledger median s |
|---|---:|---:|---:|---:|---:|---:|
| clarification_abstention | 32 | 8 | 0 | 24 | 16.729 | 0.226 |
| deterministic_calculation | 32 | 0 | 0 | 32 | 6.920 | 0.215 |
| field_reasoning | 32 | 32 | 16 | 0 | 138.988 | 3.366 |
| general_explanation | 32 | 24 | 14 | 8 | 133.962 | 4.420 |
| multi_turn_correction | 32 | 24 | 12 | 8 | 78.300 | 2.170 |
| source_table_lookup | 32 | 24 | 12 | 8 | 128.630 | 2.058 |

## Caps, context and repeated trials

No draft call reported 640 generated tokens (maximum 309). 11/54 editor calls reported exactly the 220-token cap; the receipts do not record a stop reason, so exact-cap counts are not confirmed length stops. All 112 draft context budgets and all 54 editor context budgets report `within_budget`; 4 editor budgets explicitly report evidence truncation. The 80 bypass cells have `generation_bypassed` and no counted prompt budget.

The fixed-history receipt pattern is {'0/0': 160, '1/1': 24, '1/0': 8}. Across 96 case-arm pairs, 4 final and 4 draft hashes changed between trials; all four changed pairs are `sv24-08` table cells with fresh per-cell import IDs and derived receipt hashes. The other 92 answer hashes match. This is a byte-repeatability observation, not a quality grade.

The JSON report retains per-arm and per-stratum distributions, provenance checks and residual limits. No grader inputs or files were read.
