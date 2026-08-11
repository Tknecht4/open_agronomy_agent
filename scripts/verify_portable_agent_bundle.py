#!/usr/bin/env python3
"""Verify a portable Open Agronomy source-and-knowledge archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "open_agronomy_agent.portable_runtime_bundle.v4"
SUPPORTED_SCHEMA_VERSIONS = {
    "open_agronomy_agent.portable_runtime_bundle.v2",
    "open_agronomy_agent.portable_runtime_bundle.v3",
    SCHEMA_VERSION,
}
ARCHIVE_ROOT = PurePosixPath("open_agronomy_agent")
MANIFEST_PATH = ARCHIVE_ROOT / "PORTABLE_BUNDLE_MANIFEST.json"
MODEL_WEIGHT_SUFFIXES = {".safetensors", ".gguf", ".bin", ".pt", ".pth", ".npz"}
RETIRED_EVAL_MARKERS = (
    "crop_benchmark_english_",
    "open_agronomy_public_verification_",
)
EXTERNAL_RELEASE_AUTHORITY = PurePosixPath(
    "open_agronomy_agent/docs/conference_release_authority_20260810.json"
)


def _sha256_stream(handle: Any) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def verify(archive_path: Path) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    errors: list[str] = []
    with tarfile.open(archive_path, "r:gz") as archive:
        members = {PurePosixPath(member.name): member for member in archive.getmembers()}
        unsafe = [
            str(path)
            for path in members
            if path.is_absolute() or ".." in path.parts or not path.is_relative_to(ARCHIVE_ROOT)
        ]
        if unsafe:
            errors.append("unsafe archive members: " + ", ".join(unsafe[:10]))
        manifest_member = members.get(MANIFEST_PATH)
        if manifest_member is None:
            raise ValueError(f"portable bundle manifest is missing: {MANIFEST_PATH}")
        manifest_handle = archive.extractfile(manifest_member)
        if manifest_handle is None:
            raise ValueError("portable bundle manifest is not a regular file")
        manifest = json.load(manifest_handle)
        if manifest.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
            errors.append(f"unsupported schema: {manifest.get('schema_version')}")
        if manifest.get("status") != "pass":
            errors.append(f"embedded manifest status is not pass: {manifest.get('status')}")

        entries = manifest.get("entries") if isinstance(manifest.get("entries"), list) else []
        if len(entries) != manifest.get("file_count"):
            errors.append("manifest file_count does not match entries")
        hash_failures: list[str] = []
        for entry in entries:
            relative = PurePosixPath(str(entry.get("path") or ""))
            member = members.get(ARCHIVE_ROOT / relative)
            if member is None or not member.isfile():
                hash_failures.append(f"missing:{relative}")
                continue
            handle = archive.extractfile(member)
            if handle is None or _sha256_stream(handle) != entry.get("sha256"):
                hash_failures.append(f"sha256:{relative}")
        if hash_failures:
            errors.append("entry verification failed: " + ", ".join(hash_failures[:20]))

        geospatial_entries = [
            entry for entry in entries if entry.get("role") == "offline_geospatial_context"
        ]
        if manifest.get("schema_version") in {
            "open_agronomy_agent.portable_runtime_bundle.v3",
            SCHEMA_VERSION,
        }:
            if len(geospatial_entries) != manifest.get("offline_geospatial_file_count"):
                errors.append("offline geospatial file count does not match entries")
            if sum(int(entry.get("bytes") or 0) for entry in geospatial_entries) != manifest.get(
                "offline_geospatial_bytes"
            ):
                errors.append("offline geospatial byte count does not match entries")
            layer_ids = manifest.get("offline_geospatial_layer_ids")
            if not isinstance(layer_ids, list) or len(layer_ids) != manifest.get(
                "offline_geospatial_layer_count"
            ):
                errors.append("offline geospatial layer count does not match layer IDs")
            soil_gate = manifest.get("national_soil_context_gate")
            if not isinstance(soil_gate, dict):
                errors.append("national soil context gate is missing")
            elif soil_gate.get("release_eligible") is not False:
                errors.append("national soil context gate must remain fail-closed in this bundle")

        benchmark_entries = [
            entry for entry in entries if entry.get("role") == "benchmark_evidence"
        ]
        if manifest.get("schema_version") == SCHEMA_VERSION:
            if len(benchmark_entries) != manifest.get("benchmark_evidence_file_count"):
                errors.append("benchmark evidence file count does not match entries")
            if sum(int(entry.get("bytes") or 0) for entry in benchmark_entries) != manifest.get(
                "benchmark_evidence_bytes"
            ):
                errors.append("benchmark evidence byte count does not match entries")
            evidence_sets = manifest.get("benchmark_evidence_sets")
            if not isinstance(evidence_sets, dict):
                errors.append("benchmark evidence set inventory is missing")
            elif manifest.get("benchmark_evidence_required") is True:
                incomplete = [
                    str(set_id)
                    for set_id, record in evidence_sets.items()
                    if not isinstance(record, dict) or record.get("included") is not True
                ]
                if incomplete:
                    errors.append(
                        "required benchmark evidence sets are incomplete: " + ", ".join(incomplete)
                    )

        excluded_present = [
            str(row.get("path"))
            for row in manifest.get("excluded_corpora") or []
            if ARCHIVE_ROOT / PurePosixPath(str(row.get("path") or "")) in members
        ]
        if excluded_present:
            errors.append("excluded corpus bytes are present: " + ", ".join(excluded_present))
        model_weights = [
            str(path)
            for path, member in members.items()
            if member.isfile() and path.suffix.lower() in MODEL_WEIGHT_SUFFIXES
        ]
        if model_weights:
            errors.append("model weights are present: " + ", ".join(model_weights[:20]))
        historical_plans = [str(path) for path in members if "plans" in path.parts]
        if historical_plans:
            errors.append(
                "historical plan artifacts are present: " + ", ".join(historical_plans[:20])
            )
        retired_eval = [
            str(path)
            for path in members
            if any(marker in str(path) for marker in RETIRED_EVAL_MARKERS)
        ]
        if retired_eval:
            errors.append(
                "retired or quarantined evaluation artifacts are present: "
                + ", ".join(retired_eval[:20])
            )
        if EXTERNAL_RELEASE_AUTHORITY in members:
            errors.append(
                "external release authority is embedded and cannot hash-authorize its own archive"
            )

    return {
        "schema_version": "open_agronomy_agent.portable_bundle_verification.v1",
        "status": "pass" if not errors else "fail",
        "archive_path": str(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": _sha256_stream(archive_path.open("rb")),
        "entry_count": len(entries),
        "runtime_knowledge_file_count": manifest.get("runtime_knowledge_file_count"),
        "included_corpus_count": manifest.get("included_corpus_count"),
        "included_graph_count": manifest.get("included_graph_count"),
        "excluded_corpus_count": manifest.get("excluded_corpus_count"),
        "offline_geospatial_layer_count": manifest.get("offline_geospatial_layer_count", 0),
        "offline_geospatial_file_count": len(geospatial_entries),
        "benchmark_evidence_file_count": len(benchmark_entries),
        "benchmark_evidence_required": manifest.get("benchmark_evidence_required", False),
        "model_weights_included": bool(model_weights),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.archive)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
