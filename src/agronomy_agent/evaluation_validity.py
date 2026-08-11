from __future__ import annotations

import re
import statistics
from collections import Counter
from typing import Any, Iterable


REAL_USER_ORIGINS = {
    "deidentified_grower_query",
    "deidentified_advisor_query",
    "farmer_survey",
    "support_log_with_consent",
    "participatory_field_study",
}


def _mean(values: Iterable[float]) -> float | None:
    materialized = list(values)
    return round(statistics.mean(materialized), 4) if materialized else None


def _pearson(pairs: Iterable[tuple[float, float]]) -> float | None:
    materialized = list(pairs)
    if len(materialized) < 2:
        return None
    left = [pair[0] for pair in materialized]
    right = [pair[1] for pair in materialized]
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    denominator = (
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    ) ** 0.5
    if denominator == 0:
        return None
    return round(
        sum((x - left_mean) * (y - right_mean) for x, y in materialized) / denominator,
        4,
    )


def _question_origin(row: dict[str, Any]) -> str:
    metadata = row.get("eval_metadata") if isinstance(row.get("eval_metadata"), dict) else {}
    return str(row.get("question_origin") or metadata.get("question_origin") or "missing")


def _group_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(
        str(
            row.get(key)
            or (row.get("eval_metadata") or {}).get(key)
            or "unspecified"
        )
        for row in rows
    )
    return dict(sorted(counts.items()))


def audit_question_suite(rows: list[dict[str, Any]]) -> dict[str, Any]:
    questions = [str(row.get("question") or "") for row in rows]
    origins = Counter(_question_origin(row) for row in rows)
    real_user_rows = sum(count for origin, count in origins.items() if origin in REAL_USER_ORIGINS)
    patterns = {
        "evaluator_evidence_checklist": re.compile(
            r"\b(?:what|which|how).{0,55}\b(?:evidence|observations?|measurements?|should .* check|needed|must be established|determine whether)\b",
            re.I,
        ),
        "binary_action_or_permission": re.compile(r"\b(?:should|can|is|does)\b.{0,180}\?$", re.I),
        "map_selected_point_template": re.compile(r"\bselected point\b", re.I),
        "live_or_forecast_context": re.compile(r"\b(?:today|tomorrow|this week|current forecast|forecast)\b", re.I),
        "economics_or_market_context": re.compile(r"\b(?:price|cost|pay|economic|discount|ROI|buyer)\b", re.I),
        "equipment_or_operations_context": re.compile(r"\b(?:planter|drill|opener|sprayer|combine|equipment|traffic)\b", re.I),
    }
    style_counts = {
        name: sum(bool(pattern.search(question)) for question in questions)
        for name, pattern in patterns.items()
    }
    multi_turn = sum(bool(row.get("turns")) for row in rows)
    jurisdiction_counts = _group_counts(rows, "jurisdiction")
    crop_counts = _group_counts(rows, "crop")
    max_jurisdiction_share = (
        max(jurisdiction_counts.values()) / len(rows) if rows else 0.0
    )
    blockers: list[str] = []
    if not rows:
        blockers.append("empty_suite")
    if rows and real_user_rows == 0:
        blockers.append("no_proven_real_user_questions")
    if rows and len(jurisdiction_counts) < 5:
        blockers.append("narrow_geographic_coverage")
    if rows and multi_turn == 0:
        blockers.append("no_multi_turn_decisions")
    return {
        "rows": len(rows),
        "question_origin": dict(sorted(origins.items())),
        "proven_real_user_rows": real_user_rows,
        "proven_real_user_share": round(real_user_rows / len(rows), 4) if rows else 0.0,
        "style_counts": style_counts,
        "multi_turn_rows": multi_turn,
        "mean_question_words": _mean(len(question.split()) for question in questions),
        "jurisdictions": jurisdiction_counts,
        "crops": crop_counts,
        "largest_jurisdiction_share": round(max_jurisdiction_share, 4),
        "external_validity_blocked": bool(blockers),
        "blockers": blockers,
        "supported_claim_scope": (
            "Synthetic agronomic competency and safety-boundary probes only; not representative grower usefulness."
            if real_user_rows == 0
            else "Includes traceable real-user questions, subject to the remaining coverage limits."
        ),
    }


def audit_proxy_outputs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores: list[float] = []
    invalid = 0
    for row in rows:
        score = row.get("score") if isinstance(row.get("score"), dict) else {}
        valid = bool(score.get("proxy_valid", score.get("required_total", 0) + score.get("forbidden_total", 0) + score.get("ask_total", 0) > 0))
        value = score.get("score")
        if valid and isinstance(value, (int, float)):
            scores.append(float(value))
        else:
            invalid += 1
    unique_scores = sorted(set(scores))
    return {
        "rows": len(rows),
        "valid_lexical_contract_rows": len(scores),
        "undefined_proxy_rows": invalid,
        "unique_valid_scores": unique_scores,
        "valid_score_mean": _mean(scores),
        "promotion_eligible": False,
        "metric_role": "lexical_contract_regression_diagnostic_only",
        "fatal_design_error": bool(rows) and not scores,
        "finding": (
            "No row has a scorable lexical contract; any prior numeric aggregate was an implementation artifact."
            if rows and not scores
            else "Lexical coverage can detect regressions but does not establish agronomic answer quality."
        ),
    }


