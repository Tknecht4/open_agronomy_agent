from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from pathlib import Path

import build_canada_context_boundary_layer as builder
import offline_spatial_profiles as profiles


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_entry() -> dict[str, object]:
    source_id = "ca_aafc_terrestrial_ecoregions_v2_2"
    return {
        "id": source_id,
        "canonical_url": "https://example.invalid/ecoregions",
        "source_record_id": "fixture-ecoregions",
        "source_scale": "fixture regional classification",
        "boundary": "Fixture context only.",
        "runtime": {"layer_id": source_id},
    }


def _feature(*, coordinates: list[list[list[float]]]) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {
            "OBJECTID": 1,
            "ECOREGION_ID": 77,
            "ECOZONE_ID": 9,
            "ECOPROVINCE_ID": 9.2,
            "ECOREGION_NAME_EN": "Fixture Ecoregion",
            "ECOREGION_NAME_FR": "Écorégion de démonstration",
            "SHAPE_Length": 1.0,
            "SHAPE_Area": 1.0,
        },
        "geometry": {"type": "Polygon", "coordinates": coordinates},
    }


def test_context_boundary_builder_dissolves_and_exposes_only_hierarchy_fields(tmp_path: Path) -> None:
    source = tmp_path / "source.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _feature(coordinates=[[[-100.0, 50.0], [-99.9, 50.0], [-99.9, 50.1], [-100.0, 50.1], [-100.0, 50.0]]]),
                    _feature(coordinates=[[[-99.8, 50.0], [-99.7, 50.0], [-99.7, 50.1], [-99.8, 50.1], [-99.8, 50.0]]]),
                ],
            }
        ),
        encoding="utf-8",
    )
    entry = _source_entry()
    lineage = tmp_path / "source.geojson.lineage.json"
    lineage.write_text(
        json.dumps(
            {
                "source_id": entry["id"],
                "raw_sha256": _sha256(source),
                "source_entry_sha256": profiles.canonical_json_sha256(entry),
                "license_snapshot": {"attribution": "Fixture attribution"},
            }
        ),
        encoding="utf-8",
    )
    database = tmp_path / "ecoregions.sqlite3"
    manifest = tmp_path / "ecoregions_manifest.json"

    report = builder.build_layer(
        source_id=str(entry["id"]),
        source_entry=entry,
        source=source,
        lineage_path=lineage,
        output=database,
        manifest_path=manifest,
        asset_root=tmp_path,
    )

    assert report["source_feature_count"] == 2
    assert report["feature_count"] == 1
    assert report["model_visible_fields"] == ["ecoregion_id", "ecoregion", "ecozone_id", "ecoprovince_id"]
    stored_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    assert stored_manifest["source_sha256"] == _sha256(source)
    assert stored_manifest["output_sha256"] == _sha256(database)

    connection = sqlite3.connect(database)
    try:
        feature_count = connection.execute("SELECT COUNT(*) FROM features").fetchone()[0]
        rtree_count = connection.execute("SELECT COUNT(*) FROM feature_bounds").fetchone()[0]
        code, name, properties_zlib = connection.execute(
            "SELECT code, name, properties_zlib FROM features"
        ).fetchone()
        metadata = {
            key: json.loads(value)
            for key, value in connection.execute("SELECT key, value_json FROM metadata")
        }
    finally:
        connection.close()

    assert feature_count == rtree_count == 1
    assert (code, name) == ("ECOREGION_77", "Fixture Ecoregion")
    assert json.loads(zlib.decompress(properties_zlib)) == {
        "ecoprovince_id": 9.2,
        "ecoregion": "Fixture Ecoregion",
        "ecoregion_id": "77",
        "ecozone_id": "9",
    }
    assert metadata["model_visible_fields"] == report["model_visible_fields"]
    assert metadata["distribution_role"] == "context_only_geographic_organization"


def test_context_boundary_profile_pins_the_three_inspected_source_bytes() -> None:
    profile_manifest = ROOT / "data/manifests/offline_spatial_profiles_v1.json"
    source_registry = json.loads((ROOT / "data/manifests/canada_geospatial_sources.json").read_text(encoding="utf-8"))
    profile = profiles.load_profile(profile_manifest, "canada-context-boundaries-v1")

    assert profiles.source_ids(profile) == (
        "ca_statcan_2021_provinces_territories",
        "ca_statcan_2021_census_agricultural_regions",
        "ca_aafc_terrestrial_ecoregions_v2_2",
    )
    assert profiles.validate_profile_registry_contract(profile, source_registry) == []
    assert profile["pack"]["estimated_raw_bytes"] == 22_968_231
    source_by_id = {source["id"]: source for source in source_registry["sources"]}
    assert source_by_id["ca_statcan_2021_provinces_territories"]["license"]["identifier"] == "Statistics Canada Open Licence"
    assert source_by_id["ca_statcan_2021_census_agricultural_regions"]["license"]["identifier"] == "Statistics Canada Open Licence"
    assert source_by_id["ca_aafc_terrestrial_ecoregions_v2_2"]["license"]["identifier"] == "Open Government Licence - Canada"
