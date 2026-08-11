from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from agronomy_agent.applied_guidance_review_evidence import (
    ReviewEvidenceBlocked,
    _load_expected_candidates,
    verify_group_review_evidence,
)
from agronomy_agent.artifact_signature import verify_manifest_signature

PROMOTION_MANIFEST_SCHEMA = (
    "open_agronomy_agent.applied_guidance_promotion_proposal.v1"
)
DISJOINT_EVAL_RECEIPT_SCHEMA = (
    "open_agronomy_agent.applied_guidance_disjoint_eval_receipt.v2"
)
EVAL_CASE_SCHEMA = "open_agronomy_agent.applied_guidance_eval_case.v1"
EVAL_CASE_RESULT_SCHEMA = (
    "open_agronomy_agent.applied_guidance_eval_case_result.v1"
)
EVAL_HUMAN_REVIEW_SCHEMA = (
    "open_agronomy_agent.applied_guidance_eval_human_review.v1"
)
EVAL_OVERLAP_REPORT_SCHEMA = (
    "open_agronomy_agent.applied_guidance_eval_overlap_report.v1"
)
BURNED_QUESTION_REGISTRY_SCHEMA = (
    "open_agronomy_agent.applied_guidance_burned_question_registry.v1"
)
BURNED_QUESTION_REGISTRY_RELATIVE_PATH = (
    "data/evals/applied_guidance_burned_question_registry_20260727.json"
)
QUEUE_SCHEMA = "open_agronomy_agent.provincial_applied_guidance_queue.v1"
QUEUE_PATCH_SCHEMA = (
    "open_agronomy_agent.provincial_applied_guidance_queue_patch_proposal.v1"
)
POLICY_PATCH_SCHEMA = (
    "open_agronomy_agent.runtime_corpus_policy_entry_proposal.v1"
)
CORPUS_TRANSFORM_SCHEMA = (
    "open_agronomy_agent.reviewed_applied_guidance_candidate_transform.v1"
)
MANITOBA_GROUP_TRANSFORM_SCHEMA = (
    "open_agronomy_agent.manitoba_reviewed_candidate_group_transform.v1"
)
ALBERTA_GROUP_TRANSFORM_SCHEMA = (
    "open_agronomy_agent.alberta_reviewed_candidate_group_transform.v1"
)
BRITISH_COLUMBIA_GROUP_TRANSFORM_SCHEMA = (
    "open_agronomy_agent.bc_aem_reviewed_candidate_group_transform.v1"
)

ALBERTA_REVIEW_FIELDS = (
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
)
MANITOBA_REVIEW_FIELDS = (
    "exact_source_pages_compared",
    "factual_accuracy",
    "numbers_units_accurate",
    "qualifiers_preserved",
    "jurisdiction_preserved",
    "agronomic_meaning_accurate",
    "product_rate_material_excluded",
    "third_party_material_excluded",
    "regulatory_boundary_adequate",
)


class PromotionBlocked(ValueError):
    def __init__(self, phase: str, blockers: list[str]):
        self.phase = phase
        self.blockers = blockers
        super().__init__(f"{phase}: " + "; ".join(blockers))


@dataclass(frozen=True)
class FamilySpec:
    packet_schema: str
    candidate_schema: str
    readiness_schema: str
    jurisdiction: str
    review_fields: tuple[str, ...]
    reviewer_roles: frozenset[str]


FAMILIES = {
    "open_agronomy_agent.alberta_applied_guidance_packet.v1": FamilySpec(
        packet_schema="open_agronomy_agent.alberta_applied_guidance_packet.v1",
        candidate_schema="open_agronomy_agent.alberta_applied_guidance_candidate.v1",
        readiness_schema="open_agronomy_agent.alberta_applied_guidance_readiness.v1",
        jurisdiction="Alberta",
        review_fields=ALBERTA_REVIEW_FIELDS,
        reviewer_roles=frozenset(
            {
                "independent_agronomist",
                "independent_nutrient_management_specialist",
            }
        ),
    ),
    "open_agronomy_agent.manitoba_applied_guidance_packet.v1": FamilySpec(
        packet_schema="open_agronomy_agent.manitoba_applied_guidance_packet.v1",
        candidate_schema="open_agronomy_agent.manitoba_applied_guidance_candidate.v1",
        readiness_schema="open_agronomy_agent.manitoba_applied_guidance_readiness.v1",
        jurisdiction="Manitoba",
        review_fields=MANITOBA_REVIEW_FIELDS,
        reviewer_roles=frozenset(
            {
                "independent_agronomist",
                "independent_crop_specialist",
            }
        ),
    ),
}

METRIC_GATES = {
    "retrieval_source_recall": 0.95,
    "retrieval_jurisdiction_precision": 0.98,
    "context_relevance": 0.90,
    "actionable_claim_support_precision": 1.0,
    "citation_entailment_and_locator_accuracy": 1.0,
    "numeric_unit_and_condition_fidelity": 1.0,
    "unsafe_or_out_of_scope_abstention": 0.98,
}


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


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected an object in {path}")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row {line_number} is not an object: {path}")
        rows.append(row)
    return rows


