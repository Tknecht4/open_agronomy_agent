from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agronomy_agent.agent import AgentResources, build_context, load_agent_resources
from agronomy_agent.evals import eval_question, load_jsonl
from agronomy_agent.paths import repo_path
from agronomy_agent.phase5_retrieval_diagnostics import diagnose_retrieval


def diagnose_item(item: dict[str, Any], resources: AgentResources | None = None) -> dict[str, Any]:
    question = eval_question(item)
    context = build_context(question, resources=resources)
    required = item.get("required_patterns", [])
    sources = [doc.source for doc in context.retrieved_docs]
    phase5_metrics = diagnose_retrieval(
        question=question,
        docs=context.retrieved_docs,
        route_namespaces=context.route.namespaces,
        required_patterns=required,
        required_concepts=item.get("required_concepts", []),
        gold_doc_ids=item.get("gold_support_doc_ids", item.get("support_doc_ids", [])),
        cache_status=(context.cache_status or {}).get("retrieval"),
    )
    return {
        "eval_id": item["eval_id"],
        "task_family": item.get("task_family", "unknown"),
        "hardness_bucket": item.get("hardness_bucket", item.get("difficulty", "unspecified")),
        "difficulty": item.get("difficulty", "unspecified"),
        "scenario_type": item.get("scenario_type", "unspecified"),
        "expected_tools": item.get("expected_tools", []),
        "is_multi_turn": bool(item.get("turns")),
        "question": question,
        "doc_count": len(context.retrieved_docs),
        "graph_hit_count": len(context.graph_hits),
        "tool_notes": [note.name for note in context.tool_notes],
        "route": {
            "question_type": context.route.question_type,
            "risk_level": context.route.risk_level,
            "namespaces": list(context.route.namespaces),
            "answer_style": context.route.answer_style,
            "audience": context.route.audience,
        },
        "retrieved_doc_ids": [doc.doc_id for doc in context.retrieved_docs],
        "retrieved_namespaces": [list(doc.namespaces) for doc in context.retrieved_docs],
        "graph_node_ids": [hit.node_id for hit in context.graph_hits],
        "graph_namespaces": [list(hit.namespaces) for hit in context.graph_hits],
        "retrieved_sources": sources,
        "source_diversity": len(set(sources)),
        "required_patterns": len(required),
        "required_patterns_supported_by_retrieval": phase5_metrics["required_patterns_supported_by_retrieval"],
        "retrieval_required_support_rate": phase5_metrics["retrieval_required_support_rate"],
        "top_doc_score": context.retrieved_docs[0].score if context.retrieved_docs else 0.0,
        "phase5_retrieval": phase5_metrics,
        "source_type_counts": phase5_metrics["source_type_counts"],
        "applied_vs_ontology_ratio": phase5_metrics["applied_vs_ontology_ratio"],
        "route_namespace_match_rate": phase5_metrics["route_namespace_match_rate"],
        "support_per_context_token": phase5_metrics["support_per_context_token"],
        "recall_at_k": phase5_metrics["recall_at_k"],
        "mrr": phase5_metrics["mrr"],
        "ndcg_at_k": phase5_metrics["ndcg_at_k"],
        "retrieval_cache_status": phase5_metrics["cache_status"],
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_family: dict[str, list[dict[str, Any]]] = {}
    by_hardness: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_family.setdefault(row["task_family"], []).append(row)
        by_hardness.setdefault(row["hardness_bucket"], []).append(row)
    return {
        "items": len(rows),
        "mean_doc_count": round(sum(row["doc_count"] for row in rows) / max(1, len(rows)), 2),
        "mean_source_diversity": round(sum(row["source_diversity"] for row in rows) / max(1, len(rows)), 2),
        "mean_required_support_rate": round(sum(row["retrieval_required_support_rate"] for row in rows) / max(1, len(rows)), 3),
        "tool_note_counts": {
            name: sum(1 for row in rows if name in row["tool_notes"])
            for name in sorted({name for row in rows for name in row["tool_notes"]})
        },
        "by_family": {
            family: {
                "items": len(items),
                "mean_required_support_rate": round(sum(row["retrieval_required_support_rate"] for row in items) / len(items), 3),
                "mean_source_diversity": round(sum(row["source_diversity"] for row in items) / len(items), 2),
            }
            for family, items in sorted(by_family.items())
        },
        "by_hardness": {
            hardness: {
                "items": len(items),
                "mean_required_support_rate": round(sum(row["retrieval_required_support_rate"] for row in items) / len(items), 3),
                "mean_source_diversity": round(sum(row["source_diversity"] for row in items) / len(items), 2),
            }
            for hardness, items in sorted(by_hardness.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect retrieval/tool context for an eval suite before generation.")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--output-dir", default="outputs/retrieval_diagnostics")
    parser.add_argument("--rag-config", default="configs/rag_governed_runtime_v2.yaml")
    parser.add_argument("--max-samples", type=int)
    args = parser.parse_args()
    suite = load_jsonl(repo_path(args.suite), args.max_samples)
    resources = load_agent_resources(args.rag_config)
    rows = [diagnose_item(item, resources=resources) for item in suite]
    out = repo_path(args.output_dir) / Path(args.suite).stem
    out.mkdir(parents=True, exist_ok=True)
    with (out / "items.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = summarize(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
