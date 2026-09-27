from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.rate_limit import FixedWindowRateLimiter
from agronomy_agent.server.settings import (
    RETIRED_HOSTED_BACKEND_ENV_VARS,
    build_settings,
)
from agronomy_agent.server.storage.object_store import LocalObjectStore


def test_local_rate_limiter_has_no_remote_backend() -> None:
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=60)

    first = limiter.check("local-user", now=1.0)
    second = limiter.check("local-user", now=2.0)
    blocked = limiter.check("local-user", now=3.0)

    assert limiter.backend == "memory"
    assert first.allowed is True
    assert second.allowed is True
    assert blocked.allowed is False


def test_local_artifact_store_round_trips_root_relative_references(
    tmp_path: Path,
) -> None:
    store = LocalObjectStore(tmp_path / "artifacts")

    stored = store.put_text("exports/thread-1/report.md", "local private report")

    assert store.backend == "local"
    assert stored.path.is_file()
    assert store.reference_for_uri(stored.uri) == "exports/thread-1/report.md"
    assert store.get_bytes("exports/thread-1/report.md") == b"local private report"
    assert store.delete_uri("exports/thread-1/report.md") is True
    assert store.delete_uri("exports/thread-1/report.md") is False


def test_local_artifact_store_rejects_paths_outside_its_root(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="escapes storage root"):
        store.put_text("../outside.txt", "blocked")


@pytest.mark.parametrize("variable", RETIRED_HOSTED_BACKEND_ENV_VARS)
def test_retired_hosted_backend_environment_fails_closed(
    variable: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(variable, "retired-value")

    with pytest.raises(ValueError, match="hosted backends were removed") as error:
        build_settings(
            db_path=tmp_path / "runtime.sqlite3",
            artifact_root=tmp_path / "artifacts",
        )

    assert variable in str(error.value)


def test_server_settings_expose_only_local_queue_storage_and_rate_limit_controls(
    tmp_path: Path,
) -> None:
    settings = build_settings(
        db_path=tmp_path / "runtime.sqlite3",
        artifact_root=tmp_path / "artifacts",
    )

    removed_fields = {
        "rate_limit_backend",
        "redis_url",
        "rate_limit_fail_open",
        "job_queue_backend",
        "job_queue_fail_open",
        "object_store_backend",
        "object_store_endpoint",
        "object_store_bucket",
        "object_store_access_key",
        "object_store_secret_key",
    }
    assert removed_fields.isdisjoint(settings.__dataclass_fields__)


def test_health_reports_fixed_local_private_backends(tmp_path: Path) -> None:
    settings = build_settings(
        db_path=tmp_path / "runtime.sqlite3",
        artifact_root=tmp_path / "artifacts",
    )

    response = TestClient(create_app(settings)).get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["object_store"] == {"backend": "local"}
    assert payload["rate_limit"] == {"backend": "memory", "fail_open": False}
    assert payload["job_queue"] == {
        "backend": "database-recorded",
        "database_backend": "sqlite",
        "fail_open": False,
        "scope": "application_private",
    }
