"""Frozen backend entry point for the Mac desktop application.

The launcher supplies only absolute resource and state paths. All model downloads
are explicit setup operations; serving resolves an already verified snapshot.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


MODEL_RECEIPT_SCHEMA = "open_agronomy_agent.desktop_model_install.v1"
RUNTIME_MANIFEST_SCHEMA = "open_agronomy_agent.macos_app_runtime.v1"
MODEL_ASSET_MANIFEST = "configs/model_assets_gemma4_e2b_mlx.json"
MODEL_ASSET_MANIFEST_SHA256 = "20eb23b66581b7d61ea66cb9d79f84a9f18de95844b96089a64ff814b06ee238"
MIN_DOWNLOAD_FREE_BYTES = 6 * 1024**3


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _absolute_directory(path: Path, *, label: str, create: bool = False) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"{label} must be a directory")
    return resolved


def _configure_runtime(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    runtime_root = _absolute_directory(args.runtime_root, label="runtime root")
    if not (runtime_root / "configs/runtime_profiles.json").is_file():
        raise ValueError("runtime root is missing the active profile registry")
    if not (runtime_root / "frontend/dist/index.html").is_file():
        raise ValueError("runtime root is missing the built frontend")
    if args.require_bundle_manifest:
        verify_runtime_manifest(runtime_root)
    state_root = _absolute_directory(args.state_root, label="state root", create=True)
    stat = state_root.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise ValueError("desktop state root must be owned by this user and accessible only to them")
    model_cache = _absolute_directory(
        args.model_cache or state_root / "models/hub",
        label="model cache",
        create=True,
    )
    desktop_secrets = {
        "AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN",
        "AGRONOMY_AGENT_DESKTOP_SESSION_SECRET",
    }
    for key in tuple(os.environ):
        if (key.startswith("AGRONOMY_AGENT_") and key not in desktop_secrets) or key.startswith("HF_"):
            os.environ.pop(key)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)
    os.environ["AGRONOMY_AGENT_RUNTIME_ROOT"] = str(runtime_root)
    os.environ["AGRONOMY_AGENT_MODEL_BACKEND"] = "mlx"
    os.environ["AGRONOMY_AGENT_MODEL_CONFIG"] = "configs/model.yaml"
    os.environ["AGRONOMY_AGENT_RAG_CONFIG"] = "configs/rag.yaml"
    os.environ["AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH"] = "false"
    os.environ["AGRONOMY_AGENT_GEO_CACHE_DIR"] = str(state_root / "cache/geo")
    os.environ["AGRONOMY_AGENT_AGNO_INDEX_CACHE_DIR"] = str(state_root / "cache/agno_lexical_index")
    os.environ["AGRONOMY_AGENT_TOOL_CACHE_ROOT"] = str(state_root / "cache/public_tools")
    os.environ["AGRONOMY_AGENT_SPATIAL_PACK_ROOT"] = str(state_root / "spatial-pack")
    os.environ["HF_HOME"] = str(model_cache.parent)
    os.environ["HF_HUB_CACHE"] = str(model_cache)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.chdir(runtime_root)
    return runtime_root, state_root, model_cache


def verify_runtime_manifest(runtime_root: Path) -> dict[str, Any]:
    manifest_path = runtime_root.parent / "runtime-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != RUNTIME_MANIFEST_SCHEMA:
        raise ValueError("unsupported desktop runtime manifest")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("desktop runtime manifest has no files")
    actual: list[dict[str, Any]] = []
    for path in sorted(runtime_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"desktop runtime contains a symlink: {path}")
        if path.is_file():
            actual.append(
                {
                    "path": path.relative_to(runtime_root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    if actual != entries:
        raise ValueError("desktop runtime files differ from the bundled manifest")
    contract = hashlib.sha256(
        "\n".join(f"{row['path']} {row['sha256']}" for row in actual).encode("utf-8")
    ).hexdigest()
    if manifest.get("contract_sha256") != contract:
        raise ValueError("desktop runtime contract digest mismatch")
    return manifest


def _model_contract(runtime_root: Path) -> tuple[str, str, str]:
    import yaml

    config_path = runtime_root / "configs/model.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    model_id = str(config.get("serving_model_id") or config.get("model_id") or "").strip()
    revision = str(config.get("model_revision") or "").strip()
    if not model_id or len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("active desktop model must have an exact Hugging Face revision")
    return model_id, revision, _sha256(config_path)


def _expected_model_files(runtime_root: Path, model_id: str, revision: str) -> list[dict[str, Any]]:
    path = runtime_root / MODEL_ASSET_MANIFEST
    if _sha256(path) != MODEL_ASSET_MANIFEST_SHA256:
        raise ValueError("pinned model asset manifest bytes do not match the reviewed version")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != "open_agronomy_agent.pinned_model_assets.v1"
        or manifest.get("repo_id") != model_id
        or manifest.get("revision") != revision
    ):
        raise ValueError("pinned model asset manifest conflicts with the active model config")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("pinned model asset manifest has no files")
    expected: list[dict[str, Any]] = []
    names: set[str] = set()
    for row in files:
        if not isinstance(row, dict):
            raise ValueError("pinned model asset manifest contains an invalid file entry")
        name = row.get("path")
        size = row.get("bytes")
        digest = row.get("sha256")
        if (
            not isinstance(name, str)
            or not name
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or name in names
            or not isinstance(size, int)
            or size <= 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("pinned model asset manifest contains an invalid file entry")
        names.add(name)
        expected.append({"path": name, "bytes": size, "sha256": digest})
    return sorted(expected, key=lambda row: row["path"])


def _snapshot(model_id: str, revision: str) -> Path:
    from agronomy_agent.agent import resolve_local_model_snapshot

    snapshot = resolve_local_model_snapshot(model_id, revision=revision)
    if snapshot.name != revision:
        raise ValueError("local model snapshot does not match the pinned revision")
    return snapshot


def _snapshot_files(snapshot: Path, model_cache: Path) -> list[dict[str, Any]]:
    cache_root = model_cache.resolve()
    rows: list[dict[str, Any]] = []
    for path in sorted(snapshot.rglob("*")):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(cache_root):
            raise ValueError(f"model snapshot file escapes the selected cache: {path}")
        rows.append(
            {
                "path": path.relative_to(snapshot).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not rows:
        raise ValueError("model snapshot contains no files")
    return rows


def _receipt_path(state_root: Path) -> Path:
    return state_root / "receipts/model-install.json"


def _record_model_mismatch(
    state_root: Path, *, expected: list[dict[str, Any]], observed: list[dict[str, Any]] | None,
    reason: str,
) -> None:
    path = state_root / "receipts/model-install-attempts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    row = {
        "schema_version": "open_agronomy_agent.desktop_model_install_attempt.v1",
        "observed_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "status": "rejected",
        "reason": reason,
        "expected": expected,
        "observed": observed,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    path.chmod(0o600)


def _write_receipt(state_root: Path, receipt: dict[str, Any]) -> None:
    path = _receipt_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def verify_model_receipt(runtime_root: Path, state_root: Path, model_cache: Path) -> dict[str, Any]:
    path = _receipt_path(state_root)
    if not path.is_file():
        raise ValueError("model has not been installed through desktop setup")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    model_id, revision, config_sha256 = _model_contract(runtime_root)
    expected_files = _expected_model_files(runtime_root, model_id, revision)
    expected = {
        "schema_version": MODEL_RECEIPT_SCHEMA,
        "model_id": model_id,
        "revision": revision,
        "model_config_sha256": config_sha256,
        "model_asset_manifest_sha256": MODEL_ASSET_MANIFEST_SHA256,
        "files": expected_files,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("model install receipt does not match the active model contract")
    actual_files = _snapshot_files(_snapshot(model_id, revision), model_cache)
    if actual_files != expected_files:
        raise ValueError("model snapshot bytes differ from the pinned asset manifest")
    return receipt


def install_model(runtime_root: Path, state_root: Path, model_cache: Path) -> dict[str, Any]:
    model_id, revision, config_sha256 = _model_contract(runtime_root)
    expected_files = _expected_model_files(runtime_root, model_id, revision)
    force_download = False
    try:
        snapshot = _snapshot(model_id, revision)
        observed_files = _snapshot_files(snapshot, model_cache)
        if observed_files != expected_files:
            _record_model_mismatch(
                state_root, expected=expected_files, observed=observed_files,
                reason="cached snapshot did not match pinned asset identities",
            )
            force_download = True
    except RuntimeError:
        _record_model_mismatch(
            state_root, expected=expected_files, observed=None,
            reason="local pinned snapshot is absent or incomplete",
        )
        snapshot = None
    if snapshot is None or force_download:
        free = shutil.disk_usage(model_cache).free
        if free < MIN_DOWNLOAD_FREE_BYTES:
            raise ValueError(
                f"model download needs at least {MIN_DOWNLOAD_FREE_BYTES // 1024**3} GiB free "
                f"in the selected cache; observed {free // 1024**3} GiB"
            ) from None
        from huggingface_hub import snapshot_download

        print(json.dumps({"phase": "downloading", "model_id": model_id, "revision": revision,
                          "repairing_cache": force_download}), flush=True)
        try:
            snapshot_download(
                repo_id=model_id, revision=revision, cache_dir=str(model_cache),
                force_download=force_download,
            )
        except Exception as exc:
            raise RuntimeError(
                "pinned model download failed; check the connection and retry setup"
            ) from exc
        snapshot = _snapshot(model_id, revision)
    files = _snapshot_files(snapshot, model_cache)
    if files != expected_files:
        _record_model_mismatch(
            state_root, expected=expected_files, observed=files,
            reason="downloaded snapshot did not match pinned asset identities",
        )
        raise ValueError("model snapshot differs from the pinned public file identities")
    receipt = {
        "schema_version": MODEL_RECEIPT_SCHEMA,
        "model_id": model_id,
        "revision": revision,
        "model_config_sha256": config_sha256,
        "model_asset_manifest_sha256": MODEL_ASSET_MANIFEST_SHA256,
        "files": expected_files,
    }
    _write_receipt(state_root, receipt)
    return {"phase": "ready", "model_id": model_id, "revision": revision, "file_count": len(files)}


def serve(runtime_root: Path, state_root: Path, model_cache: Path, *, port: int) -> int:
    if not 1024 <= port <= 65535:
        raise ValueError("desktop port must be between 1024 and 65535")
    token = os.environ.get("AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN", "")
    secret = os.environ.get("AGRONOMY_AGENT_DESKTOP_SESSION_SECRET", "")
    if len(token) < 32 or len(secret) < 32:
        raise ValueError("desktop pairing token and session secret are required")
    verify_model_receipt(runtime_root, state_root, model_cache)
    from scripts.run_cockpit import main as run_cockpit

    sys.argv = [
        "run_cockpit.py",
        "--desktop-local",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--db-path",
        str(state_root / "db/open-agronomy.sqlite3"),
        "--artifact-root",
        str(state_root / "artifacts"),
        "--static-dir",
        str(runtime_root / "frontend/dist"),
        "--model-config",
        "configs/model.yaml",
    ]
    return run_cockpit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "install-model", "serve"))
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path)
    parser.add_argument("--require-bundle-manifest", action="store_true")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args(argv)
    try:
        runtime_root, state_root, model_cache = _configure_runtime(args)
        if args.command == "status":
            try:
                receipt = verify_model_receipt(runtime_root, state_root, model_cache)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                print(json.dumps({"phase": "setup_required", "detail": str(exc)}))
                return 0
            print(json.dumps({"phase": "ready", "model_id": receipt["model_id"], "revision": receipt["revision"]}))
            return 0
        if args.command == "install-model":
            print(json.dumps(install_model(runtime_root, state_root, model_cache)))
            return 0
        return serve(runtime_root, state_root, model_cache, port=args.port)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"phase": "error", "detail": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
