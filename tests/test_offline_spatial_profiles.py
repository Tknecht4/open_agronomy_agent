from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

from agronomy_agent.offline_readiness import _validate_external_spatial_pack


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_prairie_spatial_pack as pack  # noqa: E402
import offline_spatial_profiles as profiles  # noqa: E402
import setup_offline_data as setup  # noqa: E402
import validate_canada_geospatial_sources as source_validator  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry_source(*, source_id: str, layer_id: str, download_url: str) -> dict[str, Any]:
    return {
        "id": source_id,
        "title": f"Fixture source {source_id}",
        "publisher": "Fixture Government",
        "jurisdiction": ["Canada", "Fixture"],
        "canonical_url": f"https://example.invalid/catalogue/{source_id}",
        "catalogue_api_url": f"https://example.invalid/api/{source_id}",
        "download_url": download_url,
        "source_record_id": source_id,
        "format": "fixture_zip",
        "source_crs": "EPSG:4326",
        "source_scale": "fixture",
        "currency": "fixture",
        "license": {
            "identifier": "Open Government Licence - Canada",
            "permits_modification": True,
            "permits_commercial": True,
            "permits_redistribution": True,
            "reviewed_on": "2026-08-13",
            "attribution": "Fixture attribution",
        },
        "runtime": {
            "status": "candidate_local_profile",
            "raw_path": "legacy/raw/source.zip",
            "lineage_path": "legacy/raw/source.zip.lineage.json",
            "derived_path": "legacy/derived/layer.sqlite3",
            "derived_manifest_path": "legacy/derived/layer_manifest.json",
            "layer_id": layer_id,
            "query_backend": "local_sqlite_rtree",
        },
        "boundary": "Fixture mapped context only.",
    }


def _national_gate() -> dict[str, Any]:
    return {
        "required_provinces": [
            "British Columbia",
            "Alberta",
            "Saskatchewan",
            "Manitoba",
            "Ontario",
            "Quebec",
            "New Brunswick",
            "Nova Scotia",
            "Prince Edward Island",
            "Newfoundland and Labrador",
        ],
        "release_eligible": False,
        "status": "fixture",
        "candidate_national_prior": {"required_layers": ["fixture"], "promotion_gates": ["fixture"]},
    }


