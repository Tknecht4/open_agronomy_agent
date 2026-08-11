"""Non-composite reporting for the canonical Open Agronomy Benchmark."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


_LOCAL_GUARD_IDS = {
    "field_data_guard",
    "fertility_guard",
    "label_guard",
    "nutrient_4r_guard",
    "pesticide_safety_guard",
    "resistance_management_guard",
    "salinity_sodicity_guard",
    "soil_structure_guard",
    "weather_guard",
}
_PUBLIC_ADAPTER_IDS = {
    "daymet_single_pixel_daily",
    "epa_ppls_product_search",
    "nasa_power_daily",
    "nass_quickstats_crop_stats",
    "nrcs_soil_survey_geometry",
    "openet_point_timeseries",
}


def _eligible_rate(passed: int, eligible: int) -> float | None:
    """Return an explicit eligible-case rate; ineligible rows are not failures."""

    return round(passed / eligible, 4) if eligible else None


def _benchmark_output_contract_pass(output: str) -> bool:
    words = re.findall(r"\b\w+\b", output)
    paragraphs = [part for part in re.split(r"\n\s*\n", output.strip()) if part.strip()]
    has_forbidden_shape = bool(re.search(r"(?m)^\s*(?:[-*#]|\d+[.)]\s)", output))
    return bool(output.strip()) and len(words) <= 170 and len(paragraphs) == 2 and not has_forbidden_shape


def _french_output_language_pass(output: str) -> bool:
    tokens = set(re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", output.lower()))
    markers = {
        "avant", "avec", "culture", "dans", "des", "données", "étiquette", "faire", "la", "les",
        "mesures", "ne", "pas", "pour", "provinciales", "puis", "sol", "source", "vérifier",
    }
    return len(tokens & markers) >= 4


def _system_interface_results(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Audit production-interface contracts without pretending they score advice quality."""

    rows = connection.execute(
        """
        SELECT m.model_id, m.model_revision, m.model_config_sha256,
               json_extract(c.eval_metadata_json, '$.benchmark_lane') AS benchmark_lane,
               json_extract(c.eval_metadata_json, '$.language') AS expected_language,
               br.answer_profile, r.output, r.exact_messages_json, r.context_block, r.field_context_json,
               r.metadata_json, r.generation_path
        FROM response r
        JOIN benchmark_run br ON br.run_id = r.run_id
        JOIN model m ON m.model_key = br.model_key
        JOIN benchmark_case c ON c.eval_id = r.eval_id
        WHERE br.is_canonical = 1 AND br.system_variant = 'full_system'
        ORDER BY m.model_id, m.model_revision, m.model_config_sha256, c.ordinal
        """
    ).fetchall()
    grouped: dict[tuple[str, str | None, str | None], list[sqlite3.Row]] = {}
    for row in rows:
        key = (str(row["model_id"]), row["model_revision"], row["model_config_sha256"])
        grouped.setdefault(key, []).append(row)

    results: list[dict[str, Any]] = []
    for (model_id, revision, config_sha), model_rows in sorted(grouped.items()):
        intervention_counts: Counter[str] = Counter()
        generation_paths: Counter[str] = Counter()
        route_present = exact_messages = evidence_lineage = 0
        field_context_cases = field_context_bound = 0
        non_english_cases = language_preserved = 0
        context_admission_trace = strong_primary = weak_retrieval_admitted = 0
        output_contract_eligible = output_contract_passes = 0
        local_guard_cases = local_guard_cases_complete = 0
        missing_local_guards: Counter[str] = Counter()
        public_adapter_expectations: Counter[str] = Counter()
        legacy_unimplemented_expectations: Counter[str] = Counter()
        lane_counts: Counter[str] = Counter()
        for row in model_rows:
            metadata = json.loads(row["metadata_json"])
            lane_counts[str(row["benchmark_lane"] or "legacy_unspecified")] += 1
            expected_language = str(row["expected_language"] or "English")
            if expected_language != "English":
                non_english_cases += 1
                language_preserved += expected_language == "French" and _french_output_language_pass(str(row["output"]))
            messages = json.loads(row["exact_messages_json"] or "[]")
            exact_messages += bool(messages and all(item.get("role") and item.get("content") for item in messages))
            field = json.loads(row["field_context_json"] or "{}")
            if field:
                field_context_cases += 1
                field_context_bound += bool(str(row["context_block"] or "").strip())
            route = metadata.get("route") or {}
            route_present += all(route.get(key) for key in ("question_type", "risk_level", "namespaces"))
            fabric = metadata.get("evidence_fabric") or {}
            evidence_lineage += bool(fabric.get("record_sha256") and fabric.get("evidence_packet"))
            admission = metadata.get("context_admission") or {}
            context_admission_trace += bool(admission)
            handshake = metadata.get("evidence_handshake") or {}
            has_strong = bool(
                handshake.get("primary_doc_id")
                and (
                    float(handshake.get("primary_query_coverage") or 0.0) >= 0.25
                    or (
                        float(handshake.get("primary_query_coverage") or 0.0) >= 0.16
                        and float(handshake.get("primary_relevance_score") or 0.0) >= 4.2
                    )
                )
            )
            strong_primary += has_strong
            weak_retrieval_admitted += bool(admission.get("candidate_retrieval_admitted") and not has_strong)
            expected = set(metadata.get("expected_tools") or [])
            missing = set(metadata.get("missing_expected_tools") or [])
            expected_local = expected & _LOCAL_GUARD_IDS
            missing_local = missing & _LOCAL_GUARD_IDS
            if expected_local:
                local_guard_cases += 1
                local_guard_cases_complete += not missing_local
                missing_local_guards.update(missing_local)
            public_adapter_expectations.update(expected & _PUBLIC_ADAPTER_IDS)
            legacy_unimplemented_expectations.update(
                expected - _LOCAL_GUARD_IDS - _PUBLIC_ADAPTER_IDS
            )
            verification = metadata.get("answer_verification") or {}
            intervention_counts[str(verification.get("intervention_action") or "not_run")] += 1
            generation_paths[str(row["generation_path"] or "generated_answer")] += 1
            if row["answer_profile"] == "benchmark":
                output_contract_eligible += 1
                output_contract_passes += _benchmark_output_contract_pass(str(row["output"]))
        count = len(model_rows)
        results.append({
            "model_id": model_id,
            "model_revision": revision,
            "model_config_sha256": config_sha,
            "responses": count,
            "lane_coverage": dict(sorted(lane_counts.items())),
            "generation_input_lineage_rate": round(exact_messages / count, 4),
            "field_context_binding": {
                "eligible_cases": field_context_cases,
                "bound_cases": field_context_bound,
                "rate": _eligible_rate(field_context_bound, field_context_cases),
            },
            "non_english_language_preservation": {
                "eligible_cases": non_english_cases,
                "preserved_cases": language_preserved,
                "rate": _eligible_rate(language_preserved, non_english_cases),
            },
            "route_trace_rate": round(route_present / count, 4),
            "required_tool_trace": {
                "local_guard_cases": local_guard_cases,
                "complete_local_guard_cases": local_guard_cases_complete,
                "complete_local_guard_case_rate": _eligible_rate(
                    local_guard_cases_complete,
                    local_guard_cases,
                ),
                "missing_local_guard_counts": dict(sorted(missing_local_guards.items())),
                "public_adapter_expectation_counts": dict(sorted(public_adapter_expectations.items())),
                "public_adapter_execution_status": (
                    "not_exercised_by_core_agent_text_only_harness"
                    if public_adapter_expectations else "not_applicable"
                ),
                "legacy_unimplemented_expectation_counts": dict(
                    sorted(legacy_unimplemented_expectations.items())
                ),
            },
            "context_admission_trace_rate": round(context_admission_trace / count, 4),
            "strong_primary_cases": strong_primary,
            "weak_retrieval_admitted": (
                weak_retrieval_admitted if context_admission_trace == count else None
            ),
            "evidence_lineage_rate": round(evidence_lineage / count, 4),
            "answer_origin_counts": {
                "generation_paths": dict(sorted(generation_paths.items())),
                "verifier_interventions": dict(sorted(intervention_counts.items())),
            },
            "output_contract_pass_rate": _eligible_rate(output_contract_passes, output_contract_eligible),
            "output_contract_eligible_cases": output_contract_eligible,
            "single_composite_score": None,
        })
    return results


