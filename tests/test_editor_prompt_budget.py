from __future__ import annotations

import pytest

from agronomy_agent.answer_verifier import verify_answer
from agronomy_agent.model_errors import LocalModelSnapshotUnavailable


BROKEN_DRAFT = "Answer the question directly.\n```json\n" + (
    "import math_utils_utils as math_utils_utils\n" * 12
)
QUESTION = "What is crop rotation, and why can it help manage disease pressure?"


@pytest.mark.parametrize("failure_stage", ["tokenization", "generation"])
def test_missing_editor_model_remains_an_actionable_setup_error(failure_stage: str) -> None:
    class MissingEditor:
        max_tokens = 60

        def count_prompt_tokens(self, messages):
            if failure_stage == "tokenization":
                raise LocalModelSnapshotUnavailable("synthetic missing editor snapshot")
            return 100

        def generate(self, messages):
            raise LocalModelSnapshotUnavailable("synthetic missing editor snapshot")

    with pytest.raises(LocalModelSnapshotUnavailable):
        verify_answer(
            BROKEN_DRAFT, question=QUESTION, evidence_text="", question_type="exam_review",
            risk_level="low", editor=MissingEditor(), review_mode="risk_gated",
            editor_context_management={"context_limit_tokens": 8192}, editor_max_tokens=60,
        )


class Editor:
    max_tokens = 60
    context_window_tokens = None

    def __init__(self) -> None:
        self.count_calls = 0
        self.generate_calls = 0

    def count_prompt_tokens(self, messages):  # noqa: ANN001, ANN201
        self.count_calls += 1
        return sum(len(item["content"].split()) + 4 for item in messages)

    def generate(self, messages):  # noqa: ANN001, ANN201
        self.generate_calls += 1
        return "A synthetic rewrite."


def test_oversized_editor_prompt_uses_explicit_fallback_without_editor_call() -> None:
    editor = Editor()
    result = verify_answer(
        BROKEN_DRAFT,
        question=QUESTION,
        evidence_text="Synthetic source text. " * 100,
        question_type="exam_review",
        risk_level="low",
        editor=editor,
        review_mode="risk_gated",
        max_evidence_chars=50,
        editor_context_management={"context_limit_tokens": 100},
        editor_max_tokens=60,
    )
    assert editor.count_calls == 1
    assert editor.generate_calls == 0
    assert result.triggered is True
    assert result.rewrite_accepted is False
    assert result.fallback_applied is True
    assert result.rejection_reasons == ("editor_context_budget_exceeded",)
    assert result.answer != BROKEN_DRAFT
    budget = result.as_record()["editor_context_budget"]
    assert budget["status"] == "over_limit"
    assert budget["token_count_basis"] == "tokenizer"
    assert budget["reserved_output_tokens"] == 60
    assert budget["remaining_tokens"] < 0
    assert budget["evidence_truncated"] is True
    assert budget["evidence_chars_included"] == 50
    assert budget["evidence_chars_available"] > 50


def test_selective_preserve_skips_editor_count_and_load() -> None:
    editor = Editor()
    result = verify_answer(
        "Crop rotation can reduce disease pressure.",
        question="What is crop rotation?",
        evidence_text="",
        question_type="general_agronomy",
        risk_level="low",
        editor=editor,
        review_mode="risk_conditioned_selective_v3",
        editor_context_management={"context_limit_tokens": 100},
        editor_max_tokens=60,
    )
    assert editor.count_calls == 0
    assert editor.generate_calls == 0
    assert result.triggered is False
    assert result.as_record()["editor_context_budget"] is None


def test_native_limit_discovered_during_editor_count_takes_precedence() -> None:
    class NativeEditor(Editor):
        def count_prompt_tokens(self, messages):  # noqa: ANN001, ANN201
            count = super().count_prompt_tokens(messages)
            self.context_window_tokens = 80
            return count

    editor = NativeEditor()
    result = verify_answer(
        BROKEN_DRAFT,
        question=QUESTION,
        evidence_text="",
        question_type="exam_review",
        risk_level="low",
        editor=editor,
        review_mode="risk_gated",
        editor_context_management={"context_limit_tokens": 8192},
        editor_max_tokens=60,
    )
    budget = result.as_record()["editor_context_budget"]
    assert editor.generate_calls == 0
    assert budget["context_limit_tokens"] == 80
    assert budget["limit_basis"] == "model"
    assert budget["status"] == "over_limit"
