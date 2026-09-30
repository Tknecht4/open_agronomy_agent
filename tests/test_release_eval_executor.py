from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agronomy_agent.execution_core import EXECUTION_STAGE_IDS, stable_sha256
from agronomy_agent.release_eval_executor import (
    compile_case_field_context,
    execute_product_case,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    json.loads(line)
    for line in (ROOT / "data/eval/release_harness_v1.jsonl").read_text().splitlines()
]


def case(**updates):
    return {
        "case_id": "synthetic-probe",
        "scenario_family": "numeric_complete",
        "lane": "harness",
        "question": "Convert 100 lb/ac to kg/ha.",
        "field_context": {},
        "assertions": {},
        "review_required": False,
        **updates,
    }


def run(tmp_path, row=None, **kwargs):
    return execute_product_case(
        row or case(),
        model_config=ROOT / "configs/model.yaml",
        rag_config=ROOT / "configs/rag.yaml",
        output_dir=tmp_path,
        **kwargs,
    )


@pytest.mark.parametrize("row", CASES, ids=lambda row: row["case_id"])
def test_synthetic_scenarios_have_observed_product_receipts(tmp_path, row):
    result = run(tmp_path, row)
    assert result["status"] == "completed", result.get("error")
    assert result["failed_checks"] == []
    assert result["model_execution_eligible"] is False
    assert result["claim_eligible"] is False
    for turn in result["turns"]:
        assert [receipt["stage_id"] for receipt in turn["stage_receipts"]] == list(
            EXECUTION_STAGE_IDS
        )
        assert turn["profiler_spans"]
        assert turn["peak_memory_bytes"] is None
        assert turn["persisted_turn"]["answer"] == turn["answer"]
    if row["review_required"]:
        assert "semantic_review" in {item["id"] for item in result["unknown"]}


def test_numeric_binding_retains_exact_result_and_never_calls_mock(tmp_path):
    row = case(
        scoring={"reference_numeric": 9999, "reference_unit": "wrong", "tolerance": 0}
    )
    result = run(tmp_path, row)
    turn = result["turns"][0]
    tool_result = turn["tool_results"][0]
    assert tool_result["payload"]["value"] == pytest.approx(112.0851156)
    assert tool_result["payload_sha256"] == stable_sha256(tool_result["payload"])
    assert turn["draft"] == tool_result["payload"]["answer"]
    assert result["backend_calls"] == []
    assert {
        "turn_1.tool_results_bound",
        "turn_1.tool_payloads_bound",
        "turn_1.tool_answer_used",
    }.issubset({row["id"] for row in result["checks"] if row["passed"]})
    assert "9999" not in json.dumps(turn["prompt_messages"])
    assert any(row["id"] == "answer_scoring" for row in result["unknown"])


def test_multiturn_reference_uses_persisted_user_history_and_scope(tmp_path):
    row = case()
    row.pop("question")
    row.update(
        turns=[
            {"content": "Convert 100 lb/ac to kg/ha."},
            "What about 200 instead?",
            "300 instead?",
        ]
    )
    result = run(tmp_path, row)
    assert result["failed_checks"] == []
    first, second, third = result["turns"]
    assert (
        second["metadata"]["conversation_resolution"]["source_turn_id"]
        == first["turn_id"]
    )
    assert (
        third["metadata"]["conversation_resolution"]["source_turn_id"]
        == second["turn_id"]
    )
    assert third["metadata"]["conversation_resolution"]["chain_depth"] == 2
    assert third["tool_results"][0]["payload"]["inputs"]["value"] == 300
    fresh = run(tmp_path / "fresh", case(question="What about 200 instead?"))
    assert fresh["session_id"] != result["session_id"]
    assert (
        fresh["turns"][0]["metadata"]["conversation_resolution"]["status"]
        == "no_antecedent"
    )


def test_field_aliases_reach_compiler_and_conflicts_fail_without_erasure(tmp_path):
    compiled, receipt = compile_case_field_context(
        {"crop_name": "canola", "crop": "wheat", "region_text": "Alberta"}
    )
    assert compiled["crop"] == "wheat"
    assert compiled["crop_name"] == "canola"
    assert compiled["region"] == "Alberta"
    assert receipt["conflicts"][0]["canonical"] == "crop"
    result = run(
        tmp_path,
        case(
            question="What observations should I collect?",
            field_context={"crop_name": "canola", "crop": "wheat"},
        ),
    )
    assert result["status"] == "completed"
    assert result["failed_checks"][0]["id"] == "field_aliases_unambiguous"
    assert (
        result["turns"][0]["metadata"]["field_context_compiler"]["field"]["crop"]
        == "wheat"
    )


