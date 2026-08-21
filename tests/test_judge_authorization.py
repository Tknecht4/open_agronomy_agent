from __future__ import annotations

import datetime as dt

import pytest

from agronomy_agent.judge_authorization import (
    REQUIRED_PAYLOAD_CLASSES,
    canonical_sha256,
    validate_judge_authorization,
    validate_semantic_controls,
)


def _controls() -> dict:
    return {"controls": [{"id": key, "passed": True} for key in (
        "answer_order_reversal",
        "concise_correct_vs_verbose_vague",
        "supported_vs_cosmetic_citation",
        "useful_caution_vs_blanket_refusal",
        "corrupted_reference_negative",
    )]}


def _authorization(*, relationship: str = "cross_model", promotion_eligible: bool = False) -> dict:
    return {
        "schema_version": "open_agronomy_agent.semantic_judge_egress_authorization.v1",
        "authorization_decision": "authorized",
        "authorization_source": "fixture-owner",
        "authorized_at": "2026-08-20T00:00:00Z",
        "expires_at": "2026-08-22T00:00:00Z",
        "benchmark_contract_sha256": "benchmark",
        "selected_rows_sha256": "rows",
        "judge_prompt_sha256": "prompt",
        "judge_output_schema_sha256": "schema",
        "semantic_controls_sha256": canonical_sha256(_controls()),
        "recipient_backend": "codex_app_server_chatgpt_auth",
        "model_id": "gpt-5.6-luna",
        "generator_judge_relationship": relationship,
        "promotion_eligible": promotion_eligible,
        "authorized_payload_classes": sorted(REQUIRED_PAYLOAD_CLASSES),
    }


def _validate(auth: dict, source_models: set[str]):
    return validate_judge_authorization(
        auth,
        benchmark_contract_sha256="benchmark",
        selected_rows_sha256="rows",
        judge_prompt_sha256="prompt",
        judge_output_schema_sha256="schema",
        semantic_controls_sha256=validate_semantic_controls(_controls()),
        recipient_backend="codex_app_server_chatgpt_auth",
        model_id="gpt-5.6-luna",
        source_model_ids=source_models,
        now=dt.datetime(2026, 8, 21, tzinfo=dt.UTC),
    )


def test_cross_model_authorization_is_advisory_and_bound() -> None:
    grant = _validate(_authorization(), {"mlx-community/gemma-4-e2b-it-4bit"})
    assert grant.generator_judge_relationship == "cross_model"
    assert grant.promotion_eligible is False


def test_self_judgment_cannot_be_promotion_eligible() -> None:
    with pytest.raises(ValueError, match="cannot be promotion eligible"):
        _validate(_authorization(relationship="same_exact_model", promotion_eligible=True), {"gpt-5.6-luna"})


def test_authorization_fails_on_selected_row_or_control_drift() -> None:
    auth = _authorization()
    auth["selected_rows_sha256"] = "different"
    with pytest.raises(ValueError, match="selected_rows_sha256 mismatch"):
        _validate(auth, {"gemma"})
    controls = _controls()
    controls["controls"][0]["passed"] = False
    with pytest.raises(ValueError, match="semantic controls not satisfied"):
        validate_semantic_controls(controls)
