#!/usr/bin/env python3
"""Build a compact, auditable offline snapshot of Statistics Canada table 32-10-0359-01."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import tempfile
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.local_tools import (
    STATCAN_CROP_MEMBER_IDS,
    STATCAN_FIELD_CROP_PRODUCT_ID,
    STATCAN_FIELD_CROP_STATISTICS,
    STATCAN_FIELD_CROP_TABLE_URL,
    STATCAN_PROVINCE_MEMBER_IDS,
)
from agronomy_agent.paths import repo_path


SOURCE_ZIP_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/32100359-eng.zip"
SOURCE_DOI = "https://doi.org/10.25318/3210035901-eng"
LICENSE_URL = "https://www.statcan.gc.ca/en/terms-conditions/open-licence"
DEFAULT_OUTPUT = "data/snapshots/statcan_field_crop_statistics.jsonl"
DEFAULT_MANIFEST = "data/snapshots/statcan_field_crop_statistics_manifest.json"
SCHEMA_VERSION = "open_agronomy_agent.portable_statcan_field_crop_snapshot.v1"

CANONICAL_CROPS: dict[str, int] = {
    "barley": 6,
    "beans": 39,
    "buckwheat": 12,
    "canola": 16,
    "chickpeas": 38,
    "corn grain": 11,
    "flaxseed": 14,
    "lentils": 32,
    "mustard": 30,
    "oats": 5,
    "dry peas": 13,
    "soybeans": 15,
    "sunflower": 31,
    "wheat": 1,
}

PROVINCE_LABELS = {
    "CANADA": "Canada",
    "NL": "Newfoundland and Labrador",
    "PE": "Prince Edward Island",
    "NS": "Nova Scotia",
    "NB": "New Brunswick",
    "QC": "Quebec",
    "ON": "Ontario",
    "MB": "Manitoba",
    "SK": "Saskatchewan",
    "AB": "Alberta",
    "BC": "British Columbia",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _member_release_date(info: zipfile.ZipInfo) -> str:
    year, month, day, *_ = info.date_time
    return f"{year:04d}-{month:02d}-{day:02d}"


def _canonical_crop_by_member() -> dict[int, str]:
    return {member_id: crop for crop, member_id in CANONICAL_CROPS.items()}


def _crop_aliases() -> dict[str, str]:
    canonical_by_member = _canonical_crop_by_member()
    return {
        alias: canonical_by_member[member_id]
        for alias, member_id in sorted(STATCAN_CROP_MEMBER_IDS.items())
        if member_id in canonical_by_member
    }


def _parse_value(value: str, decimals: str) -> int | float | None:
    text = str(value or "").strip()
    if not text:
        return None
    decimal_count = int(decimals or 0)
    return float(text) if decimal_count else int(text)


def _snapshot_row(
    row: dict[str, str],
    *,
    province_code: str,
    crop_key: str,
    statistic_id: str,
    source_release_date: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "product_id": STATCAN_FIELD_CROP_PRODUCT_ID,
        "table": "32-10-0359-01",
        "source_release_date": source_release_date,
        "reference_period": str(row.get("REF_DATE") or ""),
        "province_code": province_code,
        "geography": str(row.get("GEO") or ""),
        "dguid": str(row.get("DGUID") or ""),
        "crop_key": crop_key,
        "crop_label": str(row.get("Type of crop") or ""),
        "statistic_id": statistic_id,
        "statistic_label": str(row.get("Harvest disposition") or ""),
        "unit": str(row.get("UOM") or ""),
        "unit_id": int(row.get("UOM_ID") or 0),
        "scalar_factor": str(row.get("SCALAR_FACTOR") or ""),
        "scalar_id": int(row.get("SCALAR_ID") or 0),
        "value": _parse_value(str(row.get("VALUE") or ""), str(row.get("DECIMALS") or "0")),
        "decimals": int(row.get("DECIMALS") or 0),
        "status_code": str(row.get("STATUS") or "") or None,
        "symbol_code": str(row.get("SYMBOL") or "") or None,
        "terminated": str(row.get("TERMINATED") or "") or None,
        "vector_id": str(row.get("VECTOR") or "") or None,
        "coordinate": str(row.get("COORDINATE") or "") or None,
        "provenance": "statistics_canada_table_32100359_portable_snapshot",
    }


def _iter_supported_rows(
    rows: Iterable[dict[str, str]],
    *,
    source_release_date: str,
) -> Iterable[dict[str, Any]]:
    province_by_label = {label: code for code, label in PROVINCE_LABELS.items()}
    crop_by_label_member = _canonical_crop_by_member()
    statistic_by_label = {
        label: statistic_id
        for statistic_id, (_, label) in STATCAN_FIELD_CROP_STATISTICS.items()
    }
    for row in rows:
        province_code = province_by_label.get(str(row.get("GEO") or ""))
        statistic_id = statistic_by_label.get(str(row.get("Harvest disposition") or ""))
        coordinate = str(row.get("COORDINATE") or "")
        try:
            crop_member = int(coordinate.split(".")[2])
        except (IndexError, ValueError):
            continue
        crop_key = crop_by_label_member.get(crop_member)
        if not (province_code and statistic_id and crop_key):
            continue
        payload = _snapshot_row(
            row,
            province_code=province_code,
            crop_key=crop_key,
            statistic_id=statistic_id,
            source_release_date=source_release_date,
        )
        if payload["value"] is not None:
            yield payload


def build_snapshot(
    *,
    source_zip: Path,
    output: Path,
    manifest: Path,
    source_url: str = SOURCE_ZIP_URL,
    latest_periods: int = 5,
) -> dict[str, Any]:
    if latest_periods < 1 or latest_periods > 20:
        raise ValueError("latest_periods must be between 1 and 20")
    with zipfile.ZipFile(source_zip) as archive:
        csv_name = f"{STATCAN_FIELD_CROP_PRODUCT_ID}.csv"
        metadata_name = f"{STATCAN_FIELD_CROP_PRODUCT_ID}_MetaData.csv"
        info = archive.getinfo(csv_name)
        source_release_date = _member_release_date(info)
        with archive.open(csv_name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            supported = list(_iter_supported_rows(reader, source_release_date=source_release_date))

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in supported:
        grouped[(row["province_code"], row["crop_key"], row["statistic_id"])].append(row)

    selected: list[dict[str, Any]] = []
    for rows in grouped.values():
        selected.extend(
            sorted(rows, key=lambda item: str(item["reference_period"]))[-latest_periods:]
        )
    selected.sort(
        key=lambda item: (
            str(item["province_code"]),
            str(item["crop_key"]),
            str(item["statistic_id"]),
            str(item["reference_period"]),
        )
    )
    if not selected:
        raise RuntimeError("Statistics Canada archive produced no supported snapshot rows")

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    with partial.open("w", encoding="utf-8", newline="\n") as handle:
        for row in selected:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    partial.replace(output)

    province_counts = Counter(str(row["province_code"]) for row in selected)
    crop_counts = Counter(str(row["crop_key"]) for row in selected)
    statistic_counts = Counter(str(row["statistic_id"]) for row in selected)
    snapshot_sha256 = _sha256(output)
    source_sha256 = _sha256(source_zip)
    report = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "provider": "Statistics Canada",
            "product_id": STATCAN_FIELD_CROP_PRODUCT_ID,
            "table": "32-10-0359-01",
            "title": (
                "Estimated areas, yield, production, average farm price and total farm value "
                "of principal field crops, in metric and imperial units"
            ),
            "table_url": STATCAN_FIELD_CROP_TABLE_URL,
            "archive_url": source_url,
            "doi": SOURCE_DOI,
            "release_date": source_release_date,
            "archive_sha256": source_sha256,
            "archive_bytes": source_zip.stat().st_size,
            "csv_member": csv_name,
            "metadata_member": metadata_name,
        },
        "license": {
            "identifier": "Statistics Canada Open Licence",
            "url": LICENSE_URL,
            "permits_redistribution": True,
            "permits_modification": True,
            "permits_commercial": True,
            "attribution": (
                "Adapted from Statistics Canada, Estimated areas, yield, production, average farm price "
                "and total farm value of principal field crops, in metric and imperial units, "
                f"{source_release_date}. This does not constitute an endorsement by Statistics Canada of this product."
            ),
        },
        "snapshot": {
            "path": output.name,
            "sha256": snapshot_sha256,
            "bytes": output.stat().st_size,
            "row_count": len(selected),
            "latest_periods_per_series": latest_periods,
            "province_counts": dict(sorted(province_counts.items())),
            "crop_counts": dict(sorted(crop_counts.items())),
            "statistic_counts": dict(sorted(statistic_counts.items())),
            "crop_aliases": _crop_aliases(),
            "scope": (
                "Latest available national/provincial metric area, yield, and production observations "
                "for crops supported by the local adapter. Missing and suppressed values are not imputed."
            ),
        },
        "decision_boundary": (
            "This portable snapshot is dated regional statistical context. It is not field-specific yield prediction, "
            "a market forecast, grower records, or a rate recommendation. Check the release date, reference period, "
            "status/symbol codes, and local farm records before acting."
        ),
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _download_source(url: str, *, timeout: int) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "open-agronomy-agent-statcan-snapshot/1.0"})
    temporary = tempfile.NamedTemporaryFile(prefix="statcan-32100359-", suffix=".zip", delete=False)
    path = Path(temporary.name)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, temporary:
            while block := response.read(1024 * 1024):
                temporary.write(block)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip")
    parser.add_argument("--source-url", default=SOURCE_ZIP_URL)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--latest-periods", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    downloaded = not bool(args.source_zip)
    source_zip = Path(args.source_zip).resolve() if args.source_zip else _download_source(args.source_url, timeout=args.timeout)
    try:
        report = build_snapshot(
            source_zip=source_zip,
            output=repo_path(args.output),
            manifest=repo_path(args.manifest),
            source_url=args.source_url,
            latest_periods=args.latest_periods,
        )
    finally:
        if downloaded:
            source_zip.unlink(missing_ok=True)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
