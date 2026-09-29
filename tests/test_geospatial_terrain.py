"""Synthetic numerical references and negative terrain admission contracts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from agronomy_agent.geospatial.terrain import TerrainError, run_terrain_analysis, terrain_readiness


METADATA = {
    "source_id": "synthetic-contract-fixture", "source_url": "https://example.org/synthetic-fixture",
    "source_date": "2026-09-28", "license": "synthetic test data",
    "terrain_type": "DTM", "bare_earth": True, "vertical_units": "m",
    "vertical_datum": "synthetic local vertical reference",
}


@pytest.fixture
def terrain_fixture(tmp_path):
    np = pytest.importorskip("numpy")
    rio = pytest.importorskip("rasterio")
    pytest.importorskip("pyflwdir")
    pytest.importorskip("shapely")
    pyproj = pytest.importorskip("pyproj")
    from rasterio.transform import from_origin
    transform = from_origin(500000, 6000150, 10, 10)
    to_wgs84 = pyproj.Transformer.from_crs(32612, 4326, always_xy=True)
    coordinates = [(500060, 6000060), (500090, 6000060), (500090, 6000090),
                   (500060, 6000090), (500060, 6000060)]
    geometry = {"type": "Polygon", "coordinates": [[list(to_wgs84.transform(*xy)) for xy in coordinates]]}

    def make(array=None, *, crs="EPSG:32612", affine=transform, nodata=None):
        if array is None:
            rows, cols = np.indices((15, 15))
            array = 100 + 2 * cols + rows
        path = tmp_path / "input.tif"
        with rio.open(path, "w", driver="GTiff", count=1, width=15, height=15,
                      dtype="float64", transform=affine, crs=crs, nodata=nodata) as dst:
            dst.write(np.asarray(array, dtype="float64"), 1)
        return path

    return np, rio, make, geometry, tmp_path / "output"


def _run(fixture, **kwargs):
    np, rio, make, geometry, output = fixture
    path = kwargs.pop("dem_path", None) or make()
    return run_terrain_analysis(path, geometry, output,
                                source_metadata=kwargs.pop("source_metadata", METADATA),
                                context_buffer_m=kwargs.pop("context_buffer_m", 40), **kwargs)


def test_readiness_has_explicit_limits():
    result = terrain_readiness()
    assert result["status"] in {"setup_required", "installed_not_exercised"}
    assert result["scientific_status"] == "model_derived_context_only"
    assert result["network_required"] is False


@pytest.mark.parametrize("change, message", [
    ({"terrain_type": "DSM"}, "bare-earth"),
    ({"bare_earth": False}, "bare-earth"),
    ({"vertical_units": "ft"}, "vertical_units"),
    ({"vertical_datum": "unknown"}, "vertical_datum"),
    ({"source_date": ""}, "source_date"),
    ({"license": None}, "license"),
])
def test_metadata_fails_before_optional_imports(tmp_path, change, message):
    with pytest.raises(TerrainError, match=message):
        run_terrain_analysis("does-not-exist.tif", {}, tmp_path / "out",
                             source_metadata={**METADATA, **change}, context_buffer_m=40)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("path", ["https://example.org/dem.tif", "/vsicurl/https://example.org/dem.tif"])
def test_remote_raster_is_rejected(tmp_path, path):
    with pytest.raises(TerrainError, match="local GeoTIFF"):
        run_terrain_analysis(path, {}, tmp_path / "out", source_metadata=METADATA, context_buffer_m=40)


def test_plane_slope_matches_analytic_reference_and_preserves_source(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    path = make()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = _run(terrain_fixture, dem_path=path, include_twi=True)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert result["source"]["sha256"] == before
    assert result["field_summary"]["slope_m_per_m"]["mean"] == pytest.approx(np.sqrt(5) / 10, rel=1e-6)
    assert result["field_summary"]["potential_depression_fill_depth_m"]["max"] == 0
    assert result["field"]["support_area_m2"] == pytest.approx(900, abs=1e-5)
    assert result["processing"]["grid"]["width"] > 3
    assert result["processing"]["resampling"] == "none"
    for artifact in result["artifacts"].values():
        artifact_path = output / artifact["path"]
        assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact["sha256"]
        with rio.open(artifact_path) as dataset:
            assert dataset.crs.to_epsg() == 32612
            assert dataset.dtypes == ("float64",)
    assert json.loads((output / "terrain.json").read_text()) == result


def test_bowl_fill_is_model_delta_and_flat_twi_unknown(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    bowl = np.full((15, 15), 100.0)
    bowl[7, 7] = 90.0
    result = _run(terrain_fixture, dem_path=make(bowl), include_twi=True)
    assert result["field_summary"]["potential_depression_fill_depth_m"]["max"] == 10
    assert result["observation_status"] == "not_field_observation"
    with rio.open(output / "dem_unconditioned_m.tif") as dataset:
        original = dataset.read(1)
    with rio.open(output / "dem_conditioned_m.tif") as dataset:
        conditioned = dataset.read(1)
    with rio.open(output / "twi.tif") as dataset:
        twi = dataset.read(1, masked=True)
    center = np.unravel_index(np.argmin(original), original.shape)
    assert original[center] == 90
    assert conditioned[center] == 100
    assert np.ma.getmaskarray(twi)[center]
    assert result["processing"]["twi"]["slope_floor"] is None
    assert result["processing"]["twi"]["pseudocount"] is None


def test_boundary_contributions_are_unknown_not_zero(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    result = _run(terrain_fixture, include_twi=True)
    with rio.open(output / "edge_influence_mask.tif") as dataset:
        influence = dataset.read(1) == 1
    with rio.open(output / "contributing_area_m2.tif") as dataset:
        area = dataset.read(1, masked=True)
    with rio.open(output / "twi.tif") as dataset:
        twi = dataset.read(1, masked=True)
    assert influence.any()
    assert np.ma.getmaskarray(area)[influence].all()
    assert np.ma.getmaskarray(twi)[influence].all()
    assert result["field_summary"]["edge_influenced_support_area_m2"] > 0


@pytest.mark.parametrize("context", [0, -1, float("nan"), float("inf"), 10, 1000])
def test_insufficient_or_invalid_context_creates_no_output(terrain_fixture, context):
    with pytest.raises(TerrainError, match="context|Context|buffer"):
        _run(terrain_fixture, context_buffer_m=context)
    assert not terrain_fixture[-1].exists()


def test_void_in_context_outside_field_rejected(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    array = np.full((15, 15), 100.0)
    array[3, 3] = -9999
    with pytest.raises(TerrainError, match="nodata/voids"):
        _run(terrain_fixture, dem_path=make(array, nodata=-9999))
    assert not output.exists()


def test_nonfinite_dem_rejected(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    array = np.full((15, 15), 100.0)
    array[7, 7] = np.nan
    with pytest.raises(TerrainError, match="nodata/voids"):
        _run(terrain_fixture, dem_path=make(array))


def test_geographic_dem_rejected(terrain_fixture):
    with pytest.raises(TerrainError, match="projected"):
        _run(terrain_fixture, dem_path=terrain_fixture[2](crs="EPSG:4326"))


def test_rotated_and_rectangular_grid_rejected(terrain_fixture):
    from affine import Affine
    for affine in [Affine(10, 1, 500000, 0, -10, 6000150), Affine(10, 0, 500000, 0, -20, 6000150)]:
        with pytest.raises(TerrainError, match="square cells"):
            _run(terrain_fixture, dem_path=terrain_fixture[2](affine=affine))


def test_resource_bound_rejected_before_write(terrain_fixture):
    with pytest.raises(TerrainError, match="max_cells"):
        _run(terrain_fixture, max_cells=10)
    assert not terrain_fixture[-1].exists()


def test_point_geometry_is_not_a_field(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    with pytest.raises(ValueError):
        run_terrain_analysis(make(), {"type": "Point", "coordinates": [-111, 54]}, output,
                             source_metadata=METADATA, context_buffer_m=40)
    assert not output.exists()


def test_output_never_clobbers(terrain_fixture):
    output = terrain_fixture[-1]
    output.mkdir()
    marker = output / "user-file.txt"
    marker.write_text("retain")
    with pytest.raises(TerrainError, match="never overwrite"):
        _run(terrain_fixture)
    assert marker.read_text() == "retain"


def test_flat_dem_reports_null_twi(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    result = _run(terrain_fixture, dem_path=make(np.ones((15, 15))), include_twi=True)
    assert result["field_summary"]["twi"]["mean"] is None
    assert result["field_summary"]["twi"]["area_m2"] == 0
    assert result["field_summary"]["flat_slope_support_area_m2"] == pytest.approx(900, abs=1e-5)


def test_summit_cell_area_and_finite_twi_reference(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    rows, cols = np.indices((15, 15))
    hill = 100.0 - np.abs(rows - 7) - np.abs(cols - 7)
    result = _run(terrain_fixture, dem_path=make(hill), include_twi=True)
    with rio.open(output / "dem_unconditioned_m.tif") as dataset:
        original = dataset.read(1)
    peak = np.unravel_index(np.argmax(original), original.shape)
    with rio.open(output / "contributing_area_m2.tif") as dataset:
        area = dataset.read(1, masked=True)
    with rio.open(output / "slope_m_per_m.tif") as dataset:
        slope = dataset.read(1, masked=True)
    with rio.open(output / "twi.tif") as dataset:
        twi = dataset.read(1, masked=True)
    assert area[peak] == 100  # Summit has no upstream neighbour; its own cell counts.
    assert np.ma.getmaskarray(twi)[peak]  # Symmetric summit has zero local gradient.
    valid = ~np.ma.getmaskarray(twi)
    assert valid.any()
    assert np.asarray(twi[valid]) == pytest.approx(np.log(np.asarray(area[valid]) / 10 / np.asarray(slope[valid])))
    assert result["field_summary"]["twi"]["mean"] is not None


def test_optional_dependency_error_is_actionable(terrain_fixture, monkeypatch):
    from agronomy_agent.geospatial import terrain
    original_import = terrain.importlib.import_module

    def unavailable(name):
        if name == "pyflwdir":
            raise ModuleNotFoundError("synthetic missing dependency")
        return original_import(name)

    monkeypatch.setattr(terrain.importlib, "import_module", unavailable)
    with pytest.raises(TerrainError, match="requirements-geospatial.txt"):
        _run(terrain_fixture)
    assert not terrain_fixture[-1].exists()


def test_valid_negative_elevation_is_not_an_implicit_nodata(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    _run(terrain_fixture, dem_path=make(np.full((15, 15), -9999.0)))
    with rio.open(output / "dem_unconditioned_m.tif") as dataset:
        array = dataset.read(1, masked=True)
        assert np.all(array.data == -9999)
        assert not np.ma.getmaskarray(array).any()
    assert not (output / "twi.tif").exists()


def test_cli_writes_bundle_then_refuses_clobber(terrain_fixture):
    np, rio, make, geometry, output = terrain_fixture
    root = Path(__file__).resolve().parents[1]
    geometry_path = output.parent / "field.json"
    geometry_path.write_text(json.dumps(geometry))
    metadata_path = output.parent / "source.json"
    metadata_path.write_text(json.dumps(METADATA))
    command = [sys.executable, str(root / "scripts" / "analyze_field_terrain.py"),
               "--dem", str(make()), "--geometry", str(geometry_path),
               "--source-metadata", str(metadata_path), "--output-dir", str(output),
               "--context-buffer-m", "40", "--include-twi"]
    first = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["status"] == "completed_model_context"
    manifest_hash = hashlib.sha256((output / "terrain.json").read_bytes()).hexdigest()
    again = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=60)
    assert again.returncode == 2
    assert json.loads(again.stderr)["status"] == "rejected"
    assert hashlib.sha256((output / "terrain.json").read_bytes()).hexdigest() == manifest_hash
