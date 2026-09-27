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
    assert "Health Canada registered product label and Canadian registration" in answer


def test_cross_border_label_source_does_not_override_us_field_target() -> None:
    for question in (
        "Can I use a Canadian-labeled herbicide on my Iowa corn field?",
        "My US field has a Canadian label. Can I use the herbicide?",
        "May I treat my crop in the US using a Canadian label?",
        "Can I use an Ontario pesticide label on my Iowa farm?",
    ):
        answer = enforce_answer_safety_postconditions(
            "Check the current PMRA label.",
            question=question,
            route={"question_type": "product_label"},
        )
        assert "EPA-registered" in answer
        assert "PMRA" not in answer


def test_cross_border_us_label_does_not_override_canadian_field_target() -> None:
    for place in ("Manitoba", "Nova Scotia", "Yukon"):
        answer = enforce_answer_safety_postconditions(
            "I cannot choose a rate.",
            question=f"Can I use a US-labeled herbicide on my {place} field?",
            route={"question_type": "product_label"},
        )
        assert "Health Canada registered product label and Canadian registration" in answer

    for question in (
        "May I treat my crop in Canada using a US label?",
        "Can I apply a US pesticide to my Canadian field using an Iowa label?",
    ):
        answer = enforce_answer_safety_postconditions(
            "I cannot choose a rate.",
            question=question,
            route={"question_type": "product_label"},
        )
        assert "Health Canada registered product label and Canadian registration" in answer


def test_wrong_epa_instruction_is_not_retained_for_canadian_field() -> None:
    answer = enforce_answer_safety_postconditions(
        "Check the current EPA-registered product label before applying.",
        question="Can I use a US-labeled herbicide on my Nova Scotia field?",
        route={"question_type": "product_label"},
    )
    assert answer.startswith("A U.S. product label or recommendation does not authorize")
    assert "Health Canada registered product label and Canadian registration" in answer
    assert "Check the current EPA" not in answer


def test_factual_epa_explanation_is_preserved_for_canadian_reader() -> None:
    answer = enforce_answer_safety_postconditions(
        "EPA is the U.S. Environmental Protection Agency; its label does not authorize Canadian use.",
        question="What does EPA mean on a document sent to my Canadian farm?",
        route={"question_type": "product_label"},
    )
    assert "EPA is the U.S. Environmental Protection Agency" in answer
    assert "Health Canada registered product label" in answer


def test_pmra_definition_is_not_renamed_to_epa_for_us_reader() -> None:
    answer = enforce_answer_safety_postconditions(
        "PMRA is Canada's Pest Management Regulatory Agency. It does not authorize use in the United States.",
        question="What does PMRA mean on a label sent to my US farm?",
        route={"question_type": "product_label"},
    )
    assert "PMRA is Canada's Pest Management Regulatory Agency" in answer
    assert "EPA is Canada's" not in answer
    assert "current EPA-registered labeling" in answer


def test_us_explanation_does_not_preserve_wrong_pmra_instruction() -> None:
    answer = enforce_answer_safety_postconditions(
        "Verify the current PMRA label.",
        question="What label authority matters for my US farm?",
        route={"question_type": "product_label"},
    )
    assert "current EPA-registered product labeling" in answer
    assert "PMRA" not in answer


def test_canadian_action_uses_stable_health_canada_authority_name() -> None:
    answer = enforce_answer_safety_postconditions(
        "Verify the current PMRA label.",
        question="Can I apply this pesticide to my Manitoba field?",
        route={"question_type": "product_label"},
    )
    assert "current Health Canada registered product label" in answer
    assert "current PMRA label" not in answer


def test_ambiguous_or_missing_treatment_jurisdiction_stays_neutral() -> None:
    for question in (
        "Can I apply this pesticide?",
        "Can I use this product on my US field and my Ontario field?",
    ):
        answer = enforce_answer_safety_postconditions(
            "Check a current PMRA label.",
            question=question,
            route={"question_type": "product_label"},
        )
        assert "without the treatment jurisdiction" in answer
        assert "PMRA" not in answer
        assert "EPA" not in answer
