#!/usr/bin/env python3
"""Read-only hash check of a separately restored historical raw experiment tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path


def digest(path: Path) -> tuple[int, str]:
    size = 0
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            sha.update(chunk)
    return size, sha.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--expected-catalog-sha256", required=True)
    parser.add_argument("--root", type=Path, required=True,
                        help="existing private restore root, containing docs/reviews/artifacts")
    args = parser.parse_args()
    expected = args.expected_catalog_sha256.lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        parser.error("expected catalog SHA-256 must be 64 lowercase hex digits")
    catalog_bytes = args.catalog.read_bytes()
    if hashlib.sha256(catalog_bytes).hexdigest() != expected:
        parser.error("public catalog differs from the independently pinned SHA-256")
    catalog = json.loads(catalog_bytes)
    files = catalog.get("files")
    if (catalog.get("schema_version") != "open_agronomy_agent.private_experiment_catalog.v1"
            or not isinstance(files, list) or len(files) != 22):
        parser.error("unexpected catalog schema or file count")
    root = args.root.expanduser().resolve(strict=True)
    if not root.is_dir():
        parser.error("private restore root is not a directory")
    checkout = next((parent for parent in Path(__file__).resolve().parents
                     if (parent / "AGENTS.md").is_file()
                     and (parent / "configs/public_repository_manifest.json").is_file()), None)
    if checkout is None:
        parser.error("cannot identify checkout for private restore boundary")
    if root.is_relative_to(checkout) or checkout.is_relative_to(root):
        parser.error("private restore root must be outside the checkout")
    seen: set[str] = set()
    total = 0
    for row in files:
        rel = row["old_path"]
        path = Path(rel)
        if (path.is_absolute() or ".." in path.parts or rel in seen
                or not rel.startswith("docs/reviews/artifacts/")):
            parser.error(f"unsafe or duplicate catalog path: {rel}")
        seen.add(rel)
        current = root
        for component in path.parts[:-1]:
            current /= component
            if not stat.S_ISDIR(current.lstat().st_mode):
                parser.error(f"linked or missing directory: {current}")
        source = current / path.name
        if not stat.S_ISREG(source.lstat().st_mode):
            parser.error(f"linked or missing raw file: {source}")
        actual = digest(source)
        if actual != (row["bytes"], row["sha256"]):
            parser.error(f"raw file bytes differ from public catalog: {rel}")
        total += actual[0]
    print(json.dumps({"status": "private_restore_verified", "files": len(files),
                      "bytes": total, "catalog_sha256": expected}, sort_keys=True))


if __name__ == "__main__":
    main()
