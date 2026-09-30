from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("retrieval_scoring", ROOT / "scripts/evaluate_offline_corpus_retrieval.py")
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)


def doc(source: str, tier_path: str = "fixture"):
    return SimpleNamespace(doc_id=source, source_id=source, corpus_path=tier_path,
                           source_locator={}, retrieval_policy="context_only",
                           transfer_scope=None, applicability_boundary=None, tags=())


def case(expected, **kwargs):
    return {"case_id": "fixture", "partition": "test", "case_status": "active", "expected_source_ids": expected, **kwargs}


def test_positive_metrics_exclude_negative_control_denominators(monkeypatch):
    monkeypatch.setattr(scorer, "RESAMPLES", 20)
    positive = scorer._case_result(case(["expected"]), [doc("expected")], {}, 1)
    negative = scorer._case_result(case([], forbidden_evidence_tiers=["community_experience"]), [], {}, 1)
    summary = scorer.summarize_results([positive, negative])
    assert negative["recall_at"]["7"] is None
    assert negative["ndcg_at_7"] is None
    assert summary["recall_at_7"]["mean"] == 1
    assert summary["recall_at_7"]["denominator"] == 1
    assert summary["negative_control_compliance_rate"]["denominator"] == 1


def test_recall_counts_all_expected_sources_and_ndcg_deduplicates_chunks():
    first = doc("a")
    duplicate = doc("a")
    duplicate.doc_id = "a-second-chunk"
    row = scorer._case_result(case(["a", "b"]), [first, duplicate], {}, 1)
    assert row["recall_at"]["7"] == .5
    assert row["ndcg_at_7"] < 1


def test_multiple_negative_authority_constraints_are_conjunctive():
    row = scorer._case_result(case([], expect_no_us_analogue_context=True, expect_no_admitted_community_context=True),
                              [doc("us")], {"fixture": "US_government_analogue_reference"}, 1)
    assert row["negative_control_compliant"] is False
    assert row["authority_compliant"] is False


def test_empty_populations_remain_unknown_and_policy_is_explicit(monkeypatch):
    monkeypatch.setattr(scorer, "RESAMPLES", 20)
    report = {"failed_case_count": 0, "executed_case_count": 1, "blocked_case_count": 1,
              "summary": scorer.summarize_results([])}
    assert report["summary"]["recall_at_7"]["mean"] is None
    assert scorer.evaluation_gate(report)["passed"] is True
    assert not scorer.evaluation_gate(report, {"minimum_rates": {"recall_at_7": .5}})["passed"]
    assert not scorer.evaluation_gate(report, {"require_no_blocked_cases": True})["passed"]
    with pytest.raises(ValueError, match="unknown"):
        scorer.evaluation_gate(report, {"minimum_rates": {"imagined_metric": 1}})


def test_evaluate_retains_blocked_and_failed_rows_and_provenance(tmp_path, monkeypatch):
    import agronomy_agent.evals as evals
    monkeypatch.setattr(scorer, "RESAMPLES", 20)
    rows = [case(["expected"], question="retrieve"), {"case_id": "blocked", "partition": "test", "case_status": "blocked_missing_source", "blocking_reason": "not admitted"}]
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps(row) for row in rows))
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps({"suite_id": "test", "suite_sha256": "declared", "case_file_sha256": scorer._sha256(cases)}))
    config = tmp_path / "config.yaml"
    config.write_text("retrieval: {}")
    def fail(*args, **kwargs):
        raise RuntimeError("retrieval fixture failed")
    monkeypatch.setattr(scorer, "load_agent_resources", lambda _: SimpleNamespace(retriever=SimpleNamespace(search=fail), on_demand_releases=[]))
    monkeypatch.setattr(scorer, "_policy_tiers", lambda *_: {})
    monkeypatch.setattr(evals, "build_rag_artifact_identity", lambda _: [{"sha256": "source"}])
    report = scorer.evaluate(config_path=config, case_path=cases, suite_path=suite)
    assert report["case_count"] == 2
    assert report["failed_case_count"] == report["blocked_case_count"] == 1
    assert report["status"] == "blocked"
    assert report["results"][1]["blocking_reason"] == "not admitted"
    assert report["config_sha256"] == scorer._sha256(config)
    assert report["implementation"]["sha256"]
    assert report["source_artifacts"][0]["sha256"] == "source"
    cases.write_text(cases.read_text() + "\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        scorer.evaluate(config_path=config, case_path=cases, suite_path=suite)


def test_empty_expected_sources_without_negative_contract_are_unscored():
    row = scorer._case_result(case([]), [], {}, 1)
    assert row["metric_population"] == "unscored_no_contract"
    assert row["negative_control_compliant"] is None
