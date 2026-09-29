"""Fail-closed release reports, paired production gates and public aggregates.

Trials remain dependent observations. Semantic labels are source-bound supplied
reviews; no label or engineering score establishes external field validity.
"""

from __future__ import annotations

import math
import random
import re
import statistics
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

from agronomy_agent.release_evaluation import COMPONENTS, REPORT_SCHEMA, digest
from agronomy_agent.server.trace_timer import PHASE5_STAGES

REVIEW_FIELDS = (
    "required_complete",
    "optional_usefulness",
    "source_supported",
    "material_error",
    "unnecessary_abstention",
)
IDENTITY_FIELDS = (
    "observation_id",
    "suite_id",
    "case_id",
    "case_sha256",
    "scenario_family",
    "lane",
    "arm_id",
    "trial_id",
    "backend",
)
PRODUCTION_ARM = "production_full"
LIMITATIONS = [
    "Exposed development suites; no independent target-user or field-outcome validation.",
    "Trials and dependent field bundles are not independent scenarios.",
    "Semantic judgments remain pending without source-bound human review.",
    "GPU measurements do not establish Mac latency or memory budgets.",
    "Cluster bootstrap intervals describe the observed family cohort, not a population validation claim.",
]


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def measurement(values: Sequence[Any]) -> dict[str, Any]:
    observed = [float(value) for value in values if _finite(value)]
    return {
        "denominator_n": len(values),
        "eligible_n": len(observed),
        "missing_n": len(values) - len(observed),
        "mean": statistics.mean(observed) if observed else None,
    }


def binary_measurement(values: Sequence[Any]) -> dict[str, Any]:
    return measurement(
        [int(value) if isinstance(value, bool) else None for value in values]
    )


def distribution(values: Sequence[Any]) -> dict[str, Any]:
    observed = sorted(float(value) for value in values if _finite(value) and value >= 0)
    return {
        "denominator_n": len(values),
        "samples": len(observed),
        "missing_n": len(values) - len(observed),
        "p50": statistics.median(observed) if observed else None,
        "p95": (
            observed[max(0, math.ceil(0.95 * len(observed)) - 1)] if observed else None
        ),
        "maximum": max(observed) if observed else None,
    }


def _nonfinite_paths(value: Any, path: str = "") -> list[str]:
    if isinstance(value, float) and not math.isfinite(value):
        return [path]
    if isinstance(value, Mapping):
        return [
            item
            for key, child in value.items()
            for item in _nonfinite_paths(child, f"{path}.{key}")
        ]
    if isinstance(value, (list, tuple)):
        return [
            item
            for index, child in enumerate(value)
            for item in _nonfinite_paths(child, f"{path}[{index}]")
        ]
    return []


