"""Feedback summaries and mapped context cannot invent execution or coverage."""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

import agronomy_agent.server.app as app_module
from agronomy_agent.server.app import _change_proposal_gates, _geo_priors_for_location, _present_geo_priors
from agronomy_agent.server.services.eval_service import eval_run_gates, eval_run_metrics
from agronomy_agent.server.services.export_service import (
    _demo_eval_run_record,
    build_phase6_demo_eval_snapshot,
    build_phase6_demo_eval_snapshot_markdown,
)
from agronomy_agent.server.settings import build_settings

OWNER = {"X-Agronomy-User-Email": "checkpoint-owner@example.test"}
OUTSIDER = {"X-Agronomy-User-Email": "checkpoint-outsider@example.test"}


def candidate(tags=()):
    return {"id": "synthetic-reviewed-feedback", "target_component": "answer", "review_status": "approved_for_suite",
            "payload": {"feedback": {"ideal_answer": "Synthetic expected answer", "failure_tags": list(tags)}}}


def test_clear_feedback_is_not_executed_regression_or_rollout_authority():
    metrics = eval_run_metrics([candidate()])
    gates = eval_run_gates(metrics)
    assert metrics["evidence_kind"] == gates["evidence_kind"] == "review_feedback_summary"
    assert metrics["execution_status"] == gates["execution_status"] == "not_run"
    assert metrics["no_reported_failure_count"] == 1
    assert metrics["no_reported_failure_rate"] == 1.0
    assert "pass_rate" not in metrics and "pass_count" not in metrics
    assert gates["feedback_clear"] is True
    assert gates["regression_suite"] is None
    assert gates["promotion_allowed"] is False
    assert "regression_not_executed" in gates["reasons"]


def test_reported_failures_and_review_counts_remain_explicit():
    metrics = eval_run_metrics([candidate(["wrong_unit"]), candidate()])
    assert metrics["candidate_count"] == metrics["reviewed_count"] == metrics["ideal_answer_count"] == 2
    assert metrics["failure_case_count"] == metrics["no_reported_failure_count"] == 1
    assert metrics["failure_tag_counts"] == {"wrong_unit": 1}
    assert metrics["reported_failures"][0]["failure_tags"] == ["wrong_unit"]
    assert eval_run_gates(metrics)["reported_failures_present"] is True
    assert eval_run_gates(metrics)["promotion_allowed"] is False


def test_empty_feedback_has_no_observed_rate_or_promotion_claim():
    metrics = eval_run_metrics([])
    assert metrics["candidate_count"] == 0
    assert metrics["no_reported_failure_rate"] is None
    assert eval_run_gates(metrics)["promotion_allowed"] is False
    assert "no_candidates" in eval_run_gates(metrics)["reasons"]


@pytest.mark.parametrize("run", [None, {"status": "completed", "metrics": {"candidate_count": "unknown"},
                                        "gates": {"promotion_allowed": True, "regression_suite": "legacy"}}])
def test_missing_or_legacy_positive_gates_cannot_authorize_a_new_claim(run):
    original = deepcopy(run)
    gates = _change_proposal_gates(run)
    assert gates["promotion_allowed"] is False
    assert gates["regression_execution_status"] == "not_run"
    assert run == original


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    root = tmp_path_factory.mktemp("checkpoint-truthfulness")
    settings = build_settings(db_path=root / "synthetic.sqlite3", artifact_root=root / "artifacts", network_mode="offline")
    app = app_module.create_app(settings)
    client = TestClient(app)
    created = client.post("/api/demo/fields", headers=OWNER,
                          json={"name": "Synthetic legacy snapshot", "field": {}, "geometry": {"kind": "none"}})
    assert created.status_code == 201, created.text
    identity = client.get("/auth/me", headers=OWNER).json()
    user, workspace = identity["user"], identity["workspaces"][0]
    thread = client.post("/threads", headers=OWNER,
                         json={"workspace_id": workspace["id"], "title": "Synthetic reviewed feedback"})
    assert thread.status_code == 201, thread.text
    store = app.state.trace_store
    row = store.create_phase4_eval_candidate(thread=thread.json(), created_by_user_id=user["id"],
                                             payload={"target_component": "answer", "feedback": candidate()["payload"]["feedback"]})
    store.update_phase4_eval_candidate_status(candidate_id=row["id"], reviewed_by_user_id=user["id"],
                                             review_status="approved_for_suite")
    yield client, store, user, workspace, created.json()["field"]["id"]
    client.close()
    store._conn.close()


