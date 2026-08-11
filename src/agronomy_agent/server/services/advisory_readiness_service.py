from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agronomy_agent.paths import REPO_ROOT, repo_path


ADVISORY_READINESS_PATH = (
    "outputs/current_source_readiness_20260725/advisory_readiness.json"
)
ADVISORY_BLOCKER_BASELINE_PATH = (
    "data/manifests/advisory_blocker_baseline_v1.json"
)
SCHEMA_VERSION = "open_agronomy_agent.system_advisory_readiness.v2"
SOURCE_SCHEMA_VERSION = "open_agronomy_agent.conference_freeze_readiness.v1"
BASELINE_SCHEMA_VERSION = "open_agronomy_agent.advisory_blocker_baseline.v1"
EXTERNAL_ATTESTATION_GATES = frozenset({"freeze_candidate_package"})
KNOWLEDGE_COVERAGE_GATES = frozenset(
    {"applied_guidance_breadth", "french_applied_guidance"}
)


def system_advisory_readiness(
    *,
    knowledge_coverage_ready: bool,
    readiness_path: Path | None = None,
    blocker_baseline_path: Path | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    root = (evidence_root or REPO_ROOT).resolve()
    path = (
        readiness_path
        if readiness_path is not None
        else repo_path(ADVISORY_READINESS_PATH)
    ).resolve()
    try:
        payload = _read_json(path)
        requirements = _validate_readiness_payload(payload)
        evidence_findings = _evidence_findings(
            requirements,
            root=root,
            requirements_manifest=payload["requirements_manifest"],
        )
    except FileNotFoundError as exc:
        baseline_path = (
            blocker_baseline_path
            if blocker_baseline_path is not None
            else repo_path(ADVISORY_BLOCKER_BASELINE_PATH)
        ).resolve()
        try:
            baseline = _read_json(baseline_path)
            _validate_blocker_baseline(baseline, root=root)
            return _baseline_response(
                baseline,
                path=baseline_path,
                knowledge_coverage_ready=knowledge_coverage_ready,
            )
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as baseline_exc:
            return _unavailable_response(
                knowledge_coverage_ready=knowledge_coverage_ready,
                error=(
                    f"full readiness receipt is absent ({exc}); embedded blocker "
                    f"baseline is unavailable or invalid ({baseline_exc})"
                ),
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _unavailable_response(
            knowledge_coverage_ready=knowledge_coverage_ready,
            error=str(exc),
        )

    decisions = payload["decisions"]
    source_blockers = list(decisions["advisory_blockers"])
    blockers = list(source_blockers)
    blocker_details = _source_blocker_details(requirements, source_blockers)
    if (
        not knowledge_coverage_ready
        and "current_knowledge_coverage" not in blockers
        and not KNOWLEDGE_COVERAGE_GATES.issubset(blockers)
    ):
        blockers.append("current_knowledge_coverage")
        blocker_details.append(
            {
                "id": "current_knowledge_coverage",
                "status": "blocked",
                "priority": "P1",
                "criterion": (
                    "The governed local corpus must contain current, admitted applied "
                    "guidance for every province in scope, including French guidance."
                ),
                "note": (
                    "Regional context and source-discovery records do not establish "
                    "recommendation-grade knowledge coverage."
                ),
                "evidence": [],
            }
        )
    if evidence_findings:
        blockers.append("advisory_evidence_stale_or_missing")
        blocker_details.append(
            {
                "id": "advisory_evidence_stale_or_missing",
                "status": "blocked",
                "priority": "P0",
                "criterion": (
                    "Every passing advisory gate must remain bound to the exact current "
                    "evidence bytes declared by the governed readiness receipt."
                ),
                "note": (
                    "Restore or regenerate the named evidence and rerun the readiness "
                    "audit. A stale receipt cannot be treated as a pass."
                ),
                "evidence": evidence_findings,
            }
        )
    blockers = list(dict.fromkeys(blockers))
    advisory_ready = (
        knowledge_coverage_ready
        and decisions["advisory_pilot"] == "pass"
        and not source_blockers
        and not evidence_findings
    )
    passed_count = sum(row["status"] == "pass" for row in requirements)
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "status": "ready" if advisory_ready else "blocked",
        "advisory_ready": advisory_ready,
        "knowledge_coverage_ready": knowledge_coverage_ready,
        "evidence_current": not evidence_findings,
        "verified_evidence_scope": "non_self_referential_advisory_evidence",
        "blockers": blockers,
        "blocker_details": blocker_details,
        "source_generated_at": payload["generated_at"],
        "source_decision": decisions["advisory_pilot"],
        "advisory_requirement_count": len(requirements),
        "passed_advisory_requirement_count": passed_count,
        "external_attestation_required_gates": sorted(
            EXTERNAL_ATTESTATION_GATES.intersection(
                row["id"] for row in requirements
            )
        ),
        "evidence_findings": evidence_findings,
        "message": (
            "All governed advisory requirements and their current evidence pass."
            if advisory_ready
            else "Agronomic advisory use remains blocked by the named system gates."
        ),
        "boundary": (
            "This is a necessary system-readiness gate, not evidence of agronomic "
            "effectiveness for a population or permission for autonomous prescription."
        ),
        "evidence": {
            "advisory_readiness_sha256": _sha256(path),
            "requirements_manifest_sha256": payload["requirements_manifest"]["sha256"],
        },
    }


def _baseline_response(
    payload: dict[str, Any],
    *,
    path: Path,
    knowledge_coverage_ready: bool,
) -> dict[str, Any]:
    blockers = list(payload["blockers"])
    blocker_details = _baseline_blocker_details(payload, path=path)
    if (
        not knowledge_coverage_ready
        and not KNOWLEDGE_COVERAGE_GATES.issubset(blockers)
    ):
        blockers.append("current_knowledge_coverage")
        blocker_details.append(
            {
                "id": "current_knowledge_coverage",
                "status": "blocked",
                "priority": "P1",
                "criterion": (
                    "The governed local corpus must contain current, admitted applied "
                    "guidance for every province in scope, including French guidance."
                ),
                "note": (
                    "Regional context and source-discovery records do not establish "
                    "recommendation-grade knowledge coverage."
                ),
                "evidence": [],
            }
        )
    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": SCHEMA_VERSION,
        "available": True,
        "status": "blocked",
        "advisory_ready": False,
        "knowledge_coverage_ready": knowledge_coverage_ready,
        "evidence_current": True,
        "verified_evidence_scope": "embedded_fail_closed_advisory_baseline",
        "blockers": blockers,
        "blocker_details": blocker_details,
        "source_generated_at": payload["reviewed_at"],
        "source_decision": "blocked",
        "advisory_requirement_count": len(payload["blockers"]),
        "passed_advisory_requirement_count": 0,
        "external_attestation_required_gates": [
            "external_release_candidate_attestation"
        ],
        "evidence_findings": [],
        "message": (
            "Agronomic advisory use remains blocked by the embedded governed "
            "baseline. A full external promotion receipt is not mounted."
        ),
        "boundary": payload["boundary"],
        "evidence": {
            "advisory_blocker_baseline_sha256": _sha256(path),
            "requirements_manifest_sha256": payload["requirements_manifest"]["sha256"],
        },
    }


