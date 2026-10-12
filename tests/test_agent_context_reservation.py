from __future__ import annotations

from dataclasses import replace

import pytest

from agronomy_agent.agent import (
    _format_no_primary_context,
    _non_decisive_evidence_hold,
    _reserve_named_crop_health_specification,
    build_context,
)
from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.canada_sources import apply_soileri_coverage_disclosure, build_soileri_source_coverage
from agronomy_agent.query_context import SOILERI_SOURCE_ID, analyze_query_context, filter_docs_for_query
from agronomy_agent.runtime_profiles import DEFAULT_RAG_CONFIG


def _doc(doc_id: str, *, source_id: str = "other") -> RetrievedDoc:
    return RetrievedDoc(
        doc_id=doc_id,
        title=doc_id,
        text="Context",
        source="Public source",
        score=1.0,
        tags=(),
        namespaces=("regional_environment",),
        source_type="regional_environment_profile",
        allowed_roles=("grower", "adviser"),
        source_id=source_id,
        retrieval_policy="context_only",
    )


SOILERI_QUESTION = "Does the AAFC Soil Erosion Risk 2021 map class establish the erosion happening in my field?"


def _regional_fixture(source_id: str, text: str) -> RetrievedDoc:
    return replace(_doc(source_id, source_id=source_id), text=text, jurisdictions=("Canada",), crops=("all",))


@pytest.mark.parametrize("source_id", ["ca_aafc_crop_health_indices_specification", "ca_aafc_crop_health_indices_specification_fr"])
def test_soileri_does_not_substitute_crop_health_specification(source_id):
    product = _regional_fixture(source_id, "Crop Health Indices are national regional soil moisture and climate context.")
    result = filter_docs_for_query([product], analyze_query_context(SOILERI_QUESTION, {"country": "Canada"}))
    assert not result.docs
    assert result.dropped == ({"doc_id": source_id, "reason": "named_regional_product_mismatch"},)
    coverage = build_soileri_source_coverage(SOILERI_QUESTION, result.docs, source_indexed=False)
    assert coverage["status"] == "not_indexed" and not coverage["retrieved_doc_ids"]


@pytest.mark.parametrize("text", ["Erosion can leave rills and displaced sediment; inspect field evidence.",
                                 "Wind-erodible sandy soils require field assessment; keep general screening separate from field observations."])
def test_soileri_keeps_general_erosion_context_and_reserves_matching_source(text):
    general = _regional_fixture("general-erosion-context", text)
    product = _regional_fixture(SOILERI_SOURCE_ID, "Synthetic named-source fixture: documented regional model, not a field observation.")
    result = filter_docs_for_query([general, product], analyze_query_context(SOILERI_QUESTION, {"country": "Canada"}))
    assert list(result.docs) == [general, product]
    reserved = _reserve_named_crop_health_specification(SOILERI_QUESTION, list(result.docs), [general], limit=2)
    assert reserved == [product, general]
    coverage = build_soileri_source_coverage(SOILERI_QUESTION, reserved, source_indexed=True)
    assert coverage["status"] == "retrieved"
    assert coverage["retrieved_doc_ids"] == [product.doc_id]
    assert coverage["general_context_doc_ids"] == [general.doc_id]
    assert not coverage["prompt_block"]
    assert apply_soileri_coverage_disclosure("Qualified explanation.", question=SOILERI_QUESTION, coverage=coverage) == "Qualified explanation."


@pytest.mark.parametrize("indexed,status", [(False, "not_indexed"), (True, "not_retrieved")])
def test_missing_soileri_coverage_preserves_general_answer_and_is_idempotent(indexed, status):
    general = _regional_fixture("general-erosion-context", "General erosion context: inspect rills and sediment.")
    coverage = build_soileri_source_coverage(SOILERI_QUESTION, [general], source_indexed=indexed)
    assert coverage["status"] == status and coverage["general_context_doc_ids"] == [general.doc_id]
    text = "Inspect rills and sediment as field observations; a regional map alone is not a field measurement."
    disclosed = apply_soileri_coverage_disclosure(text, question=SOILERI_QUESTION, coverage=coverage)
    assert disclosed.startswith(text)
    assert "cannot verify its class thresholds or trend definitions" in disclosed
    assert "General erosion context is separate" in disclosed
    assert apply_soileri_coverage_disclosure(disclosed, question=SOILERI_QUESTION, coverage=coverage) == disclosed


