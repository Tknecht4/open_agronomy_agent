from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.paths import repo_path


DEFAULT_SKILL_PLAN_PATH = "plans/agronomy_agent_phase5_optimization_hardening_packet/phase5_skill_optimization_plan.yaml"
REGISTRY_VERSION = "phase5_skill_registry_v1"
DEFAULT_TOOL_BOUNDARY = "Decision-support guardrail only; do not convert this output into field-specific legal, label, rate, or calibration advice."
DEFAULT_TOOL_PROVENANCE = ("deterministic_guard_rule", "phase5_skill_registry_v1")


@dataclass(frozen=True)
class SkillContract:
    skill_id: str
    tool_name: str
    name: str
    risk_class: str
    inputs: dict[str, str]
    outputs: dict[str, str]
    eval_tags: tuple[str, ...]
    provenance: tuple[str, ...] = DEFAULT_TOOL_PROVENANCE
    boundary: str = DEFAULT_TOOL_BOUNDARY
    network_allowed_in_chat: bool = False
    favor_recall: bool = False

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["eval_tags"] = list(self.eval_tags)
        record["provenance"] = list(self.provenance)
        return record


SKILL_CONTRACTS: dict[str, SkillContract] = {
    "label_guard": SkillContract(
        skill_id="label_guard_v1",
        tool_name="label_guard",
        name="Label Boundary Guard",
        risk_class="regulated",
        inputs={"query": "string"},
        outputs={"decision_frame": "string", "missing_inputs": "list[string]", "cautions": "list[string]"},
        eval_tags=("product_stewardship", "label_boundary", "regulated"),
        favor_recall=True,
    ),
    "fertility_guard": SkillContract(
        skill_id="fertility_guard_v1",
        tool_name="fertility_guard",
        name="Fertility Calibration Guard",
        risk_class="medium",
        inputs={"query": "string"},
        outputs={"missing_inputs": "list[string]", "decision_frame": "string"},
        eval_tags=("fertility", "soil_test", "missing_data"),
    ),
    "weather_guard": SkillContract(
        skill_id="weather_guard_v1",
        tool_name="weather_guard",
        name="Weather Risk Guard",
        risk_class="regulated",
        inputs={"query": "string"},
        outputs={"blocking_flags": "list[string]", "required_next_checks": "list[string]"},
        eval_tags=("weather_guard", "spray_window", "drift"),
        favor_recall=True,
    ),
    "field_data_guard": SkillContract(
        skill_id="field_data_guard_v1",
        tool_name="field_data_guard",
        name="Field Data Audit Guard",
        risk_class="medium",
        inputs={"query": "string"},
        outputs={"workflow_checks": "list[string]", "audit_boundary": "string"},
        eval_tags=("field_data", "precision_ag", "audit_trail"),
    ),
    "salinity_sodicity_guard": SkillContract(
        skill_id="salinity_sodicity_guard_v1",
        tool_name="salinity_sodicity_guard",
        name="Salinity/Sodicity Evidence Guard",
        risk_class="medium",
        inputs={"query": "string"},
        outputs={"required_evidence": "list[string]", "diagnosis_boundary": "string"},
        eval_tags=("soil_water", "salinity", "sodicity"),
    ),
    "soil_structure_guard": SkillContract(
        skill_id="soil_structure_guard_v1",
        tool_name="soil_structure_guard",
        name="Soil Structure Guard",
        risk_class="medium",
        inputs={"query": "string"},
        outputs={"required_evidence": "list[string]", "management_boundary": "string"},
        eval_tags=("soil_water", "compaction", "diagnostic"),
    ),
    "pesticide_safety_guard": SkillContract(
        skill_id="pesticide_safety_guard_v1",
        tool_name="pesticide_safety_guard",
        name="Pesticide Safety Guard",
        risk_class="regulated",
        inputs={"query": "string"},
        outputs={"required_next_checks": "list[string]", "safety_boundary": "string"},
        eval_tags=("product_stewardship", "pesticide_safety", "regulated"),
        favor_recall=True,
    ),
    "resistance_management_guard": SkillContract(
        skill_id="resistance_management_guard_v1",
        tool_name="resistance_management_guard",
        name="Resistance Management Guard",
        risk_class="regulated",
        inputs={"query": "string"},
        outputs={"required_next_checks": "list[string]", "nonchemical_tactics": "list[string]"},
        eval_tags=("product_stewardship", "resistance", "regulated"),
        favor_recall=True,
    ),
    "nutrient_4r_guard": SkillContract(
        skill_id="nutrient_4r_guard_v1",
        tool_name="nutrient_4r_guard",
        name="4R Nutrient Guard",
        risk_class="medium",
        inputs={"query": "string"},
        outputs={"decision_checks": "list[string]", "water_quality_boundary": "string"},
        eval_tags=("fertility", "4r", "water_quality"),
    ),
    "spray_window": SkillContract(
        skill_id="spray_window_screen_v1",
        tool_name="spray_window",
        name="Spray Window Screen",
        risk_class="regulated",
        inputs={
            "wind_mph": "number",
            "gust_mph": "number",
            "temperature_f": "number",
            "rain_hours": "number",
            "inversion_risk": "string",
            "sensitive_downwind": "boolean",
        },
        outputs={"decision_frame": "string", "blocking_flags": "list[string]", "cautions": "list[string]", "required_next_checks": "list[string]"},
        eval_tags=("product_stewardship", "weather_guard", "drift"),
        favor_recall=True,
    ),
    "agronomic_calculator": SkillContract(
        skill_id="agronomic_calculator_v1",
        tool_name="agronomic_calculator",
        name="Structured Agronomic Calculator",
        risk_class="medium",
        inputs={"operation": "string", "inputs": "object"},
        outputs={
            "value": "number",
            "unit": "string",
            "formula": "string",
            "assumptions": "list[string]",
            "boundary": "string",
        },
        eval_tags=("calculation", "offline", "deterministic", "unit_validation"),
        provenance=("typed_calculation_engine", "agronomic_calculation_v2"),
        boundary=(
            "Arithmetic from supplied structured inputs only; the tool does not choose a target, "
            "confirm a label, or establish field suitability."
        ),
    ),
}


