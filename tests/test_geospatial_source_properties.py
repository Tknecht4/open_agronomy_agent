"""Source metadata remains typed, bounded and distinct from current crop."""
import hashlib
import json

import pytest

from agronomy_agent.geospatial import json_properties as props
from agronomy_agent.geospatial.vector_io import _property, read_vector_upload
from agronomy_agent.server.services.geospatial_service import parse_boundary_upload


def _upload(properties):
    return json.dumps({"type": "Feature", "geometry": {
        "type": "Point", "coordinates": [-112.0, 49.5]},
        "properties": properties}).encode()


def test_typed_source_cells_and_import_identity_survive_boundary_intake():
    source = {
        "year_list": [1980, 2005, 2021], "Crop22": "Barley",
        "crop": None, "irrigation": None, "active": False,
        "details": {"trial": [None, {"year": 2021, "rate": 0.0}], "source": "historical"},
    }
    raw = _upload(source)
    direct = read_vector_upload(filename="field.geojson", raw=raw)
    parsed = parse_boundary_upload(filename="field.geojson", raw=raw, content_type=None)
    assert direct["features"][0]["properties"] == source
    properties = parsed["feature_collection"]["features"][0]["properties"]
    for key, value in source.items():
        assert properties[key] == value
    assert parsed["feature_summaries"][0]["properties"] == properties
    assert properties["crop"] is None and properties["Crop22"] == "Barley"
    assert parsed["import_receipt"]["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert json.loads(json.dumps(parsed, allow_nan=False))["feature_collection"]["features"][0]["properties"] == properties


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_geojson_properties_fail_instead_of_becoming_unknown_or_strings(bad):
    with pytest.raises(ValueError, match="finite JSON numbers"):
        parse_boundary_upload(filename="field.geojson", raw=_upload({"rate": [None, bad]}), content_type=None)


def test_depth_node_string_and_total_property_budgets_refuse_whole_feature():
    nested = None
    for _ in range(props.MAX_PROPERTY_DEPTH + 1):
        nested = [nested]
    cases = [
        ({"nested": nested}, "nesting depth"),
        ({"many": [None] * props.MAX_PROPERTY_NODES}, "JSON values"),
        ({"text": "é" * props.MAX_PROPERTY_STRING_BYTES}, "UTF-8 bytes"),
        ({str(index): "x" * props.MAX_PROPERTY_STRING_BYTES for index in range(5)}, "encoded JSON bytes"),
    ]
    for properties, reason in cases:
        with pytest.raises(ValueError, match=reason):
            parse_boundary_upload(filename="field.geojson", raw=_upload(properties), content_type=None)


def test_driver_missing_cells_and_array_scalars_keep_types_without_repr():
    np = pytest.importorskip("numpy")
    assert _property(np.array([2021, 2022], dtype="int32")) == [2021, 2022]
    assert _property({"years": [np.int64(2022), None], "missing": float("nan")}) == {"years": [2022, None], "missing": None}
    with pytest.raises(ValueError, match="finite JSON numbers"):
        _property(float("inf"))
    with pytest.raises(ValueError, match="unsupported bytes"):
        _property(b"historical metadata")


def test_nonstring_keys_and_unknown_objects_are_not_stringified():
    with pytest.raises(ValueError, match="keys must be strings"):
        props.bounded_json_properties({1: "one"})
    with pytest.raises(ValueError, match="unsupported object"):
        props.bounded_json_properties({"source": object()})


def test_original_feature_id_is_distinct_from_upload_selection_id_and_position():
    feature = json.loads(_upload({"year_list": [2021], "upload_source_feature_id": "spoofed"}))
    feature["id"] = "publisher-field-42"
    raw = json.dumps(feature).encode()
    imported = read_vector_upload(filename="field.geojson", raw=raw)
    assert imported["features"][0]["source_feature_id"] == "publisher-field-42"
    assert imported["features"][0]["source_feature_index"] == 0
    parsed = parse_boundary_upload(filename="field.geojson", raw=raw, content_type=None)
    selected = parsed["feature_collection"]["features"][0]
    assert selected["id"] == "geojson:0"
    assert selected["properties"]["upload_source_feature_id"] == "publisher-field-42"
    assert selected["properties"]["upload_source_feature_index"] == 0
    assert selected["properties"]["upload_source_layer"] == "geojson"
    del feature["id"]
    unknown = parse_boundary_upload(filename="field.geojson", raw=json.dumps(feature).encode(), content_type=None)
    assert unknown["feature_collection"]["features"][0]["properties"]["upload_source_feature_id"] is None


@pytest.mark.parametrize("bad", [True, [], {}])
def test_original_feature_ids_reject_non_identifier_types(bad):
    feature = json.loads(_upload({}))
    feature["id"] = bad
    with pytest.raises(ValueError, match="id must be a string or finite number"):
        read_vector_upload(filename="field.geojson", raw=json.dumps(feature).encode())


@pytest.mark.parametrize("bad", [False, [], ""])
def test_falsy_non_object_properties_are_not_silently_dropped(bad):
    feature = json.loads(_upload({}))
    feature["properties"] = bad
    with pytest.raises(ValueError, match="properties must be an object"):
        read_vector_upload(filename="field.geojson", raw=json.dumps(feature).encode())
