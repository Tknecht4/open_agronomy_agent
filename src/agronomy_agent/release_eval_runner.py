"""Bounded release-suite execution with immutable inputs and append-only cells."""

from __future__ import annotations

import fcntl
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import yaml

from agronomy_agent.release_evaluation import (
    ROOT,
    build_plan,
    controlled_inputs,
    digest,
    environment_identity,
    file_digest,
    load_registry,
    plan_identity,
    source_identity,
    worker_case,
    write_new_json,
)
from agronomy_agent.release_eval_analysis import compare, public_projection, summarize


def _instrument_controls() -> dict[str, Any]:
    from agronomy_agent.evals import (
        score_item,
        score_item_numeric,
        score_item_agribench_proxy,
    )

    case = {
        "reference_numeric": 120.0,
        "reference_unit": "L/ha",
        "unit_aliases": ["L ha-1"],
        "absolute_tolerance": 0.1,
    }
    checks = []
    for text, expected in (
        ("120 L/ha", 100.0),
        ("120 lb/ac", 0.0),
        ("120", 0.0),
        ("Do not use 120 L/ha.", 0.0),
        ("Use 120 L/ha and 240 L/ha.", 0.0),
    ):
        score = score_item_numeric(text, case)
        checks.append(
            {
                "id": f"numeric_control_{len(checks)}",
                "passed": score["score"] == expected,
                "detail": {"expected": expected, "observed": score["score"]},
            }
        )
    empty = {"required_patterns": [], "forbidden_patterns": [], "ask_for_patterns": []}
    for scorer in (score_item, score_item_agribench_proxy):
        result = scorer("", empty)
        checks.append(
            {
                "id": f"empty_contract_{scorer.__name__}",
                "passed": result.get("score") is None
                and result.get("proxy_valid") is False,
            }
        )
    return {
        "component": "instrument",
        "status": "pass" if all(row["passed"] for row in checks) else "blocked",
        "checks": checks,
        "metrics": {
            "controls": len(checks),
            "failed": sum(not row["passed"] for row in checks),
        },
    }


def _command(
    argv: list[str],
    *,
    cwd: Path,
    output: Path,
    timeout: float,
    new_session: bool = True,
) -> tuple[int, str]:
    """Kill the complete owned process group on timeout, preserving its log."""
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AGRONOMY_AGENT_")
    }
    environment["AGRONOMY_AGENT_RUNTIME_ROOT"] = str(cwd)
    environment["AGRONOMY_AGENT_MODEL_BACKEND"] = "mlx"
    environment["AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"] = "disabled"
    environment["HF_HUB_OFFLINE"] = "1"
    environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
    environment.pop("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", None)
    environment["PYTHONPATH"] = str(cwd / "src") + os.pathsep + str(cwd)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    with output.open("x", encoding="utf-8") as handle:
        child = subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=new_session,
        )
        try:
            return child.wait(timeout=timeout), "completed"
        except subprocess.TimeoutExpired:
            try:
                (
                    os.killpg(child.pid, signal.SIGTERM)
                    if new_session
                    else child.terminate()
                )
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    (
                        os.killpg(child.pid, signal.SIGKILL)
                        if new_session
                        else child.kill()
                    )
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
            return 124, "timeout"


