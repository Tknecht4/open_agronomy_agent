from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from agronomy_agent.paths import repo_path
from agronomy_agent.runtime_profiles import DEFAULT_MODEL_CONFIG
from agronomy_agent.server.services.model_decision_service import (
    _active_runtime_configuration,
    conference_model_decision,
)


DECISION_MANIFEST_PATH = (
    "data/manifests/model_adaptation_decision_20260727.json"
)
ANCHOR_CANDIDATES_PATH = "data/manifests/canadian_anchor_model_candidates_v1.json"
TASK_RABBIT_TRAINING_PATH = "data/training/canadian_task_rabbit_v1/manifest.json"
TASK_RABBIT_LORA_PATH = "data/manifests/gemma3_270m_task_rabbit_lora_v1.json"
TASK_RABBIT_POLICY_PATH = "configs/task_rabbit_promotion_v1.json"
ANSWER_MODEL_COMPARISON_PATH = (
    "outputs/evals/canadian_semantic_reserve_v2_qwen_vs_gemma_valid_20260721/"
    "summary.json"
)
E2B_PROMOTION_STATUS_PATH = (
    "outputs/models/gemma4_e2b_agxqa_grounded_lora_v3_positive4to1/"
    "PROMOTION_STATUS.json"
)
E2B_FEASIBILITY_METRICS_PATH = (
    "docs/rc13_system_peer_review_20260723/skill_state/gepa_metrics.json"
)


def model_adaptation_readiness(
    *,
    active_model_config_path: Path | None = None,
    decision_manifest_path: Path | None = None,
    anchor_candidates_path: Path | None = None,
    task_rabbit_training_path: Path | None = None,
    task_rabbit_lora_path: Path | None = None,
    task_rabbit_policy_path: Path | None = None,
    answer_model_comparison_path: Path | None = None,
    e2b_promotion_status_path: Path | None = None,
    e2b_feasibility_metrics_path: Path | None = None,
) -> dict[str, Any]:
    """Return the shipped, fail-closed model-adaptation decision.

    The grower-facing edge image does not ship bulky training runs. Its default
    path therefore reads a compact manifest compiled and validated from the raw
    experiments. Raw-path overrides remain available only for evidence-builder
    tests and source-repository audits.
    """

    raw_overrides = (
        anchor_candidates_path,
        task_rabbit_training_path,
        task_rabbit_lora_path,
        task_rabbit_policy_path,
        answer_model_comparison_path,
        e2b_promotion_status_path,
        e2b_feasibility_metrics_path,
    )
    if any(path is not None for path in raw_overrides):
        return compile_model_adaptation_decision(
            active_model_config_path=active_model_config_path,
            anchor_candidates_path=anchor_candidates_path,
            task_rabbit_training_path=task_rabbit_training_path,
            task_rabbit_lora_path=task_rabbit_lora_path,
            task_rabbit_policy_path=task_rabbit_policy_path,
            answer_model_comparison_path=answer_model_comparison_path,
            e2b_promotion_status_path=e2b_promotion_status_path,
            e2b_feasibility_metrics_path=e2b_feasibility_metrics_path,
        )

    path = (
        decision_manifest_path or repo_path(DECISION_MANIFEST_PATH)
    ).resolve()
    try:
        manifest = _read_json(path)
        if (
            manifest.get("schema_version")
            != "open_agronomy_agent.model_adaptation_decision_manifest.v1"
        ):
            raise ValueError("unsupported model-adaptation decision manifest schema")
        decision = manifest.get("decision")
        if not isinstance(decision, dict):
            raise ValueError("model-adaptation decision manifest has no decision object")
        _validate_compiled_decision(decision)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        return _unavailable(
            f"Model-adaptation decision manifest is unavailable or inconsistent: {exc}"
        )

    result = deepcopy(decision)
    conference_model = result["conference_answer_model"]
    active = _active_runtime_configuration(
        path=(
            active_model_config_path
            or repo_path(DEFAULT_MODEL_CONFIG)
        ).resolve(),
        conference_model={
            "model_id": conference_model["model_id"],
            "model_revision": conference_model["revision"],
        },
    )
    conference_model["active_runtime_configuration"] = active
    conference_model["active_identity_matches_decision"] = bool(
        active.get("matches_conference_model")
    )
    blockers = [
        item
        for item in result.get("blockers", [])
        if item.get("id") != "active_model_configuration_mismatch"
    ]
    if not active.get("matches_conference_model"):
        blockers.append(
            {
                "id": "active_model_configuration_mismatch",
                "status": "open",
                "reason": (
                    "The active process configuration does not match the pinned conference "
                    "model ID and revision. A model-quality claim cannot be attached to this "
                    "process."
                ),
            }
        )
    result["blockers"] = blockers
    result.setdefault("evidence", {})["model_adaptation_decision_manifest"] = {
        "path": _repo_relative(path),
        "sha256": _sha256(path),
    }
    active_path = (
        active_model_config_path or repo_path(DEFAULT_MODEL_CONFIG)
    ).resolve()
    if active_path.is_file():
        result["evidence"]["active_model_config"] = {
            "path": _repo_relative(active_path),
            "sha256": _sha256(active_path),
        }
    return result


