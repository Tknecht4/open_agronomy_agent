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
    class IncompleteBackend:
        backend_id = "imposed_incomplete_fixture"
        intervention_profile = "balanced"
        def generate(self, messages):
            return "More field information is required before drawing a conclusion."
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
    assert "current applicable provincial potato" in answer


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
])
def test_mixed_pesticide_and_nitrogen_requests_retain_both_authority_lanes(question):
    from agronomy_agent.high_consequence import evaluate_high_consequence_policy
    policy = evaluate_high_consequence_policy(question=question,
        trace={}, field_context={}, network_mode="offline")
    missing = " ".join(policy["missing_evidence"])
    assert "current product label" in missing and "soil or tissue test" in missing
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