def execute_worker(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Worker entry; product outputs retain all turns and local traces privately."""
    kind = spec["kind"]
    directory = Path(spec["directory"])
    if kind == "product":
        from agronomy_agent.release_eval_executor import execute_product_case

        return execute_product_case(
            spec["case"],
            model_config=Path(spec["model_config"]),
            rag_config=Path(spec["rag_config"]),
            arm_id=spec["cell"]["arm_id"],
            backend=spec["cell"]["backend"],
            max_tokens=spec["max_tokens"],
            output_dir=directory / "product",
            trial_id=spec["cell"]["trial_id"],
        )
    if kind == "instrument":
        return _instrument_controls()
    if kind == "capability":
        from scripts.run_benchmark_capability_conformance import run_conformance

        result = run_conformance(
            ROOT / "configs/benchmark_capability_conformance_v2.json"
        )
        write_new_json(directory / "capability.json", result)
        return {
            "component": kind,
            "status": result["status"],
            "metrics": {
                "capabilities": len(result["capabilities"]),
                "operations": sum(
                    row["declared_operation_count"] for row in result["capabilities"]
                ),
                "failures": len(result["failures"]),
            },
        }
    if kind == "retrieval":
        from scripts.evaluate_offline_corpus_retrieval import evaluate

        minimum = {
            key.removeprefix("minimum_"): value
            for key, value in spec["registry"]["retrieval_policy"].items()
        }
        result = evaluate(
            config_path=Path(spec["rag_config"]),
            case_path=ROOT / "data/eval/offline_corpus_retrieval.jsonl",
            suite_path=ROOT / "data/manifests/offline_corpus_retrieval_suite.json",
            threshold_policy={"minimum_rates": minimum},
        )
        write_new_json(directory / "retrieval.json", result)
        status, _ = _command(
            [sys.executable, str(ROOT / "scripts/audit_runtime_corpus.py")],
            cwd=ROOT,
            output=directory / "corpus-audit.log",
            timeout=spec["timeout"],
            new_session=False,
        )
        metrics = {
            "positive_cases": result["positive_case_count"],
            "negative_cases": result["negative_case_count"],
            "blocked_cases": result["blocked_case_count"],
            "failed_cases": result["failed_case_count"],
            "positive_recall_at_7": result["summary"]["recall_at_7"]["mean"],
            "positive_ndcg_at_7": result["summary"]["ndcg_at_7"]["mean"],
            "negative_control_compliance": result["summary"][
                "negative_control_compliance_rate"
            ]["mean"],
            "source_locator_validity": result["summary"][
                "source_locator_validity_rate"
            ]["mean"],
            "authority_compliance": result["summary"][
                "jurisdiction_authority_compliance_rate"
            ]["mean"],
        }
        return {
            "component": kind,
            "status": (
                "pass"
                if result["evaluation_gate"]["passed"] and status == 0
                else "blocked"
            ),
            "metrics": metrics,
            "checks": [
                {"id": "runtime_corpus_audit", "passed": status == 0},
                {
                    "id": "retrieval_gate",
                    "passed": result["evaluation_gate"]["passed"],
                    "detail": result["evaluation_gate"],
                },
            ],
        }
    if kind == "field_data":
        from agronomy_agent.field_data_benchmark import run_pilot

        result = run_pilot(
            ROOT / "data/eval/field_data_pilot_v1", directory / "field-data"
        )
        return {
            "component": kind,
            "status": (
                "pass"
                if result["failed_case_count"] == 0 and result["runtime_code_stable"]
                else "blocked"
            ),
            "metrics": {
                "cases": result["case_count"],
                "failed": result["failed_case_count"],
                "product_mode": result["product_mode"],
                "dependent_bundle_counts": result["source_group_bundle_counts"],
            },
        }
    if kind == "product_contracts":
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            *spec["registry"]["product_contract_tests"],
        ]
        status, disposition = _command(
            command,
            cwd=ROOT,
            output=directory / "contracts.log",
            timeout=spec["timeout"],
            new_session=False,
        )
        return {
            "component": kind,
            "status": "pass" if status == 0 else "blocked",
            "metrics": {
                "test_files": len(spec["registry"]["product_contract_tests"]),
                "exit_code": status,
                "disposition": disposition,
            },
        }
    if kind == "performance":
        command = [
            sys.executable,
            str(ROOT / "scripts/profile_workspace_backend.py"),
            "--output-dir",
            str(directory / "backend-profile"),
            "--warm-repeats",
            str(spec["registry"]["profiles"][spec["profile"]]["performance_repeats"]),
        ]
        status, disposition = _command(
            command,
            cwd=ROOT,
            output=directory / "performance.log",
            timeout=spec["timeout"],
            new_session=False,
        )
        receipt = directory / "backend-profile/receipt.json"
        result = json.loads(receipt.read_text()) if receipt.is_file() else {}
        cells = result.get("cells") or {}
        return {
            "component": kind,
            "status": (
                "pass"
                if status == 0 and result.get("status") == "completed"
                else "blocked"
            ),
            "metrics": {
                "boundary": "synthetic_mock_backend_and_storage_only",
                "exit_code": status,
                "disposition": disposition,
                "repeats": spec["registry"]["profiles"][spec["profile"]][
                    "performance_repeats"
                ],
                "cells": {
                    name: {
                        key: value
                        for key, value in cell.items()
                        if key in {"status", "timing", "requested_samples"}
                    }
                    for name, cell in cells.items()
                },
            },
        }
    raise ValueError(f"unknown release component: {kind}")


def _subprocess_cell(spec: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    directory = Path(spec["directory"])
    if directory.exists():
        # No automatic rerun after an interrupted child: that would select an
        # eventual successful sample and erase the original attempt.
        return {
            "status": "failed",
            "error_type": "InterruptedAttempt",
            "checks": [
                {
                    "id": "fresh_cell_directory",
                    "passed": False,
                    "detail": "interrupted cell artifacts retained; start a successor run to retry",
                }
            ],
        }
    directory.mkdir(parents=True)
    write_new_json(directory / "spec.json", spec)
    result_path = directory / "worker-result.json"
    status, disposition = _command(
        [
            sys.executable,
            str(ROOT / "scripts/run_release_evaluation.py"),
            "--worker-spec",
            str(directory / "spec.json"),
            "--worker-output",
            str(result_path),
        ],
        cwd=ROOT,
        output=directory / "execution.log",
        timeout=timeout,
    )
    result = (
        json.loads(result_path.read_text())
        if result_path.is_file()
        else {"status": "failed", "checks": []}
    )
    if status != 0:
        result["status"] = "failed"
        result.setdefault("checks", []).append(
            {
                "id": "child_completion",
                "passed": False,
                "detail": {"exit_code": status, "disposition": disposition},
            }
        )
    result["worker_exit_code"] = status
    return result


def _append(path: Path, record: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
            + "\n"
        )
        handle.flush()
        os.fsync(handle.fileno())


def _ledger(path: Path, *, plan_sha256: str) -> list[dict[str, Any]]:
    rows = (
        [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if path.is_file()
        else []
    )
    keys = []
    for row in rows:
        if row.get("plan_sha256") != plan_sha256 or row.get("record_sha256") != digest(
            {key: value for key, value in row.items() if key != "record_sha256"}
        ):
            raise ValueError("ledger source binding or record hash mismatch")
        for name, binding in (row.get("retained_artifacts") or {}).items():
            target = (path.parent / name).resolve()
            if (
                not target.is_relative_to(path.parent.resolve())
                or not target.is_file()
                or target.is_symlink()
                or file_digest(target) != binding["sha256"]
                or target.stat().st_size != binding["bytes"]
            ):
                raise ValueError("ledger retained artifact hash mismatch")
        keys.append(row.get("observation_id") or row.get("component"))
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate ledger identities")
    return rows


def _seal_record(record: dict[str, Any], plan_sha256: str) -> dict[str, Any]:
    record["plan_sha256"] = plan_sha256
    record["record_sha256"] = digest(record)
    return record


def retention_manifest(directory: Path) -> dict[str, Any]:
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("retained evaluation outputs must not contain symlinks")
        if path.is_file() and path.relative_to(directory).as_posix() not in {
            ".run.lock",
            "retention.json",
        }:
            files[path.relative_to(directory).as_posix()] = {
                "sha256": file_digest(path),
                "bytes": path.stat().st_size,
            }
        elif not path.is_dir() and not path.is_file():
            raise ValueError("retained evaluation output is not a regular file")
    return {
        "schema_version": "open_agronomy_agent.release_evaluation_retention.v1",
        "files": files,
        "files_sha256": digest(files),
        "total_bytes": sum(record["bytes"] for record in files.values()),
    }


def verify_retention(directory: Path) -> None:
    expected = json.loads((directory / "retention.json").read_text())
    if expected != retention_manifest(directory):
        raise ValueError("completed-run retained evidence hash mismatch")


def load_retained_report(path: Path) -> dict[str, Any]:
    """References are complete retained runs, not unattested aggregate JSON."""
    path = path.resolve()
    directory = path if path.is_dir() else path.parent
    report_path = directory / "report.json"
    if not path.is_dir() and path != report_path:
        raise ValueError("reference must be a retained run or its report.json")
    verify_retention(directory)
    report = json.loads(report_path.read_text())
    plan = json.loads((directory / "plan.json").read_text())
    if report.get("plan_sha256") != plan_identity(plan):
        raise ValueError("reference plan/report binding differs")
    _ledger(directory / "observations.jsonl", plan_sha256=plan_identity(plan))
    _ledger(directory / "components.jsonl", plan_sha256=plan_identity(plan))
    return report


def _bind_artifacts(result: dict[str, Any], directory: Path, output_dir: Path) -> None:
    if directory.exists():
        retained = retention_manifest(directory)["files"]
        prefix = directory.relative_to(output_dir).as_posix()
        result["retained_artifacts"] = {
            prefix + "/" + name: value for name, value in retained.items()
        }


def _effective_yaml(path: Path, value: Mapping[str, Any]) -> None:
    expected = yaml.safe_dump(dict(value), sort_keys=True)
    if path.exists():
        if path.is_symlink() or path.read_text() != expected:
            raise ValueError("effective runtime config differs from frozen plan")
    else:
        with path.open("x") as handle:
            handle.write(expected)


def run_suite(
    *,
    registry_path: Path,
    profile: str,
    output_dir: Path,
    run_id: str,
    resume: bool = False,
    limit: int | None = None,
    reference_path: Path | None = None,
    reviews_path: Path | None = None,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    if profile == "release" and reference_path is None:
        raise ValueError("release profile requires a retained full reference report")
    if reference_path is not None and profile not in {"baseline", "release"}:
        raise ValueError("reference comparison requires a complete model profile")
    reference = load_retained_report(reference_path) if reference_path else None
    plan = build_plan(registry, profile=profile, run_id=run_id, limit=limit)
    plan["environment"] = environment_identity()
    plan["reference_sha256"] = digest(reference) if reference else None
    plan["reviews_sha256"] = file_digest(reviews_path) if reviews_path else None
    plan_sha256 = plan_identity(plan)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not resume:
        raise ValueError(
            "output directory must be new; use exact-identity resume or a successor run"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another owner holds this evaluation run") from exc
        saved_plan = output_dir / "plan.json"
        if saved_plan.is_file():
            if not resume or json.loads(saved_plan.read_text()) != plan:
                raise ValueError("resume identity differs from frozen plan")
        else:
            if resume and any(
                path.name != ".run.lock" for path in output_dir.iterdir()
            ):
                raise ValueError(
                    "cannot resume a directory without a valid frozen plan"
                )
            write_new_json(saved_plan, plan)
        if (output_dir / "report.json").is_file():
            verify_retention(output_dir)
            return json.loads((output_dir / "report.json").read_text())
        effective = output_dir / "effective"
        effective.mkdir(exist_ok=True)
        rag = yaml.safe_load((ROOT / registry["rag_config"]).read_text())
        rag["private_knowledge"] = {"enabled": False, "required": False}
        public_rag = effective / "public-rag.yaml"
        _effective_yaml(public_rag, rag)
        for trial in range(1, registry["profiles"][profile]["trials"] + 1):
            path = effective / f"model-trial-{trial:03d}.yaml"
            model = yaml.safe_load((ROOT / registry["model_config"]).read_text())
            model["seed"] = registry["seed"] + trial - 1
            model["prompt_cache_enabled"] = False
            _effective_yaml(path, model)
        clock_path = output_dir / "run-clock.json"
        if not clock_path.exists():
            write_new_json(
                clock_path,
                {"started_unix_seconds": time.time(), "plan_sha256": plan_sha256},
            )
        clock = json.loads(clock_path.read_text())
        if clock.get("plan_sha256") != plan_sha256:
            raise ValueError("run deadline source binding differs")
        remaining_budget = registry["whole_run_timeout_seconds"] - max(
            0, time.time() - clock["started_unix_seconds"]
        )
        deadline = time.monotonic() + max(0, remaining_budget)
        components_path, observations_path = (
            output_dir / "components.jsonl",
            output_dir / "observations.jsonl",
        )
        components = _ledger(components_path, plan_sha256=plan_sha256)
        completed_components = {row["component"] for row in components}
        for kind in registry["required_components"]:
            if kind in completed_components:
                continue
            remaining = deadline - time.monotonic()
            timeout = min(registry["cell_timeout_seconds"], max(0.01, remaining))
            spec = {
                "kind": kind,
                "directory": str(output_dir / "components" / kind),
                "registry": registry,
                "profile": profile,
                "rag_config": str(public_rag),
                "timeout": timeout,
            }
            result = (
                _subprocess_cell(spec, timeout=timeout)
                if remaining > 0
                else {"status": "failed", "error_type": "WholeRunDeadline"}
            )
            result["component"] = kind
            if result.get("status") == "failed":
                result["status"] = "blocked"
            _bind_artifacts(result, Path(spec["directory"]), output_dir)
            result["receipt_sha256"] = digest(result)
            record = _seal_record(result, plan_sha256)
            _append(components_path, record)
            components.append(record)
            print(
                json.dumps({"component": kind, "status": result["status"]}), flush=True
            )
        rows = _ledger(observations_path, plan_sha256=plan_sha256)
        done = {row["observation_id"] for row in rows}
        cases = {(case["suite_id"], case["case_id"]): case for case in plan["cases"]}
        matrix = list(plan["matrix"])
        for trial_id in sorted({cell["trial_id"] for cell in matrix}):
            ordered = [cell for cell in matrix if cell["trial_id"] == trial_id]
            random.Random(
                registry["seed"] + int(trial_id.removeprefix("trial-"))
            ).shuffle(ordered)
            for cell in ordered:
                if cell["observation_id"] in done:
                    continue
                case = cases[(cell["suite_id"], cell["case_id"])]
                remaining = deadline - time.monotonic()
                spec = {
                    "kind": "product",
                    "directory": str(output_dir / "cells" / cell["observation_id"]),
                    "cell": cell,
                    "case": worker_case(case),
                    "model_config": str(effective / f"model-{trial_id}.yaml"),
                    "rag_config": str(public_rag),
                    "max_tokens": registry["max_tokens"],
                }
                result = (
                    _subprocess_cell(
                        spec,
                        timeout=min(
                            registry["cell_timeout_seconds"], max(0.01, remaining)
                        ),
                    )
                    if remaining > 0
                    else {
                        "status": "failed",
                        "error_type": "WholeRunDeadline",
                        "checks": [
                            {"id": "within_whole_run_deadline", "passed": False}
                        ],
                    }
                )
                result.update(cell)
                result["review_required"] = case["review_required"]
                turns = result.get("turns") or []
                answer = str(turns[-1].get("answer") or "") if turns else ""
                result["answer_sha256"] = digest(answer) if turns else None
                if (
                    case.get("scoring_method") == "numeric_tolerance"
                    or (case.get("scoring") or {}).get("method") == "numeric_tolerance"
                ):
                    from agronomy_agent.evals import score_item_numeric

                    result["independent_score"] = score_item_numeric(
                        answer, case if case.get("scoring_method") else case["scoring"]
                    )
                    # A numeric task scores a failed completion as an observed
                    # zero rather than disappearing from the denominator.
                    if cell["arm_id"] == "production_full":
                        result.setdefault("checks", []).append(
                            {
                                "id": "independent_numeric_contract",
                                "passed": result["independent_score"]["score"] == 100.0,
                                "detail": result["independent_score"],
                            }
                        )
                elif (
                    case.get("required_patterns")
                    or case.get("forbidden_patterns")
                    or case.get("ask_for_patterns")
                ):
                    from agronomy_agent.evals import score_item_agribench_proxy

                    result["lexical_diagnostic"] = score_item_agribench_proxy(
                        answer, case
                    )
                _bind_artifacts(result, Path(spec["directory"]), output_dir)
                record = _seal_record(result, plan_sha256)
                _append(observations_path, record)
                rows.append(record)
                print(
                    json.dumps(
                        {
                            "observed": len(rows),
                            "planned": len(matrix),
                            "case_id": cell["case_id"],
                            "trial_id": trial_id,
                            "status": result["status"],
                        }
                    ),
                    flush=True,
                )
        reviews = (
            [
                json.loads(line)
                for line in reviews_path.read_text().splitlines()
                if line.strip()
            ]
            if reviews_path
            else []
        )
        report = summarize(
            plan, rows, components, environment=plan["environment"], reviews=reviews
        )
        report["plan_sha256"] = plan_sha256
        report["source_stable"] = (
            source_identity()["source_sha256"] == plan["source"]["source_sha256"]
            and controlled_inputs(registry) == plan["auxiliary_inputs"]
            and digest(load_registry(registry_path)) == plan["registry_sha256"]
        )
        if not report["source_stable"]:
            report["status"] = "blocked"
            report["failures"]["source_drift"] = True
        if profile == "smoke":
            report["status"] = (
                "smoke_complete"
                if report["status"] == "engineering_pass"
                else "blocked"
            )
        if reference is not None:
            report["comparison"] = compare(
                reference, report, registry["comparison_policy"]
            )
            if report["comparison"]["status"] != "pass":
                report["status"] = "blocked"
        write_new_json(output_dir / "report.json", report)
        write_new_json(output_dir / "public-summary.json", public_projection(report))
        write_new_json(output_dir / "retention.json", retention_manifest(output_dir))
        verify_retention(output_dir)
        return report
