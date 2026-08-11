#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


SOURCE_PRIORITY = (
    "data/eval/agronomy_hardness_buckets_eval.jsonl",
    "data/eval/final_mvp_assessment_eval.jsonl",
    "data/eval/final_mvp_stability_probe_eval.jsonl",
    "data/eval/cca_local_style_eval.jsonl",
    "data/eval/cca_aligned_eval.jsonl",
    "data/eval/agronomy_mvp_eval.jsonl",
)

TOPIC_MAP = {
    "nutrient": "Nutrition",
    "fertility": "Nutrition",
    "soil": "Soils",
    "water": "Water",
    "product": "Pests",
    "pest": "Pests",
    "weed": "Weeds",
    "disease": "Diseases",
    "plant": "Diseases",
    "seed": "Seed Hybrids",
    "crop": "Horticulture",
    "weather": "Weather",
    "precision": "Soils",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def eval_question(item: dict[str, Any]) -> str:
    if "question" in item:
        return str(item["question"]).strip()
    turns = item.get("turns") or []
    latest = next((turn.get("content", "") for turn in reversed(turns) if turn.get("role") == "user"), "")
    return str(latest).strip()


def topic_categories(item: dict[str, Any]) -> list[str]:
    family = str(item.get("task_family", "")).lower()
    scenario = str(item.get("scenario_type", "")).lower()
    text = f"{family} {scenario}"
    topics = []
    for hint, category in TOPIC_MAP.items():
        if hint in text and category not in topics:
            topics.append(category)
    return topics[:3] or ["Horticulture"]


def gold_answer(item: dict[str, Any]) -> str:
    required = [pattern.replace("|", " / ") for pattern in item.get("required_patterns", [])]
    ask_for = [pattern.replace("|", " / ") for pattern in item.get("ask_for_patterns", [])]
    forbidden = [pattern.replace("|", " / ") for pattern in item.get("forbidden_patterns", [])]
    crop = item.get("crop", "the crop")
    region = item.get("region", "the local production region")
    parts = [
        f"A strong answer should address {crop} in {region} directly, using plain farmer/advisor language.",
        "It should cover these decision points: " + "; ".join(required) + ".",
    ]
    if ask_for:
        parts.append("If information is missing, it should ask for: " + "; ".join(ask_for) + ".")
    if forbidden:
        parts.append("It should avoid unsafe or misleading framing such as: " + "; ".join(forbidden) + ".")
    return " ".join(parts)


def normalize(item: dict[str, Any], source: str) -> dict[str, Any]:
    out = dict(item)
    out["question"] = eval_question(item)
    out.pop("turns", None)
    out["gold_answer"] = gold_answer(item)
    out["topic_categories"] = topic_categories(item)
    out["crop_name"] = item.get("crop", "NA")
    out["crop_group"] = crop_group(str(item.get("crop", "NA")))
    out["split"] = "local_proxy_public_sources"
    out.setdefault("source_basis", [])
    out["source_basis"] = list(dict.fromkeys([*out["source_basis"], "AI AgriBench-style local proxy"]))
    out["proxy_source_suite"] = source
    out["eval_metadata"] = {
        "benchmark_style": "ai_agribench_v0_5_proxy",
        "official_ai_agribench": False,
        "judge_metrics": ["accuracy", "relevance", "completeness", "conciseness"],
    }
    return out


def crop_group(crop: str) -> str:
    c = crop.lower()
    if c in {"corn", "soybean", "wheat", "canola", "sorghum", "cotton", "dry bean"}:
        return "Broadacre_Row_Crops"
    if c in {"alfalfa", "forage"}:
        return "Forage_Crops"
    if c in {"potato", "vegetable", "garlic"}:
        return "Commercial_Vegetables"
    return "Mixed_Agronomy"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a 416-item local AI AgriBench-style proxy suite.")
    parser.add_argument("--output", default="data/eval/agribench_proxy_eval.jsonl")
    parser.add_argument("--manifest", default="data/eval/agribench_proxy_manifest.json")
    parser.add_argument("--target", type=int, default=416)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    seen_questions: set[str] = set()
    seen_ids: set[str] = set()
    selected: list[dict[str, Any]] = []
    counts = Counter()
    loaded_sources = [(source, load_jsonl(root / source)) for source in SOURCE_PRIORITY]
    for source, rows in loaded_sources:
        for item in rows:
            question = eval_question(item)
            question_key = " ".join(question.lower().split())
            source_id = f"{source}:{item['eval_id']}"
            if not question_key or question_key in seen_questions or source_id in seen_ids:
                continue
            seen_questions.add(question_key)
            seen_ids.add(source_id)
            normalized = normalize(item, source)
            normalized["eval_id"] = f"agribench_proxy_{len(selected) + 1:03d}_{item['eval_id']}"
            selected.append(normalized)
            counts[source] += 1
            if len(selected) >= args.target:
                break
        if len(selected) >= args.target:
            break
    if len(selected) < args.target:
        for source, rows in loaded_sources:
            for item in rows:
                source_id = f"{source}:{item['eval_id']}"
                if source_id in seen_ids:
                    continue
                seen_ids.add(source_id)
                normalized = normalize(item, source)
                normalized["eval_id"] = f"agribench_proxy_{len(selected) + 1:03d}_{item['eval_id']}"
                normalized["proxy_duplicate_question_variant"] = True
                selected.append(normalized)
                counts[source] += 1
                if len(selected) >= args.target:
                    break
            if len(selected) >= args.target:
                break
    if len(selected) < args.target:
        raise SystemExit(f"only found {len(selected)} unique items; target was {args.target}")
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest = {
        "suite": args.output,
        "items": len(selected),
        "official_ai_agribench": False,
        "purpose": "Local proxy for AI AgriBench-style regression and readiness screening.",
        "source_counts": dict(counts),
        "unique_question_count": len(seen_questions),
        "duplicate_question_variants": sum(1 for row in selected if row.get("proxy_duplicate_question_variant")),
        "topics": Counter(topic for row in selected for topic in row["topic_categories"]),
        "hardness": Counter(row.get("hardness_bucket", row.get("difficulty", "unspecified")) for row in selected),
        "limitations": [
            "Gold answers are rubric summaries derived from local eval requirements, not expert-edited AI AgriBench answers.",
            "Use for local trend prediction and failure diagnosis only; public leaderboard scores require official AI AgriBench evaluation.",
        ],
    }
    (root / args.manifest).write_text(json.dumps(manifest, indent=2, default=dict), encoding="utf-8")
    print(json.dumps(manifest, indent=2, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
