from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from agronomy_agent.leak_guard import detect_prompt_leaks
from agronomy_agent.phase5_optimization import candidate_promotion_gate
from agronomy_agent.skill_registry import normalize_tool_names


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(float(ordered[index]), 3)


def stage_latency_report(spans: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: dict[str, list[float]] = defaultdict(list)
    cache_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for span in spans:
        if span.get("status") == "skipped" or span.get("duration_ms") is None:
            continue
        stage = str(span.get("stage") or "unknown")
        by_stage[stage].append(float(span["duration_ms"]))
        cache_status = span.get("cache_status")
        if cache_status:
            cache_counts[stage][str(cache_status)] += 1
    return {
        "stage_count": len(by_stage),
        "stages": {
            stage: {
                "count": len(values),
                "p50_ms": percentile(values, 0.50),
                "p95_ms": percentile(values, 0.95),
                "max_ms": round(max(values), 3),
                "cache": dict(cache_counts.get(stage, {})),
            }
            for stage, values in sorted(by_stage.items())
        },
    }


def context_packer_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("context_packer_version") or "unknown")].append(row)
    summaries = {}
    for version, items in grouped.items():
        scores = [_number(item.get("answer_score")) for item in items if _number(item.get("answer_score")) is not None]
        tokens = [_number(item.get("context_tokens_est")) for item in items if _number(item.get("context_tokens_est")) is not None]
        latencies = [_number(item.get("total_latency_ms")) for item in items if _number(item.get("total_latency_ms")) is not None]
        summaries[version] = {
            "samples": len(items),
            "mean_answer_score": _mean(scores),
            "mean_context_tokens": _mean(tokens),
            "p95_latency_ms": percentile([float(value) for value in latencies], 0.95),
        }
    promoted = _choose_context_packer(summaries)
    return {"comparison_version": "phase5_context_packer_comparison_v1", "packers": summaries, "promoted_version": promoted}


def retrieval_ablation_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_type_totals: Counter[str] = Counter()
    for row in rows:
        by_family[str(row.get("task_family") or "unknown")].append(row)
        source_type_totals.update(row.get("source_type_counts") or (row.get("phase5_retrieval") or {}).get("source_type_counts") or {})
    cache_values = [
        str(row.get("retrieval_cache_status") or row.get("cache_status") or (row.get("phase5_retrieval") or {}).get("cache_status"))
        for row in rows
        if row.get("retrieval_cache_status") or row.get("cache_status") or (row.get("phase5_retrieval") or {}).get("cache_status")
    ]
    return {
        "report_version": "phase5_retrieval_ablation_v1",
        "samples": len(rows),
        "mean_required_support_rate": _mean([_number(row.get("retrieval_required_support_rate")) for row in rows]),
        "mean_doc_count": _mean([_number(row.get("doc_count")) for row in rows]),
        "mean_source_diversity": _mean([_number(row.get("source_diversity")) for row in rows]),
        "mean_route_namespace_match_rate": _mean([_number(row.get("route_namespace_match_rate")) for row in rows]),
        "mean_support_per_context_token": _mean([_number(row.get("support_per_context_token")) for row in rows]),
        "mean_recall_at_k": _mean([_number(row.get("recall_at_k")) for row in rows]),
        "mean_mrr": _mean([_number(row.get("mrr")) for row in rows]),
        "mean_ndcg_at_k": _mean([_number(row.get("ndcg_at_k")) for row in rows]),
        "mean_answer_gain_over_no_rag": _mean([_number(row.get("answer_gain_over_no_rag")) for row in rows]),
        "cache": dict(Counter(cache_values)),
        "cache_hit_rate": round(sum(1 for value in cache_values if value == "hit") / max(1, len(cache_values)), 4) if cache_values else None,
        "source_type_counts": dict(sorted(source_type_totals.items())),
        "by_family": {
            family: {
                "samples": len(items),
                "mean_required_support_rate": _mean([_number(item.get("retrieval_required_support_rate")) for item in items]),
                "mean_doc_count": _mean([_number(item.get("doc_count")) for item in items]),
                "mean_recall_at_k": _mean([_number(item.get("recall_at_k")) for item in items]),
                "mean_route_namespace_match_rate": _mean([_number(item.get("route_namespace_match_rate")) for item in items]),
            }
            for family, items in sorted(by_family.items())
        },
    }


