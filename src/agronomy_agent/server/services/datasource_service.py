from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agronomy_agent.paths import repo_path


def read_checksum(path: str) -> str:
    target = repo_path(path) if path and not Path(path).is_absolute() else Path(path)
    if not target.exists():
        return ""
    if target.is_file():
        return _hash_file(target)
    if target.is_dir():
        return _hash_directory(target)
    return ""


def inspect_source(path: str | None = None, url: str | None = None) -> dict[str, Any]:
    if path:
        target = repo_path(path) if not Path(path).is_absolute() else Path(path)
        if not target.exists():
            return {"exists": False, "path": str(path), "type": "missing"}
        if target.is_file():
            return {
                "exists": True,
                "path": str(target),
                "type": target.suffix.lower() or "file",
                "size": target.stat().st_size,
            }
        if target.is_dir():
            files = [p.as_posix() for p in target.rglob("*") if p.is_file()]
            return {
                "exists": True,
                "path": str(target),
                "type": "directory",
                "file_count": len(files),
            }
    if url:
        return {"exists": True, "url": url, "type": "url"}
    return {"exists": False, "type": "unknown"}


def run_local_data_source_ingest(store: Any, job_id: str, *, worker_name: str = "local_inline") -> dict[str, Any]:
    job = store.get_phase4_ingest_job(job_id)
    if not job:
        raise ValueError(f"ingest job not found: {job_id}")
    data_source = store.get_phase4_data_source(job["data_source_id"])
    if not data_source:
        return store.update_phase4_ingest_job(
            job_id=job_id,
            status="failed",
            result={"chunk_count": 0, "worker": worker_name},
            error_message="data source not found",
            finished_at=_now_iso(),
        )

    started_at = _now_iso()
    store.update_phase4_ingest_job(
        job_id=job_id,
        status="running",
        result={**job.get("result", {}), "worker": worker_name},
        started_at=started_at,
    )
    try:
        source_text, source_kind = _load_data_source_text(data_source)
        chunks = _chunk_text(source_text)
        if not chunks:
            raise ValueError("source text produced zero chunks after cleanup")
        chunk_count = store.replace_phase4_data_source_chunks(
            data_source=data_source,
            chunks=[
                {
                    "text_content": chunk,
                    "metadata": {"source_kind": source_kind},
                }
                for chunk in chunks
            ],
        )
    except Exception as exc:
        return store.update_phase4_ingest_job(
            job_id=job_id,
            status="failed",
            result={
                "chunk_count": 0,
                "worker": worker_name,
                "source_id": data_source["source_id"],
            },
            error_message=str(exc),
            finished_at=_now_iso(),
        )

    return store.update_phase4_ingest_job(
        job_id=job_id,
        status="completed",
        result={
            "chunk_count": chunk_count,
            "worker": worker_name,
            "source_id": data_source["source_id"],
            "source_kind": source_kind,
        },
        error_message=None,
        finished_at=_now_iso(),
    )


def run_queued_data_source_ingests(store: Any, *, limit: int = 1, worker_name: str = "local_worker") -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be > 0")
    jobs = store.list_phase4_queued_ingest_jobs(limit=limit)
    return run_data_source_ingest_jobs(store, [job["id"] for job in jobs], requested_limit=limit, worker_name=worker_name, queue_name="ingest")


def run_data_source_ingest_jobs(
    store: Any,
    job_ids: list[str],
    *,
    requested_limit: int,
    worker_name: str = "local_worker",
    queue_name: str = "ingest",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for job_id in job_ids:
        try:
            result = run_local_data_source_ingest(store, job_id, worker_name=worker_name)
        except Exception as exc:
            result = store.update_phase4_ingest_job(
                job_id=job_id,
                status="failed",
                result={"chunk_count": 0, "worker": worker_name, "unhandled_error": exc.__class__.__name__},
                error_message=str(exc),
                finished_at=_now_iso(),
            )
        results.append(result)
    return {
        "queue": queue_name,
        "worker": worker_name,
        "requested_limit": requested_limit,
        "processed": len(results),
        "completed": sum(1 for item in results if item.get("status") == "completed"),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "job_ids": [item.get("id") for item in results],
    }


def _load_data_source_text(data_source: dict[str, Any]) -> tuple[str, str]:
    metadata = data_source.get("metadata") or {}
    inline_text = str(metadata.get("text_content") or "")
    if inline_text.strip():
        return inline_text, "inline_text"

    source_path = str(metadata.get("source_path") or "").strip()
    if source_path:
        target = repo_path(source_path) if not Path(source_path).is_absolute() else Path(source_path)
        if not target.exists() or not target.is_file():
            raise ValueError(f"source_path is not a readable file: {source_path}")
        if target.suffix.lower() not in {".txt", ".md", ".json", ".jsonl", ".csv", ".tsv"}:
            raise ValueError(f"unsupported local source format: {target.suffix or 'unknown'}")
        return target.read_text(encoding="utf-8"), "local_file"

    raise ValueError("no local ingest content available; provide text_content or source_path")


def _chunk_text(text: str, *, max_chars: int = 1200) -> list[str]:
    cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in cleaned.split("\n"):
        paragraph_len = len(paragraph)
        if current and current_len + paragraph_len + 1 > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        if paragraph_len > max_chars:
            chunks.extend(paragraph[index : index + max_chars] for index in range(0, paragraph_len, max_chars))
            continue
        current.append(paragraph)
        current_len += paragraph_len + 1
    if current:
        chunks.append("\n".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file():
            continue
        digest.update(str(file_path.relative_to(path)).encode("utf-8"))
        digest.update(str(_hash_file(file_path)).encode("utf-8"))
    return digest.hexdigest()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
