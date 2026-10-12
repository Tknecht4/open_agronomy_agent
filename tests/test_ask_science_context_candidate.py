"""Deterministic contracts for two non-active, source-bound research cards."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from agronomy_agent.agent import build_context, load_agent_resources
from agronomy_agent.corpus_governance import filter_docs_by_corpus_governance, load_corpus_policy
from agronomy_agent.corpus_release import quality_ledger_status, source_locator_status
from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query

ROOT = Path(__file__).resolve().parents[1]
SEED = Path("data/seed/ask_science_context_v1.jsonl")
REGISTRY = Path("data/manifests/ask_science_sources_v1.json")
STORE = Path("data/derived/rag/offline_agronomy/ask_science/v1")
CONFIG = "configs/rag_ask_science_candidate.yaml"
POLICY = "data/manifests/runtime_corpus_policy_ask_science_candidate.json"
IDS = {"W2948372212", "W3184228112"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def builder(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ask_science_builder", ROOT / "scripts/build_production_foundations_supplement.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    for relative in (SEED, REGISTRY):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    return module, tmp_path


def test_candidate_rebuild_is_byte_reproducible_and_refuses_overwrite(builder):
    module, root = builder
    module.build(root / SEED, root / REGISTRY, root / STORE, store_id="ask-science-context-v1")
    for relative in ("shards/foundations-0001.jsonl", "quality_ledger.json", "source_receipt.json", "store_manifest.json"):
        assert (root / STORE / relative).read_bytes() == (ROOT / STORE / relative).read_bytes()
    with pytest.raises(FileExistsError):
        module.build(root / SEED, root / REGISTRY, root / STORE, store_id="ask-science-context-v1")


@pytest.mark.parametrize("fault", ["free_access", "missing_attribution", "missing_authors", "wrong_snapshot", "missing_span", "invalid_span", "unreviewed_base", "active"])
def test_candidate_rejects_incomplete_article_rights_and_lineage(builder, fault):
    module, root = builder
    registry = _json(root / REGISTRY)
    source = registry["sources"][0]
    if fault == "free_access":
        source["rights"] = "free_to_read"
    elif fault == "missing_attribution":
        source["attribution"] = ""
    elif fault == "missing_authors":
        source["authors"] = []
    elif fault == "wrong_snapshot":
        source["license_evidence"]["snapshot_sha256"] = "0" * 64
    elif fault == "missing_span":
        source["locators"] = []
    elif fault == "invalid_span":
        source["locators"][0]["extracted_text_lines"] = [0, 5]
    elif fault == "unreviewed_base":
        registry["base_registry_path"] = "data/manifests/production_foundations_sources_v1.json"
    else:
        registry["activation"] = "startup"
    (root / REGISTRY).write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="Ask Science"):
        module.build(root / SEED, root / REGISTRY, root / STORE, store_id="ask-science-context-v1")
    assert not (root / STORE).exists()


@pytest.mark.parametrize("field", ["application_boundary", "applicability_boundary"])
def test_candidate_rejects_missing_application_boundary(builder, field):
    module, root = builder
    rows = _rows(root / SEED)
    rows[0][field] = ""
    (root / SEED).write_text("\n".join(json.dumps(row) for row in rows))
    with pytest.raises(ValueError, match="context boundary"):
        module.build(root / SEED, root / REGISTRY, root / STORE, store_id="ask-science-context-v1")


def test_release_preserves_seed_and_external_article_provenance():
    manifest = _json(ROOT / STORE / "store_manifest.json")
    receipt = _json(ROOT / STORE / "source_receipt.json")
    registry = _json(ROOT / REGISTRY)
    rows = _rows(ROOT / STORE / "shards/foundations-0001.jsonl")
    assert manifest["row_count"] == len(rows) == 2
    assert manifest["shards"][0]["sha256"] == hashlib.sha256((ROOT / STORE / "shards/foundations-0001.jsonl").read_bytes()).hexdigest()
    assert receipt["source_ids"] == sorted(IDS)
    assert receipt["external_source_registry_sha256"] == hashlib.sha256((ROOT / REGISTRY).read_bytes()).hexdigest()
    assert receipt["external_snapshots_in_public_package"] is False
    assert registry["delivery_manifest_sha256"] == "a3841d94eb4c4ff43aa64848b8a6fcb82a72c8095ea6b829df3c906f9c5c5223"
    for source in registry["sources"]:
        assert source["authors"] and source["doi"] in source["attribution"]
        assert all(", " in name for name in source["authors"])
        assert source["independent_review"] == "approved_narrow_source_summary_non_active_candidate"
        assert source["rights"] == "CC-BY-4.0_article_only"
        assert source["underlying_trial_overlap"] == "not_fully_reconciled"
        assert source["license_evidence"]["snapshot_sha256"] == source["snapshot_sha256"]
    assert len(registry["independent_review"]["receipt_sha256"]) == 64
    for row in rows:
        assert set(row["supporting_source_ids"]) <= IDS
        assert row["authority_tier"] == "internal_synthesis"
        assert row["retrieval_policy"] == "context_only"
        assert row["answer_role"] == "research_context"
        assert row["evidence_roles"] == ["source_observation", "study_model", "project_interpretation"]
        assert source_locator_status(row["source_locator"])[0]
        assert quality_ledger_status(row)[0]


def test_candidate_is_not_an_active_or_selectable_runtime_profile():
    active = yaml.safe_load((ROOT / "configs/rag.yaml").read_text())
    controls = _json(ROOT / "configs/runtime_profiles.json")
    assert CONFIG not in json.dumps(controls)
    assert STORE.as_posix() not in json.dumps(active)
    assert not IDS.intersection({row.get("source_id") for row in load_agent_resources("configs/rag.yaml").retriever.docs})
    config = yaml.safe_load((ROOT / CONFIG).read_text())
    assert config["retrieval"]["corpus_policy_manifest"] == POLICY
    assert all(not path.startswith(("data/eval/", "docs/reviews/", "outputs/")) for path in config["retrieval"]["corpus_paths"])
    policy = _json(ROOT / POLICY)
    candidate = [row for row in policy["corpora"] if row.get("store_profile_id") == "ask-science-context-v1"]
    assert len(candidate) == 1
    assert candidate[0]["source_ids"] == sorted(IDS)
    assert candidate[0]["runtime_eligibility"] == "context_only"


@pytest.mark.parametrize("question,doc_id", [
    ("For Ontario hybrid corn, why does a positive fungicide yield response not guarantee profitability?", "ask_science_w2948372212"),
    ("For Canadian Daymet V4 gridded weather, what do station-year cross-validation errors tell us?", "ask_science_w3184228112"),
])
def test_explicit_candidate_reaches_product_context_without_generation(question, doc_id):
    context = build_context(question, rag_config=CONFIG, use_context_cache=False, use_search_cache=False)
    doc = next(doc for doc in context.retrieved_docs if doc.doc_id == doc_id)
    assert doc.retrieval_policy == "context_only"
    assert doc.source_locator and doc.supporting_source_ids
    assert doc.applicability_boundary


@pytest.fixture(scope="module")
def candidate_docs():
    resources = load_agent_resources(CONFIG)
    return {doc.doc_id: doc for doc in resources.retriever.search("corn fungicide profitability Daymet V4 cross-validation", top_k=100) if doc.doc_id.startswith("ask_science_")}


@pytest.mark.parametrize("query,reason", [
    ("For Saskatchewan corn, does a positive fungicide yield response guarantee profit?", "jurisdiction_mismatch"),
    ("For Ontario wheat, does fungicide yield response guarantee profit?", "crop_mismatch"),
    ("For Iowa corn, does fungicide yield response guarantee profit?", "jurisdiction_mismatch"),
])
def test_corn_study_does_not_gain_other_province_or_crop_scope(candidate_docs, query, reason):
    doc = candidate_docs["ask_science_w2948372212"]
    result = filter_docs_for_query([doc], analyze_query_context(query), primary_intent="conceptual")
    assert not result.docs
    assert result.dropped[0]["reason"] == reason


def test_candidate_scope_is_narrower_than_preserved_trial_geography(candidate_docs):
    doc = candidate_docs["ask_science_w2948372212"]
    assert doc.jurisdictions == ("Ontario",)
    assert doc.source_jurisdictions == ("United States; Ontario, Canada",)
    assert "Ontario-scoped candidate context only" in doc.applicability_boundary


def test_context_cannot_authorize_a_pesticide_application(candidate_docs):
    policy = load_corpus_policy(ROOT, POLICY)
    allowed, blocked = filter_docs_by_corpus_governance("What exact fungicide rate should I apply to Ontario corn tomorrow?", [candidate_docs["ask_science_w2948372212"]], policy)
    assert not allowed
    assert blocked[0]["reason"] == "not_decisive_for_high_consequence"


def test_weather_estimates_and_historical_economics_remain_bounded():
    rows = {row["source_id"]: row for row in _rows(ROOT / SEED)}
    assert "2014-2015" in rows["W2948372212"]["text"]
    assert "no current prices" in rows["W2948372212"]["text"]
    weather = rows["W3184228112"]["text"]
    assert "V4 release in the 2021 paper" in weather
    assert "estimate rather than a field rain gauge or a seasonal forecast" in weather
    for row in rows.values():
        assert "$" not in row["text"]
        assert "benchmark" not in row["text"] and "expected_answer" not in json.dumps(row)
    coverage = _json(ROOT / REGISTRY)["batch_coverage"]
    assert len(coverage["deferred_knowledge_source_ids"]) == 18
    assert "development-only" in coverage["scenario_admission"]
