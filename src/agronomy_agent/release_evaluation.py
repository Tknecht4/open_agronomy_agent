"""Versioned, source-bound plans for the expandable release evaluation suite.

Evaluation gold remains in the controller. Product workers receive questions,
premises and mechanical assertions, never reference answers or semantic rubrics.
This is an engineering release instrument, not agronomic validation.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sqlite3
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from agronomy_agent.benchmark_arms import ALL_ARM_IDS

REGISTRY_SCHEMA = "open_agronomy_agent.release_evaluation_registry.v1"
PLAN_SCHEMA = "open_agronomy_agent.release_evaluation_plan.v1"
REPORT_SCHEMA = "open_agronomy_agent.release_evaluation_report.v1"
SCORER_VERSION = "open_agronomy_agent.release_evaluation_scoring.v1"
SCORER_FILES = (
    "src/agronomy_agent/evals.py",
    "src/agronomy_agent/release_eval_analysis.py",
    "scripts/evaluate_offline_corpus_retrieval.py",
    "src/agronomy_agent/field_data_benchmark.py",
)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "configs/release_evaluation_v1.json"
COMPONENTS = {
    "instrument",
    "capability",
    "retrieval",
    "field_data",
    "product_contracts",
    "performance",
}
CONTROLLER_INPUT_LIMIT = 2 * 1024 * 1024
TASK_FIELD_ALIASES = {"crop_name": "crop", "region_text": "region", "province": "jurisdiction", "field_name": "display_name"}
CONTROLLER_GOLD_KEYS = {"reference_answer", "reference_numeric", "reference_unit", "semantic_rubric", "rubric", "rubrics", "numeric_oracle", "criterion_scores", "model_scoring_policy", "expected_answer"}


def strict_json(raw: bytes | str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite JSON input: " + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def read_controller_inputs(*, rubrics_path: Path | None = None, policy_path: Path | None = None) -> dict[str, Any]:
    """Capture bounded exact controller bytes once; never pass them to workers."""
    result = {}
    for name, path in (("rubrics", rubrics_path), ("policy", policy_path)):
        if path is None:
            continue
        info = Path(path).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > CONTROLLER_INPUT_LIMIT:
            raise ValueError("controller input must be a bounded regular file")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > CONTROLLER_INPUT_LIMIT:
                raise ValueError("controller input must be a bounded regular file")
            raw = handle.read(CONTROLLER_INPUT_LIMIT + 1)
        if len(raw) > CONTROLLER_INPUT_LIMIT:
            raise ValueError("controller input exceeds 2 MiB")
        value = strict_json(raw) if name == "policy" else [strict_json(line) for line in raw.splitlines() if line.strip()]
        if (name == "policy" and not isinstance(value, dict)) or (name == "rubrics" and any(not isinstance(row, dict) for row in value)):
            raise ValueError("controller inputs require object records")
        result[name] = {"path": Path(path), "bytes": raw, "value": value,
                        "sha256": hashlib.sha256(raw).hexdigest()}
    return result


def _no_controller_gold(value: Any) -> None:
    if isinstance(value, Mapping):
        if set(value) & CONTROLLER_GOLD_KEYS:
            raise ValueError("controller gold is forbidden in supplied task facts")
        for item in value.values():
            _no_controller_gold(item)
    elif isinstance(value, list):
        for item in value:
            _no_controller_gold(item)


def task_input_contract(case: Mapping[str, Any]) -> dict[str, Any]:
    """Match exact user input, never a case hash or arm-dependent history."""
    if ("question" in case) == ("turns" in case):
        raise ValueError("task requires exactly one question or turns")
    turns = [case["question"]] if "question" in case else case["turns"]
    if not isinstance(turns, list) or not turns:
        raise ValueError("task turns must be nonempty")
    requests = []
    for turn in turns:
        if isinstance(turn, Mapping):
            if turn.get("role", "user") != "user":
                raise ValueError("shared tasks require user turns")
            turn = turn.get("content")
        if not isinstance(turn, str) or not turn.strip():
            raise ValueError("task requests must be nonempty text")
        requests.append(turn)
    context = case.get("field_context", {})
    if not isinstance(context, dict):
        raise ValueError("task field context must be an object")
    _no_controller_gold(context)
    inline = not context
    decoder = json.JSONDecoder()
    # Scan complete suffix objects through strict_json as well: duplicate keys,
    # typed differences and quoted/stringified examples cannot qualify facts.
    for request in requests:
        for index, char in enumerate(request):
            if char != "{":
                continue
            try:
                permissive, end = decoder.raw_decode(request[index:])
            except (ValueError, json.JSONDecodeError):
                continue
            _no_controller_gold(permissive)
            try:
                parsed = strict_json(request[index:index + end])
            except (ValueError, json.JSONDecodeError):
                continue
            _no_controller_gold(parsed)
            label = request[:index].rsplit("\n", 1)[-1].strip()
            declared = label in {"Supplied facts:", "Supplied facts (canonical JSON):", "Supplied synthetic facts (project-authored, not study observations):"}
            if declared and not request[index + end:].strip() and digest(parsed) == digest(context):
                inline = True
    conflicts = [alias for alias, canonical in TASK_FIELD_ALIASES.items()
                 if alias in context and canonical in context and digest(context[alias]) != digest(context[canonical])]
    matched = len(requests) == 1 and inline and not conflicts
    return {"schema_version": "open_agronomy_agent.shared_task_input.v1", "requests": requests,
            "field_context": context, "request_sha256": digest(requests), "supplied_facts_sha256": digest(context),
            "task_input_sha256": digest({"requests": requests, "field_context": context}) if matched else None,
            "status": "matched_single_request_inline_facts" if matched else "unknown_multiturn_history" if len(requests) != 1 else "unknown_alias_conflict" if conflicts else "unknown_field_only_facts"}


def validate_task_exposure(case: Mapping[str, Any], arm_id: str, exposure: Mapping[str, Any] | None) -> dict[str, Any]:
    """Check recorded source fields, not a worker-supplied matching digest."""
    expected = task_input_contract(case)
    unknown = {"status": "unknown_missing_exposure", "task_input_sha256": None}
    if exposure is None:
        return unknown
    if not isinstance(exposure, Mapping) or exposure.get("schema_version") != "open_agronomy_agent.task_exposure.v1" or exposure.get("arm_id") != arm_id:
        raise ValueError("task exposure arm/schema mismatch")
    if exposure.get("receipt_sha256") != digest({k: v for k, v in exposure.items() if k != "receipt_sha256"}):
        raise ValueError("task exposure receipt hash mismatch")
    if exposure.get("worker_case_sha256") != digest(worker_case(case)):
        raise ValueError("task exposure worker case mismatch")
    inputs = exposure.get("requests")
    if not isinstance(inputs, list) or not inputs:
        return unknown
    if any(not isinstance(item, Mapping) for item in inputs) or len(inputs) > len(expected["requests"]) or [item.get("message") for item in inputs] != expected["requests"][:len(inputs)]:
        raise ValueError("task exposure request mismatch")
    compiled = dict(expected["field_context"])
    applied = {}
    conflicts = []
    for alias, canonical in TASK_FIELD_ALIASES.items():
        if alias not in compiled:
            continue
        if canonical in compiled and digest(compiled[canonical]) != digest(compiled[alias]):
            conflicts.append({"alias": alias, "canonical": canonical, "alias_value": compiled[alias], "canonical_value": compiled[canonical]})
        elif canonical not in compiled:
            compiled[canonical] = compiled[alias]; applied[alias] = canonical
    aliases = {"schema_version": "open_agronomy_agent.release_field_aliases.v1", "aliases_applied": applied,
               "conflicts": conflicts, "input_sha256": digest(expected["field_context"]), "compiled_sha256": digest(compiled)}
    if exposure.get("compiled_field_context_sha256") != digest(compiled) or digest(exposure.get("field_alias_receipt")) != digest(aliases):
        raise ValueError("task exposure compiler/alias pins mismatch")
    for item in inputs:
        if arm_id in {"raw_model", "kernel_only"}:
            prompt = item.get("prompt_messages")
            if not isinstance(prompt, list) or not prompt or prompt[-1] != {"role": "user", "content": item["message"]} or item.get("field_context_delivered") is not None:
                raise ValueError("reference task exposure differs from actual user prompt")
            if len(expected["requests"]) == 1 and len(prompt) != (2 if arm_id == "kernel_only" else 1):
                raise ValueError("reference task has unplanned history")
        elif digest(item.get("field_context_delivered", {})) != digest(compiled):
            raise ValueError("product task exposure context mismatch")
    return ({"status": "unknown_incomplete_exposure", "task_input_sha256": None} if len(inputs) != len(expected["requests"])
            else {"status": expected["status"], "task_input_sha256": expected["task_input_sha256"]})


def bind_controller_inputs(plan: dict[str, Any], inputs: Mapping[str, Any], comparison_cohort: str | None = None) -> dict[str, Any]:
    if not inputs and comparison_cohort is None:
        return plan
    if comparison_cohort is not None and (not isinstance(comparison_cohort, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", comparison_cohort)):
        raise ValueError("explicit comparison cohort must be a stable identifier")
    from agronomy_agent.release_eval_model_metrics import score_model_matrix
    rubrics = inputs.get("rubrics", {}).get("value", [])
    policy = inputs.get("policy", {}).get("value")
    projected = {**plan, "matrix": [{**cell, "model_id": plan["model"]["id"], "model_revision": plan["model"]["revision"], "backend_id": cell["backend"]} for cell in plan["matrix"]]}
    score_model_matrix(projected, [], rubrics=rubrics, policy=policy)
    bound = {**plan, "controller_inputs": {"schema_version": "open_agronomy_agent.controller_inputs.v1",
             "files": {name: {"sha256": item["sha256"], "bytes": len(item["bytes"]), "canonical_sha256": digest(item["value"]), "source_path": str(item["path"].resolve())} for name, item in inputs.items()},
             "rubric_sha256_by_case": {r["case_id"]: r["rubric_sha256"] for r in rubrics}},
             "comparison_cohort": comparison_cohort,
             "shared_task_rule": "single_user_request_exact_suffix_inline_original_facts_v1",
             "model_scoring_policy_sha256": digest(policy) if policy is not None else None}
    bound["matrix"] = []
    for cell in plan["matrix"]:
        case = next(case for case in plan["cases"] if case["case_id"] == cell["case_id"] and case["suite_id"] == cell["suite_id"])
        contract = task_input_contract(case)
        bound["matrix"].append({**cell, "comparison_cohort": comparison_cohort,
                                "task_input_sha256": contract["task_input_sha256"], "task_input_status": contract["status"]})
    return bound


def planned_analysis_condition(plan: Mapping[str, Any], cell: Mapping[str, Any]) -> dict[str, Any]:
    files = plan.get("source", {}).get("files", {})
    names = ("src/agronomy_agent/release_eval_executor.py", "src/agronomy_agent/benchmark_arms.py") + (("src/agronomy_agent/release_evaluation.py",) if "controller_inputs" in plan else ())
    recipe = {name: files.get(name) for name in names}
    runtime = plan.get("effective_runtime_inputs")
    return {"model_config_sha256": plan["model"].get("config_sha256"),
            "source_sha256": plan.get("source", {}).get("source_sha256"),
            "runtime_config_sha256": digest({"sampling": plan["sampling"], "environment": plan["environment"],
                **({"effective_model_sha256": runtime["model_trial_sha256"].get(cell["trial_id"]), "effective_rag_sha256": runtime["rag_sha256"]} if runtime else {})}) if "sampling" in plan and "environment" in plan else None,
            "arm_recipe_sha256": digest({"arm_id": cell["arm_id"], "files": recipe}) if all(recipe.values()) else None}


def validate_worker_runtime(plan: Mapping[str, Any], cell: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    expected = plan.get("effective_runtime_inputs")
    if expected is None:
        return "unknown_unbound_runtime"
    observed = row.get("config_identity") or {}
    if row.get("config_identity") is not None and not isinstance(row["config_identity"], Mapping):
        raise ValueError("worker config identity must be a mapping")
    complete = True
    for role, bound in (("model", expected["model_trial_sha256"][cell["trial_id"]]), ("rag", expected["rag_sha256"])):
        if role in observed and not isinstance(observed[role], Mapping):
            raise ValueError("worker config role must be a mapping")
        value = observed.get(role, {}).get("sha256")
        if value is None:
            complete = False
        elif value != bound:
            raise ValueError("observed worker runtime config differs: " + role)
    return "verified_worker_config_bytes" if complete else "unknown_missing_worker_config"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def checked_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"registry input must be a repository-relative path: {value}")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"missing or escaped registry input: {value}")
    return resolved


def _positive(value: Any, name: str, *, integer: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or (integer and not isinstance(value, int))
    ):
        raise ValueError(
            f"{name} must be a finite positive {'integer' if integer else 'number'}"
        )
    return value


def load_registry(
    path: Path = DEFAULT_REGISTRY, *, root: Path = ROOT
) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if (
        registry.get("schema_version") != REGISTRY_SCHEMA
        or registry.get("claim_eligible") is not False
    ):
        raise ValueError("unsupported registry or claim-bearing release registry")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(registry.get("suite_id") or "")):
        raise ValueError("suite_id must be a stable nonempty identifier")
    for key in ("model_config", "rag_config"):
        checked_path(root, registry[key])
    if set(registry.get("profiles") or {}) != {"ci", "smoke", "baseline", "release"}:
        raise ValueError(
            "registry must declare ci, smoke, baseline and release profiles"
        )
    for name, profile in registry["profiles"].items():
        if profile.get("backend") != ("mock" if name == "ci" else "mlx"):
            raise ValueError("only CI may use the mock default backend")
        _positive(profile.get("trials"), "trials", integer=True)
        _positive(
            profile.get("performance_repeats"), "performance_repeats", integer=True
        )
    if set(registry.get("required_components") or []) != COMPONENTS or len(
        registry["required_components"]
    ) != len(COMPONENTS):
        raise ValueError("all foundational components must be required")
    for name in ("max_tokens", "cell_timeout_seconds", "whole_run_timeout_seconds"):
        _positive(registry.get(name), name, integer=True)
    if isinstance(registry.get("seed"), bool) or not isinstance(
        registry.get("seed"), int
    ):
        raise ValueError("seed must be an integer")
    arms = registry.get("arms")
    if (
        not arms
        or len(arms) != len(set(arms))
        or not set(arms).issubset(ALL_ARM_IDS)
        or "production_full" not in arms
    ):
        raise ValueError("unique supported arms including production_full are required")
    ids = []
    for suite in registry.get("suites") or []:
        ids.append(suite.get("id"))
        checked_path(root, suite["path"])
        if suite.get("format") not in {"scenario", "legacy_domain"} or suite.get(
            "exposure"
        ) not in {"exposed_development", "prospective_confirmation"}:
            raise ValueError("suite format and exposure must be explicit")
        if (
            suite.get("required") is not True
            or not suite.get("profiles")
            or not set(suite["profiles"]).issubset(registry["profiles"])
        ):
            raise ValueError("suite must declare required profile coverage")
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(not isinstance(value, str) or not value for value in ids)
    ):
        raise ValueError("suite IDs must be nonempty and unique")
    tests = registry.get("product_contract_tests")
    if not tests or len(tests) != len(set(tests)):
        raise ValueError("product contract tests must be declared")
    for value in tests:
        checked_path(root, value)
    coverage = registry.get("domain_policy", {}).get("required_review_coverage")
    if (
        isinstance(coverage, bool)
        or not isinstance(coverage, (int, float))
        or not 0 <= coverage <= 1
    ):
        raise ValueError("domain review coverage must be declared in [0,1]")
    policy = registry.get("comparison_policy") or {}
    required = {
        "maximum_new_failed_checks",
        "maximum_numeric_accuracy_regression",
        "maximum_positive_recall_at_7_regression",
        "maximum_introduced_material_errors",
        "maximum_required_completion_regression",
        "maximum_latency_p95_ratio",
        "maximum_peak_memory_ratio",
        "minimum_performance_samples",
    }
    if set(policy) != required:
        raise ValueError(
            "comparison policy must declare every supported regression limit"
        )
    for name, value in policy.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"invalid comparison limit: {name}")
    if (
        policy["minimum_performance_samples"] < 2
        or policy["maximum_latency_p95_ratio"] < 1
        or policy["maximum_peak_memory_ratio"] < 1
    ):
        raise ValueError("invalid performance comparison policy")
    retrieval = registry.get("retrieval_policy") or {}
    if set(retrieval) != {
        "minimum_source_locator_validity_rate",
        "minimum_jurisdiction_authority_compliance_rate",
        "minimum_negative_control_compliance_rate",
    }:
        raise ValueError(
            "retrieval policy must declare all authority and negative-control limits"
        )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
        for value in retrieval.values()
    ):
        raise ValueError("retrieval limits must be finite rates in [0,1]")
    for profile in ("baseline", "release"):
        if registry["profiles"][profile]["trials"] < 2:
            raise ValueError("complete model profiles require repeated trials")
    if registry["profiles"]["baseline"] != registry["profiles"]["release"]:
        raise ValueError("baseline and release must use matched measurement profiles")
    backend_policy = registry.get("backend_performance_policy") or {}
    cells = backend_policy.get("required_warm_cells") or []
    if (
        not cells
        or len(cells) != len(set(cells))
        or any(
            not isinstance(name, str) or not re.fullmatch(r"[a-z_]+_warm", name)
            for name in cells
        )
    ):
        raise ValueError("backend performance must declare unique warm cell contracts")
    _positive(
        backend_policy.get("minimum_samples"), "backend minimum samples", integer=True
    )
    _positive(backend_policy.get("maximum_p95_ratio"), "backend p95 ratio")
    if (
        backend_policy["minimum_samples"] < 2
        or backend_policy["maximum_p95_ratio"] < 1
        or registry["profiles"]["baseline"]["performance_repeats"]
        < backend_policy["minimum_samples"]
    ):
        raise ValueError(
            "backend performance profile must provide its required samples"
        )
    return registry


def normalize_case(row: Mapping[str, Any], suite: Mapping[str, Any]) -> dict[str, Any]:
    case = dict(row)
    if suite["format"] == "legacy_domain":
        case["case_id"] = str(row.get("eval_id") or "")
        case["scenario_family"] = str(
            row.get("scenario_family")
            or f"{row.get('source_suite', suite['id'])}:{row.get('task_family', 'unspecified')}"
        )
        case["family_origin"] = (
            "legacy_metadata_grouping_not_independent_scenario_certification"
        )
        case["lane"] = "agronomy"
        case["assertions"] = {}
        case["review_required"] = row.get("scoring_method") != "numeric_tolerance"
    if (
        not str(case.get("case_id") or "").strip()
        or not str(case.get("scenario_family") or "").strip()
    ):
        raise ValueError("case_id and scenario_family are required")
    if case.get("lane") not in {"agronomy", "harness", "conversation"}:
        raise ValueError("case lane must be agronomy, harness or conversation")
    turns = case.get("turns")
    if turns is not None:
        if (
            not isinstance(turns, list)
            or not turns
            or any(
                not (
                    isinstance(turn, str)
                    and turn.strip()
                    or isinstance(turn, dict)
                    and str(turn.get("content") or "").strip()
                )
                for turn in turns
            )
        ):
            raise ValueError("turns must contain nonempty user requests")
    elif not isinstance(case.get("question"), str) or not case["question"].strip():
        raise ValueError("question or turns is required")
    if (
        not isinstance(case.get("assertions", {}), dict)
        or not isinstance(case.get("field_context", {}), dict)
        or not isinstance(case.get("review_required"), bool)
    ):
        raise ValueError(
            "assertions, field_context and review_required must be explicit typed values"
        )
    case["suite_id"] = suite["id"]
    by_arm = case.get("assertions_by_arm", {})
    if (
        not isinstance(by_arm, dict)
        or not set(by_arm).issubset(ALL_ARM_IDS)
        or any(not isinstance(value, dict) for value in by_arm.values())
    ):
        raise ValueError(
            "assertions_by_arm must map supported arms to assertion objects"
        )
    case["exposure"] = suite["exposure"]
    case["case_sha256"] = digest(row)
    return case


def worker_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist inputs; independent numeric/semantic gold never crosses this seam."""
    keys = {
        "case_id",
        "scenario_family",
        "lane",
        "question",
        "turns",
        "field_context",
        "assertions",
        "assertions_by_arm",
        "synthetic_fault",
        "review_required",
    }
    projected = {key: value for key, value in case.items() if key in keys}
    if "question" in projected or "turns" in projected:
        task_input_contract(projected)
    return projected


