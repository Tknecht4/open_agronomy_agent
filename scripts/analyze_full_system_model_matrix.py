#!/usr/bin/env python3
"""Audit and summarize the paired baseline-versus-full-system benchmark database."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import random
import re
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.evals import score_item_agribench_proxy  # noqa: E402

DEFAULT_EXPERIMENT = ROOT / "outputs" / "full_system_model_matrix_20260801"
DEFAULT_SUITE = ROOT / "data" / "eval" / "open_agronomy_internal_v2.jsonl"
SCHEMA_VERSION = "open_agronomy_agent.full_system_benchmark_analysis.v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return round(statistics.fmean(rows), 3) if rows else None


def percentile(sorted_values: list[float], proportion: float) -> float:
    if not sorted_values:
        raise ValueError("cannot take a percentile of no values")
    position = (len(sorted_values) - 1) * proportion
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def paired_delta(values: list[tuple[float, float]], *, seed: int, samples: int = 10_000) -> dict[str, Any]:
    """Return a paired delta and deterministic non-parametric bootstrap interval."""

    deltas = [full - baseline for baseline, full in values]
    if not deltas:
        return {"pairs": 0, "baseline_mean": None, "full_system_mean": None, "delta": None}
    rng = random.Random(seed)
    bootstrap = sorted(
        statistics.fmean(deltas[rng.randrange(len(deltas))] for _ in deltas)
        for _ in range(samples)
    )
    wins = sum(delta > 0 for delta in deltas)
    ties = sum(delta == 0 for delta in deltas)
    losses = sum(delta < 0 for delta in deltas)
    return {
        "pairs": len(deltas),
        "baseline_mean": mean(baseline for baseline, _ in values),
        "full_system_mean": mean(full for _, full in values),
        "delta": round(statistics.fmean(deltas), 3),
        "delta_95pct_bootstrap_ci": [
            round(percentile(bootstrap, 0.025), 3),
            round(percentile(bootstrap, 0.975), 3),
        ],
        "win_tie_loss": {"full_better": wins, "tie": ties, "baseline_better": losses},
    }


def repetition_metrics(output: str) -> dict[str, Any]:
    words = re.findall(r"[a-z0-9]+", output.casefold())
    unique_word_ratio = len(set(words)) / len(words) if words else 0.0
    ngrams = [tuple(words[index : index + 8]) for index in range(max(0, len(words) - 7))]
    unique_ngram_ratio = len(set(ngrams)) / len(ngrams) if ngrams else 1.0
    return {
        "word_count": len(words),
        "unique_word_ratio": round(unique_word_ratio, 4),
        "unique_8gram_ratio": round(unique_ngram_ratio, 4),
        "suspected_repetition": bool(
            len(words) >= 100 and (unique_word_ratio < 0.24 or unique_ngram_ratio < 0.55)
        ),
    }


def _load_suite(path: Path) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {str(row["eval_id"]): row for row in rows}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def model_contribution_summary(
    connection: sqlite3.Connection,
    suite_path: Path,
) -> list[dict[str, Any]]:
    """Separate model draft behavior from deterministic system rescue.

    The final full-system output can be a deterministic hold, a verifier
    fallback, an accepted editor rewrite, or the original model draft. Treating
    all four as model quality hides whether a small model actually synthesized
    the answer. This report preserves both constructs.
    """

    suite = _load_suite(suite_path)
    models = [
        str(row[0])
        for row in connection.execute("SELECT DISTINCT model_id FROM paired_response ORDER BY model_id")
    ]
    summaries: list[dict[str, Any]] = []
    for model_id in models:
        rows = list(
            connection.execute(
                """
                SELECT c.eval_id, c.eval_metadata_json, c.question,
                       fullresp.output final_output, fullresp.score_json final_score_json,
                       fullresp.metadata_json, fullresp.verification_json,
                       fullresp.generation_stats_json, fullresp.generation_path
                FROM model m
                JOIN benchmark_run run ON run.model_key=m.model_key
                    AND run.mode='agronomic_rag' AND run.is_canonical=1
                JOIN response fullresp ON fullresp.run_id=run.run_id
                JOIN benchmark_case c ON c.eval_id=fullresp.eval_id
                WHERE m.model_id=?
                ORDER BY c.ordinal
                """,
                (model_id,),
            )
        )
        counters: Counter[str] = Counter()
        lanes: dict[str, Counter[str]] = {}
        draft_scores: list[float] = []
        final_scores: list[float] = []
        paired_scores: list[tuple[float, float]] = []
        for row in rows:
            counters["rows"] += 1
            eval_metadata = json.loads(row["eval_metadata_json"] or "{}")
            lane = str(eval_metadata.get("benchmark_lane") or "unknown")
            lane_counter = lanes.setdefault(lane, Counter())
            lane_counter["rows"] += 1
            verification = json.loads(row["verification_json"] or "{}")
            generation_stats = json.loads(row["generation_stats_json"] or "{}")
            deterministic_hold = row["generation_path"] == "deterministic_evidence_sufficiency_hold"
            fallback = bool(verification.get("fallback_applied"))
            rewrite = bool(verification.get("rewrite_accepted"))
            if deterministic_hold:
                counters["deterministic_holds"] += 1
                lane_counter["deterministic_holds"] += 1
            elif fallback:
                counters["verifier_fallbacks"] += 1
                lane_counter["verifier_fallbacks"] += 1
            elif rewrite:
                counters["accepted_rewrites"] += 1
                lane_counter["accepted_rewrites"] += 1
            else:
                counters["direct_model_drafts"] += 1
                lane_counter["direct_model_drafts"] += 1
            if int(generation_stats.get("generation_tokens") or 0) >= 480:
                counters["generation_token_cap_hits"] += 1
                lane_counter["generation_token_cap_hits"] += 1

            draft = verification.get("draft_output")
            if not isinstance(draft, str) or not draft.strip():
                continue
            counters["raw_drafts_present"] += 1
            lane_counter["raw_drafts_present"] += 1
            repetition = repetition_metrics(draft)
            if repetition["suspected_repetition"]:
                counters["raw_draft_suspected_repetition"] += 1
                lane_counter["raw_draft_suspected_repetition"] += 1
            question = str(row["question"] or "").strip()
            if question and question.casefold() in draft.casefold():
                counters["raw_draft_question_copy"] += 1
                lane_counter["raw_draft_question_copy"] += 1

            item = suite.get(str(row["eval_id"]))
            if item is None:
                continue
            score = score_item_agribench_proxy(
                draft,
                item,
                json.loads(row["metadata_json"] or "{}"),
            )
            final_score = json.loads(row["final_score_json"] or "{}").get("score")
            if score.get("proxy_valid") and score.get("score") is not None and final_score is not None:
                draft_value = float(score["score"])
                final_value = float(final_score)
                draft_scores.append(draft_value)
                final_scores.append(final_value)
                paired_scores.append((draft_value, final_value))

        lane_summary = {
            lane: {
                **dict(sorted(values.items())),
                "system_rescue_rate": _ratio(
                    values["deterministic_holds"] + values["verifier_fallbacks"],
                    values["rows"],
                ),
                "direct_model_draft_rate": _ratio(values["direct_model_drafts"], values["rows"]),
            }
            for lane, values in sorted(lanes.items())
        }
        rows_count = counters["rows"]
        rescue_count = counters["deterministic_holds"] + counters["verifier_fallbacks"]
        summaries.append(
            {
                "model_id": model_id,
                **dict(sorted(counters.items())),
                "system_rescue_rows": rescue_count,
                "system_rescue_rate": _ratio(rescue_count, rows_count),
                "direct_model_draft_rate": _ratio(counters["direct_model_drafts"], rows_count),
                "raw_draft_cap_hit_rate": _ratio(counters["generation_token_cap_hits"], rows_count),
                "lexical_contract_diagnostic": {
                    "rows": len(paired_scores),
                    "raw_draft_mean": mean(draft_scores),
                    "final_system_mean": mean(final_scores),
                    "system_minus_raw_draft": mean(final - draft for draft, final in paired_scores),
                    "construct": "lexical_contract_coverage_not_answer_quality",
                },
                "by_benchmark_lane": lane_summary,
            }
        )
    return summaries


def gap_register(
    contribution: list[dict[str, Any]],
    evidence_fabric: dict[str, Any],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = [
        {
            "priority": "P0",
            "gap": "final_system_scores_conflate_model_quality_with_system_rescue",
            "repair": "report raw draft, rewrite, fallback, and deterministic-hold outcomes separately",
            "validation": "analysis schema v2 model_contribution section",
        },
        {
            "priority": "P0",
            "gap": "public_v2_no_longer_unseen_after_developer_exposure",
            "repair": "retire v2 and freeze a source-row-disjoint v3 before any model run",
            "validation": "frozen profile hashes plus internal, training, and RAG separation audit",
        },
        {
            "priority": "P1",
            "gap": "external_crop_mcq_validity_does_not_establish_field_advisory_validity",
            "repair": "report CROP as objective knowledge transfer and retain agronomist review as an unmet promotion gate",
            "validation": "claim boundary in public v3 contract",
        },
    ]
    if float(evidence_fabric.get("unresolved_coverage_rate") or 0.0) >= 0.25:
        gaps.append(
            {
                "priority": "P0",
                "gap": "evidence_packets_frequently_record_absent_or_stale_obligations",
                "evidence": {
                    "coverage_rows": evidence_fabric["coverage_rows"],
                    "unresolved_rows": evidence_fabric["unresolved_absent_stale_or_conflicting_rows"],
                    "unresolved_rate": evidence_fabric["unresolved_coverage_rate"],
                },
                "repair": "surface coverage limits to the answer policy and prioritize corpus/live-tool work by missing slot",
                "validation": "coverage-by-slot improvement without converting unknown evidence to adequate",
            }
        )
    for row in contribution:
        if float(row.get("system_rescue_rate") or 0.0) >= 0.50:
            gaps.append(
                {
                    "priority": "P0",
                    "model_id": row["model_id"],
                    "gap": "majority_of_full_system_answers_are_system_rescues",
                    "evidence": {
                        "rows": row["rows"],
                        "system_rescue_rows": row["system_rescue_rows"],
                        "system_rescue_rate": row["system_rescue_rate"],
                    },
                    "repair": "improve or replace the draft synthesizer; do not market rescued final accuracy as model accuracy",
                    "validation": "lower rescue rate without reduced blinded answer quality or safety",
                }
            )
        if float(row.get("raw_draft_cap_hit_rate") or 0.0) >= 0.25:
            gaps.append(
                {
                    "priority": "P0",
                    "model_id": row["model_id"],
                    "gap": "draft_generation_frequently_hits_token_ceiling",
                    "evidence": {
                        "cap_hits": row.get("generation_token_cap_hits", 0),
                        "cap_hit_rate": row["raw_draft_cap_hit_rate"],
                    },
                    "repair": "validate a bounded small-model synthesis contract on internal data before promotion",
                    "validation": "cap-hit and repetition reductions with non-inferior internal quality",
                }
            )
    return gaps


def evidence_fabric_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    packet_status = {
        str(row["capture_status"]): int(row["rows"])
        for row in connection.execute(
            "SELECT capture_status, COUNT(*) rows FROM evidence_packet GROUP BY capture_status ORDER BY capture_status"
        )
    }
    answer_status = {
        str(row["answer_status"] or "unknown"): int(row["rows"])
        for row in connection.execute(
            "SELECT answer_status, COUNT(*) rows FROM evidence_packet GROUP BY answer_status ORDER BY answer_status"
        )
    }
    coverage = {
        str(row["status"]): int(row["rows"])
        for row in connection.execute(
            "SELECT status, COUNT(*) rows FROM query_coverage_state GROUP BY status ORDER BY status"
        )
    }
    slots = [
        {
            "slot_key": str(row["slot_key"]),
            "rows": int(row["rows"]),
            "adequate": int(row["adequate"] or 0),
            "partial": int(row["partial"] or 0),
            "absent": int(row["absent"] or 0),
            "stale": int(row["stale"] or 0),
            "conflicting": int(row["conflicting"] or 0),
            "out_of_scope": int(row["out_of_scope"] or 0),
        }
        for row in connection.execute(
            """
            SELECT slot_key, COUNT(*) rows,
                   SUM(status='ADEQUATE') adequate, SUM(status='PARTIAL') partial,
                   SUM(status='ABSENT') absent, SUM(status='STALE') stale,
                   SUM(status='CONFLICTING') conflicting, SUM(status='OUT_OF_SCOPE') out_of_scope
            FROM query_coverage_state
            GROUP BY slot_key ORDER BY COUNT(*) DESC, slot_key
            """
        )
    ]
    capsule_review = {
        str(row["review_state"]): int(row["rows"])
        for row in connection.execute(
            "SELECT review_state, COUNT(*) rows FROM evidence_capsule GROUP BY review_state ORDER BY review_state"
        )
    }
    packets = sum(packet_status.values())
    unresolved = coverage.get("ABSENT", 0) + coverage.get("STALE", 0) + coverage.get("CONFLICTING", 0)
    return {
        "packets": packets,
        "packet_capture_status": packet_status,
        "validated_answer_status": answer_status,
        "coverage_state_counts": coverage,
        "coverage_rows": sum(coverage.values()),
        "unresolved_absent_stale_or_conflicting_rows": unresolved,
        "unresolved_coverage_rate": _ratio(unresolved, sum(coverage.values())),
        "coverage_by_slot": slots,
        "capsule_review_state": capsule_review,
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def audit_contract(connection: sqlite3.Connection) -> tuple[dict[str, int], list[dict[str, Any]]]:
    violations: list[dict[str, Any]] = []
    counters = Counter()
    query = """
        SELECT r.response_id, r.eval_id, m.model_id, br.system_variant, bc.question,
               r.output, r.exact_messages_json, r.context_block,
               r.generation_stats_json, r.generation_path,
               (SELECT COUNT(*) FROM retrieved_document d WHERE d.response_id=r.response_id) doc_count,
               (SELECT COUNT(*) FROM graph_hit g WHERE g.response_id=r.response_id) graph_count,
               (SELECT COUNT(*) FROM tool_note t WHERE t.response_id=r.response_id) tool_count
        FROM response r
        JOIN benchmark_run br ON br.run_id=r.run_id AND br.is_canonical=1
        JOIN model m ON m.model_key=br.model_key
        JOIN benchmark_case bc ON bc.eval_id=r.eval_id
        ORDER BY br.system_variant, r.response_id
    """
    for row in connection.execute(query):
        messages = json.loads(row["exact_messages_json"])
        stats = json.loads(row["generation_stats_json"]) if row["generation_stats_json"] else {}
        repetition = repetition_metrics(str(row["output"] or ""))
        if not str(row["output"] or "").strip():
            counters["empty_outputs"] += 1
            violations.append({"kind": "empty_output", "response_id": row["response_id"]})
        if repetition["suspected_repetition"]:
            counters["suspected_repetition"] += 1
            violations.append(
                {
                    "kind": "suspected_repetition",
                    "response_id": row["response_id"],
                    "eval_id": row["eval_id"],
                    "model_id": row["model_id"],
                    "system_variant": row["system_variant"],
                    **repetition,
                }
            )
        if int(stats.get("generation_tokens") or 0) >= 480:
            counters["generation_token_cap_hits"] += 1
            violations.append(
                {
                    "kind": "generation_token_cap_hit",
                    "response_id": row["response_id"],
                    "eval_id": row["eval_id"],
                    "model_id": row["model_id"],
                    "system_variant": row["system_variant"],
                    "generation_tokens": int(stats["generation_tokens"]),
                }
            )
        if row["system_variant"] in {"raw_model", "model_only_baseline", "kernel_only"}:
            if row["context_block"] is not None or row["doc_count"] or row["graph_count"] or row["tool_count"]:
                counters["baseline_context_violations"] += 1
                violations.append({"kind": "baseline_context_present", "response_id": row["response_id"]})
            expected_message_count = 1 if row["system_variant"] == "raw_model" else 2
            if len(messages) != expected_message_count or messages[-1].get("role") != "user" or messages[-1].get("content") != row["question"]:
                counters["baseline_message_violations"] += 1
                violations.append({"kind": "baseline_messages_not_question_only", "response_id": row["response_id"]})
        else:
            if row["generation_path"] == "deterministic_evidence_sufficiency_hold":
                counters["deterministic_evidence_sufficiency_holds"] += 1
            if row["context_block"] is None:
                counters["full_system_without_context_block"] += 1
            counters["full_system_documents"] += int(row["doc_count"])
            counters["full_system_graph_hits"] += int(row["graph_count"])
            counters["full_system_tool_notes"] += int(row["tool_count"])
    return dict(sorted(counters.items())), violations


def model_comparisons(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    models = [row[0] for row in connection.execute("SELECT DISTINCT model_id FROM paired_response ORDER BY model_id")]
    comparisons: list[dict[str, Any]] = []
    for model in models:
        rows = list(connection.execute("SELECT * FROM paired_response WHERE model_id=? ORDER BY eval_id", (model,)))
        proxy_pairs = [
            (float(row["baseline_proxy_score"]), float(row["full_system_proxy_score"]))
            for row in rows
            if row["baseline_proxy_score"] is not None and row["full_system_proxy_score"] is not None
        ]
        semantic_pairs = [
            (float(row["baseline_semantic_score"]), float(row["full_system_semantic_score"]))
            for row in rows
            if row["baseline_semantic_score"] is not None and row["full_system_semantic_score"] is not None
        ]
        seed = int(hashlib.sha256(model.encode("utf-8")).hexdigest()[:16], 16)
        comparisons.append(
            {
                "model_id": model,
                "model_revision": rows[0]["model_revision"] if rows else None,
                "paired_rows": len(rows),
                "proxy_diagnostic": paired_delta(proxy_pairs, seed=seed),
                "semantic_primary": paired_delta(semantic_pairs, seed=seed ^ 0x5A17),
                "latency": {
                    "baseline_mean_seconds": mean(float(row["baseline_elapsed_seconds"]) for row in rows),
                    "full_system_mean_seconds": mean(float(row["full_system_elapsed_seconds"]) for row in rows),
                },
                "semantic_disposition_transitions": dict(
                    sorted(
                        Counter(
                            f"{row['baseline_disposition'] or 'unjudged'}->{row['full_system_disposition'] or 'unjudged'}"
                            for row in rows
                        ).items()
                    )
                ),
            }
        )
    return comparisons


def system_effect_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    full_model_count = int(
        connection.execute(
            """
            SELECT COUNT(DISTINCT run.model_key)
            FROM benchmark_run run
            WHERE run.is_canonical=1 AND run.mode='agronomic_rag'
            """
        ).fetchone()[0]
    )
    full_response_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM response resp
            JOIN benchmark_run run ON run.run_id=resp.run_id
            WHERE run.is_canonical=1 AND run.mode='agronomic_rag'
            """
        ).fetchone()[0]
    )
    path_rows = {
        str(row["path"]): {
            "rows": int(row["rows"]),
            "semantic_mean": float(row["semantic_mean"]) if row["semantic_mean"] is not None else None,
            "judged_rows": int(row["judged_rows"]),
            "pass": int(row["pass"] or 0),
            "revise": int(row["revise"] or 0),
            "fail": int(row["fail"] or 0),
        }
        for row in connection.execute(
            """
            SELECT COALESCE(resp.generation_path, 'generated') path, COUNT(*) rows,
                   ROUND(AVG(j.semantic_score), 3) semantic_mean,
                   COUNT(j.response_id) judged_rows,
                   SUM(j.answer_disposition='pass') pass,
                   SUM(j.answer_disposition='revise') revise,
                   SUM(j.answer_disposition='fail') fail
            FROM response resp
            JOIN benchmark_run run ON run.run_id=resp.run_id AND run.is_canonical=1
            LEFT JOIN semantic_judgment j ON j.response_id=resp.response_id
            WHERE run.mode='agronomic_rag'
            GROUP BY path
            """
        )
    }
    verifier_rows = {
        str(row["outcome"]): {
            "rows": int(row["rows"]),
            "semantic_mean": float(row["semantic_mean"]) if row["semantic_mean"] is not None else None,
            "judged_rows": int(row["judged_rows"]),
        }
        for row in connection.execute(
            """
            SELECT CASE
                     WHEN json_extract(resp.verification_json, '$.fallback_applied')=1 THEN 'fallback_applied'
                     WHEN json_extract(resp.verification_json, '$.rewrite_accepted')=1 THEN 'rewrite_accepted'
                     ELSE 'no_accepted_verifier_change'
                   END outcome,
                   COUNT(*) rows, ROUND(AVG(j.semantic_score), 3) semantic_mean,
                   COUNT(j.response_id) judged_rows
            FROM response resp
            JOIN benchmark_run run ON run.run_id=resp.run_id AND run.is_canonical=1
            LEFT JOIN semantic_judgment j ON j.response_id=resp.response_id
            WHERE run.mode='agronomic_rag'
            GROUP BY outcome
            """
        )
    }
    diversity = {
        int(row["distinct_outputs"]): int(row["cases"])
        for row in connection.execute(
            """
            SELECT distinct_outputs, COUNT(*) cases FROM (
                SELECT resp.eval_id, COUNT(DISTINCT resp.output_sha256) distinct_outputs
                FROM response resp
                JOIN benchmark_run run ON run.run_id=resp.run_id
                WHERE run.is_canonical=1 AND run.mode='agronomic_rag'
                GROUP BY resp.eval_id
                HAVING COUNT(DISTINCT run.model_key)=?
            ) GROUP BY distinct_outputs ORDER BY distinct_outputs
            """,
            (full_model_count,),
        )
    }
    compared_case_count = sum(diversity.values())
    identical_case_count = diversity.get(1, 0)
    paired_paths = {
        str(row["path"]): {
            "pairs": int(row["pairs"]),
            "semantic_delta": float(row["delta"]),
            "full_better": int(row["wins"]),
            "tie": int(row["ties"]),
            "baseline_better": int(row["losses"]),
        }
        for row in connection.execute(
            """
            SELECT COALESCE(fullresp.generation_path, 'generated') path, COUNT(*) pairs,
                   ROUND(AVG(jfull.semantic_score-jbase.semantic_score), 3) delta,
                   SUM(jfull.semantic_score>jbase.semantic_score) wins,
                   SUM(jfull.semantic_score=jbase.semantic_score) ties,
                   SUM(jfull.semantic_score<jbase.semantic_score) losses
            FROM benchmark_run base_run
            JOIN response base ON base.run_id=base_run.run_id
            JOIN semantic_judgment jbase ON jbase.response_id=base.response_id
            JOIN benchmark_run full_run ON full_run.model_key=base_run.model_key
                 AND full_run.mode='agronomic_rag' AND full_run.is_canonical=1
            JOIN response fullresp ON fullresp.run_id=full_run.run_id AND fullresp.eval_id=base.eval_id
            JOIN semantic_judgment jfull ON jfull.response_id=fullresp.response_id
            WHERE base_run.mode='baseline' AND base_run.is_canonical=1
            GROUP BY path
            """
        )
    }
    return {
        "full_system_model_count": full_model_count,
        "full_system_response_count": full_response_count,
        "cases_compared_across_all_models": compared_case_count,
        "full_system_by_generation_path": path_rows,
        "full_system_by_verifier_outcome": verifier_rows,
        "distinct_full_outputs_per_case_histogram": diversity,
        "cases_identical_across_all_models": identical_case_count,
        "cases_with_model_dependent_full_outputs": compared_case_count - identical_case_count,
        "paired_effect_by_full_generation_path": paired_paths,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    contract = report["contract_audit"]
    lines = [
        "# Full-system model matrix audit",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "This is a paired local development benchmark, not a held-out claim or human agronomist sign-off. "
        "When blinded semantic judgments are present they are the primary answer-quality signal; proxy scores "
        "remain diagnostic.",
        "",
        "## Completeness and integrity",
        "",
        f"- Models: **{counts['models']}**",
        f"- Canonical runs: **{counts['canonical_runs']}**",
        f"- Cases: **{counts['cases']}**",
        f"- Responses: **{counts['responses']}**",
        f"- Semantic judgments: **{counts['semantic_judgments']}**",
        f"- SQLite integrity: **{report['integrity_check']}**; foreign-key errors: **{report['foreign_key_errors']}**",
        f"- Contract/anomaly records: **{len(report['anomalies'])}**",
        "",
        "## Input-contract audit",
        "",
        f"- Baseline context violations: **{contract.get('baseline_context_violations', 0)}**",
        f"- Baseline message violations: **{contract.get('baseline_message_violations', 0)}**",
        f"- Full-system retrieved documents: **{contract.get('full_system_documents', 0)}**",
        f"- Full-system graph hits: **{contract.get('full_system_graph_hits', 0)}**",
        f"- Full-system tool notes: **{contract.get('full_system_tool_notes', 0)}**",
        f"- Deterministic evidence-sufficiency holds: **{contract.get('deterministic_evidence_sufficiency_holds', 0)}**",
        f"- Generation token-cap hits: **{contract.get('generation_token_cap_hits', 0)}**",
        f"- Suspected repetitive answers: **{contract.get('suspected_repetition', 0)}**",
        f"- Duplicate generated-output groups: **{contract.get('duplicate_generated_output_groups_within_model_arm', 0)}**",
        "",
        "## Paired results by model",
        "",
        "| Model | Semantic baseline | Semantic full | Delta [95% bootstrap CI] | Full/base/tie | Proxy delta | Baseline s | Full s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["model_comparisons"]:
        semantic = item["semantic_primary"]
        proxy = item["proxy_diagnostic"]
        ci = semantic.get("delta_95pct_bootstrap_ci")
        delta_text = "unjudged" if semantic.get("delta") is None else f"{semantic['delta']} [{ci[0]}, {ci[1]}]"
        wtl = semantic.get("win_tie_loss") or {}
        lines.append(
            f"| `{item['model_id']}` | {semantic.get('baseline_mean')} | {semantic.get('full_system_mean')} | "
            f"{delta_text} | {wtl.get('full_better', 0)}/{wtl.get('baseline_better', 0)}/{wtl.get('tie', 0)} | "
            f"{proxy.get('delta')} | {item['latency']['baseline_mean_seconds']} | {item['latency']['full_system_mean_seconds']} |"
        )
    effect = report["system_effect"]
    verifier = effect["full_system_by_verifier_outcome"]
    paths = effect["full_system_by_generation_path"]
    compared_cases = effect["cases_compared_across_all_models"]
    full_responses = effect["full_system_response_count"]
    lines.extend(
        [
            "",
            "## System dominance",
            "",
            f"- Cases compared across all {effect['full_system_model_count']} full-system model arms: **{compared_cases}**",
            f"- Cases with one identical full-system answer across all models: **{effect['cases_identical_across_all_models']}/{compared_cases}**",
            f"- Cases retaining model-dependent full-system outputs: **{effect['cases_with_model_dependent_full_outputs']}/{compared_cases}**",
            f"- Deterministic evidence holds: **{paths.get('deterministic_evidence_sufficiency_hold', {}).get('rows', 0)}/{full_responses} responses**",
            f"- Verifier fallbacks: **{verifier.get('fallback_applied', {}).get('rows', 0)}/{full_responses} responses**",
            f"- Accepted verifier rewrites: **{verifier.get('rewrite_accepted', {}).get('rows', 0)}/{full_responses} responses**, semantic mean **{verifier.get('rewrite_accepted', {}).get('semantic_mean')}**",
        ]
    )
    lines.extend(
        [
            "",
            "## Model contribution versus system rescue",
            "",
            "A final full-system answer is not automatically a model-authored answer. Deterministic evidence "
            "holds and verifier fallbacks are reported as system rescues; accepted rewrites and unchanged "
            "drafts remain visible separately.",
            "",
            "| Model | Rows | Direct drafts | Rewrites | Fallbacks | Holds | Rescue rate | Cap-hit rate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in report["model_contribution"]:
        lines.append(
            f"| `{item['model_id']}` | {item['rows']} | {item.get('direct_model_drafts', 0)} | "
            f"{item.get('accepted_rewrites', 0)} | {item.get('verifier_fallbacks', 0)} | "
            f"{item.get('deterministic_holds', 0)} | {item['system_rescue_rate']} | "
            f"{item['raw_draft_cap_hit_rate']} |"
        )
    fabric = report["evidence_fabric"]
    lines.extend(
        [
            "",
            "## Evidence-fabric coverage",
            "",
            f"- Evidence packets: **{fabric['packets']}**",
            f"- Packet capture states: `{json.dumps(fabric['packet_capture_status'], sort_keys=True)}`",
            f"- Query coverage states: `{json.dumps(fabric['coverage_state_counts'], sort_keys=True)}`",
            f"- Absent, stale, or conflicting obligations: **{fabric['unresolved_absent_stale_or_conflicting_rows']}/{fabric['coverage_rows']} ({fabric['unresolved_coverage_rate']})**",
            f"- Capsule review states: `{json.dumps(fabric['capsule_review_state'], sort_keys=True)}`",
        ]
    )
    lines.extend(["", "## Gap register", ""])
    for item in report["gap_register"]:
        model = f" (`{item['model_id']}`)" if item.get("model_id") else ""
        lines.append(f"- **{item['priority']}** `{item['gap']}`{model}: {item['repair']}")
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This internal suite is a development set and is not claim-eligible. Any automated judgments may "
            "contain self- or model-family-preference bias. Paired raw responses, exact model messages, context "
            "packets, retrieved text, model revisions, and judgments remain queryable in the local SQLite database.",
            "",
        ]
    )
    return "\n".join(lines)


def export_pairs(connection: sqlite3.Connection, destination: Path) -> None:
    rows = list(connection.execute("SELECT * FROM paired_response ORDER BY model_id, eval_id"))
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(rows[0].keys() if rows else [])
        writer.writerows(tuple(row) for row in rows)


def analyze(database: Path, output_dir: Path, suite_path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
    counts = {
        "models": int(connection.execute("SELECT COUNT(*) FROM model").fetchone()[0]),
        "canonical_runs": int(connection.execute("SELECT COUNT(*) FROM benchmark_run WHERE is_canonical=1").fetchone()[0]),
        "cases": int(connection.execute("SELECT COUNT(*) FROM benchmark_case").fetchone()[0]),
        "responses": int(
            connection.execute(
                "SELECT COUNT(*) FROM response r JOIN benchmark_run br ON br.run_id=r.run_id WHERE br.is_canonical=1"
            ).fetchone()[0]
        ),
        "semantic_judgments": int(connection.execute("SELECT COUNT(*) FROM semantic_judgment").fetchone()[0]),
        "paired_rows": int(connection.execute("SELECT COUNT(*) FROM paired_response").fetchone()[0]),
    }
    contract, anomalies = audit_contract(connection)
    duplicate_groups = list(
        connection.execute(
            """
            SELECT m.model_id, br.system_variant, COALESCE(r.generation_path, 'generated') generation_path,
                   r.output_sha256, COUNT(*) n
            FROM response r
            JOIN benchmark_run br ON br.run_id=r.run_id
            JOIN model m ON m.model_key=br.model_key
            WHERE br.is_canonical=1
            GROUP BY m.model_id, br.system_variant, generation_path, r.output_sha256 HAVING COUNT(*) > 1
            """
        )
    )
    contract["duplicate_generated_output_groups_within_model_arm"] = sum(
        row["generation_path"] != "deterministic_evidence_sufficiency_hold"
        for row in duplicate_groups
    )
    contract["duplicate_deterministic_hold_groups"] = sum(
        row["generation_path"] == "deterministic_evidence_sufficiency_hold"
        for row in duplicate_groups
    )
    for row in duplicate_groups:
        kind = (
            "duplicate_deterministic_hold_group"
            if row["generation_path"] == "deterministic_evidence_sufficiency_hold"
            else "duplicate_generated_output_group"
        )
        anomalies.append({"kind": kind, **dict(row)})
    contribution = model_contribution_summary(connection, suite_path)
    fabric = evidence_fabric_summary(connection)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "database_path": display_path(database),
        "database_sha256": sha256(database),
        "development_suite_claim_eligible": False,
        "semantic_judgment_primary": True,
        "integrity_check": integrity,
        "foreign_key_errors": len(foreign_keys),
        "counts": counts,
        "contract_audit": contract,
        "model_comparisons": model_comparisons(connection),
        "system_effect": system_effect_summary(connection),
        "model_contribution": contribution,
        "evidence_fabric": fabric,
        "gap_register": gap_register(contribution, fabric),
        "anomalies": anomalies,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "benchmark_analysis.json", report)
    (output_dir / "benchmark_analysis.md").write_text(render_markdown(report), encoding="utf-8")
    with (output_dir / "anomalies.jsonl").open("w", encoding="utf-8") as handle:
        for anomaly in anomalies:
            handle.write(json.dumps(anomaly, ensure_ascii=False, sort_keys=True) + "\n")
    export_pairs(connection, output_dir / "paired_results.csv")
    connection.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    args = parser.parse_args()
    experiment = args.experiment_dir.resolve()
    report = analyze(experiment / "full_system_benchmark.sqlite3", experiment, args.suite.resolve())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
