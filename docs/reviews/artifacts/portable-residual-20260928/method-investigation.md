# METHOD family selection contrast investigation

Status: project-authored, exploratory development evidence, 2026-09-28. The candidate METHOD profile is inactive. This investigation changes no runtime selector, tests, config, or historical evaluation records.

## Reference and question

The reference selector is `requested_methods(question)` in `src/agronomy_agent/method_context.py` on branch `codex/residual-risk-investigation` at base `3ff64813ce14833f3c819044b96ebda738a60cbe`. It supports exactly seven families: `seed_mass`, `thermal_time`, `partial_budget`, `enterprise_budget`, `liquidity`, `cash_flow`, and `nutrient_plan_inputs`. The seven METHOD cards are an independently configured, context-only candidate; an admitted card has general-method scope, never field-action authority.

The exposed PFMH3 record already showed delivery of a METHOD card on 7/7 positive cases but wrong family on two: the balance-sheet request PFMH3-05 expected liquidity and received `method_cash_flow`; the dated cash-plan request PFMH3-06 expected cash flow and received `method_enterprise_budget`. This is a selection defect distinct from answer quality. The historical candidate also produced three new materially wrong finance answers and failed its preregistered gate. The answers cannot establish that the two family errors caused those answer failures. The post-removal local model ablation completed 0/12 generations, so it cannot settle that question either.

## Predeclared contrasts and measurement

I wrote [method-contrasts.json](method-contrasts.json) before calling the selector. Its SHA-256 is `d7c676376b178ed97c5809c68e549357507453a90be0d9bfbc619c3ad3ecbe34`. **Before-selector label seal status:** this hash was recorded before the current selector probe ran; it does not make the labels independent, source-distinct, or held out. The 47 questions include two explicit tasks per family, seven incidental topic mentions, seven negations, six multiple-task requests, six underspecified requests labelled abstain, and seven cross-family contrasts. Labels mean the method family needed to answer the *requested general-method task*; an empty set means no family obligation should be created. A specific local decision can still require ordinary evidence, even with an empty method set. The contrast set is authored after the PFMH3 failures were known and must never enter runtime retrieval or training.

The read-only [probe](method_probe.py) calls the unchanged selector and writes [method-analysis.json](method-analysis.json). Family precision and recall count family memberships, including multiple-family questions. Exact match compares each full set. Null recall means a group contains no positive labels.

| Group | Cases | Exact | Family TP / FP / FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|
| Explicit | 14 | 12 | 12 / 0 / 2 | 1.00 | 0.857 |
| Topic only | 7 | 0 | 0 / 7 / 0 | 0 | — |
| Negated | 7 | 0 | 0 / 7 / 0 | 0 | — |
| Multiple | 6 | 3 | 9 / 1 / 2 | 0.90 | 0.818 |
| Abstain | 6 | 4 | 0 / 2 / 0 | 0 | — |
| Contrast | 7 | 0 | 3 / 7 / 4 | 0.30 | 0.429 |
| **Total** | **47** | **19** | **24 / 24 / 8** | **0.50** | **0.75** |

By family, `cash_flow` had 0 TP, 5 FP and 6 FN in this set. `enterprise_budget` had 5 TP and 6 FP; `liquidity` had 5 TP, 2 FP and 1 FN. These are small, authored samples, not population estimates. The supported-family set is complete at seven; no missing card family explains the errors.

## Failure patterns and consumer impact

`requested_methods` searches the entire raw question with family regexes and then adds three cross-token conjunctions. It does not represent what the user asked the system to do, which clause is background, whether a clause is negated, or whether the method is underspecified. The balance-sheet PFMH3-05 text matches the cash-flow regex through “bills fall due before ... grain is sold,” while it never says `current ratio`, `working capital`, or another liquidity trigger. The cash-plan PFMH3-06 text matches `enterprise_budget` through “farm budget,” while “lay out a cash plan” has no cash-flow trigger. In the new contrasts, C01 and C02 reproduce those semantic substitutions; C03–C07 show related background-term leakage.

