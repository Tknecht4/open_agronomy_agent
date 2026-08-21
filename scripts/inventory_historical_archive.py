#!/usr/bin/env python3
"""Create a read-only, hash-bound intake receipt for a historical repository.

The inventory intentionally does not copy or promote archive bytes.  It is an
admission input: callers must build a new release from records whose source,
rights, and provenance status are explicitly reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import canonical_json, sha256_bytes  # noqa: E402


SCHEMA = "open_agronomy_agent.historical_archive_intake.v2"
DEFAULT_OUTPUT = ROOT / "data" / "manifests" / "historical_archive_lexar_20260819.json"
DATA_ROOTS = ("data", "configs", "docs", "scripts", "src")
SKIP_TREES = {".git", "node_modules", ".venv", "dist", "build", "__pycache__", ".pytest_cache"}
SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "bearer_token": re.compile(rb"\bBearer\s+[A-Za-z0-9._~-]{16,}"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "openai_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
}


def _scan_file(path: Path) -> tuple[str, list[str]]:
    """Hash and scan in one bounded-memory pass over archival bytes."""

    digest = hashlib.sha256()
    hits: set[str] = set()
    tail = b""
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            sample = tail + block
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(sample):
                    hits.add(name)
            tail = sample[-128:]
    return digest.hexdigest(), sorted(hits)


def _git_revision(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _iter_files(archive_root: Path, roots: tuple[str, ...], *, include_top_level_files: tuple[str, ...] = ()) -> Iterator[Path]:
    for relative_root in roots:
        root = archive_root / relative_root
        if root.is_symlink():
            yield root
            continue
        if root.is_file():
            yield root
            continue
        if not root.exists():
            continue
        for current, directories, names in os.walk(root, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in SKIP_TREES)
            current_path = Path(current)
            for name in sorted(names):
                yield current_path / name
    for relative_root in include_top_level_files:
        root = archive_root / relative_root
        if not root.is_dir():
            raise ValueError(f"top-level-file root is not a directory: {relative_root}")
        for child in sorted(root.iterdir(), key=lambda path: path.name):
            if child.is_file() or child.is_symlink():
                yield child


def _classify(relative: str) -> tuple[str, str, str]:
    normalized = relative.casefold()
    name = Path(relative).name.casefold()
    if name.startswith("._") or name == ".ds_store":
        return "rejected", "macos_sidecar_metadata", "not_a_source_asset"
    if "/private_knowledge/" in normalized or normalized.endswith("/private_knowledge"):
        return "quarantined", "private_or_operator_scoped_material", "not_reproducible_for_public_release"
    if "/node_modules/" in normalized or "/.git/" in normalized:
        return "rejected", "dependency_or_vcs_material", "not_a_source_asset"
    if "/forum_" in normalized or "community" in normalized:
        return "candidate", "community_source_requires_rights_and_privacy_review", "requires_source_specific_review"
    if "nrcs_esd" in normalized or "usda" in normalized:
        return "candidate", "us_government_source_requires_successor_projection", "rebuildable_from_hashed_archive"
    if "/geo_layers/" in normalized or "/geo_cache/" in normalized or "spatial" in normalized:
        return "candidate", "optional_spatial_pack_requires_portability_review", "requires_profile_rebuild"
    if "/derived/rag/" in normalized and any(
        marker in name
        for marker in ("attempt", "_candidate", "document_expansion", "rag_full_forums")
    ):
        return "rejected", "superseded_or_experimental_generated_artifact", "retain_as_history_not_runtime_input"
    if normalized.endswith(".jsonl") or "/raw/" in normalized:
        return "candidate", "source_or_derivative_requires_admission_review", "requires_lineage_review"
    return "candidate", "archive_supporting_artifact", "requires_scope_review"


def _first_json_metadata(path: Path) -> dict[str, Any]:
    if path.suffix not in {".json", ".jsonl"} or path.name.startswith("._"):
        return {}
    try:
        with path.open("rb") as handle:
            line = handle.readline(2 * 1024 * 1024)
        payload = json.loads(line.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: payload[key]
        for key in (
            "source_id",
            "source",
            "license",
            "publisher",
            "source_type",
            "download_url",
            "jurisdiction",
            "region",
            "retrieved_at",
            "reviewed_at",
            "date",
            "updated_at",
        )
        if isinstance(payload.get(key), (str, int, float, bool))
    }


def _forensic_fields(relative: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Derive conservative intake labels without treating unknown as benign."""

    normalized = relative.casefold()
    name = Path(relative).name.casefold()
    if "/raw/" in normalized:
        role = "raw_source"
    elif "/derived/" in normalized:
        role = "derived_artifact"
    elif normalized.startswith("data/eval") or "/eval/" in normalized:
        role = "evaluation_asset"
    elif normalized.startswith("configs/"):
        role = "configuration_or_contract"
    elif normalized.startswith("src/") or normalized.startswith("scripts/"):
        role = "implementation_or_builder"
    elif normalized.startswith("docs/"):
        role = "documentation_or_report"
    else:
        role = "archive_supporting_artifact"
    if "nrcs" in normalized or "usda" in normalized:
        jurisdiction = ["United States"]
    elif any(token in normalized for token in ("canada", "canadian", "alberta", "manitoba", "saskatchewan")):
        jurisdiction = ["Canada"]
    else:
        metadata_jurisdiction = metadata.get("jurisdiction") or metadata.get("region")
        jurisdiction = [str(metadata_jurisdiction)] if metadata_jurisdiction else ["unknown"]
    freshness = next(
        (
            str(metadata[key])
            for key in ("reviewed_at", "retrieved_at", "updated_at", "date")
            if metadata.get(key)
        ),
        "unknown_not_inferred_from_archive_mtime",
    )
    family_stem = re.sub(r"(?:[_-]v?\d+(?:[._-]\d+)*)$", "", Path(relative).stem.casefold())
    duplicate_family = f"{Path(relative).parent.as_posix().casefold()}/{family_stem}"
    return {
        "archive_role": role,
        "licence_evidence": str(metadata.get("license") or "unknown_requires_source_review"),
        "jurisdiction": jurisdiction,
        "freshness": freshness,
        "duplicate_family": duplicate_family,
    }


