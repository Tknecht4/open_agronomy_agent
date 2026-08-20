from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

from agronomy_agent.high_consequence import classify_high_consequence_domains
from agronomy_agent.corpus_release import quality_ledger_status, source_locator_status
from agronomy_agent.security_evidence import build_implementation_binding


CORPUS_POLICY_SCHEMA = "open_agronomy_agent.runtime_corpus_policy.v1"
CORPUS_AUDIT_SCHEMA = "open_agronomy_agent.runtime_corpus_audit.v1"
ALLOWED_ELIGIBILITY = {"decisive", "context_only", "quarantined"}
RUNTIME_LOADABLE_ELIGIBILITY = {"decisive", "context_only"}
EFFECTIVE_ELIGIBILITY = {*ALLOWED_ELIGIBILITY, "requires_live_authority"}
PROVINCIAL_ADMISSION_QUEUE_PATH = Path(
    "data/manifests/provincial_applied_guidance_admission_queue_20260724.json"
)
CANADIAN_PROVINCES = {
    "Alberta",
    "British Columbia",
    "Manitoba",
    "New Brunswick",
    "Newfoundland and Labrador",
    "Nova Scotia",
    "Ontario",
    "Prince Edward Island",
    "Quebec",
    "Saskatchewan",
}
CORPUS_AUDIT_IMPLEMENTATION_PATHS = (
    "src/agronomy_agent/corpus_governance.py",
    "src/agronomy_agent/high_consequence.py",
    "src/agronomy_agent/security_evidence.py",
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_corpus_policy(root: Path, policy_path: str | Path | None) -> dict[str, Any]:
    if not policy_path:
        return {}
    path = Path(policy_path)
    if not path.is_absolute():
        path = root / path
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != CORPUS_POLICY_SCHEMA:
        raise ValueError("unsupported runtime corpus policy schema")
    entries = payload.get("corpora")
    if not isinstance(entries, list):
        raise ValueError("runtime corpus policy must contain a corpora list")
    paths = [str(item.get("path") or "") for item in entries if isinstance(item, dict)]
    if len(paths) != len(set(paths)) or any(not value for value in paths):
        raise ValueError("runtime corpus policy paths must be non-empty and unique")
    for item in entries:
        if item.get("runtime_eligibility") not in ALLOWED_ELIGIBILITY:
            raise ValueError(f"invalid runtime eligibility for {item.get('path')}")
    default_eligibility = payload.get("default_eligibility", "quarantined")
    if default_eligibility not in ALLOWED_ELIGIBILITY:
        raise ValueError("invalid runtime corpus policy default eligibility")
    return payload


def corpus_policy_for_path(
    corpus_path: str | Path,
    policy: dict[str, Any],
) -> dict[str, Any] | None:
    corpus_path = str(corpus_path or "")
    for item in policy.get("corpora", []) if isinstance(policy, dict) else []:
        aliases = {
            str(item.get("path") or ""),
            str(item.get("runtime_path_reference") or ""),
        }
        for relative in aliases - {""}:
            if corpus_path == relative or corpus_path.endswith("/" + relative):
                return item
    return None


def corpus_policy_for_doc(doc: Any, policy: dict[str, Any]) -> dict[str, Any] | None:
    return corpus_policy_for_path(
        str(getattr(doc, "corpus_path", "") or ""),
        policy,
    )


def partition_runtime_corpus_paths(
    corpus_paths: Iterable[str | Path],
    policy: dict[str, Any],
) -> tuple[list[str | Path], list[dict[str, Any]]]:
    """Exclude quarantined and unregistered corpora before building an index.

    The post-retrieval governance filter remains necessary as defense in depth,
    but loading quarantined rows first can let them distort BM25 statistics and
    crowd eligible evidence out of the candidate set. A configured path without
    an exact policy entry fails closed even if the manifest default is looser.
    """

    configured = list(corpus_paths)
    if not policy:
        return configured, []

    loadable: list[str | Path] = []
    excluded: list[dict[str, Any]] = []
    for corpus_path in configured:
        item = corpus_policy_for_path(corpus_path, policy)
        if item is None:
            excluded.append(
                {
                    "path": str(corpus_path),
                    "runtime_eligibility": "quarantined",
                    "reason": "missing_policy_entry",
                    "policy_reason": None,
                }
            )
            continue
        eligibility = str(item.get("runtime_eligibility") or "quarantined")
        if eligibility in RUNTIME_LOADABLE_ELIGIBILITY:
            loadable.append(corpus_path)
            continue
        excluded.append(
            {
                "path": str(item.get("path") or corpus_path),
                "runtime_eligibility": eligibility,
                "reason": "corpus_quarantined_at_load",
                "policy_reason": item.get("reason"),
            }
        )
    return loadable, excluded


def filter_docs_by_corpus_governance(
    question: str,
    docs: Iterable[Any],
    policy: dict[str, Any],
    *,
    allow_context_only_support: bool = False,
) -> tuple[list[Any], list[dict[str, Any]]]:
    if not policy:
        return list(docs), []
    high_consequence = bool(classify_high_consequence_domains(question))
    allowed: list[Any] = []
    blocked: list[dict[str, Any]] = []
    for doc in docs:
        item = corpus_policy_for_doc(doc, policy)
        eligibility = str((item or {}).get("runtime_eligibility") or policy.get("default_eligibility") or "quarantined")
        reason = None
        if eligibility == "quarantined":
            reason = "corpus_quarantined"
        elif (
            high_consequence
            and eligibility != "decisive"
            and not (
                allow_context_only_support
                and eligibility == "context_only"
            )
        ):
            reason = "not_decisive_for_high_consequence"
        if reason:
            blocked.append(
                {
                    "doc_id": str(getattr(doc, "doc_id", "")),
                    "corpus_path": str(getattr(doc, "corpus_path", "")),
                    "runtime_eligibility": eligibility,
                    "reason": reason,
                    "policy_reason": (item or {}).get("reason"),
                }
            )
        else:
            allowed.append(doc)
    return allowed, blocked


def audit_runtime_corpora(*, root: Path, rag_config_path: Path) -> dict[str, Any]:
    root = root.resolve()
    config = yaml.safe_load(rag_config_path.read_text(encoding="utf-8")) or {}
    retrieval = config.get("retrieval") if isinstance(config.get("retrieval"), dict) else {}
    artifact_root_value = retrieval.get("artifact_root")
    artifact_root = (
        (rag_config_path.resolve().parent / str(artifact_root_value)).resolve()
        if artifact_root_value
        else root
    )
    configured_paths = [str(value) for value in retrieval.get("corpus_paths") or []]
    on_demand_paths: list[str] = []
    for release in retrieval.get("on_demand_corpus_releases") or []:
        if not isinstance(release, dict):
            raise ValueError("on-demand corpus release entry must be an object")
        manifest_relative = str(release.get("manifest_path") or "")
        manifest_path = artifact_root / manifest_relative
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid_on_demand_manifest:{manifest_relative}:{exc}") from exc
        expected_release_id = str(release.get("release_id") or "")
        if manifest.get("release_id") != expected_release_id:
            raise ValueError(f"on_demand_release_id_mismatch:{manifest_relative}")
        for shard in manifest.get("shards") or []:
            if not isinstance(shard, dict) or not shard.get("path"):
                raise ValueError(f"invalid_on_demand_shard:{manifest_relative}")
            on_demand_paths.append((Path(manifest_relative).parent / str(shard["path"])).as_posix())
    configured_paths = list(dict.fromkeys([*configured_paths, *on_demand_paths]))
    policy = load_corpus_policy(artifact_root, retrieval.get("corpus_policy_manifest"))
    by_path = {str(item["path"]): item for item in policy.get("corpora", [])}
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    source_locator_failures: Counter[str] = Counter()
    provincial_standard_decisive_rows: Counter[str] = Counter()
    provincial_standard_decisive_sources: dict[str, set[str]] = {}
    for relative in configured_paths:
        path = artifact_root / relative
        item = by_path.get(relative)
        if item is None:
            errors.append(f"missing_policy:{relative}")
            continue
        if not path.is_file():
            if item.get("runtime_eligibility") != "quarantined":
                errors.append(f"missing_corpus:{relative}")
            rows.append(
                {
                    "path": relative,
                    "sha256": None,
                    "sha256_verified": False,
                    "bytes_available": False,
                    "rows": 0,
                    "malformed_rows": 0,
                    "missing_doc_id_rows": 0,
                    "missing_source_rows": 0,
                    "runtime_eligibility": item["runtime_eligibility"],
                    "row_retrieval_policy_counts": {},
                    "effective_eligibility_counts": {},
                    "rights_status": item["rights_status"],
                    "evidence_tier": item["evidence_tier"],
                    "reason": item["reason"],
                    "availability_boundary": (
                        "Quarantined bytes are optional in distributable runtimes and are never indexed."
                    ),
                }
            )
            continue
        actual_sha = sha256_path(path)
        expected_sha = str(item.get("sha256") or "")
        row_count = 0
        malformed = 0
        missing_doc_id = 0
        missing_source = 0
        row_retrieval_policies: Counter[str] = Counter()
        effective_eligibility: Counter[str] = Counter()
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row_count += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                missing_doc_id += int(not row.get("doc_id"))
                missing_source += int(not (row.get("source_id") or row.get("source")))
                if str(item.get("evidence_tier") or "") == "US_government_analogue_reference":
                    complete, locator_status = source_locator_status(row.get("source_locator"))
                    if not complete:
                        source_locator_failures[locator_status] += 1
                    jurisdictions_for_policy = row.get("jurisdiction") or row.get("region") or []
                    if isinstance(jurisdictions_for_policy, str):
                        jurisdictions_for_policy = [jurisdictions_for_policy]
                    if "United States" not in {str(value) for value in jurisdictions_for_policy}:
                        source_locator_failures["missing_us_jurisdiction"] += 1
                    if str(row.get("retrieval_policy") or "") != "context_only":
                        source_locator_failures["not_context_only"] += 1
                    quality_complete, quality_status = quality_ledger_status(row)
                    if not quality_complete:
                        source_locator_failures[quality_status] += 1
                row_policy = str(row.get("retrieval_policy") or "standard").strip().lower()
                row_retrieval_policies[row_policy] += 1
                corpus_eligibility = str(item["runtime_eligibility"])
                if corpus_eligibility == "quarantined":
                    effective = "quarantined"
                elif row_policy == "requires_live_authority":
                    effective = "requires_live_authority"
                elif corpus_eligibility == "context_only" or row_policy == "context_only":
                    effective = "context_only"
                else:
                    effective = "decisive"
                effective_eligibility[effective] += 1
                jurisdictions = row.get("jurisdiction") or row.get("region") or []
                if isinstance(jurisdictions, str):
                    jurisdictions = [jurisdictions]
                if (
                    effective == "decisive"
                    and row_policy == "standard"
                    and str(row.get("source_type") or "").strip().lower()
                    == "applied_guidance"
                ):
                    for jurisdiction in jurisdictions:
                        jurisdiction = str(jurisdiction)
                        if jurisdiction not in CANADIAN_PROVINCES:
                            continue
                        provincial_standard_decisive_rows[jurisdiction] += 1
                        provincial_standard_decisive_sources.setdefault(
                            jurisdiction, set()
                        ).add(str(row.get("source_id") or row.get("source") or ""))
        if actual_sha != expected_sha:
            errors.append(f"sha256_mismatch:{relative}")
        if malformed or missing_doc_id or missing_source:
            errors.append(f"invalid_rows:{relative}")
        rows.append(
            {
                "path": relative,
                "sha256": actual_sha,
                "sha256_verified": actual_sha == expected_sha,
                "bytes_available": True,
                "rows": row_count,
                "malformed_rows": malformed,
                "missing_doc_id_rows": missing_doc_id,
                "missing_source_rows": missing_source,
                "runtime_eligibility": item["runtime_eligibility"],
                "row_retrieval_policy_counts": dict(sorted(row_retrieval_policies.items())),
                "effective_eligibility_counts": dict(sorted(effective_eligibility.items())),
                "rights_status": item["rights_status"],
                "evidence_tier": item["evidence_tier"],
                "reason": item["reason"],
            }
        )
    unconfigured = sorted(set(by_path) - set(configured_paths))
    if unconfigured:
        errors.extend(f"policy_path_not_configured:{path}" for path in unconfigured)
    errors.extend(
        f"invalid_source_locator:{status}:{count}"
        for status, count in sorted(source_locator_failures.items())
    )
    corpus_policy_counts = {
        eligibility: sum(row["rows"] for row in rows if row["runtime_eligibility"] == eligibility)
        for eligibility in sorted(ALLOWED_ELIGIBILITY)
    }
    counts = {
        eligibility: sum(
            int((row.get("effective_eligibility_counts") or {}).get(eligibility, 0))
            for row in rows
        )
        for eligibility in sorted(EFFECTIVE_ELIGIBILITY)
    }
    queue_path = root / PROVINCIAL_ADMISSION_QUEUE_PATH
    active_jurisdictions: set[str] = set()
    queue_sha256: str | None = None
    queue_required = bool(provincial_standard_decisive_rows) or queue_path.is_file()
    if queue_required:
        try:
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            queue_sha256 = sha256_path(queue_path)
            if (
                queue.get("schema_version")
                != "open_agronomy_agent.provincial_applied_guidance_queue.v1"
            ):
                raise ValueError("unsupported provincial admission queue schema")
            active_values = queue.get("recommendation_grade_active_jurisdictions")
            if (
                not isinstance(active_values, list)
                or any(
                    not isinstance(value, str) or value not in CANADIAN_PROVINCES
                    for value in active_values
                )
                or len(active_values) != len(set(active_values))
            ):
                raise ValueError(
                    "invalid recommendation-grade active jurisdiction list"
                )
            active_jurisdictions = set(active_values)
            active_rows = {
                str(row.get("jurisdiction"))
                for row in queue.get("rows") or []
                if isinstance(row, dict)
                and row.get("admission_state") == "active_decisive"
            }
            if active_rows != active_jurisdictions:
                raise ValueError(
                    "active jurisdiction list does not match active admission rows"
                )
            if queue.get("recommendation_grade_active_provinces") != len(
                active_jurisdictions
            ):
                raise ValueError(
                    "active province count does not match active jurisdiction list"
                )
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"invalid_provincial_admission_queue:{exc}")

    unreviewed_decisive = {
        jurisdiction: count
        for jurisdiction, count in sorted(provincial_standard_decisive_rows.items())
        if jurisdiction not in active_jurisdictions
    }
    errors.extend(
        f"unreviewed_provincial_decisive_rows:{jurisdiction}:{count}"
        for jurisdiction, count in unreviewed_decisive.items()
    )
    return {
        "schema_version": CORPUS_AUDIT_SCHEMA,
        "status": "pass" if not errors else "fail",
        "implementation_binding": build_implementation_binding(
            CORPUS_AUDIT_IMPLEMENTATION_PATHS
        ),
        "rag_config": str(rag_config_path),
        "policy_manifest": retrieval.get("corpus_policy_manifest"),
        "artifact_root": str(artifact_root),
        "configured_corpus_count": len(configured_paths),
        "direct_startup_corpus_count": len(retrieval.get("corpus_paths") or []),
        "on_demand_corpus_count": len(on_demand_paths),
        "audited_corpus_count": len(rows),
        "row_counts_by_eligibility": counts,
        "corpus_policy_row_counts_by_eligibility": corpus_policy_counts,
        "corpus_file_counts_by_eligibility": {
            eligibility: sum(
                1 for row in rows if row["runtime_eligibility"] == eligibility
            )
            for eligibility in sorted(ALLOWED_ELIGIBILITY)
        },
        "corpora": rows,
        "provincial_applied_guidance_boundary": {
            "admission_queue_path": str(PROVINCIAL_ADMISSION_QUEUE_PATH),
            "admission_queue_sha256": queue_sha256,
            "admission_queue_required": queue_required,
            "active_jurisdictions": sorted(active_jurisdictions),
            "standard_decisive_rows_by_jurisdiction": dict(
                sorted(provincial_standard_decisive_rows.items())
            ),
            "standard_decisive_source_ids_by_jurisdiction": {
                jurisdiction: sorted(source_ids)
                for jurisdiction, source_ids in sorted(
                    provincial_standard_decisive_sources.items()
                )
            },
            "unreviewed_standard_decisive_rows_by_jurisdiction": unreviewed_decisive,
            "gate_passed": not unreviewed_decisive
            and not any(
                error.startswith("invalid_provincial_admission_queue:")
                for error in errors
            ),
            "boundary": (
                "A provincial applied-guidance row may be standard-policy decisive only "
                "when the same jurisdiction is explicitly active in the governed admission queue."
            ),
        },
        "errors": errors,
        "source_locator_failures": dict(sorted(source_locator_failures.items())),
        "high_consequence_policy": (
            "Only rows that are decisive under both the corpus policy and row retrieval policy may support "
            "high-consequence answers; context-only and live-authority rows cannot become decisive."
        ),
        "quarantine_policy": "Quarantined corpora remain available for research provenance but cannot enter runtime context.",
    }