def _clean_numbers(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {key: _clean_numbers(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_numbers(child) for child in value]
    return value


def bind_reviews(
    rows: Sequence[Mapping[str, Any]], reviews: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_id = {row["observation_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("review observations must be unique")
    bound: dict[str, dict[str, Any]] = {}
    for review in reviews:
        key = review.get("observation_id")
        if key not in by_id or key in bound:
            raise ValueError("review refers to an unknown or duplicate observation")
        row = by_id[key]
        if (
            row.get("status") != "completed"
            or review.get("answer_sha256") != row.get("answer_sha256")
            or review.get("case_sha256") != row.get("case_sha256")
        ):
            raise ValueError(
                "review answer/case binding does not match a completed observation"
            )
        if (
            not review.get("reviewer_id")
            or review.get("reviewer_type")
            not in {"human_agronomist", "human_domain_reviewer", "automated_triage"}
            or not re.fullmatch(
                r"[a-fA-F0-9]{64}", str(review.get("rubric_sha256") or "")
            )
        ):
            raise ValueError("review identity, type and rubric hash are required")
        for name in REVIEW_FIELDS:
            value = review.get(name)
            if name == "optional_usefulness":
                if value is not None and (not _finite(value) or not 0 <= value <= 1):
                    raise ValueError("optional usefulness must be null or in [0,1]")
            elif value is not None and not isinstance(value, bool):
                raise ValueError(f"{name} must be bool or null")
        stage_labels = review.get("stage_labels", {})
        if not isinstance(stage_labels, Mapping) or set(stage_labels) - {
            "draft",
            "post_verification",
            "final",
        }:
            raise ValueError("stage_labels must map known answer stages")
        turns = row.get("turns") or []
        stages = turns[-1].get("answer_stages", {}) if turns else {}
        hashes = row.get("answer_stage_hashes") or {
            name: item.get("sha256")
            for name, item in stages.items()
            if isinstance(item, Mapping)
        }
        for stage, label in stage_labels.items():
            if (
                not isinstance(label, Mapping)
                or not hashes.get(stage)
                or label.get("sha256") != hashes[stage]
            ):
                raise ValueError(
                    "stage label hash does not match the retained answer stage"
                )
            for name in REVIEW_FIELDS:
                value = label.get(name)
                if name == "optional_usefulness":
                    if value is not None and (
                        not _finite(value) or not 0 <= value <= 1
                    ):
                        raise ValueError(
                            "stage optional usefulness must be null or in [0,1]"
                        )
                elif value is not None and not isinstance(value, bool):
                    raise ValueError(f"stage {name} must be bool or null")
            if stage == "final" and any(
                label.get(name) != review.get(name)
                for name in REVIEW_FIELDS
                if name in label and name in review
            ):
                raise ValueError("final stage labels conflict with final answer review")
        bound[key] = {
            **review,
            "review_record_sha256": digest(review),
            "qualification": "supplied_review_record_not_independently_authenticated",
        }
    return bound


def _numeric_required(case: Mapping[str, Any]) -> bool:
    return (
        case.get("scoring_method") == "numeric_tolerance"
        or (case.get("scoring") or {}).get("method") == "numeric_tolerance"
    )


def _numeric_value(row: Mapping[str, Any]) -> float | None:
    if not row.get("numeric_required"):
        return None
    if row.get("status") == "failed":
        return 0.0
    score = row.get("independent_score") or {}
    value = score.get("score")
    return (
        value / 100
        if score.get("rubric") == "numeric_tolerance"
        and _finite(value)
        and 0 <= value <= 100
        else None
    )


def _semantic_summary(
    rows: Sequence[Mapping[str, Any]], labels: Mapping[str, Any]
) -> dict[str, Any]:
    required = [row for row in rows if row.get("review_required")]
    reviews = [labels.get(row["observation_id"], {}) for row in required]
    complete_n = sum(
        review.get("required_complete") is not None
        and review.get("material_error") is not None
        for review in reviews
    )
    return {
        "status": (
            "not_applicable"
            if not required
            else (
                "review_pending"
                if complete_n < len(required)
                else "supplied_review_complete_not_external_validation"
            )
        ),
        "required_n": len(required),
        "paired_core_labels_n": complete_n,
        "unknown_n": len(required) - complete_n,
        "coverage": complete_n / len(required) if required else 1.0,
        "metrics": {
            name: (
                measurement([review.get(name) for review in reviews])
                if name == "optional_usefulness"
                else binary_measurement([review.get(name) for review in reviews])
            )
            for name in REVIEW_FIELDS
        },
    }


def _outcome_summary(
    rows: Sequence[Mapping[str, Any]], labels: Mapping[str, Any]
) -> dict[str, Any]:
    numeric = [row for row in rows if row.get("numeric_required")]
    return {
        "planned_n": len(rows),
        "completed_n": sum(row.get("status") == "completed" for row in rows),
        "failed_n": sum(row.get("status") == "failed" for row in rows),
        "missing_n": sum(row.get("status") == "missing" for row in rows),
        "numeric_accuracy": measurement([_numeric_value(row) for row in numeric]),
        "semantic": _semantic_summary(rows, labels),
    }


def _intervention_summary(
    rows: Sequence[Mapping[str, Any]], labels: Mapping[str, Any]
) -> dict[str, Any]:
    pairs = []
    for row in rows:
        review = labels.get(row["observation_id"], {})
        stages = review.get("stage_labels") or {}
        draft, final = stages.get("draft", {}), {**review, **stages.get("final", {})}
        pairs.append((draft, final))
    completion = [
        (
            int(final["required_complete"]) - int(draft["required_complete"])
            if isinstance(draft.get("required_complete"), bool)
            and isinstance(final.get("required_complete"), bool)
            else None
        )
        for draft, final in pairs
    ]
    usefulness = [
        (
            final["optional_usefulness"] - draft["optional_usefulness"]
            if _finite(draft.get("optional_usefulness"))
            and _finite(final.get("optional_usefulness"))
            else None
        )
        for draft, final in pairs
    ]
    error_pairs = [
        (draft["material_error"], final["material_error"])
        for draft, final in pairs
        if isinstance(draft.get("material_error"), bool)
        and isinstance(final.get("material_error"), bool)
    ]
    return {
        "status": (
            "supplied_stage_review_pairs"
            if error_pairs or any(value is not None for value in completion)
            else "review_pending_not_assessed"
        ),
        "denominator_n": len(rows),
        "completion_delta": measurement(completion),
        "optional_usefulness_delta": measurement(usefulness),
        "material_error": {
            "eligible_pair_n": len(error_pairs),
            "unknown_pair_n": len(rows) - len(error_pairs),
            "introduced_n": (
                sum(not draft and final for draft, final in error_pairs)
                if error_pairs
                else None
            ),
            "removed_n": (
                sum(draft and not final for draft, final in error_pairs)
                if error_pairs
                else None
            ),
        },
    }


def _verified_generation(turn: Mapping[str, Any], revision: str | None) -> bool:
    execution = turn.get("model_execution") or {}
    identity = turn.get("model_identity") or execution.get("identity") or {}
    observed = turn.get("model_revision_observation") or {}
    tokens = (turn.get("generation_stats") or {}).get("generation_tokens")
    return bool(
        revision
        and execution.get("model_generation_eligible") is True
        and execution.get("synthetic") is False
        and identity.get("status")
        in {"verified_direct_loader", "verified_runtime_receipt"}
        and observed.get("verified") is True
        and observed.get("configured") == revision
        and observed.get("resolved") == revision
        and _finite(tokens)
        and tokens > 0
    )


def summarize(
    plan: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    components: Sequence[Mapping[str, Any]],
    *,
    environment: Mapping[str, Any],
    reviews: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    expected = {row["observation_id"]: row for row in plan["matrix"]}
    actual = {row["observation_id"]: row for row in rows}
    if (
        len(expected) != len(plan["matrix"])
        or len(actual) != len(rows)
        or set(actual) - set(expected)
    ):
        raise ValueError("observation ledger contains duplicate or unplanned cells")
    cases = {(case["suite_id"], case["case_id"]): case for case in plan["cases"]}
    missing = sorted(set(expected) - set(actual))
    identity_failures = [
        key
        for key, row in actual.items()
        if any(row.get(name) != expected[key].get(name) for name in IDENTITY_FIELDS)
    ]
    invalid_data = _nonfinite_paths(
        {"rows": rows, "components": components, "environment": environment}
    )
    labels = bind_reviews(rows, reviews)
    human_labels = {
        key: review
        for key, review in labels.items()
        if review["reviewer_type"] != "automated_triage"
    }
    observations = []
    numeric_failures = []
    planned = []
    for key, cell in expected.items():
        case = cases[(cell["suite_id"], cell["case_id"])]
        question_hash = digest(
            case.get("turns") if "turns" in case else case.get("question")
        )
        identity = {
            **{name: cell.get(name) for name in IDENTITY_FIELDS},
            "question_sha256": question_hash,
            "numeric_required": _numeric_required(case),
            "review_required": case.get("review_required") is True,
        }
        planned.append(identity)
        row = actual.get(key, {})
        observation = {
            **identity,
            "status": row.get("status", "missing"),
            "answer_sha256": row.get("answer_sha256"),
            "independent_score": _clean_numbers(row.get("independent_score")),
        }
        turns = row.get("turns") or []
        stages = turns[-1].get("answer_stages", {}) if turns else {}
        observation["answer_stage_hashes"] = {
            name: value.get("sha256")
            for name, value in stages.items()
            if name in {"draft", "post_verification", "final"}
            and isinstance(value, Mapping)
        }
        if identity["numeric_required"]:
            score = row.get("independent_score") or {}
            valid = (
                score.get("rubric") == "numeric_tolerance"
                and _finite(score.get("score"))
                and 0 <= score["score"] <= 100
            )
            observation["numeric_score_status"] = (
                "observed" if valid else "missing_or_invalid"
            )
            if not valid:
                numeric_failures.append(key)
        observations.append(observation)
    failed_checks = [
        {"observation_id": row["observation_id"], **_clean_numbers(check)}
        for row in rows
        for check in row.get("checks") or []
        if check.get("passed") is not True
    ]
    failed = [row["observation_id"] for row in rows if row.get("status") != "completed"]
    component_ids = [row["component"] for row in components]
    component_failures = [
        row["component"]
        for row in components
        if row.get("status") != "pass"
        or any(check.get("passed") is not True for check in row.get("checks") or [])
    ]
    if set(component_ids) != set(plan["required_components"]) or len(
        component_ids
    ) != len(set(component_ids)):
        component_failures.append("required_component_coverage")
    production = [row for row in observations if row["arm_id"] == PRODUCTION_ARM]
    semantic = _semantic_summary(production, human_labels)
    coverage_required = plan["domain_policy"]["required_review_coverage"]
    model_rows = [
        row
        for row in rows
        if row.get("arm_id") == PRODUCTION_ARM and row.get("backend") == "mlx"
    ]
    model_turns = [turn for row in model_rows for turn in row.get("turns") or []]
    verified_n = sum(
        _verified_generation(turn, plan["model"].get("revision"))
        for turn in model_turns
    )
    model_evidence_required = plan["profile"] in {"baseline", "release"}
    model_evidence_missing = model_evidence_required and not verified_n
    performance = {
        "boundary": "production_turn_including_load_editor_and_persistence_separate_from_child_startup",
        "elapsed_ms": distribution([turn.get("elapsed_ms") for turn in model_turns]),
        "peak_memory_bytes": distribution(
            [turn.get("peak_memory_bytes") for turn in model_turns]
        ),
        "generation_tokens": measurement(
            [
                (turn.get("generation_stats") or {}).get("generation_tokens")
                for turn in model_turns
            ]
        ),
        "first_token_ms": distribution(
            [
                (turn.get("generation_stats") or {}).get("time_to_first_token_ms")
                for turn in model_turns
            ]
        ),
        "editor_generation_tokens": measurement(
            [
                (turn.get("verification_generation_stats") or {}).get(
                    "generation_tokens"
                )
                for turn in model_turns
            ]
        ),
        "environment_sha256": environment.get("performance_environment_sha256"),
        "warmth_policy": "fresh_scenario_process_multi_turn_reuse_within_scenario",
    }
    all_turns = [turn for row in rows for turn in row.get("turns") or []]
    origins = Counter(
        str((turn.get("model_execution") or {}).get("disposition") or "unknown")
        for turn in all_turns
    )
    stage_values: dict[str, list[Any]] = defaultdict(list)
    stage_statuses: dict[str, Counter] = defaultdict(Counter)
    for turn in all_turns:
        for span in turn.get("profiler_spans") or []:
            stage_values[span["stage"]].append(span.get("duration_ms"))
            stage_statuses[span["stage"]][str(span.get("status") or "unknown")] += 1
    sources = {
        "turns_n": len(all_turns),
        "document_receipts_n": sum(
            len(turn.get("source_receipts") or []) for turn in all_turns
        ),
        "graph_receipts_n": sum(
            len(turn.get("graph_receipts") or []) for turn in all_turns
        ),
        "tool_results_n": sum(
            len(turn.get("tool_results") or []) for turn in all_turns
        ),
    }
    lanes: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_case: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        lanes[row["lane"]].append(row)
        families[row["scenario_family"]].append(row)
        by_case[(row["suite_id"], row["case_id"], row["arm_id"])].append(row)
    repeatability = [
        {
            "suite_id": key[0],
            "case_id": key[1],
            "arm_id": key[2],
            "trials": len(repeats),
            "exact_final_repeatable": (
                len({row.get("answer_sha256") for row in repeats}) == 1
                if len(repeats) > 1
                and all(row["status"] == "completed" for row in repeats)
                else None
            ),
        }
        for key, repeats in sorted(by_case.items())
    ]
    numeric = [row for row in production if row["numeric_required"]]
    blocked = bool(
        missing
        or failed
        or failed_checks
        or component_failures
        or identity_failures
        or invalid_data
        or numeric_failures
        or model_evidence_missing
        or semantic["coverage"] < coverage_required
    )
    domain_status = (
        "required_review_missing"
        if semantic["coverage"] < coverage_required
        else semantic["status"]
    )
    return {
        "schema_version": REPORT_SCHEMA,
        "suite_id": plan["suite_id"],
        "run_id": plan["run_id"],
        "profile": plan["profile"],
        "claim_eligible": False,
        "status": "blocked" if blocked else "engineering_pass",
        "domain_status": domain_status,
        "domain_review_coverage": semantic["coverage"],
        "domain_review_required_coverage": coverage_required,
        "reviewed_observations": len(labels),
        "triage_observations": sum(
            review["reviewer_type"] == "automated_triage" for review in labels.values()
        ),
        "source": {key: plan["source"][key] for key in ("commit", "source_sha256")},
        "registry_sha256": plan["registry_sha256"],
        "cohort_sha256": plan["cohort_sha256"],
        "scorer_version": plan["scorer_version"],
        "model": plan["model"],
        "sampling": plan["sampling"],
        "environment": _clean_numbers(environment),
        "counts": {
            **plan["counts"],
            "observed": len(rows),
            "failed": len(failed),
            "missing": len(missing),
            "failed_checks": len(failed_checks),
            "review_required": semantic["required_n"],
            "numeric_required": len(numeric),
            "numeric_scores_missing": len(numeric_failures),
        },
        "failures": {
            "missing_observations": missing,
            "failed_observations": failed,
            "failed_checks": failed_checks,
            "components": component_failures,
            "identity_mismatches": identity_failures,
            "invalid_measurements": invalid_data,
            "numeric_scores_missing": numeric_failures,
            "model_execution_missing": model_evidence_missing,
        },
        "metrics": {
            "numeric_accuracy": measurement([_numeric_value(row) for row in numeric]),
            "domain": semantic["metrics"],
            "intervention_benefit": _intervention_summary(production, human_labels),
            "performance": performance,
            "generation_origins": dict(sorted(origins.items())),
            "model_execution": {
                "required": model_evidence_required,
                "planned_mlx_cells": sum(row["backend"] == "mlx" for row in production),
                "observed_mlx_turns": len(model_turns),
                "verified_generated_turns": verified_n,
                "status": (
                    "observed"
                    if verified_n
                    else (
                        "missing"
                        if model_evidence_required
                        else "not_required_mock_profile"
                    )
                ),
            },
            "source_coverage": sources,
            "stage_timings": {
                stage: {**distribution(values), "states": dict(stage_statuses[stage])}
                for stage, values in sorted(stage_values.items())
            },
            "cost": {
                "currency_cost": None,
                "status": "not_measured",
                "draft_tokens": measurement(
                    [
                        (turn.get("generation_stats") or {}).get("generation_tokens")
                        for turn in all_turns
                    ]
                ),
                "editor_tokens": measurement(
                    [
                        (turn.get("verification_generation_stats") or {}).get(
                            "generation_tokens"
                        )
                        for turn in all_turns
                    ]
                ),
            },
        },
        "lane_summaries": {
            key: _outcome_summary(values, human_labels)
            for key, values in sorted(lanes.items())
        },
        "family_summaries": {
            key: _outcome_summary(values, human_labels)
            for key, values in sorted(families.items())
        },
        "components": _clean_numbers(components),
        "repeatability": repeatability,
        "semantic_reviews": list(labels.values()),
        "planned_observations": planned,
        "observations": observations,
        "limitations": list(LIMITATIONS),
    }


def _cluster_interval(
    deltas: Sequence[tuple[str, float]], *, seed: int = 42, samples: int = 1000
) -> dict[str, Any]:
    families: dict[str, list[float]] = defaultdict(list)
    for family, value in deltas:
        families[family].append(value)
    means = [statistics.mean(values) for _, values in sorted(families.items())]
    if not means:
        return {
            "status": "pending_no_pairs",
            "clusters_n": 0,
            "paired_n": 0,
            "mean_delta": None,
            "lower_95": None,
            "upper_95": None,
        }
    rng = random.Random(seed)
    boot = sorted(
        statistics.mean(rng.choices(means, k=len(means))) for _ in range(samples)
    )
    return {
        "status": (
            "observed_cohort_cluster_interval"
            if len(means) >= 2
            else "insufficient_independent_clusters"
        ),
        "clusters_n": len(means),
        "paired_n": len(deltas),
        "mean_delta": statistics.mean(means),
        "lower_95": boot[int(samples * 0.025)],
        "upper_95": boot[min(samples - 1, int(samples * 0.975))],
        "seed": seed,
        "bootstrap_samples": samples,
        "weighting": "equal_scenario_family_after_within_family_mean",
        "boundary": "dependent trials remain within scenario-family clusters",
    }


def _production_table(
    report: Mapping[str, Any], key: str
) -> dict[str, Mapping[str, Any]]:
    return {
        row["observation_id"]: row
        for row in report.get(key) or []
        if row.get("arm_id") == PRODUCTION_ARM
    }


def _arm_benefits(report: Mapping[str, Any]) -> dict[str, Any]:
    by_arm: dict[str, dict[tuple[str, str, str], Mapping[str, Any]]] = defaultdict(dict)
    for row in report.get("observations") or []:
        by_arm[row["arm_id"]][(row["suite_id"], row["case_id"], row["trial_id"])] = row
    full = by_arm.get(PRODUCTION_ARM, {})
    output = {}
    for arm in ("raw_model", "kernel_only"):
        deltas = []
        for key in sorted(set(full) & set(by_arm.get(arm, {}))):
            left, right = by_arm[arm][key], full[key]
            a, b = _numeric_value(left), _numeric_value(right)
            if (
                a is not None
                and b is not None
                and left.get("question_sha256") == right.get("question_sha256")
            ):
                deltas.append((right["scenario_family"], b - a))
        output[arm] = {
            "status": (
                "diagnostic_only" if deltas else "pending_no_matched_numeric_arms"
            ),
            "numeric_benefit": _cluster_interval(deltas),
        }
    return output


def compare(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Gate paired production observations; optional semantic unknowns stay pending."""
    checks: list[dict[str, Any]] = []

    def check(
        name: str, passed: bool | None, detail: Any, *, required: bool = True
    ) -> None:
        checks.append(
            {
                "id": name,
                "passed": passed,
                "required": required,
                "detail": _clean_numbers(detail),
            }
        )

    for name in (
        "suite_id",
        "registry_sha256",
        "cohort_sha256",
        "scorer_version",
        "model",
        "sampling",
    ):
        check(
            f"compatible_{name}",
            reference.get(name) == candidate.get(name),
            {"reference": reference.get(name), "candidate": candidate.get(name)},
        )
    for label, report in (("reference", reference), ("candidate", candidate)):
        check(
            f"complete_{label}",
            report.get("status") == "engineering_pass"
            and report.get("profile") in {"baseline", "release"},
            report.get("status"),
        )
        check(
            f"finite_{label}_data",
            not _nonfinite_paths(report),
            _nonfinite_paths(report),
        )
        check(
            f"model_evidence_{label}",
            (
                report.get("metrics", {})
                .get("model_execution", {})
                .get("verified_generated_turns")
                or 0
            )
            > 0,
            report.get("metrics", {}).get("model_execution"),
        )
    rplan, cplan = _production_table(
        reference, "planned_observations"
    ), _production_table(candidate, "planned_observations")
    rrows, crows = _production_table(reference, "observations"), _production_table(
        candidate, "observations"
    )
    planned_pairs = bool(rplan) and set(rplan) == set(cplan) == set(rrows) == set(crows)
    check(
        "planned_production_identity_coverage",
        planned_pairs,
        {
            "reference_planned_n": len(rplan),
            "candidate_planned_n": len(cplan),
            "reference_observed_n": len(rrows),
            "candidate_observed_n": len(crows),
        },
    )
    check(
        "planned_production_completed",
        planned_pairs
        and all(
            row.get("status") == "completed"
            for row in [*rrows.values(), *crows.values()]
        ),
        {
            "reference_completed_n": sum(
                row.get("status") == "completed" for row in rrows.values()
            ),
            "candidate_completed_n": sum(
                row.get("status") == "completed" for row in crows.values()
            ),
        },
    )
    identity_names = (
        *IDENTITY_FIELDS,
        "question_sha256",
        "numeric_required",
        "review_required",
    )
    mismatches = [
        key
        for key in set(rplan) & set(cplan) & set(rrows) & set(crows)
        if any(
            rplan[key].get(name) != cplan[key].get(name)
            or rrows[key].get(name) != rplan[key].get(name)
            or crows[key].get(name) != cplan[key].get(name)
            for name in identity_names
        )
    ]
    check(
        "paired_question_and_case_contract",
        planned_pairs and not mismatches,
        mismatches,
    )
    a_failed, b_failed = reference.get("counts", {}).get(
        "failed_checks"
    ), candidate.get("counts", {}).get("failed_checks")
    check(
        "no_new_failed_checks",
        _finite(a_failed)
        and _finite(b_failed)
        and b_failed - a_failed <= policy["maximum_new_failed_checks"],
        {"reference": a_failed, "candidate": b_failed},
    )
    numeric_ids = [key for key, row in rplan.items() if row.get("numeric_required")]
    numeric_pairs = []
    numeric_missing = []
    for key in numeric_ids:
        left, right = rrows.get(key, {}), crows.get(key, {})
        a, b = _numeric_value(left), _numeric_value(right)
        if (
            a is None
            or b is None
            or left.get("numeric_score_status") != "observed"
            or right.get("numeric_score_status") != "observed"
        ):
            numeric_missing.append(key)
        else:
            numeric_pairs.append((key, right["scenario_family"], b - a))
    check(
        "paired_numeric_score_coverage",
        not numeric_missing and len(numeric_pairs) == len(numeric_ids),
        {
            "planned_n": len(numeric_ids),
            "paired_n": len(numeric_pairs),
            "missing": numeric_missing,
        },
    )
    by_case: dict[tuple[str, str], list[float]] = defaultdict(list)
    for key, _, delta in numeric_pairs:
        row = crows[key]
        by_case[(row["suite_id"], row["case_id"])].append(delta)
    regressions = [
        {"suite_id": key[0], "case_id": key[1], "delta": statistics.mean(values)}
        for key, values in sorted(by_case.items())
        if min(values) < -policy["maximum_numeric_accuracy_regression"]
    ]
    check(
        "no_paired_numeric_case_regression",
        not numeric_missing and not regressions,
        regressions,
    )
    check(
        "numeric_accuracy",
        (
            statistics.mean(delta for _, _, delta in numeric_pairs)
            >= -policy["maximum_numeric_accuracy_regression"]
            if numeric_pairs
            else None
        ),
        {"paired_n": len(numeric_pairs)},
        required=bool(numeric_ids),
    )

    def retrieval_mean(report: Mapping[str, Any]) -> Any:
        item = next(
            (
                row
                for row in report.get("components") or []
                if row["component"] == "retrieval"
            ),
            {},
        )
        return (item.get("metrics") or {}).get("positive_recall_at_7")

    before, after = retrieval_mean(reference), retrieval_mean(candidate)
    check(
        "positive_retrieval_recall_at_7",
        _finite(before)
        and _finite(after)
        and 0 <= before <= 1
        and 0 <= after <= 1
        and after >= before - policy["maximum_positive_recall_at_7_regression"],
        {"reference": before, "candidate": after},
    )
    a, b = reference.get("metrics", {}).get("performance", {}), candidate.get(
        "metrics", {}
    ).get("performance", {})
    compatible_environment = (
        a.get("environment_sha256") == b.get("environment_sha256")
        and a.get("environment_sha256") is not None
    )
    check(
        "performance_environment",
        compatible_environment,
        {
            "reference": a.get("environment_sha256"),
            "candidate": b.get("environment_sha256"),
        },
    )
    for metric, limit, statistic in (
        ("elapsed_ms", "maximum_latency_p95_ratio", "p95"),
        ("peak_memory_bytes", "maximum_peak_memory_ratio", "maximum"),
    ):
        before, after = a.get(metric, {}), b.get(metric, {})
        eligible = (
            compatible_environment
            and _finite(before.get("samples"))
            and _finite(after.get("samples"))
            and min(before["samples"], after["samples"])
            >= policy["minimum_performance_samples"]
            and _finite(before.get(statistic))
            and before[statistic] > 0
            and _finite(after.get(statistic))
            and after[statistic] >= 0
        )
        check(
            f"performance_{metric}",
            eligible and after[statistic] <= before[statistic] * policy[limit],
            {"reference": before, "candidate": after, "maximum_ratio": policy[limit]},
        )
    try:
        rlabels = {
            key: value
            for key, value in bind_reviews(
                list(rrows.values()),
                [
                    row
                    for row in reference.get("semantic_reviews") or []
                    if row.get("observation_id") in rrows
                ],
            ).items()
            if value["reviewer_type"] != "automated_triage"
        }
        clabels = {
            key: value
            for key, value in bind_reviews(
                list(crows.values()),
                [
                    row
                    for row in candidate.get("semantic_reviews") or []
                    if row.get("observation_id") in crows
                ],
            ).items()
            if value["reviewer_type"] != "automated_triage"
        }
        check("semantic_review_binding", True, None)
    except ValueError as exc:
        rlabels, clabels = {}, {}
        check("semantic_review_binding", False, str(exc))
    review_ids = [key for key, row in rplan.items() if row.get("review_required")]
    pair_ids = sorted(set(review_ids) & set(rlabels) & set(clabels))
    rubric_mismatch = [
        key
        for key in pair_ids
        if rlabels[key]["rubric_sha256"] != clabels[key]["rubric_sha256"]
    ]
    check("paired_review_rubric", not rubric_mismatch, rubric_mismatch)
    required_r, required_c = reference.get(
        "domain_review_required_coverage"
    ), candidate.get("domain_review_required_coverage")
    policy_valid = (
        _finite(required_r)
        and _finite(required_c)
        and required_r == required_c
        and 0 <= required_c <= 1
    )
    check(
        "compatible_required_review_coverage",
        policy_valid,
        {"reference": required_r, "candidate": required_c},
    )
    core_pairs = [
        key
        for key in pair_ids
        if key not in rubric_mismatch
        and all(
            isinstance(labels[key].get(name), bool)
            for labels in (rlabels, clabels)
            for name in ("required_complete", "material_error")
        )
    ]
    paired_coverage = len(core_pairs) / len(review_ids) if review_ids else 1.0
    semantic_required = policy_valid and required_c > 0
    check(
        "paired_required_review_coverage",
        policy_valid and paired_coverage >= required_c,
        {
            "planned_n": len(review_ids),
            "paired_n": len(core_pairs),
            "coverage": paired_coverage,
        },
    )
    introduced = sum(
        not rlabels[key]["material_error"] and clabels[key]["material_error"]
        for key in core_pairs
    )
    removed = sum(
        rlabels[key]["material_error"] and not clabels[key]["material_error"]
        for key in core_pairs
    )
    deltas = [
        (
            rrows[key]["scenario_family"],
            int(clabels[key]["required_complete"])
            - int(rlabels[key]["required_complete"]),
        )
        for key in core_pairs
    ]
    check(
        "introduced_material_errors",
        (
            introduced <= policy["maximum_introduced_material_errors"]
            if core_pairs
            else None
        ),
        {
            "paired_n": len(core_pairs),
            "introduced": introduced if core_pairs else None,
            "removed": removed if core_pairs else None,
            "status": "assessed" if core_pairs else "review_pending_not_assessed",
        },
        required=semantic_required or bool(core_pairs),
    )
    check(
        "required_completion",
        (
            statistics.mean(delta for _, delta in deltas)
            >= -policy["maximum_required_completion_regression"]
            if deltas
            else None
        ),
        {
            "paired_n": len(deltas),
            "status": "assessed" if deltas else "review_pending_not_assessed",
        },
        required=semantic_required or bool(deltas),
    )
    return {
        "schema_version": "open_agronomy_agent.release_evaluation_comparison.v1",
        "status": (
            "pass"
            if all(row["passed"] is True for row in checks if row["required"])
            else "blocked"
        ),
        "semantic_status": (
            "review_pending_not_assessed"
            if not core_pairs
            else (
                "partially_paired_review"
                if paired_coverage < 1
                else "paired_supplied_review_not_external_validation"
            )
        ),
        "reference_run_id": reference["run_id"],
        "candidate_run_id": candidate["run_id"],
        "claim_eligible": False,
        "release_arm": PRODUCTION_ARM,
        "checks": checks,
        "paired_numeric_uncertainty": _cluster_interval(
            [(family, delta) for _, family, delta in numeric_pairs]
        ),
        "paired_completion_uncertainty": _cluster_interval(deltas),
        "arm_benefit_diagnostics": {
            "reference": _arm_benefits(reference),
            "candidate": _arm_benefits(candidate),
        },
    }


_AGGREGATE_KEYS = {
    "denominator_n",
    "eligible_n",
    "missing_n",
    "mean",
    "samples",
    "p50",
    "p95",
    "maximum",
    "required_n",
    "paired_core_labels_n",
    "unknown_n",
    "coverage",
    "planned_n",
    "completed_n",
    "failed_n",
}


def _aggregate(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: child if _finite(child) else None
        for key, child in value.items()
        if key in _AGGREGATE_KEYS
    }


def _public_outcome(value: Mapping[str, Any]) -> dict[str, Any]:
    semantic = value.get("semantic") or {}
    return {
        **_aggregate(value),
        "numeric_accuracy": _aggregate(value.get("numeric_accuracy") or {}),
        "semantic": {
            **_aggregate(semantic),
            "status": (
                semantic.get("status")
                if semantic.get("status")
                in {
                    "not_applicable",
                    "review_pending",
                    "supplied_review_complete_not_external_validation",
                }
                else "unknown"
            ),
            "metrics": {
                name: _aggregate((semantic.get("metrics") or {}).get(name) or {})
                for name in REVIEW_FIELDS
            },
        },
    }


def _hash(value: Any) -> str | None:
    return str(value) if re.fullmatch(r"[a-fA-F0-9]{40,64}", str(value or "")) else None


def _identifier(value: Any) -> str | None:
    return (
        str(value) if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", str(value or "")) else None
    )


def public_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Whitelist aggregate values; free-form nested fields never cross this seam."""
    metrics = report.get("metrics") or {}
    performance = metrics.get("performance") or {}
    model = report.get("model") or {}
    model_id = str(model.get("id") or "")
    model_id = (
        model_id if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", model_id) else None
    )
    public_metrics = {
        "numeric_accuracy": _aggregate(metrics.get("numeric_accuracy") or {}),
        "domain": {
            name: _aggregate((metrics.get("domain") or {}).get(name) or {})
            for name in REVIEW_FIELDS
        },
        "performance": {
            name: _aggregate(performance.get(name) or {})
            for name in (
                "elapsed_ms",
                "peak_memory_bytes",
                "generation_tokens",
                "first_token_ms",
                "editor_generation_tokens",
            )
        },
        "generation_origins": {
            name: count
            for name, count in (metrics.get("generation_origins") or {}).items()
            if name
            in {
                "model_generated",
                "deterministic_bypass",
                "backend_fallback_or_unavailable",
                "unknown",
            }
            and _finite(count)
        },
        "source_coverage": {
            name: value
            for name, value in (metrics.get("source_coverage") or {}).items()
            if name
            in {"turns_n", "document_receipts_n", "graph_receipts_n", "tool_results_n"}
            and _finite(value)
        },
        "model_execution": {
            name: value
            for name, value in (metrics.get("model_execution") or {}).items()
            if name
            in {"planned_mlx_cells", "observed_mlx_turns", "verified_generated_turns"}
            and _finite(value)
        },
        "stage_timings": {
            name: _aggregate(value)
            for name, value in (metrics.get("stage_timings") or {}).items()
            if name in PHASE5_STAGES
        },
        "cost": {
            "currency_cost": None,
            "status": "not_measured",
            "draft_tokens": _aggregate(
                (metrics.get("cost") or {}).get("draft_tokens") or {}
            ),
            "editor_tokens": _aggregate(
                (metrics.get("cost") or {}).get("editor_tokens") or {}
            ),
        },
    }
    sampling = report.get("sampling") or {}
    allowed_counts = {
        "cases",
        "observations",
        "families",
        "observed",
        "failed",
        "missing",
        "failed_checks",
        "review_required",
        "numeric_required",
        "numeric_scores_missing",
    }
    result = {
        "schema_version": REPORT_SCHEMA,
        "suite_id": _identifier(report.get("suite_id")),
        "run_id": _identifier(report.get("run_id")),
        "profile": (
            report.get("profile")
            if report.get("profile") in {"ci", "smoke", "baseline", "release"}
            else None
        ),
        "claim_eligible": False,
        "status": (
            report.get("status")
            if report.get("status") in {"engineering_pass", "blocked"}
            else "blocked"
        ),
        "domain_status": (
            report.get("domain_status")
            if report.get("domain_status")
            in {
                "required_review_missing",
                "review_pending",
                "not_applicable",
                "supplied_review_complete_not_external_validation",
            }
            else "unknown"
        ),
        "domain_review_coverage": (
            report.get("domain_review_coverage")
            if _finite(report.get("domain_review_coverage"))
            else None
        ),
        "domain_review_required_coverage": (
            report.get("domain_review_required_coverage")
            if _finite(report.get("domain_review_required_coverage"))
            else None
        ),
        "source": {
            name: _hash((report.get("source") or {}).get(name))
            for name in ("commit", "source_sha256")
        },
        "registry_sha256": _hash(report.get("registry_sha256")),
        "cohort_sha256": _hash(report.get("cohort_sha256")),
        "scorer_version": _identifier(report.get("scorer_version")),
        "model": {
            "id": model_id,
            "revision": _hash(model.get("revision")),
            "config_sha256": _hash(model.get("config_sha256")),
        },
        "sampling": {
            name: value
            for name, value in sampling.items()
            if name in {"seed", "trials", "max_tokens"} and _finite(value)
        },
        "performance_environment_sha256": _hash(performance.get("environment_sha256")),
        "counts": {
            name: value
            for name, value in (report.get("counts") or {}).items()
            if name in allowed_counts and _finite(value)
        },
        "metrics": public_metrics,
        "lane_summaries": {
            name: _public_outcome(value)
            for name, value in (report.get("lane_summaries") or {}).items()
            if name in {"agronomy", "harness", "conversation"}
        },
        "family_summaries": [
            {"family_sha256": digest(name), **_public_outcome(value)}
            for name, value in sorted((report.get("family_summaries") or {}).items())
        ],
        "limitations": list(LIMITATIONS),
    }
    component_metrics = {
        "controls",
        "failed",
        "capabilities",
        "operations",
        "failures",
        "positive_cases",
        "negative_cases",
        "blocked_cases",
        "failed_cases",
        "positive_recall_at_7",
        "positive_ndcg_at_7",
        "negative_control_compliance",
        "source_locator_validity",
        "authority_compliance",
        "cases",
        "test_files",
        "exit_code",
        "repeats",
    }
    result["components"] = [
        {
            "component": row["component"],
            "status": (
                row.get("status")
                if row.get("status") in {"pass", "blocked", "failed"}
                else "blocked"
            ),
            "metrics": {
                key: value
                for key, value in (row.get("metrics") or {}).items()
                if key in component_metrics and _finite(value)
            },
            "receipt_sha256": _hash(row.get("receipt_sha256")),
        }
        for row in report.get("components") or []
        if row.get("component") in COMPONENTS
    ]
    result["repeatability"] = {
        "eligible_n": sum(
            row.get("exact_final_repeatable") is not None
            for row in report.get("repeatability") or []
        ),
        "exact_repeatable_n": sum(
            row.get("exact_final_repeatable") is True
            for row in report.get("repeatability") or []
        ),
    }
    intervention = metrics.get("intervention_benefit") or {}
    errors = intervention.get("material_error") or {}
    result["metrics"]["intervention_benefit"] = {
        "status": (
            intervention.get("status")
            if intervention.get("status")
            in {"supplied_stage_review_pairs", "review_pending_not_assessed"}
            else "unknown"
        ),
        "completion_delta": _aggregate(intervention.get("completion_delta") or {}),
        "optional_usefulness_delta": _aggregate(
            intervention.get("optional_usefulness_delta") or {}
        ),
        "material_error": {
            name: value if _finite(value) else None
            for name, value in errors.items()
            if name
            in {"eligible_pair_n", "unknown_pair_n", "introduced_n", "removed_n"}
        },
    }
    if report.get("comparison"):
        comparison = report["comparison"]
        check_ids = {
            "compatible_suite_id",
            "compatible_registry_sha256",
            "compatible_cohort_sha256",
            "compatible_scorer_version",
            "compatible_model",
            "compatible_sampling",
            "complete_reference",
            "complete_candidate",
            "finite_reference_data",
            "finite_candidate_data",
            "model_evidence_reference",
            "model_evidence_candidate",
            "planned_production_identity_coverage",
            "paired_question_and_case_contract",
            "no_new_failed_checks",
            "paired_numeric_score_coverage",
            "no_paired_numeric_case_regression",
            "numeric_accuracy",
            "positive_retrieval_recall_at_7",
            "performance_environment",
            "performance_elapsed_ms",
            "performance_peak_memory_bytes",
            "semantic_review_binding",
            "paired_review_rubric",
            "compatible_required_review_coverage",
            "paired_required_review_coverage",
            "introduced_material_errors",
            "required_completion",
        }
        check_ids.add("planned_production_completed")
        result["comparison"] = {
            "status": "pass" if comparison.get("status") == "pass" else "blocked",
            "claim_eligible": False,
            "semantic_status": (
                comparison.get("semantic_status")
                if comparison.get("semantic_status")
                in {
                    "review_pending_not_assessed",
                    "partially_paired_review",
                    "paired_supplied_review_not_external_validation",
                }
                else "unknown"
            ),
            "checks": [
                {
                    "id": row["id"],
                    "passed": (
                        row.get("passed")
                        if isinstance(row.get("passed"), bool)
                        else None
                    ),
                    "required": row.get("required") is True,
                }
                for row in comparison.get("checks") or []
                if row.get("id") in check_ids
            ],
        }
    result["private_report_sha256"] = digest(_clean_numbers(report))
    return result
