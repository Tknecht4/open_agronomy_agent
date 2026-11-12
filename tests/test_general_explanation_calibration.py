import pytest

from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.answer_verifier import verify_answer
from agronomy_agent.answerability import simple_definition_subject, is_rate_basis_explanation, assess_answerability
from agronomy_agent.decision_route import build_decision_route_state
from agronomy_agent.evidence_handshake import build_evidence_handshake, filter_decision_distractors


class UnavailableEditor:
    def generate(self, messages):
        raise RuntimeError("Imposed unavailable editor")


def doc(key, title, text, *, kind="applied_guidance"):
    return RetrievedDoc(doc_id=key, title=title, text=text, source="Synthetic source",
        score=1.0, tags=(), namespaces=("crop_management",), source_type=kind, allowed_roles=("grower",),
        retrieval_policy="context_only")


def test_context_only_policy_does_not_make_unrelated_definition_sources_relevant():
    rotation = doc("rotation", "Crop rotation", "A planned sequence of crops in the same field over time.")
    variety = doc("variety", "Variety selection", "Check maturity, standability, drydown and seed quality.")
    nitrogen = doc("nitrogen", "Nitrogen after rain", "Assess applied nitrogen and soil texture before a rescue rate.")
    kept, dropped = filter_decision_distractors("Explain crop rotation.", (variety, nitrogen, rotation))
    assert [d.doc_id for d in kept] == ["rotation"]
    assert {d["doc_id"] for d in dropped} == {"variety", "nitrogen"}
    # Relevance never upgrades context-only material into action authority.
    assert not build_evidence_handshake("Explain crop rotation.", kept).has_strong_primary


def test_definition_in_broad_reference_is_kept_but_incidental_keyword_is_not():
    reference = doc("reference", "Agronomy manual", "Soil texture refers to the proportions of sand, silt and clay.")
    incidental = doc("incidental", "Corn nutrition", "Check soil texture and drainage before nitrogen application.")
    kept, _ = filter_decision_distractors("What does soil texture mean?", (incidental, reference))
    assert [d.doc_id for d in kept] == ["reference"]


@pytest.mark.parametrize("question,subject", [("Explain crop rotations.", "crop rotation"), ("Define soil textures.", "soil texture")])
def test_named_plural_definition_keeps_relevant_context(question, subject):
    assert simple_definition_subject(question) == subject
    reference = doc("reference", subject.title(), "A general definition.")
    kept, _ = filter_decision_distractors(question, (reference,))
    assert kept == (reference,)


def test_new_control_headings_are_detected_as_prompt_leaks():
    from agronomy_agent.leak_guard import detect_prompt_leaks
    for text in ("Decision evidence requirements: not observations", "Explanation task: give a bounded explanation"):
        assert detect_prompt_leaks(text)


def test_variety_evidence_method_does_not_admit_unrelated_farm_ontology():
    question = "A soybean variety topped one trial. What evidence should we compare before selecting it across regions?"
    farm = doc("farm", "Soil health concept: sewage farms", "sewage farms", kind="ontology")
    trials = doc("trials", "Variety comparison methods", "Compare replicated trials across years and locations, uncertainty and maturity fit.")
    kept, _ = filter_decision_distractors(question, (farm, trials))
    assert [d.doc_id for d in kept] == ["trials"]


def test_decision_requirements_are_not_presented_as_supplied_observations():
    block = build_decision_route_state("Which soybean variety should I select from one trial?", "crop_management").prompt_block()
    assert "requirements" in block.lower() and "not observations" in block.lower()
    definition = build_decision_route_state("Define soil texture.", "conceptual").prompt_block()
    assert "next field action" not in definition
    assert "general explanation" in definition.lower()


def test_no_primary_handshake_allows_bounded_explanation_before_long_source_ids():
    h = build_evidence_handshake("Explain crop rotation.", ())
    text = h.prompt_block()[:650].lower()
    assert "bounded general explanation" in text
    assert "hold unsupported factual commitments" not in text
    assert "field" in text


@pytest.mark.parametrize("question", [
    "What is the herbicide rate I should apply?",
    "Define crop rotation and tell me which pesticide to spray.",
    "What does soil texture mean? Should I install drainage now?",
])
def test_definition_projection_does_not_hide_follow_on_actions(question):
    assert simple_definition_subject(question) is None