def source_identity(root: Path = ROOT) -> dict[str, Any]:
    paths = sorted((root / "src/agronomy_agent").rglob("*.py")) + sorted(
        (root / "scripts").glob("*.py")
    )
    paths += [
        root / name
        for name in (
            "pyproject.toml",
            "requirements-release-evaluation-colab.txt",
            "requirements-phase4-ci.txt",
            "configs/model.yaml",
            "configs/rag.yaml",
            "configs/runtime_profiles.json",
            "configs/risk_conditioned_selective_v3.json",
            "configs/skill_registry.yaml",
            "configs/context_policy_v1.yaml",
            "configs/public_repository_manifest.json",
            "data/manifests/runtime_corpus_policy.json",
        )
    ]
    records = {
        path.relative_to(root).as_posix(): file_digest(path)
        for path in paths
        if path.is_file()
    }
    commit = None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        commit = result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    capsule = root / "EVALUATION_SOURCE.json"
    if commit is None and capsule.is_file():
        declared = json.loads(capsule.read_text())
        if declared.get("source_sha256") != digest(records):
            raise ValueError("transferred source capsule does not match source bytes")
        commit = declared.get("commit")
    return {"commit": commit, "source_sha256": digest(records), "files": records}


def environment_identity() -> dict[str, Any]:
    versions = {}
    for name in (
        "mlx",
        "mlx-lm",
        "agno",
        "numpy",
        "fastapi",
        "pydantic",
        "PyYAML",
        "transformers",
        "huggingface_hub",
        "httpx",
        "httpx2",
        "shapely",
        "pyproj",
        "geopandas",
        "pyogrio",
        "rdflib",
        "cryptography",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    hardware: dict[str, Any] = {
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "logical_cpu_count": os.cpu_count(),
    }
    if platform.system() == "Linux":
        cpuinfo = Path("/proc/cpuinfo")
        hardware["cpu_brand"] = (
            next(
                (
                    line.partition(":")[2].strip()
                    for line in cpuinfo.read_text().splitlines()
                    if line.startswith("model name")
                ),
                None,
            )
            if cpuinfo.is_file()
            else None
        )
        hardware["available_cpu_count"] = (
            len(os.sched_getaffinity(0))
            if hasattr(os, "sched_getaffinity")
            else os.cpu_count()
        )
        hardware["memory_bytes"] = os.sysconf("SC_PAGE_SIZE") * os.sysconf(
            "SC_PHYS_PAGES"
        )
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,driver_version",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            hardware["gpu"] = result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            hardware["gpu"] = None
    elif platform.system() == "Darwin":
        try:
            hardware["cpu_brand"] = (
                subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout.strip()
                or None
            )
        except (OSError, subprocess.TimeoutExpired):
            hardware["cpu_brand"] = None
    identity = {
        "python": platform.python_version(),
        "packages": versions,
        "hardware": hardware,
        "sqlite_version": sqlite3.sqlite_version,
    }
    identity["performance_environment_sha256"] = digest(identity)
    return identity


def controlled_inputs(registry: Mapping[str, Any], root: Path = ROOT) -> dict[str, str]:
    """Bind actual runtime evidence and fixtures, including lazy corpus payloads."""
    names = {
        # The answer path reads this registry for provincial coverage, even
        # when public adapters are disabled and retrieval itself is governed.
        "data/manifests/canada_agronomy_sources.json",
        "data/eval/offline_corpus_retrieval.jsonl",
        "data/manifests/offline_corpus_retrieval_suite.json",
        "data/eval/field_data_pilot_v1/manifest.json",
        "data/eval/field_data_pilot_v1/gold_cases.jsonl",
        "configs/benchmark_capability_conformance_v2.json",
        *registry["product_contract_tests"],
    }
    # An absent optional admission queue remains absent. Adding one changes
    # this input map and is therefore detected by resume and source-drift gates.
    admission_queue = (
        "data/manifests/provincial_applied_guidance_admission_queue_20260724.json"
    )
    if (root / admission_queue).is_file():
        names.add(admission_queue)
    names.update(suite["path"] for suite in registry["suites"])
    pilot = json.loads(
        checked_path(root, "data/eval/field_data_pilot_v1/manifest.json").read_text()
    )
    names.update(
        "data/eval/field_data_pilot_v1/" + row["fixture_path"]
        for row in pilot["bundles"]
    )
    rag = yaml.safe_load(checked_path(root, registry["rag_config"]).read_text())
    retrieval = rag["retrieval"]
    names.add(retrieval["corpus_policy_manifest"])
    policy = json.loads(
        checked_path(root, retrieval["corpus_policy_manifest"]).read_text()
    )
    names.update(row["path"] for row in policy["corpora"])
    names.update(retrieval.get("corpus_paths") or [])
    for graph in retrieval.get("graph_paths") or []:
        names.add(graph)
        names.add(str(Path(graph).with_suffix(".manifest.json")))
    names.update(
        row["manifest_path"] for row in retrieval.get("on_demand_corpus_releases") or []
    )
    names.update(
        value
        for key, value in (rag.get("release_profile") or {}).items()
        if key.endswith("store")
    )
    # Store manifests govern indexes and corpus policy. Bind every regular file
    # in their store, rather than trusting an unchanged pointer to changed data.
    for name in list(names):
        if name.endswith("store_manifest.json"):
            names.update(
                path.relative_to(root).as_posix()
                for path in checked_path(root, name).parent.rglob("*")
                if path.is_file()
            )
    return {name: file_digest(checked_path(root, name)) for name in sorted(names)}


def build_plan(
    registry: Mapping[str, Any],
    *,
    profile: str,
    root: Path = ROOT,
    limit: int | None = None,
    run_id: str = "evaluation",
    controller_inputs: Mapping[str, Any] | None = None,
    comparison_cohort: str | None = None,
) -> dict[str, Any]:
    if profile not in registry["profiles"] or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,100}", run_id
    ):
        raise ValueError("invalid profile or run_id")
    if limit is not None and (
        profile != "smoke" or isinstance(limit, bool) or limit < 1
    ):
        raise ValueError("case limits are allowed only for claim-ineligible smoke runs")
    suites, cases = [], []
    for suite in registry["suites"]:
        if profile not in suite["profiles"]:
            continue
        path = checked_path(root, suite["path"])
        rows = [
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        ]
        normalized = [normalize_case(row, suite) for row in rows]
        if not normalized or len({case["case_id"] for case in normalized}) != len(
            normalized
        ):
            raise ValueError(f"empty suite or duplicate case IDs: {suite['id']}")
        selected = normalized[:limit] if limit else normalized
        cases.extend(selected)
        suites.append(
            {
                **suite,
                "sha256": file_digest(path),
                "total_cases": len(rows),
                "selected_cases": len(selected),
            }
        )
    model_bytes = checked_path(root, registry["model_config"]).read_bytes()
    model = yaml.safe_load(model_bytes)
    if not str(model.get("model_revision") or "").strip():
        raise ValueError("revision-pinned model required")
    profile_config = registry["profiles"][profile]
    matrix = []
    for trial in range(1, profile_config["trials"] + 1):
        for case in cases:
            for arm in registry["arms"]:
                backend = (
                    "mock" if case.get("synthetic_fault") else profile_config["backend"]
                )
                identity = {
                    "suite_id": case["suite_id"],
                    "case_id": case["case_id"],
                    "case_sha256": case["case_sha256"],
                    "arm_id": arm,
                    "trial_id": f"trial-{trial:03d}",
                    "backend": backend,
                }
                matrix.append(
                    {
                        **identity,
                        "observation_id": digest(identity),
                        "scenario_family": case["scenario_family"],
                        "lane": case["lane"],
                    }
                )
    cohort = {
        "suites": suites,
        "cases": [
            {
                key: case[key]
                for key in (
                    "suite_id",
                    "case_id",
                    "case_sha256",
                    "scenario_family",
                    "lane",
                )
            }
            for case in cases
        ],
        "arms": registry["arms"],
        "trials": profile_config["trials"],
    }
    auxiliary_inputs = controlled_inputs(registry, root)
    plan = {
        "schema_version": PLAN_SCHEMA,
        "suite_id": registry["suite_id"],
        "run_id": run_id,
        "profile": profile,
        "claim_eligible": False,
        "registry_sha256": digest(registry),
        "cohort_sha256": digest(cohort),
        "scorer_version": SCORER_VERSION,
        "scorer_sha256": digest(
            {name: file_digest(checked_path(root, name)) for name in SCORER_FILES}
        ),
        "source": source_identity(root),
        "model": {
            "id": model.get("model_id"),
            "revision": model["model_revision"],
            "config_sha256": hashlib.sha256(model_bytes).hexdigest(),
        },
        "rag_config_sha256": file_digest(checked_path(root, registry["rag_config"])),
        "auxiliary_inputs": auxiliary_inputs,
        "required_components": registry["required_components"],
        "sampling": {
            "seed": registry["seed"],
            "trials": profile_config["trials"],
            "max_tokens": registry["max_tokens"],
            "prompt_cache_policy": "disabled",
            "retrieval_cache_policy": "shared_source_bound_compiled_index",
            "kernel_cache_policy": "runtime_managed",
            "environment_policy": "discard_inherited_agronomy_overrides_native_mlx_offline",
            "process_policy": "fresh_process_per_scenario",
            "case_order_policy": "seeded_trial_shuffle",
        },
        "suites": suites,
        "cases": cases,
        "matrix": matrix,
        "counts": {
            "cases": len(cases),
            "observations": len(matrix),
            "families": len({case["scenario_family"] for case in cases}),
            "lanes": dict(Counter(case["lane"] for case in cases)),
        },
        "comparison_policy": registry["comparison_policy"],
        "backend_performance_policy": registry["backend_performance_policy"],
        "domain_policy": registry["domain_policy"],
    }
    return bind_controller_inputs(plan, controller_inputs or {}, comparison_cohort)


