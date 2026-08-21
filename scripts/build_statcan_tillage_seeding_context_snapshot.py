#!/usr/bin/env python3
"""Build and verify a compact, boundary-keyed Statistics Canada context snapshot.

This is intentionally *not* a RAG ingestion path.  It derives a local SQLite
table from Statistics Canada table 32-10-0367-01 only after every included
province or Census Agricultural Region (CAR) has an exact 2021 DGUID match in
the separately installed Statistics Canada boundary layers.  The result is a
historical, aggregate regional-context table.  It must not be used as a field
observation, farm record, practice claim, diagnosis, prescription, or training
example.

Raw Statistics Canada bytes are read in place and never copied into the Git
checkout or the derived SQLite database.  The default command is pinned to the
official 2021 archive inspected for this candidate; a changed archive fails
closed until it is reviewed and its contract is deliberately updated.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import zipfile
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "open_agronomy_agent.statcan_tillage_seeding_context_snapshot.v1"
BOUNDARY_LAYER_SCHEMA_VERSION = "open_agronomy_agent.canada_context_boundary_layer.v1"
SOURCE_ID = "ca_statcan_2021_tillage_seeding_practices"
SOURCE_TITLE = "Tillage and seeding practices, Census of Agriculture, 2021"
SOURCE_TABLE_ID = "32-10-0367-01"
SOURCE_URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210036701"
SOURCE_DOWNLOAD_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/32100367-eng.zip"
SOURCE_LICENSE = "Statistics Canada Open Licence"
SOURCE_ATTRIBUTION = (
    "Adapted from Statistics Canada, Tillage and seeding practices, Census of Agriculture, 2021. "
    "This does not constitute an endorsement by Statistics Canada of this product."
)
RAW_CSV_MEMBER = "32100367.csv"
RAW_METADATA_MEMBER = "32100367_MetaData.csv"
EXPECTED_RAW_SHA256 = "0fe0a2f9d3dcd02fa68ef2207da8932b5a3f631c29a624f8f1f8593bf0f2d216"
EXPECTED_RAW_BYTES = 383_321
EXPECTED_CSV_SHA256 = "14c842e5765d075c761037b2302e7d087a9893441bc04ff484b10cd69a128fa0"
EXPECTED_METADATA_SHA256 = "e23363ba8be16b5ba47702f0c7ecdafe9d3493493094bd2451738171777a1b55"
REFERENCE_DATE = "2021"
CONTEXT_ROLE = "aggregate_historical_regional_context_only"
INTERPRETATION_BOUNDARY = (
    "Published 2021 aggregate regional Census of Agriculture context only; not a field observation, "
    "farm record, current practice claim, diagnosis, prescription, or management-rate authority."
)
KEY_CONTRACT = "exact_statcan_2021_dguid_only"

REQUIRED_COLUMNS = (
    "REF_DATE",
    "GEO",
    "DGUID",
    "Tillage practices",
    "Unit of measure",
    "UOM",
    "UOM_ID",
    "SCALAR_FACTOR",
    "SCALAR_ID",
    "VECTOR",
    "COORDINATE",
    "VALUE",
    "STATUS",
    "SYMBOL",
    "TERMINATED",
    "DECIMALS",
)
PRACTICES = (
    "Total land prepared for seeding",
    "No-till seeding or zero-till seeding",
    "Tillage retaining most crop residue on the surface",
    "Tillage incorporating most crop residue into soil",
)
UNITS = ("Number of farms reporting", "Acres", "Hectares")
QUALITY_STATUS_CODES = frozenset({"A", "B", "C", "D", "E", "F"})
EXPECTED_RELEASE_COUNTS = {
    "province": 10,
    "census_agricultural_region": 69,
    "observation": 948,
}
GEO_TOKEN_PATTERN = re.compile(r"^.+ \[(?P<prefix>[A-Z]*)(?P<digits>\d{9})\]$")
VECTOR_PATTERN = re.compile(r"^v\d+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def sha256_path(path: Path) -> str:
    """Return a SHA-256 without loading the entire file into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _require_external_derived_path(path: Path, *, label: str) -> Path:
    """Keep generated local state out of the repository by construction."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError(f"{label} must be outside the Git checkout: {resolved}")


def _require_external_source_path(path: Path) -> Path:
    """Raw public-source bytes belong in user-managed local state, never Git."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError(f"source archive must be outside the Git checkout: {resolved}")


