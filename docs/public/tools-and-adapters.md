# Tools and adapters

The agent has three materially different capability classes: deterministic local tools, decision guards, and optional public/local-data adapters. Their outputs have different authority and availability. All should produce a typed invocation/result receipt that can be consumed by generation, validation, trace, persistence, and evaluation.

## Structured calculator

**Implemented:** typed decimal calculations for unit conversion, seed/fertilizer/nutrient quantities, sprayer/tank/area operations, growing degree days, row population, weighted averages, and partial budgets. A bounded planner recognizes explicit supported arithmetic requests; it does not infer targets or fill missing material inputs.

**Tested:** deterministic executor, API/adapter and registry contracts, plus a natural-language question through planner, tool receipt, evidence context, final answer, and trace-facing metadata.

**Benchmark evidence:** RC1's 16 objective questions exercised natural-language routing, but the governed arm did not invoke the calculator and scored 0/16 for all candidates. The canonical registry therefore marks the calculator itself as **not benchmark-exercised**. This is a retained orchestration failure—not evidence that the arithmetic engine itself is wrong.

**Boundary:** the calculator uses supplied or explicitly stated inputs. It does not choose a target, diagnose a field, confirm a label, or establish suitability. The repaired path has focused automated coverage but has not completed a post-RC1 benchmark round.

```bash
PYTHONPATH=src python -m agronomy_agent.tool_cli calculate unit_conversion \
  --inputs-json '{"value":100,"from_unit":"kg/ha","to_unit":"lb/ac"}'
```

## Guard capabilities

Guards add field-data, fertility, weather, label, product-safety, resistance, soil-structure, salinity/sodicity, or 4R decision checks. They supply boundaries and missing-input logic, not missing observations. RC1 showed that broad whole-answer intervention can reduce usefulness for capable models, so the upgrade policy applies safeguards according to claim/action consequence rather than simply the presence of any missing field evidence.

## Public and local-data adapters

| Family | Examples | Availability | Boundary |
|---|---|---|---|
| Weather/climate | NASA POWER, Daymet, Canadian agroclimate lanes | Live provider or dated cache | Gridded context; not a field sensor or guaranteed forecast |
| Evapotranspiration | OpenET and Canadian source lane | Credential/provider or explicit unavailable result | Planning prior, not irrigation prescription or water-right record |
| Soil/land cover | NRCS/CanSIS/AAFC, packaged Prairie layers | Geography, network/cache, or installed pack | Mapped/classified prior, not point truth or lab result |
| Crop statistics | NASS/Statistics Canada snapshots or queries | Credential/provider/cache dependent | Regional context, not a field yield |
| Product metadata | EPA PPLS/Health Canada PMRA paths | Provider/cache/jurisdiction dependent | Discovery metadata; always confirm the current applicable label |

Offline-fixture tests verify routing, normalization, credential/error handling, and declared boundaries. They do not prove current provider uptime, exhaustive coverage, or agronomic validity.

## Offline behavior

Every capability declares whether it is local, network-required, or cache-capable. Offline operation blocks public calls before execution. A missing adapter returns an explicit unavailable/blocked state; it must never be replaced by a fabricated current value.

## Adding a capability

Use the [developer extension contract](developer/extending.md#add-a-tool-or-adapter) and [`src/agronomy_agent/tools/README.md`](https://github.com/Tknecht4/open_agronomy_agent/blob/main/src/agronomy_agent/tools/README.md). One canonical specification should drive/check all surfaces. Do not add a chat-specific regex and call that a complete tool integration.
