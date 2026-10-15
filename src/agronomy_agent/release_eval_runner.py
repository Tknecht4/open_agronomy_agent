"""Bounded release-suite execution with immutable inputs and append-only cells."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import random
import resource
import signal
import subprocess
import sys
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

import yaml

from agronomy_agent.release_evaluation import (
    ROOT,
    build_plan,
    bind_controller_inputs,
    checked_path,
    controlled_inputs,
    digest,
    environment_identity,
    file_digest,
    load_registry,
    plan_identity,
    source_identity,
    read_controller_inputs,
    read_stop_policy,
    bind_stop_policy,
    validate_task_exposure,
    validate_worker_runtime,
    planned_analysis_condition,
    worker_case,
    write_new_json,
)
from agronomy_agent.release_eval_analysis import compare, public_projection, summarize


class _PolicyStop(ValueError):
    def __init__(self, reason: str, detail: Any = None):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def _capacity(directory: Path, policy: Mapping[str, Any], *, dispatch: bool = True) -> dict[str, Any]:
    allocated = 0
    for path in directory.rglob("*"):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise _PolicyStop("invalid_retained_path")
        if path.is_file():
            info = path.stat()
            allocated += info.st_blocks * 512
            if info.st_size > policy["file_hardcap_bytes"]:
                raise _PolicyStop("file_hardcap", {"path": str(path), "bytes": info.st_size})
    free = os.statvfs(directory).f_bavail * os.statvfs(directory).f_frsize
    reserve = policy["finalization_reserve_bytes"] if dispatch else 0
    # Leave one maximum file of monitored overshoot headroom before dispatch.
    headroom = policy["file_hardcap_bytes"] if dispatch else 0
    snapshot = {"allocated_entry_bytes": allocated, "free_bytes": free}
    if allocated + reserve + headroom >= policy["retention_budget_bytes"]:
        raise _PolicyStop("retention_capacity", snapshot)
    if free < policy["minimum_free_bytes"] + reserve + headroom:
        raise _PolicyStop("free_capacity", snapshot)
    return snapshot


@contextmanager
def _owned_cancellation(enabled: bool):
    previous = {}
    requested = False
    def cancel(_signum, _frame):
        nonlocal requested
        if not requested:
            requested = True
            raise KeyboardInterrupt
    if enabled and threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, cancel)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


@contextmanager
def _cleanup_shield():
    """Repeated cancellation never interrupts containment of our owned group."""
    previous, pending = {}, []
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda number, _frame: pending.append(number))
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if pending:
            handler = previous[pending[0]]
            if callable(handler):
                handler(pending[0], None)
            elif handler != signal.SIG_IGN:
                raise KeyboardInterrupt


def _parent_write_guard(directory: Path, policy: Mapping[str, Any], *, extra: bytes,
                        path: Path, append: bool = False) -> None:
    if path.is_symlink():
        raise _PolicyStop("invalid_retained_path")
    size = (path.stat().st_size if append and path.exists() else 0) + len(extra)
    if size > policy["file_hardcap_bytes"]:
        raise _PolicyStop("parent_file_hardcap", str(path))
    current = _capacity(directory, policy, dispatch=False)
    charge = ((len(extra) + 4095) // 4096) * 4096
    if (current["allocated_entry_bytes"] + charge + policy["finalization_reserve_bytes"] > policy["retention_budget_bytes"]
            or current["free_bytes"] - charge < policy["minimum_free_bytes"] + policy["finalization_reserve_bytes"]):
        raise _PolicyStop("parent_write_capacity")


def _required_worker_identity(row: Mapping[str, Any], plan: Mapping[str, Any]) -> str:
    """Use original worker fields, never the planned outer-cell overlay, as proof."""
    try:
        if validate_worker_runtime(plan, row, row) != "verified_worker_config_bytes":
            raise _PolicyStop("required_worker_config_unknown")
        if row.get("runtime_input_binding_status", "verified_worker_config_bytes") != "verified_worker_config_bytes":
            raise _PolicyStop("required_worker_config_unknown")
        cell = next((item for item in plan["matrix"] if item["observation_id"] == row.get("observation_id")), None)
        observed = row.get("worker_input_binding")
        if cell is None or not isinstance(observed, Mapping):
            raise _PolicyStop("required_worker_identity_unknown")
        for key in ("observation_id", "case_id", "suite_id", "arm_id", "trial_id", "backend"):
            # The canonical executor does not emit the controller's observation/suite IDs.
            # Its case/arm/trial/backend and projected-case hash are mandatory evidence.
            if key in {"observation_id", "suite_id"} and observed.get(key) is None:
                continue
            if observed.get(key) is None:
                raise _PolicyStop("required_worker_identity_unknown", key)
            if observed[key] != cell[key] or row.get(key) != cell[key]:
                raise _PolicyStop("worker_identity_drift", key)
        case = next(case for case in plan["cases"] if case["case_id"] == cell["case_id"] and case["suite_id"] == cell["suite_id"])
        expected_case = digest(worker_case(case)) if row.get("schema_version") == "open_agronomy_agent.release_product_cell.v1" else cell["case_sha256"]
        if observed.get("case_sha256") is None:
            raise _PolicyStop("required_worker_identity_unknown", "case_sha256")
        if observed["case_sha256"] != expected_case or row.get("case_sha256") != cell["case_sha256"]:
            raise _PolicyStop("worker_identity_drift", "case_sha256")
        for key, expected in (("model_id", plan["model"]["id"]), ("model_revision", plan["model"]["revision"])):
            if observed.get(key) is not None and observed[key] != expected:
                raise _PolicyStop("model_identity_drift", key)
        if "controller_inputs" in plan:
            exposure = validate_task_exposure(case, cell["arm_id"], row.get("task_exposure"))
            if exposure["status"].startswith("unknown_missing") or exposure["status"] == "unknown_incomplete_exposure":
                raise _PolicyStop("required_task_exposure_unknown")
            if row.get("task_input_status") != exposure["status"] or row.get("task_input_sha256") != exposure["task_input_sha256"]:
                raise _PolicyStop("task_exposure_drift")
        return row["config_identity"]["model"]["sha256"]
    except _PolicyStop:
        raise
    except (ValueError, KeyError, TypeError, StopIteration) as exc:
        raise _PolicyStop("worker_identity_binding_invalid", str(exc)) from exc


def _editor_identity_unobserved(turn: Mapping[str, Any]) -> bool:
    """Current producer does not bind an independent identity to editor attempts."""
    metadata = turn.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        return True
    if (turn.get("verification_observation") or {}).get("status") == "unknown_after_draft_return":
        return True
    if any(turn.get(key) is not None for key in ("editor_generation_stats", "verification_generation_stats")):
        return True
    for editor in (turn.get("editor"), metadata.get("answer_verification")):
        if editor is None:
            continue
        if not isinstance(editor, Mapping) or any(editor.get(key) is not None for key in ("generation_stats", "editor_output")):
            return True
        if editor.get("rewrite_accepted") is True or editor.get("triggered") is True or "editor_error" in (editor.get("rejection_reasons") or []):
            return True
    return False


def _identity_shapes(turn: Any) -> None:
    """Malformed optional mirrors are unknown, never erased by ``or {}``."""
    if not isinstance(turn, Mapping):
        raise _PolicyStop("required_identity_evidence_unknown")
    for record, keys in ((turn, ("metadata", "model_execution", "model_revision_observation", "verification_observation", "draft_checkpoint", "editor", "generation_stats", "model_identity", "editor_generation_stats", "verification_generation_stats")),
                         (turn.get("metadata") or {}, ("generation_bypass", "generation_stats", "model_identity", "answer_verification"))):
        if not isinstance(record, Mapping) or any(record.get(key) is not None and not isinstance(record[key], Mapping) for key in keys):
            raise _PolicyStop("required_identity_evidence_unknown")
    for editor in (turn.get("editor"), (turn.get("metadata") or {}).get("answer_verification")):
        if editor is not None and (not isinstance(editor.get("rejection_reasons", []), list)
                                   or editor.get("generation_stats") is not None and not isinstance(editor["generation_stats"], Mapping)):
            raise _PolicyStop("required_identity_evidence_unknown")


def _verification_no_editor_evidence(turn: Mapping[str, Any], stage: Mapping[str, Any]) -> None:
    record = (turn.get("metadata") or {}).get("answer_verification")
    records = [item for item in (record, turn.get("editor")) if item is not None]
    if stage["state"] == "executed" or stage["evidence"]["executed"] is True:
        if (stage["state"] != "executed" or stage["evidence"]["executed"] is not True
                or not isinstance(record, Mapping) or record.get("triggered") is not False):
            raise _PolicyStop("required_editor_identity_unknown")
    if any(digest(item) != stage["evidence"]["adjudication_sha256"] for item in records):
        raise _PolicyStop("contradictory_verification_evidence")


def _corroborated_no_model(turn: Mapping[str, Any]) -> bool:
    execution = turn.get("model_execution") or {}
    metadata = turn.get("metadata") or {}
    if execution.get("disposition") != "deterministic_bypass":
        return False
    from agronomy_agent.execution_core import validate_execution_stage_receipts
    try:
        stages = {item["stage_id"]: item for item in validate_execution_stage_receipts(turn.get("stage_receipts"))}
    except (ValueError, TypeError) as exc:
        raise _PolicyStop("required_no_model_evidence_unknown", str(exc)) from exc
    bypass, draft, verify, origin = (stages[key] for key in ("deterministic_bypass", "draft_generation", "verification", "fallback_origin"))
    _verification_no_editor_evidence(turn, verify)
    if not (turn.get("status") == "completed" and turn.get("execution_kind") == "production"
            and isinstance(metadata.get("generation_bypass"), Mapping) and bool(metadata["generation_bypass"])
            and not metadata.get("generation_fallback") and not metadata.get("generation_unavailable")
            and execution.get("synthetic") is False and execution.get("backend_available") is True
            and all(execution.get(key) is False for key in ("model_generation_eligible", "model_execution_eligible", "generation_stats_present"))
            and turn.get("model_execution_eligible") is False
            and (execution.get("generator_called") is None or execution["generator_called"] is False)
            and turn.get("generation_stats") is None and metadata.get("generation_stats") is None
            and not _editor_identity_unobserved(turn)
            and (turn.get("draft_checkpoint") or {}).get("status") == "not_observed"
            and bypass["state"] == "executed" and bypass["evidence"]["bypass_selected"] is True
            and draft["state"] == "bypassed" and draft["evidence"]["model_call_executed"] is False
            and draft["evidence"]["fallback_used"] is False
            and verify["state"] in {"not_applicable", "disabled_by_arm"} and verify["evidence"]["executed"] is False
            and origin["evidence"]["origin_class"] == "deterministic_bypass" and origin["evidence"]["fallback_used"] is False):
        raise _PolicyStop("contradictory_no_model_evidence")
    return True


def _bound_turn_identity(turn: Mapping[str, Any], plan: Mapping[str, Any], config_sha256: str, *, required: bool) -> None:
    execution = turn.get("model_execution") or {}
    identities = [value for value in (turn.get("model_identity"), (turn.get("metadata") or {}).get("model_identity"), execution.get("identity")) if value is not None]
    if not identities and not required:
        return
    if not identities or any(not isinstance(value, Mapping) for value in identities):
        raise _PolicyStop("required_model_identity_unknown")
    if any(digest(value) != digest(identities[0]) for value in identities[1:]):
        raise _PolicyStop("model_identity_drift", "conflicting identity mirrors")
    identity = identities[0]
    if identity.get("schema_version") != "open_agronomy_agent.model_identity_contract.v1":
        raise _PolicyStop("required_model_identity_unknown")
    for key, expected in (("configured_model_id", plan["model"]["id"]), ("configured_model_revision", plan["model"]["revision"]), ("model_config_sha256", config_sha256)):
        if identity.get(key) is None or expected is None:
            raise _PolicyStop("required_model_identity_unknown", key)
        if identity[key] != expected:
            raise _PolicyStop("model_identity_drift", key)
    runtime = identity.get("runtime")
    if runtime is not None or identity.get("status") == "verified_runtime_receipt":
        if not isinstance(runtime, Mapping) or any(runtime.get(key) is None for key in ("model_id", "model_revision")):
            raise _PolicyStop("required_model_identity_unknown", "runtime")
        if runtime["model_id"] != plan["model"]["id"] or runtime["model_revision"] != plan["model"]["revision"]:
            raise _PolicyStop("model_identity_drift", "runtime")


def _required_generation_identity(turn: Mapping[str, Any], plan: Mapping[str, Any], config_sha256: str) -> None:
    from agronomy_agent.release_eval_analysis import _verified_generation
    execution = turn.get("model_execution") or {}
    if (turn.get("execution_kind") not in {"production", "ungoverned_reference"}
            or execution.get("disposition") != "model_generated" or execution.get("backend_available") is not True
            or execution.get("generation_stats_present") is not True or turn.get("model_execution_eligible") is not True
            or execution.get("model_execution_eligible") is not True
            or "generator_called" in execution and execution["generator_called"] is not True):
        raise _PolicyStop("contradictory_model_execution")
    metadata = turn.get("metadata") or {}
    if metadata.get("generation_fallback") or metadata.get("generation_unavailable"):
        raise _PolicyStop("contradictory_model_execution", "backend fallback/unavailable")
    if metadata.get("generation_stats") is not None and digest(metadata["generation_stats"]) != digest(turn.get("generation_stats")):
        raise _PolicyStop("contradictory_model_execution", "generation stats mirrors")
    if turn.get("execution_kind") == "production":
        from agronomy_agent.execution_core import validate_execution_stage_receipts
        try:
            stages = {item["stage_id"]: item for item in validate_execution_stage_receipts(turn.get("stage_receipts"))}
            if (stages["draft_generation"]["state"] != "executed"
                    or stages["draft_generation"]["evidence"]["model_call_executed"] is not True
                    or stages["draft_generation"]["evidence"]["fallback_used"] is not False):
                raise ValueError("generated draft stage contradicts model execution")
        except (ValueError, TypeError) as exc:
            raise _PolicyStop("contradictory_model_execution", str(exc)) from exc
        _verification_no_editor_evidence(turn, stages["verification"])
    _bound_turn_identity(turn, plan, config_sha256, required=True)
    if not _verified_generation(turn, plan["model"]["revision"]):
        raise _PolicyStop("required_model_identity_unknown")
    if _editor_identity_unobserved(turn):
        raise _PolicyStop("required_editor_identity_unknown")


def _attempt_stop(row: Mapping[str, Any], plan: Mapping[str, Any], *, product: bool) -> None:
    if row.get("status") not in ({"completed"} if product else {"pass"}):
        raise _PolicyStop("attempt_status", row.get("status"))
    if any(check.get("passed") is not True for check in row.get("checks") or []):
        raise _PolicyStop("failed_check")
    if not product:
        return
    from agronomy_agent.release_eval_executor import observation_termination
    from agronomy_agent.release_eval_model_metrics import termination_evidence
    from agronomy_agent.release_eval_reanalysis import _merge_termination
    policy = plan["bounded_stop_policy"]["policy"]
    turns = row.get("turns") or []
    if policy["require_model_identity"]:
        if not isinstance(turns, list):
            raise _PolicyStop("required_identity_evidence_unknown")
        for turn in turns:
            _identity_shapes(turn)
    recorded = termination_evidence(row)
    derived = observation_termination(turns) if turns else None
    actual = termination_evidence({"termination": derived})
    if recorded["truncated"] is not None and actual["truncated"] is not None and recorded["truncated"] != actual["truncated"]:
        raise _PolicyStop("contradictory_termination")
    merged = _merge_termination(row.get("termination"), derived)
    terminal = termination_evidence({**row, "termination": merged})
    if terminal["truncated"] is True:
        raise _PolicyStop("generation_truncated")
    if policy["require_termination"] and terminal["status"] == "unknown":
        raise _PolicyStop("required_termination_unknown")
    if policy["require_model_identity"]:
        config_sha256 = _required_worker_identity(row, plan)
        revision = plan["model"].get("revision")
        if not turns:
            raise _PolicyStop("required_model_identity_unknown")
        for turn in turns:
            execution = turn.get("model_execution") or {}
            observed = turn.get("model_revision_observation") or {}
            if any(observed.get(key) not in (None, revision) for key in ("configured", "resolved")):
                raise _PolicyStop("model_identity_drift")
            if _corroborated_no_model(turn):
                _bound_turn_identity(turn, plan, config_sha256, required=False)
                continue
            if (turn.get("metadata") or {}).get("generation_bypass") or execution.get("generator_called") is False:
                raise _PolicyStop("required_no_model_evidence_unknown")
            _required_generation_identity(turn, plan, config_sha256)


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


def _stop_owned_processes(
    child: subprocess.Popen, *, new_session: bool, grace: float = 5.0
) -> None:
    """A leader's exit does not establish that its process group has exited."""
    if not new_session and child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM) if new_session else child.terminate()
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace
    probe_error = None
    while time.monotonic() < deadline:
        child.poll()  # reap the leader, while continuing to observe its group
        try:
            if new_session:
                os.killpg(child.pid, 0)
                probe_error = None
            elif child.poll() is not None:
                return
        except ProcessLookupError:
            return
        except PermissionError as exc:
            # macOS can transiently deny a group probe while SIGTERM is
            # completing. Retry within the bound; denial never proves exit.
            probe_error = exc
        time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    try:
        os.killpg(child.pid, signal.SIGKILL) if new_session else child.kill()
    except ProcessLookupError:
        pass
    child.wait(timeout=5)
    if probe_error is not None:
        raise PermissionError(
            "owned process group remained unobservable at cleanup deadline"
        ) from probe_error


