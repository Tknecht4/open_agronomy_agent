#!/usr/bin/env python3
"""Build and verify the curated public-review repository tree.

The source checkout remains untouched. The destination must be absent or
empty, which makes the operation reversible and prevents accidental mixing
with historical files or another repository.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "configs/public_repository_manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _excluded(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def _collect(manifest: dict[str, Any]) -> list[Path]:
    exclusions = [str(value) for value in manifest.get("exclude_globs") or []]
    files: set[Path] = set()
    for value in manifest.get("paths") or []:
        path = (ROOT / str(value)).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"public repository input is missing: {value}")
        files.add(path)
    for value in manifest.get("trees") or []:
        tree = (ROOT / str(value)).resolve()
        if not tree.is_dir():
            raise FileNotFoundError(f"public repository tree is missing: {value}")
        for path in tree.rglob("*"):
            if path.is_file() and not path.is_symlink():
                relative = _relative(path)
                if not _excluded(relative, exclusions):
                    files.add(path.resolve())
    for pattern in manifest.get("globs") or []:
        matched = [path.resolve() for path in ROOT.glob(str(pattern)) if path.is_file()]
        if not matched:
            raise FileNotFoundError(f"public repository glob matched no files: {pattern}")
        files.update(matched)
    return sorted(files, key=_relative)


def _validate_scope(files: list[Path], manifest: dict[str, Any]) -> None:
    maximum = int(manifest.get("maximum_file_bytes") or 99_000_000)
    forbidden = [str(value) for value in manifest.get("forbidden_release_prefixes") or []]
    exceptions = [str(value) for value in manifest.get("allowed_forbidden_prefix_exceptions") or []]
    errors: list[str] = []
    for path in files:
        relative = _relative(path)
        if path.stat().st_size > maximum:
            errors.append(f"oversized:{relative}:{path.stat().st_size}")
        for prefix in forbidden:
            if relative.startswith(prefix) and not any(relative.startswith(value) for value in exceptions):
                errors.append(f"forbidden_prefix:{relative}")
    if errors:
        raise ValueError("invalid public repository scope: " + ", ".join(errors[:20]))


def _regenerate_runtime_manifest(destination: Path) -> None:
    """Bind the generated manifest to the curated tree, not the source checkout."""

    builder_path = destination / "scripts/build_edge_runtime_manifest.py"
    if not builder_path.is_file():
        return
    destination_src = str(destination / "src")
    if destination_src not in sys.path:
        sys.path.insert(0, destination_src)
    spec = importlib.util.spec_from_file_location(
        "_public_edge_runtime_manifest_builder",
        builder_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runtime manifest builder: {builder_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime_manifest = module.build_manifest(destination)
    output = destination / "container/runtime_manifest.json"
    output.write_text(json.dumps(runtime_manifest, indent=2) + "\n", encoding="utf-8")


def build(destination: Path, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "open_agronomy_agent.public_repository_manifest.v1":
        raise ValueError("unsupported public repository manifest schema")
    destination = destination.resolve()
    if destination == ROOT.resolve() or ROOT.resolve().is_relative_to(destination):
        raise ValueError("destination must not contain the source repository")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"destination must be absent or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    files = _collect(manifest)
    _validate_scope(files, manifest)

    for source in files:
        relative = _relative(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    _regenerate_runtime_manifest(destination)

    records: list[dict[str, Any]] = []
    total_bytes = 0
    for source in files:
        relative = _relative(source)
        target = destination / relative
        size = target.stat().st_size
        total_bytes += size
        records.append({"path": relative, "bytes": size, "sha256": _sha256(target)})

    receipt = {
        "schema_version": "open_agronomy_agent.public_repository_receipt.v1",
        "release_id": manifest["release_id"],
        "built_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "manifest_path": _relative(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "file_count": len(records),
        "total_bytes": total_bytes,
        "files": records,
    }
    receipt_path = destination / "PUBLIC_RELEASE_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["receipt_sha256"] = _sha256(receipt_path)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--print-files", action="store_true")
    args = parser.parse_args()
    receipt = build(args.destination, args.manifest.resolve())
    output = receipt if args.print_files else {
        key: value for key, value in receipt.items() if key != "files"
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
