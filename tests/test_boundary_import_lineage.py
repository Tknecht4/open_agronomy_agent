"""Import metadata is typed context, and geometry edits do not renew its binding."""
from copy import deepcopy

import pytest

from agronomy_agent.geospatial.json_properties import MAX_PROPERTY_DEPTH
from agronomy_agent.server.services.boundary_import_lineage import (
    BOUNDARY_IMPORT_UNSET,
    geometry_sha256,
    normalize_boundary_import,
)


def geometry():
    return {"kind": "point", "point": {"lon": -111.0, "lat": 49.0}}


def snapshot():
    return {
        "import_receipt": {"schema_version": "open_agronomy_agent.vector_import.v1", "source_sha256": "a" * 64, "source_bytes": 1234},
        "coordinate_reference": {"target_crs": "EPSG:4326", "label": "WGS84 longitude/latitude", "reprojected": False,
            "sources": [{"layer": "geojson", "source_crs": "EPSG:4326", "crs_basis": "RFC7946", "target_crs": "EPSG:4326", "reprojected": False}]},
        "selected_feature": {"id": "geojson:0", "source_layer": "geojson", "source_feature_index": 0,
            "source_feature_id": "native-17", "properties": {"year_list": [1980, 2022], "Crop22": "Barley", "crop": None, "management": {"rate": None, "active": False}}},
    }


def test_source_snapshot_preserves_unknown_and_historical_types_without_authority():
    original = snapshot()
    normalized = normalize_boundary_import(original, geometry=geometry())
    assert normalized["selected_feature"] == original["selected_feature"]
    assert normalized["import_receipt"] == original["import_receipt"]
    assert normalized["coordinate_reference"] == original["coordinate_reference"]
    assert normalized["geometry_sha256"] == geometry_sha256(geometry())
    assert normalized["current_geometry_sha256"] == normalized["geometry_sha256"]
    assert normalized["binding_status"] == "client_snapshot_context_only"
    assert normalized["validity"] == "bound"
    assert normalized["source_attested"] is False
    assert normalized["authority"] == "context_only"
    assert normalized["not_field_measurement"] is True
    assert normalized["not_current_crop_authority"] is True
    assert normalized["not_training_data"] is True
    normalized["selected_feature"]["properties"]["year_list"].append(2023)
    assert original["selected_feature"]["properties"]["year_list"] == [1980, 2022]


def test_metadata_edits_preserve_binding_and_geometry_edits_supersede_without_reactivation():
    initial = normalize_boundary_import(snapshot(), geometry=geometry())
    assert normalize_boundary_import(geometry={**geometry(), "acres": 160}, previous_lineage=initial) == initial
    replacement = geometry()
    replacement["point"]["lon"] = -112.0
    changed = normalize_boundary_import(geometry=replacement, previous_lineage=initial)
    assert changed["geometry_sha256"] == initial["geometry_sha256"]
    assert changed["current_geometry_sha256"] != initial["geometry_sha256"]
    assert changed["import_receipt"] == initial["import_receipt"]
    assert changed["selected_feature"] == initial["selected_feature"]
    assert changed["validity"] == "superseded"
    assert changed["binding_status"] == "superseded_geometry_edit"
    reverted = normalize_boundary_import(geometry=geometry(), previous_lineage=changed)
    assert reverted["validity"] == "superseded"
    unknown = normalize_boundary_import(geometry={"kind": "none"}, previous_lineage=initial)
    assert unknown["validity"] == "superseded"
    assert normalize_boundary_import(None, geometry=geometry(), previous_lineage=initial) is None
    assert normalize_boundary_import(BOUNDARY_IMPORT_UNSET, geometry=geometry()) is None


@pytest.mark.parametrize("bad", [True, 0, -1, 26 * 1024 * 1024, 1.25, "1234"])
def test_source_byte_count_cannot_be_unknown_outside_limit_or_coerced(bad):
    value = snapshot()
    value["import_receipt"]["source_bytes"] = bad
    with pytest.raises(ValueError, match="source_bytes"):
        normalize_boundary_import(value, geometry=geometry())


