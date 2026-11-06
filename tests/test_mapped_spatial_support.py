"""Spatial support must survive producer→prompt→answer without changed meaning."""
import math

import pytest
from shapely.geometry import Point, shape

from agronomy_agent.server.services import chat_service as chat
from agronomy_agent.server.services import geospatial_service as geo
from agronomy_agent.server.services.answer_renderer import (
    _map_context_intersection_bits,
    render_map_component_explanation_answer,
)
from agronomy_agent.server.services.field_context_compiler import compile_field_context
from agronomy_agent.geospatial.context_support import mapped_coverage_label
from agronomy_agent.geographic_context import attach_trusted_geographic_context, format_trusted_geographic_context


REGION = {"type": "Polygon", "coordinates": [[[-100, 40], [-96, 40], [-96, 44], [-100, 44], [-100, 40]]]}
CONCAVE = {"type": "Polygon", "coordinates": [[[-100, 40], [-96, 40], [-96, 44], [-97, 44], [-97, 41], [-99, 41], [-99, 44], [-100, 44], [-100, 40]]]}
HOLED = {"type": "Polygon", "coordinates": [REGION["coordinates"][0], [[-99, 41], [-99, 43], [-97, 43], [-97, 41], [-99, 41]]]}
MULTI = {"type": "MultiPolygon", "coordinates": [CONCAVE["coordinates"], [[[-94, 40], [-93, 40], [-93, 41], [-94, 41], [-94, 40]]]]}


def intersection(geometry):
    return geo._intersection_record(
        feature={"type": "Feature", "geometry": REGION,
                 "properties": {"code": "TEST", "name": "Mapped test", "label": "Mapped test",
                                "source_scale_range": "1:100,000", "map_unit": "TEST",
                                "dominant_components": [{"soil_name": "Test mapped soil"}]}},
        layer=geo.REGION_LAYERS["ab_detailed_soil"], input_geometry=geometry,
    )


@pytest.mark.parametrize(("geometry", "support", "label"), [
    ({"type": "Point", "coordinates": [-99.5, 40.5]}, "point_membership", "point is covered by mapped polygon"),
    ({"type": "Point", "coordinates": [-101, 40.5]}, "point_membership", "point is outside mapped polygon"),
    (REGION, "polygon_area", "100% polygon area overlap"),
    (MULTI, "polygon_area", None),
])
def test_producer_support_is_preserved_through_both_prompts_and_answer(geometry, support, label):
    mapped = intersection(geometry)
    assert mapped["coverage_support_type"] == support
    field = {"geometry": geometry, "regional_intersections": [mapped]}
    safe = chat._safe_field_context_summary(field)
    compiled = compile_field_context(field, [], safe_field_summary=chat._safe_field_context_summary)
    record = compiled["receipt"]["map_context"][0]
    assert record["coverage_support_type"] == support
    assert record["coverage_method"] == mapped["coverage_method"]
    assert record["confidence_kind"] == "heuristic_not_calibrated"
    assert record["confidence"] == mapped["confidence"]
    prompts = [compiled["prompt"], chat._append_field_context_prompt("base", field)]
    for prompt in prompts:
        assert "source scale 1:100,000" in prompt
        assert "heuristic overlap score" in prompt and "not a calibrated probability" in prompt
        assert "% confidence" not in prompt and "% field coverage" not in prompt
        if label:
            assert label in prompt
    if label:
        assert label in _map_context_intersection_bits(safe)[0]
    answer = render_map_component_explanation_answer("What do the mapped soil components represent?", {"metadata": {"field_context": safe}})
    assert answer and "% of the selected boundary" not in answer
    if label:
        assert label in answer


def test_legacy_support_stays_unknown_and_unknown_calibration_is_not_probability():
    legacy = intersection(REGION)
    legacy.pop("coverage_support_type")
    legacy.pop("confidence_kind")
    field = {"regional_intersections": [legacy]}
    compiled = compile_field_context(field, [], safe_field_summary=chat._safe_field_context_summary)
    assert compiled["receipt"]["map_context"][0]["coverage_support_type"] == "unknown"
    for prompt in [compiled["prompt"], chat._append_field_context_prompt("base", field)]:
        assert "spatial support unknown; no area coverage inferred" in prompt
        assert "calibration unknown" in prompt
        assert "% confidence" not in prompt and "% polygon area overlap" not in prompt