def compile_model_adaptation_decision(
    *,
    active_model_config_path: Path | None = None,
    anchor_candidates_path: Path | None = None,
    task_rabbit_training_path: Path | None = None,
    task_rabbit_lora_path: Path | None = None,
    task_rabbit_policy_path: Path | None = None,
    answer_model_comparison_path: Path | None = None,
    e2b_promotion_status_path: Path | None = None,
    e2b_feasibility_metrics_path: Path | None = None,
) -> dict[str, Any]:
    paths = {
        "anchor_candidates": (
            anchor_candidates_path or repo_path(ANCHOR_CANDIDATES_PATH)
        ).resolve(),
        "task_rabbit_training": (
            task_rabbit_training_path or repo_path(TASK_RABBIT_TRAINING_PATH)
        ).resolve(),
        "task_rabbit_lora": (
            task_rabbit_lora_path or repo_path(TASK_RABBIT_LORA_PATH)
        ).resolve(),
        "task_rabbit_policy": (
            task_rabbit_policy_path or repo_path(TASK_RABBIT_POLICY_PATH)
        ).resolve(),
        "answer_model_comparison": (
            answer_model_comparison_path or repo_path(ANSWER_MODEL_COMPARISON_PATH)
        ).resolve(),
        "e2b_promotion_status": (
            e2b_promotion_status_path or repo_path(E2B_PROMOTION_STATUS_PATH)
        ).resolve(),
        "e2b_feasibility_metrics": (
            e2b_feasibility_metrics_path or repo_path(E2B_FEASIBILITY_METRICS_PATH)
        ).resolve(),
    }
    try:
        anchor = _read_json(paths["anchor_candidates"])
        training = _read_json(paths["task_rabbit_training"])
        rabbit = _read_json(paths["task_rabbit_lora"])
        policy = _read_json(paths["task_rabbit_policy"])
        comparison = _read_json(paths["answer_model_comparison"])
        e2b_status = _read_json(paths["e2b_promotion_status"])
        feasibility = _read_json(paths["e2b_feasibility_metrics"])
        _validate_evidence(
            anchor=anchor,
            training=training,
            rabbit=rabbit,
            policy=policy,
            comparison=comparison,
            e2b_status=e2b_status,
            feasibility=feasibility,
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        return _unavailable(
            f"Model-adaptation evidence is unavailable or inconsistent: {exc}"
        )

    conference = conference_model_decision(
        active_model_config_path=active_model_config_path
    )
    if not conference.get("available"):
        return _unavailable(
            "Conference model-decision evidence is unavailable or inconsistent.",
            boundary=conference.get("boundary"),
        )

    active = conference["active_runtime_configuration"]
    active_matches = bool(active.get("matches_conference_model"))
    rabbit_checkpoint = rabbit["training"]["checkpoints"]["step_100"]
    rabbit_eval = rabbit["valid_evaluations"]["step_100"]
    paired = comparison["paired_left_minus_right_by_variant"][
        "complete_routed_and_verified_system"
    ]
    e2b_scoped = e2b_status["scoped_agxqa_test"]
    e2b_stability = e2b_status["full_system_stability"]
    blockers = [
        {
            "id": "independent_agronomist_model_review",
            "status": "open",
            "reason": (
                "The corrected answer-model comparison is a reused 90-question reserve "
                "with blinded AI semantic review, not independent agronomist sign-off."
            ),
        },
        {
            "id": "task_rabbit_independent_transfer",
            "status": "open",
            "reason": (
                "The Gemma 270M training package is synthetic and explicitly contains no "
                "independent transfer set; its development evaluation still had "
                f"{rabbit_eval['rows_with_safety_critical_tool_omission']} safety-critical "
                "tool-omission rows."
            ),
        },
        {
            "id": "global_adapter_system_stability",
            "status": "open",
            "reason": (
                "The Gemma E2B adapter improved its document-disjoint microtask but created "
                f"{e2b_stability['critical_regression_rows']} critical full-system "
                f"regressions and changed the system mean by "
                f"{e2b_stability['mean_score_delta']} points."
            ),
        },
    ]
    if not active_matches:
        blockers.append(
            {
                "id": "active_model_configuration_mismatch",
                "status": "open",
                "reason": (
                    "The active process configuration does not match the pinned conference "
                    "model ID and revision. A model-quality claim cannot be attached to this "
                    "process."
                ),
            }
        )

    evidence = {
        name: {
            "path": _repo_relative(path),
            "sha256": _sha256(path),
        }
        for name, path in paths.items()
    }
    evidence.update(conference["evidence"])
    return {
        "schema_version": "open_agronomy_agent.model_adaptation_readiness.v1",
        "available": True,
        "status": "do_not_start_new_global_lora",
        "global_adapter_promoted": False,
        "new_global_lora_authorized": False,
        "hardware_feasibility": {
            "status": "demonstrated_for_bounded_experiments",
            "machine_class": "Apple silicon, 16 GB unified memory",
            "gemma3_270m_observed_peak_memory_gb": rabbit["training"]["peak_memory_gb"],
            "gemma4_e2b_smoke_observed_peak_memory_gb": feasibility[
                "quality_signals"
            ]["lora_peak_memory_gb"],
            "boundary": (
                "These completed MLX runs demonstrate that small adapter experiments fit on "
                "the development machine. They do not establish thermal endurance, battery "
                "behavior, production latency, or quality."
            ),
        },
        "conference_answer_model": {
            **conference["conference_model"],
            "active_runtime_configuration": active,
            "active_identity_matches_decision": active_matches,
            "selection_evidence": {
                "comparison_status": comparison["status"],
                "rows_per_model_all_variants": comparison["rows_per_model"],
                "complete_system_paired_rows": paired["pairs"],
                "qwen_minus_gemma_semantic_delta": paired["semantic_delta_mean"],
                "paired_bootstrap_95_ci": paired[
                    "semantic_delta_paired_bootstrap_95_ci"
                ],
                "independent_agronomist_signoff": comparison[
                    "scientific_boundary"
                ]["independent_agronomist_signoff"],
                "untouched_second_holdout": comparison["scientific_boundary"][
                    "untouched_second_holdout"
                ],
            },
        },
        "experiments": [
            {
                "id": "gemma3_270m_task_rabbit_lora_v1",
                "role": "schema-bounded route and evidence extraction",
                "base_model_id": rabbit["base_model"]["model_id"],
                "selected_checkpoint": "step_100",
                "trainable_parameters": rabbit["training"]["trainable_parameters"],
                "selected_validation_loss": rabbit_checkpoint["validation_loss"],
                "strict_json_rate": rabbit_eval["strict_json_rate"],
                "tool_micro_f1": rabbit_eval["tool_micro_f1"],
                "safety_critical_omission_rows": rabbit_eval[
                    "rows_with_safety_critical_tool_omission"
                ],
                "synthetic_training": training["synthetic"],
                "independent_transfer_set_included": training[
                    "independent_transfer_set_included"
                ],
                "status": "rejected_for_runtime",
                "allowed_use": "research only",
                "prohibited_use": "grower-facing answer generation or tool authority",
            },
            {
                "id": "gemma4_e2b_agxqa_grounded_lora_v3",
                "role": "excerpt-grounded extraction and abstention",
                "base_model_id": conference["conference_model"]["model_id"],
                "selected_checkpoint": e2b_status["selected_checkpoint"],
                "document_disjoint_task_status": e2b_scoped["status"],
                "document_disjoint_balanced_delta": e2b_scoped[
                    "balanced_primary_delta_points"
                ],
                "full_system_status": e2b_stability["status"],
                "full_system_mean_delta": e2b_stability["mean_score_delta"],
                "critical_regression_rows": e2b_stability[
                    "critical_regression_rows"
                ],
                "status": "research_only_not_for_global_runtime",
                "allowed_use": e2b_status["allowed_use"],
                "prohibited_use": e2b_status["prohibited_use"],
            },
        ],
        "blockers": blockers,
        "next_experiment": {
            "authorized_scope": (
                "One explicitly routed, non-advisory extraction microtask; do not train a "
                "global agronomy-answer adapter."
            ),
            "required_before_training": [
                "Freeze a separately authored source-document-disjoint transfer set.",
                "Freeze base, adapter, retrieval, prompt, quantization, seed, and decoding controls.",
                "Keep the locked test unopened until checkpoint selection and full validation pass.",
                "Require zero new forbidden claims and zero new safety-critical omissions.",
                "Include English and French task slices when the route can affect bilingual users.",
                "Require independent agronomist review before any grower-facing promotion.",
            ],
            "comparison_arms": [
                "base without retrieval",
                "base with governed retrieval",
                "adapter without retrieval",
                "adapter with governed retrieval",
            ],
            "stop_rule": (
                "Stop after the first validated iteration unless the routed task improves on "
                "the locked source-disjoint test and the complete system has zero critical "
                "regressions."
            ),
        },
        "evidence": evidence,
        "boundary": (
            "LoRA is technically feasible on this Mac, but another global adaptation is not "
            "scientifically justified by the current evidence. Retrieval, deterministic "
            "policy, field context, and answer lineage remain separate causal components and "
            "must be evaluated separately from parametric adaptation."
        ),
    }


def _validate_evidence(
    *,
    anchor: dict[str, Any],
    training: dict[str, Any],
    rabbit: dict[str, Any],
    policy: dict[str, Any],
    comparison: dict[str, Any],
    e2b_status: dict[str, Any],
    feasibility: dict[str, Any],
) -> None:
    expected_schemas = {
        "anchor": (
            anchor,
            "open_agronomy_agent.anchor_model_candidates.v1",
        ),
        "training": (
            training,
            "open_agronomy_agent.canadian_task_rabbit_training_manifest.v1",
        ),
        "rabbit": (
            rabbit,
            "open_agronomy_agent.gemma3_270m_task_rabbit_lora.v1",
        ),
        "policy": (
            policy,
            "open_agronomy_agent.task_rabbit_promotion_policy.v1",
        ),
        "comparison": (
            comparison,
            "open_agronomy_agent.canadian_semantic_reserve_v2_model_comparison.v1",
        ),
        "e2b_status": (
            e2b_status,
            "open_agronomy_agent.adapter_promotion_status.v1",
        ),
    }
    for label, (payload, schema) in expected_schemas.items():
        if payload.get("schema_version") != schema:
            raise ValueError(f"unsupported {label} evidence schema")
    if training.get("synthetic") is not True:
        raise ValueError("task-rabbit training evidence no longer records synthetic data")
    if training.get("independent_transfer_set_included") is not False:
        raise ValueError("task-rabbit independent-transfer boundary is inconsistent")
    if rabbit.get("runtime_promoted") is not False:
        raise ValueError("task-rabbit manifest unexpectedly records runtime promotion")
    if policy.get("required_maximums", {}).get(
        "rows_with_safety_critical_tool_omission"
    ) != 0:
        raise ValueError("task-rabbit promotion policy no longer requires zero omissions")
    if comparison.get("status") != "complete_pending_independent_agronomist_review":
        raise ValueError("answer-model comparison status is not the reviewed state")
    scientific = comparison.get("scientific_boundary")
    if not isinstance(scientific, dict) or scientific.get(
        "independent_agronomist_signoff"
    ) is not False:
        raise ValueError("answer-model independent-review boundary is inconsistent")
    if e2b_status.get("status") != "research_only_not_for_global_runtime":
        raise ValueError("E2B adapter promotion status is inconsistent")
    if e2b_status.get("full_system_stability", {}).get("status") != "fail":
        raise ValueError("E2B adapter stability evidence does not record failure")
    quality = feasibility.get("quality_signals")
    if (
        not isinstance(quality, dict)
        or quality.get("lora_promotable") is not False
        or not isinstance(quality.get("lora_peak_memory_gb"), (int, float))
    ):
        raise ValueError("E2B feasibility metrics are incomplete")
    candidate_ids = {
        item.get("model_id")
        for item in anchor.get("candidates", [])
        if isinstance(item, dict)
    }
    if rabbit.get("base_model", {}).get("model_id") not in candidate_ids:
        raise ValueError("task-rabbit base model is absent from the candidate registry")


def _validate_compiled_decision(decision: dict[str, Any]) -> None:
    if (
        decision.get("schema_version")
        != "open_agronomy_agent.model_adaptation_readiness.v1"
    ):
        raise ValueError("unsupported compiled model-adaptation decision schema")
    if decision.get("available") is not True:
        raise ValueError("compiled model-adaptation decision is not available")
    if decision.get("status") != "do_not_start_new_global_lora":
        raise ValueError("compiled decision does not reject a new global LoRA")
    if decision.get("global_adapter_promoted") is not False:
        raise ValueError("compiled decision unexpectedly promotes a global adapter")
    if decision.get("new_global_lora_authorized") is not False:
        raise ValueError("compiled decision unexpectedly authorizes a new global LoRA")

    conference = decision.get("conference_answer_model")
    if not isinstance(conference, dict):
        raise ValueError("compiled decision has no conference answer model")
    for field in ("model_id", "revision", "license", "quality_gate"):
        if not conference.get(field):
            raise ValueError(f"compiled conference model is missing {field}")
    selection = conference.get("selection_evidence")
    if (
        not isinstance(selection, dict)
        or selection.get("independent_agronomist_signoff") is not False
        or selection.get("untouched_second_holdout") is not False
    ):
        raise ValueError("compiled model-selection boundary is inconsistent")

    experiments = {
        item.get("id"): item
        for item in decision.get("experiments", [])
        if isinstance(item, dict)
    }
    rabbit = experiments.get("gemma3_270m_task_rabbit_lora_v1")
    if (
        not isinstance(rabbit, dict)
        or rabbit.get("status") != "rejected_for_runtime"
        or rabbit.get("synthetic_training") is not True
        or rabbit.get("independent_transfer_set_included") is not False
        or not isinstance(rabbit.get("safety_critical_omission_rows"), int)
        or rabbit["safety_critical_omission_rows"] <= 0
    ):
        raise ValueError("compiled Gemma 270M decision is inconsistent")
    e2b = experiments.get("gemma4_e2b_agxqa_grounded_lora_v3")
    if (
        not isinstance(e2b, dict)
        or e2b.get("status") != "research_only_not_for_global_runtime"
        or e2b.get("document_disjoint_task_status") != "pass"
        or e2b.get("full_system_status") != "fail"
        or not isinstance(e2b.get("critical_regression_rows"), int)
        or e2b["critical_regression_rows"] <= 0
    ):
        raise ValueError("compiled Gemma E2B adapter decision is inconsistent")

    blocker_ids = {
        item.get("id")
        for item in decision.get("blockers", [])
        if isinstance(item, dict)
    }
    required_blockers = {
        "independent_agronomist_model_review",
        "task_rabbit_independent_transfer",
        "global_adapter_system_stability",
    }
    if not required_blockers.issubset(blocker_ids):
        raise ValueError("compiled decision omits a required model-adaptation blocker")

    next_experiment = decision.get("next_experiment")
    if (
        not isinstance(next_experiment, dict)
        or "non-advisory extraction microtask"
        not in str(next_experiment.get("authorized_scope") or "")
        or "zero critical regressions"
        not in str(next_experiment.get("stop_rule") or "")
    ):
        raise ValueError("compiled next-experiment boundary is incomplete")

    evidence = decision.get("evidence")
    if not isinstance(evidence, dict) or len(evidence) < 10:
        raise ValueError("compiled decision has incomplete source-evidence lineage")
    for label, item in evidence.items():
        if not isinstance(item, dict):
            raise ValueError(f"compiled evidence entry is invalid: {label}")
        path = str(item.get("path") or "")
        digest = str(item.get("sha256") or "")
        if (
            not path
            or path.startswith("/")
            or ".." in Path(path).parts
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError(f"compiled evidence lineage is invalid: {label}")


def _unavailable(
    message: str,
    *,
    boundary: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "open_agronomy_agent.model_adaptation_readiness.v1",
        "available": False,
        "status": "unavailable",
        "global_adapter_promoted": False,
        "new_global_lora_authorized": False,
        "message": message,
        "boundary": boundary
        or (
            "Missing or inconsistent evidence must not be interpreted as permission to "
            "train, promote, or attach an adapter to the grower-facing answer path."
        ),
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"evidence root must be an object: {path}")
    return payload


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(repo_path(".").resolve()))
    except ValueError:
        return f"<external>/{path.name}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
