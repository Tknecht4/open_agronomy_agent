# Production foundations: source-distinct efficacy audit

Status: plan and 14-case instrument frozen before model comparison. This is an exposed development audit, not sealed agronomic validation or approval to activate the candidate cards.

## Reference state

- Code: merged `main` commit `393b07185f5dc7ff2b62e56e30928fb44de25ba9`. The active profile remains `configs/rag.yaml` (SHA-256 `8f45880dbadf368848d52251aaafb24e25b17d9baa7923aa7707f6880fc04b91`); the non-active nine-card profile is `configs/rag_production_foundations_candidate.yaml` (SHA-256 `ae7228c494ede35cd9109c38e5a987910fe76a99737780e7e70cbd47ef0d02d0`). Their retrieval settings differ only by the candidate shard, bound policy and store declaration.
- Model: pinned local Gemma 4 E2B revision `238767527555cb75a05732a84dff5d6ba0dd6809`, `configs/model.yaml` SHA-256 `8cd880ac68b3631a4eccc11bd9716be3e1768b1a5d49653ac13acc7ec6aeba10`, configured temperature zero and seed 42. The already provisioned primary-checkout cache must be explicitly supplied to the isolated worktree; no model download is part of evaluation.
- Runner: `scripts/run_production_foundations_development.py`, SHA-256 `63676563d23eb5aabe88f9e970cac325b12ee9ba2fb4a4dc0968137a3846acee`, through the 17-stage product execution core.
- New case/rubric file: [production_foundations_transfer_v1.jsonl](../../data/eval/production_foundations_transfer_v1.jsonl), SHA-256 `06bd3cb6c4f6e8122e809609132879ab31395d0810c6c09e7a981c6e5a346467`, 10 qualitative transfer cases and four negative controls. All are expected to require model generation or a safety hold, never a completed arithmetic tool result.

The earlier exposed 18-case confirmation was rerun on this exact merged code with the real pinned model and both RAG profiles. Both completed 18/18 with three model drafts and one fallback; 17 final answers were byte-identical. The candidate made the remaining current-ratio definition more farm-specific. Eleven numerical answers came from the same deterministic calculator in each arm. That run confirms the operational model/cache path and the typed calculation boundary; it cannot establish that the cards improve agronomic knowledge.

## Hypothesis, rivals and intervention

**Hypothesis.** The nine method cards improve complete, bounded answers to production and farm-business transfer questions even when the user does not supply a calculable numerical input. A useful improvement should survive a comparison against the same active system, code, model, seed and cases, with candidate RAG as the only treatment.

**Rivals.** The model already knows the principles; a card is retrieved but excluded from final context; a card is selected but restates generic knowledge; its context displaces stronger Canadian evidence; verification hides a gain or introduces a fallback; apparent changes reflect stochastic generation, order or source-conditioned wording rather than reliable reasoning.

