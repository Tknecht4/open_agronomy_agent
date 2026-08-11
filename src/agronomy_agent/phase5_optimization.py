from __future__ import annotations

import difflib
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OptimizationCandidate:
    candidate_id: str
    candidate_type: str
    parent_version: str
    candidate_version: str
    generated_from_trace_ids: tuple[str, ...]
    reflection_summary: str
    patch: dict[str, Any]
    eval_summary: dict[str, Any]
    pareto_status: str
    rollback_plan: str

    def as_record(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "parent_version": self.parent_version,
            "candidate_version": self.candidate_version,
            "generated_from_trace_ids": list(self.generated_from_trace_ids),
            "reflection_summary": self.reflection_summary,
            "patch": self.patch,
            "eval_summary": self.eval_summary,
            "pareto_status": self.pareto_status,
            "rollback_plan": self.rollback_plan,
            "schema_version": "phase5_optimization_candidate_v1",
        }


def reflect_on_trace(trace_payload: dict[str, Any]) -> dict[str, Any]:
    metrics = trace_payload.get("metrics") or {}
    spans = trace_payload.get("spans") or []
    slow_stages = sorted(
        [span for span in spans if isinstance(span, dict) and span.get("duration_ms") is not None],
        key=lambda span: float(span["duration_ms"]),
        reverse=True,
    )[:3]
    quality_flags = list(metrics.get("quality_flags") or [])
    focus = []
    if not metrics.get("leak_check_passed", True):
        focus.append("remove hidden prompt/template leakage from public answer rendering")
    if metrics.get("retrieval_doc_count", 0) == 0:
        focus.append("improve retrieval recall or abstain with missing-data wording")
    if slow_stages:
        focus.append("profile slow stages: " + ", ".join(str(span.get("stage")) for span in slow_stages))
    if not focus:
        focus.append("candidate trace is healthy; keep as SFT/eval positive only after review")
    return {
        "trace_id": trace_payload.get("trace_id") or metrics.get("trace_id"),
        "focus": focus,
        "quality_flags": quality_flags,
        "slow_stages": [
            {"stage": span.get("stage"), "duration_ms": span.get("duration_ms"), "cache_status": span.get("cache_status")}
            for span in slow_stages
        ],
    }


def generate_prompt_candidate(
    *,
    parent_version: str,
    parent_prompt: str,
    proposed_prompt: str,
    reflections: list[dict[str, Any]],
    eval_summary: dict[str, Any] | None = None,
) -> OptimizationCandidate:
    trace_ids = tuple(str(item["trace_id"]) for item in reflections if item.get("trace_id"))
    diff = "\n".join(
        difflib.unified_diff(
            parent_prompt.splitlines(),
            proposed_prompt.splitlines(),
            fromfile=f"{parent_version}/prompt",
            tofile="candidate/prompt",
            lineterm="",
        )
    )
    return OptimizationCandidate(
        candidate_id=str(uuid.uuid4()),
        candidate_type="prompt_context_policy",
        parent_version=parent_version,
        candidate_version=f"{parent_version}.candidate.{uuid.uuid4().hex[:8]}",
        generated_from_trace_ids=trace_ids,
        reflection_summary="; ".join(_reflection_focus(reflections))[:1200],
        patch={"unified_diff": diff, "proposed_prompt": proposed_prompt},
        eval_summary=eval_summary or {},
        pareto_status="pending",
        rollback_plan=f"Revert prompt/context policy to {parent_version} and rerun Phase 5 release gates.",
    )


def candidate_promotion_gate(candidate: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if not candidate.get("generated_from_trace_ids"):
        reasons.append("missing_trace_links")
    patch = candidate.get("patch") or {}
    if not (patch.get("unified_diff") or patch.get("diff") or patch.get("policy_patch")):
        reasons.append("missing_candidate_diff")
    eval_summary = candidate.get("eval_summary") or {}
    if not eval_summary:
        reasons.append("missing_eval_results")
    if not (eval_summary.get("pareto_frontier") is True or eval_summary.get("promotion_allowed") is True):
        reasons.append("not_on_pareto_frontier")
    if not str(candidate.get("rollback_plan") or "").strip():
        reasons.append("missing_rollback_plan")
    return {
        "promotion_allowed": not reasons,
        "reasons": reasons,
        "gate_version": "phase5_pareto_promotion_gate_v1",
    }


def _reflection_focus(reflections: list[dict[str, Any]]) -> list[str]:
    focus: list[str] = []
    for reflection in reflections:
        focus.extend(str(item) for item in reflection.get("focus", []))
    return focus or ["no reflection focus supplied"]
