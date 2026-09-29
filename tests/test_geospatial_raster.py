"""Small synthetic contracts for shared support and standard raster interchange."""
import json

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
shapely = pytest.importorskip("shapely")
from affine import Affine
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from agronomy_agent.geospatial.raster import (
    fractional_weights, source_extent_mask, weighted_statistics, write_geotiff,
)


def test_fractional_weights_holes_and_sub_float32_precision():
    transform = from_origin(0, 3, 1, 1)
    polygon = Polygon([(0, 0), (3, 0), (3, 3), (0, 3)],
                      holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]])
    weights = fractional_weights(polygon, transform, 3, 3)
    assert weights.dtype == np.float64
    assert weights[1, 1] == 0
    assert weights.sum() == 8
    precise = 0.1234567890123
    partial = fractional_weights(box(0, 0, precise, 1), from_origin(0, 1, 1, 1), 1, 1)
    assert partial[0, 0] == pytest.approx(precise, abs=1e-15)
    assert abs(partial[0, 0] - np.float64(np.float32(precise))) > 1e-10


def test_rotated_cells_and_multipolygon_use_affine_area():
    transform = Affine.translation(1000, 2000) * Affine.rotation(25) * Affine.scale(4, -2)
    corners = [transform * p for p in [(0, 0), (2, 0), (2, 2), (0, 2)]]
    support = Polygon(corners)
    weights = fractional_weights(support, transform, 3, 3)
    assert weights[:2, :2] == pytest.approx(np.ones((2, 2)), abs=1e-12)
    assert weights.sum() * 8 == pytest.approx(support.area, abs=1e-10)
    multi = shapely.MultiPolygon([box(0, 0, .5, 1), box(1.5, 0, 2, 1)])
    assert fractional_weights(multi, from_origin(0, 1, 1, 1), 2, 1).tolist() == [[.5, .5]]


def test_source_extent_is_coverage_not_nodata_or_support():
    covered = source_extent_mask(from_origin(-1, 3, 1, 1), 4, 4,
                                 source_transform=from_origin(0, 2, 1, 1),
                                 source_width=2, source_height=2)
    expected = np.zeros((4, 4), dtype=bool)
    expected[1:3, 1:3] = True
    assert np.array_equal(covered, expected)
    far = source_extent_mask(from_origin(100, 3, 1, 1), 2, 2,
                             source_transform=from_origin(0, 2, 1, 1),
                             source_width=2, source_height=2)
    assert not far.any()


def test_reductions_use_finite_supported_values_and_float64():
    values = np.array([[.7, .7, np.nan, 999]], dtype=np.float32)
    weights = np.array([[.1, .2, .3, 0]], dtype=np.float64)
    stats = weighted_statistics(values, weights, cell_area=900)
    assert stats["min"] <= stats["mean"] <= stats["max"]
    assert stats["area_m2"] == pytest.approx(270)
    empty = weighted_statistics(values, weights, valid=np.zeros((1, 4), bool))
    assert empty == {"mean": None, "min": None, "max": None, "area_m2": 0}
    with pytest.raises(ValueError, match="matching shapes"):
        weighted_statistics(values, weights[:, :2])


def test_geotiff_roundtrip_crs_transform_nodata_descriptions_and_lineage(tmp_path):
    transform = Affine(3, .25, 500000, .5, -3, 4400000)
    values = np.ma.array([[[1.1234567890123, np.nan], [3, 4]],
                          [[5, 6], [7, 8]]], mask=False)
    values.mask[1, 1, 1] = True
    path = write_geotiff(tmp_path / "tiny.tif", values, crs="EPSG:32613",
                         transform=transform, band_names=["elevation", "slope"],
                         metadata={"evidence_role": "model_output", "source": "synthetic"})
    with rasterio.open(path) as dataset:
        assert dataset.crs == rasterio.crs.CRS.from_epsg(32613)
        assert dataset.transform == transform
        assert dataset.descriptions == ("elevation", "slope")
        assert dataset.nodata == -9999
        assert dataset.dtypes == ("float64", "float64")
        restored = dataset.read(masked=True)
        assert restored[0, 0, 0] == values[0, 0, 0]
        assert restored.mask[0, 0, 1] and restored.mask[1, 1, 1]
        assert json.loads(dataset.tags()["metadata_json"])["source"] == "synthetic"


@pytest.mark.parametrize("kwargs", [{"crs": None}, {"band_names": []}, {"nodata": 1}])
def test_geotiff_rejects_ambiguous_export_before_writing(tmp_path, kwargs):
    options = {"crs": "EPSG:4326", "transform": from_origin(1, 2, .1, .1), **kwargs}
    path = tmp_path / "invalid.tif"
    with pytest.raises(ValueError):
        write_geotiff(path, np.ones((1, 1)), **options)
    assert not path.exists()


def test_nan_nodata_preserves_valid_negative_elevations(tmp_path):
    path = write_geotiff(tmp_path / "nan-nodata.tif", [[-9999., np.nan]],
                         crs="EPSG:32613", transform=from_origin(1, 2, 1, 1),
                         nodata=float("nan"))
    with rasterio.open(path) as dataset:
        assert np.isnan(dataset.nodata)
        restored = dataset.read(1, masked=True)
        assert restored[0, 0] == -9999.
        assert not restored.mask[0, 0]
        assert restored.mask[0, 1]
    with pytest.raises(ValueError, match="nodata"):
        write_geotiff(tmp_path / "inf.tif", [[1]], crs="EPSG:32613",
                      transform=from_origin(1, 2, 1, 1), nodata=float("inf"))