def _build_inventory_payload(
    *,
    archive_root: Path,
    revision: str | None,
    entries: list[dict[str, Any]],
    symlinks: list[str],
    hidden_metadata: list[str],
    secret_hits: list[dict[str, Any]],
    classification_recomputed_from_inventory_sha256: str | None = None,
) -> dict[str, Any]:
    classification_counts = Counter(entry["classification"] for entry in entries)
    role_counts = Counter(entry["classification_reason"] for entry in entries)
    source_groups: dict[str, dict[str, Any]] = {}
    for record in entries:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        relative = str(record["path"])
        source_id = str(metadata.get("source_id") or relative.split("/")[0])
        group = source_groups.setdefault(
            source_id,
            {
                "source_id": source_id,
                "files": 0,
                "bytes": 0,
                "classifications": Counter(),
                "licence_evidence": set(),
                "publishers": set(),
                "source_urls": set(),
            },
        )
        group["files"] += 1
        group["bytes"] += int(record["bytes"])
        group["classifications"][str(record["classification"])] += 1
        for key, target in (("license", "licence_evidence"), ("publisher", "publishers"), ("source", "source_urls")):
            if metadata.get(key):
                group[target].add(str(metadata[key]))
    normalized_groups = []
    for group in source_groups.values():
        normalized_groups.append(
            {
                "source_id": group["source_id"],
                "files": group["files"],
                "bytes": group["bytes"],
                "classifications": dict(sorted(group["classifications"].items())),
                "licence_evidence": sorted(group["licence_evidence"]),
                "publishers": sorted(group["publishers"]),
                "source_urls": sorted(group["source_urls"]),
            }
        )
    entries.sort(key=lambda item: item["path"])
    normalized_groups.sort(key=lambda item: item["source_id"])
    inventory = {
        "schema_version": SCHEMA,
        "archive_root_label": archive_root.name,
        "archive_git_revision": revision,
        "archive_content_sha256": sha256_bytes(canonical_json(entries).encode("utf-8")),
        "files": entries,
        "source_groups": normalized_groups,
        "summary": {
            "regular_files": len(entries),
            "bytes": sum(int(entry["bytes"]) for entry in entries),
            "classifications": dict(sorted(classification_counts.items())),
            "roles": dict(sorted(role_counts.items())),
            "symlinks": sorted(symlinks),
            "hidden_metadata": sorted(hidden_metadata),
            "secret_pattern_hits": sorted(secret_hits, key=lambda item: item["path"]),
            "safe_for_automatic_promotion": False,
            "promotion_boundary": "Every candidate requires a successor source-rights, provenance, and quality decision.",
        },
    }
    if classification_recomputed_from_inventory_sha256:
        inventory["classification_recomputed_from_inventory_sha256"] = classification_recomputed_from_inventory_sha256
    inventory["inventory_sha256"] = sha256_bytes(canonical_json(inventory).encode("utf-8"))
    return inventory