def test_current_product_soileri_gap_excludes_wrong_source_without_refusal():
    from agronomy_agent.server.services.answer_renderer import render_structured_answer
    context = build_context(SOILERI_QUESTION, rag_config=DEFAULT_RAG_CONFIG, field_context={"country": "Canada", "region_text": "Canada"},
                            use_context_cache=False, use_search_cache=False)
    coverage = context.runtime_metadata["named_regional_product_coverage"]
    assert coverage["status"] == "not_indexed" and coverage["source_id"] == SOILERI_SOURCE_ID
    assert context.retrieved_docs and coverage["general_context_doc_ids"]
    assert all("crop_health_indices_specification" not in doc.source_id for doc in context.retrieved_docs)
    assert any(row["reason"] == "named_regional_product_mismatch" and "crop_health_indices_specification" in row["doc_id"]
               for row in context.runtime_metadata["evidence_selection_trace"]["candidate_dispositions"])
    assert coverage["prompt_block"] in context.packed_context.text
    assert "general erosion context" in context.packed_context.text
    assert coverage["prompt_block"] in _format_no_primary_context(context)
    assert _non_decisive_evidence_hold(context, question=SOILERI_QUESTION) is None
    answer = "Inspect rills and sediment as field observations; the regional map alone cannot establish current field erosion."
    rendered = render_structured_answer(answer, question=SOILERI_QUESTION,
        trace={"metadata": {"answer_policy_profile": "general_agronomy", "agno_runtime": context.runtime_metadata}})
    assert "Inspect rills and sediment" in rendered.answer
    assert "reviewed SoilERI specification is unavailable" in rendered.answer
    assert "cannot verify its class thresholds or trend definitions" in rendered.answer


def test_ordinary_crop_health_query_retrieval_and_answer_are_unchanged():
    question = "Are AAFC crop health grids station-driven regional estimates or field measurements?"
    context = build_context(question, rag_config=DEFAULT_RAG_CONFIG, use_context_cache=False, use_search_cache=False)
    assert context.retrieved_docs[0].source_id == "ca_aafc_crop_health_indices_specification"
    assert context.runtime_metadata["named_regional_product_doc_ids"]
    assert "named_regional_product_coverage" not in context.runtime_metadata
    assert build_soileri_source_coverage(question, context.retrieved_docs, source_indexed=True) is None
    assert apply_soileri_coverage_disclosure("Qualified crop-health explanation.", question=question, coverage=None) == "Qualified crop-health explanation."


def test_combined_manitoba_and_soileri_coverage_preserves_both_complete_boundaries():
    context = build_context(SOILERI_QUESTION, rag_config=DEFAULT_RAG_CONFIG,
                            field_context={"country": "Canada", "province_state": "Manitoba", "region_text": "Manitoba"},
                            use_context_cache=False, use_search_cache=False)
    sections = [s for s in context.packed_context.sections if s.slot == "canadian_jurisdiction_evidence_boundary"]
    assert len(sections) == 1 and sections[0].token_estimate <= 190
    text = sections[0].text
    for essential in ("Manitoba", "current province-specific guidance", "other provinces", "current calibration",
                      "legal requirements", "provincial authority", "PMRA labels", "SoilERI specification is unavailable",
                      "class thresholds", "trend definitions", "user-reported", "qualified explanations", "do not infer field truth."):
        assert essential in text
    assert context.runtime_metadata["canadian_coverage_boundaries"][0]["prompt_block"]
    assert context.runtime_metadata["named_regional_product_coverage"]["prompt_block"] in text


def test_named_crop_health_specification_survives_final_context_cutoff() -> None:
    selected = [_doc("applied-1"), _doc("applied-2")]
    product = _doc(
        "crop-health-spec",
        source_id="ca_aafc_crop_health_indices_specification",
    )

    reserved = _reserve_named_crop_health_specification(
        "Use the AAFC growth-stage raster as regional context.",
        [*selected, product],
        selected,
        limit=2,
    )

    assert [doc.doc_id for doc in reserved] == ["crop-health-spec", "applied-1"]


def test_crop_stage_alias_reserves_the_crop_health_specification() -> None:
    selected = [_doc("applied-1"), _doc("applied-2")]
    product = _doc("crop-health-spec", source_id="ca_aafc_crop_health_indices_specification")

    reserved = _reserve_named_crop_health_specification(
        "The regional crop-stage raster says 3 for small grains and soybean.",
        [*selected, product],
        selected,
        limit=2,
    )

    assert [doc.doc_id for doc in reserved] == ["crop-health-spec", "applied-1"]


