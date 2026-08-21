from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.paths import repo_path
from agronomy_agent.runtime_profiles import DEFAULT_MODEL_CONFIG


CONFERENCE_MODEL_CONFIG_PATH = DEFAULT_MODEL_CONFIG
LORA_PREREGISTRATION_PATH = (
    "outputs/not_bounded_research_20260724/"
    "agxqa_grounded_lora_iteration2_preregistration_20260724.json"
)
LORA_DECISION_PATH = (
    "outputs/not_bounded_research_20260724/"
    "agxqa_grounded_lora_iteration2_decision_20260724.md"
)
LORA_STABILITY_COMPARISON_PATH = (
    "outputs/not_bounded_research_20260724/"
    "canadian_stability_adapter_step0200_comparison.json"
)
LORA_BASE_TEST_PATH = (
    "outputs/not_bounded_research_20260724/agxqa_grounded_eval/"
    "gemma4_e2b_base_test_once_20260724T074058Z/summary.json"
)
LORA_ADAPTER_TEST_PATH = (
    "outputs/not_bounded_research_20260724/agxqa_grounded_eval/"
    "gemma4_e2b_agxqa_v3_positive4to1_step0200_test_once_20260724T073132Z/"
    "summary.json"
)


def conference_model_decision(
    *,
    model_config_path: Path | None = None,
    active_model_config_path: Path | None = None,
    preregistration_path: Path | None = None,
    decision_path: Path | None = None,
    stability_comparison_path: Path | None = None,
    base_test_path: Path | None = None,
    adapter_test_path: Path | None = None,
) -> dict[str, Any]:
    paths = {
        "conference_model_config": (
            model_config_path or repo_path(CONFERENCE_MODEL_CONFIG_PATH)
        ).resolve(),
        "adapter_preregistration": (
            preregistration_path or repo_path(LORA_PREREGISTRATION_PATH)
        ).resolve(),
        "adapter_decision": (decision_path or repo_path(LORA_DECISION_PATH)).resolve(),
        "full_system_comparison": (
            stability_comparison_path or repo_path(LORA_STABILITY_COMPARISON_PATH)
        ).resolve(),
        "base_task_test": (base_test_path or repo_path(LORA_BASE_TEST_PATH)).resolve(),
        "adapter_task_test": (
            adapter_test_path or repo_path(LORA_ADAPTER_TEST_PATH)
        ).resolve(),
    }
    try:
        model = _read_yaml(paths["conference_model_config"])
        preregistration = _read_json(paths["adapter_preregistration"])
        comparison = _read_json(paths["full_system_comparison"])
        base_test = _read_json(paths["base_task_test"])
        adapter_test = _read_json(paths["adapter_task_test"])
        decision_text = paths["adapter_decision"].read_text(encoding="utf-8")
        _validate_evidence(
            model=model,
            preregistration=preregistration,
            comparison=comparison,
            base_test=base_test,
            adapter_test=adapter_test,
            decision_text=decision_text,
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return {
            "schema_version": "open_agronomy_agent.conference_model_decision.v1",
            "available": False,
            "status": "unavailable",
            "message": f"Conference model-decision evidence is unavailable: {exc}",
            "global_adapter_promoted": False,
            "boundary": (
                "Missing or inconsistent model evidence must not be interpreted as proof that "
                "an adapter is active, safe, or better than the base conference model."
            ),
        }

    base_metrics = base_test["metrics"]
    adapter_metrics = adapter_test["metrics"]
    evidence = {
        name: {
            "path": _repo_relative(path),
            "sha256": _sha256(path),
        }
        for name, path in paths.items()
    }
    active_runtime_configuration = _active_runtime_configuration(
        path=(
            active_model_config_path
            or repo_path(CONFERENCE_MODEL_CONFIG_PATH)
        ).resolve(),
        conference_model=model,
    )
    return {
        "schema_version": "open_agronomy_agent.conference_model_decision.v1",
        "available": True,
        "status": "base_model_retained",
        "conference_model": {
            "model_id": model["model_id"],
            "revision": model["model_revision"],
            "license": model["license"],
            "quality_gate": model["serving_quality_gate"],
            "max_tokens": model["serving_max_tokens"],
        },
        "active_runtime_configuration": active_runtime_configuration,
        "adapter_candidate": {
            "task": "excerpt-grounded irrigation QA and abstention",
            "checkpoint_step": 200,
            "scoped_task_test_status": "pass",
            "global_runtime_status": "rejected",
            "global_adapter_promoted": False,
            "task_test": {
                "rows": adapter_metrics["rows"],
                "base_balanced_primary": base_metrics["balanced_primary_score"],
                "adapter_balanced_primary": adapter_metrics["balanced_primary_score"],
                "delta": round(
                    adapter_metrics["balanced_primary_score"]
                    - base_metrics["balanced_primary_score"],
                    2,
                ),
            },
            "full_system_stability": {
                "status": comparison["status"],
                "rows": comparison["rows"],
                "base_mean": comparison["base"]["mean_score"],
                "adapter_mean": comparison["candidate"]["mean_score"],
                "delta": comparison["mean_score_delta"],
                "critical_regression_rows": comparison["critical_regression_rows"],
                "new_missing_required_rows": comparison["new_missing_required_rows"],
                "new_forbidden_hit_rows": comparison["new_forbidden_hit_rows"],
            },
        },
        "evidence": evidence,
        "boundary": (
            "The adapter improved its frozen document-disjoint extraction test but regressed the "
            "complete Canadian/regional answer path. It is not attached to the global conference "
            "runtime. This decision is evidence for retaining the pinned base model, not a claim "
            "of general agronomic competence. The active-runtime record reports the process "
            "configuration only; even an exact match does not prove that weights loaded or that "
            "a response used that model."
        ),
    }


def _active_runtime_configuration(
    *,
    path: Path,
    conference_model: dict[str, Any],
) -> dict[str, Any]:
    try:
        active = _read_yaml(path)
        model_id = str(active.get("serving_model_id") or active.get("model_id") or "")
        revision = str(active.get("model_revision") or "")
        if not model_id:
            raise ValueError("active model configuration has no model identity")
    except (FileNotFoundError, OSError, ValueError, yaml.YAMLError) as exc:
        return {
            "available": False,
            "status": "unavailable",
            "matches_conference_model": False,
            "config_path": _safe_config_reference(path),
            "message": (
                "Active model configuration could not be read or validated "
                f"({type(exc).__name__})."
            ),
            "boundary": (
                "No active-model match may be inferred when the process configuration cannot be read."
            ),
        }

    matches = (
        model_id == conference_model["model_id"]
        and revision == conference_model["model_revision"]
    )
    return {
        "available": True,
        "status": (
            "configuration_matches_decision"
            if matches
            else "configuration_mismatch"
        ),
        "config_path": _safe_config_reference(path),
        "sha256": _sha256(path),
        "model_id": model_id,
        "revision": revision or None,
        "serving_role": active.get("serving_role"),
        "quality_gate": active.get("serving_quality_gate"),
        "matches_conference_model": matches,
        "identity_fields": ["model_id", "revision"],
        "boundary": (
            "This is the model identity selected in the server process configuration. "
            "It is not proof that weights loaded successfully or that any particular answer "
            "was generated by this model."
        ),
    }


def _validate_evidence(
    *,
    model: dict[str, Any],
    preregistration: dict[str, Any],
    comparison: dict[str, Any],
    base_test: dict[str, Any],
    adapter_test: dict[str, Any],
    decision_text: str,
) -> None:
    required_model_fields = (
        "model_id",
        "model_revision",
        "license",
        "serving_quality_gate",
        "serving_max_tokens",
    )
    if any(not model.get(field) for field in required_model_fields):
        raise ValueError("conference model configuration is incomplete")
    if (
        preregistration.get("schema_version")
        != "open_agronomy_agent.agxqa_grounded_lora_preregistration.v2"
    ):
        raise ValueError("unsupported adapter preregistration")
    preregistered_model = preregistration.get("base_model")
    if not isinstance(preregistered_model, dict) or (
        preregistered_model.get("model_id"),
        preregistered_model.get("revision"),
    ) != (model["model_id"], model["model_revision"]):
        raise ValueError("adapter preregistration does not match the conference model identity")
    if (
        comparison.get("schema_version")
        != "open_agronomy_agent.canadian_stability_comparison.v1"
        or comparison.get("status") != "fail"
    ):
        raise ValueError("full-system adapter comparison is not a recorded failure")
    if not isinstance(comparison.get("critical_regression_rows"), int) or comparison[
        "critical_regression_rows"
    ] <= 0:
        raise ValueError("full-system comparison has no recorded critical regression")
    for label, summary in (("base", base_test), ("adapter", adapter_test)):
        if summary.get("schema_version") != "open_agronomy_agent.agxqa_grounded_eval.v1":
            raise ValueError(f"unsupported {label} task-test evidence")
        dataset = summary.get("dataset")
        metrics = summary.get("metrics")
        if not isinstance(dataset, dict) or not isinstance(metrics, dict):
            raise ValueError(f"{label} task-test evidence is incomplete")
        if metrics.get("rows") != 476:
            raise ValueError(f"{label} task-test row count is invalid")
    if base_test["dataset"].get("sha256") != adapter_test["dataset"].get("sha256"):
        raise ValueError("base and adapter task tests do not use the same frozen dataset")
    if any(
        summary.get("model", {}).get("model_id") != model["model_id"]
        for summary in (base_test, adapter_test)
    ):
        raise ValueError("task-test model identity does not match the conference model")
    if (
        "global-runtime promotion rejected" not in decision_text
        or "Do not attach this adapter to the global agronomy answer model" not in decision_text
    ):
        raise ValueError("adapter decision does not record global-runtime rejection")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"evidence root must be an object: {path}")
    return payload


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"model configuration root must be an object: {path}")
    return payload


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(repo_path(".").resolve()))
    except ValueError:
        return str(path)


def _safe_config_reference(path: Path) -> str:
    try:
        return str(path.relative_to(repo_path(".").resolve()))
    except ValueError:
        return f"<external>/{path.name}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
