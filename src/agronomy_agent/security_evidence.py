from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable


IMPLEMENTATION_BINDING_SCHEMA = (
    "open_agronomy_agent.security_evidence_implementation_binding.v1"
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def build_implementation_binding(
    relative_paths: Iterable[str],
    *,
    root: Path = REPO_ROOT,
) -> dict[str, Any]:
    root = root.resolve()
    normalized = _normalized_paths(relative_paths)
    files: list[dict[str, Any]] = []
    for relative in normalized:
        candidate = root / relative
        path = candidate.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"implementation evidence path escapes the repository: {relative}"
            ) from exc
        if candidate.is_symlink() or not path.is_file():
            raise FileNotFoundError(
                f"implementation evidence must be a regular file: {relative}"
            )
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "schema_version": IMPLEMENTATION_BINDING_SCHEMA,
        "files": files,
    }


def validate_implementation_binding(
    payload: Any,
    *,
    expected_paths: Iterable[str],
    root: Path = REPO_ROOT,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError("implementation binding must be an object")
    if set(payload) != {"schema_version", "files"}:
        raise ValueError("implementation binding keys do not match the supported schema")
    if payload.get("schema_version") != IMPLEMENTATION_BINDING_SCHEMA:
        raise ValueError("implementation binding schema is unsupported")
    expected = _normalized_paths(expected_paths)
    files = payload.get("files")
    if not isinstance(files, list):
        raise ValueError("implementation binding files must be an array")
    observed_paths = [
        str(row.get("path") or "") if isinstance(row, dict) else ""
        for row in files
    ]
    if observed_paths != expected:
        raise ValueError(
            "implementation binding file set does not match the required control"
        )
    current = build_implementation_binding(expected, root=root)
    if files != current["files"]:
        raise ValueError(
            "implementation binding is stale or does not match the current checkout"
        )


def _normalized_paths(relative_paths: Iterable[str]) -> list[str]:
    normalized: set[str] = set()
    for value in relative_paths:
        path = Path(str(value))
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"unsafe implementation evidence path: {value}")
        normalized.add(path.as_posix())
    if not normalized:
        raise ValueError("implementation evidence path set must not be empty")
    return sorted(normalized)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
