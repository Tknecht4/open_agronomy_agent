"""Synthetic COG fixture tests for projection, masks, scale and cache identity."""

from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import threading

import httpx

import numpy as np
import pytest
from PIL import Image

rasterio = pytest.importorskip("rasterio")
pyproj = pytest.importorskip("pyproj")

from rasterio.transform import from_origin
from agronomy_agent import imagery_analytics as analytics
from agronomy_agent.imagery_store import ImageryStore

PROVIDER = "hls-s30-planetary-computer"
SCENE = "hls2-s30:HLS.S30.TEST"


def _geometry():
    inverse = pyproj.Transformer.from_crs("EPSG:32613", "EPSG:4326", always_xy=True)
    points = [(500030, 4427720), (500090, 4427720), (500090, 4427780),
              (500030, 4427780), (500030, 4427720)]
    return {"type": "Polygon", "coordinates": [[list(inverse.transform(*p)) for p in points]]}


def _fixture(tmp_path, monkeypatch, *, all_cloud=False, source_crs="EPSG:32613",
             source_transform=None, side=4, nodata_metadata=True):
    # Numerical raster fixtures do not depend on unrelated host disk pressure.
    # Storage admission/refusal is asserted separately in test_imagery_budget.
    from types import SimpleNamespace
    from agronomy_agent import imagery_budget
    monkeypatch.setattr(imagery_budget.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    keys = (*analytics.BAND_KEYS[PROVIDER][1], "Fmask")
    urls = {}
    source_transform = source_transform or from_origin(500000, 4427810, 30, 30)
    for key in keys:
        data = np.full((side, side), 1000, dtype=np.int16)
        if key == "B04":
            data[:] = 2000
        if key == "B8A":
            data[:] = 6000
        if key == "Fmask":
            data[:] = 2 if all_cloud else 0
            if not all_cloud:
                data[1, 1] = 2
        path = tmp_path / f"{key}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=side, height=side, count=1,
                           dtype="int16", crs=source_crs, transform=source_transform,
                           nodata=-9999 if nodata_metadata else None) as dst:
            dst.write(data, 1)
        urls[key] = str(path)
    item = {"id": SCENE, "collection": "hls2-s30", "acquired_at": "2025-07-01T00:00:00Z",
            "availability_at": None, "scene_cloud_percent": 10,
            "assets": {k: {"id": f"{SCENE}:{k}", "href": f"https://hls2euwest.blob.core.windows.net/hls2/{k}.tif",
                            "raster_bands": [{"scale": .0001, "offset": 0}]} for k in keys}}
    monkeypatch.setattr(analytics, "_scene_item", lambda *args: item)
    monkeypatch.setattr(analytics, "_signed_hrefs", lambda item: urls)
    @contextmanager
    def local_files(hrefs):
        yield hrefs, {"bytes": 0, "requests": 0}
    monkeypatch.setattr(analytics, "_bounded_cog_proxy", local_files)


def test_chip_weights_qa_scale_indices_and_offline_reuse(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    cache = tmp_path / "cache"
    receipt = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=cache,
                                      network_mode="online", buffer_m=30)
    assert receipt["status"] == "available"
    assert receipt["qa"]["field_area_m2"] == pytest.approx(3600, abs=1)
    # The chip follows the native asset lattice, so one of four cells is cloudy.
    assert receipt["qa"]["valid_area_fraction"] == pytest.approx(.75)
    assert receipt["zonal_stats"]["NDVI"]["mean"] == pytest.approx(.5)
    assert receipt["zonal_stats"]["NDMI"]["mean"] == pytest.approx(5/7)
    assert 4 <= receipt["grid"]["width"] <= 5
    assert 4 <= receipt["grid"]["height"] <= 5
    assert receipt["grid"]["crs"] == "EPSG:32613"
    assert (receipt["grid"]["transform"][2] - 500000) / 30 == pytest.approx(
        round((receipt["grid"]["transform"][2] - 500000) / 30))
    assert receipt["qa"]["excluded_area_m2_by_reason"]["cloud"] == pytest.approx(900)
    with np.load(cache / receipt["cache_files"]["npz"]) as chip:
        assert chip["bands"].shape == (6, receipt["grid"]["height"], receipt["grid"]["width"])
        assert chip["bands"].dtype == np.float32
        assert np.count_nonzero(chip["field_mask"]) == 4
        assert np.isnan(chip["bands"][:, chip["fmask"] == 2]).all()
        metadata = json.loads(str(chip["metadata_json"]))
        assert metadata["process_version"] == analytics.PROCESS_VERSION
        assert metadata["source_native_grid"] is True
        assert metadata["resampling_method"] == "nearest"
        assert metadata["native_asset_grid"]["crs"] == "EPSG:32613"
        assert metadata["band_names"] == list(analytics.BAND_NAMES)
        assert metadata["source"]["band_metadata"]["B8A"]["scale"] == .0001
    monkeypatch.setattr(analytics, "_scene_item", lambda *args: pytest.fail("offline network"))
    cached = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=cache,
                                     network_mode="offline", buffer_m=30)
    assert cached["cache_hit"] and cached["chip_hash"] == receipt["chip_hash"]
    missed = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=cache,
                                     network_mode="offline", buffer_m=0)
    assert missed["status"] == "blocked_offline"