def build_inventory(
    archive_root: Path,
    *,
    include_roots: tuple[str, ...] = DATA_ROOTS,
    include_top_level_files: tuple[str, ...] = (),
) -> dict[str, Any]:
    archive_root = archive_root.resolve(strict=True)
    revision = _git_revision(archive_root)
    entries: list[dict[str, Any]] = []
    secret_hits: list[dict[str, Any]] = []
    symlinks: list[str] = []
    hidden_metadata: list[str] = []
    for path in _iter_files(archive_root, include_roots, include_top_level_files=include_top_level_files):
        relative = path.relative_to(archive_root).as_posix()
        if path.is_symlink():
            symlinks.append(relative)
            continue
        if not path.is_file():
            continue
        classification, role, reproducibility = _classify(relative)
        metadata = _first_json_metadata(path)
        digest, hits = _scan_file(path)
        if hits:
            classification = "quarantined"
            role = "secret_pattern_requires_manual_review"
            reproducibility = "blocked_pending_secret_or_fixture_review"
        record = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "classification": classification,
            "classification_reason": role,
            "reproducibility": reproducibility,
            "metadata": metadata,
        }
        record.update(_forensic_fields(relative, metadata))
        entries.append(record)
        if path.name.startswith("._") or path.name == ".DS_Store":
            hidden_metadata.append(relative)
        if hits:
            secret_hits.append({"path": relative, "patterns": hits})
    return _build_inventory_payload(
        archive_root=archive_root,
        revision=revision,
        entries=entries,
        symlinks=symlinks,
        hidden_metadata=hidden_metadata,
        secret_hits=secret_hits,
    )


def merge_inventories(paths: list[Path]) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if not payloads:
        raise ValueError("at least one inventory is required")
    root_label = payloads[0].get("archive_root_label")
    revision = payloads[0].get("archive_git_revision")
    if any(item.get("archive_root_label") != root_label or item.get("archive_git_revision") != revision for item in payloads):
        raise ValueError("cannot merge inventories from different archives")
    entries_by_path: dict[str, dict[str, Any]] = {}
    for item in payloads:
        for raw_record in item.get("files") or []:
            if not isinstance(raw_record, dict):
                raise ValueError("invalid inventory record")
            record = dict(raw_record)
            relative = str(record.get("path") or "")
            previous = entries_by_path.get(relative)
            if previous is not None and (
                previous.get("sha256") != record.get("sha256")
                or previous.get("bytes") != record.get("bytes")
            ):
                raise ValueError(f"cannot merge inventories with conflicting path hash: {relative}")
            entries_by_path.setdefault(relative, record)
    entries = list(entries_by_path.values())
    return _build_inventory_payload(
        archive_root=Path(str(root_label)),
        revision=str(revision) if revision else None,
        entries=entries,
        symlinks=[value for item in payloads for value in (item.get("summary") or {}).get("symlinks") or []],
        hidden_metadata=[value for item in payloads for value in (item.get("summary") or {}).get("hidden_metadata") or []],
        secret_hits=[value for item in payloads for value in (item.get("summary") or {}).get("secret_pattern_hits") or []],
    )


