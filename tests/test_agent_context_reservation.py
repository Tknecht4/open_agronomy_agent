from __future__ import annotations

from agronomy_agent.agent import (
    _reserve_named_crop_health_specification,
    build_context,
)
from agronomy_agent.agno_runtime.local_index import RetrievedDoc
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
