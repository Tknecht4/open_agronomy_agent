"""Executable, fail-closed orchestration for Open Agronomy Benchmark v2.

The runner executes the declared case-by-arm matrix through an injected
``ArmExecutor``.  This preserves a strict boundary between orchestration and a
runtime adapter: the existing four-arm RC1 runner is not relabeled as if it
implemented the nine v2 causal arms.  The checked-in deterministic executor is
for contract/trace QA only and never constitutes a system performance result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

import yaml

from agronomy_agent.agronomic_calculations import CalculationOperation
from agronomy_agent.answerability import (
    ANSWERABILITY_POLICY_VERSION,
    assess_answerability,
)
from agronomy_agent.benchmark_harness_compatibility import (
    EXECUTOR_CAPABILITIES_SCHEMA_VERSION,
    derive_system_configuration_sha256,
    negotiate_harness,
)
from agronomy_agent.benchmark_v2_metrics import (
    METRIC_SCHEMA_VERSION,
    score_case_observation,
    summarize_measurements,
    summarize_preregistered_estimands,
)
from agronomy_agent.tool_planner import (
    PLANNER_VERSION,
    TOOL_PLAN_SCHEMA_VERSION,
    plan_and_execute_tools,
)


RUN_SCHEMA_VERSION = "open_agronomy_agent.benchmark_v2_run.v1"
OBSERVATION_SCHEMA_VERSION = "open_agronomy_agent.benchmark_v2_observation.v1"
RUNNER_VERSION = "open_agronomy_agent.benchmark_v2_runner.v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_TRACE_SCHEMA_VERSION = "open_agronomy_agent.benchmark_v2_evidence_trace.v1"
VERIFIER_TRACE_SCHEMA_VERSION = "open_agronomy_agent.benchmark_v2_verifier_trace.v1"
TOOL_INVOCATION_SCHEMA_VERSION = "open_agronomy_agent.tool_invocation.v1"
TOOL_RESULT_SCHEMA_VERSION = "open_agronomy_agent.tool_result.v1"

ALLOWED_EXECUTOR_OBSERVATION_FIELDS = frozenset(
    {
        "status",
        "direct_answer",
        "abstained",
        "clarifying_questions",
        "clarification_fields",
        "selected_tools",
        "tool_plan",
        "tool_invocations",
        "tool_results",
        "pre_generation_intervened",
        "pre_generation_intervention",
        "verifier_had_opportunity",
        "draft_verifier_intervention_required",
        "verifier_intervened",
        "verifier_trace",
        "answer_numeric",
        "answerability_state",
        "action_commitment_made",
        "answer_origin",
        "fallback_used",
        "fallback_justified",
        "answer_stages",
        "evidence_trace",
        "component_receipts",
        "synthetic_expected_state",
        "interpretation_boundary",
        "draft_utility",
        "final_utility",
    }
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"runtime identity path escapes the project root: {path}") from exc


def _bundle_sha256(
    paths: Sequence[Path],
    *,
    allow_missing: bool = False,
) -> str:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        relative = _project_relative(path)
        if relative in seen:
            continue
        seen.add(relative)
        resolved = PROJECT_ROOT / relative
        if not resolved.is_file():
            if not allow_missing:
                raise ValueError(f"required runtime identity asset is missing: {relative}")
            records.append({"path": relative, "status": "missing"})
            continue
        records.append(
            {
                "path": relative,
                "status": "present",
                "sha256": file_sha256(resolved),
                "bytes": resolved.stat().st_size,
            }
        )
    return stable_sha256(records)


def _retrieval_runtime_paths() -> tuple[Path, ...]:
    config_path = PROJECT_ROOT / "configs/rag_governed_runtime_v1.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    retrieval = config.get("retrieval") if isinstance(config, Mapping) else {}
    retrieval = retrieval if isinstance(retrieval, Mapping) else {}
    configured: list[Path] = [config_path]
    for key in ("corpus_policy_manifest",):
        value = retrieval.get(key)
        if isinstance(value, str) and value.strip():
            configured.append(PROJECT_ROOT / value)
    for key in ("corpus_paths", "graph_paths"):
        values = retrieval.get(key) or ()
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValueError(f"governed RAG configuration {key} must be an array")
        for value in values:
            path = PROJECT_ROOT / str(value)
            configured.append(path)
            if key == "graph_paths":
                configured.append(path.with_suffix(".manifest.json"))
    private_knowledge = config.get("private_knowledge")
    if isinstance(private_knowledge, Mapping):
        manifest_path = private_knowledge.get("manifest_path")
        if isinstance(manifest_path, str) and manifest_path.strip():
            configured.append(PROJECT_ROOT / manifest_path)
    configured.extend(
        [
            PROJECT_ROOT / "src/agronomy_agent/agent.py",
            PROJECT_ROOT / "src/agronomy_agent/agno_runtime/knowledge_factory.py",
            PROJECT_ROOT / "src/agronomy_agent/agno_runtime/knowledge_graph.py",
            PROJECT_ROOT / "src/agronomy_agent/agno_runtime/local_index.py",
            PROJECT_ROOT / "src/agronomy_agent/agno_runtime/retriever_adapter.py",
            PROJECT_ROOT / "src/agronomy_agent/agno_runtime/source_ingest.py",
        ]
    )
    return tuple(configured)


def _runtime_implementation_receipts() -> dict[str, str]:
    single_files = {
        "capability_registry": "src/agronomy_agent/capability_registry.py",
        "tool_planner": "src/agronomy_agent/tool_planner.py",
        "graph_contract": "src/agronomy_agent/agno_runtime/knowledge_graph.py",
        "evidence_contract": "src/agronomy_agent/evidence_contracts.py",
        "answerability_policy": "src/agronomy_agent/answerability.py",
        "verifier_policy": "src/agronomy_agent/answer_verifier.py",
    }
    receipts = {
        receipt_id: file_sha256(PROJECT_ROOT / relative)
        for receipt_id, relative in single_files.items()
    }
    receipts.update(
        {
            "runtime_orchestrator": _bundle_sha256(
                (
                    PROJECT_ROOT / "src/agronomy_agent/agent.py",
                    PROJECT_ROOT
                    / "src/agronomy_agent/server/services/chat_service.py",
                )
            ),
            "kernel_config": _bundle_sha256(
                (PROJECT_ROOT / "src/agronomy_agent/agent.py",)
            ),
            "field_context_contract": _bundle_sha256(
                (
                    PROJECT_ROOT / "src/agronomy_agent/context_packer.py",
                    PROJECT_ROOT
                    / "src/agronomy_agent/server/services/field_context_compiler.py",
                    PROJECT_ROOT / "src/agronomy_agent/server/schemas.py",
                    PROJECT_ROOT / "configs/context_policy_v1.yaml",
                )
            ),
            "retrieval_config_and_assets": _bundle_sha256(
                _retrieval_runtime_paths(),
                allow_missing=True,
            ),
            "tool_executor_bundle": _bundle_sha256(
                (
                    PROJECT_ROOT / "src/agronomy_agent/tool_planner.py",
                    PROJECT_ROOT / "src/agronomy_agent/capability_registry.py",
                    PROJECT_ROOT / "src/agronomy_agent/tools/registry.py",
                    PROJECT_ROOT / "src/agronomy_agent/local_tools.py",
                    PROJECT_ROOT
                    / "src/agronomy_agent/agronomic_calculations.py",
                    PROJECT_ROOT
                    / "src/agronomy_agent/agno_runtime/tool_adapters.py",
                )
            ),
            "fallback_policy": _bundle_sha256(
                (
                    PROJECT_ROOT / "src/agronomy_agent/agent.py",
                    PROJECT_ROOT
                    / "src/agronomy_agent/server/services/chat_service.py",
                    PROJECT_ROOT / "src/agronomy_agent/answer_verifier.py",
                )
            ),
        }
    )
    return receipts


def _component_configuration_receipts(
    implementation_receipts: Mapping[str, str],
) -> dict[str, str]:
    implementation_by_component = {
        "kernel_prompt": "kernel_config",
        "field_context": "field_context_contract",
        "retrieval": "retrieval_config_and_assets",
        "typed_tools": "tool_executor_bundle",
        "risk_intervention": "answerability_policy",
        "verifier": "verifier_policy",
        "fallback": "fallback_policy",
    }
    return {
        component: str(implementation_receipts[receipt_id])
        for component, receipt_id in implementation_by_component.items()
    }


def _deterministic_executor_semantic_profile() -> dict[str, Any]:
    contract_path = (
        PROJECT_ROOT / "configs/open_agronomy_benchmark_v2_harness_contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    construct_profile = contract["semantic_profile"]
    return {
        "schema_version": construct_profile["schema_version"],
        "construct_profile_sha256": stable_sha256(construct_profile),
        "tool_implementations": {
            "agronomic_calculator": {
                "implementation_version": "agronomic_calculator_v1",
                "family": "supplied_input_arithmetic",
                "operations": [operation.value for operation in CalculationOperation],
                "authority_roles": ["supplied_inputs_arithmetic_only"],
            }
        },
        "evidence_implementations": {
            "governed_document_retrieval": {
                "implementation_version": "v1",
                "modality": "document",
            },
            "governed_graph_retrieval": {
                "implementation_version": "v1",
                "modality": "knowledge_graph",
            },
        },
    }


@dataclass(frozen=True)
class ModelIdentity:
    model_id: str
    model_revision: str
    backend: str
    configuration_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArmExecutionRequest:
    run_id: str
    case_index: int
    arm_index: int
    case: Mapping[str, Any]
    arm_id: str
    components: Mapping[str, bool]
    component_contracts: Mapping[str, Mapping[str, Any]]
    component_configuration_receipts: Mapping[str, str]
    model: ModelIdentity


class ArmExecutor(Protocol):
    executor_id: str
    executor_version: str
    result_class: str

    def harness_capabilities(self) -> Mapping[str, Any]: ...

    def execute(self, request: ArmExecutionRequest) -> Mapping[str, Any]: ...


def _tool_records(results: Sequence[Any]) -> list[dict[str, Any]]:
    return [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in results]


def _answerability_artifact_id(
    request: ArmExecutionRequest,
    decision: Mapping[str, Any],
) -> str:
    return "answerability_decision_" + stable_sha256(
        {
            "run_id": request.run_id,
            "eval_id": request.case["eval_id"],
            "arm_id": request.arm_id,
            "decision": decision,
        }
    )[:24]


def _verifier_artifact_id(
    request: ArmExecutionRequest,
    *,
    draft_sha256: str,
    trace: Mapping[str, Any],
) -> str:
    return "verifier_adjudication_" + stable_sha256(
        {
            "run_id": request.run_id,
            "eval_id": request.case["eval_id"],
            "arm_id": request.arm_id,
            "draft_sha256": draft_sha256,
            "policy_id": trace["policy_id"],
            "policy_version": trace["policy_version"],
            "decision_unit": trace["decision_unit"],
            "outcome_schema_version": trace["outcome_schema_version"],
            "decision_outcome": trace["decision_outcome"],
            "draft_intervention_required": trace[
                "draft_intervention_required"
            ],
            "intervened": trace["intervened"],
            "adjudication_source": trace["adjudication_source"],
        }
    )[:24]


class DeterministicContractExecutor:
    """Exercise orchestration and local contracts without model inference.

    Outputs are derived from frozen case expectations and deterministic tools.
    They are intentionally labeled synthetic and are prohibited from capability
    reporting, model comparison, or external claims.
    """

    executor_id = "deterministic_contract_executor"
    executor_version = "v1"
    result_class = "synthetic_contract_qa_not_system_performance"

    _COMPONENT_CONTRACT_VERSIONS = {
        "kernel_prompt": "v1",
        "field_context": "v1",
        "retrieval": "v1",
        "typed_tools": "v1",
        "risk_intervention": "v1",
        "verifier": "v1",
        "fallback": "v1",
    }
    _FEATURE_CONTRACT_VERSIONS = {
        "governed_prompt_kernel": "v1",
        "typed_field_context_snapshot": "v1",
        "governed_document_retrieval": "v1",
        "governed_graph_retrieval": "v1",
        "typed_tool_plan": "v1",
        "typed_tool_result": "v1",
        "answerability_state": "v1",
        "draft_verification": "v1",
        "replacement_audit": "v1",
        "answer_origin": "v1",
        "fallback_receipt": "v1",
    }

    def harness_capabilities(self) -> Mapping[str, Any]:
        implementation_receipts = _runtime_implementation_receipts()
        capabilities: dict[str, Any] = {
            "schema_version": EXECUTOR_CAPABILITIES_SCHEMA_VERSION,
            "executor_id": self.executor_id,
            "executor_version": self.executor_version,
            "result_class": self.result_class,
            "benchmark_id": "open_agronomy_benchmark_v2",
            "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
            "metric_schema_version": METRIC_SCHEMA_VERSION,
            "stage_topology": ["draft", "post_verification", "final"],
            "component_contract_versions": dict(self._COMPONENT_CONTRACT_VERSIONS),
            "feature_contract_versions": dict(self._FEATURE_CONTRACT_VERSIONS),
            "implementation_receipts": implementation_receipts,
            "component_configuration_receipts": (
                _component_configuration_receipts(implementation_receipts)
            ),
            "semantic_profile": _deterministic_executor_semantic_profile(),
            "system_identity": {
                "system_id": "open_agronomy_agent_deterministic_contract_qa",
                "system_revision": self.executor_version,
                "system_configuration_sha256": "",
            },
        }
        capabilities["system_identity"][
            "system_configuration_sha256"
        ] = derive_system_configuration_sha256(capabilities)
        return capabilities

    def execute(self, request: ArmExecutionRequest) -> Mapping[str, Any]:
        case = request.case
        components = dict(request.components)
        expected = case["expected_response"]
        plan, results = plan_and_execute_tools(
            str(case["question"]),
            field_context=case.get("field_context") if components.get("field_context") else None,
        )
        plan_record = plan.to_dict()
        result_records = _tool_records(results) if components.get("typed_tools") else []
        invocation_records = [
            invocation.to_dict()
            for invocation in plan.invocations
        ] if components.get("typed_tools") else []

        if components.get("risk_intervention"):
            answerability = assess_answerability(
                str(case["question"]),
                tool_plan=plan_record if components.get("typed_tools") else None,
                tool_results=result_records,
                field_context=case.get("field_context") if components.get("field_context") else None,
            )
            state = answerability.state.value
            answerability_decision = answerability.to_dict()
            answerability_decision["missing_inputs"] = list(
                answerability_decision["missing_inputs"]
            )
            answerability_artifact_id = _answerability_artifact_id(
                request,
                answerability_decision,
            )
            answerability_receipt = {
                **answerability_decision,
                "artifact_id": answerability_artifact_id,
            }
        else:
            answerability = None
            state = "answer_directly"
            answerability_artifact_id = None
            answerability_receipt = None

        expected_state = str(expected["acceptable_answerability_states"][0])
        pre_generation_intervened = bool(
            components.get("risk_intervention")
            and state in {"ask_one_discriminating_question", "require_authority", "refuse_unsafe_action"}
        )
        tool_result_used = bool(
            components.get("typed_tools")
            and result_records
            and case.get("tool_execution_expected") is True
        )
        tool_clarification_used = bool(
            components.get("typed_tools")
            and plan.status == "clarification_required"
            and case.get("stratum") == "one_critical_input_missing"
        )
        direct_answer = bool(
            tool_result_used
            or (
                not pre_generation_intervened
                and expected.get("direct_answer_expected") is True
            )
        )
        clarification_fields = (
            list(expected.get("clarification_fields") or [])
            if tool_clarification_used or state == "ask_one_discriminating_question"
            else []
        )
        clarifying_questions = (
            [
                str(plan.clarification or answerability.response_text or "What is the missing decision input?")
            ]
            if clarification_fields
            else []
        )

        if tool_result_used:
            answer_origin = "deterministic_tool_result"
            draft_text = str(result_records[0].get("payload", {}).get("answer") or "")
            answer_numeric = result_records[0].get("payload", {}).get("value")
        elif pre_generation_intervened:
            answer_origin = "pre_generation_answerability_intervention"
            draft_text = str(
                (answerability.response_text if answerability is not None else "")
                or plan.clarification
                or "A bounded authority or input check is required before the requested action."
            )
            answer_numeric = None
        else:
            answer_origin = "synthetic_mock_model"
            draft_text = (
                "Synthetic contract-QA response. This text is not a model result and must not be scored as agronomic ability."
            )
            answer_numeric = None

        verifier_had_opportunity = bool(components.get("verifier") and not pre_generation_intervened)
        draft_intervention_required = False if verifier_had_opportunity else None
        verifier_intervened = False if verifier_had_opportunity else None
        fallback_used = bool(components.get("fallback") and False)
        final_text = draft_text
        stages = {
            "draft": {"text": draft_text, "sha256": hashlib.sha256(draft_text.encode("utf-8")).hexdigest()},
            "post_verification": {"text": draft_text, "sha256": hashlib.sha256(draft_text.encode("utf-8")).hexdigest()},
            "final": {"text": final_text, "sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest()},
        }
        evidence_trace = {
            "schema_version": EVIDENCE_TRACE_SCHEMA_VERSION,
            "retrieval_requested": bool(components.get("retrieval")),
            "retrieval_status": "synthetic_not_executed" if components.get("retrieval") else "disabled_by_arm",
            "evidence_packet_id": None,
            "retrieved_document_ids": [],
            "graph_hit_ids": [],
            "evidence_items": [],
            "boundary": "The deterministic contract executor does not exercise retrieval.",
        }
        if not components.get("verifier"):
            verifier_outcome = "not_applicable_disabled"
        elif pre_generation_intervened:
            verifier_outcome = "not_applicable_pre_generation_prevention"
        elif draft_intervention_required:
            verifier_outcome = (
                "intervene_on_required_draft"
                if verifier_intervened
                else "miss_required_intervention"
            )
        else:
            verifier_outcome = (
                "intervene_on_acceptable_draft"
                if verifier_intervened
                else "accept_draft"
            )
        adjudication_source = (
            "synthetic_contract_executor"
            if verifier_had_opportunity
            else (
                "synthetic_not_applicable_pre_generation"
                if components.get("verifier")
                else "disabled_by_arm"
            )
        )
        verifier_trace = {
            "schema_version": VERIFIER_TRACE_SCHEMA_VERSION,
            "policy_id": "hard_safety_then_specificity",
            "policy_version": "v2",
            "decision_unit": "generated_draft_claim_risk",
            "outcome_schema_version": (
                "open_agronomy_agent.benchmark_v2_verifier_outcome.v1"
            ),
            "decision_outcome": verifier_outcome,
            "enabled_by_arm": bool(components.get("verifier")),
            "had_opportunity": verifier_had_opportunity,
            "draft_intervention_required": draft_intervention_required,
            "intervened": verifier_intervened,
            "adjudication_source": adjudication_source,
            "artifact_id": None,
        }
        verifier_artifact_id = (
            _verifier_artifact_id(
                request,
                draft_sha256=stages["draft"]["sha256"],
                trace=verifier_trace,
            )
            if verifier_had_opportunity
            else None
        )
        verifier_trace["artifact_id"] = verifier_artifact_id
        typed_tool_artifact_ids = [
            *(
                str(item.get("invocation_id"))
                for item in invocation_records
                if item.get("invocation_id")
            ),
            *(
                str(item.get("result_id"))
                for item in result_records
                if item.get("result_id")
            ),
        ]
        component_receipts = {
            component: {
                "enabled_by_arm": enabled,
                "execution_status": "synthetic_contract_qa" if enabled else "disabled_by_arm",
                "component_id": request.component_contracts[component]["component_id"],
                "component_version": request.component_contracts[component]["contract_version"],
                "configuration_sha256": request.component_configuration_receipts[
                    component
                ],
                "artifact_ids": (
                    typed_tool_artifact_ids
                    if component == "typed_tools"
                    else (
                        [verifier_artifact_id]
                        if component == "verifier" and verifier_artifact_id
                        else (
                            [answerability_artifact_id]
                            if component == "risk_intervention"
                            and answerability_artifact_id
                            else []
                        )
                    )
                ),
                "boundary": "Synthetic expectation-driven harness exercise; not observed runtime execution.",
            }
            for component, enabled in components.items()
        }
        return {
            "status": "completed",
            "direct_answer": direct_answer,
            "abstained": state == "refuse_unsafe_action",
            "clarifying_questions": clarifying_questions,
            "clarification_fields": clarification_fields,
            "selected_tools": ["agronomic_calculator"] if components.get("typed_tools") and case.get("expected_tools") else [],
            "tool_plan": plan_record if components.get("typed_tools") else None,
            "tool_invocations": invocation_records,
            "tool_results": result_records,
            "pre_generation_intervened": pre_generation_intervened,
            "pre_generation_intervention": answerability_receipt,
            "verifier_had_opportunity": verifier_had_opportunity,
            "draft_verifier_intervention_required": draft_intervention_required,
            "verifier_intervened": verifier_intervened,
            "verifier_trace": verifier_trace,
            "answer_numeric": answer_numeric,
            "answerability_state": state if components.get("risk_intervention") else None,
            "action_commitment_made": False,
            "answer_origin": answer_origin,
            "fallback_used": fallback_used,
            "fallback_justified": None,
            "answer_stages": stages,
            "evidence_trace": evidence_trace,
            "component_receipts": component_receipts,
            "synthetic_expected_state": expected_state,
            "interpretation_boundary": (
                "Synthetic expectation-driven contract QA; not observed system performance."
            ),
        }


def validate_interface(interface: Mapping[str, Any]) -> tuple[str, ...]:
    components = tuple(str(value) for value in interface.get("component_fields") or ())
    arm_order = tuple(str(value) for value in interface.get("arm_order") or ())
    arms = interface.get("arms") or {}
    if not components or not arm_order or not isinstance(arms, Mapping):
        raise ValueError("v2 interface is missing components, arm_order, or arms")
    if len(arm_order) != len(set(arm_order)) or set(arm_order) != set(arms):
        raise ValueError("v2 arm_order must contain every declared arm exactly once")
    for arm_id in arm_order:
        arm = arms[arm_id]
        if not isinstance(arm, Mapping):
            raise ValueError(f"arm is not an object: {arm_id}")
        missing = [component for component in components if not isinstance(arm.get(component), bool)]
        if missing:
            raise ValueError(f"arm {arm_id} has missing/non-boolean components: {missing}")
    if interface.get("claim_eligible") is not False:
        raise ValueError("Benchmark v2 interface must remain claim_eligible=false")
    return arm_order


def _exact_mapping(value: Any, fields: set[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} fields do not match the frozen contract")
    return value


def _string_list(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must not contain duplicate IDs")
    return value


def _validate_answerability_trace(
    request: ArmExecutionRequest,
    raw: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    semantic_profile: Mapping[str, Any],
) -> None:
    enabled = bool(request.components.get("risk_intervention"))
    if not enabled:
        if (
            raw.get("pre_generation_intervened") is not False
            or raw.get("pre_generation_intervention") is not None
            or raw.get("answerability_state") is not None
            or receipt.get("artifact_ids")
        ):
            raise ValueError(
                "risk_intervention-disabled arm contains policy contamination"
            )
        return

    state = raw.get("answerability_state")
    if not isinstance(state, str) or not state:
        raise ValueError("enabled risk intervention requires answerability_state")
    if state not in set(
        semantic_profile["construct_semantics"]["answerability_states"]
    ):
        raise ValueError("answerability_state uses an unknown semantic class")

    policy = _exact_mapping(
        raw.get("pre_generation_intervention"),
        {
            "schema_version",
            "state",
            "reason",
            "rule_pack_id",
            "risk",
            "missing_inputs",
            "failed_claim",
            "required_authority",
            "response_text",
            "artifact_id",
        },
        label="answerability policy receipt",
    )
    if policy.get("schema_version") != ANSWERABILITY_POLICY_VERSION:
        raise ValueError("answerability policy receipt schema version mismatch")
    if policy.get("state") != state:
        raise ValueError("answerability policy receipt state mismatch")
    for field in ("reason", "rule_pack_id", "risk"):
        if not isinstance(policy.get(field), str) or not policy.get(field):
            raise ValueError(
                f"answerability policy receipt requires non-empty text: {field}"
            )
    for field in ("failed_claim", "required_authority", "response_text"):
        value = policy.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(
                f"answerability policy receipt field must be non-empty text or null: {field}"
            )
    missing_inputs = _string_list(
        policy.get("missing_inputs"),
        label="answerability policy receipt missing_inputs",
    )
    artifact_id = policy.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ValueError("answerability policy receipt requires an artifact ID")
    decision = {key: value for key, value in policy.items() if key != "artifact_id"}
    if artifact_id != _answerability_artifact_id(request, decision):
        raise ValueError("answerability policy receipt artifact ID is not content-addressed")
    if receipt.get("artifact_ids") != [artifact_id]:
        raise ValueError(
            "risk_intervention artifact ID does not match its policy receipt"
        )

    questions = raw["clarifying_questions"]
    fields = raw["clarification_fields"]
    hold_states = {
        "ask_one_discriminating_question",
        "require_authority",
        "refuse_unsafe_action",
    }
    expected_hold = state in hold_states
    if raw.get("pre_generation_intervened") is not expected_hold:
        raise ValueError("answerability state does not match pre-generation hold state")

    if state in {"answer_directly", "answer_with_bounded_uncertainty"}:
        if (
            raw.get("direct_answer") is not True
            or raw.get("abstained") is not False
            or questions
            or fields
            or missing_inputs
            or policy.get("failed_claim") is not None
            or policy.get("required_authority") is not None
            or policy.get("response_text") is not None
        ):
            raise ValueError("answerable state is inconsistent with answer disposition")
        if (
            state == "answer_with_bounded_uncertainty"
            and raw.get("action_commitment_made") is not False
        ):
            raise ValueError(
                "bounded-uncertainty answer cannot make an action commitment"
            )
        return

    if raw.get("direct_answer") is not False or raw.get(
        "action_commitment_made"
    ) is not False:
        raise ValueError("answerability hold cannot answer directly or commit an action")
    if state == "ask_one_discriminating_question":
        if (
            raw.get("abstained") is not False
            or len(questions) != 1
            or not fields
            or not missing_inputs
            or not isinstance(policy.get("failed_claim"), str)
            or not isinstance(policy.get("response_text"), str)
            or questions != [policy["response_text"]]
            or policy.get("required_authority") is not None
        ):
            raise ValueError(
                "discriminating-question state lacks one linked clarification"
            )
        return
    if questions or fields or missing_inputs:
        raise ValueError("authority/refusal hold cannot contain clarification state")
    if raw.get("abstained") is not (state == "refuse_unsafe_action"):
        raise ValueError("authority/refusal state has inconsistent abstention")
    if not isinstance(policy.get("failed_claim"), str) or not isinstance(
        policy.get("response_text"), str
    ):
        raise ValueError("authority/refusal hold lacks a typed blocked-claim response")
    if state == "require_authority" and not isinstance(
        policy.get("required_authority"), str
    ):
        raise ValueError("require_authority state lacks required_authority")


def _validate_tool_trace(
    request: ArmExecutionRequest,
    raw: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    executor: ArmExecutor,
    semantic_profile: Mapping[str, Any],
) -> None:
    tool_semantics = semantic_profile["construct_semantics"]["tool_semantics"]
    tool_implementations = semantic_profile["tool_implementations"]
    selected_tools = _string_list(raw.get("selected_tools"), label="selected_tools")
    invocations = raw.get("tool_invocations")
    results = raw.get("tool_results")
    if not isinstance(invocations, list) or not isinstance(results, list):
        raise ValueError("tool invocations/results must be arrays")
    if not request.components.get("typed_tools"):
        if raw.get("tool_plan") is not None or selected_tools or invocations or results:
            raise ValueError("executor emitted tool records while typed_tools is disabled")
        if receipt.get("artifact_ids"):
            raise ValueError("disabled typed_tools component emitted artifact IDs")
        return

    plan = _exact_mapping(
        raw.get("tool_plan"),
        {
            "schema_version",
            "planner_version",
            "status",
            "invocations",
            "clarification",
        },
        label="tool plan",
    )
    if plan.get("schema_version") != TOOL_PLAN_SCHEMA_VERSION or plan.get(
        "planner_version"
    ) != PLANNER_VERSION:
        raise ValueError("tool plan schema/planner version mismatch")
    if plan.get("status") not in set(tool_semantics["plan_statuses"]):
        raise ValueError("tool plan status is not declared")
    if plan.get("clarification") is not None and not isinstance(
        plan.get("clarification"), str
    ):
        raise ValueError("tool plan clarification must be text or null")
    planned_invocations = plan.get("invocations")
    if not isinstance(planned_invocations, Sequence) or isinstance(
        planned_invocations, (str, bytes)
    ):
        raise ValueError("tool plan invocations must be an array")
    if canonical_json(planned_invocations) != canonical_json(invocations):
        raise ValueError("tool plan/top-level invocation linkage mismatch")

    invocation_fields = {
        "schema_version",
        "invocation_id",
        "planner_version",
        "tool_id",
        "tool_version",
        "operation",
        "inputs",
        "question_sha256",
        "status",
        "missing_inputs",
        "authority_role",
        "risk_class",
    }
    question_sha256 = hashlib.sha256(
        str(request.case["question"]).encode("utf-8")
    ).hexdigest()
    invocations_by_id: dict[str, Mapping[str, Any]] = {}
    for value in invocations:
        invocation = _exact_mapping(value, invocation_fields, label="tool invocation")
        invocation_id = str(invocation.get("invocation_id") or "")
        if not invocation_id or invocation_id in invocations_by_id:
            raise ValueError("tool invocation IDs must be unique and non-empty")
        if invocation.get("schema_version") != TOOL_INVOCATION_SCHEMA_VERSION or invocation.get(
            "planner_version"
        ) != PLANNER_VERSION:
            raise ValueError("tool invocation schema/planner version mismatch")
        if invocation.get("question_sha256") != question_sha256:
            raise ValueError("tool invocation question hash mismatch")
        if not isinstance(invocation.get("inputs"), Mapping):
            raise ValueError("tool invocation inputs must be an object")
        missing_inputs = invocation.get("missing_inputs")
        if not isinstance(missing_inputs, Sequence) or isinstance(
            missing_inputs, (str, bytes)
        ) or not all(isinstance(item, str) and item for item in missing_inputs):
            raise ValueError("tool invocation missing_inputs must be typed strings")
        if not all(
            isinstance(invocation.get(field), str) and invocation.get(field)
            for field in (
                "tool_id",
                "tool_version",
                "operation",
                "authority_role",
                "risk_class",
            )
        ):
            raise ValueError("tool invocation identity fields are malformed")
        tool_id = str(invocation["tool_id"])
        implementation = tool_implementations.get(tool_id)
        if not isinstance(implementation, Mapping):
            raise ValueError("tool invocation uses an undeclared implementation ID")
        family = tool_semantics["families"].get(implementation.get("family"))
        if not isinstance(family, Mapping):
            raise ValueError("tool invocation uses an unknown semantic family")
        if (
            invocation.get("tool_version")
            != implementation.get("implementation_version")
            or invocation.get("operation")
            not in set(implementation.get("operations") or ())
            or invocation.get("operation") not in set(family["operations"])
            or invocation.get("authority_role")
            not in set(implementation.get("authority_roles") or ())
            or invocation.get("authority_role") not in set(family["authority_roles"])
            or invocation.get("status") not in set(family["invocation_statuses"])
        ):
            raise ValueError("tool invocation uses an unknown operation/authority/status semantic")
        expected_invocation_id = "invocation_" + stable_sha256(
            {
                "planner_version": invocation["planner_version"],
                "tool_id": invocation["tool_id"],
                "tool_version": invocation["tool_version"],
                "operation": invocation["operation"],
                "inputs": invocation["inputs"],
                "question_sha256": invocation["question_sha256"],
            }
        )[:24]
        if invocation_id != expected_invocation_id:
            raise ValueError(
                "tool invocation ID does not match canonical invocation content"
            )
        invocations_by_id[invocation_id] = invocation

    result_fields = {
        "schema_version",
        "result_id",
        "invocation_id",
        "tool_id",
        "tool_version",
        "operation",
        "status",
        "payload",
        "payload_sha256",
        "authority_role",
        "freshness_status",
        "provenance",
        "limitations",
    }
    result_ids: list[str] = []
    for value in results:
        result = _exact_mapping(value, result_fields, label="tool result")
        result_id = str(result.get("result_id") or "")
        invocation_id = str(result.get("invocation_id") or "")
        if not result_id or result_id in result_ids:
            raise ValueError("tool result IDs must be unique and non-empty")
        invocation = invocations_by_id.get(invocation_id)
        if invocation is None:
            raise ValueError("tool result references an unknown invocation")
        if result.get("schema_version") != TOOL_RESULT_SCHEMA_VERSION:
            raise ValueError("tool result schema version mismatch")
        if not isinstance(result.get("payload"), Mapping) or result.get(
            "payload_sha256"
        ) != stable_sha256(result["payload"]):
            raise ValueError("tool result payload hash mismatch")
        expected_result_id = "tool_result_" + stable_sha256(
            {
                "invocation_id": invocation_id,
                "payload_sha256": result["payload_sha256"],
            }
        )[:24]
        if result_id != expected_result_id:
            raise ValueError("tool result ID does not match canonical result content")
        if any(
            result.get(field) != invocation.get(field)
            for field in ("tool_id", "tool_version", "operation", "authority_role")
        ):
            raise ValueError("tool result identity does not match its invocation")
        implementation = tool_implementations[str(result["tool_id"])]
        family = tool_semantics["families"][implementation["family"]]
        if result.get("status") not in set(family["result_statuses"]):
            raise ValueError("tool result uses an unknown status semantic")
        limitations = result.get("limitations")
        if not isinstance(limitations, Sequence) or isinstance(
            limitations, (str, bytes)
        ) or not all(isinstance(item, str) for item in limitations):
            raise ValueError("tool result limitations must be typed strings")
        if not all(
            isinstance(result.get(field), str) and result.get(field)
            for field in ("status", "freshness_status", "provenance")
        ):
            raise ValueError("tool result status/provenance fields are malformed")
        result_ids.append(result_id)

    plan_status = str(plan["status"])
    clarification = plan.get("clarification")
    result_invocation_ids = {str(value["invocation_id"]) for value in results}
    if plan_status == "not_applicable":
        if invocations or results or selected_tools or clarification is not None:
            raise ValueError("not_applicable tool plan must be empty")
    elif plan_status == "clarification_required":
        if not invocations or results:
            raise ValueError(
                "clarification_required tool plan requires invocations and no results"
            )
        if not isinstance(clarification, str) or not clarification.strip():
            raise ValueError(
                "clarification_required tool plan requires non-empty clarification text"
            )
        clarification_text = clarification.casefold()
        if any(
            invocation.get("status") != "clarification_required"
            or not invocation.get("missing_inputs")
            or any(
                str(missing).casefold() not in clarification_text
                for missing in invocation["missing_inputs"]
            )
            for invocation in invocations_by_id.values()
        ):
            raise ValueError(
                "clarification_required tool plan lacks linked missing inputs"
            )
        if raw.get("clarifying_questions") != [clarification] or not raw.get(
            "clarification_fields"
        ):
            raise ValueError(
                "clarification_required tool plan lacks matching top-level clarification"
            )
    elif plan_status == "ready":
        if (
            not invocations
            or clarification is not None
            or any(
                invocation.get("status") != "planned"
                or invocation.get("missing_inputs")
                for invocation in invocations_by_id.values()
            )
        ):
            raise ValueError("ready tool plan lacks executable invocations")
        if request.case.get("tool_execution_expected") is True and (
            not results or result_invocation_ids != set(invocations_by_id)
        ):
            raise ValueError(
                "ready tool plan lacks the result required by the benchmark case"
            )
    else:
        raise ValueError("tool plan status has no frozen structural semantics")

    invoked_tools = {str(value["tool_id"]) for value in invocations_by_id.values()}
    if set(selected_tools) != invoked_tools:
        raise ValueError("selected_tools does not match typed invocation identities")
    expected_artifact_ids = [*invocations_by_id, *result_ids]
    if set(receipt.get("artifact_ids") or ()) != set(expected_artifact_ids):
        raise ValueError("typed_tools artifact IDs do not match invocation/result records")
    if executor.result_class == "observed_system_execution_nonclaim":
        expected_status = (
            "completed"
            if results
            else "completed_no_result"
            if invocations
            else "not_applicable_case"
        )
        if receipt.get("execution_status") != expected_status:
            raise ValueError("typed_tools execution status does not match its records")


def _validate_evidence_trace(
    request: ArmExecutionRequest,
    raw: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    executor: ArmExecutor,
    semantic_profile: Mapping[str, Any],
) -> None:
    trace = _exact_mapping(
        raw.get("evidence_trace"),
        {
            "schema_version",
            "retrieval_requested",
            "retrieval_status",
            "evidence_packet_id",
            "retrieved_document_ids",
            "graph_hit_ids",
            "evidence_items",
            "boundary",
        },
        label="evidence trace",
    )
    if trace.get("schema_version") != EVIDENCE_TRACE_SCHEMA_VERSION:
        raise ValueError("evidence trace schema version mismatch")
    enabled = bool(request.components.get("retrieval"))
    if trace.get("retrieval_requested") is not enabled:
        raise ValueError("evidence trace retrieval enablement mismatch")
    document_ids = _string_list(
        trace.get("retrieved_document_ids"), label="retrieved_document_ids"
    )
    graph_ids = _string_list(trace.get("graph_hit_ids"), label="graph_hit_ids")
    evidence_items = trace.get("evidence_items")
    if not isinstance(evidence_items, list):
        raise ValueError("evidence_items must be an array")
    packet_id = trace.get("evidence_packet_id")
    if not enabled:
        if (
            trace.get("retrieval_status") != "disabled_by_arm"
            or packet_id is not None
            or document_ids
            or graph_ids
            or evidence_items
            or receipt.get("artifact_ids")
        ):
            raise ValueError("retrieval-disabled arm contains evidence contamination")
        return
    construct = semantic_profile["construct_semantics"]["evidence_semantics"]
    implementations = semantic_profile["evidence_implementations"]
    item_ids: set[str] = set()
    document_item_ids: set[str] = set()
    graph_item_ids: set[str] = set()
    for value in evidence_items:
        item = _exact_mapping(
            value,
            {
                "evidence_id",
                "implementation_id",
                "modality",
                "evidence_role",
                "factual_authority",
                "field_action_authority",
            },
            label="evidence item",
        )
        evidence_id = str(item.get("evidence_id") or "")
        implementation_id = str(item.get("implementation_id") or "")
        implementation = implementations.get(implementation_id)
        modality = str(item.get("modality") or "")
        if not evidence_id or evidence_id in item_ids:
            raise ValueError("evidence item IDs must be unique and non-empty")
        if not isinstance(implementation, Mapping) or implementation.get(
            "modality"
        ) != modality:
            raise ValueError("evidence item uses an undeclared implementation/modality")
        if (
            modality not in set(construct["modalities"])
            or item.get("evidence_role") not in set(construct["evidence_roles"])
            or item.get("factual_authority")
            not in set(construct["factual_authority_classes"])
            or item.get("field_action_authority")
            not in set(construct["field_action_authority_classes"])
        ):
            raise ValueError("evidence item uses an unknown authority semantic class")
        item_ids.add(evidence_id)
        if modality == "document":
            document_item_ids.add(evidence_id)
        elif modality == "knowledge_graph":
            graph_item_ids.add(evidence_id)
    if set(document_ids) != document_item_ids or set(graph_ids) != graph_item_ids:
        raise ValueError("evidence item modalities do not match document/graph trace IDs")
    if not isinstance(trace.get("boundary"), str) or not trace.get("boundary"):
        raise ValueError("evidence trace boundary must be non-empty text")
    if trace.get("retrieval_status") not in set(construct["retrieval_statuses"]):
        raise ValueError("evidence trace uses an unknown retrieval status")
    if executor.result_class == "synthetic_contract_qa_not_system_performance":
        if (
            trace.get("retrieval_status") != "synthetic_not_executed"
            or packet_id is not None
            or document_ids
            or graph_ids
            or evidence_items
            or receipt.get("artifact_ids")
        ):
            raise ValueError("synthetic retrieval trace must remain explicitly unexecuted")
        return
    status = str(receipt.get("execution_status") or "")
    if trace.get("retrieval_status") != status or status not in {
        "completed",
        "completed_no_result",
    }:
        raise ValueError("retrieval trace status does not match component execution")
    if not isinstance(packet_id, str) or not packet_id:
        raise ValueError("observed retrieval requires an evidence packet ID")
    if status == "completed" and not (document_ids or graph_ids):
        raise ValueError("completed retrieval must identify retrieved evidence")
    if status == "completed_no_result" and (document_ids or graph_ids):
        raise ValueError("completed_no_result retrieval cannot contain evidence hits")
    if set(receipt.get("artifact_ids") or ()) != {
        packet_id,
        *document_ids,
        *graph_ids,
    }:
        raise ValueError("retrieval artifact IDs do not match its evidence trace")


def _validate_verifier_trace(
    request: ArmExecutionRequest,
    raw: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    executor: ArmExecutor,
    semantic_profile: Mapping[str, Any],
) -> None:
    verifier_semantics = semantic_profile["construct_semantics"][
        "verifier_semantics"
    ]
    trace = _exact_mapping(
        raw.get("verifier_trace"),
        {
            "schema_version",
            "policy_id",
            "policy_version",
            "decision_unit",
            "outcome_schema_version",
            "decision_outcome",
            "enabled_by_arm",
            "had_opportunity",
            "draft_intervention_required",
            "intervened",
            "adjudication_source",
            "artifact_id",
        },
        label="verifier trace",
    )
    if trace.get("schema_version") != VERIFIER_TRACE_SCHEMA_VERSION:
        raise ValueError("verifier trace schema version mismatch")
    for field in (
        "policy_id",
        "policy_version",
        "decision_unit",
        "outcome_schema_version",
    ):
        if trace.get(field) != verifier_semantics[field]:
            raise ValueError(f"verifier trace semantic identity mismatch: {field}")
    if trace.get("decision_outcome") not in set(verifier_semantics["outcomes"]):
        raise ValueError("verifier trace uses an unknown decision outcome semantic")
    enabled = bool(request.components.get("verifier"))
    if trace.get("enabled_by_arm") is not enabled:
        raise ValueError("verifier trace enablement mismatch")
    for trace_field, raw_field in (
        ("had_opportunity", "verifier_had_opportunity"),
        ("draft_intervention_required", "draft_verifier_intervention_required"),
        ("intervened", "verifier_intervened"),
    ):
        if trace.get(trace_field) != raw.get(raw_field):
            raise ValueError(f"verifier trace does not match {raw_field}")
    source = trace.get("adjudication_source")
    if not isinstance(source, str) or not source:
        raise ValueError("verifier adjudication source must be non-empty text")
    artifact_id = trace.get("artifact_id")
    if not enabled:
        expected_outcome = "not_applicable_disabled"
    elif raw.get("pre_generation_intervened") is True:
        expected_outcome = "not_applicable_pre_generation_prevention"
    elif trace.get("draft_intervention_required") is True:
        expected_outcome = (
            "intervene_on_required_draft"
            if trace.get("intervened") is True
            else "miss_required_intervention"
        )
    elif trace.get("draft_intervention_required") is False:
        expected_outcome = (
            "intervene_on_acceptable_draft"
            if trace.get("intervened") is True
            else "accept_draft"
        )
    else:
        expected_outcome = None
    if expected_outcome is not None and trace.get("decision_outcome") != expected_outcome:
        raise ValueError("verifier decision outcome does not match draft adjudication")
    if not enabled:
        if (
            trace.get("had_opportunity") is not False
            or trace.get("draft_intervention_required") is not None
            or trace.get("intervened") is not None
            or source != "disabled_by_arm"
            or artifact_id is not None
            or receipt.get("artifact_ids")
        ):
            raise ValueError("verifier-disabled arm contains verifier contamination")
        return
    if raw.get("pre_generation_intervened") is True:
        if (
            trace.get("had_opportunity") is not False
            or trace.get("draft_intervention_required") is not None
            or trace.get("intervened") is not None
            or artifact_id is not None
            or receipt.get("artifact_ids")
        ):
            raise ValueError("pre-generation prevention cannot contain draft adjudication")
        if (
            executor.result_class == "observed_system_execution_nonclaim"
            and receipt.get("execution_status")
            != "not_applicable_pre_generation_prevention"
        ):
            raise ValueError("verifier receipt must record pre-generation non-applicability")
        return
    if (
        trace.get("had_opportunity") is not True
        or not isinstance(trace.get("draft_intervention_required"), bool)
        or not isinstance(trace.get("intervened"), bool)
    ):
        raise ValueError("completed verifier requires explicit draft adjudication booleans")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ValueError("completed verifier requires an adjudication artifact ID")
    expected_artifact_id = _verifier_artifact_id(
        request,
        draft_sha256=raw["answer_stages"]["draft"]["sha256"],
        trace=trace,
    )
    if artifact_id != expected_artifact_id:
        raise ValueError(
            "verifier artifact ID is not content-addressed to its adjudication"
        )
    if receipt.get("artifact_ids") != [artifact_id]:
        raise ValueError("verifier artifact ID does not match its adjudication trace")
    if (
        executor.result_class == "observed_system_execution_nonclaim"
        and receipt.get("execution_status") != "completed"
    ):
        raise ValueError("draft adjudication requires a completed verifier receipt")


def _complete_observation(
    request: ArmExecutionRequest,
    raw: Mapping[str, Any],
    *,
    executor: ArmExecutor,
    negotiation: Mapping[str, Any],
    harness_contract: Mapping[str, Any],
) -> dict[str, Any]:
    required = {
        "status",
        "direct_answer",
        "abstained",
        "clarifying_questions",
        "clarification_fields",
        "selected_tools",
        "tool_plan",
        "tool_invocations",
        "tool_results",
        "pre_generation_intervened",
        "pre_generation_intervention",
        "verifier_had_opportunity",
        "draft_verifier_intervention_required",
        "verifier_intervened",
        "verifier_trace",
        "answer_numeric",
        "answerability_state",
        "action_commitment_made",
        "answer_origin",
        "fallback_used",
        "fallback_justified",
        "answer_stages",
        "evidence_trace",
        "component_receipts",
        "interpretation_boundary",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"executor omitted required observation fields: {missing}")
    unknown = sorted(set(raw) - ALLOWED_EXECUTOR_OBSERVATION_FIELDS)
    if unknown:
        raise ValueError(
            "executor emitted undeclared observation fields; migration or a new benchmark "
            f"contract is required: {unknown}"
        )
    components = dict(request.components)
    if raw.get("status") != "completed":
        raise ValueError(f"executor observation is not completed: {raw.get('status')!r}")
    for field in (
        "direct_answer",
        "abstained",
        "pre_generation_intervened",
        "verifier_had_opportunity",
        "action_commitment_made",
        "fallback_used",
    ):
        if not isinstance(raw.get(field), bool):
            raise ValueError(f"executor observation field must be boolean: {field}")
    for field in (
        "draft_verifier_intervention_required",
        "verifier_intervened",
        "fallback_justified",
    ):
        if raw.get(field) is not None and not isinstance(raw.get(field), bool):
            raise ValueError(f"executor observation field must be boolean or null: {field}")
    for field in ("clarifying_questions", "clarification_fields"):
        _string_list(raw.get(field), label=field)
    if not isinstance(raw.get("answer_origin"), str) or not raw.get("answer_origin"):
        raise ValueError("answer_origin must be non-empty text")
    if not isinstance(raw.get("interpretation_boundary"), str) or not raw.get(
        "interpretation_boundary"
    ):
        raise ValueError("interpretation_boundary must be non-empty text")
    component_receipts = raw.get("component_receipts")
    if not isinstance(component_receipts, Mapping) or set(component_receipts) != set(components):
        raise ValueError("executor must emit exactly one receipt for every declared component")
    required_receipt_fields = {
        "enabled_by_arm",
        "execution_status",
        "component_id",
        "component_version",
        "configuration_sha256",
        "artifact_ids",
        "boundary",
    }
    for component, enabled in components.items():
        receipt = component_receipts.get(component)
        if not isinstance(receipt, Mapping) or receipt.get("enabled_by_arm") is not enabled:
            raise ValueError(f"component receipt enablement mismatch: {component}")
        if set(receipt) != required_receipt_fields:
            raise ValueError(f"component receipt fields do not match the frozen contract: {component}")
        declaration = request.component_contracts[component]
        if (
            receipt.get("component_id") != declaration.get("component_id")
            or receipt.get("component_version") != declaration.get("contract_version")
            or receipt.get("configuration_sha256")
            != negotiation["component_configuration_receipts"][component]
        ):
            raise ValueError(f"component identity/version/configuration mismatch: {component}")
        artifact_ids = _string_list(
            receipt.get("artifact_ids"), label=f"{component} artifact_ids"
        )
        if not isinstance(receipt.get("boundary"), str) or not receipt.get("boundary"):
            raise ValueError(f"component receipt artifacts/boundary are malformed: {component}")
        status = str(receipt.get("execution_status") or "")
        if not enabled and status != "disabled_by_arm":
            raise ValueError(f"disabled component lacks disabled_by_arm receipt: {component}")
        if enabled and executor.result_class == "synthetic_contract_qa_not_system_performance" and status != "synthetic_contract_qa":
            raise ValueError(f"synthetic component lacks contract-QA receipt: {component}")
        if enabled and executor.result_class == "observed_system_execution_nonclaim":
            allowed = set(str(value) for value in declaration["allowed_observed_statuses"])
            if component == "typed_tools" and request.case.get("expected_tools"):
                allowed.discard("not_applicable_case")
            if component == "verifier":
                allowed = (
                    {"not_applicable_pre_generation_prevention"}
                    if raw.get("pre_generation_intervened") is True
                    else {"completed"}
                )
            if status not in allowed:
                raise ValueError(f"enabled observed component is unavailable, failed, or unreceipted: {component}:{status}")
            if (
                status in {"completed", "completed_no_result"}
                and component not in {"retrieval", "typed_tools", "verifier"}
                and not artifact_ids
            ):
                raise ValueError(
                    f"completed observed component lacks an execution artifact: {component}"
                )
    answer_stages = raw.get("answer_stages")
    expected_stages = set(str(value) for value in harness_contract["stage_topology"])
    if not isinstance(answer_stages, Mapping) or set(answer_stages) != expected_stages:
        raise ValueError("answer stages do not match the frozen harness topology")
    for stage in expected_stages:
        record = _exact_mapping(
            answer_stages[stage], {"text", "sha256"}, label=f"answer stage {stage}"
        )
        if not isinstance(record.get("text"), str):
            raise ValueError(f"answer stage is malformed: {stage}")
        if record.get("sha256") != hashlib.sha256(record["text"].encode("utf-8")).hexdigest():
            raise ValueError(f"answer stage hash mismatch: {stage}")
    if raw.get("pre_generation_intervened") is True and raw.get("verifier_had_opportunity") is True:
        raise ValueError("a prevented draft cannot also create verifier opportunity")
    _validate_answerability_trace(
        request,
        raw,
        component_receipts["risk_intervention"],
        semantic_profile=negotiation["semantic_profile"],
    )
    _validate_tool_trace(
        request,
        raw,
        component_receipts["typed_tools"],
        executor=executor,
        semantic_profile=negotiation["semantic_profile"],
    )
    _validate_evidence_trace(
        request,
        raw,
        component_receipts["retrieval"],
        executor=executor,
        semantic_profile=negotiation["semantic_profile"],
    )
    _validate_verifier_trace(
        request,
        raw,
        component_receipts["verifier"],
        executor=executor,
        semantic_profile=negotiation["semantic_profile"],
    )
    draft = answer_stages["draft"]
    post_verification = answer_stages["post_verification"]
    final = answer_stages["final"]
    if raw.get("verifier_intervened") is True:
        if post_verification["sha256"] == draft["sha256"]:
            raise ValueError("verifier intervention did not change the draft stage")
    elif post_verification["sha256"] != draft["sha256"]:
        raise ValueError("post-verification stage changed without verifier intervention")
    if not components.get("fallback"):
        if (
            raw.get("fallback_used") is not False
            or raw.get("fallback_justified") is not None
            or "fallback" in str(raw.get("answer_origin") or "").casefold()
            or final["sha256"] != post_verification["sha256"]
        ):
            raise ValueError("fallback-disabled arm contains fallback contamination")
    elif raw.get("fallback_used") is True:
        if (
            not isinstance(raw.get("fallback_justified"), bool)
            or "fallback" not in str(raw.get("answer_origin") or "").casefold()
            or component_receipts["fallback"].get("execution_status") != "completed"
        ):
            raise ValueError("used fallback lacks an explicit justified fallback receipt")
    elif raw.get("fallback_justified") is not None or final["sha256"] != post_verification[
        "sha256"
    ]:
        raise ValueError("unused fallback changed the final answer or justification state")
    identity = {
        "run_id": request.run_id,
        "case_index": request.case_index,
        "arm_index": request.arm_index,
        "sample_id": "single_sample",
        "eval_id": request.case["eval_id"],
        "arm_id": request.arm_id,
        "components": components,
        "model": request.model.to_dict(),
        "model_id": request.model.model_id,
        "model_revision": request.model.model_revision,
        "model_backend": request.model.backend,
        "model_configuration_sha256": request.model.configuration_sha256,
        "executor_id": executor.executor_id,
        "executor_version": executor.executor_version,
        "construct_fingerprint": negotiation["construct_fingerprint"],
        "cohort_fingerprint": negotiation["cohort_fingerprint"],
        "system_fingerprint": negotiation["system_fingerprint"],
        "executor_capabilities_sha256": negotiation[
            "executor_capabilities_sha256"
        ],
        "component_contract_versions": dict(
            negotiation["component_contract_versions"]
        ),
        "feature_contract_versions": dict(negotiation["feature_contract_versions"]),
        "implementation_receipts": dict(negotiation["implementation_receipts"]),
        "component_configuration_receipts": dict(
            negotiation["component_configuration_receipts"]
        ),
        "semantic_profile": dict(negotiation["semantic_profile"]),
        **dict(negotiation["system_identity"]),
    }
    observation = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": "observation_" + stable_sha256(identity)[:24],
        **identity,
        "match_group": request.case["match_group"],
        "stratum": request.case["stratum"],
        "risk_level": request.case["risk_level"],
        "result_class": executor.result_class,
        **dict(raw),
    }
    observation["observation_sha256"] = stable_sha256(observation)
    return observation


def run_benchmark_v2(
    *,
    cases: Sequence[Mapping[str, Any]],
    interface: Mapping[str, Any],
    model: ModelIdentity,
    executor: ArmExecutor,
    suite_sha256: str,
    interface_sha256: str,
    contract_sha256: str,
    harness_contract: Mapping[str, Any],
    harness_amendment: Mapping[str, Any],
    artifact_receipts: Mapping[str, Any],
    preregistration: Mapping[str, Any] | None = None,
    exposure_amendment: Mapping[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run the full declared matrix; errors fail the run instead of truncating it."""

    arm_order = validate_interface(interface)
    if not cases:
        raise ValueError("Benchmark v2 suite is empty")
    eval_ids = [str(case.get("eval_id") or "") for case in cases]
    if not all(eval_ids) or len(eval_ids) != len(set(eval_ids)):
        raise ValueError("Benchmark v2 cases require unique non-empty eval_id values")
    if executor.result_class not in {
        "synthetic_contract_qa_not_system_performance",
        "observed_system_execution_nonclaim",
    }:
        raise ValueError(f"unsupported executor result_class: {executor.result_class}")
    if exposure_amendment is None or exposure_amendment.get("status") != "exposed_and_used_for_deterministic_behavior_tuning":
        raise ValueError("Benchmark v2 execution requires its exposure amendment and regression-only status")
    if harness_amendment.get("status") != "harness_compatibility_contract_added_before_model_execution":
        raise ValueError("Benchmark v2 execution requires its harness compatibility amendment")
    receipts = {str(key): str(value) for key, value in artifact_receipts.items()}
    expected_legacy_receipts = {
        "suite": suite_sha256,
        "causal_interface": interface_sha256,
        "contract": contract_sha256,
    }
    mismatches = sorted(
        key
        for key, value in expected_legacy_receipts.items()
        if receipts.get(key) != value
    )
    if mismatches:
        raise ValueError(f"legacy benchmark hashes disagree with artifact receipts: {mismatches}")
    if receipts.get("runner") != file_sha256(Path(__file__).resolve()):
        raise ValueError("runner artifact receipt does not match executing source")
    metric_source = PROJECT_ROOT / "src/agronomy_agent/benchmark_v2_metrics.py"
    if receipts.get("metrics") != file_sha256(metric_source):
        raise ValueError("metric artifact receipt does not match executing source")
    try:
        executor_capabilities = executor.harness_capabilities()
    except AttributeError as exc:
        raise ValueError("executor does not implement the harness capability handshake") from exc
    if not isinstance(executor_capabilities, Mapping):
        raise ValueError("executor capability handshake must return an object")
    expected_executor_identity = {
        "executor_id": executor.executor_id,
        "executor_version": executor.executor_version,
        "result_class": executor.result_class,
    }
    if any(
        executor_capabilities.get(key) != value
        for key, value in expected_executor_identity.items()
    ):
        raise ValueError("executor capability handshake identity does not match the active executor")
    negotiation = negotiate_harness(
        contract=harness_contract,
        interface_components=tuple(str(value) for value in interface["component_fields"]),
        capabilities=executor_capabilities,
        artifact_receipts=receipts,
    )
    if not negotiation["run_permitted"]:
        raise ValueError(
            "executor is incompatible with the frozen benchmark harness: "
            + ", ".join(negotiation["reason_codes"])
        )
    created_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    resolved_run_id = run_id or "oab2_run_" + stable_sha256(
        {
            "created_at": created_at,
            "suite_sha256": suite_sha256,
            "interface_sha256": interface_sha256,
            "model": model.to_dict(),
            "executor": [executor.executor_id, executor.executor_version],
            "cohort_fingerprint": negotiation["cohort_fingerprint"],
            "system_fingerprint": negotiation["system_fingerprint"],
        }
    )[:24]
    observations: list[dict[str, Any]] = []
    for arm_index, arm_id in enumerate(arm_order):
        arm = interface["arms"][arm_id]
        components = {key: bool(arm[key]) for key in interface["component_fields"]}
        for case_index, case in enumerate(cases):
            request = ArmExecutionRequest(
                run_id=resolved_run_id,
                case_index=case_index,
                arm_index=arm_index,
                case=case,
                arm_id=arm_id,
                components=components,
                component_contracts=harness_contract["component_contracts"],
                component_configuration_receipts=negotiation[
                    "component_configuration_receipts"
                ],
                model=model,
            )
            raw = executor.execute(request)
            observations.append(
                _complete_observation(
                    request,
                    raw,
                    executor=executor,
                    negotiation=negotiation,
                    harness_contract=harness_contract,
                )
            )
    expected_count = len(cases) * len(arm_order)
    if len(observations) != expected_count:
        raise RuntimeError(f"incomplete v2 matrix: expected {expected_count}, observed {len(observations)}")
    pairs = {(row["eval_id"], row["arm_id"]) for row in observations}
    if len(pairs) != expected_count:
        raise RuntimeError("duplicate or missing case-arm observations")

    cases_by_id = {str(case["eval_id"]): case for case in cases}
    measurements = [
        score_case_observation(cases_by_id[str(observation["eval_id"])], observation)
        for observation in observations
    ]
    summary = summarize_measurements(
        measurements,
        named_contrasts=tuple(interface.get("named_causal_contrasts") or ()),
    )
    preregistered_estimands = (
        []
        if preregistration is None
        else summarize_preregistered_estimands(
            measurements,
            preregistration=preregistration,
            named_contrasts=tuple(interface.get("named_causal_contrasts") or ()),
        )
    )
    run = {
        "schema_version": RUN_SCHEMA_VERSION,
        "runner_version": RUNNER_VERSION,
        "run_id": resolved_run_id,
        "created_at": created_at,
        "status": "complete",
        "claim_eligible": False,
        "holdout_status": "invalidated_for_evaluation_by_exact_case_tuning",
        "permitted_role": "exposed_internal_development_regression_and_harness_contract_qa",
        "fresh_untouched_successor_required": "v3",
        "exposure_amendment_id": exposure_amendment.get("amendment_id"),
        "harness_amendment_id": harness_amendment.get("amendment_id"),
        "result_class": executor.result_class,
        "benchmark_id": interface["benchmark_id"],
        "suite_sha256": suite_sha256,
        "interface_sha256": interface_sha256,
        "contract_sha256": contract_sha256,
        "harness_contract_sha256": receipts["harness_contract"],
        "preregistration_sha256": receipts["preregistration"],
        "exposure_amendment_sha256": receipts["exposure_amendment"],
        "harness_amendment_sha256": receipts["harness_amendment"],
        "metric_source_sha256": receipts["metrics"],
        "runner_source_sha256": receipts["runner"],
        "construct_fingerprint": negotiation["construct_fingerprint"],
        "cohort_fingerprint": negotiation["cohort_fingerprint"],
        "system_fingerprint": negotiation["system_fingerprint"],
        "harness_negotiation": negotiation,
        "model_identity": model.to_dict(),
        "executor_identity": {
            "executor_id": executor.executor_id,
            "executor_version": executor.executor_version,
            **dict(negotiation["system_identity"]),
        },
        "arm_order": list(arm_order),
        "case_order": eval_ids,
        "case_count": len(cases),
        "arm_count": len(arm_order),
        "expected_observation_count": expected_count,
        "completed_observation_count": len(observations),
        "early_stopping": False,
        "observations": observations,
        "measurements": measurements,
        "measurement_summary": summary,
        "preregistered_estimands": preregistered_estimands,
        "preregistered_estimand_status": "computed" if preregistration is not None else "not_supplied",
        "interpretation_boundary": (
            "This artifact is claim-ineligible. Synthetic executor output tests the harness only; "
            "v2 exact cases were used for tuning and cannot test post-tuning generalization. "
            "An evaluative outcome requires a fresh untouched v3, preferably independently authored and reviewed."
        ),
    }
    run["run_sha256"] = stable_sha256(run)
    return run


def write_run_bundle(run: Mapping[str, Any], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    observations_path = output_dir / "observations.jsonl"
    measurements_path = output_dir / "measurements.jsonl"
    summary_path = output_dir / "measurement_summary.json"
    run_path = output_dir / "run_receipt.json"
    observations_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in run["observations"]),
        encoding="utf-8",
    )
    measurements_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in run["measurements"]),
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps(run["measurement_summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    estimands_path = output_dir / "preregistered_estimands.json"
    estimands_path.write_text(json.dumps(run["preregistered_estimands"], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {key: value for key, value in run.items() if key not in {"observations", "measurements", "measurement_summary", "preregistered_estimands"}}
    receipt["artifacts"] = [
        {"path": path.name, "sha256": file_sha256(path), "bytes": path.stat().st_size}
        for path in (observations_path, measurements_path, summary_path, estimands_path)
    ]
    run_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**receipt, "run_receipt": str(run_path), "run_receipt_sha256": file_sha256(run_path)}


__all__ = [
    "ArmExecutionRequest",
    "ArmExecutor",
    "DeterministicContractExecutor",
    "ModelIdentity",
    "run_benchmark_v2",
    "validate_interface",
    "write_run_bundle",
]
