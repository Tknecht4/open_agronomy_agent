from __future__ import annotations

import json
from pathlib import Path

import pytest

from agronomy_agent.server.redis_preflight import RedisPreflightError, preflight_redis
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.object_store_preflight import main as object_store_preflight_main
from agronomy_agent.server.worker import main as worker_main


class _RedisProbeClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.queues: dict[str, list[str]] = {}
        self.deleted: list[str] = []

    def execute(self, command: str, *args: str) -> object:
        if self.failure is not None:
            raise self.failure
        if command == "PING":
            return "PONG"
        if command == "RPUSH":
            queue, token = args
            self.queues.setdefault(queue, []).append(token)
            return len(self.queues[queue])
        if command == "LPOP":
            queue = args[0]
            values = self.queues.setdefault(queue, [])
            return values.pop(0) if values else None
        if command == "INCR":
            return 1
        if command == "EXPIRE":
            return 1
        if command == "TTL":
            return 60
        if command == "DEL":
            self.deleted.append(args[0])
            return 1
        raise AssertionError(f"unexpected Redis command: {command}")


def test_local_worker_once_reports_that_no_queue_was_consumed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = worker_main(
        [
            "--once",
            "--db-path",
            str(tmp_path / "worker.sqlite3"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ready"
    assert payload["queue_backend"] == "sqlite-local"
    assert payload["queue_enabled"] is False
    assert "note" in payload


def test_local_worker_healthcheck_is_non_consuming(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = worker_main(
        [
            "--healthcheck",
            "--db-path",
            str(tmp_path / "worker.sqlite3"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "queue_backend": "sqlite-local",
        "queue_enabled": False,
        "status": "ready",
        "worker": "phase4-local",
    }


def test_redis_preflight_checks_every_queue_and_cleans_probe_keys(tmp_path: Path) -> None:
    client = _RedisProbeClient()
    settings = build_settings(
        db_path=tmp_path / "worker.sqlite3",
        artifact_root=tmp_path / "artifacts",
        job_queue_backend="redis",
        redis_url="redis://example.test:6379/0",
    )

    result = preflight_redis(
        settings,
        client_factory=lambda _url: client,
        probe_prefix="agronomy:test-preflight",
    )

    assert result.backend == "redis"
    assert result.queue_write_pop_checked is True
    assert result.rate_limit_counter_checked is True
    assert len(result.queue_names) == 5
    assert len(client.deleted) == 6


def test_redis_preflight_redacts_configured_url_from_failures(tmp_path: Path) -> None:
    redis_url = "redis://user:secret@example.test:6379/0"
    client = _RedisProbeClient(failure=OSError(f"cannot connect to {redis_url}"))
    settings = build_settings(
        db_path=tmp_path / "worker.sqlite3",
        artifact_root=tmp_path / "artifacts",
        job_queue_backend="redis",
        redis_url=redis_url,
    )

    with pytest.raises(RedisPreflightError) as error:
        preflight_redis(settings, client_factory=lambda _url: client)

    assert redis_url not in str(error.value)
    assert "redis://<redacted>" in str(error.value)


def test_local_object_store_preflight_round_trips_and_cleans_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("AGRONOMY_AGENT_DB_PATH", str(tmp_path / "worker.sqlite3"))
    monkeypatch.setenv("AGRONOMY_AGENT_ARTIFACT_ROOT", str(artifact_root))

    exit_code = object_store_preflight_main(["--backend", "local"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["backend"] == "local"
    assert not (artifact_root / ".phase4-preflight" / "probe.txt").exists()
