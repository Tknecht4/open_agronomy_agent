#!/usr/bin/env python3
"""Validate the fail-closed national 100 m soil tile candidate manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data/manifests/canada_100m_soil_tile_candidate.json"
REQUIRED_PROVINCES = {
    "British Columbia", "Alberta", "Saskatchewan", "Manitoba", "Ontario", "Quebec",
    "New Brunswick", "Nova Scotia", "Prince Edward Island", "Newfoundland and Labrador",
}
REQUIRED_PROPERTIES = {
    "soil_great_group_probability", "ph", "sand_silt_clay", "soil_organic_carbon",
    "bulk_density", "cation_exchange_capacity",
}
REQUIRED_CONTINUOUS_STATISTICS = {"predicted_value", "q05", "q95"}
ALLOWED_TILE_STATUS = {"missing", "downloaded_unverified", "derived_unvalidated", "validated"}


def validate(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != "open_agronomy_agent.national_soil_tile_candidate.v1":
        errors.append("unsupported schema_version")
    soil = payload.get("soil_source") or {}
    if soil.get("record_id") != "4d39c9f9-a85c-4bf2-b920-138fdd423384":
        errors.append("soil source record is not the pinned official 100 m product")
    if soil.get("wcs_capabilities_url") != (
        "https://sis.agr.gc.ca/geoserver/ows/"
        "?service=WCS&acceptversions=2.0.1&request=GetCapabilities"
    ):
        errors.append("soil source does not pin the official CanSIS WCS capabilities endpoint")
    mask_ids = {str(row.get("source_id")) for row in payload.get("mask_sources") or []}
    if mask_ids != {"ca_aafc_annual_crop_inventory_2025", "ca_aafc_land_use_2020"}:
        errors.append("mask sources must be the pinned ACI 2025 and AAFC Land Use 2020 records")
    properties = set(payload.get("required_property_families") or [])
    if properties != REQUIRED_PROPERTIES:
        errors.append("required property families are incomplete or unexpected")
    statistics = set(payload.get("required_continuous_property_statistics") or [])
    if statistics != REQUIRED_CONTINUOUS_STATISTICS:
        errors.append("continuous statistics must be predicted_value plus q05 and q95")
    value_contract = payload.get("published_value_contract") or {}
    if value_contract.get("continuous_property_point_estimate") != "predicted_value":
        errors.append("published continuous point estimate must not be relabelled as q50")
    if set(value_contract.get("continuous_property_uncertainty") or []) != {"q05", "q95"}:
        errors.append("published continuous uncertainty must be q05 and q95")
    if value_contract.get("silt_uncertainty") != "not_published_do_not_invent":
        errors.append("silt uncertainty must remain explicitly unavailable")
    province_rows = payload.get("required_provinces") or []
    provinces = {str(row.get("province")) for row in province_rows}
    if provinces != REQUIRED_PROVINCES or len(province_rows) != len(REQUIRED_PROVINCES):
        errors.append("province coverage matrix must contain each crop-producing province exactly once")
    invalid_status = sorted(
        str(row.get("tile_status")) for row in province_rows
        if row.get("tile_status") not in ALLOWED_TILE_STATUS
    )
    if invalid_status:
        errors.append(f"invalid tile statuses: {invalid_status}")
    validated = sorted(str(row.get("province")) for row in province_rows if row.get("tile_status") == "validated")
    missing = sorted(REQUIRED_PROVINCES - set(validated))
    required_lineage = set((payload.get("tile_contract") or {}).get("required_lineage_fields") or [])
    if not {
        "source_sha256", "wcs_capabilities_sha256", "mask_source_sha256", "property",
        "units", "statistic", "request_bounds", "output_sha256",
    } <= required_lineage:
        errors.append("tile lineage contract is incomplete")
    promotion_eligible = not errors and not missing and payload.get("promotion_eligible") is True
    if payload.get("promotion_eligible") is True and missing:
        errors.append("promotion_eligible cannot be true while required province tiles are missing")
        promotion_eligible = False
    return {
        "schema_version": "open_agronomy_agent.national_soil_tile_validation.v1",
        "status": "valid_candidate_blocked" if not errors and not promotion_eligible else "pass" if promotion_eligible else "invalid",
        "manifest_path": str(path),
        "validated_provinces": validated,
        "missing_or_unvalidated_provinces": missing,
        "promotion_eligible": promotion_eligible,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate(args.manifest.resolve())
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if report["status"] == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
