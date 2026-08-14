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
from scripts.build_benchmark_retention_bundle import (  # noqa: E402
    OUTER_COMPLETION_RECEIPT,
    build_retention_bundle,
)


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
    "scripts/run_local_mlx_semantic_answer_judge.py",
    "scripts/build_full_system_benchmark_database.py",
    "scripts/build_benchmark_cost_ledger.py",
)
ARM_CONTRACT_VERSION = "open_agronomy_agent.benchmark_arms.v2"
TRIAL_INVOCATION_IDENTITY_KEYS = (
    "benchmark_id",
    "evaluation_partition",
    "benchmark_manifest_sha256",
    "benchmark_suite_sha256",
    "system_interface_contract_sha256",
    "benchmark_source_snapshot_sha256",
    "model_id",
    "model_revision",
    "model_config_sha256",
    "modes",
    "arm_contract",
    "expected_rows_per_arm",
    "replication_contract",
    "effective_generation_config",
    "candidate_model_backend",
    "candidate_reasoning_effort",
    "automated_judge_requested",
    "judge_backend",
    "judge_model_id",
    "judge_reasoning_effort",
    "judge_roles",
    "generation_harness_scope",
)


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_.-").lower()
    if not key:
        raise ValueError("model key is empty after normalization")
    return key


def _nested_value(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _replication_expectations(
    args: argparse.Namespace,
    config: dict[str, Any],
) -> dict[str, Any]:
    configured_seed = config.get("seed")
    generation_seed = (
        args.generation_seed if args.generation_seed is not None else configured_seed
    )
    verification_config = config.get("answer_verification") or {}
    verification_seed = (
        args.verification_seed
        if args.verification_seed is not None
        else verification_config.get("seed", generation_seed)
    )
    return {
        "replication_contract.trial_id": args.trial_id,
        "replication_contract.generation_seed": generation_seed,
        "replication_contract.verification_seed": verification_seed,
        "replication_contract.judge_seed": args.judge_seed,
        "replication_contract.case_order.case_order_seed": args.case_order_seed,
        "replication_contract.process_isolation_policy": args.process_isolation_policy,
        "replication_contract.cache_contract.policy": args.cache_policy,
        "generation_config.temperature": (
            args.temperature if args.temperature is not None else float(config.get("temperature", 0.0))
        ),
        "generation_config.top_p": (
            args.top_p if args.top_p is not None else float(config.get("top_p", 0.9))
        ),
        "generation_config.top_k": (
            args.top_k if args.top_k is not None else int(config.get("top_k", 0))
        ),
    }


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
    if payload.get("schema_version") != "open_agronomy_agent.benchmark_egress_authorization.v2":
        raise ValueError(f"invalid benchmark egress authorization schema: {resolved}")
    if payload.get("authorization_decision") != "authorized":
        raise ValueError(f"benchmark egress authorization is not authorized: {resolved}")
    if payload.get("benchmark_id") != benchmark_id:
        raise ValueError(f"egress authorization benchmark mismatch: {resolved}")
    if payload.get("benchmark_suite_sha256") != benchmark_suite_sha256:
        raise ValueError(f"egress authorization suite hash mismatch: {resolved}")
    authorization_source = str(payload.get("authorization_source") or "").strip()
    authorized_by_key_id = str(payload.get("authorized_by_key_id") or "").strip()
    placeholder_markers = ("replace-with", "placeholder", "template", "example")
    if (
        not authorization_source
        or not authorized_by_key_id
        or any(marker in authorization_source.lower() for marker in placeholder_markers)
        or any(marker in authorized_by_key_id.lower() for marker in placeholder_markers)
    ):
        raise ValueError(f"egress authorization is missing non-placeholder provenance: {resolved}")

    def parse_utc(field: str) -> dt.datetime:
        raw = str(payload.get(field) or "").strip()
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"egress authorization has invalid {field}: {resolved}") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
            raise ValueError(f"egress authorization {field} must be UTC: {resolved}")
        return parsed.astimezone(dt.UTC)

    authorized_at = parse_utc("authorized_at")
    expires_at = parse_utc("expires_at")
    checked_at = dt.datetime.now(dt.UTC)
    if authorized_at > checked_at:
        raise ValueError(f"egress authorization is not yet valid: {resolved}")
    if expires_at <= checked_at or expires_at <= authorized_at:
        raise ValueError(f"egress authorization is expired or has an invalid interval: {resolved}")
    raw_authorized_payload_classes = payload.get("authorized_payload_classes")
    raw_excluded_payload_classes = payload.get("excluded_payload_classes")
    if (
        not isinstance(raw_authorized_payload_classes, list)
        or not raw_authorized_payload_classes
        or any(
            not isinstance(value, str) or not value.strip()
            for value in raw_authorized_payload_classes
        )
    ):
        raise ValueError(f"egress authorization has no authorized payload classes: {resolved}")
    if raw_excluded_payload_classes is not None and (
        not isinstance(raw_excluded_payload_classes, list)
        or any(
            not isinstance(value, str) or not value.strip()
            for value in raw_excluded_payload_classes
        )
    ):
        raise ValueError(f"egress authorization has invalid excluded payload classes: {resolved}")
    authorized_payload_classes = [value.strip() for value in raw_authorized_payload_classes]
    excluded_payload_classes = [value.strip() for value in (raw_excluded_payload_classes or [])]
    if len(set(authorized_payload_classes)) != len(authorized_payload_classes):
        raise ValueError(f"egress authorization has duplicate authorized payload classes: {resolved}")
    if len(set(excluded_payload_classes)) != len(excluded_payload_classes):
        raise ValueError(f"egress authorization has duplicate excluded payload classes: {resolved}")
    return {
        "path": str(resolved),
        "sha256": sha256(resolved),
        "authorization_decision": "authorized",
        "authorized_at": authorized_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "authorization_source": authorization_source,
        "authorized_by_key_id": authorized_by_key_id,
        "authorized_payload_classes": authorized_payload_classes,
        "excluded_payload_classes": excluded_payload_classes,
    }


