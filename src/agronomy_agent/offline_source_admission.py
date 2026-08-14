"""Fail-closed validation for the unadmitted Canadian offline-source queue.

This module intentionally has no runtime retrieval or ingestion integration.  The
queue records research targets and the gates required before a later, explicit
source-admission decision.  A record here is not permission to download,
derive, bundle, retrieve from, or train on a source.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from agronomy_agent.paths import repo_path


SCHEMA_VERSION = "open_agronomy_agent.canada_offline_source_admission_candidates.v1"
DEFAULT_MANIFEST_PATH = "data/manifests/canada_offline_source_admission_candidates_v1.json"

ROOT_FIELDS = {
    "schema_version",
    "generated_at",
    "status",
    "scope",
    "universal_boundary",
    "admission_gates",
    "candidate_sources",
}
UNIVERSAL_BOUNDARY_FIELDS = {
    "metadata_discovery",
    "runtime_admission",
    "download_or_fetch",
    "raw_bytes_present",
    "local_rag",
    "distributable_bundle",
    "model_training",
}
CANDIDATE_FIELDS = {
    "id",
    "category",
    "title",
    "publisher",
    "authority_type",
    "jurisdictions",
    "languages",
    "canonical_url",
    "source_identity",
    "candidate_resources",
    "source_characteristics",
    "rights",
    "training_rights",
    "proposed_use",
    "admission_state",
    "required_gate_ids",
    "limitations",
}
SOURCE_IDENTITY_FIELDS = {
    "identifier_type",
    "identifier",
    "identifier_status",
    "evidence_url",
}
CANDIDATE_RESOURCE_FIELDS = {"role", "url", "format", "status"}
SOURCE_CHARACTERISTIC_FIELDS = {"content_type", "spatial_linkage", "decision_role"}
RIGHTS_FIELDS = {
    "status",
    "licence_identifier",
    "evidence_url",
    "catalogue_licence_observed",
    "commercial_reuse_status",
    "redistribution_status",
    "third_party_rights_review_required",
    "notes",
}
TRAINING_RIGHTS_FIELDS = {"status", "source_specific_authorization", "notes"}
PROPOSED_USE_FIELDS = {
    "metadata_discovery",
    "download",
    "raw_snapshot",
    "derived_local_store",
    "runtime_lookup",
    "local_rag",
    "distributable_bundle",
    "training",
}
GATE_FIELDS = {"id", "title", "purpose"}

IDENTIFIER_TYPES = {"open_canada_dataset_id", "publisher_canonical_page"}
IDENTIFIER_STATUSES = {
    "official_catalogue_record_observed",
    "publisher_canonical_page_only",
}
RIGHTS_STATUSES = {
    "catalogue_open_licence_observed_pending_admission",
    "publisher_open_licence_observed_pending_resource_scope",
    "licence_scope_review_required",
    "permission_required",
}
TRAINING_RIGHTS_STATUS = "not_assessed_no_training_authorization"
ADMISSION_STATE = "candidate_not_admitted"
HTTPS_RE = re.compile(r"^https://[^\s]+$", re.IGNORECASE)
SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

EXPECTED_UNIVERSAL_BOUNDARY = {
    "metadata_discovery": True,
    "runtime_admission": False,
    "download_or_fetch": False,
    "raw_bytes_present": False,
    "local_rag": False,
    "distributable_bundle": False,
    "model_training": False,
}
EXPECTED_PROPOSED_USE = {
    "metadata_discovery": True,
    "download": False,
    "raw_snapshot": False,
    "derived_local_store": False,
    "runtime_lookup": False,
    "local_rag": False,
    "distributable_bundle": False,
    "training": False,
}
REQUIRED_CANDIDATE_GATES = {
    "exact_resource_and_byte_freeze",
    "rights_scope",
    "training_rights",
    "derivation_or_extraction_validation",
    "runtime_policy_admission",
}


def load_offline_source_admission_candidates(
    path: str | Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Load and fail closed on an invalid candidate-only source registry."""

    manifest_path = repo_path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"offline source admission manifest is missing: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"offline source admission manifest is invalid JSON: {exc}") from exc
    validate_offline_source_admission_candidates(payload)
    return payload


