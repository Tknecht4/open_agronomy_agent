"""Canonical governed-arm definitions for the v3 candidate matrix."""

from __future__ import annotations

from agronomy_agent.execution_core import ExecutionArmConfiguration


COMMON_ARMS = ("raw_model", "kernel_only", "production_full")
REGIONAL_DIAGNOSTIC_ARMS = (
    "full_minus_field_context",
    "retrieval_neither",
    "retrieval_document_only",
    "retrieval_graph_only",
    "retrieval_document_and_graph",
    "full_minus_typed_tools",
    "full_minus_risk_intervention_private_only",
    "full_minus_verifier",
    "full_minus_fallback",
)
ALL_ARM_IDS = COMMON_ARMS + REGIONAL_DIAGNOSTIC_ARMS


def execution_arm(arm_id: str) -> ExecutionArmConfiguration:
    if arm_id not in ALL_ARM_IDS:
        raise ValueError(f"unknown v3 candidate arm: {arm_id}")
    disabled: dict[str, bool] = {}
    if arm_id == "raw_model":
        disabled = {"governed_topology": False}
    elif arm_id == "kernel_only":
        disabled = {
            "document_retrieval_enabled": False,
            "graph_retrieval_enabled": False,
            "field_context_enabled": False,
        }
    elif arm_id == "full_minus_field_context":
        disabled = {"field_context_enabled": False}
    elif arm_id == "retrieval_neither":
        disabled = {"document_retrieval_enabled": False, "graph_retrieval_enabled": False}
    elif arm_id == "retrieval_document_only":
        disabled = {"graph_retrieval_enabled": False}
    elif arm_id == "retrieval_graph_only":
        disabled = {"document_retrieval_enabled": False}
    elif arm_id == "full_minus_typed_tools":
        disabled = {"typed_tools_enabled": False}
    elif arm_id == "full_minus_risk_intervention_private_only":
        disabled = {"risk_intervention_enabled": False}
    elif arm_id == "full_minus_verifier":
        disabled = {"verifier_enabled": False}
    elif arm_id == "full_minus_fallback":
        disabled = {"fallback_enabled": False}
    return ExecutionArmConfiguration(arm_id=arm_id, **disabled)


def assert_disabled_components_empty(
    arm: ExecutionArmConfiguration,
    *,
    document_ids: tuple[str, ...] = (),
    graph_ids: tuple[str, ...] = (),
    tool_invocation_ids: tuple[str, ...] = (),
) -> None:
    if not arm.document_retrieval_enabled and document_ids:
        raise ValueError("document-disabled arm contains document outputs")
    if not arm.graph_retrieval_enabled and graph_ids:
        raise ValueError("graph-disabled arm contains graph outputs")
    if not arm.typed_tools_enabled and tool_invocation_ids:
        raise ValueError("typed-tool-disabled arm contains tool invocations")


__all__ = ["ALL_ARM_IDS", "COMMON_ARMS", "REGIONAL_DIAGNOSTIC_ARMS", "assert_disabled_components_empty", "execution_arm"]
