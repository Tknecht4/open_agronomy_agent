from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.phase5_sft import is_held_out_eval_trace
from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


OWNER = {"X-Agronomy-User-Email": "synthetic-sft-reviewer@example.test"}
EVAL = {
    "is_evaluation_case": True, "evaluation_suite_id": "synthetic-development-suite",
    "evaluation_case_id": "synthetic-case", "exposure": "exposed_development",
}
EVIDENCE = [{"doc_id": "synthetic-original-source"}]


@pytest.fixture
def environment(tmp_path):
    client = TestClient(create_app(build_settings(
        db_path=tmp_path / "synthetic-sft.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline",
    )))
    org = client.post("/orgs", headers=OWNER, json={"name": "Synthetic SFT org"})
    assert org.status_code == 201, org.text
    workspace_response = client.post("/workspaces", headers=OWNER, json={
        "organization_id": org.json()["id"], "name": "Synthetic SFT workspace",
    })
    assert workspace_response.status_code == 201, workspace_response.text
    workspace = workspace_response.json()
    store = client.app.state.trace_store
    thread = store.create_phase4_thread(
        workspace=workspace, created_by_user_id=workspace["created_by_user_id"],
        title="Synthetic provenance test", mode="baseline", trace_capture_level="full", training_eligible=True,
    )
    store.create_phase4_message(thread=thread, actor="user", content="Synthetic question.")
    assistant = store.create_phase4_message(thread=thread, actor="assistant", content="Synthetic answer.")
    trace_id = str(uuid.uuid4())
    store.create_phase5_turn_metrics({
        "trace_id": trace_id, "thread_id": thread["id"], "turn_id": assistant["id"],
        "workspace_id": workspace["id"], "model_id": "synthetic-model", "total_latency_ms": 1,
        "leak_check_passed": True,
    })
    return client, store, workspace, thread, trace_id, assistant


def _create(environment, labels=None, headers=OWNER):
    client, _, _, _, trace_id, _ = environment
    return client.post("/api/phase5/sft-candidates/from-trace", headers=headers, json={
        "trace_id": trace_id, "failure_class": "synthetic_failure",
        "labels": {"source_evidence": EVIDENCE, **(labels or {})},
    })


def _legacy_candidate(environment, labels=None):
    _, store, workspace, thread, trace_id, _ = environment
    return store.create_phase5_training_candidate({
        "workspace_id": workspace["id"], "thread_id": thread["id"], "trace_id": trace_id,
        "review_status": "approved", "consent_scope": "research_and_training_opt_in",
        "repair_layer": "training_candidate", "failure_class": "synthetic_failure",
        "messages": [{"role": "user", "content": "Synthetic question."}, {"role": "assistant", "content": "Synthetic answer."}],
        "labels": {"source_evidence": EVIDENCE, **(labels or {})},
    })


def _export(environment):
    client, _, workspace, _, _, _ = environment
    return client.get("/api/phase5/sft-candidates/export", headers=OWNER, params={"workspace_id": workspace["id"]})


@pytest.mark.parametrize("origin", ["thread", "message", "event", "span", "labels"])
def test_creation_blocks_exposed_development_lineage_at_every_persisted_source(environment, origin):
    client, store, workspace, thread, trace_id, assistant = environment
    labels = {}
    if origin == "thread":
        store.update_phase4_thread_metadata(thread["id"], metadata=EVAL)
    elif origin == "message":
        store.create_phase4_message(thread=thread, actor="user", content="Synthetic prior evaluation question.", metadata=EVAL)
    elif origin == "event":
        store.append_phase4_trace_event(thread=thread, event_type="synthetic_evaluation", payload={"metadata": EVAL})
    elif origin == "span":
        store.create_phase5_trace_spans([{
            "trace_id": trace_id, "thread_id": thread["id"], "turn_id": assistant["id"], "span_id": "synthetic-span",
            "stage": "synthetic", "start_ns": 0, "end_ns": 1, "duration_ms": 0.001, "status": "ok", "metadata": EVAL,
        }])
    else:
        labels = EVAL
    response = _create(environment, labels=labels)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["reason"] == "evaluation_lineage"
    assert store.list_phase5_training_candidates(workspace["id"]) == []