def route_tool_precision_recall_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    route_tp = route_fp = route_fn = 0
    tool_tp = tool_fp = tool_fn = 0
    for row in rows:
        expected_route = row.get("expected_route") or row.get("task_family")
        actual_route = row.get("actual_route") or (row.get("route") or {}).get("question_type")
        if expected_route and actual_route == expected_route:
            route_tp += 1
        elif expected_route:
            route_fp += 1
            route_fn += 1
        expected_tools = normalize_tool_names(row.get("expected_tools", []) or [])
        actual_tools = normalize_tool_names(row.get("actual_tools", []) or row.get("tool_notes", []) or [])
        tool_tp += len(expected_tools & actual_tools)
        tool_fp += len(actual_tools - expected_tools)
        tool_fn += len(expected_tools - actual_tools)
    return {
        "report_version": "phase5_route_tool_precision_recall_v1",
        "samples": len(rows),
        "route": _precision_recall(route_tp, route_fp, route_fn),
        "tools": _precision_recall(tool_tp, tool_fp, tool_fn),
    }


def prompt_leak_report(answers: list[dict[str, Any]]) -> dict[str, Any]:
    leak_counts: Counter[str] = Counter()
    failed_ids: list[str] = []
    for row in answers:
        findings = detect_prompt_leaks(str(row.get("answer") or row.get("output") or ""))
        if findings:
            failed_ids.append(str(row.get("id") or row.get("eval_id") or row.get("trace_id") or "unknown"))
        leak_counts.update(finding.leak_class for finding in findings)
    return {
        "report_version": "phase5_prompt_leak_report_v1",
        "samples": len(answers),
        "leak_count": sum(leak_counts.values()),
        "failed_sample_count": len(failed_ids),
        "leak_classes": dict(sorted(leak_counts.items())),
        "failed_ids": failed_ids,
        "pass_rate": round((len(answers) - len(failed_ids)) / max(1, len(answers)), 4),
    }


def eval_hardening_report(eval_summary: dict[str, Any], hardening_matrix: list[dict[str, Any]]) -> dict[str, Any]:
    required_suites = [_row_value(row, "eval_layer", "Eval", "eval", "suite", "name") for row in hardening_matrix]
    gates = {
        suite: _row_value(row, "gate", "Gate")
        for suite, row in zip(required_suites, hardening_matrix, strict=False)
        if suite
    }
    return {
        "report_version": "phase5_eval_hardening_v1",
        "eval_summary": eval_summary,
        "matrix_suite_count": len([suite for suite in required_suites if suite]),
        "required_suites": [suite for suite in required_suites if suite],
        "gates": gates,
        "blocks_release": any("block" in gate.lower() for gate in gates.values()),
    }


