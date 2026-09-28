"""Mounting a field starts simultaneous authorized reads on one SQLite store."""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi.testclient import TestClient

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


def test_simultaneous_field_mount_and_first_workspace_keep_authority(tmp_path):
    settings = build_settings(db_path=tmp_path / "concurrent.sqlite3",
                              artifact_root=tmp_path / "artifacts", network_mode="offline")
    app = create_app(settings)
    owner = {"X-Agronomy-User-Email": "mounted-owner@example.test"}
    newcomer = {"X-Agronomy-User-Email": "newcomer@example.test"}
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/demo/fields", headers=owner, json={
            "name": "Concurrent study", "field": {}, "geometry": {"kind": "none"}})
        assert response.status_code == 201, response.text
        field_id = response.json()["field"]["field_context_id"]
        base = f"/api/demo/fields/{field_id}"
        upload = client.post(base + "/data/preview", headers=owner, json={
            "filename": "measurements.csv", "base64_content": base64.b64encode(b"sample,yield\na,2\nb,4\n").decode()})
        assert upload.status_code == 201, upload.text
        import_id = upload.json()["import_id"]
        committed = client.post(base + f"/data/{import_id}/commit", headers=owner, json={"mapping": {
            "filters": {}, "record_key": ["sample"], "source": {"title": "Synthetic study"},
            "columns": [{"column": "yield", "label": "Yield", "unit": "kg/ha",
                         "role": "measurement", "aggregation": "mean", "evidence_role": "observation"}]}})
        assert committed.status_code == 200, committed.text
        paths = [base + "/data", base + "/history", base + "/imagery/analytics", base + "/events/sync"]

        def batch(headers, expected):
            barrier = threading.Barrier(8)

            def worker(index):
                barrier.wait(timeout=10)
                for turn in range(6):
                    path = paths[(index + turn) % len(paths)]
                    result = client.get(path, headers=headers)
                    assert result.status_code == expected, (path, result.status_code, result.text[:200])
                    if expected == 200 and path.endswith("/data"):
                        assert [item["import_id"] for item in result.json()["imports"]] == [import_id]
                return True

            with ThreadPoolExecutor(max_workers=8) as pool:
                assert all(pool.map(worker, range(8)))

        batch(owner, 200)
        # First concurrent use of this actor must create one personal workspace
        # and consistently refuse access to the existing owner's field.
        batch(newcomer, 403)
        store = app.state.trace_store
        user = store.upsert_phase4_user(email=newcomer["X-Agronomy-User-Email"])
        assert len(store.list_phase4_workspaces_for_user(user["id"])) == 1
        assert len(store.list_phase4_organizations_for_user(user["id"])) == 1
        assert len(store.list_phase4_field_events(field_id)) == 0
