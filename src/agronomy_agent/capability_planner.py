"""Registry-driven capability planning for the production agent.

The planner is deliberately deterministic and answer-blind.  It consumes the
question frame, decision contract, typed field snapshot, registry identity and
arm controls; retrieved text, model output and benchmark expectations are not
planner inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Mapping

from agronomy_agent.capability_registry import capability_registry
from agronomy_agent.calculator_contracts import EXPLICIT_ARITHMETIC_SELECTOR_ID
from agronomy_agent.execution_core import stable_sha256
from agronomy_agent.tool_planner import plan_tools
from agronomy_agent.tools.registry import run_tools


PLANNER_VERSION = "open_agronomy_agent.capability_planner.v3"
PLANNER_INPUT_SCHEMA_VERSION = "open_agronomy_agent.planner_input.v2"
PLANNER_BINDING_SCHEMA_VERSION = "open_agronomy_agent.planner_binding.v1"
CAPABILITY_PLAN_SCHEMA_VERSION = "open_agronomy_agent.capability_plan.v2"
CAPABILITY_INVOCATION_SCHEMA_VERSION = "open_agronomy_agent.capability_invocation.v2"


@dataclass(frozen=True)
class PlannerInput:
    schema_version: str
    planning_context_id: str
    question: str
    question_sha256: str
    question_frame_id: str
    decision_contract_sha256: str
    field_snapshot_sha256: str | None
    capability_registry_sha256: str
    arm_id: str
    phase: str
    intent_set: tuple[str, ...]
    primary_intent: str
    risk_level: str
    obligation_keys: tuple[str, ...]
    required_capability_ids: tuple[str, ...]
    field_context: Mapping[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlannerBinding:
    schema_version: str
    selector_id: str
    phase: str
    obligation_keys: tuple[str, ...]
    intent_ids: tuple[str, ...]
    arm_eligibility: tuple[str, ...]
    priority: int
    max_invocations: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityInvocation:
    schema_version: str
    invocation_id: str
    planning_context_id: str
    planner_version: str
    phase: str
    capability_id: str
    capability_version: str
    operation: str
    inputs: Mapping[str, Any]
    status: str
    missing_inputs: tuple[str, ...]
    authority_role: str
    risk_class: str
    selector_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilityPlan:
    schema_version: str
    planner_version: str
    planning_context_id: str
    phase: str
    status: str
    invocations: tuple[CapabilityInvocation, ...]
    clarification: str | None
    plan_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_planner_input(
    question: str,
    *,
    question_frame: Mapping[str, Any],
    decision_contract: Mapping[str, Any],
    capability_registry_sha256: str,
    arm_id: str,
    phase: str,
    field_context: Mapping[str, Any] | None = None,
) -> PlannerInput:
    if phase not in {"public_adapter_selection", "tool_planning"}:
        raise ValueError(f"unsupported planner phase: {phase}")
    question_sha256 = stable_sha256(question)
    obligations = tuple(
        str(row.get("key") or "")
        for row in decision_contract.get("evidence_obligations", ())
        if isinstance(row, Mapping) and str(row.get("key") or "")
    )
    required = tuple(
        dict.fromkeys(str(value) for value in decision_contract.get("required_tools", ()))
    )
    seed = {
        "planner_version": PLANNER_VERSION,
        "question_sha256": question_sha256,
        "question_frame_id": question_frame.get("question_frame_id"),
        "decision_contract_sha256": stable_sha256(decision_contract),
        "field_snapshot_sha256": question_frame.get("field_snapshot_sha256"),
        "capability_registry_sha256": capability_registry_sha256,
        "arm_id": arm_id,
    }
    return PlannerInput(
        schema_version=PLANNER_INPUT_SCHEMA_VERSION,
        planning_context_id=f"planning_{stable_sha256(seed)[:24]}",
        question=question,
        question_sha256=question_sha256,
        question_frame_id=str(question_frame.get("question_frame_id") or ""),
        decision_contract_sha256=seed["decision_contract_sha256"],
        field_snapshot_sha256=(
            str(question_frame.get("field_snapshot_sha256"))
            if question_frame.get("field_snapshot_sha256")
            else None
        ),
        capability_registry_sha256=capability_registry_sha256,
        arm_id=arm_id,
        phase=phase,
        intent_set=tuple(str(value) for value in decision_contract.get("intent_set", ())),
        primary_intent=str(decision_contract.get("primary_intent") or ""),
        risk_level=str(question_frame.get("risk_level") or "low"),
        obligation_keys=obligations,
        required_capability_ids=required,
        field_context=dict(field_context) if field_context is not None else None,
    )


def plan_capabilities(planner_input: PlannerInput) -> CapabilityPlan:
    if planner_input.phase == "public_adapter_selection":
        if not isinstance(planner_input.field_context, Mapping):
            return _finish_plan(planner_input, (), clarification=None)
        from agronomy_agent.server.services.chat_service import _public_source_card_tasks

        registry = capability_registry()
        selected_ids = tuple(
            dict.fromkeys(
                str(getattr(task, "capability_id", ""))
                for task in _public_source_card_tasks(
                    planner_input.question,
                    dict(planner_input.field_context),
                )
                if str(getattr(task, "capability_id", ""))
            )
        )
        invocations = tuple(
            _invocation(
                planner_input,
                capability_id=spec.capability_id,
                capability_version=spec.version,
                operation="public_source_card",
                inputs={"question_sha256": planner_input.question_sha256},
                status="planned",
                missing_inputs=(),
                authority_role=spec.authority_role,
                risk_class=spec.risk_class,
                selector_id=str(spec.planner.selector_id or ""),
            )
            for capability_id in selected_ids
            for spec in (registry.require(capability_id),)
            if spec.kind == "source_card" and "public_adapter_selection" in spec.planner.phases
        )
        return _finish_plan(planner_input, invocations, clarification=None)
    if planner_input.arm_id == "full_minus_typed_tools":
        return _finish_plan(planner_input, (), clarification=None)

    registry = capability_registry()
    invocations: list[CapabilityInvocation] = []
    secondary_by_primary = {
        "plant_health": {"field_data", "product_label", "integrated_management"},
        "field_data": {"soil_water", "crop_management", "regional_context"},
        "exam_review": {"field_data", "plant_health", "product_label"},
    }
    if planner_input.primary_intent == "exam_review" and planner_input.risk_level != "regulated":
        secondary_by_primary["exam_review"] = set()
    selector_intents = {
        planner_input.primary_intent,
        *(set(planner_input.intent_set) & secondary_by_primary.get(planner_input.primary_intent, set())),
    }
    lexically_applicable_guards = {note.name for note in run_tools(planner_input.question)}
    applicable_guards = {
        capability_id
        for capability_id in lexically_applicable_guards
        if (
            (spec := registry.get(capability_id)) is not None
            and (
                bool(selector_intents & set(spec.planner.intent_ids))
                or planner_input.risk_level in spec.planner.risk_levels
                or (not spec.planner.intent_ids and not spec.planner.risk_levels)
            )
        )
    }
    applicable_guards.update(
        spec.capability_id
        for spec in registry.specs
        if spec.kind == "guard" and spec.planner.automatic_intent_selection
        if selector_intents & set(spec.planner.intent_ids)
    )
    if (
        planner_input.primary_intent == "product_label"
        and re.search(
            r"\b(?:rate|dose|herbicide|fungicide|insecticide|weed|weeds|fongicide|herbicide)\b",
            planner_input.question,
            flags=re.IGNORECASE,
        )
    ):
        applicable_guards.add("resistance_management_guard")
    applicable_guards.update(
        spec.capability_id
        for spec in registry.specs
        if spec.kind == "guard" and planner_input.risk_level in spec.planner.risk_levels
    )
    guard_ids = tuple(
        dict.fromkeys(
            (
                *(
                    capability_id
                    for capability_id in planner_input.required_capability_ids
                    if (
                        (required_spec := registry.get(capability_id)) is not None
                        and (
                            bool(selector_intents & set(required_spec.planner.intent_ids))
                            or planner_input.risk_level in required_spec.planner.risk_levels
                            or capability_id in lexically_applicable_guards
                        )
                    )
                ),
                *sorted(applicable_guards),
            )
        )
    )
    for capability_id in guard_ids:
        spec = registry.get(capability_id)
        if spec is None:
            raise ValueError(f"planner selected an unregistered capability: {capability_id}")
        if spec.kind != "guard":
            continue
        inputs = {"query": planner_input.question}
        invocations.append(
            _invocation(
                planner_input,
                capability_id=spec.capability_id,
                capability_version=spec.version,
                operation="guard_note",
                inputs=inputs,
                status="planned",
                missing_inputs=(),
                authority_role=spec.authority_role,
                risk_class=spec.risk_class,
                selector_id="registered_guard_applicability_v1",
            )
        )

    calculator_plan = plan_tools(
        planner_input.question,
        field_context=planner_input.field_context,
    )
    calculator_spec = registry.require("agronomic_calculator")
    for item in calculator_plan.invocations:
        invocations.append(
            _invocation(
                planner_input,
                capability_id=calculator_spec.capability_id,
                capability_version=calculator_spec.version,
                operation=item.operation,
                inputs=item.inputs,
                status=item.status,
                missing_inputs=item.missing_inputs,
                authority_role=item.authority_role,
                risk_class=item.risk_class,
                selector_id=EXPLICIT_ARITHMETIC_SELECTOR_ID,
                invocation_id=item.invocation_id,
            )
        )
    return _finish_plan(
        planner_input,
        tuple(invocations),
        clarification=calculator_plan.clarification,
    )


def select_guard_capability_ids(
    question: str,
    *,
    route: Any,
    field_context: Mapping[str, Any] | None = None,
    arm_id: str = "production_full",
) -> tuple[str, ...]:
    """Compatibility projection of planner v2 guard selection.

    This keeps evaluation traces and older route-shaped interfaces honest
    without returning capability ownership to the router.
    """

    from agronomy_agent.decision_contract import build_decision_contract
    from agronomy_agent.evidence_contracts import question_frame_from_runtime

    registry = capability_registry()
    registry_sha256 = stable_sha256([spec.as_record() for spec in registry.specs])
    contract = build_decision_contract(question, route, field_context=field_context)
    frame = question_frame_from_runtime(
        question=question,
        route=route,
        query_context={},
        decision_contract=contract.to_dict(),
        field_context=field_context,
    )
    planner_input = build_planner_input(
        question,
        question_frame=frame.to_dict(),
        decision_contract=contract.to_dict(),
        capability_registry_sha256=registry_sha256,
        arm_id=arm_id,
        phase="tool_planning",
        field_context=field_context,
    )
    return tuple(
        item.capability_id
        for item in plan_capabilities(planner_input).invocations
        if item.operation == "guard_note"
    )


def select_public_capability_plan(
    question: str,
    *,
    route: Any,
    field_context: Mapping[str, Any] | None,
    arm_id: str = "production_full",
) -> CapabilityPlan:
    from agronomy_agent.decision_contract import build_decision_contract
    from agronomy_agent.evidence_contracts import question_frame_from_runtime

    registry = capability_registry()
    contract = build_decision_contract(question, route, field_context=field_context)
    frame = question_frame_from_runtime(
        question=question,
        route=route,
        query_context={},
        decision_contract=contract.to_dict(),
        field_context=field_context,
    )
    planner_input = build_planner_input(
        question,
        question_frame=frame.to_dict(),
        decision_contract=contract.to_dict(),
        capability_registry_sha256=stable_sha256([spec.as_record() for spec in registry.specs]),
        arm_id=arm_id,
        phase="public_adapter_selection",
        field_context=field_context,
    )
    return plan_capabilities(planner_input)


def _invocation(
    planner_input: PlannerInput,
    *,
    capability_id: str,
    capability_version: str,
    operation: str,
    inputs: Mapping[str, Any],
    status: str,
    missing_inputs: tuple[str, ...],
    authority_role: str,
    risk_class: str,
    selector_id: str,
    invocation_id: str | None = None,
) -> CapabilityInvocation:
    seed = {
        "planning_context_id": planner_input.planning_context_id,
        "phase": planner_input.phase,
        "capability_id": capability_id,
        "capability_version": capability_version,
        "operation": operation,
        "inputs": dict(inputs),
    }
    return CapabilityInvocation(
        schema_version=CAPABILITY_INVOCATION_SCHEMA_VERSION,
        invocation_id=invocation_id or f"invocation_{stable_sha256(seed)[:24]}",
        planning_context_id=planner_input.planning_context_id,
        planner_version=PLANNER_VERSION,
        phase=planner_input.phase,
        capability_id=capability_id,
        capability_version=capability_version,
        operation=operation,
        inputs=dict(inputs),
        status=status,
        missing_inputs=tuple(missing_inputs),
        authority_role=authority_role,
        risk_class=risk_class,
        selector_id=selector_id,
    )


def _finish_plan(
    planner_input: PlannerInput,
    invocations: tuple[CapabilityInvocation, ...],
    *,
    clarification: str | None,
) -> CapabilityPlan:
    status = (
        "clarification_required"
        if any(item.status == "clarification_required" for item in invocations)
        else "ready"
        if invocations
        else "not_applicable"
    )
    base = {
        "schema_version": CAPABILITY_PLAN_SCHEMA_VERSION,
        "planner_version": PLANNER_VERSION,
        "planning_context_id": planner_input.planning_context_id,
        "phase": planner_input.phase,
        "status": status,
        "invocations": [item.to_dict() for item in invocations],
        "clarification": clarification,
    }
    return CapabilityPlan(
        schema_version=CAPABILITY_PLAN_SCHEMA_VERSION,
        planner_version=PLANNER_VERSION,
        planning_context_id=planner_input.planning_context_id,
        phase=planner_input.phase,
        status=status,
        invocations=invocations,
        clarification=clarification,
        plan_sha256=stable_sha256(base),
    )


__all__ = [
    "CAPABILITY_PLAN_SCHEMA_VERSION",
    "PLANNER_VERSION",
    "CapabilityInvocation",
    "CapabilityPlan",
    "PlannerBinding",
    "PlannerInput",
    "build_planner_input",
    "plan_capabilities",
    "select_guard_capability_ids",
    "select_public_capability_plan",
]