def _unavailable_response(
    *,
    knowledge_coverage_ready: bool,
    error: str,
) -> dict[str, Any]:
    blockers = ["advisory_readiness_evidence_unavailable"]
    if not knowledge_coverage_ready:
        blockers.insert(0, "current_knowledge_coverage")
    return {
        "schema_version": SCHEMA_VERSION,
        "available": False,
        "status": "unavailable",
        "advisory_ready": False,
        "knowledge_coverage_ready": knowledge_coverage_ready,
        "evidence_current": False,
        "verified_evidence_scope": "non_self_referential_advisory_evidence",
        "blockers": blockers,
        "blocker_details": [
            {
                "id": blocker,
                "status": "unavailable",
                "priority": "P0",
                "criterion": (
                    "Governed advisory-readiness evidence must be present, valid, and "
                    "hash-bound before any advisory clearance can be evaluated."
                ),
                "note": (
                    "Restore a valid readiness receipt or its fail-closed baseline. "
                    "Do not infer clearance from missing evidence."
                ),
                "evidence": [],
            }
            for blocker in blockers
        ],
        "source_generated_at": None,
        "source_decision": "unavailable",
        "advisory_requirement_count": 0,
        "passed_advisory_requirement_count": 0,
        "external_attestation_required_gates": sorted(EXTERNAL_ATTESTATION_GATES),
        "evidence_findings": [],
        "message": f"Governed advisory-readiness evidence is unavailable: {error}",
        "boundary": (
            "Missing or invalid readiness evidence must never be interpreted as "
            "clearance for an agronomic advisory pilot."
        ),
        "evidence": {},
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("advisory-readiness evidence root must be an object")
    return payload


def _validate_blocker_baseline(
    payload: dict[str, Any],
    *,
    root: Path,
) -> None:
    if payload.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise ValueError("unsupported advisory blocker baseline schema")
    reviewed_at = payload.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not reviewed_at.endswith("+00:00"):
        raise ValueError("advisory blocker baseline reviewed_at must be UTC")
    if payload.get("status") != "blocked":
        raise ValueError("advisory blocker baseline must be fail-closed")
    blockers = payload.get("blockers")
    if (
        not isinstance(blockers, list)
        or not blockers
        or any(not isinstance(value, str) or not value for value in blockers)
        or len(blockers) != len(set(blockers))
    ):
        raise ValueError("advisory blocker baseline blockers are invalid")
    boundary = payload.get("boundary")
    if not isinstance(boundary, str) or not boundary.strip():
        raise ValueError("advisory blocker baseline boundary is missing")
    manifest = payload.get("requirements_manifest")
    if (
        not isinstance(manifest, dict)
        or not _is_safe_relative_path(manifest.get("path"))
        or not _is_sha256(manifest.get("sha256"))
    ):
        raise ValueError("advisory blocker baseline lineage is invalid")
    manifest_path = (root / manifest["path"]).resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "advisory blocker baseline requirements manifest is outside evidence root"
        ) from exc
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError(
            "advisory blocker baseline requirements manifest is missing or unsafe"
        )
    if _sha256(manifest_path) != manifest["sha256"]:
        raise ValueError(
            "advisory blocker baseline requirements manifest hash does not match"
        )


