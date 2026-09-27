from __future__ import annotations

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