def reclassify_inventory(path: Path) -> dict[str, Any]:
    """Reapply the current pure policy to a previously hashed full receipt.

    This is deliberately not a substitute for byte hashing: it only corrects
    an intake-policy classification while preserving each prior file hash and
    recording the precise receipt from which the bytes were observed.
    """

    previous = json.loads(path.read_text(encoding="utf-8"))
    if previous.get("schema_version") not in {SCHEMA, "open_agronomy_agent.historical_archive_intake.v1"}:
        raise ValueError("unsupported inventory schema for reclassification")
    entries: list[dict[str, Any]] = []
    flagged_paths = {
        str(item.get("path") or "")
        for item in (previous.get("summary") or {}).get("secret_pattern_hits") or []
        if isinstance(item, dict)
    }
    for previous_entry in previous.get("files") or []:
        if not isinstance(previous_entry, dict):
            raise ValueError("invalid inventory entry")
        entry = dict(previous_entry)
        classification, reason, reproducibility = _classify(str(entry.get("path") or ""))
        if str(entry.get("path") or "") in flagged_paths:
            classification = "quarantined"
            reason = "secret_pattern_requires_manual_review"
            reproducibility = "blocked_pending_secret_or_fixture_review"
        entry["classification"] = classification
        entry["classification_reason"] = reason
        entry["reproducibility"] = reproducibility
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        entry.update(_forensic_fields(str(entry.get("path") or ""), metadata))
        entries.append(entry)
    return _build_inventory_payload(
        archive_root=Path(str(previous.get("archive_root_label") or "archive")),
        revision=str(previous.get("archive_git_revision")) if previous.get("archive_git_revision") else None,
        entries=entries,
        symlinks=list((previous.get("summary") or {}).get("symlinks") or []),
        hidden_metadata=list((previous.get("summary") or {}).get("hidden_metadata") or []),
        secret_hits=list((previous.get("summary") or {}).get("secret_pattern_hits") or []),
        classification_recomputed_from_inventory_sha256=str(previous.get("inventory_sha256") or ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True, help="mounted historical source archive")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--include-root", action="append", default=[])
    parser.add_argument("--include-top-level-files", action="append", default=[])
    parser.add_argument("--merge-input", type=Path, action="append", default=[])
    parser.add_argument("--reclassify-input", type=Path)
    args = parser.parse_args()
    if args.merge_input and args.reclassify_input:
        raise ValueError("--merge-input and --reclassify-input are mutually exclusive")
    inventory = (
        reclassify_inventory(args.reclassify_input)
        if args.reclassify_input
        else merge_inventories(args.merge_input)
        if args.merge_input
        else build_inventory(
            args.archive_root,
            include_roots=(
                tuple(args.include_root)
                if args.include_root or args.include_top_level_files
                else DATA_ROOTS
            ),
            include_top_level_files=tuple(args.include_top_level_files),
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = inventory["summary"]
    print(
        json.dumps(
            {
                "output": str(args.output),
                "inventory_sha256": inventory["inventory_sha256"],
                "regular_files": summary["regular_files"],
                "bytes": summary["bytes"],
                "classifications": summary["classifications"],
                "symlink_count": len(summary["symlinks"]),
                "hidden_metadata_count": len(summary["hidden_metadata"]),
                "secret_pattern_hit_count": len(summary["secret_pattern_hits"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
