"""Intent, source-meaning and sampling-contrast regressions; no model grades."""
from dataclasses import replace

import pytest

from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.agent import _DIRECT_COMMITMENT_REQUEST_RE, build_answer_prompt
from agronomy_agent.answerability import _DIRECT_RATE_RE
from agronomy_agent.answer_verifier import assess_claim_risk, _conservative_failure_answer
from agronomy_agent.decision_route import build_decision_route_state
from agronomy_agent.evidence_handshake import build_evidence_handshake, evidence_grounded_fallback
from agronomy_agent.high_consequence import classify_high_consequence_domains
from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query
from agronomy_agent.router import classify_query, refine_query_route, evidence_interpretation_kind, operational_request_text


def reference(**kwargs):
    values = dict(doc_id="reviewed-method", title="Reference chapter: analytical methods",
        text="Nitrification and immobilization are different nitrogen transformations.",
        source="Publisher textbook", score=5.0, tags=(), namespaces=("soil_health",),
        source_type="applied_guidance", allowed_roles=("grower",),
        retrieval_policy="context_only", answer_role="reference_context",
        transfer_scope="general_explanation_only",
        applicability_boundary="General mechanism only; no field rate or diagnosis.")
    return RetrievedDoc(**(values | kwargs))


@pytest.mark.parametrize("noun", ["confidence", "certainty", "trust"])
def test_epistemic_amount_is_not_a_rate_at_any_gate(noun):
    q = f"How much {noun} should I place in the hay sample?"
    assert not _DIRECT_RATE_RE.search(q)
    assert not _DIRECT_COMMITMENT_REQUEST_RE.search(q)
    assert "numeric_rate" not in classify_high_consequence_domains(q)
    action = q + " How much nitrogen should I apply?"
    assert _DIRECT_RATE_RE.search(action)
    assert _DIRECT_COMMITMENT_REQUEST_RE.search(action)
    assert "numeric_rate" in classify_high_consequence_domains(action)


def test_measurement_equivalence_does_not_hide_a_second_treatment_request():
    q = "Should I treat wheat height including awns as the same measurement as height without awns?"
    assert evidence_interpretation_kind(q) == "measurement_comparison"
    assert not _DIRECT_COMMITMENT_REQUEST_RE.search(operational_request_text(q))
    mixed = q + " Should I treat the crop with fungicide?"
    assert evidence_interpretation_kind(mixed) is None
    assert _DIRECT_COMMITMENT_REQUEST_RE.search(operational_request_text(mixed))
    assert refine_query_route(mixed, classify_query(mixed)).risk_level == "regulated"


def test_scoped_reference_can_explain_but_cannot_authorize_action():
    q = "What is the difference between nitrification and immobilization?"
    doc = reference()
    handshake = build_evidence_handshake(q, [doc])
    assert handshake.primary_doc_id == doc.doc_id
    assert handshake.has_strong_primary
    assert not handshake.has_field_action_primary
    assert handshake.authority_for(doc.doc_id)[1] == "not_authorized"
    fallback = evidence_grounded_fallback(q, [doc])
    assert doc.text in fallback and doc.applicability_boundary in fallback
    action = build_evidence_handshake("What nitrogen rate should I apply?", [doc])
    assert action.primary_doc_id is None


def test_title_is_not_the_only_possible_evidence_match():
    q = "What is the difference between nitrification and immobilization?"
    doc = reference()
    assert filter_docs_for_query([doc], analyze_query_context(q), primary_intent="exam_review").docs
    noise = replace(doc, text="They have two different examples available.")
    assert not filter_docs_for_query([noise], analyze_query_context(q), primary_intent="exam_review").docs


def test_explicit_short_acronym_survives_title_mismatch():
    doc = reference(text="CEC describes exchange capacity under a specified analytical method.")
    q = "My laboratory reports CEC. What does it mean?"
    assert filter_docs_for_query([doc], analyze_query_context(q), primary_intent="exam_review").docs


