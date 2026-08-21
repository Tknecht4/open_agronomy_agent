from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from agronomy_agent.benchmark_v2_runner import (
    DeterministicContractExecutor,
    ModelIdentity,
    file_sha256,
    run_benchmark_v2,
    stable_sha256,
    write_run_bundle,
)
from agronomy_agent.benchmark_harness_compatibility import (
    REQUIRED_ARTIFACT_RECEIPTS,
    derive_system_configuration_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "data/eval/open_agronomy_benchmark_v2_cases.jsonl"
INTERFACE = ROOT / "configs/open_agronomy_benchmark_v2_interface.json"
CONTRACT = ROOT / "configs/open_agronomy_benchmark_v2.json"
PREREGISTRATION = ROOT / "configs/open_agronomy_benchmark_v2_preregistration.json"
EXPOSURE_AMENDMENT = ROOT / "data/eval/open_agronomy_benchmark_v2_exposure_amendment_20260813.json"
HARNESS_CONTRACT = ROOT / "configs/open_agronomy_benchmark_v2_harness_contract.json"
HARNESS_AMENDMENT = ROOT / "data/eval/open_agronomy_benchmark_v2_harness_amendment_20260813.json"

ARTIFACT_PATHS = {
    "suite": SUITE,
    "contract": CONTRACT,
    "case_schema": ROOT / "configs/schemas/benchmark_v2_case.schema.json",
    "causal_interface": INTERFACE,
    "preregistration": PREREGISTRATION,
    "exposure_amendment": EXPOSURE_AMENDMENT,
    "metrics": ROOT / "src/agronomy_agent/benchmark_v2_metrics.py",
    "runner": ROOT / "src/agronomy_agent/benchmark_v2_runner.py",
    "runner_cli": ROOT / "scripts/run_open_agronomy_benchmark_v2.py",
    "audit": ROOT / "scripts/audit_open_agronomy_benchmark_v2.py",
    "test_metrics": ROOT / "tests/test_benchmark_v2_metrics.py",
    "test_design_audit": ROOT / "tests/test_open_agronomy_benchmark_v2_audit.py",
    "test_tool_contract": ROOT / "tests/test_open_agronomy_benchmark_v2_tool_contract.py",
    "test_runner": ROOT / "tests/test_open_agronomy_benchmark_v2_runner.py",
    "test_runtime_contract": ROOT / "tests/test_open_agronomy_benchmark_v2_runtime_contract.py",
    "harness_contract": HARNESS_CONTRACT,
    "harness_amendment": HARNESS_AMENDMENT,
    "harness_compatibility": ROOT / "src/agronomy_agent/benchmark_harness_compatibility.py",
    "test_harness_compatibility": ROOT / "tests/test_benchmark_harness_compatibility.py",
}


def _rows() -> list[dict]:
    return [json.loads(line) for line in SUITE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _interface() -> dict:
    return json.loads(INTERFACE.read_text(encoding="utf-8"))


def _model() -> ModelIdentity:
    return ModelIdentity("deterministic-contract-qa", "v1", "no_model_inference", file_sha256(CONTRACT))


def _run(executor=None) -> dict:  # noqa: ANN001
    return run_benchmark_v2(
        cases=_rows(),
        interface=_interface(),
        model=_model(),
        executor=executor or DeterministicContractExecutor(),
        suite_sha256=file_sha256(SUITE),
        interface_sha256=file_sha256(INTERFACE),
        contract_sha256=file_sha256(CONTRACT),
        harness_contract=json.loads(HARNESS_CONTRACT.read_text(encoding="utf-8")),
        harness_amendment=json.loads(HARNESS_AMENDMENT.read_text(encoding="utf-8")),
        artifact_receipts={
            role: file_sha256(ARTIFACT_PATHS[role])
            for role in REQUIRED_ARTIFACT_RECEIPTS
        },
        preregistration=json.loads(PREREGISTRATION.read_text(encoding="utf-8")),
        exposure_amendment=json.loads(EXPOSURE_AMENDMENT.read_text(encoding="utf-8")),
        run_id="test_run_v2",
    )


def test_deterministic_runner_executes_every_declared_case_arm_without_early_stopping() -> None:
    run = _run()
    interface = _interface()
    rows = _rows()

    assert run["status"] == "complete"
    assert run["claim_eligible"] is False
    assert run["holdout_status"] == "invalidated_for_evaluation_by_exact_case_tuning"
    assert run["fresh_untouched_successor_required"] == "v3"
    assert run["result_class"] == "synthetic_contract_qa_not_system_performance"
    assert run["harness_negotiation"]["status"] == "comparable"
    assert run["construct_fingerprint"]
    assert run["cohort_fingerprint"]
    assert run["system_fingerprint"]
    assert run["early_stopping"] is False
    assert run["arm_order"] == interface["arm_order"]
    assert run["case_order"] == [row["eval_id"] for row in rows]
    assert run["expected_observation_count"] == 30 * 9
    assert run["completed_observation_count"] == 270
    assert len(run["observations"]) == 270
    assert len(run["measurements"]) == 270
    assert run["preregistered_estimand_status"] == "computed"
    assert len(run["preregistered_estimands"]) == 5
    assert len({(row["eval_id"], row["arm_id"]) for row in run["observations"]}) == 270


def test_observations_preserve_exact_component_model_stage_tool_and_evidence_identity() -> None:
    run = _run()
    interface = _interface()
    observation = next(
        row
        for row in run["observations"]
        if row["eval_id"] == "oab2::spring_wheat_stand::fully_specified_calculation"
        and row["arm_id"] == "production_full"
    )

    assert observation["components"] == {
        key: interface["arms"]["production_full"][key]
        for key in interface["component_fields"]
    }
    assert observation["model"] == _model().to_dict()
    assert observation["executor_id"] == "deterministic_contract_executor"
    assert observation["tool_invocations"][0]["invocation_id"] == observation["tool_results"][0]["invocation_id"]
    assert observation["tool_results"][0]["result_id"].startswith("tool_result_")
    assert observation["answer_stages"]["draft"]["sha256"] == observation["answer_stages"]["final"]["sha256"]
    assert observation["evidence_trace"]["retrieval_status"] == "synthetic_not_executed"
    assert set(observation["component_receipts"]) == set(interface["component_fields"])
    assert observation["component_receipts"]["retrieval"]["execution_status"] == "synthetic_contract_qa"
    assert observation["component_receipts"]["retrieval"]["configuration_sha256"] == (
        run["harness_negotiation"]["component_configuration_receipts"]["retrieval"]
    )
    assert {
        "runtime_orchestrator",
        "kernel_config",
        "field_context_contract",
        "retrieval_config_and_assets",
        "tool_executor_bundle",
        "fallback_policy",
    } <= set(observation["implementation_receipts"])
    assert observation["verifier_trace"]["enabled_by_arm"] is True
    assert observation["pre_generation_intervention"]["state"] == observation[
        "answerability_state"
    ]
    assert observation["component_receipts"]["risk_intervention"][
        "artifact_ids"
    ] == [observation["pre_generation_intervention"]["artifact_id"]]
    assert observation["answer_origin"] == "deterministic_tool_result"
    assert observation["observation_sha256"]
    measurement = next(
        row
        for row in run["measurements"]
        if row["eval_id"] == observation["eval_id"]
        and row["arm_id"] == observation["arm_id"]
    )
    assert measurement["executor_id"] == observation["executor_id"]
    assert measurement["executor_version"] == observation["executor_version"]
    assert measurement["feature_contract_versions"] == observation[
        "feature_contract_versions"
    ]
    assert measurement["component_configuration_receipts"] == observation[
        "component_configuration_receipts"
    ]


def test_pre_generation_hold_is_distinct_from_verifier_opportunity() -> None:
    run = _run()
    observation = next(
        row
        for row in run["observations"]
        if row["eval_id"] == "oab2::sprayer_calibration::high_consequence_authority"
        and row["arm_id"] == "production_full"
    )
    measurement = next(
        row
        for row in run["measurements"]
        if row["eval_id"] == observation["eval_id"] and row["arm_id"] == observation["arm_id"]
    )

    assert observation["pre_generation_intervened"] is True
    assert observation["answerability_state"] == "require_authority"
    assert observation["direct_answer"] is False
    assert observation["abstained"] is False
    assert observation["clarifying_questions"] == []
    assert observation["action_commitment_made"] is False
    assert observation["verifier_had_opportunity"] is False
    assert observation["verifier_intervened"] is None
    assert measurement["values"]["verifier_false_negative"] is None
    assert measurement["values"]["risk_calibration"] == 1.0


def test_summary_never_pools_models_revisions_or_arms() -> None:
    summary = _run()["measurement_summary"]

    assert summary["cross_system_overall"] is None
    assert summary["cross_system_pooling_policy"] == "prohibited"
    assert len(summary["systems"]) == 9
    assert {item["arm_id"] for item in summary["systems"]} == set(_interface()["arm_order"])
    assert all(item["model_id"] == "deterministic-contract-qa" for item in summary["systems"])
    assert all(item["model_revision"] == "v1" for item in summary["systems"])
    assert summary["paired_contrast_status"] == "computed"
    assert len(summary["paired_contrasts"]) == len(_interface()["named_causal_contrasts"])
    assert all(item["status"] == "complete" for item in summary["paired_contrasts"])
    assert all(item["available_case_pairs"] == 30 for item in summary["paired_contrasts"])
    estimands = _run()["preregistered_estimands"]
    by_id = {item["estimand_id"]: item for item in estimands}
    assert by_id["unnecessary_abstention_delta"]["eligible_cases"] == 18
    assert by_id["missing_input_clarification_gain"]["eligible_cases"] == 6
    assert by_id["authority_calibration_gain"]["eligible_cases"] == 6
    assert by_id["verifier_utility_delta"]["eligible_cases"] == 30
    assert by_id["calculator_selection_gain"]["status"] == "not_computable"
    assert by_id["verifier_utility_delta"]["status"] == "not_computable"


def test_write_bundle_is_content_addressed_and_claim_ineligible(tmp_path: Path) -> None:
    run = _run()
    receipt = write_run_bundle(run, tmp_path / "run")

    assert receipt["claim_eligible"] is False
    assert receipt["completed_observation_count"] == 270
    assert {item["path"] for item in receipt["artifacts"]} == {
        "observations.jsonl",
        "measurements.jsonl",
        "measurement_summary.json",
        "preregistered_estimands.json",
    }
    assert all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in receipt["artifacts"])
    persisted = json.loads(Path(receipt["run_receipt"]).read_text(encoding="utf-8"))
    assert persisted["claim_eligible"] is False
    assert "observations" not in persisted


class _BadClaimExecutor(DeterministicContractExecutor):
    result_class = "claim_eligible_performance"


def test_runner_refuses_claim_eligible_or_unknown_result_class() -> None:
    with pytest.raises(ValueError, match="unsupported executor result_class"):
        _run(_BadClaimExecutor())


class _MismatchedHandshakeExecutor(DeterministicContractExecutor):
    def harness_capabilities(self):  # noqa: ANN201
        capabilities = dict(super().harness_capabilities())
        capabilities["executor_id"] = "different_hidden_executor"
        return capabilities


def test_runner_binds_capability_handshake_to_active_executor_identity() -> None:
    with pytest.raises(ValueError, match="handshake identity"):
        _run(_MismatchedHandshakeExecutor())


def test_runner_refuses_to_execute_without_exposure_amendment() -> None:
    with pytest.raises(ValueError, match="exposure amendment"):
        run_benchmark_v2(
            cases=_rows(),
            interface=_interface(),
            model=_model(),
            executor=DeterministicContractExecutor(),
            suite_sha256=file_sha256(SUITE),
            interface_sha256=file_sha256(INTERFACE),
            contract_sha256=file_sha256(CONTRACT),
            harness_contract=json.loads(HARNESS_CONTRACT.read_text(encoding="utf-8")),
            harness_amendment=json.loads(HARNESS_AMENDMENT.read_text(encoding="utf-8")),
            artifact_receipts={
                role: file_sha256(ARTIFACT_PATHS[role])
                for role in REQUIRED_ARTIFACT_RECEIPTS
            },
            preregistration=json.loads(PREREGISTRATION.read_text(encoding="utf-8")),
            exposure_amendment=None,
            run_id="missing_exposure_receipt",
        )


class _IncompleteExecutor(DeterministicContractExecutor):
    def execute(self, request):  # noqa: ANN001, ANN201
        row = dict(super().execute(request))
        row.pop("answer_stages")
        return row


def test_runner_fails_closed_on_incomplete_trace_instead_of_skipping_case() -> None:
    with pytest.raises(ValueError, match="answer_stages"):
        _run(_IncompleteExecutor())


class _UnavailableExecutor(DeterministicContractExecutor):
    def execute(self, request):  # noqa: ANN001, ANN201
        row = dict(super().execute(request))
        row["status"] = "unavailable"
        return row


def test_runner_fails_full_matrix_on_unavailable_observation() -> None:
    with pytest.raises(ValueError, match="not completed"):
        _run(_UnavailableExecutor())


class _MissingComponentReceiptExecutor(DeterministicContractExecutor):
    def execute(self, request):  # noqa: ANN001, ANN201
        row = dict(super().execute(request))
        row["component_receipts"] = dict(row["component_receipts"])
        row["component_receipts"].pop("retrieval")
        return row


def test_runner_fails_closed_when_component_execution_is_not_receipted() -> None:
    with pytest.raises(ValueError, match="one receipt"):
        _run(_MissingComponentReceiptExecutor())


class _UndeclaredStageExecutor(DeterministicContractExecutor):
    executor_version = "v2-with-hidden-stage"

    def execute(self, request):  # noqa: ANN001, ANN201
        row = dict(super().execute(request))
        row["new_active_planning_stage"] = {"status": "completed"}
        return row


def test_runner_rejects_undeclared_active_stage_instead_of_dropping_it() -> None:
    with pytest.raises(ValueError, match="undeclared observation fields"):
        _run(_UndeclaredStageExecutor())


class _ObservedAvailableNotUsedExecutor(DeterministicContractExecutor):
    result_class = "observed_system_execution_nonclaim"

    def execute(self, request):  # noqa: ANN001, ANN201
        row = dict(super().execute(request))
        row["component_receipts"] = {
            component: {
                **receipt,
                "execution_status": "available_not_used" if receipt["enabled_by_arm"] else "disabled_by_arm",
            }
            for component, receipt in row["component_receipts"].items()
        }
        return row


def test_observed_executor_cannot_mark_answer_affecting_components_available_not_used() -> None:
    with pytest.raises(ValueError, match="kernel_prompt:available_not_used"):
        _run(_ObservedAvailableNotUsedExecutor())


class _TraceMutationExecutor(DeterministicContractExecutor):
    def __init__(self, mutation: str):
        self.mutation = mutation

    def harness_capabilities(self):  # noqa: ANN201
        capabilities = json.loads(json.dumps(super().harness_capabilities()))
        if self.mutation == "tool_stale_invocation_id":
            capabilities["semantic_profile"]["tool_implementations"][
                "alternate_calculator"
            ] = {
                "implementation_version": "alternate_calculator_v1",
                "family": "supplied_input_arithmetic",
                "operations": ["seed_rate_mass"],
                "authority_roles": ["supplied_inputs_arithmetic_only"],
            }
            capabilities["system_identity"][
                "system_configuration_sha256"
            ] = derive_system_configuration_sha256(capabilities)
        return capabilities

    def execute(self, request):  # noqa: ANN001, ANN201
        row = json.loads(json.dumps(super().execute(request)))
        if self.mutation == "evidence_schema":
            row["evidence_trace"]["schema_version"] = "unexpected.evidence.v2"
        elif self.mutation == "evidence_extra_field":
            row["evidence_trace"]["hidden_retrieval"] = True
        elif self.mutation == "retrieval_disabled_contamination" and not request.components[
            "retrieval"
        ]:
            row["evidence_trace"]["retrieved_document_ids"] = ["hidden_document"]
        elif (
            self.mutation == "verifier_missing_artifact"
            and request.components["verifier"]
            and row["verifier_had_opportunity"]
        ):
            row["verifier_trace"]["artifact_id"] = None
            row["component_receipts"]["verifier"]["artifact_ids"] = []
        elif (
            self.mutation == "verifier_missing_adjudication"
            and request.components["verifier"]
            and row["verifier_had_opportunity"]
        ):
            row["draft_verifier_intervention_required"] = None
            row["verifier_trace"]["draft_intervention_required"] = None
        elif (
            self.mutation == "verifier_required_miss_stale_artifact"
            and request.components["verifier"]
            and row["verifier_had_opportunity"]
        ):
            row["draft_verifier_intervention_required"] = True
            row["verifier_trace"]["draft_intervention_required"] = True
            row["verifier_trace"]["decision_outcome"] = (
                "miss_required_intervention"
            )
        elif (
            self.mutation == "verifier_source_stale_artifact"
            and request.components["verifier"]
            and row["verifier_had_opportunity"]
        ):
            row["verifier_trace"]["adjudication_source"] = (
                "mutated_adjudication_source"
            )
        elif (
            self.mutation == "verifier_artifact_component_link"
            and request.components["verifier"]
            and row["verifier_had_opportunity"]
        ):
            row["component_receipts"]["verifier"]["artifact_ids"] = [
                "verifier_adjudication_unlinked"
            ]
        elif self.mutation == "tool_payload_hash" and row["tool_results"]:
            row["tool_results"][0]["payload"]["value"] = -999
        elif self.mutation == "tool_result_schema" and row["tool_results"]:
            row["tool_results"][0]["schema_version"] = "unexpected.tool_result.v2"
        elif self.mutation == "tool_result_link" and row["tool_results"]:
            row["tool_results"][0]["invocation_id"] = "unknown_invocation"
        elif self.mutation == "tool_artifact_ids" and row["tool_invocations"]:
            row["component_receipts"]["typed_tools"]["artifact_ids"] = []
        elif self.mutation == "tool_stale_invocation_id" and row["tool_results"]:
            row["selected_tools"] = ["alternate_calculator"]
            for invocation in (
                row["tool_invocations"][0],
                row["tool_plan"]["invocations"][0],
            ):
                invocation["tool_id"] = "alternate_calculator"
                invocation["tool_version"] = "alternate_calculator_v1"
            row["tool_results"][0]["tool_id"] = "alternate_calculator"
            row["tool_results"][0]["tool_version"] = "alternate_calculator_v1"
        elif self.mutation == "tool_stale_result_id" and row["tool_results"]:
            row["tool_results"][0]["payload"]["tampered_receipted_value"] = True
            row["tool_results"][0]["payload_sha256"] = stable_sha256(
                row["tool_results"][0]["payload"]
            )
        elif (
            self.mutation == "tool_plan_not_applicable_content"
            and row["tool_plan"]
            and row["tool_plan"]["status"] == "not_applicable"
        ):
            row["tool_plan"]["clarification"] = "Hidden planner output."
        elif (
            self.mutation == "tool_plan_clarification_text"
            and row["tool_plan"]
            and row["tool_plan"]["status"] == "clarification_required"
        ):
            row["tool_plan"]["clarification"] = "Provide something else."
            row["clarifying_questions"] = ["Provide something else."]
        elif (
            self.mutation == "tool_plan_clarification_missing_inputs"
            and row["tool_plan"]
            and row["tool_plan"]["status"] == "clarification_required"
        ):
            row["tool_invocations"][0]["missing_inputs"] = []
            row["tool_plan"]["invocations"][0]["missing_inputs"] = []
        elif (
            self.mutation == "tool_plan_clarification_result"
            and row["tool_results"]
            and row["tool_plan"]["status"] == "ready"
        ):
            row["tool_plan"]["status"] = "clarification_required"
            row["tool_plan"]["clarification"] = "To calculate this, provide test input."
            row["clarifying_questions"] = [row["tool_plan"]["clarification"]]
            row["clarification_fields"] = ["test_input"]
            for invocation in (
                row["tool_invocations"][0],
                row["tool_plan"]["invocations"][0],
            ):
                invocation["status"] = "clarification_required"
                invocation["missing_inputs"] = ["test input"]
        elif (
            self.mutation == "tool_plan_ready_missing_result"
            and row["tool_results"]
            and row["tool_plan"]["status"] == "ready"
        ):
            removed_result_id = row["tool_results"][0]["result_id"]
            row["tool_results"] = []
            row["component_receipts"]["typed_tools"]["artifact_ids"].remove(
                removed_result_id
            )
        elif (
            self.mutation == "tool_plan_ready_empty"
            and row["tool_results"]
            and row["tool_plan"]["status"] == "ready"
        ):
            row["tool_plan"]["invocations"] = []
            row["tool_invocations"] = []
            row["tool_results"] = []
            row["selected_tools"] = []
            row["component_receipts"]["typed_tools"]["artifact_ids"] = []
        elif self.mutation == "tool_operation_semantic" and row["tool_invocations"]:
            row["tool_invocations"][0]["operation"] = "unknown_operation"
            row["tool_plan"]["invocations"][0]["operation"] = "unknown_operation"
            if row["tool_results"]:
                row["tool_results"][0]["operation"] = "unknown_operation"
        elif self.mutation == "tool_authority_semantic" and row["tool_invocations"]:
            row["tool_invocations"][0]["authority_role"] = "unknown_authority"
            row["tool_plan"]["invocations"][0]["authority_role"] = "unknown_authority"
            if row["tool_results"]:
                row["tool_results"][0]["authority_role"] = "unknown_authority"
        elif (
            self.mutation == "evidence_authority_semantic"
            and request.components["retrieval"]
        ):
            row["evidence_trace"]["retrieved_document_ids"] = ["evidence_bad"]
            row["evidence_trace"]["evidence_items"] = [
                {
                    "evidence_id": "evidence_bad",
                    "implementation_id": "governed_document_retrieval",
                    "modality": "document",
                    "evidence_role": "supporting",
                    "factual_authority": "unknown_authority",
                    "field_action_authority": "not_authorized",
                }
            ]
        elif self.mutation == "verifier_decision_unit":
            row["verifier_trace"]["decision_unit"] = "unknown_decision_unit"
        elif self.mutation == "verifier_outcome_semantic":
            row["verifier_trace"]["decision_outcome"] = "unknown_outcome"
        elif (
            self.mutation == "answerability_unknown_semantic"
            and request.components["risk_intervention"]
        ):
            row["answerability_state"] = "unknown_answerability_state"
            row["pre_generation_intervention"]["state"] = (
                "unknown_answerability_state"
            )
        elif (
            self.mutation == "require_authority_without_hold"
            and request.components["risk_intervention"]
            and not request.components["verifier"]
            and row["answerability_state"] == "require_authority"
        ):
            row["pre_generation_intervened"] = False
        elif (
            self.mutation == "answer_directly_with_hold"
            and request.components["risk_intervention"]
            and not request.components["verifier"]
            and row["answerability_state"] == "answer_directly"
        ):
            row["pre_generation_intervened"] = True
        elif (
            self.mutation == "policy_receipt_state"
            and request.components["risk_intervention"]
        ):
            row["pre_generation_intervention"]["state"] = "require_authority"
        elif (
            self.mutation == "policy_receipt_extra_field"
            and request.components["risk_intervention"]
        ):
            row["pre_generation_intervention"]["hidden_policy_output"] = True
        elif (
            self.mutation == "policy_receipt_empty_reason"
            and request.components["risk_intervention"]
        ):
            row["pre_generation_intervention"]["reason"] = ""
        elif (
            self.mutation == "policy_receipt_stale_artifact"
            and request.components["risk_intervention"]
        ):
            row["pre_generation_intervention"]["reason"] += " tampered"
        elif (
            self.mutation == "policy_receipt_artifact_link"
            and request.components["risk_intervention"]
        ):
            row["component_receipts"]["risk_intervention"]["artifact_ids"] = []
        elif self.mutation == "component_configuration":
            row["component_receipts"]["kernel_prompt"]["configuration_sha256"] = "0" * 64
        elif self.mutation == "risk_disabled_contamination" and not request.components[
            "risk_intervention"
        ]:
            row["answerability_state"] = "answer_directly"
        elif self.mutation == "fallback_disabled_contamination" and not request.components[
            "fallback"
        ]:
            row["answer_stages"]["final"]["text"] += " hidden fallback"
            row["answer_stages"]["final"]["sha256"] = hashlib.sha256(
                row["answer_stages"]["final"]["text"].encode("utf-8")
            ).hexdigest()
        return row


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("evidence_schema", "evidence trace schema version mismatch"),
        ("evidence_extra_field", "evidence trace fields"),
        ("retrieval_disabled_contamination", "retrieval-disabled arm contains evidence contamination"),
        ("verifier_missing_artifact", "completed verifier requires an adjudication artifact ID"),
        ("verifier_missing_adjudication", "completed verifier requires explicit draft adjudication"),
        (
            "verifier_required_miss_stale_artifact",
            "verifier artifact ID is not content-addressed to its adjudication",
        ),
        (
            "verifier_source_stale_artifact",
            "verifier artifact ID is not content-addressed to its adjudication",
        ),
        (
            "verifier_artifact_component_link",
            "verifier artifact ID does not match its adjudication trace",
        ),
        ("tool_payload_hash", "tool result payload hash mismatch"),
        ("tool_result_schema", "tool result schema version mismatch"),
        ("tool_result_link", "unknown invocation"),
        ("tool_artifact_ids", "typed_tools artifact IDs"),
        (
            "tool_stale_invocation_id",
            "tool invocation ID does not match canonical invocation content",
        ),
        (
            "tool_stale_result_id",
            "tool result ID does not match canonical result content",
        ),
        ("tool_plan_not_applicable_content", "not_applicable tool plan must be empty"),
        (
            "tool_plan_clarification_text",
            "clarification_required tool plan lacks linked missing inputs",
        ),
        (
            "tool_plan_clarification_missing_inputs",
            "clarification_required tool plan lacks linked missing inputs",
        ),
        (
            "tool_plan_clarification_result",
            "clarification_required tool plan requires invocations and no results",
        ),
        (
            "tool_plan_ready_missing_result",
            "ready tool plan lacks the result required by the benchmark case",
        ),
        ("tool_plan_ready_empty", "ready tool plan lacks executable invocations"),
        (
            "tool_operation_semantic",
            "unknown operation/authority/status semantic",
        ),
        (
            "tool_authority_semantic",
            "unknown operation/authority/status semantic",
        ),
        (
            "evidence_authority_semantic",
            "evidence item uses an unknown authority semantic class",
        ),
        (
            "verifier_decision_unit",
            "verifier trace semantic identity mismatch: decision_unit",
        ),
        (
            "verifier_outcome_semantic",
            "verifier trace uses an unknown decision outcome semantic",
        ),
        (
            "answerability_unknown_semantic",
            "answerability_state uses an unknown semantic class",
        ),
        (
            "require_authority_without_hold",
            "answerability state does not match pre-generation hold state",
        ),
        (
            "answer_directly_with_hold",
            "answerability state does not match pre-generation hold state",
        ),
        ("policy_receipt_state", "answerability policy receipt state mismatch"),
        ("policy_receipt_extra_field", "answerability policy receipt fields"),
        (
            "policy_receipt_empty_reason",
            "answerability policy receipt requires non-empty text: reason",
        ),
        (
            "policy_receipt_stale_artifact",
            "answerability policy receipt artifact ID is not content-addressed",
        ),
        (
            "policy_receipt_artifact_link",
            "risk_intervention artifact ID does not match its policy receipt",
        ),
        ("component_configuration", "component identity/version/configuration mismatch"),
        ("risk_disabled_contamination", "risk_intervention-disabled arm contains policy contamination"),
        ("fallback_disabled_contamination", "fallback-disabled arm contains fallback contamination"),
    ],
)
def test_runner_rejects_component_trace_and_enablement_contamination(
    mutation: str,
    expected: str,
) -> None:
    with pytest.raises(ValueError, match=expected):
        _run(_TraceMutationExecutor(mutation))


def test_v2_cli_bootstraps_repository_imports_outside_repo_cwd(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_open_agronomy_benchmark_v2.py"),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "deterministic-contract-qa" in result.stdout
