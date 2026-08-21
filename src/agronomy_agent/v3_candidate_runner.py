"""Resumable orchestration contract for the v3 competence candidate."""

from __future__ import annotations

import fcntl
import hashlib
import importlib
import json
import multiprocessing
import os
import queue
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from agronomy_agent.benchmark_arms import ALL_ARM_IDS, execution_arm


MATRIX_SCHEMA_VERSION = "open_agronomy_agent.v3_candidate_matrix.v1"
OBSERVATION_REQUEST_SCHEMA_VERSION = "open_agronomy_agent.v3_candidate_observation_request.v1"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateObservationRequest:
    schema_version: str
    observation_id: str
    benchmark_id: str
    lane: str
    eval_id: str
    model_key: str
    model_id: str
    model_revision: str | None
    backend: str
    arm: str
    trial_id: str
    sample_index: int
    case_sha256: str
    process_isolation_policy: str = "fresh_process_per_observation"
    cache_policy: str = "fresh_process_model_weights_may_reuse_provider_cache"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_matrix(
    *,
    config: Mapping[str, Any],
    external_cases: Iterable[Mapping[str, Any]],
    regional_cases: Iterable[Mapping[str, Any]],
) -> tuple[CandidateObservationRequest, ...]:
    cases_by_lane = {
        "public_external_competence_candidate": tuple(dict(row) for row in external_cases),
        "canadian_regional_competence_candidate": tuple(dict(row) for row in regional_cases),
    }
    output: list[CandidateObservationRequest] = []
    sample_index = 0
    for model in config.get("candidate_models", ()):
        for lane, arm_key in (
            ("public_external_competence_candidate", "external_arms"),
            ("canadian_regional_competence_candidate", "regional_arms"),
        ):
            for trial_id in config["trial_ids"]:
                for arm in model[arm_key]:
                    if arm not in ALL_ARM_IDS:
                        raise ValueError(f"model declares unknown candidate arm: {arm}")
                    execution_arm(str(arm))
                    for case in cases_by_lane[lane]:
                        sample_index += 1
                        case_identity = {
                            "lane": lane,
                            "eval_id": case["eval_id"],
                            "question_sha256": case.get("question_sha256") or sha256(str(case.get("question") or "")),
                        }
                        seed = {
                            "benchmark_id": config["benchmark_id"],
                            "case": case_identity,
                            "model_key": model["model_key"],
                            "model_id": model["model_id"],
                            "model_revision": model.get("model_revision"),
                            "arm": arm,
                            "trial_id": trial_id,
                        }
                        output.append(
                            CandidateObservationRequest(
                                schema_version=OBSERVATION_REQUEST_SCHEMA_VERSION,
                                observation_id=f"observation_{sha256(seed)[:24]}",
                                benchmark_id=str(config["benchmark_id"]),
                                lane=lane,
                                eval_id=str(case["eval_id"]),
                                model_key=str(model["model_key"]),
                                model_id=str(model["model_id"]),
                                model_revision=str(model["model_revision"]) if model.get("model_revision") is not None else None,
                                backend=str(model["backend"]),
                                arm=str(arm),
                                trial_id=str(trial_id),
                                sample_index=sample_index,
                                case_sha256=sha256(case_identity),
                            )
                        )
    expected = int((config.get("expected_observation_counts") or {}).get("total") or 0)
    if expected and len(output) != expected:
        raise ValueError(f"candidate matrix count mismatch: expected={expected} observed={len(output)}")
    identities = [item.observation_id for item in output]
    if len(set(identities)) != len(identities):
        raise ValueError("candidate matrix contains duplicate observation identities")
    return tuple(output)


