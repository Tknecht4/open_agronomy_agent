"""Synthetic driver round trips and adversarial intake policy checks."""
import hashlib
import io
import json
import sqlite3
import stat
import zipfile

import pytest

gpd = pytest.importorskip("geopandas")
pytest.importorskip("pyogrio")
from shapely.geometry import MultiPolygon, Polygon, Point, shape

from agronomy_agent.geospatial.vector_io import read_vector_upload
from agronomy_agent.server.services.geospatial_service import parse_boundary_upload


def _zip(directory, *, omit=(), extras=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path in sorted(directory.iterdir()):
            if path.suffix not in omit:
                archive.writestr("nested/" + path.name, path.read_bytes())
        for name, content in (extras or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def _geometry():
    return MultiPolygon([
        Polygon([(-113, 53), (-112.99, 53), (-112.99, 53.01), (-113, 53.01)],
                holes=[[(-112.998, 53.002), (-112.996, 53.002), (-112.996, 53.004), (-112.998, 53.004)]]),
        Polygon([(-112.98, 53), (-112.97, 53), (-112.97, 53.01), (-112.98, 53.01)]),
    ])


@pytest.mark.parametrize("format", ["shapefile", "gpkg"])
def test_projected_driver_roundtrip_preserves_members_hole_and_crs(tmp_path, format):
    original = _geometry()
    frame = gpd.GeoDataFrame({"name": ["Synthetic parcel"]}, geometry=[original], crs="EPSG:4326").to_crs(32612)
    if format == "shapefile":
        frame.to_file(tmp_path / "field.shp", engine="pyogrio")
        filename, raw = "field.zip", _zip(tmp_path)
    else:
        path = tmp_path / "field.gpkg"
        frame.to_file(path, engine="pyogrio", driver="GPKG")
        filename, raw = path.name, path.read_bytes()
    result = read_vector_upload(filename=filename, raw=raw)
    restored = shape(result["features"][0]["geometry"])
    assert len(restored.geoms) == 2
    assert sum(len(part.interiors) for part in restored.geoms) == 1
    assert restored.hausdorff_distance(original) < 1e-10
    assert result["coordinate_reference"]["reprojected"] is True
    assert result["coordinate_reference"]["sources"][0]["source_crs"] == "EPSG:32612"
    assert result["features"][0]["properties"]["name"] == "Synthetic parcel"
    with pytest.raises(ValueError, match="No components were dropped"):
        parse_boundary_upload(filename=filename, raw=raw, content_type=None)


def test_geopackage_reads_all_vector_layers_without_silent_selection(tmp_path):
    path = tmp_path / "fields.gpkg"
    for index in range(2):
        gpd.GeoDataFrame({"name": [f"field {index}"]}, geometry=[Point(-113 + index, 53)], crs=4326).to_file(path, layer=f"field_{index}", engine="pyogrio")
    result = read_vector_upload(filename=path.name, raw=path.read_bytes())
    assert {feature["source_layer"] for feature in result["features"]} == {"field_0", "field_1"}
    assert len(result["coordinate_reference"]["sources"]) == 2


def test_shapefile_missing_crs_and_standalone_shp_are_rejected(tmp_path):
    gpd.GeoDataFrame(geometry=[Point(-113, 53)], crs=4326).to_file(tmp_path / "field.shp", engine="pyogrio")
    with pytest.raises(ValueError, match=".prj"):
        read_vector_upload(filename="field.zip", raw=_zip(tmp_path, omit=(".prj",)))
    with pytest.raises(ValueError, match="standalone"):
        read_vector_upload(filename="field.shp", raw=(tmp_path / "field.shp").read_bytes())


def test_geopackage_undefined_crs_fails_even_for_plausible_lonlat(tmp_path):
    path = tmp_path / "field.gpkg"
    gpd.GeoDataFrame(geometry=[Point(-113, 53)], crs=4326).to_file(path, engine="pyogrio")
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE gpkg_geometry_columns SET srs_id=0")
        connection.execute("UPDATE gpkg_contents SET srs_id=0")
    with pytest.raises(ValueError, match="CRS"):
        read_vector_upload(filename=path.name, raw=path.read_bytes())


@pytest.mark.parametrize("name", ["../field.shp", "/field.shp", "nested\\field.shp"])
def test_archive_paths_are_rejected(name):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, b"not a shapefile")
    with pytest.raises(ValueError, match="unsafe"):
        read_vector_upload(filename="field.zip", raw=output.getvalue())


def test_archive_symlink_and_duplicate_dataset_fail_closed():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        link = zipfile.ZipInfo("field.shp")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/private/data")
    with pytest.raises(ValueError, match="unsafe"):
        read_vector_upload(filename="field.zip", raw=output.getvalue())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("one.shp", b"one")
        archive.writestr("two.shp", b"two")
    with pytest.raises(ValueError, match="exactly one"):
        read_vector_upload(filename="field.zip", raw=output.getvalue())


def test_geojson_is_rfc7946_no_crs_guess_or_partial_feature_drop():
    geometry = {"type": "Point", "coordinates": [-113, 53]}
    raw = json.dumps(geometry).encode()
    parsed = parse_boundary_upload(filename="point.geojson", raw=raw, content_type=None)
    assert parsed["import_receipt"]["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert parsed["import_receipt"]["source_bytes"] == len(raw)
    assert parsed["coordinate_reference"]["sources"][0]["crs_basis"] == "RFC7946"
    assert parsed["coordinate_reference"]["reprojected"] is False
    with pytest.raises(ValueError, match="CRS"):
        read_vector_upload(filename="point.geojson", raw=json.dumps({**geometry, "crs": {"name": "EPSG:3857"}}).encode())
    with pytest.raises(ValueError):
        read_vector_upload(filename="point.geojson", raw=json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": geometry}, {"type": "Feature", "geometry": None}
        ]}).encode())


def test_feature_and_expanded_archive_caps(monkeypatch):
    import agronomy_agent.geospatial.vector_io as vector
    monkeypatch.setattr(vector, "MAX_FEATURES", 1)
    raw = json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}}] * 2}).encode()
    with pytest.raises(ValueError, match="exceeds 1 features"):
        read_vector_upload(filename="points.geojson", raw=raw)
    monkeypatch.setattr(vector, "MAX_EXPANDED_BYTES", 2)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("field.shp", b"abc")
    with pytest.raises(ValueError, match="expanded size"):
        read_vector_upload(filename="field.zip", raw=output.getvalue())
