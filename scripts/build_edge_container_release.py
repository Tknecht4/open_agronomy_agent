#!/usr/bin/env python3
"""Assemble a machine-readable release manifest for the shared OCI artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_release(
    root: Path,
    *,
    version: str,
    image: str,
    archive: Path,
    archive_validation: Path,
    package_validation: Path,
    translation_validation: Path,
    sbom: Path,
    release_evidence: list[Path] | None = None,
) -> dict[str, Any]:
    runtime_manifest_path = root / "container/runtime_manifest.json"
    runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
    oci = json.loads(archive_validation.read_text(encoding="utf-8"))
    package = json.loads(package_validation.read_text(encoding="utf-8"))
    translation = json.loads(translation_validation.read_text(encoding="utf-8"))
    statuses = {
        "runtime_manifest": runtime_manifest.get("status"),
        "package_validation": package.get("status"),
        "oci_archive_validation": oci.get("status"),
        "runtime_translation_validation": translation.get("status"),
    }
    return {
        "schema_version": "open_agronomy_agent.edge_container_release.v4",
        "status": "pass" if set(statuses.values()) == {"pass"} else "fail",
        "version": version,
        "image": image,
        "platform": "linux/arm64",
        "runtime_contract_sha256": runtime_manifest.get("contract_sha256"),
        "runtime_manifest_file_sha256": _sha256(runtime_manifest_path),
        "archive": {
            "path": archive.name,
            "bytes": archive.stat().st_size,
            "sha256": _sha256(archive),
            "format": "OCI image layout tar",
        },
        "sbom": {
            "path": sbom.name,
            "bytes": sbom.stat().st_size,
            "sha256": _sha256(sbom),
            "format": "SPDX-2.3 JSON",
            "python_dependency_boundary": "direct declared ranges; attach image-resolved SBOM before production promotion",
        },
        "release_evidence": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in (release_evidence or [])
        ],
        "runtime_parity": {
            "artifact_policy": "byte_identical_shared_oci_archive",
            "apple_container": {
                "role": "reference_runtime",
                "import": f"container image load --input {archive.name}",
                "launcher": "container/apple.sh",
            },
            "docker": {
                "role": "direct_translation",
                "import": f"docker load --input {archive.name}",
                "launcher": "container/docker.sh",
            },
            "application_port": 8080,
            "persistent_mount": "/state",
            "model_protocol": "OpenAI-compatible HTTP to native MLX host",
            "model_weights_in_archive": False,
            "translation_validation": translation_validation.name,
        },
        "validation": statuses,
        "knowledge": {
            "files": package.get("runtime_knowledge_file_count"),
            "bytes": package.get("runtime_knowledge_bytes"),
        },
        "geospatial_layers": {
            "files": package.get("bundled_geo_layer_file_count"),
            "bytes": package.get("bundled_geo_layer_bytes"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--version", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-validation", type=Path, required=True)
    parser.add_argument("--package-validation", type=Path, required=True)
    parser.add_argument("--translation-validation", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument(
        "--release-evidence",
        type=Path,
        action="append",
        default=[],
        help="External source/readiness receipt to bind beside, not inside, the OCI archive.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_release(
        args.root.resolve(),
        version=args.version,
        image=args.image,
        archive=args.archive.resolve(),
        archive_validation=args.archive_validation.resolve(),
        package_validation=args.package_validation.resolve(),
        translation_validation=args.translation_validation.resolve(),
        sbom=args.sbom.resolve(),
        release_evidence=[path.resolve() for path in args.release_evidence],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
