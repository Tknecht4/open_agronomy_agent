from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Sequence

from agronomy_agent.server.queue import JobQueueUnavailable, build_job_queue
from agronomy_agent.server.services.datasource_service import run_data_source_ingest_jobs, run_queued_data_source_ingests
from agronomy_agent.server.services.embedding_service import run_embedding_job_ids, run_queued_embedding_jobs
from agronomy_agent.server.services.eval_service import run_eval_run_ids, run_queued_eval_runs
from agronomy_agent.server.services.export_service import run_phase4_export_job_ids, run_queued_phase4_export_jobs
from agronomy_agent.server.services.image_observation import build_image_observation_adapter
from agronomy_agent.server.services.image_rag_service import run_image_job_ids, run_queued_image_jobs
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.storage.object_store import build_object_store


def _run_queued_ingest(*, db_path: str | None, artifact_root: str | None, max_jobs: int) -> dict[str, object]:
    settings = build_settings(
        db_path=Path(db_path) if db_path else None,
        artifact_root=Path(artifact_root) if artifact_root else None,
    )
    store = TraceStore(settings.db_path)
    if settings.job_queue_backend == "redis":
        queue = build_job_queue(settings)
        job_ids = queue.pop_ingest_jobs(limit=max_jobs)
        return run_data_source_ingest_jobs(
            store,
            job_ids,
            requested_limit=max_jobs,
            worker_name="redis_worker",
            queue_name=settings.job_queue_name,
        )
    return run_queued_data_source_ingests(store, limit=max_jobs, worker_name="local_worker")


def _run_queued_evals(*, db_path: str | None, artifact_root: str | None, max_jobs: int) -> dict[str, object]:
    settings = build_settings(
        db_path=Path(db_path) if db_path else None,
        artifact_root=Path(artifact_root) if artifact_root else None,
    )
    store = TraceStore(settings.db_path)
    if settings.job_queue_backend == "redis":
        queue = build_job_queue(settings)
        run_ids = queue.pop_eval_runs(limit=max_jobs)
        return run_eval_run_ids(
            store,
            run_ids,
            requested_limit=max_jobs,
            worker_name="redis_worker",
            queue_name=settings.eval_queue_name,
        )
    return run_queued_eval_runs(store, limit=max_jobs, worker_name="local_worker")


def _run_queued_exports(*, db_path: str | None, artifact_root: str | None, max_jobs: int) -> dict[str, object]:
    settings = build_settings(
        db_path=Path(db_path) if db_path else None,
        artifact_root=Path(artifact_root) if artifact_root else None,
    )
    store = TraceStore(settings.db_path)
    object_store = build_object_store(settings)
    if settings.job_queue_backend == "redis":
        queue = build_job_queue(settings)
        job_ids = queue.pop_export_jobs(limit=max_jobs)
        return run_phase4_export_job_ids(
            store=store,
            object_store=object_store,
            storage_backend=settings.object_store_backend,
            job_ids=job_ids,
            requested_limit=max_jobs,
            worker_name="redis_worker",
            queue_name=settings.export_queue_name,
        )
    return run_queued_phase4_export_jobs(
        store=store,
        object_store=object_store,
        storage_backend=settings.object_store_backend,
        limit=max_jobs,
        worker_name="local_worker",
    )


def _run_queued_embeddings(*, db_path: str | None, artifact_root: str | None, max_jobs: int) -> dict[str, object]:
    settings = build_settings(
        db_path=Path(db_path) if db_path else None,
        artifact_root=Path(artifact_root) if artifact_root else None,
    )
    store = TraceStore(settings.db_path)
    if settings.job_queue_backend == "redis":
        queue = build_job_queue(settings)
        job_ids = queue.pop_embedding_jobs(limit=max_jobs)
        return run_embedding_job_ids(
            store,
            job_ids,
            requested_limit=max_jobs,
            worker_name="redis_worker",
            queue_name=settings.embedding_queue_name,
        )
    return run_queued_embedding_jobs(store, limit=max_jobs, worker_name="local_worker")


