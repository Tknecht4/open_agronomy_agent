from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


PASS_LABELS = {"pass", "passed", "accept", "accepted", "approved", "approved_for_suite", "promoted", "safe", "good", "true", "1", "yes"}
FAIL_LABELS = {"fail", "failed", "reject", "rejected", "blocked", "needs_eval", "pending", "unsafe", "bad", "false", "0", "no"}


def human_review_slice(
    rows: list[dict[str, Any]],
    *,
    min_pass_rate: float = 0.9,
    min_rubric_score: float = 3.0,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        passed, reasons = _human_pass(row, min_rubric_score=min_rubric_score)
        if not passed:
            failures.append({"id": _row_id(row), "reasons": reasons, "failure_tags": [str(tag) for tag in row.get("failure_tags", []) or []]})
    pass_rate = (len(rows) - len(failures)) / max(1, len(rows))
    return {
        "name": "human_review_slice",
        "samples": len(rows),
        "pass_rate": round(pass_rate, 4),
        "min_pass_rate": min_pass_rate,
        "min_rubric_score": min_rubric_score,
        "blocked": bool(rows) and pass_rate < min_pass_rate,
        "failures": failures,
    }


def judge_model_audit(
    rows: list[dict[str, Any]],
    *,
    threshold: float = 0.7,
    min_accuracy: float = 0.8,
    max_false_accept_rate: float = 0.1,
    min_calibration_samples: int = 3,
) -> dict[str, Any]:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("judge threshold must be between 0 and 1")
    if min_calibration_samples <= 0:
        raise ValueError("min_calibration_samples must be > 0")

    labeled = [_normalize_judge_row(row, threshold=threshold) for row in rows if _has_human_label(row)]
    confusion = Counter((row["human_pass"], row["judge_pass"]) for row in labeled)
    samples = len(labeled)
    true_accept = confusion[(True, True)]
    true_reject = confusion[(False, False)]
    false_accept = confusion[(False, True)]
    false_reject = confusion[(True, False)]
    accuracy = (true_accept + true_reject) / max(1, samples)
    false_accept_rate = false_accept / max(1, false_accept + true_reject)
    false_reject_rate = false_reject / max(1, false_reject + true_accept)
    mean_abs_error = (
        sum(abs(row["judge_score"] - (1.0 if row["human_pass"] else 0.0)) for row in labeled) / max(1, samples)
        if labeled
        else None
    )
    failures: list[dict[str, Any]] = []
    if samples < min_calibration_samples:
        failures.append({"reason": "insufficient_human_labels", "samples": samples, "required": min_calibration_samples})
    if samples >= min_calibration_samples and accuracy < min_accuracy:
        failures.append({"reason": "judge_accuracy_below_threshold", "accuracy": round(accuracy, 4), "min_accuracy": min_accuracy})
    if samples >= min_calibration_samples and false_accept_rate > max_false_accept_rate:
        failures.append(
            {
                "reason": "judge_false_accept_rate_above_threshold",
                "false_accept_rate": round(false_accept_rate, 4),
                "max_false_accept_rate": max_false_accept_rate,
            }
        )

    return {
        "name": "judge_model_audit",
        "samples": samples,
        "unlabeled_samples": len(rows) - samples,
        "threshold": threshold,
        "min_accuracy": min_accuracy,
        "max_false_accept_rate": max_false_accept_rate,
        "min_calibration_samples": min_calibration_samples,
        "accuracy": round(accuracy, 4) if samples else None,
        "false_accept_rate": round(false_accept_rate, 4) if samples else None,
        "false_reject_rate": round(false_reject_rate, 4) if samples else None,
        "mean_absolute_calibration_error": round(mean_abs_error, 4) if mean_abs_error is not None else None,
        "confusion": {
            "true_accept": true_accept,
            "true_reject": true_reject,
            "false_accept": false_accept,
            "false_reject": false_reject,
        },
        "calibration_bins": _calibration_bins(labeled),
        "blocked": bool(failures),
        "failures": failures,
    }


def _normalize_judge_row(row: dict[str, Any], *, threshold: float) -> dict[str, Any]:
    score = _score(row)
    human_pass = _human_label(row)
    return {
        "id": _row_id(row),
        "judge_score": score,
        "judge_pass": score >= threshold,
        "human_pass": human_pass,
        "task_family": str(row.get("task_family") or "unknown"),
    }


def _score(row: dict[str, Any]) -> float:
    raw = row.get("judge_score", row.get("score", row.get("judge_pass_probability")))
    if raw is None:
        raise ValueError(f"{_row_id(row)} missing judge_score")
    try:
        score = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_row_id(row)} judge_score must be numeric") from exc
    if score > 1.0:
        score = score / 100.0
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"{_row_id(row)} judge_score must be between 0 and 1 or 0 and 100")
    return score


def _has_human_label(row: dict[str, Any]) -> bool:
    return any(key in row for key in ("human_label", "reviewer_label", "human_pass", "review_status"))


def _human_label(row: dict[str, Any]) -> bool:
    if "human_pass" in row:
        return bool(row["human_pass"])
    raw = row.get("human_label", row.get("reviewer_label", row.get("review_status")))
    label = str(raw).strip().lower()
    if label in PASS_LABELS:
        return True
    if label in FAIL_LABELS:
        return False
    raise ValueError(f"{_row_id(row)} has unknown human label: {raw}")


def _human_pass(row: dict[str, Any], *, min_rubric_score: float) -> tuple[bool, list[str]]:
    if _has_human_label(row):
        passed = _human_label(row)
        return passed, ([] if passed else ["human_label_failed"])
    reasons = []
    for key in ("groundedness_score", "usefulness_score", "safety_score"):
        value = _optional_float(row.get(key))
        if value is not None and value < min_rubric_score:
            reasons.append(f"{key}_below_threshold")
    if row.get("unsafe") or row.get("blocked"):
        reasons.append("review_marked_unsafe_or_blocked")
    if not reasons and not any(key in row for key in ("groundedness_score", "usefulness_score", "safety_score")):
        reasons.append("missing_human_review_label_or_rubric")
    return not reasons, reasons


def _calibration_bins(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        start = min(9, int(row["judge_score"] * 10)) / 10
        buckets[f"{start:.1f}-{start + 0.1:.1f}"].append(row)
    return [
        {
            "bin": name,
            "samples": len(items),
            "mean_judge_score": round(sum(item["judge_score"] for item in items) / len(items), 4),
            "human_pass_rate": round(sum(1 for item in items if item["human_pass"]) / len(items), 4),
        }
        for name, items in sorted(buckets.items())
    ]


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rubric score must be numeric: {value}") from exc


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("eval_id") or row.get("id") or row.get("trace_id") or "unknown")