def test_sampling_method_scope_is_not_cross_border_action_permission():
    doc = reference(title="Soil sample design", text="Keep diagnostic samples separately identified.",
        jurisdictions=("Ontario",), transfer_scope="general_explanation_or_named_study_only")
    q = "In Alberta, should soil samples from an affected patch be mixed with normal soil to understand the patch?"
    assert evidence_interpretation_kind(q) == "sampling_interpretation"
    assert filter_docs_for_query([doc], analyze_query_context(q), primary_intent="exam_review").docs
    assert not filter_docs_for_query([doc], analyze_query_context(q.replace("Alberta", "Texas")), primary_intent="exam_review").docs
    assert not filter_docs_for_query([doc], analyze_query_context(q), primary_intent="fertility_rate").docs


def test_digestive_physiology_is_not_soil_averaging_or_feed_moisture_basis():
    doc = reference(title="Protein digestion in ruminant animals", text="They have two phases of digestion, including rumen microbial protein.")
    for q in ["I have two soil reports; how do I average them?", "Can I compare silage protein on dry matter and as-fed bases?"]:
        assert not filter_docs_for_query([doc], analyze_query_context(q), primary_intent="exam_review").docs
    dm = replace(doc, title="Animal nutrition: dry matter", text="Dry matter and water content are needed to compare feed analyses.")
    q = "Can I compare silage protein on dry matter and as-fed bases?"
    assert filter_docs_for_query([dm], analyze_query_context(q), primary_intent="exam_review").docs


def test_subsoil_is_not_an_instruction_to_subsoil():
    q = "The subsoil is still wet. Can a grain cart cross the field safely?"
    assert build_decision_route_state(q, "soil_water").decision == "field_trafficability"
    fallback = _conservative_failure_answer("soil_water", question=q)
    assert "below the surface" in fallback and "axle load" in fallback
    assert "northeast" not in fallback and "deep-rip" not in fallback
    assert "flowmeter" not in fallback and "rejected answer" not in fallback
    assert build_decision_route_state("Should I use a subsoiler to relieve compaction?", "soil_water").decision == "compaction_tillage"


@pytest.mark.parametrize("answer", [
    "Mix the affected patch sample with the normal soil. Ask a specialist before acting.",
    "You should consider mixing the affected and normal samples to compare them. I cannot authorize a diagnosis.",
])
def test_disclaimer_does_not_retract_destructive_sampling_instruction(answer):
    q = "Should soil from an affected patch be sampled with normal soil to understand the patch?"
    assessment = assess_claim_risk(answer, question=q, question_type="exam_review")
    assert "diagnostic_sampling_contrast_destroyed" in assessment.reasons


@pytest.mark.parametrize("answer", [
    "Do not mix the affected and normal samples; keep them separate.",
    "Mix cores within each separately identified area, keeping affected and normal samples separate.",
    "Mixing affected with normal soil would obscure the contrast.",
])
def test_preserving_diagnostic_contrast_is_not_flagged(answer):
    q = "Should soil from an affected patch be sampled with normal soil to understand the patch?"
    assessment = assess_claim_risk(answer, question=q, question_type="exam_review")
    assert "diagnostic_sampling_contrast_destroyed" not in assessment.reasons


def test_french_explanation_keeps_language_request_and_is_reviewed():
    q = "Quelle est la différence entre texture et structure du sol?"
    assert refine_query_route(q, classify_query(q)).question_type == "exam_review"
    assert "Répondez en français" in build_answer_prompt("source", q)
    assert "wrong_response_language" in assess_claim_risk("Soil texture describes particle sizes.", question=q).reasons


def test_economic_forecast_is_not_current_weather_authority():
    domains = classify_high_consequence_domains("Is a historical price model a reliable forecast of profit?")
    assert "financial" in domains and "current_weather" not in domains
    domains = classify_high_consequence_domains("What does tomorrow's weather forecast mean for rain and profit?")
    assert "current_weather" in domains and "financial" in domains


def test_sampling_cores_and_resampling_units_keep_interpretation_scope():
    assert evidence_interpretation_kind(
        "Can a laboratory compare the wet and dry zones if soil cores from both are combined?"
    ) == "sampling_interpretation"
    assert evidence_interpretation_kind(
        "Do bootstrap estimates count as independent experimental observations?"
    ) == "study_methods"
    assert evidence_interpretation_kind(
        "Why does dietary protein change during digestion in a cow?"
    ) == "concept_explanation"
    assert evidence_interpretation_kind(
        "Why does dietary protein change, and what ration should I feed?"
    ) is None


