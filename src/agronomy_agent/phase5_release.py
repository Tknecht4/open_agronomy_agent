from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_HARDENING_SUITES = (
    "golden_trace_replay",
    "semantic_concept_eval",
    "human_review_slice",
    "judge_model_audit",
    "abstention_eval",
    "adversarial_eval",
)


@dataclass(frozen=True)
class ReleaseGateResult:
    promotion_allowed: bool
    reasons: tuple[str, ...]
    metrics: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return {
            "promotion_allowed": self.promotion_allowed,
            "reasons": list(self.reasons),
            "metrics": self.metrics,
            "gate_version": "phase5_release_gate_v1",
        }


def evaluate_phase5_release_gates(
    *,
    eval_summary: dict[str, Any],
    latency_summary: dict[str, Any],
    leak_report: dict[str, Any] | None,
    hardening_report: dict[str, Any] | None = None,
    min_mean_score: float = 72.0,
    max_p95_latency_ms: float = 12000.0,
) -> ReleaseGateResult:
    reasons: list[str] = []
    missing_gate_artifacts: list[str] = []
    mean_score = _float(eval_summary.get("mean_score"))
    pass_rate = _float(eval_summary.get("pass_rate"))
    p95_latency = _float((latency_summary.get("latency_ms") or {}).get("p95"))
    leak_count = _count_leaks(leak_report)
    unsafe_count = int(eval_summary.get("unsafe_count") or 0)

    if mean_score is None and pass_rate is None:
        missing_gate_artifacts.append("eval_quality_metrics")
    if mean_score is not None and mean_score < min_mean_score:
        reasons.append("quality_regression")
    if pass_rate is not None and pass_rate < 0.90:
        reasons.append("release_suite_failures")
    if p95_latency is None:
        missing_gate_artifacts.append("latency_p95")
    if p95_latency is not None and p95_latency > max_p95_latency_ms:
        reasons.append("latency_regression")
    if leak_report is None:
        missing_gate_artifacts.append("prompt_leak_report")
    elif "leak_count" not in leak_report and "failures" not in leak_report:
        missing_gate_artifacts.append("prompt_leak_count")
    if leak_count:
        reasons.append("prompt_leak_failures")
    if unsafe_count:
        reasons.append("safety_failures")
    if hardening_report is None:
        missing_gate_artifacts.append("eval_hardening_report")
        hardening_report = {}
    for suite_name in REQUIRED_HARDENING_SUITES:
        if not isinstance(hardening_report.get(suite_name), dict):
            missing_gate_artifacts.append(suite_name)
    if hardening_report:
        semantic = _suite(hardening_report, "semantic_concept_eval")
        golden = _suite(hardening_report, "golden_trace_replay")
        human = _suite(hardening_report, "human_review_slice")
        judge = _suite(hardening_report, "judge_model_audit")
        abstention = _suite(hardening_report, "abstention_eval")
        adversarial = _suite(hardening_report, "adversarial_eval")
        if golden.get("blocked"):
            reasons.append("golden_trace_replay_failures")
        if semantic.get("blocked"):
            reasons.append("semantic_concept_regression")
        if human.get("blocked"):
            reasons.append("human_review_failures")
        if judge.get("blocked"):
            reasons.append("judge_model_calibration_failures")
        if abstention.get("blocked"):
            reasons.append("abstention_failures")
        if adversarial.get("blocked") or int(adversarial.get("unsafe_count") or 0) > 0:
            reasons.append("adversarial_failures")
    reasons.extend(f"missing_{artifact}" for artifact in missing_gate_artifacts)

    return ReleaseGateResult(
        promotion_allowed=not reasons,
        reasons=tuple(reasons),
        metrics={
            "mean_score": mean_score,
            "pass_rate": pass_rate,
            "p95_latency_ms": p95_latency,
            "leak_count": leak_count,
            "unsafe_count": unsafe_count,
            "hardening_blocked_suites": list(hardening_report.get("blocked_suites", [])) if hardening_report else [],
            "missing_gate_artifacts": missing_gate_artifacts,
            "min_mean_score": min_mean_score,
            "max_p95_latency_ms": max_p95_latency_ms,
        },
    )


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _count_leaks(report: dict[str, Any] | None) -> int:
    if not report:
        return 0
    raw = report.get("leak_count", report.get("failures", 0))
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        return len(raw)
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _suite(report: dict[str, Any], name: str) -> dict[str, Any]:
    value = report.get(name)
    return value if isinstance(value, dict) else {}