def _write_fixture_database(
    database: Path,
    *,
    source_id: str,
    raw_sha256: str,
    source_entry_sha256: str,
) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            CREATE TABLE features (
              fid INTEGER PRIMARY KEY,
              code TEXT NOT NULL,
              name TEXT NOT NULL,
              properties_json TEXT NOT NULL,
              geometry_json TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE feature_bounds USING rtree(fid, min_lon, max_lon, min_lat, max_lat);
            """
        )
        metadata = {
            "source_id": source_id,
            "source_sha256": raw_sha256,
            "source_entry_sha256": source_entry_sha256,
            "source_scale_range": "fixture",
            "output_crs": "EPSG:4326",
        }
        for key, value in metadata.items():
            connection.execute("INSERT INTO metadata VALUES (?, ?)", (key, json.dumps(value)))
        connection.execute(
            "INSERT INTO features VALUES (?, ?, ?, ?, ?)",
            (1, "fixture", "fixture", "{}", "{}"),
        )
        connection.execute("INSERT INTO feature_bounds VALUES (?, ?, ?, ?, ?)", (1, 0, 1, 0, 1))
        connection.commit()
    finally:
        connection.close()


def _write_fixture_profile_state(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    state_root = tmp_path / "state"
    registry_path = tmp_path / "registry.json"
    profile_path = tmp_path / "profiles.json"
    source_id = "fixture_dss"
    layer_id = "fixture_detailed_soil"
    download_url = "https://example.invalid/fixture.zip"
    source = _registry_source(source_id=source_id, layer_id=layer_id, download_url=download_url)
    missing_legacy = _registry_source(
        source_id="unrelated_legacy_bundled",
        layer_id="unrelated_layer",
        download_url="https://example.invalid/unrelated.zip",
    )
    missing_legacy["runtime"]["status"] = "candidate_not_bundled"
    registry = {
        "schema_version": source_validator.SCHEMA_VERSION,
        "national_soil_context_gate": _national_gate(),
        "sources": [source, missing_legacy],
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    raw_path = state_root / "raw/fixture/source.zip"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"fixture source bytes")
    raw_sha256 = _sha256(raw_path)
    source_entry_sha256 = profiles.canonical_json_sha256(source)
    profile = {
        "id": "fixture-dss-v1",
        "title": "Fixture DSS",
        "status": "approved_for_local_install",
        "source_registry_path": "registry.json",
        "pack": {
            "directory": "spatial-pack/fixture-dss-v1",
            "manifest": pack.PACK_MANIFEST_NAME,
            "install_receipt": "install_receipt.json",
            "minimum_free_bytes": 1,
        },
        "sources": [
            {
                "source_id": source_id,
                "layer_id": layer_id,
                "source_record_id": source_id,
                "download_url": download_url,
                "source_entry_sha256": source_entry_sha256,
                "expected_raw_bytes": raw_path.stat().st_size,
                "expected_raw_sha256": raw_sha256,
                "state_paths": {
                    "raw": "raw/fixture/source.zip",
                    "lineage": "raw/fixture/source.zip.lineage.json",
                    "derived": "derived/fixture.sqlite3",
                    "derived_manifest": "derived/fixture_manifest.json",
                },
            }
        ],
        "boundary": "Fixture mapped context only.",
    }
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": profiles.PROFILE_SCHEMA_VERSION,
                "profiles": [profile],
            }
        ),
        encoding="utf-8",
    )
    lineage_path = state_root / "raw/fixture/source.zip.lineage.json"
    lineage = {
        "schema_version": setup.LINEAGE_SCHEMA_VERSION,
        "source_id": source_id,
        "source_record_id": source_id,
        "download_url": download_url,
        "raw_path": "raw/fixture/source.zip",
        "raw_bytes": raw_path.stat().st_size,
        "raw_sha256": raw_sha256,
        "source_entry_sha256": source_entry_sha256,
        "support_files": [],
    }
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
    database = state_root / "derived/fixture.sqlite3"
    _write_fixture_database(
        database,
        source_id=source_id,
        raw_sha256=raw_sha256,
        source_entry_sha256=source_entry_sha256,
    )
    derived_manifest = {
        "source_id": source_id,
        "source_sha256": raw_sha256,
        "lineage_sha256": _sha256(lineage_path),
        "source_entry_sha256": source_entry_sha256,
        "output_bytes": database.stat().st_size,
        "output_sha256": _sha256(database),
        "feature_count": 1,
        "support_files": [],
    }
    (state_root / "derived/fixture_manifest.json").write_text(
        json.dumps(derived_manifest), encoding="utf-8"
    )
    return state_root, registry_path, profile_path, source_id


def test_prairie_profile_pins_exact_dss_sources_and_registry_entries() -> None:
    profile_path = ROOT / "data/manifests/offline_spatial_profiles_v1.json"
    registry_path = ROOT / "data/manifests/canada_geospatial_sources.json"
    profile = profiles.load_profile(profile_path, "prairie-dss-v1")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    assert profiles.source_ids(profile) == (
        "ca_aafc_ab_detailed_soil_survey",
        "ca_aafc_sk_detailed_soil_survey",
        "ca_aafc_mb_detailed_soil_survey",
    )
    assert profiles.validate_profile_registry_contract(profile, registry) == []
    assert profile["pack"]["minimum_free_bytes"] >= 1_000_000_000
    assert "ca_aafc_soil_erosion_risk_2021" in profile["deferred_layers"]


def test_default_geospatial_catalog_validation_does_not_claim_external_assets_are_bundled() -> None:
    registry_path = ROOT / "data/manifests/canada_geospatial_sources.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    assert all(source["runtime"]["status"] != "bundled" for source in registry["sources"])
    assert {
        source["runtime"]["status"] for source in registry["sources"]
    } <= source_validator.KNOWN_RUNTIME_STATUSES

    report = source_validator.validate(registry_path)
    assert report["status"] == "pass", report["errors"]
    assert report["bundled_source_count"] == 0
    assert set(report["candidate_source_ids"]) == {
        source["id"] for source in registry["sources"]
    }


def test_profile_scoped_validation_and_pack_ignore_unrelated_legacy_assets(tmp_path: Path) -> None:
    state_root, registry_path, profile_path, _ = _write_fixture_profile_state(tmp_path)

    source_validation = source_validator.validate(
        registry_path,
        root=state_root,
        profile_manifest_path=profile_path,
        profile_id="fixture-dss-v1",
    )

    assert source_validation["status"] == "pass", source_validation["errors"]
    assert source_validation["bundled_source_count"] == 1
    assert source_validation["profile"]["required_source_ids"] == ["fixture_dss"]

    destination = tmp_path / "pack"
    built = pack.build_pack(
        registry_path=registry_path,
        asset_root=state_root,
        destination=destination,
        profile_id="fixture-dss-v1",
        profile_manifest_path=profile_path,
        retain_raw=True,
    )

    assert built["validation"]["status"] == "pass"
    assert pack.validate_pack(
        destination,
        profile_id="fixture-dss-v1",
        profile_manifest_path=profile_path,
    )["status"] == "pass"
    receipt = json.loads((destination / "install_receipt.json").read_text(encoding="utf-8"))
    assert receipt["profile_id"] == "fixture-dss-v1"
    assert receipt["raw_retained"] is True
    assert {row["source_id"] for row in receipt["sources"]} == {"fixture_dss"}


def test_setup_dry_run_never_creates_the_selected_state_directory(tmp_path: Path) -> None:
    state_root = tmp_path / "offline-state"

    report = setup.run_setup(
        profile_id="prairie-dss-v1",
        data_root=state_root,
        download=True,
        build=True,
        verify=True,
        dry_run=True,
        retain_raw=True,
    )

    assert report["status"] == "planned"
    assert report["network_requested"] is True
    assert report["runtime_environment"]["AGRONOMY_AGENT_SPATIAL_PACK_ROOT"].endswith(
        "spatial-pack/prairie-dss-v1"
    )
    assert not state_root.exists()


def test_setup_dry_run_does_not_create_a_state_root_lock(tmp_path: Path) -> None:
    state_root, registry_path, profile_path, _ = _write_fixture_profile_state(tmp_path)
    lock_path = setup._state_root_lock_path(state_root)

    report = setup.run_setup(
        profile_id="fixture-dss-v1",
        data_root=state_root,
        download=False,
        build=False,
        verify=True,
        dry_run=True,
        retain_raw=True,
        registry_path=registry_path,
        profile_manifest_path=profile_path,
    )

    assert report["status"] == "planned"
    assert not lock_path.exists()


def test_setup_state_root_lock_rejects_another_installer_with_owner_diagnostics(tmp_path: Path) -> None:
    state_root, registry_path, profile_path, _ = _write_fixture_profile_state(tmp_path)
    lock = setup._StateRootLock(data_root=state_root, profile_id="fixture-dss-v1")
    lock.acquire()
    lock_path = setup._state_root_lock_path(state_root)
    try:
        assert lock_path.is_file()
        with pytest.raises(setup.StateRootLockError, match="already locked") as exc_info:
            setup.run_setup(
                profile_id="fixture-dss-v1",
                data_root=state_root,
                download=False,
                build=False,
                verify=False,
                dry_run=False,
                retain_raw=True,
                registry_path=registry_path,
                profile_manifest_path=profile_path,
            )
        message = str(exc_info.value)
        assert "pid=" in message
        assert "raw, derived, or pack assets" in message
    finally:
        lock.release()
    assert not lock_path.exists()


def test_setup_releases_state_root_lock_after_normal_and_error_paths(tmp_path: Path) -> None:
    state_root, registry_path, profile_path, _ = _write_fixture_profile_state(tmp_path)
    lock_path = setup._state_root_lock_path(state_root)

    normal = setup.run_setup(
        profile_id="fixture-dss-v1",
        data_root=state_root,
        download=False,
        build=False,
        verify=False,
        dry_run=False,
        retain_raw=True,
        registry_path=registry_path,
        profile_manifest_path=profile_path,
    )

    assert normal["status"] == "pass"
    assert normal["state_root_lock"]["scope"] == "raw_derived_pack"
    assert not lock_path.exists()

    with pytest.raises(FileNotFoundError, match="spatial pack manifest is missing"):
        setup.run_setup(
            profile_id="fixture-dss-v1",
            data_root=state_root,
            download=False,
            build=False,
            verify=True,
            dry_run=False,
            retain_raw=True,
            registry_path=registry_path,
            profile_manifest_path=profile_path,
        )
    assert not lock_path.exists()


def test_setup_refuses_a_state_root_inside_the_checkout() -> None:
    with pytest.raises(ValueError, match="outside the Git checkout"):
        setup.run_setup(
            profile_id="prairie-dss-v1",
            data_root=ROOT / "data" / "local-spatial-state",
            download=False,
            build=False,
            verify=False,
            dry_run=True,
            retain_raw=True,
        )


def test_existing_unpinned_raw_bytes_fail_before_any_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root, _, profile_path, source_id = _write_fixture_profile_state(tmp_path)
    profile = profiles.load_profile(profile_path, "fixture-dss-v1")
    profile_source = profiles.source_row(profile, source_id)
    raw_path = profiles.resolve_state_path(state_root, profile_source, "raw")
    raw_path.write_bytes(b"tampered")

    def unexpected_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network must not be reached when an existing raw asset fails its pin")

    monkeypatch.setattr(setup.urllib.request, "urlopen", unexpected_network)
    with pytest.raises(ValueError, match="raw byte count differs"):
        setup._download_source(profile_source=profile_source, data_root=state_root)


def test_offline_readiness_uses_the_profile_bound_external_pack_validator(tmp_path: Path) -> None:
    state_root, registry_path, profile_path, _ = _write_fixture_profile_state(tmp_path)
    destination = state_root / "spatial-pack/fixture-dss-v1"
    pack.build_pack(
        registry_path=registry_path,
        asset_root=state_root,
        destination=destination,
        profile_id="fixture-dss-v1",
        profile_manifest_path=profile_path,
        retain_raw=True,
    )

    report = _validate_external_spatial_pack(
        root=ROOT,
        pack_root=destination,
        profile_id="fixture-dss-v1",
        profile_manifest_path=profile_path,
    )

    assert report["status"] == "pass", report["errors"]