An independent author used official Canadian and U.S. government or extension references whose URLs differ from the seven source URLs behind the cards. The author did not inspect card text, previous benchmark questions or model outputs. We replaced three references that could not be directly reopened with accessible official sources before freezing the instrument: [Minnesota alfalfa thermal-time guidance](https://extension.umn.edu/agriculture/crop-production/forages/using-growing-degree-days-to-plan-early-season-alfalfa-harvests), [Oklahoma partial-budget guidance](https://extension.okstate.edu/fact-sheets/machinery-ownership-versus-custom-harvest), and [Oklahoma enterprise-budget guidance](https://extension.okstate.edu/fact-sheets/using-enterprise-budgets-in-farm-financial-planning). The Saskatchewan winter-wheat page has a malformed displayed equation; its case uses only the source's unambiguous prose on required seed-lot inputs. No external source text is added to runtime retrieval.

## Frozen comparison and assessment

Run the cases once through active RAG and once through candidate RAG, serially, at a 320-token limit. Each case receives a new product session; retain the final answer, selected document IDs, model/seed receipt, fallback, trace and elapsed time. Freeze raw reports before grading. Shuffle and mask the arm labels for an independent grader using the checked-in expected and forbidden claims.

- **Complete:** all expected claims substantively present, scenario's mistaken inference corrected, applicable jurisdiction/assumptions respected, no forbidden claim.
- **Partial:** some relevant claims, at least one missing, no material false or forbidden claim. A generic caveat with no scenario reasoning earns zero claim coverage.
- **Unsafe/materially misleading:** any forbidden claim asserted or endorsed, invented measurements/current facts/authorization/actionable rate, even if another paragraph is correct. Record the offending sentence and code.
- Record each expected claim as present, absent or contradicted; report fallback, truncation, tool bypass, selected card and citation/source correctness separately. A safe refusal on a positive case is incomplete. A refusal on a negative control is complete only with its required authority or missing-evidence explanation.

The engineering signal for card usefulness is at least **three paired complete-answer gains across two different method families**, no more than one paired loss, zero new unsafe answers, and a relevant candidate card selected in final document context for at least **7/10** transfer cases. These small-sample thresholds are decision aids, not statistical proof. Report all 14 pairs and four controls regardless of outcome. If this signal appears, repeat four discriminating cases in reversed arm order without changing code, cases or rubric. Any unsafe answer, model-identity mismatch or evaluation leakage stops promotion consideration.

## Resource and authority boundary

Budget one serial paired run of 28 turns (approximately 5–10 minutes at the observed local rate), up to four reversed-order pairs if informative, and a separate source-bound grading pass. Expect under 30 MiB of new local reports; stop new runs if disk falls below 150 MiB. Model identity, applied seed, corpus hashes, source selection and completion status must be observed, not inferred. Preserve failed/null runs. Evaluation questions and answers remain under `data/eval/` or ignored local reports and must never enter retrieval or training.

The result can support only a narrow statement about this exposed transfer cohort. It cannot establish broad agronomist-level competence, legal/rate authority, field outcomes, source redistribution rights or active-corpus admission.

## Prospective context-selection confirmation

Before examining or changing selection code, a separate author prepared [eight confirmation cases](../../data/eval/production_foundations_topic_confirmation_v1.jsonl), SHA-256 `8dcc4964aa7a3af8cd3dcb08a1d2def6d348686a18422c2d8d478c8afee6cf9d`: six qualitative method cases, two negative controls. Their source URLs are distinct from the seven card sources and the first 14-case cohort. One Penn State page with unreliable direct access was replaced before freezing by directly opened [Minnesota market-channel guidance](https://extension.umn.edu/agriculture/farm-operations-and-systems/agricultural-business-management/marketing-farm-products/marketing-mix-analysis-for-farm-operators). The author did not inspect cards, first-cohort outputs or code.

Run the unchanged code once with active then candidate RAG on these eight cases; retain both reports without reading their answers. Implement a bounded selection/safety repair derived only from the first 14-case development diagnosis. Then repeat the eight cases with candidate then active RAG, matching model revision, seed, token limit and runner. Grade all four arms from shuffled, masked answers against the already frozen claims. The old-code baseline and new-code comparison have different implementation identities, so report them as separate paired contrasts. A useful context-preparation repair requires a relevant card in at least 4/6 final positive-case contexts, no new unsafe answer in either control, and no decline in the older 21-case retrieval/authority suite. Complete-answer changes remain separately adjudicated; case exposure and the small denominator prohibit a general competence claim.

## Observed paired results

The [public evidence artifact](artifacts/production-foundations-efficacy-20260927.json) retains every final answer and its SHA-256, product-selected document IDs, actual model/seed and fallback receipts, raw report hashes, masked-grade records and source-selection diagnosis. The first cohort's active and candidate reports are SHA-256 `41e6f750daee60fbdf55c627e5d87d540ec733d4b62cf3ad08fb8bfaa4dd789f` and `02100fadae335329cffa9a4670f7f1ee8bc67f3d2dfbca8ce76b9d681507e7f2`. Both ran all 14 cases with 12 completed model drafts, applied seed when drafting, and four fallbacks. Seven paired final answers changed.

| First transfer cohort, blind grade | Active | Candidate |
|---|---:|---:|
| Complete | 1/14 | 1/14 |
| Partial | 12/14 | 10/14 |
| Materially misleading | 1/14 | 3/14 |
| Expected card in final context, ten positive cases | Not in profile | 3/10 |

There was **no paired complete-answer gain**. The candidate introduced two additional materially misleading answers: it treated moisture as the established cause of differing alfalfa maturity and misstated proportionality in a break-even explanation. Both arms also told a U.S. herbicide user to check Canada's PMRA label. These judgments include the independent blind grader's rationale and uncertainty; none involved a supplied numerical herbicide rate. A safe fallback on a positive case still counted as incomplete.

The candidate's direct raw question search ranked the expected card within seven documents in **9/10** positive cases, but final product context retained it in **3/10**. Four method cards were excluded for mismatched jurisdiction, which correctly prevents a Manitoba guide from establishing an Oklahoma or Saskatchewan field recommendation. Three U.S. business cards were dropped by topic or lexical-fit filters. Irrelevant nutrient-planning cards sometimes occupied business-question context. This identifies context preparation and missing jurisdiction-appropriate source coverage as distinct bottlenecks; raw recall alone overstated treatment delivery.

The previously unresolved integrated-model check is also closed operationally. With the worktree pointed at the already provisioned cache, the pinned model completed the exposed 18-case active/candidate rerun on merged code: three drafts and one fallback in each arm; **17/18 final answers byte-identical**. All eleven arithmetic answers were the same deterministic tool results. The candidate's remaining answer was a more farm-specific current-ratio definition. These exposed cases do not establish card efficacy.

## Rejected selector experiment and separate safety repair

The first cohort exposed a tempting lexical repair: broaden `economics` topic terms so U.S. partial-budget and whole-farm cards survive final filtering. On the exposed first cohort, this raised expected-card delivery from **3/10 to 6/10**. The independently frozen eight-case confirmation contradicted the apparent improvement. The old code selected the expected card in **5/6** positive candidate cases; the experimental code selected **3/6**, below the preregistered 4/6 floor. The new topic tag made the whole-farm card itself exclusive while ordinary questions about a cash projection or direct-market poultry lacked matching finance keywords. A valid card was then filtered out. The selector experiment was **reverted**; it is not a supported optimization.

| Eight-case confirmation, blind grade | Before active | Before candidate | Selector experiment active | Selector experiment candidate |
|---|---:|---:|---:|---:|
| Complete | 0/8 | 0/8 | 0/8 | 0/8 |
| Partial | 8/8 | 8/8 | 8/8 | 8/8 |
| Materially misleading | 0/8 | 0/8 | 0/8 | 0/8 |
| Expected claims fully present | 8/31 | 14/31 | 9/31 | 12/31 |
| Expected card in final context, six positive cases | Not in profile | 5/6 | Not in profile | 3/6 |

Individual claim coverage is diagnostic, not a substitute for a complete answer. Both candidate arms supplied more fragments than their paired active arms, but neither completed a case; the selector experiment reduced the candidate's claim coverage and card delivery. The before-code reports are SHA-256 `d506f6b449b84cac0b88da971eefeeff0fdd849232f018db1d35bd3322a1e9b5` and `dfec37eb1cc9abd6a398bab4c509e342a6c5d9936ad9d15b493cb0155e2ce603`; after-code reports are `4bf12b01c39de41695e996bb94a6845cfbd8fd33ef24f68aa7c6e4ae0419ccc3` and `a42b3c9efe34758fbff235e500520424ead1cfc6b1de9856694deb3609f37402`. Each run completed seven model drafts and one fallback. The post-change comparison was reversed in arm order as planned.

The U.S. product-label error was a separate, high-consequence defect: a postcondition hardcoded PMRA/Canadian registration even when the user explicitly named a U.S. field. The bounded repair recognizes explicit U.S. jurisdiction and withholds a pesticide/rate decision pending exact product, [current EPA-registered labeling](https://www.epa.gov/pesticide-labels/introduction-pesticide-labels), crop/site, target and applicable state requirements. It leaves the Canadian label boundary intact. A product-path replay of the previously failed U.S. control returned that U.S. boundary with zero model drafts and no fallback. This is a post-hoc safety fix, not a card win or a new unbiased evaluation.

## Decision and next research gate

**Do not activate the nine-card candidate.** On the first independent transfer cohort it added no complete answers and two material errors; on confirmation it completed no case; context delivery was unreliable; and the exposed lexical selector repair failed independent confirmation. The cards may supply useful partial claims when applicable, but that does not meet the preregistered answer-quality or safety gate. The public corpus and policy remain non-active development assets.

The next candidate should make `farm_business` and crop-production methods explicit in the capability/context contract, distinguish method transfer from local authority, and add U.S. and Canadian source coverage where the current jurisdiction filter correctly refuses transfer. In particular, the present cards have no U.S. GDD or break-even counterpart and no Saskatchewan-specific seeding-method card. Design that representation and source/rights package before another retrieval change; compare it against a separately authored, still-unseen cohort and require no unsafe regression. Do not tune another keyword list on these exposed answers.

Limits: two small authored development cohorts, one pinned local model, one blind grader per cohort, no independent field outcomes or calibrated agronomist panel, and some external source pages with incomplete direct-fetch receipts. Card presence and individual claim coverage do not prove the model used the card correctly. All null, fallback and failed selector observations are retained; no activation or general competence claim follows.
