# `agronomy_agent` package

## Purpose and status

This package owns the local agent kernel, routing, evidence contracts, retrieval integration, model adapters, validation, traces, persistence-facing services, and deterministic capabilities. It is active development code. Public behavior should be described from executable contracts and tests, not from a filename or historical phase label alone.

## Canonical request flow

The supported cockpit composes the system through `server/app.py`. A normal answer follows these conceptual stages:

1. bind the question to available field and session context;
2. classify intent, risk, namespaces, and capability needs;
3. collect governed retrieval, graph hints, field history, and eligible capability results;
4. pack bounded context for the configured local model;
5. generate a draft;
6. validate evidence use and consequence-sensitive boundaries;
7. render the answer, source cards, and trace; and
8. persist immutable observations and answer lineage.

`agent.py` still coordinates several of these stages directly. The stage list is an architectural contract, not a claim that each stage is already independently replaceable.

## Package map

| Area | Entry points | Responsibility |
|---|---|---|
| Kernel | `agent.py`, `context_packer.py` | Resource loading, context construction, prompts, generation, intervention |
| Routing | `router.py`, `decision_route.py`, `decision_contract.py`, `capability_planner.py` | Question type, risk, namespaces, evidence obligations, and capability plans |
| Evidence | `evidence_contracts.py`, `evidence_handshake.py`, `evidence_authority.py` | Typed provenance, applicability, coverage, and validated-answer records |
| Validation | `answer_verifier.py`, `answer_safety.py`, `high_consequence.py` | Evidence and action-boundary checks |
| Execution receipts | `execution_core.py`, `benchmark_rehearsal.py` | Typed production-path requests/results, fail-closed stage receipts, and claim-ineligible rehearsals |
| Capabilities | `skill_registry.py`, `tools/`, `local_tools.py`, `agronomic_calculations.py` | Guard notes, deterministic calculations, and public adapters |
| Shared GIS/imagery/terrain | `geospatial/` | Library-backed geometry/CRS/imports, source/access catalog, bounded metadata discovery, raster support/statistics and offline terrain derivatives; see its README |
| Runtime adapters | `agno_runtime/` | Local retrieval/graph/model/tool/trace adapters |
| Application | `server/` | FastAPI composition, services, auth/network settings, storage |
| Field state | `field_events.py`, `field_measurements.py`, `query_context.py` | Append-oriented field observations and usable question context |
| Candidate method knowledge | `method_context.py`, `decision_contract.py` | Reviewed method IDs, source-bound draft background, and method-only coverage; enabled only by the non-active method profile |

## Inputs and outputs

- Inputs: a question, optional field/session identity, model and RAG configuration, admitted corpus/graph artifacts, and authorized capability inputs.
- Outputs: an answer, source/evidence records, route and validation state, tool receipts, model identity, and a persisted trace.
- Unknown field facts remain unknown. Absence must not silently become `0`, `false`, a diagnosis, or a locally calibrated recommendation.

## Invariants

- Preserve source identity, scope, time, jurisdiction, rights, and limitations through every transformation.
- Keep observations, model output, and system interpretation distinguishable.
- Evaluation questions and answers never become retrieval knowledge.
- Network use is explicit and blocked before execution in offline modes.
- A map or graph relationship is context, not field measurement or decision authority.
- High-consequence outputs require current applicable authority; validation cannot promote weak evidence.
- New versions append or supersede records; they do not rewrite historical traces.

Document applicability travels with selected excerpts, persisted source cards,
and structured answer caveats. If a slot cannot fit the complete policy and
applicability prefix plus a useful excerpt, it drops that document and records
the budget exclusion. `packed_doc_ids` identifies final packed sources; a
retrieval hit alone does not prove prompt delivery or correct use in prose.

Study-design and measurement-comparison questions can remain explanatory
without inheriting incidental field-diagnosis obligations. Mixed requests for
rates, treatments, or field actions retain their operational boundaries. A
same-country subregional study may support such an explanation only through
the explicit context-only named-study scope with retained applicability; this
does not establish transfer of its results to the user's farm.

Focused concept queries, bounded terminology expansions and bilingual equivalents
supplement the full request during document and graph retrieval; publication
metadata is not an exhaustive description of a passage. Scoped reference
passages may become primary evidence for an explanation, while their field-action
authority remains `not_authorized`. Country and explicit transfer limits still
apply. A bounded same-country sampling-method explanation can use a source from
another province; this does not admit its local calibration or prescribe a rate.

