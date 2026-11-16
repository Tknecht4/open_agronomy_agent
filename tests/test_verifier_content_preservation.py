"""Keep useful requested content while editing concrete unsupported claims."""
import pytest

from agronomy_agent.answer_verifier import assess_claim_risk, verify_answer


ROOT_QUESTION = "My corn roots are swollen. What should I inspect today?"
ROOT_METHOD = (
    "Dig plants with their roots intact and compare affected plants with nearby healthy plants. "
    "Look for the shape and attachment of swellings, lesions, rot, or discoloration. "
    "Record crop stage and the field pattern. The cause remains uncertain; ask a diagnostic lab "
    "how to package representative roots if inspection does not resolve it."
)


class Editor:
    def __init__(self, answer=None):
        self.answer = answer
        self.calls = 0

    def generate(self, messages):
        self.calls += 1
        assert self.answer is not None, "Correct complete methods should not need an editor"
        return self.answer


@pytest.mark.parametrize("issuance", [
    "Report issued: 2030-06-21.",
    "The laboratory report was issued on 2030-06-21.",
    "The report has been issued on 2030-06-21.",
])
def test_supplied_date_roles_survive_equivalent_report_event_prose(issuance):
    question = (
        "My soil sample was collected 2030-06-14, analysed 2030-06-19, and its report "
        "issued 2030-06-21. Which sampling date should I compare across seasons, and "
        "how should I preserve the other dates?"
    )
    draft = (
        "Use the sample collection date, 2030-06-14, for sampling-date comparisons. "
        "Analysis date: 2030-06-19. " + issuance +
        " Keep the three events separately linked to the sample and original report."
    )
    editor = Editor()
    result = verify_answer(draft, question=question, evidence_text="", question_type="field_data",
                           risk_level="low", editor=editor, review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft
    assert not result.fallback_applied and editor.calls == 0


@pytest.mark.parametrize("inspection", [
    "Look for lesions, rot, or discoloration.",
    "Compare the roots, looking for damaged attachments, rot, and discoloration.",
    "Inspect the roots for rot.",
])
def test_generic_decay_in_an_inspection_list_is_not_a_named_disease(inspection):
    draft = ROOT_METHOD.replace("Look for the shape and attachment of swellings, lesions, rot, or discoloration.", inspection)
    editor = Editor()
    result = verify_answer(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health",
                           risk_level="high", editor=editor, review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft
    assert not result.draft_assessment.unsupported_named_conditions and editor.calls == 0


@pytest.mark.parametrize("claim", [
    "The swollen roots show rot, so that is the cause.",
    "Look for rot, which is confirmed.",
    "Look for damaged attachments, rot, which explains the swelling.",
    "Check the roots for rot, identified on every affected plant.",
    "Look for rot, or discoloration that explains the swelling.",
    "Look for root rot.",
    "Look for bacterial rot.",
    "Look for soft rot.",
    "Look for lesions, rot, or discoloration. The diagnosis is root rot.",
])
def test_inspection_context_does_not_license_disease_names_or_confirmed_findings(claim):
    assessment = assess_claim_risk(claim, question=ROOT_QUESTION, evidence_text="",
                                  question_type="plant_health", risk_level="high")
    assert assessment.unsupported_named_conditions


def test_generic_decay_exception_does_not_apply_to_other_tasks():
    assessment = assess_claim_risk("Look for rot.", question="What should I inspect on grain leaves?",
                                  evidence_text="", question_type="plant_health", risk_level="high")
    assert assessment.unsupported_named_conditions


@pytest.mark.parametrize("draft_missing_records", [False, True])
def test_claim_editor_cannot_trade_previously_present_required_content_for_a_repair(draft_missing_records):
    from agronomy_agent.answer_verifier import _rewrite_rejection_reasons
    draft = ROOT_METHOD + " Inspect for root rot."
    if draft_missing_records:
        draft = draft.replace("Record crop stage and the field pattern. ", "")
    rewrite = (
        "Dig plants with their roots intact and compare affected plants with nearby healthy plants. "
        "Record crop stage and the field pattern. The cause remains uncertain; ask a diagnostic lab "
        "how to package representative roots if inspection does not resolve it."
    )
    before = assess_claim_risk(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health", risk_level="high")
    after = assess_claim_risk(rewrite, question=ROOT_QUESTION, evidence_text="", question_type="plant_health", risk_level="high")
    reasons = _rewrite_rejection_reasons(draft=draft, rewrite=rewrite, draft_assessment=before,
        rewrite_assessment=after, question=ROOT_QUESTION, question_type="plant_health", evidence_handshake=None)
    assert "decision_content_lost:root_structure" in reasons


def test_editor_can_remove_an_unsupported_disease_name_without_losing_requested_help():
    draft = ROOT_METHOD + " Inspect for root rot."
    result = verify_answer(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health",
                           risk_level="high", editor=Editor(ROOT_METHOD), review_mode="risk_conditioned_selective_v3")
    assert result.rewrite_accepted and result.answer == ROOT_METHOD


def test_public_verification_rejects_an_editor_that_drops_concrete_root_inspection():
    draft = ROOT_METHOD + " Inspect for root rot."
    rewrite = ROOT_METHOD.replace("Look for the shape and attachment of swellings, lesions, rot, or discoloration. ", "")
    result = verify_answer(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health",
                           risk_level="high", editor=Editor(rewrite), review_mode="risk_conditioned_selective_v3")
    assert not result.rewrite_accepted
    assert "decision_content_lost:root_structure" in result.rejection_reasons
    assert "discoloration" in result.answer


@pytest.mark.parametrize("question,draft", [
    (ROOT_QUESTION, ROOT_METHOD),
    (
        "My soil sample was collected 2030-06-14, analysed 2030-06-19, and its report issued "
        "2030-06-21. Which sampling date should I compare across seasons, and how should I preserve the other dates?",
        "Use the sample collection date, 2030-06-14, for sampling-date comparisons. Analysis date: "
        "2030-06-19. Report issued: 2030-06-21. Keep the three events separately linked to the sample and original report.",
    ),
])
def test_complete_method_survives_the_persisted_production_path(tmp_path, monkeypatch, question, draft):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore

    class Backend:
        backend_id = "imposed_complete_method_fixture"
        intervention_profile = "balanced"
        calls = 0

        def generate(self, messages):
            self.calls += 1
            return draft

        def close(self):
            pass

    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *args, **kwargs: backend)
    db = tmp_path / "synthetic.sqlite3"
    store = TraceStore(db)
    try:
        session = store.create_session("Complete method preservation", {}, {})
        request = AgentExecutionRequest(store=store,
            settings=build_settings(db_path=db, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message=question, mode="agronomic_rag",
            model_id="imposed", rag_config="configs/rag.yaml", max_tokens=200,
            generation_backend=backend)
        result = chat_service.execute_agent_request(request)
        assert result.answer == draft
        assert store.get_turn(result.turn["turn_id"])["answer"] == draft
        assert len(result.stage_receipts) == 17 and backend.calls == 1
    finally:
        store._conn.close()


SOIL_EVIDENCE_CASES = [
    (
        "A soil analysis reports elevated EC. Can I derive an organic nutrient dose from that measurement?",
        "No. Electrical conductivity measures soluble salts; it does not calibrate a nutrient dose. "
        "Verify the sampling depth and laboratory method, then use representative fertility evidence, "
        "crop needs, nutrient credits and the material's analysis with applicable local guidance.",
    ),
    (
        "Our field boundary intersects a provincial soil survey polygon. What can its legend and coverage tell us?",
        "The legend describes mapped soil properties at the survey's stated scale. Check its coverage, "
        "date and boundary overlap; the map does not establish current conditions throughout the field. "
        "Compare representative sites with field observations before using the map for a decision.",
    ),
    (
        "Can an irrigation-water EC report determine an organic nutrient dose?",
        "No. An electrical conductivity report does not establish a nutrient budget. Confirm its method "
        "and sampling basis, obtain representative nutrient analyses, and check the crop requirement "
        "and applicable guidance before determining a dose.",
    ),
    (
        "Last season we scheduled irrigation. What does a soil map's coverage establish?",
        "It describes the area for which that survey provides mapping. Check the legend, scale, date "
        "and boundary overlap. Coverage does not establish uniform or current field conditions.",
    ),
    (
        "Explain how our irrigation timing was recorded last year.",
        "Use the dated operation log and its recording method. Distinguish the planned time from "
        "the recorded event and preserve missing or uncertain entries rather than inventing observations.",
    ),
]


@pytest.mark.parametrize("question,draft", SOIL_EVIDENCE_CASES)
def test_soil_domain_does_not_require_an_unrequested_water_management_method(question, draft):
    result = verify_answer(draft, question=question, evidence_text="", question_type="soil_water",
        risk_level="medium", editor=Editor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft and not result.fallback_applied
    assert not result.draft_assessment.missing_intent_facets


@pytest.mark.parametrize("question", [
    "What evidence do I need for an irrigation decision?",
    "How much should I irrigate today?",
    "How should I schedule watering this week?",
    "Which observations should support irrigation timing?",
    "Plan irrigation for tomorrow. What does a soil map cover?",
    "Calculate the irrigation depth for tomorrow. What does the soil map legend mean?",
    "Tell me when to irrigate. What does the soil map legend mean?",
    "Explain the soil legend and calculate the irrigation depth for tomorrow.",
    "Which root-zone observations and water records should support irrigation timing?",
])
def test_actual_irrigation_requests_keep_missing_water_evidence_checks(question):
    class UnavailableEditor:
        def generate(self, messages):
            raise RuntimeError("Imposed unavailable editor")
    result = verify_answer("Just look at the weather.", question=question, evidence_text="",
        question_type="soil_water", risk_level="medium", editor=UnavailableEditor(),
        review_mode="risk_conditioned_selective_v3")
    assert result.draft_assessment.missing_intent_facets
    assert result.fallback_applied
    assert "root zone" in result.answer.replace("root-zone", "root zone")
    assert "applied" in result.answer and not result.final_assessment.missing_intent_facets


@pytest.mark.parametrize("negative", [
    "I cannot confirm the field's current condition.",
    "I can't confirm the field's current condition.",
    "I can’t confirm the field's current condition.",
    "It does not independently confirm the field's current condition.",
    "It cannot yet reliably confirm the field's current condition.",
    "The soil survey never confirms current field conditions.",
])
def test_map_metadata_followed_by_negated_confirmation_is_not_an_affirmative_claim(negative):
    answer = "The soil survey has a coverage boundary. " + negative
    assessment = assess_claim_risk(answer, question="What can a soil survey establish?",
        question_type="field_data", risk_level="low")
    assert "map_prior_presented_as_field_truth" not in assessment.reasons


@pytest.mark.parametrize("answer", [
    "The soil survey confirms this field has uniform drainage. It cannot confirm the planting date.",
    "The soil survey cannot confirm the planting date, but confirms uniform drainage in this field.",
    "The soil survey indicates the field is dry. A map is not field truth.",
    "The soil survey confirms current texture. The source is not a field measurement.",
])
def test_negation_or_a_disclaimer_cannot_hide_a_separate_affirmative_map_claim(answer):
    assessment = assess_claim_risk(answer, question="What can a soil survey establish?",
        question_type="field_data", risk_level="low")
    assert "map_prior_presented_as_field_truth" in assessment.reasons


@pytest.mark.parametrize("crop", [None, "soybean", "canola"])
def test_freeze_recovery_does_not_invent_corn_or_a_reproductive_stage(crop):
    from agronomy_agent.answer_verifier import _conservative_failure_answer
    subject = "The crop" if crop is None else crop.capitalize()
    question = f"{subject} was injured by frost. What evidence would support a replant decision?"
    answer = _conservative_failure_answer("crop_management", question=question)
    assert "corn" not in answer.lower()
    assert "below the soil" not in answer and "reproductive stage" not in answer
    assert "crop stage" in answer and "growing points" in answer
    assert "stand uniformity" in answer and "new growth" in answer


def test_known_corn_recovery_does_not_assume_an_early_growth_stage():
    from agronomy_agent.answer_verifier import _conservative_failure_answer
    answer = _conservative_failure_answer("crop_management",
        question="Corn was injured by frost. What evidence would support a replant decision?")
    assert "Confirm corn growth stage" in answer
    assert "may still be protected" in answer and "later stages" in answer


def test_equivalent_plural_growing_points_do_not_replace_a_complete_recovery_answer():
    question = "What observations should support a decision about replanting after frost?"
    draft = (
        "First establish the crop and stage. Inspect growing points for healthy firm tissue, roots and "
        "the injury pattern across representative areas. Revisit for new growth and count surviving "
        "plants and stand uniformity. Compare the recovered stand with the remaining planting window "
        "and the cost of replanting using current local guidance."
    )
    result = verify_answer(draft, question=question, evidence_text="", question_type="crop_management",
        risk_level="medium", editor=Editor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft and not result.fallback_applied


APPLICATION_EXPLANATION_QUESTION = "Why can weed responses to a herbicide differ with growth stage?"
APPLICATION_EXPLANATION = (
    "Growth stage affects uptake, translocation and susceptibility. Different weed species and "
    "conditions can therefore produce different responses; that mechanism does not establish a "
    "product choice or permission for any field application."
)


@pytest.mark.parametrize("instruction", [
    "Spray the whole field now.",
    "You should spray this crop today.",
    "Use glyphosate.",
    "Apply nitrogen to the crop.",
    "Treat this field now.",
    "I recommend spraying the field now.",
    "Check records and spray the crop.",
    "Apply the herbicide only if its label allows it.",
    "Consider using glyphosate.",
    "Spray all fields now.",
    "You could spray the whole field now.",
    "You need to spray this crop.",
    "Apply a tank mix of herbicides.",
    "Apply nitrogen then check records.",
    "Use glyphosate then compare costs.",
    "Use the herbicide per label.",
    "Apply herbicides.",
    "Use fungicides.",
    "Increase nitrogen now.",
    "Select a herbicide.",
    "Spray pesticides today.",
    "An efficacy result does not mean you can use glyphosate, but you should apply nitrogen now.",
])
def test_explanations_cannot_introduce_nonnumeric_application_instructions(instruction):
    from agronomy_agent.answerability import has_application_instruction
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    from agronomy_agent.router import classify_query, refine_query_route
    question = APPLICATION_EXPLANATION_QUESTION
    route = refine_query_route(question, classify_query(question))
    draft = APPLICATION_EXPLANATION + " " + instruction
    assessment = assess_claim_risk(draft, question=question, question_type=route.question_type,
        risk_level=route.risk_level)
    assert "unrequested_application_instruction" in assessment.reasons
    final = enforce_answer_safety_postconditions(draft, question=question, route=route)
    assert not has_application_instruction(final)
    assert instruction not in final


@pytest.mark.parametrize("prose", [
    "Spray drift depends on droplet size and wind.",
    "Do not spray the field.",
    "You should not apply a pesticide from a general explanation.",
    "Use the pesticide label to verify restrictions.",
    "Use glyphosate label information to identify the registered use.",
    "Use manure analysis and soil-test records to build a nutrient budget.",
    "Use treatment comparisons to assess efficacy.",
    "Apply the formula to the supplied values.",
    "Pesticides can be sprayed according to their verified labels.",
    "The untreated comparison is evidence, not permission to spray.",
    "Use the product's label to check the use restrictions.",
    "Spraying the crop is an application, not a resistance mechanism.",
    "Applying nitrogen changes the nutrient input.",
    "Using a pesticide does not establish that resistance caused a control failure.",
    "Use herbicide response data to compare the treatments.",
    "Use nitrogen uptake data to explain the growth response.",
    "Use fertilizer prices to compare the costs.",
    "Farmers may apply manure to supply crop nitrogen; that can also add phosphorus.",
    "An efficacy result does not mean you can use glyphosate.",
    "This mechanism does not establish that you should spray the field.",
    "The analysis cannot show that you may apply nitrogen.",
])
def test_descriptions_data_methods_and_negative_application_boundaries_are_not_instructions(prose):
    from agronomy_agent.answerability import has_application_instruction
    assert not has_application_instruction(prose)


def test_rewrite_can_remove_an_unasked_application_and_keep_the_explanation():
    draft = APPLICATION_EXPLANATION + " Spray the whole field now."
    result = verify_answer(draft, question=APPLICATION_EXPLANATION_QUESTION,
        evidence_text="", question_type="exam_review", risk_level="low",
        editor=Editor(APPLICATION_EXPLANATION), review_mode="risk_conditioned_selective_v3")
    assert result.answer == APPLICATION_EXPLANATION and result.rewrite_accepted
    assert "unrequested_application_instruction" in result.draft_assessment.reasons


def test_persisted_explanation_rejects_an_imposed_nonnumeric_spray_instruction(tmp_path, monkeypatch):
    from agronomy_agent.answerability import has_application_instruction
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    draft = APPLICATION_EXPLANATION + " Spray the whole field now."

    class Backend:
        backend_id = "imposed_unasked_application_fixture"
        intervention_profile = "balanced"
        calls = 0

        def generate(self, messages):
            self.calls += 1
            return draft

        def close(self):
            pass

    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: backend)
    db = tmp_path / "synthetic.sqlite3"
    store = TraceStore(db)
    try:
        session = store.create_session("Bounded explanation", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=db, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message=APPLICATION_EXPLANATION_QUESTION,
            mode="agronomic_rag", model_id="imposed", rag_config="configs/rag.yaml", max_tokens=200,
            generation_backend=backend))
        assert backend.calls >= 1 and len(result.stage_receipts) == 17
        assert result.answer != draft and not has_application_instruction(result.answer)
        assert store.get_turn(result.turn["turn_id"])["answer"] == result.answer
    finally:
        store._conn.close()
