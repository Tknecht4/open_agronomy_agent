from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


TOKEN = "field-pairing-token-with-at-least-32-characters"
SECRET = "field-session-secret-with-at-least-32-characters"


def test_field_lan_pairing_keeps_https_cookie_behavior(tmp_path: Path) -> None:
    settings = build_settings(
        db_path=tmp_path / "field.sqlite3",
        artifact_root=tmp_path / "artifacts",
        allow_local_dev_auth=False,
        local_pairing_token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest(),
        oidc_session_secret=SECRET,
    )
    client = TestClient(create_app(settings), base_url="https://field-runtime.test")

    response = client.post("/auth/local-pair", json={"token": TOKEN})

    assert response.status_code == 200
    assert all("secure" in cookie.lower() for cookie in response.headers.get_list("set-cookie"))
    assert client.get("/auth/me").status_code == 200
    assert client.get("/api/health").json()["local_pairing"]["transport_required"] == "https"
    assert "launch_id" not in client.get("/api/health").json()["local_pairing"]


@pytest.mark.parametrize("base_url", ["http://field-runtime.test", "http://127.0.0.1:8000", "http://[::1]:8000"])
@pytest.mark.parametrize("headers", [{}, {"X-Forwarded-Proto": "https"}, {"Forwarded": "proto=https"}])
def test_field_pairing_rejects_http_without_consuming_token(tmp_path: Path, base_url: str, headers: dict) -> None:
    settings = build_settings(
        db_path=tmp_path / "field.sqlite3",
        artifact_root=tmp_path / "artifacts",
        allow_local_dev_auth=False,
        local_pairing_token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest(),
        oidc_session_secret=SECRET,
    )
    app = create_app(settings)
    insecure = TestClient(app, base_url=base_url)

    for token in ("wrong-field-pairing-token-with-32-characters", TOKEN):
        rejected = insecure.post("/auth/local-pair", json={"token": token}, headers=headers)
        assert rejected.status_code == 403
        assert rejected.json()["detail"] == "local pairing requires direct HTTPS"
        assert not rejected.headers.get_list("set-cookie")
        assert not insecure.cookies
        assert app.state.local_pairing_consumed is False
        assert app.state.trace_store.get_phase4_user_by_email("local-demo@open-agronomy.local") is None
        assert insecure.get("/auth/me").status_code == 401

    secure = TestClient(app, base_url="https://field-runtime.test")
    accepted = secure.post("/auth/local-pair", json={"token": TOKEN})
    assert accepted.status_code == 200
    assert all("secure" in cookie.lower() for cookie in accepted.headers.get_list("set-cookie"))
    assert secure.get("/auth/me").status_code == 200
    assert secure.post("/auth/local-pair", json={"token": TOKEN}).status_code == 409


@pytest.mark.parametrize("header", ["Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Forwarded-Port"])
def test_field_pairing_rejects_forwarding_metadata_even_with_https_scope(tmp_path: Path, header: str) -> None:
    settings = build_settings(
        db_path=tmp_path / "field.sqlite3",
        artifact_root=tmp_path / "artifacts",
        allow_local_dev_auth=False,
        local_pairing_token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest(),
        oidc_session_secret=SECRET,
    )
    app = create_app(settings)
    client = TestClient(app, base_url="https://field-runtime.test")
    # The ASGI scheme is already HTTPS, as after a proxy rewrites HTTP metadata.
    rejected = client.post("/auth/local-pair", json={"token": TOKEN}, headers={header: "https"})
    assert rejected.status_code == 403
    assert not rejected.headers.get_list("set-cookie")
    assert app.state.local_pairing_consumed is False
    assert app.state.trace_store.get_phase4_user_by_email("local-demo@open-agronomy.local") is None
    accepted = client.post("/auth/local-pair", json={"token": TOKEN})
    assert accepted.status_code == 200