def validate_offline_source_admission_candidates(payload: Mapping[str, Any]) -> None:
    """Validate that every record remains a metadata-only, unadmitted candidate."""

    errors: list[str] = []
    if not isinstance(payload, Mapping):
        raise ValueError("offline source admission manifest must be an object")

    _check_exact_fields(payload, ROOT_FIELDS, "manifest", errors)
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if payload.get("status") != "candidate_research_queue_unadmitted":
        errors.append("manifest status must remain candidate_research_queue_unadmitted")
    _require_text(payload.get("generated_at"), "manifest.generated_at", errors)
    _require_text(payload.get("scope"), "manifest.scope", errors)

    boundary = payload.get("universal_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("manifest.universal_boundary must be an object")
    else:
        _check_exact_fields(boundary, UNIVERSAL_BOUNDARY_FIELDS, "manifest.universal_boundary", errors)
        if dict(boundary) != EXPECTED_UNIVERSAL_BOUNDARY:
            errors.append("manifest.universal_boundary must keep all material use disabled")

    gates = payload.get("admission_gates")
    gate_ids: set[str] = set()
    if not isinstance(gates, list) or not gates:
        errors.append("manifest.admission_gates must be a non-empty list")
    else:
        for index, gate in enumerate(gates):
            prefix = f"manifest.admission_gates[{index}]"
            if not isinstance(gate, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            _check_exact_fields(gate, GATE_FIELDS, prefix, errors)
            gate_id = _require_identifier(gate.get("id"), f"{prefix}.id", errors)
            _require_text(gate.get("title"), f"{prefix}.title", errors)
            _require_text(gate.get("purpose"), f"{prefix}.purpose", errors)
            if gate_id:
                if gate_id in gate_ids:
                    errors.append(f"duplicate admission gate id: {gate_id}")
                gate_ids.add(gate_id)

    candidates = payload.get("candidate_sources")
    if not isinstance(candidates, list) or not candidates:
        errors.append("manifest.candidate_sources must be a non-empty list")
        candidates = []
    source_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        _validate_candidate(candidate, index=index, gate_ids=gate_ids, source_ids=source_ids, errors=errors)

    if errors:
        raise ValueError("invalid offline source admission manifest: " + "; ".join(errors))


def source_admission_candidate_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a reportable summary after validation without changing admission state."""

    validate_offline_source_admission_candidates(payload)
    candidates = list(payload["candidate_sources"])
    return {
        "schema_version": payload["schema_version"],
        "status": payload["status"],
        "candidate_count": len(candidates),
        "categories": dict(sorted(Counter(row["category"] for row in candidates).items())),
        "rights_statuses": dict(sorted(Counter(row["rights"]["status"] for row in candidates).items())),
        "training_rights_statuses": dict(
            sorted(Counter(row["training_rights"]["status"] for row in candidates).items())
        ),
        "candidate_source_ids": [row["id"] for row in candidates],
        "all_material_use_disabled": all(
            row["proposed_use"] == EXPECTED_PROPOSED_USE for row in candidates
        ),
    }


def _validate_candidate(
    candidate: Any,
    *,
    index: int,
    gate_ids: set[str],
    source_ids: set[str],
    errors: list[str],
) -> None:
    prefix = f"manifest.candidate_sources[{index}]"
    if not isinstance(candidate, Mapping):
        errors.append(f"{prefix} must be an object")
        return
    _check_exact_fields(candidate, CANDIDATE_FIELDS, prefix, errors)
    source_id = _require_identifier(candidate.get("id"), f"{prefix}.id", errors)
    if source_id:
        if source_id in source_ids:
            errors.append(f"duplicate candidate source id: {source_id}")
        source_ids.add(source_id)
    for field in ("category", "title", "publisher", "authority_type"):
        _require_text(candidate.get(field), f"{prefix}.{field}", errors)
    _require_string_list(candidate.get("jurisdictions"), f"{prefix}.jurisdictions", errors)
    _require_string_list(candidate.get("languages"), f"{prefix}.languages", errors)
    _require_https(candidate.get("canonical_url"), f"{prefix}.canonical_url", errors)

    identity = candidate.get("source_identity")
    if not isinstance(identity, Mapping):
        errors.append(f"{prefix}.source_identity must be an object")
    else:
        _check_exact_fields(identity, SOURCE_IDENTITY_FIELDS, f"{prefix}.source_identity", errors)
        identifier_type = identity.get("identifier_type")
        if identifier_type not in IDENTIFIER_TYPES:
            errors.append(f"{prefix}.source_identity.identifier_type is invalid")
        identifier = _require_text(identity.get("identifier"), f"{prefix}.source_identity.identifier", errors)
        if identifier_type == "open_canada_dataset_id" and identifier and not UUID_RE.fullmatch(identifier):
            errors.append(f"{prefix}.source_identity.identifier must be an Open Canada UUID")
        if identity.get("identifier_status") not in IDENTIFIER_STATUSES:
            errors.append(f"{prefix}.source_identity.identifier_status is invalid")
        _require_https(identity.get("evidence_url"), f"{prefix}.source_identity.evidence_url", errors)

    resources = candidate.get("candidate_resources")
    if not isinstance(resources, list) or not resources:
        errors.append(f"{prefix}.candidate_resources must be a non-empty list")
    else:
        for resource_index, resource in enumerate(resources):
            resource_prefix = f"{prefix}.candidate_resources[{resource_index}]"
            if not isinstance(resource, Mapping):
                errors.append(f"{resource_prefix} must be an object")
                continue
            _check_exact_fields(resource, CANDIDATE_RESOURCE_FIELDS, resource_prefix, errors)
            _require_text(resource.get("role"), f"{resource_prefix}.role", errors)
            _require_https(resource.get("url"), f"{resource_prefix}.url", errors)
            _require_text(resource.get("format"), f"{resource_prefix}.format", errors)
            if resource.get("status") != "unfetched_candidate":
                errors.append(f"{resource_prefix}.status must remain unfetched_candidate")

    characteristics = candidate.get("source_characteristics")
    if not isinstance(characteristics, Mapping):
        errors.append(f"{prefix}.source_characteristics must be an object")
    else:
        _check_exact_fields(
            characteristics,
            SOURCE_CHARACTERISTIC_FIELDS,
            f"{prefix}.source_characteristics",
            errors,
        )
        for field in SOURCE_CHARACTERISTIC_FIELDS:
            _require_text(characteristics.get(field), f"{prefix}.source_characteristics.{field}", errors)

    rights = candidate.get("rights")
    if not isinstance(rights, Mapping):
        errors.append(f"{prefix}.rights must be an object")
    else:
        _check_exact_fields(rights, RIGHTS_FIELDS, f"{prefix}.rights", errors)
        if rights.get("status") not in RIGHTS_STATUSES:
            errors.append(f"{prefix}.rights.status is invalid")
        for field in (
            "licence_identifier",
            "commercial_reuse_status",
            "redistribution_status",
            "notes",
        ):
            _require_text(rights.get(field), f"{prefix}.rights.{field}", errors)
        _require_https(rights.get("evidence_url"), f"{prefix}.rights.evidence_url", errors)
        for field in ("catalogue_licence_observed", "third_party_rights_review_required"):
            if not isinstance(rights.get(field), bool):
                errors.append(f"{prefix}.rights.{field} must be boolean")

    training_rights = candidate.get("training_rights")
    if not isinstance(training_rights, Mapping):
        errors.append(f"{prefix}.training_rights must be an object")
    else:
        _check_exact_fields(
            training_rights,
            TRAINING_RIGHTS_FIELDS,
            f"{prefix}.training_rights",
            errors,
        )
        if training_rights.get("status") != TRAINING_RIGHTS_STATUS:
            errors.append(f"{prefix}.training_rights.status must remain {TRAINING_RIGHTS_STATUS}")
        if training_rights.get("source_specific_authorization") is not False:
            errors.append(f"{prefix}.training_rights.source_specific_authorization must be false")
        _require_text(training_rights.get("notes"), f"{prefix}.training_rights.notes", errors)

    proposed_use = candidate.get("proposed_use")
    if not isinstance(proposed_use, Mapping):
        errors.append(f"{prefix}.proposed_use must be an object")
    else:
        _check_exact_fields(proposed_use, PROPOSED_USE_FIELDS, f"{prefix}.proposed_use", errors)
        if dict(proposed_use) != EXPECTED_PROPOSED_USE:
            errors.append(f"{prefix}.proposed_use must keep all material use disabled")
    if candidate.get("admission_state") != ADMISSION_STATE:
        errors.append(f"{prefix}.admission_state must remain {ADMISSION_STATE}")

    required_gates = candidate.get("required_gate_ids")
    if not isinstance(required_gates, list) or not required_gates:
        errors.append(f"{prefix}.required_gate_ids must be a non-empty list")
    else:
        normalized_gates = {str(value) for value in required_gates}
        if len(normalized_gates) != len(required_gates):
            errors.append(f"{prefix}.required_gate_ids must not contain duplicates")
        unknown_gates = normalized_gates - gate_ids
        if unknown_gates:
            errors.append(f"{prefix}.required_gate_ids contains unknown gate(s): {sorted(unknown_gates)}")
        missing_gates = REQUIRED_CANDIDATE_GATES - normalized_gates
        if missing_gates:
            errors.append(f"{prefix}.required_gate_ids missing universal gate(s): {sorted(missing_gates)}")
    _require_string_list(candidate.get("limitations"), f"{prefix}.limitations", errors)


def _check_exact_fields(
    value: Mapping[str, Any], expected: set[str], label: str, errors: list[str]
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        errors.append(f"{label} missing field(s): {missing}")
    if unknown:
        errors.append(f"{label} has unsupported field(s): {unknown}")


def _require_text(value: Any, label: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} must be non-empty text")
        return ""
    return value.strip()


def _require_identifier(value: Any, label: str, errors: list[str]) -> str:
    identifier = _require_text(value, label, errors)
    if identifier and not SOURCE_ID_RE.fullmatch(identifier):
        errors.append(f"{label} must use lowercase stable identifier syntax")
    return identifier


def _require_https(value: Any, label: str, errors: list[str]) -> str:
    url = _require_text(value, label, errors)
    if url and not HTTPS_RE.fullmatch(url):
        errors.append(f"{label} must be an https URL")
    return url


def _require_string_list(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{label} must be a non-empty list")
        return
    if any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{label} must contain non-empty text values")
    if len({str(item) for item in value}) != len(value):
        errors.append(f"{label} must not contain duplicate values")
