"""Typed, bounded capability planning for deterministic local tools.

Natural language extraction is deliberately limited to explicit arithmetic and
reviewed private-table queries. Ambiguous agronomic targets remain model/human
decisions and are never sent to an executor as if they were supplied facts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from agronomy_agent.agronomic_calculations import calculation_tool_schema
from agronomy_agent.calculator_contracts import CALCULATOR_VERSION, TOOL_PLANNER_VERSION, format_calculator_clarification, tool_version_for
from agronomy_agent.foundation_math_parser import _unsafe_action_request, parse_foundation_calculation


PLANNER_VERSION = TOOL_PLANNER_VERSION
TOOL_PLAN_SCHEMA_VERSION = "open_agronomy_agent.tool_plan.v1"
CALCULATOR_ID = "agronomic_calculator"
_NUMBER = r"([0-9][0-9,]*(?:\.[0-9]+)?)"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _identifier(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:24]}"


def _number(value: str) -> float:
    return float(value.replace(",", ""))


@dataclass(frozen=True)
class ToolInvocation:
    schema_version: str
    invocation_id: str
    planner_version: str
    tool_id: str
    tool_version: str
    operation: str
    inputs: Mapping[str, Any]
    question_sha256: str
    status: str
    missing_inputs: tuple[str, ...]
    authority_role: str
    risk_class: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResult:
    schema_version: str
    result_id: str
    invocation_id: str
    tool_id: str
    tool_version: str
    operation: str
    status: str
    payload: Mapping[str, Any]
    payload_sha256: str
    authority_role: str
    freshness_status: str
    provenance: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def answer(self) -> str:
        return str(self.payload.get("answer") or "").strip()


@dataclass(frozen=True)
class ToolPlan:
    schema_version: str
    planner_version: str
    status: str
    invocations: tuple[ToolInvocation, ...]
    clarification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_tools(question: str, *, field_context: Mapping[str, Any] | None = None) -> ToolPlan:
    """Plan explicit deterministic queries through registered capability contracts."""

    from agronomy_agent.field_data_capability import select_query, CAPABILITY_ID, CAPABILITY_VERSION, AUTHORITY_ROLE
    selected = select_query(question, field_context)
    if selected is not None:
        operation, inputs, missing, clarification = selected
        seed = {"planner_version": PLANNER_VERSION, "tool_id": CAPABILITY_ID,
                "tool_version": CAPABILITY_VERSION, "operation": operation, "inputs": inputs,
                "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest()}
        invocation = ToolInvocation(
            "open_agronomy_agent.tool_invocation.v1", _identifier("invocation", seed),
            PLANNER_VERSION, CAPABILITY_ID, CAPABILITY_VERSION, operation, inputs,
            seed["question_sha256"], "clarification_required" if missing else "planned",
            missing, AUTHORITY_ROLE, "low_arithmetic",
        )
        return ToolPlan(TOOL_PLAN_SCHEMA_VERSION, PLANNER_VERSION,
                        "clarification_required" if missing else "ready", (invocation,), clarification)
    parsed = _parse_calculation(question)
    if parsed is None:
        return ToolPlan(TOOL_PLAN_SCHEMA_VERSION, PLANNER_VERSION, "not_applicable", ())
    operation, inputs, missing = parsed
    tool_version = tool_version_for(operation)
    seed = {
        "planner_version": PLANNER_VERSION,
        "tool_id": CALCULATOR_ID,
        "tool_version": tool_version,
        "operation": operation,
        "inputs": inputs,
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
    }
    invocation = ToolInvocation(
        schema_version="open_agronomy_agent.tool_invocation.v1",
        invocation_id=_identifier("invocation", seed),
        planner_version=PLANNER_VERSION,
        tool_id=CALCULATOR_ID,
        tool_version=tool_version,
        operation=operation,
        inputs=inputs,
        question_sha256=seed["question_sha256"],
        status="clarification_required" if missing else "planned",
        missing_inputs=missing,
        authority_role="supplied_inputs_arithmetic_only",
        risk_class="low_arithmetic",
    )
    if missing:
        return ToolPlan(
            TOOL_PLAN_SCHEMA_VERSION,
            PLANNER_VERSION,
            "clarification_required",
            (invocation,),
            format_calculator_clarification(missing),
        )
    return ToolPlan(TOOL_PLAN_SCHEMA_VERSION, PLANNER_VERSION, "ready", (invocation,))


def execute_tool_plan(plan: ToolPlan) -> tuple[ToolResult, ...]:
    results: list[ToolResult] = []
    for invocation in plan.invocations:
        if invocation.status != "planned":
            continue
        from agronomy_agent.capability_registry import capability_registry, execute_registered_capability
        spec = capability_registry().require(invocation.tool_id)
        if spec.kind not in {"calculator", "local_data"}:
            raise ValueError(f"unsupported planned tool: {invocation.tool_id}")
        payload = execute_registered_capability(invocation.tool_id, {
            "operation": invocation.operation, "inputs": dict(invocation.inputs),
        })
        payload_sha256 = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        results.append(
            ToolResult(
                schema_version="open_agronomy_agent.tool_result.v1",
                result_id=_identifier(
                    "tool_result",
                    {
                        "invocation_id": invocation.invocation_id,
                        "payload_sha256": payload_sha256,
                    },
                ),
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                tool_version=invocation.tool_version,
                operation=invocation.operation,
                status=str(payload.get("status") or "calculated"),
                payload=payload,
                payload_sha256=payload_sha256,
                authority_role=invocation.authority_role,
                freshness_status="not_time_sensitive",
                provenance=("agronomy_agent.agronomic_calculations" if invocation.tool_id == CALCULATOR_ID else spec.executor_ref.split(":")[0]),
                limitations=(str(payload.get("boundary") or ""), *(str(item) for item in payload.get("limitations", ()))),
            )
        )
    return tuple(results)


def plan_and_execute_tools(
    question: str,
    *,
    field_context: Mapping[str, Any] | None = None,
) -> tuple[ToolPlan, tuple[ToolResult, ...]]:
    plan = plan_tools(question, field_context=field_context)
    return plan, execute_tool_plan(plan)


def calculator_contract() -> dict[str, Any]:
    return calculation_tool_schema()


def _parse_calculation(question: str) -> tuple[str, dict[str, Any], tuple[str, ...]] | None:
    text = " ".join(question.replace("−", "-").split())
    lower = text.casefold()
    if _unsafe_action_request(lower):
        return None
    if _explanation_or_method_request(lower) or _record_lookup_request(lower):
        return None
    foundation = parse_foundation_calculation(text)
    if foundation is not None and not foundation[2]:
        # The foundation parser has bound every required numeric input. Its
        # complete operation is stronger evidence of arithmetic intent than a
        # broad wording gate (for example, "saved costs" is a budget term).
        return foundation
    if foundation is not None and any(item.startswith("invalid ") for item in foundation[2]):
        # An identified operation with an invalid supplied input must retain
        # its typed clarification even when the wording contains a term such
        # as "measured" or "saved costs".
        return foundation
    parsers = (
        _parse_unit_conversion,
        _parse_seed_rate,
        _parse_sprayer_volume,
        _parse_tank_coverage,
        _parse_daily_gdd,
        _parse_accumulated_gdd,
        _parse_row_population,
        _parse_area_weighted_average,
        _parse_field_product_total,
        _parse_nutrient_delivery,
        _parse_fertilizer_product_mass,
    )
    legacy_clarification = None
    for parser in parsers:
        parsed = parser(text, lower)
        if parsed is not None:
            if not parsed[2]:
                return parsed
            legacy_clarification = legacy_clarification or parsed

    # A recognized operation with supplied operands retains its clarification
    # even if the question mentions a measured input or an unsupplied field.
    # Recognition without any bound operand still needs clear arithmetic
    # wording; this keeps saved-record lookups out of calculator prompts.
    if not _explicit_arithmetic_request(lower) and not (
        (foundation is not None and foundation[1])
        or (legacy_clarification is not None and legacy_clarification[1])
    ):
        return None

    if (
        foundation is not None
        and legacy_clarification is not None
        and foundation[0] == legacy_clarification[0]
        and foundation[1] == legacy_clarification[1]
    ):
        return legacy_clarification
    if foundation is not None:
        return foundation
    if legacy_clarification is not None:
        return legacy_clarification

    # A generic "what is" with a supplied measurement is not, by itself, a
    # request to calculate product mass or seed mass. These final clarifications
    # require an explicit calculation request; parsed numeric operations above
    # can still run from an operand-bearing "what is" question.
    if not _strong_arithmetic_request(lower):
        return None
    if any(token in lower for token in ("fertilizer", "urea", "map", "potash", "nitrogen", "p₂o₅", "k₂o")):
        return "fertilizer_product_mass", {}, (
            "the supplied nutrient target with units",
            "the product nutrient percentage or grade",
        )
    if "seed rate" in lower or ("plants/m²" in lower and "tkw" in lower):
        return "seed_rate_mass", {}, (
            "target plants/m²",
            "TKW in grams",
            "germination percent",
            "field survival or emergence percent",
        )
    return None


def _explicit_arithmetic_request(lower: str) -> bool:
    if _explanation_or_method_request(lower):
        return False
    explicit_operator = bool(re.search(r"\b(?:calculate|compute|convert|work out|arithmetic check)\b", lower))
    if explicit_operator:
        return True
    # Saved observations and lab values are lookup questions unless the user
    # explicitly asks to compute from them. "How many" alone can still be a
    # request to read a recorded count.
    if re.search(r"\b(?:saved|recorded|observed|measured|latest|previous|soil test|lab result)\b", lower):
        return False
    if _strong_arithmetic_request(lower):
        return True
    return bool(
        re.search(r"\bwhat is (?:the|one|this|five-day|area-weighted)\b", lower)
        and re.search(
            r"(?:\b(?:cad|usd)\s*|\$\s*)\d|"
            r"\d[\d,.]*\s*(?:%|°?c\b|kg\b|lb\b|l\b|m\b|ha\b|ac\b|plants?\b|bu\b|tonnes?\b)",
            lower,
        )
    )


def _explanation_or_method_request(lower: str) -> bool:
    if re.search(r"^\s*(?:what is the difference|why\b|how does\b|what does\b|explain\b|define\b)", lower):
        return True
    if re.search(r"^\s*(?:how (?:do|can|would) (?:i|we|you|one) (?:calculate|compute|work out)\b|how many (?:steps|inputs|factors|variables)\b)", lower):
        return True
    return bool(
        re.search(r"\b(?:formula|method|steps|factors|variables)\b", lower)
        and not re.search(r"\b(?:calculate|compute|convert|work out|arithmetic check|how many)\b", lower)
    )


def _record_lookup_request(lower: str) -> bool:
    return bool(re.search(
        r"^\s*what is (?:the|my|this) (?:current )?(?:recorded|saved|observed|measured|latest|previous)\b",
        lower,
    ))


def _strong_arithmetic_request(lower: str) -> bool:
    return bool(re.search(r"\b(?:calculate|compute|convert|work out|how many|arithmetic check|required in)\b", lower))


def _parse_unit_conversion(text: str, lower: str):  # noqa: ANN202
    if "convert" not in lower:
        return None
    match = re.search(
        rf"convert(?: a fertilizer rate of)?\s*{_NUMBER}\s*(kg/ha|lb/ac)"
        rf"(?:\s+of this (?:product|herbicide|fungicide|insecticide|pesticide) label rate)?"
        rf"\s+to\s+(kg/ha|lb/ac)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return "unit_conversion", {}, ("value", "from unit", "to unit")
    return "unit_conversion", {
        "value": _number(match.group(1)),
        "from_unit": match.group(2),
        "to_unit": match.group(3),
    }, ()


def _parse_seed_rate(text: str, lower: str):  # noqa: ANN202
    if "tkw" not in lower or "plants/m²" not in lower:
        return None
    target = re.search(rf"(?:target stand is|targets?)\s*{_NUMBER}\s*plants/m²", text, re.IGNORECASE)
    tkw = re.search(rf"tkw\s+is\s*{_NUMBER}\s*g", text, re.IGNORECASE)
    germination = re.search(rf"germination\s+is\s*{_NUMBER}%", text, re.IGNORECASE)
    survival = re.search(rf"expected (?:field survival|emergence)\s+is\s*{_NUMBER}%", text, re.IGNORECASE)
    values = {
        "target_plants_per_m2": target,
        "tkw_g": tkw,
        "germination_pct": germination,
        "field_survival_pct": survival,
    }
    missing = tuple(key for key, value in values.items() if value is None)
    inputs = {key: _number(value.group(1)) for key, value in values.items() if value is not None}
    return "seed_rate_mass", inputs, missing


def _parse_fertilizer_product_mass(text: str, lower: str):  # noqa: ANN202
    if not any(token in lower for token in ("supplies that", "urea supplies", "product-mass", "from urea", "from potash", "from a liquid product")):
        return None
    target = re.search(
        rf"(?:calls for|requires|for|supplies)\s*{_NUMBER}\s*kg\s*(N|P(?:₂|2)O(?:₅|5)|K(?:₂|2)O)/ha",
        text,
        re.IGNORECASE,
    )
    grade = re.search(r"(?:labelled|grade(?:d)?|a)\s*(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    percent_n = re.search(rf"{_NUMBER}%\s*N\b", text, re.IGNORECASE)
    if target is None:
        return "fertilizer_product_mass", {}, ("nutrient_target_kg_per_ha", "nutrient_percent")
    nutrient = target.group(2).upper().replace("₂", "2").replace("₅", "5")
    nutrient_percent: float | None = None
    if grade:
        nutrient_percent = {
            "N": _number(grade.group(1)),
            "P2O5": _number(grade.group(2)),
            "K2O": _number(grade.group(3)),
        }[nutrient]
    elif percent_n and nutrient == "N":
        nutrient_percent = _number(percent_n.group(1))
    missing = () if nutrient_percent is not None else ("nutrient_percent",)
    inputs = {
        "nutrient_target_kg_per_ha": _number(target.group(1)),
        "nutrient_label": nutrient.replace("2", "₂").replace("5", "₅"),
    }
    if nutrient_percent is not None:
        inputs["nutrient_percent"] = nutrient_percent
    return "fertilizer_product_mass", inputs, missing


def _parse_nutrient_delivery(text: str, lower: str):  # noqa: ANN202
    if "does the application deliver" not in lower:
        return None
    rate = re.search(rf"receives\s*{_NUMBER}\s*kg/ha", text, re.IGNORECASE)
    grade = re.search(r"(?:of a|of an?)\s*(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    nutrient = re.search(r"how many kg\s*(N|P(?:₂|2)O(?:₅|5)|K(?:₂|2)O)/ha", text, re.IGNORECASE)
    if not rate or not grade or not nutrient:
        return "nutrient_delivery", {}, ("product_rate_kg_per_ha", "nutrient_percent")
    label = nutrient.group(1).upper().replace("₂", "2").replace("₅", "5")
    percent = {"N": grade.group(1), "P2O5": grade.group(2), "K2O": grade.group(3)}[label]
    return "nutrient_delivery", {
        "product_rate_kg_per_ha": _number(rate.group(1)),
        "nutrient_percent": _number(percent),
        "nutrient_label": label.replace("2", "₂").replace("5", "₅"),
    }, ()


def _parse_sprayer_volume(text: str, lower: str):  # noqa: ANN202
    if "nozzles" not in lower or "application volume" not in lower:
        return None
    count = re.search(rf"{_NUMBER}\s*nozzles", text, re.IGNORECASE)
    flow = re.search(rf"flowing\s*{_NUMBER}\s*L/min", text, re.IGNORECASE)
    speed = re.search(rf"travels at\s*{_NUMBER}\s*km/h", text, re.IGNORECASE)
    boom = re.search(rf"{_NUMBER}\s*m boom", text, re.IGNORECASE)
    values = {"nozzle_count": count, "flow_l_per_min_per_nozzle": flow, "speed_km_per_h": speed, "boom_width_m": boom}
    return "sprayer_application_volume", {key: _number(value.group(1)) for key, value in values.items() if value}, tuple(key for key, value in values.items() if not value)


def _parse_tank_coverage(text: str, lower: str):  # noqa: ANN202
    if "sprayer tank" not in lower or "tank cover" not in lower:
        return None
    tank = re.search(rf"{_NUMBER}\s*L sprayer tank", text, re.IGNORECASE)
    rate = re.search(rf"applying\s*{_NUMBER}\s*L/ha", text, re.IGNORECASE)
    values = {"tank_volume_l": tank, "application_volume_l_per_ha": rate}
    inputs = {key: _number(value.group(1)) for key, value in values.items() if value}
    if "ignoring unusable tank volume" in lower:
        inputs["unusable_volume_l"] = 0
    return "tank_coverage", inputs, tuple(key for key, value in values.items() if not value)


def _parse_daily_gdd(text: str, lower: str):  # noqa: ANN202
    if "maximum temperature" not in lower or "growing degree days" not in lower:
        return None
    maximum = re.search(rf"maximum temperature was\s*{_NUMBER}°?C", text, re.IGNORECASE)
    minimum = re.search(rf"minimum temperature was\s*{_NUMBER}°?C", text, re.IGNORECASE)
    base = re.search(rf"using a\s*{_NUMBER}°?C base", text, re.IGNORECASE)
    values = {"max_temp_c": maximum, "min_temp_c": minimum, "base_temp_c": base}
    return "daily_gdd", {key: _number(value.group(1)) for key, value in values.items() if value}, tuple(key for key, value in values.items() if not value)


def _parse_accumulated_gdd(text: str, lower: str):  # noqa: ANN202
    if "gdd values" not in lower or "accumulated gdd" not in lower:
        return None
    match = re.search(r"GDD values of ([0-9.,\sand]+?) for", text, re.IGNORECASE)
    if not match:
        return "accumulated_gdd", {}, ("daily_gdd_values",)
    values = [_number(value) for value in re.findall(r"\d+(?:\.\d+)?", match.group(1))]
    return "accumulated_gdd", {"daily_gdd_values": values}, () if values else ("daily_gdd_values",)


def _parse_row_population(text: str, lower: str):  # noqa: ANN202
    if "plants per metre of row" not in lower or "plants/m²" not in lower:
        return None
    spacing = re.search(rf"rows\s*{_NUMBER}\s*m apart", text, re.IGNORECASE)
    plants = re.search(rf"{_NUMBER}\s*established plants per metre of row", text, re.IGNORECASE)
    values = {"plants_per_row_m": plants, "row_spacing_m": spacing}
    return "row_population", {key: _number(value.group(1)) for key, value in values.items() if value}, tuple(key for key, value in values.items() if not value)


def _parse_field_product_total(text: str, lower: str):  # noqa: ANN202
    if "whole field" not in lower or "kg/ha of a fertilizer product" not in lower:
        return None
    area = re.search(rf"field is\s*{_NUMBER}\s*ha", text, re.IGNORECASE)
    rate = re.search(rf"calls for\s*{_NUMBER}\s*kg/ha of a fertilizer product", text, re.IGNORECASE)
    values = {"area_ha": area, "product_rate_kg_per_ha": rate}
    return "field_product_total", {key: _number(value.group(1)) for key, value in values.items() if value}, tuple(key for key, value in values.items() if not value)


def _parse_area_weighted_average(text: str, lower: str):  # noqa: ANN202
    if "area-weighted" not in lower or "zone yielding" not in lower:
        return None
    total = re.search(rf"{_NUMBER}\s*ha[^.]*field", text, re.IGNORECASE)
    zones = re.findall(rf"{_NUMBER}\s*ha zone yielding\s*{_NUMBER}\s*bu/ac", text, re.IGNORECASE)
    if not total or len(zones) < 2:
        return "area_weighted_average", {}, ("total_area_ha", "at least two zone areas and values")
    return "area_weighted_average", {
        "total_area_ha": _number(total.group(1)),
        "zones": [{"area_ha": _number(area), "value": _number(value)} for area, value in zones],
        "value_unit": "bu/ac",
    }, ()