The method set has two direct consumers. `build_decision_contract(..., method_context_enabled=True)` creates one method-only evidence obligation and retrieval query per selected family. `method_fit_reason` calls the same selector to admit reviewed cards when the target is in Canada or the US and the operation site is resolved. Downstream, `obligation_coverage` permits a METHOD card to fill only a matching METHOD obligation, and the evidence packet can mark that slot `ADEQUATE` for explanation-only support. That separation protects local authority but cannot correct a wrongly identified user task.

Model-free candidate-profile spot checks confirmed the propagation: PFMH3-05 made a `method:cash_flow` obligation and selected `method_cash_flow`; PFMH3-06 made `method:enterprise_budget` and selected `method_enterprise_budget`. New T06, which merely asks about a brochure author in Alberta, made `method:liquidity`, selected `method_liquidity`, and marked that irrelevant method slot `ADEQUATE`. M02 requested liquidity plus a monthly cash schedule but made only `method:liquidity`. E12's dated cash-plan task made no method obligation. These checks do not call the model or grade final answers. A separate E09 check selected the correct liquidity family but placed no METHOD card in final context because the question had no resolved country; country applicability is a separate gate. The original terminal observations were not serialized. [The consumer probe](method-consumer-probe.py) reruns exactly these six fixtures on the same HEAD, with source, fixture, profile, support, obligation, card, applicability, and coverage metadata in [its result](method-consumer-results.json). The result explicitly identifies itself as a rerun.

## Smallest generalizable candidate to test

Replace the string-to-family match as the authority for both consumers with one typed, question-only **method task frame**. Each family entry should carry a requested task span, an operation such as explain/compare/calculate/organize/schedule, and a disposition: requested, background, negated, or unresolved. Compile METHOD obligations only from requested entries; reuse exactly that frame for card fit. Keep existing source-support, country, site, and method-only authority checks. Return no family obligation for unresolved requests and ask for task clarification or use the ordinary answer path. A comparison that explicitly asks how two methods differ can legitimately select both.

The first implementation should establish clause scope and explicit user intent before family mapping, then validate on independently authored questions spanning all seven families and mixed requests. This is a representation/interface change, not a wider keyword list. Counterexamples that must remain in a fresh evaluation include “Do not *omit* a cash plan” (surface negation reverses meaning), “Why does this document say ‘no partial budget’?” (quoted text is background), “Compare a partial budget with an enterprise budget” (both requested), and “Can this farm afford it?” (finance topic without a specified method). A frame inferred solely by another unchecked model would need its own abstention and provenance contract.

## Checks and limits

- `PYTHONPATH=src .venv/bin/python docs/reviews/artifacts/portable-residual-20260928/method_probe.py` completed and wrote the 47 per-case observations and aggregate metrics. Its result embeds the fixed label and selector hashes.
- `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_method_transfer_candidate.py` passed: 9 focused tests. These tests cover existing boundary behavior but do not assert task-versus-background or negation semantics.
- `PYTHONPATH=src .venv/bin/python docs/reviews/artifacts/portable-residual-20260928/method-consumer-probe.py` reran the same six model-free `build_context` checks and captured the T06 coverage status. It pins HEAD `3ff64813ce14833f3c819044b96ebda738a60cbe` and input/source hashes. No generation, answer quality, active-profile change, or source-distinct efficacy result is claimed.

Residual risk: The authored labels involve judgment; some vague requests could reasonably be clarified rather than assigned an empty method set. A task-frame candidate can still miss paraphrases, negation scope, multi-clause dependencies and retrieval delivery. It needs a new independent contrast cohort and product-path safety assessment before any activation discussion.

Changed | Contrast labels, selector and consumer probes/results, this note only. Verified | Fixed-label selector probe, focused tests, model-free consumer rerun. Residual Risk | Exploratory labels, incomplete language coverage, no answer benefit evidence. Memory Delta | None.
