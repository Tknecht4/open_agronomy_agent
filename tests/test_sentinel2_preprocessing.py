"""Analytic source-encoding and grid/QA contracts for the C1 L2A adapter."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
rasterio = pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
from rasterio.transform import from_origin
from pyproj import Transformer

from agronomy_agent.geospatial.sentinel2 import (
    ALL_KEYS, BAND_KEYS, BAND_CODES, COLLECTION, PROCESS_VERSION,
    Sentinel2Refusal, prepare_scene, validate_item,
)

BASE = "https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/52/J/FM/2024/4/S2B_T52JFM_20240407T012410_L2A/"
CODES = dict(zip(BAND_KEYS, BAND_CODES)) | {"scl": "SCL"}


def raw_item():
    assets = {}
    for key in ALL_KEYS:
        resolution = 10 if key in ("blue", "green", "red") else 20
        band = {"nodata": 0, "data_type": "uint8" if key == "scl" else "uint16",
                "spatial_resolution": resolution}
        if key != "scl":
            band.update(scale=.0001, offset=-.1)
        assets[key] = {"href": BASE + CODES[key] + ".tif",
                       "roles": ["data"] if key == "scl" else ["data", "reflectance"],
                       "gsd": resolution, "raster:bands": [band],
                       "proj:shape": [12, 12] if resolution == 10 else [6, 6],
                       "proj:transform": [resolution, 0, 600000, 0, -resolution, 6700000]}
        if key != "scl":
            assets[key]["eo:bands"] = [{"name": CODES[key]}]
    return {"type": "Feature", "id": "S2B_T52JFM_20240407T012410_L2A",
            "collection": COLLECTION,
            "properties": {"datetime": "2024-04-07T01:24:10Z",
                           "created": "2024-04-07T06:00:11Z",
                           "s2:product_type": "S2MSI2A",
                           "s2:processing_baseline": "05.10",
                           "s2:product_uri": "S2B_MSIL2A_20240407T011719_N0510_R088_T52JFM_20240407T025718.SAFE",
                           "view:sun_elevation": 43.7935883542371,
                           "eo:cloud_cover": 20.0, "proj:epsg": 32752},
            "assets": assets}


def geom_for_cells(col0=2, row0=2, col1=4, row1=4):
    west, east = 600000 + col0 * 20, 600000 + col1 * 20
    north, south = 6700000 - row0 * 20, 6700000 - row1 * 20
    transform = Transformer.from_crs(32752, 4326, always_xy=True)
    coords = [transform.transform(x, y) for x, y in
              [(west, north), (east, north), (east, south), (west, south), (west, north)]]
    return {"type": "Polygon", "coordinates": [[list(point) for point in coords]]}


def tiffs(tmp_path: Path, arrays=None):
    arrays = arrays or {}
    hrefs = {}
    for key in ALL_KEYS:
        resolution = 10 if key in ("blue", "green", "red") else 20
        shape = (12, 12) if resolution == 10 else (6, 6)
        value = 4 if key == "scl" else {"blue": 2000, "green": 3000,
                                          "red": 3000, "nir08": 7000,
                                          "swir16": 4000, "swir22": 3000}[key]
        data = np.array(arrays.get(key, np.full(shape, value)), copy=True)
        path = tmp_path / f"{key}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=shape[1], height=shape[0],
                           count=1, dtype="uint8" if key == "scl" else "uint16",
                           crs="EPSG:32752", transform=from_origin(600000, 6700000, resolution, resolution),
                           nodata=0) as dst:
            dst.write(data.astype(dst.dtypes[0]), 1)
            if key != "scl":
                dst.scales = (.0001,)
                dst.offsets = (-.1,)
        hrefs[key] = str(path)
    return hrefs


def test_admission_requires_real_source_semantics():
    item = validate_item(raw_item())
    assert item["id"].startswith(COLLECTION + ":")
    assert item["sun_zenith_deg"] == pytest.approx(46.2064116457629)
    assert len(item["source_metadata_sha256"]) == 64
    for mutate in (
        lambda x: x["properties"].update({"view:sun_elevation": 19.9}),
        lambda x: x["properties"].update({"s2:processing_baseline": "04.00"}),
        lambda x: x["assets"]["red"]["raster:bands"][0].update({"offset": 0}),
        lambda x: x["assets"]["scl"].update({"roles": ["visual"]}),
        lambda x: x["assets"]["nir08"].update({"href": "https://evil.example/B8A.tif"}),
        lambda x: x["assets"]["swir16"].update({"proj:transform": [20, 0, 600020, 0, -20, 6700000]}),
        lambda x: x["properties"].update({"eo:cloud_cover": float("nan")}),
    ):
        x = raw_item(); mutate(x)
        with pytest.raises(ValueError): validate_item(x)


def test_constant_reflectance_indices_and_native_dn(tmp_path):
    item = validate_item(raw_item())
    result = prepare_scene(item, tiffs(tmp_path), geom_for_cells(), cloud_buffer_m=0, edge_buffer_m=0)
    a = result["arrays"]
    assert result["grid"]["resolution_m"] == 20
    assert a["bands"].shape[0] == 6
    assert result["process_spec"]["version"] == PROCESS_VERSION
    assert result["process_spec"]["ndvi_nir_band"] == "B8A"
    assert result["zonal_stats"]["NDVI"]["mean"] == pytest.approx(.5)
    assert result["zonal_stats"]["NDMI"]["mean"] == pytest.approx(1/3)
    assert result["zonal_stats"]["NDVI"]["area_m2"] == pytest.approx(1600, rel=.02)
    assert a["raw_dn_red"].shape[0] == a["scl"].shape[0] * 2
    assert a["raw_dn_red"].dtype == np.uint16
    assert not np.any(a["source_invalid_red"])
    assert result["source_band_metadata"]["red"]["scale"] == pytest.approx(.0001)


def test_full_four_contributors_and_qa_classes(tmp_path):
    arrays = {"red": np.full((12, 12), 3000, dtype=np.uint16),
              "scl": np.full((6, 6), 4, dtype=np.uint8)}
    arrays["red"][4, 4] = 0  # one native 10 m contributor invalidates its 20 m cell
    arrays["scl"][3, 3] = 9
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path, arrays),
                           geom_for_cells(1, 1, 5, 5), cloud_buffer_m=0, edge_buffer_m=0)
    a = result["arrays"]
    assert a["source_invalid_mask"].sum() >= 1
    assert result["qa"]["excluded_area_m2_by_reason"]["scl_high_cloud"] > 0
    assert result["qa"]["valid_area_m2"] < result["qa"]["field_area_m2"]


def test_cloud_halo_and_interior_support(tmp_path):
    arrays = {"scl": np.full((6, 6), 4, dtype=np.uint8)}
    arrays["scl"][2, 2] = 8
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path, arrays),
                           geom_for_cells(3, 2, 5, 4), cloud_buffer_m=20, edge_buffer_m=20)
    assert result["qa"]["excluded_area_m2_by_reason"]["cloud_shadow_adjacency"] > 0
    assert result["qa"]["interior_field_area_m2"] < result["qa"]["field_area_m2"]


def test_non_grid_step_interior_buffer(tmp_path):
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path), geom_for_cells(1, 1, 5, 5),
                           cloud_buffer_m=0, edge_buffer_m=15)
    assert result["process_spec"]["edge_buffer_m"] == 15
    assert result["qa"]["interior_field_area_m2"] < result["qa"]["field_area_m2"]


def test_header_contradiction_and_resource_bound(tmp_path):
    item = validate_item(raw_item())
    hrefs = tiffs(tmp_path)
    with rasterio.open(hrefs["red"], "r+") as dst:
        dst.offsets = (0,)
    with pytest.raises(Sentinel2Refusal, match="source_radiometry_mismatch"):
        prepare_scene(item, hrefs, geom_for_cells(), cloud_buffer_m=0, edge_buffer_m=0)
    with pytest.raises(Sentinel2Refusal, match="resource_limit"):
        prepare_scene(validate_item(raw_item()), tiffs(tmp_path),
                      geom_for_cells(-300, -300, 300, 300), cloud_buffer_m=0, edge_buffer_m=0)


def test_admission_threshold_and_missing_offset():
    raw = raw_item()
    raw["properties"]["view:sun_elevation"] = 20
    assert validate_item(raw)["sun_zenith_deg"] == 70
    raw["properties"]["view:sun_elevation"] = 19.999
    with pytest.raises(Sentinel2Refusal) as failure:
        validate_item(raw)
    assert failure.value.reason == "solar_zenith_exceeds_limit"
    raw = raw_item()
    del raw["assets"]["red"]["raster:bands"][0]["offset"]
    with pytest.raises(Sentinel2Refusal) as failure:
        validate_item(raw)
    assert failure.value.reason == "source_radiometry_mismatch"
    raw = raw_item(); raw["properties"]["s2:processing_baseline"] = "05.01"
    raw["properties"]["s2:product_uri"] = raw["properties"]["s2:product_uri"].replace("N0510", "N0501")
    with pytest.raises(Sentinel2Refusal): validate_item(raw)


def test_average_ramp_and_native_invalid_retention(tmp_path):
    red = np.full((12, 12), 3000, dtype=np.uint16)
    red[4:6, 4:6] = [[2000, 3000], [4000, 5000]]
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path, {"red": red}),
                           geom_for_cells(1, 1, 5, 5), cloud_buffer_m=0, edge_buffer_m=0)
    a = result["arrays"]
    col = round((600040 - result["grid"]["transform"][2]) / 20)
    row = round((result["grid"]["transform"][5] - 6699960) / 20)
    assert a["bands"][2, row, col] == pytest.approx(.25)
    red[4, 4] = 0
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path, {"red": red}),
                           geom_for_cells(1, 1, 5, 5), cloud_buffer_m=0, edge_buffer_m=0)
    a = result["arrays"]
    col = round((600040 - result["grid"]["transform"][2]) / 20)
    row = round((result["grid"]["transform"][5] - 6699960) / 20)
    assert a["source_invalid_mask"][row, col]
    assert not a["valid_mask"][row, col]
    assert (a["raw_dn_red"] == 0).sum() >= 1
    assert a["source_invalid_red"].sum() >= 1


def test_cloud_outside_field_and_unknown_class(tmp_path):
    scl = np.full((6, 6), 4, dtype=np.uint8)
    scl[3, 2] = 9  # west of the field; field contains columns 3,4
    scl[3, 4] = 12
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path, {"scl": scl}),
                           geom_for_cells(3, 2, 5, 4), cloud_buffer_m=20, edge_buffer_m=0)
    reasons = result["qa"]["excluded_area_m2_by_reason"]
    assert reasons["scl_high_cloud"] == 0
    assert reasons["cloud_shadow_adjacency"] > 0
    assert reasons["scl_unknown_class"] > 0
    assert result["qa"]["valid_area_m2"] < result["qa"]["field_area_m2"]


def test_offsource_and_empty_interior(tmp_path):
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path),
                           geom_for_cells(-2, 1, 1, 4), cloud_buffer_m=0, edge_buffer_m=0)
    assert result["qa"]["excluded_area_m2_by_reason"]["source_invalid"] > 0
    assert result["qa"]["valid_area_m2"] < result["qa"]["field_area_m2"]
    assert result["qa"]["excluded_area_m2_by_reason"]["source_edge_guard"] > 0
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path),
                           geom_for_cells(2, 2, 3, 3), cloud_buffer_m=0, edge_buffer_m=20)
    assert result["qa"]["interior_field_area_m2"] == 0
    assert result["interior_zonal_stats"]["NDVI"]["mean"] is None
    assert result["process_spec"]["source_edge_guard_m"] == 20


def test_negative_pair_partition_and_grid_shift(tmp_path):
    nir = np.full((6, 6), 7000, dtype=np.uint16)
    nir[2, 2] = 500  # genuine encoded source DN, calibrated reflectance -0.05
    item = validate_item(raw_item())
    hrefs = tiffs(tmp_path, {"nir08": nir})
    result = prepare_scene(item, hrefs, geom_for_cells(1, 1, 5, 5),
                           cloud_buffer_m=0, edge_buffer_m=0)
    qa = result["qa"]
    assert qa["index_undefined_area_m2_by_reason"]["NDVI"]["negative_reflectance"] > 0
    assert qa["valid_area_m2"] == pytest.approx(
        qa["index_eligible_area_m2"]["NDVI"] +
        sum(qa["index_undefined_area_m2_by_reason"]["NDVI"].values()))
    assert np.nanmin(result["arrays"]["bands"][3]) < 0
    with rasterio.open(hrefs["nir08"], "r+") as dst:
        dst.transform = from_origin(600005, 6700000, 20, 20)
    with pytest.raises(Sentinel2Refusal) as failure:
        prepare_scene(item, hrefs, geom_for_cells(), cloud_buffer_m=0, edge_buffer_m=0)
    assert failure.value.reason == "source_grid_mismatch"


def test_header_nodata_and_offset_mismatch(tmp_path):
    item = validate_item(raw_item())
    hrefs = tiffs(tmp_path)
    with rasterio.open(hrefs["scl"], "r+") as dst:
        dst.nodata = 255
    with pytest.raises(Sentinel2Refusal) as failure:
        prepare_scene(item, hrefs, geom_for_cells(), cloud_buffer_m=0, edge_buffer_m=0)
    assert failure.value.reason == "source_radiometry_mismatch"
    hrefs = tiffs(tmp_path)
    with rasterio.open(hrefs["red"], "r+") as dst:
        dst.scales = (1,)
    with pytest.raises(Sentinel2Refusal) as failure:
        prepare_scene(item, hrefs, geom_for_cells(), cloud_buffer_m=0, edge_buffer_m=0)
    assert failure.value.reason == "source_radiometry_mismatch"


def test_zero_denominator_and_recipe_identity(tmp_path):
    nir = np.full((6, 6), 7000, dtype=np.uint16)
    red = np.full((12, 12), 3000, dtype=np.uint16)
    nir[2, 2] = 1000
    red[4:6, 4:6] = 1000
    item = validate_item(raw_item())
    result = prepare_scene(item, tiffs(tmp_path, {"nir08": nir, "red": red}),
                           geom_for_cells(1, 1, 5, 5), cloud_buffer_m=0, edge_buffer_m=0)
    reasons = result["qa"]["index_undefined_area_m2_by_reason"]["NDVI"]
    assert reasons["nonpositive_denominator"] > 0
    assert reasons["negative_reflectance"] == 0
    spec = result["process_spec"]
    assert "source_metadata_sha256" not in spec
    assert all(spec["libraries"].get(x) for x in ("numpy", "rasterio", "gdal", "pyproj", "shapely", "scipy"))
    assert result["source_band_metadata"]["red"]["transform"][0] == 10
    with pytest.raises(Sentinel2Refusal):
        prepare_scene(item, tiffs(tmp_path), geom_for_cells(), cloud_buffer_m=15, edge_buffer_m=0)


def test_reserved_saturation_even_when_scl_clear(tmp_path):
    red = np.full((12, 12), 3000, dtype=np.uint16)
    nir = np.full((6, 6), 7000, dtype=np.uint16)
    red[4, 4] = 65535
    nir[3, 3] = 65535
    result = prepare_scene(validate_item(raw_item()), tiffs(tmp_path, {"red": red, "nir08": nir}),
                           geom_for_cells(1, 1, 5, 5), cloud_buffer_m=0, edge_buffer_m=0)
    a = result["arrays"]
    assert 65535 in a["raw_dn_red"]
    assert a["source_saturated_red"].sum() == 1
    assert np.all(a["source_invalid_red"][a["source_saturated_red"]])
    assert a["source_saturated_nir08"].sum() == 1
    assert a["source_saturated_mask"].sum() == 2
    assert result["qa"]["excluded_area_m2_by_reason"]["source_saturated"] > 0
    assert result["zonal_stats"]["NDVI"]["max"] <= 1
    assert result["process_spec"]["spectral_special_values"]["saturated_dn"] == 65535


def test_malformed_eo_and_boolean_nodata_are_typed_refusals():
    raw = raw_item(); raw["assets"]["red"]["eo:bands"] = [None]
    with pytest.raises(Sentinel2Refusal): validate_item(raw)
    raw = raw_item(); raw["assets"]["red"]["raster:bands"][0]["nodata"] = False
    with pytest.raises(Sentinel2Refusal): validate_item(raw)


@pytest.mark.parametrize("replacement", [
    ("T52JFM", "T13TFE"), ("S2B_", "S2A_"),
    (".SAFE", ".unexpected"), ("20240407T011719", "20240231T011719"),
])
def test_safe_product_identity_must_match_admitted_item(replacement):
    raw = raw_item()
    raw["properties"]["s2:product_uri"] = raw["properties"]["s2:product_uri"].replace(*replacement)
    with pytest.raises(Sentinel2Refusal):
        validate_item(raw)


def test_safe_datatake_and_granule_timestamps_may_differ():
    raw = raw_item()
    assert "20240407T011719" in validate_item(raw)["product_uri"]
    assert "20240407T012410" in raw["id"]
