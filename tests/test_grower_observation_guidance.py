"""Production-bound observation help and negative authority controls.

These imposed answers test the repair mechanism, not model or agronomic quality.
"""
from types import SimpleNamespace

import pytest

from agronomy_agent.agent import build_answer_prompt, decide_evidence_intervention
from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
from agronomy_agent.answer_verifier import verify_answer, bounded_decision_support
from agronomy_agent.answerability import AnswerabilityState, assess_answerability
from agronomy_agent.execution_core import AgentExecutionRequest
from agronomy_agent.observation_guidance import observation_guidance
from agronomy_agent.router import classify_query
from agronomy_agent.server.services.chat_service import execute_agent_request
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


METHOD_CASES = [
    ("NDVI declined between dates and masks are missing. Also, can one GPS point establish planted area?", "combined_observations", ("valid pixel", "closed polygon", "length and width")),
    ("An empty LiDAR terrain clip has zero features. How should I compare affected and normal plants while scouting?", "combined_observations", ("parcel coverage", "separately", "revisit")),
    ("Can a vegetable spacing guide describe a haskap layout, and can one GPS point establish planted area?", "combined_observations", ("closed polygon", "perennial", "harvest access")),
    ("How should we compare normal and affected plants on a scouting walk?", "paired_scouting", ("roots", "separately", "revisit")),
    ("On my next walk after rain, what should I check in pale low spots?", "paired_scouting", ("roots", "normal", "soil moisture")),
    ("NDVI declined between dates; masks and valid pixel counts are missing. What can I infer?", "imagery_comparison", ("cloud", "valid pixel", "processing")),
    ("An empty LiDAR terrain clip has no flow-path intersections. Does that mean no wetness risk?", "empty_terrain_coverage", ("parcel coverage", "acquisition", "infiltration")),
    ("Can one GPS point establish planted area?", "point_area", ("closed polygon", "length and width")),
    ("Can a vegetable guide's fertilizer table and spacing plan transfer to honeyberry?", "crop_guide_applicability", ("perennial", "harvest access", "do not copy")),
    ("A national crop-health layer has a stress patch: should I reduce nitrogen everywhere?", "regional_crop_signal", ("not a field diagnosis", "roots", "previous-crop credits", "soil nitrate")),
    ("Can the regional crop-health map diagnose mummy berry and let me spray blueberries?", "regional_crop_signal", ("not a field diagnosis", "roots", "diagnostic sampling")),
]


class UnavailableEditor:
    def generate(self, messages):
        raise RuntimeError("imposed editor failure")


FOLIAR_COMPARISON = (
    "Compare several affected plants with nearby healthy plants of the same variety and crop stage. "
    "Inspect upper and lower leaf surfaces and stems, photograph the lesions, and map their distribution. "
    "The comparison describes a pattern; lesions alone do not confirm a disease."
)


@pytest.mark.parametrize("question", [
    "Our potato leaves show brown spots. How can we compare affected leaves with nearby normal leaves?",
    "My barley foliage has lesions. How should I compare affected and healthy plants for suspected leaf disease?",
])
def test_foliar_comparison_keeps_the_inspection_task_without_a_disease_program(question, tmp_path, monkeypatch):
    from agronomy_agent.answer_verifier import _intent_requirements
    from agronomy_agent.decision_route import build_decision_route_state
    route = classify_query(question)
    state = build_decision_route_state(question, route.question_type)
    assert state.decision == "foliar_observation"
    assert not state.answer_violations(FOLIAR_COMPARISON)
    method = observation_guidance(question)
    assert method and method.has_method("foliar_comparison")
    assert not method.missing(FOLIAR_COMPARISON)
    requirements = {item.name for item in _intent_requirements(question, route.question_type)}
    assert "foliar_paired_comparison" in requirements
    assert "weather_disease_risk" not in requirements and "current_label_context" not in requirements
    _assert_persisted_product_answer(tmp_path, monkeypatch, question,
        ("same variety", "leaf surfaces", "distribution"), draft=FOLIAR_COMPARISON)


@pytest.mark.parametrize("addition", [
    "Then choose a fungicide.",
    "What application rate should I spray?",
    "Is it safe to enter the field?",
    "Also mow the field.",
])
@pytest.mark.parametrize("action_first", [False, True])
def test_foliar_comparison_does_not_consume_an_additional_action(addition, action_first):
    from agronomy_agent.decision_route import build_decision_route_state
    from agronomy_agent.plant_health_scope import foliar_observation_request_kind
    question = "Our potato leaves show brown spots. How can we compare affected leaves with nearby normal leaves?"
    mixed = addition + " " + question if action_first else question + " " + addition
    assert foliar_observation_request_kind(mixed) is None
    assert build_decision_route_state(mixed, classify_query(mixed).question_type).decision != "foliar_observation"