def test_eval_api_records_feedback_only_and_no_execution_job(runtime, monkeypatch):
    client, store, user, workspace, _ = runtime
    monkeypatch.setattr(app_module, "_corpus_audit", lambda *args: "synthetic-corpus-audit")
    response = client.post("/eval-runs", headers=OWNER,
                           json={"workspace_id": workspace["id"], "name": "Feedback summary"})
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["metrics"]["execution_status"] == run["gates"]["execution_status"] == "not_run"
    assert run["metadata"]["evidence_kind"] == "review_feedback_summary"
    assert run["metadata"]["execution_status"] == "not_run"
    assert "queue_backend" not in run["metadata"]
    assert run["gates"]["promotion_allowed"] is False
    assert run["metrics"]["reviewed_count"] == 1
    assert store.get_phase4_eval_run(run["id"]) == run
    proposal = client.post("/change-proposals", headers=OWNER,
                           json={"workspace_id": workspace["id"], "title": "Synthetic proposal", "target_component": "tool",
                                 "proposal_type": "tool_patch", "summary": "Synthetic review", "linked_eval_run_id": run["id"]})
    assert proposal.status_code == 201, proposal.text
    assert proposal.json()["gates"]["promotion_allowed"] is False


def test_legacy_run_and_proposal_flags_are_preserved_but_cannot_grant_new_rollout(runtime, monkeypatch):
    client, store, user, workspace, _ = runtime
    legacy = store.create_phase4_eval_run(workspace=workspace, created_by_user_id=user["id"], name="Legacy summary",
                candidate_ids=[], metrics={"candidate_count": 1, "pass_rate": 1.0},
                gates={"promotion_allowed": True, "regression_suite": "local_trace_feedback_regression_v1"})
    proposal = store.create_phase4_change_proposal(workspace=workspace, created_by_user_id=user["id"],
                payload={"title": "Legacy proposal", "target_component": "tool", "proposal_type": "tool_patch",
                         "summary": "Historical declaration", "linked_eval_run_id": legacy["id"]},
                gates={"promotion_allowed": True})
    saved = json.dumps([legacy, proposal], sort_keys=True)
    reads = []
    original = store.get_phase4_eval_run
    def get_run(run_id):
        reads.append(run_id)
        return original(run_id)
    monkeypatch.setattr(store, "get_phase4_eval_run", get_run)
    path = f"/change-proposals/{proposal['id']}/review"
    denied = client.post(path, headers=OUTSIDER, json={"review_status": "approved_for_rollout"})
    assert denied.status_code == 403, denied.text
    assert reads == []
    for _ in range(2):
        rejected = client.post(path, headers=OWNER, json={"review_status": "approved_for_rollout"})
        assert rejected.status_code == 400, rejected.text
        assert "not executed regression evidence" in rejected.json()["detail"]
    assert json.dumps([original(legacy["id"]), store.get_phase4_change_proposal(proposal["id"])], sort_keys=True) == saved


def test_unauthorized_eval_request_never_reads_private_feedback(runtime, monkeypatch):
    client, store, _, workspace, _ = runtime
    def forbidden(*args, **kwargs):
        raise AssertionError("private feedback read before authorization")
    monkeypatch.setattr(store, "list_phase4_eval_candidates", forbidden)
    response = client.post("/eval-runs", headers=OUTSIDER,
                           json={"workspace_id": workspace["id"], "name": "Forbidden"})
    assert response.status_code == 403, response.text


@pytest.mark.parametrize("text", ["crop on sandy field", "symptoms on wheat", "Ontario", "Iowa", "Manitoba"])
def test_declared_location_text_does_not_fabricate_mapped_candidates(text):
    priors = _geo_priors_for_location(text)
    assert priors["location_text"] == text
    assert priors["candidate_regions"] == []
    assert priors["evidence"] == []
    assert priors["uncertainty"] == "unknown"
    assert "confidence" not in json.dumps(priors)


