"""Non-claim benchmark adapter over the production execution core.

This adapter is a release-readiness instrument, not a v3 performance runner.
It supports only the complete observed product configuration and deliberately
has no case expectation or scoring input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from agronomy_agent.execution_core import (
    AgentExecutionRequest,
    AgentExecutionResult,
    EXECUTION_STAGE_IDS,
    EXECUTION_STAGE_TOPOLOGY_VERSION,
)
from agronomy_agent.server.services.chat_service import execute_agent_request


REHEARSAL_RESULT_SCHEMA_VERSION = (
    "open_agronomy_agent.observed_system_rehearsal.v1"
)
REHEARSAL_RESULT_CLASS = "observed_system_execution_nonclaim"
RETRIEVAL_NEITHER_CONFIGURATION_ID = "retrieval_neither"
RETRIEVAL_DOCUMENT_ONLY_CONFIGURATION_ID = "retrieval_document_only"
RETRIEVAL_GRAPH_ONLY_CONFIGURATION_ID = "retrieval_graph_only"
RETRIEVAL_BOTH_CONFIGURATION_ID = "retrieval_both"


def _retrieval_configuration(
    *,
    document_retrieval: bool,
    graph_retrieval: bool,
) -> dict[str, bool]:
    components = {stage_id: True for stage_id in EXECUTION_STAGE_IDS}
    components["document_retrieval"] = document_retrieval
    components["graph_retrieval"] = graph_retrieval
    return components


RETRIEVAL_COMPONENT_CONFIGURATIONS: dict[str, dict[str, bool]] = {
    RETRIEVAL_NEITHER_CONFIGURATION_ID: _retrieval_configuration(
        document_retrieval=False,
        graph_retrieval=False,
    ),
    RETRIEVAL_DOCUMENT_ONLY_CONFIGURATION_ID: _retrieval_configuration(
        document_retrieval=True,
        graph_retrieval=False,
    ),
    RETRIEVAL_GRAPH_ONLY_CONFIGURATION_ID: _retrieval_configuration(
        document_retrieval=False,
        graph_retrieval=True,
    ),
    RETRIEVAL_BOTH_CONFIGURATION_ID: _retrieval_configuration(
        document_retrieval=True,
        graph_retrieval=True,
    ),
}

# Compatibility names now identify the explicit both-enabled arm; the adapter
# exposes exactly four supported retrieval configurations.
PRODUCTION_FULL_CONFIGURATION_ID = RETRIEVAL_BOTH_CONFIGURATION_ID
PRODUCTION_FULL_COMPONENTS = dict(
    RETRIEVAL_COMPONENT_CONFIGURATIONS[RETRIEVAL_BOTH_CONFIGURATION_ID]
)


@dataclass(frozen=True)
class ObservedSystemRehearsalResult:
    execution: AgentExecutionResult
    component_configuration_id: str = PRODUCTION_FULL_CONFIGURATION_ID
    components: Mapping[str, bool] = field(
        default_factory=lambda: dict(PRODUCTION_FULL_COMPONENTS)
    )
    schema_version: str = REHEARSAL_RESULT_SCHEMA_VERSION
    result_class: str = REHEARSAL_RESULT_CLASS
    claim_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "result_class": self.result_class,
            "claim_eligible": self.claim_eligible,
            "claim_boundary": (
                "Observed server answer-path execution and receipt parity only; "
                "not HTTP/UI parity, legacy evaluator parity, model performance, "
                "agronomic validity, or benchmark outcome."
            ),
            "component_configuration": {
                "configuration_id": self.component_configuration_id,
                "components": dict(self.components),
            },
            "execution": self.execution.to_record(),
        }


class ObservedSystemBenchmarkAdapter:
    """Execute one non-claim rehearsal through the same core as the cockpit."""

    executor_id = "observed_system_benchmark_adapter"
    executor_version = "v1"
    result_class = REHEARSAL_RESULT_CLASS

    def harness_capabilities(self) -> dict[str, Any]:
        return {
            "schema_version": "open_agronomy_agent.observed_system_adapter_capabilities.v1",
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "result_class": self.result_class,
            "claim_eligible": False,
            "stage_topology_version": EXECUTION_STAGE_TOPOLOGY_VERSION,
            "stage_topology": list(EXECUTION_STAGE_IDS),
            "supported_execution_modes": ["baseline", "agronomic_rag", "mock"],
            "supported_configuration_modes": {
                configuration_id: (
                    ["baseline", "agronomic_rag", "mock"]
                    if configuration_id == RETRIEVAL_BOTH_CONFIGURATION_ID
                    else ["agronomic_rag"]
                )
                for configuration_id in RETRIEVAL_COMPONENT_CONFIGURATIONS
            },
            "supported_component_configurations": {
                configuration_id: dict(configuration)
                for configuration_id, configuration in RETRIEVAL_COMPONENT_CONFIGURATIONS.items()
            },
            "component_control_boundary": (
                "Only document_retrieval and graph_retrieval vary. Every other "
                "answer-affecting stage remains enabled and is still receipted."
            ),
            "unsupported": [
                "non-retrieval component toggles",
                "raw_model",
                "kernel-only arms",
                "causal ablations",
                "performance scoring",
                "claim-eligible execution",
                "HTTP, hosted-message, and frontend presentation parity",
                "legacy agent.generate_answer evaluator parity",
            ],
        }

    def execute(
        self,
        request: AgentExecutionRequest,
        *,
        component_configuration_id: str = PRODUCTION_FULL_CONFIGURATION_ID,
        components: Mapping[str, bool] | None = None,
    ) -> ObservedSystemRehearsalResult:
        if request.execution_class != REHEARSAL_RESULT_CLASS:
            raise ValueError(
                "the observed-system adapter requires "
                "execution_class='observed_system_execution_nonclaim'"
            )
        expected_components = RETRIEVAL_COMPONENT_CONFIGURATIONS.get(
            component_configuration_id
        )
        if expected_components is None:
            raise ValueError(
                "unsupported observed-system component configuration: "
                f"{component_configuration_id}"
            )
        supplied_components = (
            dict(expected_components)
            if components is None
            else dict(components)
        )
        if set(supplied_components) != set(EXECUTION_STAGE_IDS):
            raise ValueError(
                "observed-system component mapping must contain the exact "
                "production stage topology"
            )
        invalid_component_values = sorted(
            stage_id
            for stage_id, enabled in supplied_components.items()
            if not isinstance(enabled, bool)
        )
        if invalid_component_values:
            raise TypeError(
                "observed-system component values must be bools: "
                + ", ".join(invalid_component_values)
            )
        disabled_non_retrieval = sorted(
            stage_id
            for stage_id in EXECUTION_STAGE_IDS
            if stage_id not in {"document_retrieval", "graph_retrieval"}
            and supplied_components.get(stage_id) is not True
        )
        if disabled_non_retrieval:
            raise ValueError(
                "the observed-system rehearsal adapter does not support "
                "non-retrieval component toggles: "
                + ", ".join(disabled_non_retrieval)
            )
        if supplied_components != expected_components:
            raise ValueError(
                "component mapping does not match the named retrieval configuration"
            )
        expected_document = expected_components["document_retrieval"]
        expected_graph = expected_components["graph_retrieval"]
        if request.document_retrieval_enabled is not expected_document:
            raise ValueError(
                "request document_retrieval_enabled does not match the named "
                "retrieval configuration"
            )
        if request.graph_retrieval_enabled is not expected_graph:
            raise ValueError(
                "request graph_retrieval_enabled does not match the named "
                "retrieval configuration"
            )
        execution = execute_agent_request(request)
        return ObservedSystemRehearsalResult(
            execution=execution,
            component_configuration_id=component_configuration_id,
            components=dict(expected_components),
        )


__all__ = [
    "ObservedSystemBenchmarkAdapter",
    "ObservedSystemRehearsalResult",
    "PRODUCTION_FULL_COMPONENTS",
    "PRODUCTION_FULL_CONFIGURATION_ID",
    "RETRIEVAL_BOTH_CONFIGURATION_ID",
    "RETRIEVAL_COMPONENT_CONFIGURATIONS",
    "RETRIEVAL_DOCUMENT_ONLY_CONFIGURATION_ID",
    "RETRIEVAL_GRAPH_ONLY_CONFIGURATION_ID",
    "RETRIEVAL_NEITHER_CONFIGURATION_ID",
    "REHEARSAL_RESULT_CLASS",
    "REHEARSAL_RESULT_SCHEMA_VERSION",
]
