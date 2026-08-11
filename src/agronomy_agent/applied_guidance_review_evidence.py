from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agronomy_agent.artifact_signature import verify_manifest_signature
from agronomy_agent.knowledge_update_trust import ed25519_public_key_id


REVIEWER_REGISTRY_SCHEMA = (
    "open_agronomy_agent.applied_guidance_reviewer_registry.v1"
)
ASSIGNMENT_SCHEMA = (
    "open_agronomy_agent.applied_guidance_review_assignment.v1"
)
SIGNED_REVIEW_SCHEMA = "open_agronomy_agent.applied_guidance_signed_review.v1"
VERIFICATION_SCHEMA = (
    "open_agronomy_agent.applied_guidance_review_evidence_verification.v1"
)
PACKET_REGISTRY_SCHEMA = (
    "open_agronomy_agent.applied_guidance_review_packet_registry.v1"
)
MAX_FUTURE_CLOCK_SKEW = dt.timedelta(minutes=5)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class PacketSpec:
    jurisdiction: str
    candidate_schema: str
    review_fields: tuple[str, ...]
    required_specialist_roles: frozenset[str]


PACKET_SPECS = {
    "open_agronomy_agent.bc_aem_nap_packet.v1": PacketSpec(
        jurisdiction="British Columbia",
        candidate_schema="open_agronomy_agent.bc_aem_nap_candidate.v1",
        review_fields=(
            "exact_source_pages_compared",
            "factual_accuracy",
            "numbers_units_accurate",
            "all_conditions_logic_preserved",
            "section_locators_accurate",
            "jurisdiction_preserved",
            "regulatory_meaning_accurate",
            "not_legal_or_agronomic_advice",
            "official_currentness_rechecked",
            "2026_section_56_57_amendment_excluded",
            "area_map_and_test_method_boundary_preserved",
            "kings_printer_attribution_present",
            "third_party_material_excluded",
        ),
        required_specialist_roles=frozenset(
            {
                "independent_bc_nutrient_management_specialist",
                "independent_bc_regulatory_plain_language_reviewer",
            }
        ),
    ),
    "open_agronomy_agent.alberta_applied_guidance_packet.v1": PacketSpec(
        jurisdiction="Alberta",
        candidate_schema=(
            "open_agronomy_agent.alberta_applied_guidance_candidate.v1"
        ),
        review_fields=(
            "exact_source_pages_compared",
            "factual_accuracy",
            "numbers_units_accurate",
            "qualifiers_preserved",
            "legal_scope_preserved",
            "jurisdiction_preserved",
            "agronomic_meaning_accurate",
            "official_symbols_excluded",
            "third_party_material_excluded",
            "no_unstated_application_rate",
            "live_authority_boundary_adequate",
        ),
        required_specialist_roles=frozenset({"independent_agronomist"}),
    ),
    "open_agronomy_agent.manitoba_applied_guidance_packet.v1": PacketSpec(
        jurisdiction="Manitoba",
        candidate_schema=(
            "open_agronomy_agent.manitoba_applied_guidance_candidate.v1"
        ),
        review_fields=(
            "exact_source_pages_compared",
            "factual_accuracy",
            "numbers_units_accurate",
            "qualifiers_preserved",
            "jurisdiction_preserved",
            "agronomic_meaning_accurate",
            "product_rate_material_excluded",
            "third_party_material_excluded",
            "regulatory_boundary_adequate",
        ),
        required_specialist_roles=frozenset({"independent_agronomist"}),
    ),
    "open_agronomy_agent.manitoba_fertilizer_check_stamp_packet.v1": PacketSpec(
        jurisdiction="Manitoba",
        candidate_schema=(
            "open_agronomy_agent.manitoba_fertilizer_check_stamp_candidate.v1"
        ),
        review_fields=(
            "exact_source_pages_compared",
            "factual_accuracy",
            "numbers_units_accurate",
            "qualifiers_preserved",
            "jurisdiction_preserved",
            "agronomic_meaning_accurate",
            "not_a_rate_recommendation",
            "third_party_material_excluded",
            "currentness_acceptable_for_bounded_method",
        ),
        required_specialist_roles=frozenset(
            {"independent_soil_fertility_specialist"}
        ),
    ),
    "open_agronomy_agent.manitoba_stored_grain_packet.v1": PacketSpec(
        jurisdiction="Manitoba",
        candidate_schema=(
            "open_agronomy_agent.manitoba_stored_grain_candidate.v1"
        ),
        review_fields=(
            "exact_source_compared",
            "factual_accuracy",
            "numbers_units_accurate",
            "qualifiers_preserved",
            "jurisdiction_preserved",
            "agronomic_meaning_accurate",
            "nonchemical_boundary_preserved",
            "third_party_material_excluded",
            "currentness_acceptable_for_bounded_method",
        ),
        required_specialist_roles=frozenset(
            {
                "independent_stored_product_entomologist",
                "independent_grain_storage_specialist",
            }
        ),
    ),
}