def verified_intersection():
    # The legitimate code deliberately contains STUB; only known legacy IDs may be removed.
    return {"layer_id": "reviewed_survey", "name": "Synthetic source polygon", "system": "Verified survey",
            "code": "SURVEY_STUB_VALID", "source": "synthetic-hash-bound-map", "source_sha256": "1" * 64,
            "confidence": 0.91, "coverage_estimate": 0.75, "match_reason": "polygon intersection"}


def old_geo_snapshot():
    official = verified_intersection()
    return {"location_text": "Declared region retained", "uncertainty": "medium", "used_as_prior_only": True,
            "candidate_regions": [{"source": "local_rule_stub", "code": "MLRA_103", "confidence": 0.58},
                                  {"source": "old_unknown", "code": "GL_ON_STUB", "confidence": 0.6}, official],
            "regional_intersections": [official], "evidence": ["string_match:great_lakes", "official_polygon_intersection"],
            "regional_feature_collection": {"type": "FeatureCollection", "features": []}}


def test_legacy_projection_is_nonmutating_idempotent_and_preserves_verified_coverage():
    stored = old_geo_snapshot()
    before = json.dumps(stored, sort_keys=True)
    result = _present_geo_priors(stored)
    assert result["candidate_regions"] == [verified_intersection()]
    assert result["regional_intersections"] == stored["regional_intersections"]
    assert result["location_text"] == stored["location_text"]
    assert result["evidence"] == ["official_polygon_intersection"]
    assert result["presentation"]["legacy_text_candidates_excluded"] is True
    assert _present_geo_priors(result) == result
    result["regional_intersections"][0]["coverage_estimate"] = 0
    assert json.dumps(stored, sort_keys=True) == before


def test_legacy_only_projection_remains_unknown_and_idempotent():
    snapshot = old_geo_snapshot()
    snapshot["candidate_regions"] = snapshot["candidate_regions"][:2]
    snapshot["regional_intersections"] = []
    result = _present_geo_priors(snapshot)
    assert result["candidate_regions"] == []
    assert result["uncertainty"] == "unknown"
    assert _present_geo_priors(result) == result


def test_saved_legacy_geo_response_excludes_stubs_without_rewriting_storage(runtime):
    client, store, user, _, field_id = runtime
    record = store.get_phase4_field_context(field_id)
    metadata = deepcopy(record["metadata"])
    metadata["open_agronomy_agent"]["geo_priors"] = old_geo_snapshot()
    store.update_phase4_field_context(field_context_id=field_id, actor_user_id=user["id"], payload={"metadata": metadata})
    raw = lambda: store._conn.execute("SELECT metadata FROM phase4_field_contexts WHERE id = ?", (field_id,)).fetchone()[0]
    before = raw()
    views = []
    for _ in range(2):
        response = client.get("/api/demo/fields", headers=OWNER)
        assert response.status_code == 200, response.text
        field = next(row for row in response.json()["fields"] if row["id"] == field_id)
        views.append(field["geoPriors"])
        assert field["geoPriors"]["candidate_regions"] == [verified_intersection()]
        assert field["geoPriors"]["regional_intersections"] == [verified_intersection()]
        assert raw() == before
    assert views[0] == views[1]