def audit_automated_judge(
    rows: list[dict[str, Any]],
    manual_reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reviews = manual_reviews or []
    score_rows = [row for row in rows if isinstance(row.get("semantic_score_0_to_100"), (int, float))]
    length_pairs = [
        (
            float(len(re.findall(r"\b\w+\b", str(row.get("answer") or "")))),
            float(row["semantic_score_0_to_100"]),
        )
        for row in score_rows
    ]
    disposition = Counter(str(row.get("answer_disposition") or "missing") for row in rows)
    confidence = Counter(str(row.get("confidence") or "missing") for row in rows)
    by_id = {str(row.get("review_id") or row.get("eval_id") or ""): row for row in rows}
    known_false_accepts: list[dict[str, Any]] = []
    agronomist_reviews = 0
    for review in reviews:
        if review.get("reviewer_type") == "human_agronomist":
            agronomist_reviews += 1
        review_id = str(review.get("review_id") or review.get("eval_id") or "")
        judged = by_id.get(review_id)
        audited = str(review.get("answer_disposition") or "")
        if judged and judged.get("answer_disposition") == "pass" and audited in {"revise", "fail"}:
            known_false_accepts.append(
                {
                    "review_id": review_id,
                    "judge_disposition": "pass",
                    "audit_disposition": audited,
                    "reviewer_type": review.get("reviewer_type"),
                    "reason": review.get("reason"),
                }
            )
    high_confidence_rate = confidence.get("high", 0) / max(1, len(rows))
    pass_rate = disposition.get("pass", 0) / max(1, len(rows))
    blockers = []
    if agronomist_reviews == 0:
        blockers.append("no_blinded_independent_agronomist_calibration")
    if known_false_accepts:
        blockers.append("observed_false_accepts")
    if pass_rate >= 0.85 and high_confidence_rate >= 0.85:
        blockers.append("ceiling_and_overconfidence_risk")
    return {
        "rows": len(rows),
        "answer_disposition": dict(disposition),
        "judge_self_reported_confidence": dict(confidence),
        "pass_rate": round(pass_rate, 4),
        "high_confidence_rate": round(high_confidence_rate, 4),
        "answer_length_score_pearson": _pearson(length_pairs),
        "manual_review_rows": len(reviews),
        "independent_agronomist_review_rows": agronomist_reviews,
        "known_false_accepts": known_false_accepts,
        "promotion_eligible": False if blockers else True,
        "blockers": blockers,
        "score_role": "automated_triage_only" if blockers else "human_calibrated_automated_assistance",
    }


def audit_judge_controls(
    judgments: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    actual_by_id = {
        str(row.get("review_id") or row.get("eval_id") or ""): row
        for row in judgments
    }
    comparisons: list[dict[str, Any]] = []
    missing: list[str] = []
    for expected in expected_rows:
        review_id = str(expected.get("review_id") or expected.get("eval_id") or "")
        actual = actual_by_id.get(review_id)
        if actual is None:
            missing.append(review_id)
            continue
        expected_disposition = str(expected.get("answer_disposition") or "")
        actual_disposition = str(actual.get("answer_disposition") or "")
        comparisons.append(
            {
                "review_id": review_id,
                "expected": expected_disposition,
                "actual": actual_disposition,
                "exact_match": expected_disposition == actual_disposition,
                "false_accept": expected_disposition in {"revise", "fail"} and actual_disposition == "pass",
                "false_reject": expected_disposition == "pass" and actual_disposition in {"revise", "fail"},
                "confidence": actual.get("confidence"),
                "rationale": actual.get("rationale"),
            }
        )
    negative_controls = sum(row["expected"] in {"revise", "fail"} for row in comparisons)
    false_accepts = sum(row["false_accept"] for row in comparisons)
    exact_accuracy = sum(row["exact_match"] for row in comparisons) / max(1, len(comparisons))
    false_accept_rate = false_accepts / max(1, negative_controls)
    blocked = bool(missing or false_accepts or exact_accuracy < 0.9)
    return {
        "control_rows": len(expected_rows),
        "evaluated_rows": len(comparisons),
        "missing_rows": missing,
        "exact_disposition_accuracy": round(exact_accuracy, 4),
        "negative_controls": negative_controls,
        "false_accepts": false_accepts,
        "false_accept_rate": round(false_accept_rate, 4),
        "blocked": blocked,
        "control_boundary": "Logic and metamorphic controls, not agronomist calibration labels.",
        "comparisons": comparisons,
    }


def build_evaluation_validity_report(
    *,
    suite_rows: list[dict[str, Any]],
    output_rows: list[dict[str, Any]],
    judgment_rows: list[dict[str, Any]],
    manual_reviews: list[dict[str, Any]] | None = None,
    judge_control_judgments: list[dict[str, Any]] | None = None,
    judge_control_expected: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    question_audit = audit_question_suite(suite_rows)
    proxy_audit = audit_proxy_outputs(output_rows)
    judge_audit = audit_automated_judge(judgment_rows, manual_reviews)
    judge_controls = audit_judge_controls(
        judge_control_judgments or [], judge_control_expected or []
    ) if judge_control_expected is not None else None
    if judge_controls is not None:
        judge_audit["logic_control_audit"] = judge_controls
        if judge_controls["blocked"]:
            judge_audit["promotion_eligible"] = False
            if "logic_control_false_accept" not in judge_audit["blockers"]:
                judge_audit["blockers"].append("logic_control_false_accept")
    blockers = {
        "question_external_validity": question_audit["external_validity_blocked"],
        "proxy_construct_validity": proxy_audit["fatal_design_error"],
        "automated_judge_calibration": not judge_audit["promotion_eligible"],
    }
    return {
        "schema_version": "open_agronomy_agent.evaluation_validity_audit.v1",
        "question_suite": question_audit,
        "deterministic_proxy": proxy_audit,
        "automated_judge": judge_audit,
        "external_capability_claim_eligible": not any(blockers.values()),
        "release_blockers": [name for name, blocked in blockers.items() if blocked],
        "honest_conclusion": (
            "The current artifacts measure synthetic competency probes and system guardrail behaviour. "
            "They do not estimate the probability that a grower receives a correct, useful answer in practice."
        ),
    }
