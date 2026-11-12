# Independent review of PR 130

November 12, 2026. Reviewed source: `418f73b`, against main `0cacde7`.

This fresh review challenged the earlier completion assessment with compound
requests, counterfactual evidence and primary agronomic sources. The prior
33/33 automated completion labels were development evidence, not an accuracy
or field-qualification pass.

## Findings and repairs

| Finding | Repair and evidence |
| --- | --- |
| First-match observation recovery omitted another explicitly requested method. A global pixel/buffer exclusion also suppressed an independent planted-area question. | Compose recognized methods and their facets; retain each contradiction check. Scope footprint exclusions to the relevant area clause. Persisted production-seam tests cover combined requests. |
| A mixed pesticide and nutrient rate request selected fertility evidence instead of retaining pesticide stages, pressure and history. It could report minimum evidence satisfied with only fertility and label records. | Require both field-evidence lanes. Numeric nutrient proposals, including decimal quantities and common uppercase P/K/S/P2O5/K2O shorthand, retain the nutrient lane. |
| A historical nitrogen-rate phrase created a new fertilizer request inside a current herbicide question. | Bind quantity obligations to request clauses; retain historical facts without inventing a second requested rate. |
| Explicit `False` diagnostic-confirmation values satisfied the shared evidence-presence check. This defect preceded PR 130. | Negative confirmation cannot satisfy an evidence requirement. Numeric zero remains distinct. |
| Healthy potato monitoring received an invented collapse/wet-weather scenario and a categorical negative lead. | Keep collapse differentials conditional on collapse/wilting; give healthy-crop monitoring and local prevention checks otherwise. |
| Canonically recognized plural haskap names did not receive the crop-guide method. | Reuse canonical crop identity at request time, preserving existing source compatibility and avoiding an import-time dependency cycle. |

The initial added regressions failed in 22 cases with 41 passing. A separate
healthy-potato regression and three original-source alias probes reproduced
additional gaps. Follow-up scope and numeric-proposal failures were retained.
After correction, the focused source/context/rendering/answerability selection
passed 375 tests. An intermediate full-suite run was stopped because source
changed after it started; it does not qualify the final composed revision.
A subsequent full local run passed 3,799 tests but failed nine localhost
server tests because the sandbox denied socket binding; this is retained as a
failed attempt. The first native regression run completed 58/58 cells with no
failed execution checks. Common fertilizer-symbol probes then exposed five
additional request forms missing the nutrient lane. Fresh final-source
full-suite, expanded 80-cell model and exact-head CI receipts are retained
with the PR.

## Agronomic source review

The repairs preserve diagnosis and application boundaries while supplying
useful observations. The following distinctions were checked and clarified:

- [NASA HLS harmonization](https://hls.gsfc.nasa.gov/algorithms/) supports
  cross-sensor comparisons when processing, QA and spatial support are
  appropriate; it does not eliminate measurement uncertainty or establish
  crop cause or yield. Requiring identical sensors would be unnecessarily
  restrictive.
- [Manitoba pea-aphid guidance](https://www.gov.mb.ca/agriculture/crops/insects/pubs/aphids-on-peas-factsheet-revised-june2023.pdf)
  supports representative interior sampling, matching threshold units and
  stage-specific interpretation. Its historical numeric assumptions do not
  become a current prescription. Bloom and label restrictions remain relevant.
- [Alberta's clubroot plan](https://www.alberta.ca/alberta-clubroot-management-plan)
  supports persistent inoculum, nonhost rotations and soil-movement controls.
  A year without canola is not equivalent to excluding all susceptible
  brassicas, volunteers and weed hosts. Local requirements still control.
- [Minnesota late-blight monitoring](https://extension.umn.edu/agriculture/specialty-crops/vegetable-farming/disease-management/late-blight)
  supports early scouting of leaves and stems and prompt diagnostic contact.
  [Manitoba's management guidance](https://www.gov.mb.ca/agriculture/crops/plant-diseases/mgmt-late-blight-potatoes.html)
  connects prevention timing to scouting, forecasts and crop development;
  visible collapse is not required before prevention planning. These general
  methods supply no cross-jurisdiction product authority.
- [USask haskap guidance](https://gardening.usask.ca/gardening-advice/gardenline-nested-pages/food-plant-pages/fruit/haskap.php)
  supports compatible cross-pollination with overlapping bloom.
  [Iowa State's fruit guidance](https://yardandgarden.extension.iastate.edu/how-to/pollination-requirements-tree-and-small-fruits)
  distinguishes self-fruitful raspberries. A generic perennial-berry method
  must check the crop's requirements rather than require another cultivar
  for every berry crop. No regional fertilizer amounts were transferred.
- [NRCS water-quality guidance](https://www.nrcs.usda.gov/sites/default/files/2022-11/WA-Irrigation-Guide_4.pdf)
  supports joint EC/SAR interpretation for infiltration. A dated water
  sample does not establish season-long operation or a soil-sodicity diagnosis.

Mapped signals remain screening evidence. Their source, metric, time and spatial
support must be verified rather than assuming every crop-health layer is
regional or weather-modelled. Crop-specific diagnosis, economic thresholds,
label authority and calibrated quantities remain separate requirements.

## Evidence boundaries

The original 50 cases and eight exposed paraphrases remain regression cohorts.
Twelve review probes were frozen before production edits; ten later probes
record further review-informed edge cases, including fertilizer shorthand and
possessive-language controls. They are exposed development cases,
not an independent holdout. Raw answers, rubric bindings, rejected hypotheses,
failed/partial attempts and final-source receipts remain private.

The maintained runner exercises the actual native MLX production seam; canonical
analysis binds semantic reviews as automated triage. Source checking by an AI
reviewer is not human agronomic qualification. Serving pins, budgets and active
retrieval data are unchanged; references and evaluation criteria were not
admitted to runtime retrieval or training. An installed native release and
real-farm outcomes remain separate qualifications.