@pytest.mark.parametrize("origin", ["thread", "labels"])
def test_review_cannot_approve_legacy_candidate_after_lineage_was_shed(environment, origin):
    client, store, _, thread, _, _ = environment
    candidate = _legacy_candidate(environment, labels=EVAL if origin == "labels" else None)
    if origin == "thread":
        store.update_phase4_thread_metadata(thread["id"], metadata=EVAL)
    response = client.patch(f"/api/phase5/sft-candidates/{candidate['id']}/review", headers=OWNER, json={
        "review_status": "approved", "labels": {"is_evaluation_case": False, "split": "train"},
    })
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["reason"] == "evaluation_lineage"
    assert store.get_phase5_training_candidate(candidate["id"])["labels"].get("split") is None


def test_rejection_can_record_review_but_cannot_erase_evaluation_lineage(environment):
    client, store, _, _, _, _ = environment
    candidate = _legacy_candidate(environment, labels=EVAL)
    response = client.patch(f"/api/phase5/sft-candidates/{candidate['id']}/review", headers=OWNER, json={
        "review_status": "rejected", "labels": {"is_evaluation_case": False, "evaluation_suite_id": ""},
    })
    assert response.status_code == 200, response.text
    assert is_held_out_eval_trace(response.json())
    approved = client.patch(f"/api/phase5/sft-candidates/{candidate['id']}/review", headers=OWNER, json={"review_status": "approved"})
    assert approved.status_code == 400, approved.text
    assert store.get_phase5_training_candidate(candidate["id"])["review_status"] == "rejected"


@pytest.mark.parametrize("reason", ["evaluation_lineage", "unresolved_lineage", "thread_not_training_eligible", "prompt_leak_check_failed"])
def test_export_rechecks_legacy_originals_and_does_not_mark_exclusions_exported(environment, monkeypatch, reason):
    _, store, _, thread, trace_id, _ = environment
    candidate = _legacy_candidate(environment)
    if reason == "evaluation_lineage":
        store.update_phase4_thread_metadata(thread["id"], metadata=EVAL)
    elif reason == "unresolved_lineage":
        monkeypatch.setattr(store, "get_phase5_admin_trace", lambda _: None)
    elif reason == "thread_not_training_eligible":
        store.update_phase4_thread_consent(thread_id=thread["id"], actor_user_id=thread["created_by_user_id"], training_eligible=False)
    else:
        metrics = store.get_phase5_turn_metrics(trace_id)
        store.create_phase5_turn_metrics({**metrics, "leak_check_passed": False})
    response = _export(environment)
    assert response.status_code == 200, response.text
    assert response.json()["candidate_count"] == 0
    assert response.json()["records"] == []
    assert response.json()["jsonl"] == ""
    assert response.json()["excluded_records"] == [{"candidate_id": candidate["id"], "reason": reason}]
    assert store.get_phase5_training_candidate(candidate["id"])["exported_at"] is None


@pytest.mark.parametrize("mismatch", ["thread", "workspace", "trace", "turn", "user_turn", "admin_trace", "source_trace_id"])
def test_export_blocks_inconsistent_original_identity(environment, monkeypatch, mismatch):
    _, store, _, _, trace_id, _ = environment
    candidate = _legacy_candidate(environment, labels={"source_trace_id": "different"} if mismatch == "source_trace_id" else None)
    if mismatch != "source_trace_id":
        original = store.get_phase5_admin_trace(trace_id)
        if mismatch == "admin_trace":
            original["trace_id"] = str(uuid.uuid4())
        elif mismatch == "user_turn":
            original["metrics"]["turn_id"] = store.list_phase4_messages(original["metrics"]["thread_id"])[0]["id"]
        else:
            key = {"thread": "thread_id", "workspace": "workspace_id", "trace": "trace_id", "turn": "turn_id"}[mismatch]
            original["metrics"][key] = str(uuid.uuid4())
        monkeypatch.setattr(store, "get_phase5_admin_trace", lambda _: original)
    response = _export(environment)
    assert response.status_code == 200, response.text
    assert response.json()["excluded_records"] == [{"candidate_id": candidate["id"], "reason": "unresolved_lineage"}]
    assert store.get_phase5_training_candidate(candidate["id"])["exported_at"] is None