def test_empty_cloud_is_explicit_and_does_not_invent_index(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch, all_cloud=True)
    receipt = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=tmp_path / "cache",
                                      network_mode="online")
    assert receipt["status"] == "empty_valid_area"
    assert receipt["qa"]["valid_area_fraction"] == 0
    assert receipt["zonal_stats"]["NDVI"]["mean"] is None


def test_native_context_keeps_field_stats_unbuffered(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    receipt = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=tmp_path / "cache",
                                      network_mode="online", context_pixels=224)
    assert receipt["status"] == "available"
    assert receipt["grid"]["width"] == receipt["grid"]["height"] == 224
    assert receipt["qa"]["field_area_m2"] == pytest.approx(3600, abs=1)
    with np.load(tmp_path / "cache" / receipt["cache_files"]["npz"]) as chip:
        assert chip["bands"].shape == (6, 224, 224)
        assert 0 < np.count_nonzero(chip["field_mask"]) < 20


def test_undefined_ndvi_is_transparent_and_preview_version_changes_cache_identity(tmp_path, monkeypatch):
    ndvi = np.array([[np.nan, -1.0, 0.5]], dtype=np.float32)
    valid = np.ones((1, 3), dtype=bool)
    weights = np.ones((1, 3), dtype=np.float32)
    rgba = np.asarray(Image.open(io.BytesIO(analytics._png(ndvi, valid, weights, Image))))
    assert rgba[0, :, 3].tolist() == [0, 255, 255]

    _fixture(tmp_path, monkeypatch)
    first = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=tmp_path / "cache",
                                    network_mode="online")
    assert first["preview_version"] == analytics.PREVIEW_VERSION
    original = analytics.PREVIEW_VERSION
    monkeypatch.setattr(analytics, "PREVIEW_VERSION", "older-display-only-preview")
    second = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=tmp_path / "cache",
                                     network_mode="online")
    assert not second["cache_hit"]
    assert first["request_hash"] != second["request_hash"]
    assert first["process_hash"] != second["process_hash"]
    assert first["chip_hash"] != second["chip_hash"]
    monkeypatch.setattr(analytics, "PREVIEW_VERSION", original)


def test_utm_boundary_uses_source_asset_crs_and_lattice(tmp_path, monkeypatch):
    geometry = {"type": "Polygon", "coordinates": [[
        [-106.7005, 52.1000], [-106.6995, 52.1000], [-106.6995, 52.1010],
        [-106.7005, 52.1010], [-106.7005, 52.1000]]]}
    # The AOI centroid is in UTM 13, but this public HLS tile is UTM 12.
    center_x, center_y = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32612", always_xy=True).transform(-106.7, 52.1005)
    left = round(center_x / 30) * 30 - 240
    top = round(center_y / 30) * 30 + 240
    _fixture(tmp_path, monkeypatch, source_crs="EPSG:32612",
             source_transform=from_origin(left, top, 30, 30), side=16)
    receipt = analytics.analyze_scene(geometry, PROVIDER, SCENE, cache_root=tmp_path / "cache",
                                      network_mode="online")
    assert receipt["status"] == "available"
    assert receipt["grid"]["crs"] == "EPSG:32612"
    assert receipt["grid"]["native_asset_grid"]["crs"] == "EPSG:32612"
    assert receipt["grid"]["resampling_method"] == "nearest"
    assert (receipt["grid"]["transform"][2] - left) / 30 == pytest.approx(
        round((receipt["grid"]["transform"][2] - left) / 30))


