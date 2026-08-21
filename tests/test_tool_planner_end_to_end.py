from __future__ import annotations

import json
from pathlib import Path

from agronomy_agent.agent import generate_answer, load_agent_resources
from agronomy_agent.server.services.chat_service import run_turn
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


ROOT = Path(__file__).resolve().parents[1]


class _NeverGenerate:
    measured_capability_profile = "balanced"

    def generate(self, messages):  # noqa: ANN001, ANN201
        raise AssertionError("a deterministic calculation or clarification must not call the model")


def _calculation_rows() -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / "data/eval/canadian_agronomic_calculations_v1.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]


def test_all_frozen_calculations_use_one_result_identity_through_the_full_agent_path() -> None:
    resources = load_agent_resources("configs/rag_final_mvp.yaml")

    for row in _calculation_rows():
        answer, metadata = generate_answer(
            row["question"],
            "agronomic_rag",
            _NeverGenerate(),
            resources=resources,
            field_context=row.get("field_context"),
            verification_enabled=True,
            capture_context_packet=True,
        )

        invocation = metadata["tool_invocations"][0]
        result = metadata["tool_results"][0]
        result_id = result["result_id"]
        evidence_rows = metadata["evidence_fabric"]["evidence_packet"]["capability_evidence"]
        tool_evidence = [item for item in evidence_rows if item["evidence_kind"] == "tool_result"]

        assert metadata["generation_path"] == "deterministic_tool_result", row["eval_id"]
        assert invocation["tool_id"] == "agronomic_calculator"
        assert invocation["invocation_id"] == result["invocation_id"]
        assert result["status"] == "calculated"
        assert answer == result["payload"]["answer"]
        assert abs(float(result["payload"]["value"]) - float(row["reference_numeric"])) <= float(
            row["absolute_tolerance"]
        )
        assert tool_evidence[0]["result_id"] == result_id
        assert result_id in metadata["benchmark_generation_input"]["context_block"]
        assert result_id in metadata["benchmark_generation_input"]["messages"][1]["content"]
        assert metadata["answer_verification"]["result_ids"] == [result_id]
        assert metadata["evidence_fabric"]["validated_answer"]["answer_status"] == (
            "validated_typed_capability_result"
        )
        assert metadata["answer_stages"]["draft"]["sha256"] == metadata["answer_stages"]["final"]["sha256"]


def test_missing_calculator_input_returns_only_the_minimal_clarification() -> None:
    answer, metadata = generate_answer(
        "How many kg of urea supplies 80 kg N/ha?",
        "agronomic_rag",
        _NeverGenerate(),
        verification_enabled=True,
    )

    assert metadata["generation_path"] == "deterministic_tool_clarification"
    assert answer == "To calculate this, provide nutrient_percent."
    assert "soil test" not in answer.casefold()
    assert "cannot" not in answer.casefold()
    assert metadata["answer_verification"]["status"] == "needs_input"
    assert metadata["answer_verification"]["result_ids"] == []
    assert metadata["evidence_fabric"]["validated_answer"]["answer_status"] == "review_required"


def test_product_label_number_conversion_preserves_the_claim_boundary() -> None:
    answer, metadata = generate_answer(
        "Convert 2 kg/ha of this herbicide label rate to lb/ac.",
        "agronomic_rag",
        _NeverGenerate(),
        verification_enabled=True,
    )

    assert metadata["generation_path"] == "deterministic_tool_result"
    assert answer.startswith("1.784 lb/ac")
    assert "only converts the user-supplied number" in answer
    assert "does not establish that a label is current or applicable" in answer
    assert "does not authorize use" in answer


def test_server_persists_the_same_result_id_in_prompt_trace_evidence_and_database(tmp_path) -> None:  # noqa: ANN001
    store = TraceStore(tmp_path / "trace.sqlite3")
    session = store.create_session("calculator", {}, {})
    settings = build_settings(
        db_path=tmp_path / "unused.sqlite3",
        artifact_root=tmp_path / "artifacts",
    )

    response = run_turn(
        store=store,
        settings=settings,
        session_id=session["session_id"],
        message="Convert a fertilizer rate of 100 lb/ac to kg/ha.",
        mode="agronomic_rag",
        model_id="mock",
        rag_config="configs/rag_final_mvp.yaml",
        max_tokens=100,
        trace_options={"store_prompt_messages": True, "store_retrieved_text": False},
    )

    stored = store.get_turn(response["turn_id"])
    assert stored is not None
    trace = stored["trace"]
    result = next(item for item in trace["tool_invocations"] if item.get("result_id"))
    result_id = result["result_id"]
    evidence = trace["metadata"]["evidence_fabric"]["evidence_packet"]["capability_evidence"]

    assert trace["metadata"]["generation_path"] == "deterministic_tool_result"
    assert trace["metadata"]["tool_result_ids"] == [result_id]
    assert result_id in trace["prompt_messages"][1]["content"]
    assert result_id in {item["result_id"] for item in evidence}
    assert trace["metadata"]["answer_verification"]["result_ids"] == [result_id]
    assert trace["metadata"]["evidence_fabric"]["validated_answer"]["answer_status"] == (
        "validated_typed_capability_result"
    )
    assert stored["answer"].startswith("112.085 kg/ha")
