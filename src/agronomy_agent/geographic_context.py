"""Bounded model context from server-recomputed Canadian boundary layers.

The spatial service can return rich polygon-intersection records.  This module
is deliberately narrower: it admits only three installed Canadian boundary
layers, after the server has bound a saved field to locally installed source
bytes.  It is an organizational aid for evidence and statistics, never a
field measurement, a legal boundary determination, or a retrieval override.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


TRUSTED_GEOGRAPHIC_CONTEXT_KEY = "_trusted_geographic_context"
TRUSTED_GEOGRAPHIC_CONTEXT_SCHEMA_VERSION = "open_agronomy_agent.trusted_geographic_context.v1"
_SERVER_BOUND_STATUS = "server_recomputed_bundled_source"
_AUTHORIZED_SNAPSHOT_STATUS = "stored_field_snapshot"
_SOURCE_KIND = "bundled_official_geospatial_layer"
_MAX_RECORDS_PER_LAYER = 2


_LAYER_CONTRACTS: dict[str, dict[str, Any]] = {
    "ca_statcan_2021_provinces_territories": {
        "label": "Province or territory",
        "source_label": "Statistics Canada 2021 cartographic boundary",
        "code_pattern": r"PR_\d{1,2}",
        "properties": (
            ("province_name", "province"),
            ("province_abbreviation", "abbreviation"),
            ("province_uid", "province UID"),
            ("dissemination_geography_id", "DGUID"),
        ),
    },
    "ca_statcan_2021_census_agricultural_regions": {
        "label": "Census Agricultural Region",
        "source_label": "Statistics Canada 2021 Census Agricultural Region boundary",
        "code_pattern": r"CAR_\d{4}",
        "properties": (
            ("census_agricultural_region", "region"),
            ("census_agricultural_region_code", "CAR code"),
            ("province_uid", "province UID"),
            ("dissemination_geography_id", "DGUID"),
        ),
    },
    "ca_aafc_terrestrial_ecoregions_v2_2": {
        "label": "Terrestrial ecoregion",
        "source_label": "AAFC National Ecological Framework",
        "code_pattern": r"ECOREGION_\d{1,4}",
        "properties": (
            ("ecoregion", "ecoregion"),
            ("ecoregion_id", "ecoregion ID"),
            ("ecozone_id", "ecozone ID"),
            ("ecoprovince_id", "ecoprovince ID"),
        ),
    },
}

TRUSTED_GEOGRAPHIC_LAYER_IDS = frozenset(_LAYER_CONTRACTS)


@dataclass(frozen=True)
class TrustedGeographicContext:
    """An in-process capability marker for a server-created projection.

    It is intentionally not a JSON mapping.  A client can submit a field
    context dictionary, but cannot create this object through the HTTP payload
    boundary.  Its stable string form keeps request hashing and trace capture
    deterministic without making a private marker part of a public schema.
    """

    records: tuple[dict[str, Any], ...]

    def __str__(self) -> str:
        return json.dumps(
            {
                "schema_version": TRUSTED_GEOGRAPHIC_CONTEXT_SCHEMA_VERSION,
                "source_kind": _SOURCE_KIND,
                "retrieval_scope": "not_applied",
                "records": self.records,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def attach_trusted_geographic_context(
    field_context: dict[str, Any] | None,
    *,
    field_access_authorized: bool,
    geo_context_binding_status: str | None,
) -> dict[str, Any] | None:
    """Attach a projection that only the authorized server turn can create.

    A browser may send ``regional_intersections`` for display, so those raw
    records alone never become core model context.  The caller must have an
    authorized saved-field binding, and every retained record must identify a
    server-recomputed bundled layer.  Any client-supplied private projection is
    removed before this decision.
    """

    if not isinstance(field_context, dict):
        return field_context
    projected = dict(field_context)
    projected.pop(TRUSTED_GEOGRAPHIC_CONTEXT_KEY, None)
    if not field_access_authorized or geo_context_binding_status != _AUTHORIZED_SNAPSHOT_STATUS:
        return projected

    records = _project_server_bound_intersections(projected.get("regional_intersections"))
    if not records:
        return projected
    projected[TRUSTED_GEOGRAPHIC_CONTEXT_KEY] = TrustedGeographicContext(records=tuple(records))
    return projected


def has_trusted_geographic_context(field_context: dict[str, Any] | None) -> bool:
    """Whether a field context carries a valid server-created projection."""

    return bool(_normalized_projection(field_context))


def trusted_geographic_layer_ids_for_context(field_context: dict[str, Any] | None) -> frozenset[str]:
    """Return the trusted layer IDs represented in a valid projection."""

    projection = _normalized_projection(field_context)
    if projection is None:
        return frozenset()
    return frozenset(str(record["layer_id"]) for record in projection["records"])


def format_trusted_geographic_context(field_context: dict[str, Any] | None) -> str | None:
    """Render the compact, provenance-labelled geographic packet for a model."""

    projection = _normalized_projection(field_context)
    if projection is None:
        return None

    lines = [
        "Trusted geographic context (server-recomputed installed official boundary pack; CONTEXT ONLY):",
        "- Role: organize regional evidence and geographic/statistical identifiers only.",
        "- Retrieval boundary: these labels do not expand document eligibility; explicit crop, jurisdiction, date, and geographic applicability still control use.",
        "- Field boundary: not a surveyed field boundary, field condition, soil property, crop-production or practice record, legal status, or management authorization.",
    ]
    records_by_layer: dict[str, list[dict[str, Any]]] = {
        layer_id: [] for layer_id in _LAYER_CONTRACTS
    }
    for record in projection["records"]:
        records_by_layer[record["layer_id"]].append(record)
    if any(len(records) > 1 for records in records_by_layer.values()):
        lines.append(
            "- Spatial ambiguity: a listed layer has multiple mapped overlaps; no single regional label is selected for that layer."
        )
    for layer_id, contract in _LAYER_CONTRACTS.items():
        records = records_by_layer[layer_id]
        if not records:
            continue
        if len(records) > 1:
            rendered_matches = "; ".join(_compact_match(record) for record in records)
            total = max(int(record.get("layer_match_count") or len(records)) for record in records)
            omitted = max(int(record.get("additional_matches_omitted") or 0) for record in records)
            suffix = f"; {omitted} additional overlap(s) not rendered" if omitted else ""
            lines.append(
                f"- {contract['label']} [{layer_id}]: multiple mapped intersections; "
                f"no single label selected: {rendered_matches}{suffix}."
            )
            continue
        record = records[0]
        details = [f"{record['name']} ({record['code']})"]
        for key, label in contract["properties"]:
            value = record["properties"].get(key)
            if value and str(value) != str(record["name"]) and key != "dissemination_geography_id":
                details.append(f"{label}={value}")
        coverage = record.get("coverage_estimate")
        if coverage is not None and coverage < 0.999999:
            details.append(f"mapped geometry coverage estimate={round(float(coverage) * 100)}%")
        lines.append(
            f"- {contract['label']} [{layer_id}]: "
            + "; ".join(details)
            + "."
        )
    return "\n".join(lines)


def _project_server_bound_intersections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    by_layer: dict[str, list[dict[str, Any]]] = {layer_id: [] for layer_id in _LAYER_CONTRACTS}
    seen_codes: dict[str, set[str]] = {layer_id: set() for layer_id in _LAYER_CONTRACTS}
    for item in value[:24]:
        if not isinstance(item, dict):
            continue
        layer_id = str(item.get("layer_id") or "").strip()
        contract = _LAYER_CONTRACTS.get(layer_id)
        if contract is None:
            continue
        if item.get("binding_status") != _SERVER_BOUND_STATUS or item.get("source") != _SOURCE_KIND:
            continue
        code = _code(item.get("code"), contract["code_pattern"])
        name = _text(item.get("name"), limit=120)
        if not code or not name:
            continue
        if code in seen_codes[layer_id]:
            continue
        properties = {
            key: value
            for key, _ in contract["properties"]
            if (value := _text(item.get(key), limit=120)) is not None
        }
        coverage = _coverage(item.get("coverage_estimate"))
        record: dict[str, Any] = {
            "layer_id": layer_id,
            "code": code,
            "name": name,
            "properties": properties,
        }
        if coverage is not None:
            record["coverage_estimate"] = coverage
        by_layer[layer_id].append(record)
        seen_codes[layer_id].add(code)

    records: list[dict[str, Any]] = []
    for layer_id in _LAYER_CONTRACTS:
        matches = by_layer[layer_id]
        total = len(matches)
        for record in matches[:_MAX_RECORDS_PER_LAYER]:
            if total > 1:
                record["layer_match_count"] = total
            if total > _MAX_RECORDS_PER_LAYER:
                record["additional_matches_omitted"] = total - _MAX_RECORDS_PER_LAYER
            records.append(record)
    return records


def _normalized_projection(field_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(field_context, dict):
        return None
    value = field_context.get(TRUSTED_GEOGRAPHIC_CONTEXT_KEY)
    if not isinstance(value, TrustedGeographicContext):
        return None
    normalized_records = _project_projection_records(value.records)
    if not normalized_records:
        return None
    return {"records": normalized_records}


def _project_projection_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    normalized_by_layer: dict[str, list[dict[str, Any]]] = {layer_id: [] for layer_id in _LAYER_CONTRACTS}
    seen_codes: dict[str, set[str]] = {layer_id: set() for layer_id in _LAYER_CONTRACTS}
    for item in value[: len(_LAYER_CONTRACTS) * _MAX_RECORDS_PER_LAYER]:
        if not isinstance(item, dict):
            continue
        layer_id = str(item.get("layer_id") or "").strip()
        contract = _LAYER_CONTRACTS.get(layer_id)
        if contract is None:
            continue
        code = _code(item.get("code"), contract["code_pattern"])
        name = _text(item.get("name"), limit=120)
        raw_properties = item.get("properties")
        if not code or code in seen_codes[layer_id] or not name or not isinstance(raw_properties, dict):
            continue
        properties = {
            key: text
            for key, _ in contract["properties"]
            if (text := _text(raw_properties.get(key), limit=120)) is not None
        }
        record: dict[str, Any] = {
            "layer_id": layer_id,
            "code": code,
            "name": name,
            "properties": properties,
        }
        coverage = _coverage(item.get("coverage_estimate"))
        if coverage is not None:
            record["coverage_estimate"] = coverage
        layer_match_count = item.get("layer_match_count")
        if isinstance(layer_match_count, int) and not isinstance(layer_match_count, bool) and layer_match_count > 1:
            record["layer_match_count"] = layer_match_count
        additional_matches_omitted = item.get("additional_matches_omitted")
        if (
            isinstance(additional_matches_omitted, int)
            and not isinstance(additional_matches_omitted, bool)
            and additional_matches_omitted > 0
        ):
            record["additional_matches_omitted"] = additional_matches_omitted
        normalized_by_layer[layer_id].append(record)
        seen_codes[layer_id].add(code)

    return [
        record
        for layer_id in _LAYER_CONTRACTS
        for record in normalized_by_layer[layer_id][:_MAX_RECORDS_PER_LAYER]
    ]


def _compact_match(record: dict[str, Any]) -> str:
    coverage = record.get("coverage_estimate")
    coverage_text = (
        f", {round(float(coverage) * 100)}% mapped geometry coverage"
        if coverage is not None
        else ""
    )
    return f"{record['name']} ({record['code']}{coverage_text})"


def _code(value: Any, pattern: str) -> str | None:
    text = _text(value, limit=48)
    if text is None or not re.fullmatch(pattern, text):
        return None
    return text


def _text(value: Any, *, limit: int) -> str | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = " ".join(str(value).split())
    return text[:limit] if text else None


def _coverage(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    normalized = float(value)
    if not 0 <= normalized <= 1:
        return None
    return round(normalized, 6)
