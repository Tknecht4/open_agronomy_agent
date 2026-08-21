from __future__ import annotations

import pytest

from agronomy_agent.benchmark_arms import ALL_ARM_IDS, assert_disabled_components_empty, execution_arm


def test_all_twelve_arm_families_have_explicit_execution_controls() -> None:
    assert len(ALL_ARM_IDS) == 12
    assert execution_arm("production_full").to_dict() == {
        "arm_id": "production_full",
        "governed_topology": True,
        "document_retrieval_enabled": True,
        "graph_retrieval_enabled": True,
        "field_context_enabled": True,
        "typed_tools_enabled": True,
        "risk_intervention_enabled": True,
        "verifier_enabled": True,
        "fallback_enabled": True,
    }
    assert execution_arm("full_minus_typed_tools").typed_tools_enabled is False
    assert execution_arm("raw_model").governed_topology is False
    assert execution_arm("full_minus_verifier").request_controls()["verifier_enabled"] is False
    with pytest.raises(ValueError, match="outside AgentExecutionRequest"):
        execution_arm("raw_model").request_controls()
    assert execution_arm("full_minus_verifier").verifier_enabled is False
    assert execution_arm("retrieval_graph_only").document_retrieval_enabled is False


def test_disabled_component_contamination_fails_closed() -> None:
    with pytest.raises(ValueError, match="tool invocations"):
        assert_disabled_components_empty(
            execution_arm("full_minus_typed_tools"),
            tool_invocation_ids=("invocation-1",),
        )