@pytest.mark.parametrize("path,bad", [
    (("import_receipt", "source_sha256"), "not-a-digest"),
    (("import_receipt", "schema_version"), "server-attested.v1"),
    (("selected_feature", "source_feature_index"), True),
    (("selected_feature", "source_feature_index"), 250),
    (("selected_feature", "source_feature_id"), float("nan")),
    (("selected_feature", "source_feature_id"), True),
    (("selected_feature", "source_layer"), "missing-layer"),
    (("coordinate_reference", "reprojected"), "false"),
    (("coordinate_reference", "reprojected"), True),
    (("coordinate_reference", "target_crs"), "EPSG:32100"),
])
def test_invalid_identity_and_crs_envelopes_fail_closed(path, bad):
    value = snapshot()
    value[path[0]][path[1]] = bad
    with pytest.raises(ValueError, match="boundaryImport"):
        normalize_boundary_import(value, geometry=geometry())


def test_unknown_authority_flags_nested_payload_and_nonfinite_properties_are_rejected():
    for path, bad in [((), {"authority": "field_truth"}), (("selected_feature",), {"measurement": True}), (("import_receipt",), {"source_attested": True})]:
        value = snapshot()
        target = value if not path else value[path[0]]
        target.update(bad)
        with pytest.raises(ValueError, match="unsupported fields"):
            normalize_boundary_import(value, geometry=geometry())
    value = snapshot()
    value["selected_feature"]["properties"]["rate"] = float("inf")
    with pytest.raises(ValueError, match="finite JSON numbers"):
        normalize_boundary_import(value, geometry=geometry())
    nested = None
    for _ in range(MAX_PROPERTY_DEPTH + 1):
        nested = [nested]
    value["selected_feature"]["properties"] = {"nested": nested}
    with pytest.raises(ValueError, match="nesting depth"):
        normalize_boundary_import(value, geometry=geometry())
    with pytest.raises(ValueError, match="unknown field location"):
        normalize_boundary_import(snapshot(), geometry={"kind": "none"})


def test_crs_receipt_native_feature_id_and_whole_lineage_budget():
    value = snapshot()
    value["coordinate_reference"]["reprojected"] = True
    value["coordinate_reference"]["sources"][0].update({"source_crs": "EPSG:32100", "crs_basis": "declared_dataset_metadata", "source_crs_wkt": "a declared WKT", "transform_policy": "PyProj always_xy; no ballpark; best available operation required", "reprojected": True})
    value["selected_feature"]["source_feature_id"] = 955
    normalized = normalize_boundary_import(value, geometry=geometry())
    assert normalized["selected_feature"]["source_feature_id"] == 955
    assert normalized["coordinate_reference"] == value["coordinate_reference"]
    oversized = deepcopy(value)
    oversized["coordinate_reference"]["sources"] *= 10
    for source in oversized["coordinate_reference"]["sources"]:
        source["source_crs_wkt"] = "x" * 16_384
    with pytest.raises(ValueError, match="encoded JSON bytes"):
        normalize_boundary_import(oversized, geometry=geometry())


def test_valid_empty_native_id_and_deep_typed_properties_remain_lossless():
    value = snapshot()
    value["selected_feature"]["source_feature_id"] = ""
    nested = None
    for _ in range(MAX_PROPERTY_DEPTH - 1):
        nested = [nested]
    value["selected_feature"]["properties"] = {"deep": nested}
    normalized = normalize_boundary_import(value, geometry=geometry())
    assert normalized["selected_feature"] == value["selected_feature"]


@pytest.mark.parametrize("property_key,bad", [("upload_source_layer", "other"), ("upload_source_feature_index", 17), ("upload_source_feature_index", False), ("upload_source_feature_id", "other")])
def test_duplicate_feature_identity_fields_cannot_contradict_upload_properties(property_key, bad):
    value = snapshot()
    value["selected_feature"]["properties"][property_key] = bad
    with pytest.raises(ValueError, match="disagrees with upload properties"):
        normalize_boundary_import(value, geometry=geometry())