def plan_identity(plan: Mapping[str, Any]) -> str:
    return digest(plan)


def read_stop_policy(path: Path | None) -> dict[str, Any] | None:
    """An opt-in collection contract, never model or domain qualification."""
    if path is None:
        return None
    item = read_controller_inputs(policy_path=path)["policy"]
    policy = item["value"]
    keys = {"schema_version", "finalization_reserve_seconds", "retention_budget_bytes",
            "finalization_reserve_bytes", "minimum_free_bytes", "file_hardcap_bytes",
            "require_model_identity", "require_termination"}
    if set(policy) != keys or policy["schema_version"] != "open_agronomy_agent.bounded_stop_policy.v1":
        raise ValueError("unsupported bounded stop policy")
    reserve = policy["finalization_reserve_seconds"]
    if type(reserve) not in (int, float) or not math.isfinite(reserve) or reserve <= 10:
        raise ValueError("finalization reserve must exceed ten-second process cleanup bound")
    for key in ("retention_budget_bytes", "finalization_reserve_bytes", "minimum_free_bytes", "file_hardcap_bytes"):
        if type(policy[key]) is not int or policy[key] <= 0:
            raise ValueError("stop policy byte amounts must be positive integers")
    if policy["finalization_reserve_bytes"] + policy["file_hardcap_bytes"] >= policy["retention_budget_bytes"]:
        raise ValueError("retention budget must leave dispatch and finalization headroom")
    if any(type(policy[key]) is not bool for key in ("require_model_identity", "require_termination")):
        raise ValueError("stop policy requirements must be explicit booleans")
    return {"path": str(item["path"]), "bytes": item["bytes"], "policy": policy,
            "sha256": item["sha256"]}