@pytest.mark.parametrize(
    ("arm", "stages"),
    [
        ("retrieval_neither", ["document_retrieval", "graph_retrieval"]),
        ("full_minus_typed_tools", ["tool_planning", "tool_execution"]),
        ("full_minus_field_context", ["typed_field_context"]),
        ("full_minus_verifier", ["verification"]),
    ],
)
def test_direct_product_controls_preserve_disabled_stage_receipts(
    tmp_path, arm, stages
):
    result = run(tmp_path, arm_id=arm)
    assert result["status"] == "completed"
    assert result["failed_checks"] == []
    receipts = {row["stage_id"]: row for row in result["turns"][0]["stage_receipts"]}
    assert all(receipts[stage]["state"] == "disabled_by_arm" for stage in stages)


@pytest.mark.parametrize("arm", ["raw_model", "kernel_only"])
def test_reference_arms_use_generator_and_never_fabricate_topology(tmp_path, arm):
    result = run(tmp_path, case(question="Explain soil texture."), arm_id=arm)
    assert result["status"] == "completed"
    turn = result["turns"][0]
    assert result["backend_calls"][0]["status"] == "completed"
    assert turn["stage_receipts"] == []
    assert turn["execution_kind"] == "ungoverned_reference"
    assert turn["reference_receipt"]["topology_receipts_present"] is False
    assert [message["role"] for message in turn["prompt_messages"]] == (
        ["system", "user"] if arm == "kernel_only" else ["user"]
    )
    assert turn["persisted_turn"]["answer"] == turn["answer"]
    assert result["model_execution_eligible"] is False


def test_unrecovered_mock_fault_remains_failed_without_complete_topology(tmp_path):
    row = case(
        scenario_family="backend_faults",
        question="Explain crop rotation.",
        synthetic_fault={"kind": "backend_unavailable", "fail_calls": 1},
    )
    result = run(tmp_path, row, arm_id="full_minus_fallback")
    assert result["status"] == "failed"
    turn = result["turns"][0]
    assert turn["status"] == "failed"
    assert turn["error"]["type"] == "SyntheticBackendUnavailable"
    assert turn["answer"] is None
    assert turn["stage_receipts"] == []
    assert turn["persistence_observation"]["session_turn_count"] == 0
    assert any(span["status"] == "error" for span in turn["profiler_spans"])
    assert result["failed_checks"]
    assert (
        json.loads((Path(result["artifact_dir"]) / "result.json").read_text())["status"]
        == "failed"
    )


def test_recovered_mock_fault_has_truthful_fallback_origin_and_calls(tmp_path):
    row = deepcopy(next(row for row in CASES if row["case_id"] == "HR1-fault-recovery"))
    result = run(tmp_path, row)
    first, second = result["turns"]
    first_receipts = {row["stage_id"]: row for row in first["stage_receipts"]}
    assert first_receipts["draft_generation"]["state"] != "completed"
    assert (
        first_receipts["fallback_origin"]["evidence"]["origin_class"]
        == "analysis_unavailable_fallback"
    )
    assert first["generation_stats"] is None
    assert second["generation_stats"]["synthetic"] is True
    assert [row["status"] for row in result["backend_calls"]] == ["failed", "completed"]
    assert result["model_execution_eligible"] is False


def test_fault_injection_rejects_real_model_and_nonfault_case_before_execution(
    tmp_path,
):
    row = case(synthetic_fault={"kind": "backend_unavailable", "fail_calls": 1})
    for backend in ("mock", "mlx"):
        result = run(tmp_path / backend, row, backend=backend)
        assert result["status"] == "failed"
        assert "synthetic_fault requires" in result["error"]["message"]
        assert result["turns"] == []


def test_unknown_mechanical_assertion_fails_and_semantic_review_stays_unknown(tmp_path):
    result = run(
        tmp_path,
        case(
            assertions={
                "unimplemented_mechanical_contract": True,
                "semantic_assertions": ["valid agronomic recommendation"],
            },
            review_required=True,
        ),
    )
    assert result["status"] == "completed"
    assert [row["id"] for row in result["failed_checks"]] == [
        "unimplemented_mechanical_contract"
    ]
    assert {
        "unimplemented_mechanical_contract",
        "semantic_assertions",
        "semantic_review",
    }.issubset({row["id"] for row in result["unknown"]})


def test_existing_cell_is_immutable_and_invalid_cases_retained(tmp_path):
    original = run(tmp_path)
    path = Path(original["artifact_dir"]) / "result.json"
    before = path.read_bytes()
    repeated = run(tmp_path)
    assert repeated["status"] == "failed"
    assert repeated["error"]["type"] == "FileExistsError"
    assert path.read_bytes() == before
    invalid = run(tmp_path / "invalid", case(question=""))
    assert invalid["status"] == "failed"
    assert invalid["turns"] == []
    assert invalid["failed_checks"]


