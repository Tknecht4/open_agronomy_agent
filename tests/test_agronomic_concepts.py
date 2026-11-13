"""Imposed concept/authority boundary fixtures, not agronomic model grades."""
import pytest

from agronomy_agent.agronomic_concepts import correct_concept_claims, concept_prompt_guidance
from agronomy_agent.agent import build_answer_prompt
from agronomy_agent.answer_verifier import assess_claim_risk, verify_answer
from agronomy_agent.observation_guidance import observation_guidance
from agronomy_agent.quantity_claims import unsupported_quantities
from agronomy_agent.router import classify_query


class UnavailableEditor:
    def generate(self, messages):
        raise RuntimeError("Imposed unavailable editor")


def verify(draft, question):
    route = classify_query(question)
    return verify_answer(draft, question=question, evidence_text="", question_type=route.question_type,
        risk_level=route.risk_level, editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")


def test_requested_example_is_a_checked_example_rather_than_instructions():
    question = "Explain fertilizer product rate and nutrient rate with an illustrative example."
    method = observation_guidance(question)
    instructions = ("Product rate is the mass of product per area. Nutrient rate is the mass of nutrient per area. "
                    "For a hypothetical example, choose a fictional concentration and check the calculation.")
    assert "illustrative_rate_example" in method.missing(instructions)
    result = verify(instructions, question)
    assert result.triggered
    assert not method.missing(result.answer)
    assert "20% N" in result.answer and "60 × 0.20 = 12" in result.answer
    assert not unsupported_quantities(result.answer, question=question, evidence="")
    assert not method.missing(method.answer)


@pytest.mark.parametrize("incorrect", [
    "Drydown refers to the plant's ability to survive moisture stress.",
    "Drydown is a variety's tolerance to drought.",
    "Drydown is drought tolerance, not grain-moisture loss.",
])
def test_drydown_false_definition_is_repaired_locally_with_original_trace(incorrect):
    question = "Explain how crop rotation differs from choosing hybrids for drydown and lodging."
    before = "Rotation changes the crop sequence across seasons. "
    after = " Lodging concerns plants falling over."
    result = verify(before + incorrect + after, question)
    assert result.selection_policy == "localized_agronomic_concept_correction_v1"
    assert result.answer.startswith(before) and result.answer.endswith(after)
    assert "loss of moisture" in result.answer
    assert result.draft_output == before + incorrect + after
    assert result.localized_cleanup["edits"][0]["reason"] == "drydown_drought_conflation"
    assert not result.final_assessment.reasons
    assert "not retrieved evidence" in build_answer_prompt("", question)


def test_markdown_drydown_subclause_does_not_destroy_coordinated_lodging_definition():
    question = "Explain harvest drydown and its distinction from drought tolerance."
    lodging = ", while **lodging** is the physical failure of a plant to remain upright."
    draft = "**Drydown** refers to the plant's ability to mature and survive periods of moisture stress" + lodging
    result = verify(draft, question)
    assert result.answer.endswith(lodging)
    assert result.selection_policy == "localized_agronomic_concept_correction_v1"
    assert result.localized_cleanup["edits"][0]["original"].endswith("moisture stress")
    assert "lodging" not in result.localized_cleanup["edits"][0]["original"]


@pytest.mark.parametrize("question", [
    "Compare crop rotation and hybrid traits such as drydown and lodging.",
    "Contrast crop rotation with variety traits such as drydown and standability.",
    "Could you please compare crop rotation and hybrid traits such as drydown and lodging?",
    "Contrast crop rotation with hybrid traits such as drydown, standability and lodging.",
])
def test_impersonal_concept_comparison_does_not_turn_into_variety_selection_advice(question):
    draft = ("Rotation changes the crop sequence across seasons. Varieties within a crop differ in "
             "standability, harvest drydown and lodging; drydown concerns moisture loss toward harvest, "
             "and lodging means plants fall over.")
    assert classify_query(question).question_type == "exam_review"
    result = verify(draft, question)
    assert result.answer == draft
    assert not result.triggered and not result.final_assessment.reasons


@pytest.mark.parametrize("question", [
    "Compare soil texture and structure.",
    "Compare germination and emergence.",
    "Compare photosynthesis and respiration.",
    "Please compare soil texture, structure and porosity.",
])
def test_general_comparison_scope_is_not_tied_to_one_crop_or_case(question):
    from agronomy_agent.answerability import is_mechanism_explanation
    from agronomy_agent.request_scope import has_unqualified_followup
    assert is_mechanism_explanation(question)
    assert not has_unqualified_followup(question)
    assert classify_query(question).question_type == "exam_review"


@pytest.mark.parametrize("question", [
    "Compare crop rotation and hybrid traits; which should I choose?",
    "Compare crop rotation and hybrid traits for my field.",
    "Compare herbicide rates for canola.",
    "Contrast fungicide programs for this crop.",
    "Compare crop rotation and hybrid traits, then apply nitrogen.",
    "Compare crop rotation and hybrid traits. Can the crop be sprayed?",
    "Compare crop rotation and hybrid traits and recommend a herbicide rate.",
    "Compare 30 kg/ha and 60 kg/ha nitrogen treatments.",
    "Compare crop rotation and mulch beds.",
    "Contrast these traits, then transplant seedlings.",
    "Compare soil texture and structure, and choose an option.",
    "Compare hybrids for our field and select the best one.",
    "Mulch beds first. Compare photosynthesis and respiration.",
    "Transplant seedlings first. Compare photosynthesis and respiration.",
    "Compare photosynthesis and respiration and transplant seedlings.",
    "Compare photosynthesis and respiration such as drydown and transplant seedlings.",
    "Compare 20% and 40% concentrations.",
    "Compare ProductA and ProductB and rank their properties.",
    "Compare soil texture and structure. Authorize its use.",
    "Compare soil texture and improve soil properties.",
    "Compare crop rotation and optimize plant traits.",
    "Compare photosynthesis and adjust soil texture.",
    "Compare photosynthesis and respiration such as drydown and optimize plant traits.",
    "Why does water move through soil? Compare products and treatments.",
    "Why does water move through soil? Compare rates and doses.",
    "Why does water move through soil? Contrast options and programs.",
    "Explain why water moves through soil. Compare crop rotation and optimize plant traits.",
    "Compare crop rotation and soil properties then mulch.",
    "Compare soil texture and crop traits then transplant.",
    "Compare crop rotation and soil properties also mulch.",
    "Compare crop rotation and soil properties please mulch.",
])
def test_comparison_word_does_not_remove_decision_or_application_boundaries(question):
    from agronomy_agent.answerability import is_mechanism_explanation
    assert not is_mechanism_explanation(question)


@pytest.mark.parametrize("answer", [
    "Drydown is moisture loss toward grain harvest, not drought tolerance.",
    "Drought stress can affect grain development and later drydown.",
    "Drydown is not the ability to survive water stress.",
    "It is incorrect to say drydown is the ability to survive moisture stress.",
    'The grower asked, "Drydown is the ability to survive moisture stress?"',
])
def test_correct_drydown_contrasts_and_reported_misconceptions_are_preserved(answer):
    assert correct_concept_claims(answer, "Explain harvest drydown in hybrids.") == (answer, ())


def test_nonharvest_drydown_and_french_questions_do_not_receive_english_capsules():
    assert not concept_prompt_guidance("Explain the soil drydown experiment.")
    assert not concept_prompt_guidance("Expliquez le drydown des variétés en français.")


@pytest.mark.parametrize("incorrect", [
    "These two rates are related because the product contains active ingredient(s) that deliver the desired nutrients.",
    "A nutrient rate is derived from the product rate and the concentration of the active ingredient in the product.",
    "Nutrient rate expresses nutrient mass per area. This rate is calculated from active ingredient concentration.",
    "**Nutrient rate** describes nutrient mass (e.g., N or K) per area (e.g., per hectare). This rate is derived from the product rate and active ingredient concentration.",
])
def test_fertilizer_analysis_is_not_pesticide_active_ingredient_concentration(incorrect):
    question = "Explain nutrient rate versus product rate."
    draft = "Product rate is product mass per area. " + incorrect
    corrected, edits = correct_concept_claims(draft, question)
    assert edits and edits[0]["reason"] == "nutrient_active_ingredient_conflation"
    assert corrected.startswith("Product rate is product mass per area. ")
    assert "declared nutrient analysis" in corrected
    assert "nutrient_active_ingredient_conflation" in assess_claim_risk(draft, question=question).reasons
    result = verify(draft, question)
    assert "deliver the desired nutrients" not in result.answer
    assert not result.final_assessment.reasons


@pytest.mark.parametrize("answer", [
    "Fertilizer nutrient rate uses the nutrient analysis, not pesticide active ingredient concentration.",
    "Pesticide active ingredients control pests. A fertilizer nutrient rate uses its declared nutrient analysis.",
    "Copper can be a plant nutrient and a pesticidal active ingredient; the purpose and declared analysis matter.",
    "Copper-based active ingredients supply copper nutrients as well as serving a pesticidal role.",
    "Product rate and active ingredient rate are related through the pesticide formulation's active ingredient concentration.",
    "Nutrient rate is nutrient mass per area. For a pesticide, the product rate is formulation amount per area. This rate is derived from a specified active ingredient rate and its concentration.",
    "Nutrient rate is nutrient mass per area. A separate pesticide example follows. This rate is calculated from active ingredient concentration.",
])
def test_legitimate_ingredient_discussion_and_dual_roles_are_preserved(answer):
    assert correct_concept_claims(answer, "Explain nutrient rate versus product rate.") == (answer, ())


def test_nutrient_correction_preserves_a_coordinated_record_clause():
    question = "Explain nutrient rate versus product rate."
    suffix = ", while the previous product application remains recorded separately."
    draft = "A nutrient rate is derived from active ingredient concentration" + suffix
    corrected, edits = correct_concept_claims(draft, question)
    assert edits and corrected.endswith(suffix)
    assert "previous" not in edits[0]["original"]


def test_concept_repair_does_not_clear_another_unsupported_quantity_or_permission():
    question = "Compare crop rotation and grain harvest drydown."
    draft = "Drydown is the plant's ability to survive drought. Apply 17 kg/ha and spray now; it is approved."
    result = verify(draft, question)
    assert result.selection_policy != "localized_agronomic_concept_correction_v1"
    assert "17 kg/ha" not in result.answer


@pytest.mark.parametrize("change", [
    {"draft_assessment": {"reasons": []}},
    {"final_assessment": {"reasons": ["unsupported_numeric_specificity"]}},
    {"fallback_applied": True}, {"rewrite_accepted": True}, {"triggered": False},
    {"localized_cleanup": {"kind": "agronomic_concept_correction", "edits": []}},
])
def test_concept_origin_requires_named_defect_complete_edit_and_clean_final(change):
    from agronomy_agent.execution_core import classify_verification_origin
    record = {"triggered": True, "fallback_applied": False, "rewrite_accepted": False,
        "draft_assessment": {"reasons": ["drydown_drought_conflation"]},
        "final_assessment": {"reasons": []},
        "localized_cleanup": {"kind": "agronomic_concept_correction", "other_prose_unchanged": True,
            "editor_invoked": False, "edits": [{"reason": "drydown_drought_conflation",
                "original": "Drydown is drought tolerance", "replacement": "Drydown is moisture loss toward harvest"}]}}
    assert classify_verification_origin(record, draft_sha256="a", post_verification_sha256="b")["verification_action"] == "localized_cleanup"
    with pytest.raises(ValueError):
        classify_verification_origin(record | change, draft_sha256="a", post_verification_sha256="b")


@pytest.mark.parametrize("question,draft,retained", [
    ("Compare crop rotation and hybrid traits such as drydown and lodging.",
     "Rotation changes the crop sequence across seasons. Drydown is a variety's tolerance to drought. Lodging concerns plants falling over.",
     "loss of moisture"),
    ("Contrast crop rotation with hybrid traits such as drydown, standability and lodging.",
     "Rotation changes the crop sequence across seasons. Drydown is moisture loss toward grain harvest, not drought tolerance. Lodging concerns plants falling over.",
     "Rotation changes the crop sequence"),
    ("Explain harvest drydown and its distinction from drought tolerance.",
     "**Drydown** means a crop's ability to survive water stress, while lodging means plants fall over.",
     "while lodging means plants fall over"),
    ("Explain product rate versus nutrient rate.",
     "Product rate is product mass per area. Nutrient rate is nutrient mass per area. This rate is derived from active ingredient concentration.",
     "declared nutrient analysis"),
    ("Explain product rate versus nutrient rate using an illustrative example.",
     "Product rate is product mass per area. Nutrient rate is nutrient mass per area. Use a hypothetical example and check the arithmetic.",
     "60 × 0.20 = 12"),
    ("The soil sample was collected June 1 and the lab report was issued June 9. The analysis date was 7th June. Which sampling date should I compare?",
     "Compare the collection date, June 1. Keep the report issuance date, June 9, and analysis date, June 7, separately linked to the sample.",
     "analysis date, June 7"),
])
def test_repairs_and_preservation_reach_the_persisted_product_entrypoint(tmp_path, monkeypatch, question, draft, retained):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore

    class Backend:
        backend_id = "imposed_concept_fixture"
        intervention_profile = "balanced"
        def generate(self, messages):
            return draft
        def close(self):
            pass

    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: Backend())
    db = tmp_path / "synthetic.sqlite3"
    store = TraceStore(db)
    try:
        session = store.create_session("Synthetic concept checks", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=db, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message=question, mode="agronomic_rag", model_id="imposed",
            rag_config="configs/rag.yaml", max_tokens=180, generation_backend=Backend()))
        assert retained in result.answer
        assert store.get_turn(result.turn["turn_id"])["answer"] == result.answer
        assert len(result.stage_receipts) == 17
        if question.startswith(("Compare crop rotation", "Contrast crop rotation")):
            assert result.answer.startswith("Rotation changes the crop sequence across seasons.")
            assert "Lodging concerns plants falling over." in result.answer
            assert "disease ratings" not in result.answer and "local trials" not in result.answer
            if "not drought tolerance" in draft:
                assert result.answer == draft
    finally:
        store._conn.close()
