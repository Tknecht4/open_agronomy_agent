"""Shared geometry regression contracts; all inputs are synthetic."""
import math

import pytest
from shapely.geometry import Point, Polygon, shape
from pyproj import Geod

from agronomy_agent.geospatial.geometry import canonical_geometry, geodesic_metrics, geometries_intersect, project_geometry


def polygon(x=0, y=0, width=1):
    return {"type": "Polygon", "coordinates": [[[x, y], [x+width, y], [x+width, y+width], [x, y+width], [x, y]]]}


def test_holes_and_all_multipart_members_survive_and_are_measured():
    first = polygon()
    hole = polygon(.2, .2, .2)["coordinates"][0]
    first["coordinates"].append(hole)  # Same winding deliberately supplied.
    second = polygon(2)
    value = {"type": "MultiPolygon", "coordinates": [first["coordinates"], second["coordinates"]]}
    parsed = canonical_geometry(value)
    assert parsed == value
    metrics = geodesic_metrics(parsed)
    expected = geodesic_metrics(polygon())["area_m2"] - geodesic_metrics(polygon(.2, .2, .2))["area_m2"] + geodesic_metrics(second)["area_m2"]
    assert metrics["area_m2"] == pytest.approx(expected)
    assert shape(parsed).covers(Point(metrics["representative_point"]["longitude"], metrics["representative_point"]["latitude"]))
    assert metrics["perimeter_m"] == pytest.approx(Geod(ellps="WGS84").geometry_length(shape(value).boundary))


@pytest.mark.parametrize("value", [
    {"type": "Point", "coordinates": [True, 1]},
    {"type": "Point", "coordinates": ["1", 1]},
    {"type": "Point", "coordinates": [math.nan, 1]},
    {"type": "Point", "coordinates": [181, 1]},
    {"type": "Point", "coordinates": [0, 0, math.inf]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]},
    {"type": "Polygon", "coordinates": [polygon()["coordinates"][0], polygon(2)["coordinates"][0]]},
    {"type": "MultiPolygon", "coordinates": [polygon()["coordinates"], polygon(.5)["coordinates"]]},
    {"type": "Polygon", "coordinates": [[[179, 0], [-179, 0], [-179, 1], [179, 1], [179, 0]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
])
def test_invalid_coordinates_and_topology_fail_closed(value):
    with pytest.raises(ValueError):
        canonical_geometry(value)


def test_limits_and_crs_are_explicit():
    with pytest.raises(ValueError, match="exceeds"):
        canonical_geometry(polygon(), max_vertices=4)
    with pytest.raises(ValueError, match="CRS"):
        canonical_geometry({**polygon(), "crs": {"type": "name", "properties": {"name": "EPSG:3857"}}})
    with pytest.raises(ValueError, match="type"):
        canonical_geometry({"type": "Point", "coordinates": [0, 0]}, allowed_types=("Polygon",))


def test_projection_roundtrip_and_point_metrics():
    original = {"type": "Point", "coordinates": [-113, 53]}
    projected = project_geometry(original, "EPSG:32612")
    assert projected.x == pytest.approx(365786.7509, abs=.01)
    restored = project_geometry(projected, "EPSG:4326", source_crs="EPSG:32612")
    assert restored.x == pytest.approx(-113)
    assert restored.y == pytest.approx(53)
    assert geodesic_metrics(original) == {"area_m2": 0, "perimeter_m": 0, "representative_point": {"longitude": -113, "latitude": 53}}


def test_intersection_respects_holes_and_includes_boundary():
    value = polygon()
    value["coordinates"].append(polygon(.2, .2, .2)["coordinates"][0])
    assert not geometries_intersect(value, {"type": "Point", "coordinates": [.3, .3]})
    assert geometries_intersect(value, {"type": "Point", "coordinates": [.2, .3]})
    assert geometries_intersect(value, {"type": "Point", "coordinates": [0, .3]})


def test_context_adapter_sampling_uses_interior_point_and_respects_holes():
    from agronomy_agent.local_tools import _sample_geojson_geometry
    # Its envelope centre and mean vertices fall in the hole. A one-point query
    # must still sample the polygon, rather than silently sampling neighboring land.
    value = polygon(0, 0, 4)
    value["coordinates"].append(polygon(.5, .5, 3)["coordinates"][0])
    for limit in (1, 5, 16):
        _, _, _, points = _sample_geojson_geometry(value, max_points=limit)
        assert points and len(points) <= limit
        assert all(shape(value).covers(Point(point)) for point in points)


def test_context_adapter_sampling_rejects_self_intersections():
    from agronomy_agent.local_tools import _sample_geojson_geometry
    with pytest.raises(ValueError, match="invalid"):
        _sample_geojson_geometry({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]})


def test_projection_cannot_enable_implicit_grid_downloads(monkeypatch):
    from pyproj import network
    monkeypatch.setattr(network, "is_network_enabled", lambda: True)
    with pytest.raises(ValueError, match="network access"):
        project_geometry({"type": "Point", "coordinates": [-113, 53]}, "EPSG:32612")


def test_supported_serving_installations_include_vector_drivers():
    # The developer environment can have optional preparation packages installed
    # even when a clean deployment would break the advertised ZIP/GPKG importer.
    import tomllib
    from pathlib import Path
    from packaging.requirements import Requirement

    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    required = {"geopandas", "pyogrio", "shapely", "pyproj"}
    assert required <= {Requirement(value).name for value in project["project"]["dependencies"]}
    for filename in ("requirements.txt", "requirements-container.txt"):
        lines = (root / filename).read_text().splitlines()
        assert required <= {Requirement(line).name for line in lines if line.strip() and not line.startswith("#")}
    # Native app installs the serving list, with existing observed wheel pins.
    assert "-r requirements-container.txt" in (root / "requirements-macos-app-runtime.txt").read_text().splitlines()