def load_skill_registry(plan_path: str | Path = DEFAULT_SKILL_PLAN_PATH) -> dict[str, Any]:
    payload = _read_yaml(plan_path)
    contracts = [contract.as_record() for contract in sorted(SKILL_CONTRACTS.values(), key=lambda item: item.tool_name)]
    plan_version = str(payload.get("skill_registry_version") or REGISTRY_VERSION)
    return {
        "skill_registry_version": plan_version,
        "contracts": contracts,
        "optimization_ladder": list(payload.get("optimization_ladder") or []),
        "global_constraints": list(payload.get("global_constraints") or []),
    }


def skill_contract_for_tool(tool_name: str) -> SkillContract | None:
    return SKILL_CONTRACTS.get(tool_name)


def skill_metadata(tool_name: str) -> dict[str, Any]:
    contract = skill_contract_for_tool(tool_name)
    if contract is None:
        return {
            "skill_id": f"{tool_name}_unregistered",
            "provenance": list(DEFAULT_TOOL_PROVENANCE),
            "boundary": DEFAULT_TOOL_BOUNDARY,
            "risk_class": "unknown",
            "eval_tags": [],
        }
    record = contract.as_record()
    return {
        "skill_id": record["skill_id"],
        "provenance": record["provenance"],
        "boundary": record["boundary"],
        "risk_class": record["risk_class"],
        "eval_tags": record["eval_tags"],
    }