def test_authorized_original_source_can_be_reviewed_exported_and_retains_declarations(environment):
    client, store, _, thread, _, _ = environment
    store.update_phase4_thread_metadata(thread["id"], metadata={
        "is_evaluation_case": False, "source_dataset": "When2Call", "split": "train", "exposure": "exposed_research",
    })
    created = _create(environment)
    assert created.status_code == 201, created.text
    candidate = created.json()
    assert candidate["review_status"] == "pending"
    assert any(item.get("source_dataset") == "When2Call" for item in candidate["labels"]["source_lineage"])
    assert _export(environment).json()["candidate_count"] == 0  # review is still mandatory
    reviewed = client.patch(f"/api/phase5/sft-candidates/{candidate['id']}/review", headers=OWNER, json={"review_status": "approved"})
    assert reviewed.status_code == 200, reviewed.text
    exported = _export(environment)
    assert exported.status_code == 200, exported.text
    assert exported.json()["candidate_count"] == 1
    assert store.get_phase5_training_candidate(candidate["id"])["exported_at"]


def test_unknown_provenance_cannot_be_approved_or_exported(environment):
    client, store, _, thread, _, _ = environment
    candidate = _legacy_candidate(environment)
    store.update_phase4_thread_metadata(thread["id"], metadata={"provenance_status": "unknown"})
    review = client.patch(f"/api/phase5/sft-candidates/{candidate['id']}/review", headers=OWNER, json={"review_status": "approved"})
    assert review.status_code == 400, review.text
    assert _export(environment).json()["excluded_records"][0]["reason"] == "unresolved_lineage"


def test_new_review_evaluation_declaration_blocks_approval(environment):
    client, _, _, _, _, _ = environment
    created = _create(environment).json()
    response = client.patch(f"/api/phase5/sft-candidates/{created['id']}/review", headers=OWNER, json={
        "review_status": "approved", "labels": {"evaluation_answer_id": "synthetic-answer"},
    })
    assert response.status_code == 400, response.text


def test_legacy_non_evaluation_candidate_with_authoritative_original_remains_exportable(environment):
    _, store, _, _, _, _ = environment
    candidate = _legacy_candidate(environment)
    response = _export(environment)
    assert response.status_code == 200, response.text
    assert response.json()["candidate_count"] == 1
    assert response.json()["records"][0]["id"] == candidate["id"]
    assert store.get_phase5_training_candidate(candidate["id"])["exported_at"]


def test_missing_authoritative_original_blocks_legacy_approval(environment, monkeypatch):
    client, store, _, _, _, _ = environment
    candidate = _legacy_candidate(environment)
    monkeypatch.setattr(store, "get_phase5_admin_trace", lambda _: None)
    response = client.patch(f"/api/phase5/sft-candidates/{candidate['id']}/review", headers=OWNER, json={"review_status": "approved"})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["reason"] == "unresolved_lineage"
    assert store.get_phase5_training_candidate(candidate["id"])["reviewed_at"] is None


def test_auth_consent_and_evidence_gates_still_apply(environment):
    client, store, workspace, thread, _, _ = environment
    assert _create(environment, headers={}).status_code == 401
    denied = _create(environment, headers={"X-Agronomy-User-Email": "synthetic-outsider@example.test"})
    assert denied.status_code == 403, denied.text
    wrong_trace = _create(environment, labels={"source_trace_id": "different"})
    assert wrong_trace.status_code == 400, wrong_trace.text
    assert wrong_trace.json()["detail"]["reason"] == "unresolved_lineage"
    missing = _create(environment, labels={"source_evidence": []})
    assert missing.status_code == 400, missing.text
    assert missing.json()["detail"] == "source_evidence is required for SFT candidates"
    store.update_phase4_thread_consent(thread_id=thread["id"], actor_user_id=thread["created_by_user_id"], training_eligible=False)
    assert _create(environment).status_code == 400
    assert store.list_phase5_training_candidates(workspace["id"]) == []