def test_definition_guard_keeps_an_explicit_texture_structure_distinction():
    answer = "Soil texture is about particle proportions, not their physical arrangement. Sand, silt and clay fractions define texture; their arrangement into aggregates describes soil structure. Both can affect water movement, so texture alone is not a drainage diagnosis."
    result = verify_answer(answer, question="Define soil texture.", evidence_text="", question_type="conceptual",
        risk_level="low", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer and not result.fallback_applied


def test_texture_not_only_arrangement_is_still_a_conflation():
    result = verify_answer("Soil texture is not just the arrangement of particles but also the relative proportions of sand, silt and clay. It affects water movement and nutrient retention.",
        question="Define soil texture.", evidence_text="", question_type="conceptual", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "texture_structure_conflation" in result.draft_assessment.reasons


def test_rotation_definition_can_explicitly_contrast_variety_selection():
    answer = "Crop rotation is the planned sequence of crops in the same field across seasons. It differs from variety selection using standability, drydown and lodging: rotation concerns the crop sequence and its effects on soil cover, nutrient cycling and host-specific pest cycles. The appropriate sequence depends on local conditions and crop biology."
    result = verify_answer(answer, question="Explain crop rotation.", evidence_text="", question_type="conceptual", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "definition_topic_drift" not in result.draft_assessment.reasons
    assert result.answer == answer and not result.fallback_applied


@pytest.mark.parametrize("question,answer", [
    ("What does soil texture mean?", "Soil texture describes the relative proportions of sand, silt and clay mineral particles. It influences water storage and nutrient retention. Soil structure describes how particles are arranged into aggregates; texture alone does not establish a field's drainage or condition."),
    ("Explain crop rotation.", "Crop rotation is the planned sequence of crops grown in the same field across seasons. It can help manage crop-specific pests, nutrient cycling, soil cover and water use. Benefits depend on the crop sequence, organism biology and local conditions; rotation does not eradicate every persistent disease."),
])
def test_adequate_general_model_answer_is_retained_without_field_data(question, answer):
    result = verify_answer(answer, question=question, evidence_text="", question_type="conceptual",
        risk_level="low", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer
    assert not result.fallback_applied


def test_texture_arrangement_conflation_is_corrected_without_refusing_definition():
    result = verify_answer("Soil texture is the physical arrangement and proportions of sand, silt and clay particles. These determine how soil behaves.",
        question="What does soil texture mean?", evidence_text="", question_type="conceptual", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "texture_structure_conflation" in result.draft_assessment.reasons
    assert "proportions" in result.answer and "structure" in result.answer.lower()
    assert "do not have enough" not in result.answer


def test_variety_checklist_drift_is_corrected_in_rotation_definition():
    bad = "Crop rotation changes the crop sequence. Choose it from relative maturity, standability, drydown, lodging risk and seed quality."
    result = verify_answer(bad, question="Explain crop rotation.", evidence_text="", question_type="conceptual",
        risk_level="low", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "definition_topic_drift" in result.draft_assessment.reasons
    assert "drydown" not in result.answer and "sequence" in result.answer
    assert "do not have enough" not in result.answer


@pytest.mark.parametrize("message,answer", [
    ("My soil sample was collected 2026-05-12, analyzed on 2026-05-18 and the lab report was issued 2026-05-19. How should I store these dates?",
     "Store these dates distinctly. The sample collection date is May 12, 2026. The analysis date is May 18, 2026. The report issuance date is May 19, 2026. Keep each event linked to the sample and original report."),
    ("Explain crop rotation.", "Crop rotation is the planned sequence of crops grown in the same field over time. Different crops can change soil cover, rooting and nutrient demand, and interrupt host-specific pest cycles. The useful sequence depends on climate, soil, market and pest biology; a rotation does not eliminate every persistent pathogen."),
    ("In general, what is a pesticide label rate and how is it different from a fertilizer nutrient rate? I am not asking which product or dose to use.", "A pesticide label rate is the product amount or concentration specified for the labelled use, with crop, target, method and restrictions. A fertilizer nutrient rate expresses the mass of a named nutrient per area; product concentration converts that nutrient amount to fertilizer product mass. These bases are different. This explanation does not choose a pesticide dose or a field nutrient target."),
    ("Explain how representative aphid scouting and matching threshold units help decide whether more sampling is needed. Do not choose a pesticide.", "Use representative samples from the field interior and compare affected and normal areas; an edge hotspot alone may not represent the field. Record crop and pest stage, aphid counts, damage, beneficial insects and the sampling method. Compare observations with current local guidance using the same counting basis and threshold units. If the sample is sparse, variable or not comparable, take additional representative samples rather than inferring field-wide pressure or a spray decision."),
    ("The soil sample was collected May 12 and the lab report was issued May 19. Which sampling date should I compare across seasons?", "Use May 12, the collection date, for sampling-date comparisons. Preserve May 19 as the report issuance date in a separate field linked to the sample and original report. The laboratory processing date is not established by issuance; retain it separately if supplied. Keep sampling depth, timing and analytical method comparable across seasons."),
    ("The soil sample was collected May 12 and the lab report was issued May 19. Which sampling date should I compare across seasons?", "Use May 12 as the collection date. Preserve May 19 as the report issuance date in a separate field. The processing date cannot be inferred from issuance."),
])
def test_correct_definition_survives_the_persisted_product_path(tmp_path, monkeypatch, message, answer):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore

    class Backend:
        backend_id = "imposed_correct_definition"
        intervention_profile = "balanced"
        calls = []

        def generate(self, messages):
            self.calls.append(messages)
            return answer

        def close(self):
            pass

    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: backend)
    database = tmp_path / "synthetic.sqlite3"
    store = TraceStore(database)
    try:
        session = store.create_session("Synthetic definition", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=database, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message=message, mode="agronomic_rag",
            model_id="imposed", rag_config="configs/rag.yaml", max_tokens=150, generation_backend=backend))
        assert result.answer == answer
        assert store.get_turn(result.turn["turn_id"])["answer"] == answer
        assert len(result.stage_receipts) == 17
        assert len(backend.calls) == 1
        prompt = "\n".join(x["content"] for x in backend.calls[0])
        assert "standability, drydown" not in prompt
        if message == "Explain crop rotation.":
            assert "the next field action" not in prompt
    finally:
        store._conn.close()


@pytest.mark.parametrize("question", [
    "What is a pesticide label rate?",
    "Define a nutrient rate.",
    "Explain the difference between product rate and nutrient rate.",
    "How do pesticide label rates and fertilizer nutrient rates differ?",
    "Explain product rate versus nutrient rate using a clearly hypothetical example. Do not choose a real field target or pesticide.",
    "Compare product rates with nutrient rates using an illustrative fertilizer example.",
    "Could you explain product rate vs. nutrient rate with a made-up example? Don't select any pesticide or product.",
])
def test_rate_basis_terminology_does_not_require_field_authority(question):
    from agronomy_agent.high_consequence import classify_high_consequence_domains, fertility_quantity_requested
    from agronomy_agent.router import classify_query, refine_query_route
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    assert is_rate_basis_explanation(question)
    route = refine_query_route(question, classify_query(question))
    assert route.question_type == "exam_review" and route.risk_level == "low"
    assert assess_answerability(question, route=route).state.value == "answer_directly"
    assert classify_high_consequence_domains(question) == []
    assert not fertility_quantity_requested(question)
    assert enforce_answer_safety_postconditions("A supported explanation.", question=question, route=route) == "A supported explanation."


@pytest.mark.parametrize("question", [
    "What is a pesticide label rate for glyphosate?",
    "What is a pesticide label rate for my field?",
    "Define a pesticide label rate. What herbicide rate should I spray tomorrow?",
    "Explain the difference between product rate and nutrient rate and choose a herbicide dose.",
    "In general, what is a pesticide label rate? I am not asking which product or dose to use. Also recommend a dose for canola.",
    "Explain a pesticide label rate; use 2 L/ha on my field?",
    "Compare product rate with nutrient rate using a hypothetical example. Do not choose a pesticide and recommend a dose for my field.",
    "Explain product rate versus nutrient rate using a hypothetical example. Do not choose a pesticide. Apply 2 L/ha today?",
    "Explain product rate versus nutrient rate for my field using a hypothetical example.",
])
def test_terminology_does_not_exempt_named_or_follow_on_action_requests(question):
    from agronomy_agent.high_consequence import classify_high_consequence_domains
    from agronomy_agent.router import classify_query, refine_query_route
    assert not is_rate_basis_explanation(question)
    route = refine_query_route(question, classify_query(question))
    assert assess_answerability(question, route=route).state.value != "answer_directly"
    assert "product_label" in classify_high_consequence_domains(question)


def test_terminology_question_still_rejects_an_invented_numeric_dose():
    result = verify_answer("Apply glyphosate at 2 L/ha today to control weeds in canola.",
        question="What is a pesticide label rate?", evidence_text="", question_type="exam_review",
        risk_level="low", editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.fallback_applied
    assert "2 L/ha" not in result.answer


@pytest.mark.parametrize("instruction", [
    "Apply glyphosate at 2 L/ha today and record the application.",
    "You can apply glyphosate at 2 L/ha today.",
    "Use glyphosate at 2 L/ha to convert the field.",
    "Apply 100 mg/ha today.",
    "Apply .5 L/ha today.",
    "Apply 2% solution today.",
    "**Apply 2 L/ha today.**",
    "1) Apply 2 L/ha today.",
    "1. Apply 2 L/ha today.",
    "Apply **2 L/ha** today.",
])
def test_historical_quantity_does_not_authorize_an_unasked_application(instruction):
    from types import SimpleNamespace
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    question = "What is a pesticide label rate?"
    explanation = "A pesticide label rate describes the amount or concentration specified for the labelled use and formulation. A fertilizer nutrient rate expresses the mass of a named nutrient per area, so product analysis converts nutrient mass to product mass. The unit bases differ and the exact label still controls product use."
    draft = explanation + " " + instruction
    evidence = "Field history reports a previous glyphosate application at 2 L/ha, not current label authority."
    result = verify_answer(draft, question=question, evidence_text=evidence, question_type="exam_review", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == explanation
    assert "unasked_application_instruction" in result.draft_assessment.reasons
    assert result.localized_cleanup is not None
    assert enforce_answer_safety_postconditions(draft, question=question, route=SimpleNamespace(question_type="exam_review")) == explanation


def test_safe_rate_explanation_keeps_a_marked_label_example_and_conversion():
    from types import SimpleNamespace
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    question = "Explain the difference between product rate and nutrient rate."
    answer = "For example, a hypothetical label could say 'apply 2 L/ha'; that is a product-volume basis, not a nutrient target. Use 0.46 to convert a supplied 40 kg N/ha into product mass. This illustrates the bases and does not choose a field rate."
    assert enforce_answer_safety_postconditions(answer, question=question, route=SimpleNamespace(question_type="exam_review")) == answer


def test_requested_fictional_rate_example_survives_the_verifier_without_field_authority():
    question = "Explain product rate versus nutrient rate using a hypothetical example. Do not choose a real field target or pesticide."
    answer = ("Product rate is the mass of commercial product per area. Nutrient rate is the mass of a named nutrient per area.\n\n"
        "Suppose a fictional product contains 12% N. A product rate of 25 kg/ha gives a nutrient rate of 3 kg N/ha. "
        "These invented numbers are an illustration, not a field recommendation.")
    result = verify_answer(answer, question=question, evidence_text="", question_type="exam_review", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer
    assert not result.final_assessment.reasons


@pytest.mark.parametrize("nutrient,accepted", [("3 kg N/ha", True), ("4 kg N/ha", False),
                                             ("3 kg N/acre", False)])
def test_fictional_example_is_checked_through_persisted_product_path(tmp_path, monkeypatch, nutrient, accepted):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    question = "Explain product rate versus nutrient rate using a hypothetical example. Do not choose a real field target or pesticide."
    answer = ("Product rate expresses commercial product mass per area; nutrient rate expresses a named nutrient mass per area.\n\n"
              f"Suppose a fictional product contains 12% N. A product rate of 25 kg/ha gives a nutrient rate of {nutrient}. "
              "These invented numbers are an illustration, not a field recommendation.")
    class Backend:
        backend_id = "synthetic_illustration_contract"
        intervention_profile = "balanced"
        def generate(self, messages):
            return answer
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: backend)
    database = tmp_path / "synthetic.sqlite3"
    store = TraceStore(database)
    try:
        session = store.create_session("Synthetic rate illustration", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=database, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message=question, mode="agronomic_rag",
            model_id="imposed", rag_config="configs/rag.yaml", max_tokens=150, generation_backend=backend))
        assert (result.answer == answer) is accepted
        assert store.get_turn(result.turn["turn_id"])["answer"] == result.answer
        assert len(result.stage_receipts) == 17
        if not accepted:
            assert nutrient not in result.answer
    finally:
        store._conn.close()


@pytest.mark.parametrize("instruction", ["Apply glyphosate at 2 L/ha today.", "**Apply .5 L/ha today.**", "Apply 100 mg/ha today.", "Apply 2% solution today."])
def test_persisted_terminology_answer_cannot_authorize_a_historical_rate(tmp_path, monkeypatch, instruction):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    explanation = "A pesticide label rate describes the product amount or concentration for the labelled use and formulation. Read its stated unit basis and restrictions; this general explanation does not choose an application rate."
    class Backend:
        backend_id = "imposed_history_scope_error"
        intervention_profile = "balanced"
        calls = 0
        def generate(self, messages):
            self.calls += 1
            return explanation + " " + instruction
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: backend)
    database = tmp_path / "history.sqlite3"
    store = TraceStore(database)
    try:
        session = store.create_session("Synthetic history", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=database, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message="What is a pesticide label rate?", mode="agronomic_rag",
            session_context={"field_context":{"application_history":"Past application records mention 2 L/ha, .5 L/ha, 100 mg/ha and a 2% solution; no current label is verified."}},
            model_id="imposed", rag_config="configs/rag.yaml", max_tokens=150, generation_backend=backend))
        assert result.answer == explanation
        assert store.get_turn(result.turn["turn_id"])["answer"] == explanation
        assert len(result.stage_receipts) == 17 and backend.calls == 1
    finally:
        store._conn.close()


def test_rate_basis_recovery_explains_input_mass_rather_than_crop_concentration():
    question = "Explain the difference between a pesticide label rate and a fertilizer nutrient rate."
    draft = "Pesticide label rates are controlled by the label and determine the amount used for the crop and pest. Fertilizer nutrient rates refer to the desired level of a nutrient in the crop, which is a reference for calculation. Both depend on the purpose and conditions of the operation."
    result = verify_answer(draft, question=question, evidence_text="", question_type="exam_review", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "nutrient_rate_basis" in result.draft_assessment.missing_intent_facets
    assert "mass" in result.answer and "per area" in result.answer
    assert "not a nutrient concentration measured" in result.answer


def test_below_threshold_cannot_alone_discharge_sampling_adequacy():
    from agronomy_agent.observation_guidance import observation_guidance
    question = "Explain aphid scouting and matching threshold units before deciding whether more sampling is needed."
    method = observation_guidance(question)
    assert method.has_method("scouting_unit_interpretation")
    assert method.unsupported_inference("Counts below the threshold suggest further sampling is not required.")
    assert not method.unsupported_inference("Being below the threshold does not mean that further scouting is unnecessary; continue monitoring under the appropriate sampling protocol.")


def test_entirely_unasked_numeric_instruction_recovers_a_definition():
    from types import SimpleNamespace
    from agronomy_agent.answer_safety import enforce_answer_safety_postconditions
    answer = enforce_answer_safety_postconditions("Apply 2 L/ha today.", question="What is a pesticide label rate?", route=SimpleNamespace(question_type="exam_review"))
    assert answer and "product amount" in answer and "2 L/ha" not in answer


def test_clubroot_recovery_does_not_invent_a_province():
    from agronomy_agent.answer_verifier import bounded_decision_support
    answer = bounded_decision_support("My canola roots are swollen. Is that enough to confirm clubroot?", "plant_health")
    assert "current applicable local" in answer
    assert "provincial" not in answer
    assert "provincial" not in build_decision_route_state("My canola roots are swollen. Is that enough to confirm clubroot?", "plant_health").prompt_block()


def test_declined_product_selection_does_not_create_a_sampling_authority_requirement():
    from agronomy_agent.high_consequence import classify_high_consequence_domains
    from agronomy_agent.router import classify_query, refine_query_route
    question = "Explain representative aphid scouting. Do not choose a pesticide."
    assert classify_high_consequence_domains(question) == []
    assert refine_query_route(question, classify_query(question)).risk_level != "regulated"


@pytest.mark.parametrize("suffix", [
    " Tell me which herbicide I should spray tomorrow.",
    " Give me a dose.",
    " Use 2 L/ha?",
    " But recommend a product for canola.",
])
def test_declined_selection_cannot_hide_another_product_request(suffix):
    from agronomy_agent.high_consequence import classify_high_consequence_domains
    from agronomy_agent.router import classify_query, refine_query_route
    question = "Do not choose a pesticide." + suffix
    assert "product_label" in classify_high_consequence_domains(question)
    route = refine_query_route(question, classify_query(question))
    assert assess_answerability(question, route=route).state.value != "answer_directly"


@pytest.mark.parametrize("directive", [
    " Should I spray an insecticide tomorrow?",
    " Tell me which pesticide I should use.",
    " Give me a dose for my field.",
])
def test_threshold_unit_explanation_cannot_hide_a_follow_on_treatment(directive):
    from agronomy_agent.high_consequence import classify_high_consequence_domains
    from agronomy_agent.router import classify_query, refine_query_route
    question = "Explain matching scouting counts to threshold units. Do not choose a pesticide." + directive
    route = refine_query_route(question, classify_query(question))
    assert assess_answerability(question, route=route).state.value != "answer_directly"
    assert "product_label" in classify_high_consequence_domains(question)


def test_dose_request_backstop_does_not_promote_dose_response_terminology_to_action():
    from agronomy_agent.high_consequence import classify_high_consequence_domains
    assert classify_high_consequence_domains("Explain a pesticide dose-response curve in general.") == []
    assert "product_label" in classify_high_consequence_domains("Do not choose a pesticide. Give me a dose.")
    assert "product_label" in classify_high_consequence_domains("Explain a pesticide dose-response curve. What dose should I apply?")


def test_suspected_clubroot_word_order_keeps_confirmation_and_containment():
    question = "My canola roots are swollen beside the field gate. Is that enough to confirm clubroot?"
    assert build_decision_route_state(question, "plant_health").decision == "clubroot_containment"
    result = verify_answer("Symptoms alone cannot confirm a diagnosis. Arrange a representative diagnostic sample.",
        question=question, evidence_text="", question_type="plant_health", risk_level="medium",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.fallback_applied
    assert "soil movement" in result.answer and "sanitation" in result.answer
    assert "not confirmation" in result.answer


@pytest.mark.parametrize("crop", ["soybean", "corn", "carrot", "potato"])
def test_root_swelling_alone_does_not_create_a_clubroot_concern_for_other_crops(crop):
    question = f"My {crop} roots are swollen. What should I inspect today?"
    assert build_decision_route_state(question, "plant_health").decision != "clubroot_containment"


@pytest.mark.parametrize("crop", ["canola", "cabbage", "broccoli", "mustard"])
def test_susceptible_crop_root_swelling_retains_clubroot_confirmation_and_containment(crop):
    question = f"My {crop} roots are swollen. What should I do today?"
    assert build_decision_route_state(question, "plant_health").decision == "clubroot_containment"


def test_explicit_clubroot_soil_concern_is_preserved_in_a_rotation_crop():
    question = "Corn is planted this year. Clubroot was confirmed in the previous canola crop. What soil-movement precautions should I take today?"
    assert build_decision_route_state(question, "plant_health").decision == "clubroot_containment"


def test_unknown_crop_root_swelling_does_not_assume_a_susceptible_host():
    assert build_decision_route_state("The roots are swollen. What should I inspect today?", "plant_health").decision != "clubroot_containment"


def test_soybean_swelling_does_not_inject_clubroot_into_the_persisted_product_prompt(tmp_path, monkeypatch):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    class Backend:
        backend_id = "imposed_root_observation"
        intervention_profile = "balanced"
        calls = []
        def generate(self, messages):
            self.calls.append(messages)
            return "Root swelling alone does not identify a cause. Compare affected and normal soybean plants, inspect intact roots for nodules, galls or injury, record crop stage and field distribution, and arrange representative diagnostic samples if the cause is uncertain."
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: backend)
    database = tmp_path / "soybean.sqlite3"
    store = TraceStore(database)
    try:
        session = store.create_session("Synthetic root observations", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=database, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message="My soybean roots are swollen. What should I inspect today?",
            mode="agronomic_rag", model_id="imposed", rag_config="configs/rag.yaml", max_tokens=150,
            generation_backend=backend))
        assert "clubroot_containment" not in "\n".join(m["content"] for call in backend.calls for m in call)
        assert "suspected clubroot" not in result.answer.lower()
        assert store.get_turn(result.turn["turn_id"])["answer"] == result.answer
        assert len(result.stage_receipts) == 17
    finally:
        store._conn.close()


def test_stratified_sampling_recovery_requires_a_useful_zone_method():
    question = "An adviser wants one composite soil sample for an Alberta barley field with eroded knolls, wet depressions and an old manure strip. Is one average good enough for the nutrient plan?"
    result = verify_answer("One sample may not be enough. These are contrasting management zones. Provide soil tests and nutrient requirements before I can evaluate whether an average is adequate.",
        question=question, evidence_text="", question_type="field_data", risk_level="medium",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.fallback_applied
    assert "zone_samples" in result.draft_assessment.missing_intent_facets
    assert "each zone" in result.answer and "sampling depth" in result.answer
    assert "laboratory method" in result.answer


@pytest.mark.parametrize("answer", [
    "No. Collect representative soil samples from each zone separately; do not mix the eroded knolls, wet depressions and manure strip. Keep sampling depth, timing, handling and laboratory method consistent. Interpret each zone using its history, crop needs, method and current local calibration before setting a nutrient rate.",
    "No. Keep the eroded knolls, wet depressions and old manure strip as separate sampling zones and collect representative samples within each zone. A whole-field average could conceal differences among those areas; interpret each zone's results against its own management history.",
])
def test_adequate_stratified_sampling_model_method_is_preserved(answer):
    question = "Should one composite sample combine eroded knolls, wet depressions and an old manure strip for a barley nutrient plan?"
    result = verify_answer(answer, question=question, evidence_text="", question_type="field_data", risk_level="medium",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer and not result.fallback_applied


def test_sampling_date_prompt_preserves_collection_and_report_event_roles():
    question = "The soil sample was collected May 12 and the lab report was issued May 19. Which sampling date should I compare across seasons?"
    state = build_decision_route_state(question, "field_data")
    assert any("issuance alone does not establish" in x.lower() for x in state.constraints)


def test_report_issuance_is_not_relabelled_as_sample_processing():
    question = "The soil sample was collected May 12 and the lab report was issued May 19. Which sampling date should I compare across seasons?"
    result = verify_answer("Use May 12 as the sampling date. Preserve May 19 as the date the laboratory processed or reported on that sample.",
        question=question, evidence_text="", question_type="field_data", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "sample_event_role_conflation" in result.draft_assessment.reasons
    assert "issuance" in result.answer and "separate" in result.answer
    assert "processed or reported" not in result.answer


def test_correct_sample_date_roles_are_preserved():
    question = "The soil sample was collected May 12 and the lab report was issued May 19. Which sampling date should I compare across seasons?"
    answer = "Use May 12, the collection date, for sampling-date comparisons. Preserve May 19 as the report issuance date in a separate field linked to the sample and original report. The laboratory processing date is not established by issuance; retain it separately if supplied. Keep sampling depth, timing and analytical method comparable across seasons."
    result = verify_answer(answer, question=question, evidence_text="", question_type="field_data", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer and not result.fallback_applied


@pytest.mark.parametrize("ending", [
    "The processing date is unavailable.",
    "The processing date cannot be inferred from issuance.",
    "The analysis date is unknown.",
    "The analysis date cannot be inferred from the report issuance date.",
    "If supplied, keep the processing date separately.",
])
def test_sample_date_unknowns_do_not_trigger_unnecessary_replacement(ending):
    question = "The soil sample was collected May 12 and the lab report was issued May 19. Which sampling date should I compare across seasons?"
    answer = "Use May 12 as the collection date. Preserve May 19 as the report issuance date in a separate field. " + ending
    result = verify_answer(answer, question=question, evidence_text="", question_type="field_data", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer and not result.triggered


@pytest.mark.parametrize("ending", [
    "The report issuance date is the analysis date.",
    "Use the report issuance date as the analysis date.",
    "The analysis date is May 19.",
])
def test_sample_analysis_role_cannot_be_inferred_from_report_issuance(ending):
    question = "The soil sample was collected May 12 and the lab report was issued May 19. Which sampling date should I compare across seasons? Can I infer the analysis date?"
    draft = "Use May 12 as the collection date. Preserve May 19 as the report issuance date in a separate field. " + ending
    result = verify_answer(draft, question=question, evidence_text="", question_type="field_data", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert "sample_event_role_conflation" in result.draft_assessment.reasons
    assert ending not in result.answer and result.fallback_applied


@pytest.mark.parametrize("analysis_date", ["May 18", "18 May", "18th May", "2026-05-18", "18/05/2026"])
def test_explicitly_supplied_analysis_event_is_not_treated_as_inferred(analysis_date):
    question = f"The soil sample was collected May 12 and the lab report was issued May 19. The analysis date was {analysis_date}. Which sampling date should I compare across seasons?"
    answer = f"Use May 12 as the collection date. Preserve May 19 as the report issuance date in a separate field. The analysis date is {analysis_date}, a separately supplied event."
    result = verify_answer(answer, question=question, evidence_text="", question_type="field_data", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer and not result.triggered


def test_date_method_composes_with_an_independent_area_request():
    from agronomy_agent.observation_guidance import observation_guidance
    question = "The soil sample was collected May 12 and the lab report was issued May 19. Which date belongs to the sampling event? Also, can one GPS pin establish planted area?"
    method = observation_guidance(question)
    assert method.has_method("sample_record_dates") and method.has_method("point_area")
    assert "collection date" in method.answer and "closed polygon" in method.answer


def test_date_method_does_not_remove_a_product_authority_request():
    from agronomy_agent.router import classify_query, refine_query_route
    question = "The soil sample was collected May 12 and the lab report was issued May 19. Which date should I preserve? Which herbicide rate should I spray today?"
    route = refine_query_route(question, classify_query(question))
    assert assess_answerability(question, route=route).state.value == "require_authority"


def test_yield_stability_does_not_replace_statistical_separation_in_variety_comparison():
    from agronomy_agent.answer_verifier import assess_claim_risk
    question = "One soybean variety topped a trial. What evidence should we compare before choosing it across Canadian regions?"
    answer = "Compare replicated multi-year and multi-location trials for yield stability. Match maturity, disease, lodging and adaptation to each region. Compare seed cost and downside risk and retain an on-farm comparison where uncertainty remains. The winner in one environment does not automatically establish the best cultivar for every farm."
    assessment = assess_claim_risk(answer, question=question, evidence_text="", question_type="crop_management", risk_level="medium")
    assert "variety_statistics" in assessment.missing_intent_facets
    adequate = answer + " Check reported statistical separation or uncertainty before treating a small yield-rank difference as real."
    assert "variety_statistics" not in assess_claim_risk(adequate, question=question, evidence_text="", question_type="crop_management", risk_level="medium").missing_intent_facets


def test_regional_pest_alert_requires_field_measurement_even_on_low_risk_route():
    question = "A regional alert mentions insects near my Canadian corn field. Is my field over threshold, or what must be counted first?"
    draft = "The regional alert does not mean your field is over threshold. Find the specific pest identity and life stage in the alert; without the identity it is impossible to determine what population count is required."
    class IncompleteEditor:
        def generate(self, messages):
            return draft
    result = verify_answer(draft, question=question, evidence_text="", question_type="plant_health", risk_level="low",
        editor=IncompleteEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer != draft
    assert "representative" in result.answer and "count" in result.answer
    assert "current local" in result.answer and "threshold" in result.answer


def test_regional_pest_alert_keeps_complete_model_method():
    question = "A regional insect alert covers my field pin. Does that prove infestation or what counts should I collect?"
    draft = "A regional alert does not establish field density. Identify the pest and active life stage, scout representative interior locations and count population density or injury with the crop and pest's sampling method. Compare the field measurements with a current local economic threshold using the same units and crop stage; record population trend and natural enemies. Check the current product label only if treatment is justified."
    result = verify_answer(draft, question=question, evidence_text="", question_type="plant_health", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == draft and not result.fallback_applied


@pytest.mark.parametrize("question,draft,required", [
    ("A regional insect alert covers my field pin. Does that prove infestation or what counts should I collect?",
     "A regional alert cannot prove that your field is over threshold. First identify the pest and active life stage. Without the identity I cannot determine what count is required.",
     ("representative field counts", "current local", "threshold")),
    ("How should I monitor my healthy potato crop for late blight?",
     "Inspect potato leaves and stems for spots and lesions. Note crop stage and weather; I cannot diagnose without field observations.",
     ("local disease alerts", "regularly", "undersides")),
    ("The soil sample was collected May 12 and the lab report was issued May 19. Which sampling date should I compare across seasons? Can I infer the analysis date?",
     "Use May 12 as the collection date. Preserve May 19 as the report issuance date in a separate field. The report issuance date is the analysis date.",
     ("actual sample collection date", "do not infer it")),
])
def test_persisted_observation_method_completes_failed_draft(tmp_path, monkeypatch, question, draft, required):
    from agronomy_agent.execution_core import AgentExecutionRequest
    from agronomy_agent.server.services import chat_service
    from agronomy_agent.server.settings import build_settings
    from agronomy_agent.server.storage.db import TraceStore
    class Backend:
        backend_id = "imposed_incomplete_alert"
        intervention_profile = "balanced"
        def generate(self, messages):
            return draft
        def close(self):
            pass
    backend = Backend()
    monkeypatch.setattr(chat_service, "_build_mlx_generator", lambda *a, **k: backend)
    database = tmp_path / "alert.sqlite3"
    store = TraceStore(database)
    try:
        session = store.create_session("Synthetic alert", {}, {})
        result = chat_service.execute_agent_request(AgentExecutionRequest(store=store,
            settings=build_settings(db_path=database, artifact_root=tmp_path / "artifacts", network_mode="offline"),
            session_id=session["session_id"], message=question, mode="agronomic_rag",
            model_id="imposed", rag_config="configs/rag.yaml", max_tokens=150, generation_backend=backend))
        assert all(term in result.answer for term in required)
        assert store.get_turn(result.turn["turn_id"])["answer"] == result.answer
        assert len(result.stage_receipts) == 17
    finally:
        store._conn.close()


def test_short_correct_date_roles_with_separately_are_preserved():
    question = "My soil sample was collected May 12 and its report issued May 19. Which sampling date should I compare across seasons and how do I keep the other date?"
    answer = "The soil sample collection date should be May 12. Preserve the lab report issuance date of May 19 separately, because it represents a different event."
    result = verify_answer(answer, question=question, evidence_text="", question_type="field_data", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer and not result.fallback_applied


def test_single_trial_method_does_not_invent_a_stable_alternative_or_dry_site():
    from agronomy_agent.answer_verifier import _decision_route_failure_answer
    question = "One soybean variety topped one trial. What evidence should we compare before choosing it across Canadian regions?"
    state = build_decision_route_state(question, "crop_management")
    assert state.decision == "variety_trial_selection"
    answer = _decision_route_failure_answer(state)
    assert answer
    assert "stable variety" not in answer and "dry site-year" not in answer
    assert "retain both" not in answer
    assert "statistical separation" in answer and "multi-year" in answer


def test_healthy_potato_monitoring_requires_local_alert_checks():
    question = "How should I scout my healthy potato crop for late blight?"
    draft = "Monitor the potato foliage and stems for spots, lesions and necrosis. Note the field pattern, crop stage and recent leaf wetness. I cannot offer a diagnosis without field observations."
    result = verify_answer(draft, question=question, evidence_text="", question_type="plant_health", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer != draft
    assert "local disease alerts" in result.answer
    assert "regularly" in result.answer and "undersides" in result.answer
    assert "Collapsing" not in result.answer


def test_complete_healthy_potato_monitoring_prose_is_retained():
    question = "How should I scout my healthy potato crop for late blight?"
    answer = "Scout representative potato areas regularly and inspect leaves, undersides and stems for new or spreading lesions. Monitor crop stage, weather and local disease alerts or IPM guidance. If suspect symptoms appear, contact the diagnostic lab for confirmation; this is monitoring advice, not a field diagnosis or permission to spray."
    result = verify_answer(answer, question=question, evidence_text="", question_type="plant_health", risk_level="low",
        editor=UnavailableEditor(), review_mode="risk_conditioned_selective_v3")
    assert result.answer == answer and not result.fallback_applied


def test_diagnostic_healthy_comparator_does_not_select_healthy_crop_monitoring():
    from agronomy_agent.observation_guidance import observation_guidance
    method = observation_guidance("Potato foliage has lesions. Compare affected and nearby healthy plants for late blight.")
    assert method is None or not method.has_method("healthy_potato_monitoring")