def bind_stop_policy(plan: dict[str, Any], item: Mapping[str, Any] | None,
                     whole_run_seconds: float) -> dict[str, Any]:
    if item is None:
        return plan
    if item["policy"]["finalization_reserve_seconds"] >= whole_run_seconds:
        raise ValueError("finalization reserve consumes whole run budget")
    return {**plan, "bounded_stop_policy": {"schema_version": "open_agronomy_agent.stop_policy_binding.v1",
            "sha256": item["sha256"], "bytes": len(item["bytes"]),
            "source_path": item["path"], "policy": item["policy"]}}


def write_new_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(
            value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def evaluation_entrypoints(*, root: Path = ROOT) -> dict[str, Any]:
    """Describe executable seams without treating artifact presence as proof.

    This is an explicit maintained catalog, not a dead-code detector. Contract
    tests are named as consumers; this read-only inventory never runs them or
    loads an inference backend. Historical/protocol surfaces keep their own
    constructs rather than being renamed as product competence measurements.
    """
    specs = (
        ("release_suite", "implemented_wired", "product_and_reference_arms",
         "scripts/run_release_evaluation.py", "src/agronomy_agent/release_eval_runner.py",
         "tests/test_release_eval_runner.py",
         "Model execution needs an authorized profile and provisioned backend; CI is synthetic engineering evidence."),
        ("release_analysis", "implemented_wired", "offline_retained_release",
         "scripts/analyze_release_evaluation.py", "src/agronomy_agent/release_eval_reanalysis.py",
         "tests/test_release_eval_reanalysis.py",
         "Verifies retained identity and recomputes analysis without inference; unknown review labels stay unknown."),
        ("historical_four_arm", "preserved_historical_only", "agent_generate_answer",
         "scripts/run_open_agronomy_benchmark.py", "src/agronomy_agent/benchmark_report.py",
         "tests/test_benchmark_report.py",
         "Opt-in exposed historical regression construct; not the persisted product topology or independent agronomic validation."),
        ("benchmark_v2", "implemented_contract_qa_only", "deterministic_contract_qa",
         "scripts/run_open_agronomy_benchmark_v2.py", "src/agronomy_agent/benchmark_v2_runner.py",
         "tests/test_open_agronomy_benchmark_v2_runner.py",
         "Only the deterministic executor is configured; a production adapter for the declared causal arms is not wired."),
        ("competence_v3", "implemented_orchestration_proposal_execution", "explicit_executor_binding_required",
         "scripts/run_v3_competence_candidate.py", "src/agronomy_agent/v3_candidate_runner.py",
         "tests/test_v3_candidate_runner.py",
         "Matrix/ledger orchestration is implemented; no canonical real product adapter or sealed holdout is implied."),
        ("question_inventory", "implemented_metadata_inventory", "question_provenance_only",
         "scripts/inventory_agronomy_evaluation_suites.py", "src/agronomy_agent/evaluation_validity.py",
         "tests/test_evaluation_suite_inventory.py",
         "Question counts and origins do not establish executor wiring, expert gold, independent holdouts or grower usefulness."),
    )
    surfaces = []
    for identifier, classification, execution, entrypoint, module, test, boundary in specs:
        paths = (entrypoint, module, test)
        missing = [path for path in paths if not (root / path).is_file()]
        surfaces.append({
            "id": identifier,
            "classification": "blocked_missing_declared_input" if missing else classification,
            "execution_contract": execution,
            "entrypoint": entrypoint,
            "owning_module": module,
            "declared_contract_test": test,
            "source_files": {path: file_digest(root / path) for path in paths if path not in missing},
            "missing_paths": missing,
            "tests_executed_by_inventory": False,
            "model_evidence_established": False,
            "boundary": boundary,
        })
    return {
        "schema_version": "open_agronomy_agent.evaluation_entrypoints.v1",
        "canonical_run": "scripts/run_release_evaluation.py",
        "canonical_analysis": "scripts/analyze_release_evaluation.py",
        "catalog_implementation_sha256": file_digest(Path(__file__)),
        "inference_executed": False,
        "classification_basis": "Declared code/CLI/test consumers and source hashes; no automatic dead-code or scientific-validation inference.",
        "surfaces": surfaces,
    }


__all__ = [
    "ROOT",
    "DEFAULT_REGISTRY",
    "REPORT_SCHEMA",
    "digest",
    "file_digest",
    "load_registry",
    "normalize_case",
    "worker_case",
    "source_identity",
    "environment_identity",
    "build_plan",
    "plan_identity",
    "write_new_json",
    "evaluation_entrypoints",
]
