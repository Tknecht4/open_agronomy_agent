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


@pytest.mark.parametrize("issuance,report_date", [
    ("Report issued: 2030-06-21.", "2030-06-21"),
    ("The laboratory report was issued on 2030-06-21.", "2030-06-21"),
    ("The report has been issued on 2030-06-21.", "2030-06-21"),
    ("Report issuance (2030-06-21).", "2030-06-21"),
    ("Report issuance (21 June 2030).", "2030-06-21"),
    ("Report issuance (June 21, 2030).", "2030-06-21"),
    ("Report issuance (21 Jun. 2030).", "2030-06-21"),
    ("Report issuance (Jun. 21, 2030).", "2030-06-21"),
    ("Report issuance (21 June).", "21 June"),
    ("Report issuance (21 Jun.).", "21 June"),
])
def test_supplied_date_roles_survive_equivalent_report_event_prose(issuance, report_date):
    question = (
        "My soil sample was collected 2030-06-14, analysed 2030-06-19, and its report "
        f"issued {report_date}. Which sampling date should I compare across seasons, and "
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
    "Look for galls, lesions, rot, or unusual discoloration.",
    "Check the roots for rot and abnormal discoloration.",
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
    "Look for rot, or unusual discoloration that explains the swelling.",
    "Look for rot and abnormal discoloration, which confirms the diagnosis.",
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


def test_root_records_accept_an_explicit_note_of_stage_and_symptom_distribution():
    draft = ROOT_METHOD.replace(
        "Record crop stage and the field pattern.",
        "Note where symptoms occur in the field and the crop stage, and take clear photos.",
    )
    result = verify_answer(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health",
                           risk_level="high", editor=Editor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft and not result.triggered


@pytest.mark.parametrize("statement", [
    "Note that crop stage alone cannot establish the cause.",
    "Note the current herbicide label, but crop stage is unknown.",
    "Note where symptoms occur, but ignore the distribution and the crop stage.",
])
def test_rhetorical_or_unrelated_notes_do_not_supply_root_recording_instructions(statement):
    draft = ROOT_METHOD.replace("Record crop stage and the field pattern.", statement)
    assessment = assess_claim_risk(draft, question=ROOT_QUESTION, question_type="plant_health", risk_level="high")
    assert "root_records" in assessment.missing_intent_facets


@pytest.mark.parametrize("proposition", [
    "Report issuance (2030-06-21) is the analysis date.",
    "Report issuance (2030-06-21) is the collection date.",
    "The analysis date is report issuance (2030-06-21).",
    "Use the collection date as report issuance (2030-06-21).",
    "Treat report issuance (2030-06-21) as the processing date.",
    "Analysis (2030-06-21) and report issuance (2030-06-21).",
    "Processing (21 June) and report issuance (21 June).",
    "Report issuance (21 June 2030) is the analysis date.",
    "Treat report issuance (June 21, 2030) as the collection date.",
    "Analysis (21 Jun. 2030) and report issuance (21 Jun. 2030).",
    "Report issuance (21 Jun. 2030) is the analysis date.",
    "The collection date is report issuance (Jun. 21, 2030).",
    "No analysis (21 Jun. 2030) is confirmed. Analysis (21 Jun. 2030).",
    "No analysis (21 Jun.) is confirmed. Analysis (21 Jun.).",
])
def test_nominal_date_items_do_not_license_role_conflation_or_an_invented_event(proposition):
    question = (
        "The soil sample was collected 2030-06-14 and its report issued 2030-06-21. "
        "Which sampling date should I compare, and how should I keep the other dates?"
    )
    draft = (
        "Use the collection date, 2030-06-14, for comparisons. Keep each event separately linked. "
        "Report issuance (2030-06-21). "
        + proposition
    )
    assessment = assess_claim_risk(draft, question=question, evidence_text="", question_type="field_data")
    assert "sample_event_role_conflation" in assessment.reasons


@pytest.mark.parametrize("ending", [
    "Report issuance (2030-06-21) is not the analysis date.",
    "Do not treat report issuance (2030-06-21) as the collection date.",
    "Do not use the analysis date as report issuance (2030-06-21).",
    "It is not true that report issuance (2030-06-21) is the analysis date.",
    "If report issuance (2030-06-21) is the collection date, check the separate event records first.",
    "Report issuance (21 June 2030) is not the analysis date.",
    "Do not treat report issuance (Jun. 21, 2030) as the collection date.",
])
def test_nominal_report_role_denials_or_conditionals_do_not_assert_reassignment(ending):
    question = (
        "The soil sample was collected 2030-06-14 and its report issued 2030-06-21. "
        "Which sampling date should I compare and how should I keep the dates?"
    )
    draft = (
        "Use the collection date for sampling comparisons. Keep distinct events separately. "
        "Report issuance (2030-06-21). " + ending
    )
    assessment = assess_claim_risk(draft, question=question, question_type="field_data")
    assert "sample_event_role_conflation" not in assessment.reasons


@pytest.mark.parametrize("statement", [
    "Is the analysis (2030-06-19) supplied?",
    "If analysis (2030-06-19), can I store that?",
    "No analysis (2030-06-19) is confirmed.",
    "Analysis (2030-06-19), but that is unconfirmed.",
    "Is the analysis (19 Jun. 2030) supplied?",
    "If analysis (19 Jun. 2030), can I store that?",
    "No analysis (19 Jun. 2030) is confirmed.",
    "Analysis (19 Jun. 2030), but that is unconfirmed.",
])
def test_nominal_analysis_event_retains_occurrence_local_question_and_denial_controls(statement):
    question = (
        "The soil sample was collected 2030-06-14 and the report issued 2030-06-21. "
        + statement + " How should I keep the dates?"
    )
    draft = (
        "Use the collection date for sampling comparisons. Keep the events separately: "
        "analysis (2030-06-19); report issuance (2030-06-21)."
    )
    assessment = assess_claim_risk(draft, question=question, question_type="field_data")
    assert "sample_event_role_conflation" in assessment.reasons


def test_abbreviated_analysis_date_can_be_supplied_without_merging_event_roles():
    question = (
        "My soil sample was collected 2030-06-14. Analysis (19 Jun. 2030) is supplied, "
        "and the report was issued 2030-06-21. Which sampling date should I compare, "
        "and how should I keep the dates?"
    )
    draft = (
        "Use the collection date, 2030-06-14, for sampling comparisons. Keep distinct events "
        "separately linked: analysis (19 Jun. 2030); report issuance (21 Jun. 2030)."
    )
    editor = Editor()
    result = verify_answer(draft, question=question, evidence_text="", question_type="field_data",
                           risk_level="low", editor=editor,
                           review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft and editor.calls == 0 and not result.triggered


@pytest.mark.parametrize("text,clauses", [
    ("Analysis (21 Jun. 2030). Report issuance (21 June 2030).",
     ["Analysis (21 Jun. 2030).", " Report issuance (21 June 2030)."]),
    ("Analysis (21 Jun.). Report issuance (21 June).",
     ["Analysis (21 Jun.).", " Report issuance (21 June)."]),
    ("Analysis 21 Jun. Another event remains unknown.",
     ["Analysis 21 Jun.", " Another event remains unknown."]),
    ("No analysis is confirmed. Analysis (21 Jun. 2030).",
     ["No analysis is confirmed.", " Analysis (21 Jun. 2030)."]),
])
def test_sample_event_clause_boundaries_preserve_original_date_and_sentence_bytes(text, clauses):
    from agronomy_agent.answer_verifier import _sample_event_clauses
    assert [clause + ending for clause, ending in _sample_event_clauses(text)] == clauses


def test_independently_supplied_coincident_dates_retain_their_separate_roles():
    question = (
        "The soil sample was collected 2030-06-14, analysed 2030-06-21, and its report "
        "issued 2030-06-21. Which sampling date should I compare, and how should I keep the dates?"
    )
    draft = (
        "Use the collection date for sampling comparisons. Keep distinct events: collection "
        "(2030-06-14), analysis (2030-06-21), and report issuance (2030-06-21). "
        "The analysis and report dates coincide, but their event roles remain separate."
    )
    result = verify_answer(draft, question=question, evidence_text="", question_type="field_data",
                           risk_level="low", editor=Editor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft and not result.triggered


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
    (
        "My soil sample was collected 2030-06-14, analysed 2030-06-19, and its report issued "
        "2030-06-21. Which sampling date should I compare across seasons, and how should I preserve the other dates?",
        "Store distinct dated events: collection (2030-06-14), analysis (2030-06-19), and report issuance "
        "(2030-06-21). Use the collection date for sampling comparisons; retain each role separately.",
    ),
    (
        ROOT_QUESTION,
        ROOT_METHOD.replace("rot, or discoloration", "rot, or unusual discoloration").replace(
            "Record crop stage and the field pattern.",
            "Note where symptoms occur in the field and the crop stage, and take clear photos.",
        ),
    ),
    (
        "My soil sample was collected 2030-06-14, analysed 2030-06-19, and its report issued "
        "2030-06-21. Which sampling date should I compare across seasons, and how should I preserve the other dates?",
        "Store distinct dated events: collection (2030-06-14), analysis (2030-06-19), and report issuance "
        "(June 21, 2030). Use the collection date for sampling comparisons; retain each role separately.",
    ),
    (
        ROOT_QUESTION,
        ROOT_METHOD + " Treat the plants gently while lifting them to preserve the fine roots.",
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
    "Apply it tomorrow.",
    "Spray it on your crop.",
    "You should apply it tomorrow.",
    "Apply this mixture tomorrow.",
    "Use the formulation on the field.",
    "Use these on the plants.",
    "It should be applied tomorrow.",
    "The formulation should be used on the field.",
    "It is recommended that you apply it tomorrow.",
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
    "Use it to compare the treatment responses.",
    "Use it to read the current label.",
    "Apply it to the supplied data.",
    "Apply it to the field data.",
    "Use it on the soil-test results.",
    "Apply the formulation to the crop moisture measurements.",
    "It should be applied to the field data.",
    "Use the formulation to calculate the product amount.",
    "The formulation should be used to compare the results.",
    "Do not apply it.",
    "You should not spray it.",
    "The operator applied it last season.",
    "Applying it changes the input.",
    "If you apply it tomorrow, read the label first.",
    '"Apply it tomorrow" is an example of an instruction.',
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
    "Treat the plants gently while lifting them to preserve the fine roots.",
    "Treat your plant carefully while lifting it to keep the roots intact.",
])
def test_descriptions_data_methods_and_negative_application_boundaries_are_not_instructions(prose):
    from agronomy_agent.answerability import has_application_instruction
    assert not has_application_instruction(prose)


def test_rewrite_can_remove_an_unasked_application_and_keep_the_explanation():
    draft = APPLICATION_EXPLANATION.rstrip(".").replace(". ", "; ") + "; spray the whole field now."
    result = verify_answer(draft, question=APPLICATION_EXPLANATION_QUESTION,
        evidence_text="", question_type="exam_review", risk_level="low",
        editor=Editor(APPLICATION_EXPLANATION), review_mode="risk_conditioned_selective_v3")
    assert result.answer == APPLICATION_EXPLANATION and result.rewrite_accepted
    assert "unrequested_application_instruction" in result.draft_assessment.reasons


@pytest.mark.parametrize("question,explanation", [
    (APPLICATION_EXPLANATION_QUESTION, APPLICATION_EXPLANATION),
    (ROOT_QUESTION, ROOT_METHOD.replace("rot, or discoloration", "rot, or unusual discoloration")),
    ("My corn roots are swollen beside the gate. What should I inspect today?", ROOT_METHOD),
])
@pytest.mark.parametrize("instruction", [
    "Spray the whole field now.",
    "A fungicide should be applied to the roots tomorrow.",
    "It is recommended to apply a fungicide to the roots tomorrow.",
    "It is recommended that a fungicide be applied to the roots tomorrow.",
])
def test_persisted_non_prescriptive_help_rejects_an_imposed_nonnumeric_spray_instruction(
    tmp_path, monkeypatch, question, explanation, instruction,
):
    from agronomy_agent.answerability import has_application_instruction
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    draft = explanation + " " + instruction

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
            session_id=session["session_id"], message=question,
            mode="agronomic_rag", model_id="imposed", rag_config="configs/rag.yaml", max_tokens=200,
            generation_backend=backend))
        assert backend.calls >= 1 and len(result.stage_receipts) == 17
        assert result.answer != draft and not has_application_instruction(result.answer)
        assert store.get_turn(result.turn["turn_id"])["answer"] == result.answer
    finally:
        store._conn.close()


@pytest.mark.parametrize("trailing,retained", [
    ("", ""),
    (" Then apply the fertilizer to the field.", ""),
    (" If symptoms persist, spray at dusk.", ""),
    (" Apply 10 kg/ha nitrogen. Spray tomorrow.", ""),
    ("\n- **Apply nitrogen.**", ""),
    ("\n1. Spray tomorrow.", ""),
    ("\n1) Spray tomorrow.", ""),
    ("\n+ Apply *nitrogen*.", ""),
    ("\n_Spray tomorrow._", ""),
    (" **Spray tomorrow.** Keep plot identifiers with the readings.", " Keep plot identifiers with the readings."),
    ("\n**Do not spray tomorrow based on this comparison.**", "\n**Do not spray tomorrow based on this comparison.**"),
    (' The record says "Spray tomorrow."', ' The record says "Spray tomorrow."'),
])
def test_persisted_analytical_measurements_survive_application_guard(tmp_path, monkeypatch, trailing, retained):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore

    method = "Use the nitrogen uptake measurements to compare the replicated strips. Compare matched sampling dates and units."

    class Backend:
        backend_id = "synthetic_analytical_measurements"
        intervention_profile = "balanced"
        calls = 0

        def generate(self, messages):
            self.calls += 1
            return method + trailing

        def close(self):
            pass

    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: backend)
    db = tmp_path / "synthetic.sqlite3"
    store = TraceStore(db)
    try:
        session = store.create_session("Synthetic analytical comparison", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(
            store=store,
            settings=build_settings(db_path=db, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], mode="agronomic_rag", model_id="imposed",
            message="How do I compare nitrogen uptake measurements between replicated strips?",
            rag_config="configs/rag.yaml", max_tokens=200, generation_backend=backend,
        ))
        assert backend.calls and len(result.stage_receipts) == 17
        assert result.answer == method + retained
        assert store.get_turn(result.turn["turn_id"])["answer"] == result.answer
    finally:
        store._conn.close()


