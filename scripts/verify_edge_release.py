#!/usr/bin/env python3
"""Verify a checksummed edge release before importing its OCI archive."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from agronomy_agent.artifact_signature import verify_manifest_signature
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checksum_entries(release_dir: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    entries: dict[str, str] = {}
    checksum_path = release_dir / "SHA256SUMS"
    if not checksum_path.is_file():
        return entries, ["release is missing SHA256SUMS"]
    for line_number, raw in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        digest, separator, name = raw.partition("  ")
        if not separator:
            errors.append(f"SHA256SUMS line {line_number} is malformed")
            continue
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.name != name:
            errors.append(f"SHA256SUMS line {line_number} has an unsafe path")
            continue
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            errors.append(f"SHA256SUMS line {line_number} has an invalid digest")
            continue
        if name in entries:
            errors.append(f"SHA256SUMS repeats {name}")
            continue
        entries[name] = digest
    return entries, errors


def verify_release(
    release_dir: Path,
    *,
    public_key: Path | None = None,
    require_signature: bool = False,
) -> dict[str, Any]:
    release_dir = release_dir.resolve()
    errors: list[str] = []
    checksums, checksum_errors = _checksum_entries(release_dir)
    errors.extend(checksum_errors)
    verified_files = 0
    for name, expected in checksums.items():
        path = release_dir / name
        if not path.is_file():
            errors.append(f"checksummed release file is missing: {name}")
            continue
        actual = _sha256(path)
        if actual != expected:
            errors.append(f"checksum mismatch: {name}")
            continue
        verified_files += 1

    manifest_path = release_dir / "release_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"release manifest is unreadable: {exc}")
        manifest = {}

    if manifest_path.name not in checksums:
        errors.append("release_manifest.json is not checksum-bound")
    if manifest.get("status") != "pass":
        errors.append("release manifest status is not pass")
    if manifest.get("platform") != "linux/arm64":
        errors.append("release platform is not linux/arm64")
    version = str(manifest.get("version") or "")
    image = str(manifest.get("image") or "")
    archive_record = manifest.get("archive") or {}
    archive_name = str(archive_record.get("path") or "")
    archive_path = release_dir / archive_name if archive_name else release_dir / "missing"
    if not version or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for character in version):
        errors.append("release version is missing or unsafe")
    image_repository, separator, image_version = image.rpartition(":")
    if not separator or not image_repository or image_version != version or "\n" in image:
        errors.append("release image does not match the versioned tag contract")
    if Path(archive_name).name != archive_name:
        errors.append("release archive path is unsafe")
    if archive_name not in checksums:
        errors.append("release archive is not checksum-bound")
    if archive_path.is_file():
        archive_sha = _sha256(archive_path)
        if archive_sha != archive_record.get("sha256"):
            errors.append("release archive hash does not match release_manifest.json")
        if archive_path.stat().st_size != int(archive_record.get("bytes") or -1):
            errors.append("release archive size does not match release_manifest.json")
    else:
        archive_sha = None
        errors.append("release archive is missing")

    for name in ("package_validation.json", "oci_archive_validation.json"):
        path = release_dir / name
        if name not in checksums:
            errors.append(f"{name} is not checksum-bound")
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{name} is unreadable: {exc}")
            continue
        if report.get("status") != "pass":
            errors.append(f"{name} status is not pass")
    if manifest.get("schema_version") in {
        "open_agronomy_agent.edge_container_release.v3",
        "open_agronomy_agent.edge_container_release.v4",
    }:
        translation_name = str(
            (manifest.get("runtime_parity") or {}).get("translation_validation") or ""
        )
        if Path(translation_name).name != translation_name or translation_name not in checksums:
            errors.append("runtime translation validation is missing or not checksum-bound")
        else:
            try:
                translation = json.loads((release_dir / translation_name).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"runtime translation validation is unreadable: {exc}")
            else:
                if translation.get("status") != "pass":
                    errors.append("runtime translation validation status is not pass")
    if manifest.get("schema_version") == "open_agronomy_agent.edge_container_release.v4":
        sbom_record = manifest.get("sbom") if isinstance(manifest.get("sbom"), dict) else {}
        sbom_name = str(sbom_record.get("path") or "")
        sbom_path = release_dir / sbom_name
        if Path(sbom_name).name != sbom_name or sbom_name not in checksums:
            errors.append("SBOM is missing or not checksum-bound")
        elif not sbom_path.is_file() or _sha256(sbom_path) != sbom_record.get("sha256"):
            errors.append("SBOM hash does not match release_manifest.json")
    release_evidence = manifest.get("release_evidence")
    if release_evidence is not None:
        if not isinstance(release_evidence, list) or not release_evidence:
            errors.append("release evidence must be a non-empty list")
        else:
            evidence_names: set[str] = set()
            for item in release_evidence:
                if not isinstance(item, dict):
                    errors.append("release evidence record is malformed")
                    continue
                name = str(item.get("path") or "")
                path = release_dir / name
                if (
                    Path(name).name != name
                    or name in evidence_names
                    or name not in checksums
                ):
                    errors.append(f"release evidence is unsafe or not checksum-bound: {name}")
                    continue
                evidence_names.add(name)
                if not path.is_file():
                    errors.append(f"release evidence is missing: {name}")
                    continue
                if _sha256(path) != item.get("sha256"):
                    errors.append(f"release evidence hash does not match release manifest: {name}")
                if path.stat().st_size != int(item.get("bytes") or -1):
                    errors.append(f"release evidence size does not match release manifest: {name}")

    signature_path = release_dir / "SHA256SUMS.sig"
    signature_status = "not_required"
    if public_key is not None:
        if not signature_path.is_file():
            errors.append("release signature is missing")
            signature_status = "missing"
        else:
            signature_report = verify_manifest_signature(
                manifest=release_dir / "SHA256SUMS",
                public_key=public_key.resolve(),
                signature=signature_path,
            )
            signature_status = signature_report["status"]
            if not signature_report["verified"]:
                errors.append("release signature is invalid")
    elif require_signature:
        errors.append("a trusted release public key is required")
        signature_status = "trusted_key_missing"

    return {
        "schema_version": "open_agronomy_agent.edge_release_import_preflight.v1",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "release_dir": str(release_dir),
        "version": version,
        "image": image,
        "archive_path": str(archive_path.resolve()),
        "archive_sha256": archive_sha,
        "verified_file_count": verified_files,
        "signature_status": signature_status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--format", choices=("json", "lines"), default="json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--allow-unsigned", action="store_true")
    args = parser.parse_args()
    report = verify_release(
        args.release_dir,
        public_key=args.public_key,
        require_signature=not args.allow_unsigned,
    )
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.format == "lines" and report["status"] == "pass":
        print(report["version"])
        print(report["image"])
        print(report["archive_path"])
        print(report["archive_sha256"])
    else:
        print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
