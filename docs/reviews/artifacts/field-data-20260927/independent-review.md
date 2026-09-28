# Independent acceptance review — field-data research

Decision: **accept for the research and planning scope**. No material repair finding was reproduced. This accepts the discovery evidence, sample inspection, and proposed implementation/benchmark design; it does not accept a working importer, qualified benchmark, trained model, public data release, or local EO performance result.

Review date: 2026-09-27 UTC. Reviewer: delegated independent `research_review` agent. Source checkout: `7c502d8065a46c14c6abb462833509e5b598f2f8`; checked-out branch `codex/production-corpus-supplement`, whose HEAD matches `main`. The report's reference to that commit on main is valid. No model identity or runtime run ID is inferred from document metadata.

## Independently derived expectations

Before reading the owner's conclusions, the delegated contract and repository instructions established these expected obligations. An observable violation would be an unsupported acquisition/count/license claim, fabricated sample fact, non-reproducible numeric seed, mismatch with the controlling current interface, exposure of evaluation answers to the product/training loop, unbounded future-data use, or inferred M4 performance presented as measurement.

| Obligation | Boundary and independent evidence | Assessment |
|---|---|---|
| Broad Canadian/U.S. discovery with actual downloadable observations | Inspected all three dataset ledgers and their role/license fields; recomputed 51 records, 50 distinct URLs, and 28 open/14 conditional/9 unknown labels. Read Canadian/U.S. notes. Recomputed ten local sample files: 7,534,085 bytes. | Met for discovery. Source records, sites, fields, plots and observations are explicitly different; independent field count remains null. Canadian commercial-field yield coverage is an explicit gap. |
| Source-specific rights and access | Rehashed six saved DataCite/Zenodo metadata snapshots and inspected their exact-DOI rights fields. Read conditional UBC, KBS, DRIVES, CropNet and unresolved NASA/data-specific terms. Independently opened decisive HLS, OlmoEarth and corn-survey primary pages. | No blanket permission inferred from government hosting, code license or successful download. Catalog license labels are not runtime/training/redistribution admission. Unfetched records remain unfetched. |
| Load a field from user files and expose evidence in UI/trace | Traced actual attachment MIME validation and PDF/image stubs, local-source text reader/chunker, soil-only typed measurement and bounded stored field-history code. Read current architecture/data/server/package contracts and active model profile. | Current limitations support the proposed work. The staged parser, identity/unit review, atomic snapshot, row lineage, deterministic tools and UI/trace loop are described as future additions. |
| Easy/medium/hard/expert field benchmark | Inspected difficulty templates, three test layers and actual source-backed seeds; verified nitrate rows 2–4, repeated 131.04 kg/ha rate, 840 arithmetic mean versus reported 397 geometric mean; Akron S2/2022 has 13 samples averaging 567.7894685731263 kg/ha. Checked moisture conventions in its dictionary and Canadian example rows. | Proposed numerical oracles are reproducible. Interpretation review is explicitly pending. Grouped inference, failure denominators, attribution and separate raw/reviewed-record lanes are specified. |
| Leakage-safe development, UI and future fine-tuning | Read split assignment, same-physical-field/all-year grouping, derivative and mirror deduplication, isolated evaluation workspace, excluded scorer/answer files and separate training gate. | Development examples are exposed; evaluation inputs may enter only their disposable case store. Shared retrieval, demo libraries, SFT and repair prompts exclude sequestered material. Public pretraining contamination remains acknowledged. |
| HLS/AWS and local EO feasibility | Checked HLS protected bucket and source license; OlmoEarth custom license; input/timestamp/mask contracts; recalculated 47×47×6×24×4 bytes = 1.21344 MiB, the 72 MiB tensor, and 288 MiB illustrative attention matrix. | Access conditions, native-input mismatch and total-memory uncertainty are explicit. The document never promotes input-array size or publisher metadata to observed M4 latency/memory or yield skill. |
| Temporal validity and observation/model distinction | Read observed_at/available_at replay contract, forecast cutoff, full-year embedding exclusion, crop/phenology baselines and measured-target requirements. | Model products, annual embeddings, county aggregates and field measurements remain distinct. Future imagery/labels cannot be used as in-season predictors. |

## Independent observations

All ten data/dictionary/metadata-table files were read and rehashed. Their sizes, row counts and column counts match the reported receipts: nitrate 32,025×23 with 10,675 IDs and three contiguous samples each; Akron 721×21 with 18 management-unit codes; UBC 449×21 and 2,233×27; Swift Current 5×4 and 93×11; DRIVES site metadata 22×29; county yield 45,499×3; and the two U.S. dictionaries. UTF-8 decoding fails on the Swift Current bytes while Latin-1 succeeds. UBC files are comma-delimited despite `.tab` suffixes.

Canadian example checks recover the D7-3 first ryegrass row and blank first/second plantings, the June bed range 14–17, three October ranges 1–5/6–10/11–15 with 7,046.4 ft² each, and 25 D7-3 `completed=True` seed/transplant records across crops. Those examples retain the absence of yield and exact polygon joins. U.S. numeric seeds retain logical-record locators and raw hashes; lack of source-record locators for the draft Canadian prose questions is acceptable at discovery stage and must be resolved before the planned scored benchmark.

Controlling source observations include `server/schemas.py:1020` (attachment types), `server/app.py:1497` and `:1512` (local image/PDF status), `field_measurements.py:49` (soil-only validation), `server/services/datasource_service.py:120`–`:147` (UTF-8 text input and character chunks), and `server/services/chat_service.py:4015` onward (default 12-event integrity-checked history). These are source inspection, not an executed product/upload test.

