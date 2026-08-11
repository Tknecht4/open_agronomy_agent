#!/usr/bin/env python3
"""Run the frozen paired local-model baseline/full-system benchmark matrix."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agronomy_agent.paths import repo_path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_full_system_benchmark_database import build_database  # noqa: E402


DEFAULT_MATRIX = ROOT / "configs" / "full_system_benchmark_matrix_v1.json"
DEFAULT_OUTPUT = ROOT / "outputs" / "full_system_model_matrix_20260801"
PYTHON = ROOT / ".venv" / "bin" / "python"
JUDGE_MODEL = "mlx-community/Qwen3.5-4B-MLX-4bit"
JUDGE_REVISION = "32f3e8ecf65426fc3306969496342d504bfa13f3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_matrix(matrix_path: Path) -> dict[str, Any]:
    matrix = read_json(matrix_path)
    suite = matrix.get("suite") or {}
    suite_path = repo_path(str(suite.get("path") or ""))
    if not suite_path.is_file() or sha256(suite_path) != suite.get("sha256"):
        raise ValueError("frozen suite path or SHA-256 does not match the matrix")
    rows = read_jsonl(suite_path)
    if len(rows) != int(suite.get("rows") or -1) or len({row.get("eval_id") for row in rows}) != len(rows):
        raise ValueError("frozen suite row count or eval IDs are invalid")
    if suite.get("claim_eligible") is not False:
        raise ValueError("this development benchmark must remain non-claim-eligible")
    for arm in matrix.get("arms") or []:
        config_path = repo_path(str(arm.get("model_config") or ""))
        config = _load_simple_yaml(config_path)
        if config.get("model_id") != arm.get("model_id"):
            raise ValueError(f"model ID mismatch for {arm.get('id')}")
        if config.get("model_revision") != arm.get("model_revision"):
            raise ValueError(f"model revision mismatch for {arm.get('id')}")
        _validate_cached_snapshot(str(arm["model_id"]), str(arm["model_revision"]))
    return matrix


def _load_simple_yaml(path: Path) -> dict[str, Any]:
    from agronomy_agent.agent import load_yaml

    return load_yaml(path)


def _validate_cached_snapshot(model_id: str, revision: str) -> None:
    from huggingface_hub import snapshot_download

    snapshot = Path(snapshot_download(model_id, revision=revision, local_files_only=True))
    required = ("config.json", "tokenizer.json")
    missing = [name for name in required if not (snapshot / name).is_file()]
    if not any(snapshot.glob("*.safetensors")):
        missing.append("*.safetensors")
    if missing:
        raise ValueError(f"incomplete cached model snapshot {model_id}@{revision}: {missing}")


def _completed_run(arm_root: Path, mode: str, expected_rows: int) -> Path | None:
    valid: list[Path] = []
    for run_dir in sorted(arm_root.glob(f"{mode}_*")):
        outputs = run_dir / "outputs.jsonl"
        summary_path = run_dir / "summary.json"
        if not outputs.is_file() or not summary_path.is_file():
            continue
        summary = read_json(summary_path)
        if (
            int(summary.get("samples") or -1) == expected_rows
            and summary.get("context_packet_capture") is True
            and len(read_jsonl(outputs)) == expected_rows
        ):
            valid.append(run_dir)
    return valid[-1] if valid else None


def _resumable_run(arm_root: Path, mode: str, expected_rows: int) -> Path | None:
    candidates: list[Path] = []
    for run_dir in sorted(arm_root.glob(f"{mode}_*")):
        partial = run_dir / "outputs.partial.jsonl"
        if partial.is_file() and not (run_dir / "outputs.jsonl").is_file():
            count = len(read_jsonl(partial))
            if 0 <= count < expected_rows:
                candidates.append(run_dir)
    return candidates[-1] if candidates else None


def run_command(command: list[str], *, log_path: Path, environment: dict[str, str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(command) + "\n")
        log.flush()
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        log.write(f"\nexit_code={result.returncode}\n")
    if result.returncode != 0:
        raise RuntimeError(f"command failed with exit code {result.returncode}; see {log_path}")


def arm_command(
    *,
    arm: dict[str, Any],
    mode: str,
    matrix: dict[str, Any],
    output_root: Path,
    resume_dir: Path | None,
    max_samples: int | None,
) -> list[str]:
    command = [
        str(PYTHON),
        "scripts/run_eval.py",
        "--mode",
        mode,
        "--suite",
        str(matrix["suite"]["path"]),
        "--output-dir",
        str(output_root.relative_to(ROOT)),
        "--model-config",
        str(arm["model_config"]),
        "--model",
        str(arm["model_id"]),
        "--max-tokens",
        str(matrix["max_tokens"]),
        "--use-eval-field-context",
        "--capture-context-packets",
        "--rubric",
        "agribench_proxy",
        "--answer-profile",
        str(matrix["answer_profile"]),
    ]
    if mode == "agronomic_rag":
        command.extend(["--rag-config", str(matrix["rag_config"])])
    if resume_dir is not None:
        command.extend(["--resume-run-dir", str(resume_dir.relative_to(ROOT))])
    if max_samples is not None:
        command.extend(["--max-samples", str(max_samples)])
    return command


def judge_run(run_dir: Path, *, overwrite: bool, environment: dict[str, str]) -> None:
    judgment_dir = run_dir / "semantic_judge"
    summary_path = judgment_dir / "summary.json"
    if summary_path.is_file() and int(read_json(summary_path).get("row_count") or 0) == 45 and not overwrite:
        return
    command = [
        str(PYTHON),
        "scripts/run_local_mlx_semantic_answer_judge.py",
        "--outputs",
        str((run_dir / "outputs.jsonl").relative_to(ROOT)),
        "--output-dir",
        str(judgment_dir.relative_to(ROOT)),
        "--model",
        JUDGE_MODEL,
        "--model-revision",
        JUDGE_REVISION,
        "--batch-size",
        "1",
        "--max-tokens",
        "900",
        "--shared-cache-dir",
        str((run_dir.parents[3] / "semantic_judge_cache").relative_to(ROOT)),
    ]
    if overwrite:
        command.append("--overwrite")
    run_command(command, log_path=judgment_dir / "runner.log", environment=environment)


def status_manifest(
    *,
    matrix_path: Path,
    matrix: dict[str, Any],
    experiment_dir: Path,
    selected_arms: list[dict[str, Any]],
    modes: list[str],
) -> dict[str, Any]:
    expected_rows = int(matrix["suite"]["rows"])
    arms: list[dict[str, Any]] = []
    for arm in selected_arms:
        for mode in modes:
            root = experiment_dir / "runs" / str(arm["id"]) / mode
            completed = _completed_run(root, mode, expected_rows)
            arms.append(
                {
                    "model_key": arm["id"],
                    "model_id": arm["model_id"],
                    "model_revision": arm["model_revision"],
                    "mode": mode,
                    "status": "complete" if completed else "pending",
                    "run_dir": str(completed.relative_to(ROOT)) if completed else None,
                    "semantic_judge": (
                        "complete"
                        if completed is not None and (completed / "semantic_judge" / "summary.json").is_file()
                        else "pending"
                    ),
                }
            )
    return {
        "schema_version": "open_agronomy_agent.full_system_model_matrix_run.v1",
        "updated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "status": "complete" if all(row["status"] == "complete" for row in arms) else "in_progress",
        "distribution_scope": "machine_local_private_benchmark_only",
        "matrix_path": str(matrix_path.relative_to(ROOT)),
        "matrix_sha256": sha256(matrix_path),
        "suite": matrix["suite"],
        "arms": arms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--models", help="Comma-separated matrix arm IDs; default is all arms.")
    parser.add_argument("--modes", default="baseline,agronomic_rag")
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--overwrite-judgments", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    matrix_path = args.matrix.resolve()
    matrix = validate_matrix(matrix_path)
    requested_models = {value.strip() for value in str(args.models or "").split(",") if value.strip()}
    selected_arms = [
        arm for arm in matrix["arms"] if not requested_models or str(arm["id"]) in requested_models
    ]
    if requested_models - {str(arm["id"]) for arm in selected_arms}:
        raise ValueError(f"unknown model arm IDs: {sorted(requested_models - {str(arm['id']) for arm in selected_arms})}")
    modes = [value.strip() for value in args.modes.split(",") if value.strip()]
    if not modes or not set(modes).issubset({"baseline", "agronomic_rag"}):
        raise ValueError("--modes must contain baseline and/or agronomic_rag")
    experiment_dir = args.output_dir.resolve()
    experiment_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = experiment_dir / "experiment_manifest.json"
    atomic_json(
        manifest_path,
        status_manifest(
            matrix_path=matrix_path,
            matrix=matrix,
            experiment_dir=experiment_dir,
            selected_arms=selected_arms,
            modes=modes,
        ),
    )
    if args.preflight_only:
        print(manifest_path)
        return 0
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONPATH": "src",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HOME": str(Path.home() / ".cache" / "huggingface"),
            "HF_HUB_CACHE": str(Path.home() / ".cache" / "huggingface" / "hub"),
            "AGRONOMY_AGENT_PRIVATE_KNOWLEDGE": "auto",
        }
    )
    expected_rows = args.max_samples or int(matrix["suite"]["rows"])
    for arm in selected_arms:
        for mode in modes:
            arm_root = experiment_dir / "runs" / str(arm["id"]) / mode
            completed = _completed_run(arm_root, mode, expected_rows)
            if completed is None:
                resume = _resumable_run(arm_root, mode, expected_rows)
                command = arm_command(
                    arm=arm,
                    mode=mode,
                    matrix=matrix,
                    output_root=arm_root,
                    resume_dir=resume,
                    max_samples=args.max_samples,
                )
                run_command(command, log_path=arm_root / "runner.log", environment=environment)
                completed = _completed_run(arm_root, mode, expected_rows)
                if completed is None:
                    raise RuntimeError(f"arm completed without a valid run: {arm['id']} {mode}")
            build_database(experiment_dir, experiment_dir / "full_system_benchmark.sqlite3")
            if args.judge:
                judge_run(completed, overwrite=args.overwrite_judgments, environment=environment)
                build_database(experiment_dir, experiment_dir / "full_system_benchmark.sqlite3")
            atomic_json(
                manifest_path,
                status_manifest(
                    matrix_path=matrix_path,
                    matrix=matrix,
                    experiment_dir=experiment_dir,
                    selected_arms=selected_arms,
                    modes=modes,
                ),
            )
    database_report = build_database(experiment_dir, experiment_dir / "full_system_benchmark.sqlite3")
    atomic_json(experiment_dir / "database_manifest.json", database_report)
    final = status_manifest(
        matrix_path=matrix_path,
        matrix=matrix,
        experiment_dir=experiment_dir,
        selected_arms=selected_arms,
        modes=modes,
    )
    final["database"] = database_report
    atomic_json(manifest_path, final)
    print(json.dumps(final, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
