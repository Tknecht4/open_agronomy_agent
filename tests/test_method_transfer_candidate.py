"""Method transfer stays explanatory, source-linked and outside the active corpus."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from agronomy_agent.agent import build_context, load_agent_resources
from agronomy_agent.decision_contract import build_decision_contract, obligation_coverage
from agronomy_agent.method_context import curated_method_response, method_fit_reason, requested_methods, reviewed_method_ids
from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query
from agronomy_agent.server.services.chat_service import _build_doc_snapshot


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "configs/rag_production_foundations_method_candidate.yaml"
STORE = ROOT / "data/derived/rag/offline_agronomy/production_foundations/v2"


def test_v2_release_is_bound_to_sources_and_not_active() -> None:
    manifest = json.loads((STORE / "store_manifest.json").read_text())
    receipt = json.loads((STORE / "source_receipt.json").read_text())
    source_registry = json.loads((ROOT / "data/manifests/production_foundations_sources_v2.json").read_text())
    support = ROOT / "data/manifests/production_foundations_method_support_v2.json"
    shard = STORE / manifest["shards"][0]["path"]
    rows = [json.loads(line) for line in shard.read_text().splitlines() if line.strip()]
    assert manifest["store_id"] == "production-foundations-method-v2"
    assert manifest["row_count"] == len(rows) == 7
    assert hashlib.sha256(shard.read_bytes()).hexdigest() == manifest["shards"][0]["sha256"]
    assert hashlib.sha256(support.read_bytes()).hexdigest() == receipt["source_support_receipt_sha256"]
    assert hashlib.sha256((ROOT / source_registry["base_registry_path"]).read_bytes()).hexdigest() == source_registry["base_registry_sha256"]
    assert receipt["external_snapshots_in_public_package"] is False
    active = load_agent_resources("configs/rag.yaml")
    candidate = load_agent_resources(CANDIDATE)
    assert not any(str(row.get("doc_id", "")).startswith("method_") for row in active.retriever.docs)
    assert {row["doc_id"] for row in rows} <= {row.get("doc_id") for row in candidate.retriever.docs}
    for row in rows:
        assert row["authority_tier"] == "internal_synthesis"
        assert row["retrieval_policy"] == "context_only"
        assert row["method_scope"]["source_support_receipt_sha256"] == receipt["source_support_receipt_sha256"]
        assert row["jurisdiction"] == ["Canada", "United States"]
        assert any("Canada" in region for region in row["source_jurisdictions"])
        assert any("United States" in region for region in row["source_jurisdictions"])


def test_method_scope_survives_final_context_without_field_authority() -> None:
    question = "For my Saskatchewan wheat farm's seed order, how do lot germination and thousand-kernel weight affect the mass once I choose a local stand target?"
    context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
    doc = next(doc for doc in context.retrieved_docs if doc.doc_id == "method_seed_mass")
    assert reviewed_method_ids(doc) == ("seed_mass",)
    contract = build_decision_contract(question, context.route, method_context_enabled=True)
    assert "method:seed_mass" in obligation_coverage(doc, contract)
    assert "field_observation" not in obligation_coverage(doc, contract)
    packet = context.runtime_metadata["evidence_fabric"]["evidence_packet"]
    applicability = next(row for row in packet["applicability"] if "seed_mass" in row["methods"])
    assert applicability["transfer_status"] == "reviewed_general_method_scope"
    capsule = next(row for row in packet["capsules"] if row["authority_role"] == "method_context")
    assert capsule["field_action_authority"] == "not_authorized"
    span = next(row for row in packet["spans"] if row["locator"]["doc_id"] == doc.doc_id)
    assert span["locator"]["supporting_source_ids"] == list(doc.supporting_source_ids)
    assert span["locator"]["source_jurisdictions"] == list(doc.source_jurisdictions)
    assert "GENERAL METHOD ONLY" in context.packed_context.text
    persisted = _build_doc_snapshot(1, doc, store_text=False)
    assert persisted["method_scope"] == doc.method_scope
    assert persisted["supporting_source_ids"] == list(doc.supporting_source_ids)
    assert persisted["source_jurisdictions"] == list(doc.source_jurisdictions)
    method_coverage = next(row for row in packet["coverage"] if row["slot_key"] == "method:seed_mass")
    assert method_coverage["required_authority"] == "method_context_only"
    assert method_coverage["status"] == "ADEQUATE"
    answer, receipt = curated_method_response(context, question)
    assert answer and "Saskatchewan" in answer and "local" in answer
    assert receipt and receipt["doc_ids"] == [doc.doc_id]
    assert receipt["authority"] == "method_context_only"
    forged_context = replace(context, retrieved_docs=[replace(doc, method_scope={**doc.method_scope, "source_support_receipt_sha256": "0" * 64})])
    assert curated_method_response(forged_context, question) == (None, None)
    active_context = build_context(question, rag_config="configs/rag.yaml", use_context_cache=False, use_search_cache=False)
    assert curated_method_response(active_context, question) == (None, None)


def test_unreviewed_or_out_of_scope_method_cannot_bypass_query_fit() -> None:
    resources = load_agent_resources(CANDIDATE)
    doc = next(row for row in resources.retriever.search("partial budget", top_k=10) if row.doc_id == "method_partial_budget")
    question = "Would an incremental farm budget help compare renting a weeder for our Quebec operation?"
    assert filter_docs_for_query([doc], analyze_query_context(question)).docs == (doc,)
    forged = replace(doc, method_scope={**doc.method_scope, "source_support_receipt_sha256": "missing"})
    result = filter_docs_for_query([forged], analyze_query_context(question))
    assert not result.docs and result.dropped[0]["reason"] == "invalid_method_scope"
    assert method_fit_reason(doc, question, None) == "method_target_country_unknown"
    assert method_fit_reason(doc, "Explain the embryo of a germinating bean seed on a Quebec farm", "canada") == "method_mismatch"


def test_method_recognition_does_not_swallow_unrelated_or_regulated_requests() -> None:
    assert requested_methods("Explain a farm's mission statement and vision for an Ontario workshop") == ()
    assert requested_methods("Describe sandy and clay soil texture in Saskatchewan") == ()
    assert requested_methods("Explain embryo and stored food in a germinating bean seed") == ()
    assert requested_methods("May I apply a Canadian pesticide in North Dakota with a matching active ingredient?") == ()
    assert requested_methods("Explain the bean embryo as a seed germinates; no planting population is needed.") == ()
    context = build_context(
        "May I apply a Canadian pesticide in North Dakota with a matching active ingredient?",
        rag_config=CANDIDATE,
        use_context_cache=False,
        use_search_cache=False,
    )
    assert not any(doc.doc_id.startswith("method_") for doc in context.retrieved_docs)


def test_method_recognition_uses_independent_concepts_without_a_topic_word() -> None:
    assert "seed_mass" in requested_methods(
        "Our oat seed lot has a different germination result and seed size; how do we keep the same stand when setting the drill?"
    )
    assert "enterprise_budget" in requested_methods(
        "For a new cut-flower enterprise, compare saleable output with production and marketing expenses."
    )
    assert "nutrient_plan_inputs" in requested_methods(
        "An adviser needs field history after our manure supplier changed storage; what evidence should we gather?"
    )


def test_curated_method_response_requires_explanation_not_a_transferred_rate() -> None:
    question = "Can I copy a Pennsylvania manure application rate to my Prince Edward Island field without a soil or manure analysis?"
    context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
    assert curated_method_response(context, question) == (None, None)
    question = "Explain nutrient planning, and may I use this Canadian-labeled herbicide on my North Dakota field?"
    context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
    assert curated_method_response(context, question) == (None, None)
    question = "Our British Columbia farm has land equity but cash is short before invoices are paid. How do working capital, current ratio and a cash-flow schedule help explain this?"
    context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
    answer, receipt = curated_method_response(context, question)
    assert answer and "current assets minus current liabilities" in answer
    assert "financing proceeds" in answer and "cash payment" in answer
    assert receipt and set(receipt["method_ids"]) == {"liquidity", "cash_flow"}


def test_curated_method_response_rejects_foreign_sites_and_competing_decisions() -> None:
    blocked = (
        "I farm in Australia and want to understand a Manitoba guide to seed mass and target stand.",
        "For my Alberta farm, should I sell land to improve working capital?",
        "Our Ontario farm uses a Manitoba enterprise budget. Explain the framework and tell me current wheat prices.",
        "I farm in Ontario. Explain a Manitoba crop budget, and tell me if my field is deficient in nitrogen.",
        "I farm in Alberta. Explain cash flow and advise whether to borrow to buy land.",
        "For my Ontario farm, how should I sell land to improve working capital?",
        "For my Alberta farm, explain growing degree days and whether the wheat is ready to harvest.",
        "For my Ontario farm, explain the enterprise budget and what wheat prices are now.",
        "I farm in Alberta and in Australia. Explain the Manitoba seed mass method.",
        "Our Alberta farm uses growing degree days. Explain the method. Is the wheat ready to harvest?",
        "Explain working capital for my Ontario farm. Is selling land the best choice?",
        "Explain the enterprise budget for my Ontario farm. What is wheat selling for at the local elevator?",
        "Explain the seed mass method for my Saskatchewan farm. Give me a target stand for wheat.",
        "Explain the enterprise budget for my Ontario farm. Please estimate wheat prices for next month.",
        "Explain cash flow for my Ontario farm, and is buying a combine sensible?",
        "For our Alberta farm, explain growing degree days. Describe the weather tomorrow.",
        "Explain working capital for our Ontario farm. Explain why buying the neighbouring farm is a good investment.",
        "i farm in alberta and in australia. explain the manitoba seed mass method.",
        "For our Alberta farm, explain cash flow. Decide whether we can afford a new tractor.",
        "For my Saskatchewan farm, explain seed mass and suggest a target stand.",
        "For my Ontario farm, explain an enterprise budget including the wheat price at our elevator this morning.",
        "For our Australian farm, explain the Ontario enterprise budget method.",
        "For our Ontario farm and our Australian farm, explain seed mass.",
    )
    for question in blocked:
        context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
        assert curated_method_response(context, question) == (None, None)

    question = "I farm in Australia and want to understand a Manitoba guide to seed mass and target stand."
    context = build_context(
        question,
        rag_config=CANDIDATE,
        field_context={"province_state": "New South Wales", "country": "Australia"},
        use_context_cache=False,
        use_search_cache=False,
    )
    packet = context.runtime_metadata["evidence_fabric"]["evidence_packet"]
    assert curated_method_response(context, question) == (None, None)
    assert not any(row["slot_key"].startswith("method:") and row["status"] == "ADEQUATE" for row in packet["coverage"])


def test_source_first_jurisdiction_reaches_contract_and_evidence_frame() -> None:
    question = "I saw an Iowa guide to nutrient planning. Explain which inputs matter on my Alberta farm."
    for profile in ("configs/rag.yaml", CANDIDATE):
        context = build_context(question, rag_config=profile, use_context_cache=False, use_search_cache=False)
        assert context.runtime_metadata["query_context"]["target_jurisdictions"] == ["alberta"]
        assert context.runtime_metadata["decision_contract"]["jurisdiction_scope"] == ("alberta",)
        assert context.runtime_metadata["evidence_fabric"]["question_frame"]["jurisdiction_scope"] == ("alberta",)
        if profile == CANDIDATE:
            assert context.route.question_type == "fertility_diagnostic"
            assert curated_method_response(context, question) == (None, None)


def test_comparison_between_two_method_families_keeps_both() -> None:
    question = "For our Maine farm, how do partial budgets and enterprise budgets differ in their cost boundary?"
    context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
    assert set(requested_methods(question)) == {"partial_budget", "enterprise_budget"}
    assert {doc.doc_id for doc in context.retrieved_docs if doc.doc_id.startswith("method_")} >= {
        "method_partial_budget", "method_enterprise_budget"
    }
    answer, receipt = curated_method_response(context, question)
    assert answer and "Incremental farm-change" in answer and "Enterprise cost-boundary" in answer
    assert receipt and set(receipt["method_ids"]) == {"partial_budget", "enterprise_budget"}
