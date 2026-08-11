#!/usr/bin/env python3
"""Audit the frozen release candidate immediately before model evaluation.

This gate is deliberately model-free: it verifies local snapshots, contracts,
corpus integrity, egress authority, and deterministic interface behavior, but
does not generate or judge benchmark answers.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agronomy_agent.agent import build_context  # noqa: E402
from agronomy_agent.benchmark_contract import validate_benchmark  # noqa: E402
from agronomy_agent.corpus_governance import audit_runtime_corpora  # noqa: E402
from scripts.audit_benchmark_separation import build_audit as build_separation_audit  # noqa: E402


DEFAULT_PLAN = ROOT / "configs/final_benchmark_round_rc1.json"
DEFAULT_OUTPUT = ROOT / "outputs/pre_demo_core/final_benchmark_readiness.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    detail: str,
    evidence: dict[str, Any] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "passed": bool(passed),
            "detail": detail,
            "evidence": evidence or {},
        }
    )


def _file_record(root: Path, record: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    path = root / str(record.get("path") or record.get("contract_path") or record.get("suite_path") or "")
    expected = str(record.get("sha256") or record.get("contract_sha256") or record.get("suite_sha256") or "")
    actual = sha256(path) if path.is_file() else None
    return bool(path.is_file() and expected and actual == expected), {
        "path": str(path),
        "expected_sha256": expected or None,
        "actual_sha256": actual,
    }


def verify_public_release_receipt(root: Path) -> dict[str, Any]:
    receipt_path = root / "PUBLIC_RELEASE_RECEIPT.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "blocked", "failures": [f"unreadable_receipt:{exc}"]}
    failures: list[str] = []
    total_bytes = 0
    for row in receipt.get("files") or []:
        relative = str(row.get("path") or "")
        path = root / relative
        if not path.is_file():
            failures.append(f"missing:{relative}")
            continue
        total_bytes += path.stat().st_size
        if path.stat().st_size != int(row.get("bytes") or -1):
            failures.append(f"size_mismatch:{relative}")
        elif sha256(path) != row.get("sha256"):
            failures.append(f"hash_mismatch:{relative}")
    if total_bytes != int(receipt.get("total_bytes") or -1):
        failures.append("total_bytes_mismatch")
    if len(receipt.get("files") or []) != int(receipt.get("file_count") or -1):
        failures.append("file_count_mismatch")
    return {
        "status": "pass" if not failures else "blocked",
        "receipt_sha256": sha256(receipt_path) if receipt_path.is_file() else None,
        "file_count": len(receipt.get("files") or []),
        "total_bytes": total_bytes,
        "failures": failures,
    }


def verify_output_start_state(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    files = (
        sorted(str(item.relative_to(path)) for item in path.rglob("*") if item.is_file())
        if path.is_dir()
        else []
    )
    failures = ["benchmark_output_not_fresh"] if files or (path.exists() and not path.is_dir()) else []
    return {
        "status": "pass" if not failures else "blocked",
        "path": str(path),
        "exists": path.exists(),
        "file_count": len(files),
        "files": files[:20],
        "failures": failures,
    }


def verify_egress_authorization(
    path: Path | None,
    *,
    benchmark_id: str,
    suite_sha256: str,
    required_payloads: list[str],
    forbidden_payloads: list[str],
) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"status": "blocked", "failures": ["egress_authorization_missing"]}
    payload = json.loads(path.read_text(encoding="utf-8"))
    authorized = set(payload.get("authorized_payload_classes") or [])
    excluded = set(payload.get("excluded_payload_classes") or [])
    failures: list[str] = []
    if payload.get("schema_version") != "open_agronomy_agent.benchmark_egress_authorization.v1":
        failures.append("schema_mismatch")
    if payload.get("benchmark_id") != benchmark_id:
        failures.append("benchmark_id_mismatch")
    if payload.get("benchmark_suite_sha256") != suite_sha256:
        failures.append("suite_sha256_mismatch")
    if not set(required_payloads) <= authorized:
        failures.append("required_payload_class_missing")
    if not set(forbidden_payloads) <= excluded:
        failures.append("forbidden_payload_class_not_excluded")
    if authorized & set(forbidden_payloads):
        failures.append("forbidden_payload_class_authorized")
    return {
        "status": "pass" if not failures else "blocked",
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "authorization_source": payload.get("authorization_source"),
        "authorized_at": payload.get("authorized_at"),
        "failures": failures,
    }


def verify_local_model(root: Path, hub_cache: Path, record: dict[str, Any]) -> dict[str, Any]:
    config_path = root / str(record["config_path"])
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    model_id = str(config.get("serving_model_id") or config.get("model_id") or "")
    revision = str(config.get("model_revision") or "")
    failures: list[str] = []
    if sha256(config_path) != record.get("config_sha256"):
        failures.append("config_sha256_mismatch")
    if model_id != record.get("model_id"):
        failures.append("model_id_mismatch")
    if revision != record.get("revision"):
        failures.append("revision_mismatch")
    snapshot = hub_cache / ("models--" + model_id.replace("/", "--")) / "snapshots" / revision
    files = [path for path in snapshot.rglob("*") if path.is_file()] if snapshot.is_dir() else []
    names = {path.name for path in files}
    weights = [path for path in files if path.name.endswith((".safetensors", ".gguf", ".npz"))]
    if not snapshot.is_dir():
        failures.append("snapshot_missing")
    elif not ({"config.json", "tokenizer_config.json"} <= names):
        failures.append("model_metadata_incomplete")
    elif not ({"tokenizer.json", "tokenizer.model"} & names):
        failures.append("tokenizer_missing")
    elif not weights or not all(path.resolve().stat().st_size > 0 for path in weights):
        failures.append("weights_missing_or_empty")
    return {
        "status": "pass" if not failures else "blocked",
        "model_key": record["model_key"],
        "model_id": model_id,
        "revision": revision,
        "snapshot": str(snapshot),
        "snapshot_bytes": sum(path.resolve().stat().st_size for path in files),
        "failures": failures,
    }


def build_benchmark_command(
    plan: dict[str, Any],
    model: dict[str, Any],
    egress_authorization: Path,
) -> list[str]:
    internal = plan["internal_benchmark"]
    judge = plan["judge"]
    command = [
        "python",
        "scripts/run_open_agronomy_benchmark.py",
        "--evaluation-set",
        "internal",
        "--model-config",
        str(model["config_path"]),
        "--model-key",
        str(model["model_key"]),
        "--modes",
        ",".join(internal["arms"]),
        "--output-dir",
        str(internal["output_dir"]),
        "--judge",
        "--judge-backend",
        str(judge["backend"]),
        "--judge-model",
        str(judge["model"]),
        "--judge-reasoning-effort",
        str(judge["reasoning_effort"]),
        "--judge-roles",
        ",".join(judge["roles"]),
        "--egress-authorization",
        str(egress_authorization.resolve()),
        "--build-review-packet",
        "--resume-partial-runs",
    ]
    if model["backend"] == "codex_app_server":
        command.extend(
            [
                "--codex-app-server",
                "--reasoning-effort",
                str(model.get("reasoning_effort") or "high"),
            ]
        )
    return command


def run_interface_probes(root: Path) -> dict[str, Any]:
    config = str(root / "configs/rag_governed_runtime_v1.yaml")
    explicit = build_context(
        "For a Saskatchewan field, can an NRCS ecological site be used as a cross-border analogue for soil water and ecological dynamics?",
        config,
        use_context_cache=False,
        use_search_cache=False,
    )
    ordinary = build_context(
        "A Saskatchewan field has wet depressions and poor emergence. What should I inspect before changing drainage?",
        config,
        field_context={"crop_current": "spring wheat", "province_state": "Saskatchewan"},
        use_context_cache=False,
        use_search_cache=False,
    )
    saskatchewan_rate = build_context(
        "Set an exact nitrogen rate for my Saskatchewan spring wheat field after a wet spring.",
        config,
        field_context={"crop_current": "spring wheat", "province_state": "Saskatchewan"},
        use_context_cache=False,
        use_search_cache=False,
    )
    explicit_docs = [doc for doc in explicit.retrieved_docs if doc.transfer_scope == "cross_border_analogue"]
    ordinary_docs = [doc for doc in ordinary.retrieved_docs if doc.transfer_scope == "cross_border_analogue"]
    boundaries = list((saskatchewan_rate.runtime_metadata or {}).get("canadian_coverage_boundaries") or [])
    sk_boundary = next((row for row in boundaries if row.get("jurisdiction") == "Saskatchewan"), {})
    explicit_packed = explicit.packed_context.text if explicit.packed_context else ""
    sk_packed = saskatchewan_rate.packed_context.text if saskatchewan_rate.packed_context else ""
    return {
        "nrcs_explicit_analogue": {
            "passed": bool(explicit_docs)
            and all(doc.retrieval_policy == "context_only" for doc in explicit_docs)
            and "US CROSS-BORDER ANALOGUE" in explicit_packed
            and "never treat as Canadian field truth" in explicit_packed,
            "doc_ids": [doc.doc_id for doc in explicit_docs],
        },
        "nrcs_ordinary_canadian_exclusion": {
            "passed": not ordinary_docs,
            "unexpected_doc_ids": [doc.doc_id for doc in ordinary_docs],
        },
        "saskatchewan_fail_closed": {
            "passed": sk_boundary.get("status") == "live_reference_only"
            and sk_boundary.get("requires_prompt_boundary") is True
            and "no province-specific applied-guidance document" in sk_packed
            and not saskatchewan_rate.retrieved_docs,
            "status": sk_boundary.get("status"),
            "retrieved_doc_ids": [doc.doc_id for doc in saskatchewan_rate.retrieved_docs],
            "live_reference_source_ids": [
                row.get("source_id") for row in sk_boundary.get("live_references") or []
            ],
        },
    }


def audit(
    *,
    root: Path,
    plan_path: Path,
    hub_cache: Path,
    egress_authorization: Path | None,
) -> dict[str, Any]:
    root = root.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    _check(
        checks,
        "plan_schema",
        plan.get("schema_version") == "open_agronomy_agent.final_benchmark_round.v1",
        "final benchmark round schema is supported",
        {"path": str(plan_path), "sha256": sha256(plan_path)},
    )

    git_branch = ""
    git_head = ""
    git_porcelain = ""
    try:
        git_branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()
        git_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()
        git_porcelain = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()
        git_passed = git_branch == plan.get("release_branch") and not git_porcelain
    except (OSError, subprocess.CalledProcessError):
        git_passed = False
    _check(
        checks,
        "clean_release_commit",
        git_passed,
        "benchmark must start from the named clean branch",
        {"branch": git_branch, "head": git_head, "dirty": bool(git_porcelain)},
    )

    internal_record = plan["internal_benchmark"]
    external_record = plan["external_diagnostic"]
    internal_contract_ok, internal_contract_evidence = _file_record(root, internal_record)
    internal_suite_ok = sha256(root / internal_record["suite_path"]) == internal_record["suite_sha256"]
    internal_manifest = validate_benchmark(root, root / internal_record["contract_path"])
    _check(
        checks,
        "frozen_internal_benchmark",
        internal_contract_ok
        and internal_suite_ok
        and internal_manifest.get("rows") == internal_record["rows"]
        and internal_manifest.get("evaluation_partition") == "internal",
        "internal benchmark contract, suite, partition, and row count are frozen",
        {**internal_contract_evidence, "suite_sha256": internal_manifest.get("suite_sha256"), "rows": internal_manifest.get("rows")},
    )
    external_contract_ok, external_contract_evidence = _file_record(root, external_record)
    external_manifest = validate_benchmark(root, root / external_record["contract_path"])
    _check(
        checks,
        "held_out_external_diagnostic",
        external_contract_ok
        and external_manifest.get("suite_sha256") == external_record["suite_sha256"]
        and external_manifest.get("rows") == external_record["rows"]
        and external_manifest.get("evaluation_partition") == "public",
        "external diagnostic remains separately frozen and finalist-only",
        {**external_contract_evidence, "suite_sha256": external_manifest.get("suite_sha256"), "rows": external_manifest.get("rows")},
    )

    construct_path = root / "data/eval/open_agronomy_canadian_performance_v1_construct_audit.json"
    construct = json.loads(construct_path.read_text(encoding="utf-8"))
    _check(
        checks,
        "benchmark_construct_boundary",
        construct.get("status") == "development_construct_only"
        and construct.get("construct_verdict", {}).get("primary_capability_claim_eligible") is False
        and construct.get("current_suite", {}).get("rows") == internal_record["rows"],
        "construct audit preserves the development-only claim boundary",
        {"path": str(construct_path), "sha256": sha256(construct_path)},
    )

    separation = build_separation_audit(
        root / internal_record["contract_path"],
        root / external_record["contract_path"],
    )
    _check(
        checks,
        "internal_external_separation",
        separation.get("status") == "pass",
        "internal and external questions, sources, training data, and RAG remain separated",
        {
            "maximum_token_jaccard": separation.get("question_overlap", {}).get("maximum_token_jaccard"),
            "rag_exact_matches": separation.get("rag_contamination", {}).get("exact_public_question_match_count"),
        },
    )

    runtime = audit_runtime_corpora(
        root=root,
        rag_config_path=root / "configs/rag_governed_runtime_v1.yaml",
    )
    _check(
        checks,
        "runtime_corpus_governance",
        runtime.get("status") == "pass" and not runtime.get("errors"),
        "configured runtime corpora pass policy and hash validation",
        {"audited_corpus_count": runtime.get("audited_corpus_count"), "row_counts": runtime.get("row_counts_by_eligibility")},
    )

    retention_path = root / "data/manifests/source_retention_receipt.json"
    retention = json.loads(retention_path.read_text(encoding="utf-8"))
    _check(
        checks,
        "source_retention",
        retention.get("status") == "pass"
        and retention.get("deletion_authorized") is False
        and all(retention.get("checks", {}).values()),
        "source bytes, RAG lineage, graphs, and NRCS projection are retained and no deletion is authorized",
        {"path": str(retention_path), "sha256": sha256(retention_path)},
    )

    public_receipt = verify_public_release_receipt(root)
    _check(
        checks,
        "public_release_receipt",
        public_receipt["status"] == "pass",
        "every file in the curated public checkpoint matches its release receipt",
        public_receipt,
    )

    output_start = verify_output_start_state(root, str(internal_record["output_dir"]))
    _check(
        checks,
        "fresh_benchmark_output",
        output_start["status"] == "pass",
        "the canonical final-round output directory is absent or empty before generation",
        output_start,
    )

    disk = shutil.disk_usage(root)
    minimum_free = int(plan.get("readiness", {}).get("minimum_free_disk_bytes") or 0)
    _check(
        checks,
        "free_disk",
        disk.free >= minimum_free,
        "free disk meets the bounded benchmark-output floor",
        {"free_bytes": disk.free, "minimum_free_bytes": minimum_free},
    )
    _check(
        checks,
        "mlx_runtime",
        importlib.util.find_spec("mlx") is not None and importlib.util.find_spec("mlx_lm") is not None,
        "MLX and mlx_lm are importable in the selected Python environment",
    )

    model_receipts: list[dict[str, Any]] = []
    for model in plan["models"]:
        config_path = root / model["config_path"]
        config_ok = config_path.is_file() and sha256(config_path) == model["config_sha256"]
        if model["backend"] == "mlx_local":
            receipt = verify_local_model(root, hub_cache, model)
        else:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            receipt = {
                "status": "pass" if config_ok and config.get("model_id") == model["model_id"] else "blocked",
                "model_key": model["model_key"],
                "model_id": model["model_id"],
                "backend": model["backend"],
                "failures": [] if config_ok and config.get("model_id") == model["model_id"] else ["remote_profile_mismatch"],
            }
        model_receipts.append(receipt)
    _check(
        checks,
        "model_profiles_and_snapshots",
        all(row["status"] == "pass" for row in model_receipts),
        "all model profiles are pinned and both local snapshots are complete",
        {"hub_cache": str(hub_cache.resolve()), "models": model_receipts},
    )

    egress = verify_egress_authorization(
        egress_authorization,
        benchmark_id=str(internal_manifest["benchmark_id"]),
        suite_sha256=str(internal_manifest["suite_sha256"]),
        required_payloads=list(plan["egress"]["authorized_payload_classes_required"]),
        forbidden_payloads=list(plan["egress"]["payload_classes_forbidden"]),
    )
    _check(
        checks,
        "egress_authorization",
        egress["status"] == "pass",
        "explicit authorization covers benchmark and judge payloads while excluding private data and corpus files",
        egress,
    )

    probes = run_interface_probes(root)
    _check(
        checks,
        "release_interface_probes",
        all(row.get("passed") for row in probes.values()),
        "NRCS transfer and Saskatchewan evidence-gap behavior are fail-closed",
        probes,
    )

    commands = [
        build_benchmark_command(plan, model, egress_authorization or Path("EGRESS_AUTHORIZATION_REQUIRED"))
        for model in plan["models"]
    ]
    failures = [row for row in checks if not row["passed"]]
    return {
        "schema_version": "open_agronomy_agent.final_benchmark_readiness.v1",
        "status": "ready" if not failures else "blocked",
        "round_id": plan.get("round_id"),
        "root": str(root),
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": sha256(plan_path),
        "git_commit": git_head or None,
        "network_requests_performed": 0,
        "generation_performed": False,
        "judging_performed": False,
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
        "benchmark_commands": commands,
        "external_diagnostic_policy": plan["external_diagnostic"]["use_policy"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--hub-cache", type=Path, default=None)
    parser.add_argument("--egress-authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.root.resolve()
    plan_path = args.plan if args.plan.is_absolute() else root / args.plan
    hub_cache = args.hub_cache or Path(os.getenv("HF_HUB_CACHE") or root / ".hf_cache/hub")
    output = args.output if args.output.is_absolute() else root / args.output
    report = audit(
        root=root,
        plan_path=plan_path.resolve(),
        hub_cache=hub_cache.resolve(),
        egress_authorization=args.egress_authorization.resolve(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