def _validate_raw_release(
    source: Path,
    *,
    expected_raw_sha256: str,
    strict_release: bool,
) -> tuple[bytes, bytes, dict[str, Any]]:
    """Validate the raw archive before parsing any of its public table rows."""

    source = _require_external_source_path(source)
    if not source.is_file():
        raise ValueError(f"source archive is not a regular file: {source}")
    if not SHA256_PATTERN.fullmatch(expected_raw_sha256):
        raise ValueError("expected raw SHA-256 must be a lowercase 64-character digest")
    raw_sha256 = sha256_path(source)
    if raw_sha256 != expected_raw_sha256:
        raise ValueError(
            "source archive SHA-256 does not match the declared release pin: "
            f"expected {expected_raw_sha256}, found {raw_sha256}"
        )
    try:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if names.count(RAW_CSV_MEMBER) != 1 or names.count(RAW_METADATA_MEMBER) != 1:
                raise ValueError("source archive does not contain the required Statistics Canada CSV members")
            csv_bytes = archive.read(RAW_CSV_MEMBER)
            metadata_bytes = archive.read(RAW_METADATA_MEMBER)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"source archive is not a readable ZIP file: {source}") from exc

    report = {
        "raw_path": str(source),
        "raw_bytes": source.stat().st_size,
        "raw_sha256": raw_sha256,
        "csv_member": RAW_CSV_MEMBER,
        "csv_bytes": len(csv_bytes),
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "metadata_member": RAW_METADATA_MEMBER,
        "metadata_bytes": len(metadata_bytes),
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
    }
    if strict_release:
        expected = {
            "raw_bytes": EXPECTED_RAW_BYTES,
            "raw_sha256": EXPECTED_RAW_SHA256,
            "csv_sha256": EXPECTED_CSV_SHA256,
            "metadata_sha256": EXPECTED_METADATA_SHA256,
        }
        for key, value in expected.items():
            if report[key] != value:
                raise ValueError(
                    f"official release contract mismatch for {key}: expected {value!r}, found {report[key]!r}"
                )
    return csv_bytes, metadata_bytes, report


def _target_geography(row: dict[str, str]) -> dict[str, str] | None:
    """Return one exact PR/CAR identity, or ``None`` for non-target geography."""

    geography = row["GEO"]
    match = GEO_TOKEN_PATTERN.fullmatch(geography)
    if match is None:
        raise ValueError(f"unparseable Statistics Canada GEO value: {geography!r}")
    prefix = match.group("prefix")
    digits = match.group("digits")
    if prefix in {"", "CD", "CCS"}:
        return None
    dguid = row["DGUID"]
    if prefix == "PR":
        if digits[2:] != "0000000":
            raise ValueError(f"province publication code is not canonical: {prefix}{digits}")
        province_uid = digits[:2]
        expected_dguid = f"2021A0002{province_uid}"
        result = {
            "geography_type": "province",
            "published_geography_code": f"PR{digits}",
            "geography_dguid": dguid,
            "expected_dguid": expected_dguid,
            "province_uid": province_uid,
            "boundary_feature_code": f"PR_{province_uid}",
            "source_geography_label": geography,
        }
    elif prefix == "CAR":
        if digits[4:] != "00000":
            raise ValueError(f"CAR publication code is not canonical: {prefix}{digits}")
        car_uid = digits[:4]
        province_uid = car_uid[:2]
        expected_dguid = f"2021S0501{car_uid}"
        result = {
            "geography_type": "census_agricultural_region",
            "published_geography_code": f"CAR{digits}",
            "geography_dguid": dguid,
            "expected_dguid": expected_dguid,
            "province_uid": province_uid,
            "boundary_feature_code": f"CAR_{car_uid}",
            "source_geography_label": geography,
        }
    else:
        raise ValueError(f"unexpected geography class in source table: {prefix!r}")
    if dguid != result["expected_dguid"]:
        raise ValueError(
            "published GEO code and DGUID do not satisfy the exact 2021 Statistics Canada contract: "
            f"{result['published_geography_code']} -> {dguid!r}, expected {result['expected_dguid']!r}"
        )
    return result


