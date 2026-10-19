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


def test_incomplete_local_snapshot_has_a_specific_setup_error(tmp_path: Path) -> None:
    from agronomy_agent.agent import LocalModelSnapshotUnavailable, resolve_local_model_snapshot

    with pytest.raises(LocalModelSnapshotUnavailable, match="incomplete"):
        resolve_local_model_snapshot(str(tmp_path))


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure_stage", ["construction", "tokenization", "generation"])
def test_expected_model_setup_failure_is_actionable_without_a_saved_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream: bool, failure_stage: str,
) -> None:
    from agronomy_agent.agent import LocalModelSnapshotUnavailable
    import agronomy_agent.server.services.chat_service as service

    settings = build_settings(
        db_path=tmp_path / "setup.sqlite3", artifact_root=tmp_path / "artifacts",
        network_mode="offline",
    )
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    created = client.post("/api/sessions", json={"title": "Synthetic setup recovery", "consent": {}})
    assert created.status_code == 200, created.text
    session = created.json()

    def missing(*args, **kwargs):
        raise LocalModelSnapshotUnavailable("private snapshot path must not reach the client")

    class LazyMissingBackend:
        model_id = settings.default_model_id
        max_tokens = 640

        def count_prompt_tokens(self, messages):
            if failure_stage == "tokenization":
                missing()
            return 100

        def generate(self, messages):
            missing()

    monkeypatch.setattr(service, "_build_mlx_generator", missing if failure_stage == "construction"
                        else lambda *args, **kwargs: LazyMissingBackend())
    suffix = "/stream" if stream else ""
    response = client.post(f"/api/sessions/{session['session_id']}/turns{suffix}", json={
        "message": "Explain crop rotation.", "mode": "agronomic_rag",
        "model_id": settings.default_model_id, "rag_config": "configs/rag.yaml",
    })
    assert response.status_code == (200 if stream else 503)
    assert "local_model_setup_required" in response.text
    assert "Complete model setup" in response.text
    assert "private snapshot path" not in response.text
    assert client.get(f"/api/sessions/{session['session_id']}").json()["turns"] == []


def test_unrelated_missing_file_is_not_misreported_as_model_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agronomy_agent.server.services.chat_service as service

    settings = build_settings(db_path=tmp_path / "unexpected.sqlite3", artifact_root=tmp_path / "artifacts")
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    created = client.post("/api/sessions", json={"title": "Synthetic unrelated failure", "consent": {}})
    assert created.status_code == 200, created.text
    session = created.json()

    def missing(*args, **kwargs):
        raise FileNotFoundError("unrelated runtime artifact")

    monkeypatch.setattr(service, "_build_mlx_generator", missing)
    response = client.post(f"/api/sessions/{session['session_id']}/turns", json={
        "message": "Explain crop rotation.", "mode": "agronomic_rag",
        "model_id": settings.default_model_id, "rag_config": "configs/rag.yaml",
    })
    assert response.status_code == 500
    assert "local_model_setup_required" not in response.text


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


def test_rate_limit_bounds_peers_without_evicting_active_budget():
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=10, max_keys=2)
    assert limiter.check('a', now=0).allowed
    assert limiter.check('b', now=1).allowed
    assert not limiter.check('c', now=2).allowed
    assert len(limiter._windows) == 2
    assert not limiter.check('a', now=3).allowed
    # Expiration at the exact boundary releases one slot without resetting b.
    assert limiter.check('c', now=10).allowed
    assert not limiter.check('b', now=10).allowed
    assert len(limiter._windows) == 2
    assert limiter.check('d', now=21).allowed
    assert list(limiter._windows) == ['d']