def gepa_reflexion_candidate_report(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    missing_proof_counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        gate = candidate_promotion_gate(candidate)
        status = str(candidate.get("pareto_status") or "pending")
        candidate_type = str(candidate.get("candidate_type") or "unknown")
        trace_ids = [str(item) for item in candidate.get("generated_from_trace_ids", []) or []]
        patch = candidate.get("patch") or {}
        eval_summary = candidate.get("eval_summary") or {}
        missing = []
        if not trace_ids:
            missing.append("trace_links")
        if not (patch.get("unified_diff") or patch.get("diff") or patch.get("policy_patch")):
            missing.append("candidate_diff")
        if not eval_summary:
            missing.append("eval_results")
        if not str(candidate.get("rollback_plan") or "").strip():
            missing.append("rollback_plan")
        missing_proof_counts.update(missing)
        status_counts[status] += 1
        type_counts[candidate_type] += 1
        rows.append(
            {
                "candidate_id": str(candidate.get("candidate_id") or candidate.get("id") or "unknown"),
                "candidate_type": candidate_type,
                "pareto_status": status,
                "trace_count": len(trace_ids),
                "has_candidate_diff": "candidate_diff" not in missing,
                "has_eval_results": "eval_results" not in missing,
                "has_rollback_plan": "rollback_plan" not in missing,
                "promotion_allowed": gate["promotion_allowed"],
                "promotion_gate_reasons": gate["reasons"],
                "missing_proof": missing,
            }
        )
    return {
        "report_version": "phase5_gepa_reflexion_candidate_report_v1",
        "candidate_count": len(candidates),
        "by_status": dict(sorted(status_counts.items())),
        "by_candidate_type": dict(sorted(type_counts.items())),
        "missing_proof_counts": dict(sorted(missing_proof_counts.items())),
        "promotion_ready_count": sum(1 for row in rows if row["promotion_allowed"]),
        "blocked_count": sum(1 for row in rows if not row["promotion_allowed"]),
        "candidates": rows,
    }


def model_registry_comparison(models: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        models,
        key=_model_rank_key,
    )
    selectable = [model for model in ranked if _model_demo_selectable(model)]
    blocked = [str(model.get("model_id") or "") for model in ranked if not _model_demo_selectable(model)]
    return {
        "report_version": "phase5_model_registry_comparison_v1",
        "models": ranked,
        "default_model_id": selectable[0].get("model_id") if selectable else None,
        "default_selection_policy": "demo models are selectable; candidates require explicit Phase 5 release-gate promotion; blocked/archived models are never defaults",
        "non_selectable_model_ids": [model_id for model_id in blocked if model_id],
    }


def public_demo_release_note(*, limitations: list[str], reports: dict[str, Any]) -> str:
    lines = ["# Public Demo Release Note", "", "This demo is a measured preview, not a production agronomy recommendation system.", ""]
    lines.append("## Evidence")
    for name, report in reports.items():
        lines.append(f"- {name}: {report}")
    lines.extend(["", "## Honest Limitations"])
    for item in limitations:
        lines.append(f"- {item}")
    return "\n".join(lines).strip() + "\n"


def _choose_context_packer(summaries: dict[str, dict[str, Any]]) -> str | None:
    if not summaries:
        return None
    return sorted(
        summaries.items(),
        key=lambda item: (
            -(item[1].get("mean_answer_score") or 0.0),
            item[1].get("mean_context_tokens") or 1_000_000.0,
            item[1].get("p95_latency_ms") or 1_000_000.0,
            item[0],
        ),
    )[0][0]


def _precision_recall(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn, "precision": round(precision, 4), "recall": round(recall, 4)}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 4) if clean else None


def _model_mean_score(row: dict[str, Any]) -> float | None:
    eval_profile = row.get("eval_profile") if isinstance(row.get("eval_profile"), dict) else {}
    return _first_number(row.get("mean_score"), eval_profile.get("mean_score"), eval_profile.get("overall_score"))


def _model_p95_latency_ms(row: dict[str, Any]) -> float | None:
    latency_profile = row.get("latency_profile") if isinstance(row.get("latency_profile"), dict) else {}
    return _first_number(row.get("p95_latency_ms"), latency_profile.get("p95_latency_ms"), latency_profile.get("ttft_p95_ms"))


def _model_rank_key(row: dict[str, Any]) -> tuple[float, float, str]:
    return (
        -(_model_mean_score(row) or 0.0),
        _model_p95_latency_ms(row) or 1_000_000.0,
        str(row.get("model_id") or ""),
    )


def _model_demo_selectable(row: dict[str, Any]) -> bool:
    status = str(row.get("release_status") or "candidate").strip().lower()
    if status == "demo":
        return True
    if status != "candidate":
        return False
    eval_profile = row.get("eval_profile") if isinstance(row.get("eval_profile"), dict) else {}
    release_gate = eval_profile.get("release_gate") if isinstance(eval_profile.get("release_gate"), dict) else {}
    phase5_gate = eval_profile.get("phase5_release_gate") if isinstance(eval_profile.get("phase5_release_gate"), dict) else {}
    return any(
        bool(value)
        for value in (
            row.get("release_gate_passed"),
            row.get("promotion_allowed"),
            eval_profile.get("release_gate_passed"),
            eval_profile.get("promotion_allowed"),
            release_gate.get("promotion_allowed"),
            phase5_gate.get("promotion_allowed"),
        )
    )


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _number(value)
        if parsed is not None:
            return parsed
    return None


def _row_value(row: dict[str, Any], *keys: str) -> str:
    if not row:
        return ""
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        value = normalized.get(key.strip().lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