def _parse_target_rows(csv_bytes: bytes) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], dict[str, int]]:
    """Parse only PR/CAR rows and preserve publication values/statuses verbatim."""

    try:
        reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"), newline=""))
    except UnicodeDecodeError as exc:
        raise ValueError("source CSV must be UTF-8 encoded") from exc
    if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
        raise ValueError(
            "source CSV columns do not match the reviewed table contract: "
            f"expected {list(REQUIRED_COLUMNS)!r}, found {reader.fieldnames!r}"
        )

    observations: list[dict[str, Any]] = []
    geographies: dict[str, dict[str, str]] = {}
    all_geography_classes: Counter[str] = Counter()
    seen_records: set[tuple[str, str, str]] = set()
    vectors: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"source CSV row {row_number} has an unexpected extra column")
        target = _target_geography(row)
        token_match = GEO_TOKEN_PATTERN.fullmatch(row["GEO"])
        assert token_match is not None  # Checked in _target_geography above.
        all_geography_classes[token_match.group("prefix") or "Canada"] += 1
        if target is None:
            continue
        if row["REF_DATE"] != REFERENCE_DATE:
            raise ValueError(f"row {row_number} has unexpected reference date {row['REF_DATE']!r}")
        if row["Tillage practices"] not in PRACTICES:
            raise ValueError(f"row {row_number} has unreviewed tillage practice")
        if row["Unit of measure"] not in UNITS:
            raise ValueError(f"row {row_number} has unreviewed unit of measure")
        if row["UOM"] != "Number" or row["UOM_ID"] != "223":
            raise ValueError(f"row {row_number} has unreviewed unit metadata")
        if row["SCALAR_FACTOR"] != "units" or row["SCALAR_ID"] != "0":
            raise ValueError(f"row {row_number} has unreviewed scalar metadata")
        if row["TERMINATED"] != "" or row["DECIMALS"] != "0":
            raise ValueError(f"row {row_number} has unreviewed termination or decimal metadata")
        if not VECTOR_PATTERN.fullmatch(row["VECTOR"]):
            raise ValueError(f"row {row_number} has an invalid Statistics Canada vector identifier")
        if not row["COORDINATE"]:
            raise ValueError(f"row {row_number} has an empty coordinate")
        if row["STATUS"] not in QUALITY_STATUS_CODES:
            raise ValueError(f"row {row_number} has an unreviewed published status {row['STATUS']!r}")
        if row["VALUE"] and not row["VALUE"].isdigit():
            raise ValueError(f"row {row_number} has an unreviewed non-integer published value")
        record_key = (target["geography_dguid"], row["Tillage practices"], row["Unit of measure"])
        if record_key in seen_records:
            raise ValueError(f"source table has a duplicate target observation {record_key!r}")
        seen_records.add(record_key)
        vectors.add(row["VECTOR"])
        previous = geographies.setdefault(target["geography_dguid"], target)
        if previous != target:
            raise ValueError(f"source table has conflicting exact geography identity for {target['geography_dguid']}")
        observations.append(
            {
                **target,
                "reference_date": row["REF_DATE"],
                "tillage_practice": row["Tillage practices"],
                "unit_of_measure": row["Unit of measure"],
                "uom": row["UOM"],
                "uom_id": row["UOM_ID"],
                "scalar_factor": row["SCALAR_FACTOR"],
                "scalar_id": row["SCALAR_ID"],
                "source_vector": row["VECTOR"],
                "source_coordinate": row["COORDINATE"],
                "source_value_text": row["VALUE"] or None,
                "value_present": int(bool(row["VALUE"])),
                "value_status": row["STATUS"],
                "symbol": row["SYMBOL"],
                "terminated": row["TERMINATED"],
                "decimals": row["DECIMALS"],
            }
        )

    expected_pairs = {(practice, unit) for practice in PRACTICES for unit in UNITS}
    for dguid, geography in geographies.items():
        observed_pairs = {
            (row["tillage_practice"], row["unit_of_measure"])
            for row in observations
            if row["geography_dguid"] == dguid
        }
        if observed_pairs != expected_pairs:
            raise ValueError(
                f"{geography['published_geography_code']} does not have the required 12 practice/unit rows"
            )
    if len(vectors) != len(observations):
        raise ValueError("source table reuses a Statistics Canada vector identifier in target rows")
    observations.sort(
        key=lambda row: (
            row["geography_dguid"],
            PRACTICES.index(row["tillage_practice"]),
            UNITS.index(row["unit_of_measure"]),
        )
    )
    return observations, geographies, dict(sorted(all_geography_classes.items()))


