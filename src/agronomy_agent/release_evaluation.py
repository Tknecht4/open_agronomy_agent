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
    return {key: value for key, value in case.items() if key in keys}


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
    model = yaml.safe_load(checked_path(root, registry["model_config"]).read_text())
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
    return {
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
            "config_sha256": file_digest(checked_path(root, registry["model_config"])),
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


def plan_identity(plan: Mapping[str, Any]) -> str:
    return digest(plan)


def write_new_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(
            value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
        handle.write("\n")


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
]