@pytest.mark.parametrize("mapped", [False, True])
def test_public_lookup_preserves_official_geometry_result_and_unknown_coverage(runtime, monkeypatch, mapped):
    client, _, _, _, _ = runtime
    intersections = [verified_intersection()] if mapped else []
    monkeypatch.setattr(app_module, "intersect_region_layers", lambda **kwargs: {
        "intersections": intersections, "feature_collection": {"type": "FeatureCollection", "features": []}, "errors": []})
    statuses = [{"layer_id": "reviewed_survey", "status": "available" if mapped else "not_installed"}]
    monkeypatch.setattr(app_module, "official_layer_status", lambda result: statuses)
    response = client.post("/api/geo/priors", json={"location_text": "crop on sandy field",
                           "geometry": {"type": "Point", "coordinates": [-100, 50]}})
    assert response.status_code == 200, response.text
    priors = response.json()
    assert priors["location_text"] == "crop on sandy field"
    assert priors["regional_intersections"] == intersections
    assert priors["official_layer_status"] == statuses
    if mapped:
        assert priors["candidate_regions"][0]["source"] == intersections[0]["source"]
        assert priors["candidate_regions"][0]["code"] == intersections[0]["code"]
        assert priors["candidate_regions"][0]["confidence"] == intersections[0]["confidence"]
    else:
        assert priors["candidate_regions"] == []
        assert priors["uncertainty"] == "unknown"


@pytest.mark.parametrize("metrics", [{}, {"candidate_count": "unknown", "failure_case_count": False},
                                    {"candidate_count": -1, "failure_case_count": -1}])
def test_export_projection_keeps_missing_or_invalid_feedback_counts_unknown(metrics):
    run = {"id": "legacy", "status": "completed", "metrics": metrics,
           "gates": {"promotion_allowed": True, "regression_suite": "local_trace_feedback_regression_v1"}}
    before = deepcopy(run)
    result = _demo_eval_run_record(run)
    assert result["candidate_count"] is result["failure_case_count"] is None
    assert result["pass_rate"] is result["regression_suite"] is None
    assert result["no_reported_failure_count"] is result["no_reported_failure_rate"] is None
    assert result["execution_status"] == "not_run"
    assert result["promotion_allowed"] is False
    assert _demo_eval_run_record(run) == result
    assert run == before


@pytest.mark.parametrize("runs", [[], [{"id": "unknown", "status": "completed", "metrics": {}}]])
def test_feedback_snapshot_does_not_invent_zero_quality_or_regression_identity(runs):
    before = deepcopy(runs)
    report = build_phase6_demo_eval_snapshot(thread={"id": "synthetic", "workspace_id": "synthetic"},
                                           events=[], eval_runs=runs, eval_candidates=[])
    assert report["eval_summary"]["latest_pass_rate"] is None
    assert report["eval_summary"]["latest_candidate_count"] is None
    assert report["eval_summary"]["reported_failure_count"] is None
    assert report["model_and_corpus_versions"]["eval_suite"] is None
    assert report["gate_status"]["execution_status"] == "not_run"
    assert report["gate_status"]["promotion_allowed"] is False
    markdown = build_phase6_demo_eval_snapshot_markdown(report, {"report_id": "synthetic"})
    assert "pass rate" not in markdown.lower() and "pass_rate" not in markdown
    assert "local_trace_feedback_regression_v1" not in markdown
    assert "not_run" in markdown
    assert runs == before


def test_feedback_snapshot_preserves_new_and_legacy_reported_failure_counts():
    metrics = eval_run_metrics([candidate(["wrong_unit"]), candidate()])
    runs = [{"id": "new", "name": "Current feedback", "status": "completed", "metrics": metrics,
             "gates": eval_run_gates(metrics)},
            {"id": "legacy", "name": "Historical feedback", "status": "completed",
             "metrics": {"candidate_count": 3, "failure_case_count": 1, "pass_rate": 0.6667},
             "gates": {"promotion_allowed": True, "regression_suite": "local_trace_feedback_regression_v1"}}]
    before = deepcopy(runs)
    report = build_phase6_demo_eval_snapshot(thread={"id": "synthetic", "workspace_id": "synthetic"}, events=[],
                                           eval_runs=runs, eval_candidates=[candidate(["wrong_unit"]), candidate()])
    summary = report["eval_summary"]
    assert summary["completed_feedback_summary_count"] == summary["reviewed_candidate_count"] == 2
    assert summary["reported_failure_count"] == 2
    assert summary["latest_candidate_count"] == 2 and summary["latest_failure_case_count"] == 1
    assert summary["latest_no_reported_failure_count"] == 1 and summary["latest_no_reported_failure_rate"] == 0.5
    assert summary["promotion_ready_run_count"] == 0
    for row in report["included_eval_runs"]:
        assert row["evidence_kind"] == "review_feedback_summary" and row["execution_status"] == "not_run"
        assert row["promotion_allowed"] is False and row["pass_rate"] is row["regression_suite"] is None
    assert report["included_eval_runs"][1]["failure_case_count"] == 1
    assert runs == before