def _run_queued_images(*, db_path: str | None, artifact_root: str | None, max_jobs: int) -> dict[str, object]:
    settings = build_settings(
        db_path=Path(db_path) if db_path else None,
        artifact_root=Path(artifact_root) if artifact_root else None,
    )
    store = TraceStore(settings.db_path)
    observation_adapter = build_image_observation_adapter(settings)
    if settings.job_queue_backend == "redis":
        queue = build_job_queue(settings)
        job_ids = queue.pop_image_jobs(limit=max_jobs)
        return run_image_job_ids(
            store=store,
            observation_adapter=observation_adapter,
            job_ids=job_ids,
            requested_limit=max_jobs,
            worker_name="redis_worker",
            queue_name=settings.image_queue_name,
        )
    return run_queued_image_jobs(
        store=store,
        observation_adapter=observation_adapter,
        limit=max_jobs,
        worker_name="local_worker",
    )


def _status(
    *,
    queue_enabled: bool,
    queue_backend: str = "sqlite-local",
    ingest_summary: dict[str, object] | None = None,
    eval_summary: dict[str, object] | None = None,
    export_summary: dict[str, object] | None = None,
    embedding_summary: dict[str, object] | None = None,
    image_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ready",
        "worker": "phase4-local",
        "queue_backend": queue_backend,
        "queue_enabled": queue_enabled,
    }
    if ingest_summary is not None:
        payload["ingest"] = ingest_summary
    if eval_summary is not None:
        payload["eval"] = eval_summary
    if export_summary is not None:
        payload["exports"] = export_summary
    if embedding_summary is not None:
        payload["embedding"] = embedding_summary
    if image_summary is not None:
        payload["image"] = image_summary
    if ingest_summary is None and eval_summary is None and export_summary is None and embedding_summary is None and image_summary is None:
        payload["note"] = "Queued execution is not enabled; pass --run-queued-ingest, --run-queued-evals, --run-queued-exports, --run-queued-embeddings, and/or --run-queued-images."
    return payload


def _healthcheck(*, db_path: str | None, artifact_root: str | None) -> tuple[int, dict[str, object]]:
    try:
        settings = build_settings(
            db_path=Path(db_path) if db_path else None,
            artifact_root=Path(artifact_root) if artifact_root else None,
        )
        queue = build_job_queue(settings)
        queue_status = queue.healthcheck()
    except Exception as exc:
        return 1, {
            "status": "unhealthy",
            "worker": "phase4-local",
            "queue_backend": "unknown",
            "queue_enabled": False,
            "error": str(exc),
        }
    return 0, {
        "status": "ready",
        "worker": "phase4-local",
        "queue_backend": str(queue_status.get("backend") or settings.job_queue_backend),
        "queue_enabled": settings.job_queue_backend == "redis",
    }