def _command(
    argv: list[str],
    *,
    cwd: Path,
    output: Path,
    timeout: float,
    new_session: bool = True,
    execution_guard: Mapping[str, Any] | None = None,
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
    end = time.monotonic() + timeout
    if execution_guard:
        end = min(end, execution_guard["deadline_monotonic"])
        _capacity(Path(execution_guard["directory"]), execution_guard["policy"])
        if time.monotonic() >= end:
            raise _PolicyStop("dispatch_deadline")
    with output.open("x", encoding="utf-8") as handle:
        if execution_guard:
            _capacity(Path(execution_guard["directory"]), execution_guard["policy"])
            if time.monotonic() >= end:
                raise _PolicyStop("dispatch_deadline")
        def file_limit():
            cap = execution_guard["policy"]["file_hardcap_bytes"]
            _, inherited = resource.getrlimit(resource.RLIMIT_FSIZE)
            cap = cap if inherited == resource.RLIM_INFINITY else min(cap, inherited)
            resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
        child = None
        try:
            # Defer cancellation until creation/assignment is inside containment.
            with _cleanup_shield():
                child = subprocess.Popen(
                    argv, cwd=cwd, env=environment, stdout=handle,
                    stderr=subprocess.STDOUT, start_new_session=new_session,
                    **({"preexec_fn": file_limit} if execution_guard else {}),
                )
            if execution_guard:
                write_new_json(output.parent / "child-dispatch.json", {"pid": child.pid,
                    "started_monotonic_seconds": time.monotonic(), "deadline_monotonic_seconds": end})
            if execution_guard is None:
                return child.wait(timeout=timeout), "completed"
            while True:
                try:
                    _capacity(Path(execution_guard["directory"]), execution_guard["policy"])
                except _PolicyStop as stop:
                    return 125, stop.reason
                if time.monotonic() >= end:
                    return 124, "timeout"
                status = child.poll()
                if status is not None:
                    return status, "completed"
                time.sleep(min(0.02, max(0, end - time.monotonic())))
        except subprocess.TimeoutExpired:
            return 124, "timeout"
        finally:
            # Success, timeout and owner cancellation all close the owned group.
            # Nested commands share that group; only their direct child is owned
            # here, and the outer worker owner contains any remaining descendants.
            if child is not None:
                with _cleanup_shield():
                    _stop_owned_processes(child, new_session=new_session)


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
        repeats = spec["registry"]["profiles"][spec["profile"]]["performance_repeats"]
        expected_cells = spec["registry"]["backend_performance_policy"][
            "required_warm_cells"
        ]
        completed_cells = all(
            name in cells
            and cells[name].get("status") == "completed"
            and cells[name].get("requested_samples") == repeats
            and cells[name].get("timing", {}).get("samples") == repeats
            and isinstance(cells[name].get("timing", {}).get("p95_ms"), (int, float))
            and not isinstance(cells[name]["timing"]["p95_ms"], bool)
            and math.isfinite(cells[name]["timing"]["p95_ms"])
            and cells[name]["timing"]["p95_ms"] >= 0
            for name in expected_cells
        )
        return {
            "component": kind,
            "status": (
                "pass"
                if status == 0
                and result.get("status") == "completed"
                and completed_cells
                else "blocked"
            ),
            "checks": [
                {
                    "id": "backend_profile_cell_coverage",
                    "passed": completed_cells,
                    "detail": {
                        "required_cells": expected_cells,
                        "requested_samples": repeats,
                    },
                }
            ],
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
    if spec.get("execution_guard"):
        guard = spec["execution_guard"]
        _parent_write_guard(Path(guard["directory"]), guard["policy"], path=directory / "spec.json",
            extra=(json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
    write_new_json(directory / "spec.json", spec)
    result_path = directory / "worker-result.json"
    try:
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
        execution_guard=spec.get("execution_guard"),
        )
    except KeyboardInterrupt:
        if not spec.get("execution_guard"):
            raise
        status, disposition = 130, "owner_cancelled"
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
    if status != 0:
        result["worker_disposition"] = disposition
    return result


def _append(path: Path, record: Mapping[str, Any], *, guard: Mapping[str, Any] | None = None) -> None:
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    if guard:
        _parent_write_guard(Path(guard["directory"]), guard["policy"], path=path, extra=raw.encode(), append=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(raw)
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
    excluded = {".run.lock", "retention.json"}
    if ((directory / "plan.json").is_file() and
            "bounded_stop_policy" in json.loads((directory / "plan.json").read_text())):
        # These closeout records bind the finalized retention seal and report,
        # and are independently validated by the retained-report reader.
        excluded.update({"closeout.json", "closeout-failure.json", "terminal-closeout.json"})
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("retained evaluation outputs must not contain symlinks")
        if path.is_file() and path.relative_to(directory).as_posix() not in excluded:
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
    return _load_retained_report(path, terminal_seal_required=True)


def _load_retained_report(path: Path, *, terminal_seal_required: bool) -> dict[str, Any]:
    """The runner may inspect a provisional closeout under its held run lock."""
    path = path.resolve()
    directory = path if path.is_dir() else path.parent
    report_path = directory / "report.json"
    if not path.is_dir() and path != report_path:
        raise ValueError("reference must be a retained run or its report.json")
    verify_retention(directory)
    if not (directory / "plan.json").is_file():
        from agronomy_agent.release_eval_reanalysis import load_reference_report

        return load_reference_report(path)
    report = json.loads(report_path.read_text())
    plan = json.loads((directory / "plan.json").read_text())
    if report.get("plan_sha256") != plan_identity(plan):
        raise ValueError("reference plan/report binding differs")
    _ledger(directory / "observations.jsonl", plan_sha256=plan_identity(plan))
    _ledger(directory / "components.jsonl", plan_sha256=plan_identity(plan))
    if "bounded_stop_policy" in plan:
        closed = directory / "closeout.json"
        if not closed.is_file() or closed.is_symlink():
            raise ValueError("bounded terminal report has no verified closeout receipt")
        binding = {"plan_sha256": plan_identity(plan), "policy_sha256": plan["bounded_stop_policy"]["sha256"],
                   "report_sha256": file_digest(report_path), "retention_sha256": file_digest(directory / "retention.json"),
                   "clock_sha256": file_digest(directory / "run-clock.json")}
        receipt = json.loads(closed.read_text())
        if (receipt.get("record_sha256") != digest({k: v for k, v in receipt.items() if k != "record_sha256"})
                or any(receipt.get(k) != v for k, v in binding.items())
                or receipt.get("schema_version") != "open_agronomy_agent.bounded_closeout.v1"
                or type(receipt.get("observed_remaining_seconds")) not in (int, float)
                or not math.isfinite(receipt["observed_remaining_seconds"])
                or receipt.get("status") != ("complete_within_deadline" if receipt["observed_remaining_seconds"] >= 0 else "late_blocked")
                or file_digest(directory / "stop-policy.private.json") != binding["policy_sha256"]):
            raise ValueError("bounded closeout binding differs")
        late = receipt["status"] == "late_blocked"
        failure = directory / "closeout-failure.json"
        if failure.exists():
            failed = json.loads(failure.read_text())
            if failure.is_symlink() or failed.get("record_sha256") != digest({k: v for k, v in failed.items() if k != "record_sha256"}) or failed.get("closeout_sha256") != file_digest(closed):
                raise ValueError("bounded closeout failure binding differs")
            late = True
        terminal = None
        if terminal_seal_required:
            seal = directory / "terminal-closeout.json"
            if not seal.is_file() or seal.is_symlink():
                raise ValueError("bounded terminal disposition seal is missing")
            terminal = json.loads(seal.read_text())
            failure_sha256 = file_digest(failure) if failure.is_file() else None
            remaining = terminal.get("observed_remaining_seconds")
            if (terminal.get("schema_version") != "open_agronomy_agent.terminal_closeout.v1"
                    or terminal.get("record_sha256") != digest({k: v for k, v in terminal.items() if k != "record_sha256"})
                    or any(terminal.get(k) != v for k, v in binding.items())
                    or terminal.get("closeout_sha256") != file_digest(closed)
                    or terminal.get("failure_sha256") != failure_sha256
                    or type(remaining) not in (int, float) or not math.isfinite(remaining)
                    or terminal.get("status") != ("late_blocked" if late or remaining < 0 else "complete_within_deadline")):
                raise ValueError("required terminal disposition or failure presence differs")
            late = terminal["status"] == "late_blocked"
        execution = report["bounded_execution"]
        execution["closeout"] = receipt
        execution["closeout_receipt_sha256"] = file_digest(closed)
        execution["closeout_status"] = "late_blocked" if late else "complete_within_deadline"
        if terminal is not None:
            execution["terminal_seal"] = terminal
            execution["terminal_seal_sha256"] = file_digest(directory / "terminal-closeout.json")
        if late:
            execution["status"] = "terminal_stopped"
            execution["stop"] = execution.get("stop") or {"reason": "finalization_deadline", "detail": None}
            report["status"] = "blocked"
            report["failures"]["bounded_execution_stop"] = execution["stop"]
        elif execution["status"] == "awaiting_closeout":
            execution["status"] = "dispatch_complete"
    elif any((directory / name).exists() for name in ("closeout.json", "closeout-failure.json", "terminal-closeout.json")):
        raise ValueError("legacy run has unexpected bounded closeout files")
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


def _bounded_clock(path: Path, *, plan_sha256: str, policy_sha256: str,
                   budget: float, entry_unix: float, resume: bool) -> dict[str, Any]:
    if not path.exists():
        if resume:
            raise ValueError("bounded resume requires the original durable run clock")
        clock = {"schema_version": "open_agronomy_agent.bounded_run_clock.v1",
                 "started_unix_seconds": entry_unix, "deadline_unix_seconds": entry_unix + budget,
                 "budget_seconds": budget, "plan_sha256": plan_sha256, "policy_sha256": policy_sha256}
        clock["record_sha256"] = digest(clock)
        write_new_json(path, clock)
    clock = json.loads(path.read_text())
    if path.is_symlink() or clock.get("record_sha256") != digest({k: v for k, v in clock.items() if k != "record_sha256"}):
        raise ValueError("bounded run clock integrity differs")
    if (clock.get("schema_version") != "open_agronomy_agent.bounded_run_clock.v1"
            or clock.get("plan_sha256") != plan_sha256 or clock.get("policy_sha256") != policy_sha256
            or clock.get("budget_seconds") != budget):
        raise ValueError("bounded run clock identity differs")
    for key in ("started_unix_seconds", "deadline_unix_seconds"):
        if type(clock.get(key)) not in (int, float) or not math.isfinite(clock[key]):
            raise ValueError("bounded run clock time is invalid")
    if clock["deadline_unix_seconds"] != clock["started_unix_seconds"] + budget or entry_unix < clock["started_unix_seconds"]:
        raise ValueError("bounded run clock deadline or wall-clock rollback")
    return clock


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
    model_rubrics_path: Path | None = None,
    model_policy_path: Path | None = None,
    comparison_cohort: str | None = None,
    stop_policy_path: Path | None = None,
) -> dict[str, Any]:
    entry_unix, entry_monotonic = time.time(), time.monotonic()
    stop_input = read_stop_policy(stop_policy_path)
    stop_policy = stop_input["policy"] if stop_input else None
    registry = load_registry(registry_path)
    if profile == "release" and reference_path is None:
        raise ValueError("release profile requires a retained full reference report")
    if reference_path is not None and profile not in {"baseline", "release"}:
        raise ValueError("reference comparison requires a complete model profile")
    reference = load_retained_report(reference_path) if reference_path else None
    reviews_bytes = reviews_path.read_bytes() if reviews_path else None
    reviews = (
        [
            json.loads(line)
            for line in reviews_bytes.decode("utf-8").splitlines()
            if line.strip()
        ]
        if reviews_bytes is not None
        else []
    )
    if any(not isinstance(row, dict) for row in reviews):
        raise ValueError("review input must contain JSON objects")
    controller = read_controller_inputs(rubrics_path=model_rubrics_path, policy_path=model_policy_path)
    plan = bind_controller_inputs(build_plan(registry, profile=profile, run_id=run_id, limit=limit), controller, comparison_cohort)
    model_bytes = checked_path(ROOT, registry["model_config"]).read_bytes()
    if hashlib.sha256(model_bytes).hexdigest() != plan["model"]["config_sha256"]:
        raise ValueError("model config changed during planning")
    model_snapshot = yaml.safe_load(model_bytes)
    rag_bytes = checked_path(ROOT, registry["rag_config"]).read_bytes()
    if hashlib.sha256(rag_bytes).hexdigest() != plan["rag_config_sha256"]:
        raise ValueError("RAG config changed during planning")
    rag_snapshot = yaml.safe_load(rag_bytes)
    if "controller_inputs" in plan or stop_input:
        runtime_rag = {**rag_snapshot, "private_knowledge": {"enabled": False, "required": False}}
        plan["effective_runtime_inputs"] = {
            "rag_sha256": hashlib.sha256(yaml.safe_dump(runtime_rag, sort_keys=True).encode()).hexdigest(),
            "model_trial_sha256": {
                f"trial-{trial:03d}": hashlib.sha256(yaml.safe_dump(
                    {**model_snapshot, "seed": registry["seed"] + trial - 1, "prompt_cache_enabled": False}, sort_keys=True).encode()).hexdigest()
                for trial in range(1, registry["profiles"][profile]["trials"] + 1)
            },
        }
    plan["environment"] = environment_identity()
    plan["reference_sha256"] = digest(reference) if reference else None
    plan["reviews_sha256"] = (
        hashlib.sha256(reviews_bytes).hexdigest() if reviews_bytes is not None else None
    )
    plan = bind_stop_policy(plan, stop_input, registry["whole_run_timeout_seconds"])
    plan_sha256 = plan_identity(plan)
    output_dir = output_dir.resolve()
    if stop_policy and not (resume and (output_dir / "report.json").is_file()):
        payloads = [(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
                    stop_input["bytes"], *[item["bytes"] for item in controller.values()]]
        payloads += [yaml.safe_dump({**rag_snapshot, "private_knowledge": {"enabled": False, "required": False}}, sort_keys=True).encode()]
        payloads += [yaml.safe_dump({**model_snapshot, "seed": registry["seed"] + trial - 1,
                         "prompt_cache_enabled": False}, sort_keys=True).encode()
                     for trial in range(1, registry["profiles"][profile]["trials"] + 1)]
        if reviews_bytes is not None:
            payloads.append(reviews_bytes)
        if reference is not None:
            payloads.append((json.dumps(reference, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
        charge = sum(((len(raw) + 4095) // 4096) * 4096 for raw in payloads) + 8192
        probe = output_dir if output_dir.exists() else next(parent for parent in output_dir.parents if parent.exists())
        free = os.statvfs(probe).f_bavail * os.statvfs(probe).f_frsize
        if (max(len(raw) for raw in payloads) > stop_policy["file_hardcap_bytes"]
                or charge + stop_policy["finalization_reserve_bytes"] >= stop_policy["retention_budget_bytes"]
                or free - charge < stop_policy["minimum_free_bytes"] + stop_policy["finalization_reserve_bytes"]):
            raise ValueError("bounded preparation preflight capacity refused before output")
        if not resume and time.monotonic() - entry_monotonic >= registry["whole_run_timeout_seconds"] - stop_policy["finalization_reserve_seconds"]:
            raise ValueError("bounded preparation deadline expired before output")
    if output_dir.exists() and any(output_dir.iterdir()) and not resume:
        raise ValueError(
            "output directory must be new; use exact-identity resume or a successor run"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".run.lock").open("a") as lock, _owned_cancellation(stop_policy is not None):
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another owner holds this evaluation run") from exc
        if (output_dir / "startup-stop.json").exists():
            raise ValueError("terminal startup stop requires a successor run")

        def preparation_guard(path, raw):
            if stop_policy:
                _parent_write_guard(output_dir, stop_policy, path=path, extra=raw)
                if time.monotonic() - entry_monotonic >= registry["whole_run_timeout_seconds"] - stop_policy["finalization_reserve_seconds"]:
                    raise _PolicyStop("preparation_deadline")
        try:
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
                preparation_guard(saved_plan, (json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
                write_new_json(saved_plan, plan)
            if (output_dir / "report.json").is_file():
                return load_retained_report(output_dir)
            bounded_clock = None
            if stop_input:
                frozen_stop = output_dir / "stop-policy.private.json"
                if frozen_stop.exists():
                    if frozen_stop.is_symlink() or frozen_stop.read_bytes() != stop_input["bytes"]:
                        raise ValueError("frozen stop policy bytes changed")
                else:
                    preparation_guard(frozen_stop, stop_input["bytes"])
                    with frozen_stop.open("xb") as handle:
                        handle.write(stop_input["bytes"])
                        handle.flush()
                        os.fsync(handle.fileno())
                bounded_clock = _bounded_clock(output_dir / "run-clock.json", plan_sha256=plan_sha256,
                    policy_sha256=stop_input["sha256"], budget=registry["whole_run_timeout_seconds"],
                    entry_unix=entry_unix, resume=resume)
            for name, item in controller.items():
                suffix = "jsonl" if name == "rubrics" else "json"
                path = output_dir / f"model-{name}.private.{suffix}"
                if path.exists():
                    if path.is_symlink() or path.read_bytes() != item["bytes"]:
                        raise ValueError("frozen controller bytes changed")
                else:
                    preparation_guard(path, item["bytes"])
                    with path.open("xb") as handle:
                        handle.write(item["bytes"])

            def verify_prospective_inputs():
                if stop_input:
                    current_stop = read_stop_policy(stop_policy_path)
                    if current_stop["bytes"] != stop_input["bytes"] or (output_dir / "stop-policy.private.json").read_bytes() != stop_input["bytes"]:
                        raise ValueError("bounded stop policy bytes changed")
                if "controller_inputs" not in plan:
                    if not stop_input:
                        return
                if source_identity()["source_sha256"] != plan["source"]["source_sha256"] or controlled_inputs(registry) != plan["auxiliary_inputs"] or digest(load_registry(registry_path)) != plan["registry_sha256"]:
                    raise ValueError("prospective source or controlled inputs changed")
                if file_digest(checked_path(ROOT, registry["model_config"])) != plan["model"]["config_sha256"] or file_digest(checked_path(ROOT, registry["rag_config"])) != plan["rag_config_sha256"]:
                    raise ValueError("prospective runtime inputs changed")
                current = read_controller_inputs(rubrics_path=model_rubrics_path, policy_path=model_policy_path)
                for name, item in controller.items():
                    suffix = "jsonl" if name == "rubrics" else "json"
                    path = output_dir / f"model-{name}.private.{suffix}"
                    if current[name]["bytes"] != item["bytes"] or path.is_symlink() or file_digest(path) != item["sha256"]:
                        raise ValueError("prospective controller bytes changed")
                if runtime_ready and "effective_runtime_inputs" in plan:
                    if file_digest(public_rag) != plan["effective_runtime_inputs"]["rag_sha256"] or any(
                        file_digest(effective / f"model-{trial_id}.yaml") != expected
                        for trial_id, expected in plan["effective_runtime_inputs"]["model_trial_sha256"].items()
                    ):
                        raise ValueError("prospective effective runtime bytes changed")
            runtime_ready = False
            verify_prospective_inputs()
            if reviews_bytes is not None:
                frozen_reviews = output_dir / "reviews.private.jsonl"
                if frozen_reviews.exists():
                    if (
                        frozen_reviews.is_symlink()
                        or frozen_reviews.read_bytes() != reviews_bytes
                    ):
                        raise ValueError("frozen review input differs from planned bytes")
                else:
                    preparation_guard(frozen_reviews, reviews_bytes)
                    with frozen_reviews.open("xb") as handle:
                        handle.write(reviews_bytes)
            if reference is not None:
                frozen_reference = output_dir / "reference-report.json"
                if frozen_reference.exists():
                    if (
                        digest(json.loads(frozen_reference.read_text()))
                        != plan["reference_sha256"]
                    ):
                        raise ValueError("frozen reference differs from planned bytes")
                else:
                    preparation_guard(frozen_reference, (json.dumps(reference, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
                    write_new_json(frozen_reference, reference)
            effective = output_dir / "effective"
            effective.mkdir(exist_ok=True)
            rag = dict(rag_snapshot)
            rag["private_knowledge"] = {"enabled": False, "required": False}
            public_rag = effective / "public-rag.yaml"
            if not public_rag.exists():
                preparation_guard(public_rag, yaml.safe_dump(rag, sort_keys=True).encode())
            _effective_yaml(public_rag, rag)
            for trial in range(1, registry["profiles"][profile]["trials"] + 1):
                path = effective / f"model-trial-{trial:03d}.yaml"
                model = dict(model_snapshot)
                model["seed"] = registry["seed"] + trial - 1
                model["prompt_cache_enabled"] = False
                if not path.exists():
                    preparation_guard(path, yaml.safe_dump(model, sort_keys=True).encode())
                _effective_yaml(path, model)
            if "controller_inputs" in plan or stop_input:
                expected_runtime = plan["effective_runtime_inputs"]
                if file_digest(public_rag) != expected_runtime["rag_sha256"] or any(
                    file_digest(effective / f"model-{trial_id}.yaml") != expected
                    for trial_id, expected in expected_runtime["model_trial_sha256"].items()
                ):
                    raise ValueError("effective runtime bytes differ from frozen inputs")
            runtime_ready = True
            clock_path = output_dir / "run-clock.json"
            if not clock_path.exists():
                write_new_json(
                    clock_path,
                    {"started_unix_seconds": time.time(), "plan_sha256": plan_sha256},
                )
            clock = json.loads(clock_path.read_text())
            if clock.get("plan_sha256") != plan_sha256:
                raise ValueError("run deadline source binding differs")
            if bounded_clock:
                deadline = entry_monotonic + bounded_clock["deadline_unix_seconds"] - entry_unix
            else:
                remaining_budget = registry["whole_run_timeout_seconds"] - max(
                    0, time.time() - clock["started_unix_seconds"]
                )
                deadline = time.monotonic() + max(0, remaining_budget)
        except (ValueError, OSError, KeyboardInterrupt) as exc:
            if stop_policy and not (output_dir / "report.json").exists():
                record = {"schema_version": "open_agronomy_agent.startup_stop.v1",
                          "plan_sha256": plan_sha256, "policy_sha256": stop_input["sha256"],
                          "reason": str(exc) or "owner_cancelled", "disposition": "terminal_startup_stop",
                          "new_dispatch_occurred": False, "qualification_granted": False}
                record["record_sha256"] = digest(record)
                raw = (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
                try:
                    _parent_write_guard(output_dir, {**stop_policy, "finalization_reserve_bytes": 1},
                                        path=output_dir / "startup-stop.json", extra=raw)
                    write_new_json(output_dir / "startup-stop.json", record)
                except (OSError, ValueError):
                    pass  # Missing/partial seal is refused; never invent startup authority.
            raise
        components_path, observations_path = (
            output_dir / "components.jsonl",
            output_dir / "observations.jsonl",
        )
        components = _ledger(components_path, plan_sha256=plan_sha256)
        rows = _ledger(observations_path, plan_sha256=plan_sha256)
        stopped = None

        def dispatch_remaining():
            if stop_policy:
                _capacity(output_dir, stop_policy)
                remaining = deadline - time.monotonic() - stop_policy["finalization_reserve_seconds"]
                if remaining <= 0:
                    raise _PolicyStop("dispatch_deadline")
                return remaining
            return deadline - time.monotonic()

        def dispatch(spec, *, timeout):
            if stop_policy:
                spec["execution_guard"] = {"directory": str(output_dir), "policy": stop_policy,
                    "deadline_monotonic": deadline - stop_policy["finalization_reserve_seconds"]}
            try:
                return _subprocess_cell(spec, timeout=timeout)
            except _PolicyStop:
                raise
            except KeyboardInterrupt:
                if not stop_policy:
                    raise
                return {"status": "interrupted", "error_type": "OwnerCancelled",
                        "checks": [{"id": "owner_cancellation", "passed": False}]}
            except Exception as exc:
                if not stop_policy:
                    raise
                return {"status": "failed", "error_type": type(exc).__name__,
                        "error": str(exc), "checks": [{"id": "worker_exception", "passed": False}]}

        try:
            if stop_policy:
                for previous in components:
                    _attempt_stop(previous, plan, product=False)
                for previous in rows:
                    _attempt_stop(previous, plan, product=True)
            completed_components = {row["component"] for row in components}
            for kind in registry["required_components"]:
                if kind in completed_components:
                    continue
                verify_prospective_inputs()
                remaining = dispatch_remaining()
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
                    dispatch(spec, timeout=timeout)
                    if remaining > 0
                    else {"status": "failed", "error_type": "WholeRunDeadline"}
                )
                result["component"] = kind
                if result.get("status") == "failed":
                    result["status"] = "blocked"
                _bind_artifacts(result, Path(spec["directory"]), output_dir)
                result["receipt_sha256"] = digest(result)
                record = _seal_record(result, plan_sha256)
                _append(components_path, record, guard={"directory": str(output_dir), "policy": stop_policy} if stop_policy else None)
                components.append(record)
                if stop_policy:
                    _attempt_stop(record, plan, product=False)
                print(
                    json.dumps({"component": kind, "status": result["status"]}), flush=True
                )
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
                    verify_prospective_inputs()
                    remaining = dispatch_remaining()
                    spec = {
                        "kind": "product",
                        "directory": str(output_dir / "cells" / cell["observation_id"]),
                        "cell": {key: value for key, value in cell.items() if key not in {"comparison_cohort", "task_input_sha256", "task_input_status"}},
                        "case": worker_case(case),
                        "model_config": str(effective / f"model-{trial_id}.yaml"),
                        "rag_config": str(public_rag),
                        "max_tokens": registry["max_tokens"],
                    }
                    result = (
                        dispatch(
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
                    binding_error = None
                    exposure_binding = None
                    if "controller_inputs" in plan or stop_input:
                        result["planned_input_binding"] = {key: cell.get(key) for key in ("comparison_cohort", "task_input_sha256", "task_input_status")}
                        result["worker_input_binding"] = {key: result.get(key) for key in ("observation_id", "case_id", "case_sha256", "suite_id", "arm_id", "trial_id", "backend", "model_id", "model_revision", "analysis_condition", "comparison_cohort", "task_input_sha256", "status")}
                        result["planned_input_binding"]["source_case_sha256"] = cell["case_sha256"]
                        result["planned_input_binding"]["worker_case_sha256"] = digest(worker_case(case))
                        try:
                            for key in ("observation_id", "case_id", "case_sha256", "suite_id", "arm_id", "trial_id", "backend"):
                                expected_identity = digest(worker_case(case)) if key == "case_sha256" and result.get("schema_version") == "open_agronomy_agent.release_product_cell.v1" else cell[key]
                                if result.get(key) is not None and result[key] != expected_identity:
                                    raise ValueError("observed worker cell identity differs: " + key)
                            if "controller_inputs" in plan:
                                exposure_binding = validate_task_exposure(case, cell["arm_id"], result.get("task_exposure"))
                            runtime_status = validate_worker_runtime(plan, cell, result)
                            result["runtime_input_binding_status"] = runtime_status
                            expected_condition = planned_analysis_condition(plan, cell)
                            for key in ("model_id", "model_revision"):
                                expected_value = plan["model"]["id" if key == "model_id" else "revision"]
                                if result.get(key) is not None and result[key] != expected_value:
                                    raise ValueError("observed worker model identity differs: " + key)
                            if result.get("analysis_condition") is not None:
                                if result["analysis_condition"] != expected_condition:
                                    raise ValueError("observed worker analysis condition differs")
                            elif runtime_status == "verified_worker_config_bytes":
                                result["analysis_condition"] = expected_condition
                                result["analysis_condition_scope"] = "source verified before dispatch; worker config bytes observed; actual model/runtime qualification remains separate"
                            if exposure_binding is not None and exposure_binding["task_input_sha256"] is not None and exposure_binding["task_input_sha256"] != cell["task_input_sha256"]:
                                raise ValueError("planned and exposed task input mismatch")
                        except ValueError as exc:
                            binding_error = str(exc)
                            exposure_binding = {"task_input_sha256": None, "status": "failed_input_binding"}
                            result["status"] = "failed"
                            result.setdefault("checks", []).append({"id": "shared_task_exposure", "passed": False, "detail": binding_error})
                    result.update({key: value for key, value in cell.items() if key not in {"comparison_cohort", "task_input_sha256", "task_input_status"}})
                    if exposure_binding is not None:
                        result.update(task_input_sha256=exposure_binding["task_input_sha256"],
                                      comparison_cohort=comparison_cohort if exposure_binding["task_input_sha256"] is not None else None,
                                      task_input_status=exposure_binding["status"])
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
                    _append(observations_path, record, guard={"directory": str(output_dir), "policy": stop_policy} if stop_policy else None)
                    rows.append(record)
                    if stop_policy:
                        _attempt_stop(record, plan, product=True)
                    if binding_error is not None:
                        raise ValueError("retained attempted worker input binding failed: " + binding_error)
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
            verify_prospective_inputs()
        except _PolicyStop as exc:
            stopped = {"reason": exc.reason, "detail": exc.detail}
        except (KeyboardInterrupt, ValueError) as exc:
            if not stop_policy:
                raise
            stopped = {"reason": "owner_cancelled" if isinstance(exc, KeyboardInterrupt) else "input_binding_drift",
                       "detail": str(exc)}
        if stop_policy:
            # Empty ledgers are evidence of zero attempts, not fabricated failures.
            for path in (components_path, observations_path):
                if not path.exists():
                    with path.open("xb") as handle:
                        handle.flush()
                        os.fsync(handle.fileno())
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
        if stop_policy:
            if deadline - time.monotonic() <= 0:
                stopped = stopped or {"reason": "finalization_deadline", "detail": None}
            try:
                capacity = _capacity(output_dir, stop_policy, dispatch=False)
            except _PolicyStop as exc:
                stopped = stopped or {"reason": exc.reason, "detail": exc.detail}
                capacity = None
            report["bounded_execution"] = {
                "schema_version": "open_agronomy_agent.bounded_execution.v1",
                "status": "terminal_stopped" if stopped else "awaiting_closeout",
                "closeout_status": "unknown_until_bound_receipt",
                "disposition": "terminal_immutable",
                "stop": stopped, "policy_sha256": stop_input["sha256"], "clock": clock,
                "attempted_components": len(components), "attempted_observations": len(rows),
                "remaining_components": [kind for kind in plan["required_components"] if kind not in {r["component"] for r in components}],
                "remaining_observation_ids": [cell["observation_id"] for cell in plan["matrix"] if cell["observation_id"] not in {r["observation_id"] for r in rows}],
                "capacity_before_closeout": capacity,
                "finalization_reserve_seconds": stop_policy["finalization_reserve_seconds"],
                "clock_scope": "entry preparation, validation, dispatch, process cleanup and finalization reserve",
                "capacity_scope": "OS per-file child cap; allocated-entry/free-space polling, not an atomic aggregate filesystem quota",
                "cloud_lease_provisioning_cleanup_bounded": False,
                "model_domain_qualification_granted": False,
            }
            observed_ids = {row["observation_id"] for row in rows}
            remaining_matrix = []
            dispatched_ids = set(observed_ids)
            for cell in plan["matrix"]:
                if cell["observation_id"] in observed_ids:
                    continue
                directory = output_dir / "cells" / cell["observation_id"]
                marker = directory / "child-dispatch.json"
                disposition = "attempted_unledgered" if marker.is_file() else "prepared_dispatch_unknown" if directory.exists() else "unstarted"
                if marker.is_file():
                    dispatched_ids.add(cell["observation_id"])
                remaining_matrix.append({"observation_id": cell["observation_id"], "disposition": disposition})
            report["bounded_execution"]["remaining_matrix"] = remaining_matrix
            report["bounded_execution"]["ledgered_observations"] = len(rows)
            report["bounded_execution"]["attempted_observations"] = len(dispatched_ids)
            if stopped:
                report["status"] = "blocked"
                report["failures"]["bounded_execution_stop"] = stopped
            # Validate all final payloads and their retained manifest before any
            # terminal report is published. Interrupted publication stays refused.
            payloads = {"report.json": report, "public-summary.json": public_projection(report)}
            encoded = {name: (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
                       for name, value in payloads.items()}
            retained = retention_manifest(output_dir)
            future_files = {**retained["files"], **{name: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)} for name, raw in encoded.items()}}
            future_manifest = {**retained, "files": future_files, "files_sha256": digest(future_files),
                               "total_bytes": sum(value["bytes"] for value in future_files.values())}
            manifest_raw = (json.dumps(future_manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
            payload_bytes = [len(raw) for raw in encoded.values()] + [len(manifest_raw)]
            # Charge rounded allocated entries, not only serialized bytes.
            closeout_charge = sum(((size + 4095) // 4096) * 4096 for size in payload_bytes) + 12288
            current_allocated = sum(path.stat().st_blocks * 512 for path in output_dir.rglob("*") if path.is_file() and not path.is_symlink())
            free = os.statvfs(output_dir).f_bavail * os.statvfs(output_dir).f_frsize
            if (closeout_charge > stop_policy["finalization_reserve_bytes"]
                    or max(payload_bytes) > stop_policy["file_hardcap_bytes"]
                    or current_allocated + closeout_charge > stop_policy["retention_budget_bytes"]
                    or free - closeout_charge < stop_policy["minimum_free_bytes"]):
                raise ValueError("insufficient assigned finalization capacity; retained attempt is incomplete")
        else:
            report["bounded_execution"] = {"status": "legacy_unqualified", "bounded_qualification": False}
        write_new_json(output_dir / "report.json", report)
        write_new_json(output_dir / "public-summary.json", public_projection(report))
        write_new_json(output_dir / "retention.json", retention_manifest(output_dir))
        verify_retention(output_dir)
        if stop_policy:
            observed_remaining = deadline - time.monotonic()
            closeout = {"schema_version": "open_agronomy_agent.bounded_closeout.v1",
                "plan_sha256": plan_sha256, "policy_sha256": stop_input["sha256"],
                "report_sha256": file_digest(output_dir / "report.json"),
                "retention_sha256": file_digest(output_dir / "retention.json"),
                "clock_sha256": file_digest(clock_path),
                "status": "complete_within_deadline" if observed_remaining >= 0 else "late_blocked",
                "observed_remaining_seconds": observed_remaining,
                "scope": "all preparation, artifact writes/fsync, retained hashing and verification before this receipt; receipt persistence checked afterward"}
            closeout["record_sha256"] = digest(closeout)
            write_new_json(output_dir / "closeout.json", closeout)
            if time.monotonic() > deadline and closeout["status"] == "complete_within_deadline":
                failed = {"schema_version": "open_agronomy_agent.closeout_failure.v1",
                          "closeout_sha256": file_digest(output_dir / "closeout.json"),
                          "reason": "deadline_during_closeout_persistence"}
                failed["record_sha256"] = digest(failed)
                write_new_json(output_dir / "closeout-failure.json", failed)
            final_report = _load_retained_report(output_dir, terminal_seal_required=False)
            if time.monotonic() > deadline and closeout["status"] == "complete_within_deadline" and not (output_dir / "closeout-failure.json").exists():
                failed = {"schema_version": "open_agronomy_agent.closeout_failure.v1",
                          "closeout_sha256": file_digest(output_dir / "closeout.json"),
                          "reason": "deadline_during_final_report_verification"}
                failed["record_sha256"] = digest(failed)
                write_new_json(output_dir / "closeout-failure.json", failed)
                final_report["status"] = "blocked"
                final_report["bounded_execution"].update(status="terminal_stopped", closeout_status="late_blocked",
                    stop=final_report["bounded_execution"].get("stop") or {"reason": "finalization_deadline", "detail": None})
                final_report["failures"]["bounded_execution_stop"] = final_report["bounded_execution"]["stop"]
            remaining = deadline - time.monotonic()
            terminal = {"schema_version": "open_agronomy_agent.terminal_closeout.v1",
                        **{key: closeout[key] for key in ("plan_sha256", "policy_sha256", "report_sha256", "retention_sha256", "clock_sha256")},
                        "closeout_sha256": file_digest(output_dir / "closeout.json"),
                        "failure_sha256": file_digest(output_dir / "closeout-failure.json") if (output_dir / "closeout-failure.json").is_file() else None,
                        "observed_remaining_seconds": remaining,
                        "status": "late_blocked" if remaining < 0 or final_report["bounded_execution"]["closeout_status"] == "late_blocked" else "complete_within_deadline",
                        "scope": "final disposition after artifact, closeout persistence and final read verification; terminal seal persistence is the final durability marker"}
            terminal["record_sha256"] = digest(terminal)
            write_new_json(output_dir / "terminal-closeout.json", terminal)
            if terminal["status"] == "late_blocked":
                final_report["status"] = "blocked"
                final_report["bounded_execution"].update(status="terminal_stopped", closeout_status="late_blocked",
                    stop=final_report["bounded_execution"].get("stop") or {"reason": "finalization_deadline", "detail": None})
                final_report["failures"]["bounded_execution_stop"] = final_report["bounded_execution"]["stop"]
            final_report["bounded_execution"]["terminal_seal"] = terminal
            final_report["bounded_execution"]["terminal_seal_sha256"] = file_digest(output_dir / "terminal-closeout.json")
            return final_report
        return report
