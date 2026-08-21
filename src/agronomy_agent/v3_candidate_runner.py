"""Resumable orchestration contract for the v3 competence candidate."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


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

    def completed_prefix(self) -> int:
        rows = _jsonl(self.path) if self.path.stat().st_size else []
        if len(rows) > len(self.matrix):
            raise ValueError("observation ledger is longer than the frozen matrix")
        for index, row in enumerate(rows):
            if row.get("observation_id") != self.matrix[index].observation_id:
                raise ValueError("observation ledger is not an exact frozen-matrix prefix")
        return len(rows)

    def append(self, row: Mapping[str, Any]) -> None:
        expected_index = self.completed_prefix()
        if expected_index >= len(self.matrix):
            raise ValueError("candidate matrix is already complete")
        if row.get("observation_id") != self.matrix[expected_index].observation_id:
            raise ValueError("executor returned an observation outside the next matrix position")
        with self.path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            if self.completed_prefix() != expected_index:
                raise RuntimeError("concurrent writer advanced the observation ledger")
            handle.write(canonical_json(dict(row)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
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


__all__ = ["AppendOnlyObservationLedger", "CandidateObservationRequest", "build_matrix", "matrix_manifest", "run_matrix"]