def _validate_readiness_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise ValueError("unsupported advisory-readiness evidence schema")
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.endswith("+00:00"):
        raise ValueError("advisory-readiness generated_at must be UTC")
    manifest = payload.get("requirements_manifest")
    if (
        not isinstance(manifest, dict)
        or not _is_safe_relative_path(manifest.get("path"))
        or not _is_sha256(manifest.get("sha256"))
    ):
        raise ValueError("advisory-readiness requirements manifest lineage is invalid")
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict):
        raise ValueError("advisory-readiness decisions are missing")
    if decisions.get("advisory_pilot") not in {"pass", "blocked"}:
        raise ValueError("advisory-pilot decision is invalid")
    decision_blockers = decisions.get("advisory_blockers")
    if (
        not isinstance(decision_blockers, list)
        or any(not isinstance(value, str) or not value for value in decision_blockers)
        or len(decision_blockers) != len(set(decision_blockers))
    ):
        raise ValueError("advisory blockers are invalid")
    rows = payload.get("requirements")
    if not isinstance(rows, list) or not rows:
        raise ValueError("advisory requirements are missing")
    identifiers: set[str] = set()
    advisory_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("advisory requirement must be an object")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("advisory requirement identifiers are invalid")
        identifiers.add(identifier)
        if row.get("status") not in {"pass", "blocked", "pending"}:
            raise ValueError(f"advisory requirement status is invalid: {identifier}")
        if not isinstance(row.get("advisory_required"), bool):
            raise ValueError(f"advisory requirement flag is invalid: {identifier}")
        if not isinstance(row.get("criterion"), str) or not row["criterion"].strip():
            raise ValueError(f"advisory requirement criterion is invalid: {identifier}")
        if not isinstance(row.get("note"), str) or not row["note"].strip():
            raise ValueError(f"advisory requirement note is invalid: {identifier}")
        if not isinstance(row.get("priority"), str) or not row["priority"].strip():
            raise ValueError(f"advisory requirement priority is invalid: {identifier}")
        if row["advisory_required"]:
            evidence = row.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f"advisory requirement evidence is missing: {identifier}")
            for item in evidence:
                if (
                    not isinstance(item, dict)
                    or not _is_safe_relative_path(item.get("path"))
                    or not isinstance(item.get("exists"), bool)
                    or (
                        item["exists"]
                        and not _is_sha256(item.get("sha256"))
                    )
                ):
                    raise ValueError(
                        f"advisory requirement evidence lineage is invalid: {identifier}"
                    )
            advisory_rows.append(row)
    derived_blockers = [
        row["id"] for row in advisory_rows if row["status"] != "pass"
    ]
    if decision_blockers != derived_blockers:
        raise ValueError("advisory blocker decision does not match requirement states")
    if (decisions["advisory_pilot"] == "pass") != (not derived_blockers):
        raise ValueError("advisory-pilot decision contradicts requirement states")
    return advisory_rows


