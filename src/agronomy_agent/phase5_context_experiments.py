from __future__ import annotations

from dataclasses import replace
from typing import Any

from agronomy_agent.context_packer import ContextPacker, ContextSection, PackedContext, estimate_tokens


CONTEXT_ABLATION_VARIANTS = (
    "v0_current_concat",
    "v1_top_evidence_first",
    "v2_safety_first_user_last",
    "v3_edge_pinned_evidence",
    "v4_compact_evidence_digest",
    "v5_map_reduce_evidence_digest",
)


def pack_context_variant(*, question: str, context: Any, variant: str, packer: ContextPacker | None = None) -> PackedContext:
    if variant not in CONTEXT_ABLATION_VARIANTS:
        raise ValueError(f"unknown context ablation variant: {variant}")
    active_packer = packer or ContextPacker.from_policy_path()
    base = active_packer.pack(question=question, context=context)
    sections = list(base.sections)
    if variant == "v0_current_concat":
        ordered = sections
    elif variant == "v1_top_evidence_first":
        ordered = _order(sections, ("primary_applied_evidence", "boundary_evidence", "safety_task_policy", "guard_summary"), append_rest=True)
    elif variant == "v2_safety_first_user_last":
        ordered = _order(
            sections,
            (
                "safety_task_policy",
                "guard_summary",
                "primary_applied_evidence",
                "boundary_evidence",
                "regional_context",
                "kg_vocabulary_hints",
                "hidden_answer_contract",
                "route_summary",
                "user_question_output_contract",
            ),
            append_rest=False,
        )
    elif variant == "v3_edge_pinned_evidence":
        ordered = _order(
            sections,
            (
                "safety_task_policy",
                "primary_applied_evidence",
                "guard_summary",
                "regional_context",
                "kg_vocabulary_hints",
                "hidden_answer_contract",
                "boundary_evidence",
                "user_question_output_contract",
            ),
            append_rest=False,
        )
    elif variant == "v4_compact_evidence_digest":
        ordered = [
            _compact_evidence(section, max_chars=220)
            for section in _order(sections, ("safety_task_policy", "guard_summary", "primary_applied_evidence"), append_rest=True)
        ]
    else:
        ordered = _map_reduce_sections(sections)
    return _packed_from_sections(f"phase5_context_packer_{variant}", ordered, active_packer.max_context_tokens, budget_report=base.budget_report)


def context_ablation_rows(
    *,
    question: str,
    context: Any,
    eval_scores: dict[str, float] | None = None,
    latency_ms: dict[str, float] | None = None,
    packer: ContextPacker | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for variant in CONTEXT_ABLATION_VARIANTS:
        packed = pack_context_variant(question=question, context=context, variant=variant, packer=packer)
        source_ids = sorted({source_id for section in packed.sections for source_id in section.source_ids})
        rows.append(
            {
                "context_packer_version": variant,
                "answer_score": (eval_scores or {}).get(variant),
                "context_tokens_est": packed.token_estimate,
                "total_latency_ms": (latency_ms or {}).get(variant),
                "source_count": len(source_ids),
                "slot_order": [section.slot for section in packed.sections],
                "source_ids": source_ids,
            }
        )
    return rows


def promote_context_ablation(rows: list[dict[str, Any]], *, baseline_version: str = "v0_current_concat") -> dict[str, Any]:
    baseline = next((row for row in rows if row.get("context_packer_version") == baseline_version), None)
    if baseline is None:
        return {"promotion_allowed": False, "promoted_version": None, "reasons": ["missing_baseline"]}
    baseline_score = _number(baseline.get("answer_score"))
    baseline_tokens = _number(baseline.get("context_tokens_est"))
    baseline_latency = _number(baseline.get("total_latency_ms"))
    eligible = []
    rejected = []
    for row in rows:
        version = str(row.get("context_packer_version"))
        score = _number(row.get("answer_score"))
        tokens = _number(row.get("context_tokens_est"))
        latency = _number(row.get("total_latency_ms"))
        reasons = []
        if score is None:
            reasons.append("missing_answer_score")
        elif baseline_score is not None and score < baseline_score:
            reasons.append("score_regression")
        token_gain = baseline_tokens is not None and tokens is not None and tokens < baseline_tokens
        latency_gain = baseline_latency is not None and latency is not None and latency < baseline_latency
        if not (token_gain or latency_gain):
            reasons.append("no_token_or_latency_gain")
        if reasons:
            rejected.append({"context_packer_version": version, "reasons": reasons})
        else:
            eligible.append(row)
    if not eligible:
        return {"promotion_allowed": False, "promoted_version": None, "reasons": ["no_variant_met_score_and_efficiency_gate"], "rejected": rejected}
    promoted = sorted(
        eligible,
        key=lambda row: (
            -(_number(row.get("answer_score")) or 0.0),
            _number(row.get("context_tokens_est")) or 1_000_000.0,
            _number(row.get("total_latency_ms")) or 1_000_000.0,
            str(row.get("context_packer_version")),
        ),
    )[0]
    return {
        "promotion_allowed": True,
        "promoted_version": promoted["context_packer_version"],
        "reasons": [],
        "promoted": promoted,
        "rejected": rejected,
        "gate_version": "phase5_context_ablation_promotion_gate_v1",
    }


def _order(sections: list[ContextSection], preferred: tuple[str, ...], *, append_rest: bool = True) -> list[ContextSection]:
    by_slot = {section.slot: section for section in sections}
    ordered = [by_slot[slot] for slot in preferred if slot in by_slot]
    if append_rest:
        ordered.extend(section for section in sections if section.slot not in set(preferred))
    return ordered


def _compact_evidence(section: ContextSection, *, max_chars: int) -> ContextSection:
    if section.slot not in {"primary_applied_evidence", "boundary_evidence", "regional_context"}:
        return section
    source_text = ", ".join(section.source_ids) if section.source_ids else "no source ids"
    compact = f"{section.slot.replace('_', ' ').title()} digest from {source_text}: {section.text[:max_chars].strip()}"
    return replace(section, text=compact, token_estimate=estimate_tokens(compact))


def _map_reduce_sections(sections: list[ContextSection]) -> list[ContextSection]:
    reduced = []
    for section in sections:
        if section.slot in {"primary_applied_evidence", "boundary_evidence", "regional_context", "kg_vocabulary_hints"}:
            reduced.append(_compact_evidence(section, max_chars=140))
        else:
            reduced.append(section)
    return _order(reduced, ("safety_task_policy", "guard_summary", "primary_applied_evidence", "boundary_evidence", "user_question_output_contract"), append_rest=True)


def _packed_from_sections(
    version: str,
    sections: list[ContextSection],
    max_tokens: int,
    *,
    budget_report: dict[str, Any] | None = None,
) -> PackedContext:
    kept = []
    total = 0
    for section in sections:
        if total + section.token_estimate > max_tokens and section.slot not in {"safety_task_policy", "user_question_output_contract"}:
            continue
        kept.append(section)
        total += section.token_estimate
    return PackedContext(version=version, text="\n\n".join(section.text for section in kept), sections=tuple(kept), token_estimate=total, budget_report=budget_report)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
