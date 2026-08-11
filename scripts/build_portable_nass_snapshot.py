#!/usr/bin/env python3
"""Build a compact no-key NASS crop-statistics snapshot from the official bulk file."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import itertools
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.paths import repo_path


DATASET_INDEX_URL = "https://www.nass.usda.gov/datasets/"
DEFAULT_COMMODITIES = (
    "BARLEY",
    "CANOLA",
    "CORN",
    "COTTON",
    "HAY",
    "OATS",
    "PEANUTS",
    "POTATOES",
    "RICE",
    "SORGHUM",
    "SOYBEANS",
    "SUGARBEETS",
    "SUNFLOWER",
    "WHEAT",
)
DEFAULT_STATISTICS = ("YIELD", "AREA HARVESTED", "PRODUCTION")


def discover_latest_crops_url(index_url: str = DATASET_INDEX_URL, *, timeout: int = 30) -> str:
    request = urllib.request.Request(index_url, headers={"User-Agent": "open-agronomy-agent-snapshot/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    matches = sorted(set(re.findall(r"qs\.crops_\d{8}\.txt\.gz", html)))
    if not matches:
        raise RuntimeError("USDA NASS dataset index did not expose a qs.crops_YYYYMMDD.txt.gz file")
    return urllib.request.urljoin(index_url, matches[-1])


def _canonical_row(row: dict[str, Any]) -> dict[str, str]:
    return {str(key or "").strip().upper(): str(value or "").strip() for key, value in row.items()}


def _include_bulk_row(
    row: dict[str, Any],
    *,
    commodities: set[str],
    statistics: set[str],
    min_year: int,
) -> bool:
    item = _canonical_row(row)
    if item.get("COMMODITY_DESC", "").upper() not in commodities:
        return False
    if item.get("STATISTICCAT_DESC", "").upper() not in statistics:
        return False
    if item.get("AGG_LEVEL_DESC", "").upper() != "STATE":
        return False
    if item.get("SOURCE_DESC", "").upper() != "SURVEY":
        return False
    if item.get("FREQ_DESC", "").upper() not in {"", "ANNUAL"}:
        return False
    if item.get("DOMAIN_DESC", "").upper() not in {"", "TOTAL"}:
        return False
    try:
        return int(item.get("YEAR", "0")) >= min_year
    except ValueError:
        return False


def _snapshot_row(row: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    item = _canonical_row(row)
    return {
        "commodity_desc": item.get("COMMODITY_DESC"),
        "year": int(item.get("YEAR") or 0),
        "short_desc": item.get("SHORT_DESC"),
        "statisticcat_desc": item.get("STATISTICCAT_DESC"),
        "unit_desc": item.get("UNIT_DESC"),
        "value": item.get("VALUE"),
        "agg_level_desc": item.get("AGG_LEVEL_DESC"),
        "state_alpha": item.get("STATE_ALPHA"),
        "county_name": item.get("COUNTY_NAME") or None,
        "domain_desc": item.get("DOMAIN_DESC"),
        "source_desc": item.get("SOURCE_DESC"),
        "reference_period_desc": item.get("REFERENCE_PERIOD_DESC"),
        "load_time": item.get("LOAD_TIME"),
        "source_url": source_url,
        "provenance": "usda_nass_quickstats_bulk_crops",
    }


def _iter_bulk_rows(response: Any) -> Iterable[dict[str, str]]:
    with gzip.GzipFile(fileobj=response) as compressed:
        text = io.TextIOWrapper(compressed, encoding="utf-8", errors="replace", newline="")
        first_line = text.readline()
        if not first_line:
            return
        delimiter = "\t" if first_line.count("\t") >= first_line.count("|") else "|"
        yield from csv.DictReader(itertools.chain([first_line], text), delimiter=delimiter)


def build_snapshot(
    *,
    source_url: str,
    output: Path,
    manifest: Path,
    commodities: tuple[str, ...],
    statistics: tuple[str, ...],
    min_year: int,
    timeout: int,
) -> dict[str, Any]:
    commodity_set = {item.upper() for item in commodities}
    statistic_set = {item.upper() for item in statistics}
    request = urllib.request.Request(source_url, headers={"User-Agent": "open-agronomy-agent-snapshot/1.0"})
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    row_count = 0
    state_counts: Counter[str] = Counter()
    crop_counts: Counter[str] = Counter()
    source_headers: dict[str, str | None] = {}
    hasher = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("w", encoding="utf-8") as handle:
        source_headers = {
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "content_length": response.headers.get("Content-Length"),
        }
        for row in _iter_bulk_rows(response):
            if not _include_bulk_row(
                row,
                commodities=commodity_set,
                statistics=statistic_set,
                min_year=min_year,
            ):
                continue
            payload = _snapshot_row(row, source_url=source_url)
            encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            handle.write(encoded.decode("utf-8"))
            hasher.update(encoded)
            row_count += 1
            state_counts[str(payload.get("state_alpha") or "UNKNOWN")] += 1
            crop_counts[str(payload.get("commodity_desc") or "UNKNOWN")] += 1
    if row_count == 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError("USDA NASS bulk stream produced no rows for the portable snapshot filters")
    partial.replace(output)
    report = {
        "schema_version": "open_agronomy_agent.portable_nass_snapshot.v1",
        "created_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "source_url": source_url,
        "source_index": DATASET_INDEX_URL,
        "source_headers": source_headers,
        "output": str(output),
        "sha256": hasher.hexdigest(),
        "row_count": row_count,
        "min_year": min_year,
        "commodities": sorted(commodity_set),
        "statistics": sorted(statistic_set),
        "state_counts": dict(sorted(state_counts.items())),
        "crop_counts": dict(sorted(crop_counts.items())),
        "scope": "State-level annual SURVEY rows with TOTAL domain only; county requests must be labeled as state fallback.",
        "license_boundary": "Official USDA NASS published statistics; preserve source, load time, suppression markers, units, and geography.",
    }
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url")
    parser.add_argument("--output", default="data/snapshots/nass_quickstats_state_crop_stats.jsonl")
    parser.add_argument("--manifest", default="data/snapshots/nass_quickstats_state_crop_stats_manifest.json")
    parser.add_argument("--years", type=int, default=12)
    parser.add_argument("--commodity", action="append", dest="commodities")
    parser.add_argument("--statistic", action="append", dest="statistics")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if args.years < 1:
        raise ValueError("--years must be at least 1")
    source_url = args.source_url or discover_latest_crops_url(timeout=args.timeout)
    report = build_snapshot(
        source_url=source_url,
        output=repo_path(args.output),
        manifest=repo_path(args.manifest),
        commodities=tuple(args.commodities or DEFAULT_COMMODITIES),
        statistics=tuple(args.statistics or DEFAULT_STATISTICS),
        min_year=dt.datetime.now(dt.UTC).year - args.years + 1,
        timeout=args.timeout,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