@pytest.mark.parametrize(
    ("transport", "resolved", "eligible"),
    [
        ("mlx", "revision-123", True),
        ("mlx", "wrong-revision", False),
        ("http", "revision-123", True),
        ("http", "wrong-revision", False),
    ],
)
def test_real_backend_eligibility_requires_verified_loaded_revision(
    tmp_path, monkeypatch, transport, resolved, eligible
):
    """Fake only the model boundary; still execute the production pipeline."""
    import agronomy_agent.release_eval_executor as executor

    config = yaml.safe_load((ROOT / "configs/model.yaml").read_text())
    config["model_revision"] = "revision-123"
    config["answer_verification"]["enabled"] = False
    config_path = tmp_path / "effective-model.yaml"
    config_path.write_text(yaml.safe_dump(config))

    class FixtureGenerator:
        backend_id = "identity_contract_fixture"
        model_id = config["model_id"]
        last_generation_stats = None
        model_identity = {
            "status": (
                "verified_direct_loader"
                if transport == "mlx"
                else "verified_runtime_receipt"
            ),
            "configured_model_id": config["model_id"],
            "configured_model_revision": "revision-123",
            "runtime": {"model_revision": resolved} if transport == "http" else {},
        }

        def generate(self, messages):
            self.last_generation_stats = {
                "backend": "identity_contract_fixture",
                "generation_tokens": 10,
                "prompt_tokens": 30,
            }
            return (
                "Soil texture describes relative proportions of sand, silt, and clay."
            )

    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", transport)
    monkeypatch.setattr(
        executor,
        "resolve_local_model_snapshot",
        lambda *args, **kwargs: tmp_path / resolved,
    )
    monkeypatch.setattr(
        executor.chat_service,
        "_build_mlx_generator",
        lambda *args, **kwargs: FixtureGenerator(),
    )
    result = executor.execute_product_case(
        case(question="What does soil texture mean?"),
        model_config=config_path,
        rag_config=ROOT / "configs/rag.yaml",
        output_dir=tmp_path / "cells",
        backend="mlx",
    )
    assert result["status"] == "completed", result.get("error")
    assert result["model_execution_eligible"] is eligible
    assert result["turns"][0]["model_revision_observation"]["resolved"] == resolved
    assert result["turns"][0]["model_revision_observation"]["verified"] is eligible
    assert bool(result["failed_checks"]) is not eligible


@pytest.mark.parametrize("fault_location", ["draft", "editor"])
def test_real_unavailable_draft_or_editor_blocks_quality_gate(
    tmp_path, monkeypatch, fault_location
):
    import agronomy_agent.release_eval_executor as executor

    config = yaml.safe_load((ROOT / "configs/model.yaml").read_text())
    config_path = tmp_path / "effective-model.yaml"
    config_path.write_text(yaml.safe_dump(config))

    class FixtureGenerator:
        model_id = config["model_id"]
        last_generation_stats = None
        model_identity = {
            "status": "verified_runtime_receipt",
            "configured_model_revision": config["model_revision"],
            "runtime": {"model_revision": config["model_revision"]},
        }

        def generate(self, messages):
            if fault_location == "draft":
                raise RuntimeError("fixture real draft backend unavailable")
            self.last_generation_stats = {"generation_tokens": 12, "prompt_tokens": 50}
            return "Soil texture describes sand, silt, and clay proportions."

    def editor_outcome(*args, **kwargs):
        return SimpleNamespace(
            answer="Fixture conservative fallback.",
            triggered=True,
            rewrite_accepted=False,
            draft_assessment=SimpleNamespace(reasons=("fixture_review",)),
            as_record=lambda: {
                "triggered": True,
                "rewrite_accepted": False,
                "fallback_applied": True,
                "rejection_reasons": ["editor_error", "RuntimeError"],
            },
        )

    monkeypatch.setenv("AGRONOMY_AGENT_MODEL_BACKEND", "http")
    monkeypatch.setattr(
        executor.chat_service,
        "_build_mlx_generator",
        lambda *args, **kwargs: FixtureGenerator(),
    )
    monkeypatch.setattr(executor.chat_service, "verify_answer", editor_outcome)
    result = executor.execute_product_case(
        case(question="What does soil texture mean?"),
        model_config=config_path,
        rag_config=ROOT / "configs/rag.yaml",
        output_dir=tmp_path / "cells",
        backend="mlx",
    )
    assert result["status"] == "completed", result.get("error")
    turn = result["turns"][0]
    assert turn["model_execution"]["disposition"] == "backend_fallback_or_unavailable"
    assert turn["model_execution"]["product_quality_eligible"] is False
    assert "turn_1.real_backend_and_editor_available" in {
        row["id"] for row in result["failed_checks"]
    }


