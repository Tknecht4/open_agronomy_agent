from __future__ import annotations

import json
from pathlib import Path

from agronomy_agent.answer_verifier import (
    AnswerVerificationResult,
    ClaimRiskAssessment,
    RISK_CONDITIONED_SELECTIVE_V3_THRESHOLDS,
    verify_answer,
)


ROOT = Path(__file__).resolve().parents[1]


class _NeverEdit:
    def generate(self, messages):  # noqa: ANN001, ANN201
        raise AssertionError("benign low-risk explanation must not invoke the editor")


def test_v3_thresholds_are_model_independent_and_match_frozen_config() -> None:
    config = json.loads(
        (ROOT / "configs/risk_conditioned_selective_v3.json").read_text()
    )
    assert config["model_conditioned"] is False
    assert config["thresholds"] == dict(RISK_CONDITIONED_SELECTIVE_V3_THRESHOLDS)


def test_v3_preserves_a_benign_supported_explanation_directly() -> None:
    result = verify_answer(
        "Crop rotation changes the crop sequence between seasons.",
        question="What is crop rotation?",
        evidence_text="Crop rotation changes the crop sequence between seasons.",
        question_type="conceptual",
        risk_level="low",
        editor=_NeverEdit(),
        review_mode="risk_conditioned_selective_v3",
    )
    record = result.as_record()
    assert result.triggered is False
    assert record["selection_policy"] == "risk_conditioned_selective_v3"
    assert record["risk_threshold_receipt"]["model_conditioned"] is False


def test_claim_edit_ledger_requires_a_named_defect_for_replacement() -> None:
    assessment = ClaimRiskAssessment(
        requires_review=True,
        score=3,
        reasons=("unsupported_numeric_specificity",),
        unsupported_numbers=("17 kg/ha",),
        unsupported_crop_stages=(),
        unsupported_scientific_names=(),
        unsupported_named_conditions=(),
        unsupported_named_pests=(),
        missing_intent_facets=(),
        evidence_ids=("source-1",),
    )
    record = AnswerVerificationResult(
        answer="Use the current locally applicable recommendation.",
        triggered=True,
        rewrite_accepted=True,
        draft_assessment=assessment,
        final_assessment=assessment,
        draft_output="Apply 17 kg/ha.",
        editor_output="Use the current locally applicable recommendation.",
        selection_policy="risk_conditioned_selective_v3",
    ).as_record()
    ledger = record["claim_edit_ledger"]
    assert ledger["changed_claim_count"] == 1
    assert ledger["replacement_has_named_defect"] is True
    assert ledger["changed_claims"][0]["evidence_ids"] == ["source-1"]
