# Tools and capabilities

## Purpose and status

This package contains query-triggered guard tools and participates in the wider capability system. Deterministic calculations and public-data adapters also live in `agronomic_calculations.py`, `local_tools.py`, `skill_registry.py`, `agno_runtime/tool_adapters.py`, and server services. That historical fragmentation is why the canonical capability registry is the extension authority going forward.

## Capability kinds

| Kind | Example | Authority boundary |
|---|---|---|
| Guard | field-data or label guard | Adds decision checks; does not supply missing facts |
| Deterministic tool | agronomic calculator | Computes from supplied typed inputs; does not choose a target or legal rate |
| Public adapter | weather, statistics, soil survey, label metadata | Adds dated provider context; availability and jurisdiction remain explicit |
| Local data capability | field history or packaged spatial prior | Reads authorized local state; map output is not a sample |
| Administrative probe | route/retrieval debug | Diagnostics only; not a user-facing agronomic capability |

## Canonical contract

A capability definition should own:

- stable ID and semantic version;
- kind, display name, owner, and status;
- typed input and output schemas;
- executor identity;
- network/offline/cache policy and credentials declaration;
- evidence authority, jurisdiction, freshness, risk, and limitations;
- planner trigger/requirements metadata;
- verifier and renderer adapters;
- CLI/HTTP/Agno exposure flags; and
- focused, parity, natural-language, and failure-mode tests.

CLI, HTTP, readiness, trace, and documentation surfaces should be derived from or checked against this contract. A capability is not “implemented in chat” merely because a function, adapter, endpoint, or config flag exists.

## Add a tool

1. Define the capability contract and typed schemas.
2. Implement a side-effect-bounded executor returning a typed invocation result and stable result ID.
3. Declare offline/network/cache, evidence authority, risk, freshness, and error states.
4. Connect the planner, evidence packet, verifier, renderer, trace, and persistence through the shared result—not custom prompt text.
5. Expose only the declared CLI/HTTP/Agno surfaces.
6. Add parity tests, deterministic executor tests, natural-language selection/execution tests, verifier tests, and offline/provider-failure tests.
7. Regenerate or check the public capability table.

A compliant addition should require one implementation, one contract, and tests—not manual edits to every registry.

## Calculator exemplar

The calculator takes an operation and a typed input object, uses decimal arithmetic, validates units/ranges, and returns formula, value, unit, assumptions, and boundary. It verifies arithmetic only. A natural-language request is complete only when the planner invokes it, the same result identity reaches evidence/validation/trace, and the final answer contains the parseable result.

The v2 calculator adds explicit crop-establishment, growing-degree-day, partial-budget,
break-even, farm-ratio, nitrogen-product field-total and soil-water-storage forms.
Field totals combine the existing nutrient-to-product and area-total calculations.
Soil-water storage multiplies supplied volumetric water content by uniform layer
depth and preserves the distinction from plant-available water. It uses only
numbers supplied in the question.
Missing or invalid inputs yield a specific clarification. Currency, area,
yield, and cost basis remain attached to the result. The Manitoba published
factor-10 imperial seeding approximation and exact dimensional conversion are
shown as distinct methods; they can differ. A computed scenario is not a
current quote, observed field outcome, or regulated rate.

The v6 planner wrapper can retain a seed-survival clarification while executing
two conditional v5 calculator children. This requires an otherwise complete
pure seed calculation, valid supplied germination and a sole unqualified-survival
basis gap. The parent `clarification_scenarios` record has its own schema and
provenance, retains the original missing input and contains no selected scalar
or basis. Its evidence coverage stays PARTIAL. Each child retains its exact
assumed basis, input values, imperial method if applicable, result and content
hash. Exact replay qualifies the response; altered child values, IDs or prose
cannot inherit the bypass. Readiness remains non-executing, and choosing a basis
in the next user turn produces the ordinary single-result calculation.
The structured single-calculation API still requires a denominator.

The v5 calculator exposes 46 structured operations. Its supplied-model
forms cover seed count and physical-seed mass, zoned cost changes, incremental
margin, soil carbon and nitrate-N stocks, total porosity, available-N budgets,
daily water balances, reflectance NDVI, land equivalent ratio, paired yield
differences, lime equivalence and an explicitly simplified stress-ET model.
`supplied_model_arithmetic.py` owns typed validation and formulas;
`supplied_model_parser.py` owns bounded natural-language extraction and whole
request completeness. Not every structured input spelling has a conversational
parser. Unsupported qualifiers or extra instructions cannot inherit a
model-free result. For recognized supported forms, missing or incompatible
inputs produce a clarification.

The supplied `allowable_water_depletion` operation multiplies total available
water in millimetres by a supplied depletion fraction. It reports an allowable
depletion amount under that assumption. This is FAO readily available water
(RAW) only when the fraction denotes the no-stress depletion fraction; a
management-allowed limit may differ. The operation selects no field fraction,
irrigation date or application depth. See the
[evaluation guide](../../../docs/public/operations/release-evaluation.md)
for the relationship, source and interpretation limits.

Material and measurement bases matter. Carbon stock requires a supplied coarse-
fragment volume; nitrate stock is conditional on matching dry-soil mass support.
Porosity requires dry bulk density and matching soil-solid particle density.
Neither is plant-available water or a crop-available nutrient credit. Intercrop
yields are per total intercrop area, and each named crop appears once. A paired
mean is not a significance test. Lime conversion requires an already supplied
pure-CaCO3-equivalent target and applicable effective product quality; it cannot
infer the target. The simplified stress multiplier applies to all ET only when
explicitly requested, rather than representing a dual-coefficient crop model.
An explicit incremental-budget break-even calculation retains the supplied
intervention cost basis; it is not a whole-farm profitability forecast. A missing
partial-budget component remains unknown even when the other unit bases agree.
These results retain their assumptions and do not establish measured conditions,
profit, a field recommendation or product authorization.

```bash
PYTHONPATH=src python -m agronomy_agent.tool_cli calculate unit_conversion \
  --inputs-json '{"value":100,"from_unit":"kg/ha","to_unit":"lb/ac"}'
```

## Invariants

- Never infer omitted numeric inputs.
- Never turn a map, cached response, or regional statistic into field measurement.
- Network access is declared and checked before execution.
- Provider errors and stale/unavailable caches remain visible.
- Current labels/regulations require current applicable authority.
- Every invocation/result identity is shared across generation, validation, rendering, persistence, and evaluation.

## Validation

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_agronomic_calculations.py \
  tests/test_public_tool_adapters.py \
  tests/test_evidence_handshake.py
```

Unit tests prove executor behavior. Add a conversational path test before claiming the capability is available to user questions.

## Failure modes

Expected statuses include invalid input, missing input, unsupported operation, blocked offline, provider not configured, provider unavailable, stale cache, out-of-scope jurisdiction, and verifier rejection. Unknown required capabilities and duplicate aliases should fail startup/preflight rather than disappear.

Seedling loss is not automatically the complement of overall emergence.
The two-scenario clarification requires directly supplied survival; mortality
inputs do not gain that path. A stage-specific seedling loss needs actual
overall emergence or an explicit loss definition among germinated seeds. The
parser and short follow-up resolver do not turn its complement into a supplied
overall survival fact. Explicit post-germination mortality remains supported.