def test_misaligned_band_grid_fails_closed(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    path = tmp_path / "B03.tif"
    with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=1,
                       dtype="int16", crs="EPSG:32613", transform=from_origin(500015, 4427810, 30, 30),
                       nodata=-9999) as dst:
        dst.write(np.full((4, 4), 1000, dtype=np.int16), 1)
    receipt = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=tmp_path / "cache",
                                      network_mode="online")
    assert receipt["status"] == "unavailable"
    assert receipt["error_type"] == "RuntimeError"


@pytest.mark.parametrize("crs,origin", [
    ("EPSG:4326", (-120, 60)),
    ("EPSG:2263", (1000000, 200000)),
])
def test_source_grid_rejects_geographic_and_foot_units(tmp_path, crs, origin):
    path = tmp_path / "bad-units.tif"
    with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=1,
                       dtype="int16", crs=crs,
                       transform=from_origin(origin[0], origin[1], 30, 30), nodata=-9999) as dst:
        dst.write(np.ones((4, 4), dtype=np.int16), 1)
    with pytest.raises(RuntimeError, match="metre"):
        analytics._source_grid({"B02": str(path)}, analytics._dependencies())


def test_cog_proxy_reserves_concurrent_ranges_before_streaming(monkeypatch):
    captured = {}
    started = threading.Event()
    release = threading.Event()

    class FakeServer:
        server_port = 1
        def __init__(self, address, handler):
            captured["handler"] = handler
        def serve_forever(self):
            pass
        def shutdown(self):
            pass
        def server_close(self):
            pass

    class FakeUpstream:
        status_code = 206
        headers = {"Content-Length": "3", "Content-Range": "bytes 0-2/3"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_raw(self, size):
            started.set()
            assert release.wait(5)
            yield b"abc"

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def stream(self, *args, **kwargs):
            return FakeUpstream()

    monkeypatch.setattr(analytics, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(analytics.httpx, "Client", FakeClient)
    monkeypatch.setattr(analytics, "MAX_COG_TRANSFER_BYTES", 4)
    monkeypatch.setattr(analytics, "MAX_SINGLE_RANGE_BYTES", 4)
    monkeypatch.setattr(analytics, "_PROXY_CHUNK_BYTES", 1)
    with analytics._bounded_cog_proxy({"B02": "https://allowlisted.test/redacted"}) as (_, state):
        def request():
            handler = captured["handler"].__new__(captured["handler"])
            handler.path = "/B02.tif"
            handler.headers = {"Range": "bytes=0-2"}
            handler.wfile = io.BytesIO()
            handler.close_connection = False
            handler.statuses = []
            handler.send_response = lambda code: handler.statuses.append(code)
            handler.send_header = lambda *args: None
            handler.end_headers = lambda: None
            handler.send_error = lambda code: handler.statuses.append(code)
            handler._forward(head=False)
            return handler.statuses, handler.wfile.getvalue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request)
            assert started.wait(5)
            second = pool.submit(request)
            assert second.result(timeout=5)[0] == [429]
            release.set()
            assert first.result(timeout=5) == ([206], b"abc")
        assert state["bytes"] == 3
        assert state["reserved"] == 0
        assert state["requests"] == 1
        assert state["rejected"] == 1


def test_cog_proxy_rejects_encoding_and_stops_declared_length_overrun(monkeypatch):
    captured = {}
    mode = {"encoding": "gzip", "payload": b"abcd"}
    class FakeServer:
        server_port = 1
        def __init__(self, address, handler):
            captured["handler"] = handler
        def serve_forever(self):
            pass
        def shutdown(self):
            pass
        def server_close(self):
            pass
    class FakeResponse:
        status_code = 206
        @property
        def headers(self):
            return {"Content-Length": "3", "Content-Range": "bytes 0-2/3",
                    "Content-Encoding": mode["encoding"]}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def iter_raw(self, size):
            yield mode["payload"]
    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def stream(self, *args, **kwargs):
            assert kwargs["headers"]["Accept-Encoding"] == "identity"
            return FakeResponse()
    monkeypatch.setattr(analytics, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(analytics.httpx, "Client", FakeClient)
    monkeypatch.setattr(analytics, "MAX_COG_TRANSFER_BYTES", 7)
    monkeypatch.setattr(analytics, "_PROXY_CHUNK_BYTES", 4)
    def request():
        handler = captured["handler"].__new__(captured["handler"])
        handler.path = "/B02.tif"
        handler.headers = {"Range": "bytes=0-2"}
        handler.wfile = io.BytesIO()
        handler.close_connection = False
        handler.statuses = []
        handler.send_response = lambda code: handler.statuses.append(code)
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.send_error = lambda code: handler.statuses.append(code)
        handler._forward(head=False)
        return handler
    with analytics._bounded_cog_proxy({"B02": "https://allowlisted.test/redacted"}) as (_, state):
        rejected = request()
        assert rejected.statuses == [502] and state["bytes"] == 0
        mode["encoding"] = "identity"
        overrun = request()
        assert overrun.statuses == [206]
        assert overrun.close_connection is True
        assert overrun.wfile.getvalue() == b""
        assert state["bytes"] == 4 and state["reserved"] == 0


def test_nodata_and_zero_index_denominator_are_explicit(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    with rasterio.open(tmp_path / "B04.tif", "r+") as dst:
        red = dst.read(1)
        red[2, 2] = -9999
        red[1, 2] = 0
        dst.write(red, 1)
    with rasterio.open(tmp_path / "B8A.tif", "r+") as dst:
        nir = dst.read(1)
        nir[1, 2] = 0
        dst.write(nir, 1)
    receipt = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=tmp_path / "cache",
                                      network_mode="online")
    assert receipt["status"] == "available"
    assert receipt["qa"]["nodata_area_m2"] == pytest.approx(900)
    assert receipt["qa"]["valid_area_fraction"] == pytest.approx(.5)
    # One clear cell has 0/0 NDVI and is retained as valid QA but excluded
    # from the NDVI mean and its index-area denominator.
    assert receipt["zonal_stats"]["NDVI"]["area_m2"] == pytest.approx(900)
    assert receipt["zonal_stats"]["NDVI"]["mean"] == pytest.approx(.5)


def test_missing_hashes_are_not_attested_or_rewritten(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch)
    cache = tmp_path / "cache"
    receipt = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=cache,
                                      network_mode="online")
    store = ImageryStore(cache)
    originals = {name: (cache / name).read_bytes() for name in receipt["cache_files"].values()}
    with store._connect() as db:
        db.execute("""UPDATE chips SET npz_sha256=NULL,png_sha256=NULL,
                      receipt_sha256=NULL,receipt_file_sha256=NULL""")
    assert store.get_by_chip_hash(receipt["chip_hash"]) is None
    with store._connect() as db:
        row = db.execute("SELECT npz_sha256,png_sha256,receipt_sha256 FROM chips").fetchone()
    assert list(row) == [None, None, None]
    assert {name: (cache / name).read_bytes() for name in originals} == originals


def test_polygon_no_nodata_tile_edge_and_historical_identity(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch, side=2, nodata_metadata=False)
    # Support x=500030..500090 crosses the tile edge at x=500060; its
    # bottom half is also outside. The sole supported source cell is cloudy.
    cache = tmp_path / "cache"
    receipt = analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=cache,
                                      network_mode="online")
    assert receipt["status"] == "empty_valid_area"
    assert receipt["qa"]["field_area_m2"] == pytest.approx(3600, abs=1e-5)
    assert receipt["qa"]["nodata_area_m2"] == pytest.approx(2700, abs=1e-5)
    assert receipt["qa"]["valid_area_m2"] == 0
    assert receipt["zonal_stats"]["NDVI"]["mean"] is None
    with np.load(cache / receipt["cache_files"]["npz"]) as chip:
        assert chip["field_weights"].dtype == np.float64
        assert not chip["valid_mask"].any()
        assert np.isnan(chip["bands"]).all()
    image = np.asarray(Image.open(cache / receipt["cache_files"]["png"]))
    assert not image[..., 3].any()
    # A prior processing identity cannot satisfy the corrected request.
    current = analytics.PROCESS_VERSION
    monkeypatch.setattr(analytics, "PROCESS_VERSION", "hls-chip-v2-native-asset-grid-fmask-v1")
    historical = analytics._request_identity(_geometry(), PROVIDER, SCENE, None, None, 0, None)[3]
    monkeypatch.setattr(analytics, "PROCESS_VERSION", current)
    assert receipt["request_hash"] != historical


