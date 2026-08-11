from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def run_attachment_embedding_job(store: Any, job_id: str, *, worker_name: str = "local_worker") -> dict[str, Any]:
    job = store.get_phase4_embedding_job(job_id)
    if not job:
        raise ValueError(f"embedding job not found: {job_id}")
    attachment = store.get_phase4_attachment(job["attachment_id"])
    if not attachment:
        return store.update_phase4_embedding_job(
            job_id=job_id,
            status="failed",
            result={"worker": worker_name},
            error_message="attachment not found",
            finished_at=_now_iso(),
        ) or {}
    store.update_phase4_embedding_job(
        job_id=job_id,
        status="running",
        result={**job.get("result", {}), "worker": worker_name},
        started_at=_now_iso(),
    )
    try:
        result = store.replace_phase4_attachment_embeddings(attachment["id"], worker_name=worker_name)
    except Exception as exc:
        return store.update_phase4_embedding_job(
            job_id=job_id,
            status="failed",
            result={"worker": worker_name, "unhandled_error": exc.__class__.__name__},
            error_message=str(exc),
            finished_at=_now_iso(),
        ) or {}
    return store.update_phase4_embedding_job(
        job_id=job_id,
        status="completed",
        result=result,
        error_message=None,
        finished_at=_now_iso(),
    ) or {}


def run_queued_embedding_jobs(store: Any, *, limit: int = 1, worker_name: str = "local_worker") -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be > 0")
    jobs = store.list_phase4_queued_embedding_jobs(limit=limit)
    return run_embedding_job_ids(
        store,
        [job["id"] for job in jobs],
        requested_limit=limit,
        worker_name=worker_name,
        queue_name="embedding",
    )


def run_embedding_job_ids(
    store: Any,
    job_ids: list[str],
    *,
    requested_limit: int,
    worker_name: str = "local_worker",
    queue_name: str = "embedding",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for job_id in job_ids:
        try:
            result = run_attachment_embedding_job(store, job_id, worker_name=worker_name)
        except Exception as exc:
            result = store.update_phase4_embedding_job(
                job_id=job_id,
                status="failed",
                result={"worker": worker_name, "unhandled_error": exc.__class__.__name__},
                error_message=str(exc),
                finished_at=_now_iso(),
            ) or {"id": job_id, "status": "failed"}
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