def _source_blocker_details(
    requirements: list[dict[str, Any]],
    blocker_ids: list[str],
) -> list[dict[str, Any]]:
    by_id = {row["id"]: row for row in requirements}
    return [
        {
            "id": identifier,
            "status": by_id[identifier]["status"],
            "priority": by_id[identifier]["priority"],
            "criterion": by_id[identifier]["criterion"],
            "note": by_id[identifier]["note"],
            "evidence": [
                {
                    "path": item["path"],
                    "exists": item["exists"],
                    "sha256": item.get("sha256"),
                }
                for item in by_id[identifier]["evidence"]
            ],
        }
        for identifier in blocker_ids
    ]


def _baseline_blocker_details(
    payload: dict[str, Any],
    *,
    path: Path,
) -> list[dict[str, Any]]:
    manifest_path = path.parent / payload["requirements_manifest"]["path"]
    if not manifest_path.is_file():
        manifest_path = REPO_ROOT / payload["requirements_manifest"]["path"]
    manifest = _read_json(manifest_path.resolve())
    rows = manifest.get("requirements")
    if not isinstance(rows, list):
        raise ValueError("advisory blocker baseline requirements are missing")
    catalog: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("advisory blocker baseline requirement must be an object")
        identifier = row.get("id")
        criterion = row.get("criterion")
        priority = row.get("priority")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(criterion, str)
            or not criterion.strip()
            or not isinstance(priority, str)
            or not priority.strip()
        ):
            raise ValueError("advisory blocker baseline requirement is invalid")
        catalog[identifier] = row
    missing = [identifier for identifier in payload["blockers"] if identifier not in catalog]
    if missing:
        raise ValueError(
            "advisory blocker baseline identifiers are absent from requirements manifest"
        )
    return [
        {
            "id": identifier,
            "status": "blocked",
            "priority": catalog[identifier]["priority"],
            "criterion": catalog[identifier]["criterion"],
            "note": (
                "Mount the current full readiness receipt and complete the externally "
                "governed evidence named by that receipt. This embedded baseline can "
                "preserve a block but cannot clear it."
            ),
            "evidence": [
                {
                    "path": payload["requirements_manifest"]["path"],
                    "exists": True,
                    "sha256": payload["requirements_manifest"]["sha256"],
                }
            ],
        }
        for identifier in payload["blockers"]
    ]


def _evidence_findings(
    requirements: list[dict[str, Any]],
    *,
    root: Path,
    requirements_manifest: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    seen: set[str] = set()
    evidence_items = [requirements_manifest]
    evidence_items.extend(
        item
        for row in requirements
        if row["status"] == "pass"
        and row["id"] not in EXTERNAL_ATTESTATION_GATES
        for item in row["evidence"]
    )
    for item in evidence_items:
        relative = str(item["path"])
        if relative in seen:
            continue
        seen.add(relative)
        candidate = root / relative
        target = candidate.resolve()
        try:
            target.relative_to(root)
        except ValueError:
            findings.append({"path": relative, "state": "outside_evidence_root"})
            continue
        if candidate.is_symlink() or not target.is_file():
            findings.append({"path": relative, "state": "missing_or_unsafe"})
            continue
        actual = _sha256(target)
        if item.get("exists", True) is not True or actual != item.get("sha256"):
            findings.append(
                {
                    "path": relative,
                    "state": "hash_mismatch",
                    "expected_sha256": str(item.get("sha256") or ""),
                    "actual_sha256": actual,
                }
            )
    return findings


def _is_safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
