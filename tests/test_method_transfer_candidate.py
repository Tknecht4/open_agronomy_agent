"""Method transfer stays explanatory, source-linked and outside the active corpus."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from agronomy_agent.agent import build_context, load_agent_resources
from agronomy_agent.decision_contract import build_decision_contract, obligation_coverage
from agronomy_agent.method_context import method_fit_reason, requested_methods, reviewed_method_ids, source_bound_method_appendix
from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query
from agronomy_agent.server.services.chat_service import _build_doc_snapshot
from agronomy_agent.execution_core import AgentExecutionRequest
from agronomy_agent.server.services.chat_service import execute_agent_request
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


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
    answer, receipt = source_bound_method_appendix(context, question)
    assert answer and "Method background from cited card" in answer
    assert "do not establish this farm's target" in answer
    assert receipt and receipt["doc_ids"] == [doc.doc_id]
    assert receipt["authority"] == "method_context_only_not_complete_answer"
    forged_context = replace(context, retrieved_docs=[replace(doc, method_scope={**doc.method_scope, "source_support_receipt_sha256": "0" * 64})])
    assert source_bound_method_appendix(forged_context, question) == (None, None)
    active_context = build_context(question, rag_config="configs/rag.yaml", use_context_cache=False, use_search_cache=False)
    assert source_bound_method_appendix(active_context, question) == (None, None)


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

    seed = next(row for row in resources.retriever.search("seed mass", top_k=10) if row.doc_id == "method_seed_mass")
    for foreign_question in (
        "I farm in Australia using an Ontario seed guide. Explain seed mass.",
        "For my farms in Ontario and Australia, explain seed mass.",
        "we farm in ontario and australia. explain seed mass.",
    ):
        foreign_fit = filter_docs_for_query([seed], analyze_query_context(foreign_question))
        assert not foreign_fit.docs
        assert foreign_fit.dropped[0]["reason"] == "method_target_scope_unresolved"
    cash_flow = next(row for row in resources.retriever.search("cash flow", top_k=10) if row.doc_id == "method_cash_flow")
    near_foreign = "I farm near Perth, Australia. Explain cash flow using an Ontario guide."
    near_fit = filter_docs_for_query([cash_flow], analyze_query_context(near_foreign))
    assert not near_fit.docs
    assert near_fit.dropped[0]["reason"] == "method_target_scope_unresolved"


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


def test_method_appendix_keeps_local_authority_separate() -> None:
    for question in (
        "Can I copy a Pennsylvania manure application rate to my Prince Edward Island field without a soil or manure analysis?",
        "Explain nutrient planning, and may I use this Canadian-labeled herbicide on my North Dakota field?",
        "For our Australian farm, explain the Ontario enterprise budget method.",
        "For our Ontario farm and our Australian farm, explain seed mass.",
        "I farm in Australia using an Ontario budget. Explain enterprise budgets.",
        "For my farms in Ontario and Australia, explain enterprise budgets.",
        "I farm near Perth, Australia. Explain cash flow using an Ontario guide.",
    ):
        context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
        assert source_bound_method_appendix(context, question) == (None, None)

    question = "Our British Columbia farm has land equity but cash is short before invoices are paid. How do working capital, current ratio and a cash-flow schedule help explain this?"
    context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
    appendix, receipt = source_bound_method_appendix(context, question)
    assert appendix and "current assets minus current liabilities" in appendix
    assert "financing proceeds" in appendix and "cash payment" in appendix
    assert receipt and set(receipt["included_method_ids"]) == {"liquidity", "cash_flow"}
    assert receipt["authority"] == "method_context_only_not_complete_answer"


def test_source_first_jurisdiction_reaches_contract_and_evidence_frame() -> None:
    question = "I saw an Iowa guide to nutrient planning. Explain which inputs matter on my Alberta farm."
    for profile in ("configs/rag.yaml", CANDIDATE):
        context = build_context(question, rag_config=profile, use_context_cache=False, use_search_cache=False)
        assert context.runtime_metadata["query_context"]["target_jurisdictions"] == ["alberta"]
        assert context.runtime_metadata["decision_contract"]["jurisdiction_scope"] == ("alberta",)
        assert context.runtime_metadata["evidence_fabric"]["question_frame"]["jurisdiction_scope"] == ("alberta",)
        if profile == CANDIDATE:
            assert context.route.question_type == "fertility_diagnostic"
            assert source_bound_method_appendix(context, question) == (None, None)


def test_comparison_between_two_method_families_keeps_both() -> None:
    question = "For our Maine farm, how do partial budgets and enterprise budgets differ in their cost boundary?"
    context = build_context(question, rag_config=CANDIDATE, use_context_cache=False, use_search_cache=False)
    assert set(requested_methods(question)) == {"partial_budget", "enterprise_budget"}
    assert {doc.doc_id for doc in context.retrieved_docs if doc.doc_id.startswith("method_")} >= {
        "method_partial_budget", "method_enterprise_budget"
    }
    answer, receipt = source_bound_method_appendix(context, question)
    assert answer and "Incremental farm-change" in answer and "Enterprise cost-boundary" in answer
    assert receipt and set(receipt["included_method_ids"]) == {"partial_budget", "enterprise_budget"}


def test_product_path_calls_generator_and_records_method_as_background(tmp_path) -> None:  # noqa: ANN001
    class Backend:
        backend_id = "method_path_probe_v1"

        def __init__(self) -> None:
            self.calls: list[list[dict[str, str]]] = []

        def generate(self, messages):  # noqa: ANN001, ANN201
            self.calls.append([dict(row) for row in messages])
            return "This farm decision needs its own current evidence and terms."

    for idx, question in enumerate((
        "For our Alberta farm, explain seasonal cash flow.",
        "For our Alberta farm, explain cash flow and select the best lender for us.",
    )):
        db_path = tmp_path / f"method_{idx}.sqlite3"
        store = TraceStore(db_path)
        session = store.create_session("method probe", {}, {})
        settings = build_settings(
            db_path=db_path,
            artifact_root=tmp_path / f"artifacts_{idx}",
            model_config_path="configs/model.yaml",
            default_rag_config=CANDIDATE,
            network_mode="offline",
        )
        backend = Backend()
        execution = execute_agent_request(AgentExecutionRequest(
            store=store,
            settings=settings,
            session_id=session["session_id"],
            message=question,
            mode="agronomic_rag",
            model_id="mock",
            rag_config=CANDIDATE,
            max_tokens=100,
            trace_options={"store_prompt_messages": False, "store_retrieved_text": False},
            execution_class="observed_system_execution_nonclaim",
            generation_backend=backend,
        ))
        assert len(backend.calls) == 1
        assert len(execution.stage_receipts) == 17
        metadata = execution.turn["trace"]["metadata"]
        assert metadata.get("generation_path") != "deterministic_method_context"
        assert "generation_bypass" not in metadata
        if idx == 0:
            appendix_receipt = metadata["method_appendix"]
            assert appendix_receipt["authority"] == "method_context_only_not_complete_answer"
            assert "method_cash_flow" in appendix_receipt["doc_ids"]
            assert appendix_receipt["model_draft_sha256"] == hashlib.sha256(
                "This farm decision needs its own current evidence and terms.".encode()
            ).hexdigest()
            assert appendix_receipt["combined_draft_sha256"] == metadata["answer_stages"]["draft"]["sha256"]
            assert "Method background from cited card method_cash_flow" in execution.answer
            assert "Start with opening cash" in execution.answer
            assert "These project-authored summaries explain general methods only" in execution.answer
        else:
            assert "This farm decision needs its own current evidence" in execution.answer