@pytest.mark.parametrize("arm", ["raw_model", "kernel_only"])
def test_same_harness_case_reference_omits_production_assertions_explicitly(
    tmp_path, arm
):
    row = deepcopy(
        next(row for row in CASES if row["case_id"] == "HR1-conversion-forward")
    )
    result = run(tmp_path, row, arm_id=arm)
    assert result["status"] == "completed"
    assert result["failed_checks"] == []
    assert result["turns"][0]["stage_receipts"] == []
    assert result["assertion_scope"]["selected_assertion_ids"] == []
    omitted = result["assertion_scope"]["not_applicable_product_expectations"]
    assert {item["id"] for item in omitted} == set(row["assertions"])
    assert all(
        item["status"] == "not_applicable_diagnostic_arm" and "passed" not in item
        for item in omitted
    )
    assert not set(row["assertions"]).intersection(
        item["id"] for item in result["checks"]
    )


def test_arm_specific_unknown_assertion_blocks_instead_of_becoming_pass(tmp_path):
    row = case(
        assertions={"tool_status": "ready"},
        assertions_by_arm={"raw_model": {"unimplemented_arm_contract": True}},
    )
    result = run(tmp_path, row, arm_id="raw_model")
    assert result["status"] == "completed"
    assert [item["id"] for item in result["failed_checks"]] == [
        "unimplemented_arm_contract"
    ]
    assert "unimplemented_arm_contract" in {item["id"] for item in result["unknown"]}
    assert result["assertion_scope"]["selected_assertion_ids"] == [
        "unimplemented_arm_contract"
    ]


@pytest.mark.parametrize(
    "arm, invariant",
    [
        ("full_minus_field_context", "turn_1.typed_field_context_disabled"),
        ("retrieval_neither", "turn_1.document_retrieval_disabled"),
    ],
)
def test_diagnostic_arm_keeps_real_disable_invariants_without_product_expectations(
    tmp_path, arm, invariant
):
    row = case(
        question="What observations should I collect?",
        field_context={"crop": "canola"},
        assertions={
            "field_values": {"crop": "canola"},
            "expected_source_ids": ["unavailable_expectation"],
        },
    )
    result = run(tmp_path, row, arm_id=arm)
    assert result["status"] == "completed"
    assert result["failed_checks"] == []
    passed = {item["id"] for item in result["checks"] if item["passed"]}
    assert invariant in passed
    assert "turn_1.ordered_stages" in passed
    assert "turn_1.private_overlays_absent" in passed
    assert "field_values" not in passed and "expected_source_ids" not in passed


def test_production_existing_assertions_remain_required_and_do_not_use_diagnostic_override(
    tmp_path,
):
    row = case(
        assertions={"tool_status": "clarification_required"},
        assertions_by_arm={"production_full": {"tool_status": "ready"}},
    )
    result = run(tmp_path, row)
    assert result["status"] == "completed"
    assert [item["id"] for item in result["failed_checks"]] == ["tool_status"]
    assert result["assertion_scope"]["policy"] == "production_required"
    assert result["assertion_scope"]["not_applicable_product_expectations"] == []


@pytest.mark.parametrize("mapping", [{"invented_arm": {}}, {"raw_model": []}, []])
def test_invalid_arm_assertion_schema_is_rejected_before_execution(tmp_path, mapping):
    result = run(tmp_path, case(assertions_by_arm=mapping), arm_id="raw_model")
    assert result["status"] == "failed"
    assert result["turns"] == []
    assert "assertions_by_arm" in result["error"]["message"]


def test_disabled_field_receipt_contradiction_fails_automatic_diagnostic_check(
    tmp_path, monkeypatch
):
    import agronomy_agent.release_eval_executor as executor

    original = executor._production_turn

    def contradictory_observation(question, request):
        turn = original(question, request)
        field = next(
            row
            for row in turn["stage_receipts"]
            if row["stage_id"] == "typed_field_context"
        )
        field["evidence"]["field_context_present"] = True
        return turn

    monkeypatch.setattr(executor, "_production_turn", contradictory_observation)
    result = run(
        tmp_path,
        case(
            field_context={"crop": "canola"},
            assertions={"field_values": {"crop": "canola"}},
        ),
        arm_id="full_minus_field_context",
    )
    assert result["status"] == "completed"
    assert "turn_1.typed_field_context_disabled" in {
        row["id"] for row in result["failed_checks"]
    }
    assert "field_values" not in {row["id"] for row in result["checks"]}
