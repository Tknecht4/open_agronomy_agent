# Production foundations supplement: development plan

Status: comparison preregistered before supplement authoring; method-only candidate retained **non-active** after review. This is not a sealed evaluation or an agronomic validation. The 13-case file was frozen at SHA-256 `066df89087bd9e1b6a0816e78afe57a590893e4e031f017b2416d891497bdb58` before card text was written.

## Reference state and scope

- Base: `main` at the worktree creation point. Existing active Canadian store: 3,086 rows; optional U.S. NRCS ecological-site store: 218,258 rows. The Prairie DSS spatial databases are mapped priors and are not evidence of field production or farm finances.
- Frozen reference retrieval: 21 active existing cases, Recall@1 0.810, Recall@3 0.857, Recall@7 0.905, nDCG@7 0.860, locator and authority compliance 1.000. The machine-local raw receipt is not part of the public package; its selected measurements are preserved in the public result artifact.
- Candidate: a small project-authored, source-linked, context-only collection on crop-establishment calculations, temperature accumulation, nutrient planning, enterprise budgets, break-even/sensitivity, and farm finance. It must never supply current prices, labels, regulated rates, field measurements, or Canadian authority from a U.S. source.

## Hypothesis and rivals

The supplement should improve source retrieval and small-model answers to production/business scenarios without lowering the existing retrieval or authority controls. Rival explanations: the model already knows these formulas; a benchmark may reward lexical overlap alone; unrelated source cards may displace more applicable Canadian evidence; numerical answers may come from deterministic tools rather than new knowledge; a source citation may be present without being used correctly.

## Frozen comparison

Use the checked-in `data/eval/production_foundations_development_v1.jsonl` as an exposed development instrument. It contains positive, numerical, transfer-boundary, and current-data-negative questions. Freeze its hash before writing the candidate cards. Compare baseline `configs/rag.yaml` to a candidate config differing only by the admitted supplement path and bound policy. Use the same retrieval parameters and exact model revision/seed for paired answer trials. Record every response, source hit, numeric result, unsupported claim, fallback, timeout, and trace. Source hit alone is not an answer-quality pass.

Primary development measures: source-specific Recall@3/7 for positive cases; exact numeric checks with units and denominator for calculation cases; required scope/currency qualifiers; false current-price/rate assertions; existing 21-case retrieval regression and authority compliance; runtime latency. A positive result requires at least four of six source families retrieved at rank <=3, no decline on the frozen existing Recall@7 or authority compliance, and no new unsafe answer in paired model cases. Report denominator and all failures. The current test set is authored from known public sources, so it cannot support population or sealed-v3 claims.

## Resource and stop rule

Whole phase estimate: source/rights audit and authoring 1-2 hours, candidate build and focused gates 1 hour, model comparison and diagnosis 1-2 hours, review/PR 1 hour. Disk currently has about 1 GiB free after the isolated checkout; cap new checked-in assets below 1 MiB, keep raw snapshots ignored, run model cases serially, and stop any run that threatens available disk. If the candidate harms baseline retrieval or authority, leave it as a non-active candidate and report the negative result. Promotion requires source receipt, rights disposition, corpus audit, retrieval comparison, product-path checks, and PR review.

## Inspection and missing source families

**Observation.** The checked-in direct startup store has 3,086 rows from 16 Canadian official source IDs, 36 project context cards, six project safety rows, and 1,783 SoilWise ontology rows. It has valuable soil and provincial guidance but little source-linked farm-business method content. The 218,258-row USDA NRCS ecological-site pack is separate, U.S. regional analogue context; its size does not fill enterprise budgeting or crop-operation knowledge. The non-active candidate adds nine authored cards linked to seven inspected public sources, for 3,095 rows only when its candidate profile is selected directly for development. Raw source snapshots were fetched, inspected, and SHA-256 identified but are not redistributed. The [source registry](../../data/manifests/production_foundations_sources_v1.json) keeps publisher, link, rights, and exact snapshot hash.

**Observation.** Three loose, generated Prairie Detailed Soil Survey SQLite/RTree databases were inspected under ignored local `outputs/spatial_assets/`: Alberta 28,366 polygon features, Saskatchewan 67,166, and Manitoba 168,371. Their tables contain mapped feature identifiers, compressed properties and geometries, and bounds. `AGRONOMY_AGENT_SPATIAL_PACK_ROOT` was unset during this inspection, so the loose files were not an observed installed runtime pack. The governed `prairie-dss-v1` profile remains an optional post-clone installation. The maps describe historical soil units and components, not actual crop inputs, yield, costs, market prices, or field soil tests.

