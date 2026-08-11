#!/usr/bin/env python3
"""Validate the portable OCI archive used by Apple Container and Docker."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


REQUIRED_ENV = {
    "AGRONOMY_AGENT_DB_PATH=/state/db/open-agronomy.sqlite3",
    "AGRONOMY_AGENT_STATIC_DIR=/app/frontend/dist",
    "AGRONOMY_AGENT_MODEL_BACKEND=mlx_http",
    "AGRONOMY_AGENT_TOOL_CACHE_ROOT=/state/cache/public_tools",
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe archive member: {member.name}")
        if member.isfile():
            members[str(path)] = member
    return members


def _read_member(archive: tarfile.TarFile, members: dict[str, tarfile.TarInfo], name: str) -> bytes:
    member = members.get(name)
    if member is None:
        raise ValueError(f"OCI archive is missing {name}")
    handle = archive.extractfile(member)
    if handle is None:
        raise ValueError(f"OCI archive member is unreadable: {name}")
    return handle.read()


def _read_blob(
    archive: tarfile.TarFile,
    members: dict[str, tarfile.TarInfo],
    descriptor: dict[str, Any],
) -> bytes:
    digest = str(descriptor.get("digest") or "")
    algorithm, separator, value = digest.partition(":")
    if separator != ":" or algorithm != "sha256" or len(value) != 64:
        raise ValueError(f"unsupported OCI descriptor digest: {digest}")
    payload = _read_member(archive, members, f"blobs/sha256/{value}")
    if _sha256_bytes(payload) != value:
        raise ValueError(f"OCI blob digest mismatch: {digest}")
    expected_size = descriptor.get("size")
    if expected_size is not None and len(payload) != int(expected_size):
        raise ValueError(f"OCI blob size mismatch: {digest}")
    return payload


def validate_archive(
    archive_path: Path,
    *,
    expected_version: str,
    expected_runtime_manifest_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []
    platform: dict[str, str] = {}
    config: dict[str, Any] = {}
    manifest: dict[str, Any] = {}
    layer_count = 0
    verified_blob_count = 0

    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            members = _safe_members(archive)
            layout = json.loads(_read_member(archive, members, "oci-layout"))
            if layout.get("imageLayoutVersion") != "1.0.0":
                errors.append("OCI layout version must be 1.0.0")
            index = json.loads(_read_member(archive, members, "index.json"))
            descriptors = index.get("manifests") or []
            if len(descriptors) != 1:
                errors.append("release archive must contain exactly one image manifest")
            else:
                descriptor = descriptors[0]
                platform = descriptor.get("platform") or {}
                while True:
                    payload = _read_blob(archive, members, descriptor)
                    verified_blob_count += 1
                    document = json.loads(payload)
                    children = document.get("manifests") or []
                    if not children:
                        manifest = document
                        break
                    if len(children) != 1:
                        raise ValueError("release archive must resolve to exactly one platform image")
                    descriptor = children[0]
                    platform = descriptor.get("platform") or platform
                config_payload = _read_blob(archive, members, manifest.get("config") or {})
                verified_blob_count += 1
                config = json.loads(config_payload)
                for layer in manifest.get("layers") or []:
                    _read_blob(archive, members, layer)
                    verified_blob_count += 1
                layer_count = len(manifest.get("layers") or [])
    except (OSError, tarfile.TarError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    image_config = config.get("config") or {}
    labels = image_config.get("Labels") or {}
    env = set(image_config.get("Env") or [])
    if platform.get("os") != "linux" or platform.get("architecture") != "arm64":
        errors.append("release platform must be linux/arm64")
    if labels.get("org.opencontainers.image.version") != expected_version:
        errors.append("OCI image version label does not match the requested release")
    if labels.get("io.openagronomy.runtime-manifest-sha256") != expected_runtime_manifest_sha256:
        errors.append("OCI runtime-manifest label does not match the packaged manifest")
    missing_env = sorted(REQUIRED_ENV - env)
    if missing_env:
        errors.append("OCI image is missing runtime environment entries: " + ", ".join(missing_env))
    if image_config.get("Entrypoint") != ["/app/container/entrypoint.sh"]:
        errors.append("OCI image entrypoint does not match the release contract")
    if "/state" not in (image_config.get("Volumes") or {}):
        errors.append("OCI image does not declare the /state persistence volume")
    if "8080/tcp" not in (image_config.get("ExposedPorts") or {}):
        errors.append("OCI image does not expose the application port")

    return {
        "schema_version": "open_agronomy_agent.edge_oci_archive_validation.v1",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "archive": str(archive_path),
        "archive_bytes": archive_path.stat().st_size if archive_path.is_file() else 0,
        "archive_sha256": _sha256_file(archive_path) if archive_path.is_file() else None,
        "platform": platform,
        "layer_count": layer_count,
        "verified_blob_count": verified_blob_count,
        "image_version": labels.get("org.opencontainers.image.version"),
        "runtime_manifest_sha256": labels.get("io.openagronomy.runtime-manifest-sha256"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--runtime-manifest-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate_archive(
        args.archive.resolve(),
        expected_version=args.version,
        expected_runtime_manifest_sha256=args.runtime_manifest_sha256,
    )
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
