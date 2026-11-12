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
    ("Explain crop rotation.", "Crop rotation is the planned sequence of crops grown in the same field over time. Different crops can change soil cover, rooting and nutrient demand, and interrupt host-specific pest cycles. The useful sequence depends on climate, soil, market and pest biology; a rotation does not eliminate every persistent pathogen."),
    ("In general, what is a pesticide label rate and how is it different from a fertilizer nutrient rate? I am not asking which product or dose to use.", "A pesticide label rate is the product amount or concentration specified for the labelled use, with crop, target, method and restrictions. A fertilizer nutrient rate expresses the mass of a named nutrient per area; product concentration converts that nutrient amount to fertilizer product mass. These bases are different. This explanation does not choose a pesticide dose or a field nutrient target."),
    ("Explain how representative aphid scouting and matching threshold units help decide whether more sampling is needed. Do not choose a pesticide.", "Use representative samples from the field interior and compare affected and normal areas; an edge hotspot alone may not represent the field. Record crop and pest stage, aphid counts, damage, beneficial insects and the sampling method. Compare observations with current local guidance using the same counting basis and threshold units. If the sample is sparse, variable or not comparable, take additional representative samples rather than inferring field-wide pressure or a spray decision."),
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
