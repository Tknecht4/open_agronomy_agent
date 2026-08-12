#!/usr/bin/env python3
"""Build paper-ready source data and one compact figure from the frozen result DB."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

EXPECTED_MODELS = {
    "gemma3_270m_rc1": "Gemma 3 270M",
    "gemma4_e2b_rc1": "Gemma 4 E2B",
    "luna_high_rc1": "Luna High",
}
MODEL_ID_TO_KEY = {
    "mlx-community/gemma-3-270m-it-4bit": "gemma3_270m_rc1",
    "mlx-community/gemma-4-e2b-it-4bit": "gemma4_e2b_rc1",
    "gpt-5.6-luna": "luna_high_rc1",
}
ARM_ORDER = ["raw_model", "kernel_only", "kernel_field_context", "full_system"]
ARM_LABELS = {
    "raw_model": "Raw model",
    "kernel_only": "Kernel",
    "kernel_field_context": "Kernel + field",
    "full_system": "Governed agent",
}
LANE_PRIMARY = "canadian_decision_quality"
LANE_SECONDARY = "canadian_advisory_transfer"
LANE_OBJECTIVE = "objective_agronomic_calculation"


def json_value(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_mean_ci(values: list[float], *, seed: int, draws: int = 10_000) -> tuple[float, float]:
    if not values:
        return math.nan, math.nan
    rng = random.Random(seed)
    n = len(values)
    boot = [mean(values[rng.randrange(n)] for _ in range(n)) for _ in range(draws)]
    return percentile(boot, 0.025), percentile(boot, 0.975)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_rows(db_path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    query = """
        SELECT
            r.model_key,
            m.model_id,
            m.model_revision,
            r.mode,
            r.system_variant,
            resp.eval_id,
            c.task_family,
            json_extract(c.eval_metadata_json, '$.benchmark_lane') AS benchmark_lane,
            json_extract(c.eval_metadata_json, '$.metric_role') AS metric_role,
            resp.elapsed_seconds,
            resp.output,
            resp.score_json,
            resp.generation_stats_json,
            resp.verification_json,
            j.semantic_score,
            j.answer_disposition,
            j.dimensions_json,
            j.material_errors_json,
            j.needs_source_validation,
            j.judge_generator_relationship
        FROM benchmark_run r
        JOIN model m ON m.model_key = r.model_key
        JOIN response resp ON resp.run_id = r.run_id
        JOIN benchmark_case c ON c.eval_id = resp.eval_id
        LEFT JOIN semantic_judgment j ON j.response_id = resp.response_id
        WHERE r.is_canonical = 1
        ORDER BY r.model_key, r.system_variant, resp.ordinal
    """
    rows = [dict(row) for row in connection.execute(query)]
    connection.close()
    for row in rows:
        database_model_key = row["model_key"]
        try:
            row["model_key"] = MODEL_ID_TO_KEY[row["model_id"]]
        except KeyError as exc:
            raise ValueError(
                f"unrecognized model_id {row['model_id']!r} for database key {database_model_key!r}"
            ) from exc
        row["database_model_key"] = database_model_key
        score = json_value(row.pop("score_json"))
        stats = json_value(row.pop("generation_stats_json"))
        verification = json_value(row.pop("verification_json"))
        dimensions = json_value(row.pop("dimensions_json"))
        row["proxy_score"] = score.get("score")
        row["proxy_valid"] = score.get("proxy_valid")
        row["objective_accuracy"] = score.get("accuracy")
        row["parse_valid"] = score.get("parse_valid")
        row["prompt_tokens"] = stats.get("prompt_tokens")
        row["generation_tokens"] = stats.get("generation_tokens")
        row["generation_tps"] = stats.get("generation_tps")
        row["intervention_triggered"] = bool(verification.get("triggered"))
        row["intervention_action"] = verification.get("intervention_action") or "no_action"
        row["fallback_applied"] = bool(verification.get("fallback_applied"))
        row["rewrite_accepted"] = bool(verification.get("rewrite_accepted"))
        row["answer_characters"] = len(row.pop("output") or "")
        row["dimensions"] = dimensions
        raw_errors = row.pop("material_errors_json")
        errors = json.loads(raw_errors) if raw_errors else []
        row["material_errors"] = errors if isinstance(errors, list) else []
    return rows


def validate_complete(rows: list[dict[str, Any]]) -> None:
    expected = len(EXPECTED_MODELS) * len(ARM_ORDER) * 241
    if len(rows) != expected:
        raise ValueError(f"expected {expected} canonical responses, found {len(rows)}")
    observed_models = {row["model_key"] for row in rows}
    if observed_models != set(EXPECTED_MODELS):
        raise ValueError(f"model set mismatch: {sorted(observed_models)}")
    for model_key in EXPECTED_MODELS:
        for arm in ARM_ORDER:
            subset = [row for row in rows if row["model_key"] == model_key and row["system_variant"] == arm]
            if len(subset) != 241:
                raise ValueError(f"{model_key}/{arm}: expected 241 rows, found {len(subset)}")
            judged = sum(row["semantic_score"] is not None for row in subset)
            if judged != 241:
                raise ValueError(f"{model_key}/{arm}: expected 241 judgments, found {judged}")


def response_level(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        output.append(
            {
                "model_key": row["model_key"],
                "database_model_key": row["database_model_key"],
                "model_label": EXPECTED_MODELS[row["model_key"]],
                "model_id": row["model_id"],
                "model_revision": row["model_revision"],
                "system_variant": row["system_variant"],
                "arm_label": ARM_LABELS[row["system_variant"]],
                "eval_id": row["eval_id"],
                "benchmark_lane": row["benchmark_lane"],
                "metric_role": row["metric_role"],
                "task_family": row["task_family"],
                "semantic_score": row["semantic_score"],
                "answer_disposition": row["answer_disposition"],
                "needs_source_validation": row["needs_source_validation"],
                "proxy_score": row["proxy_score"],
                "proxy_valid": row["proxy_valid"],
                "objective_accuracy": row["objective_accuracy"],
                "parse_valid": row["parse_valid"],
                "elapsed_seconds": row["elapsed_seconds"],
                "prompt_tokens": row["prompt_tokens"],
                "generation_tokens": row["generation_tokens"],
                "generation_tps": row["generation_tps"],
                "answer_characters": row["answer_characters"],
                "judge_generator_relationship": row["judge_generator_relationship"],
            }
        )
    return output


def arm_lane_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["model_key"], row["system_variant"], row["benchmark_lane"])].append(row)
    output = []
    for (model_key, arm, lane), subset in sorted(groups.items()):
        semantic = [float(row["semantic_score"]) for row in subset if row["semantic_score"] is not None]
        low, high = bootstrap_mean_ci(
            semantic,
            seed=20260811 + list(EXPECTED_MODELS).index(model_key) * 100 + ARM_ORDER.index(arm) * 10,
        )
        valid_proxy = [float(row["proxy_score"]) for row in subset if row["proxy_valid"] and row["proxy_score"] is not None]
        objective = (
            [float(row["objective_accuracy"]) for row in subset if row["objective_accuracy"] is not None]
            if lane == LANE_OBJECTIVE
            else []
        )
        elapsed = [float(row["elapsed_seconds"]) for row in subset]
        dispositions = Counter(str(row["answer_disposition"] or "missing") for row in subset)
        output.append(
            {
                "model_key": model_key,
                "model_label": EXPECTED_MODELS[model_key],
                "system_variant": arm,
                "arm_label": ARM_LABELS[arm],
                "benchmark_lane": lane,
                "n": len(subset),
                "semantic_mean": round(mean(semantic), 4) if semantic else "",
                "semantic_ci95_low": round(low, 4) if semantic else "",
                "semantic_ci95_high": round(high, 4) if semantic else "",
                "semantic_pass": dispositions["pass"],
                "semantic_revise": dispositions["revise"],
                "semantic_fail": dispositions["fail"],
                "valid_proxy_n": len(valid_proxy),
                "valid_proxy_mean": round(mean(valid_proxy), 4) if valid_proxy else "",
                "objective_n": len(objective),
                "objective_accuracy": round(mean(objective), 4) if objective else "",
                "latency_median_seconds": round(median(elapsed), 4),
                "latency_mean_seconds": round(mean(elapsed), 4),
            }
        )
    return output


def paired_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {
        (row["model_key"], row["system_variant"], row["eval_id"]): float(row["semantic_score"])
        for row in rows
        if row["semantic_score"] is not None
    }
    output = []
    for model_index, model_key in enumerate(EXPECTED_MODELS):
        for lane in (LANE_PRIMARY, LANE_SECONDARY):
            eval_ids = sorted({row["eval_id"] for row in rows if row["model_key"] == model_key and row["benchmark_lane"] == lane})
            raw = [indexed[(model_key, "raw_model", eval_id)] for eval_id in eval_ids]
            for arm_index, arm in enumerate(ARM_ORDER[1:], start=1):
                deltas = [indexed[(model_key, arm, eval_id)] - raw_value for eval_id, raw_value in zip(eval_ids, raw)]
                low, high = bootstrap_mean_ci(
                    deltas,
                    seed=20261811 + model_index * 100 + arm_index * 10 + (1 if lane == LANE_SECONDARY else 0),
                )
                output.append(
                    {
                        "model_key": model_key,
                        "model_label": EXPECTED_MODELS[model_key],
                        "benchmark_lane": lane,
                        "comparison": f"{arm}_minus_raw_model",
                        "n_paired_cases": len(deltas),
                        "mean_delta_points": round(mean(deltas), 4),
                        "ci95_low": round(low, 4),
                        "ci95_high": round(high, 4),
                        "improved_cases": sum(value > 0 for value in deltas),
                        "unchanged_cases": sum(value == 0 for value in deltas),
                        "worse_cases": sum(value < 0 for value in deltas),
                    }
                )
    return output


def resource_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["model_key"], row["system_variant"])].append(row)
    output = []
    for (model_key, arm), subset in sorted(groups.items()):
        elapsed = [float(row["elapsed_seconds"]) for row in subset]
        tps = [float(row["generation_tps"]) for row in subset if row["generation_tps"] is not None]
        prompt = [int(row["prompt_tokens"]) for row in subset if row["prompt_tokens"] is not None]
        generated = [int(row["generation_tokens"]) for row in subset if row["generation_tokens"] is not None]
        output.append(
            {
                "model_key": model_key,
                "model_label": EXPECTED_MODELS[model_key],
                "system_variant": arm,
                "arm_label": ARM_LABELS[arm],
                "n": len(subset),
                "latency_median_seconds": round(median(elapsed), 4),
                "latency_mean_seconds": round(mean(elapsed), 4),
                "generation_tps_median": round(median(tps), 4) if tps else "",
                "prompt_tokens_mean": round(mean(prompt), 2) if prompt else "",
                "generation_tokens_mean": round(mean(generated), 2) if generated else "",
                "answer_characters_mean": round(mean(row["answer_characters"] for row in subset), 2),
            }
        )
    return output


def task_family_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve task-level heterogeneity instead of reporting only pooled lane means."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["model_key"], row["system_variant"], row["benchmark_lane"], row["task_family"])].append(row)
    output = []
    for (model_key, arm, lane, task_family), subset in sorted(groups.items()):
        semantic = [float(row["semantic_score"]) for row in subset if row["semantic_score"] is not None]
        objective = (
            [float(row["objective_accuracy"]) for row in subset if row["objective_accuracy"] is not None]
            if lane == LANE_OBJECTIVE
            else []
        )
        dispositions = Counter(str(row["answer_disposition"] or "missing") for row in subset)
        output.append(
            {
                "model_key": model_key,
                "model_label": EXPECTED_MODELS[model_key],
                "system_variant": arm,
                "arm_label": ARM_LABELS[arm],
                "benchmark_lane": lane,
                "task_family": task_family,
                "n": len(subset),
                "semantic_mean": round(mean(semantic), 4) if semantic else "",
                "semantic_pass": dispositions["pass"],
                "semantic_revise": dispositions["revise"],
                "semantic_fail": dispositions["fail"],
                "objective_accuracy": round(mean(objective), 4) if objective else "",
                "latency_median_seconds": round(median(float(row["elapsed_seconds"]) for row in subset), 4),
            }
        )
    return output


def orchestration_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count governed-arm interventions so system gains are not misattributed to the generator."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["system_variant"] == "full_system":
            groups[(row["model_key"], row["benchmark_lane"])].append(row)
    output = []
    for (model_key, lane), subset in sorted(groups.items()):
        actions = Counter(row["intervention_action"] for row in subset)
        output.append(
            {
                "model_key": model_key,
                "model_label": EXPECTED_MODELS[model_key],
                "benchmark_lane": lane,
                "n": len(subset),
                "intervention_triggered": sum(row["intervention_triggered"] for row in subset),
                "fallback_or_degraded": actions["fallback_or_degraded"],
                "accept_rewrite": actions["accept_rewrite"],
                "preserve_draft": actions["preserve_draft"],
                "no_action": actions["no_action"],
            }
        )
    return output


def failure_taxonomy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for model_key in EXPECTED_MODELS:
        for arm in ARM_ORDER:
            subset = [
                row
                for row in rows
                if row["model_key"] == model_key
                and row["system_variant"] == arm
                and row["benchmark_lane"] in {LANE_PRIMARY, LANE_SECONDARY}
            ]
            counts: Counter[str] = Counter()
            for row in subset:
                counts.update(str(value) for value in row["material_errors"] if value)
            for error, count in counts.most_common(20):
                output.append(
                    {
                        "model_key": model_key,
                        "model_label": EXPECTED_MODELS[model_key],
                        "system_variant": arm,
                        "arm_label": ARM_LABELS[arm],
                        "material_error": error,
                        "count": count,
                        "case_count": len(subset),
                    }
                )
    return output


def make_figure(summary: list[dict[str, Any]], output: Path) -> None:
    import matplotlib.pyplot as plt

    primary = [row for row in summary if row["benchmark_lane"] == LANE_PRIMARY]
    objective = [row for row in summary if row["benchmark_lane"] == LANE_OBJECTIVE]
    colors = {
        "gemma3_270m_rc1": "#3f7f72",
        "gemma4_e2b_rc1": "#2f5f7f",
        "luna_high_rc1": "#9d3f3e",
    }
    markers = {"gemma3_270m_rc1": "o", "gemma4_e2b_rc1": "s", "luna_high_rc1": "^"}
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.1), constrained_layout=True)
    x = list(range(len(ARM_ORDER)))
    for model_key, label in EXPECTED_MODELS.items():
        values = [next(row for row in primary if row["model_key"] == model_key and row["system_variant"] == arm) for arm in ARM_ORDER]
        y = [float(row["semantic_mean"]) for row in values]
        low = [value - float(row["semantic_ci95_low"]) for value, row in zip(y, values)]
        high = [float(row["semantic_ci95_high"]) - value for value, row in zip(y, values)]
        axes[0].errorbar(x, y, yerr=[low, high], color=colors[model_key], marker=markers[model_key], linewidth=1.8, capsize=3, label=label)
    axes[0].set_title("a  Advisory semantic score on 90 Canadian cases", loc="left", fontweight="bold")
    axes[0].set_ylabel("Luna judge score (0--100; advisory)")
    axes[0].set_xticks(x, [ARM_LABELS[arm] for arm in ARM_ORDER], rotation=18, ha="right")
    axes[0].grid(axis="y", color="#e4ded2", linewidth=0.7)
    axes[0].spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False, fontsize=9)

    width = 0.22
    for index, (model_key, label) in enumerate(EXPECTED_MODELS.items()):
        values = [next(row for row in objective if row["model_key"] == model_key and row["system_variant"] == arm) for arm in ARM_ORDER]
        y = [float(row["objective_accuracy"]) for row in values]
        offsets = [value + (index - 1) * width for value in x]
        axes[1].scatter(offsets, y, color=colors[model_key], marker=markers[model_key], s=48, label=label, zorder=3)
    axes[1].set_title("b  Deterministic calculation accuracy (16 cases)", loc="left", fontweight="bold")
    axes[1].set_ylabel("Within-tolerance answers (%)")
    axes[1].set_xticks(x, [ARM_LABELS[arm] for arm in ARM_ORDER], rotation=18, ha="right")
    axes[1].set_ylim(-3, 103)
    axes[1].grid(axis="y", color="#e4ded2", linewidth=0.7)
    axes[1].spines[["top", "right"]].set_visible(False)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--paper-root", type=Path, required=True)
    parser.add_argument(
        "--skip-figure",
        action="store_true",
        help="Regenerate paper tables without importing matplotlib or replacing the validated figure.",
    )
    args = parser.parse_args()
    source = args.paper_root / "source_data"
    rows = load_rows(args.database)
    validate_complete(rows)
    response_rows = response_level(rows)
    summary_rows = arm_lane_summary(rows)
    delta_rows = paired_deltas(rows)
    resource_rows = resource_summary(rows)
    task_rows = task_family_summary(rows)
    orchestration_rows = orchestration_summary(rows)
    error_rows = failure_taxonomy(rows)

    write_csv(source / "response_level_metrics.csv", response_rows, list(response_rows[0]))
    write_csv(source / "arm_lane_summary.csv", summary_rows, list(summary_rows[0]))
    write_csv(source / "paired_semantic_deltas.csv", delta_rows, list(delta_rows[0]))
    write_csv(source / "resource_summary.csv", resource_rows, list(resource_rows[0]))
    write_csv(source / "task_family_summary.csv", task_rows, list(task_rows[0]))
    write_csv(source / "orchestration_summary.csv", orchestration_rows, list(orchestration_rows[0]))
    write_csv(source / "material_error_taxonomy.csv", error_rows, list(error_rows[0]))
    if not args.skip_figure:
        make_figure(summary_rows, args.paper_root / "figures" / "benchmark_results.pdf")
    manifest = {
        "schema_version": "open_agronomy_agent.paper_source_data.v1",
        "database": str(args.database.resolve()),
        "canonical_responses": len(rows),
        "canonical_judgments": sum(row["semantic_score"] is not None for row in rows),
        "models": list(EXPECTED_MODELS),
        "arms": ARM_ORDER,
        "bootstrap_draws": 10_000,
        "bootstrap_seed_family": 20260811,
        "uncertainty_boundary": "Case-resampling intervals describe this fixed development suite; they are not population-generalization intervals.",
        "files": [
            "response_level_metrics.csv",
            "arm_lane_summary.csv",
            "paired_semantic_deltas.csv",
            "resource_summary.csv",
            "task_family_summary.csv",
            "orchestration_summary.csv",
            "material_error_taxonomy.csv",
            "../figures/benchmark_results.pdf",
        ],
    }
    (source / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