def test_authorized_feedback_export_and_readback_preserve_historical_rows(runtime, monkeypatch):
    client, store, user, workspace, _ = runtime
    metrics = eval_run_metrics([candidate(["wrong_unit"]), candidate()])
    current = store.create_phase4_eval_run(workspace=workspace, created_by_user_id=user["id"], name="Export current",
                                         candidate_ids=[], metrics=metrics, gates=eval_run_gates(metrics))
    legacy = store.create_phase4_eval_run(workspace=workspace, created_by_user_id=user["id"], name="Export historical",
                                        candidate_ids=[], metrics={"candidate_count": 3, "failure_case_count": 1, "pass_rate": 1.0},
                                        gates={"promotion_allowed": True, "regression_suite": "local_trace_feedback_regression_v1"},
                                        metadata={"historical_evidence": "Preserve exact stored JSON"})
    thread_id = store.list_phase4_threads(workspace["id"])[0]["id"]
    raw_rows = lambda: [tuple(row) for row in store._conn.execute(
        "SELECT * FROM phase4_eval_runs WHERE workspace_id = ? ORDER BY id", (workspace["id"],)).fetchall()]
    before = raw_rows()
    path = f"/threads/{thread_id}/exports"
    def forbidden(*args, **kwargs):
        raise AssertionError("feedback read before export authorization")
    with monkeypatch.context() as denied:
        denied.setattr(store, "list_phase4_eval_runs", forbidden)
        denied.setattr(store, "list_phase4_eval_candidates", forbidden)
        response = client.post(path, headers=OUTSIDER, json={"export_type": "demo_eval_snapshot"})
        assert response.status_code == 403, response.text
    for _ in range(2):
        response = client.post(path, headers=OWNER, json={"export_type": "demo_eval_snapshot"})
        assert response.status_code == 202, response.text
        body = response.json()
        report = body["report"]
        assert report["eval_summary"]["execution_status"] == "not_run"
        assert report["eval_summary"]["latest_pass_rate"] is None
        assert report["eval_summary"]["promotion_ready_run_count"] == 0
        assert report["gate_status"]["promotion_allowed"] is False
        assert report["model_and_corpus_versions"]["eval_suite"] is None
        assert any(row["name"] == current["name"] and row["failure_case_count"] == 1
                   for row in report["included_eval_runs"])
        assert any(row["name"] == legacy["name"] and row["candidate_count"] == 3 and row["promotion_allowed"] is False
                   for row in report["included_eval_runs"])
        export_id = body["export"]["id"]
        download = f"/exports/{export_id}/download"
        assert client.get(download, headers=OUTSIDER).status_code == 403
        listing = client.get(download, headers=OWNER)
        assert listing.status_code == 200, listing.text
        assert {row["file"] for row in listing.json()["files"]} == {
            "phase6_report_manifest.json", "demo_eval_snapshot.md", "demo_eval_snapshot.pdf"}
        for filename in ("phase6_report_manifest.json", "demo_eval_snapshot.md", "demo_eval_snapshot.pdf"):
            assert client.get(download, headers=OUTSIDER, params={"filename": filename}).status_code == 403
            artifact = client.get(download, headers=OWNER, params={"filename": filename})
            assert artifact.status_code == 200, artifact.text
            if filename.endswith(".json"):
                assert artifact.json() == body["manifest"]
            elif filename.endswith(".md"):
                assert "Stored Feedback Summary" in artifact.text and "not_run" in artifact.text
                assert "1 reported failure cases" in artifact.text
                assert "current promotion allowed False" in artifact.text
                assert "pass rate" not in artifact.text.lower() and "pass_rate" not in artifact.text
                assert "local_trace_feedback_regression_v1" not in artifact.text
            else:
                assert artifact.content.startswith(b"%PDF")
        assert raw_rows() == before