def skill_metrics_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_tool: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "expected": 0,
            "called": 0,
            "true_positive": 0,
            "false_positive": 0,
            "false_negative": 0,
            "latencies": [],
            "answer_impacts": [],
            "feedback_deltas": [],
            "reviewed": 0,
            "accepted": 0,
            "failure_tags": Counter(),
        }
    )
    for row in rows:
        expected_tools = normalize_tool_names(row.get("expected_tools", []) or [])
        actual_tools = normalize_tool_names(row.get("actual_tools", []) or row.get("tool_notes", []) or [])
        latency_by_tool = row.get("tool_latency_ms") if isinstance(row.get("tool_latency_ms"), dict) else {}
        impact_by_tool = row.get("answer_impact") if isinstance(row.get("answer_impact"), dict) else {}
        feedback_by_tool = row.get("user_feedback_delta") if isinstance(row.get("user_feedback_delta"), dict) else {}
        accepted_tools = {str(item) for item in row.get("reviewer_accepted_tools", []) or []}
        rejected_tools = {str(item) for item in row.get("reviewer_rejected_tools", []) or []}
        failure_tags = [str(item) for item in row.get("failure_tags", []) or []]
        for tool in sorted(expected_tools | actual_tools | accepted_tools | rejected_tools):
            bucket = by_tool[tool]
            if tool in expected_tools:
                bucket["expected"] += 1
            if tool in actual_tools:
                bucket["called"] += 1
            if tool in expected_tools and tool in actual_tools:
                bucket["true_positive"] += 1
            elif tool in actual_tools:
                bucket["false_positive"] += 1
            elif tool in expected_tools:
                bucket["false_negative"] += 1
            if tool in latency_by_tool:
                bucket["latencies"].append(float(latency_by_tool[tool]))
            if tool in impact_by_tool:
                bucket["answer_impacts"].append(float(impact_by_tool[tool]))
            if tool in feedback_by_tool:
                bucket["feedback_deltas"].append(float(feedback_by_tool[tool]))
            if tool in accepted_tools or tool in rejected_tools:
                bucket["reviewed"] += 1
                bucket["accepted"] += int(tool in accepted_tools)
            if tool in actual_tools:
                bucket["failure_tags"].update(failure_tags)
    return {
        "report_version": "phase5_skill_metrics_v1",
        "samples": len(rows),
        "skills": {tool: _summarize_skill_metrics(tool, bucket) for tool, bucket in sorted(by_tool.items())},
    }


def _summarize_skill_metrics(tool: str, bucket: dict[str, Any]) -> dict[str, Any]:
    contract = skill_contract_for_tool(tool)
    called = int(bucket["called"])
    expected = int(bucket["expected"])
    reviewed = int(bucket["reviewed"])
    return {
        "skill_id": contract.skill_id if contract else f"{tool}_unregistered",
        "risk_class": contract.risk_class if contract else "unknown",
        "call_count": called,
        "expected_count": expected,
        "true_positive": int(bucket["true_positive"]),
        "false_positive": int(bucket["false_positive"]),
        "false_negative": int(bucket["false_negative"]),
        "expected_call_recall": round(int(bucket["true_positive"]) / max(1, expected), 4),
        "unnecessary_call_rate": round(int(bucket["false_positive"]) / max(1, called), 4),
        "p95_latency_ms": _percentile(bucket["latencies"], 0.95),
        "mean_answer_impact": _mean(bucket["answer_impacts"]),
        "mean_user_feedback_delta": _mean(bucket["feedback_deltas"]),
        "reviewer_acceptance": round(int(bucket["accepted"]) / max(1, reviewed), 4),
        "failure_tags": dict(bucket["failure_tags"].most_common()),
    }


def _read_yaml(path: str | Path) -> dict[str, Any]:
    resolved = repo_path(path)
    if not resolved.exists():
        return {}
    loaded = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def normalize_tool_names(values: Any) -> set[str]:
    if not values:
        return set()
    if isinstance(values, dict):
        values = [values]
    return {name for item in values for name in [_tool_name(item)] if name}


def _tool_name(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ("name", "tool_name", "tool", "skill_id"):
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""
    for attr in ("name", "tool_name", "tool", "skill_id"):
        value = getattr(item, attr, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return str(item).strip()


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(float(ordered[index]), 3)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None
