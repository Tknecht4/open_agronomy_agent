from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SIGNATURE_SCHEMA = "open_agronomy_agent.detached_artifact_signature.v1"


def _openssl() -> str:
    executable = shutil.which("openssl")
    if not executable:
        raise RuntimeError("OpenSSL is required for detached artifact signatures")
    return executable


def _validate_private_key_file(private_key: Path) -> None:
    if not private_key.is_file():
        raise FileNotFoundError(private_key)
    key_stat = private_key.stat()
    if not stat.S_ISREG(key_stat.st_mode):
        raise ValueError("private key must be a regular file")
    mode = stat.S_IMODE(key_stat.st_mode)
    if mode & 0o077:
        raise PermissionError(
            f"private key permissions must not grant group or other access: {oct(mode)}"
        )


def sign_manifest(
    *,
    manifest: Path,
    private_key: Path,
    signature: Path,
    replace_existing: bool = False,
) -> dict[str, Any]:
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    _validate_private_key_file(private_key)
    signature.parent.mkdir(parents=True, exist_ok=True)
    if signature.exists() and not replace_existing:
        raise FileExistsError(
            f"refusing to overwrite existing detached signature: {signature}"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=signature.parent,
        prefix=f".{signature.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_signature = Path(temporary_name)
    try:
        result = subprocess.run(
            [
                _openssl(),
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(private_key),
                "-in",
                str(manifest),
                "-out",
                str(temporary_signature),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"artifact signing failed: {result.stderr.strip()}")
        temporary_signature.chmod(0o644)
        with temporary_signature.open("rb") as handle:
            os.fsync(handle.fileno())
        if replace_existing:
            os.replace(temporary_signature, signature)
        else:
            os.link(temporary_signature, signature)
    finally:
        temporary_signature.unlink(missing_ok=True)
    return {
        "schema_version": SIGNATURE_SCHEMA,
        "status": "signed",
        "manifest": str(manifest.resolve()),
        "signature": str(signature.resolve()),
        "algorithm": "Ed25519",
    }


def verify_manifest_signature(*, manifest: Path, public_key: Path, signature: Path) -> dict[str, Any]:
    if not manifest.is_file():
        raise FileNotFoundError(manifest)
    if not public_key.is_file():
        raise FileNotFoundError(public_key)
    if not signature.is_file():
        raise FileNotFoundError(signature)
    result = subprocess.run(
        [
            _openssl(),
            "pkeyutl",
            "-verify",
            "-rawin",
            "-pubin",
            "-inkey",
            str(public_key),
            "-in",
            str(manifest),
            "-sigfile",
            str(signature),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "schema_version": SIGNATURE_SCHEMA,
        "status": "verified" if result.returncode == 0 else "invalid",
        "verified": result.returncode == 0,
        "manifest": str(manifest.resolve()),
        "signature": str(signature.resolve()),
        "public_key": str(public_key.resolve()),
        "algorithm": "Ed25519",
        "detail": (result.stdout or result.stderr).strip(),
    }
