from dataclasses import replace

from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.context_packer import ContextPacker, _doc_policy_note
from agronomy_agent.server.services.chat_service import _build_doc_snapshot


def _doc() -> RetrievedDoc:
    return RetrievedDoc(
        doc_id="source-scope-fixture", title="Soil test interpretation",
        text="Area-weighted values require comparable measurements.",
        source="https://example.test/source", score=1.0, tags=(),
        namespaces=("fertility",), source_type="applied_guidance",
        allowed_roles=("grower",), retrieval_policy="context_only",
        transfer_scope="general_explanation_only",
        applicability_boundary="Requires the same analyte, extractant, units and sampling depth.",
    )


def test_applicability_survives_document_slot_and_trace_without_promoting_authority():
    doc = _doc()
    sections = []
    ContextPacker({"max_context_tokens_default": 1200})._append_doc_slot(
        sections, "primary_applied_evidence", [doc],
        source_type_budget="applied_guidance",
        budget_report={"slot_limits": {}, "dropped_doc_ids": []},
        evidence_roles={},
    )
    assert len(sections) == 1
    assert doc.applicability_boundary in sections[0].text
    assert doc.text in sections[0].text
    assert "FIELD ACTION: NOT AUTHORIZED" in sections[0].text
    snapshot = _build_doc_snapshot(1, doc, store_text=False)
    assert snapshot["applicability_boundary"] == doc.applicability_boundary
    assert snapshot["transfer_scope"] == doc.transfer_scope
    assert snapshot["retrieval_policy"] == "context_only"
    assert snapshot["snippet"] == ""


def test_missing_or_long_applicability_keeps_existing_policy_and_bounded_context():
    assert "SOURCE APPLICABILITY" not in _doc_policy_note(replace(_doc(), applicability_boundary=""))
    note = _doc_policy_note(replace(_doc(), applicability_boundary="scope " * 1000))
    assert "scope " * 900 in note
    assert "FIELD ACTION: NOT AUTHORIZED" in note


def test_oversized_scope_drops_claim_instead_of_truncating_conditions():
    doc = replace(_doc(), applicability_boundary="A necessary qualification. " * 200)
    sections = []
    report = {"slot_limits": {}, "dropped_doc_ids": []}
    ContextPacker({"max_context_tokens_default": 300})._append_doc_slot(
        sections, "primary_applied_evidence", [doc],
        source_type_budget="applied_guidance", budget_report=report, evidence_roles={},
    )
    assert not sections
    assert report["scope_budget_dropped_doc_ids"] == [doc.doc_id]
    assert report["selected_by_source_type"]["applied_guidance"] == 0


def test_context_only_authority_does_not_mean_irrelevant_to_selection():
    from types import SimpleNamespace
    from agronomy_agent.context_packer import _prioritize_evidence_roles
    relevant = _doc()
    others = [replace(relevant, doc_id=f"other-{i}", retrieval_policy="standard", score=0.1)
              for i in range(4)]
    handshake = SimpleNamespace(primary_doc_id=None,
        evidence_roles=[(relevant.doc_id, "boundary", "context_only_not_decisive")])
    ranked = _prioritize_evidence_roles([relevant, *others], handshake)
    assert ranked[0] == relevant
    # Ordering does not promote authority or change the document.
    assert ranked[0].retrieval_policy == "context_only"


def test_public_evidence_card_keeps_applicability_after_answer_normalization():
    from agronomy_agent.server.services.answer_renderer import render_structured_answer
    doc = _build_doc_snapshot(1, _doc(), store_text=False)
    result = render_structured_answer("Compare compatible soil-test results.",
        question="How should soil-test results be compared?",
        trace={"retrieved_docs": [doc], "metadata": {"packed_doc_ids": [_doc().doc_id]}})
    card = result.evidence[0]
    assert card["applicability_boundary"] == _doc().applicability_boundary
    assert _doc().applicability_boundary in card["known_limitations"]
    assert card["retrieval_policy"] == "context_only"
    assert any(_doc().applicability_boundary in caveat for caveat in result.caveats)


