from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_v3_competence_candidate.py"


def _module():
    spec = importlib.util.spec_from_file_location("audit_v3_competence_candidate_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config() -> dict[str, object]:
    return {
        "benchmark_id": "fixture-v3cc",
        "status": "public_external_reference_candidate_frozen",
        "claim_eligible": False,
        "sealed_v3_satisfied": False,
        "candidate_model": {"model_id": "gemma", "model_revision": "rev"},
        "external_dataset": {"rows": 1},
        "regional_case_count": 1,
        "external_arm_order": ["raw_model", "production_full"],
        "regional_arm_order": ["raw_model", "production_full"],
        "trial_ids": ["trial-001"],
    }


def _manifest() -> dict[str, object]:
    return {"status": "frozen_inputs_verified", "external_rows": 1, "regional_rows": 1, "sealed_v3_satisfied": False}


def _results() -> list[dict[str, object]]:
    rows = []
    for lane in ("public_external_competence_candidate", "canadian_regional_competence_candidate"):
        for arm in ("raw_model", "production_full"):
            rows.append(
                {
                    "lane": lane,
                    "eval_id": f"{lane}-1",
                    "arm": arm,
                    "trial_id": "trial-001",
                    "model_id": "gemma",
                    "model_revision": "rev",
                    "stage_receipt_count": 17,
                }
            )
    return rows


def _controls(passed: bool = True) -> dict[str, object]:
    return {
        "controls": [
            {"id": control_id, "passed": passed}
            for control_id in (
                "answer_order_reversal",
                "concise_correct_vs_verbose_vague",
                "supported_vs_cosmetic_citation",
                "useful_caution_vs_blanket_refusal",
                "corrupted_reference_negative",
            )
        ]
    }


def test_audit_passes_complete_exact_matrix_but_never_sealed_v3() -> None:
    report = _module().audit(
        config=_config(),
        input_manifest=_manifest(),
        results=_results(),
        semantic_controls=_controls(),
    )
    assert report["engineering_rc_status"] == "ready_for_owner_decision"
    assert report["sealed_v3_status"] == "blocked_human_gates_unfulfilled"
    assert report["claim_eligible"] is False


def test_audit_fails_closed_without_execution_or_controls() -> None:
    report = _module().audit(
        config=_config(),
        input_manifest=_manifest(),
        results=None,
        semantic_controls=None,
    )
    assert report["engineering_rc_status"] == "blocked"
    assert {row["id"] for row in report["failures"]} >= {
        "complete_execution_matrix",
        "semantic_instrument_controls",
    }
