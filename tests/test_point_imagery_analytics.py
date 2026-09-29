"""Local source-grid fixtures for saved-point HLS sampling semantics."""

from __future__ import annotations

from contextlib import contextmanager
import io
import json
import math

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pyproj = pytest.importorskip("pyproj")
from rasterio.transform import from_origin
from PIL import Image

from agronomy_agent import imagery_analytics as analytics
from agronomy_agent.imagery_store import ImageryStore
from agronomy_agent.imagery_sampling import point_grid_and_weights


PROVIDER = "hls-s30-planetary-computer"
SCENE = "hls2-s30:HLS.S30.POINT.TEST"
ORIGIN_X = 500000
ORIGIN_Y = 4427810
SIDE = 6


def _point(x: float, y: float) -> dict:
    lon, lat = pyproj.Transformer.from_crs(
        "EPSG:32613", "EPSG:4326", always_xy=True).transform(x, y)
    return {"type": "Point", "coordinates": [lon, lat]}


def _polygon() -> dict:
    corners = [(ORIGIN_X + 30, ORIGIN_Y - 30), (ORIGIN_X + 60, ORIGIN_Y - 30),
               (ORIGIN_X + 60, ORIGIN_Y - 60), (ORIGIN_X + 30, ORIGIN_Y - 60),
               (ORIGIN_X + 30, ORIGIN_Y - 30)]
    return {"type": "Polygon", "coordinates": [[_point(x, y)["coordinates"] for x, y in corners]]}


def _fixture(tmp_path, monkeypatch, *, cloud=None, nodata=None, undefined=None,
             side=SIDE, nodata_metadata=True):
    keys = (*analytics.BAND_KEYS[PROVIDER][1], "Fmask")
    hrefs = {}
    for key in keys:
        data = np.full((side, side), 1000, dtype=np.int16)
        if key == "B04":
            data[:] = 2000
        elif key == "B8A":
            data[:] = 6000
        elif key == "Fmask":
            data[:] = 0
            if cloud is not None:
                data[cloud] = 2
        if nodata is not None and key == "B04":
            data[nodata] = -9999
        if undefined is not None and key in ("B04", "B8A"):
            data[undefined] = 0
        path = tmp_path / f"{key}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=side, height=side,
                           count=1, dtype="int16", crs="EPSG:32613",
                           transform=from_origin(ORIGIN_X, ORIGIN_Y, 30, 30),
                           nodata=-9999 if nodata_metadata else None) as dst:
            dst.write(data, 1)
        hrefs[key] = str(path)
    item = {"id": SCENE, "collection": "hls2-s30", "acquired_at": "2025-07-01T00:00:00Z",
            "availability_at": None, "scene_cloud_percent": 10,
            "assets": {key: {"id": f"{SCENE}:{key}",
                             "raster_bands": [{"scale": .0001, "offset": 0}]}
                       for key in keys}}
    seen = []
    def scene(geometry, *args):
        seen.append(geometry)
        return item
    monkeypatch.setattr(analytics, "_scene_item", scene)
    monkeypatch.setattr(analytics, "_signed_hrefs", lambda item: hrefs)
    @contextmanager
    def local_files(_):
        yield hrefs, {"bytes": 0, "requests": 0}
    monkeypatch.setattr(analytics, "_bounded_cog_proxy", local_files)
    return seen


def _analyze(point, cache, **kwargs):
    # Fixture cache lives under tmp_path and carries no runtime user data.
    # Lowering the test input reserve is needed on this low-disk checkout;
    # production defaults and admission implementation are unchanged.
    return analytics.analyze_scene(point, PROVIDER, SCENE, cache_root=cache,
                                   network_mode="online", min_free_bytes=0, **kwargs)