| Priority | Durable missing knowledge | Candidate source family and admission boundary |
|---|---|---|
| 1 | Crop establishment, crop-stage/thermal-time methods, harvest moisture and storage-quality arithmetic, and rotation/field-trial interpretation across more US/Canadian regions and crops | Provincial and land-grant extension manuals, [USDA NRCS National Agronomy Manual](https://www.nrcs.usda.gov/sites/default/files/2022-10/National-Agronomy-Manual.pdf). Capture page/table locators, versions, crop and regional fit; do not transplant old targets. |
| 2 | Enterprise and partial budgets, cost allocation, machinery ownership, break-even and sensitivity, cash versus accrual, liquidity/solvency, financing and marketing-basis scenarios | [Manitoba cost-guide formulas](https://www.gov.mb.ca/agriculture/farm-management/cost-production/pubs/cop-special-crop-production-v2.pdf), [Iowa State partial budgeting](https://www.extension.iastate.edu/Agdm/wholefarm/html/c1-50.html), [USDA ERS ratio definitions](https://www.ers.usda.gov/data-products/farm-income-and-wealth-statistics/documentation-for-the-farm-sector-financial-ratios). Store methods; obtain current farm-specific prices, contracts and costs separately. |
| 3 | Nutrient-budget arithmetic and interpretation of tests, credits, response and environmental losses | [USDA NRCS nutrient planning](https://www.nrcs.usda.gov/getting-assistance/other-topics/nutrient-management) plus source-specific Canadian calibration. A U.S. framework or a mapped soil unit never gives a Saskatchewan legal or field rate. |
| 4 | Canadian regional spatial context beyond Prairie DSS, with exact coverage and uncertainty | Existing geospatial intake lists boundary, erosion, national grids and other provincial layers as candidate or deferred. Measure install size and query value; keep soil maps separate from observations and business records. |

**Interpretation.** A smaller model needs stable, source-linked methods and explicit typed inputs. More retrieved prose alone does not make its arithmetic or verifier reliable. The next highest-value calculation work is to connect already-implemented deterministic `seed_rate_mass`, `daily_gdd`, and `partial_budget` operations to varied natural language and preserve units and source assumptions through rendering. That would be a separate intervention and benchmark arm, not a hidden claim for this nine-card corpus change.

The [agronomic expertise plan](agronomic-expertise-knowledge-plan-20260927.md) develops that into an explicit soil chemistry, nutrient-response, water-balance, crop-development, trial-design, imagery, crop-protection and farm-economics source/tool/evaluation map for coordination with the field-data ingestion task.

## Measured development result

The [public result artifact](artifacts/production-foundations-development-20260927.json) retains every paired final answer, its hash, source-selection receipt, fallback state, effective model identity, and strict nonblinded assessment. Both final arms used the exact checked-in active/candidate RAG configs, the same 13 frozen questions, pinned Gemma 4 E2B revision, 320-token limit, and offline production execution path. The model-call traces report temperature-zero argmax with **no requested or applied seed**, despite `seed: 42` in `configs/model.yaml`; the original same-seed intent was not achieved. The authored questions are exposed and source-conditioned; all outcomes are development diagnostics.

| Measure | Baseline | Candidate | Reading |
|---|---:|---:|---|
| Expected new-card raw retrieval at rank <=3 | 0/11 | 11/11 | New-card availability, by construction; not independent efficacy |
| Existing suite Recall@1 | 17/21 | 16/21 | Manitoba soil-fertility source moved from rank 1 to 2 |
| Existing suite Recall@3 | 18/21 | 19/21 | One older case moved from rank 4 to 3 |
| Existing suite Recall@7 | 19/21 | 19/21 | No loss |
| Existing suite authority compliance | 21/21 | 21/21 | No observed boundary regression |
| Expected card in execution context | 0/13 | 9/13 | Planner/selection path matters beyond BM25 rank |
| Strict full manual pass on exposed answers | 5/13 | 5/13 | Includes three safe boundary cases in each arm; no complete-answer gain |
| Conservative verifier fallbacks | 6/13 | 6/13 | No gain |
| Serial local model-run wall time | 140.5 s | 119.7 s | Prior path-equivalent pair reversed this order; no latency benefit established |

The method-only candidate made nutrient-planning and whole-farm cash-flow explanations more source-specific, and it labelled the assumed break-even-yield price more clearly. It did **not** complete an additional strict case: both arms withheld the `117 lb/ac` seeding, `$12/bu` break-even-price, `2.0` current-ratio and `40%` debt-to-asset calculations. Both gave `-$50/ac` for a partial budget whose four changes sum to `+$20/ac`. The baseline growing-degree-day answer used a wrong formula and gave `5`; the candidate withheld instead of giving the required `10`, a safer but incomplete outcome. Both yielded `60 bu/ac` in the other budget scenario, yet neither explicitly distinguished the assumed input from a current market quote, so both are partial. The current-price and Canadian cross-border-rate negative cases remained bounded. Every final answer and judgment is retained in the artifact.

Failed iterations are part of the result. The first candidate indexed but selected zero cards in 13 execution turns because its retrieval facets were outside the live route filters. A 160-token run clipped a calculation, so final arms used 320 tokens. **Independent review then found that five cards embedded the frozen questions' synthetic values and expected answers.** Those contaminated answers and package receipt were invalidated and retained only as ignored local negative evidence. The public candidate was rebuilt with method-only prose and a leakage regression test. A post-hoc sentence about preserving a user-supplied total-cost boundary also followed an observed model error; this is exposed tuning, not independent confirmation. The repaired candidate still causes the rank-1 Manitoba soil-fertility displacement. Frozen RC1–RC3 evidence was not rewritten.

## Admission and limits

The nine-card release remains **non-active**. `configs/rag_production_foundations_candidate.yaml` and its companion policy admit it only for explicit development runs as `internal_synthesis` and `context_only`; `configs/runtime_profiles.json` still selects the original five-shard active corpus. Its source registry distinguishes Manitoba OpenMB attribution, USDA government pages, AAFC site reproduction limits, and unestablished redistribution rights for Iowa State source text. Only newly authored summaries enter the public package. No external page bytes, current price series, private field data, evaluation answers, or training rights are included. `source_type=applied_guidance` and `knowledge_bucket=farmer_knowledge` are retrieval facets, not a promotion of evidence authority.

The candidate corpus audit found 57 hash-bound files and 221,353 rows with complete locators and quality fields. The active profile stays at 56 files and 221,344 rows. The candidate's raw retrieval reachability and 21-case authority checks passed, but rank-1 relevance regressed and answer quality did not improve. This is a source/tool-design artifact for review, not an activation request. The next intervention is to bind general methods to typed field records and existing deterministic calculators, then test on a fresh, source-distinct cohort before considering activation. The checked-in older retrieval baseline remains historical and bound to its earlier config hash; the paired result is separate.
