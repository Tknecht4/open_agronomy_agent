from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agronomy_agent.agno_runtime.knowledge_factory import KnowledgeSearchResult, build_knowledge
from agronomy_agent.agno_runtime.source_manifest import AgnoSourceManifest
from agronomy_agent.paths import repo_path


@dataclass(frozen=True)
class PlannedIngestJob:
    source_id: str
    status: str
    runtime: str
    reader: str
    chunking_strategy: str
    embedder_profile: str
    knowledge_base: str
    contents_table: str
    vector_table: str
    duplicate_of_source_id: str | None
    retry_limit: int
    metadata: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "runtime": self.runtime,
            "reader": self.reader,
            "chunking_strategy": self.chunking_strategy,
            "embedder_profile": self.embedder_profile,
            "knowledge_base": self.knowledge_base,
            "contents_table": self.contents_table,
            "vector_table": self.vector_table,
            "duplicate_of_source_id": self.duplicate_of_source_id,
            "retry_limit": self.retry_limit,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ExecutedIngestJob:
    plan: PlannedIngestJob
    status: str
    chunk_count: int
    docs: tuple[dict[str, Any], ...]
    search_result: KnowledgeSearchResult | None
    error_message: str | None

    def as_record(self) -> dict[str, Any]:
        return {
            **self.plan.as_record(),
            "status": self.status,
            "chunk_count": self.chunk_count,
            "docs": list(self.docs),
            "search_result_doc_ids": [doc.doc_id for doc in self.search_result.docs] if self.search_result else [],
            "error_message": self.error_message,
        }


def plan_ingest_job(
    manifest: AgnoSourceManifest,
    *,
    existing_duplicate_keys: dict[str, str] | None = None,
) -> PlannedIngestJob:
    existing_duplicate_keys = existing_duplicate_keys or {}
    ingestion = manifest.raw.get("ingestion") or {}
    retry_policy = ingestion.get("retry_policy") if isinstance(ingestion.get("retry_policy"), dict) else {}
    duplicate_of = existing_duplicate_keys.get(manifest.duplicate_key)
    enabled = bool(ingestion.get("enabled", True))
    license_status = manifest.license_status
    status = "queued"
    if duplicate_of and duplicate_of != manifest.source_id:
        status = "duplicate"
    elif not enabled:
        status = "disabled"
    elif license_status == "blocked":
        status = "blocked_license"
    elif license_status == "restricted":
        status = "needs_review"
    return PlannedIngestJob(
        source_id=manifest.source_id,
        status=status,
        runtime="agno_knowledge",
        reader=str(ingestion.get("agno_reader") or "TextReader"),
        chunking_strategy=str(ingestion.get("chunking_strategy") or "FixedSizeChunking"),
        embedder_profile=str(manifest.raw.get("knowledge", {}).get("embedder_profile") or "local_default"),
        knowledge_base=manifest.knowledge_base,
        contents_table=manifest.contents_table,
        vector_table=manifest.vector_table,
        duplicate_of_source_id=duplicate_of if status == "duplicate" else None,
        retry_limit=int(retry_policy.get("max_attempts", 1)),
        metadata={
            "dedupe_key": manifest.duplicate_key,
            "canonical_url_hash": hashlib.sha256(manifest.canonical_url.encode("utf-8")).hexdigest() if manifest.canonical_url else None,
            "reviewer_status": (manifest.raw.get("quality") or {}).get("reviewer_status"),
            "file_history_enabled": bool(ingestion.get("file_history_enabled", True)),
            "status_polling_required": bool((manifest.raw.get("workflow") or {}).get("status_polling_required", True)),
        },
    )


def execute_manifest_ingest(
    manifest: AgnoSourceManifest,
    *,
    store: Any | None = None,
    workspace_id: str | None = None,
    existing_duplicate_keys: dict[str, str] | None = None,
    probe_query: str | None = None,
) -> ExecutedIngestJob:
    plan = plan_ingest_job(manifest, existing_duplicate_keys=existing_duplicate_keys)
    _persist_source(store, manifest, workspace_id=workspace_id)
    if plan.status != "queued":
        _persist_job(store, plan, status=plan.status, chunk_count=0, error_message=None)
        return ExecutedIngestJob(plan=plan, status=plan.status, chunk_count=0, docs=(), search_result=None, error_message=None)

    try:
        text = _read_manifest_text(manifest)
        docs = tuple(_docs_from_manifest_text(manifest, text))
        if not docs:
            raise ValueError("source text produced zero Agno Knowledge chunks")
        config = {
            "agno": {
                "knowledge": {
                    "default_base": manifest.knowledge_base,
                    "contents_table": manifest.contents_table,
                    "vector_table": manifest.vector_table,
                    "search_type": manifest.raw.get("knowledge", {}).get("search_type", "hybrid"),
                    "embedder_profile": manifest.raw.get("knowledge", {}).get("embedder_profile", "local_default"),
                    "metadata": manifest.metadata,
                },
                "retrieval": {"top_k": min(8, len(docs)), "final_context_k": min(5, len(docs))},
            }
        }
        knowledge = build_knowledge(config, docs)
        search = knowledge.search(probe_query or manifest.display_name, top_k=min(3, len(docs)))
    except Exception as exc:
        _persist_job(store, plan, status="failed", chunk_count=0, error_message=str(exc))
        return ExecutedIngestJob(plan=plan, status="failed", chunk_count=0, docs=(), search_result=None, error_message=str(exc))

    _persist_job(store, plan, status="completed", chunk_count=len(docs), error_message=None)
    _persist_version(store, manifest, status="indexed", chunk_count=len(docs))
    for doc in docs:
        _persist_chunk_review(store, manifest, chunk_id=str(doc["doc_id"]))
    return ExecutedIngestJob(plan=plan, status="completed", chunk_count=len(docs), docs=docs, search_result=search, error_message=None)


