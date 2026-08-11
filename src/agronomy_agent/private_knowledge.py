from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agronomy_agent.paths import minimized_path_reference


PRIVATE_KNOWLEDGE_SCHEMA = "open_agronomy_agent.private_knowledge_overlay.v1"
PRIVATE_DISTRIBUTION_SCOPE = "local_only_not_for_redistribution"
PRIVATE_MANIFEST_ENV = "AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST"
PRIVATE_ENABLED_ENV = "AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"


@dataclass(frozen=True)
class PrivateKnowledgeOverlay:
    manifest_path: Path
    manifest_sha256: str
    corpus_paths: tuple[str, ...]
    row_count: int
    source_count: int
    distribution_scope: str
    answer_role: str
    manifest: dict[str, Any]

    def trace_record(self) -> dict[str, Any]:
        """Return provenance that is safe to persist without copying private text."""

        return {
            "enabled": True,
            "status": "loaded",
            "manifest_path": minimized_path_reference(self.manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "corpus_count": len(self.corpus_paths),
            "row_count": self.row_count,
            "source_count": self.source_count,
            "distribution_scope": self.distribution_scope,
            "answer_role": self.answer_role,
        }


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def private_knowledge_manifest_path(
    root: Path,
    config: dict[str, Any] | None,
) -> tuple[Path | None, bool]:
    config = config if isinstance(config, dict) else {}
    enabled_override = os.getenv(PRIVATE_ENABLED_ENV, "").strip().lower()
    if enabled_override in {"0", "false", "off", "disabled", "none"}:
        return None, False
    if config.get("enabled", False) is not True:
        return None, bool(config.get("required", False))
    override = os.getenv(PRIVATE_MANIFEST_ENV, "").strip()
    value = override or str(config.get("manifest_path") or "").strip()
    if not value:
        if config.get("required", False):
            raise ValueError("private knowledge is required but no manifest_path is configured")
        return None, False
    return _resolve_path(root, value), bool(config.get("required", False))


def load_private_knowledge_overlay(
    root: Path,
    config: dict[str, Any] | None,
) -> PrivateKnowledgeOverlay | None:
    """Load and integrity-check an optional, machine-local corpus overlay.

    Distribution rights and answer authority are deliberately independent. A
    local source may be useful background without being redistributable or
    decisive for a field action. Every overlay corpus therefore fails closed to
    context-only answer authority, regardless of row-level retrieval metadata.
    """

    manifest_path, required = private_knowledge_manifest_path(root, config)
    if manifest_path is None:
        return None
    if not manifest_path.is_file():
        if required:
            raise FileNotFoundError(f"required private knowledge manifest is missing: {manifest_path}")
        return None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != PRIVATE_KNOWLEDGE_SCHEMA:
        raise ValueError("unsupported private knowledge manifest schema")
    if manifest.get("distribution_scope") != PRIVATE_DISTRIBUTION_SCOPE:
        raise ValueError("private knowledge manifest must be local-only")
    if manifest.get("answer_role") != "context_only":
        raise ValueError("private knowledge manifest answer_role must be context_only")

    corpora = manifest.get("corpora")
    if not isinstance(corpora, list) or not corpora:
        raise ValueError("private knowledge manifest must contain at least one corpus")

    paths: list[str] = []
    total_rows = 0
    for entry in corpora:
        if not isinstance(entry, dict):
            raise ValueError("private knowledge corpus entries must be objects")
        value = str(entry.get("path") or "").strip()
        if not value or value in paths:
            raise ValueError("private knowledge corpus paths must be non-empty and unique")
        if entry.get("distribution_scope") != PRIVATE_DISTRIBUTION_SCOPE:
            raise ValueError(f"private corpus is not marked local-only: {value}")
        if entry.get("answer_role") != "context_only":
            raise ValueError(f"private corpus answer_role must be context_only: {value}")
        corpus_path = _resolve_path(root, value)
        if not corpus_path.is_file():
            raise FileNotFoundError(f"private knowledge corpus is missing: {corpus_path}")
        actual_sha = sha256_path(corpus_path)
        expected_sha = str(entry.get("sha256") or "")
        if not expected_sha or actual_sha != expected_sha:
            raise ValueError(f"private knowledge corpus SHA-256 mismatch: {value}")
        expected_rows = int(entry.get("rows") or 0)
        with corpus_path.open("r", encoding="utf-8") as handle:
            actual_rows = sum(1 for line in handle if line.strip())
        if expected_rows <= 0 or actual_rows != expected_rows:
            raise ValueError(f"private knowledge corpus row-count mismatch: {value}")
        paths.append(value)
        total_rows += actual_rows

    summary = manifest.get("summary") if isinstance(manifest.get("summary"), dict) else {}
    declared_rows = int(summary.get("rows") or total_rows)
    if declared_rows != total_rows:
        raise ValueError("private knowledge manifest summary row count does not match corpora")
    return PrivateKnowledgeOverlay(
        manifest_path=manifest_path,
        manifest_sha256=sha256_path(manifest_path),
        corpus_paths=tuple(paths),
        row_count=total_rows,
        source_count=int(summary.get("sources") or 0),
        distribution_scope=PRIVATE_DISTRIBUTION_SCOPE,
        answer_role="context_only",
        manifest=manifest,
    )


def merge_private_overlay_policy(
    public_policy: dict[str, Any],
    overlay: PrivateKnowledgeOverlay | None,
) -> dict[str, Any]:
    if overlay is None:
        return public_policy
    if not public_policy:
        raise ValueError("private knowledge requires a governed public corpus policy")
    merged = {**public_policy, "corpora": [dict(item) for item in public_policy.get("corpora", [])]}
    known_paths = {str(item.get("path") or "") for item in merged["corpora"]}
    entries_by_path = {
        str(entry.get("path") or ""): entry
        for entry in overlay.manifest.get("corpora", [])
        if isinstance(entry, dict)
    }
    for path in overlay.corpus_paths:
        if path in known_paths:
            raise ValueError(f"private knowledge path collides with public policy: {path}")
        entry = entries_by_path[path]
        merged["corpora"].append(
            {
                "path": path,
                "runtime_path_reference": minimized_path_reference(path),
                "sha256": entry["sha256"],
                "rows": entry["rows"],
                "runtime_eligibility": "context_only",
                "answer_role": "context_only",
                "distribution_scope": PRIVATE_DISTRIBUTION_SCOPE,
                "reason": "machine-local evidence overlay; useful as background but never sufficient authority for a high-consequence action",
                "private_manifest_sha256": overlay.manifest_sha256,
            }
        )
        known_paths.add(path)
    return merged
