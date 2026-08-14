from __future__ import annotations

import pytest

from agronomy_agent.agent import (
    AgentContext,
    _allows_context_only_regional_interpretation,
    build_context,
    generate_answer,
)
from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.evidence_handshake import EvidenceHandshake
from agronomy_agent.router import QueryRoute


SLC_QUESTION = (
    "My uploaded field intersects an AAFC historical crop-yield SLC record showing canola at "
    "2,780 kg/ha in 2018. What does that value mean, and does it prove my field yielded that?"
)
GEONB_QUESTION = (
    "My New Brunswick field intersects GeoNB Agricultural Soil Classes class 3. "
    "What does that class mean for this field?"
)


def _context_only_doc(source_id: str, text: str) -> RetrievedDoc:
    return RetrievedDoc(
        doc_id=f"{source_id}_semantic_fixture",
        title=source_id,
        text=text,
        source="Official Canadian government source",
        score=2.0,
        tags=("regional context",),
        namespaces=("regional_environment", "field_data"),
        source_type="regional_environment_profile",
        allowed_roles=("grower", "adviser"),
        crops=("all",),
        source_id=source_id,
        jurisdictions=("Canada",),
        retrieval_policy="context_only",
    )


def _weak_context(
    doc: RetrievedDoc,
    *,
    question_type: str,
    risk_level: str = "low",
    regional_context_requested: bool = True,
) -> AgentContext:
    route = QueryRoute(
        question_type=question_type,
        risk_level=risk_level,
        namespaces=("regional_environment", "field_data"),
        required_tools=("field_data_guard",),
        answer_style="plain",
        audience="farmer",
        query_expansion=(),
        guidance="Keep regional context separate from current field evidence.",
        knowledge_bucket="farmer_knowledge",
        knowledge_domains=("field_data",),
    )
    handshake = EvidenceHandshake(
        decision=question_type,
        preserve_entities=(),
        required_entities=(),
        primary_doc_id=None,
        primary_title=None,
        supporting_doc_ids=(doc.doc_id,),
        decisive_terms=(),
        primary_query_coverage=0.0,
        primary_relevance_score=0.0,
        evidence_roles=((doc.doc_id, "boundary", "context_only_not_decisive"),),
    )
    return AgentContext(
        retrieved_docs=[doc],
        graph_hits=[],
        tool_notes=[],
        route=route,
        coverage_checklist=(),
        runtime_metadata={
            "query_context": {
                "regional_context_requested": regional_context_requested,
                "target_jurisdictions": list(doc.jurisdictions),
            }
        },
        evidence_handshake=handshake,
    )


class _UnsafeDraftGenerator:
    measured_capability_profile = "balanced"
    last_generation_stats: dict[str, object] = {}

    def __init__(self, draft: str) -> None:
        self.draft = draft
        self.messages: list[dict[str, str]] = []

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return self.draft


@pytest.mark.parametrize(
    ("question", "doc", "draft", "expected"),
    (
        (
            SLC_QUESTION,
            _context_only_doc(
                "ca_aafc_historical_crop_yield_slc_specification",
                "The AAFC value is a regional historical estimate keyed by crop, year, province, SLC, and kg/ha. "
                "It is not measured field yield, yield potential, or a current forecast; verify calibrated farm "
                "records, harvested area, and moisture basis.",
            ),
            "Yes, this proves the field yielded 2,780 kg/ha.",
            "does not prove what this field yielded",
        ),
        (
            GEONB_QUESTION,
            _context_only_doc(
                "nb_geonb_agricultural_soil_classes",
                "The GeoNB service maps agricultural suitability as classes 1 through 5. The data were created "
                "in April 2021; water bodies were removed and polygons smaller than 100 square metres were "
                "eliminated. A class does not establish current drainage, nutrient status, a limiting factor, "
                "crop-specific fit, or an input rate.",
            ),
            "Class 3 proves this field has adequate drainage and nutrients.",
            "agricultural-suitability screening context",
        ),
    ),
)
def test_explicit_named_regional_interpretation_admits_context_only_evidence_to_verifier(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    doc: RetrievedDoc,
    draft: str,
    expected: str,
) -> None:
    context = _weak_context(doc, question_type="regional_context")
    generator = _UnsafeDraftGenerator(draft)
    monkeypatch.setattr(
        "agronomy_agent.agent.build_messages",
        lambda *args, **kwargs: (
            [
                {"role": "system", "content": "Use bounded regional context."},
                {"role": "user", "content": doc.text},
            ],
            context,
        ),
    )

    answer, metadata = generate_answer(
        question,
        "agronomic_rag",
        generator,
        verification_enabled=True,
        verification_mode="model_agnostic_selective_v2",
        capture_context_packet=True,
    )

    assert expected in answer
    assert doc.text in generator.messages[-1]["content"]
    assert metadata["context_admission"] == {
        "candidate_retrieval_present": True,
        "candidate_retrieval_admitted": True,
        "policy": "explicit_regional_context_interpretation",
        "rejection_reason": None,
    }
    assert metadata["answer_verification"]["fallback_applied"] is True
    assert metadata["answer_verification"]["final_assessment"]["evidence_ids"] == [doc.doc_id]


@pytest.mark.parametrize(
    ("question", "question_type", "risk_level"),
    (
        (
            "Can I use the AAFC historical crop-yield SLC value of 2,780 kg/ha to set the nitrogen rate?",
            "fertility_rate",
            "medium",
        ),
        (
            "Does a GeoNB Agricultural Soil Classes class 3 polygon diagnose why this canola field is yellow?",
            "field_data",
            "low",
        ),
    ),
)
def test_regional_context_flag_does_not_admit_context_only_evidence_for_action_or_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    question_type: str,
    risk_level: str,
) -> None:
    doc = _context_only_doc(
        "ca_aafc_historical_crop_yield_slc_specification",
        "This context-only regional record must not become field action or diagnosis authority.",
    )
    context = _weak_context(doc, question_type=question_type, risk_level=risk_level)
    generator = _UnsafeDraftGenerator("Apply the treatment now.")
    monkeypatch.setattr(
        "agronomy_agent.agent.build_messages",
        lambda *args, **kwargs: (
            [
                {"role": "system", "content": "Use bounded regional context."},
                {"role": "user", "content": doc.text},
            ],
            context,
        ),
    )

    _, metadata = generate_answer(
        question,
        "agronomic_rag",
        generator,
        verification_enabled=False,
        capture_context_packet=True,
    )

    assert metadata["context_admission"] == {
        "candidate_retrieval_present": True,
        "candidate_retrieval_admitted": False,
        "policy": "kernel_and_field_context_only",
        "rejection_reason": "no_decision_grade_primary_evidence",
    }
    packet = metadata["benchmark_generation_input"]
    assert doc.text not in packet["messages"][-1]["content"]
    assert packet["retrieved_documents"][0]["doc_id"] == doc.doc_id


def test_real_slc_context_persists_explicit_regional_signal_for_admission() -> None:
    context = build_context(
        SLC_QUESTION,
        rag_config="configs/rag_final_mvp.yaml",
        use_context_cache=False,
        use_search_cache=False,
    )

    assert context.route.question_type == "regional_context"
    assert context.runtime_metadata["query_context"]["regional_context_requested"] is True
    assert context.evidence_handshake is not None
    assert context.evidence_handshake.has_strong_primary is False
    assert any(doc.retrieval_policy == "context_only" for doc in context.retrieved_docs)
    assert _allows_context_only_regional_interpretation(context, question=SLC_QUESTION) is True
