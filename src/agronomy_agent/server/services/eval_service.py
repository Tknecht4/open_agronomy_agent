from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def eval_run_metrics(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    failure_tag_counts: dict[str, int] = {}
    target_component_counts: dict[str, int] = {}
    regression_failures: list[dict[str, Any]] = []
    ideal_answer_count = 0
    human_correction_count = 0
    training_consent_count = 0
    for candidate in candidates:
        target = str(candidate.get("target_component") or "unknown")
        target_component_counts[target] = target_component_counts.get(target, 0) + 1
        feedback = (candidate.get("payload") or {}).get("feedback") or {}
        failure_tags = [str(tag) for tag in feedback.get("failure_tags", []) or []]
        for tag_key in failure_tags:
            failure_tag_counts[tag_key] = failure_tag_counts.get(tag_key, 0) + 1
        has_ideal_answer = bool(str(feedback.get("ideal_answer") or "").strip())
        has_human_correction = bool(str(feedback.get("human_correction") or "").strip())
        if has_ideal_answer:
            ideal_answer_count += 1
        if has_human_correction:
            human_correction_count += 1
        if feedback.get("training_consent"):
            training_consent_count += 1
        if failure_tags:
            regression_failures.append(
                {
                    "candidate_id": candidate["id"],
                    "target_component": target,
                    "failure_tags": failure_tags,
                    "has_ideal_answer": has_ideal_answer,
                    "has_human_correction": has_human_correction,
                },
            )
    candidate_count = len(candidates)
    failure_case_count = len(regression_failures)
    pass_count = candidate_count - failure_case_count
    return {
        "candidate_count": candidate_count,
        "target_component_counts": target_component_counts,
        "failure_tag_counts": failure_tag_counts,
        "approved_count": sum(1 for candidate in candidates if candidate.get("review_status") == "approved_for_suite"),
        "reviewed_count": sum(1 for candidate in candidates if candidate.get("review_status") in {"approved_for_suite", "promoted"}),
        "ideal_answer_count": ideal_answer_count,
        "human_correction_count": human_correction_count,
        "training_consent_count": training_consent_count,
        "failure_case_count": failure_case_count,
        "pass_count": pass_count,
        "pass_rate": round(pass_count / candidate_count, 4) if candidate_count else 0.0,
        "regression_failures": regression_failures,
    }


def eval_run_gates(metrics: dict[str, Any]) -> dict[str, Any]:
    candidate_count = int(metrics.get("candidate_count") or 0)
    failure_case_count = int(metrics.get("failure_case_count") or 0)
    reviewed_count = int(metrics.get("reviewed_count") or 0)
    ideal_answer_count = int(metrics.get("ideal_answer_count") or 0)
    reasons: list[str] = []
    if candidate_count <= 0:
        reasons.append("no_candidates")
    if reviewed_count != candidate_count:
        reasons.append("not_all_candidates_reviewed")
    if failure_case_count > 0:
        reasons.append("regression_failures_present")
    if ideal_answer_count != candidate_count:
        reasons.append("missing_ideal_answers")
    promotion_allowed = candidate_count > 0 and not reasons
    return {
        "requires_reviewed_candidates": True,
        "requires_passing_regression": True,
        "requires_ideal_answers": True,
        "candidate_count_positive": candidate_count > 0,
        "all_candidates_reviewed": reviewed_count == candidate_count and candidate_count > 0,
        "regression_suite": "local_trace_feedback_regression_v1",
        "regression_failures_present": failure_case_count > 0,
        "promotion_allowed": promotion_allowed,
        "reasons": reasons,
    }


def run_eval_run(store: Any, run_id: str, *, worker_name: str = "local_worker") -> dict[str, Any]:
    run = store.get_phase4_eval_run(run_id)
    if not run:
        raise ValueError(f"eval run not found: {run_id}")

    started_at = _now_iso()
    store.update_phase4_eval_run(
        run_id=run_id,
        status="running",
        metadata={"worker": worker_name},
        started_at=started_at,
    )
    candidate_ids = [str(candidate_id) for candidate_id in run.get("candidate_ids", [])]
    candidate_id_set = set(candidate_ids)
    candidates_by_id = {
        candidate["id"]: candidate
        for candidate in store.list_phase4_eval_candidates(run["workspace_id"])
        if candidate["id"] in candidate_id_set
    }
    missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in candidates_by_id]
    if missing:
        return store.update_phase4_eval_run(
            run_id=run_id,
            status="failed",
            metadata={"worker": worker_name, "error": "eval candidate not found", "missing_candidate_ids": missing},
            finished_at=_now_iso(),
        ) or {}
    candidates = [candidates_by_id[candidate_id] for candidate_id in candidate_ids]
    if not candidates:
        return store.update_phase4_eval_run(
            run_id=run_id,
            status="failed",
            metadata={"worker": worker_name, "error": "eval run requires at least one reviewed candidate"},
            finished_at=_now_iso(),
        ) or {}

    metrics = eval_run_metrics(candidates)
    gates = eval_run_gates(metrics)
    return store.update_phase4_eval_run(
        run_id=run_id,
        status="completed",
        metrics=metrics,
        gates=gates,
        metadata={"worker": worker_name},
        finished_at=_now_iso(),
    ) or {}


def run_queued_eval_runs(store: Any, *, limit: int = 1, worker_name: str = "local_worker") -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be > 0")
    runs = store.list_phase4_queued_eval_runs(limit=limit)
    return run_eval_run_ids(store, [run["id"] for run in runs], requested_limit=limit, worker_name=worker_name, queue_name="eval")


def run_eval_run_ids(
    store: Any,
    run_ids: list[str],
    *,
    requested_limit: int,
    worker_name: str = "local_worker",
    queue_name: str = "eval",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for run_id in run_ids:
        try:
            result = run_eval_run(store, run_id, worker_name=worker_name)
        except Exception as exc:
            result = store.update_phase4_eval_run(
                run_id=run_id,
                status="failed",
                metadata={"worker": worker_name, "unhandled_error": exc.__class__.__name__, "error": str(exc)},
                finished_at=_now_iso(),
            ) or {"id": run_id, "status": "failed"}
        results.append(result)
    return {
        "queue": queue_name,
        "worker": worker_name,
        "requested_limit": requested_limit,
        "processed": len(results),
        "completed": sum(1 for item in results if item.get("status") == "completed"),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "run_ids": [item.get("id") for item in results],
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