@pytest.mark.parametrize("instruction", [
    "Apply a fungicide to the roots tomorrow.",
    "Use a pesticide on the affected plants.",
    "Apply a fungicide at 2 L/ha tomorrow.",
    "Treat the plants with a fungicide.",
    "Treat the plants gently while lifting them to preserve the fine roots. Then apply a fungicide.",
    "Treat the plants gently while lifting them with a fungicide.",
])
def test_root_inspection_cannot_introduce_an_unasked_material_application(instruction):
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    from agronomy_agent.answerability import has_application_instruction
    from agronomy_agent.router import classify_query, refine_query_route
    route = refine_query_route(ROOT_QUESTION, classify_query(ROOT_QUESTION))
    draft = ROOT_METHOD.replace("rot, or discoloration", "rot, or unusual discoloration") + " " + instruction
    assessment = assess_claim_risk(draft, question=ROOT_QUESTION, question_type=route.question_type,
                                  risk_level=route.risk_level)
    assert "unrequested_application_instruction" in assessment.reasons
    final = enforce_answer_safety_postconditions(draft, question=ROOT_QUESTION, route=route)
    assert not has_application_instruction(final) and instruction not in final


@pytest.mark.parametrize("boundary", [
    "Do not apply a fungicide from these observations alone.",
    "Use the pesticide label to check restrictions before any separate treatment decision.",
])
def test_root_inspection_keeps_negative_application_boundaries_and_label_information(boundary):
    draft = ROOT_METHOD + " " + boundary
    result = verify_answer(draft, question=ROOT_QUESTION, evidence_text="", question_type="plant_health",
                           risk_level="high", editor=Editor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft and not result.triggered


@pytest.mark.parametrize("question", [
    ROOT_QUESTION + " Then apply a fungicide.",
    "Apply a fungicide. " + ROOT_QUESTION,
    ROOT_QUESTION + " Also, which pesticide rate should I spray?",
    "My corn roots are swollen beside the gate. What should I inspect today? What fungicide rate should I apply?",
    "My corn roots are swollen beside the gate. What should I inspect today? Then irrigate the field.",
    ROOT_QUESTION + " Can I apply a fungicide to the roots?",
    ROOT_QUESTION + " May we spray the affected plants?",
    ROOT_QUESTION + " Should I use a pesticide on the roots?",
])
def test_non_prescriptive_output_scope_does_not_consume_a_mixed_root_and_action_request(question):
    from agronomy_agent.answerability import non_prescriptive_help_requested
    assert not non_prescriptive_help_requested(question)


@pytest.mark.parametrize("question", [
    "My corn roots are swollen beside the gate. What should I inspect today?",
    "My corn roots are swollen in the lower part of the field. What should I inspect today?",
    "My corn roots are swollen at V4. What should I inspect today?",
    "I found swollen roots on my corn near the gate. What should I inspect today?",
    "My corn roots are swollen beside healthy soybean plants. What should I inspect today?",
])
def test_root_context_does_not_disable_the_output_application_guard(question):
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    from agronomy_agent.answerability import has_application_instruction, non_prescriptive_help_requested
    from agronomy_agent.plant_health_scope import root_inspection_only_request
    from agronomy_agent.router import classify_query, refine_query_route

    # Extra context still needs the ordinary whole-request decision planner.
    assert not root_inspection_only_request(question)
    assert non_prescriptive_help_requested(question)
    route = refine_query_route(question, classify_query(question))
    assert enforce_answer_safety_postconditions(ROOT_METHOD, question=question, route=route) == ROOT_METHOD
    instruction = "Apply a fungicide to the roots tomorrow."
    draft = ROOT_METHOD + " " + instruction
    assessment = assess_claim_risk(draft, question=question, question_type=route.question_type,
                                  risk_level=route.risk_level)
    assert "unrequested_application_instruction" in assessment.reasons
    final = enforce_answer_safety_postconditions(draft, question=question, route=route)
    assert instruction not in final and not has_application_instruction(final)


@pytest.mark.parametrize("instruction", [
    "A fungicide should be applied to the roots tomorrow.",
    "The fungicide must be sprayed on the affected plants.",
    "The affected plants should be sprayed tomorrow.",
    "The plants should be treated with a fungicide tomorrow.",
    "It is recommended to apply a fungicide to the roots tomorrow.",
    "It is advisable to spray the whole field now.",
    "It is advised that you spray the whole field now.",
    "It is recommended that you apply a fungicide to the roots tomorrow.",
    "It is recommended that a fungicide be applied to the roots tomorrow.",
    "It is recommended that the plants be treated with a fungicide tomorrow.",
])
def test_passive_or_impersonal_wording_does_not_authorize_an_unasked_application(instruction):
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    from agronomy_agent.answerability import has_application_instruction

    draft = ROOT_METHOD + " " + instruction
    assert has_application_instruction(instruction)
    assessment = assess_claim_risk(draft, question=ROOT_QUESTION, question_type="plant_health", risk_level="low")
    assert "unrequested_application_instruction" in assessment.reasons
    final = enforce_answer_safety_postconditions(draft, question=ROOT_QUESTION)
    assert instruction not in final and not has_application_instruction(final)


@pytest.mark.parametrize("statement", [
    "A fungicide should not be applied from these observations alone.",
    "A fungicide must never be applied without the applicable label.",
    "It is not recommended to apply a fungicide from these observations alone.",
    "It is recommended to inspect the roots before considering treatment.",
    "It is recommended that you do not apply a fungicide from these observations alone.",
    "It is not recommended that you apply a fungicide from these observations alone.",
    "It is recommended that fungicide response data be compared with untreated controls.",
    "Fungicide response data should be compared with the untreated controls.",
    "A fungicide was applied to these plants last year.",
    "The pesticide label states which crops may be treated.",
    "Spray drift affects plants near the field edge.",
    "Treat the affected plants gently while lifting them to preserve the fine roots.",
])
def test_passive_application_screen_keeps_denials_history_and_analytical_information(statement):
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    from agronomy_agent.answerability import has_application_instruction

    draft = ROOT_METHOD + " " + statement
    assert not has_application_instruction(statement)
    assert enforce_answer_safety_postconditions(draft, question=ROOT_QUESTION) == draft


@pytest.mark.parametrize("followup", [
    "Can I use the pesticide label as a record?",
    "Can I use fungicide response data to compare the treatments?",
    "May we compare fungicide response data with the untreated controls?",
])
def test_root_output_scope_does_not_confuse_analytical_or_label_objects_with_applications(followup):
    from agronomy_agent.answerability import non_prescriptive_help_requested
    assert non_prescriptive_help_requested(ROOT_QUESTION + " " + followup)
