from __future__ import annotations

import hashlib
import json
from typing import Any


TRACE_FIELD_SNAPSHOT_SCHEMA = "open_agronomy_agent.trace_field_snapshot.v1"
DATA_USE_SCHEMA = "open_agronomy_agent.data_use_statement.v1"
EXPORT_TRACE_SCHEMA = "open_agronomy_agent.export_trace.v1"

_TRACE_FIELDS = (
    "id",
    "display_name",
    "region_text",
    "country",
    "province_state",
    "county_rm",
    "crop_current",
    "crop_year",
    "soil_series_or_texture",
    "drainage_class",
    "irrigation_status",
    "soil_test_summary",
    "crop_rotation_notes",
    "management_notes",
    "known_constraints",
    "sensitivity",
    "created_at",
    "updated_at",
    "quality_meter",
)

_TRACE_METADATA_FIELDS = (
    "data_confidence",
    "source",
    "target_pest",
    "target_weed",
    "disease_or_symptom",
    "crop_stage",
    "yield_goal",
)

_LOCATION_KEYS = {
    "geometry",
    "geometry_geojson",
    "representative_point",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "lng",
    "coordinates",
    "boundary",
    "polygon",
}


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def minimized_field_context_snapshot(field_context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Create a useful trace snapshot without persisting exact geometry or owner identifiers."""
    if not isinstance(field_context, dict):
        return None
    snapshot = {
        key: field_context[key]
        for key in _TRACE_FIELDS
        if key in field_context and field_context[key] not in (None, "", [], {})
    }
    metadata = field_context.get("metadata")
    if isinstance(metadata, dict):
        safe_metadata = {
            key: metadata[key]
            for key in _TRACE_METADATA_FIELDS
            if key in metadata and metadata[key] not in (None, "", [], {})
        }
        if safe_metadata:
            snapshot["metadata"] = safe_metadata
    excluded = sorted(
        key
        for key in field_context
        if key not in _TRACE_FIELDS and key != "metadata"
        and (key.lower() in _LOCATION_KEYS or any(token in key.lower() for token in ("geometry", "coordinate")))
    )
    metadata_excluded = (
        sorted(
            key
            for key in metadata
            if key not in _TRACE_METADATA_FIELDS
            and (key.lower() in _LOCATION_KEYS or any(token in key.lower() for token in ("geometry", "coordinate")))
        )
        if isinstance(metadata, dict)
        else []
    )
    return {
        "schema_version": TRACE_FIELD_SNAPSHOT_SCHEMA,
        **snapshot,
        "source_snapshot_sha256": _canonical_sha256(field_context),
        "exact_geometry_included": False,
        "excluded_location_fields": sorted(set(excluded + metadata_excluded)),
    }


def minimized_export_trace_payload(export: dict[str, Any]) -> dict[str, Any]:
    """Keep export lineage in a trace without duplicating private object-store handles."""
    safe = {
        key: export[key]
        for key in (
            "id",
            "organization_id",
            "workspace_id",
            "thread_id",
            "created_by_user_id",
            "export_type",
            "redaction_status",
            "sha256",
            "created_at",
        )
        if key in export
    }
    metadata = dict(export.get("metadata") or {})
    files = metadata.get("files")
    if isinstance(files, dict):
        metadata["files"] = {
            str(name): {"object_store_uri_included": False}
            for name in sorted(files)
        }
    safe["metadata"] = metadata
    return {
        "schema_version": EXPORT_TRACE_SCHEMA,
        **safe,
        "internal_handles_included": False,
    }


def public_export_record(export: dict[str, Any]) -> dict[str, Any]:
    """Return export metadata suitable for an API response, excluding storage handles."""
    public = {
        key: value
        for key, value in export.items()
        if key != "storage_uri"
    }
    metadata = dict(public.get("metadata") or {})
    files = metadata.get("files")
    if isinstance(files, dict):
        metadata["files"] = {
            str(name): {"download_by_filename": True}
            for name in sorted(files)
        }
    public["metadata"] = metadata
    public["object_store_uris_included"] = False
    return public


def data_use_statement(*, network_mode: str, telemetry_enabled: bool) -> dict[str, Any]:
    return {
        "schema_version": DATA_USE_SCHEMA,
        "network": {
            "mode": network_mode,
            "external_calls_allowed": network_mode == "online",
            "offline_boundary": "Offline mode blocks public web and API adapters before any request is made.",
            "online_boundary": (
                "Online mode may send the minimum query and generalized location needed to explicitly invoked public "
                "weather, map, label, or government-data adapters; each call is recorded in the answer trace."
            ),
        },
        "workspace_data": {
            "access": "Workspace members authorized by the configured local or hosted identity boundary.",
            "purpose": "Answer continuity, field history, reproducibility, user-requested export, and explicit review.",
            "exact_geometry": "Kept in the field record; excluded from operational answer traces and ordinary thread exports.",
            "retention": "Retained until the user deletes the applicable record/account or an operator applies a configured policy.",
        },
        "training": {
            "default": "excluded",
            "requirement": "Explicit account/thread eligibility plus per-feedback consent and human review.",
            "benchmark_boundary": "Official hidden benchmark prompts and held-out evaluation rows are never training or retrieval data.",
        },
        "telemetry": {
            "enabled": telemetry_enabled,
            "default": "disabled",
            "content_boundary": "Telemetry must not include raw questions, answers, field notes, exact geometry, or uploaded files.",
        },
        "storage_security": {
            "application_database_encryption": "not_provided_by_local_sqlite_mode",
            "operator_requirement": "Use FileVault or equivalent full-volume encryption and private filesystem permissions.",
            "exports": "User-created exports can contain private data and must be handled as private files.",
        },
    }