def test_named_study_reference_gate_preserves_country_and_action_boundaries():
    from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query
    doc = replace(_doc(), title="Independent field trials and simulated returns", text="Independent field trials and simulated returns have different replication. Study design determines independence.", namespaces=("crop_management",),
        jurisdictions=("saskatchewan",), answer_role="reference_context", applicability_boundary="Named study design only; no transfer of modeled returns to a new farm.",
        transfer_scope="general_explanation_or_named_study_only")
    question = "In Canada, do simulated returns count as independent field trials?"
    fit = lambda d, q, intent: filter_docs_for_query([d], analyze_query_context(q), primary_intent=intent)
    assert fit(doc, question, "exam_review").docs == (doc,)
    assert not fit(doc, question.replace("Canada", "United States"), "exam_review").docs
    assert not fit(doc, question, "field_data").docs
    assert not fit(replace(doc, applicability_boundary=""), question, "exam_review").docs
    assert not fit(doc, "What nitrogen rate should I apply in Canada based on simulated returns?", "fertility_rate").docs


def test_study_contract_does_not_require_field_diagnosis_but_retains_declared_tools():
    from agronomy_agent.router import classify_query, refine_query_route
    from agronomy_agent.decision_contract import build_decision_contract
    q = "Do simulated returns count as independent field trials?"
    route = refine_query_route(q, classify_query(q))
    contract = build_decision_contract(q, route)
    assert not {"field_observation", "diagnostic_evidence"}.intersection(o.key for o in contract.evidence_obligations)
    guarded = replace(route, required_tools=("field_data_guard",))
    contract = build_decision_contract(q, guarded)
    assert "field_data_guard" in contract.required_tools


def test_grounded_fallback_keeps_full_primary_source_scope():
    from agronomy_agent.evidence_handshake import evidence_grounded_fallback
    doc = replace(_doc(), title="Interpreting a soil slake test",
        text="A slake test is a qualitative indicator of aggregate stability. Compare intact air-dry aggregates in water and record how rapidly they break apart. It does not diagnose sodicity by itself.",
        tags=("slake test", "aggregate stability", "air dry aggregates", "break apart"),
        retrieval_policy="standard")
    answer = evidence_grounded_fallback("What does a soil slake test show and how should I run it?", (doc,), preserve_entities=("slake test",))
    assert answer and doc.applicability_boundary in answer


def test_measurement_ontology_requires_subject_overlap_beyond_unit_grammar():
    from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query
    ontology = replace(_doc(), source_type="ontology", namespaces=("crop_management",),
        title="Sealed area per capita", text="Sealed area per capita", tags=(),
        applicability_boundary="", transfer_scope="")
    q = "What must I check before comparing wheat grain yield per plot with yield at 15 percent moisture per hectare?"
    result = filter_docs_for_query([ontology], analyze_query_context(q), primary_intent="exam_review")
    assert result.dropped[0]["reason"] == "measurement_subject_mismatch"
    relevant = replace(ontology, title="Wheat grain yield", text="Grain yield per plot")
    assert filter_docs_for_query([relevant], analyze_query_context(q), primary_intent="exam_review").docs
    # A source is still eligible when its actual subject is what is compared.
    q = "Can I compare sealed area per capita in different units?"
    assert filter_docs_for_query([ontology], analyze_query_context(q), primary_intent="exam_review").docs


def test_reviewed_reference_is_complete_or_explicitly_dropped():
    doc = replace(_doc(), answer_role="reference_context",
        text="First establish a compatible measurement. " * 12 + "Divide the weighted total by the total represented area.")
    sections = []
    report = {"slot_limits": {}, "dropped_doc_ids": []}
    other = replace(doc, doc_id="second-reference")
    ContextPacker({"max_context_tokens_default": 420})._append_doc_slot(
        sections, "primary_applied_evidence", [doc, other],
        source_type_budget="applied_guidance", budget_report=report, evidence_roles={})
    assert doc.text in sections[0].text
    assert sections[0].source_ids == (doc.doc_id,)
    assert report["complete_passage_budget_dropped_doc_ids"] == [other.doc_id]
    assert "FIELD ACTION: NOT AUTHORIZED" in sections[0].text
    assert report["selected_by_source_type"]["applied_guidance"] == 1