The owner's subsequently available `verification.json` agrees with independently reproduced sample/count evidence. Its documentation check is owner evidence, not a test rerun by this reviewer. Public-package construction remains the owner's integration gate and was not duplicated.

## Primary-source checks and search trace

This reviewer issued **no search queries**. Direct primary-page opens on 2026-09-27 were:

- [HLS L30 AWS registry](https://registry.opendata.aws/nasa-hlsl30/): controlled `lp-prod-protected/HLSL30.020` bucket in `us-west-2` and CC BY 4.0 match the report.
- [OlmoEarth v1.2 Nano artifact license](https://huggingface.co/allenai/OlmoEarth-v1_2-Nano/blob/main/LICENSE.txt): custom conditional artifact/derivative rights match the report; not Apache/MIT.
- [Corn stalk nitrate publisher record](https://agdatacommons.nal.usda.gov/articles/dataset/Data_from_Late-season_corn_stalk_nitrate_measurements_across_the_US_Midwest_from_2006_to_2018/24668283): stated 10,675 fields and 32,025 measurements and management/weather context match the catalog and local principal CSV. Physical-farm independence is not established by that count.

## Coverage limits and residual risk

This bounded review did not independently reopen every long-tail source, rerun all 113 discovery queries, establish farm/site deduplication, or obtain unacquired substantive tables. Dataset-wide rights snapshots and exact file exceptions remain acquisition gates; the conservative conditional/unknown states preserve that uncertainty. It also did not independently measure host hardware/dependencies, download weights or imagery, run EO inference, exercise imports/UI, run model answers, or perform agronomic interpretation review. No such completion is asserted by the candidate, so those limits do not defeat research-scope acceptance. Full runtime and frontend verification becomes necessary when the planned behavior is implemented.

The most plausible downstream failures still compatible with these checks are duplicated physical farms across releases, source-specific rights changes, ambiguous experimental units, crop/soil method mismatch, wrong future-availability timestamps and an EO model that fits RAM but adds no predictive value. The plan gives discriminating next evidence: exact artifact/rights manifests, site-lineage joins, independently reviewed records/rubrics, strict historical replay, and grouped measured-label comparisons plus actual device receipts. None is silently treated as already resolved.

## Reviewed byte identities

SHA-256 bindings below cover the integrated research candidate read by this reviewer. Raw-file identities are already retained in the source receipts and were independently reproduced. Future package receipts and this review itself are outside this list. Any substantive change to a reviewed claim requires review of its delta.

| Path | SHA-256 |
|---|---|
| `docs/reviews/field-data-benchmark-research-20260927.md` | `102207d57d698acdb5011a67a562771cbabbafc9fd53781d038362cb1f654962` |
| `docs/reviews/artifacts/field-data-20260927/canada-sources.json` | `909971963ae4c4ed877f916ba3f3422e91a802901d6f6564216983856248dbab` |
| `docs/reviews/artifacts/field-data-20260927/canada-notes.md` | `53931d1fce5d8203b1232fa69af489aeb444e79ac9710a63d33e719a0fc41ecc` |
| `docs/reviews/artifacts/field-data-20260927/us-sources.json` | `517b259913d2f3949cb5721a94b872e02807f1d3fa419c960dda0af5fbb13b51` |
| `docs/reviews/artifacts/field-data-20260927/us-notes.md` | `6fb89c0d78e4374036a9fc62ac039dbcbcd7479ca4fa47e8f38f7de42063deb8` |
| `docs/reviews/artifacts/field-data-20260927/context-sources.json` | `d88042cec48229d0d2b62dd7b1fd6c9bf4df921a9a2b0fc058d976e9f44e50e0` |
| `docs/reviews/artifacts/field-data-20260927/context-sample-receipt.json` | `792067139e0b76a61205b5f88f5974a5f6508f00adadca1bf75c282760d5bcdf` |
| `docs/reviews/artifacts/field-data-20260927/imagery-sources.json` | `81345e9aa4930b30ed09cf60344d49d50e026c57501a23606e771ee707b79a1a` |
| `docs/reviews/artifacts/field-data-20260927/imagery-models.md` | `649a765d3d87a9f0b760bbd3082fcb9dda10697ae6bea0f86865b4b6f6796caa` |
| `docs/reviews/artifacts/field-data-20260927/inventory-summary.json` | `c10e6b90f5a88b6b33e7de33f859c8be1260acfc98c42843596cea71e14d5d4a` |
| `docs/reviews/artifacts/field-data-20260927/source-catalog.csv` | `4dc6b7718a0905d19c12a361649f983f45e4b17b906a0e5673d0746bfe9aa22d` |
| `docs/reviews/artifacts/field-data-20260927/sample-question-seeds.json` | `a8218ba8c86e02698bc47ec4adf0ed2c32c0cb15337ac94dbce8a9f7c9a5fab2` |
| `docs/reviews/artifacts/field-data-20260927/search-activation.json` | `6ce7da760aa8c4f33c10d4ba545b221681365c75ffdad11118c92ef12bf112a8` |
| `docs/reviews/artifacts/field-data-20260927/verification.json` | `227792dbccc07b85687ce86af29edae92e257324ca708939f8c0e93c1c21b16e` |

Changed | Added only this independent review.

Verified | Research-scope contract coverage, source/interface observations, sample facts, arithmetic, cited primary-page spot checks and candidate byte bindings.

Residual Risk | Explicit acquisition, rights, independence, agronomic-review, runtime/UI, temporal replay and EO-performance gates remain unfulfilled.

Memory Delta | None. Historical Open Agronomy memory was used only as an index to evidence/claim boundaries; current source and candidate evidence control this decision.