@pytest.mark.parametrize("question", [
    "Last season our potato leaves had spots. How can we compare affected and normal plants?",
    "Our potato leaves have no lesions. How can we compare affected and normal plants?",
    "If our potato leaves have lesions, how should we compare affected and normal plants?",
    "Our potato leaves have lesions. Does that confirm late blight?",
])
def test_foliar_comparison_does_not_invent_current_symptoms_or_consume_a_diagnosis(question):
    from agronomy_agent.plant_health_scope import foliar_observation_request_kind
    assert foliar_observation_request_kind(question) is None


def test_healthy_potato_scouting_prompt_does_not_request_a_diagnostic_program():
    from agronomy_agent.decision_route import build_decision_route_state
    question = "What should we look for while monitoring our healthy potato plants for signs of late blight?"
    state = build_decision_route_state(question, classify_query(question).question_type)
    assert state.decision == "foliar_observation" and state.capsule is None
    assert not state.decisive_evidence and not state.premise_anchors
    assert build_decision_route_state(question + " Choose a fungicide.", "plant_health").decision != "foliar_observation"


@pytest.mark.parametrize("claim", [
    "If considering a fungicide, confirm the diagnosis first.",
    "Wait for visible symptoms before starting a preventive fungicide program.",
    "Preventive fungicide use requires a confirmed infection.",
    "If symptoms appear, collect samples, but preventive fungicide use requires confirmed infection.",
])
def test_healthy_crop_monitoring_does_not_require_infection_before_preventive_planning(claim):
    question = "How can we monitor our healthy potato plants for signs of late blight?"
    method = observation_guidance(question)
    assert method and method.has_method("healthy_potato_monitoring")
    draft = claim + " " + method.answer
    assert method.unsupported_inference(draft)
    route = classify_query(question)
    result = verify_answer(draft, question=question, evidence_text="", question_type=route.question_type,
        risk_level=route.risk_level, editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer != draft and not method.unsupported_inference(result.answer)
    assert not method.missing(result.answer)


@pytest.mark.parametrize("claim", [
    "Do not wait for visible symptoms before discussing preventive fungicide protection.",
    "Preventive fungicide planning does not require confirmed field infection.",
    "If symptoms appear, ask a diagnostic service to confirm the cause before treating affected plants.",
])
def test_healthy_crop_monitoring_keeps_prevention_and_conditional_diagnostic_help(claim):
    method = observation_guidance("How can we monitor our healthy potato plants for signs of late blight?")
    assert method and not method.unsupported_inference(claim)


@pytest.mark.parametrize("purpose", [
    "harvest approval", "treatment authorization", "fungicide selection", "spray permission",
    "a confirmed diagnosis", "possible treatment authorization",
])
def test_foliar_comparison_does_not_grant_an_operational_or_certification_purpose(purpose):
    from agronomy_agent.decision_route import build_decision_route_state
    from agronomy_agent.plant_health_scope import foliar_observation_request_kind
    question = f"Our potato leaves show brown spots. How can we compare affected and nearby healthy plants for {purpose}?"
    assert foliar_observation_request_kind(question) is None
    assert build_decision_route_state(question, classify_query(question).question_type).decision != "foliar_observation"


@pytest.mark.parametrize("subject", ["My soybean", "My corn", "My potato", "My carrot", "My millet", "My faba bean", "The"])
def test_current_swollen_root_inspection_requires_a_practical_method(subject):
    from agronomy_agent.decision_route import build_decision_route_state
    question = f"{subject} roots are swollen. What should I inspect today?"
    route = classify_query(question)
    assert route.question_type == "plant_health"
    assert build_decision_route_state(question, route.question_type).decision == "root_observation"
    method = observation_guidance(question)
    assert method and method.has_method("current_root_inspection")
    draft = "Inspect the roots closely to determine the cause. Pathogens or environmental stress may be involved."
    assert method.missing(draft)
    result = verify_answer(draft, question=question, evidence_text="", question_type=route.question_type,
        risk_level=route.risk_level, editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer != draft and not method.missing(result.answer)
    assert "dig" in result.answer.lower() and "normal" in result.answer.lower()
    assert "record" in result.answer.lower() and "diagnostic" in result.answer.lower()
    assert "clubroot" not in result.answer.lower()
    assert ("nodules" in result.answer.lower()) == ("soybean" in subject)


@pytest.mark.parametrize("question", [
    "Last year soybean roots were swollen. What should I inspect today?",
    "Earlier canola had swollen roots. What should I inspect today?",
    "My soybean roots are not swollen. What should I inspect today?",
    "There are no swollen roots. What should I inspect today?",
    "My corn leaves have galls. What should I inspect today?",
    "My millet stems have galls. What should I inspect today?",
    "I saw a dying patch. What should I inspect today?",
    "Explain the difference between normal roots and swollen roots.",
    "What are soybean nodules?",
    "Define root swelling.",
    "Last year the agronomist wrote 'soybean roots are swollen'. What should I inspect today?",
    "Last year, I found swollen roots on my soybeans. What should I inspect today?",
    "If soybean roots are swollen, what should I inspect?",
])
def test_root_method_does_not_invent_a_current_root_observation(question):
    from agronomy_agent.plant_health_scope import root_inspection_requested
    assert not root_inspection_requested(question)
    method = observation_guidance(question)
    assert method is None or not method.has_method("current_root_inspection")


@pytest.mark.parametrize("question", [
    "Soybean is healthy. My corn roots are swollen. What should I inspect today?",
    "Last year soybean roots were swollen. My millet roots are swollen. What should I inspect today?",
    "My corn roots are swollen, while nearby soybean is healthy. What should I inspect today?",
    "Soybean roots are healthy and corn roots are swollen. What should I inspect today?",
    "My corn roots are swollen beside healthy soybean roots. What should I inspect today?",
])
def test_normal_soybean_nodules_are_not_projected_from_history_or_a_healthy_reference(question):
    method = observation_guidance(question)
    assert method and method.has_method("current_root_inspection")
    assert "On soybean" not in method.answer and "nodules" not in method.answer


@pytest.mark.parametrize("question", [
    "My corn roots are swollen. What should I inspect today, and what herbicide rate should I apply?",
    "My corn roots are swollen. What should I inspect today? Then transplant seedlings.",
    "Mulch beds. My corn roots are swollen. What should I inspect today?",
    "Fertilize because soybean roots are swollen. What should I inspect today?",
    "I found swollen roots on my soybeans then transplant. What should I inspect today?",
])
def test_root_observation_does_not_erase_an_additional_operation(question):
    from agronomy_agent.decision_route import build_decision_route_state
    from agronomy_agent.plant_health_scope import root_inspection_only_request
    assert not root_inspection_only_request(question)
    assert build_decision_route_state(question, classify_query(question).question_type).decision != "root_observation"


@pytest.mark.parametrize("question", [
    "My soybean roots are swollen. What should I inspect today?",
    "My millet roots are swollen. What should I inspect today?",
    "My corn roots are swollen today after last year's flooding. What should I inspect today?",
    "How should I scout my healthy potato crop for late blight?",
])
def test_useful_inspection_method_reaches_the_persisted_product_path(tmp_path, monkeypatch, question):
    terms = ("representative", "lesions", "local disease alerts", "diagnostic") if "potato" in question else ("roots", "normal", "record", "diagnostic")
    _assert_persisted_product_answer(tmp_path, monkeypatch, question, terms)


def test_potato_monitoring_rejects_surface_names_and_alerts_without_a_scouting_method():
    question = "How should I scout my healthy potato crop for late blight?"
    method = observation_guidance(question)
    draft = "Inspect the foliage and stems for any early symptoms. Keep checking current local disease alerts."
    assert method and {"potato_monitor_signs", "potato_monitor_coverage", "potato_monitor_followup"} <= set(method.missing(draft))
    result = verify_answer(draft, question=question, evidence_text="", question_type="plant_health", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer != draft and not method.missing(result.answer)
    assert "water-soaked" in result.answer and "humid" in result.answer and "diagnostic" in result.answer
    assert "absence does not exclude" in result.answer


def test_generic_lesions_and_necrosis_do_not_complete_disease_specific_scouting(tmp_path, monkeypatch):
    question = "How should I scout my healthy potato crop for late blight?"
    draft = ("Scout representative areas. Inspect foliage and stems for spots, lesions, or necrosis. "
             "Check local disease alerts and contact a diagnostic lab for suspect findings.")
    method = observation_guidance(question)
    assert method and method.missing(draft) == ("potato_monitor_signs",)
    _assert_persisted_product_answer(tmp_path, monkeypatch, question,
                                    ("water-soaked", "humid", "absence does not exclude"), draft=draft)


@pytest.mark.parametrize("signs", [
    "Look for white mildew growth under the soil.",
    "Under the stem, look for white sporulation.",
    "White growth below roots may appear when humid.",
])
def test_white_growth_requires_a_leaf_underside_location(signs):
    method = observation_guidance("How should I scout my healthy potato crop for late blight?")
    assert method and "potato_monitor_signs" in method.missing(signs)


@pytest.mark.parametrize("signs", [
    "Look for water-soaked patches on leaves.",
    "Inspect lesions that look water soaked.",
    "Watch for rapidly expanding dark lesions.",
    "Watch for dark, spreading lesions.",
    "Look for new or spreading lesions.",
    "Check whether lesions expand rapidly.",
    "White mildew growth may appear on leaf undersides in humid conditions.",
    "Under leaves, white sporulation can appear when humid.",
])
def test_potato_signs_facet_preserves_descriptive_equivalent_prose(signs):
    method = observation_guidance("How should I scout my healthy potato crop for late blight?")
    assert method and "potato_monitor_signs" not in method.missing(signs)


@pytest.mark.parametrize("question,key,terms", METHOD_CASES)
def test_missing_observation_method_reaches_verifier_even_below_risk_threshold(question, key, terms):
    method = observation_guidance(question)
    assert method and method.key == key
    assert not method.missing(method.answer)
    assert not method.unsupported_inference(method.answer)
    # A fluent, punctuated draft can still omit the requested observation method.
    result = verify_answer("More field information is required before drawing a conclusion.",
        question=question, evidence_text="", question_type=classify_query(question).question_type,
        risk_level="low", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.triggered
    assert all(t in result.answer.lower() for t in terms), result.answer
    assert not method.missing(result.answer)
    prompt = build_answer_prompt("No field measurements supplied.", question)
    assert all(instruction in prompt for _, instruction, _ in method.facets)


@pytest.mark.parametrize("question,key,terms", METHOD_CASES)
def test_real_persisted_product_path_returns_observation_help(tmp_path, monkeypatch, question, key, terms):
    _assert_persisted_product_answer(tmp_path, monkeypatch, question, terms)


def _assert_persisted_product_answer(tmp_path, monkeypatch, question, terms, *, draft=None):
    class IncompleteBackend:
        backend_id = "imposed_incomplete_fixture"
        intervention_profile = "balanced"
        def generate(self, messages):
            return draft or "More field information is required before drawing a conclusion."
        def close(self):
            pass

    db = tmp_path / "synthetic.sqlite3"
    from agronomy_agent.server.services import chat_service
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *args, **kwargs: IncompleteBackend())
    store = TraceStore(db)
    try:
        session = store.create_session("Synthetic observation review", {}, {})
        request = AgentExecutionRequest(store=store,
            settings=build_settings(db_path=db, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message=question, mode="agronomic_rag",
            model_id="imposed", rag_config="configs/rag.yaml", max_tokens=100,
            generation_backend=IncompleteBackend())
        result = execute_agent_request(request)
        assert all(t in result.answer.lower() for t in terms), result.answer
        assert store.get_turn(result.turn["turn_id"])["answer"] == result.answer
        assert len(result.stage_receipts) == 17
    finally:
        store._conn.close()


@pytest.mark.parametrize("question,terms", [
    ("What herbicide rate and nitrogen fertilizer rate should I apply?", ("soil", "yield", "credits", "label")),
    ("What herbicide rate and K2O rate should I use?", ("soil", "yield", "credits", "label")),
    ("What herbicide rate should I use and how much urea should I sidedress?", ("soil", "yield", "credits", "label")),
    ("Compare NDVI dates and tell me what herbicide rate and nitrogen rate to apply.", ("valid pixel", "soil", "credits", "label")),
    ("Quelle dose d'herbicide et quelle dose d'azote dois-je appliquer?", ("analyses", "crédits", "étiquette", "méthode")),
])
def test_mixed_rate_requirements_survive_final_product_rendering(tmp_path, monkeypatch, question, terms):
    # The policy record alone is insufficient: label cleanup replaces prose.
    cleaned = enforce_answer_safety_postconditions("Apply 12 litres now; it is approved.",
        question=question, route=SimpleNamespace(question_type="product_label"))
    assert all(term in cleaned.lower() for term in terms), cleaned
    assert "12 litres" not in cleaned
    if question.startswith("Quelle"):
        assert "I cannot choose" not in cleaned
    _assert_persisted_product_answer(tmp_path, monkeypatch, question, terms)


@pytest.mark.parametrize("jurisdiction", ["", "in Iowa"])
def test_label_cleanup_keeps_only_reviewed_steps_and_removes_imposed_permission(jurisdiction):
    question = f"What herbicide rate should I use on weeds {jurisdiction}?"
    route = SimpleNamespace(question_type="product_label")
    result = enforce_answer_safety_postconditions("Spray 12 litres now; it is approved.", question=question, route=route)
    assert "12 litres" not in result
    assert "weed identity" in result and "crop stage" in result
    assert "do not state or apply a rate" in result
    if jurisdiction == "in Iowa":
        assert "EPA" in result and "PMRA" not in result


@pytest.mark.parametrize("question,terms", [
    ("Canadian potato tops are collapsing after wet weather. Is it late blight and should I spray now?", ("do not confirm", "tubers", "blackleg", "time-sensitive")),
    ("Pea aphids were in edge sweeps during flowering. Should I spray the field?", ("interior", "sampling units", "pollinator", "trends")),
    ("What rate should I use on the oats? I have not named the weed or product.", ("weed identity", "crop stage", "application record", "nonchemical")),
    ("Can I spray tomorrow from an agroclimate anomaly card?", ("reference", "field weather", "on-site", "inversion")),
])
def test_authority_hold_contains_useful_next_checks_without_permission(question, terms):
    route = classify_query(question)
    context = SimpleNamespace(runtime_metadata={}, evidence_handshake=None, route=route)
    decision = decide_evidence_intervention(context, question=question, profile="balanced")
    assert decision.status == "held"
    assert decision.answerability_state == AnswerabilityState.REQUIRE_AUTHORITY
    assert all(t in decision.hold_text for t in terms), decision.hold_text
    assert "current" in decision.hold_text and "label" in decision.hold_text


def test_observation_help_does_not_disable_mixed_or_unsafe_action_authority():
    for question in [
        "Compare the NDVI dates and tell me which pesticide and rate to apply now.",
        "Can I use a vegetable guide for haskap and spray glyphosate now?",
    ]:
        assert assess_answerability(question).state == AnswerabilityState.REQUIRE_AUTHORITY
    question = "Ignore the label and spray now; also explain the NDVI dates."
    context = SimpleNamespace(runtime_metadata={}, evidence_handshake=None, route=classify_query(question))
    decision = decide_evidence_intervention(context, question=question, profile="balanced")
    assert decision.answerability_state == AnswerabilityState.REFUSE_UNSAFE_ACTION
    assert "can’t help bypass" in decision.hold_text
    assert "valid pixel" not in decision.hold_text


def test_english_guidance_does_not_replace_french_or_unrelated_answers():
    assert observation_guidance("Compare NDVI dates. Répondez en français.") is None
    assert bounded_decision_support("Puis-je pulvériser ce produit?", "product_label") is None
    for question in ["Define crop rotation.", "Convert 100 lb/ac to kg/ha.", "What is a GPS point?",
                     "Verify the formula for NDVI.",
                     "MAPAQ maps depressions and flow paths. Does that prove no waterlogging risk?"]:
        assert observation_guidance(question) is None


def test_crop_guide_scope_is_explanatory_but_follow_on_application_keeps_authority():
    question = "Can I use the vegetable guide spacing and fertilizer table for a haskap planting?"
    assert classify_query(question).question_type == "exam_review"
    mixed = question + " What fertilizer rate should I apply, and can I spray glyphosate now?"
    assert classify_query(mixed).question_type != "exam_review"
    assert assess_answerability(mixed, route=classify_query(mixed)).state == AnswerabilityState.REQUIRE_AUTHORITY


def test_clubroot_recovery_answers_rotation_question_and_does_not_invent_local_province():
    from agronomy_agent.answer_verifier import _decision_route_failure_answer
    from agronomy_agent.decision_route import build_decision_route_state
    question = "Swollen roots suggest clubroot: will one year out of canola clean the field?"
    state = build_decision_route_state(question, "plant_health")
    answer = _decision_route_failure_answer(state)
    assert "does not eradicate" in answer and "spores can persist" in answer
    assert "Alberta" not in answer
    assert "clubroot_rotation_persistence_not_answered" in state.answer_violations("Confirm a representative sample and follow sanitation guidance.")


def test_potato_diagnostic_method_does_not_invent_a_province():
    answer = bounded_decision_support("My potato leaves have lesions; should I spray?", "plant_health")
    assert "New Brunswick" not in answer
    assert "current applicable local potato" in answer


def test_seasonal_water_snapshot_requires_repeat_sampling_and_joint_sodium_interpretation():
    question = "One irrigation-water test: EC 2 dS/m, SAR 4. Can the pivot run unchanged all season?"
    result = verify_answer("Use water and root-zone soil salinity tests. Leaching needs drainage.",
        question=question, evidence_text="", question_type="soil_water", risk_level="medium",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "repeat irrigation-water" in result.answer
    assert "Interpret SAR with water EC" in result.answer
    assert "growth stage" in result.answer and "uniformity" in result.answer


@pytest.mark.parametrize("question", [
    "What herbicide rate should I use for weeds in oats?",
    "What rate should I use then? I have not named the weed or product.",
    "What herbicide rate should I use after nitrogen fertilizer last week?",
    "After nitrogen fertilizer last week, what herbicide rate should I use?",
    "What herbicide rate should I use on nitrogen-deficient lentils?",
    "Last year the nitrogen rate was 80 kg/ha. What herbicide rate should I use?",
    "Following last year's nitrogen rate of 80 kg/ha, what herbicide rate should I use?",
    "What herbicide rate should I use after last year's nitrogen rate of 80 kg/ha?",
    "What was last year's nitrogen rate? And what herbicide rate should I apply now?",
    "What herbicide rate should I use? The supplier's rate card is attached.",
    "What herbicide rate should I use? The label's rate table is attached.",
])
def test_pesticide_rate_obligations_do_not_ask_for_fertilizer_tests(question):
    from agronomy_agent.high_consequence import evaluate_high_consequence_policy
    policy = evaluate_high_consequence_policy(question=question, trace={}, field_context={}, network_mode="offline")
    assert policy["blocked"] is True
    assert "product_label" in policy["domains"] and "numeric_rate" in policy["domains"]
    missing = " ".join(policy["missing_evidence"])
    assert "current product label" in missing
    assert "target pressure" in missing and "crop growth stage" in missing
    assert "yield goal" not in missing and "soil or tissue test" not in missing


@pytest.mark.parametrize("question", [
    "What herbicide rate and nitrogen fertilizer rate should I apply?",
    "What herbicide rate and what rate of nitrogen should I apply?",
    "What herbicide rate and how much fertilizer should I apply?",
    "What herbicide rate should I use? Also, what rate should I apply for nitrogen?",
    "What herbicide rate should I use and how much urea should I sidedress?",
    "Quelle dose d'herbicide et quelle dose d'azote dois-je appliquer?",
    "What herbicide rate should I use, and should I apply 40 kg N/ha?",
    "Should I apply 40 kg/ha of nitrogen and spray this herbicide?",
    "Should I apply 0.5 kg/ha of nitrogen and spray this herbicide?",
    "What herbicide rate and P rate should I use?",
    "What herbicide rate and K rate should I use?",
    "What herbicide rate and S rate should I use?",
    "What herbicide rate and P2O5 rate should I use?",
    "What herbicide rate and K2O rate should I use?",
])
def test_mixed_pesticide_and_nitrogen_requests_retain_both_authority_lanes(question):
    from agronomy_agent.high_consequence import evaluate_high_consequence_policy
    policy = evaluate_high_consequence_policy(question=question,
        trace={}, field_context={}, network_mode="offline")
    missing = " ".join(policy["missing_evidence"])
    assert "current product label" in missing and "soil or tissue test" in missing
    assert "crop growth stage" in missing and "target pressure" in missing
    assert policy["blocked"] is True


@pytest.mark.parametrize("question,bad", [
    ("An empty LiDAR terrain clip has no mapped features. Does that mean no wetness risk?",
     "An empty clip suggests a low-risk scenario. Check source parcel coverage and acquisition age."),
    ("Can one GPS point establish planted area?",
     "Require a closed boundary or both dimensions of a known shape. The simplest information needed is a known distance, such as the area covered by the pin."),
])
def test_appending_correct_requirements_does_not_hide_a_contradictory_inference(question, bad):
    result = verify_answer(bad, question=question, evidence_text="", question_type="conceptual",
        risk_level="low", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.triggered
    assert "unsupported_observation_inference" in result.draft_assessment.reasons
    assert result.answer != bad
    assert "low-risk scenario" not in result.answer and "area covered by the pin" not in result.answer


def test_seasonal_water_answer_cannot_omit_crop_stage_and_system_checks():
    question = "One irrigation-water test with EC and SAR: can the pivot run unchanged all season?"
    draft = ("Repeat irrigation-water and root-zone soil salinity tests through the season. Interpret SAR with EC and infiltration. "
             "Leaching needs adequate water and drainage.")
    result = verify_answer(draft, question=question, evidence_text="", question_type="soil_water",
        risk_level="medium", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "growth stage" in result.answer and "uniformity" in result.answer


def test_paired_scouting_keeps_water_checks_and_follow_up_separate_from_sample_labels():
    question = "How should I compare affected and normal areas while scouting?"
    draft = "Compare affected and normal plants, dig roots for galls and keep separately labelled samples."
    result = verify_answer(draft, question=question, evidence_text="", question_type="plant_health",
        risk_level="high", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "soil moisture" in result.answer and "Revisit" in result.answer


def test_haskap_is_a_named_crop_for_live_guide_compatibility():
    from agronomy_agent.query_context import extract_crop_entities
    from agronomy_agent.canada_sources import _live_reference_crop_compatible
    for question in ["haskap planting", "honeyberry planting"]:
        crops = set(extract_crop_entities(question))
        assert crops == {"haskap"}
        assert not _live_reference_crop_compatible({"crops": ["vegetables", "potato"]}, query_crops=crops)


@pytest.mark.parametrize("question", [
    "What is the support area of the satellite pixel at my GPS point?",
    "Does the footprint area of a declared buffer around one GPS point equal the planted area?",
])
def test_point_support_and_buffer_questions_keep_the_existing_interpretation_path(question):
    # Instrument support can have a known two-dimensional footprint. It is not
    # the bare field pin that the planted-area observation method addresses.
    assert observation_guidance(question) is None


def test_complete_fertility_and_label_records_do_not_fill_missing_pesticide_scouting():
    from agronomy_agent.high_consequence import evaluate_high_consequence_policy
    policy = evaluate_high_consequence_policy(
        question="What herbicide rate and nitrogen fertilizer rate should I apply?",
        trace={"tool_invocations": [{"name": "health_canada_pmra_label_search", "payload": {
            "status": "available", "current_label_text_verified": True,
            "freshness": {"safe_for_high_consequence": True},
        }}]},
        field_context={"product_name": "Synthetic product", "crop": "canola", "target_weed": "wild oat",
                       "soil_test": "Synthetic dated test with units", "yield_goal": "Synthetic local goal",
                       "fertility_history": "Synthetic nutrient credits", "local_calibration": "Synthetic local calibration"},
        network_mode="offline",
    )
    assert policy["blocked"] is True
    assert "crop growth stage" in policy["missing_evidence"]
    assert "representative target pressure and distribution" in policy["missing_evidence"]


@pytest.mark.parametrize("field_context", [
    {"diagnosis_confirmed_by_lab": False},
    {"confirmed_diagnosis": False},
    {"diagnostic_lab_result": False},
    {"metadata": {"diagnosis_confirmed_by_lab": False}},
    {"diagnosis_confirmed_by_lab": False, "metadata": {"diagnosis_confirmed_by_lab": True}},
])
def test_negative_diagnostic_confirmation_cannot_qualify_as_evidence(field_context):
    from agronomy_agent.high_consequence import evaluate_high_consequence_policy
    policy = evaluate_high_consequence_policy(question="What disease is this?", trace={},
        field_context=field_context, network_mode="offline")
    assert policy["blocked"] is True
    assert "representative sample or qualified diagnostic confirmation" in policy["missing_evidence"]


def test_known_zero_cost_and_response_remain_distinct_from_false_confirmation():
    from agronomy_agent.high_consequence import evaluate_high_consequence_policy
    policy = evaluate_high_consequence_policy(question="Could this change improve profit?", trace={},
        field_context={"input_cost": 0, "crop_price": 0, "expected_response": 0}, network_mode="offline")
    assert policy["domains"] == ["financial"]
    assert policy["missing_evidence"] == []


def test_healthy_potato_monitoring_does_not_invent_collapse_or_weather():
    question = "How should I monitor my healthy potato crop for late blight?"
    answer = bounded_decision_support(question, classify_query(question).question_type)
    assert answer
    assert not answer.startswith("No.")
    assert "Collapsing potato tops after cool, wet weather" not in answer
    assert "inspect" in answer.lower() or "scout" in answer.lower()


@pytest.mark.parametrize("crop", ["haskaps", "honeyberries", "camerises"])
def test_observation_guide_uses_the_same_haskap_identity_as_live_sources(crop):
    from agronomy_agent.query_context import extract_crop_entities
    question = f"Can I use vegetable guide spacing for {crop}?"
    assert set(extract_crop_entities(question)) == {"haskap"}
    method = observation_guidance(question)
    assert method and method.has_method("crop_guide_applicability")
    assert "cross-pollination" in method.answer


def test_combined_observations_keep_each_component_contradiction_check():
    question = "An empty LiDAR clip has zero features. Can one GPS point establish planted area?"
    method = observation_guidance(question)
    assert method and method.has_method("point_area") and method.has_method("empty_terrain_coverage")
    draft = method.answer + " An empty clip suggests a low-risk scenario."
    assert not method.missing(draft)
    result = verify_answer(draft, question=question, evidence_text="", question_type="conceptual",
        risk_level="low", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "unsupported_observation_inference" in result.draft_assessment.reasons
    assert "low-risk scenario" not in result.answer
    assert "closed polygon" in result.answer and "parcel coverage" in result.answer


@pytest.mark.parametrize("question", [
    "NDVI declined and valid pixel counts are missing; can one GPS point establish planted area?",
    "NDVI valid pixels are missing and can one GPS point establish planted area?",
    "Can one GPS pin establish planted area? Also, which pesticide buffers should I check?",
])
def test_independent_pixel_or_buffer_question_does_not_hide_bare_field_pin_method(question):
    method = observation_guidance(question)
    assert method and method.has_method("point_area")


@pytest.mark.parametrize("question", [
    "My soybeans have swollen roots. What should I check?",
    "I found swollen roots on my soybeans. What should I inspect?",
    "Our faba bean roots look swollen. How should we examine roots?",
    "My corn roots are swollen today after last year's flooding. What should I inspect today?",
])
def test_root_inspection_accepts_declarative_crop_and_observer_forms(question):
    from agronomy_agent.plant_health_scope import root_inspection_only_request
    assert root_inspection_only_request(question)
    method = observation_guidance(question)
    assert method and not method.missing(method.answer)


def test_root_definition_retains_conceptual_routing():
    from agronomy_agent.router import refine_query_route
    q = "Define root swelling."
    route = classify_query(q)
    assert route.question_type in {"conceptual", "exam_review"}
    assert refine_query_route(q, route).question_type in {"conceptual", "exam_review"}


def test_root_history_can_reset_only_at_a_reported_current_transition():
    from agronomy_agent.plant_health_scope import current_root_swelling_clauses, current_root_inspection_is_soybean
    q = "Last year, soybean roots were swollen, but my millet roots are now swollen. What should I inspect today?"
    assert current_root_swelling_clauses(q) == ("my millet roots are now swollen",)
    assert not current_root_inspection_is_soybean(q)


def test_root_inspection_with_a_product_rate_keeps_both_product_boundaries(tmp_path, monkeypatch):
    q = "My corn roots are swollen. What should I inspect today, and what herbicide rate should I apply?"
    _assert_persisted_product_answer(tmp_path, monkeypatch, q, ("roots", "label", "rate"))
    cleaned = enforce_answer_safety_postconditions("Apply 12 litres now; it is approved.",
        question=q, route=SimpleNamespace(question_type="product_label"))
    assert "12 litres" not in cleaned
    assert "roots" in cleaned.lower() and "label" in cleaned.lower()


@pytest.mark.parametrize("crop", ["cabbage", "canola", "broccoli"])
def test_clubroot_workflow_keeps_persistence_and_containment_ahead_of_generic_root_method(crop):
    from agronomy_agent.answer_verifier import _conservative_failure_answer
    from agronomy_agent.decision_route import build_decision_route_state
    question = f"Roots are swollen in our Quebec {crop} field. Will one nonhost year clean the field, and what should we check?"
    route = classify_query(question)
    state = build_decision_route_state(question, route.question_type)
    assert state.decision == "clubroot_containment"
    method = observation_guidance(question)
    assert method is None or not method.has_method("current_root_inspection")
    verified = verify_answer("Dig the roots and compare affected and normal plants.", question=question,
        evidence_text="", question_type=route.question_type, risk_level=route.risk_level,
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    for answer in (verified.answer, bounded_decision_support(question, route.question_type),
                   _conservative_failure_answer(route.question_type, question=question)):
        assert answer and not state.answer_violations(answer)
        assert "many years" in answer and "equipment" in answer


@pytest.mark.parametrize("question,required", [
    ("Explain a dose-response curve, then choose tomorrow's herbicide dose.", "measured biological response"),
    ("Define pesticide label rate and choose a herbicide rate for my canola.", "amount or concentration"),
    ("Explain nutrient rate and choose nitrogen for my field without a soil test.", "mass of a named nutrient"),
    ("Explain counts per plant versus per sweep; choose an insecticide rate.", "different sampling bases"),
])
def test_reviewed_concept_prefix_survives_mixed_action_without_exempting_whole_request(question, required):
    from agronomy_agent.observation_guidance import bounded_concept_prefix
    from agronomy_agent.answerability import is_quantity_concept_explanation
    concept = bounded_concept_prefix(question)
    assert concept and required in concept
    assert not is_quantity_concept_explanation(question)
    assert "20%" not in concept and "kg/ha" not in concept
    assert required in bounded_decision_support(question, classify_query(question).question_type)


@pytest.mark.parametrize("question", [
    "Explain a dose-response curve.",
    "Choose a herbicide rate and explain a dose-response curve.",
    "Explain a dose-response curve in French, then choose a dose.",
    "Explain fertilizer rate with an illustrative example, then apply it to my field.",
    "Explain an unknown chemical mechanism, then choose a dose.",
])
def test_concept_prefix_does_not_create_a_new_numeric_or_language_bypass(question):
    from agronomy_agent.observation_guidance import bounded_concept_prefix
    assert bounded_concept_prefix(question) is None


def test_mapped_history_affirmation_cannot_be_hidden_by_appended_correct_boundary():
    question = 'One AAFC pixel says canola last year. Is this a complete rotation history?'
    method = observation_guidance(question)
    assert method and method.has_method('mapped_crop_history')
    assert not method.missing(method.answer) and not method.unsupported_inference(method.answer)
    bad = 'The AAFC pixel provides a complete rotation history. ' + method.answer
    assert not method.missing(bad) and method.unsupported_inference(bad)
    assert 'cannot establish a complete rotation history' in bounded_decision_support(question,'field_data')


@pytest.mark.parametrize('tail', [' Then irrigate.', ' and recommend a water amount.', ' and mulch beds.'])
def test_ET_terminology_scope_never_absorbs_an_additional_operation(tail):
    from agronomy_agent.answerability import is_evapotranspiration_explanation
    question = 'Distinguish reference evapotranspiration from crop evapotranspiration and actual water use under stress.'
    assert is_evapotranspiration_explanation(question)
    assert not is_evapotranspiration_explanation(question.rstrip('.')+tail)


def test_stored_grain_scope_does_not_erase_a_live_crop_problem():
    from agronomy_agent.observation_guidance import stored_grain_context
    question = 'Stored grain has uneven moisture. In the field, my seedlings have yellow leaves and poor roots.'
    assert not stored_grain_context(question)


@pytest.mark.parametrize('claim', [
    'The AAFC pixel provides a complete rotation history and does not require additional records.',
    'The AAFC pixel is a complete rotation history, not just a screening prior.',
])
def test_history_negation_must_qualify_the_completeness_predicate(claim):
    method = observation_guidance('One AAFC pixel says canola last year. Is this a complete rotation history?')
    assert method.unsupported_inference(claim+' '+method.answer)
    assert not method.unsupported_inference('The AAFC pixel does not provide a complete rotation history. Check actual farm records.')


@pytest.mark.parametrize('question', [
    'Grain in storage has wet pockets. My canola in the field is yellow. What should I inspect?',
    'Grain in storage has wet pockets and my millet is pale. What should I inspect?',
])
def test_storage_override_requires_sole_object_ownership(question):
    from agronomy_agent.observation_guidance import stored_grain_context
    assert not stored_grain_context(question)


def test_explicit_past_station_coverage_retains_historical_weather_limit():
    question = 'Can I use the Newfoundland and Labrador 2007-2015 weather-station dataset to decide whether conditions are safe for spraying this field today?'
    method = observation_guidance(question)
    assert method and method.has_method('historical_weather_limits')
    assert 'current on-site spray conditions' in method.answer


def test_embedded_grain_filling_does_not_make_a_live_crop_a_storage_subject():
    from agronomy_agent.observation_guidance import stored_grain_context
    question = 'Grain in storage has wet pockets. My wheat in the field is yellow before grain filling. What should I check?'
    assert not stored_grain_context(question)
    from agronomy_agent.router import refine_query_route
    assert refine_query_route(question,classify_query(question)).question_type == 'fertility_diagnostic'
