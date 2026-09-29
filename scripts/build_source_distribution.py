#!/usr/bin/env python3
"""Build and reconstruct a bounded split of the curated public repository.

The public repository builder remains the authority for selection, generated
runtime manifests, and the release receipt. This tool only divides that exact
tree into a smaller source archive and a companion data/evidence archive.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, nullcontext
import ctypes
import errno
import gzip
import hashlib
import json
import os
import stat
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from scripts import build_public_repository as public


SCHEMA = "open_agronomy_agent.source_distribution.v1"
PLAN_NAME = "DISTRIBUTION_PLAN.json"
ARCHIVES = {"source": "source.tar.gz", "evidence": "evidence.tar.gz"}
MAX_FILES = 20_000
MAX_TOTAL_BYTES = 2_000_000_000
MAX_SOURCE_BYTES = 100_000_000
MAX_PLAN_BYTES = 16_000_000
CHUNK = 1024 * 1024


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"unsafe member path: {value!r}")
    if len(value.encode("utf-8")) > 1024:
        raise ValueError("archive member path exceeds 1024 bytes")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError(f"unsafe member path: {value!r}")
    return value


def _pack_for(relative: str) -> str:
    return "evidence" if relative.startswith(("data/", "docs/reviews/artifacts/")) else "source"


def _rows(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {"path": _safe_path(row["path"]), "bytes": row["bytes"],
         "sha256": row["sha256"], "pack": _pack_for(row["path"])}
        for row in receipt["files"]
    ]
    rows.append({"path": "PUBLIC_RELEASE_RECEIPT.json", "bytes": None,
                 "sha256": receipt["receipt_sha256"], "pack": "source"})
    return sorted(rows, key=lambda row: row["path"])


def _write_archive(path: Path, tree: Path, rows: list[dict[str, Any]]) -> None:
    # Fixed gzip and tar metadata. The public receipt itself is deterministic
    # when SOURCE_DATE_EPOCH is set for the underlying public builder.
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for row in rows:
                    source = tree / row["path"]
                    info = tarfile.TarInfo(row["path"])
                    info.size = row["bytes"]
                    info.mode = row["mode"]
                    info.mtime = info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with source.open("rb") as stream:
                        tar.addfile(info, stream)


def _validate_plan(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (plan.get("schema_version") != SCHEMA or not isinstance(plan.get("archives"), dict)
            or set(plan["archives"]) != set(ARCHIVES)):
        raise ValueError("unsupported distribution plan")
    rows = plan.get("files")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_FILES:
        raise ValueError("invalid distribution file count")
    seen: dict[str, dict[str, Any]] = {}
    total = 0
    source_total = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid distribution row")
        name = _safe_path(row.get("path"))
        size = row.get("bytes")
        digest = row.get("sha256")
        pack = row.get("pack")
        mode = row.get("mode")
        if name in seen or pack != _pack_for(name) or type(size) is not int or size < 0:
            raise ValueError(f"invalid or duplicate distribution row: {name}")
        if mode not in (0o644, 0o755):
            raise ValueError(f"invalid file mode for {name}")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"invalid digest for {name}")
        total += size
        if pack == "source":
            source_total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("distribution exceeds uncompressed size bound")
        if source_total > MAX_SOURCE_BYTES:
            raise ValueError("source archive exceeds uncompressed size bound")
        seen[name] = row
    for name in seen:
        parts = name.split("/")
        if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
            raise ValueError(f"file/directory collision: {name}")
    if plan.get("total_bytes") != total or plan.get("file_count") != len(rows):
        raise ValueError("distribution totals do not match inventory")
    if "PUBLIC_RELEASE_RECEIPT.json" not in seen:
        raise ValueError("public release receipt is missing")
    for pack, filename in ARCHIVES.items():
        archive = plan["archives"][pack]
        if not isinstance(archive, dict) or archive.get("file") != filename:
            raise ValueError("unexpected archive name")
        size, digest = archive.get("bytes"), archive.get("sha256")
        if type(size) is not int or size < 0 or size > MAX_TOTAL_BYTES + 1_000_000:
            raise ValueError("invalid archive size")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid archive digest")
    return seen


def dry_run(manifest_path: Path = public.DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "open_agronomy_agent.public_repository_manifest.v1":
        raise ValueError("unsupported public repository manifest schema")
    files = public._collect(manifest)
    public._validate_scope(files, manifest)
    totals = {pack: {"files": 0, "input_bytes": 0} for pack in ARCHIVES}
    for path in files:
        pack = _pack_for(public._relative(path))
        totals[pack]["files"] += 1
        totals[pack]["input_bytes"] += path.stat().st_size
    return {"manifest_sha256": _hash_file(manifest_path), "planned": totals,
            "note": "Input byte inventory only; generated runtime manifest and receipt may differ. No archives written."}


def build(destination: Path, manifest_path: Path = public.DEFAULT_MANIFEST) -> dict[str, Any]:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"distribution destination must be new: {destination}")
    destination = destination.resolve()
    if (destination == public.ROOT.resolve()
            or public.ROOT.resolve().is_relative_to(destination)
            or destination.is_relative_to(public.ROOT.resolve())):
        raise ValueError("destination must be outside the repository")
    destination.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(prefix="curated-", dir=destination) as staging:
            tree = Path(staging)
            # A fixed epoch makes the generated public receipt reproducible;
            # restore the caller's environment even if the build fails.
            previous = os.environ.get("SOURCE_DATE_EPOCH")
            os.environ["SOURCE_DATE_EPOCH"] = previous if previous is not None else "0"
            try:
                receipt = public.build(tree, manifest_path)
            finally:
                if previous is None:
                    del os.environ["SOURCE_DATE_EPOCH"]
                else:
                    os.environ["SOURCE_DATE_EPOCH"] = previous
            rows = _rows(receipt)
            for row in rows:
                original_mode = stat.S_IMODE((tree / row["path"]).stat().st_mode)
                if original_mode not in (0o644, 0o755):
                    raise ValueError(f"unsupported curated file mode: {row['path']}:{original_mode:o}")
                row["mode"] = original_mode
                if row["path"] == "PUBLIC_RELEASE_RECEIPT.json":
                    row["bytes"] = (tree / row["path"]).stat().st_size
            plan = {"schema_version": SCHEMA, "manifest_sha256": _hash_file(manifest_path),
                    "public_receipt_sha256": receipt["receipt_sha256"],
                    "file_count": len(rows), "total_bytes": sum(row["bytes"] for row in rows),
                    "files": rows, "archives": {}}
            if len(rows) > MAX_FILES or plan["total_bytes"] > MAX_TOTAL_BYTES:
                raise ValueError("curated distribution exceeds fixed safety bounds")
            for pack, filename in ARCHIVES.items():
                archive = destination / filename
                _write_archive(archive, tree, [row for row in rows if row["pack"] == pack])
                plan["archives"][pack] = {"file": filename, "bytes": archive.stat().st_size,
                                          "sha256": _hash_file(archive)}
            _validate_plan(plan)
            plan_path = destination / PLAN_NAME
            plan_path.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            return {"plan_sha256": _hash_file(plan_path), "plan": str(plan_path),
                    "archives": plan["archives"], "file_count": plan["file_count"],
                    "total_bytes": plan["total_bytes"]}
    except Exception as exc:
        # Preserve a local failure receipt. No plan is written, so this
        # directory cannot be mistaken for a completed distribution.
        try:
            (destination / "BUILD_FAILED.json").write_text(
                json.dumps({"status": "failed", "error_type": type(exc).__name__,
                            "error": str(exc)}, indent=2) + "\n", encoding="utf-8"
            )
        except OSError:
            pass
        raise


class _BoundedReader:
    """Stop gzip expansion before tar can consume an unbounded PAX/header body."""

    def __init__(self, source: gzip.GzipFile, maximum: int) -> None:
        self.source = source
        self.remaining = maximum

    def read(self, size: int = -1) -> bytes:
        if size < 0 or size > self.remaining:
            size = self.remaining + 1
        block = self.source.read(size)
        self.remaining -= len(block)
        if self.remaining < 0:
            raise ValueError("archive exceeds decompressed byte bound")
        return block


def _publish_new_tree(source: Path, destination: Path) -> None:
    """Atomically publish a verified tree only if its destination is absent."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        operation = getattr(libc, "renamex_np", None)
        if operation is None:
            raise RuntimeError("atomic no-replace rename is unavailable")
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        result = operation(os.fsencode(source), os.fsencode(destination), 0x4)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        operation = getattr(libc, "renameat2", None)
        if operation is None:
            raise RuntimeError("atomic no-replace rename is unavailable")
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                              ctypes.c_char_p, ctypes.c_uint]
        operation.restype = ctypes.c_int
        result = operation(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise RuntimeError("atomic no-replace rename is unavailable on this platform")
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(code, "reconstruction destination already exists", str(destination))
        raise OSError(code, os.strerror(code), str(destination))


def verify(distribution: Path, expected_plan_sha256: str,
           destination: Path | None = None) -> dict[str, Any]:
    distribution = distribution.resolve()
    if destination is not None:
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"reconstruction destination must be new: {destination}")
        destination = destination.resolve()
        if destination == distribution or destination.is_relative_to(distribution):
            raise ValueError("destination must be outside distribution")
    if len(expected_plan_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_plan_sha256):
        raise ValueError("expected plan digest must be lowercase SHA-256")
    plan_path = distribution / PLAN_NAME
    if plan_path.is_symlink() or not plan_path.is_file():
        raise ValueError("distribution plan is missing or symbolic")
    if plan_path.stat().st_size > MAX_PLAN_BYTES or _hash_file(plan_path) != expected_plan_sha256:
        raise ValueError("distribution plan digest mismatch or size limit")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    expected = _validate_plan(plan)
    if {p.name for p in distribution.iterdir()} != {PLAN_NAME, *ARCHIVES.values()}:
        raise ValueError("unexpected or missing distribution files")
    for pack, filename in ARCHIVES.items():
        path = distribution / filename
        if not path.is_file() or path.is_symlink():
            raise ValueError("archive is missing or symbolic")
        record = plan["archives"][pack]
        if path.stat().st_size != record["bytes"] or _hash_file(path) != record["sha256"]:
            raise ValueError(f"archive hash or size mismatch: {filename}")
    with ExitStack() as stack:
        tree = None
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = stack.enter_context(
                tempfile.TemporaryDirectory(prefix="reconstruct-", dir=destination.parent)
            )
            tree = Path(temporary) / "tree"
            tree.mkdir()
        observed: set[str] = set()
        receipt_bytes: bytes | None = None
        for pack, filename in ARCHIVES.items():
            pack_rows = [row for row in expected.values() if row["pack"] == pack]
            max_expanded = sum(row["bytes"] for row in pack_rows) + 4096 * len(pack_rows) + 1_000_000
            with gzip.open(distribution / filename, "rb") as uncompressed:
                bounded = _BoundedReader(uncompressed, max_expanded)
                # A 512-byte stream buffer prevents read-ahead past the tar
                # end marker, so the tail can be checked byte for byte.
                with tarfile.open(fileobj=bounded, mode="r|", bufsize=512) as archive:
                    for member in archive:
                        name = _safe_path(member.name)
                        row = expected.get(name)
                        if (member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                                or row is None or row["pack"] != pack or name in observed
                                or member.size != row["bytes"] or member.mode != row["mode"]):
                            raise ValueError(f"unexpected, duplicate, or unsafe archive member: {name}")
                        observed.add(name)
                        digest = hashlib.sha256()
                        remaining = row["bytes"]
                        source = archive.extractfile(member)
                        if source is None:
                            raise ValueError(f"unreadable archive member: {name}")
                        target = tree / name if tree is not None else None
                        if target is not None:
                            target.parent.mkdir(parents=True, exist_ok=True)
                        output = target.open("xb") if target is not None else None
                        with output if output is not None else nullcontext() as sink:
                            while remaining:
                                block = source.read(min(CHUNK, remaining))
                                if not block:
                                    raise ValueError(f"truncated archive member: {name}")
                                if output is not None:
                                    sink.write(block)
                                if name == "PUBLIC_RELEASE_RECEIPT.json":
                                    if receipt_bytes is None:
                                        receipt_bytes = b""
                                    if len(receipt_bytes) + len(block) > MAX_PLAN_BYTES:
                                        raise ValueError("public receipt exceeds size bound")
                                    receipt_bytes += block
                                digest.update(block)
                                remaining -= len(block)
                        if digest.hexdigest() != row["sha256"]:
                            raise ValueError(f"member hash mismatch: {name}")
                        if target is not None:
                            target.chmod(row["mode"])
                    # Tar iteration stops at its first zero header and does
                    # not consume the gzip trailer. Require a second zero
                    # header and only standard zero record padding, then
                    # read gzip through EOF to validate CRC/ISIZE and reject
                    # concatenated members or hidden tar entries.
                    padding_bytes = 0
                    while True:
                        block = archive.fileobj.read(512)
                        if not block:
                            break
                        padding_bytes += len(block)
                        if padding_bytes > tarfile.RECORDSIZE or any(block):
                            raise ValueError("archive has nonzero or excessive tar end padding")
                    expanded_bytes = max_expanded - bounded.remaining
                    if (padding_bytes < 512 or expanded_bytes % tarfile.RECORDSIZE != 0):
                        raise ValueError("archive has invalid tar end framing")
        if observed != set(expected):
            raise ValueError(f"missing archive members: {sorted(set(expected) - observed)[:10]}")
        if receipt_bytes is None or _sha_bytes(receipt_bytes) != plan["public_receipt_sha256"]:
            raise ValueError("public release receipt mismatch")
        receipt = json.loads(receipt_bytes)
        if receipt.get("schema_version") != "open_agronomy_agent.public_repository_receipt.v1":
            raise ValueError("unsupported public release receipt")
        if (receipt.get("file_count") != len(receipt.get("files", []))
                or receipt.get("total_bytes") != sum(row["bytes"] for row in receipt["files"])):
            raise ValueError("public release receipt totals differ")
        if receipt.get("manifest_sha256") != plan.get("manifest_sha256"):
            raise ValueError("public release manifest digest differs")
        manifest_name = _safe_path(receipt.get("manifest_path"))
        if manifest_name not in expected or expected[manifest_name]["sha256"] != plan["manifest_sha256"]:
            raise ValueError("curated manifest is missing or differs")
        public_rows = {row["path"]: row for row in receipt["files"]}
        if set(public_rows) != set(expected) - {"PUBLIC_RELEASE_RECEIPT.json"}:
            raise ValueError("public release inventory differs from distribution")
        if any(row["bytes"] != expected[name]["bytes"] or row["sha256"] != expected[name]["sha256"]
               for name, row in public_rows.items()):
            raise ValueError("public release hashes differ from distribution")
        if tree is not None:
            _publish_new_tree(tree, destination)
    return {"destination": str(destination) if destination is not None else None,
            "verified_only": destination is None, "file_count": len(expected),
            "total_bytes": plan["total_bytes"], "plan_sha256": expected_plan_sha256}


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def reconstruct(distribution: Path, destination: Path, expected_plan_sha256: str) -> dict[str, Any]:
    return verify(distribution, expected_plan_sha256, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    draft = commands.add_parser("plan", help="report curated split sizes without writing archives")
    draft.add_argument("--manifest", type=Path, default=public.DEFAULT_MANIFEST)
    make = commands.add_parser("build", help="build split archives in a new directory")
    make.add_argument("--destination", required=True, type=Path)
    make.add_argument("--manifest", type=Path, default=public.DEFAULT_MANIFEST)
    restore = commands.add_parser("reconstruct", help="verify and restore both packs into a new tree")
    restore.add_argument("--distribution", required=True, type=Path)
    restore.add_argument("--destination", required=True, type=Path)
    restore.add_argument("--expected-plan-sha256", required=True)
    check = commands.add_parser("verify", help="verify both packs without reconstructing")
    check.add_argument("--distribution", required=True, type=Path)
    check.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    result = (dry_run(args.manifest.resolve()) if args.command == "plan" else
              build(args.destination, args.manifest.resolve()) if args.command == "build" else
              reconstruct(args.distribution, args.destination, args.expected_plan_sha256)
              if args.command == "reconstruct" else
              verify(args.distribution, args.expected_plan_sha256))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
