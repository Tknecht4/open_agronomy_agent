#!/usr/bin/env python3
"""Write an atomic identity receipt for the native MLX model host."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shlex
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.model_identity import (
    MODEL_HOST_IDENTITY_SCHEMA,
    minimized_path_reference,
    sha256_path,
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _hub_model_dir(cache_root: Path, model_id: str) -> Path:
    return cache_root / ("models--" + model_id.replace("/", "--"))


def _snapshot_manifest(cache_root: Path, model_id: str, revision: str) -> dict[str, Any]:
    model_dir = _hub_model_dir(cache_root, model_id)
    snapshot = model_dir / "snapshots" / revision
    if not snapshot.is_dir():
        ref = model_dir / "refs" / "main"
        if ref.is_file():
            resolved = ref.read_text(encoding="utf-8").strip()
            if revision and resolved != revision:
                raise ValueError(
                    f"cached model revision {resolved} does not match configured revision {revision}"
                )
            snapshot = model_dir / "snapshots" / resolved
    if not snapshot.is_dir():
        raise FileNotFoundError(f"cached model snapshot is missing: {snapshot}")

    files: list[dict[str, Any]] = []
    for path in sorted(item for item in snapshot.rglob("*") if item.is_file()):
        resolved = path.resolve()
        files.append(
            {
                "path": str(path.relative_to(snapshot)),
                "bytes": resolved.stat().st_size,
                "blob_id": resolved.name,
            }
        )
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return {
        "model_artifact_manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "model_artifact_file_count": len(files),
        "model_artifact_bytes": sum(int(item["bytes"]) for item in files),
    }


def build_receipt(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.model_config).resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    configured_id = str(config.get("serving_model_id") or config.get("model_id") or "")
    if configured_id != args.model_id:
        raise ValueError(
            f"model host ID {args.model_id} does not match serving model {configured_id} "
            f"in {minimized_path_reference(config_path)}"
        )
    revision = str(args.model_revision or config.get("model_revision") or "")
    if not revision:
        raise ValueError("model revision is required for a verified model-host receipt")
    artifact = _snapshot_manifest(Path(args.hub_cache).resolve(), args.model_id, revision)
    command = str(args.server_command).strip()
    if not command:
        raise ValueError("server command is required")
    adapter_config_keys = {
        "adapter",
        "adapters",
        "adapter_path",
        "lora_adapter",
        "lora_adapter_path",
    }
    configured_adapter_keys = sorted(adapter_config_keys.intersection(config))
    if configured_adapter_keys:
        raise ValueError(
            "global model config requests parametric adaptation: "
            + ", ".join(configured_adapter_keys)
        )
    command_tokens = shlex.split(command)
    adapter_flags = {"--adapter-path", "--adapter_path", "--adapter"}
    adapter_arguments = [
        token
        for token in command_tokens
        if token in adapter_flags
        or any(token.startswith(flag + "=") for flag in adapter_flags)
    ]
    if adapter_arguments:
        raise ValueError(
            "global model server command requests an adapter: "
            + ", ".join(adapter_arguments)
        )
    return {
        "schema_version": MODEL_HOST_IDENTITY_SCHEMA,
        "status": "ready",
        "created_at": _now(),
        "model_id": args.model_id,
        "model_revision": revision,
        "paths_minimized": True,
        "model_config_path": minimized_path_reference(config_path),
        "model_config_sha256": sha256_path(config_path),
        "server_command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "parametric_adaptation": {
            "mode": "base_only",
            "adapter_path": None,
            "decision": "do_not_start_new_global_lora",
        },
        "process_id": int(args.process_id),
        "bind": args.bind,
        "port": int(args.port),
        "endpoint": f"http://{args.bind}:{int(args.port)}/v1",
        **artifact,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-config", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-revision")
    parser.add_argument("--hub-cache", required=True)
    parser.add_argument("--process-id", required=True, type=int)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--server-command", required=True)
    args = parser.parse_args()
    receipt = build_receipt(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