def _run(command: list[str], *, log_path: Path, environment: dict[str, str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(command) + "\n")
        result = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
        log.write(f"\nexit_code={result.returncode}\n")
    if result.returncode:
        raise RuntimeError(f"benchmark command failed ({result.returncode}); see {log_path}")


def _write_invocation(
    experiment: Path,
    model_key: str,
    invocation: dict[str, Any],
    *,
    allow_completed_reuse: bool = False,
) -> None:
    """Keep the latest convenience file without erasing prior model receipts."""

    payload = json.dumps(invocation, indent=2) + "\n"
    invocation_dir = experiment / "invocations"
    invocation_dir.mkdir(parents=True, exist_ok=True)
    replication = invocation.get("replication_contract") or {}
    trial_key = _safe_key(str(replication.get("trial_id") or "legacy-trial-000"))
    durable_path = invocation_dir / f"{model_key}__{trial_key}.json"
    preserve_completed_durable_receipt = False
    if durable_path.is_file():
        existing = read_json(durable_path)
        for identity_key in TRIAL_INVOCATION_IDENTITY_KEYS:
            if existing.get(identity_key) != invocation.get(identity_key):
                raise ValueError(
                    f"trial invocation identity changed for {durable_path}: {identity_key}"
                )
        if existing.get("status") == "execution_complete" and invocation.get("status") != "execution_complete":
            if not allow_completed_reuse:
                raise ValueError(
                    f"trial invocation is already complete: {durable_path}; use --reuse-complete-runs"
                )
            preserve_completed_durable_receipt = True
    if not preserve_completed_durable_receipt:
        durable_path.write_text(payload, encoding="utf-8")
    (experiment / "benchmark_invocation.json").write_text(payload, encoding="utf-8")


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
    identity_expectations: dict[str, Any] | None = None,
) -> Path:
    expected = {
        "suite_sha256": suite_sha256,
        "model_id": model_id,
        "model_config_sha256": model_config_sha256,
        "implementation": build_implementation_identity(),
    }
    candidates: list[Path] = []
    for run_dir in reversed(sorted(root.glob(f"{mode}_*"))):
        summary_path = run_dir / "summary.json"
        outputs_path = run_dir / "outputs.jsonl"
        manifest_path = run_dir / "run_manifest.json"
        if not summary_path.is_file() or not outputs_path.is_file() or not manifest_path.is_file():
            continue
        if int(read_json(summary_path).get("samples") or -1) != expected_rows:
            continue
        candidates.append(run_dir)
        manifest = read_json(manifest_path)
        mismatches = {
            key: {"expected": value, "observed": manifest.get(key)}
            for key, value in expected.items()
            if manifest.get(key) != value
        }
        for key, value in (identity_expectations or {}).items():
            observed = _nested_value(manifest, key)
            if observed != value:
                mismatches[key] = {"expected": value, "observed": observed}
        observed_outputs_sha256 = sha256(outputs_path)
        if manifest.get("outputs_sha256") != observed_outputs_sha256:
            mismatches["outputs_sha256"] = {
                "expected": manifest.get("outputs_sha256"),
                "observed": observed_outputs_sha256,
            }
        if not mismatches:
            return run_dir
    if not candidates:
        raise RuntimeError(f"no complete {mode} run with {expected_rows} rows under {root}")
    raise RuntimeError(
        f"no complete {mode} run matches the requested trial/sampling identity under {root}"
    )


