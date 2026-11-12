# Independent review of PR 131

November 12, 2026. Reviewed head `0d2d40e`, against main `0a50562`.
This review checks the production request path, agronomic meaning, refusal
scope and retained evidence independently of the earlier automated labels.

## Findings and repairs

1. **Unasked rate instructions survived ordinary notation and formatting.**
   The new terminology permission correctly avoids an application-authority
   hold, but its output cleanup missed milligram rates, leading-decimal amounts,
   percentages, emphasis and numbered instructions. A known historical quantity
   could therefore remain an unasked instruction. Keep decimal quantities intact,
   inspect a formatting-free matching view and include mass/concentration bases.
   Remove the original instruction bytes, preserving the retained explanation.
   Marked hypothetical examples and conversion instructions remain explanations.
   Tests exercise verification, independent safety postconditions and persisted
   production turns; changing history into permission remains disallowed.

2. **Date-role checking both over-intervened and missed a conflation.**
   Correct statements that processing was unavailable or could not be inferred
   acquired a factual-error flag. Conversely, an explicit statement equating the
   report issuance date with the analysis date escaped the guard, especially when
   the question mentioned analysis. Recognize those uncertainty statements and
   analysis-role assertions. A question about an analysis date does not supply
   one; a separately declared analysis event does. Positive retention controls,
   negative inference controls and persisted turns cover both directions.

3. **Root swelling was being promoted into a crop-independent clubroot concern.**
   The added word-order alias routed soybean, corn, carrot and potato symptoms
   into clubroot containment without a stated concern or susceptible-crop context.
   Require a supported brassica context for symptom-only selection. Preserve an
   explicit clubroot concern, including contaminated-soil precautions in a
   rotation crop. Unknown crop identity is not a susceptible-host observation.
   The soybean production prompt and persisted answer now avoid that injected
   decision. This selector is not an exhaustive host-range classifier.
   The prompt's containment requirements now use applicable local guidance too,
   matching the final-answer boundary without assuming a province.

The first two regression groups reproduced 14 failures; the crop group reproduced
four more. Failed attempts are retained privately. The final focused selection
covers conceptual routing, evidence selection, quantity verification, answerability,
observation guidance and execution receipts. Full source and packaging gates are
tracked at the final PR head; their terminal receipts remain separate from the
historical model study.

## Agronomic and refusal assessment

The texture/structure distinction agrees with the
[NRCS structure guidance](https://www.nrcs.usda.gov/sites/default/files/2022-10/Soil%20Structure%20and%20Macropores.pdf).
General definitions do not require a grower's field measurement. Trial
interpretation should preserve site-year relevance and statistical uncertainty,
rather than infer broad superiority from one rank; [Seed Manitoba](https://seedmb.ca/trials/oilseed-crops/soybeans/)
also cautions against one-year yield and maturity inference and incompatible
table comparisons. No ranking, trial result or new field rate is supplied here.

[Alberta's clubroot plan](https://www.alberta.ca/alberta-clubroot-management-plan)
supports the susceptible-crop distinction, confirmation and precautions against
soil movement. Root swelling does not itself establish a cause.
[Iowa State's scouting methods](https://crops.extension.iastate.edu/encyclopedia/soybean-aphid)
distinguish representative field observations, action thresholds and resampling.
Their crop-specific numeric thresholds are not transferred. Label terminology
can be explained without choosing an application; current use directions remain
separate, consistent with [EPA's label guidance](https://www.epa.gov/pesticide-labels/introduction-pesticide-labels).

Read all 15 changed product finals from the retained Colab comparison, including
the concise healthy-potato and date answers. Their bounded meanings support the
observed repairs. Rechecked canonical retention for 87 product and 32 diagnostic
observations, plus persistence and all 17 stages for 87 product and 24 governed
diagnostic turns. Replaying only the revised rate/date screens against the
recorded production finals introduced no new flag or removal. This replay does
not rerun generation, reproduce whole-pipeline behavior or create new grades.

Keep the scoped explanation permissions and factual verification. The retained
ablation panel does not support globally disabling refusal or verification.
Actual field diagnosis, product choice and follow-on application requests retain
their authority checks. Model pins, generation budgets, runtime corpus admission,
evaluation rubrics and qualification policies are unchanged.

## Evidence boundary

The original GPU observations remain bound to runtime commit `fb2bc78`, not this
review's successor fixes. No new GPU run was performed for these bounded parser
and selector repairs. Source tests impose synthetic backend text and inspect the
actual persisted production path; they do not establish model or field efficacy.
The original ambiguous probe remains unknown, while its explicit task scopes
retain their original observations. Smoke-profile reference comparisons remain
blocked and expert domain metrics remain pending. No expert, holdout, native
installation or field qualification is claimed.