def test_containing_pixel_uses_native_grid_origin_and_edge_floor(tmp_path, monkeypatch):
    seen = _fixture(tmp_path, monkeypatch, cloud=(1, 1))
    point = _point(ORIGIN_X + 45, ORIGIN_Y - 15)
    receipt = _analyze(point, tmp_path / "cache")
    assert receipt["status"] == "available"
    assert seen == [point]
    assert receipt["process_version"] == analytics.POINT_PROCESS_VERSION
    assert receipt["sampling"]["mode"] == "point_pixel"
    assert receipt["sampling"]["support_kind"] == "native_pixel"
    assert receipt["sampling"]["original_geometry"] == point
    assert receipt["sampling"]["pixel_count"] == 1
    assert receipt["sampling"]["valid_pixel_count"] == 1
    assert receipt["sampling"]["positional_uncertainty_m"] is None
    assert receipt["sampling"]["point_role"] == "unspecified"
    assert receipt["request"] == {
        "provider_id": PROVIDER, "scene_id": SCENE, "start_date": None,
        "end_date": None, "buffer_m": 0, "context_pixels": None,
        "sampling_mode": "point_pixel", "sample_radius_m": None}
    assert receipt["qa"]["sample_area_m2"] == pytest.approx(900)
    assert "field_area_m2" not in receipt["qa"]
    assert receipt["zonal_stats"]["NDVI"]["mean"] == pytest.approx(.5)
    assert receipt["grid"]["transform"][2] == ORIGIN_X + 30
    assert receipt["grid"]["transform"][5] == ORIGIN_Y
    assert len(receipt["sampling"]["footprint"]["coordinates"][0]) > 5
    with np.load(tmp_path / "cache" / receipt["cache_files"]["npz"]) as chip:
        assert "sample_weights" in chip and "field_weights" not in chip
        assert chip["sample_weights"].shape == (1, 1)
        metadata = json.loads(str(chip["metadata_json"]))
        assert metadata["sampling"] == receipt["sampling"]
        assert metadata["request"] == receipt["request"]
    other_lon, other_lat = _point(ORIGIN_X + 55, ORIGIN_Y - 15)["coordinates"]
    assert receipt["chip_hash"] in ImageryStore(tmp_path / "cache").intersects(
        (other_lon, other_lat, other_lon, other_lat))

    # A point exactly on the eastern/southern edge selects the next cell.
    edge = _point(ORIGIN_X + 60, ORIGIN_Y - 30)
    edge_receipt = _analyze(edge, tmp_path / "edge-cache")
    assert edge_receipt["grid"]["transform"][2] == ORIGIN_X + 60
    assert edge_receipt["grid"]["transform"][5] == ORIGIN_Y - 30


def test_cloud_nodata_and_undefined_index_are_distinct(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch, cloud=(0, 0), nodata=(0, 1), undefined=(0, 2))
    for col, reason in ((0, "cloud"), (1, "nodata"), (2, "undefined")):
        point = _point(ORIGIN_X + col * 30 + 15, ORIGIN_Y - 15)
        result = _analyze(point, tmp_path / f"cache-{col}")
        if reason == "undefined":
            assert result["status"] == "available"
            assert result["sampling"]["valid_pixel_count"] == 1
            assert result["zonal_stats"]["NDVI"]["mean"] is None
            assert result["zonal_stats"]["NDVI"]["area_m2"] == 0
        else:
            assert result["status"] == "empty_valid_area"
            assert result["sampling"]["valid_pixel_count"] == 0
            assert result["qa"]["valid_area_m2"] == 0
            if reason == "cloud":
                assert result["qa"]["excluded_area_m2_by_reason"]["cloud"] == 900
            else:
                assert result["qa"]["nodata_area_m2"] == 900
        with np.load(tmp_path / f"cache-{col}" / result["cache_files"]["npz"]) as chip:
            if reason == "undefined":
                assert math.isnan(float(chip["ndvi"][0, 0]))
                png = Image.open(io.BytesIO((tmp_path / f"cache-{col}" / result["cache_files"]["png"]).read_bytes()))
                assert png.getpixel((0, 0))[3] == 0
            else:
                assert not bool(chip["valid_mask"][0, 0])