@pytest.mark.parametrize("local_dev", [True, False])
def test_public_routes_cannot_buy_rate_budget_with_rotating_identity_headers(tmp_path, local_dev):
    settings = build_settings(db_path=tmp_path/'rate.sqlite3', artifact_root=tmp_path/'artifacts',
                              rate_limit_requests=2, rate_limit_window_seconds=60, allow_local_dev_auth=local_dev)
    # Explicit origin keeps this independent of the shared TestClient default.
    client = TestClient(create_app(settings), base_url='http://127.0.0.1:8000')
    for i in range(2):
        response = client.get('/api/configs', headers={'Authorization': f'Bearer invalid-{i}',
                              'X-Agronomy-User-Email': f'synthetic-{i}@example.test'})
        assert response.status_code == 200
    denied = client.get('/api/configs', headers={'Authorization':'Bearer another', 'X-Agronomy-User-Email':'other@example.test'})
    assert denied.status_code == 429
    assert denied.headers['X-RateLimit-Remaining'] == '0'
    assert 1 <= int(denied.headers['Retry-After']) <= 60
    # Health remains a deliberately minimal readiness exemption.
    assert client.get('/api/health').status_code == 200
    assert 'db_path' not in client.get('/api/health').json()


@pytest.mark.parametrize('headers', [
    {'Host':'attacker.example'}, {'Host':'127.0.0.1.attacker.example'},
    {'Host':'127.0.0.1:bad'}, {'Host':'localhost@attacker.example'},
    {'Host':'[invalid'}, {'Host':'[::1'},
    {'Origin':'http://attacker.example'}, {'Origin':'null'},
    {'Origin':'http://localhost:9000'}, {'Origin':'http://localhost:5173/path'},
    {'X-Forwarded-For':'192.0.2.1'}, {'Forwarded':'for=192.0.2.1'},
    {'X-Forwarded-Host':'localhost:5173'}, {'X-Forwarded-Proto':'http'},
    {'X-Forwarded-Port':'5173'},
    [('Host','127.0.0.1:8000'),('Host','attacker.example')],
    [('Origin','http://localhost:5173'),('Origin','http://attacker.example')],
])
def test_dev_browser_authority_rejected_before_private_routes(tmp_path, headers):
    settings = build_settings(db_path=tmp_path/'origin.sqlite3', artifact_root=tmp_path/'artifacts')
    client = TestClient(create_app(settings), base_url='http://127.0.0.1:8000')
    assert client.get('/api/health', headers=headers).status_code == 403
    assert client.post('/api/sessions', json={'title':'must not save'}, headers=headers).status_code == 403
    assert client.get('/api/sessions').json() == []


@pytest.mark.parametrize('host', ['127.0.0.1:8000','localhost:8000','[::1]:8000'])
def test_dev_accepts_loopback_cli_same_origin_and_configured_frontend(tmp_path, host):
    settings = build_settings(db_path=tmp_path/'allowed.sqlite3', artifact_root=tmp_path/'artifacts',
                              local_dev_origins=('http://localhost:6199',))
    client = TestClient(create_app(settings), base_url=f'http://{host}')
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/health', headers={'Origin':f'http://{host}'}).status_code == 200
    assert client.get('/api/health', headers={'Origin':'http://localhost:6199'}).status_code == 200
    assert client.get('/api/health', headers={'Origin':'http://localhost:5173'}).status_code == 403


def test_default_vite_origin_and_untrusted_authority_have_distinct_contracts(tmp_path):
    client = TestClient(create_app(build_settings(db_path=tmp_path/'vite.sqlite3', artifact_root=tmp_path/'artifacts')),
                        base_url='http://127.0.0.1:8000')
    assert client.get('/api/health', headers={'Origin':'http://127.0.0.1:5173'}).status_code == 200
    assert client.get('/api/health', headers={'Host':'testserver'}).status_code == 403


def test_dev_settings_reject_remote_frontend_origin(tmp_path):
    with pytest.raises(ValueError, match='loopback origin'):
        build_settings(db_path=tmp_path/'invalid.sqlite3', artifact_root=tmp_path/'artifacts',
                       local_dev_origins=('http://attacker.example:5173',))