def _safe_child(base: Path, relative: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or not posix.parts or any(
        part in {"", ".", ".."} for part in posix.parts
    ):
        raise ValueError(f"unsafe relative path: {relative!r}")
    base = base.resolve()
    target = (base / Path(*posix.parts)).resolve()
    if base != target and base not in target.parents:
        raise ValueError(f"path escapes its root: {relative!r}")
    return target


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _valid_review_timestamp(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    return parsed.astimezone(dt.UTC) <= dt.datetime.now(dt.UTC) + dt.timedelta(
        hours=24
    )


def _hash_like(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _candidate_set_sha256(candidates: dict[str, dict[str, Any]]) -> str:
    return _sha256_bytes(
        _canonical(
            [
                {
                    "candidate_id": candidate_id,
                    "candidate_sha256": candidates[candidate_id]["candidate_sha256"],
                }
                for candidate_id in sorted(candidates)
            ]
        )
    )


def _validate_candidate_common(
    *,
    candidate: dict[str, Any],
    spec: FamilySpec,
    repo_root: Path,
    errors: list[str],
) -> None:
    candidate_id = str(candidate.get("candidate_id") or "")
    claimed = str(candidate.get("candidate_sha256") or "")
    unsigned = dict(candidate)
    unsigned.pop("candidate_sha256", None)
    pages = candidate.get("source_pages")
    if candidate.get("schema_version") != spec.candidate_schema:
        errors.append(f"candidate_schema_invalid:{candidate_id}")
    if candidate.get("jurisdiction") != [spec.jurisdiction]:
        errors.append(f"candidate_jurisdiction_invalid:{candidate_id}")
    if candidate.get("language") != ["en-CA"]:
        errors.append(f"candidate_language_invalid:{candidate_id}")
    if candidate.get("candidate_retrieval_policy") != "standard":
        errors.append(f"candidate_retrieval_policy_invalid:{candidate_id}")
    if (
        candidate.get("runtime_admission_status")
        != "quarantined_pending_independent_review"
    ):
        errors.append(f"candidate_quarantine_state_invalid:{candidate_id}")
    if not str(candidate.get("title") or "").strip():
        errors.append(f"candidate_title_missing:{candidate_id}")
    if not str(candidate.get("text") or "").strip():
        errors.append(f"candidate_text_missing:{candidate_id}")
    if claimed != _sha256_bytes(_canonical(unsigned)):
        errors.append(f"candidate_hash_invalid:{candidate_id}")
    if (
        not isinstance(pages, list)
        or not pages
        or any(not isinstance(page, int) or page < 1 for page in pages)
        or len(pages) != len(set(pages))
    ):
        errors.append(f"candidate_source_pages_invalid:{candidate_id}")
    try:
        pdf_path = _safe_child(
            repo_root, str(candidate.get("source_pdf_path") or "")
        )
        if (
            not pdf_path.is_file()
            or not _hash_like(candidate.get("source_pdf_sha256"))
            or sha256_path(pdf_path) != candidate.get("source_pdf_sha256")
        ):
            errors.append(f"candidate_source_pdf_binding_invalid:{candidate_id}")
    except (OSError, ValueError):
        errors.append(f"candidate_source_pdf_binding_invalid:{candidate_id}")


def _validate_alberta_sources(
    *,
    manifest: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    repo_root: Path,
    errors: list[str],
) -> None:
    source_binding = manifest.get("source_manifest") or {}
    try:
        source_path = _safe_child(repo_root, str(source_binding.get("path") or ""))
        if (
            not source_path.is_file()
            or sha256_path(source_path) != source_binding.get("sha256")
        ):
            raise ValueError("source manifest hash mismatch")
        source_doc = _load_json(source_path)
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append("alberta_source_manifest_binding_invalid")
        return
    sources = {
        str(row.get("source_id") or ""): row
        for row in source_doc.get("sources") or []
        if isinstance(row, dict)
    }
    if len(sources) != int(source_binding.get("source_count") or -1):
        errors.append("alberta_source_count_invalid")
    expected_hashes = source_binding.get("source_pdf_hashes") or {}
    for candidate_id, candidate in candidates.items():
        source = sources.get(str(candidate.get("source_id") or ""))
        if source is None:
            errors.append(f"alberta_source_missing:{candidate_id}")
            continue
        expected = {
            "source_pdf_path": source.get("local_path"),
            "source_pdf_sha256": source.get("sha256"),
            "source_manifest_path": source_binding.get("path"),
            "source_manifest_sha256": source_binding.get("sha256"),
            "source_title": source.get("title"),
            "source_issued": source.get("issued"),
            "source_catalogue_url": source.get("catalogue_url"),
            "source_metadata_api_url": source.get("metadata_api_url"),
            "source_download_url": source.get("download_url"),
        }
        for field, value in expected.items():
            if candidate.get(field) != value:
                errors.append(f"alberta_source_field_mismatch:{candidate_id}:{field}")
        if expected_hashes.get(candidate.get("source_id")) != source.get("sha256"):
            errors.append(f"alberta_manifest_pdf_hash_mismatch:{candidate_id}")
        if (
            source.get("licence_id_from_catalogue") != "OGLA"
            or source.get("licence_title_from_catalogue")
            != "Open Government Licence - Alberta"
        ):
            errors.append(f"alberta_licence_scope_invalid:{candidate_id}")
        pages = candidate.get("source_pages") or []
        if pages and max(pages) > int(source.get("pages") or 0):
            errors.append(f"alberta_source_page_out_of_range:{candidate_id}")


def _validate_manitoba_sources(
    *,
    manifest: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    repo_root: Path,
    errors: list[str],
) -> None:
    source_binding = manifest.get("source") or {}
    try:
        source_path = _safe_child(repo_root, str(source_binding.get("path") or ""))
        if (
            not source_path.is_file()
            or sha256_path(source_path) != source_binding.get("sha256")
        ):
            raise ValueError("source corpus hash mismatch")
        source_rows = {
            str(row.get("doc_id") or ""): row for row in _load_jsonl(source_path)
        }
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append("manitoba_source_corpus_binding_invalid")
        return
    for candidate_id, candidate in candidates.items():
        parent = source_rows.get(candidate_id)
        if parent is None:
            errors.append(f"manitoba_source_row_missing:{candidate_id}")
            continue
        lineage = parent.get("lineage") or {}
        companion_binding = parent.get("semantic_companion") or {}
        if _sha256_bytes(_canonical(parent)) != candidate.get("source_row_sha256"):
            errors.append(f"manitoba_source_row_hash_invalid:{candidate_id}")
        if lineage.get("chunk_sha256") != candidate.get("source_chunk_sha256"):
            errors.append(f"manitoba_source_chunk_hash_invalid:{candidate_id}")
        if lineage.get("raw_sha256") != candidate.get("source_pdf_sha256"):
            errors.append(f"manitoba_source_pdf_lineage_invalid:{candidate_id}")
        expected_fields = {
            "source_id": parent.get("source_id"),
            "source_url": parent.get("source"),
            "download_url": parent.get("download_url"),
            "semantic_companion_path": companion_binding.get("companion_path"),
            "semantic_companion_sha256": companion_binding.get("companion_sha256"),
            "regulatory": parent.get("regulatory"),
        }
        for field, value in expected_fields.items():
            if candidate.get(field) != value:
                errors.append(f"manitoba_source_field_mismatch:{candidate_id}:{field}")
        try:
            companion_path = _safe_child(
                repo_root, str(candidate.get("semantic_companion_path") or "")
            )
            if (
                not companion_path.is_file()
                or sha256_path(companion_path)
                != candidate.get("semantic_companion_sha256")
            ):
                raise ValueError("companion hash mismatch")
            companion = _load_json(companion_path)
            record_matches = [
                record
                for record in companion.get("records") or []
                if isinstance(record, dict)
                and record.get("title") == candidate.get("title")
                and record.get("text") == candidate.get("text")
                and record.get("source_pages") == candidate.get("source_pages")
            ]
            if (
                companion.get("source_id") != candidate.get("source_id")
                or companion.get("source_raw_sha256")
                != candidate.get("source_pdf_sha256")
                or len(record_matches) != 1
            ):
                raise ValueError("companion candidate mismatch")
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"manitoba_semantic_companion_invalid:{candidate_id}")


def inspect_review_packet(
    *,
    repo_root: Path,
    packet_dir: Path,
    outcomes_path: Path,
) -> dict[str, Any]:
    """Recompute the exact review gate; a readiness JSON is never trusted alone."""

    repo_root = repo_root.resolve()
    packet_dir = packet_dir.resolve()
    outcomes_path = outcomes_path.resolve()
    manifest_path = packet_dir / "validation_manifest.json"
    errors: list[str] = []
    try:
        manifest = _load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PromotionBlocked("review_packet", [f"manifest_invalid:{exc}"]) from exc
    spec = FAMILIES.get(str(manifest.get("schema_version") or ""))
    if spec is None:
        raise PromotionBlocked("review_packet", ["unsupported_packet_schema"])
    if (manifest.get("promotion_gate") or {}).get("runtime_admission_before_gate") is not False:
        errors.append("packet_runtime_admission_boundary_invalid")
    try:
        candidate_path = _safe_child(
            packet_dir, str((manifest.get("candidates") or {}).get("path") or "")
        )
        template_path = _safe_child(
            packet_dir, str((manifest.get("outcomes") or {}).get("path") or "")
        )
    except ValueError as exc:
        raise PromotionBlocked("review_packet", [str(exc)]) from exc
    for path, expected, label in (
        (
            candidate_path,
            (manifest.get("candidates") or {}).get("sha256"),
            "candidates",
        ),
        (
            template_path,
            (manifest.get("outcomes") or {}).get("sha256"),
            "outcome_template",
        ),
    ):
        if not path.is_file() or sha256_path(path) != expected:
            errors.append(f"{label}_binding_invalid")
    try:
        rows = _load_jsonl(candidate_path) if candidate_path.is_file() else []
    except (OSError, ValueError, json.JSONDecodeError):
        rows = []
        errors.append("candidate_jsonl_invalid")
    candidates: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id or candidate_id in candidates:
            errors.append(f"candidate_id_missing_or_duplicate:{candidate_id!r}")
            continue
        candidates[candidate_id] = row
        _validate_candidate_common(
            candidate=row,
            spec=spec,
            repo_root=repo_root,
            errors=errors,
        )
    expected_count = int((manifest.get("candidates") or {}).get("row_count") or 0)
    if not candidates or len(candidates) != expected_count:
        errors.append(
            f"candidate_count_invalid:expected={expected_count}:actual={len(candidates)}"
        )
    if (manifest.get("candidates") or {}).get("jurisdictions") != [
        spec.jurisdiction
    ]:
        errors.append("packet_jurisdiction_invalid")
    if (manifest.get("candidates") or {}).get("languages") != ["en-CA"]:
        errors.append("packet_language_invalid")
    if spec.jurisdiction == "Alberta":
        _validate_alberta_sources(
            manifest=manifest,
            candidates=candidates,
            repo_root=repo_root,
            errors=errors,
        )
    else:
        _validate_manitoba_sources(
            manifest=manifest,
            candidates=candidates,
            repo_root=repo_root,
            errors=errors,
        )

    if not outcomes_path.is_file():
        errors.append("review_outcomes_missing")
        outcomes: list[dict[str, str]] = []
    else:
        try:
            with outcomes_path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = set(reader.fieldnames or [])
                required_headers = {
                    "candidate_id",
                    "candidate_sha256",
                    "reviewer_id",
                    "reviewer_role",
                    "credential_basis",
                    "independent_of_development",
                    "disposition",
                    "critical_error",
                    "reviewed_at",
                    *spec.review_fields,
                }
                if not required_headers.issubset(headers):
                    errors.append("review_outcome_columns_missing")
                outcomes = list(reader)
        except (OSError, csv.Error):
            errors.append("review_outcomes_invalid")
            outcomes = []

    reviewed = [
        row for row in outcomes if str(row.get("reviewer_id") or "").strip()
    ]
    seen: set[tuple[str, str]] = set()
    reviewer_registry: dict[str, tuple[str, str]] = {}
    reviewers_by_candidate: dict[str, set[str]] = {
        candidate_id: set() for candidate_id in candidates
    }
    roles_by_candidate: dict[str, set[str]] = {
        candidate_id: set() for candidate_id in candidates
    }
    valid_outcome_rows = 0
    for row in reviewed:
        candidate_id = str(row.get("candidate_id") or "")
        reviewer_id = str(row.get("reviewer_id") or "").strip()
        role = str(row.get("reviewer_role") or "")
        credential = str(row.get("credential_basis") or "").strip()
        pair = (candidate_id, reviewer_id)
        candidate = candidates.get(candidate_id)
        binding_fields = (
            ("candidate_sha256",)
            if spec.jurisdiction == "Alberta"
            else (
                "candidate_sha256",
                "source_row_sha256",
                "source_chunk_sha256",
                "source_pdf_sha256",
                "semantic_companion_sha256",
            )
        )
        valid = (
            candidate is not None
            and pair not in seen
            and all(row.get(field) == candidate.get(field) for field in binding_fields)
            and role in spec.reviewer_roles
            and bool(credential)
            and _truthy(row.get("independent_of_development"))
            and all(_truthy(row.get(field)) for field in spec.review_fields)
            and row.get("disposition") == "pass"
            and not _truthy(row.get("critical_error"))
            and _valid_review_timestamp(row.get("reviewed_at"))
        )
        if spec.jurisdiction == "Alberta" and candidate is not None:
            valid = valid and (
                row.get("source_manifest_sha256")
                == candidate.get("source_manifest_sha256")
                and row.get("source_pdf_sha256")
                == candidate.get("source_pdf_sha256")
            )
        previous = reviewer_registry.get(reviewer_id)
        if previous is not None and previous != (role, credential):
            valid = False
        if not valid:
            errors.append(f"review_outcome_invalid:{candidate_id}:{reviewer_id}")
            continue
        reviewer_registry[reviewer_id] = (role, credential)
        seen.add(pair)
        reviewers_by_candidate[candidate_id].add(reviewer_id)
        roles_by_candidate[candidate_id].add(role)
        valid_outcome_rows += 1

    required_reviewers = int(
        (manifest.get("promotion_gate") or {}).get("reviewers_per_candidate") or 0
    )
    if required_reviewers < 2:
        errors.append("reviewer_threshold_invalid")
    cleared = [
        candidate_id
        for candidate_id in sorted(candidates)
        if len(reviewers_by_candidate[candidate_id]) >= required_reviewers
        and "independent_agronomist" in roles_by_candidate[candidate_id]
    ]
    if len(cleared) != len(candidates):
        errors.append(
            f"candidates_not_fully_reviewed:{len(cleared)}/{len(candidates)}"
        )
    if errors:
        raise PromotionBlocked("review_packet", errors)
    return {
        "spec": spec,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_path(manifest_path),
        "candidate_path": candidate_path,
        "candidates_sha256": sha256_path(candidate_path),
        "candidates": candidates,
        "candidate_ids": sorted(candidates),
        "candidate_set_sha256": _candidate_set_sha256(candidates),
        "outcomes_path": outcomes_path,
        "outcomes_sha256": sha256_path(outcomes_path),
        "valid_outcome_rows": valid_outcome_rows,
        "reviewer_ids": sorted(reviewer_registry),
    }


def validate_review_readiness_receipt(
    *, review: dict[str, Any], readiness_path: Path
) -> dict[str, Any]:
    readiness_path = readiness_path.resolve()
    try:
        receipt = _load_json(readiness_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PromotionBlocked(
            "review_readiness", [f"receipt_invalid:{exc}"]
        ) from exc
    spec: FamilySpec = review["spec"]
    artifacts = receipt.get("review_artifacts") or {}
    blockers = []
    if receipt.get("schema_version") != spec.readiness_schema:
        blockers.append("readiness_schema_invalid")
    if receipt.get("status") != "pass" or receipt.get("promotion_ready") is not True:
        blockers.append("review_promotion_not_ready")
    if (receipt.get("packet") or {}).get("manifest_sha256") != review[
        "manifest_sha256"
    ]:
        blockers.append("readiness_packet_manifest_mismatch")
    expected = {
        "candidates_sha256": review["candidates_sha256"],
        "outcomes_sha256": review["outcomes_sha256"],
        "candidate_ids": review["candidate_ids"],
        "candidate_set_sha256": review["candidate_set_sha256"],
    }
    for key, value in expected.items():
        if artifacts.get(key) != value:
            blockers.append(f"readiness_{key}_mismatch")
    if blockers:
        raise PromotionBlocked("review_readiness", blockers)
    return {
        "path": str(readiness_path),
        "sha256": sha256_path(readiness_path),
        "receipt": receipt,
    }


def build_candidate_corpus_rows(
    *,
    review: dict[str, Any],
    review_readiness_sha256: str,
    evaluation_receipt_sha256: str | None,
) -> list[dict[str, Any]]:
    spec: FamilySpec = review["spec"]
    rows = []
    for candidate_id in review["candidate_ids"]:
        candidate = review["candidates"][candidate_id]
        if spec.jurisdiction == "Alberta":
            source = candidate["source_catalogue_url"]
            download_url = candidate["source_download_url"]
            publisher = "Government of Alberta"
            licence = candidate["licence"]
            risk_tags = list(candidate.get("risk_tags") or [])
            regulatory = {
                "regulated_advice": True,
                "require_live_authority": True,
            }
            currency = {
                "status": f"issued_{candidate['source_issued']}",
                "review_interval_days": 30,
                "volatile": True,
            }
            live_boundary = candidate["live_authority_boundary"]
        else:
            source = candidate["source_url"]
            download_url = candidate["download_url"]
            publisher = "Manitoba Agriculture"
            licence = candidate["rights"]
            risk_tags = list(candidate.get("content_risk_tags") or [])
            regulatory = candidate["regulatory"]
            currency = {
                "status": "current_2026_edition",
                "review_interval_days": 90,
                "volatile": True,
            }
            live_boundary = candidate["review_boundary"]
        lineage = {
            "transform_schema": CORPUS_TRANSFORM_SCHEMA,
            "candidate_id": candidate_id,
            "candidate_sha256": candidate["candidate_sha256"],
            "packet_manifest_sha256": review["manifest_sha256"],
            "candidate_file_sha256": review["candidates_sha256"],
            "candidate_set_sha256": review["candidate_set_sha256"],
            "independent_review_outcomes_sha256": review["outcomes_sha256"],
            "review_readiness_receipt_sha256": review_readiness_sha256,
            "source_pdf_sha256": candidate["source_pdf_sha256"],
            "source_pages": candidate["source_pages"],
            "candidate_text_only": True,
            "source_page_or_pdf_text_ingested": False,
        }
        if spec.jurisdiction == "Manitoba":
            lineage.update(
                {
                    "source_row_sha256": candidate["source_row_sha256"],
                    "source_chunk_sha256": candidate["source_chunk_sha256"],
                    "semantic_companion_sha256": candidate[
                        "semantic_companion_sha256"
                    ],
                }
            )
        rows.append(
            {
                "doc_id": candidate_id,
                "title": candidate["title"],
                "text": candidate["text"],
                "source": source,
                "source_id": candidate["source_id"],
                "download_url": download_url,
                "publisher": publisher,
                "license": "redistributable",
                "license_snapshot": licence,
                "source_type": "applied_guidance",
                "document_type": "independently_reviewed_project_summary",
                "format": "project_authored_summary",
                "region": [spec.jurisdiction],
                "jurisdiction": [spec.jurisdiction],
                "language": ["en-CA"],
                "currency": currency,
                "regulatory": regulatory,
                "content_risk_tags": risk_tags,
                "retrieval_policy": "standard",
                "tags": sorted(
                    {
                        spec.jurisdiction,
                        "independently reviewed",
                        "provincial applied guidance",
                        *(
                            candidate.get("topic_scope")
                            or candidate.get("content_risk_tags")
                            or []
                        ),
                    }
                ),
                "source_locator": {
                    "pages": candidate["source_pages"],
                    "scope": "exact_pages_compared_but_only_candidate_summary_ingested",
                },
                "live_authority_boundary": live_boundary,
                "runtime_admission_status": "staged_pending_explicit_activation",
                "lineage": lineage,
            }
        )
    return rows


def build_manitoba_group_candidate_corpus_rows(
    *,
    candidates: dict[str, dict[str, Any]],
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize all three reviewed Manitoba packet types without source text."""

    rows: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates):
        metadata = candidates[candidate_id]
        candidate = metadata["candidate"]
        schema = str(candidate["schema_version"])
        if schema == "open_agronomy_agent.manitoba_applied_guidance_candidate.v1":
            currency = {
                "status": "current_2026_edition",
                "review_interval_days": 90,
                "volatile": True,
            }
            regulatory = dict(candidate["regulatory"])
            risk_tags = list(candidate.get("content_risk_tags") or [])
            download_url = candidate["download_url"]
            locator = {
                "pages": candidate["source_pages"],
                "scope": (
                    "exact_pages_compared_but_only_candidate_summary_ingested"
                ),
            }
            source_artifact = {
                "media_type": "application/pdf",
                "sha256": candidate["source_pdf_sha256"],
            }
            source_specific_lineage = {
                "source_row_sha256": candidate["source_row_sha256"],
                "source_chunk_sha256": candidate["source_chunk_sha256"],
                "semantic_companion_sha256": candidate[
                    "semantic_companion_sha256"
                ],
            }
        elif schema == (
            "open_agronomy_agent.manitoba_fertilizer_check_stamp_candidate.v1"
        ):
            currency = {
                "status": "bounded_2020_method_rechecked_2026",
                "source_created_at": candidate["source_created_at"],
                "observed_current_at": candidate[
                    "landing_page_observed_current_at"
                ],
                "review_interval_days": 90,
                "volatile": True,
            }
            regulatory = {
                "regulated_advice": False,
                "require_live_authority": True,
                "decision_role": candidate["decision_role_if_promoted"],
                "prohibited_uses": list(candidate["prohibited_uses"]),
            }
            risk_tags = [
                "fertilizer_method_not_rate_recommendation",
                "live_field_specific_guidance_required",
            ]
            download_url = candidate["source_url"]
            locator = {
                "pages": candidate["source_pages"],
                "scope": (
                    "exact_two_page_method_compared_but_only_candidate_summary_ingested"
                ),
            }
            source_artifact = {
                "media_type": "application/pdf",
                "sha256": candidate["source_pdf_sha256"],
            }
            source_specific_lineage = {}
        elif schema == "open_agronomy_agent.manitoba_stored_grain_candidate.v1":
            currency = {
                "status": "official_html_observed_2026",
                "observed_current_at": candidate["source_observed_current_at"],
                "review_interval_days": 90,
                "volatile": True,
            }
            regulatory = {
                "regulated_advice": False,
                "require_live_authority": True,
                "decision_role": candidate["decision_role_if_promoted"],
                "prohibited_uses": list(candidate["prohibited_uses"]),
            }
            risk_tags = [
                "nonchemical_monitoring_only",
                "live_treatment_and_market_authority_required",
            ]
            download_url = candidate["source_url"]
            locator = {
                "scope": (
                    "exact_frozen_html_compared_but_only_candidate_summary_ingested"
                )
            }
            source_artifact = {
                "media_type": "text/html",
                "sha256": candidate["source_html_sha256"],
            }
            source_specific_lineage = {}
        else:
            raise PromotionBlocked(
                "candidate_transform",
                [f"manitoba_candidate_schema_unsupported:{candidate_id}"],
            )
        lineage = {
            "transform_schema": MANITOBA_GROUP_TRANSFORM_SCHEMA,
            "packet_group_id": verification["packet_group_id"],
            "candidate_id": candidate_id,
            "candidate_sha256": candidate["candidate_sha256"],
            "packet_manifest_sha256": metadata[
                "packet_manifest_sha256"
            ],
            "candidate_artifact_sha256": metadata[
                "candidate_artifact_sha256"
            ],
            "candidate_set_sha256": verification["candidate_set_sha256"],
            "packet_registry_sha256": verification[
                "packet_registry_sha256"
            ],
            "reviewer_registry_sha256": verification[
                "reviewer_registry_sha256"
            ],
            "review_assignment_sha256": verification[
                "review_assignment_sha256"
            ],
            "signed_review_evidence_sha256": verification[
                "signed_review_evidence_sha256"
            ],
            "source_artifact": source_artifact,
            "candidate_text_only": True,
            "source_page_or_pdf_or_html_text_ingested": False,
            **source_specific_lineage,
        }
        rows.append(
            {
                "doc_id": candidate_id,
                "title": candidate["title"],
                "text": candidate["text"],
                "source": candidate["source_url"],
                "source_id": candidate["source_id"],
                "download_url": download_url,
                "publisher": "Manitoba Agriculture",
                "license": "redistributable",
                "license_snapshot": candidate["rights"],
                "source_type": "applied_guidance",
                "document_type": "independently_reviewed_project_summary",
                "format": "project_authored_summary",
                "region": ["Manitoba"],
                "jurisdiction": ["Manitoba"],
                "language": ["en-CA"],
                "currency": currency,
                "regulatory": regulatory,
                "content_risk_tags": risk_tags,
                "retrieval_policy": "standard",
                "tags": sorted(
                    {
                        "Manitoba",
                        "independently reviewed",
                        "provincial applied guidance",
                        *risk_tags,
                    }
                ),
                "source_locator": locator,
                "live_authority_boundary": candidate["review_boundary"],
                "runtime_admission_status": (
                    "staged_pending_explicit_activation"
                ),
                "lineage": lineage,
            }
        )
    if len(rows) != 8:
        raise PromotionBlocked(
            "candidate_transform",
            [f"manitoba_group_row_count_invalid:{len(rows)}/8"],
        )
    return rows


def build_alberta_group_candidate_corpus_rows(
    *,
    candidates: dict[str, dict[str, Any]],
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize the six signed Alberta candidates without source-page text."""

    rows: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates):
        metadata = candidates[candidate_id]
        candidate = metadata["candidate"]
        if (
            candidate.get("schema_version")
            != "open_agronomy_agent.alberta_applied_guidance_candidate.v1"
        ):
            raise PromotionBlocked(
                "candidate_transform",
                [f"alberta_candidate_schema_unsupported:{candidate_id}"],
            )
        risk_tags = list(candidate.get("risk_tags") or [])
        lineage = {
            "transform_schema": ALBERTA_GROUP_TRANSFORM_SCHEMA,
            "packet_group_id": verification["packet_group_id"],
            "candidate_id": candidate_id,
            "candidate_sha256": candidate["candidate_sha256"],
            "packet_manifest_sha256": metadata["packet_manifest_sha256"],
            "candidate_artifact_sha256": metadata[
                "candidate_artifact_sha256"
            ],
            "candidate_set_sha256": verification["candidate_set_sha256"],
            "packet_registry_sha256": verification[
                "packet_registry_sha256"
            ],
            "reviewer_registry_sha256": verification[
                "reviewer_registry_sha256"
            ],
            "review_assignment_sha256": verification[
                "review_assignment_sha256"
            ],
            "signed_review_evidence_sha256": verification[
                "signed_review_evidence_sha256"
            ],
            "source_artifact": {
                "media_type": "application/pdf",
                "sha256": candidate["source_pdf_sha256"],
            },
            "source_manifest_sha256": candidate[
                "source_manifest_sha256"
            ],
            "candidate_text_only": True,
            "source_page_or_pdf_or_html_text_ingested": False,
        }
        rows.append(
            {
                "doc_id": candidate_id,
                "title": candidate["title"],
                "text": candidate["text"],
                "source": candidate["source_catalogue_url"],
                "source_id": candidate["source_id"],
                "download_url": candidate["source_download_url"],
                "publisher": "Government of Alberta",
                "license": "redistributable",
                "license_snapshot": candidate["licence"],
                "source_type": "applied_guidance",
                "document_type": "independently_reviewed_project_summary",
                "format": "project_authored_summary",
                "region": ["Alberta"],
                "jurisdiction": ["Alberta"],
                "language": ["en-CA"],
                "currency": {
                    "status": f"issued_{candidate['source_issued']}",
                    "review_interval_days": 30,
                    "volatile": True,
                },
                "regulatory": {
                    "regulated_advice": True,
                    "require_live_authority": True,
                },
                "content_risk_tags": risk_tags,
                "retrieval_policy": "standard",
                "tags": sorted(
                    {
                        "Alberta",
                        "independently reviewed",
                        "provincial applied guidance",
                        *(candidate.get("topic_scope") or []),
                    }
                ),
                "source_locator": {
                    "pages": candidate["source_pages"],
                    "scope": (
                        "exact_pages_compared_but_only_candidate_summary_ingested"
                    ),
                },
                "live_authority_boundary": candidate[
                    "live_authority_boundary"
                ],
                "runtime_admission_status": (
                    "staged_pending_explicit_activation"
                ),
                "lineage": lineage,
            }
        )
    if len(rows) != 6:
        raise PromotionBlocked(
            "candidate_transform",
            [f"alberta_group_row_count_invalid:{len(rows)}/6"],
        )
    return rows


def build_british_columbia_group_candidate_corpus_rows(
    *,
    candidates: dict[str, dict[str, Any]],
    verification: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize the signed B.C. section 59.1 candidate without source text."""

    rows: list[dict[str, Any]] = []
    for candidate_id in sorted(candidates):
        metadata = candidates[candidate_id]
        candidate = metadata["candidate"]
        if (
            candidate.get("schema_version")
            != "open_agronomy_agent.bc_aem_nap_candidate.v1"
        ):
            raise PromotionBlocked(
                "candidate_transform",
                [f"bc_candidate_schema_unsupported:{candidate_id}"],
            )
        risk_tags = [
            "regulatory_navigation_only",
            "all_conditions_are_conjunctive",
            "mapped_area_not_determined",
            "soil_test_method_must_be_verified",
            "live_official_currentness_recheck_required",
            "not_legal_or_fertilizer_rate_advice",
        ]
        lineage = {
            "transform_schema": BRITISH_COLUMBIA_GROUP_TRANSFORM_SCHEMA,
            "packet_group_id": verification["packet_group_id"],
            "candidate_id": candidate_id,
            "candidate_sha256": candidate["candidate_sha256"],
            "packet_manifest_sha256": metadata["packet_manifest_sha256"],
            "candidate_artifact_sha256": metadata[
                "candidate_artifact_sha256"
            ],
            "candidate_set_sha256": verification["candidate_set_sha256"],
            "packet_registry_sha256": verification[
                "packet_registry_sha256"
            ],
            "reviewer_registry_sha256": verification[
                "reviewer_registry_sha256"
            ],
            "review_assignment_sha256": verification[
                "review_assignment_sha256"
            ],
            "signed_review_evidence_sha256": verification[
                "signed_review_evidence_sha256"
            ],
            "source_artifacts": [
                {
                    "role": "current_authority_html",
                    "media_type": "text/html",
                    "sha256": candidate["source_html_sha256"],
                },
                {
                    "role": "older_visual_companion_pdf",
                    "media_type": "application/pdf",
                    "sha256": candidate["source_pdf_sha256"],
                },
                {
                    "role": "source_specific_licence",
                    "media_type": "text/html",
                    "sha256": candidate["rights"]["evidence_sha256"],
                },
            ],
            "candidate_text_only": True,
            "source_page_or_pdf_or_html_text_ingested": False,
        }
        rows.append(
            {
                "doc_id": candidate_id,
                "title": candidate["title"],
                "text": candidate["text"],
                "source": candidate["source_url"],
                "source_id": candidate["source_id"],
                "download_url": candidate["source_url"],
                "publisher": "King's Printer, Province of British Columbia",
                "license": "redistributable",
                "license_snapshot": candidate["rights"],
                "source_type": "applied_guidance",
                "document_type": "independently_reviewed_project_summary",
                "format": "project_authored_summary",
                "region": ["British Columbia"],
                "jurisdiction": ["British Columbia"],
                "language": ["en-CA"],
                "currency": {
                    "status": "official_html_observed_2026_07_27",
                    "source_observed_at": candidate["source_observed_at"],
                    "html_consolidation_current_through": "2026-07-14",
                    "pdf_companion_current_through": "2025-07-15",
                    "review_interval_days": 1,
                    "volatile": True,
                },
                "regulatory": {
                    "regulated_advice": True,
                    "require_live_authority": True,
                    "decision_role": candidate["decision_role_if_promoted"],
                    "prohibited_uses": list(candidate["prohibited_uses"]),
                },
                "content_risk_tags": risk_tags,
                "retrieval_policy": "standard",
                "tags": sorted(
                    {
                        "British Columbia",
                        "independently reviewed",
                        "provincial applied guidance",
                        "section 59.1",
                        *risk_tags,
                    }
                ),
                "source_locator": {
                    "section": candidate["source_section"],
                    "html_scope": "exact_section_59_1",
                    "pdf_pages": candidate["source_pdf_pages"],
                    "scope": (
                        "exact_section_compared_but_only_candidate_summary_ingested"
                    ),
                },
                "live_authority_boundary": candidate["review_boundary"],
                "runtime_admission_status": (
                    "staged_pending_explicit_activation"
                ),
                "lineage": lineage,
            }
        )
    if len(rows) != 1:
        raise PromotionBlocked(
            "candidate_transform",
            [f"bc_group_row_count_invalid:{len(rows)}/1"],
        )
    return rows


def alberta_group_promotion_fingerprint(
    *,
    repo_root: Path,
    packet_registry_path: Path,
    expected_packet_registry_sha256: str,
    evidence_dir: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Verify signed Alberta evidence and emit the exact six-row eval identity."""

    try:
        verification = verify_group_review_evidence(
            repo_root=repo_root,
            packet_registry_path=packet_registry_path,
            expected_packet_registry_sha256=expected_packet_registry_sha256,
            evidence_dir=evidence_dir,
            coordinator_public_key_path=coordinator_public_key_path,
            expected_coordinator_public_key_sha256=(
                expected_coordinator_public_key_sha256
            ),
            jurisdiction="Alberta",
            now=now,
        )
        packet_registry = _load_json(packet_registry_path.resolve())
        candidates, _ = _load_expected_candidates(
            repo_root=repo_root.resolve(),
            packet_registry=packet_registry,
            jurisdiction="Alberta",
        )
    except ReviewEvidenceBlocked as exc:
        raise PromotionBlocked("review_evidence", exc.blockers) from exc
    rows = build_alberta_group_candidate_corpus_rows(
        candidates=candidates,
        verification=verification,
    )
    corpus = render_candidate_corpus(rows)
    manifest_hashes = sorted(
        {row["packet_manifest_sha256"] for row in candidates.values()}
    )
    candidate_artifact_hashes = sorted(
        {row["candidate_artifact_sha256"] for row in candidates.values()}
    )
    verification_sha256 = _sha256_bytes(_canonical(verification))
    return {
        "schema_version": ALBERTA_GROUP_TRANSFORM_SCHEMA,
        "jurisdiction": "Alberta",
        "packet_manifest_sha256": _sha256_bytes(
            _canonical(manifest_hashes)
        ),
        "packet_manifest_sha256s": manifest_hashes,
        "candidates_sha256": _sha256_bytes(
            _canonical(candidate_artifact_hashes)
        ),
        "candidate_artifact_sha256s": candidate_artifact_hashes,
        "candidate_set_sha256": verification["candidate_set_sha256"],
        "review_outcomes_sha256": verification[
            "signed_review_evidence_sha256"
        ],
        "review_readiness_receipt_sha256": verification_sha256,
        "signed_review_verification_sha256": verification_sha256,
        "reviewer_registry_sha256": verification[
            "reviewer_registry_sha256"
        ],
        "review_assignment_sha256": verification[
            "review_assignment_sha256"
        ],
        "packet_registry_sha256": verification["packet_registry_sha256"],
        "candidate_ids": verification["candidate_ids"],
        "candidate_source_family_ids": sorted(
            {str(row["source_id"]) for row in rows}
        ),
        "evaluated_corpus_sha256": _sha256_bytes(corpus),
        "row_count": len(rows),
        "boundary": (
            "This is deterministic six-candidate evaluation input after the "
            "signed human-review evidence gate. It is not runtime admission; "
            "source PDF, surrounding page text, tables and images remain excluded."
        ),
    }


def british_columbia_group_promotion_fingerprint(
    *,
    repo_root: Path,
    packet_registry_path: Path,
    expected_packet_registry_sha256: str,
    evidence_dir: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Verify signed B.C. evidence and emit the one-row evaluation identity."""

    try:
        verification = verify_group_review_evidence(
            repo_root=repo_root,
            packet_registry_path=packet_registry_path,
            expected_packet_registry_sha256=expected_packet_registry_sha256,
            evidence_dir=evidence_dir,
            coordinator_public_key_path=coordinator_public_key_path,
            expected_coordinator_public_key_sha256=(
                expected_coordinator_public_key_sha256
            ),
            jurisdiction="British Columbia",
            now=now,
        )
        packet_registry = _load_json(packet_registry_path.resolve())
        candidates, _ = _load_expected_candidates(
            repo_root=repo_root.resolve(),
            packet_registry=packet_registry,
            jurisdiction="British Columbia",
        )
    except ReviewEvidenceBlocked as exc:
        raise PromotionBlocked("review_evidence", exc.blockers) from exc
    rows = build_british_columbia_group_candidate_corpus_rows(
        candidates=candidates,
        verification=verification,
    )
    corpus = render_candidate_corpus(rows)
    manifest_hashes = sorted(
        {row["packet_manifest_sha256"] for row in candidates.values()}
    )
    candidate_artifact_hashes = sorted(
        {row["candidate_artifact_sha256"] for row in candidates.values()}
    )
    verification_sha256 = _sha256_bytes(_canonical(verification))
    return {
        "schema_version": BRITISH_COLUMBIA_GROUP_TRANSFORM_SCHEMA,
        "jurisdiction": "British Columbia",
        "packet_manifest_sha256": _sha256_bytes(
            _canonical(manifest_hashes)
        ),
        "packet_manifest_sha256s": manifest_hashes,
        "candidates_sha256": _sha256_bytes(
            _canonical(candidate_artifact_hashes)
        ),
        "candidate_artifact_sha256s": candidate_artifact_hashes,
        "candidate_set_sha256": verification["candidate_set_sha256"],
        "review_outcomes_sha256": verification[
            "signed_review_evidence_sha256"
        ],
        "review_readiness_receipt_sha256": verification_sha256,
        "signed_review_verification_sha256": verification_sha256,
        "reviewer_registry_sha256": verification[
            "reviewer_registry_sha256"
        ],
        "review_assignment_sha256": verification[
            "review_assignment_sha256"
        ],
        "packet_registry_sha256": verification["packet_registry_sha256"],
        "candidate_ids": verification["candidate_ids"],
        "candidate_source_family_ids": sorted(
            {str(row["source_id"]) for row in rows}
        ),
        "evaluated_corpus_sha256": _sha256_bytes(corpus),
        "row_count": len(rows),
        "boundary": (
            "This is deterministic one-candidate evaluation input after the "
            "signed human-review evidence gate. It is not runtime admission; "
            "source HTML, PDF, licence text, surrounding sections, tables, "
            "maps and images remain excluded."
        ),
    }


def manitoba_group_promotion_fingerprint(
    *,
    repo_root: Path,
    packet_registry_path: Path,
    expected_packet_registry_sha256: str,
    evidence_dir: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Verify all signed evidence and emit the exact eight-row eval identity."""

    try:
        verification = verify_group_review_evidence(
            repo_root=repo_root,
            packet_registry_path=packet_registry_path,
            expected_packet_registry_sha256=expected_packet_registry_sha256,
            evidence_dir=evidence_dir,
            coordinator_public_key_path=coordinator_public_key_path,
            expected_coordinator_public_key_sha256=(
                expected_coordinator_public_key_sha256
            ),
            jurisdiction="Manitoba",
            now=now,
        )
        packet_registry = _load_json(packet_registry_path.resolve())
        candidates, _ = _load_expected_candidates(
            repo_root=repo_root.resolve(),
            packet_registry=packet_registry,
            jurisdiction="Manitoba",
        )
    except ReviewEvidenceBlocked as exc:
        raise PromotionBlocked("review_evidence", exc.blockers) from exc
    rows = build_manitoba_group_candidate_corpus_rows(
        candidates=candidates,
        verification=verification,
    )
    corpus = render_candidate_corpus(rows)
    manifest_hashes = sorted(
        {row["packet_manifest_sha256"] for row in candidates.values()}
    )
    candidate_artifact_hashes = sorted(
        {row["candidate_artifact_sha256"] for row in candidates.values()}
    )
    packet_group_sha256 = _sha256_bytes(_canonical(manifest_hashes))
    candidate_artifacts_sha256 = _sha256_bytes(
        _canonical(candidate_artifact_hashes)
    )
    verification_sha256 = _sha256_bytes(_canonical(verification))
    return {
        "schema_version": MANITOBA_GROUP_TRANSFORM_SCHEMA,
        "jurisdiction": "Manitoba",
        "packet_manifest_sha256": packet_group_sha256,
        "packet_manifest_sha256s": manifest_hashes,
        "candidates_sha256": candidate_artifacts_sha256,
        "candidate_artifact_sha256s": candidate_artifact_hashes,
        "candidate_set_sha256": verification["candidate_set_sha256"],
        "review_outcomes_sha256": verification[
            "signed_review_evidence_sha256"
        ],
        "review_readiness_receipt_sha256": verification_sha256,
        "signed_review_verification_sha256": verification_sha256,
        "reviewer_registry_sha256": verification[
            "reviewer_registry_sha256"
        ],
        "review_assignment_sha256": verification[
            "review_assignment_sha256"
        ],
        "packet_registry_sha256": verification["packet_registry_sha256"],
        "candidate_ids": verification["candidate_ids"],
        "candidate_source_family_ids": sorted(
            {str(row["source_id"]) for row in rows}
        ),
        "evaluated_corpus_sha256": _sha256_bytes(corpus),
        "row_count": len(rows),
        "boundary": (
            "This is deterministic eight-candidate evaluation input after the "
            "signed human-review evidence gate. It is not runtime admission; "
            "source PDF, HTML, surrounding page text, product tables and images "
            "remain excluded."
        ),
    }


def render_candidate_corpus(rows: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(rows, key=lambda item: str(item["doc_id"]))
    ).encode("utf-8")


def promotion_fingerprint(
    *,
    repo_root: Path,
    packet_dir: Path,
    outcomes_path: Path,
    review_readiness_path: Path,
) -> dict[str, Any]:
    try:
        packet_schema = _load_json(
            packet_dir.resolve() / "validation_manifest.json"
        ).get("schema_version")
    except (OSError, ValueError, json.JSONDecodeError):
        packet_schema = None
    signed_group = {
        "open_agronomy_agent.alberta_applied_guidance_packet.v1": (
            "alberta",
            "six",
        ),
        "open_agronomy_agent.manitoba_applied_guidance_packet.v1": (
            "manitoba",
            "eight",
        ),
    }.get(packet_schema)
    if signed_group is not None:
        jurisdiction, candidate_count = signed_group
        raise PromotionBlocked(
            "review_evidence",
            [
                f"{jurisdiction}_unsigned_csv_not_promotion_evidence",
                (
                    f"{jurisdiction}_signed_{candidate_count}_candidate_"
                    "group_gate_required"
                ),
                f"use_{jurisdiction}_group_promotion_fingerprint",
            ],
        )
    review = inspect_review_packet(
        repo_root=repo_root,
        packet_dir=packet_dir,
        outcomes_path=outcomes_path,
    )
    readiness = validate_review_readiness_receipt(
        review=review, readiness_path=review_readiness_path
    )
    rows = build_candidate_corpus_rows(
        review=review,
        review_readiness_sha256=readiness["sha256"],
        evaluation_receipt_sha256=None,
    )
    corpus = render_candidate_corpus(rows)
    return {
        "schema_version": CORPUS_TRANSFORM_SCHEMA,
        "jurisdiction": review["spec"].jurisdiction,
        "packet_manifest_sha256": review["manifest_sha256"],
        "candidates_sha256": review["candidates_sha256"],
        "candidate_set_sha256": review["candidate_set_sha256"],
        "review_outcomes_sha256": review["outcomes_sha256"],
        "review_readiness_receipt_sha256": readiness["sha256"],
        "candidate_ids": review["candidate_ids"],
        "candidate_source_family_ids": sorted(
            {str(row["source_id"]) for row in rows}
        ),
        "evaluated_corpus_sha256": _sha256_bytes(corpus),
        "row_count": len(rows),
        "boundary": (
            "This fingerprint is deterministic evaluation input, not runtime admission. "
            "Only candidate text is transformed; source PDF and surrounding page text are excluded."
        ),
    }


def validate_disjoint_evaluation_receipt(
    *,
    receipt_path: Path,
    fingerprint: dict[str, Any],
    repo_root: Path,
    coordinator_public_key_path: Path | None = None,
    expected_coordinator_public_key_sha256: str | None = None,
) -> dict[str, Any]:
    receipt_path = receipt_path.resolve()
    repo_root = repo_root.resolve()
    try:
        receipt = _load_json(receipt_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PromotionBlocked("disjoint_evaluation", [f"receipt_invalid:{exc}"]) from exc
    blockers = []
    if (
        coordinator_public_key_path is None
        or not _hash_like(expected_coordinator_public_key_sha256)
    ):
        blockers.append("evaluation_coordinator_signature_key_required")
    else:
        public_key_path = coordinator_public_key_path.resolve()
        if (
            not public_key_path.is_file()
            or sha256_path(public_key_path)
            != expected_coordinator_public_key_sha256
        ):
            blockers.append("evaluation_coordinator_public_key_pin_mismatch")
        else:
            try:
                signature = verify_manifest_signature(
                    manifest=receipt_path,
                    signature=receipt_path.with_suffix(".sig"),
                    public_key=public_key_path,
                )
            except (OSError, RuntimeError, ValueError):
                blockers.append("evaluation_receipt_signature_invalid")
            else:
                if not signature["verified"]:
                    blockers.append("evaluation_receipt_signature_invalid")
    expected = {
        "schema_version": DISJOINT_EVAL_RECEIPT_SCHEMA,
        "status": "pass",
        "promotion_allowed": True,
        "jurisdiction": fingerprint["jurisdiction"],
        "packet_manifest_sha256": fingerprint["packet_manifest_sha256"],
        "candidates_sha256": fingerprint["candidates_sha256"],
        "candidate_set_sha256": fingerprint["candidate_set_sha256"],
        "review_outcomes_sha256": fingerprint["review_outcomes_sha256"],
        "review_readiness_receipt_sha256": fingerprint[
            "review_readiness_receipt_sha256"
        ],
        "candidate_ids": fingerprint["candidate_ids"],
        "candidate_source_family_ids": fingerprint[
            "candidate_source_family_ids"
        ],
        "evaluated_corpus_sha256": fingerprint["evaluated_corpus_sha256"],
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            blockers.append(f"evaluation_{key}_mismatch")
    split = receipt.get("split_integrity") or {}
    for key in (
        "candidate_source_families_excluded_from_held_out_gold",
        "same_document_chunks_disjoint",
        "superseded_and_current_editions_grouped",
        "question_authors_blinded_to_candidate_answers_and_model_outputs",
    ):
        if split.get(key) is not True:
            blockers.append(f"evaluation_split_{key}_not_proven")
    if split.get("exact_overlap_count") != 0:
        blockers.append("evaluation_exact_overlap_detected")
    if split.get("near_duplicate_review_status") != "pass":
        blockers.append("evaluation_near_duplicate_review_not_passed")
    execution = receipt.get("execution") or {}
    seeds = execution.get("random_seeds")
    if (
        not isinstance(seeds, list)
        or len(seeds) < 3
        or len(seeds) != len(set(seeds))
        or any(not isinstance(seed, int) for seed in seeds)
    ):
        blockers.append("evaluation_random_seeds_invalid")
    for mode in ("offline", "online"):
        mode_result = (execution.get("modes") or {}).get(mode) or {}
        if mode_result.get("status") != "pass":
            blockers.append(f"evaluation_{mode}_mode_not_passed")
    for key in (
        "runtime_contract_sha256",
        "model_artifact_sha256",
        "adapter_artifact_sha256",
        "retrieval_snapshot_sha256",
    ):
        if not _hash_like(execution.get(key)):
            blockers.append(f"evaluation_{key}_invalid")

    artifact_rows: dict[str, Any] = {}
    artifact_specs = receipt.get("artifacts") or {}
    receipt_root = receipt_path.parent
    for artifact_id, is_jsonl in (
        ("evaluation_contract", False),
        ("case_manifest", True),
        ("case_results", True),
        ("human_reviews", True),
        ("overlap_report", False),
    ):
        descriptor = artifact_specs.get(artifact_id) or {}
        try:
            artifact_path = _safe_child(
                receipt_root, str(descriptor.get("path") or "")
            )
            claimed_hash = str(descriptor.get("sha256") or "")
            if (
                not artifact_path.is_file()
                or not _hash_like(claimed_hash)
                or sha256_path(artifact_path) != claimed_hash
            ):
                raise ValueError("missing or hash mismatch")
            payload: Any = (
                _load_jsonl(artifact_path)
                if is_jsonl
                else _load_json(artifact_path)
            )
            if is_jsonl and descriptor.get("row_count") != len(payload):
                raise ValueError("row count mismatch")
            artifact_rows[artifact_id] = payload
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blockers.append(
                f"evaluation_artifact_invalid:{artifact_id}:{exc}"
            )

    contract = artifact_rows.get("evaluation_contract") or {}
    if (
        contract.get("schema_version")
        != "open_agronomy_agent.canadian_applied_guidance_admission_eval_contract.v1"
        or contract.get("results_claimed") is not False
        or contract.get("runtime_admission_before_gate") is not False
    ):
        blockers.append("evaluation_contract_invalid")
    contract_gates = {
        row.get("metric"): row.get("threshold")
        for row in contract.get("metrics_and_gates") or []
        if isinstance(row, dict)
    }
    for name, threshold in METRIC_GATES.items():
        if contract_gates.get(name) != threshold:
            blockers.append(f"evaluation_contract_gate_mismatch:{name}")
    if contract_gates.get("critical_safety_errors") != 0:
        blockers.append("evaluation_contract_critical_gate_invalid")

    burned_registry_path = (
        repo_root / BURNED_QUESTION_REGISTRY_RELATIVE_PATH
    )
    burned_question_hashes: set[str] = set()
    try:
        burned_registry = _load_json(burned_registry_path)
        burned_rows = burned_registry.get("questions") or []
        burned_question_hashes = {
            str(row.get("question_sha256") or "")
            for row in burned_rows
            if isinstance(row, dict)
        }
        if (
            burned_registry.get("schema_version")
            != BURNED_QUESTION_REGISTRY_SCHEMA
            or burned_registry.get("status")
            != "active_fail_closed_exclusion_registry"
            or burned_registry.get("question_count") != len(burned_rows)
            or len(burned_question_hashes) != len(burned_rows)
            or any(not _hash_like(value) for value in burned_question_hashes)
            or any(
                row.get("promotion_eval_eligible") is not False
                or int(row.get("prior_output_count") or 0) < 1
                for row in burned_rows
            )
        ):
            raise ValueError("registry contract invalid")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        blockers.append(f"evaluation_burned_question_registry_invalid:{exc}")

    cases = artifact_rows.get("case_manifest") or []
    cases_by_id: dict[str, dict[str, Any]] = {}
    held_out_families: set[str] = set()
    candidate_families = set(fingerprint.get("candidate_source_family_ids") or [])
    for row in cases:
        case_id = str(row.get("case_id") or "")
        source_families = row.get("gold_source_family_ids")
        source_hashes = row.get("gold_source_artifact_sha256s")
        slices = row.get("task_slices")
        failure_classes = row.get("failure_classes")
        if (
            row.get("schema_version") != EVAL_CASE_SCHEMA
            or not case_id
            or case_id in cases_by_id
            or not _hash_like(row.get("question_sha256"))
            or not _hash_like(row.get("gold_answer_sha256"))
            or not isinstance(source_families, list)
            or not source_families
            or len(source_families) != len(set(source_families))
            or not isinstance(source_hashes, list)
            or not source_hashes
            or any(not _hash_like(value) for value in source_hashes)
            or not str(row.get("jurisdiction") or "")
            or row.get("language") not in {"en-CA", "fr-CA"}
            or not isinstance(slices, list)
            or not slices
            or len(slices) != len(set(slices))
            or not isinstance(failure_classes, list)
            or len(failure_classes) != len(set(failure_classes))
            or not isinstance(row.get("recommendation_bearing"), bool)
            or row.get("prior_system_generation_count") != 0
            or row.get("independent_question_authoring_verified") is not True
            or not _hash_like(
                row.get("question_authoring_evidence_sha256")
            )
            or not _hash_like(
                row.get("independent_question_review_evidence_sha256")
            )
        ):
            blockers.append(f"evaluation_case_invalid:{case_id or 'missing'}")
            continue
        if row["question_sha256"] in burned_question_hashes:
            blockers.append(f"evaluation_burned_question_reused:{case_id}")
            continue
        held_out_families.update(str(value) for value in source_families)
        cases_by_id[case_id] = row
    if not cases_by_id:
        blockers.append("evaluation_case_manifest_empty")
    if candidate_families & held_out_families:
        blockers.append("evaluation_candidate_gold_source_family_overlap")

    required_slices = {
        str(row.get("slice_id")): row
        for row in contract.get("required_slices") or []
        if isinstance(row, dict) and row.get("slice_id")
    }
    for slice_id, requirement in required_slices.items():
        matching = [
            row for row in cases_by_id.values()
            if slice_id in (row.get("task_slices") or [])
        ]
        for failure_class in requirement.get("required_failures") or []:
            if not any(
                failure_class in (row.get("failure_classes") or [])
                for row in matching
            ):
                blockers.append(
                    f"evaluation_required_failure_class_missing:"
                    f"{slice_id}:{failure_class}"
                )
        minimum = int(requirement.get("minimum_cases") or 0)
        if minimum and len(matching) < minimum:
            blockers.append(
                f"evaluation_slice_under_minimum:{slice_id}:{len(matching)}/{minimum}"
            )
        per_jurisdiction = int(
            requirement.get("minimum_cases_per_covered_jurisdiction") or 0
        )
        if per_jurisdiction:
            counts: dict[str, int] = {}
            for row in matching:
                key = str(row["jurisdiction"])
                counts[key] = counts.get(key, 0) + 1
            if (
                fingerprint["jurisdiction"] not in counts
                or any(value < per_jurisdiction for value in counts.values())
            ):
                blockers.append(
                    f"evaluation_slice_jurisdiction_under_minimum:{slice_id}"
                )
        per_pair = int(
            requirement.get("minimum_cases_per_language_pair") or 0
        )
        if per_pair:
            pairs: dict[str, list[dict[str, Any]]] = {}
            for row in matching:
                pair_id = str(row.get("language_pair_id") or "")
                pairs.setdefault(pair_id, []).append(row)
            if (
                "" in pairs
                or not pairs
                or any(
                    len(rows) < per_pair
                    or any(
                        sum(
                            1
                            for item in rows
                            if item["language"] == language
                        )
                        < per_pair
                        for language in ("en-CA", "fr-CA")
                    )
                    for rows in pairs.values()
                )
            ):
                blockers.append(
                    f"evaluation_slice_language_pair_under_minimum:{slice_id}"
                )
        per_numeric = int(
            requirement.get("minimum_cases_per_numeric_source_family") or 0
        )
        if per_numeric:
            numeric: dict[str, int] = {}
            for row in matching:
                family = str(row.get("numeric_source_family_id") or "")
                numeric[family] = numeric.get(family, 0) + 1
            if (
                "" in numeric
                or not numeric
                or any(value < per_numeric for value in numeric.values())
            ):
                blockers.append(
                    f"evaluation_slice_numeric_family_under_minimum:{slice_id}"
                )

    overlap = artifact_rows.get("overlap_report") or {}
    if (
        overlap.get("schema_version") != EVAL_OVERLAP_REPORT_SCHEMA
        or overlap.get("evaluated_corpus_sha256")
        != fingerprint["evaluated_corpus_sha256"]
        or overlap.get("case_manifest_sha256")
        != (artifact_specs.get("case_manifest") or {}).get("sha256")
        or overlap.get("candidate_source_family_ids")
        != sorted(candidate_families)
        or overlap.get("held_out_gold_source_family_ids")
        != sorted(held_out_families)
        or overlap.get("exact_overlap_count") != 0
        or overlap.get("near_duplicate_review_status") != "pass"
    ):
        blockers.append("evaluation_overlap_report_invalid")

    results = artifact_rows.get("case_results") or []
    expected_seeds = set(seeds) if isinstance(seeds, list) else set()
    expected_modes = {"offline", "online"}
    result_keys: set[tuple[str, str, int]] = set()
    metric_totals = {
        name: [0, 0] for name in (*METRIC_GATES, "bilingual_quality_pass")
    }
    grouped_totals: dict[str, dict[str, list[int]]] = {
        "retrieval_source_recall": {},
        "retrieval_jurisdiction_precision": {},
        "context_relevance": {},
        "unsafe_or_out_of_scope_abstention": {},
    }
    critical_safety_errors = 0

    def add_count(
        totals: dict[str, list[int]], key: str, numerator: int, denominator: int
    ) -> None:
        bucket = totals.setdefault(key, [0, 0])
        bucket[0] += numerator
        bucket[1] += denominator

    for row in results:
        case_id = str(row.get("case_id") or "")
        mode = str(row.get("mode") or "")
        seed = row.get("seed")
        key = (case_id, mode, seed) if isinstance(seed, int) else None
        counts = row.get("metric_counts") or {}
        case = cases_by_id.get(case_id)
        if (
            row.get("schema_version") != EVAL_CASE_RESULT_SCHEMA
            or case is None
            or mode not in expected_modes
            or seed not in expected_seeds
            or key is None
            or key in result_keys
            or not _hash_like(row.get("output_sha256"))
            or not _hash_like(row.get("answer_trace_sha256"))
            or row.get("runtime_contract_sha256")
            != execution.get("runtime_contract_sha256")
            or row.get("model_artifact_sha256")
            != execution.get("model_artifact_sha256")
            or row.get("adapter_artifact_sha256")
            != execution.get("adapter_artifact_sha256")
            or row.get("retrieval_snapshot_sha256")
            != execution.get("retrieval_snapshot_sha256")
            or (
                mode == "offline"
                and (
                    row.get("network_access_observed") is not False
                    or row.get("external_tool_call_count") != 0
                )
            )
        ):
            blockers.append(
                f"evaluation_case_result_invalid:{case_id}:{mode}:{seed}"
            )
            continue
        result_keys.add(key)
        metric_values: dict[str, tuple[int, int]] = {}
        for name in metric_totals:
            metric = counts.get(name) or {}
            numerator = metric.get("numerator")
            denominator = metric.get("denominator")
            if (
                not isinstance(numerator, int)
                or not isinstance(denominator, int)
                or denominator <= 0
                or numerator < 0
                or numerator > denominator
            ):
                blockers.append(
                    f"evaluation_metric_count_invalid:{case_id}:{mode}:{seed}:{name}"
                )
                continue
            metric_values[name] = (numerator, denominator)
            metric_totals[name][0] += numerator
            metric_totals[name][1] += denominator
        critical = row.get("critical_safety_errors")
        if not isinstance(critical, int) or critical < 0:
            blockers.append(
                f"evaluation_critical_count_invalid:{case_id}:{mode}:{seed}"
            )
        else:
            critical_safety_errors += critical
        for name, dimensions in (
            (
                "retrieval_source_recall",
                [str(case["jurisdiction"]), str(case["language"])],
            ),
            (
                "retrieval_jurisdiction_precision",
                [str(case["jurisdiction"])],
            ),
            ("context_relevance", list(case.get("task_slices") or [])),
            (
                "unsafe_or_out_of_scope_abstention",
                list(case.get("failure_classes") or []),
            ),
        ):
            if name in metric_values:
                numerator, denominator = metric_values[name]
                for dimension in dimensions:
                    add_count(
                        grouped_totals[name],
                        dimension,
                        numerator,
                        denominator,
                    )

    expected_result_keys = {
        (case_id, mode, seed)
        for case_id in cases_by_id
        for mode in expected_modes
        for seed in expected_seeds
    }
    if result_keys != expected_result_keys:
        blockers.append(
            "evaluation_case_result_matrix_incomplete:"
            f"{len(result_keys)}/{len(expected_result_keys)}"
        )

    recomputed_metrics: dict[str, float | int] = {}
    for name, threshold in METRIC_GATES.items():
        numerator, denominator = metric_totals[name]
        value = numerator / denominator if denominator else -1.0
        if grouped_totals.get(name):
            grouped_rates = [
                num / den
                for num, den in grouped_totals[name].values()
                if den
            ]
            value = min(grouped_rates) if grouped_rates else -1.0
        recomputed_metrics[name] = value
        if value < threshold:
            blockers.append(f"evaluation_metric_below_gate:{name}")
    recomputed_metrics["critical_safety_errors"] = critical_safety_errors
    if critical_safety_errors != 0:
        blockers.append("evaluation_critical_safety_errors_nonzero")
    bilingual_by_language: dict[str, list[int]] = {}
    for row in results:
        case = cases_by_id.get(str(row.get("case_id") or ""))
        metric = (row.get("metric_counts") or {}).get(
            "bilingual_quality_pass"
        ) or {}
        if (
            case is not None
            and isinstance(metric.get("numerator"), int)
            and isinstance(metric.get("denominator"), int)
            and metric["denominator"] > 0
        ):
            add_count(
                bilingual_by_language,
                str(case["language"]),
                metric["numerator"],
                metric["denominator"],
            )
    if set(bilingual_by_language) != {"en-CA", "fr-CA"}:
        bilingual_gap = 1.0
        blockers.append("evaluation_bilingual_languages_incomplete")
    else:
        rates = [
            numerator / denominator
            for numerator, denominator in bilingual_by_language.values()
        ]
        bilingual_gap = abs(rates[0] - rates[1])
    recomputed_metrics["bilingual_quality_gap"] = bilingual_gap
    if bilingual_gap > 0.03:
        blockers.append("evaluation_bilingual_quality_gap_above_gate")
    claimed_metrics = receipt.get("metrics") or {}
    for name, value in recomputed_metrics.items():
        claimed = claimed_metrics.get(name)
        if (
            not isinstance(claimed, (int, float))
            or abs(float(claimed) - float(value)) > 1e-12
        ):
            blockers.append(f"evaluation_metric_not_reproducible:{name}")

    review_rows = artifact_rows.get("human_reviews") or []
    reviews_by_case: dict[str, list[dict[str, Any]]] = {}
    for row in review_rows:
        case_id = str(row.get("case_id") or "")
        reviewer_id = str(row.get("reviewer_id") or "")
        if (
            row.get("schema_version") != EVAL_HUMAN_REVIEW_SCHEMA
            or case_id not in cases_by_id
            or not reviewer_id
            or not str(row.get("reviewer_role") or "")
            or row.get("disposition") != "pass"
            or row.get("all_actionable_claims_reviewed") is not True
            or row.get("all_numerical_claims_reviewed") is not True
            or not _hash_like(row.get("review_record_sha256"))
        ):
            blockers.append(
                f"evaluation_human_review_row_invalid:{case_id}:{reviewer_id}"
            )
            continue
        reviews_by_case.setdefault(case_id, []).append(row)
    recommendation_cases = [
        case_id
        for case_id, row in cases_by_id.items()
        if row["recommendation_bearing"]
    ]
    for case_id in recommendation_cases:
        rows = reviews_by_case.get(case_id) or []
        reviewer_ids = {str(row["reviewer_id"]) for row in rows}
        roles = {str(row["reviewer_role"]) for row in rows}
        if len(reviewer_ids) < 2 or "independent_agronomist" not in roles:
            blockers.append(
                f"evaluation_human_review_incomplete:{case_id}"
            )
    human = receipt.get("human_review") or {}
    if (
        human.get("status") != "pass"
        or human.get("recommendation_case_count")
        != len(recommendation_cases)
        or human.get("reviewed_recommendation_case_count")
        != sum(
            1
            for case_id in recommendation_cases
            if len(
                {
                    str(row["reviewer_id"])
                    for row in reviews_by_case.get(case_id) or []
                }
            )
            >= 2
        )
        or human.get("independent_reviewers_per_recommendation_item") != 2
        or human.get("independent_agronomist_included") is not True
        or human.get("all_actionable_and_numerical_claims_reviewed") is not True
    ):
        blockers.append("evaluation_human_review_summary_invalid")
    if blockers:
        raise PromotionBlocked("disjoint_evaluation", blockers)
    return {
        "path": str(receipt_path),
        "sha256": sha256_path(receipt_path),
        "case_count": len(cases_by_id),
        "case_result_count": len(result_keys),
        "metrics": recomputed_metrics,
        "receipt": receipt,
    }


def _validate_target_path(repo_root: Path, target_corpus_path: str) -> Path:
    posix = PurePosixPath(target_corpus_path)
    if (
        posix.is_absolute()
        or posix.suffix != ".jsonl"
        or posix.parts[:3] != ("data", "derived", "rag")
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise PromotionBlocked(
            "staging",
            [
                "target_corpus_path_must_be_new_jsonl_under_data/derived/rag"
            ],
        )
    target = _safe_child(repo_root, target_corpus_path)
    if target.exists() or target.is_symlink():
        raise PromotionBlocked("staging", ["target_corpus_path_already_exists"])
    return target


def _load_queue(
    *, repo_root: Path, queue_path: Path, jurisdiction: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    queue_path = queue_path.resolve()
    try:
        queue = _load_json(queue_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise PromotionBlocked("admission_queue", [f"queue_invalid:{exc}"]) from exc
    blockers = []
    if queue.get("schema_version") != QUEUE_SCHEMA:
        blockers.append("queue_schema_invalid")
    active = queue.get("recommendation_grade_active_jurisdictions")
    rows = [row for row in queue.get("rows") or [] if isinstance(row, dict)]
    row_jurisdictions = [str(row.get("jurisdiction") or "") for row in rows]
    active_rows = sorted(
        str(row.get("jurisdiction") or "")
        for row in rows
        if row.get("admission_state") == "active_decisive"
    )
    if (
        not isinstance(active, list)
        or len(active) != len(set(active))
        or sorted(active) != active_rows
        or queue.get("recommendation_grade_active_provinces") != len(active)
        or len(row_jurisdictions) != 10
        or len(row_jurisdictions) != len(set(row_jurisdictions))
        or jurisdiction in active
    ):
        blockers.append("jurisdiction_already_active_or_active_list_invalid")
    matches = [
        row
        for row in rows
        if row.get("jurisdiction") == jurisdiction
    ]
    if len(matches) != 1:
        blockers.append("queue_jurisdiction_row_missing_or_duplicate")
        row = {}
    else:
        row = matches[0]
        expected_state = (
            "candidate_pending_independent_professional_review"
            if jurisdiction == "British Columbia"
            else "candidate_pending_independent_agronomist"
        )
        if row.get("admission_state") != expected_state:
            blockers.append("queue_candidate_state_changed")
    if blockers:
        raise PromotionBlocked("admission_queue", blockers)
    return queue, row


def stage_promotion_proposal(
    *,
    repo_root: Path,
    packet_dir: Path,
    outcomes_path: Path,
    review_readiness_path: Path,
    evaluation_receipt_path: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    admission_queue_path: Path,
    output_dir: Path,
    target_corpus_path: str,
) -> dict[str, Any]:
    """Stage immutable proposal artifacts without mutating any active runtime input."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() or output_dir.is_symlink():
        raise PromotionBlocked("staging", ["output_directory_already_exists"])
    _validate_target_path(repo_root, target_corpus_path)
    fingerprint = promotion_fingerprint(
        repo_root=repo_root,
        packet_dir=packet_dir,
        outcomes_path=outcomes_path,
        review_readiness_path=review_readiness_path,
    )
    evaluation = validate_disjoint_evaluation_receipt(
        receipt_path=evaluation_receipt_path,
        fingerprint=fingerprint,
        repo_root=repo_root,
        coordinator_public_key_path=coordinator_public_key_path,
        expected_coordinator_public_key_sha256=(
            expected_coordinator_public_key_sha256
        ),
    )
    review = inspect_review_packet(
        repo_root=repo_root,
        packet_dir=packet_dir,
        outcomes_path=outcomes_path,
    )
    readiness = validate_review_readiness_receipt(
        review=review, readiness_path=review_readiness_path
    )
    queue, queue_row = _load_queue(
        repo_root=repo_root,
        queue_path=admission_queue_path,
        jurisdiction=review["spec"].jurisdiction,
    )
    rows = build_candidate_corpus_rows(
        review=review,
        review_readiness_sha256=readiness["sha256"],
        evaluation_receipt_sha256=evaluation["sha256"],
    )
    corpus_bytes = render_candidate_corpus(rows)
    staged_corpus_sha256 = _sha256_bytes(corpus_bytes)
    if staged_corpus_sha256 != fingerprint["evaluated_corpus_sha256"]:
        raise PromotionBlocked(
            "staging", ["evaluated_and_staged_corpus_hashes_differ"]
        )
    queue_sha256 = sha256_path(admission_queue_path.resolve())
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    evidence = {
        "packet_manifest_sha256": review["manifest_sha256"],
        "candidate_file_sha256": review["candidates_sha256"],
        "candidate_set_sha256": review["candidate_set_sha256"],
        "review_outcomes_sha256": review["outcomes_sha256"],
        "review_readiness_receipt_sha256": readiness["sha256"],
        "disjoint_evaluation_receipt_sha256": evaluation["sha256"],
        "evaluation_input_corpus_sha256": fingerprint["evaluated_corpus_sha256"],
        "staged_corpus_sha256": staged_corpus_sha256,
        "base_admission_queue_sha256": queue_sha256,
    }
    replacement_row = dict(queue_row)
    replacement_row.update(
        {
            "admission_state": "active_decisive",
            "next_action": (
                "Monitor source currency, rerun the bound disjoint evaluation after "
                "any candidate or runtime change, and ship only through a signed, "
                "rollback-capable knowledge release."
            ),
            "promotion_evidence": evidence,
        }
    )
    queue_patch = {
        "schema_version": QUEUE_PATCH_SCHEMA,
        "generated_at": generated_at,
        "automatic_application": False,
        "jurisdiction": review["spec"].jurisdiction,
        "base_queue": {
            "path": str(admission_queue_path.resolve()),
            "sha256": queue_sha256,
            "expected_active_jurisdictions": queue[
                "recommendation_grade_active_jurisdictions"
            ],
        },
        "expected_current_row": queue_row,
        "proposed_replacement_row": replacement_row,
        "proposed_active_jurisdictions": sorted(
            {
                *queue["recommendation_grade_active_jurisdictions"],
                review["spec"].jurisdiction,
            }
        ),
        "evidence": evidence,
        "boundary": (
            "This is a compare-and-swap proposal. It does not edit the admission "
            "queue and must be applied atomically with the corpus, policy, RAG config, "
            "tests, and a newly sealed release."
        ),
    }
    policy_patch = {
        "schema_version": POLICY_PATCH_SCHEMA,
        "generated_at": generated_at,
        "automatic_application": False,
        "proposed_entry": {
            "path": target_corpus_path,
            "sha256": staged_corpus_sha256,
            "runtime_eligibility": "decisive",
            "evidence_tier": "independently_reviewed_government_applied_guidance",
            "rights_status": "redistributable_project_authored_summary_only",
            "reason": (
                f"Candidate-only {review['spec'].jurisdiction} summaries passed "
                "hash-bound external review and source-family-disjoint evaluation. "
                "Source PDF and neighboring page text are excluded."
            ),
        },
        "evidence": evidence,
        "boundary": (
            "This proposed policy entry is inactive until an operator builds and "
            "validates a complete runtime policy and RAG configuration."
        ),
    }
    manifest = {
        "schema_version": PROMOTION_MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "status": "staged_not_active",
        "jurisdiction": review["spec"].jurisdiction,
        "activation_automatic": False,
        "candidate_only_transform": True,
        "source_pdf_or_page_text_ingested": False,
        "staged_corpus": {
            "path": "reviewed_applied_guidance_candidates.jsonl",
            "sha256": staged_corpus_sha256,
            "row_count": len(rows),
            "candidate_ids": review["candidate_ids"],
            "proposed_repository_path": target_corpus_path,
        },
        "artifacts": {
            "queue_patch_proposal": "admission_queue_patch_proposal.json",
            "policy_entry_proposal": "runtime_corpus_policy_entry_proposal.json",
        },
        "evidence": evidence,
        "required_operator_actions": [
            "Independently verify reviewer credentials and conflict declarations.",
            "Compare-and-swap the exact base admission queue; do not hand-edit around a stale hash.",
            "Copy the corpus to the new proposed path without overwriting an existing file.",
            "Add the exact hash-bound policy entry and RAG path in the same release source state.",
            "Run corpus governance, retrieval, answer-safety, offline, online, lineage, and rollback tests.",
            "Build, sign, verify, and seal a new runtime and knowledge release; preserve the prior release for rollback.",
        ],
        "boundary": (
            "Staging is not admission. No active source file is modified, and no "
            "runtime may consume this corpus until every operator action succeeds."
        ),
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.", dir=output_dir.parent
    ) as temp_name:
        temp_dir = Path(temp_name)
        (temp_dir / "reviewed_applied_guidance_candidates.jsonl").write_bytes(
            corpus_bytes
        )
        (temp_dir / "admission_queue_patch_proposal.json").write_text(
            json.dumps(queue_patch, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        (temp_dir / "runtime_corpus_policy_entry_proposal.json").write_text(
            json.dumps(policy_patch, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        (temp_dir / "promotion_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temp_dir, output_dir)
    return {
        **manifest,
        "output_dir": str(output_dir),
        "promotion_manifest_sha256": sha256_path(
            output_dir / "promotion_manifest.json"
        ),
    }


def _stage_signed_group_promotion_proposal(
    *,
    jurisdiction: str,
    repo_root: Path,
    packet_registry_path: Path,
    expected_packet_registry_sha256: str,
    evidence_dir: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    evaluation_receipt_path: Path,
    admission_queue_path: Path,
    output_dir: Path,
    target_corpus_path: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Stage a signed provincial candidate group without activating it."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() or output_dir.is_symlink():
        raise PromotionBlocked("staging", ["output_directory_already_exists"])
    _validate_target_path(repo_root, target_corpus_path)
    fingerprint_kwargs = {
        "repo_root": repo_root,
        "packet_registry_path": packet_registry_path,
        "expected_packet_registry_sha256": expected_packet_registry_sha256,
        "evidence_dir": evidence_dir,
        "coordinator_public_key_path": coordinator_public_key_path,
        "expected_coordinator_public_key_sha256": (
            expected_coordinator_public_key_sha256
        ),
        "now": now,
    }
    if jurisdiction == "Alberta":
        fingerprint = alberta_group_promotion_fingerprint(
            **fingerprint_kwargs
        )
    elif jurisdiction == "British Columbia":
        fingerprint = british_columbia_group_promotion_fingerprint(
            **fingerprint_kwargs
        )
    elif jurisdiction == "Manitoba":
        fingerprint = manitoba_group_promotion_fingerprint(
            **fingerprint_kwargs
        )
    else:
        raise PromotionBlocked(
            "staging", [f"signed_group_jurisdiction_unsupported:{jurisdiction}"]
        )
    evaluation = validate_disjoint_evaluation_receipt(
        receipt_path=evaluation_receipt_path,
        fingerprint=fingerprint,
        repo_root=repo_root,
        coordinator_public_key_path=coordinator_public_key_path,
        expected_coordinator_public_key_sha256=(
            expected_coordinator_public_key_sha256
        ),
    )
    try:
        verification = verify_group_review_evidence(
            repo_root=repo_root,
            packet_registry_path=packet_registry_path,
            expected_packet_registry_sha256=expected_packet_registry_sha256,
            evidence_dir=evidence_dir,
            coordinator_public_key_path=coordinator_public_key_path,
            expected_coordinator_public_key_sha256=(
                expected_coordinator_public_key_sha256
            ),
            jurisdiction=jurisdiction,
            now=now,
        )
        candidates, _ = _load_expected_candidates(
            repo_root=repo_root,
            packet_registry=_load_json(packet_registry_path.resolve()),
            jurisdiction=jurisdiction,
        )
    except ReviewEvidenceBlocked as exc:
        raise PromotionBlocked("review_evidence", exc.blockers) from exc
    queue, queue_row = _load_queue(
        repo_root=repo_root,
        queue_path=admission_queue_path,
        jurisdiction=jurisdiction,
    )
    if jurisdiction == "Alberta":
        rows = build_alberta_group_candidate_corpus_rows(
            candidates=candidates,
            verification=verification,
        )
    elif jurisdiction == "British Columbia":
        rows = build_british_columbia_group_candidate_corpus_rows(
            candidates=candidates,
            verification=verification,
        )
    else:
        rows = build_manitoba_group_candidate_corpus_rows(
            candidates=candidates,
            verification=verification,
        )
    corpus_bytes = render_candidate_corpus(rows)
    staged_corpus_sha256 = _sha256_bytes(corpus_bytes)
    if staged_corpus_sha256 != fingerprint["evaluated_corpus_sha256"]:
        raise PromotionBlocked(
            "staging", ["evaluated_and_staged_corpus_hashes_differ"]
        )
    queue_sha256 = sha256_path(admission_queue_path.resolve())
    generated_at = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    evidence = {
        "packet_registry_sha256": fingerprint["packet_registry_sha256"],
        "packet_manifest_sha256": fingerprint["packet_manifest_sha256"],
        "packet_manifest_sha256s": fingerprint["packet_manifest_sha256s"],
        "candidate_artifacts_sha256": fingerprint["candidates_sha256"],
        "candidate_artifact_sha256s": fingerprint[
            "candidate_artifact_sha256s"
        ],
        "candidate_set_sha256": fingerprint["candidate_set_sha256"],
        "reviewer_registry_sha256": fingerprint[
            "reviewer_registry_sha256"
        ],
        "review_assignment_sha256": fingerprint[
            "review_assignment_sha256"
        ],
        "signed_review_evidence_sha256": fingerprint[
            "review_outcomes_sha256"
        ],
        "signed_review_verification_sha256": fingerprint[
            "signed_review_verification_sha256"
        ],
        "disjoint_evaluation_receipt_sha256": evaluation["sha256"],
        "evaluation_input_corpus_sha256": fingerprint[
            "evaluated_corpus_sha256"
        ],
        "staged_corpus_sha256": staged_corpus_sha256,
        "base_admission_queue_sha256": queue_sha256,
    }
    replacement_row = dict(queue_row)
    replacement_row.update(
        {
            "admission_state": "active_decisive",
            "next_action": (
                "Monitor every bound source family, rerun signed review and "
                "disjoint evaluation after any candidate, evidence or runtime "
                "change, and ship only through a signed rollback-capable "
                "knowledge release."
            ),
            "promotion_evidence": evidence,
        }
    )
    queue_patch = {
        "schema_version": QUEUE_PATCH_SCHEMA,
        "generated_at": generated_at,
        "automatic_application": False,
        "jurisdiction": jurisdiction,
        "base_queue": {
            "path": str(admission_queue_path.resolve()),
            "sha256": queue_sha256,
            "expected_active_jurisdictions": queue[
                "recommendation_grade_active_jurisdictions"
            ],
        },
        "expected_current_row": queue_row,
        "proposed_replacement_row": replacement_row,
        "proposed_active_jurisdictions": sorted(
            {
                *queue["recommendation_grade_active_jurisdictions"],
                jurisdiction,
            }
        ),
        "evidence": evidence,
        "boundary": (
            "This compare-and-swap proposal does not edit the admission queue "
            "and must be applied atomically with corpus, policy, RAG config, "
            "tests and a newly sealed release."
        ),
    }
    policy_patch = {
        "schema_version": POLICY_PATCH_SCHEMA,
        "generated_at": generated_at,
        "automatic_application": False,
        "proposed_entry": {
            "path": target_corpus_path,
            "sha256": staged_corpus_sha256,
            "runtime_eligibility": "decisive",
            "evidence_tier": (
                "independently_reviewed_government_applied_guidance"
            ),
            "rights_status": (
                "redistributable_project_authored_summary_only"
            ),
            "reason": (
                f"{len(rows)} candidate-only {jurisdiction} summaries passed "
                "signed external review and source-family-disjoint evaluation. "
                "Source PDF, HTML, images, product tables and neighboring text "
                "are excluded."
            ),
        },
        "evidence": evidence,
        "boundary": (
            "This policy entry remains inactive until a complete runtime policy "
            "and RAG configuration are independently validated."
        ),
    }
    manifest = {
        "schema_version": PROMOTION_MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "status": "staged_not_active",
        "jurisdiction": jurisdiction,
        "packet_group_id": verification["packet_group_id"],
        "activation_automatic": False,
        "candidate_only_transform": True,
        "source_pdf_or_page_text_ingested": False,
        "source_html_or_image_text_ingested": False,
        "staged_corpus": {
            "path": "reviewed_applied_guidance_candidates.jsonl",
            "sha256": staged_corpus_sha256,
            "row_count": len(rows),
            "candidate_ids": fingerprint["candidate_ids"],
            "proposed_repository_path": target_corpus_path,
        },
        "artifacts": {
            "queue_patch_proposal": "admission_queue_patch_proposal.json",
            "policy_entry_proposal": "runtime_corpus_policy_entry_proposal.json",
        },
        "evidence": evidence,
        "required_operator_actions": [
            "Independently verify coordinator identity, reviewer credentials and conflict declarations.",
            "Compare-and-swap the exact base admission queue and do not bypass a stale hash.",
            "Apply the exact corpus, policy and RAG changes in one release source state.",
            "Rerun governance, retrieval, safety, offline, online, lineage and rollback tests.",
            "Build, sign and verify a new release while preserving the prior release.",
        ],
        "boundary": (
            "Staging is not admission. No active source is modified and no "
            "runtime may consume this corpus until every operator action succeeds."
        ),
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.", dir=output_dir.parent
    ) as temp_name:
        temp_dir = Path(temp_name)
        (temp_dir / "reviewed_applied_guidance_candidates.jsonl").write_bytes(
            corpus_bytes
        )
        for filename, payload in (
            ("admission_queue_patch_proposal.json", queue_patch),
            ("runtime_corpus_policy_entry_proposal.json", policy_patch),
            ("promotion_manifest.json", manifest),
        ):
            (temp_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        os.replace(temp_dir, output_dir)
    return {
        **manifest,
        "output_dir": str(output_dir),
        "promotion_manifest_sha256": sha256_path(
            output_dir / "promotion_manifest.json"
        ),
    }


def stage_alberta_group_promotion_proposal(
    *,
    repo_root: Path,
    packet_registry_path: Path,
    expected_packet_registry_sha256: str,
    evidence_dir: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    evaluation_receipt_path: Path,
    admission_queue_path: Path,
    output_dir: Path,
    target_corpus_path: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Stage the reviewed six-candidate Alberta group without activation."""

    return _stage_signed_group_promotion_proposal(
        jurisdiction="Alberta",
        repo_root=repo_root,
        packet_registry_path=packet_registry_path,
        expected_packet_registry_sha256=expected_packet_registry_sha256,
        evidence_dir=evidence_dir,
        coordinator_public_key_path=coordinator_public_key_path,
        expected_coordinator_public_key_sha256=(
            expected_coordinator_public_key_sha256
        ),
        evaluation_receipt_path=evaluation_receipt_path,
        admission_queue_path=admission_queue_path,
        output_dir=output_dir,
        target_corpus_path=target_corpus_path,
        now=now,
    )


def stage_manitoba_group_promotion_proposal(
    *,
    repo_root: Path,
    packet_registry_path: Path,
    expected_packet_registry_sha256: str,
    evidence_dir: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    evaluation_receipt_path: Path,
    admission_queue_path: Path,
    output_dir: Path,
    target_corpus_path: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Stage the reviewed eight-candidate Manitoba group without activation."""

    return _stage_signed_group_promotion_proposal(
        jurisdiction="Manitoba",
        repo_root=repo_root,
        packet_registry_path=packet_registry_path,
        expected_packet_registry_sha256=expected_packet_registry_sha256,
        evidence_dir=evidence_dir,
        coordinator_public_key_path=coordinator_public_key_path,
        expected_coordinator_public_key_sha256=(
            expected_coordinator_public_key_sha256
        ),
        evaluation_receipt_path=evaluation_receipt_path,
        admission_queue_path=admission_queue_path,
        output_dir=output_dir,
        target_corpus_path=target_corpus_path,
        now=now,
    )


def stage_british_columbia_group_promotion_proposal(
    *,
    repo_root: Path,
    packet_registry_path: Path,
    expected_packet_registry_sha256: str,
    evidence_dir: Path,
    coordinator_public_key_path: Path,
    expected_coordinator_public_key_sha256: str,
    evaluation_receipt_path: Path,
    admission_queue_path: Path,
    output_dir: Path,
    target_corpus_path: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Stage the reviewed one-candidate B.C. group without activation."""

    return _stage_signed_group_promotion_proposal(
        jurisdiction="British Columbia",
        repo_root=repo_root,
        packet_registry_path=packet_registry_path,
        expected_packet_registry_sha256=expected_packet_registry_sha256,
        evidence_dir=evidence_dir,
        coordinator_public_key_path=coordinator_public_key_path,
        expected_coordinator_public_key_sha256=(
            expected_coordinator_public_key_sha256
        ),
        evaluation_receipt_path=evaluation_receipt_path,
        admission_queue_path=admission_queue_path,
        output_dir=output_dir,
        target_corpus_path=target_corpus_path,
        now=now,
    )
