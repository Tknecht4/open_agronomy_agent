"""Public crop-cover contracts using synthetic raw categorical rasters."""
from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from shapely.geometry import MultiPolygon, Polygon, box, mapping

from agronomy_agent import local_tools
from agronomy_agent.geospatial import crop_cover
from scripts.smoke_public_adapter_regional_matrix import _crop_cover_export_fixture


@pytest.mark.parametrize(("codes", "status", "classification", "dominant"), [
    ([1] * 9 + [5], "available", "dominant", 1),
    ([1] * 8 + [5] * 2, "available", "mixed", None),
    ([1] * 8 + [0] * 2, "partial_available", "insufficient_coverage", None),
    ([1] * 6 + [5] * 3 + [81], "partial_available", "mixed", None),
    ([1] * 9 + [0], "partial_available", "dominant", 1),
    ([0, 81, 255, 7, 0] * 2, "no_data", "no_data", None),
])
def test_dominance_uses_total_field_area(monkeypatch, codes, status, classification, dominant):
    monkeypatch.setattr(crop_cover, "project_geometry", lambda geometry, crs: geometry)

    def fake_urlopen(request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)
        assert query["interpolation"] == ["RSP_NearestNeighbor"]
        assert query["renderingRule"] == ['{"rasterFunction":"None"}']
        assert json.loads(query["mosaicRule"][0])["lockRasterIds"] == [40]
        return io.BytesIO(_crop_cover_export_fixture(query, 0, codes))

    monkeypatch.setattr(crop_cover.urllib.request, "urlopen", fake_urlopen)
    result = crop_cover.query_crop_cover(
        box(20, 40, 120, 50), service=crop_cover.CDL_IMAGE_SERVER, crs=6933, year=2025,
        resolution=10, labels={1: "Corn", 5: "Soybeans"}, no_class_codes=frozenset({0, 81}),
        raster={"object_id": 40}, timeout=5,
    )
    assert result["status"] == status and result["classification_status"] == classification
    assert (result["dominant_class"] or {}).get("code") == dominant
    assert result["boundary_area_m2"] == 1000
    assert result["classified_fraction"] == (codes.count(1) + codes.count(5)) / 10
    assert sum(entry["area_m2"] for entry in result["classes"]) + result["unclassified_area_m2"] == pytest.approx(1000)


def test_multipart_hole_and_fractional_pixels(monkeypatch):
    monkeypatch.setattr(crop_cover, "project_geometry", lambda geometry, crs: geometry)
    geometry = MultiPolygon([
        Polygon(box(0, 0, 20, 20).exterior.coords, [box(2, 2, 8, 8).exterior.coords]),
        Polygon([(20, 10), (30, 10), (30, 20)]),
    ])
    values = [1, 5, 1, 1, 5, 5]

    def provider(request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)
        return io.BytesIO(_crop_cover_export_fixture(query, 0, values))

    monkeypatch.setattr(crop_cover.urllib.request, "urlopen", provider)
    result = crop_cover.query_crop_cover(
        geometry, service=crop_cover.CDL_IMAGE_SERVER, crs=6933, year=2025,
        resolution=10, labels={1: "Corn", 5: "Soybeans"}, no_class_codes=frozenset({0, 81}),
        raster={"object_id": 40}, timeout=5,
    )
    assert result["boundary_area_m2"] == 414
    assert {row["code"]: row["area_m2"] for row in result["classes"]} == pytest.approx({1: 214, 5: 200})
    assert result["classification_status"] == "mixed"


def test_sparse_geotiff_tiles_and_wrong_grid(monkeypatch, tmp_path):
    geom = mapping(box(-73.041, 45.619, -73.039, 45.621))
    requested = []

    def provider(request, timeout):
        split = urlsplit(request.full_url)
        requested.append(split.path)
        query = parse_qs(split.query)
        assert json.loads(query["mosaicRule"][0]) == {"where": "Category=1"}
        assert query["pixelType"] == ["U8"]
        if "/2010/" in split.path:
            return io.BytesIO(_crop_cover_export_fixture(query, 147, epsg=3857))
        return io.BytesIO(_crop_cover_export_fixture(query, 0, sparse=True))

    monkeypatch.setattr(crop_cover.urllib.request, "urlopen", provider)
    old = local_tools.aafc_annual_crop_inventory(geometry=geom, year=2009, cache_dir=str(tmp_path))
    year = old["coverage_by_year"]["2009"]
    assert year["resolution_m"] == 56 and year["status"] == "no_data"
    assert year["classified_fraction"] == 0 and year["unclassified_codes"] == [0]
    assert local_tools.aafc_annual_crop_inventory(geometry=geom, year=2009, cache_dir=str(tmp_path))["cache_hit"]
    assert len(requested) == 1
    wrong = local_tools.aafc_annual_crop_inventory(geometry=geom, year=2010, cache_dir=str(tmp_path))
    assert wrong["status"] == "unavailable"
    assert "does not match" in wrong["coverage_by_year"]["2010"]["message"]


