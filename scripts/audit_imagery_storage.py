#!/usr/bin/env python3
"""Bounded, read-only imagery storage inventory; output contains no local paths.

Roots are explicit LABEL=ABSOLUTE_PATH arguments. Symlinks are counted but
never followed. Optional hashing verifies duplicate payloads under its own
byte cap. The script never deletes, vacuums, rewrites, or migrates source data.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import statistics
from typing import Any
import zipfile

SCHEMA_VERSION = 1
_CHIP = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")
_MEMBERS = {"bands.npy", "fmask.npy", "field_weights.npy", "field_mask.npy",
            "valid_mask.npy", "ndvi.npy", "metadata_json.npy"}
_MAX_NPZ_BYTES = 128 * 1024 * 1024
_MAX_NPZ_MEMBERS = 32
_MAX_NPZ_MEMBER_BYTES = 16 * 1024 * 1024
_MAX_NPZ_UNCOMPRESSED_BYTES = 32 * 1024 * 1024


def parse_root(argument: str) -> tuple[str, Path]:
    label, marker, raw = argument.partition("=")
    if not marker or not _LABEL.fullmatch(label) or not Path(raw).is_absolute():
        raise ValueError("root must be LABEL=ABSOLUTE_PATH with a safe label")
    path = Path(raw).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError("root must be an existing real directory")
    return label, path.resolve(strict=True)


def _canonical_roots(roots: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    if not roots or len({label for label, _ in roots}) != len(roots):
        raise ValueError("unique roots required")
    normalized: list[tuple[str, Path]] = []
    for label, supplied in roots:
        path = Path(supplied).expanduser()
        if not _LABEL.fullmatch(label) or path.is_symlink() or not path.is_dir():
            raise ValueError("root must be an existing real directory with safe label")
        canonical = path.resolve(strict=True)
        if any(canonical == earlier or canonical in earlier.parents or earlier in canonical.parents
               for _, earlier in normalized):
            raise ValueError("duplicate or overlapping storage roots")
        normalized.append((label, canonical))
    return normalized


def _kind(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if name.startswith("imagery-v") and suffix in (".sqlite3", ".db"):
        return "imagery_index"
    if suffix == ".npz":
        return "chip_npz"
    if suffix == ".png":
        return "png"
    if suffix == ".json":
        return "chip_receipt" if _CHIP.fullmatch(Path(name).stem) else "other_json"
    if suffix in (".safetensors", ".pt", ".pth", ".bin"):
        return "model_weights_or_binary"
    if suffix == ".pyc":
        return "python_bytecode"
    return "other"


def _new_totals() -> dict[str, int]:
    return {"files": 0, "logical_bytes": 0, "allocated_bytes_sum_st_blocks": 0}


@contextmanager
def _safe_open(path: Path, *, expected_size: int, max_size: int):
    if path.is_symlink():
        raise ValueError("symlink file refused")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected_size or info.st_size > max_size:
            raise ValueError("file changed during scan")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            yield handle
    finally:
        os.close(fd)


def _hash_file(path: Path, expected_size: int, budget: int) -> tuple[str | None, int]:
    digest = hashlib.sha256()
    consumed = 0
    with _safe_open(path, expected_size=expected_size, max_size=budget) as handle:
        while True:
            chunk = handle.read(min(1024 * 1024, budget - consumed + 1))
            if not chunk:
                return (digest.hexdigest(), consumed) if consumed == expected_size else (None, consumed)
            consumed += len(chunk)
            if consumed > budget:
                return None, consumed
            digest.update(chunk)


def audit_roots(
    roots: list[tuple[str, Path]], *, max_files: int = 100_000,
    max_directories: int = 20_000, max_logical_bytes: int = 4 * 1024**3,
    verify_duplicates: bool = False, max_hash_bytes: int = 1024**3,
) -> dict[str, Any]:
    if any(value < 1 for value in (max_files, max_directories, max_logical_bytes, max_hash_bytes)):
        raise ValueError("positive scan limits required")
    roots = _canonical_roots(roots)
    summaries: dict[str, dict[str, Any]] = {}
    records: list[tuple[Path, int, str, str]] = []  # private process memory only
    receipt_scenes: set[str] = set()
    receipt_geometries: set[str] = set()
    contexts: list[int] = []
    transfer_bytes = 0
    transfer_unknown = 0
    npz_members: dict[str, dict[str, int]] = defaultdict(
        lambda: {"count": 0, "uncompressed_bytes": 0, "compressed_bytes": 0})
    member_records: list[tuple[Path, int, str, int, int]] = []
    global_files = 0
    global_dirs = 0
    global_bytes = 0
    reasons: list[str] = []
    invalid_npz = 0
    invalid_receipts = 0
    auxiliary_hashed_json = 0
    for label, root in roots:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("root must be an existing real directory")
        summary: dict[str, Any] = {**_new_totals(), "directories": 0,
                                   "symlinks_skipped": 0, "other_entries_skipped": 0,
                                   "unreadable_entries": 0, "by_kind": {}}
        summaries[label] = summary
        stack = [root]
        while stack:
            if global_dirs >= max_directories:
                reasons.append("directory_limit")
                break
            directory = stack.pop()
            global_dirs += 1
            summary["directories"] += 1
            try:
                if directory.is_symlink():
                    summary["symlinks_skipped"] += 1
                    continue
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                summary["symlinks_skipped"] += 1
                                continue
                            info = entry.stat(follow_symlinks=False)
                            if stat.S_ISDIR(info.st_mode):
                                stack.append(Path(entry.path))
                                continue
                            if not stat.S_ISREG(info.st_mode):
                                summary["other_entries_skipped"] += 1
                                continue
                            if global_files >= max_files:
                                reasons.append("file_limit")
                                break
                            if global_bytes + info.st_size > max_logical_bytes:
                                reasons.append("logical_byte_limit")
                                break
                            kind = _kind(entry.name)
                            allocated = int(getattr(info, "st_blocks", 0)) * 512
                            for totals in (summary, summary["by_kind"].setdefault(kind, _new_totals())):
                                totals["files"] += 1
                                totals["logical_bytes"] += info.st_size
                                totals["allocated_bytes_sum_st_blocks"] += allocated
                            global_files += 1
                            global_bytes += info.st_size
                            path = Path(entry.path)
                            records.append((path, info.st_size, label, kind))
                            if kind == "chip_npz" and _CHIP.fullmatch(path.stem):
                                try:
                                    with _safe_open(path, expected_size=info.st_size,
                                                    max_size=_MAX_NPZ_BYTES) as source, zipfile.ZipFile(source) as archive:
                                        members = archive.infolist()
                                        if (len(members) > _MAX_NPZ_MEMBERS or
                                                sum(member.file_size for member in members) > _MAX_NPZ_UNCOMPRESSED_BYTES or
                                                any(member.file_size > _MAX_NPZ_MEMBER_BYTES for member in members) or
                                                len({member.filename for member in members}) != len(members)):
                                            raise ValueError("oversized or ambiguous NPZ")
                                        for member in members:
                                            if member.filename in _MEMBERS:
                                                totals = npz_members[member.filename.removesuffix(".npy")]
                                                totals["count"] += 1
                                                totals["uncompressed_bytes"] += member.file_size
                                                totals["compressed_bytes"] += member.compress_size
                                                member_records.append((path, info.st_size, member.filename,
                                                                       member.file_size, member.compress_size))
                                except (OSError, ValueError, zipfile.BadZipFile):
                                    invalid_npz += 1
                            elif kind == "chip_receipt":
                                try:
                                    with _safe_open(path, expected_size=info.st_size,
                                                    max_size=2 * 1024 * 1024) as source_file:
                                        receipt = json.load(source_file)
                                    claimed = receipt.get("chip_hash") if isinstance(receipt, dict) else None
                                    sibling_name = receipt.get("cache_files", {}).get("npz") if isinstance(receipt, dict) else None
                                    if (isinstance(receipt, dict) and claimed != path.stem and
                                            (claimed is None or
                                             (isinstance(claimed, str) and _CHIP.fullmatch(claimed) and
                                              sibling_name == claimed + ".npz"))):
                                        auxiliary_hashed_json += 1
                                        for key in ("files", "logical_bytes", "allocated_bytes_sum_st_blocks"):
                                            amount = 1 if key == "files" else info.st_size if key == "logical_bytes" else allocated
                                            summary["by_kind"]["chip_receipt"][key] -= amount
                                            summary["by_kind"].setdefault("other_json", _new_totals())[key] += amount
                                        records[-1] = (path, info.st_size, label, "other_json")
                                        continue
                                    if not isinstance(receipt, dict) or claimed != path.stem:
                                        raise ValueError("receipt identity mismatch")
                                    npz_name = receipt.get("cache_files", {}).get("npz")
                                    if npz_name != path.stem + ".npz":
                                        raise ValueError("receipt NPZ sibling identity mismatch")
                                    source = receipt.get("source", {})
                                    if not isinstance(source, dict):
                                        raise ValueError("invalid receipt source")
                                    if isinstance(source.get("scene_id"), str):
                                        receipt_scenes.add(source["scene_id"])
                                    if isinstance(receipt.get("geometry_hash"), str):
                                        receipt_geometries.add(receipt["geometry_hash"])
                                    grid = receipt.get("grid", {})
                                    if grid.get("width") == grid.get("height") == 224:
                                        chip_path = path.parent / npz_name
                                        chip_info = chip_path.lstat()
                                        with _safe_open(chip_path, expected_size=chip_info.st_size,
                                                        max_size=_MAX_NPZ_BYTES):
                                            contexts.append(chip_info.st_size)
                                    transferred = receipt.get("cog_transfer_bytes")
                                    if type(transferred) is int and transferred >= 0:
                                        transfer_bytes += transferred
                                    else:
                                        transfer_unknown += 1
                                except (OSError, ValueError, TypeError, AttributeError):
                                    invalid_receipts += 1
                                    transfer_unknown += 1
                        except OSError:
                            summary["unreadable_entries"] += 1
                if any(reason in reasons for reason in ("file_limit", "logical_byte_limit")):
                    break
            except OSError:
                summary["unreadable_entries"] += 1
        if reasons:
            break

    duplicate: dict[str, Any] = {"requested": verify_duplicates,
                                 "status": "not_requested" if not verify_duplicates else "complete",
                                 "candidate_files": 0, "hashed_files": 0, "bytes_hashed": 0,
                                 "exact_duplicate_file_groups": 0,
                                 "redundant_logical_file_bytes": 0,
                                 "file_by_kind": {},
                                 "exact_duplicate_member_groups": 0,
                                 "redundant_uncompressed_member_bytes": 0,
                                 "candidate_compressed_member_savings_bytes": 0,
                                 "member_by_name": {}}
    if verify_duplicates:
        by_size: dict[int, list[tuple[Path, int, str, str]]] = defaultdict(list)
        for record in records:
            by_size[record[1]].append(record)
        candidate_files = [record for group in by_size.values() if len(group) > 1 for record in group]
        duplicate["candidate_files"] = len(candidate_files)
        digests: dict[tuple[int, str], list[tuple[Path, int, str, str]]] = defaultdict(list)
        remaining = max_hash_bytes
        for record in candidate_files:
            if record[1] > remaining:
                duplicate["status"] = "hash_byte_limit"
                continue
            try:
                digest, consumed = _hash_file(record[0], record[1], remaining)
            except (OSError, ValueError):
                duplicate["status"] = "unreadable_file"
                continue
            remaining -= consumed
            if digest is None:
                duplicate["status"] = "hash_byte_limit"
                continue
            duplicate["hashed_files"] += 1
            duplicate["bytes_hashed"] += consumed
            digests[(record[1], digest)].append(record)
        for (size, _), group in digests.items():
            if len(group) > 1:
                duplicate["exact_duplicate_file_groups"] += 1
                duplicate["redundant_logical_file_bytes"] += (len(group) - 1) * size
                kind = group[0][3] if len({item[3] for item in group}) == 1 else "cross_kind"
                row = duplicate["file_by_kind"].setdefault(kind, {"groups": 0, "redundant_logical_bytes": 0})
                row["groups"] += 1
                row["redundant_logical_bytes"] += (len(group) - 1) * size
        member_digests: dict[tuple[str, int, str], list[int]] = defaultdict(list)
        for path, file_size, name, size, compressed in member_records:
            if size > remaining:
                duplicate["status"] = "hash_byte_limit"
                continue
            try:
                digest = hashlib.sha256()
                consumed = 0
                with _safe_open(path, expected_size=file_size, max_size=_MAX_NPZ_BYTES) as source, \
                        zipfile.ZipFile(source) as archive, archive.open(name) as handle:
                    while True:
                        chunk = handle.read(min(1024 * 1024, remaining - consumed + 1))
                        if not chunk:
                            break
                        consumed += len(chunk)
                        if consumed > remaining:
                            break
                        digest.update(chunk)
                if consumed > remaining:
                    duplicate["status"] = "hash_byte_limit"
                    continue
                remaining -= consumed
                duplicate["bytes_hashed"] += consumed
                member_digests[(name, size, digest.hexdigest())].append(compressed)
            except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
                duplicate["status"] = "unreadable_member"
        for (name, size, _), compressed_sizes in member_digests.items():
            if len(compressed_sizes) > 1:
                duplicate["exact_duplicate_member_groups"] += 1
                duplicate["redundant_uncompressed_member_bytes"] += (len(compressed_sizes) - 1) * size
                duplicate["candidate_compressed_member_savings_bytes"] += sum(compressed_sizes) - min(compressed_sizes)
                row = duplicate["member_by_name"].setdefault(name.removesuffix(".npy"),
                    {"groups": 0, "redundant_uncompressed_bytes": 0,
                     "candidate_compressed_savings_bytes": 0})
                row["groups"] += 1
                row["redundant_uncompressed_bytes"] += (len(compressed_sizes) - 1) * size
                row["candidate_compressed_savings_bytes"] += sum(compressed_sizes) - min(compressed_sizes)

    if any(summary["unreadable_entries"] for summary in summaries.values()):
        reasons.append("unreadable_entries")
    if invalid_npz or invalid_receipts:
        reasons.append("invalid_artifacts")
    if verify_duplicates and duplicate["status"] != "complete":
        reasons.append("duplicate_verification_incomplete")
    context_sizes = sorted(contexts)
    median_context = int(statistics.median(context_sizes)) if context_sizes else None
    projections: dict[str, Any] = {"measured_224_context_samples": len(context_sizes),
                                   "median_compressed_chip_bytes": median_context,
                                   "assumed_dates_per_field_season": 4,
                                   "same_context_reuse_scenarios": {}}
    if median_context is not None:
        for seasons in (100, 1000):
            projections["same_context_reuse_scenarios"][str(seasons)] = {
                "one_context_per_field_season_bytes": seasons * 4 * median_context,
                "twelve_units_per_shared_context_bytes": math.ceil(seasons / 12) * 4 * median_context,
            }
    return {"schema_version": SCHEMA_VERSION,
            "status": "complete" if not reasons else "incomplete",
            "incomplete_reasons": sorted(set(reasons)),
            "limits": {"max_files": max_files, "max_directories": max_directories,
                       "max_logical_bytes": max_logical_bytes, "max_hash_bytes": max_hash_bytes},
            "roots": summaries,
            "aggregate": {"files": global_files, "directories": global_dirs,
                          "logical_bytes": global_bytes,
                          "allocated_bytes_sum_st_blocks": sum(x["allocated_bytes_sum_st_blocks"] for x in summaries.values()),
                          "allocated_note": "st_blocks sum is not unique physical bytes; APFS clone/shared extents are unknown",
                          "invalid_npz": invalid_npz, "invalid_chip_receipts": invalid_receipts,
                          "auxiliary_hashed_json_files": auxiliary_hashed_json,
                          "distinct_scene_ids_in_receipts": len(receipt_scenes),
                          "distinct_geometry_hashes_in_receipts": len(receipt_geometries),
                          "recorded_cog_transfer_bytes_sum": transfer_bytes,
                          "receipts_with_unknown_cog_transfer": transfer_unknown,
                          "npz_member_totals": dict(npz_members)},
            "duplicates": duplicate, "projection": projections}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, metavar="LABEL=ABSOLUTE_PATH")
    parser.add_argument("--max-files", type=int, default=100_000)
    parser.add_argument("--max-directories", type=int, default=20_000)
    parser.add_argument("--max-logical-bytes", type=int, default=4 * 1024**3)
    parser.add_argument("--verify-duplicates", action="store_true")
    parser.add_argument("--max-hash-bytes", type=int, default=1024**3)
    parser.add_argument("--output", type=Path, help="write aggregate JSON receipt outside scanned roots")
    args = parser.parse_args()
    roots = _canonical_roots([parse_root(value) for value in args.root])
    output_path: Path | None = None
    if args.output:
        output_path = args.output.expanduser()
        if output_path.exists() or output_path.is_symlink():
            parser.error("output destination already exists")
        try:
            canonical_parent = output_path.parent.resolve(strict=True)
        except OSError:
            parser.error("output parent must already exist")
        output_path = canonical_parent / output_path.name
        if any(output_path == root or root in output_path.parents for _, root in roots):
            parser.error("output must be outside scanned roots")
    receipt = audit_roots(roots, max_files=args.max_files, max_directories=args.max_directories,
                          max_logical_bytes=args.max_logical_bytes,
                          verify_duplicates=args.verify_duplicates, max_hash_bytes=args.max_hash_bytes)
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if output_path:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(output_path, flags, 0o600)
        except FileExistsError:
            parser.error("output destination already exists")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