class AppendOnlyObservationLedger:
    def __init__(self, path: Path, matrix: tuple[CandidateObservationRequest, ...]) -> None:
        self.path = path
        self.matrix = matrix
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        self._next_index: int | None = None
        self._validated_size: int | None = None

    def completed_prefix(self) -> int:
        rows = _jsonl(self.path) if self.path.stat().st_size else []
        if len(rows) > len(self.matrix):
            raise ValueError("observation ledger is longer than the frozen matrix")
        for index, row in enumerate(rows):
            if row.get("observation_id") != self.matrix[index].observation_id:
                raise ValueError("observation ledger is not an exact frozen-matrix prefix")
        self._next_index = len(rows)
        self._validated_size = self.path.stat().st_size
        return len(rows)

    def append(self, row: Mapping[str, Any]) -> None:
        expected_index = self._next_index if self._next_index is not None else self.completed_prefix()
        if expected_index >= len(self.matrix):
            raise ValueError("candidate matrix is already complete")
        if row.get("observation_id") != self.matrix[expected_index].observation_id:
            raise ValueError("executor returned an observation outside the next matrix position")
        with self.path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            current_size = self.path.stat().st_size
            if self._validated_size is None or current_size != self._validated_size:
                if self.completed_prefix() != expected_index:
                    raise RuntimeError("concurrent writer advanced the observation ledger")
            handle.write(canonical_json(dict(row)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            self._next_index = expected_index + 1
            self._validated_size = self.path.stat().st_size
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_matrix(
    *,
    matrix: tuple[CandidateObservationRequest, ...],
    ledger: AppendOnlyObservationLedger,
    executor: Callable[[CandidateObservationRequest], Mapping[str, Any]],
) -> int:
    start = ledger.completed_prefix()
    for request in matrix[start:]:
        ledger.append(dict(executor(request)))
    return len(matrix) - start


def _child_execute(executor_ref: str, request: Mapping[str, Any], result_queue: Any) -> None:
    try:
        module_name, attribute = executor_ref.split(":", 1)
        executor = getattr(importlib.import_module(module_name), attribute)
        result_queue.put({"kind": "result", "row": dict(executor(dict(request)))})
    except BaseException as exc:  # noqa: BLE001
        result_queue.put(
            {
                "kind": "error",
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
            }
        )


def execute_in_fresh_process(
    request: CandidateObservationRequest,
    *,
    executor_ref: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Execute one observation in a killable spawned process with no retry."""

    if timeout_seconds <= 0:
        raise ValueError("observation timeout must be greater than zero")
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_child_execute,
        args=(executor_ref, request.to_dict(), result_queue),
        daemon=False,
    )
    started = time.monotonic()
    process.start()
    process.join(timeout_seconds)
    cancellation = "not_required"
    if process.is_alive():
        process.terminate()
        process.join(2.0)
        cancellation = "terminated"
        if process.is_alive():
            process.kill()
            process.join(2.0)
            cancellation = "killed"
        elapsed = max(0.0, time.monotonic() - started)
        return {
            **request.to_dict(),
            "status": "terminal_failure",
            "row_disposition": "terminal_failure",
            "terminal_receipt": {
                "schema_version": "open_agronomy_agent.candidate_process_terminal_receipt.v1",
                "failed_stage": "observation_process",
                "failure_class": "timeout",
                "error_type": "ObservationTimeout",
                "timeout_seconds": timeout_seconds,
                "elapsed_seconds": elapsed,
                "cancellation": cancellation,
                "completed_stage_receipts": [],
                "pending_stages": "retained_in_child_artifacts_if_emitted",
                "partial_artifacts_retained": True,
            },
        }
    elapsed = max(0.0, time.monotonic() - started)
    try:
        message = result_queue.get_nowait()
    except queue.Empty:
        message = {
            "kind": "error",
            "error_type": "ChildProcessExit",
            "error": f"child exited {process.exitcode} without a result",
        }
    if message.get("kind") == "result":
        row = dict(message["row"])
        if row.get("observation_id") != request.observation_id:
            raise ValueError("child executor returned a mismatched observation identity")
        return row
    return {
        **request.to_dict(),
        "status": "terminal_failure",
        "row_disposition": "terminal_failure",
        "terminal_receipt": {
            "schema_version": "open_agronomy_agent.candidate_process_terminal_receipt.v1",
            "failed_stage": "observation_process",
            "failure_class": "error",
            "error_type": str(message.get("error_type") or "ChildProcessError"),
            "error": str(message.get("error") or "")[:1000],
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": elapsed,
            "cancellation": cancellation,
            "completed_stage_receipts": [],
            "pending_stages": "retained_in_child_artifacts_if_emitted",
            "partial_artifacts_retained": True,
        },
    }


def matrix_manifest(matrix: tuple[CandidateObservationRequest, ...]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in matrix:
        key = f"{item.model_key}:{item.lane}"
        counts[key] = counts.get(key, 0) + 1
    record = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "observation_count": len(matrix),
        "counts": counts,
        "first_observation_id": matrix[0].observation_id if matrix else None,
        "last_observation_id": matrix[-1].observation_id if matrix else None,
        "observation_ids_sha256": sha256([item.observation_id for item in matrix]),
        "claim_eligible": False,
    }
    return {**record, "manifest_sha256": sha256(record)}


__all__ = ["AppendOnlyObservationLedger", "CandidateObservationRequest", "build_matrix", "execute_in_fresh_process", "matrix_manifest", "run_matrix"]
