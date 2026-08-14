from __future__ import annotations

from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


def test_capability_registry_api_exposes_canonical_http_view(tmp_path) -> None:  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "capabilities.sqlite3",
        artifact_root=tmp_path / "artifacts",
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/tools/capabilities", params={"surface": "http"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "open_agronomy_agent.capability_registry.v1"
    assert payload["capability_count"] == 47
    assert {item["capability_id"] for item in payload["capabilities"]} >= {
        "agronomic_calculator",
        "nasa_power_daily",
    }


def test_capability_registry_api_rejects_unknown_surface(tmp_path) -> None:  # noqa: ANN001
    settings = build_settings(
        db_path=tmp_path / "capabilities.sqlite3",
        artifact_root=tmp_path / "artifacts",
    )
    client = TestClient(create_app(settings))

    response = client.get("/api/tools/capabilities", params={"surface": "mystery"})

    assert response.status_code == 400
