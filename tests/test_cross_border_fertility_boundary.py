from agronomy_agent.answer_safety import enforce_answer_safety_postconditions


def test_us_nutrient_guide_cannot_set_canadian_field_rate() -> None:
    question = "Can a USDA nutrient guide legally set a Manitoba nitrogen fertilizer rate for my field?"
    original = "The field needs current soil tests and local calibration."

    answer = enforce_answer_safety_postconditions(original, question=question)

    assert answer.startswith("No. U.S. nutrient guidance")
    assert "cannot establish a Canadian legal or locally calibrated field fertilizer rate" in answer
    assert original not in answer


def test_cross_border_boundary_discards_conflicting_rate_claim() -> None:
    question = "Can a USDA guide legally set a fertilizer rate for a Canadian field?"
    answer = enforce_answer_safety_postconditions(
        "Yes, apply 100 kg/ha because the U.S. guide is authoritative.", question=question
    )

    assert answer.startswith("No. U.S. nutrient guidance")
    assert "100 kg/ha" not in answer


def test_cross_border_boundary_is_not_injected_into_unrelated_questions() -> None:
    original = "Compare methods and preserve their geographic limits."
    for question in (
        "Compare U.S. and Canadian nutrient testing methods.",
        "Compare U.S. and Canadian fertilizer application rates.",
        "What does the Manitoba nutrient guide say about soil sampling?",
        "What nitrogen rate should I apply to my Iowa corn field?",
        "Can you help us check a Canadian nitrogen fertilizer rate?",
    ):
        assert enforce_answer_safety_postconditions(original, question=question) == original


def test_existing_explicit_cross_border_refusal_is_normalized_once() -> None:
    question = "Can a U.S. guide set the legal fertilizer rate for a Canadian wheat field?"
    original = "U.S. guidance cannot establish a Canadian field fertilizer rate."

    answer = enforce_answer_safety_postconditions(original, question=question)

    assert answer.startswith("No. U.S. nutrient guidance")
    assert answer.count("cannot establish") == 1