def _resumable_run(
    root: Path,
    *,
    mode: str,
    expected_rows: int,
    suite_sha256: str,
    model_id: str,
    model_config_sha256: str,
    identity_expectations: dict[str, Any] | None = None,
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
        if any(
            _nested_value(identity, key) != value
            for key, value in (identity_expectations or {}).items()
        ):
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
        "--trial-id", args.trial_id,
        "--process-isolation-policy", args.process_isolation_policy,
        "--cache-policy", args.cache_policy,
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
    for option, value in (
        ("--generation-seed", args.generation_seed),
        ("--verification-seed", args.verification_seed),
        ("--case-order-seed", args.case_order_seed),
        ("--judge-seed", args.judge_seed),
        ("--temperature", args.temperature),
        ("--top-p", args.top_p),
        ("--top-k", args.top_k),
    ):
        if value is not None:
            command.extend([option, str(value)])
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
    parser.add_argument(
        "--trial-id",
        default="trial-000",
        help="Stable trial identity shared by every requested benchmark arm.",
    )
    parser.add_argument("--generation-seed", type=int)
    parser.add_argument("--verification-seed", type=int)
    parser.add_argument("--case-order-seed", type=int)
    parser.add_argument("--judge-seed", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--top-p", type=float)
    parser.add_argument("--top-k", type=int)
    parser.add_argument(
        "--process-isolation-policy",
        choices=["shared_process", "fresh_process_per_run"],
        default="fresh_process_per_run",
        help="Each arm is normally launched in its own fresh evaluator process.",
    )
    parser.add_argument(
        "--cache-policy",
        choices=["as_configured", "no_prompt_cache"],
        default="as_configured",
    )
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
    parser.add_argument(
        "--retention-root",
        type=Path,
        default=ROOT / "outputs" / "benchmark_retention",
        help=(
            "Private content-addressed retention root. A successful run is not marked complete "
            "until the canonical database and public-safe derivative verify here."
        ),
    )
    args = parser.parse_args()

    if args.codex_app_server and args.model_base_url:
        raise ValueError("--codex-app-server and --model-base-url are mutually exclusive")
    if not args.trial_id.strip() or len(args.trial_id.strip()) > 128:
        raise ValueError("--trial-id must contain between 1 and 128 characters")
    if args.temperature is not None and args.temperature < 0:
        raise ValueError("--temperature must be non-negative")
    if args.top_p is not None and not 0 <= args.top_p <= 1:
        raise ValueError("--top-p must be between 0 and 1")
    if args.top_k is not None and args.top_k < 0:
        raise ValueError("--top-k must be non-negative")
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
        (not args.mock and args.codex_app_server)
        or (args.judge and args.judge_backend == "codex_app_server")
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
    identity_expectations = _replication_expectations(args, config)
    identity_expectations["generation_config.max_tokens"] = int(contract["max_tokens"])
    identity_expectations["answer_profile"] = str(contract["answer_profile"])
    identity_expectations["rubric"] = str(contract.get("rubric") or "agribench_proxy")
    model_id = str(args.model or config.get("model_id") or "mock")
    model_key = _safe_key(args.model_key or model_id)
    candidate_model_backend = (
        "mock"
        if args.mock
        else "codex_app_server_chatgpt_auth"
        if args.codex_app_server
        else "openai_compatible_http"
        if args.model_base_url
        else "mlx_local"
    )
    candidate_sampling_contract = {
        "mlx_local": {
            "sampling_parameters": "applied_by_native_mlx_sampler",
            "generation_seed": "applied_before_each_serialized_generation",
        },
        "openai_compatible_http": {
            "sampling_parameters": "sent_in_openai_compatible_request",
            "generation_seed": "not_sent_backend_contract_has_no_seed_field",
        },
        "codex_app_server_chatgpt_auth": {
            "sampling_parameters": "not_configurable_by_backend",
            "generation_seed": "not_configurable_by_backend",
        },
        "mock": {
            "sampling_parameters": "not_applicable_mock",
            "generation_seed": "not_applicable_mock",
        },
    }[candidate_model_backend]
    effective_judge_model = (
        args.judge_model
        or (
            "mlx-community/Qwen3.5-4B-MLX-4bit"
            if args.judge_backend == "mlx_local"
            else "gpt-5.6-luna"
        )
        if args.judge
        else None
    )
    expected_run_model_id = "mock" if args.mock else model_id
    identity_expectations["model_backend"] = candidate_model_backend
    identity_expectations["request_model_id"] = (
        None
        if args.mock
        else model_id
        if args.codex_app_server
        else args.request_model_id
        if args.model_base_url
        else None
    )
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
        "benchmark_source_snapshot_sha256": source_snapshot["aggregate_sha256"],
        "model_key": model_key,
        "model_id": model_id,
        "model_revision": config.get("model_revision"),
        "model_config": str(model_config),
        "model_config_sha256": sha256(model_config),
        "modes": modes,
        "arm_contract": arm_contract,
        "expected_rows_per_arm": expected_rows,
        "replication_contract": {
            "schema_version": "open_agronomy_agent.benchmark_replication_request.v1",
            "trial_id": args.trial_id,
            "generation_seed": identity_expectations["replication_contract.generation_seed"],
            "verification_seed": identity_expectations["replication_contract.verification_seed"],
            "case_order_seed": args.case_order_seed,
            "judge_seed": args.judge_seed,
            "process_isolation_policy": args.process_isolation_policy,
            "cache_policy": args.cache_policy,
            "sampling_overrides": {
                "temperature": args.temperature,
                "top_p": args.top_p,
                "top_k": args.top_k,
            },
            "candidate_sampling_backend_contract": candidate_sampling_contract,
            "judge_seed_application": (
                "applied_by_local_mlx_judge"
                if args.judge and args.judge_backend == "mlx_local" and args.judge_seed is not None
                else "unsupported_by_codex_app_server"
                if args.judge and args.judge_backend == "codex_app_server" and args.judge_seed is not None
                else "not_requested"
            ),
        },
        "effective_generation_config": {
            "max_tokens": int(contract["max_tokens"]),
            "temperature": identity_expectations["generation_config.temperature"],
            "top_p": identity_expectations["generation_config.top_p"],
            "top_k": identity_expectations["generation_config.top_k"],
        },
        "automated_judge_requested": bool(args.judge),
        "candidate_model_backend": candidate_model_backend,
        "candidate_reasoning_effort": args.reasoning_effort if args.codex_app_server else None,
        "judge_backend": args.judge_backend if args.judge else None,
        "judge_model_id": effective_judge_model,
        "judge_reasoning_effort": args.judge_reasoning_effort if args.judge else None,
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
    _write_invocation(
        experiment,
        model_key,
        invocation,
        allow_completed_reuse=bool(args.reuse_complete_runs),
    )
    if args.preflight_only:
        print(json.dumps(invocation, indent=2))
        return 0

    environment = dict(os.environ)
    environment.update({"PYTHONPATH": "src", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "AGRONOMY_AGENT_PRIVATE_KNOWLEDGE": "auto"})
    completed: list[dict[str, Any]] = []
    for mode in modes:
        arm_root = experiment / "runs" / model_key / mode
        arm_identity_expectations = {**identity_expectations, "mode": mode}
        run_dir = None
        if args.reuse_complete_runs:
            try:
                run_dir = _reusable_run(
                    arm_root,
                    mode=mode,
                    expected_rows=expected_rows,
                    suite_sha256=str(frozen["suite_sha256"]),
                    model_id=expected_run_model_id,
                    model_config_sha256=sha256(model_config),
                    identity_expectations=arm_identity_expectations,
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
                    model_id=expected_run_model_id,
                    model_config_sha256=sha256(model_config),
                    identity_expectations=arm_identity_expectations,
                )
            command = _eval_command(
                args=args,
                contract=contract,
                model_config=model_config,
                model_id=expected_run_model_id,
                mode=mode,
                output_dir=arm_root,
                resume_run_dir=resume_run_dir,
            )
            _run(command, log_path=arm_root / "runner.log", environment=environment)
            run_dir = _reusable_run(
                arm_root,
                mode=mode,
                expected_rows=expected_rows,
                suite_sha256=str(frozen["suite_sha256"]),
                model_id=expected_run_model_id,
                model_config_sha256=sha256(model_config),
                identity_expectations=arm_identity_expectations,
            )
        if args.judge:
            roles = [value.strip() for value in args.judge_roles.split(",") if value.strip()]
            if not roles:
                raise ValueError("--judge-roles must contain at least one role")
            if args.judge_backend == "mlx_local" and roles != ["semantic_answer_quality"]:
                raise ValueError("the local MLX judge currently supports only semantic_answer_quality")
            for role in roles:
                judgment = run_dir / f"semantic_judge_{role}"
                if args.judge_backend == "codex_app_server":
                    judge_model = str(effective_judge_model)
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
                    judge_model = str(effective_judge_model)
                    judge_command = [
                        str(PYTHON), "scripts/run_local_mlx_semantic_answer_judge.py",
                        "--outputs", str(run_dir / "outputs.jsonl"),
                        "--output-dir", str(judgment),
                        "--model", judge_model,
                        "--batch-size", "1",
                        "--max-tokens", "900",
                    ]
                    if args.judge_seed is not None:
                        judge_command.extend(["--seed", str(args.judge_seed)])
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
    source_snapshot = _benchmark_source_snapshot()
    invocation.update(
        {
            "status": "execution_complete",
            "completed": completed,
            "database": database,
            "cost_ledger": cost_ledger,
            "report": report,
            "review_packet": review_packet,
            "retention_status": "pending",
            "implementation_source_snapshot": source_snapshot,
        }
    )
    # Freeze the terminal execution receipt before retention.  The immutable
    # bundle therefore captures the actual completed experiment rather than an
    # earlier in-progress invocation.
    _write_invocation(
        experiment,
        model_key,
        invocation,
        allow_completed_reuse=bool(args.reuse_complete_runs),
    )
    terminal_invocation_sha256 = sha256(experiment / "benchmark_invocation.json")
    retention = build_retention_bundle(
        database=experiment / "full_system_benchmark.sqlite3",
        bundle_root=args.retention_root,
        experiment_dir=experiment,
        implementation_commit=str(source_snapshot.get("git_commit") or "not_captured"),
    )
    if retention.get("status") != "verified":
        raise RuntimeError("benchmark retention verification did not complete")
    completion = {
        "schema_version": "open_agronomy_agent.benchmark_retention_completion.v1",
        "status": "complete",
        "benchmark_id": frozen["benchmark_id"],
        "model_key": model_key,
        "terminal_invocation_sha256": terminal_invocation_sha256,
        "retention": retention,
        "boundary": (
            "This outer receipt binds the terminal execution receipt to its immutable retention bundle. "
            "It is excluded from that bundle's self-identity by construction."
        ),
    }
    (experiment / OUTER_COMPLETION_RECEIPT).write_text(
        json.dumps(completion, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(completion, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
