from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings
from scripts.run_cockpit import _build_parser, _validate_desktop_launch


ORIGIN = "http://127.0.0.1:48721"
TOKEN = "desktop-pairing-token-with-at-least-32-characters"
SECRET = "desktop-session-secret-with-at-least-32-characters"


def _settings(tmp_path: Path):  # noqa: ANN201
    return build_settings(
        db_path=tmp_path / "desktop.sqlite3",
        artifact_root=tmp_path / "artifacts",
        allow_local_dev_auth=False,
        local_pairing_token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest(),
        oidc_session_secret=SECRET,
        desktop_local_origin=ORIGIN,
    )


def test_desktop_pairing_issues_loopback_cookie_and_requires_csrf(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)), base_url=ORIGIN)
    origin_header = {"Origin": ORIGIN}

    assert client.get("/auth/me").status_code == 401
    assert client.post("/auth/local-pair", json={"token": "wrong-desktop-pairing-token-with-32-characters"}, headers=origin_header).status_code == 401
    response = client.post("/auth/local-pair", json={"token": TOKEN}, headers=origin_header)

    assert response.status_code == 200
    assert response.json()["schema_version"] == "open_agronomy_agent.local_pairing_session.v1"
    assert "agronomy_session" in client.cookies
    assert all("secure" not in cookie.lower() for cookie in response.headers.get_list("set-cookie"))
    csrf = response.json()["csrf_token"]
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/local-pair", json={"token": TOKEN}, headers=origin_header).status_code == 409

    assert client.post("/auth/logout", headers=origin_header).status_code == 403
    assert client.post("/auth/logout", headers={**origin_header, "X-Agronomy-User-Email": "spoof@local"}).status_code == 403
    assert client.post("/auth/logout", headers={**origin_header, "X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_desktop_rejects_spoofed_host_origin_and_missing_origin(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)), base_url=ORIGIN)

    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 403
    assert client.get("/api/health", headers={"Origin": "http://attacker.example"}).status_code == 403
    assert client.get("/api/health", headers={"X-Forwarded-Host": "attacker.example"}).status_code == 403
    assert client.post("/auth/local-pair", json={"token": TOKEN}).status_code == 403
    assert client.post("/auth/local-pair", json={"token": TOKEN}, headers={"Origin": "http://attacker.example"}).status_code == 403
    assert client.get("/api/health").json()["local_pairing"]["consumed"] is False
    assert client.get("/api/health").json()["local_pairing"]["transport_required"] == "http_loopback"
    assert client.get("/api/health").json()["local_pairing"]["launch_id"] == hashlib.sha256(TOKEN.encode()).hexdigest()


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


@pytest.mark.parametrize("origin", ["http://0.0.0.0:48721", "http://192.168.1.4:48721", "http://localhost:48721", "https://127.0.0.1:48721", "http://127.0.0.1", "http://127.0.0.1:0"])
def test_desktop_settings_reject_nonloopback_or_invalid_origin(tmp_path: Path, origin: str) -> None:
    with pytest.raises(ValueError, match="desktop-local origin"):
        build_settings(
            db_path=tmp_path / "invalid.sqlite3",
            artifact_root=tmp_path / "artifacts",
            allow_local_dev_auth=False,
            local_pairing_token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest(),
            oidc_session_secret=SECRET,
            desktop_local_origin=origin,
        )


def test_desktop_settings_require_pairing_and_session_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pairing token hash"):
        build_settings(
            db_path=tmp_path / "missing-pair.sqlite3",
            artifact_root=tmp_path / "artifacts",
            allow_local_dev_auth=False,
            oidc_session_secret=SECRET,
            desktop_local_origin=ORIGIN,
        )
    with pytest.raises(ValueError, match="local pairing requires"):
        build_settings(
            db_path=tmp_path / "missing-secret.sqlite3",
            artifact_root=tmp_path / "artifacts",
            allow_local_dev_auth=False,
            local_pairing_token_sha256=hashlib.sha256(TOKEN.encode()).hexdigest(),
            desktop_local_origin=ORIGIN,
        )


def test_desktop_launcher_requires_environment_secrets_and_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("desktop")
    parser = _build_parser()
    args = parser.parse_args(["--desktop-local", "--port", "48721", "--static-dir", str(static_dir)])
    with pytest.raises(SystemExit):
        _validate_desktop_launch(args, parser)
    monkeypatch.setenv("AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN", TOKEN)
    monkeypatch.setenv("AGRONOMY_AGENT_DESKTOP_SESSION_SECRET", SECRET)
    assert _validate_desktop_launch(args, parser) == (TOKEN, SECRET)
    assert "AGRONOMY_AGENT_DESKTOP_PAIRING_TOKEN" not in os.environ
    nonloopback = parser.parse_args(["--desktop-local", "--host", "0.0.0.0", "--static-dir", str(static_dir)])
    with pytest.raises(SystemExit):
        _validate_desktop_launch(nonloopback, parser)
