from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import sys
import zipfile
import zlib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_statcan_tillage_seeding_context_snapshot as snapshot  # noqa: E402


def _write_boundary_layer(
    path: Path,
    *,
    source_id: str,
    features: list[tuple[str, dict[str, str]]],
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            CREATE TABLE features (code TEXT NOT NULL, properties_zlib BLOB NOT NULL);
            """
        )
        metadata = {
            "schema_version": snapshot.BOUNDARY_LAYER_SCHEMA_VERSION,
            "source_id": source_id,
            "feature_payload_encoding": "zlib_json_v1",
        }
        for key, value in metadata.items():
            connection.execute("INSERT INTO metadata VALUES (?, ?)", (key, json.dumps(value)))
        for code, properties in features:
            connection.execute(
                "INSERT INTO features VALUES (?, ?)",
                (code, sqlite3.Binary(zlib.compress(json.dumps(properties, sort_keys=True).encode("utf-8")))),
            )
        connection.commit()
    finally:
        connection.close()


def _row(
    *,
    geography: str,
    dguid: str,
    practice: str,
    unit: str,
    vector: int,
    value: str,
    status: str,
) -> dict[str, str]:
    return {
        "REF_DATE": "2021",
        "GEO": geography,
        "DGUID": dguid,
        "Tillage practices": practice,
        "Unit of measure": unit,
        "UOM": "Number",
        "UOM_ID": "223",
        "SCALAR_FACTOR": "units",
        "SCALAR_ID": "0",
        "VECTOR": f"v{vector}",
        "COORDINATE": f"1.{vector}",
        "VALUE": value,
        "STATUS": status,
        "SYMBOL": "",
        "TERMINATED": "",
        "DECIMALS": "0",
    }


def _write_source_archive(path: Path) -> str:
    rows: list[dict[str, str]] = []
    vector = 1
    for geography, dguid in (
        ("Alberta [PR480000000]", "2021A000248"),
        ("Census Agricultural Region 1, Alberta [CAR481000000]", "2021S05014810"),
    ):
        for practice in snapshot.PRACTICES:
            for unit in snapshot.UNITS:
                blank = geography.startswith("Alberta") and practice == snapshot.PRACTICES[0] and unit == "Acres"
                rows.append(
                    _row(
                        geography=geography,
                        dguid=dguid,
                        practice=practice,
                        unit=unit,
                        vector=vector,
                        value="" if blank else str(vector * 10),
                        status="F" if blank else "A",
                    )
                )
                vector += 1
    rows.append(
        _row(
            geography="Division No. 1, Alberta [CD480100000]",
            dguid="2021A00034801",
            practice=snapshot.PRACTICES[0],
            unit=snapshot.UNITS[0],
            vector=vector,
            value="123",
            status="B",
        )
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=snapshot.REQUIRED_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(snapshot.RAW_CSV_MEMBER, buffer.getvalue().encode("utf-8-sig"))
        archive.writestr(snapshot.RAW_METADATA_MEMBER, b'"fixture","metadata"\n')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _layers(tmp_path: Path, *, car_uid: str = "4810") -> tuple[Path, Path]:
    province = tmp_path / "province.sqlite3"
    car = tmp_path / "car.sqlite3"
    _write_boundary_layer(
        province,
        source_id="ca_statcan_2021_provinces_territories",
        features=[
            (
                "PR_48",
                {
                    "province_uid": "48",
                    "dissemination_geography_id": "2021A000248",
                },
            )
        ],
    )
    _write_boundary_layer(
        car,
        source_id="ca_statcan_2021_census_agricultural_regions",
        features=[
            (
                f"CAR_{car_uid}",
                {
                    "province_uid": "48",
                    "census_agricultural_region_code": car_uid,
                    "dissemination_geography_id": f"2021S0501{car_uid}",
                },
            )
        ],
    )
    return province, car


def test_builds_exact_pr_car_snapshot_and_preserves_blank_status(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    expected_sha256 = _write_source_archive(source)
    province, car = _layers(tmp_path)
    output = tmp_path / "tillage.sqlite3"
    manifest = tmp_path / "tillage_manifest.json"

    report = snapshot.build_snapshot(
        source=source,
        province_boundary_layer=province,
        car_boundary_layer=car,
        output=output,
        manifest=manifest,
        expected_raw_sha256=expected_sha256,
        strict_release=False,
    )

    assert report["validation"]["status"] == "pass"
    assert report["geography_count"] == 2
    assert report["observation_count"] == 24
    assert snapshot.validate_snapshot(
        output,
        province_boundary_layer=province,
        car_boundary_layer=car,
        expected_raw_sha256=expected_sha256,
        strict_release=False,
    )["status"] == "pass"
    connection = sqlite3.connect(output)
    try:
        geography = connection.execute(
            "SELECT geography_dguid, published_geography_code, boundary_feature_code, context_role "
            "FROM geographies WHERE geography_dguid = ?",
            ("2021S05014810",),
        ).fetchone()
        blank = connection.execute(
            "SELECT source_value_text, value_present, value_status, symbol, context_role "
            "FROM observations WHERE geography_dguid = ? AND tillage_practice = ? AND unit_of_measure = ?",
            ("2021A000248", snapshot.PRACTICES[0], "Acres"),
        ).fetchone()
    finally:
        connection.close()
    assert geography == (
        "2021S05014810",
        "CAR481000000",
        "CAR_4810",
        snapshot.CONTEXT_ROLE,
    )
    assert blank == (None, 0, "F", "", snapshot.CONTEXT_ROLE)
    receipt = json.loads(manifest.read_text(encoding="utf-8"))
    assert receipt["source"]["raw_sha256"] == expected_sha256
    assert receipt["context_role"] == snapshot.CONTEXT_ROLE
    assert receipt["key_contract"] == snapshot.KEY_CONTRACT


def test_fails_closed_when_census_agricultural_region_dguid_does_not_match(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    expected_sha256 = _write_source_archive(source)
    province, car = _layers(tmp_path, car_uid="4820")
    output = tmp_path / "tillage.sqlite3"
    manifest = tmp_path / "tillage_manifest.json"

    with pytest.raises(ValueError, match="no exact installed 2021 boundary match"):
        snapshot.build_snapshot(
            source=source,
            province_boundary_layer=province,
            car_boundary_layer=car,
            output=output,
            manifest=manifest,
            expected_raw_sha256=expected_sha256,
            strict_release=False,
        )

    assert not output.exists()
    assert not manifest.exists()


def test_rejects_noncanonical_published_car_code_before_any_output(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    expected_sha256 = _write_source_archive(source)
    province, car = _layers(tmp_path)
    with zipfile.ZipFile(source, "r") as archive:
        csv_bytes = archive.read(snapshot.RAW_CSV_MEMBER)
        metadata_bytes = archive.read(snapshot.RAW_METADATA_MEMBER)
    changed = csv_bytes.replace(b"CAR481000000", b"CAR481000001", 1)
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(snapshot.RAW_CSV_MEMBER, changed)
        archive.writestr(snapshot.RAW_METADATA_MEMBER, metadata_bytes)
    expected_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="CAR publication code is not canonical"):
        snapshot.build_snapshot(
            source=source,
            province_boundary_layer=province,
            car_boundary_layer=car,
            output=tmp_path / "tillage.sqlite3",
            manifest=tmp_path / "tillage_manifest.json",
            expected_raw_sha256=expected_sha256,
            strict_release=False,
        )