def test_source_scale_label_alias_is_visible_in_both_prompts():
    mapped = intersection(REGION)
    mapped["source_scale_label"] = mapped.pop("source_scale_range")
    field = {"regional_intersections": [mapped]}
    compiled = compile_field_context(field, [], safe_field_summary=chat._safe_field_context_summary)
    assert "source scale 1:100,000" in compiled["prompt"]
    assert "source scale 1:100,000" in chat._append_field_context_prompt("base", field)


@pytest.mark.parametrize("geometry", [REGION, CONCAVE, HOLED, MULTI, {"type": "Point", "coordinates": [-100, 40]}])
def test_representative_lookup_uses_valid_complete_interior_geometry(geometry):
    lat, lon = chat._representative_lat_lon({"geometry": geometry, "representative_point": {"lat": 0, "lon": 0}})
    assert shape(geometry).covers(Point(lon, lat))
    assert (lat, lon) != (0, 0)
    if geometry == HOLED:
        assert not shape({"type": "Polygon", "coordinates": [HOLED["coordinates"][1]]}).contains(Point(lon, lat))


@pytest.mark.parametrize("geometry", [
    {}, {"type": "LineString", "coordinates": [[-100, 40], [-99, 41]]},
    {"type": "Point", "coordinates": [181, 40]}, {"type": "Point", "coordinates": [-100, 91]},
    {"type": "Point", "coordinates": [math.nan, 40]}, {"type": "Point", "coordinates": [True, 40]},
    {"type": "Point", "coordinates": ["-100", 40]},
    {"type": "Polygon", "coordinates": [[[-100, 40], [-96, 44], [-100, 44], [-96, 40], [-100, 40]]]},
    {"kind": "polygon", "points": [{"lon": -100, "lat": 40}, {"lon": -99, "lat": 40}, {"lon": -99, "lat": 41}, {"bad": 0}]},
])
def test_invalid_geometry_does_not_use_override_or_infer_a_location(geometry):
    assert chat._public_adapter_geometry(geometry) is None
    assert chat._representative_lat_lon({"geometry": geometry, "representative_point": {"lat": 40, "lon": -100}}) is None


@pytest.mark.parametrize("point", [{"lat": 91, "lon": -100}, {"lat": 40, "lon": math.inf}, {"lat": "40", "lon": -100}, {}])
def test_invalid_standalone_representative_is_unavailable(point):
    assert chat._representative_lat_lon({"representative_point": point}) is None


def test_valid_standalone_representative_and_ui_shape_are_supported():
    assert chat._representative_lat_lon({"representative_point": {"lat": 40, "lon": -100}}) == (40, -100)
    ui = {"kind": "polygon", "points": [{"lon": lon, "lat": lat} for lon, lat in CONCAVE["coordinates"][0][:-1]]}
    lat, lon = chat._representative_lat_lon({"geometry": ui})
    assert shape(CONCAVE).covers(Point(lon, lat))


@pytest.mark.parametrize("value", [math.nan, math.inf, -1, 2, True, "1", 10 ** 1000])
def test_invalid_coverage_does_not_claim_area(value):
    assert mapped_coverage_label({"coverage_support_type": "polygon_area", "coverage_estimate": value}) == "polygon area overlap unknown"


def test_invalid_geometry_blocks_spatial_provider_tasks_even_with_valid_override(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid support reached a live spatial provider")
    monkeypatch.setattr(chat, "_run_public_adapter_tasks", forbidden)
    records = chat._run_public_adapter_preflight("Explain field observations", {
        "enable_public_adapters": True, "country": "US", "jurisdiction": "Iowa",
        "geometry": {"type": "Point", "coordinates": [181, 40]},
        "representative_point": {"lat": 40, "lon": -100},
    }, network_mode="online")
    assert len(records) == 1 and records[0]["payload"]["status"] == "geometry_unavailable"
    assert records[0]["payload"]["external_request_attempted"] is False


@pytest.mark.parametrize("support", ["point_membership", "polygon_area", None])
def test_trusted_geography_preserves_support_without_changing_authority(support):
    field = {"regional_intersections": [{
        "layer_id": "ca_statcan_2021_provinces_territories", "code": "PR_48", "name": "Alberta",
        "source": "bundled_official_geospatial_layer", "binding_status": "server_recomputed_bundled_source",
        "coverage_estimate": 1, "coverage_support_type": support,
    }]}
    projected = attach_trusted_geographic_context(field, field_access_authorized=True, geo_context_binding_status="stored_field_snapshot")
    text = format_trusted_geographic_context(projected)
    assert "CONTEXT ONLY" in text and "not a surveyed field boundary" in text
    assert mapped_coverage_label(field["regional_intersections"][0]) in text
    assert "% mapped geometry coverage" not in text