def test_past_tense_traffic_is_still_an_operational_question():
    q = "Does a grain cart crossing become safe because a tractor crossed yesterday?"
    assert evidence_interpretation_kind(q) is None
    assert refine_query_route(q, classify_query(q)).question_type == "soil_water"


def test_measurement_focus_preserves_literal_basis_without_answer_injection():
    from agronomy_agent.router import explanation_focus_query
    q = "Can I compare silage protein on dry matter and as-fed bases?"
    focus = explanation_focus_query(q)
    assert "dry matter" in focus and "as-fed" in focus
    assert all(term in q.lower() for term in focus.split())


def test_feed_interpretation_excludes_soil_sampling_distractors():
    q = "How much confidence can I place in a hay sample for the lot?"
    soil = reference(title="Soil analysis and sampling", text="Sample soil for representative soil nutrient concentration.")
    feed = reference(doc_id="feed-method", title="Hay feed analysis and sampling", text="Sample hay feed to represent the lot and preserve sample integrity.")
    result = filter_docs_for_query([soil, feed], analyze_query_context(q), primary_intent="exam_review")
    assert soil not in result.docs and feed in result.docs


def test_copied_control_heading_is_removed_without_rewriting_supported_prose():
    from agronomy_agent.answer_verifier import verify_answer
    class NoEditor:
        def generate(self, *args, **kwargs):
            raise AssertionError("An isolated control heading needs no model rewrite")
    answer = "Water content measures water amount. Water potential is an energy quantity; they are not the same measurement."
    header = "- Decision: Are these the same measurement?\n- Preserve: the measurement basis.\n- Primary decision evidence: [source_water_method].\n- Evidence roles: interpretive."
    result = verify_answer(header + "\n\n" + answer,
        question="Are water content and water potential the same measurement?",
        evidence_text=answer, question_type="exam_review", risk_level="low",
        editor=NoEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer
    assert result.localized_cleanup and not result.rewrite_accepted and not result.fallback_applied
    record = result.as_record()
    assert record["intervention_action"] == "localized_cleanup"
    assert record["claim_edit_ledger"]["replacement_kind"] == "localized_cleanup"
    assert record["claim_edit_ledger"]["all_changed_claims_have_localized_trigger"]


def test_localized_cleanup_cannot_hide_an_unsafe_remaining_instruction():
    from agronomy_agent.answer_verifier import verify_answer
    class RejectingEditor:
        def generate(self, *args, **kwargs):
            return "I cannot authorize a product or rate without the current label."
    draft = "- Preserve: crop.\n- Primary decision evidence: none.\n\nYou can legally spray any insecticide at 12 L/ha without checking the label."
    result = verify_answer(draft, question="Which insecticide and rate can I spray?",
        evidence_text="No label is provided.", question_type="product_label", risk_level="regulated",
        editor=RejectingEditor(), review_mode="risk_conditioned_selective_v3")
    assert not result.localized_cleanup
    assert "12 L/ha" not in result.answer


@pytest.mark.parametrize('answer', [
    'If the soil cores are in one bag, the lab can still determine differences between the areas.',
    'The lab may distinguish the affected and healthy zones after mixing.',
])
def test_pooled_cores_cannot_recover_area_contrast(answer):
    from agronomy_agent.answer_verifier import verify_answer
    q = 'Can a lab compare affected and normal areas if soil cores are combined in one bag?'
    assert 'diagnostic_sampling_contrast_destroyed' in assess_claim_risk(answer, question=q).reasons
    class NoEditor:
        def generate(self, *args, **kwargs):
            raise AssertionError('Explicit loss of area identity has a bounded correction')
    result = verify_answer(answer, question=q, evidence_text='', question_type='exam_review',
        risk_level='low', editor=NoEditor(), review_mode='risk_conditioned_selective_v3')
    assert result.fallback_applied
    assert 'cannot recover' in result.answer
    assert 'separately identified' in result.answer


def test_sampling_guard_allows_separate_area_recoverability():
    q = 'Can a lab compare affected and normal areas if soil cores are combined in one bag?'
    good = 'The lab can compare the areas only with separately identified samples. Do not pool the areas.'
    assert 'diagnostic_sampling_contrast_destroyed' not in assess_claim_risk(good, question=q).reasons


def test_traffic_load_comparison_reaches_actual_decision_contract():
    q = 'Can a loaded grain cart cross because a pickup crossed the field without ruts?'
    assert build_decision_route_state(q, 'soil_water').decision == 'field_trafficability'
    assert 'axle load' in _conservative_failure_answer('soil_water', question=q)


@pytest.mark.parametrize('q', [
    'Can compaction change particle arrangement without changing mineral fractions?',
    'Does all protein entering a cow intestine remain dietary protein?',
    'Are water content and water potential the same measurement?',
])
def test_nonoperational_mechanism_questions_keep_explanation_scope(q):
    assert evidence_interpretation_kind(q)
    assert evidence_interpretation_kind(q + ' Give me a herbicide product and rate.') is None


def test_mixed_explanation_product_rate_is_direct_commitment():
    q = 'Explain grain moisture, then give me a herbicide product and rate.'
    assert _DIRECT_COMMITMENT_REQUEST_RE.search(q)
    assert _DIRECT_RATE_RE.search(q)



def test_generic_guide_title_cannot_hide_soil_methods_in_feed_analysis():
    q = "How much confidence can I place in a hay sample for the lot?"
    soil = reference(title="Agriculture guide page 71", text="Soil analysis requires samples representing the plow layer depth.")
    feed = reference(doc_id="feed-method", title="Agriculture guide page 72", text="Confidence in a hay sample depends on representative feed material from the lot.")
    result = filter_docs_for_query([soil, feed], analyze_query_context(q), primary_intent="exam_review")
    assert soil not in result.docs and feed in result.docs
    mixed = replace(feed, text="Confidence in a hay sample depends on the feed lot; soil contamination should be avoided.")
    assert filter_docs_for_query([mixed], analyze_query_context(q), primary_intent="exam_review").docs



@pytest.mark.parametrize('answer', [
    "If you put soil cores from both the saline-looking patch and the healthy stand into one bag, the lab will be able to determine the differences, but the interpretation will depend on the thoroughness of your sampling and the specific analytical methods used.",
    "If you put soil cores from both the saline-looking patch and the healthy patch into one bag, the laboratory may still be able to determine differences, but this depends on the nature of the contamination.",
])
def test_complete_generated_pooling_claims_are_blocked(answer):
    from agronomy_agent.answer_verifier import verify_answer
    q = "I want to compare the poor stand on a saline-looking patch with the healthy stand beside it. If I put soil cores from both areas into one bag, can the lab still tell me how the patch differs?"
    class NoEditor:
        def generate(self, *args, **kwargs):
            raise AssertionError("The pooling claim must receive the bounded correction")
    result = verify_answer(answer, question=q, evidence_text="", question_type="exam_review", risk_level="low",
        editor=NoEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.fallback_applied and "cannot recover" in result.answer



def test_conceptual_tillage_mechanism_does_not_gain_tillage_decision_requirements():
    q = "Can tillage or compaction change how soil particles are arranged without changing the percentages of sand, silt and clay?"
    assert build_decision_route_state(q, "exam_review").decision == "exam_review"
    answer = "Yes. Tillage or compaction can change soil structure and pore arrangement while mineral particle-size fractions remain unchanged."
    assert "missing_decision_content" not in assess_claim_risk(answer, question=q, question_type="exam_review").reasons
    assert build_decision_route_state("Should I use a subsoiler to relieve compaction?", "soil_water").decision == "compaction_tillage"


def test_within_area_pooling_keeps_valid_between_area_comparison():
    question = "Can I compare affected and normal soil areas if I combine cores within each area and keep samples separate?"
    answer = "Yes. The lab can compare the areas."
    assert "diagnostic_sampling_contrast_destroyed" not in assess_claim_risk(answer, question=question).reasons
    unsafe = "Combine all cores from both areas into one bag."
    assert "diagnostic_sampling_contrast_destroyed" in assess_claim_risk(unsafe, question=question).reasons


@pytest.mark.parametrize("action", ["till this wet field", "subsoil this field", "drive across this field"])
def test_concept_comparison_does_not_erase_operational_clause(action):
    from agronomy_agent.router import classify_query, refine_query_route
    question = "Explain the difference between soil structure and texture; should I " + action + "?"
    assert evidence_interpretation_kind(question) is None
    route = refine_query_route(question, classify_query(question))
    assert route.question_type != "exam_review"
    from agronomy_agent.decision_contract import build_decision_contract
    assert "field_data_guard" in build_decision_contract(question, route).required_tools
