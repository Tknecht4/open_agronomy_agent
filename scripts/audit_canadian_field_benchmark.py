#!/usr/bin/env python3
"""Audit Canadian field-question construct validity and legacy retention.

This script does not score answers.  It determines what the checked-in question
banks can legitimately measure before a model run is interpreted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CURRENT = ROOT / "data/eval/open_agronomy_canadian_performance_v1.jsonl"
DEFAULT_PROXY: Path | None = None
DEFAULT_SEMANTIC_V1: Path | None = None
DEFAULT_TRANSFER = ROOT / "data/eval/canadian_conference_transfer_gate_v2.jsonl"
DEFAULT_OUTPUT = ROOT / "data/eval/open_agronomy_canadian_performance_v1_construct_audit.json"
DEFAULT_RETENTION: Path | None = None

CANADIAN_JURISDICTIONS = {
    "canada",
    "alberta",
    "british columbia",
    "saskatchewan",
    "manitoba",
    "ontario",
    "quebec",
    "new brunswick",
    "nova scotia",
    "prince edward island",
    "newfoundland and labrador",
    "yukon",
}
REAL_USER_ORIGINS = {
    "deidentified_grower_query",
    "deidentified_advisor_query",
    "farmer_survey",
    "support_log_with_consent",
    "participatory_field_study",
}
FIELD_TERMS = re.compile(
    r"\b(field|crop|canola|wheat|corn|soybean|potato|barley|oat|pulse|pea|lentil|"
    r"orchard|vineyard|forage|pasture|soil|seed|plant|harvest|spray|scout)\b",
    re.I,
)
DECISION_TERMS = re.compile(
    r"\b(should|can|do|decide|recommend|diagnos|check|apply|spray|plant|harvest|"
    r"manage|rate|timing|risk|threshold|sample|scout|compare|evaluate)\b",
    re.I,
)
META_TERMS = re.compile(
    r"\b(which (?:public )?source|what does the (?:current )?app know|source boundary|"
    r"website|document|retrieval|knowledge base|citation|lineage trace)\b",
    re.I,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_optional_jsonl(path: Path | None) -> list[dict[str, Any]]:
    return read_jsonl(path) if path is not None and path.is_file() else []


def normalized_question(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def token_set(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def jaccard(left: str, right: str) -> float:
    a, b = token_set(left), token_set(right)
    return len(a & b) / len(a | b) if a or b else 1.0


def jurisdiction(row: dict[str, Any]) -> str:
    value = row.get("jurisdiction")
    if value is None and isinstance(row.get("field_context"), dict):
        value = row["field_context"].get("province_state")
    return str(value or "unspecified")


def is_canadian(row: dict[str, Any]) -> bool:
    place = jurisdiction(row).strip().lower()
    return place in CANADIAN_JURISDICTIONS or bool(
        re.search(r"\bcanad(?:a|ian)\b", str(row.get("question") or ""), re.I)
    )


def construct(row: dict[str, Any]) -> str:
    question = str(row.get("question") or "")
    if META_TERMS.search(question):
        return "source_or_interface_boundary"
    if FIELD_TERMS.search(question) and DECISION_TERMS.search(question):
        return "field_decision_scenario"
    if FIELD_TERMS.search(question):
        return "agronomic_knowledge_or_interpretation"
    return "other"


def template_signature(row: dict[str, Any]) -> str:
    text = normalized_question(row.get("question"))
    replace_values: list[str] = []
    for key in ("jurisdiction", "region", "crop"):
        if row.get(key):
            replace_values.append(str(row[key]))
    field = row.get("field_context") if isinstance(row.get("field_context"), dict) else {}
    replace_values.extend(str(value) for value in field.values() if isinstance(value, str))
    for value in sorted(replace_values, key=len, reverse=True):
        normalized = normalized_question(value)
        if normalized:
            text = text.replace(normalized, "<context>")
    text = re.sub(r"\b(?:alberta|saskatchewan|manitoba|ontario|quebec|canada)\b", "<place>", text)
    return text


def row_id(row: dict[str, Any]) -> str:
    return str(row.get("eval_id") or row.get("id") or "")


def _proxy_anomaly(row: dict[str, Any]) -> str | None:
    question = normalized_question(row.get("question"))
    crop = str(row.get("crop") or "").lower()
    scenario = str(row.get("scenario_type") or "").lower()
    weather = str(row.get("weather") or "").lower()
    if crop == "soybean" and scenario == "fertility_n_loss":
        return "template_crop_mismatch_soybean_blanket_nitrogen_frame"
    if "harvest" in scenario and ("frost risk" in question or "dry wind and limited stored water" in question):
        return "template_weather_does_not_explain_stated_harvest_delay"
    if "early planted" in question and question.count(" with ") >= 2:
        return "template_grammar_and_causal_ambiguity"
    if weather and weather not in question:
        return "structured_weather_not_rendered"
    return None


def audit(
    current_rows: list[dict[str, Any]],
    proxy_rows: list[dict[str, Any]],
    semantic_v1_rows: list[dict[str, Any]],
    transfer_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    current_questions = {normalized_question(row.get("question")) for row in current_rows}
    current_primary = [row for row in current_rows if row.get("benchmark_lane") == "canadian_decision_quality"]
    current_transfer = [row for row in current_rows if row.get("benchmark_lane") == "canadian_advisory_transfer"]
    exact_counts = Counter(normalized_question(row.get("question")) for row in proxy_rows)
    signatures = Counter(template_signature(row) for row in proxy_rows if is_canadian(row))
    retention: list[dict[str, Any]] = []
    seen_proxy: set[str] = set()
    for row in proxy_rows:
        if not is_canadian(row):
            continue
        question = normalized_question(row.get("question"))
        anomaly = _proxy_anomaly(row)
        if question in seen_proxy or exact_counts[question] > 1:
            decision = "reject_exact_duplicate"
        elif anomaly:
            decision = "defer_reauthor_and_source_check"
        elif construct(row) != "field_decision_scenario":
            decision = "defer_not_field_decision"
        else:
            decision = "retain_legacy_template_regression_only"
        seen_proxy.add(question)
        nearest = max((jaccard(question, candidate) for candidate in current_questions), default=0.0)
        retention.append(
            {
                "source_suite": "data/eval/agribench_proxy_eval.jsonl",
                "source_eval_id": row_id(row),
                "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
                "question": row.get("question"),
                "jurisdiction": jurisdiction(row),
                "crop": row.get("crop"),
                "task_family": row.get("task_family"),
                "construct": construct(row),
                "template_cluster_size": signatures[template_signature(row)],
                "nearest_current_token_jaccard": round(nearest, 4),
                "anomaly": anomaly,
                "decision": decision,
                "claim_eligible": False,
                "reason": (
                    "Generated from a region-by-scenario template and previously used during system development; "
                    "its keyword-derived gold summary is not independent agronomic ground truth."
                ),
            }
        )

    origin_counts = Counter(
        str(row.get("question_origin") or "project_authored_or_legacy_synthetic_not_real_user")
        for row in current_rows
    )
    real_user = sum(count for origin, count in origin_counts.items() if origin in REAL_USER_ORIGINS)
    proxy_decisions = Counter(row["decision"] for row in retention)
    report = {
        "schema_version": "open_agronomy_agent.canadian_field_benchmark_audit.v1",
        "status": "development_construct_only",
        "current_suite": {
            "rows": len(current_rows),
            "canadian_rows": sum(is_canadian(row) for row in current_rows),
            "field_decision_rows": sum(construct(row) == "field_decision_scenario" for row in current_rows),
            "canadian_field_decision_rows": sum(
                is_canadian(row) and construct(row) == "field_decision_scenario"
                for row in current_rows
            ),
            "primary_semantic_rows": len(current_primary),
            "secondary_advisory_rows": len(current_transfer),
            "regression_or_interface_rows": len(current_rows) - len(current_primary) - len(current_transfer),
            "proven_real_user_rows": real_user,
            "question_origin_counts": dict(sorted(origin_counts.items())),
            "primary_coverage": {
                "jurisdictions": dict(sorted(Counter(jurisdiction(row) for row in current_primary).items())),
                "categories": dict(sorted(Counter(str(row.get("category") or "unspecified") for row in current_primary).items())),
                "crops": dict(sorted(Counter(str(row.get("crop") or "unspecified") for row in current_primary).items())),
                "question_styles": dict(sorted(Counter(str(row.get("question_style") or "unspecified") for row in current_primary).items())),
                "multi_turn_rows": sum(bool(row.get("turns")) for row in current_primary),
                "nonempty_field_context_rows": sum(bool(row.get("field_context")) for row in current_primary),
                "geometry_payload_rows": sum(
                    bool((row.get("field_context") or {}).get("geometry"))
                    for row in current_primary
                    if isinstance(row.get("field_context"), dict)
                ),
                "independently_adjudicated_reference_rows": sum(
                    str(row.get("expert_reference_status") or "").startswith("independent_")
                    for row in current_primary
                ),
            },
        },
        "legacy_proxy": {
            "available_in_checkout": bool(proxy_rows),
            "rows": len(proxy_rows),
            "unique_questions": len(set(normalized_question(row.get("question")) for row in proxy_rows)),
            "duplicate_rows": len(proxy_rows) - len(set(normalized_question(row.get("question")) for row in proxy_rows)),
            "canadian_rows": len(retention),
            "canadian_unique_questions": len({normalized_question(row["question"]) for row in retention}),
            "canadian_jurisdictions": dict(sorted(Counter(row["jurisdiction"] for row in retention).items())),
            "retention_decisions": dict(sorted(proxy_decisions.items())),
            "largest_template_clusters": [
                {"signature": signature, "rows": count}
                for signature, count in signatures.most_common(12)
            ],
            "gold_reference_status": "keyword_contract_summary_not_independent_agronomic_ground_truth",
        },
        "legacy_input_inventory": {
            "proxy_rows": len(proxy_rows),
            "semantic_v1_rows": len(semantic_v1_rows),
            "standalone_transfer_rows": len(transfer_rows),
            "note": (
                "Legacy banks are optional research inputs. Their absence does not block auditing the consolidated suite."
            ),
        },
        "construct_verdict": {
            "what_it_measures": [
                "synthetic Canadian field-scenario response behaviour",
                "kernel, retrieval, evidence-boundary, and safety regressions",
                "answer-origin and fallback dependence when generation traces are retained",
            ],
            "what_it_does_not_measure": [
                "frequency or distribution of real grower questions",
                "probability of a correct and useful field recommendation",
                "field outcomes or economic benefit",
                "independently certified agronomic correctness",
            ],
            "primary_capability_claim_eligible": False,
            "blockers": [
                "zero proven real-user questions",
                "primary reference points are project-authored and not independently adjudicated",
                "legacy proxy gold answers are keyword-derived",
                "service and live tool orchestration is not exercised by the text-only runner",
            ],
            "next_authoring_gaps": [
                "traceable deidentified grower and adviser questions with consent and province/crop labels",
                "multi-turn cases where the correct next action is to ask one discriminating question",
                "objective calculations and unit conversions with exact tolerances",
                "field geometry cases that execute local soil, weather, and history services rather than merely naming tools",
                "longitudinal cases where a later answer must use dated field observations and distinguish stale from current evidence",
                "answer-blind agronomist adjudication of reference claims, material errors, and acceptable uncertainty",
            ],
        },
        "required_benchmark_roles": {
            "raw_model": "user question only",
            "baseline": "raw model plus the Open Agronomy kernel and answer contract",
            "kernel_field_context": "kernel plus the same structured field context admitted to the full-system arm",
            "agronomic_rag": (
                "kernel, governed evidence, deterministic in-process tools and guards, and verifier policy; "
                "external service orchestration remains a separate product gate"
            ),
        },
        "promotion_rule": (
            "Do not promote a legacy proxy row into the semantic capability lane without answer-blind source review, "
            "case-specific reference claims and material errors, and an independent agronomy reviewer."
        ),
    }
    return report, retention


def render_markdown(report: dict[str, Any]) -> str:
    current = report["current_suite"]
    proxy = report["legacy_proxy"]
    verdict = report["construct_verdict"]
    lines = [
        "# Canadian field benchmark construct audit",
        "",
        "## Verdict",
        "",
        "The current benchmark is useful development evidence, but it is not an estimate of real-world agronomist-level correctness. The original proxy is retained as regression raw material, not promoted as ground truth.",
        "",
        "## Current suite",
        "",
        f"- {current['rows']} total rows; {current['primary_semantic_rows']} primary semantic field-decision rows; {current['secondary_advisory_rows']} secondary advisory rows.",
        f"- {current['regression_or_interface_rows']} rows test regression or interface behaviour and must not be averaged into agronomic answer quality.",
        f"- Proven real-user questions: {current['proven_real_user_rows']}.",
        f"- Primary multi-turn cases: {current['primary_coverage']['multi_turn_rows']}; primary executable geometry payloads: {current['primary_coverage']['geometry_payload_rows']}.",
        "",
        "## Original proxy recovery",
        "",
        *(
            [
                f"- {proxy['rows']} rows but only {proxy['unique_questions']} unique questions; {proxy['duplicate_rows']} duplicate rows.",
                f"- {proxy['canadian_rows']} Canadian rows and {proxy['canadian_unique_questions']} unique Canadian questions.",
                f"- Retention decisions: `{json.dumps(proxy['retention_decisions'], sort_keys=True)}`.",
                f"- Reference boundary: {proxy['gold_reference_status']}.",
            ]
            if proxy["available_in_checkout"]
            else [
                "- Legacy proxy banks are not packaged in this public checkout. The consolidated 241-case suite remains independently auditable.",
            ]
        ),
        "",
        "## Claims",
        "",
        "What it can measure:",
        "",
        *[f"- {value}" for value in verdict["what_it_measures"]],
        "",
        "What it cannot measure:",
        "",
        *[f"- {value}" for value in verdict["what_it_does_not_measure"]],
        "",
        "## Required arms",
        "",
        *[f"- `{key}`: {value}." for key, value in report["required_benchmark_roles"].items()],
        "",
        "## Promotion rule",
        "",
        report["promotion_rule"],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--proxy", type=Path, default=DEFAULT_PROXY)
    parser.add_argument("--semantic-v1", type=Path, default=DEFAULT_SEMANTIC_V1)
    parser.add_argument("--transfer", type=Path, default=DEFAULT_TRANSFER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--retention", type=Path, default=DEFAULT_RETENTION)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report, retention = audit(
        read_jsonl(args.current),
        read_optional_jsonl(args.proxy),
        read_optional_jsonl(args.semantic_v1),
        read_optional_jsonl(args.transfer),
    )
    expected_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    expected_retention = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in retention)
    markdown_path = args.output.with_suffix(".md")
    expected_markdown = render_markdown(report)
    if args.check:
        if args.output.read_text(encoding="utf-8") != expected_json:
            raise SystemExit("benchmark audit drift; rebuild without --check")
        if args.retention is not None and args.retention.read_text(encoding="utf-8") != expected_retention:
            raise SystemExit("benchmark retention drift; rebuild without --check")
        if markdown_path.read_text(encoding="utf-8") != expected_markdown:
            raise SystemExit("benchmark audit markdown drift; rebuild without --check")
    else:
        args.output.write_text(expected_json, encoding="utf-8")
        if args.retention is not None:
            args.retention.write_text(expected_retention, encoding="utf-8")
        markdown_path.write_text(expected_markdown, encoding="utf-8")
    print(json.dumps({"status": report["status"], "retention_rows": len(retention)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