def test_crop_stage_alias_retrieves_the_named_specification_from_the_real_corpus() -> None:
    context = build_context(
        "The regional crop-stage raster says 3. What does that number mean for small grains versus soybean, and what field check is still needed?",
        rag_config=DEFAULT_RAG_CONFIG,
        field_context={"crop_current": "wheat", "province_state": "Manitoba"},
        use_context_cache=False,
        use_search_cache=False,
    )

    assert any(
        doc.source_id == "ca_aafc_crop_health_indices_specification"
        for doc in context.retrieved_docs
    )
    assert context.runtime_metadata["named_regional_product_doc_ids"]
    assert context.runtime_metadata["evidence_handshake"]["primary_doc_id"].startswith(
        "ca_aafc_crop_health_indices_specification"
    )
    trace = context.runtime_metadata["evidence_selection_trace"]
    assert trace["candidate_doc_ids"]
    assert trace["selected_doc_ids"]
    assert trace["admission_receipts"]
    assert all("reason" in row for row in trace["candidate_dispositions"])
    assert all("reason" in row for row in trace["admission_receipts"])


def test_crop_health_grid_alias_retrieves_lineage_semantics() -> None:
    context = build_context(
        "Are the five-kilometre AAFC crop health grids remotely sensed field measurements, or station-driven VSMB regional estimates?",
        rag_config=DEFAULT_RAG_CONFIG,
        use_context_cache=False,
        use_search_cache=False,
    )

    assert context.retrieved_docs[0].source_id == "ca_aafc_crop_health_indices_specification"
    assert "station" in context.retrieved_docs[0].text.lower()
    assert context.runtime_metadata["evidence_handshake"]["primary_doc_id"].startswith(
        "ca_aafc_crop_health_indices_specification"
    )


def test_unrequested_product_specification_is_not_forced_into_context() -> None:
    selected = [_doc("applied-1"), _doc("applied-2")]
    product = _doc(
        "crop-health-spec",
        source_id="ca_aafc_crop_health_indices_specification",
    )

    reserved = _reserve_named_crop_health_specification(
        "What should I scout in this wheat field?",
        [*selected, product],
        selected,
        limit=2,
    )

    assert reserved == selected


def test_named_saskatchewan_soil_specification_survives_final_context_cutoff() -> None:
    selected = [_doc("applied-1"), _doc("applied-2")]
    product = _doc(
        "soil-spec",
        source_id="ca_aafc_sk_detailed_soil_survey_specification",
    )

    reserved = _reserve_named_crop_health_specification(
        "What does the Saskatchewan Detailed Soil Survey polygon establish?",
        [*selected, product],
        selected,
        limit=2,
    )

    assert [doc.doc_id for doc in reserved] == ["soil-spec", "applied-1"]


def test_explicit_nrcs_analogue_keeps_its_boundary_in_packed_context() -> None:
    context = build_context(
        "For a Saskatchewan field, can NRCS MLRA 001X ecological-site material be used as a cross-border analogue for soil water and ecological dynamics?",
        rag_config=DEFAULT_RAG_CONFIG,
        use_context_cache=False,
        use_search_cache=False,
    )

    assert any(doc.transfer_scope == "US_analogue_context_only" for doc in context.retrieved_docs)
    assert context.packed_context is not None
    assert "US CROSS-BORDER ANALOGUE" in context.packed_context.text
    assert "never treat as Canadian field truth" in context.packed_context.text


def test_unpadded_mlra_reaches_the_same_source_bound_product_context() -> None:
    contexts = [
        build_context(
            f"Summarize NRCS MLRA {code} ecological site climate as historical regional context.",
            rag_config=DEFAULT_RAG_CONFIG,
            use_context_cache=False,
            use_search_cache=False,
        )
        for code in ("63B", "063B")
    ]
    source_docs = [
        [doc for doc in context.retrieved_docs if doc.source_id == "nrcs_edit_ecological_site_description_json"]
        for context in contexts
    ]
    assert source_docs[0]
    assert {doc.doc_id for doc in source_docs[0]} == {doc.doc_id for doc in source_docs[1]}
    for docs in source_docs:
        for doc in docs:
            assert "/063B/" in doc.source
            assert doc.source_locator is not None
            assert doc.source_locator["raw_sha256"] == doc.raw_sha256
            assert doc.source_locator["chunk_text_sha256"] == doc.chunk_sha256
            assert doc.retrieval_policy == "context_only"
            assert "cannot establish Canadian" in doc.applicability_boundary