Intent checks distinguish confidence in a measurement from an application
quantity, measurement equivalence from treatment, and subsoil condition from a
request for subsoiling. Traffic fallback uses the requested operation and does
not invent a named field location. Verification flags instructions that destroy
an explicitly requested affected-versus-normal soil sampling contrast, even if
a later disclaimer follows. These bounded rules and lexical checks do not form
a general scientific correctness verifier; model answers still require review.

Explicit SoilERI interpretation keeps general erosion context separate from the
named specification. `named_regional_product_coverage` records whether that
source is indexed and retrieved; missing coverage is disclosed in the prompt
and answer without blocking qualified general explanations. This record does
not authorize source admission or promote general context into product facts.

## Extension procedure

- Add a capability through the canonical capability contract, executor, evidence contribution, and parity tests; see [`tools/README.md`](tools/README.md).
- Add graph data through a governed graph manifest and configured path; see [`agno_runtime/README.md`](agno_runtime/README.md).
- Add an API domain through a service boundary and thin route; see [`server/README.md`](server/README.md).
- Add a new evidence type by extending the typed contracts and every serialization/validation boundary. Do not inject untyped prompt text as a shortcut.

## Configuration

Runtime selection starts in `configs/`.
`configs/model.yaml` and `configs/rag.yaml` are the active release profiles;
`configs/runtime_profiles.json` is the selectable/default registry. Adding a
config file does not activate it. See [`configs/README.md`](../../configs/README.md)
before changing an active profile.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m compileall -q src scripts
```

Use focused tests while iterating, then run the full suite before making a system-wide claim. Benchmark results are bound to their exact implementation identity and do not automatically validate current code.

The cockpit's `run_turn` compatibility facade and the non-claim benchmark
rehearsal both call `execute_agent_request`. The shared result validates an
ordered, content-addressed receipt for routing, field context, public adapters,
document and graph observations, typed tools, prompt construction, risk
intervention, generation, verification, safety policy, high-consequence policy,
and final rendering. The observed-system adapter supports the complete
production configuration and the explicit document/graph retrieval 2×2; other
component ablations must fail instead of being reported as implemented.

This seam covers the persisted server answer pipeline. HTTP authorization and
configuration selection, hosted-message copying and metrics, image-research
routes, frontend presentation, and the legacy `agent.generate_answer` evaluator
remain outside it. Their parity requires separate integration evidence.

## Failure modes

The intended failure mode is explicit: setup-required model, blocked-offline adapter, excluded corpus, missing authority, insufficient evidence, failed validation, or persisted error trace. Silent graph omission, registry drift, untyped capability output, and fallback text presented as model reasoning are defects.

### Residual repair contracts

The verifier compares complete quantities rather than numeric substrings. Its
small arithmetic checker can validate an explicit question phrase binding container count and per-container
mass; arbitrary numerical reasoning still needs typed calculation evidence.
A matched number is not action authority. Diagnostic exclusion requires explicit
source exclusion, not a disease name appearing somewhere in the question.
Verifier replacement audit and claim edit ledger version 2 distinguish answer
review triggers from localized lexical triggers; neither asserts semantic proof
against every changed sentence.

For an explicit request to preserve an eligible supplied record, the verifier
checks requested quantities, basis, depth, attribution and date/calibration
unknowns before accepting an editor rewrite. A safe-looking rewrite can still
lose required facts. Rejected or failed editors can recover a bounded record
from complete positive assertions in allowed evidence, with one eligible
quantitative anchor and the existing answer-level checks. Wrapped claims and
records outside the requested field do not establish eligibility. Named-field
recovery supports provable one-token ASCII IDs; ambiguous, multiword or
non-ASCII names disable this recovery. These lexical checks can leave valid
unrecognized records unresolved and do not establish field truth or general
semantic completeness.

`observation_guidance.py` owns bounded observation-method requirements shared
by drafting, completeness review and fallback selection. Applicable methods
cover paired scouting, satellite comparability, empty terrain coverage, point
versus area geometry, crop-guide scope and regional stress interpretation.
Explicit missing method steps receive review even below the ordinary risk score
threshold; complete answers keep the existing thresholds. Authority holds reuse
reviewed procedural help without granting the blocked action. Product-label
cleanup can retain that reviewed help when replacing an unverified answer, but
cannot preserve arbitrary draft permissions or rates. These lexical method
checks do not establish complete scientific verification. Source rationale and
transfer limits are in the [field observation guide](../../docs/public/operations/field-observations.md).
Numeric-rate obligations distinguish pesticide scouting, stages and application
history from fertility tests and credits. Mixed pesticide/nutrient requests
retain the product-label and fertility authority lanes.
When a bounded observation method is incomplete or contradicts its own evidence
limit, a reviewed method can replace it before editing only after the normal
safety and requested-record preservation checks pass. Coverage words alone do
not validate an unsupported low-risk inference, and a correct boundary sentence
cannot validate a subsequent one-dimensional area claim. The final leak screen
preserves the ordinary phrase `source-water samples` while retaining identifier
and internal-control detection. Haskap/honeyberry crop identity also participates
in the existing live-reference compatibility filter.

The active verifier retains its risk-conditioned review thresholds. A proposed
advisory-only bypass was withdrawn after a paired development run exposed an
unsupported field-action recommendation. An unknown map type is not renamed as
a suitability product by a fallback.

Whole-request mechanism and differential-evidence explanations do not inherit
an operational checklist merely because they mention manure, salinity, seed
vigor or crusting. Personal field diagnosis, authority questions and follow-up
actions retain their normal requirements. This is bounded intent calibration,
not a general scientific verifier.

Clubroot soil biosecurity preserves reported history without inventing symptoms
in the current rotation crop. Capsule retrieval, route anchors and verifier
completeness checks require symptom confirmation only for a symptom or diagnosis
question. Soil-movement advice retains containment and equipment-cleaning checks;
generic crop-stage, weather and fresh plant-sample prerequisites do not belong
to a history-only hygiene request. The fallback keeps those scopes distinct. Current crop and symptom mentions are
separate from historical or negated observations; a tentative disease name
does not establish that the current crop is a susceptible host.

The supplied-input calculator also supports elemental/oxide P and K basis
conversion, apparent nutrient balances, and liquid-product totals. Named
quantities, units and nutrient bases must bind without conflicts; invalid or
ambiguous premises need clarification. Apparent balances do not establish
soil-test changes or losses, and product litres are distinct from carrier
volume. Readiness shares the execution validators. The saved answer and final
renderer preserve an exact, recomputed calculator result with its boundary;
neither a generation-path flag nor a plausible trace can bypass validation.
Default P/K reporting conversions use the four direction-specific factors in
[USDA NRCS National Agronomy Manual, Table 503-42](https://www.nrcs.usda.gov/sites/default/files/2022-10/National-Agronomy-Manual.pdf):
P→P2O5 2.2915, P2O5→P 0.4364, K→K2O 1.2045 and K2O→K 0.8302.
A supplied rounded factor is preserved when it has at least two significant
digits and lies within half its last decimal unit plus 0.01% of the reference
factor. This is an explicit engineering rounding policy, not a field safety
tolerance; inversion of a rounded forward factor is not used as the reference.
Whole-field product requests retain their area and total-mass output. The
calculation also shows product mass per hectare, so a request for both quantities
uses one checked operation. An input described as total area does not override an
explicit request for a per-hectare result. Unlabelled
numeric alternatives and multiple destination nutrient bases require clarification.
Universal requests to evade safety or authority remain blocked.

Water accounting uses supplied volumetric contents and uniform depth for
available capacity or refill deficit, standard-condition `ETc = Kc × ETo`,
supplied net depth/application efficiency, and depth/area volume. It does not
choose irrigation timing, stress coefficients or layered soil properties.
Single-nozzle calibration retains supplied spacing and flow without inventing
whole-boom width or nozzle count. Grain moisture adjustment conserves dry
matter, preserves any yield-area denominator and excludes handling losses;
storage and marketing targets must be supplied. A separate uncapped daily-mean
GDD operation uses the actual supplied mean and base, with a stated zero floor;
it cannot infer individually capped temperature extremes. These operations
share non-executing readiness validators and whole-request guards for extra
decisions, permission requests and unhandled questions. The historical v1
operation family remains distinct from the current calculator contract. Seed-mass arithmetic now uses the revised contract because its survival denominator must be explicit.
Grain harvest index divides supplied grain dry mass by total above-ground dry
biomass, including grain, on the same mass and area basis; both fraction and
percentage are shown. This follows the [FAO biomass/harvest-index definition](https://www.fao.org/4/y5146e/y5146e07.htm)
and does not set a crop-specific target or harvest date. Circular sampling area
uses a supplied radius and planar πr², reports square metres and hectares, and
explains why a sampling footprint is not a mapped field boundary. Diameter,
annulus, terrain-corrected and geodesic requests are outside that operation.

MLX adapters retain at most one target/draft model pair across serialized public
operations. Generators release temporary references after token counting,
warmup and generation, and reload if another pair displaced theirs. Pair changes
invalidate old KV namespaces. This bounds weight ownership by pair count, not
peak device memory; model changes can incur reload latency. Prompt caching remains
disabled in the active profile.

Scoped explanatory references are packed as complete passages or explicitly
dropped with a budget receipt. They can use otherwise available space within
the configured total context cap; their field-action authority stays unchanged.
A separate leading block of copied internal control labels can be removed
without rewriting the remaining prose only when the original has no other
verifier defect and the retained prose passes reassessment. The trace records
this localized cleanup separately from model editing and fallback.

The explanation repair also records isolated control-heading removal as
`verifier_localized_cleanup` throughout the production execution receipts.
It is neither an editor rewrite nor a verifier fallback. The quantity screen
normalizes a bounded set of source-matched ion charges and unit exponents across
plain, Unicode and LaTeX notation; annotation digits cannot authorize numerical
rates or scalar claims. This is typography equivalence, not chemical validation.
A bounded diagnostic sampling check rejects claims that separately attributable
area results remain recoverable after samples are pooled into one composite.
These checks do not constitute a general scientific correctness verifier.

Compound observation requests combine each recognized method's requirements and
contradiction checks. Instrument footprint terms in a separate request do not
suppress an explicitly asked planted-area method. Crop-guide recovery uses the
same canonical haskap identity as live-source compatibility. Mixed pesticide
and nutrient quantities retain both evidence lanes; historical rates do not
create a new requested fertilizer rate. Explicit negative confirmation flags
cannot satisfy evidence requirements, while a supplied numeric zero remains a
value. These bounded checks do not constitute a general scientific verifier.

Mixed pesticide and fertilizer requests share the quantity-subject check between
the evidence policy and final procedural support. Final label-safety replacement
must preserve both requested methods, including supported French guidance;
a complete machine-policy record alone does not establish a complete visible answer.

Seed-mass inputs distinguish overall establishment per seed sown from survival
per germinated seed. Overall emergence already includes germination; supplied
laboratory germination stays in the record and is not multiplied again.
Conditional survival requires a separate supplied germination percentage. Both
metric and imperial execution share the same validator with API readiness.
Unqualified survival or mortality needs a denominator clarification; conventional
emergence uses a visibly stated seeds-sown interpretation. No germination value
is invented, and no crop population or survival percentage is selected. See
[Manitoba's establishment definition](https://www.gov.mb.ca/agriculture/crops/crop-management/print,seeding-by-plant-population.html)
and [Canola Council's emergence basis](https://www.canolacouncil.org/canola-encyclopedia/plant-establishment/seeding-rate/).


### Complete arithmetic requests and observed crop roles

`supplied_numeric_inputs.py` owns ordinary decimal/comma-thousands token
boundaries shared by supplied, foundation and legacy extraction. A valid prefix
of a decimal comma, exponent, fraction or malformed token is never an operand.
The supplied parsers and seed/GDD owners bind every numeric token to an actual
operand, a recognized incidental role or a supported method constant. A
per-hectare product result may retain field area as context; an additional
nutrient flow, dry-matter loss, excluded sampling area or unknown output cannot
silently disappear. Unsupported compound units require clarification. Structured
GDD accepts only its explicit Celsius input keys, method and temperature unit.

`request_scope.py` positively qualifies complete explanatory/calculation request
clauses. Unknown trailing or coordinated commands return to ordinary decision
handling, including comma-separated requests and polite request wrappers.
Parser-owned arithmetic without an anchored request head still receives a full
tail check. A first output after a qualified arithmetic input declaration, closed assumption
or owned formula remains eligible; these prefixes do not authorize
a second output or an unknown command. The bypass accepts bounded
analytical continuations and explicit parameter declarations; it does not infer
that a word is analytical from its spelling. Leaving a bypass is not a refusal.

`plant_health_scope.py` preserves crop mentions while distinguishing the affected
crop from a healthy reference subject. Negative root observations retain their
actual wording: absence of galls does not imply absence of swelling. Decision
checks reject invented root signs and require an explicitly requested current
crop inspection alongside separate clubroot soil-history precautions. Fallbacks
preserve these roles rather than assigning the historical disease to the current
rotation crop.


A valid tool plan may contribute arithmetic evidence to a compound request.
`has_unqualified_followup` also controls answerability, model-free readiness and
`deterministic_tool_response`: completion requires the whole request. Legacy
daily GDD retains its verified sub-result for separately requested provenance or
stage interpretation, and for ordinary model handling of extra commands. Its
explicit `note` JSON key is text-only non-operative metadata; unknown numeric or
unit-bearing keys remain invalid. Closed negative constraints preserve the pure
calculation path rather than creating a new task.