def test_polygon_partial_clear_coverage_and_context_outside_tile(tmp_path, monkeypatch):
    _fixture(tmp_path, monkeypatch, side=2, nodata_metadata=False)
    with rasterio.open(tmp_path / "Fmask.tif", "r+") as dst:
        dst.write(np.zeros((2, 2), dtype=np.int16), 1)
    receipt = analytics.analyze_scene(_geometry(), PROVIDER, SCENE,
                                      cache_root=tmp_path / "cache", network_mode="online",
                                      context_pixels=224)
    assert receipt["qa"]["valid_area_fraction"] == pytest.approx(.25, abs=1e-8)
    assert receipt["qa"]["valid_area_m2"] == pytest.approx(900, abs=1e-5)
    assert receipt["qa"]["nodata_area_m2"] == pytest.approx(2700, abs=1e-5)
    assert receipt["zonal_stats"]["NDVI"]["mean"] == pytest.approx(.5)
    with np.load(tmp_path / "cache" / receipt["cache_files"]["npz"]) as chip:
        # Validity includes context inside the source tile, independently of
        # the polygon's reporting support, but never zeros outside the tile.
        assert np.count_nonzero(chip["valid_mask"]) == 4


def test_cog_proxy_counts_ranges_and_rejects_redirects():
    content = b"abcde"
    class Origin(BaseHTTPRequestHandler):
        redirect = False
        def log_message(self, *args):
            pass
        def do_HEAD(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
        def do_GET(self):
            if self.redirect:
                self.send_response(302)
                self.send_header("Location", "https://example.org/other")
                self.end_headers()
                return
            assert self.headers.get("Range") == "bytes=1-3"
            self.send_response(206)
            self.send_header("Content-Length", "3")
            self.send_header("Content-Range", "bytes 1-3/5")
            self.end_headers()
            self.wfile.write(content[1:4])
    origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    thread = threading.Thread(target=origin.serve_forever, daemon=True)
    thread.start()
    try:
        with analytics._bounded_cog_proxy({"B02": f"http://127.0.0.1:{origin.server_port}/asset"}) as (urls, state):
            with httpx.Client(timeout=3) as client:
                assert client.head(urls["B02"]).status_code == 200
                response = client.get(urls["B02"], headers={"Range": "bytes=1-3"})
                assert response.status_code == 206 and response.content == b"bcd"
                assert client.get(urls["B02"]).status_code == 416
                Origin.redirect = True
                assert client.get(urls["B02"], headers={"Range": "bytes=1-3"}).status_code == 502
            assert state["bytes"] == 3 and state["requests"] == 1
            assert state["rejected"] == 2
    finally:
        origin.shutdown()
        origin.server_close()
        thread.join(timeout=5)


def test_bad_scope_and_cache_location_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=tmp_path, buffer_m=3001)
    with pytest.raises(ValueError):
        analytics.analyze_scene(_geometry(), "sentinel2-c1-earth-search", SCENE, cache_root=tmp_path)
    with pytest.raises(ValueError):
        analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=analytics.Path(__file__).resolve().parents[1] / "outputs")
    with pytest.raises(ValueError):
        analytics.analyze_scene(_geometry(), PROVIDER, SCENE, cache_root=tmp_path, start_date="2025-07-01")
    with pytest.raises(ValueError):
        analytics.analyze_scene(_geometry(), PROVIDER, "hls2-s30:bad/path", cache_root=tmp_path)
