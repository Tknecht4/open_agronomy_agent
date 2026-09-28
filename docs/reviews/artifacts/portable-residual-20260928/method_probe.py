"""Exploratory, project-authored method-family contrast probe; never runtime input."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from agronomy_agent.method_context import METHODS, requested_methods


HERE = Path(__file__).resolve().parent
LABELS = HERE / "method-contrasts.json"
RESULT = HERE / "method-analysis.json"


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def main() -> None:
    label_bytes = LABELS.read_bytes()
    corpus = json.loads(label_bytes)
    families = set(corpus["supported_families"])
    assert families == set(METHODS)
    ids = [row["id"] for row in corpus["cases"]]
    assert len(ids) == len(set(ids))
    records = []
    group_counts = defaultdict(lambda: Counter())
    family_counts = {family: Counter() for family in sorted(families)}
    for case in corpus["cases"]:
        expected = set(case["expected"])
        assert expected <= families
        observed = set(requested_methods(case["question"]))
        assert observed <= families
        fp = observed - expected
        fn = expected - observed
        record = {
            "id": case["id"],
            "group": case["group"],
            "question": case["question"],
            "expected": sorted(expected),
            "observed": sorted(observed),
            "false_positive": sorted(fp),
            "false_negative": sorted(fn),
            "exact": expected == observed,
        }
        records.append(record)
        counts = group_counts[case["group"]]
        counts["cases"] += 1
        counts["exact"] += int(record["exact"])
        counts["tp"] += len(expected & observed)
        counts["fp"] += len(fp)
        counts["fn"] += len(fn)
        for family in families:
            family_counts[family]["tp" if family in expected and family in observed else
                                  "fp" if family in observed else
                                  "fn" if family in expected else "tn"] += 1

    def summarize(counts: Counter, *, include_cases: bool = False) -> dict:
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        out = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": _ratio(tp, tp + fp),
            "recall": _ratio(tp, tp + fn),
        }
        if include_cases:
            out.update({"cases": counts["cases"], "exact": counts["exact"],
                        "exact_rate": _ratio(counts["exact"], counts["cases"])})
        return out

    total = Counter()
    for counts in group_counts.values():
        total.update(counts)
    result = {
        "status": "project_authored_exploratory_in_sample_selector_probe",
        "labels_sha256": hashlib.sha256(label_bytes).hexdigest(),
        "selector_sha256": hashlib.sha256((HERE.parents[3] / "src/agronomy_agent/method_context.py").read_bytes()).hexdigest(),
        "supported_family_count": len(families),
        "overall": summarize(total, include_cases=True),
        "by_group": {group: summarize(counts, include_cases=True) for group, counts in sorted(group_counts.items())},
        "by_family": {family: summarize(counts) for family, counts in family_counts.items()},
        "records": records,
    }
    RESULT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"overall": result["overall"], "by_group": result["by_group"]}, indent=2))


if __name__ == "__main__":
    main()