def _metadata_values(connection: sqlite3.Connection) -> dict[str, Any]:
    try:
        rows = connection.execute("SELECT key, value_json FROM metadata").fetchall()
    except sqlite3.Error as exc:
        raise ValueError("boundary/snapshot database does not have the required metadata table") from exc
    result: dict[str, Any] = {}
    for key, value in rows:
        if key in result:
            raise ValueError(f"metadata contains a duplicate key: {key}")
        try:
            result[str(key)] = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"metadata value for {key!r} is not JSON") from exc
    return result


def _load_boundary_index(
    path: Path,
    *,
    expected_source_id: str,
    geography_type: str,
) -> dict[str, dict[str, str]]:
    """Load the exact DGUID hierarchy from one installed boundary database."""

    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"required boundary layer is not a regular file: {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        metadata = _metadata_values(connection)
        if metadata.get("schema_version") != BOUNDARY_LAYER_SCHEMA_VERSION:
            raise ValueError(f"boundary layer has an unsupported schema: {path}")
        if metadata.get("source_id") != expected_source_id:
            raise ValueError(
                f"boundary layer source identity mismatch: expected {expected_source_id}, found {metadata.get('source_id')!r}"
            )
        if metadata.get("feature_payload_encoding") != "zlib_json_v1":
            raise ValueError(f"boundary layer does not use the reviewed payload contract: {path}")
        rows = connection.execute("SELECT code, properties_zlib FROM features ORDER BY code").fetchall()
    except sqlite3.Error as exc:
        raise ValueError(f"boundary layer does not satisfy the expected feature schema: {path}") from exc
    finally:
        connection.close()

    required_fields = {
        "province": {"province_uid", "dissemination_geography_id"},
        "census_agricultural_region": {
            "province_uid",
            "census_agricultural_region_code",
            "dissemination_geography_id",
        },
    }[geography_type]
    index: dict[str, dict[str, str]] = {}
    for code, compressed in rows:
        try:
            properties = json.loads(zlib.decompress(compressed))
        except (TypeError, zlib.error, json.JSONDecodeError) as exc:
            raise ValueError(f"boundary feature has unreadable properties: {path}") from exc
        if not isinstance(properties, dict) or not required_fields.issubset(properties):
            raise ValueError(f"boundary feature is missing exact-key properties: {path}")
        dguid = str(properties["dissemination_geography_id"])
        province_uid = str(properties["province_uid"])
        if geography_type == "province":
            expected_code = f"PR_{province_uid}"
            expected_dguid = f"2021A0002{province_uid}"
        else:
            car_uid = str(properties["census_agricultural_region_code"])
            expected_code = f"CAR_{car_uid}"
            expected_dguid = f"2021S0501{car_uid}"
            if not car_uid.startswith(province_uid):
                raise ValueError(f"CAR layer contains an inconsistent province/CAR hierarchy: {dguid}")
        if str(code) != expected_code or dguid != expected_dguid:
            raise ValueError(f"boundary feature does not satisfy the exact 2021 Statistics Canada key contract: {dguid}")
        if dguid in index:
            raise ValueError(f"boundary layer contains duplicate DGUID {dguid!r}")
        index[dguid] = {
            "boundary_feature_code": str(code),
            "province_uid": province_uid,
        }
    if not index:
        raise ValueError(f"boundary layer has no usable exact DGUID features: {path}")
    return index


def _validate_boundary_join(
    geographies: Iterable[dict[str, str]],
    *,
    province_boundary_layer: Path,
    car_boundary_layer: Path,
) -> dict[str, dict[str, str]]:
    """Fail closed unless every source row joins one exact installed boundary ID."""

    indexes = {
        "province": _load_boundary_index(
            province_boundary_layer,
            expected_source_id="ca_statcan_2021_provinces_territories",
            geography_type="province",
        ),
        "census_agricultural_region": _load_boundary_index(
            car_boundary_layer,
            expected_source_id="ca_statcan_2021_census_agricultural_regions",
            geography_type="census_agricultural_region",
        ),
    }
    joined: dict[str, dict[str, str]] = {}
    for geography in sorted(geographies, key=lambda row: row["geography_dguid"]):
        dguid = geography["geography_dguid"]
        geography_type = geography["geography_type"]
        if geography_type not in indexes:
            raise ValueError(f"snapshot/source contains an unsupported geography type: {geography_type!r}")
        boundary = indexes[geography_type].get(dguid)
        if boundary is None:
            raise ValueError(
                "no exact installed 2021 boundary match for published source geography: "
                f"{geography['published_geography_code']} / {dguid}"
            )
        if (
            boundary["boundary_feature_code"] != geography["boundary_feature_code"]
            or boundary["province_uid"] != geography["province_uid"]
        ):
            raise ValueError(
                "installed boundary hierarchy does not exactly match the published source geography: "
                f"{geography['published_geography_code']} / {dguid}"
            )
        joined[dguid] = boundary
    return joined


