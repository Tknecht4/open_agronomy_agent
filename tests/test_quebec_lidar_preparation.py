"""Checkout setup and numerical contracts for the MAPAQ preparation lane."""
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from agronomy_agent import offline_context_packs as packs

ROOT = Path(__file__).resolve().parents[1]


def test_checkout_supplies_the_pinned_source_and_operator_command():
    manifest = json.loads(packs.DEFAULT_QUEBEC_CONTEXT_MANIFEST.read_text())
    source, resource = packs._quebec_lidar_source(manifest)
    assert source["publisher"] and source["catalogue_url"]
    assert resource["url"] == packs.QUEBEC_LIDAR_INDEX_DOWNLOAD_URL
    assert len(resource["sha256"]) == 64 and resource["bytes"] > 0
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/manage_quebec_lidar_field_pack.py"), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "fetch-index" in result.stdout


@pytest.fixture
def source_fixture(tmp_path):
    index = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}, "features": [
        {"type": "Feature", "properties": {"FEUILLET": "31H10NO", "RELPAG_URL": packs.QUEBEC_LIDAR_TILE_URL_PREFIX + "31H10NO/ReliefParcellesAgricoles_31H10NO.zip"},
         "geometry": {"type": "Polygon", "coordinates": [[[-74, 45], [-72, 45], [-72, 47], [-74, 47], [-74, 45]]]}}
    ]}
    index_bytes = json.dumps(index).encode()
    manifest = {"licence": {"identifier": "CC-BY-4.0", "permits_modification": True, "permits_commercial_use": True, "permits_redistribution": True}, "candidates": [
        {"source_id": packs.QUEBEC_LIDAR_SOURCE_ID, "title": "Synthetic MAPAQ fixture", "publisher": "Synthetic publisher", "package_id": "fixture", "catalogue_url": "https://example.invalid", "metadata_api_url": "https://example.invalid",
         "does_not_establish": ["current field conditions"], "selected_resources": [
             {"resource_id": packs.QUEBEC_LIDAR_INDEX_RESOURCE_ID, "url": packs.QUEBEC_LIDAR_INDEX_DOWNLOAD_URL, "bytes": len(index_bytes), "sha256": hashlib.sha256(index_bytes).hexdigest()}
         ]}
    ]}
    source_path = tmp_path / "source.json"
    source_path.write_text(json.dumps(manifest))
    index_path = tmp_path / "index.geojson"
    index_path.write_bytes(index_bytes)
    return source_path, index_path, index_bytes


def test_index_fetch_is_explicit_and_preserves_an_existing_index_on_drift(source_fixture, monkeypatch):
    source_path, index_path, expected = source_fixture
    monkeypatch.setattr(packs, "urlopen", lambda *args, **kwargs: pytest.fail("unexpected network"))
    with pytest.raises(ValueError, match="allow_network"):
        packs.download_quebec_lidar_index(source_manifest_path=source_path, output_path=index_path, allow_network=False)
    changed = io.BytesIO(expected.replace(b"Synthetic", b"Different") + b" ")
    changed.headers = {"Content-Type": "application/json"}
    monkeypatch.setattr(packs, "urlopen", lambda *args, **kwargs: changed)
    with pytest.raises(ValueError):
        packs.download_quebec_lidar_index(source_manifest_path=source_path, output_path=index_path, allow_network=True)
    assert index_path.read_bytes() == expected
    assert not index_path.with_suffix(".geojson.partial").exists()


def test_plan_cli_uses_verified_local_bytes_without_network(source_fixture, tmp_path):
    source_path, index_path, _ = source_fixture
    field = {"type": "Polygon", "coordinates": [[[-73, 46], [-72.999, 46], [-72.999, 46.001], [-73, 46.001], [-73, 46]]]}
    geometry = tmp_path / "field.geojson"
    geometry.write_text(json.dumps(field))
    output = tmp_path / "plan.json"
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/manage_quebec_lidar_field_pack.py"), "plan",
        "--source-manifest", str(source_path), "--index", str(index_path),
        "--geometry", str(geometry), "--output", str(output),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text())
    assert plan["status"] == "ready_to_download"
    assert len(plan["resources"]) == 1
    assert plan["privacy"]["exact_field_geometry_sent_to_source"] is False


