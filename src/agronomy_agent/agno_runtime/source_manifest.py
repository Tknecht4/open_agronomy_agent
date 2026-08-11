from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.paths import repo_path


REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "source_id",
    "display_name",
    "owner",
    "visibility",
    "license",
    "provenance",
    "ingestion",
    "knowledge",
    "quality",
    "workflow",
)


@dataclass(frozen=True)
class AgnoSourceManifest:
    source_id: str
    display_name: str
    visibility: str
    license_status: str
    canonical_url: str
    local_path: str
    checksum_sha256: str
    knowledge_base: str
    contents_table: str
    vector_table: str
    metadata: dict[str, Any]
    raw: dict[str, Any]

    @property
    def duplicate_key(self) -> str:
        payload = f"{self.canonical_url}|{self.checksum_sha256}|{self.source_id}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_source_manifest(path: str | Path) -> AgnoSourceManifest:
    raw = yaml.safe_load(repo_path(path).read_text(encoding="utf-8")) or {}
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"Agno source manifest missing required fields: {', '.join(missing)}")
    if raw.get("schema_version") != "agno_rag_source_manifest_v1":
        raise ValueError("Agno source manifest schema_version must be agno_rag_source_manifest_v1")
    license_payload = raw.get("license") or {}
    provenance = raw.get("provenance") or {}
    knowledge = raw.get("knowledge") or {}
    metadata = dict(knowledge.get("metadata") or {})
    license_status = str(license_payload.get("status") or "").strip()
    if license_status not in {"approved", "review_required", "restricted", "blocked"}:
        raise ValueError("Agno source manifest license.status must be approved, review_required, restricted, or blocked")
    source_id = str(raw.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("Agno source manifest source_id must be non-empty")
    visibility = str(raw.get("visibility") or "").strip()
    if visibility not in {"public", "workspace", "private"}:
        raise ValueError("Agno source manifest visibility must be public, workspace, or private")
    return AgnoSourceManifest(
        source_id=source_id,
        display_name=str(raw.get("display_name") or source_id),
        visibility=visibility,
        license_status=license_status,
        canonical_url=str(provenance.get("canonical_url") or ""),
        local_path=str(provenance.get("local_path") or ""),
        checksum_sha256=str(provenance.get("checksum_sha256") or ""),
        knowledge_base=str(knowledge.get("knowledge_base") or "agronomy_public"),
        contents_table=str(knowledge.get("contents_table") or "agno_knowledge_contents"),
        vector_table=str(knowledge.get("vector_table") or "agno_knowledge_vectors"),
        metadata=metadata,
        raw=raw,
    )
