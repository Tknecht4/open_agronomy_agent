"""Tiny synthetic closeouts; never load the real answers or call a model."""
import hashlib
import json
from pathlib import Path

import pytest

from agronomy_agent.release_eval_diagnostic_inputs import read_six_cell_closeout


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def seal(root):
    pins = [{"path": str(p), "bytes": p.stat().st_size, "sha256": sha(p.read_bytes())}
            for p in sorted(root.iterdir()) if p.name != "closure-seal-v1.json"]
    write(root / "closure-seal-v1.json", {
        "schema": "open_agronomy_agent.six_cell_final_closure.v1", "root": str(root),
        "files": pins, "file_count": len(pins), "total_bytes": sum(p["bytes"] for p in pins),
    })


@pytest.fixture
def closeout(tmp_path):
    root = tmp_path.resolve() / "closeout"
    root.mkdir()
    models = {
        "gemma_e2b": ("mlx-community/gemma-4-e2b-it-4bit", "238767527555cb75a05732a84dff5d6ba0dd6809"),
        "gemma_e4b": ("mlx-community/gemma-4-e4b-it-4bit", "475b9088d29754a3379866cf5aeb6b41acd313c2"),
        "luna_medium": ("gpt-6-luna", None),
    }
    case, rows, answers = "synthetic::boundary", [], []
    external = str(root.parent / "never-follow" / "runtime.sqlite3")
    for backend, (model, revision) in models.items():
        for arm in ["raw_model", "production_full"]:
            answer = f"{backend}/{arm} — synthetic answer."
            row = {"observation_id": digest([backend, arm]), "backend_id": backend,
                   "arm_id": arm, "case_sha256": digest(case), "case_input_sha256": digest("inputs"),
                   "model_id": model, "model_revision": revision, "status": "completed",
                   "worker_exit_code": 0, "model_execution_eligible": backend != "luna_medium",
                   "claim_eligible": False, "domain_eligible": False, "domain_quality": None,
                   "answer_utf8_sha256": sha(answer.encode()), "ledger_answer_identity_sha256": digest(answer),
                   "elapsed_seconds": 1.5, "prompt_tokens": 10, "generation_tokens": 5,
                   "finish_reason": "length" if backend == "gemma_e2b" and arm == "raw_model" else "stop",
                   "unknown": [{"id": "semantic_review", "detail": "No expert labels."}],
                   "archive": {"path": external, "bytes": 1, "sha256": "0" * 64}}
            if backend == "luna_medium":
                row.update(identity_status="catalog_verified_response_observed",
                           original_helper_receipt_status="failed", effective_reasoning_effort_observed=False)
            rows.append(row)
            answers.append({"observation_id": row["observation_id"], "backend_id": backend, "arm_id": arm,
                            "answer": answer, "answer_utf8_sha256": row["answer_utf8_sha256"],
                            "ledger_answer_identity_sha256": digest(answer), "elapsed_seconds": 1.5,
                            "native_weight_model_execution_eligible": row["model_execution_eligible"],
                            "row_status": "completed"})
    collection = {"case_id": case, "entries": rows, "observations_completed": 6, "exposed_cases": 1,
                  "semantic_expert_labels": 0, "trials_per_model_arm": 1, "native_weight_eligible_observations": 4,
                  "catalog_response_observed_remote_observations_native_weight_ineligible": 2,
                  "full_suite_executed": False, "current_JLens_executed": False,
                  "historical_bounded_CUDA_JLens": "Separate historical result."}
    hc = {"exposed_case_id": case, "actual_completed_observations": 6, "cases": 1,
          "independent_semantic_labels": 0, "trials_per_model_arm": 1, "native_weight_eligible_observations": 4,
          "remote_catalog_response_observed_native_weight_ineligible": 2, "all_claim_and_domain_flags_false": True,
          "full_suite_executed": False, "current_JLens_executed": False,
          "models": [[m, r or "unobserved remote revision"] for m, r in models.values()]}
    source = {"head": "1" * 40, "source_sha256": "2" * 64, "worktree": external, "clean": True}
    documents = {
        "actual-answers-v1.json": ("actual_six_cell_answer_readout.v1", {
            "case_id": case, "question": "Synthetic question?", "same_safe_case_all_six": True, "answers": answers}),
        "collection-observations-v1.json": ("six_cell_completed_observations.v1", collection),
        "root-final-handoff-v1.json": ("six_cell_final_evidence_handoff.v1", {
            "collection": hc, "source": source, "remaining_limits": ["One exposed case; no grades."],
            "Luna_original_receipts": [{"arm": a, "original_status": "failed", "original_receipt": {"path": external}}
                                      for a in ["raw-model", "production-full"]]}),
        "retained-grounding-readout-v1.json": ("six_cell_retained_grounding_readout.v1", {
            "entries": [{"backend_id": b, "arm_id": "production_full", "source_grounded": False,
                         "draft_final_equal": True, "verification_triggered": False,
                         "verification_action": "not_triggered", "retrieved_doc_ids": ["synthetic_context"],
                         "compressed_trace": {"path": external}} for b in models]}),
        "final-retained-inspection-v1.json": ("six_cell_final_retained_inspection.v1", {
            "source_head": source["head"], "source_sha256": source["source_sha256"]}),
        "paired-answer-findings-v1.json": ("six_cell_paired_answer_interpretation.v1", {}),
        "terminal-accounting-v1.json": ("six_cell_terminal_reconciled_accounting.v1", {}),
    }
    for name, (schema, value) in documents.items():
        write(root / name, {"schema": "open_agronomy_agent." + schema, **value})
    for name in ["delayed-account.json", "native-execution-file-seal-v1.json", "original-luna-file-seal-v1.json"]:
        write(root / name, {"reference_only": external})
    (root / "paired-answer-analysis-v1.md").write_text("Synthetic analyst note; no grades.")
    seal(root)
    return root


