"""Admission and product-reachability contracts for the source-linked cards."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agronomy_agent.agent import build_context, load_agent_resources
from agronomy_agent.corpus_governance import filter_docs_by_corpus_governance, load_corpus_policy
from agronomy_agent.corpus_release import quality_ledger_status, source_locator_status


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data/derived/rag/offline_agronomy/production_foundations/v1"
SHARD = STORE / "shards/foundations-0001.jsonl"


def test_foundations_release_preserves_project_text_and_external_receipts() -> None:
    manifest = json.loads((STORE / "store_manifest.json").read_text(encoding="utf-8"))
    registry_path = ROOT / "data/manifests/production_foundations_sources_v1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    receipt = json.loads((STORE / "source_receipt.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in SHARD.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = {entry["source_id"] for entry in registry["sources"]}

    assert manifest["row_count"] == len(rows) == 9
    assert hashlib.sha256(SHARD.read_bytes()).hexdigest() == manifest["shards"][0]["sha256"]
    assert receipt["external_source_registry_sha256"] == hashlib.sha256(registry_path.read_bytes()).hexdigest()
    assert receipt["external_snapshots_in_public_package"] is False
    assert len(ids) == 7
    for row in rows:
        assert row["supporting_source_ids"] and set(row["supporting_source_ids"]) <= ids
        assert row["authority_tier"] == "internal_synthesis"
        assert row["retrieval_policy"] == "context_only"
        assert row["source_kind"] == "project_authored_source_linked_synthesis"
        assert row["source_type"] == "applied_guidance"
        assert row["knowledge_bucket"] == "farmer_knowledge"
        assert source_locator_status(row["source_locator"])[0]
        assert quality_ledger_status(row)[0]


def test_foundations_runtime_cards_do_not_contain_exposed_case_examples() -> None:
    rows = [json.loads(line) for line in SHARD.read_text(encoding="utf-8").splitlines() if line.strip()]
    questions = [
        json.loads(line)["question"]
        for line in (ROOT / "data/eval/production_foundations_development_v1.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        text = row["text"]
        assert "$" not in text, row["doc_id"]
        assert not re.search(r"\b(?:117|600|240,000|120,000|300,000|750,000)\b", text), row["doc_id"]
        assert not re.search(r"\b\d+(?:\.\d+)?\s*(?:lb/ac|bu/ac|C days)\b", text, re.IGNORECASE), row["doc_id"]
        assert all(question not in text for question in questions), row["doc_id"]


def test_candidate_card_reaches_execution_route_but_cannot_authorize_a_rate() -> None:
    candidate_config = "configs/rag_production_foundations_candidate.yaml"
    active = load_agent_resources("configs/rag.yaml")
    assert "foundation_mb_break_even" not in {row.get("doc_id") for row in active.retriever.docs}
    resources = load_agent_resources(candidate_config)
    question = "A Manitoba crop budget totals $600 per acre and assumes 50 bushels per acre. What is the break-even sale price per bushel?"
    context = build_context(
        question,
        rag_config=candidate_config,
        use_context_cache=False,
        use_search_cache=False,
    )
    assert "foundation_mb_break_even" in {doc.doc_id for doc in context.retrieved_docs}

    nutrient_card = next(
        doc for doc in resources.retriever.search("US NRCS nutrient management soil test manure crop plan", top_k=20)
        if doc.doc_id == "foundation_us_nutrient_plan"
    )
    policy = load_corpus_policy(ROOT, "data/manifests/runtime_corpus_policy_production_foundations_candidate.json")
    allowed, blocked = filter_docs_by_corpus_governance(
        "What exact nitrogen rate should I apply to a Saskatchewan canola field?",
        [nutrient_card],
        policy,
    )
    assert allowed == []
    assert blocked and blocked[0]["reason"] == "not_decisive_for_high_consequence"


def test_canadian_budget_card_does_not_gain_us_decisive_scope() -> None:
    resources = load_agent_resources("configs/rag_production_foundations_candidate.yaml")
    doc = next(
        doc for doc in resources.retriever.search("Manitoba crop budget break-even price", top_k=20)
        if doc.doc_id == "foundation_mb_break_even"
    )
    from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query

    query = "For an Oklahoma wheat budget, what is the break-even grain price concept?"
    fit = filter_docs_for_query([doc], analyze_query_context(query), primary_intent="conceptual")
    assert not fit.docs
    assert fit.dropped[0]["reason"] == "jurisdiction_mismatch"
