from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agronomy_agent.paths import minimized_path_reference, repo_path


MODEL_HOST_IDENTITY_SCHEMA = "open_agronomy_agent.model_host_identity.v2"
MODEL_IDENTITY_CONTRACT_SCHEMA = "open_agronomy_agent.model_identity_contract.v1"


def sha256_path(path: str | Path) -> str:
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(path: str | Path) -> Path:
    target = Path(path)
    return target if target.is_absolute() else repo_path(target)


def _endpoint_port(endpoint: str | None) -> int | None:
    if not endpoint:
        return None
    try:
        parsed = urlparse(endpoint)
        return parsed.port
    except ValueError:
        return None


def load_model_host_identity(path: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    target = _safe_path(path)
    reference = minimized_path_reference(path)
    if not target.is_file():
        return None, f"model identity receipt is missing: {reference}"
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, (
            f"model identity receipt is unreadable: {reference} "
            f"({type(exc).__name__})"
        )
    if not isinstance(payload, dict):
        return None, "model identity receipt must be a JSON object"
    return payload, None


def model_identity_contract(
    *,
    model_id: str,
    model_revision: str | None,
    backend: str,
    model_config_path: str | Path | None,
    request_model_id: str | None = None,
    endpoint: str | None = None,
    receipt_path: str | Path | None = None,
    identity_required: bool = False,
) -> dict[str, Any]:
    config_target = _safe_path(model_config_path) if model_config_path else None
    contract: dict[str, Any] = {
        "schema_version": MODEL_IDENTITY_CONTRACT_SCHEMA,
        "status": "unverified",
        "identity_required": bool(identity_required),
        "configured_model_id": str(model_id),
        "configured_model_revision": str(model_revision or "") or None,
        "backend": str(backend),
        "request_model_id": str(request_model_id or "") or None,
        "endpoint_port": _endpoint_port(endpoint),
        "paths_minimized": True,
        "model_config_path": (
            minimized_path_reference(model_config_path) if model_config_path else None
        ),
        "model_config_sha256": (
            sha256_path(config_target) if config_target is not None and config_target.is_file() else None
        ),
        "receipt_path": minimized_path_reference(receipt_path) if receipt_path else None,
        "receipt_sha256": None,
        "response_model_id": None,
        "verification_errors": [],
    }

    if backend == "mlx_local":
        contract["status"] = "verified_direct_loader"
        contract["parametric_adaptation"] = {
            "mode": "base_only",
            "adapter_path": None,
        }
        return contract

    if backend == "mock":
        contract["status"] = "mock"
        return contract

    errors: list[str] = []
    receipt: dict[str, Any] | None = None
    if receipt_path:
        receipt, load_error = load_model_host_identity(receipt_path)
        if load_error:
            errors.append(load_error)
        else:
            receipt_target = _safe_path(receipt_path)
            contract["receipt_sha256"] = sha256_path(receipt_target)
    else:
        errors.append("model identity receipt path is not configured")

    if receipt is not None:
        if receipt.get("schema_version") != MODEL_HOST_IDENTITY_SCHEMA:
            errors.append("model identity receipt schema is not supported")
        if receipt.get("status") != "ready":
            errors.append("model identity receipt is not ready")
        if str(receipt.get("model_id") or "") != str(model_id):
            errors.append("loaded model ID does not match configured model ID")
        if model_revision and str(receipt.get("model_revision") or "") != str(model_revision):
            errors.append("loaded model revision does not match configured model revision")
        receipt_port = receipt.get("port")
        endpoint_port = _endpoint_port(endpoint)
        if endpoint_port is not None and receipt_port is not None and int(receipt_port) != endpoint_port:
            errors.append("model identity receipt port does not match generation endpoint")
        required_receipt_fields = (
            "model_config_sha256",
            "server_command_sha256",
            "model_artifact_manifest_sha256",
            "parametric_adaptation",
            "process_id",
        )
        missing = [field for field in required_receipt_fields if not receipt.get(field)]
        if missing:
            errors.append("model identity receipt is incomplete: " + ", ".join(missing))
        if contract["model_config_sha256"] and receipt.get("model_config_sha256") != contract["model_config_sha256"]:
            errors.append("model identity receipt config hash does not match application config")
        adaptation = receipt.get("parametric_adaptation")
        if (
            not isinstance(adaptation, dict)
            or adaptation.get("mode") != "base_only"
            or adaptation.get("adapter_path") is not None
        ):
            errors.append(
                "model identity receipt does not verify the base-only adaptation policy"
            )
        contract["runtime"] = {
            "model_id": receipt.get("model_id"),
            "model_revision": receipt.get("model_revision"),
            "process_id": receipt.get("process_id"),
            "port": receipt.get("port"),
            "server_command_sha256": receipt.get("server_command_sha256"),
            "model_artifact_manifest_sha256": receipt.get("model_artifact_manifest_sha256"),
            "model_artifact_file_count": receipt.get("model_artifact_file_count"),
            "parametric_adaptation": adaptation,
            "created_at": receipt.get("created_at"),
        }

    contract["verification_errors"] = errors
    if not errors:
        contract["status"] = "verified_runtime_receipt"
    elif not identity_required:
        contract["status"] = "unverified_optional"
    return contract


def bind_response_identity(contract: dict[str, Any], response_model_id: Any) -> dict[str, Any]:
    bound = dict(contract)
    bound["response_model_id"] = str(response_model_id) if response_model_id is not None else None
    return bound
