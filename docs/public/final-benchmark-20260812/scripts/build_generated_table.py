#!/usr/bin/env python3
"""Render the compact manuscript table from validated benchmark CSVs."""

from __future__ import annotations

import argparse
import csv
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
    found = [row for row in rows if all(row.get(key) == value for key, value in criteria.items())]
    if len(found) != 1:
        raise ValueError(f"expected one row for {criteria}, found {len(found)}")
    return found[0]


def f1(value: str) -> str:
    return f"{float(value):.1f}"


def pct(value: str) -> str:
    return f"{float(value):.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-root", type=Path, required=True)
    args = parser.parse_args()
    source = args.paper_root / "source_data"
    summary = read_csv(source / "arm_lane_summary.csv")
    deltas = read_csv(source / "paired_semantic_deltas.csv")
    resources = read_csv(source / "resource_summary.csv")

    body: list[str] = []
    for model in MODEL_ORDER:
        raw = one(
            summary,
            model_key=model,
            system_variant="raw_model",
            benchmark_lane="canadian_decision_quality",
        )
        agent = one(
            summary,
            model_key=model,
            system_variant="full_system",
            benchmark_lane="canadian_decision_quality",
        )
        delta = one(
            deltas,
            model_key=model,
            comparison="full_system_minus_raw_model",
            benchmark_lane="canadian_decision_quality",
        )
        raw_calc = one(
            summary,
            model_key=model,
            system_variant="raw_model",
            benchmark_lane="objective_agronomic_calculation",
        )
        agent_calc = one(
            summary,
            model_key=model,
            system_variant="full_system",
            benchmark_lane="objective_agronomic_calculation",
        )
        agent_resource = one(resources, model_key=model, system_variant="full_system")
        body.append(
            "{} & {} & {} & {:+.1f} [{:.1f}, {:.1f}] & {} & {} & {} \\\\".format(
                MODEL_LABELS[model],
                f1(raw["semantic_mean"]),
                f1(agent["semantic_mean"]),
                float(delta["mean_delta_points"]),
                float(delta["ci95_low"]),
                float(delta["ci95_high"]),
                pct(raw_calc["objective_accuracy"]),
                pct(agent_calc["objective_accuracy"]),
                f1(agent_resource["latency_median_seconds"]),
            )
        )

    tex = r"""\begin{table*}[t]
  \centering
  \caption{\textbf{Raw-model versus governed-agent results.} Semantic scores are Luna High advisory judgments on 90 primary Canadian cases; brackets are 95\% fixed-suite case-bootstrap intervals for the paired agent-minus-raw difference. Calculation accuracy is deterministic on 16 cases. Latency is median candidate-generation time per case; it excludes judging.}
  \label{tab:benchmark}
  \small
  \begin{tabular}{lrrrrrr}
    \toprule
    Model & Raw sem. & Agent sem. & Paired $\Delta$ [95\% CI] & Raw calc. (\%) & Agent calc. (\%) & Agent latency (s) \\
    \midrule
""" + "\n".join(body) + r"""
    \bottomrule
  \end{tabular}
\end{table*}
"""
    (args.paper_root / "generated_table.tex").write_text(tex, encoding="utf-8")
    print(args.paper_root / "generated_table.tex")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
