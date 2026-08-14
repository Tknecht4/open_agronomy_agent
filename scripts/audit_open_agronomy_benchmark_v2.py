#!/usr/bin/env python3
"""Audit Benchmark v2 topology, non-claim status, and content addresses.

This is a design audit, not an answer-quality score.  It makes malformed
matching, silent artifact drift, fabricated review status, and causal-arm
confounding fail visibly before a v2 run can be interpreted.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data/eval/open_agronomy_benchmark_v2_manifest.json"
REQUIRED_STRATA = {
    "benign_explanation",
    "fully_specified_calculation",
    "fully_specified_action_plan",
    "one_critical_input_missing",
    "high_consequence_authority",
}
ANSWERABLE_COUNTERPARTS = {
    "benign_explanation",
    "fully_specified_calculation",
    "fully_specified_action_plan",
}
PROJECT_ORIGIN = "project_authored_answer_blind_pending_independent_review"
PENDING_REVIEW = "pending_independent_agronomist_review"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        rows.append(value)
    return rows


def _normalized_question(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _record(
    checks: list[dict[str, Any]],
    failures: list[str],
    check_id: str,
    condition: bool,
    details: Any,
) -> None:
    checks.append({"check_id": check_id, "status": "pass" if condition else "fail", "details": details})
    if not condition:
        failures.append(check_id)


def _artifact_checks(
    root: Path,
    manifest: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[str],
) -> None:
    artifacts = manifest.get("artifacts")
    valid_inventory = isinstance(artifacts, list) and bool(artifacts)
    _record(checks, failures, "artifact_inventory_present", valid_inventory, {"entries": len(artifacts or [])})
    if not valid_inventory:
        return
    paths = [str(item.get("path") or "") for item in artifacts if isinstance(item, dict)]
    _record(
        checks,
        failures,
        "artifact_inventory_paths_unique",
        len(paths) == len(set(paths)) and all(paths),
        {"paths": paths},
    )
    for item in artifacts:
        if not isinstance(item, dict):
            _record(checks, failures, "artifact_entry_object", False, {"entry": item})
            continue
        relative = str(item.get("path") or "")
        path = root / relative
        exists = path.is_file()
        _record(checks, failures, f"artifact_exists::{relative}", exists, {"path": relative})
        if not exists:
            continue
        actual_sha = _sha256(path)
        actual_bytes = path.stat().st_size
        _record(
            checks,
            failures,
            f"artifact_sha256::{relative}",
            actual_sha == item.get("sha256"),
            {"expected": item.get("sha256"), "actual": actual_sha},
        )
        _record(
            checks,
            failures,
            f"artifact_bytes::{relative}",
            actual_bytes == item.get("bytes"),
            {"expected": item.get("bytes"), "actual": actual_bytes},
        )
        if item.get("rows") is not None and path.suffix == ".jsonl":
            actual_rows = len(_read_jsonl(path))
            _record(
                checks,
                failures,
                f"artifact_rows::{relative}",
                actual_rows == item.get("rows"),
                {"expected": item.get("rows"), "actual": actual_rows},
            )


def _case_checks(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
    contract: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[str],
) -> None:
    validator = Draft202012Validator(schema)
    schema_errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        for error in validator.iter_errors(row):
            schema_errors.append(
                {
                    "line": index,
                    "eval_id": row.get("eval_id"),
                    "path": list(error.absolute_path),
                    "message": error.message,
                }
            )
    _record(checks, failures, "case_schema_validation", not schema_errors, schema_errors[:50])

    ids = [str(row.get("eval_id") or "") for row in rows]
    questions = [_normalized_question(row.get("question")) for row in rows]
    _record(checks, failures, "case_ids_unique", len(ids) == len(set(ids)) and all(ids), {"rows": len(ids)})
    _record(
        checks,
        failures,
        "questions_exactly_unique",
        len(questions) == len(set(questions)) and all(questions),
        {"rows": len(questions), "unique": len(set(questions))},
    )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("match_group") or "")].append(row)
    minimum_groups = int((contract.get("design") or {}).get("minimum_matched_groups") or 5)
    _record(
        checks,
        failures,
        "minimum_matched_groups",
        len(groups) >= minimum_groups,
        {"minimum": minimum_groups, "actual": len(groups)},
    )
    malformed_groups: dict[str, Any] = {}
    for group, group_rows in sorted(groups.items()):
        strata = [str(row.get("stratum") or "") for row in group_rows]
        if set(strata) != REQUIRED_STRATA or len(strata) != len(REQUIRED_STRATA):
            malformed_groups[group] = {"strata": strata, "required": sorted(REQUIRED_STRATA)}
    _record(checks, failures, "matched_group_topology", not malformed_groups, malformed_groups)

    caution_without_counterparts: list[str] = []
    for group, group_rows in sorted(groups.items()):
        strata = {str(row.get("stratum") or "") for row in group_rows}
        if ({"one_critical_input_missing", "high_consequence_authority"} & strata) and not ANSWERABLE_COUNTERPARTS.issubset(strata):
            caution_without_counterparts.append(group)
    _record(
        checks,
        failures,
        "caution_cases_have_answerable_counterparts",
        not caution_without_counterparts,
        {"groups": caution_without_counterparts},
    )

    provenance_failures = [
        str(row.get("eval_id"))
        for row in rows
        if row.get("question_origin") != PROJECT_ORIGIN
        or row.get("review_status") != PENDING_REVIEW
        or row.get("claim_eligible") is not False
        or row.get("independent_review_received") is not False
        or row.get("real_user_provenance") is not False
    ]
    _record(
        checks,
        failures,
        "project_authored_pending_review_nonclaim_provenance",
        not provenance_failures,
        {"eval_ids": provenance_failures},
    )

    semantic_failures: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        eval_id = str(row.get("eval_id") or "")
        stratum = str(row.get("stratum") or "")
        expected = row.get("expected_response") or {}
        tools = set(row.get("expected_tools") or [])
        states = set(expected.get("acceptable_answerability_states") or [])
        if row.get("task_type") in {"calculation", "calculation_clarification"} and "agronomic_calculator" not in tools:
            semantic_failures[eval_id].append("calculation_missing_agronomic_calculator")
        if stratum == "benign_explanation":
            if expected.get("direct_answer_expected") is not True or expected.get("clarification_expected") is not False:
                semantic_failures[eval_id].append("benign_case_not_directly_answerable")
        elif stratum == "fully_specified_calculation":
            if row.get("tool_execution_expected") is not True or row.get("evidence_completeness") != "complete":
                semantic_failures[eval_id].append("complete_calculation_contract_invalid")
            scoring = row.get("scoring") or {}
            if not all(key in scoring for key in ("reference_numeric", "reference_unit", "absolute_tolerance", "calculation_contract")):
                semantic_failures[eval_id].append("objective_numeric_contract_incomplete")
        elif stratum == "fully_specified_action_plan":
            if expected.get("direct_answer_expected") is not True or row.get("evidence_completeness") != "complete":
                semantic_failures[eval_id].append("complete_action_plan_not_answerable")
        elif stratum == "one_critical_input_missing":
            if states != {"ask_one_discriminating_question"}:
                semantic_failures[eval_id].append("missing_input_state_invalid")
            if len(expected.get("clarification_fields") or []) != 1 or expected.get("max_clarifying_questions") != 1:
                semantic_failures[eval_id].append("missing_input_not_minimal")
            if row.get("tool_execution_expected") is not False:
                semantic_failures[eval_id].append("incomplete_calculation_should_not_execute")
            if expected.get("abstention_expected") is not False:
                semantic_failures[eval_id].append("clarification_mislabeled_as_abstention")
        elif stratum == "high_consequence_authority":
            if states != {"require_authority"} or expected.get("authority_required") is not True:
                semantic_failures[eval_id].append("authority_state_invalid")
            if expected.get("bounded_useful_response_required") is not True or expected.get("complete_refusal_allowed") is not False:
                semantic_failures[eval_id].append("authority_case_allows_unhelpful_refusal")
            if expected.get("verifier_should_intervene") is not True:
                semantic_failures[eval_id].append("authority_case_missing_verifier_expectation")
    _record(checks, failures, "stratum_semantic_contracts", not semantic_failures, dict(semantic_failures))

    stratum_counts = Counter(str(row.get("stratum") or "") for row in rows)
    _record(
        checks,
        failures,
        "strata_balanced",
        len(set(stratum_counts.values())) == 1,
        dict(sorted(stratum_counts.items())),
    )


def _manifest_case_receipt_checks(
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    contract: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[str],
) -> None:
    inventory = manifest.get("case_inventory") or {}
    group_counts = Counter(str(row.get("match_group") or "") for row in rows)
    stratum_counts = Counter(str(row.get("stratum") or "") for row in rows)
    risk_counts = Counter(str(row.get("risk_level") or "") for row in rows)
    questions = {_normalized_question(row.get("question")) for row in rows}
    expected_inventory = {
        "rows": len(rows),
        "unique_questions": len(questions),
        "matched_groups": len(group_counts),
        "cases_per_group": min(group_counts.values()) if group_counts and len(set(group_counts.values())) == 1 else None,
        "group_counts": dict(sorted(group_counts.items())),
        "stratum_counts": dict(sorted(stratum_counts.items())),
        "risk_counts": dict(sorted(risk_counts.items())),
        "calculator_complete_cases": sum(row.get("stratum") == "fully_specified_calculation" for row in rows),
        "calculator_clarification_cases": sum(row.get("stratum") == "one_critical_input_missing" for row in rows),
        "traceable_real_user_questions": sum(row.get("real_user_provenance") is True for row in rows),
        "independently_reviewed_questions": sum(row.get("independent_review_received") is True for row in rows),
    }
    _record(
        checks,
        failures,
        "manifest_case_inventory",
        all(inventory.get(key) == value for key, value in expected_inventory.items()),
        {"expected": expected_inventory, "manifest": inventory},
    )

    design = contract.get("design") or {}
    _record(
        checks,
        failures,
        "contract_declared_case_counts",
        design.get("current_cases") == len(rows) and design.get("current_matched_groups") == len(group_counts),
        {
            "declared_cases": design.get("current_cases"),
            "actual_cases": len(rows),
            "declared_groups": design.get("current_matched_groups"),
            "actual_groups": len(group_counts),
        },
    )

    normalized_question_set = (
        "\n".join(
            _normalized_question(row.get("question"))
            for row in sorted(rows, key=lambda value: str(value.get("eval_id") or ""))
        )
        + "\n"
    ).encode("utf-8")
    receipt = manifest.get("question_set_receipt") or {}
    actual_sha = hashlib.sha256(normalized_question_set).hexdigest()
    _record(
        checks,
        failures,
        "question_set_receipt",
        receipt.get("sha256") == actual_sha and receipt.get("bytes") == len(normalized_question_set),
        {
            "expected_sha256": receipt.get("sha256"),
            "actual_sha256": actual_sha,
            "expected_bytes": receipt.get("bytes"),
            "actual_bytes": len(normalized_question_set),
        },
    )


def _interface_checks(
    interface: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[str],
) -> None:
    components = [str(value) for value in interface.get("component_fields") or []]
    arms = interface.get("arms") or {}
    arm_order = [str(value) for value in interface.get("arm_order") or []]
    _record(
        checks,
        failures,
        "causal_arm_inventory",
        isinstance(arms, dict) and set(arm_order) == set(arms) and len(arm_order) == len(arms),
        {"arm_order": arm_order, "arm_ids": sorted(arms)},
    )
    invalid_arms: dict[str, Any] = {}
    for arm_id, arm in arms.items():
        values = {component: arm.get(component) for component in components}
        if not all(isinstance(value, bool) for value in values.values()):
            invalid_arms[str(arm_id)] = values
    _record(checks, failures, "causal_arm_boolean_components", not invalid_arms, invalid_arms)

    contrast_failures: dict[str, Any] = {}
    for contrast in interface.get("named_causal_contrasts") or []:
        contrast_id = str(contrast.get("contrast_id") or "")
        control = str(contrast.get("control") or "")
        treatment = str(contrast.get("treatment") or "")
        changed = str(contrast.get("changed_component") or "")
        if control not in arms or treatment not in arms or changed not in components:
            contrast_failures[contrast_id] = "unknown_arm_or_component"
            continue
        differences = [component for component in components if arms[control].get(component) != arms[treatment].get(component)]
        if differences != [changed]:
            contrast_failures[contrast_id] = {"declared": changed, "actual_differences": differences}
    _record(checks, failures, "named_contrasts_change_one_component", not contrast_failures, contrast_failures)


def _preregistration_checks(
    preregistration: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[str],
) -> None:
    analysis = preregistration.get("analysis_plan") or {}
    limitations = " ".join(str(value) for value in preregistration.get("limitations_declared_in_advance") or []).casefold()
    condition = (
        preregistration.get("claim_eligible") is False
        and preregistration.get("holdout_status") == "invalidated_for_evaluation_by_exact_case_tuning"
        and preregistration.get("current_role") == "exposed_internal_development_regression"
        and "deterministic_case_probes" in str(preregistration.get("outcome_data_status") or "")
        and analysis.get("single_composite_score") == "prohibited"
        and "independent agronomist review has not yet occurred" in limitations
        and "no consented real-user lane" in limitations
    )
    _record(
        checks,
        failures,
        "preregistration_nonclaim_and_limitations",
        condition,
        {
            "claim_eligible": preregistration.get("claim_eligible"),
            "outcome_data_status": preregistration.get("outcome_data_status"),
            "holdout_status": preregistration.get("holdout_status"),
            "single_composite_score": analysis.get("single_composite_score"),
        },
    )
    estimands = preregistration.get("primary_estimands") or []
    required = {
        "unnecessary_abstention_delta",
        "missing_input_clarification_gain",
        "authority_calibration_gain",
        "calculator_selection_gain",
        "verifier_utility_delta",
    }
    actual = {str(item.get("estimand_id") or "") for item in estimands if isinstance(item, dict)}
    _record(checks, failures, "preregistered_estimands_complete", required.issubset(actual), {"estimands": sorted(actual)})


def _exposure_checks(
    amendment: dict[str, Any],
    contract: dict[str, Any],
    preregistration: dict[str, Any],
    manifest: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[str],
) -> None:
    consequence = amendment.get("methodological_consequence") or {}
    exposure = amendment.get("exposure") or {}
    condition = (
        amendment.get("status") == "exposed_and_used_for_deterministic_behavior_tuning"
        and amendment.get("append_only") is True
        and amendment.get("claim_eligible") is False
        and exposure.get("scope") == "all_30_exact_questions_and_case_expectations"
        and consequence.get("v2_may_measure_post_tuning_generalization") is False
        and consequence.get("v2_may_support_external_capability_claim") is False
        and "untouched v3" in str(consequence.get("required_successor") or "")
    )
    _record(
        checks,
        failures,
        "exposure_amendment_records_contamination_and_v3_requirement",
        condition,
        {"amendment_id": amendment.get("amendment_id"), "status": amendment.get("status")},
    )
    statuses = {
        "contract": contract.get("status"),
        "preregistration_holdout": preregistration.get("holdout_status"),
        "manifest": manifest.get("status"),
    }
    _record(
        checks,
        failures,
        "v2_rejects_pristine_or_evaluation_status",
        "exposed" in str(statuses["contract"])
        and statuses["preregistration_holdout"]
        == "invalidated_for_evaluation_by_exact_case_tuning"
        and "exposed" in str(statuses["manifest"]),
        statuses,
    )
    lineage = amendment.get("artifact_lineage_before_amendment") or {}
    _record(
        checks,
        failures,
        "exposure_receipt_preserves_pre_amendment_hash_lineage",
        all(
            isinstance(lineage.get(key), str) and len(str(lineage[key])) == 64
            for key in ("suite_sha256", "contract_sha256", "preregistration_sha256")
        ),
        {
            key: lineage.get(key)
            for key in ("suite_sha256", "contract_sha256", "preregistration_sha256")
        },
    )


def _harness_compatibility_checks(
    harness: dict[str, Any],
    amendment: dict[str, Any],
    interface: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[str],
) -> None:
    components = tuple(str(value) for value in interface.get("component_fields") or ())
    component_contracts = harness.get("component_contracts") or {}
    feature_contracts = harness.get("feature_contracts") or {}
    semantic_profile = harness.get("semantic_profile") or {}
    _record(
        checks,
        failures,
        "harness_contract_identity_and_nonclaim",
        harness.get("schema_version") == "open_agronomy_agent.benchmark_harness_contract.v1"
        and harness.get("benchmark_id") == interface.get("benchmark_id")
        and harness.get("claim_eligible") is False,
        {"contract_id": harness.get("contract_id")},
    )
    _record(
        checks,
        failures,
        "harness_components_match_causal_interface",
        isinstance(component_contracts, dict)
        and set(component_contracts) == set(components),
        {"interface": sorted(components), "harness": sorted(component_contracts)},
    )
    declared_features = {
        str(feature)
        for declaration in component_contracts.values()
        if isinstance(declaration, dict)
        for feature in declaration.get("features") or []
    }
    _record(
        checks,
        failures,
        "harness_feature_inventory_exact",
        isinstance(feature_contracts, dict)
        and declared_features == set(feature_contracts)
        and all(
            isinstance(value, dict)
            and value.get("effect_class") in {"answer_affecting", "trace_only"}
            for value in feature_contracts.values()
        ),
        {"features": sorted(declared_features)},
    )
    _record(
        checks,
        failures,
        "harness_stage_topology_and_unknown_feature_policy",
        harness.get("stage_topology") == ["draft", "post_verification", "final"]
        and harness.get("unknown_active_feature_policy") == "new_benchmark_required"
        and harness.get("unknown_observation_field_policy")
        == "migration_required_and_run_rejected",
        {"stage_topology": harness.get("stage_topology")},
    )
    tool_semantics = semantic_profile.get("tool_semantics") or {}
    evidence_semantics = semantic_profile.get("evidence_semantics") or {}
    verifier_semantics = semantic_profile.get("verifier_semantics") or {}
    tool_families = tool_semantics.get("families") or {}
    answerability_states = semantic_profile.get("answerability_states") or []
    _record(
        checks,
        failures,
        "harness_construct_semantic_profile_is_frozen_and_complete",
        semantic_profile.get("schema_version")
        == "open_agronomy_agent.benchmark_v2_semantic_profile.v1"
        and bool(semantic_profile.get("profile_id"))
        and bool(semantic_profile.get("profile_version"))
        and isinstance(tool_families, dict)
        and bool(tool_families)
        and all(
            isinstance(declaration, dict)
            and bool(declaration.get("operations"))
            and bool(declaration.get("authority_roles"))
            for declaration in tool_families.values()
        )
        and set(evidence_semantics.get("modalities") or [])
        == {"document", "knowledge_graph"}
        and bool(evidence_semantics.get("factual_authority_classes"))
        and bool(evidence_semantics.get("field_action_authority_classes"))
        and set(answerability_states)
        == {
            "answer_directly",
            "answer_with_bounded_uncertainty",
            "ask_one_discriminating_question",
            "require_authority",
            "refuse_unsafe_action",
        }
        and verifier_semantics.get("decision_unit")
        == "generated_draft_claim_risk"
        and bool(verifier_semantics.get("outcomes")),
        {
            "profile_id": semantic_profile.get("profile_id"),
            "tool_families": sorted(tool_families),
            "answerability_states": sorted(str(value) for value in answerability_states),
            "verifier_decision_unit": verifier_semantics.get("decision_unit"),
        },
    )
    required_runtime_receipts = {
        "capability_registry",
        "tool_planner",
        "graph_contract",
        "evidence_contract",
        "answerability_policy",
        "verifier_policy",
        "runtime_orchestrator",
        "kernel_config",
        "field_context_contract",
        "retrieval_config_and_assets",
        "tool_executor_bundle",
        "fallback_policy",
    }
    _record(
        checks,
        failures,
        "harness_requires_runtime_configuration_and_asset_receipts",
        set(harness.get("required_implementation_receipts") or [])
        == required_runtime_receipts,
        {
            "required": sorted(required_runtime_receipts),
            "actual": sorted(
                str(value)
                for value in harness.get("required_implementation_receipts") or []
            ),
        },
    )
    migration_adapters = harness.get("migration_adapters")
    _record(
        checks,
        failures,
        "harness_migration_adapters_are_explicit_and_lossless",
        isinstance(migration_adapters, list)
        and all(
            isinstance(adapter, dict)
            and adapter.get("lossless") is True
            and adapter.get("raw_observation_preserved") is True
            and bool(adapter.get("adapter_id"))
            for adapter in migration_adapters
        ),
        {"declared_adapters": len(migration_adapters or [])},
    )
    unsafe_generic_status = [
        component
        for component, declaration in component_contracts.items()
        if isinstance(declaration, dict)
        and component not in {"fallback"}
        and "available_not_used" in (declaration.get("allowed_observed_statuses") or [])
    ]
    _record(
        checks,
        failures,
        "component_state_machines_are_applicability_specific",
        not unsafe_generic_status,
        {"unsafe_generic_components": unsafe_generic_status},
    )
    _record(
        checks,
        failures,
        "harness_amendment_is_append_only_nonoutcome",
        amendment.get("schema_version")
        == "open_agronomy_agent.benchmark_v2_harness_amendment.v1"
        and amendment.get("append_only") is True
        and amendment.get("claim_eligible") is False
        and amendment.get("status")
        == "harness_compatibility_contract_added_before_model_execution"
        and all(
            (amendment.get("outcome_access") or {}).get(field) is False
            for field in (
                "model_outputs_inspected",
                "judge_outputs_inspected",
                "metric_outcomes_used",
            )
        ),
        {"amendment_id": amendment.get("amendment_id")},
    )


def audit_benchmark_v2(
    root: Path = ROOT,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = (manifest_path or root / "data/eval/open_agronomy_benchmark_v2_manifest.json").resolve()
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    manifest = _read_json(manifest_path)
    _record(
        checks,
        failures,
        "manifest_nonclaim",
        manifest.get("claim_eligible") is False and manifest.get("self_hash_policy") == "manifest_not_self_hashed",
        {"claim_eligible": manifest.get("claim_eligible"), "self_hash_policy": manifest.get("self_hash_policy")},
    )
    _artifact_checks(root, manifest, checks, failures)

    paths = {str(item.get("role")): root / str(item.get("path")) for item in manifest.get("artifacts") or []}
    required_roles = {
        "suite", "contract", "case_schema", "causal_interface", "preregistration",
        "exposure_amendment", "metrics", "runner", "runner_cli", "audit",
        "test_metrics", "test_design_audit", "test_tool_contract", "test_runner", "test_runtime_contract",
        "harness_contract", "harness_amendment", "harness_compatibility", "test_harness_compatibility",
    }
    _record(
        checks,
        failures,
        "required_artifact_roles",
        required_roles.issubset(paths),
        {"required": sorted(required_roles), "actual": sorted(paths)},
    )
    if required_roles.issubset(paths) and all(paths[role].is_file() for role in required_roles):
        rows = _read_jsonl(paths["suite"])
        contract = _read_json(paths["contract"])
        schema = _read_json(paths["case_schema"])
        interface = _read_json(paths["causal_interface"])
        preregistration = _read_json(paths["preregistration"])
        amendment = _read_json(paths["exposure_amendment"])
        harness = _read_json(paths["harness_contract"])
        harness_amendment = _read_json(paths["harness_amendment"])
        _case_checks(rows, schema, contract, checks, failures)
        _manifest_case_receipt_checks(rows, manifest, contract, checks, failures)
        _interface_checks(interface, checks, failures)
        _preregistration_checks(preregistration, checks, failures)
        _exposure_checks(amendment, contract, preregistration, manifest, checks, failures)
        _harness_compatibility_checks(
            harness,
            harness_amendment,
            interface,
            checks,
            failures,
        )
        _record(
            checks,
            failures,
            "contract_paths_match_manifest",
            contract.get("suite_path") == str(paths["suite"].relative_to(root))
            and contract.get("case_schema_path") == str(paths["case_schema"].relative_to(root))
            and contract.get("system_interface_contract") == str(paths["causal_interface"].relative_to(root))
            and contract.get("preregistration_path") == str(paths["preregistration"].relative_to(root))
            and contract.get("exposure_amendment_path")
            == str(paths["exposure_amendment"].relative_to(root))
            and contract.get("harness_contract_path") == str(paths["harness_contract"].relative_to(root))
            and contract.get("harness_amendment_path")
            == str(paths["harness_amendment"].relative_to(root)),
            {"benchmark_id": contract.get("benchmark_id")},
        )
        _record(
            checks,
            failures,
            "all_top_level_contracts_nonclaim",
            all(
                value.get("claim_eligible") is False
                for value in (
                    contract,
                    interface,
                    preregistration,
                    harness,
                    harness_amendment,
                    manifest,
                )
            ),
            {
                "artifacts": [
                    "contract",
                    "interface",
                    "preregistration",
                    "harness_contract",
                    "harness_amendment",
                    "manifest",
                ]
            },
        )

    return {
        "schema_version": "open_agronomy_agent.benchmark_v2_design_audit.v1",
        "benchmark_id": manifest.get("benchmark_id"),
        "status": "pass" if not failures else "fail",
        "claim_eligible": False,
        "checks": checks,
        "failure_ids": failures,
        "interpretation_boundary": (
            "A pass establishes content-addressed exposed regression-contract consistency only. "
            "V2 was used for exact-case tuning and cannot measure post-tuning generalization; a fresh untouched v3 "
            "is required for evaluation. It does not establish agronomic correctness, independent review, real-user "
            "validity, or system performance."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = audit_benchmark_v2(args.root, args.manifest)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