class ReviewEvidenceBlocked(ValueError):
    def __init__(self, blockers: list[str]):
        self.blockers = blockers
        super().__init__("; ".join(blockers))


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_repo_path(repo_root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str):
        raise ReviewEvidenceBlocked([f"{field}_path_invalid"])
    posix = PurePosixPath(value)
    if (
        posix.is_absolute()
        or not posix.parts
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ReviewEvidenceBlocked([f"{field}_path_invalid"])
    root = repo_root.resolve()
    path = (root / Path(*posix.parts)).resolve()
    if root != path and root not in path.parents:
        raise ReviewEvidenceBlocked([f"{field}_path_escape"])
    return path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewEvidenceBlocked([f"{label}_invalid:{exc}"]) from exc
    if not isinstance(payload, dict):
        raise ReviewEvidenceBlocked([f"{label}_root_not_object"])
    return payload


def _load_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"row {line_number} is not an object")
            rows.append(row)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ReviewEvidenceBlocked([f"{label}_invalid:{exc}"]) from exc
    return rows


def _parse_time(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ReviewEvidenceBlocked([f"{field}_invalid"])
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewEvidenceBlocked([f"{field}_invalid"]) from exc
    if parsed.tzinfo is None:
        raise ReviewEvidenceBlocked([f"{field}_timezone_missing"])
    return parsed.astimezone(dt.UTC)


def _coerce_now(value: dt.datetime | None) -> dt.datetime:
    current = value or dt.datetime.now(dt.UTC)
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    return current.astimezone(dt.UTC)


def _validate_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ReviewEvidenceBlocked([f"{field}_invalid"])
    return value


def _validate_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ReviewEvidenceBlocked([f"{field}_invalid"])
    return value


def _load_public_key_pem(value: Any, field: str) -> ed25519.Ed25519PublicKey:
    if not isinstance(value, str):
        raise ReviewEvidenceBlocked([f"{field}_invalid"])
    try:
        key = serialization.load_pem_public_key(value.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ReviewEvidenceBlocked([f"{field}_invalid"]) from exc
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise ReviewEvidenceBlocked([f"{field}_not_ed25519"])
    return key


def _candidate_set_sha256(
    candidates: dict[str, dict[str, Any]],
) -> str:
    return _sha256_bytes(
        _canonical(
            [
                {
                    "candidate_id": candidate_id,
                    "candidate_sha256": row["candidate_sha256"],
                    "packet_manifest_sha256": row["packet_manifest_sha256"],
                }
                for candidate_id, row in sorted(candidates.items())
            ]
        )
    )


def _load_expected_candidates(
    *,
    repo_root: Path,
    packet_registry: dict[str, Any],
    jurisdiction: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    groups = [
        group
        for group in packet_registry.get("packet_groups") or []
        if isinstance(group, dict) and group.get("jurisdiction") == jurisdiction
    ]
    if len(groups) != 1:
        raise ReviewEvidenceBlocked(["packet_group_missing_or_duplicate"])
    group = groups[0]
    manifests = group.get("validation_manifests")
    if not isinstance(manifests, list) or not manifests:
        raise ReviewEvidenceBlocked(["packet_group_manifest_inventory_invalid"])
    candidates: dict[str, dict[str, Any]] = {}
    for manifest_ref in manifests:
        if not isinstance(manifest_ref, dict):
            raise ReviewEvidenceBlocked(["packet_manifest_reference_invalid"])
        manifest_path = _safe_repo_path(
            repo_root, manifest_ref.get("path"), "packet_manifest"
        )
        expected_manifest_sha = _validate_sha256(
            manifest_ref.get("sha256"), "packet_manifest_sha256"
        )
        if (
            not manifest_path.is_file()
            or sha256_path(manifest_path) != expected_manifest_sha
        ):
            raise ReviewEvidenceBlocked(["packet_manifest_binding_invalid"])
        manifest = _load_json(manifest_path, "packet_manifest")
        spec = PACKET_SPECS.get(str(manifest.get("schema_version") or ""))
        if spec is None:
            raise ReviewEvidenceBlocked(["packet_schema_unsupported"])
        if (
            spec.jurisdiction != jurisdiction
            or (manifest.get("candidates") or {}).get("jurisdictions")
            != [jurisdiction]
        ):
            raise ReviewEvidenceBlocked(["packet_jurisdiction_invalid"])
        for source_key in ("source_manifest", "source"):
            source_ref = manifest.get(source_key)
            if not isinstance(source_ref, dict):
                continue
            source_path = _safe_repo_path(
                repo_root, source_ref.get("path"), source_key
            )
            source_sha = _validate_sha256(
                source_ref.get("sha256"), f"{source_key}_sha256"
            )
            if (
                not source_path.is_file()
                or sha256_path(source_path) != source_sha
            ):
                raise ReviewEvidenceBlocked(
                    [f"{source_key}_binding_invalid"]
                )
        promotion_gate = manifest.get("promotion_gate") or {}
        allowed_reviewer_roles = promotion_gate.get("allowed_reviewer_roles")
        if (
            promotion_gate.get("runtime_admission_before_gate") is not False
            or int(promotion_gate.get("reviewers_per_candidate") or 0) != 2
            or not isinstance(allowed_reviewer_roles, list)
            or not allowed_reviewer_roles
            or len(allowed_reviewer_roles) != len(set(allowed_reviewer_roles))
        ):
            raise ReviewEvidenceBlocked(["packet_promotion_boundary_invalid"])
        candidate_ref = manifest.get("candidates") or {}
        candidate_path = _safe_repo_path(
            manifest_path.parent,
            candidate_ref.get("path"),
            "candidate_artifact",
        )
        expected_candidate_file_sha = _validate_sha256(
            candidate_ref.get("sha256"), "candidate_artifact_sha256"
        )
        if (
            not candidate_path.is_file()
            or sha256_path(candidate_path) != expected_candidate_file_sha
        ):
            raise ReviewEvidenceBlocked(["candidate_artifact_binding_invalid"])
        rows = _load_jsonl(candidate_path, "candidate_artifact")
        if (
            len(rows) != int(candidate_ref.get("row_count") or 0)
            or len(rows) != int(manifest_ref.get("candidate_count") or 0)
        ):
            raise ReviewEvidenceBlocked(["candidate_artifact_row_count_invalid"])
        for row in rows:
            candidate_id = _validate_id(row.get("candidate_id"), "candidate_id")
            if candidate_id in candidates:
                raise ReviewEvidenceBlocked(
                    [f"candidate_id_duplicate:{candidate_id}"]
                )
            if row.get("schema_version") != spec.candidate_schema:
                raise ReviewEvidenceBlocked(
                    [f"candidate_schema_invalid:{candidate_id}"]
                )
            if row.get("jurisdiction") != [jurisdiction]:
                raise ReviewEvidenceBlocked(
                    [f"candidate_jurisdiction_invalid:{candidate_id}"]
                )
            claimed = _validate_sha256(
                row.get("candidate_sha256"), "candidate_sha256"
            )
            unsigned = dict(row)
            unsigned.pop("candidate_sha256", None)
            if _sha256_bytes(_canonical(unsigned)) != claimed:
                raise ReviewEvidenceBlocked(
                    [f"candidate_self_hash_invalid:{candidate_id}"]
                )
            if row.get("runtime_admission_status") not in {
                "quarantined_pending_independent_review",
                "candidate_pending_independent_review",
            }:
                raise ReviewEvidenceBlocked(
                    [f"candidate_quarantine_invalid:{candidate_id}"]
                )
            source_fields = (
                ("source_pdf_path", "source_pdf_sha256")
                if row.get("source_pdf_path")
                else ("source_html_path", "source_html_sha256")
            )
            source_path = _safe_repo_path(
                repo_root, row.get(source_fields[0]), "candidate_source"
            )
            source_sha = _validate_sha256(
                row.get(source_fields[1]), "candidate_source_sha256"
            )
            if not source_path.is_file() or sha256_path(source_path) != source_sha:
                raise ReviewEvidenceBlocked(
                    [f"candidate_source_binding_invalid:{candidate_id}"]
                )
            if row.get("semantic_companion_path"):
                companion_path = _safe_repo_path(
                    repo_root,
                    row.get("semantic_companion_path"),
                    "semantic_companion",
                )
                companion_sha = _validate_sha256(
                    row.get("semantic_companion_sha256"),
                    "semantic_companion_sha256",
                )
                if (
                    not companion_path.is_file()
                    or sha256_path(companion_path) != companion_sha
                ):
                    raise ReviewEvidenceBlocked(
                        [
                            "semantic_companion_binding_invalid:"
                            f"{candidate_id}"
                        ]
                    )
            source_manifest_ref = manifest.get("source_manifest")
            if isinstance(source_manifest_ref, dict) and (
                row.get("source_manifest_path")
                != source_manifest_ref.get("path")
                or row.get("source_manifest_sha256")
                != source_manifest_ref.get("sha256")
                or (source_manifest_ref.get("source_pdf_hashes") or {}).get(
                    row.get("source_id")
                )
                != row.get("source_pdf_sha256")
            ):
                raise ReviewEvidenceBlocked(
                    [f"candidate_source_manifest_invalid:{candidate_id}"]
                )
            candidates[candidate_id] = {
                "candidate_id": candidate_id,
                "candidate_sha256": claimed,
                "packet_manifest_sha256": expected_manifest_sha,
                "candidate_artifact_sha256": expected_candidate_file_sha,
                "packet_schema": manifest["schema_version"],
                "review_fields": list(spec.review_fields),
                "allowed_reviewer_roles": list(allowed_reviewer_roles),
                "required_specialist_roles": sorted(
                    spec.required_specialist_roles
                ),
                "candidate": row,
            }
    expected_count = int((group.get("candidates") or {}).get("count") or 0)
    if expected_count < 1 or len(candidates) != expected_count:
        raise ReviewEvidenceBlocked(
            [
                "candidate_group_count_invalid:"
                f"expected={expected_count}:actual={len(candidates)}"
            ]
        )
    if int(group.get("required_independent_reviews") or 0) != len(candidates) * 2:
        raise ReviewEvidenceBlocked(["required_review_count_invalid"])
    return candidates, group


def verify_group_review_evidence(
    *,
    repo_root: Path,
    packet_registry_path: Path,
    expected_packet_registry_sha256: str,
    evidence_dir: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    jurisdiction: str = "Manitoba",
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Verify signed review evidence; it does not prove real-world credentials."""

    checked_at = _coerce_now(now)
    repo_root = repo_root.resolve()
    packet_registry_path = packet_registry_path.resolve()
    evidence_dir = evidence_dir.resolve()
    coordinator_public_key_path = coordinator_public_key_path.resolve()
    expected_packet_registry_sha256 = _validate_sha256(
        expected_packet_registry_sha256, "expected_packet_registry_sha256"
    )
    expected_coordinator_public_key_sha256 = _validate_sha256(
        expected_coordinator_public_key_sha256,
        "expected_coordinator_public_key_sha256",
    )
    if (
        not packet_registry_path.is_file()
        or sha256_path(packet_registry_path) != expected_packet_registry_sha256
    ):
        raise ReviewEvidenceBlocked(["packet_registry_pin_mismatch"])
    packet_registry = _load_json(packet_registry_path, "packet_registry")
    if packet_registry.get("schema_version") != PACKET_REGISTRY_SCHEMA:
        raise ReviewEvidenceBlocked(["packet_registry_schema_invalid"])
    candidates, packet_group = _load_expected_candidates(
        repo_root=repo_root,
        packet_registry=packet_registry,
        jurisdiction=jurisdiction,
    )
    if (
        not coordinator_public_key_path.is_file()
        or sha256_path(coordinator_public_key_path)
        != expected_coordinator_public_key_sha256
    ):
        raise ReviewEvidenceBlocked(["coordinator_public_key_pin_mismatch"])

    registry_path = evidence_dir / "reviewer_registry.json"
    registry_signature_path = evidence_dir / "reviewer_registry.sig"
    registry_signature = verify_manifest_signature(
        manifest=registry_path,
        signature=registry_signature_path,
        public_key=coordinator_public_key_path,
    )
    if not registry_signature["verified"]:
        raise ReviewEvidenceBlocked(["reviewer_registry_signature_invalid"])
    reviewer_registry = _load_json(registry_path, "reviewer_registry")
    if reviewer_registry.get("schema_version") != REVIEWER_REGISTRY_SCHEMA:
        raise ReviewEvidenceBlocked(["reviewer_registry_schema_invalid"])
    if reviewer_registry.get("jurisdiction") != jurisdiction:
        raise ReviewEvidenceBlocked(["reviewer_registry_jurisdiction_invalid"])
    registry_issued = _parse_time(
        reviewer_registry.get("issued_at"), "reviewer_registry_issued_at"
    )
    registry_expires = _parse_time(
        reviewer_registry.get("expires_at"), "reviewer_registry_expires_at"
    )
    if (
        registry_issued > checked_at + MAX_FUTURE_CLOCK_SKEW
        or checked_at >= registry_expires
        or registry_expires <= registry_issued
    ):
        raise ReviewEvidenceBlocked(["reviewer_registry_validity_invalid"])
    reviewer_registry_sha = sha256_path(registry_path)
    reviewers: dict[str, dict[str, Any]] = {}
    key_ids: set[str] = set()
    for row in reviewer_registry.get("reviewers") or []:
        if not isinstance(row, dict):
            raise ReviewEvidenceBlocked(["reviewer_registry_row_invalid"])
        reviewer_id = _validate_id(row.get("reviewer_id"), "reviewer_id")
        if reviewer_id in reviewers:
            raise ReviewEvidenceBlocked(
                [f"reviewer_id_duplicate:{reviewer_id}"]
            )
        key = _load_public_key_pem(
            row.get("public_key_pem"), f"reviewer_public_key:{reviewer_id}"
        )
        key_id = ed25519_public_key_id(key)
        if row.get("key_id") != key_id:
            raise ReviewEvidenceBlocked(
                [f"reviewer_key_id_mismatch:{reviewer_id}"]
            )
        if key_id in key_ids:
            raise ReviewEvidenceBlocked([f"reviewer_key_reused:{key_id}"])
        key_ids.add(key_id)
        roles = row.get("authorized_roles")
        independence = row.get("independence_attestation") or {}
        if (
            row.get("status") != "active"
            or not isinstance(roles, list)
            or not roles
            or len(roles) != len(set(roles))
            or not str(row.get("credential_basis") or "").strip()
            or independence.get("independent_of_development") is not True
            or independence.get("developer_contributor") is not False
            or not isinstance(independence.get("conflicts_disclosed"), list)
        ):
            raise ReviewEvidenceBlocked(
                [f"reviewer_attestation_invalid:{reviewer_id}"]
            )
        reviewers[reviewer_id] = {
            "key": key,
            "key_id": key_id,
            "roles": set(roles),
        }
    if len(reviewers) < 2:
        raise ReviewEvidenceBlocked(["reviewer_registry_too_small"])

    assignment_path = evidence_dir / "review_assignment.json"
    assignment_signature_path = evidence_dir / "review_assignment.sig"
    assignment_signature = verify_manifest_signature(
        manifest=assignment_path,
        signature=assignment_signature_path,
        public_key=coordinator_public_key_path,
    )
    if not assignment_signature["verified"]:
        raise ReviewEvidenceBlocked(["review_assignment_signature_invalid"])
    assignment = _load_json(assignment_path, "review_assignment")
    if assignment.get("schema_version") != ASSIGNMENT_SCHEMA:
        raise ReviewEvidenceBlocked(["review_assignment_schema_invalid"])
    assignment_id = _validate_id(
        assignment.get("assignment_id"), "assignment_id"
    )
    if (
        assignment.get("packet_group_id") != packet_group.get("packet_id")
        or assignment.get("jurisdiction") != jurisdiction
        or assignment.get("reviewer_registry_sha256")
        != reviewer_registry_sha
        or assignment.get("packet_registry_sha256")
        != expected_packet_registry_sha256
        or assignment.get("candidate_set_sha256")
        != _candidate_set_sha256(candidates)
    ):
        raise ReviewEvidenceBlocked(["review_assignment_binding_invalid"])
    window = assignment.get("review_window") or {}
    opens_at = _parse_time(window.get("opens_at"), "review_window_opens_at")
    closes_at = _parse_time(window.get("closes_at"), "review_window_closes_at")
    if closes_at <= opens_at or checked_at < opens_at - MAX_FUTURE_CLOCK_SKEW:
        raise ReviewEvidenceBlocked(["review_window_invalid"])
    assigned: dict[str, tuple[str, ...]] = {}
    for row in assignment.get("candidates") or []:
        if not isinstance(row, dict):
            raise ReviewEvidenceBlocked(["review_assignment_candidate_invalid"])
        candidate_id = str(row.get("candidate_id") or "")
        expected = candidates.get(candidate_id)
        reviewer_ids = row.get("reviewer_ids")
        if (
            expected is None
            or row.get("candidate_sha256") != expected["candidate_sha256"]
            or row.get("packet_manifest_sha256")
            != expected["packet_manifest_sha256"]
            or not isinstance(reviewer_ids, list)
            or len(reviewer_ids) != 2
            or len(set(reviewer_ids)) != 2
            or any(reviewer_id not in reviewers for reviewer_id in reviewer_ids)
        ):
            raise ReviewEvidenceBlocked(
                [f"review_assignment_candidate_invalid:{candidate_id}"]
            )
        if candidate_id in assigned:
            raise ReviewEvidenceBlocked(
                [f"review_assignment_candidate_duplicate:{candidate_id}"]
            )
        if len({reviewers[item]["key_id"] for item in reviewer_ids}) != 2:
            raise ReviewEvidenceBlocked(
                [f"review_assignment_keys_not_distinct:{candidate_id}"]
            )
        assigned[candidate_id] = tuple(reviewer_ids)
    if set(assigned) != set(candidates):
        raise ReviewEvidenceBlocked(["review_assignment_candidate_set_mismatch"])

    reviews_dir = evidence_dir / "reviews"
    if not reviews_dir.is_dir():
        raise ReviewEvidenceBlocked(["signed_reviews_directory_missing"])
    expected_pairs = {
        (candidate_id, reviewer_id)
        for candidate_id, reviewer_ids in assigned.items()
        for reviewer_id in reviewer_ids
    }
    valid_pairs: set[tuple[str, str]] = set()
    roles_by_candidate: dict[str, set[str]] = {
        candidate_id: set() for candidate_id in candidates
    }
    review_artifacts: list[dict[str, str]] = []
    for review_path in sorted(reviews_dir.glob("*.json")):
        payload = _load_json(review_path, "signed_review")
        candidate_id = str(payload.get("candidate_id") or "")
        reviewer_id = str(payload.get("reviewer_id") or "")
        pair = (candidate_id, reviewer_id)
        if pair not in expected_pairs or pair in valid_pairs:
            raise ReviewEvidenceBlocked(
                [f"signed_review_unassigned_or_duplicate:{candidate_id}:{reviewer_id}"]
            )
        expected = candidates[candidate_id]
        reviewer = reviewers[reviewer_id]
        role = str(payload.get("reviewer_role") or "")
        reviewed_at = _parse_time(
            payload.get("reviewed_at"),
            f"signed_review_reviewed_at:{candidate_id}:{reviewer_id}",
        )
        checklist = payload.get("checklist")
        if (
            payload.get("schema_version") != SIGNED_REVIEW_SCHEMA
            or payload.get("assignment_id") != assignment_id
            or payload.get("reviewer_registry_sha256")
            != reviewer_registry_sha
            or payload.get("candidate_sha256") != expected["candidate_sha256"]
            or payload.get("packet_manifest_sha256")
            != expected["packet_manifest_sha256"]
            or payload.get("reviewer_key_id") != reviewer["key_id"]
            or role not in reviewer["roles"]
            or role not in expected["allowed_reviewer_roles"]
            or not isinstance(checklist, dict)
            or set(checklist) != set(expected["review_fields"])
            or any(value is not True for value in checklist.values())
            or payload.get("disposition") != "pass"
            or payload.get("critical_error") is not False
            or reviewed_at < opens_at
            or reviewed_at > closes_at
            or reviewed_at > checked_at + MAX_FUTURE_CLOCK_SKEW
        ):
            raise ReviewEvidenceBlocked(
                [f"signed_review_contract_invalid:{candidate_id}:{reviewer_id}"]
            )
        signature_path = review_path.with_suffix(".sig")
        try:
            signature = signature_path.read_bytes()
            reviewer["key"].verify(signature, _canonical(payload))
        except (OSError, InvalidSignature):
            raise ReviewEvidenceBlocked(
                [f"signed_review_signature_invalid:{candidate_id}:{reviewer_id}"]
            ) from None
        valid_pairs.add(pair)
        roles_by_candidate[candidate_id].add(role)
        review_artifacts.append(
            {
                "path": str(review_path.relative_to(evidence_dir)),
                "sha256": sha256_path(review_path),
                "signature_sha256": sha256_path(signature_path),
            }
        )
    if valid_pairs != expected_pairs:
        missing = sorted(expected_pairs - valid_pairs)
        raise ReviewEvidenceBlocked(
            [
                "signed_reviews_incomplete:"
                f"{len(valid_pairs)}/{len(expected_pairs)}:"
                + ",".join(f"{candidate}:{reviewer}" for candidate, reviewer in missing)
            ]
        )
    for candidate_id, expected in candidates.items():
        required_roles = set(expected["required_specialist_roles"])
        actual_roles = roles_by_candidate[candidate_id]
        if (
            expected["packet_schema"]
            == "open_agronomy_agent.manitoba_stored_grain_packet.v1"
        ):
            specialist_present = bool(required_roles & actual_roles)
        else:
            specialist_present = required_roles.issubset(actual_roles)
        if not specialist_present:
            raise ReviewEvidenceBlocked(
                [f"required_specialist_missing:{candidate_id}"]
            )
    signed_review_evidence_sha256 = _sha256_bytes(
        _canonical(
            {
                "reviewer_registry_sha256": reviewer_registry_sha,
                "reviewer_registry_signature_sha256": sha256_path(
                    registry_signature_path
                ),
                "review_assignment_sha256": sha256_path(assignment_path),
                "review_assignment_signature_sha256": sha256_path(
                    assignment_signature_path
                ),
                "review_artifacts": review_artifacts,
            }
        )
    )
    return {
        "schema_version": VERIFICATION_SCHEMA,
        "status": "pass",
        "promotion_review_gate_cleared": True,
        "jurisdiction": jurisdiction,
        "packet_group_id": packet_group["packet_id"],
        "checked_at": checked_at.replace(microsecond=0).isoformat(),
        "candidate_count": len(candidates),
        "required_review_count": len(expected_pairs),
        "valid_signed_review_count": len(valid_pairs),
        "candidate_ids": sorted(candidates),
        "candidate_set_sha256": _candidate_set_sha256(candidates),
        "packet_registry_sha256": expected_packet_registry_sha256,
        "reviewer_registry_sha256": reviewer_registry_sha,
        "review_assignment_sha256": sha256_path(assignment_path),
        "reviewer_registry_signature_sha256": sha256_path(
            registry_signature_path
        ),
        "review_assignment_signature_sha256": sha256_path(
            assignment_signature_path
        ),
        "signed_review_evidence_sha256": signed_review_evidence_sha256,
        "coordinator_public_key_sha256": expected_coordinator_public_key_sha256,
        "review_artifacts": review_artifacts,
        "software_verified": [
            "coordinator signatures and pinned coordinator key",
            "reviewer public-key continuity and unique key per reviewer identity",
            "frozen candidate assignments and exact candidate/source hashes",
            "two distinct assigned signatures per candidate",
            "candidate-specific checklist, specialist role, timestamp, and disposition",
        ],
        "human_attestations_not_independently_proven_by_software": [
            "legal identity",
            "professional credential",
            "independence from development",
            "completeness of disclosed conflicts",
            "substantive correctness of a reviewer's judgment",
        ],
        "boundary": (
            "Pass clears only the signed human-review evidence gate for the exact "
            "eight-candidate Manitoba group. It does not admit content, validate "
            "credentials independently, clear disjoint evaluation, or authorize "
            "advisory deployment."
        ),
    }


def encode_signature(signature: bytes) -> str:
    """Convenience for external systems that need a printable signature value."""

    return base64.b64encode(signature).decode("ascii")