def change(root, name, mutate):
    path = root / name
    value = json.loads(path.read_text())
    mutate(value)
    write(path, value)
    seal(root)


def test_projection_preserves_limits_failures_and_hash_scope(closeout):
    result = read_six_cell_closeout(closeout)
    assert result["plan"]["schema_version"] == "open_agronomy_agent.diagnostic_projection.v1"
    assert len(result["plan"]["cases"]) == 1 and len(result["observations"]) == 6
    assert result["reviews"] == [] and result["comparison_cohort"] is None
    for row in result["observations"]:
        assert row["answer_sha256"] == digest(row["answer"])
        assert row["task_input_sha256"] == digest("inputs")
        assert row["domain_quality"] is None and row["claim_eligible"] is False
        if row["backend_id"] == "luna_medium":
            assert row["model_execution_eligible"] is False and row["model_revision"] is None
            assert row["original_helper_receipt_status"] == "failed"
        if row["arm_id"] == "production_full":
            assert row["retained_grounding"]["source_grounded"] is False


def test_changed_pinned_bytes_refused(closeout):
    (closeout / "paired-answer-analysis-v1.md").write_text("Changed")
    with pytest.raises(ValueError, match="pin mismatch"):
        read_six_cell_closeout(closeout)


@pytest.mark.parametrize("field,value,reason", [
    ("answer_utf8_sha256", "0" * 64, "UTF-8"),
    ("ledger_answer_identity_sha256", "0" * 64, "ledger string"),
    ("case_sha256", "0" * 64, "case/task"),
    ("model_id", "different", "model metadata"),
    ("claim_eligible", True, "domain flags"),
    ("observation_id", "0" * 64, "observation join"),
])
def test_resealed_semantic_corruption_refused(closeout, field, value, reason):
    change(closeout, "collection-observations-v1.json", lambda d: d["entries"][0].update({field: value}))
    with pytest.raises(ValueError, match=reason):
        read_six_cell_closeout(closeout)


@pytest.mark.parametrize("path", ["../actual-answers-v1.json", "/outside/actual-answers-v1.json"])
def test_manifest_escape_refused_before_following_path(closeout, path):
    p = closeout / "closure-seal-v1.json"
    d = json.loads(p.read_text()); d["files"][0]["path"] = path; write(p, d)
    with pytest.raises(ValueError, match="escaped"):
        read_six_cell_closeout(closeout)


def test_known_pin_symlink_refused(closeout):
    path = closeout / "actual-answers-v1.json"
    external = closeout.parent / "external.json"
    external.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(external)
    with pytest.raises(ValueError, match="linked file"):
        read_six_cell_closeout(closeout)


def test_oversized_pin_refused_without_large_fixture(closeout):
    p = closeout / "closure-seal-v1.json"
    d = json.loads(p.read_text()); d["files"][0]["bytes"] = 2 * 1024 * 1024 + 1; write(p, d)
    with pytest.raises(ValueError, match="pin byte cap"):
        read_six_cell_closeout(closeout)


def test_duplicate_observation_refused(closeout):
    change(closeout, "collection-observations-v1.json",
           lambda d: d["entries"][1].update(observation_id=d["entries"][0]["observation_id"]))
    with pytest.raises(ValueError, match="duplicate collection observation"):
        read_six_cell_closeout(closeout)


def test_schema_and_source_joins_refused(closeout):
    change(closeout, "final-retained-inspection-v1.json", lambda d: d.update(source_sha256="3" * 64))
    with pytest.raises(ValueError, match="inspection source"):
        read_six_cell_closeout(closeout)