def _write_metadata(connection: sqlite3.Connection, metadata: dict[str, Any]) -> None:
    for key, value in sorted(metadata.items()):
        connection.execute(
            "INSERT INTO metadata(key, value_json) VALUES (?, ?)",
            (key, _canonical_json(value)),
        )


def _write_snapshot(
    output: Path,
    *,
    raw_report: dict[str, Any],
    observations: list[dict[str, Any]],
    geographies: dict[str, dict[str, str]],
    source_geography_class_counts: dict[str, int],
    allow_replace: bool,
) -> None:
    """Write a compact normalized SQLite table using a replace-safe temporary file."""

    output = _require_external_derived_path(output, label="output")
    if output.exists() and not allow_replace:
        raise FileExistsError(f"output already exists; pass --replace to rebuild it: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"temporary output already exists; inspect it before rebuilding: {temporary}")

    counts = Counter(row["geography_type"] for row in geographies.values())
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "source_id": SOURCE_ID,
        "source_title": SOURCE_TITLE,
        "source_table_id": SOURCE_TABLE_ID,
        "source_url": SOURCE_URL,
        "source_download_url": SOURCE_DOWNLOAD_URL,
        "source_license": SOURCE_LICENSE,
        "source_attribution": SOURCE_ATTRIBUTION,
        "source_reference_date": REFERENCE_DATE,
        "raw_sha256": raw_report["raw_sha256"],
        "raw_bytes": raw_report["raw_bytes"],
        "csv_member": raw_report["csv_member"],
        "csv_sha256": raw_report["csv_sha256"],
        "metadata_member": raw_report["metadata_member"],
        "metadata_sha256": raw_report["metadata_sha256"],
        "key_contract": KEY_CONTRACT,
        "allowed_geography_types": ["province", "census_agricultural_region"],
        "geography_count": len(geographies),
        "geography_counts": dict(sorted(counts.items())),
        "observation_count": len(observations),
        "source_geography_class_counts": source_geography_class_counts,
        "context_role": CONTEXT_ROLE,
        "interpretation_boundary": INTERPRETATION_BOUNDARY,
        "status_symbol_policy": (
            "Preserve Statistics Canada STATUS and SYMBOL verbatim. Do not infer suppression, quality, "
            "or missing-value meaning beyond the source row."
        ),
        "distribution_role": "optional_local_aggregate_historical_context",
    }
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA temp_store=MEMORY;
            PRAGMA foreign_keys=ON;
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            CREATE TABLE geographies (
                geography_dguid TEXT PRIMARY KEY,
                geography_type TEXT NOT NULL CHECK (geography_type IN ('province', 'census_agricultural_region')),
                published_geography_code TEXT NOT NULL UNIQUE,
                source_geography_label TEXT NOT NULL,
                province_uid TEXT NOT NULL,
                boundary_feature_code TEXT NOT NULL UNIQUE,
                key_contract TEXT NOT NULL CHECK (key_contract = 'exact_statcan_2021_dguid_only'),
                context_role TEXT NOT NULL CHECK (context_role = 'aggregate_historical_regional_context_only'),
                interpretation_boundary TEXT NOT NULL
            );
            CREATE TABLE observations (
                geography_dguid TEXT NOT NULL REFERENCES geographies(geography_dguid),
                reference_date TEXT NOT NULL CHECK (reference_date = '2021'),
                tillage_practice TEXT NOT NULL,
                unit_of_measure TEXT NOT NULL,
                uom TEXT NOT NULL,
                uom_id TEXT NOT NULL,
                scalar_factor TEXT NOT NULL,
                scalar_id TEXT NOT NULL,
                source_vector TEXT NOT NULL UNIQUE,
                source_coordinate TEXT NOT NULL,
                source_value_text TEXT,
                value_present INTEGER NOT NULL CHECK (value_present IN (0, 1)),
                value_status TEXT NOT NULL,
                symbol TEXT NOT NULL,
                terminated TEXT NOT NULL,
                decimals TEXT NOT NULL,
                context_role TEXT NOT NULL CHECK (context_role = 'aggregate_historical_regional_context_only'),
                interpretation_boundary TEXT NOT NULL,
                PRIMARY KEY (geography_dguid, tillage_practice, unit_of_measure),
                CHECK ((value_present = 1 AND source_value_text IS NOT NULL) OR (value_present = 0 AND source_value_text IS NULL))
            );
            CREATE INDEX observations_by_geography ON observations(geography_dguid, tillage_practice, unit_of_measure);
            """
        )
        _write_metadata(connection, metadata)
        for geography_dguid in sorted(geographies):
            row = geographies[geography_dguid]
            connection.execute(
                "INSERT INTO geographies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    geography_dguid,
                    row["geography_type"],
                    row["published_geography_code"],
                    row["source_geography_label"],
                    row["province_uid"],
                    row["boundary_feature_code"],
                    KEY_CONTRACT,
                    CONTEXT_ROLE,
                    INTERPRETATION_BOUNDARY,
                ),
            )
        for row in observations:
            connection.execute(
                "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["geography_dguid"],
                    row["reference_date"],
                    row["tillage_practice"],
                    row["unit_of_measure"],
                    row["uom"],
                    row["uom_id"],
                    row["scalar_factor"],
                    row["scalar_id"],
                    row["source_vector"],
                    row["source_coordinate"],
                    row["source_value_text"],
                    row["value_present"],
                    row["value_status"],
                    row["symbol"],
                    row["terminated"],
                    row["decimals"],
                    CONTEXT_ROLE,
                    INTERPRETATION_BOUNDARY,
                ),
            )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()
    os.replace(temporary, output)


def _release_count_errors(metadata: dict[str, Any]) -> list[str]:
    counts = metadata.get("geography_counts")
    errors: list[str] = []
    if not isinstance(counts, dict):
        return ["metadata_geography_counts_missing"]
    for geography_type, expected in EXPECTED_RELEASE_COUNTS.items():
        if geography_type == "observation":
            actual = metadata.get("observation_count")
        else:
            actual = counts.get(geography_type)
        if actual != expected:
            errors.append(f"release_count_mismatch:{geography_type}:{actual!r}!={expected}")
    return errors


def validate_snapshot(
    snapshot: Path,
    *,
    province_boundary_layer: Path,
    car_boundary_layer: Path,
    expected_raw_sha256: str | None = None,
    strict_release: bool = True,
) -> dict[str, Any]:
    """Validate snapshot structure, exact boundary joins, and contextual limits."""

    snapshot = snapshot.expanduser().resolve()
    errors: list[str] = []
    metadata: dict[str, Any] = {}
    rows: list[dict[str, str]] = []
    observation_count = 0
    try:
        connection = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
        try:
            metadata = _metadata_values(connection)
            if metadata.get("schema_version") != SCHEMA_VERSION:
                errors.append("unsupported_snapshot_schema")
            required_metadata = {
                "source_id": SOURCE_ID,
                "source_table_id": SOURCE_TABLE_ID,
                "source_reference_date": REFERENCE_DATE,
                "key_contract": KEY_CONTRACT,
                "context_role": CONTEXT_ROLE,
                "interpretation_boundary": INTERPRETATION_BOUNDARY,
            }
            for key, expected in required_metadata.items():
                if metadata.get(key) != expected:
                    errors.append(f"metadata_mismatch:{key}")
            raw_sha = metadata.get("raw_sha256")
            if not isinstance(raw_sha, str) or not SHA256_PATTERN.fullmatch(raw_sha):
                errors.append("invalid_raw_sha256")
            if expected_raw_sha256 is not None and raw_sha != expected_raw_sha256:
                errors.append("raw_sha256_mismatch")
            if strict_release:
                errors.extend(_release_count_errors(metadata))
                if raw_sha != EXPECTED_RAW_SHA256:
                    errors.append("release_raw_sha256_mismatch")
                if metadata.get("csv_sha256") != EXPECTED_CSV_SHA256:
                    errors.append("release_csv_sha256_mismatch")
                if metadata.get("metadata_sha256") != EXPECTED_METADATA_SHA256:
                    errors.append("release_metadata_sha256_mismatch")
            geography_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(geographies)").fetchall()
            }
            if {
                "geography_dguid",
                "geography_type",
                "published_geography_code",
                "province_uid",
                "boundary_feature_code",
                "context_role",
            } - geography_columns:
                errors.append("geography_schema_mismatch")
            observation_columns = {row[1] for row in connection.execute("PRAGMA table_info(observations)").fetchall()}
            if {"value_status", "symbol", "value_present", "context_role"} - observation_columns:
                errors.append("observation_schema_mismatch")
            rows = [
                {
                    "geography_dguid": str(row[0]),
                    "geography_type": str(row[1]),
                    "published_geography_code": str(row[2]),
                    "province_uid": str(row[3]),
                    "boundary_feature_code": str(row[4]),
                    "context_role": str(row[5]),
                }
                for row in connection.execute(
                    "SELECT geography_dguid, geography_type, published_geography_code, province_uid, "
                    "boundary_feature_code, context_role FROM geographies ORDER BY geography_dguid"
                ).fetchall()
            ]
            if not rows:
                errors.append("snapshot_has_no_geographies")
            if any(row["context_role"] != CONTEXT_ROLE for row in rows):
                errors.append("geography_context_boundary_mismatch")
            observation_count = int(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
            value_state_errors = int(
                connection.execute(
                    "SELECT COUNT(*) FROM observations WHERE "
                    "(value_present = 1 AND source_value_text IS NULL) OR "
                    "(value_present = 0 AND source_value_text IS NOT NULL) OR "
                    "context_role != ?",
                    (CONTEXT_ROLE,),
                ).fetchone()[0]
            )
            if value_state_errors:
                errors.append("observation_value_or_context_boundary_mismatch")
            observed_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
            observation_rows = connection.execute(
                "SELECT geography_dguid, reference_date, tillage_practice, unit_of_measure, uom, uom_id, "
                "scalar_factor, scalar_id, source_vector, value_status FROM observations"
            ).fetchall()
            for (
                geography_dguid,
                reference_date,
                practice,
                unit,
                uom,
                uom_id,
                scalar_factor,
                scalar_id,
                vector,
                value_status,
            ) in observation_rows:
                observed_pairs[str(geography_dguid)].add((str(practice), str(unit)))
                if (
                    reference_date != REFERENCE_DATE
                    or practice not in PRACTICES
                    or unit not in UNITS
                    or uom != "Number"
                    or uom_id != "223"
                    or scalar_factor != "units"
                    or scalar_id != "0"
                    or not isinstance(vector, str)
                    or not VECTOR_PATTERN.fullmatch(vector)
                    or value_status not in QUALITY_STATUS_CODES
                ):
                    errors.append("observation_contract_mismatch")
                    break
            expected_pairs = {(practice, unit) for practice in PRACTICES for unit in UNITS}
            if any(observed_pairs.get(row["geography_dguid"], set()) != expected_pairs for row in rows):
                errors.append("observation_matrix_mismatch")
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError) as exc:
        errors.append(f"snapshot_unreadable:{exc}")

    try:
        if rows:
            _validate_boundary_join(
                rows,
                province_boundary_layer=province_boundary_layer,
                car_boundary_layer=car_boundary_layer,
            )
    except (KeyError, ValueError) as exc:
        errors.append(f"boundary_join_failed:{exc}")
    if metadata.get("geography_count") != len(rows):
        errors.append("geography_count_mismatch")
    if metadata.get("observation_count") != observation_count:
        errors.append("observation_count_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if not errors else "fail",
        "snapshot_path": str(snapshot),
        "snapshot_sha256": sha256_path(snapshot) if snapshot.is_file() else None,
        "snapshot_bytes": snapshot.stat().st_size if snapshot.is_file() else None,
        "geography_count": len(rows),
        "observation_count": observation_count,
        "raw_sha256": metadata.get("raw_sha256"),
        "context_role": metadata.get("context_role"),
        "boundary_join_contract": KEY_CONTRACT,
        "errors": errors,
        "boundary": INTERPRETATION_BOUNDARY,
    }


def build_snapshot(
    *,
    source: Path,
    province_boundary_layer: Path,
    car_boundary_layer: Path,
    output: Path,
    manifest: Path,
    expected_raw_sha256: str = EXPECTED_RAW_SHA256,
    strict_release: bool = True,
    allow_replace: bool = False,
) -> dict[str, Any]:
    """Create one provenance-bound local snapshot and its deterministic receipt."""

    output = _require_external_derived_path(output, label="output")
    manifest = _require_external_derived_path(manifest, label="manifest")
    if output == manifest:
        raise ValueError("output and manifest must be different files")
    if manifest.exists() and not allow_replace:
        raise FileExistsError(f"manifest already exists; pass --replace to rebuild it: {manifest}")
    csv_bytes, _metadata_bytes, raw_report = _validate_raw_release(
        source,
        expected_raw_sha256=expected_raw_sha256,
        strict_release=strict_release,
    )
    observations, geographies, source_geography_class_counts = _parse_target_rows(csv_bytes)
    if strict_release:
        observed_counts = Counter(row["geography_type"] for row in geographies.values())
        if (
            observed_counts["province"] != EXPECTED_RELEASE_COUNTS["province"]
            or observed_counts["census_agricultural_region"] != EXPECTED_RELEASE_COUNTS["census_agricultural_region"]
            or len(observations) != EXPECTED_RELEASE_COUNTS["observation"]
        ):
            raise ValueError("source table does not satisfy the reviewed 2021 PR/CAR release counts")
    _validate_boundary_join(
        geographies.values(),
        province_boundary_layer=province_boundary_layer,
        car_boundary_layer=car_boundary_layer,
    )
    _write_snapshot(
        output,
        raw_report=raw_report,
        observations=observations,
        geographies=geographies,
        source_geography_class_counts=source_geography_class_counts,
        allow_replace=allow_replace,
    )
    validation = validate_snapshot(
        output,
        province_boundary_layer=province_boundary_layer,
        car_boundary_layer=car_boundary_layer,
        expected_raw_sha256=expected_raw_sha256,
        strict_release=strict_release,
    )
    if validation["status"] != "pass":
        raise ValueError(f"built snapshot failed validation: {validation['errors']}")
    report = {
        "schema_version": SCHEMA_VERSION,
        "source": raw_report,
        "source_id": SOURCE_ID,
        "source_title": SOURCE_TITLE,
        "source_table_id": SOURCE_TABLE_ID,
        "source_license": SOURCE_LICENSE,
        "source_attribution": SOURCE_ATTRIBUTION,
        "snapshot_path": str(output),
        "snapshot_sha256": validation["snapshot_sha256"],
        "snapshot_bytes": validation["snapshot_bytes"],
        "geography_count": validation["geography_count"],
        "observation_count": validation["observation_count"],
        "key_contract": KEY_CONTRACT,
        "context_role": CONTEXT_ROLE,
        "interpretation_boundary": INTERPRETATION_BOUNDARY,
        "boundary_layers": {
            "province": str(province_boundary_layer.expanduser().resolve()),
            "census_agricultural_region": str(car_boundary_layer.expanduser().resolve()),
        },
        "validation": validation,
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest.with_name(manifest.name + ".tmp")
    if temporary_manifest.exists():
        raise FileExistsError(f"temporary manifest already exists; inspect it before rebuilding: {temporary_manifest}")
    temporary_manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Pinned official 32100367 ZIP outside the checkout")
    parser.add_argument("--province-boundary-layer", type=Path, required=True)
    parser.add_argument("--car-boundary-layer", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="External-state SQLite destination (build mode)")
    parser.add_argument("--manifest", type=Path, help="External-state JSON receipt destination (build mode)")
    parser.add_argument("--validate", action="store_true", help="Validate --output instead of building it")
    parser.add_argument(
        "--expected-raw-sha256",
        default=EXPECTED_RAW_SHA256,
        help="Exact source archive SHA-256; default is the reviewed 2021 release",
    )
    parser.add_argument("--replace", action="store_true", help="Allow replacement of an existing output and manifest")
    args = parser.parse_args()
    if args.validate:
        if args.output is None:
            parser.error("--output is required with --validate")
        report = validate_snapshot(
            args.output,
            province_boundary_layer=args.province_boundary_layer,
            car_boundary_layer=args.car_boundary_layer,
            expected_raw_sha256=args.expected_raw_sha256,
            strict_release=True,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "pass" else 1
    if args.output is None or args.manifest is None:
        parser.error("--output and --manifest are required in build mode")
    report = build_snapshot(
        source=args.source,
        province_boundary_layer=args.province_boundary_layer,
        car_boundary_layer=args.car_boundary_layer,
        output=args.output,
        manifest=args.manifest,
        expected_raw_sha256=args.expected_raw_sha256,
        strict_release=True,
        allow_replace=args.replace,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
