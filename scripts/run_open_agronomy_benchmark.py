#!/usr/bin/env python3
"""Canonical runner for the internal benchmark and external transfer diagnostic.

Internal results support development. The external set is a finalist-only,
non-claim transfer diagnostic and must never be used for iterative tuning on
the same frozen version. Quarantined historical sets are intentionally absent.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agronomy_agent.agent import load_yaml  # noqa: E402
from agronomy_agent.benchmark_contract import read_json, sha256, validate_benchmark  # noqa: E402
from agronomy_agent.benchmark_report import write_report  # noqa: E402
from agronomy_agent.evals import build_implementation_identity  # noqa: E402
from scripts.build_full_system_benchmark_database import build_database  # noqa: E402
from scripts.build_benchmark_cost_ledger import build_ledger  # noqa: E402


CONTRACTS = {
    "internal": ROOT / "configs" / "open_agronomy_canadian_performance_v1.json",
    "internal-legacy": ROOT / "configs" / "open_agronomy_internal_v2.json",
    # Retained only so historical commands fail with the contract's explicit
    # quarantine reason instead of an ambiguous CLI parse error.
    "public": ROOT / "configs" / "open_agronomy_public_verification_v3.json",
    "external": ROOT / "configs" / "open_agronomy_external_agroqa_v1.json",
}
LEGACY_INTERFACE_CONTRACT = ROOT / "configs" / "open_agronomy_system_interface_v1.json"
_LOCAL_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = _LOCAL_PYTHON if _LOCAL_PYTHON.is_file() else Path(sys.executable)
BENCHMARK_EXECUTABLE_SCRIPTS = (
    "scripts/run_open_agronomy_benchmark.py",
    "scripts/run_codex_semantic_answer_judge.py",
    "scripts/build_full_system_benchmark_database.py",
    "scripts/build_benchmark_cost_ledger.py",
)
ARM_CONTRACT_VERSION = "open_agronomy_agent.benchmark_arms.v2"


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_.-").lower()
    if not key:
        raise ValueError("model key is empty after normalization")
    return key


def _benchmark_source_snapshot() -> dict[str, Any]:
    """Hash the executable benchmark tree independently of Git cleanliness.

    A commit id alone is insufficient when a benchmark is intentionally run
    from a dirty engineering checkout.  The aggregate includes each relative
    path, byte length, and content digest so the receipt remains portable even
    when Git is unavailable in the packaged edge runtime.
    """

    paths = sorted((ROOT / "src" / "agronomy_agent").rglob("*.py"))
    paths.extend(ROOT / relative for relative in BENCHMARK_EXECUTABLE_SCRIPTS)
    unique_paths = sorted({path.resolve() for path in paths if path.is_file()})
    aggregate = hashlib.sha256()
    files: list[dict[str, Any]] = []
    for path in unique_paths:
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        files.append({"path": relative, "bytes": len(data), "sha256": digest})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(str(len(data)).encode("ascii"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")

    git_commit = None
    git_dirty = None
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        git_dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        pass

    return {
        "schema_version": "open_agronomy_agent.benchmark_source_snapshot.v1",
        "aggregate_sha256": aggregate.hexdigest(),
        "file_count": len(files),
        "files": files,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
    }


def _load_egress_authorization(
    path: Path | None,
    *,
    benchmark_id: str,
    benchmark_suite_sha256: str,
) -> dict[str, Any]:
    if path is None:
        raise ValueError(
            "external App Server execution of the machine-local internal benchmark requires "
            "--egress-authorization"
        )
    resolved = path.resolve()
    payload = read_json(resolved)
    if payload.get("schema_version") != "open_agronomy_agent.benchmark_egress_authorization.v1":
        raise ValueError(f"invalid benchmark egress authorization schema: {resolved}")
    if payload.get("benchmark_id") != benchmark_id:
        raise ValueError(f"egress authorization benchmark mismatch: {resolved}")
    if payload.get("benchmark_suite_sha256") != benchmark_suite_sha256:
        raise ValueError(f"egress authorization suite hash mismatch: {resolved}")
    if not payload.get("authorized_at") or not payload.get("authorization_source"):
        raise ValueError(f"egress authorization is missing provenance: {resolved}")
    return {
        "path": str(resolved),
        "sha256": sha256(resolved),
        "authorized_at": payload["authorized_at"],
        "authorization_source": payload["authorization_source"],
        "authorized_payload_classes": list(payload.get("authorized_payload_classes") or []),
    }


def _run(command: list[str], *, log_path: Path, environment: dict[str, str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(command) + "\n")
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
        log.write(f"\nexit_code={result.returncode}\n")
    if result.returncode:
        raise RuntimeError(f"benchmark command failed ({result.returncode}); see {log_path}")


def _write_invocation(experiment: Path, model_key: str, invocation: dict[str, Any]) -> None:
    """Keep the latest convenience file without erasing prior model receipts."""

    payload = json.dumps(invocation, indent=2) + "\n"
    (experiment / "benchmark_invocation.json").write_text(payload, encoding="utf-8")
    invocation_dir = experiment / "invocations"
    invocation_dir.mkdir(parents=True, exist_ok=True)
    (invocation_dir / f"{model_key}.json").write_text(payload, encoding="utf-8")


def _latest_run(root: Path, mode: str, expected_rows: int) -> Path:
    candidates: list[Path] = []
    for path in sorted(root.glob(f"{mode}_*")):
        summary = path / "summary.json"
        outputs = path / "outputs.jsonl"
        if not summary.is_file() or not outputs.is_file():
            continue
        if int(read_json(summary).get("samples") or -1) == expected_rows:
            candidates.append(path)
    if not candidates:
        raise RuntimeError(f"no complete {mode} run with {expected_rows} rows under {root}")
    return candidates[-1]


def _reusable_run(
    root: Path,
    *,
    mode: str,
    expected_rows: int,
    suite_sha256: str,
    model_id: str,
    model_config_sha256: str,
) -> Path:
    run_dir = _latest_run(root, mode, expected_rows)
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"complete run is missing identity manifest: {run_dir}")
    manifest = read_json(manifest_path)
    expected = {
        "suite_sha256": suite_sha256,
        "model_id": model_id,
        "model_config_sha256": model_config_sha256,
        "implementation": build_implementation_identity(),
    }
    mismatches = {
        key: {"expected": value, "observed": manifest.get(key)}
        for key, value in expected.items()
        if manifest.get(key) != value
    }
    outputs_path = run_dir / "outputs.jsonl"
    observed_outputs_sha256 = sha256(outputs_path)
    if manifest.get("outputs_sha256") != observed_outputs_sha256:
        mismatches["outputs_sha256"] = {
            "expected": manifest.get("outputs_sha256"),
            "observed": observed_outputs_sha256,
        }
    if mismatches:
        raise RuntimeError(f"complete run is not reusable: {run_dir}; mismatches={mismatches}")
    return run_dir


def _resumable_run(
    root: Path,
    *,
    mode: str,
    expected_rows: int,
    suite_sha256: str,
    model_id: str,
    model_config_sha256: str,
) -> Path | None:
    """Find a partial run whose substantive identity still matches exactly."""

    expected = {
        "suite_sha256": suite_sha256,
        "model_id": model_id,
        "model_config_sha256": model_config_sha256,
        "implementation": build_implementation_identity(),
    }
    for run_dir in reversed(sorted(root.glob(f"{mode}_*"))):
        partial = run_dir / "outputs.partial.jsonl"
        identity_path = run_dir / "resumable_run_identity.json"
        if not partial.is_file() or not identity_path.is_file():
            continue
        identity = read_json(identity_path)
        if any(identity.get(key) != value for key, value in expected.items()):
            continue
        rows = 0
        with partial.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"partial run has invalid JSON at {partial}:{line_number}"
                    ) from exc
                if not isinstance(row, dict):
                    raise RuntimeError(f"partial run row is not an object at {partial}:{line_number}")
                rows += 1
        if rows > expected_rows:
            raise RuntimeError(
                f"partial run has {rows} rows but benchmark expects only {expected_rows}: {run_dir}"
            )
        if rows < expected_rows:
            return run_dir
    return None


def _eval_command(
    *, args: argparse.Namespace, contract: dict[str, Any], model_config: Path,
    model_id: str, mode: str, output_dir: Path, resume_run_dir: Path | None = None,
) -> list[str]:
    command = [
        str(PYTHON), "scripts/run_eval.py", "--mode", mode,
        "--suite", str(contract["suite_path"]), "--output-dir", str(output_dir),
        "--model-config", str(model_config), "--max-tokens", str(contract["max_tokens"]),
        "--capture-context-packets",
        "--rubric", str(contract.get("rubric") or "agribench_proxy"),
        "--answer-profile", str(contract["answer_profile"]),
    ]
    if resume_run_dir is not None:
        command.extend(["--resume-run-dir", str(resume_run_dir)])
    if contract.get("evaluation_partition") != "public":
        command.append("--use-eval-field-context")
    if args.mock:
        command.append("--mock")
    else:
        command.extend(["--model", model_id])
    if mode == "agronomic_rag":
        command.extend(["--rag-config", str(contract["rag_config"])])
    if args.max_samples is not None:
        command.extend(["--max-samples", str(args.max_samples)])
    if args.model_base_url:
        command.extend(["--model-base-url", args.model_base_url, "--request-model-id", args.request_model_id])
    if args.codex_app_server:
        command.extend(["--codex-app-server", "--reasoning-effort", args.reasoning_effort])
    if args.model_identity_receipt:
        command.extend(["--model-identity-receipt", args.model_identity_receipt, "--require-model-identity"])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-set", choices=sorted(CONTRACTS), default="internal")
    parser.add_argument("--contract", type=Path, help="Advanced override for a frozen benchmark contract.")
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--model-key")
    parser.add_argument("--model")
    parser.add_argument("--modes", help="Comma-separated arm override; defaults to the frozen contract.")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--model-base-url")
    parser.add_argument(
        "--codex-app-server",
        action="store_true",
        help="Run candidate generation through the ChatGPT-authenticated Codex App Server.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default="high",
    )
    parser.add_argument("--request-model-id", default="default_model")
    parser.add_argument("--model-identity-receipt")
    parser.add_argument(
        "--egress-authorization",
        type=Path,
        help="Explicit authorization receipt required when internal benchmark data leaves the device.",
    )
    parser.add_argument("--judge", action="store_true", help="Run uncalibrated semantic triage after generation.")
    parser.add_argument(
        "--judge-backend",
        choices=["codex_app_server", "mlx_local"],
        default="codex_app_server",
    )
    parser.add_argument("--judge-model")
    parser.add_argument(
        "--judge-reasoning-effort",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default="high",
    )
    parser.add_argument(
        "--judge-roles",
        default="semantic_answer_quality",
        help=(
            "Comma-separated App Server roles: semantic_answer_quality, evidence_fidelity, "
            "agronomic_reasoning_applicability, decision_safety_uncertainty, or appeal."
        ),
    )
    parser.add_argument("--judge-batch-size", type=int, default=8)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--reuse-complete-runs",
        action="store_true",
        help=(
            "Reuse complete candidate arms in the locked experiment directory; "
            "judge batches still validate their own cached IDs before reuse."
        ),
    )
    parser.add_argument(
        "--resume-partial-runs",
        action="store_true",
        help=(
            "Resume the newest incomplete arm only when its suite, model configuration, RAG artifacts, "
            "and implementation identity match the current run exactly."
        ),
    )
    parser.add_argument(
        "--build-review-packet",
        action="store_true",
        help="Blind paired primary-lane answers for independent agronomist review.",
    )
    args = parser.parse_args()

    if args.codex_app_server and args.model_base_url:
        raise ValueError("--codex-app-server and --model-base-url are mutually exclusive")
    if args.judge_batch_size < 1:
        raise ValueError("--judge-batch-size must be at least 1")
    allowed_judge_roles = {
        "semantic_answer_quality",
        "evidence_fidelity",
        "agronomic_reasoning_applicability",
        "decision_safety_uncertainty",
        "appeal",
    }
    requested_judge_roles = {value.strip() for value in args.judge_roles.split(",") if value.strip()}
    unknown_judge_roles = sorted(requested_judge_roles - allowed_judge_roles)
    if unknown_judge_roles:
        raise ValueError(f"unknown --judge-roles: {unknown_judge_roles}")

    contract_path = (args.contract or CONTRACTS[args.evaluation_set]).resolve()
    contract = read_json(contract_path)
    interface_contract = ROOT / str(
        contract.get("system_interface_contract") or LEGACY_INTERFACE_CONTRACT.relative_to(ROOT)
    )
    if str(contract.get("status") or "").startswith(("retired_", "quarantined_")):
        raise ValueError(
            f"benchmark contract is retired or quarantined and cannot be executed: {contract.get('benchmark_id')}"
        )
    frozen = validate_benchmark(ROOT, contract_path)
    uses_external_app_server = bool(
        args.codex_app_server or (args.judge and args.judge_backend == "codex_app_server")
    )
    egress_authorization = None
    if frozen.get("evaluation_partition") == "internal" and uses_external_app_server:
        egress_authorization = _load_egress_authorization(
            args.egress_authorization,
            benchmark_id=str(frozen["benchmark_id"]),
            benchmark_suite_sha256=str(frozen["suite_sha256"]),
        )
    if contract.get("evaluation_partition") == "public":
        from scripts.audit_benchmark_separation import build_audit

        audit = build_audit(CONTRACTS["internal"], contract_path)
        if audit["status"] != "pass":
            raise ValueError("public verification is blocked because the internal/public separation audit failed")
        if args.judge and contract.get("rubric") == "multiple_choice":
            raise ValueError("the public multiple-choice verifier uses objective exact match; --judge is not allowed")
    model_config = args.model_config.resolve()
    config = load_yaml(model_config)
    model_id = str(args.model or config.get("model_id") or "mock")
    model_key = _safe_key(args.model_key or model_id)
    configured_modes = args.modes or ",".join(str(mode) for mode in contract.get("default_modes") or [])
    modes = [part.strip() for part in configured_modes.split(",") if part.strip()]
    if not modes or not set(modes).issubset({"raw_model", "baseline", "kernel_field_context", "agronomic_rag"}):
        raise ValueError(
            "--modes may contain raw_model, baseline, kernel_field_context, and/or agronomic_rag"
        )
    expected_rows = int(args.max_samples or frozen["rows"])
    experiment = (args.output_dir or (ROOT / "outputs" / str(frozen["benchmark_id"]))).resolve()
    source_snapshot = _benchmark_source_snapshot()
    arm_contract = {
        "schema_version": ARM_CONTRACT_VERSION,
        "raw_model": "user question only; no Open Agronomy kernel, retrieval, verifier, or answer post-processing",
        "baseline": "Open Agronomy kernel and answer contract; no retrieval or verifier",
        "kernel_field_context": (
            "Open Agronomy kernel plus the same admitted crop, region, jurisdiction, and management context "
            "as the full agent; no retrieval, tools, verifier, or evidence intervention"
        ),
        "agronomic_rag": "kernel, governed retrieval/evidence fabric, intervention policy, verifier when configured, and answer post-processing",
        "primary_causal_comparison": (
            "raw_model_vs_agronomic_rag"
            if "raw_model" in modes
            else contract.get("primary_comparison") or "baseline_vs_agronomic_rag"
        ),
        "kernel_ablation": "raw_model_vs_baseline",
        "field_context_increment": "baseline_vs_kernel_field_context",
        "knowledge_and_orchestration_increment": "kernel_field_context_vs_agronomic_rag",
    }
    invocation = {
        "schema_version": "open_agronomy_agent.benchmark_invocation.v1",
        "updated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "benchmark_id": frozen["benchmark_id"],
        "evaluation_partition": frozen.get("evaluation_partition"),
        "benchmark_manifest_sha256": sha256(ROOT / str(contract["manifest_path"])),
        "benchmark_suite_sha256": frozen["suite_sha256"],
        "system_interface_contract": (
            str(interface_contract)
            if contract.get("evaluation_partition") == "internal"
            else None
        ),
        "system_interface_contract_sha256": (
            sha256(interface_contract)
            if contract.get("evaluation_partition") == "internal"
            else None
        ),
        "benchmark_source_snapshot": source_snapshot,
        "model_key": model_key,
        "model_id": model_id,
        "model_revision": config.get("model_revision"),
        "model_config": str(model_config),
        "modes": modes,
        "arm_contract": arm_contract,
        "expected_rows_per_arm": expected_rows,
        "automated_judge_requested": bool(args.judge),
        "candidate_model_backend": (
            "codex_app_server_chatgpt_auth"
            if args.codex_app_server
            else "openai_compatible_http" if args.model_base_url else "mlx_local"
        ),
        "candidate_reasoning_effort": args.reasoning_effort if args.codex_app_server else None,
        "judge_backend": args.judge_backend if args.judge else None,
        "judge_roles": (
            [value.strip() for value in args.judge_roles.split(",") if value.strip()]
            if args.judge
            else []
        ),
        "egress_authorization": egress_authorization,
        "reuse_complete_runs": bool(args.reuse_complete_runs),
        "resume_partial_runs": bool(args.resume_partial_runs),
        "generation_harness_scope": "core_agent_text_only",
        "service_orchestration_exercised": False,
        "public_adapter_policy": "record_expected_but_do_not_execute_without_structured_payloads",
        "promotion_eligible": False,
        "evidence_boundary": (
            str((contract.get("evaluation_policy") or {}).get("claim_boundary") or "Public external diagnostic only.")
            if frozen.get("evaluation_partition") == "public"
            else "Project-owned internal development evidence; automated judging is triage only."
        ),
    }
    experiment.mkdir(parents=True, exist_ok=True)
    lock_path = experiment / "benchmark_lock.json"
    lock = {
        "benchmark_id": frozen["benchmark_id"],
        "benchmark_suite_sha256": frozen["suite_sha256"],
        "evaluation_partition": frozen.get("evaluation_partition"),
        "benchmark_source_snapshot_sha256": source_snapshot["aggregate_sha256"],
        "arm_contract_version": ARM_CONTRACT_VERSION,
        "system_interface_contract_sha256": invocation["system_interface_contract_sha256"],
    }
    if lock_path.is_file() and read_json(lock_path) != lock:
        raise ValueError(f"output directory is locked to a different benchmark: {lock_path}")
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_invocation(experiment, model_key, invocation)
    if args.preflight_only:
        print(json.dumps(invocation, indent=2))
        return 0

    environment = dict(os.environ)
    environment.update({"PYTHONPATH": "src", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "AGRONOMY_AGENT_PRIVATE_KNOWLEDGE": "auto"})
    completed: list[dict[str, Any]] = []
    for mode in modes:
        arm_root = experiment / "runs" / model_key / mode
        run_dir = None
        if args.reuse_complete_runs:
            try:
                run_dir = _reusable_run(
                    arm_root,
                    mode=mode,
                    expected_rows=expected_rows,
                    suite_sha256=str(frozen["suite_sha256"]),
                    model_id=model_id,
                    model_config_sha256=sha256(model_config),
                )
            except RuntimeError as exc:
                if not str(exc).startswith("no complete "):
                    raise
                run_dir = None
        if run_dir is None:
            resume_run_dir = None
            if args.resume_partial_runs:
                resume_run_dir = _resumable_run(
                    arm_root,
                    mode=mode,
                    expected_rows=expected_rows,
                    suite_sha256=str(frozen["suite_sha256"]),
                    model_id=model_id,
                    model_config_sha256=sha256(model_config),
                )
            command = _eval_command(
                args=args,
                contract=contract,
                model_config=model_config,
                model_id=model_id,
                mode=mode,
                output_dir=arm_root,
                resume_run_dir=resume_run_dir,
            )
            _run(command, log_path=arm_root / "runner.log", environment=environment)
            run_dir = _latest_run(arm_root, mode, expected_rows)
        if args.judge:
            roles = [value.strip() for value in args.judge_roles.split(",") if value.strip()]
            if not roles:
                raise ValueError("--judge-roles must contain at least one role")
            if args.judge_backend == "mlx_local" and roles != ["semantic_answer_quality"]:
                raise ValueError("the local MLX judge currently supports only semantic_answer_quality")
            for role in roles:
                judgment = run_dir / f"semantic_judge_{role}"
                if args.judge_backend == "codex_app_server":
                    judge_model = args.judge_model or "gpt-5.6-luna"
                    judge_command = [
                        str(PYTHON), "scripts/run_codex_semantic_answer_judge.py",
                        "--outputs", str(run_dir / "outputs.jsonl"),
                        "--output-dir", str(judgment),
                        "--model", judge_model,
                        "--reasoning-effort", args.judge_reasoning_effort,
                        "--judge-role", role,
                        "--transport", "app-server",
                        "--batch-size", str(args.judge_batch_size),
                    ]
                else:
                    judge_model = args.judge_model or "mlx-community/Qwen3.5-4B-MLX-4bit"
                    judge_command = [
                        str(PYTHON), "scripts/run_local_mlx_semantic_answer_judge.py",
                        "--outputs", str(run_dir / "outputs.jsonl"),
                        "--output-dir", str(judgment),
                        "--model", judge_model,
                        "--batch-size", "1",
                        "--max-tokens", "900",
                    ]
                _run(judge_command, log_path=judgment / "runner.log", environment=environment)
        completed.append({"mode": mode, "run_dir": str(run_dir)})
        build_database(experiment, experiment / "full_system_benchmark.sqlite3")
    database = build_database(experiment, experiment / "full_system_benchmark.sqlite3")
    cost_ledger = build_ledger(
        experiment,
        experiment / "cost_ledger.sqlite3",
        experiment / "cost_ledger_manifest.json",
    )
    review_packet: str | None = None
    if args.build_review_packet:
        by_mode = {row["mode"]: Path(row["run_dir"]) for row in completed}
        if not {"raw_model", "agronomic_rag"} <= set(by_mode):
            raise ValueError("--build-review-packet requires raw_model and agronomic_rag modes")
        review_dir = experiment / "review_packets" / model_key
        _run([
            str(PYTHON), "scripts/build_agronomist_answer_review_packet.py",
            "--source", f"model_only={by_mode['raw_model'] / 'outputs.jsonl'}",
            "--source", f"full_system={by_mode['agronomic_rag'] / 'outputs.jsonl'}",
            "--benchmark-lane", "canadian_decision_quality",
            "--output-dir", str(review_dir),
        ], log_path=review_dir / "builder.log", environment=environment)
        review_packet = str(review_dir / "manifest.json")
    report = write_report(experiment / "full_system_benchmark.sqlite3", frozen, experiment)
    invocation.update(
        {
            "status": "complete",
            "completed": completed,
            "database": database,
            "cost_ledger": cost_ledger,
            "report": report,
            "review_packet": review_packet,
        }
    )
    _write_invocation(experiment, model_key, invocation)
    print(json.dumps(invocation, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
