from agronomy_agent.answer_safety import enforce_answer_safety_postconditions


def test_us_rate_request_uses_us_product_authority() -> None:
    question = (
        "For my US crop field, choose a herbicide application rate from general agronomy principles. "
        "I have not provided the product name, formulation, crop, state or label."
    )
    draft = "Use the current PMRA label and Canadian registration. Apply 100 kg/ha."
    answer = enforce_answer_safety_postconditions(
        draft, question=question, route={"question_type": "product_label"}
    )

    assert "cannot choose a U.S. pesticide or application rate" in answer
    assert "EPA registration number" in answer
    assert "applicable state requirements" in answer
    assert "PMRA" not in answer
    assert "100 kg/ha" not in answer


def test_us_state_rate_request_uses_us_product_authority() -> None:
    answer = enforce_answer_safety_postconditions(
        "Check a current PMRA label.",
        question="Can I spray this product in Iowa at a typical rate?",
        route={"question_type": "product_label"},
    )
    assert "EPA-registered" in answer
    assert "PMRA" not in answer


def test_canadian_label_request_preserves_canadian_authority() -> None:
    answer = enforce_answer_safety_postconditions(
        "I cannot choose a rate.",
        question="What pesticide rate should I apply to my Manitoba field?",
        route={"question_type": "product_label"},
    )
    assert "PMRA label and Canadian registration" in answer