def test_buffer_fractional_weights_footprint_and_outside_source(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    center = _point(ORIGIN_X + 75, ORIGIN_Y - 75)
    result = _analyze(center, tmp_path / "circle", sampling_mode="point_buffer", sample_radius_m=25)
    assert result["status"] == "available"
    assert result["sampling"]["pixel_count"] == 9
    assert result["sampling"]["valid_pixel_count"] == 9
    assert result["sampling"]["sample_radius_m"] == 25
    assert result["qa"]["sample_area_m2"] == pytest.approx(math.pi * 25**2, rel=2e-4)
    with np.load(tmp_path / "circle" / result["cache_files"]["npz"]) as chip:
        weights = chip["sample_weights"]
        assert np.count_nonzero(weights > 0) == 9
        assert np.count_nonzero((weights > 0) & (weights < 1)) >= 8
        assert weights.sum() * 900 == pytest.approx(result["qa"]["sample_area_m2"])
    # The support can extend outside a tile. Those cells carry nodata, not zeros.
    edge = _point(ORIGIN_X + 15, ORIGIN_Y - 15)
    outside = _analyze(edge, tmp_path / "outside", sampling_mode="point_buffer", sample_radius_m=45)
    assert outside["status"] == "available"
    assert outside["qa"]["nodata_area_m2"] > 0
    assert outside["qa"]["valid_area_m2"] < outside["qa"]["sample_area_m2"]


def test_pixel_beyond_source_is_nodata_not_valid_zero(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    point = _point(ORIGIN_X + SIDE * 30 + 15, ORIGIN_Y - 15)
    result = _analyze(point, tmp_path / "outside-pixel")
    assert result["status"] == "empty_valid_area"
    assert result["sampling"]["pixel_count"] == 1
    assert result["sampling"]["valid_pixel_count"] == 0
    assert result["qa"]["sample_area_m2"] == 900
    assert result["qa"]["nodata_area_m2"] == 900
    assert result["qa"]["valid_area_m2"] == 0
    assert result["zonal_stats"]["NDVI"]["mean"] is None


def test_missing_nodata_metadata_cannot_invent_valid_pixels_beyond_tile(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch, side=2, nodata_metadata=False)
    # The point lies 90 m east of a 2x2 tile: VRT may return zero reflectance
    # and Fmask=0 without any nodata metadata. Source extent decides validity.
    outside = _point(ORIGIN_X + 90, ORIGIN_Y - 15)
    pixel = _analyze(outside, tmp_path / "missing-nodata-pixel")
    assert pixel["status"] == "empty_valid_area"
    assert pixel["sampling"]["valid_pixel_count"] == 0
    assert pixel["qa"]["valid_area_m2"] == 0
    assert pixel["qa"]["nodata_area_m2"] == 900
    assert pixel["zonal_stats"]["NDVI"]["mean"] is None
    preview = Image.open(io.BytesIO((tmp_path / "missing-nodata-pixel" /
                                      pixel["cache_files"]["png"]).read_bytes()))
    assert preview.getpixel((0, 0))[3] == 0

    near_edge = _point(ORIGIN_X + 45, ORIGIN_Y - 15)
    buffer = _analyze(near_edge, tmp_path / "missing-nodata-buffer",
                      sampling_mode="point_buffer", sample_radius_m=45)
    assert buffer["status"] == "available"
    assert 0 < buffer["sampling"]["valid_pixel_count"] < buffer["sampling"]["pixel_count"]
    assert 0 < buffer["qa"]["valid_area_m2"] < buffer["qa"]["sample_area_m2"]
    assert buffer["qa"]["nodata_area_m2"] == pytest.approx(
        buffer["qa"]["sample_area_m2"] - buffer["qa"]["valid_area_m2"], abs=1e-3)
    assert buffer["zonal_stats"]["NDVI"]["mean"] == pytest.approx(.5)
    with np.load(tmp_path / "missing-nodata-buffer" / buffer["cache_files"]["npz"]) as chip:
        assert np.count_nonzero(chip["valid_mask"] & chip["sample_mask"]) > 0
        assert np.count_nonzero(~chip["valid_mask"] & chip["sample_mask"]) > 0


def test_zero_weight_cloud_corner_keeps_exact_all_clear_fraction(tmp_path, monkeypatch):
    point = _point(ORIGIN_X + 612.032118333, ORIGIN_Y - 619.100343629)
    source_grid = (rasterio.crs.CRS.from_epsg(32613),
                   from_origin(ORIGIN_X, ORIGIN_Y, 30, 30), 50, 50)
    grid, weights, _, _ = point_grid_and_weights(
        point, "point_buffer", 204, source_grid, analytics._dependencies())
    assert weights[0, 0] == 0
    native_col = round((grid[1].c - ORIGIN_X) / 30)
    native_row = round((ORIGIN_Y - grid[1].f) / 30)
    _fixture(tmp_path, monkeypatch, side=50, cloud=(native_row, native_col))
    receipt = _analyze(point, tmp_path / "float64-cache",
                       sampling_mode="point_buffer", sample_radius_m=204)
    assert receipt["status"] == "available"
    assert receipt["sampling"]["valid_pixel_count"] == receipt["sampling"]["pixel_count"]
    assert receipt["qa"]["valid_area_fraction"] == 1
    assert receipt["qa"]["valid_area_m2"] == receipt["qa"]["sample_area_m2"]
    assert receipt["qa"]["excluded_area_m2_by_reason"]["cloud"] == 0
    ndmi = receipt["zonal_stats"]["NDMI"]
    assert ndmi["min"] - 1e-6 <= ndmi["mean"] <= ndmi["max"] + 1e-6
    with np.load(tmp_path / "float64-cache" / receipt["cache_files"]["npz"]) as chip:
        assert chip["sample_weights"].dtype == np.float32
        assert json.loads(str(chip["metadata_json"]))["qa_accumulator_dtype"] == "float64"


def test_request_validation_and_identity_separation(tmp_path):
    point = _point(ORIGIN_X + 45, ORIGIN_Y - 15)
    polygon = {"type": "Polygon", "coordinates": [[[point["coordinates"][0], point["coordinates"][1]],
                [point["coordinates"][0] + .001, point["coordinates"][1]],
                [point["coordinates"][0], point["coordinates"][1] + .001],
                [point["coordinates"][0], point["coordinates"][1]]]]}
    def identity(geometry, mode=None, radius=None):
        return analytics._request_identity(geometry, PROVIDER, SCENE, None, None, 0, None,
                                           sampling_mode=mode, sample_radius_m=radius)
    pixel = identity(point)
    assert pixel[2] == analytics._hash(point)
    assert pixel[3] == identity(point, "point_pixel")[3]
    assert pixel[3] != identity(point, "point_buffer", 60)[3]
    assert identity(point, "point_buffer", 60)[3] != identity(point, "point_buffer", 61)[3]
    assert pixel[3] != identity(_point(ORIGIN_X + 46, ORIGIN_Y - 15))[3]
    assert pixel[3] != identity(polygon)[3]
    for geometry, mode, radius in ((point, "field_polygon", None),
                                   (point, "", None),
                                   (polygon, "point_pixel", None),
                                   (point, "point_pixel", 60),
                                   (polygon, "field_polygon", 60),
                                   (point, "point_buffer", None),
                                   (point, "point_buffer", 14),
                                   (point, "point_buffer", 1501),
                                   (point, "point_buffer", True),
                                   (point, "point_buffer", 60.0)):
        with pytest.raises(ValueError):
            identity(geometry, mode, radius)
    for kwargs in ({"buffer_m": 1}, {"context_pixels": 224}):
        with pytest.raises(ValueError):
            analytics.analyze_scene(point, PROVIDER, SCENE, cache_root=tmp_path / "cache", **kwargs)


def test_offline_verified_point_cache_and_mode_miss(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    point = _point(ORIGIN_X + 45, ORIGIN_Y - 15)
    cache = tmp_path / "cache"
    first = _analyze(point, cache)
    assert first["status"] == "available"
    monkeypatch.setattr(analytics, "_scene_item", lambda *args: pytest.fail("offline provider access"))
    cached = analytics.analyze_scene(point, PROVIDER, SCENE, cache_root=cache,
                                     network_mode="offline")
    assert cached["cache_hit"] is True
    assert cached["chip_hash"] == first["chip_hash"]
    miss = analytics.analyze_scene(point, PROVIDER, SCENE, cache_root=cache,
                                   network_mode="offline", sampling_mode="point_buffer",
                                   sample_radius_m=60)
    assert miss["status"] == "blocked_offline"


def test_date_discovered_point_keeps_nullable_requested_scene(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    point = _point(ORIGIN_X + 45, ORIGIN_Y - 15)
    cache = tmp_path / "date-cache"
    result = analytics.analyze_scene(
        point, PROVIDER, None, cache_root=cache, network_mode="online",
        start_date="2025-07-01", end_date="2025-07-02", min_free_bytes=0)
    assert result["status"] == "available"
    assert result["request"]["scene_id"] is None
    assert result["scene_id"] == SCENE
    assert result["request"]["start_date"] == "2025-07-01"
    expected = analytics._request_identity(
        point, PROVIDER, None, "2025-07-01", "2025-07-02", 0, None)[3]
    assert result["request_hash"] == expected
    cached = analytics.analyze_scene(
        point, PROVIDER, None, cache_root=cache, network_mode="offline",
        start_date="2025-07-01", end_date="2025-07-02")
    assert cached["cache_hit"] is True
    assert cached["request"] == result["request"]


def test_polygon_version_changes_while_receipt_and_npz_shape_remain_compatible(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    polygon = _polygon()
    expected_request = analytics._hash({
        "version": analytics.PROCESS_VERSION, "preview_version": analytics.PREVIEW_VERSION,
        "geometry_hash": analytics._hash(polygon), "provider": PROVIDER,
        "scene_id": SCENE, "start_date": None, "end_date": None,
        "buffer_m": 0, "context_pixels": None})
    receipt = _analyze(polygon, tmp_path / "polygon-cache")
    assert receipt["status"] == "available"
    assert receipt["request_hash"] == expected_request
    assert receipt["process_version"] == analytics.PROCESS_VERSION
    assert receipt["process_hash"] == analytics._hash({
        "version": analytics.PROCESS_VERSION,
        "band_keys": analytics.BAND_KEYS[PROVIDER][1], "scale": analytics.SCALE,
        "excluded_bits": analytics.EXCLUDE_BITS, "aerosol_high": 3,
        "resampling_method": "nearest", "preview_version": analytics.PREVIEW_VERSION})
    assert "sampling" not in receipt
    assert "field_area_m2" in receipt["qa"] and "sample_area_m2" not in receipt["qa"]
    with np.load(tmp_path / "polygon-cache" / receipt["cache_files"]["npz"]) as chip:
        assert "field_weights" in chip and "sample_weights" not in chip
        assert list(chip.files) == ["bands", "valid_mask", "field_mask", "field_weights",
                                    "fmask", "ndvi", "metadata_json"]


@pytest.mark.parametrize("radius", [15, 45, 204])
def test_shared_weights_preserve_point_v3_storage_bytes(radius):
    from shapely.geometry import box
    point = _point(ORIGIN_X + 612.032118333, ORIGIN_Y - 619.100343629)
    source_grid = (rasterio.crs.CRS.from_epsg(32613),
                   from_origin(ORIGIN_X, ORIGIN_Y, 30, 30), 50, 50)
    grid, weights, _, _ = point_grid_and_weights(
        point, "point_buffer", radius, source_grid, analytics._dependencies())
    _, transform, width, height, _, support = grid
    # Retained v3 scalar Shapely calculation is an oracle for the published
    # point artifact contract, independent of the shared vectorized path.
    previous = np.zeros((height, width), dtype=np.float32)
    for row in range(height):
        for col in range(width):
            left, top = transform.c + col * 30, transform.f - row * 30
            previous[row, col] = support.intersection(box(left, top - 30, left + 30, top)).area / 900
    assert weights.tobytes() == previous.tobytes()