def build_report(database: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    lanes = [dict(row) for row in connection.execute(
        "SELECT * FROM benchmark_lane_summary ORDER BY model_id, model_revision, system_variant, benchmark_lane"
    )]
    models = [dict(row) for row in connection.execute(
        "SELECT model_id, model_revision, model_config_path, model_config_sha256 FROM model ORDER BY model_id, model_revision, model_config_sha256"
    )]
    counts = {
        "models": int(connection.execute("SELECT COUNT(*) FROM model").fetchone()[0]),
        "runs": int(connection.execute("SELECT COUNT(*) FROM benchmark_run").fetchone()[0]),
        "responses": int(connection.execute("SELECT COUNT(*) FROM response").fetchone()[0]),
        "paired_responses": int(connection.execute("SELECT COUNT(*) FROM paired_response").fetchone()[0]),
        "automated_triage_judgments": int(connection.execute("SELECT COUNT(*) FROM semantic_judgment").fetchone()[0]),
        "role_scoped_judge_assessments": int(
            connection.execute("SELECT COUNT(*) FROM judge_assessment").fetchone()[0]
        ),
    }
    interface_results = _system_interface_results(connection)
    connection.close()
    expected_per_model = int(manifest["rows"]) * len(manifest.get("default_modes") or ["baseline", "agronomic_rag"])
    complete_models = sum(
        1
        for model in models
        if sum(
            int(row["response_count"])
            for row in lanes
            if row["model_id"] == model["model_id"]
            and row["model_revision"] == model["model_revision"]
            and row["model_config_sha256"] == model["model_config_sha256"]
        ) == expected_per_model
    )
    evaluation_partition = manifest.get("evaluation_partition") or "legacy_mixed"
    public_partition = evaluation_partition == "public"
    public_metric_roles = {
        str(source.get("metric_role") or "") for source in manifest.get("sources") or []
    }
    public_reference_diagnostic = "deterministic_reference_overlap_diagnostic" in public_metric_roles
    public_claim_boundary = str(
        (manifest.get("evaluation_policy") or {}).get("claim_boundary")
        or "Public external diagnostic only; not Canadian field-advisory validity."
    )
    return {
        "schema_version": "open_agronomy_agent.benchmark_report.v1",
        "benchmark_id": manifest["benchmark_id"],
        "suite_sha256": manifest["suite_sha256"],
        "suite_rows": manifest["rows"],
        "lane_counts": manifest["lane_counts"],
        "run_status": "complete" if models and complete_models == len(models) else "partial_or_smoke",
        "complete_models": complete_models,
        "models": models,
        "counts": counts,
        "lane_results": lanes,
        "system_interface_contract": manifest.get("system_interface_contract"),
        "system_interface_harness": {
            "generation_scope": "core_agent_text_only",
            "service_orchestration_exercised": False,
            "public_adapters": "registered expectations are reported separately and not counted as local guard misses",
        },
        "system_interface_results": interface_results,
        "single_composite_score": None,
        "external_capability_claim_eligible": False,
        "evaluation_partition": evaluation_partition,
        "public_benchmark_score_claim_eligible": bool(public_partition and manifest.get("claim_eligible")),
        "grower_advisory_claim_eligible": False,
        "human_calibration_status": "missing_or_external_to_database",
        "interpretation": (
            ({
                "external_real_farmer_agronomy_qa": (
                    "Normalized token overlap with published external answers; not semantic correctness."
                ),
                "claim_boundary": public_claim_boundary,
                "automated_triage": "Optional blinded triage only; never the primary or promotion metric.",
            } if public_reference_diagnostic else {
                "public_crop_science_mcq": "Objective exact-match accuracy on the frozen controlled CROP English profile.",
                "claim_boundary": public_claim_boundary,
                "automated_triage": "Not used for public scoring.",
            })
            if public_partition
            else {
                "canadian_decision_quality": "Project-owned answer-quality lane; requires blinded independent agronomist review.",
                "canadian_advisory_transfer": "Project-owned Canadian advisory scenarios; answer quality requires blinded independent review.",
                "field_history_lineage": "Field-history, source authority, and continuity trace behaviour; not field-outcome evidence.",
                "objective_agronomic_calculation": "Deterministic numeric tolerance accuracy with explicit units; reported separately from advice quality.",
                "official_source_answer_boundary": "Source-specific factual and scope regression; historically exposed to development.",
                "retrieval_lineage": "Expected-source trace regression; not answer quality.",
                "automated_triage": "Optional prioritization evidence only; self-reported judge confidence is not calibration.",
            }
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Open Agronomy Benchmark result",
        "",
        f"- Status: `{report['run_status']}`",
        f"- Suite: `{report['benchmark_id']}` ({report['suite_rows']} frozen cases)",
        f"- Models: {report['counts']['models']}",
        f"- Responses: {report['counts']['responses']}",
        f"- Paired responses: {report['counts']['paired_responses']}",
        f"- Legacy single-judge triage judgments: {report['counts']['automated_triage_judgments']}",
        f"- Role-scoped judge assessments: {report['counts']['role_scoped_judge_assessments']}",
        f"- Public benchmark score claim eligible: **{'yes' if report['public_benchmark_score_claim_eligible'] else 'no'}**",
        "- Grower advisory claim eligible: **no**",
        "- Composite score: **not defined**",
        "",
        "## Lane results",
        "",
        "| Model | Arm | Lane | Rows | Lane score mean | Automated triage mean | Pass / revise / fail | Mean seconds |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["lane_results"]:
        proxy = "—" if row["valid_proxy_mean"] is None else f"{row['valid_proxy_mean']:.2f}"
        triage = "—" if row["automated_triage_mean"] is None else f"{row['automated_triage_mean']:.2f}"
        lines.append(
            f"| {row['model_id']} | {row['system_variant']} | {row['benchmark_lane']} | {row['response_count']} | "
            f"{proxy} | {triage} | {row['automated_triage_pass']} / {row['automated_triage_revise']} / "
            f"{row['automated_triage_fail']} | {row['latency_mean_seconds']:.3f} |"
        )
    lines.extend([
        "",
        (
            "The lane score is objective multiple-choice accuracy. It is not evidence of Canadian advisory safety or grower usefulness."
            if report["evaluation_partition"] == "public"
            else "Results are intentionally separated by lane. Automated semantic values are uncalibrated triage; valid lexical proxy values are regression diagnostics. Neither is grower-facing accuracy."
        ),
        "",
    ])
    if report.get("system_interface_results"):
        lines.extend([
            "## System-interface diagnostics",
            "",
            "These are deterministic interface-contract checks, not agronomic answer accuracy. The generation "
            "harness exercises the offline core agent; online service adapters are reported as unexecuted requirements, "
            "not counted as missing local guards.",
            "",
            "| Model | Exact input trace | Field context | Language | Route trace | Tool trace | Admission trace | Weak retrieval admitted | Evidence lineage | Output contract |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for row in report["system_interface_results"]:
            tool_rate = row["required_tool_trace"]["complete_local_guard_case_rate"]
            field_rate = row["field_context_binding"]["rate"]
            language_rate = row["non_english_language_preservation"]["rate"]
            output_contract_rate = row["output_contract_pass_rate"]
            lines.append(
                f"| {row['model_id']} | {row['generation_input_lineage_rate']:.1%} | "
                f"{'—' if field_rate is None else f'{field_rate:.1%}'} | "
                f"{'—' if language_rate is None else f'{language_rate:.1%}'} | {row['route_trace_rate']:.1%} | "
                f"{'—' if tool_rate is None else f'{tool_rate:.1%}'} | "
                f"{row['context_admission_trace_rate']:.1%} | "
                f"{'—' if row['weak_retrieval_admitted'] is None else row['weak_retrieval_admitted']} | "
                f"{row['evidence_lineage_rate']:.1%} | "
                f"{'n/a' if output_contract_rate is None else f'{output_contract_rate:.1%}'} |"
            )
        lines.append("")
    return "\n".join(lines)


def write_report(database: Path, manifest: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    report = build_report(database, manifest)
    (output_dir / "benchmark_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output_dir / "benchmark_report.md").write_text(render_markdown(report), encoding="utf-8")
    return report