def _read_manifest_text(manifest: AgnoSourceManifest) -> str:
    local_path = str(manifest.local_path or "").strip()
    if not local_path:
        raise ValueError("manifest provenance.local_path is required for local Agno ingest execution")
    target = repo_path(local_path) if not Path(local_path).is_absolute() else Path(local_path)
    if not target.exists() or not target.is_file():
        raise ValueError(f"manifest local_path is not a readable file: {local_path}")
    if target.suffix.lower() not in {".txt", ".md", ".json", ".jsonl", ".csv", ".tsv"}:
        raise ValueError(f"unsupported Agno ingest source format: {target.suffix or 'unknown'}")
    return target.read_text(encoding="utf-8")


def _docs_from_manifest_text(manifest: AgnoSourceManifest, text: str) -> list[dict[str, Any]]:
    ingestion = manifest.raw.get("ingestion") or {}
    max_chars = max(200, int(ingestion.get("chunk_size_chars") or 3000))
    chunks = _chunk_text(text, max_chars=max_chars)
    metadata = manifest.metadata
    return [
        {
            "doc_id": f"{manifest.source_id}_{idx:04d}",
            "title": manifest.display_name,
            "text": chunk,
            "source": manifest.source_id,
            "source_type": str(metadata.get("source_type") or "applied_guidance"),
            "tags": [manifest.source_id, manifest.visibility, str(metadata.get("access_level") or manifest.visibility)],
            "allowed_roles": list(metadata.get("audience") or ["farmer", "crop_adviser"]),
            "knowledge_domains": list(metadata.get("knowledge_domains") or []),
            "knowledge_bucket": str(metadata.get("knowledge_bucket") or ""),
            "namespaces": list(metadata.get("namespaces") or []),
        }
        for idx, chunk in enumerate(chunks, start=1)
    ]


def _chunk_text(text: str, *, max_chars: int) -> list[str]:
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in cleaned.split("\n"):
        if current and current_len + len(paragraph) + 1 > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        if len(paragraph) > max_chars:
            chunks.extend(paragraph[index : index + max_chars] for index in range(0, len(paragraph), max_chars))
            continue
        current.append(paragraph)
        current_len += len(paragraph) + 1
    if current:
        chunks.append("\n".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def _persist_source(store: Any | None, manifest: AgnoSourceManifest, *, workspace_id: str | None) -> None:
    if store is None or not hasattr(store, "create_knowledge_source"):
        return
    store.create_knowledge_source(
        {
            "workspace_id": workspace_id,
            "source_id": manifest.source_id,
            "title": manifest.display_name,
            "owner": manifest.raw.get("owner", "unknown"),
            "visibility": manifest.visibility,
            "license_status": manifest.license_status,
            "canonical_url": manifest.canonical_url,
            "artifact_path": manifest.local_path,
            "checksum_sha256": manifest.checksum_sha256,
            "source_kind": manifest.raw.get("source_kind"),
            "rag_eligible": True,
            "sft_eligible": bool(manifest.raw.get("license", {}).get("commercial_use_allowed") is True),
            "metadata": {"knowledge_base": manifest.knowledge_base, **manifest.metadata},
        }
    )


def _persist_job(store: Any | None, plan: PlannedIngestJob, *, status: str, chunk_count: int, error_message: str | None) -> None:
    if store is None or not hasattr(store, "create_knowledge_ingest_job"):
        return
    store.create_knowledge_ingest_job({**plan.as_record(), "status": status, "chunk_count": chunk_count, "error_message": error_message})


def _persist_version(store: Any | None, manifest: AgnoSourceManifest, *, status: str, chunk_count: int) -> None:
    if store is None or not hasattr(store, "create_knowledge_source_version"):
        return
    store.create_knowledge_source_version(
        {
            "source_id": manifest.source_id,
            "checksum_sha256": manifest.checksum_sha256,
            "canonical_url": manifest.canonical_url,
            "artifact_path": manifest.local_path,
            "status": status,
            "metadata": {"chunk_count": chunk_count, "knowledge_base": manifest.knowledge_base},
        }
    )


def _persist_chunk_review(store: Any | None, manifest: AgnoSourceManifest, *, chunk_id: str) -> None:
    if store is None or not hasattr(store, "create_knowledge_chunk_review"):
        return
    quality = manifest.raw.get("quality") or {}
    store.create_knowledge_chunk_review(
        {
            "source_id": manifest.source_id,
            "chunk_id": chunk_id,
            "reviewer_status": quality.get("reviewer_status") or "pending",
            "rejection_reasons": quality.get("rejection_reasons") or [],
            "evidence_coordinates": {"source_id": manifest.source_id},
        }
    )
