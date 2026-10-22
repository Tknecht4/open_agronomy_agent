from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib

from scripts.build_edge_runtime_manifest import CONTROL_PATHS
from scripts.build_macos_app import ASSET_PATHS
from scripts.build_portable_agent_bundle import ROOT_FILES
from scripts.build_portable_agent_bundle import TREE_ROOTS
from scripts.build_public_repository import _collect
from scripts.build_runtime_sbom import build_sbom


ROOT = Path(__file__).resolve().parents[1]
LICENSE_ID = "PolyForm-Noncommercial-1.0.0"
LEGAL_FILES = {"LICENSE", "NOTICE", "LICENSES/Apache-2.0.txt", "THIRD_PARTY_NOTICES.md"}


def test_standard_license_and_actual_project_notice_are_distinct() -> None:
    # Exact official PolyForm text retrieved from its publisher on 2026-10-22.
    assert hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest() == (
        "7573a6c93397a51d957542a3e258750699c3bf1c437b4b85541ec551b87066a6"
    )
    notice = (ROOT / "NOTICE").read_text()
    required = [line for line in notice.splitlines() if line.startswith("Required Notice:")]
    assert required and all("Tknecht4" in line and "Yoyodyne" not in line for line in required)
    # Preserve the actual earlier grant rather than substituting another licence.
    assert hashlib.sha256((ROOT / "LICENSES/Apache-2.0.txt").read_bytes()).hexdigest() == (
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
    )


def test_distribution_metadata_and_legal_payload_agree() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["license"] == LICENSE_ID
    assert {"LICENSE", "NOTICE", "LICENSES/*.txt", "THIRD_PARTY_NOTICES.md"} <= set(project["license-files"])
    frontend = json.loads((ROOT / "frontend/package.json").read_text())
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    assert frontend["license"] == lock["packages"][""]["license"] == LICENSE_ID
    assert build_sbom(ROOT)["packages"][0]["licenseDeclared"] == LICENSE_ID
    assert LEGAL_FILES <= set(CONTROL_PATHS)
    assert LEGAL_FILES <= set(ROOT_FILES)
    assert all(any(path == root or path.startswith(root + "/") for root in ASSET_PATHS) for path in LEGAL_FILES)
    manifest = json.loads((ROOT / "configs/public_repository_manifest.json").read_text())
    public = {str(path.relative_to(ROOT)) for path in _collect(manifest)}
    assert LEGAL_FILES <= public
    container = (ROOT / "Containerfile").read_text()
    assert f'org.opencontainers.image.licenses="{LICENSE_ID}"' in container
    assert "COPY LICENSES ./LICENSES" in container
    assert "LICENSE NOTICE THIRD_PARTY_NOTICES.md" in container
    # Frontend build contexts must contain the new generator and its legal inputs.
    assert "COPY frontend/scripts ./scripts" in container
    assert "COPY LICENSE NOTICE /build/" in container
    launch = (ROOT / "frontend/Dockerfile.launch").read_text()
    assert "WORKDIR /app/frontend" in launch
    assert "COPY frontend/ ./" in launch
    assert "COPY LICENSE NOTICE /app/" in launch
    assert "frontend/scripts" in TREE_ROOTS


def test_upstream_and_frozen_artifact_licenses_remain_separate() -> None:
    graph = json.loads((ROOT / "data/seed/agronomy_knowledge_graph.manifest.json").read_text())
    assert graph["license"] == "Apache-2.0"
    assert "license: apache-2.0" in (ROOT / "configs/model.yaml").read_text()
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    assert "CC BY-NC-SA 4.0" in notices
    assert "share-alike" in notices
