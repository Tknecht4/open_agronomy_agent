from __future__ import annotations

from typing import Any

from agronomy_agent.server.rate_limit import RateLimiterUnavailable, RedisProtocolClient
from agronomy_agent.server.settings import ServerSettings


class JobQueueUnavailable(RuntimeError):
    pass


class LocalJobQueue:
    backend = "sqlite-local"

    def healthcheck(self) -> dict[str, Any]:
        return {"backend": self.backend, "status": "ready"}

    def enqueue_ingest_job(self, job_id: str) -> dict[str, Any]:
        return {"backend": self.backend, "enqueued": True, "job_id": job_id}

    def enqueue_eval_run(self, run_id: str) -> dict[str, Any]:
        return {"backend": self.backend, "enqueued": True, "run_id": run_id}

    def enqueue_export_job(self, job_id: str) -> dict[str, Any]:
        return {"backend": self.backend, "enqueued": True, "job_id": job_id}

    def enqueue_embedding_job(self, job_id: str) -> dict[str, Any]:
        return {"backend": self.backend, "enqueued": True, "job_id": job_id}

    def enqueue_image_job(self, job_id: str) -> dict[str, Any]:
        return {"backend": self.backend, "enqueued": True, "job_id": job_id}

    def pop_ingest_jobs(self, *, limit: int) -> list[str]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        return []

    def pop_eval_runs(self, *, limit: int) -> list[str]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        return []

    def pop_export_jobs(self, *, limit: int) -> list[str]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        return []

    def pop_embedding_jobs(self, *, limit: int) -> list[str]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        return []

    def pop_image_jobs(self, *, limit: int) -> list[str]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        return []


class RedisJobQueue:
    backend = "redis"

    def __init__(
        self,
        *,
        redis_url: str,
        queue_name: str = "agronomy:jobs:ingest",
        eval_queue_name: str = "agronomy:jobs:eval",
        export_queue_name: str = "agronomy:jobs:exports",
        embedding_queue_name: str = "agronomy:jobs:embedding",
        image_queue_name: str = "agronomy:jobs:image",
        client: Any | None = None,
    ) -> None:
        if not redis_url.strip() and client is None:
            raise ValueError("redis_url is required")
        self.queue_name = queue_name.strip() or "agronomy:jobs:ingest"
        self.eval_queue_name = eval_queue_name.strip() or "agronomy:jobs:eval"
        self.export_queue_name = export_queue_name.strip() or "agronomy:jobs:exports"
        self.embedding_queue_name = embedding_queue_name.strip() or "agronomy:jobs:embedding"
        self.image_queue_name = image_queue_name.strip() or "agronomy:jobs:image"
        self.client = client or RedisProtocolClient(redis_url)

    def enqueue_ingest_job(self, job_id: str) -> dict[str, Any]:
        return self._enqueue(self.queue_name, "job_id", job_id)

    def enqueue_eval_run(self, run_id: str) -> dict[str, Any]:
        return self._enqueue(self.eval_queue_name, "run_id", run_id)

    def enqueue_export_job(self, job_id: str) -> dict[str, Any]:
        return self._enqueue(self.export_queue_name, "job_id", job_id)

    def enqueue_embedding_job(self, job_id: str) -> dict[str, Any]:
        return self._enqueue(self.embedding_queue_name, "job_id", job_id)

    def enqueue_image_job(self, job_id: str) -> dict[str, Any]:
        return self._enqueue(self.image_queue_name, "job_id", job_id)

    def pop_ingest_jobs(self, *, limit: int) -> list[str]:
        return self._pop(self.queue_name, limit=limit)

    def pop_eval_runs(self, *, limit: int) -> list[str]:
        return self._pop(self.eval_queue_name, limit=limit)

    def pop_export_jobs(self, *, limit: int) -> list[str]:
        return self._pop(self.export_queue_name, limit=limit)

    def pop_embedding_jobs(self, *, limit: int) -> list[str]:
        return self._pop(self.embedding_queue_name, limit=limit)

    def pop_image_jobs(self, *, limit: int) -> list[str]:
        return self._pop(self.image_queue_name, limit=limit)

    def healthcheck(self) -> dict[str, Any]:
        try:
            response = self.client.execute("PING")
        except (OSError, TypeError, ValueError, RateLimiterUnavailable) as exc:
            raise JobQueueUnavailable(str(exc)) from exc
        if isinstance(response, bytes):
            response_text = response.decode("utf-8", errors="replace")
        else:
            response_text = str(response)
        if response_text.upper() != "PONG":
            raise JobQueueUnavailable(f"unexpected Redis PING response: {response!r}")
        return {"backend": self.backend, "status": "ready"}

    def _enqueue(self, queue_name: str, id_key: str, item_id: str) -> dict[str, Any]:
        if not item_id.strip():
            raise ValueError(f"{id_key} is required")
        try:
            depth = int(self.client.execute("RPUSH", queue_name, item_id))
        except (OSError, TypeError, ValueError, RateLimiterUnavailable) as exc:
            raise JobQueueUnavailable(str(exc)) from exc
        return {"backend": self.backend, "enqueued": True, id_key: item_id, "queue_name": queue_name, "depth": depth}

    def _pop(self, queue_name: str, *, limit: int) -> list[str]:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        item_ids: list[str] = []
        try:
            for _ in range(limit):
                item_id = self.client.execute("LPOP", queue_name)
                if item_id is None:
                    break
                item_ids.append(str(item_id))
        except (OSError, TypeError, ValueError, RateLimiterUnavailable) as exc:
            raise JobQueueUnavailable(str(exc)) from exc
        return item_ids


def build_job_queue(settings: ServerSettings) -> LocalJobQueue | RedisJobQueue:
    if settings.job_queue_backend == "redis":
        return RedisJobQueue(
            redis_url=str(settings.redis_url or ""),
            queue_name=settings.job_queue_name,
            eval_queue_name=settings.eval_queue_name,
            export_queue_name=settings.export_queue_name,
            embedding_queue_name=settings.embedding_queue_name,
            image_queue_name=settings.image_queue_name,
        )
    return LocalJobQueue()