def test_cdl_uses_published_year_and_preserves_partial_provider_failure(monkeypatch, tmp_path):
    calls = []

    def provider(request, timeout):
        split = urlsplit(request.full_url)
        query = parse_qs(split.query)
        if split.path.endswith("/query"):
            assert query["where"] == ["Category=1 AND Year>=2008"]
            rows = [{"attributes": {"OBJECTID": 38, "Year": 2023, "Name": "2023_30m_cdls"}},
                    {"attributes": {"OBJECTID": 40, "Year": 2025, "Name": "2025_10m_cdls"}}]
            return io.BytesIO(json.dumps({"features": rows}).encode())
        rule = json.loads(query["mosaicRule"][0])
        calls.append(rule["lockRasterIds"])
        if rule["where"] == "Year=2023":
            raise OSError("synthetic provider failure")
        assert rule["where"] == "Year=2025"
        return io.BytesIO(_crop_cover_export_fixture(query, 26))

    monkeypatch.setattr(crop_cover.urllib.request, "urlopen", provider)
    result = local_tools.cropland_data_layer_geometry(mapping(box(-96.651, 46.849, -96.649, 46.851)),
        years=(2023, 2024, 2025), cache_dir=str(tmp_path))
    by_year = result["coverage_by_year"]
    assert result["status"] == "partial_available"
    assert calls == [[40], [38]]
    assert by_year["2023"]["status"] == "unavailable"
    assert by_year["2024"]["status"] == "year_unavailable"
    assert by_year["2025"]["dominant_class"]["label"] == "Double Crop Winter Wheat/Soybeans"

    point = local_tools.cropland_data_layer_point(46.85, -96.65, cache_dir=str(tmp_path))
    assert point["year"] == 2025 and point["cdl_code"] == 26
    assert "classified_fraction" not in point["coverage_by_year"]["2025"]


@pytest.mark.parametrize(("code", "label", "fraction", "conflict"), [
    (5, "Soybeans", 0.90, False),
    (21, "Barley", 0.90, True),
    (21, "Barley", 0.80, False),
    (26, "Double Crop Winter Wheat/Soybeans", 0.90, False),
    (37, "Other Hay/Non Alfalfa", 0.90, False),
])
def test_crop_conflicts_require_a_disagreeing_single_class_and_confirmed_crop_set(code, label, fraction, conflict):
    from agronomy_agent.server.services.chat_service import _detect_evidence_conflicts, _public_tool_record

    name = "cropland_data_layer_geometry"
    record = _public_tool_record(name, "", {"tool": name, "coverage_by_year": {"2025": {
        "classification_status": "dominant",
        "dominant_class": {"code": code, "label": label, "field_fraction": fraction},
    }}}, status="available")
    context = {"crop": "Corn", "crop_year": 2025, "field_season_lineage": {
        "status": "saved", "season": 2025, "crops": [{"crop": "Corn"}, {"crop": "Soybeans"}],
    }}
    conflicts = _detect_evidence_conflicts(context, [record])
    assert bool(conflicts) == conflict
    assert _detect_evidence_conflicts({**context, "retained_public_context": [record]}, []) == conflicts
    assert _detect_evidence_conflicts({**context, "retained_public_context": [record]}, [record]) == conflicts
    if conflicts:
        assert conflicts[0]["declared_crop"] == "Corn, Soybeans"
        assert conflicts[0]["sources"][0]["source_id"] == "field_season_lineage.crops"


def test_long_narrow_boundary_uses_adjacent_windows(monkeypatch):
    monkeypatch.setattr(crop_cover, "project_geometry", lambda geometry, crs: geometry)

    def provider(request, timeout):
        query = parse_qs(urlsplit(request.full_url).query)
        return io.BytesIO(_crop_cover_export_fixture(query, 1))

    monkeypatch.setattr(crop_cover.urllib.request, "urlopen", provider)
    result = crop_cover.query_crop_cover(
        box(3, 5, 11_007, 15), service=crop_cover.CDL_IMAGE_SERVER, crs=6933, year=2025,
        resolution=10, labels={1: "Corn"}, no_class_codes=frozenset({0}),
        raster={"object_id": 40}, timeout=5,
    )
    assert result["classified_fraction"] == 1
    assert len(result["exports"]) == 2
    assert result["exports"][0]["bbox"][2] == result["exports"][1]["bbox"][0]
    with pytest.raises(crop_cover.WindowLimitError):
        crop_cover._windows(box(0, 0, 11_000, 11_000), 10)
    assert len(crop_cover._windows(box(0, 0, 11_000, 11_000), 30)) == 1
