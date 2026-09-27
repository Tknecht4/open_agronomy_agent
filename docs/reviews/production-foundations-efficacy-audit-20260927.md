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