def _run_enabled_queues(
    *,
    db_path: str | None,
    artifact_root: str | None,
    max_jobs: int,
    run_ingest: bool,
    run_evals: bool,
    run_exports: bool,
    run_embeddings: bool,
    run_images: bool,
) -> tuple[dict[str, object] | None, dict[str, object] | None, dict[str, object] | None, dict[str, object] | None, dict[str, object] | None]:
    ingest_summary = _run_queued_ingest(db_path=db_path, artifact_root=artifact_root, max_jobs=max_jobs) if run_ingest else None
    eval_summary = _run_queued_evals(db_path=db_path, artifact_root=artifact_root, max_jobs=max_jobs) if run_evals else None
    export_summary = _run_queued_exports(db_path=db_path, artifact_root=artifact_root, max_jobs=max_jobs) if run_exports else None
    embedding_summary = _run_queued_embeddings(db_path=db_path, artifact_root=artifact_root, max_jobs=max_jobs) if run_embeddings else None
    image_summary = _run_queued_images(db_path=db_path, artifact_root=artifact_root, max_jobs=max_jobs) if run_images else None
    return ingest_summary, eval_summary, export_summary, embedding_summary, image_summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4 local worker.")
    parser.add_argument("--once", action="store_true", help="Print one status payload and exit.")
    parser.add_argument("--healthcheck", action="store_true", help="Check worker settings and queue connectivity without consuming jobs.")
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--run-queued-ingest", action="store_true", help="Process queued local ingest jobs each tick.")
    parser.add_argument("--run-queued-evals", action="store_true", help="Process queued eval runs each tick.")
    parser.add_argument("--run-queued-exports", action="store_true", help="Process queued thread export jobs each tick.")
    parser.add_argument("--run-queued-embeddings", action="store_true", help="Process queued attachment embedding jobs each tick.")
    parser.add_argument("--run-queued-images", action="store_true", help="Process queued image observation jobs each tick.")
    parser.add_argument("--max-jobs", type=int, default=1, help="Maximum queued jobs to process per queue per tick.")
    parser.add_argument("--db-path", help="SQLite database path. Defaults to AGRONOMY_AGENT_DB_PATH.")
    parser.add_argument("--artifact-root", help="Artifact root. Defaults to AGRONOMY_AGENT_ARTIFACT_ROOT.")
    args = parser.parse_args(argv)
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")
    if args.max_jobs <= 0:
        raise SystemExit("--max-jobs must be positive")

    if args.healthcheck:
        exit_code, payload = _healthcheck(db_path=args.db_path, artifact_root=args.artifact_root)
        print(json.dumps(payload, sort_keys=True), flush=True)
        return exit_code

    try:
        settings = build_settings(db_path=Path(args.db_path) if args.db_path else None, artifact_root=Path(args.artifact_root) if args.artifact_root else None)
        queue_backend = "redis" if settings.job_queue_backend == "redis" else "sqlite-local"
        ingest_summary, eval_summary, export_summary, embedding_summary, image_summary = _run_enabled_queues(
            db_path=args.db_path,
            artifact_root=args.artifact_root,
            max_jobs=args.max_jobs,
            run_ingest=args.run_queued_ingest,
            run_evals=args.run_queued_evals,
            run_exports=args.run_queued_exports,
            run_embeddings=args.run_queued_embeddings,
            run_images=args.run_queued_images,
        )
    except JobQueueUnavailable as exc:
        queue_backend = "redis"
        ingest_summary = {"queue": "ingest", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_ingest else None
        eval_summary = {"queue": "eval", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_evals else None
        export_summary = {"queue": "exports", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_exports else None
        embedding_summary = {"queue": "embedding", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_embeddings else None
        image_summary = {"queue": "image", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_images else None
    print(
        json.dumps(
            _status(
                queue_enabled=args.run_queued_ingest or args.run_queued_evals or args.run_queued_exports or args.run_queued_embeddings or args.run_queued_images,
                queue_backend=queue_backend,
                ingest_summary=ingest_summary,
                eval_summary=eval_summary,
                export_summary=export_summary,
                embedding_summary=embedding_summary,
                image_summary=image_summary,
            ),
            sort_keys=True,
        ),
        flush=True,
    )
    if args.once:
        return 0

    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        time.sleep(args.interval_seconds)
        try:
            ingest_summary, eval_summary, export_summary, embedding_summary, image_summary = _run_enabled_queues(
                db_path=args.db_path,
                artifact_root=args.artifact_root,
                max_jobs=args.max_jobs,
                run_ingest=args.run_queued_ingest,
                run_evals=args.run_queued_evals,
                run_exports=args.run_queued_exports,
                run_embeddings=args.run_queued_embeddings,
                run_images=args.run_queued_images,
            )
        except JobQueueUnavailable as exc:
            ingest_summary = {"queue": "ingest", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_ingest else None
            eval_summary = {"queue": "eval", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_evals else None
            export_summary = {"queue": "exports", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_exports else None
            embedding_summary = {"queue": "embedding", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_embeddings else None
            image_summary = {"queue": "image", "processed": 0, "completed": 0, "failed": 1, "error": str(exc)} if args.run_queued_images else None
        print(
            json.dumps(
                _status(
                    queue_enabled=args.run_queued_ingest or args.run_queued_evals or args.run_queued_exports or args.run_queued_embeddings or args.run_queued_images,
                    queue_backend=queue_backend,
                    ingest_summary=ingest_summary,
                    eval_summary=eval_summary,
                    export_summary=export_summary,
                    embedding_summary=embedding_summary,
                    image_summary=image_summary,
                ),
                sort_keys=True,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
