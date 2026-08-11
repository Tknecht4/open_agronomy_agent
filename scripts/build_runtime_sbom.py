#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any


PYTHON_REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9_.-]+)(.*)$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _python_packages(path: Path) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        match = PYTHON_REQUIREMENT_RE.match(value)
        if not match:
            continue
        name, specifier = match.groups()
        packages.append(
            {
                "SPDXID": f"SPDXRef-Python-{re.sub(r'[^A-Za-z0-9.-]', '-', name)}",
                "name": name,
                "versionInfo": specifier.strip() or "unspecified",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "supplier": "NOASSERTION",
                "comment": "Direct container requirement; version is a declared range, not a fully locked transitive resolution.",
            }
        )
    return packages


def _frontend_packages(path: Path) -> list[dict[str, Any]]:
    lock = json.loads(path.read_text(encoding="utf-8"))
    packages: list[dict[str, Any]] = []
    for package_path, record in sorted((lock.get("packages") or {}).items()):
        if not package_path.startswith("node_modules/") or not isinstance(record, dict):
            continue
        name = package_path.removeprefix("node_modules/")
        if "/node_modules/" in name:
            name = name.rsplit("/node_modules/", 1)[-1]
        version = str(record.get("version") or "unspecified")
        identifier = re.sub(r"[^A-Za-z0-9.-]", "-", f"{name}-{version}-{package_path}")[:180]
        packages.append(
            {
                "SPDXID": f"SPDXRef-Npm-{identifier}",
                "name": name,
                "versionInfo": version,
                "downloadLocation": str(record.get("resolved") or "NOASSERTION"),
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": str(record.get("license") or "NOASSERTION"),
                "supplier": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:npm/{name.replace('@', '%40')}@{version}",
                    }
                ],
            }
        )
    return packages


def build_sbom(root: Path) -> dict[str, Any]:
    requirements = root / "requirements-container.txt"
    package_lock = root / "frontend/package-lock.json"
    root_package = {
        "SPDXID": "SPDXRef-OpenAgronomyAgent",
        "name": "open-agronomy-agent-edge-runtime",
        "versionInfo": "0.1.0",
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "supplier": "Organization: Open Agronomy Agent project",
    }
    dependencies = [*_python_packages(requirements), *_frontend_packages(package_lock)]
    input_digest = hashlib.sha256(
        (requirements.read_bytes() + package_lock.read_bytes())
    ).hexdigest()
    namespace_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"open-agronomy-agent-sbom:{input_digest}")
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "Open Agronomy Agent edge runtime dependency inventory",
        "documentNamespace": f"urn:uuid:{namespace_uuid}",
        "creationInfo": {
            "creators": ["Tool: scripts/build_runtime_sbom.py"],
            "created": "2026-07-23T00:00:00Z",
            "comment": (
                "Frontend transitive versions come from package-lock.json. Python entries are direct declared ranges "
                "because the container requirements are not fully locked; resolve and attach an image-level SBOM at release."
            ),
        },
        "documentDescribes": [root_package["SPDXID"]],
        "packages": [root_package, *dependencies],
        "relationships": [
            {
                "spdxElementId": root_package["SPDXID"],
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": package["SPDXID"],
            }
            for package in dependencies
        ],
        "annotations": [
            {
                "annotationType": "OTHER",
                "annotator": "Tool: scripts/build_runtime_sbom.py",
                "annotationDate": "2026-07-23T00:00:00Z",
                "comment": json.dumps(
                    {
                        "requirements_container_sha256": _sha256(requirements),
                        "frontend_package_lock_sha256": _sha256(package_lock),
                        "python_direct_dependency_count": len(_python_packages(requirements)),
                        "frontend_locked_package_count": len(_frontend_packages(package_lock)),
                    },
                    sort_keys=True,
                ),
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic release dependency inventory in SPDX JSON.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("outputs/release/open_agronomy_agent.spdx.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    sbom = build_sbom(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "pass",
                "output": str(output),
                "sha256": _sha256(output),
                "package_count": len(sbom["packages"]),
                "python_lock_boundary": "declared_ranges_only",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