def test_saved_field_api_uses_the_local_index_and_enforces_workspace_access(source_fixture, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from agronomy_agent.server.app import create_app
    from agronomy_agent.server.settings import build_settings

    source_path, index_path, _ = source_fixture
    original = packs.plan_quebec_lidar_field_pack

    def local_plan(**kwargs):
        return original(**kwargs, source_manifest_path=source_path, index_path=index_path)

    monkeypatch.setattr(packs, "plan_quebec_lidar_field_pack", local_plan)
    monkeypatch.setattr(packs, "urlopen", lambda *args, **kwargs: pytest.fail("availability check contacted provider"))
    settings = build_settings(db_path=tmp_path / "db.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline")
    owner = {"X-Agronomy-User-Email": "terrain-owner@example.test"}
    with TestClient(create_app(settings)) as client:
        created = client.post("/api/demo/fields", headers=owner, json={
            "name": "Synthetic Quebec terrain", "field": {"jurisdiction": "Quebec"},
            "geometry": {"kind": "polygon", "points": [
                {"lat": 46, "lon": -73}, {"lat": 46, "lon": -72.999},
                {"lat": 46.001, "lon": -72.999}, {"lat": 46.001, "lon": -73},
            ]},
        })
        assert created.status_code == 201
        field_id = created.json()["field"]["field_context_id"]
        url = f"/api/demo/fields/{field_id}/context-packs/quebec-lidar/plan"
        response = client.post(url, headers=owner, json={})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["receipt"]["matched_tile_count"] == 1
        assert result["preparation"]["planning_network_request_attempted"] is False
        assert (ROOT / result["preparation"]["operator_workflow"]).is_file()
        assert client.post(url, headers={"X-Agronomy-User-Email": "terrain-outsider@example.test"}, json={}).status_code == 403
        index_path.unlink()
        unavailable = client.post(url, headers=owner, json={})
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["status"] == "source_index_not_prepared"


def test_frozen_derivation_clips_metric_features_and_rejects_a_changed_field(source_fixture, tmp_path):
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import LineString, box, mapping

    source_path, index_path, _ = source_fixture
    origin_x, origin_y = 655000, 5100000
    field = geopandas.GeoSeries([box(origin_x, origin_y, origin_x + 100, origin_y + 100)], crs="EPSG:32618").to_crs("EPSG:4326").iloc[0]
    geometry = json.loads(json.dumps(mapping(field)))
    plan = packs.plan_quebec_lidar_field_pack(field_geometry=geometry, source_manifest_path=source_path, index_path=index_path)
    tile = "31H10NO"
    members = tmp_path / "members"
    members.mkdir()
    geopandas.GeoDataFrame({"geometry": [box(origin_x + 20, origin_y + 20, origin_x + 80, origin_y + 80)]}, crs="EPSG:32618").to_file(members / f"CuvPAg_{tile}.shp")
    geopandas.GeoDataFrame({"geometry": [LineString([(origin_x - 20, origin_y + 50), (origin_x + 120, origin_y + 50)])]}, crs="EPSG:32618").to_file(members / f"TEPAg_{tile}.shp")
    (members / f"PentesParcellesAgricoles_{tile}.tif").write_bytes(b"unprocessed synthetic raster")
    downloads = tmp_path / "tiles"
    downloads.mkdir()
    with zipfile.ZipFile(downloads / f"ReliefParcellesAgricoles_{tile}.zip", "w") as archive:
        for path in members.iterdir():
            archive.write(path, path.name)
    frozen = packs.freeze_downloaded_quebec_lidar_pack(plan=plan, download_dir=downloads, output_manifest=tmp_path / "frozen.json")
    result = packs.derive_quebec_lidar_field_context(plan=plan, frozen=frozen, field_geometry=geometry, download_dir=downloads)
    assert result["totals"]["depression_clipped_area_m2"] == pytest.approx(3600, abs=.01)
    assert result["totals"]["flow_path_clipped_length_m"] == pytest.approx(100, abs=.01)
    assert result["totals"]["slope_raster_processed"] is False
    assert result["decision_boundary"]["recommendation_grade"] is False
    changed = {"type": "Polygon", "coordinates": [[[-73, 46], [-72.999, 46], [-72.999, 46.001], [-73, 46.001], [-73, 46]]]}
    with pytest.raises(ValueError, match="binding"):
        packs.derive_quebec_lidar_field_context(plan=plan, frozen=frozen, field_geometry=changed, download_dir=downloads)
