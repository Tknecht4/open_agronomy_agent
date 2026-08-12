#!/usr/bin/env python3
"""Render manuscript result macros from frozen internal and external summaries."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


MODEL_ORDER = ["gemma3_270m_rc1", "gemma4_e2b_rc1", "luna_high_rc1"]
MODEL_LABELS = {
    "gemma3_270m_rc1": "Gemma 3 270M",
    "gemma4_e2b_rc1": "Gemma 4 E2B",
    "luna_high_rc1": "Luna High",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def one(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    matches = [row for row in rows if all(row.get(key) == value for key, value in criteria.items())]
    if len(matches) != 1:
        raise ValueError(f"expected one row for {criteria}, found {len(matches)}")
    return matches[0]


def esc(text: str) -> str:
    return text.replace("%", r"\%").replace("_", r"\_").replace("&", r"\&")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-root", type=Path, required=True)
    parser.add_argument("--cost-ledger-manifest", type=Path, required=True)
    parser.add_argument("--external-summary", type=Path, required=True)
    args = parser.parse_args()

    source = args.paper_root / "source_data"
    summary = read_csv(source / "arm_lane_summary.csv")
    deltas = read_csv(source / "paired_semantic_deltas.csv")
    resources = read_csv(source / "resource_summary.csv")
    orchestration = read_csv(source / "orchestration_summary.csv")
    cost_manifest = json.loads(args.cost_ledger_manifest.read_text(encoding="utf-8"))
    cost = cost_manifest["totals"]
    groups = list(cost_manifest.get("groups", {}).values())
    failed_judge_calls = sum(
        int(group.get("calls") or 0)
        for group in groups
        if group.get("usage_role") == "judge" and str(group.get("judge_role") or "").endswith("::failed_attempt")
    )
    accepted_judge_calls = sum(
        int(group.get("calls") or 0)
        for group in groups
        if group.get("usage_role") == "judge" and not str(group.get("judge_role") or "").endswith("::failed_attempt")
    )
    candidate_calls = sum(int(group.get("calls") or 0) for group in groups if group.get("usage_role") == "candidate")
    external = json.loads(args.external_summary.read_text(encoding="utf-8"))

    primary: dict[str, tuple[float, float, float, float]] = {}
    for model in MODEL_ORDER:
        raw = one(summary, model_key=model, system_variant="raw_model", benchmark_lane="canadian_decision_quality")
        agent = one(summary, model_key=model, system_variant="full_system", benchmark_lane="canadian_decision_quality")
        delta = one(deltas, model_key=model, comparison="full_system_minus_raw_model", benchmark_lane="canadian_decision_quality")
        primary[model] = (
            float(raw["semantic_mean"]),
            float(agent["semantic_mean"]),
            float(delta["ci95_low"]),
            float(delta["ci95_high"]),
        )

    primary_sentences = []
    for model in MODEL_ORDER:
        raw, agent, low, high = primary[model]
        primary_sentences.append(
            f"{MODEL_LABELS[model]} changed from {raw:.1f} to {agent:.1f} "
            f"(paired $\\Delta={agent - raw:+.1f}$ points; 95\\% fixed-suite interval {low:.1f} to {high:.1f})"
        )

    abstract = (
        f"On the 90-case primary lane, governed-system advisory scores changed from "
        f"{primary['gemma3_270m_rc1'][0]:.1f} to {primary['gemma3_270m_rc1'][1]:.1f} for Gemma 3 270M, "
        f"{primary['gemma4_e2b_rc1'][0]:.1f} to {primary['gemma4_e2b_rc1'][1]:.1f} for Gemma 4 E2B, and "
        f"{primary['luna_high_rc1'][0]:.1f} to {primary['luna_high_rc1'][1]:.1f} for Luna High. "
        "Objective calculation behavior did not consistently improve because "
        "the benchmark execution path did not invoke the registered typed calculator."
    )

    ablation_sentences = []
    for model in MODEL_ORDER:
        values = []
        for arm, label in (("kernel_only", "kernel"), ("kernel_field_context", "field context"), ("full_system", "governed agent")):
            delta = one(deltas, model_key=model, comparison=f"{arm}_minus_raw_model", benchmark_lane="canadian_decision_quality")
            values.append(f"{label} {float(delta['mean_delta_points']):+.1f}")
        ablation_sentences.append(f"{MODEL_LABELS[model]}: " + ", ".join(values) + " points")

    intervention_sentences = []
    for model in MODEL_ORDER:
        row = one(orchestration, model_key=model, benchmark_lane="canadian_decision_quality")
        intervention_sentences.append(
            f"{MODEL_LABELS[model]} {int(row['fallback_or_degraded'])}/{int(row['n'])} fallback/degraded outputs "
            f"and {int(row['accept_rewrite'])}/{int(row['n'])} accepted rewrites"
        )

    calc_sentences = []
    for model in MODEL_ORDER:
        raw = one(summary, model_key=model, system_variant="raw_model", benchmark_lane="objective_agronomic_calculation")
        agent = one(summary, model_key=model, system_variant="full_system", benchmark_lane="objective_agronomic_calculation")
        calc_sentences.append(
            f"{MODEL_LABELS[model]} {float(raw['objective_accuracy']):.0f}\\% raw and "
            f"{float(agent['objective_accuracy']):.0f}\\% governed"
        )

    finalist = external["finalist"]
    raw_external = external["arms"]["raw_model"]
    agent_external = external["arms"]["full_system"]
    external_paired = external["paired_comparison"]
    external_text = (
        f"The predeclared diagnostic finalist, {esc(finalist['model_label'])} with the governed arm, was then "
        f"run once on all {external['rows']} held-out AgroQA questions. Mean normalized reference-token F1 was "
        f"{raw_external['mean_reference_token_f1']:.3f} for the raw model and "
        f"{agent_external['mean_reference_token_f1']:.3f} for the governed system "
        f"(paired change {external_paired['mean_full_system_minus_raw']:+.3f}; 95\\% fixed-suite interval "
        f"{external_paired['fixed_suite_bootstrap_ci95'][0]:+.3f} to {external_paired['fixed_suite_bootstrap_ci95'][1]:+.3f}; "
        f"{external_paired['improved_cases']} improved and {external_paired['worse_cases']} worsened); "
        "this geographically mismatched resemblance measure is descriptive only."
    )

    local_latency = []
    for model in MODEL_ORDER:
        resource = one(resources, model_key=model, system_variant="full_system")
        local_latency.append(f"{MODEL_LABELS[model]} {float(resource['latency_median_seconds']):.2f}~s")
    cost_text = (
        f"Governed-arm median generation latency was " + ", ".join(local_latency) + ". "
        f"The App Server ledger recorded {candidate_calls:,} candidate calls, {accepted_judge_calls:,} accepted judge "
        f"batches, and {failed_judge_calls:,} archived invalid judge attempts ({int(cost['calls']):,} calls total), with "
        f"{int(cost['total_tokens']):,} tokens, corresponding to an API-equivalent estimate of "
        f"US\\${float(cost['api_equivalent_cost_usd']):.2f}; actual ChatGPT-authenticated billing was not observed."
    )

    macros = {
        "ResultAbstract": abstract,
        "ResultPrimary": "; ".join(primary_sentences) + ". These are automated triage scores, not agronomist ratings.",
        "ResultAblation": "; ".join(ablation_sentences) + ". The sequence shows that system effects were model-dependent rather than a uniform retrieval gain.",
        "ResultIntervention": "On the primary lane, orchestration produced " + "; ".join(intervention_sentences) + ". These rates prevent attributing the governed-arm score wholly to the underlying generator.",
        "ResultCalculation": "Deterministic calculation accuracy was " + "; ".join(calc_sentences) + ". The registered calculator was absent from all 16 benchmark traces, exposing an orchestration gap rather than validating calculator-backed arithmetic.",
        "ResultExternal": external_text,
        "ResultCost": cost_text,
    }
    text = "\n".join(f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macros.items()) + "\n"
    (args.paper_root / "generated_results.tex").write_text(text, encoding="utf-8")
    print(args.paper_root / "generated_results.tex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
