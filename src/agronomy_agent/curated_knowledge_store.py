"""Deterministic, distributable curated-knowledge-store construction.

This module deliberately operates on *already extracted* JSONL rows.  It does
not download a document, crawl a source, or manufacture a training dataset.
Its responsibility is the narrow release boundary described in
``docs/reviews/open-agronomy-compact-offline-data-plan-20260813.md``:

* admit only source-registry records with explicit distributable-RAG rights;
* preserve the source row's retrieval policy rather than promoting it;
* split canonical JSONL only between complete records and never mix policy
  roles in a shard; and
* emit hash-bound, explicitly enumerated runtime configuration and policy
  artifacts.

The implementation uses only the standard library plus PyYAML, which is
already required by the existing RAG configuration audit.  A store is built in
an adjacent temporary directory and promoted only after it passes its own
validator, so a failed build cannot leave a partial release at ``output_root``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from agronomy_agent.canada_sources import (
    load_canada_source_manifest,
    source_allowed_for,
    source_license_snapshot,
)
from agronomy_agent.corpus_governance import CORPUS_POLICY_SCHEMA


CURATED_STORE_SCHEMA = "open_agronomy_agent.curated_knowledge_store.v1"
CURATED_PROFILE_SPEC_SCHEMA = "open_agronomy_agent.curated_knowledge_store_profiles.v1"
CURATED_STORE_RECEIPT_SCHEMA = "open_agronomy_agent.curated_knowledge_store_receipt.v1"
CURATED_STORE_BUILDER = "agronomy_agent.curated_knowledge_store"
CURATED_STORE_BUILDER_VERSION = 2
SEMANTIC_COMPANION_SCHEMA = "open_agronomy_agent.reviewed_semantic_companion.v1"
DEFAULT_MAX_SHARD_BYTES = 24 * 1024 * 1024
MAX_SHARD_BYTES = 24 * 1024 * 1024

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RETRIEVAL_POLICY_TO_ROLE = {
    "standard": "decisive",
    "decisive": "decisive",
    "context_only": "context_only",
    "requires_live_authority": "requires_live_authority",
}
_ROLE_ORDER = {"decisive": 0, "context_only": 1, "requires_live_authority": 2}
_ROLE_RUNTIME_ELIGIBILITY = {
    "decisive": "decisive",
    "context_only": "context_only",
    # Current runtime filtering preserves this row policy and fails it closed
    # before a static answer can use it.  It must remain loadable for that
    # guard to produce a transparent live-authority boundary.
    "requires_live_authority": "decisive",
}


class CuratedStoreError(ValueError):
    """Raised when a candidate curated store violates its release contract."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Return a stable JSON representation used for all emitted artifacts."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row))


def _safe_relative_path(value: str) -> str:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise CuratedStoreError(f"unsafe relative path: {value!r}")
    return path.as_posix()


def _require_identifier(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise CuratedStoreError(f"{label} must match {_ID_RE.pattern}: {value!r}")
    return text


def _require_sha256(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not _SHA256_RE.fullmatch(text):
        raise CuratedStoreError(f"{label} must be a lowercase SHA-256: {value!r}")
    return text


def _require_release_date(value: str) -> str:
    if not _DATE_RE.fullmatch(value):
        raise CuratedStoreError("release_date must be YYYY-MM-DD")
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise CuratedStoreError("release_date must be a valid calendar date") from exc
    return value


def _source_record_sha256(source: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(source))


def _content_fingerprint(row: Mapping[str, Any]) -> str:
    lineage = row.get("lineage")
    if isinstance(lineage, Mapping) and _SHA256_RE.fullmatch(str(lineage.get("chunk_sha256") or "")):
        return str(lineage["chunk_sha256"])
    return sha256_bytes(str(row.get("text") or "").encode("utf-8"))


def _row_policy_role(row: Mapping[str, Any], *, label: str) -> str:
    policy = str(row.get("retrieval_policy") or "standard").strip().lower()
    role = _RETRIEVAL_POLICY_TO_ROLE.get(policy)
    if role is None:
        raise CuratedStoreError(
            f"{label}.retrieval_policy must be one of {sorted(_RETRIEVAL_POLICY_TO_ROLE)}"
        )
    return role


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _row_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    lineage = row.get("lineage") if isinstance(row.get("lineage"), Mapping) else {}
    source_edition = str(
        lineage.get("raw_sha256")
        or lineage.get("extracted_text_sha256")
        or ""
    )
    chunk_index = row.get("chunk_index")
    try:
        normalized_index: Any = int(chunk_index)
    except (TypeError, ValueError):
        normalized_index = 0
    return (
        str(row.get("source_id") or ""),
        source_edition,
        normalized_index,
        str(row.get("doc_id") or ""),
        _content_fingerprint(row),
    )


def _input_path_hint(path: Path, *, repository_root: Path | None) -> str:
    resolved = path.resolve()
    if repository_root is not None:
        try:
            return resolved.relative_to(repository_root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def load_profile_spec(path: Path) -> list[dict[str, Any]]:
    """Load a small declarative core/extended profile specification.

    Source IDs are intentionally explicit.  There is no "all registry sources"
    default because a new registry record should never silently enter the Git
    bundle.
    """

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CuratedStoreError(f"unable to read profile specification {path}: {exc}") from exc
    if payload.get("schema_version") != CURATED_PROFILE_SPEC_SCHEMA:
        raise CuratedStoreError(
            f"profile specification schema_version must be {CURATED_PROFILE_SPEC_SCHEMA}"
        )
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise CuratedStoreError("profile specification must contain a non-empty profiles list")

    parsed: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(profiles):
        if not isinstance(raw, Mapping):
            raise CuratedStoreError(f"profiles[{index}] must be an object")
        profile_id = _require_identifier(raw.get("id"), label=f"profiles[{index}].id")
        if profile_id in parsed:
            raise CuratedStoreError(f"duplicate profile id: {profile_id}")
        source_ids_raw = raw.get("source_ids")
        if not isinstance(source_ids_raw, list) or not source_ids_raw:
            raise CuratedStoreError(f"profile {profile_id} must have non-empty source_ids")
        source_ids = [_require_identifier(value, label=f"profile {profile_id}.source_ids") for value in source_ids_raw]
        if len(source_ids) != len(set(source_ids)):
            raise CuratedStoreError(f"profile {profile_id} has duplicate source_ids")
        base_profile = raw.get("base_profile")
        if base_profile is not None:
            base_profile = _require_identifier(base_profile, label=f"profile {profile_id}.base_profile")
        description = str(raw.get("description") or "").strip()
        if not description:
            raise CuratedStoreError(f"profile {profile_id} requires a description")
        parsed[profile_id] = {
            "id": profile_id,
            "description": description,
            "source_ids": sorted(source_ids),
            "base_profile": base_profile,
        }

    for profile in parsed.values():
        base_profile = profile["base_profile"]
        if base_profile is None:
            continue
        base = parsed.get(base_profile)
        if base is None:
            raise CuratedStoreError(
                f"profile {profile['id']} references missing base_profile {base_profile}"
            )
        missing_base_sources = sorted(set(base["source_ids"]) - set(profile["source_ids"]))
        if missing_base_sources:
            raise CuratedStoreError(
                f"profile {profile['id']} must retain base sources from {base_profile}: {missing_base_sources}"
            )

    ordered: list[dict[str, Any]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(profile_id: str) -> None:
        if profile_id in visited:
            return
        if profile_id in visiting:
            raise CuratedStoreError(f"profile inheritance cycle at {profile_id}")
        visiting.add(profile_id)
        base_profile = parsed[profile_id]["base_profile"]
        if base_profile:
            visit(base_profile)
        visiting.remove(profile_id)
        visited.add(profile_id)
        ordered.append(parsed[profile_id])

    for profile_id in sorted(parsed):
        visit(profile_id)
    return ordered


def _validate_semantic_companion_binding(
    row: dict[str, Any],
    *,
    label: str,
    source: Mapping[str, Any],
    repository_root: Path | None,
    allow_rebind: bool,
) -> bool:
    """Fail closed on reviewed-companion lineage and optionally rebind legacy rows.

    A rebind is not a content migration: the title, text, source pages, source ID,
    and parent raw hash must exactly match one record in the newly hash-pinned
    companion.  Only the companion path/hash/review metadata may be refreshed.
    This lets an immutable master release repair old unversioned path metadata
    without silently changing the reviewed agronomic content.
    """

    lineage = row.get("lineage")
    row_binding = row.get("semantic_companion")
    lineage_binding = (
        lineage.get("semantic_companion") if isinstance(lineage, Mapping) else None
    )
    if row_binding is None and lineage_binding is None:
        return False
    if not isinstance(row_binding, dict) or not isinstance(lineage_binding, dict):
        raise CuratedStoreError(f"{label} must carry both semantic companion bindings")

    ingest_policy = source.get("ingest_policy")
    if not isinstance(ingest_policy, Mapping):
        raise CuratedStoreError(f"{label} semantic row has no source ingest policy")
    path_value = str(ingest_policy.get("semantic_companion_path") or "").strip()
    try:
        path_value = _safe_relative_path(path_value)
        expected_sha256 = _require_sha256(
            ingest_policy.get("semantic_companion_sha256"),
            label=f"{label}.source.semantic_companion_sha256",
        )
    except CuratedStoreError as exc:
        raise CuratedStoreError(
            f"{label} has an invalid semantic companion declaration: {exc}"
        ) from exc
    if repository_root is None:
        raise CuratedStoreError(
            f"{label} requires repository_root to validate semantic companion {path_value}"
        )
    companion_path = Path(repository_root).resolve() / path_value
    if not companion_path.is_file():
        raise CuratedStoreError(f"{label} semantic companion is missing: {path_value}")
    actual_sha256 = sha256_path(companion_path)
    if actual_sha256 != expected_sha256:
        raise CuratedStoreError(
            f"{label} semantic companion SHA-256 mismatch: expected {expected_sha256}, "
            f"observed {actual_sha256}"
        )
    companion = _load_json(companion_path, label="semantic companion")
    if companion.get("schema_version") != SEMANTIC_COMPANION_SCHEMA:
        raise CuratedStoreError(f"{label} semantic companion has an unsupported schema")
    source_id = str(row.get("source_id") or "")
    if companion.get("source_id") != source_id:
        raise CuratedStoreError(f"{label} semantic companion source_id mismatch")
    parent_raw_sha256 = str((lineage or {}).get("raw_sha256") or "")
    if companion.get("source_raw_sha256") != parent_raw_sha256:
        raise CuratedStoreError(f"{label} semantic companion parent raw SHA-256 mismatch")

    source_pages = [int(page) for page in row_binding.get("source_pages") or []]
    matching_records = [
        record
        for record in companion.get("records") or []
        if isinstance(record, Mapping)
        and str(record.get("title") or "").strip()
        == str(row.get("title") or "").strip()
        and str(record.get("text") or "").strip() == str(row.get("text") or "").strip()
        and [int(page) for page in record.get("source_pages") or []] == source_pages
    ]
    if len(matching_records) != 1:
        raise CuratedStoreError(
            f"{label} does not match exactly one record in semantic companion {path_value}"
        )

    expected_binding = {
        "schema_version": companion.get("schema_version"),
        "reviewed_on": companion.get("reviewed_on"),
        "review_method": companion.get("review_method"),
        "source_pages": source_pages,
    }
    row_expected = {
        **expected_binding,
        "companion_path": path_value,
        "companion_sha256": expected_sha256,
    }
    lineage_expected = {
        **expected_binding,
        "path": path_value,
        "sha256": expected_sha256,
        "parent_raw_sha256": parent_raw_sha256,
    }
    row_matches = all(row_binding.get(key) == value for key, value in row_expected.items())
    lineage_matches = all(
        lineage_binding.get(key) == value for key, value in lineage_expected.items()
    )
    if row_matches and lineage_matches:
        return False
    if not allow_rebind:
        raise CuratedStoreError(f"{label} semantic companion binding is stale or ambiguous")
    row_binding.update(row_expected)
    lineage_binding.update(lineage_expected)
    return True


def _validate_row(
    row: dict[str, Any],
    *,
    label: str,
    source_by_id: Mapping[str, Mapping[str, Any]],
    repository_root: Path | None = None,
    allow_semantic_rebind: bool = False,
) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise CuratedStoreError(f"{label} must be a JSON object")
    doc_id = str(row.get("doc_id") or "").strip()
    if not doc_id:
        raise CuratedStoreError(f"{label}.doc_id is required")
    source_id = _require_identifier(row.get("source_id"), label=f"{label}.source_id")
    text = str(row.get("text") or "").strip()
    if not text:
        raise CuratedStoreError(f"{label}.text is required")
    source = source_by_id.get(source_id)
    if source is None:
        raise CuratedStoreError(f"{label} references unregistered source_id {source_id}")
    if not source_allowed_for(dict(source), "local_rag") or not source_allowed_for(
        dict(source), "distributable_bundle"
    ):
        raise CuratedStoreError(
            f"{label} source {source_id} lacks local_rag/distributable_bundle admission"
        )
    if (source.get("use_policy") or {}).get("training") is not False:
        raise CuratedStoreError(
            f"{label} source {source_id} has training permission enabled; "
            "a curated retrieval store must not imply a training grant"
        )
    if str(row.get("source") or "").strip() != str(source.get("url") or "").strip():
        raise CuratedStoreError(f"{label}.source must exactly match the registered canonical URL")

    role = _row_policy_role(row, label=label)
    lineage = row.get("lineage")
    if not isinstance(lineage, Mapping):
        raise CuratedStoreError(f"{label}.lineage must be an object")
    if str(lineage.get("source_id") or "") != source_id:
        raise CuratedStoreError(f"{label}.lineage.source_id must match source_id")
    for key in ("raw_sha256", "extracted_text_sha256", "chunk_sha256", "manifest_sha256"):
        _require_sha256(lineage.get(key), label=f"{label}.lineage.{key}")
    calculated_chunk_sha = sha256_bytes(text.encode("utf-8"))
    if calculated_chunk_sha != str(lineage.get("chunk_sha256")):
        raise CuratedStoreError(f"{label}.lineage.chunk_sha256 does not bind row text")
    if not str(lineage.get("fetched_at") or "").strip():
        raise CuratedStoreError(f"{label}.lineage.fetched_at is required")

    expected_license = source_license_snapshot(dict(source))
    row_license = row.get("license_snapshot")
    lineage_license = lineage.get("license_snapshot")
    if row_license != expected_license or lineage_license != expected_license:
        raise CuratedStoreError(
            f"{label} must carry the exact current registry licence snapshot for {source_id}"
        )
    if str(lineage.get("retrieval_policy") or "").strip().lower() != str(
        row.get("retrieval_policy") or "standard"
    ).strip().lower():
        raise CuratedStoreError(f"{label}.lineage.retrieval_policy must match retrieval_policy")
    semantic_companion_rebound = _validate_semantic_companion_binding(
        row,
        label=label,
        source=source,
        repository_root=repository_root,
        allow_rebind=allow_semantic_rebind,
    )

    return {
        "doc_id": doc_id,
        "source_id": source_id,
        "role": role,
        "content_fingerprint": calculated_chunk_sha,
        "source": dict(source),
        "semantic_companion_rebound": semantic_companion_rebound,
    }


def _load_and_validate_rows(
    input_paths: Sequence[Path],
    *,
    source_by_id: Mapping[str, Mapping[str, Any]],
    selected_source_ids: set[str],
    repository_root: Path | None,
    allow_semantic_rebind: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    """Load only profile-selected rows while receipting every skipped source.

    Existing reviewed Canadian input corpora can contain a mixture of admitted
    and still-unadmitted source records.  The profile specification is the
    release selection boundary: an unselected row is never validated as a
    candidate release row or copied into the store, but its identifier and
    count remain in the input receipt.  Malformed JSON remains a hard error so
    an input cannot hide corrupt records behind the selector.
    """

    if not input_paths:
        raise CuratedStoreError("at least one input JSONL path is required")
    rows: list[dict[str, Any]] = []
    input_receipts: list[dict[str, Any]] = []
    excluded_source_counts: Counter[str] = Counter()
    seen_doc_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    for input_path in sorted((Path(path) for path in input_paths), key=lambda path: str(path.resolve())):
        if not input_path.is_file():
            raise CuratedStoreError(f"input JSONL does not exist: {input_path}")
        input_rows = 0
        selected_rows = 0
        skipped_source_counts: Counter[str] = Counter()
        with input_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CuratedStoreError(
                        f"invalid JSON in {input_path}:{line_number}: {exc.msg}"
                    ) from exc
                input_rows += 1
                source_id = str(row.get("source_id") or "").strip() or "missing_source_id"
                if source_id not in selected_source_ids:
                    skipped_source_counts[source_id] += 1
                    excluded_source_counts[source_id] += 1
                    continue
                metadata = _validate_row(
                    row,
                    label=f"{input_path.name}:{line_number}",
                    source_by_id=source_by_id,
                    repository_root=repository_root,
                    allow_semantic_rebind=allow_semantic_rebind,
                )
                doc_id = metadata["doc_id"]
                fingerprint = metadata["content_fingerprint"]
                if doc_id in seen_doc_ids:
                    raise CuratedStoreError(f"duplicate doc_id across inputs: {doc_id}")
                if fingerprint in seen_fingerprints:
                    raise CuratedStoreError(
                        f"duplicate content fingerprint across inputs: {fingerprint}"
                    )
                seen_doc_ids.add(doc_id)
                seen_fingerprints.add(fingerprint)
                rows.append({"row": dict(row), **metadata})
                selected_rows += 1
        if not input_rows:
            raise CuratedStoreError(f"input JSONL contains no records: {input_path}")
        input_receipts.append(
            {
                "path_hint": _input_path_hint(input_path, repository_root=repository_root),
                "sha256": sha256_path(input_path),
                "bytes": input_path.stat().st_size,
                "rows": input_rows,
                "selected_rows": selected_rows,
                "excluded_rows": input_rows - selected_rows,
                "excluded_source_counts": dict(sorted(skipped_source_counts.items())),
            }
        )
    return (
        rows,
        sorted(input_receipts, key=lambda item: (item["path_hint"], item["sha256"])),
        excluded_source_counts,
    )


def _pack_role_rows(
    *,
    stage_root: Path,
    profile_id: str,
    role: str,
    rows: Sequence[dict[str, Any]],
    max_shard_bytes: int,
) -> list[dict[str, Any]]:
    """Write one role's rows into deterministic, complete-record JSONL shards."""

    shard_rows: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 0
    shard_number = 0
    emitted: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal shard_number, current, current_bytes
        if not current:
            return
        shard_number += 1
        path = Path("shards") / f"{role}-{profile_id}-{shard_number:04d}.jsonl"
        destination = stage_root / path
        _write_jsonl(destination, (item["row"] for item in current))
        byte_count = destination.stat().st_size
        if byte_count > max_shard_bytes:
            raise AssertionError("shard packer wrote a shard above its byte budget")
        source_ids = sorted({item["source_id"] for item in current})
        retrieval_policy_counts = Counter(
            str(item["row"].get("retrieval_policy") or "standard").strip().lower()
            for item in current
        )
        languages = sorted(
            {
                language
                for item in current
                for language in _as_string_list(item["row"].get("language"))
            }
        )
        jurisdictions = sorted(
            {
                jurisdiction
                for item in current
                for jurisdiction in _as_string_list(
                    item["row"].get("jurisdiction") or item["row"].get("region")
                )
            }
        )
        emitted.append(
            {
                "id": f"{role}-{profile_id}-{shard_number:04d}",
                "path": path.as_posix(),
                "sha256": sha256_path(destination),
                "bytes": byte_count,
                "rows": len(current),
                "source_ids": source_ids,
                "languages": languages,
                "jurisdictions": jurisdictions,
                "policy_role": role,
                "row_retrieval_policy_counts": dict(sorted(retrieval_policy_counts.items())),
                "unique_doc_ids": len({item["doc_id"] for item in current}),
                "unique_content_fingerprints": len(
                    {item["content_fingerprint"] for item in current}
                ),
            }
        )
        shard_rows.extend(current)
        current = []
        current_bytes = 0

    for item in sorted(rows, key=lambda item: _row_sort_key(item["row"])):
        record = canonical_json_bytes(item["row"])
        if len(record) > max_shard_bytes:
            raise CuratedStoreError(
                f"row {item['doc_id']} is {len(record)} bytes and cannot fit the shard budget "
                f"of {max_shard_bytes} bytes"
            )
        if current and current_bytes + len(record) > max_shard_bytes:
            flush()
        current.append(item)
        current_bytes += len(record)
    flush()
    if sum(item["rows"] for item in emitted) != len(rows) or len(shard_rows) != len(rows):
        raise AssertionError("shard packer lost rows")
    return emitted


def _profile_paths_in_order(shards: Iterable[Mapping[str, Any]]) -> list[str]:
    return [
        str(shard["path"])
        for shard in sorted(
            shards,
            key=lambda shard: (
                _ROLE_ORDER[str(shard["policy_role"])],
                str(shard["path"]),
            ),
        )
    ]


def _write_profile_runtime_artifacts(
    *,
    stage_root: Path,
    profile: Mapping[str, Any],
    profile_shards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    profile_id = str(profile["id"])
    corpus_paths = _profile_paths_in_order(profile_shards)
    shard_by_path = {str(shard["path"]): shard for shard in profile_shards}
    corpora = []
    for path in corpus_paths:
        shard = shard_by_path[path]
        role = str(shard["policy_role"])
        corpus_eligibility = _ROLE_RUNTIME_ELIGIBILITY[role]
        if role == "requires_live_authority":
            reason = (
                "Rows require a live authority. They are physically separated and retain "
                "requires_live_authority row policy; the existing row-level guard blocks static use."
            )
        elif role == "context_only":
            reason = "Rows are context-only and cannot support high-consequence action."
        else:
            reason = "Rows are admitted as decisive only within their row-level source, currency, and fit limits."
        corpora.append(
            {
                "path": path,
                "runtime_path_reference": path,
                "sha256": shard["sha256"],
                "runtime_eligibility": corpus_eligibility,
                "evidence_tier": "curated_canadian_source",
                "rights_status": "redistributable_with_verified_source_scope",
                "reason": reason,
                "store_profile_id": profile_id,
                "shard_policy_role": role,
                "source_ids": shard["source_ids"],
            }
        )
    policy = {
        "schema_version": CORPUS_POLICY_SCHEMA,
        "policy_id": f"{profile_id}-curated-store-v1",
        "default_eligibility": "quarantined",
        "rules": {
            "decisive": "May support an action only within source, currency, retrieval-policy, and field-fit limits.",
            "context_only": "May explain concepts or frame questions, but cannot support a high-consequence action.",
            "quarantined": "Must not enter runtime model context.",
        },
        "corpora": corpora,
        "training_authorization": {
            "granted": False,
            "statement": "Retrieval admission and redistribution do not grant permission to train or fine-tune a model.",
        },
    }
    profile_dir = Path("profiles") / profile_id
    policy_path = profile_dir / "runtime_corpus_policy.json"
    _write_json(stage_root / policy_path, policy)
    rag_config = {
        "retrieval": {
            "artifact_root": "../..",
            "corpus_policy_manifest": policy_path.as_posix(),
            "corpus_paths": corpus_paths,
            # A profile with no graph must say so.  The runtime preserves this
            # explicit empty list rather than silently adding its legacy seed
            # graph, which would make the profile scope inaccurate.
            "graph_paths": [],
        }
    }
    rag_path = profile_dir / "rag.yaml"
    rag_serialized = yaml.safe_dump(
        rag_config,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    (stage_root / rag_path).parent.mkdir(parents=True, exist_ok=True)
    (stage_root / rag_path).write_text(rag_serialized, encoding="utf-8")
    return {
        "profile_id": profile_id,
        "description": str(profile["description"]),
        "base_profile": profile.get("base_profile"),
        "source_ids": list(profile["source_ids"]),
        "source_ids_added": [],
        "corpus_paths": corpus_paths,
        "policy_manifest_path": policy_path.as_posix(),
        "policy_manifest_sha256": sha256_path(stage_root / policy_path),
        "rag_config_path": rag_path.as_posix(),
        "rag_config_sha256": sha256_path(stage_root / rag_path),
    }


def _extractor_contract(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    contracts: set[tuple[str, int, int | None, int | None]] = set()
    for item in rows:
        lineage = item["row"].get("lineage") or {}
        extractor = lineage.get("extractor") if isinstance(lineage, Mapping) else None
        if not isinstance(extractor, Mapping):
            raise CuratedStoreError(
                f"row {item['doc_id']} is missing lineage.extractor; store cannot bind chunking provenance"
            )
        name = str(extractor.get("name") or "").strip()
        version = extractor.get("schema_version")
        if not name or not isinstance(version, int) or version <= 0:
            raise CuratedStoreError(
                f"row {item['doc_id']} has incomplete lineage.extractor provenance"
            )
        max_words = extractor.get("max_words")
        overlap_words = extractor.get("overlap_words")
        if max_words is not None and not isinstance(max_words, int):
            raise CuratedStoreError(f"row {item['doc_id']} extractor.max_words must be an integer")
        if overlap_words is not None and not isinstance(overlap_words, int):
            raise CuratedStoreError(f"row {item['doc_id']} extractor.overlap_words must be an integer")
        contracts.add((name, version, max_words, overlap_words))
    return [
        {
            "name": name,
            "schema_version": version,
            "max_words": max_words,
            "overlap_words": overlap_words,
        }
        for name, version, max_words, overlap_words in sorted(contracts)
    ]


def build_curated_knowledge_store(
    *,
    store_id: str,
    release_date: str,
    source_manifest_path: Path,
    profile_spec_path: Path,
    input_paths: Sequence[Path],
    output_root: Path,
    max_shard_bytes: int = DEFAULT_MAX_SHARD_BYTES,
    repository_root: Path | None = None,
    allow_semantic_rebind: bool = False,
) -> dict[str, Any]:
    """Build and atomically promote a compact curated knowledge store.

    ``output_root`` must not already exist.  That intentionally makes a
    release immutable at this layer; callers who want a new release create a
    new versioned output directory rather than mutating a known-good one.
    """

    store_id = _require_identifier(store_id, label="store_id")
    release_date = _require_release_date(release_date)
    if not isinstance(max_shard_bytes, int) or not 0 < max_shard_bytes <= MAX_SHARD_BYTES:
        raise CuratedStoreError(
            f"max_shard_bytes must be between 1 and {MAX_SHARD_BYTES} (24 MiB)"
        )
    output_root = Path(output_root)
    if output_root.exists():
        raise CuratedStoreError(
            f"output_root already exists; create a new versioned store instead: {output_root}"
        )
    if output_root.parent.exists() and not output_root.parent.is_dir():
        raise CuratedStoreError(f"output_root parent is not a directory: {output_root.parent}")
    output_root.parent.mkdir(parents=True, exist_ok=True)

    try:
        source_manifest = load_canada_source_manifest(source_manifest_path)
    except (OSError, ValueError) as exc:
        raise CuratedStoreError(f"invalid source manifest {source_manifest_path}: {exc}") from exc
    source_manifest_hash = sha256_path(source_manifest_path)
    source_by_id = {
        str(source["id"]): source
        for source in source_manifest.get("sources", [])
        if isinstance(source, Mapping)
    }
    profiles = load_profile_spec(profile_spec_path)
    profile_source_ids = {
        source_id for profile in profiles for source_id in profile["source_ids"]
    }
    unknown_profile_sources = sorted(profile_source_ids - set(source_by_id))
    if unknown_profile_sources:
        raise CuratedStoreError(
            f"profile specification references unknown source IDs: {unknown_profile_sources}"
        )
    for source_id in sorted(profile_source_ids):
        source = source_by_id[source_id]
        if not source_allowed_for(dict(source), "local_rag") or not source_allowed_for(
            dict(source), "distributable_bundle"
        ):
            raise CuratedStoreError(
                f"profile source {source_id} lacks distributable local-RAG rights"
            )
        if (source.get("use_policy") or {}).get("training") is not False:
            raise CuratedStoreError(
                f"profile source {source_id} enables training; curated RAG release does not grant training permission"
            )

    rows, input_receipts, excluded_input_source_counts = _load_and_validate_rows(
        input_paths,
        source_by_id=source_by_id,
        selected_source_ids=profile_source_ids,
        repository_root=repository_root,
        allow_semantic_rebind=allow_semantic_rebind,
    )
    rows_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in rows:
        rows_by_source[item["source_id"]].append(item)
    missing_profile_rows = sorted(
        source_id for source_id in profile_source_ids if not rows_by_source.get(source_id)
    )
    if missing_profile_rows:
        raise CuratedStoreError(
            f"selected profile sources produced no rows: {missing_profile_rows}"
        )

    stage_root = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.build-", dir=output_root.parent)
    )
    try:
        all_shards: list[dict[str, Any]] = []
        profile_records: list[dict[str, Any]] = []
        profile_shards: dict[str, list[dict[str, Any]]] = {}
        assigned_source_ids: set[str] = set()
        for profile in profiles:
            profile_id = str(profile["id"])
            base_profile = profile.get("base_profile")
            inherited_shards = list(profile_shards.get(str(base_profile), [])) if base_profile else []
            inherited_sources = (
                set(next(record for record in profile_records if record["profile_id"] == base_profile)["source_ids"])
                if base_profile
                else set()
            )
            source_ids_added = sorted(set(profile["source_ids"]) - inherited_sources)
            # A source may only be physically emitted once.  Profile inheritance
            # is the explicit sharing contract that prevents a core corpus from
            # being duplicated into an extended store.
            already_assigned = sorted(set(source_ids_added) & assigned_source_ids)
            if already_assigned:
                raise CuratedStoreError(
                    f"profile {profile_id} reuses sources outside declared inheritance: {already_assigned}"
                )
            delta_rows = [item for item in rows if item["source_id"] in set(source_ids_added)]
            delta_shards: list[dict[str, Any]] = []
            for role in sorted(_ROLE_ORDER, key=_ROLE_ORDER.__getitem__):
                role_rows = [item for item in delta_rows if item["role"] == role]
                if role_rows:
                    delta_shards.extend(
                        _pack_role_rows(
                            stage_root=stage_root,
                            profile_id=profile_id,
                            role=role,
                            rows=role_rows,
                            max_shard_bytes=max_shard_bytes,
                        )
                    )
            assigned_source_ids.update(source_ids_added)
            all_shards.extend(delta_shards)
            effective_shards = [*inherited_shards, *delta_shards]
            profile_shards[profile_id] = effective_shards
            profile_record = _write_profile_runtime_artifacts(
                stage_root=stage_root,
                profile=profile,
                profile_shards=effective_shards,
            )
            profile_record["source_ids_added"] = source_ids_added
            profile_records.append(profile_record)

        source_coverage = []
        for source_id in sorted(profile_source_ids):
            source = source_by_id[source_id]
            source_rows = rows_by_source[source_id]
            source_coverage.append(
                {
                    "source_id": source_id,
                    "source_title": source.get("title"),
                    "publisher": source.get("publisher"),
                    "authority_type": source.get("authority_type"),
                    "source_record_sha256": _source_record_sha256(source),
                    "license_snapshot": source_license_snapshot(dict(source)),
                    "use_policy": {
                        "local_rag": bool((source.get("use_policy") or {}).get("local_rag")),
                        "distributable_bundle": bool(
                            (source.get("use_policy") or {}).get("distributable_bundle")
                        ),
                        "training": bool((source.get("use_policy") or {}).get("training")),
                    },
                    "rows": len(source_rows),
                    "policy_roles": sorted({item["role"] for item in source_rows}, key=_ROLE_ORDER.__getitem__),
                    "crops": _as_string_list(source.get("crops")),
                    "topic_buckets": _as_string_list(source.get("buckets")),
                    "source_declared_jurisdictions": _as_string_list(source.get("jurisdiction")),
                    "languages": sorted(
                        {
                            language
                            for item in source_rows
                            for language in _as_string_list(item["row"].get("language"))
                        }
                    ),
                    "jurisdictions": sorted(
                        {
                            jurisdiction
                            for item in source_rows
                            for jurisdiction in _as_string_list(
                                item["row"].get("jurisdiction") or item["row"].get("region")
                            )
                        }
                    ),
                    "profile_ids": sorted(
                        profile["id"] for profile in profiles if source_id in profile["source_ids"]
                    ),
                }
            )
        excluded_source_ids = sorted(excluded_input_source_counts)
        source_declared_rows_by_crop: Counter[str] = Counter()
        source_declared_rows_by_topic: Counter[str] = Counter()
        source_declared_rows_by_jurisdiction: Counter[str] = Counter()
        row_count_by_jurisdiction: Counter[str] = Counter()
        source_count_by_profile: Counter[str] = Counter()
        for coverage in source_coverage:
            row_count = int(coverage["rows"])
            for crop in coverage["crops"]:
                source_declared_rows_by_crop[crop] += row_count
            for topic in coverage["topic_buckets"]:
                source_declared_rows_by_topic[topic] += row_count
            for jurisdiction in coverage["source_declared_jurisdictions"]:
                source_declared_rows_by_jurisdiction[jurisdiction] += row_count
            for jurisdiction in coverage["jurisdictions"]:
                row_count_by_jurisdiction[jurisdiction] += row_count
            for profile_id in coverage["profile_ids"]:
                source_count_by_profile[profile_id] += 1
        source_coverage_receipt = {
            "schema_version": CURATED_STORE_RECEIPT_SCHEMA,
            "receipt_type": "source_coverage",
            "store_id": store_id,
            "release_date": release_date,
            "sources": source_coverage,
            "coverage_summary": {
                "measurement_boundary": (
                    "Counts describe included source rows against publisher-declared crop/topic/"
                    "jurisdiction metadata. They route applicability and expose gaps; they do not "
                    "establish field-level coverage or recommendation authority."
                ),
                "source_declared_rows_by_crop": dict(sorted(source_declared_rows_by_crop.items())),
                "source_declared_rows_by_topic": dict(sorted(source_declared_rows_by_topic.items())),
                "source_declared_rows_by_jurisdiction": dict(
                    sorted(source_declared_rows_by_jurisdiction.items())
                ),
                "row_count_by_row_jurisdiction": dict(sorted(row_count_by_jurisdiction.items())),
                "source_count_by_profile": dict(sorted(source_count_by_profile.items())),
            },
            "excluded_sources": [
                {
                    "source_id": source_id,
                    "rows": int(excluded_input_source_counts[source_id]),
                    "reason": "not_selected_by_profile_spec",
                }
                for source_id in excluded_source_ids
            ],
            "training_authorization": {
                "granted": False,
                "statement": "RAG redistribution and retrieval admission do not authorize training or fine-tuning.",
            },
        }
        coverage_path = Path("receipts") / "source_coverage.json"
        _write_json(stage_root / coverage_path, source_coverage_receipt)

        extractor_contract = _extractor_contract(
            item for item in rows if item["source_id"] in profile_source_ids
        )
        ingest_summary = {
            "schema_version": CURATED_STORE_RECEIPT_SCHEMA,
            "receipt_type": "ingest_summary",
            "store_id": store_id,
            "release_date": release_date,
            "input_corpora": input_receipts,
            "input_rows": sum(int(receipt["rows"]) for receipt in input_receipts),
            "selected_rows": len(rows),
            "excluded_input_rows": sum(
                int(receipt["excluded_rows"]) for receipt in input_receipts
            ),
            "excluded_input_source_counts": dict(sorted(excluded_input_source_counts.items())),
            "extractor_contract": extractor_contract,
            "semantic_companion_rebindings": sum(
                1 for item in rows if item.get("semantic_companion_rebound")
            ),
            "semantic_companion_rebinding_policy": (
                "Only path, hash, and review metadata may be rebound after exact title, text, "
                "source-page, source-ID, and parent-raw-hash agreement with a registry-pinned "
                "reviewed semantic companion."
            ),
            "network_access": "not_performed_by_curated_store_builder",
        }
        ingest_path = Path("receipts") / "ingest_summary.json"
        _write_json(stage_root / ingest_path, ingest_summary)

        selected_rows = [item for item in rows if item["source_id"] in profile_source_ids]
        manifest = {
            "schema_version": CURATED_STORE_SCHEMA,
            "store_id": store_id,
            "release_date": release_date,
            "builder": {
                "name": CURATED_STORE_BUILDER,
                "version": CURATED_STORE_BUILDER_VERSION,
                "packing_order": [
                    "policy_role",
                    "source_id",
                    "source_edition_hash",
                    "chunk_index",
                    "doc_id",
                ],
            },
            "source_registry": {
                "schema_version": source_manifest.get("schema_version"),
                "sha256": source_manifest_hash,
                "path_hint": _input_path_hint(source_manifest_path, repository_root=repository_root),
            },
            "chunking": {
                "extractors": extractor_contract,
                "input_mode": "preextracted_jsonl",
            },
            "max_shard_bytes": max_shard_bytes,
            "training_authorization": {
                "granted": False,
                "statement": "No source in this store is admitted for training; retrieval admission does not grant a training or fine-tuning licence.",
            },
            "shards": sorted(
                all_shards,
                key=lambda shard: (
                    _ROLE_ORDER[str(shard["policy_role"])],
                    str(shard["path"]),
                ),
            ),
            "profiles": sorted(profile_records, key=lambda profile: str(profile["profile_id"])),
            "included_source_ids": sorted(profile_source_ids),
            "excluded_source_ids": excluded_source_ids,
            "receipts": {
                "ingest_summary_path": ingest_path.as_posix(),
                "ingest_summary_sha256": sha256_path(stage_root / ingest_path),
                "source_coverage_path": coverage_path.as_posix(),
                "source_coverage_sha256": sha256_path(stage_root / coverage_path),
            },
            "totals": {
                "shards": len(all_shards),
                "bytes": sum(int(shard["bytes"]) for shard in all_shards),
                "rows": len(selected_rows),
                "unique_doc_ids": len({item["doc_id"] for item in selected_rows}),
                "unique_content_fingerprints": len(
                    {item["content_fingerprint"] for item in selected_rows}
                ),
            },
        }
        _write_json(stage_root / "store_manifest.json", manifest)
        validation = validate_curated_knowledge_store(
            store_root=stage_root,
            source_manifest_path=source_manifest_path,
            expected_profile_ids={profile["id"] for profile in profiles},
            repository_root=repository_root,
        )
        if validation["status"] != "pass":
            raise CuratedStoreError(
                "generated store failed validation: " + "; ".join(validation["errors"])
            )
        os.replace(stage_root, output_root)
        return {
            "store_root": str(output_root),
            "manifest": manifest,
            "validation": validation,
        }
    except Exception:
        shutil.rmtree(stage_root, ignore_errors=True)
        raise


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CuratedStoreError(f"unable to read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CuratedStoreError(f"{label} must be a JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CuratedStoreError(f"invalid JSON in {path}:{line_number}: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise CuratedStoreError(f"row in {path}:{line_number} is not an object")
            rows.append(row)
    return rows


def validate_curated_knowledge_store(
    *,
    store_root: Path,
    source_manifest_path: Path,
    expected_profile_ids: set[str] | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Validate a promoted or staged store without using the network."""

    errors: list[str] = []
    store_root = Path(store_root)
    manifest_path = store_root / "store_manifest.json"
    try:
        manifest = _load_json(manifest_path, label="store manifest")
    except CuratedStoreError as exc:
        return {"status": "fail", "errors": [str(exc)]}
    if manifest.get("schema_version") != CURATED_STORE_SCHEMA:
        errors.append(f"unsupported_schema:{manifest.get('schema_version')}")
    try:
        _require_identifier(manifest.get("store_id"), label="store_manifest.store_id")
        _require_release_date(str(manifest.get("release_date") or ""))
    except CuratedStoreError as exc:
        errors.append(str(exc))
    max_shard_bytes = manifest.get("max_shard_bytes")
    if not isinstance(max_shard_bytes, int) or not 0 < max_shard_bytes <= MAX_SHARD_BYTES:
        errors.append("invalid_max_shard_bytes")
        max_shard_bytes = MAX_SHARD_BYTES
    training = manifest.get("training_authorization")
    if not isinstance(training, Mapping) or training.get("granted") is not False:
        errors.append("training_authorization_must_be_false")
    source_registry = manifest.get("source_registry")
    source_registry_digest_match = False
    source_by_id: dict[str, Mapping[str, Any]] = {}
    try:
        source_manifest = load_canada_source_manifest(source_manifest_path)
        source_by_id = {
            str(source["id"]): source
            for source in source_manifest.get("sources", [])
            if isinstance(source, Mapping)
        }
        source_registry_digest_match = bool(
            isinstance(source_registry, Mapping)
            and source_registry.get("sha256") == sha256_path(source_manifest_path)
        )
    except (OSError, ValueError) as exc:
        errors.append(f"invalid_source_manifest:{exc}")

    included_source_ids = manifest.get("included_source_ids")
    if not isinstance(included_source_ids, list) or not included_source_ids:
        errors.append("included_source_ids_missing")
        included_source_ids = []
    elif included_source_ids != sorted(set(str(item) for item in included_source_ids)):
        errors.append("included_source_ids_not_sorted_unique")
    for source_id in included_source_ids:
        source = source_by_id.get(str(source_id))
        if source is None:
            errors.append(f"unknown_included_source:{source_id}")
            continue
        if not source_allowed_for(dict(source), "local_rag") or not source_allowed_for(
            dict(source), "distributable_bundle"
        ):
            errors.append(f"source_not_distributable:{source_id}")
        if (source.get("use_policy") or {}).get("training") is not False:
            errors.append(f"source_training_not_false:{source_id}")

    raw_shards = manifest.get("shards")
    if not isinstance(raw_shards, list) or not raw_shards:
        errors.append("shards_missing")
        raw_shards = []
    shard_by_path: dict[str, Mapping[str, Any]] = {}
    seen_doc_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    actual_rows = 0
    actual_bytes = 0
    for index, shard in enumerate(raw_shards):
        label = f"shards[{index}]"
        if not isinstance(shard, Mapping):
            errors.append(f"{label}_not_object")
            continue
        try:
            path_text = _safe_relative_path(str(shard.get("path") or ""))
            _require_identifier(shard.get("id"), label=f"{label}.id")
            _require_sha256(shard.get("sha256"), label=f"{label}.sha256")
        except CuratedStoreError as exc:
            errors.append(str(exc))
            continue
        if path_text in shard_by_path:
            errors.append(f"duplicate_shard_path:{path_text}")
            continue
        shard_by_path[path_text] = shard
        role = str(shard.get("policy_role") or "")
        if role not in _ROLE_ORDER:
            errors.append(f"invalid_shard_policy_role:{path_text}:{role}")
            continue
        path = store_root / path_text
        if not path.is_file():
            errors.append(f"missing_shard:{path_text}")
            continue
        byte_count = path.stat().st_size
        actual_bytes += byte_count
        if byte_count > max_shard_bytes:
            errors.append(f"shard_over_budget:{path_text}:{byte_count}")
        if shard.get("bytes") != byte_count:
            errors.append(f"shard_byte_count_mismatch:{path_text}")
        if shard.get("sha256") != sha256_path(path):
            errors.append(f"shard_sha256_mismatch:{path_text}")
        try:
            rows = _read_jsonl(path)
        except CuratedStoreError as exc:
            errors.append(str(exc))
            continue
        if shard.get("rows") != len(rows):
            errors.append(f"shard_row_count_mismatch:{path_text}")
        actual_rows += len(rows)
        observed_sources: set[str] = set()
        observed_policies: Counter[str] = Counter()
        observed_languages: set[str] = set()
        observed_jurisdictions: set[str] = set()
        for row_number, row in enumerate(rows, start=1):
            try:
                metadata = _validate_row(
                    row,
                    label=f"{path_text}:{row_number}",
                    source_by_id=source_by_id,
                    repository_root=repository_root,
                )
            except CuratedStoreError as exc:
                errors.append(str(exc))
                continue
            if metadata["source_id"] not in included_source_ids:
                errors.append(f"unlisted_source_in_shard:{path_text}:{metadata['source_id']}")
            if metadata["role"] != role:
                errors.append(f"mixed_policy_role:{path_text}:{metadata['role']}")
            if metadata["doc_id"] in seen_doc_ids:
                errors.append(f"duplicate_doc_id:{metadata['doc_id']}")
            if metadata["content_fingerprint"] in seen_fingerprints:
                errors.append(f"duplicate_content_fingerprint:{metadata['content_fingerprint']}")
            seen_doc_ids.add(metadata["doc_id"])
            seen_fingerprints.add(metadata["content_fingerprint"])
            observed_sources.add(metadata["source_id"])
            observed_policies[str(row.get("retrieval_policy") or "standard").strip().lower()] += 1
            observed_languages.update(_as_string_list(row.get("language")))
            observed_jurisdictions.update(
                _as_string_list(row.get("jurisdiction") or row.get("region"))
            )
        if shard.get("source_ids") != sorted(observed_sources):
            errors.append(f"shard_source_ids_mismatch:{path_text}")
        if shard.get("row_retrieval_policy_counts") != dict(sorted(observed_policies.items())):
            errors.append(f"shard_policy_counts_mismatch:{path_text}")
        if shard.get("languages") != sorted(observed_languages):
            errors.append(f"shard_languages_mismatch:{path_text}")
        if shard.get("jurisdictions") != sorted(observed_jurisdictions):
            errors.append(f"shard_jurisdictions_mismatch:{path_text}")

    totals = manifest.get("totals") if isinstance(manifest.get("totals"), Mapping) else {}
    if totals.get("shards") != len(raw_shards):
        errors.append("total_shards_mismatch")
    if totals.get("rows") != actual_rows:
        errors.append("total_rows_mismatch")
    if totals.get("bytes") != actual_bytes:
        errors.append("total_bytes_mismatch")
    if totals.get("unique_doc_ids") != len(seen_doc_ids):
        errors.append("total_unique_doc_ids_mismatch")
    if totals.get("unique_content_fingerprints") != len(seen_fingerprints):
        errors.append("total_unique_content_fingerprints_mismatch")

    receipts = manifest.get("receipts") if isinstance(manifest.get("receipts"), Mapping) else {}
    source_snapshot_records: dict[str, Mapping[str, Any]] = {}
    source_snapshot_is_valid = False
    for name in ("ingest_summary", "source_coverage"):
        path_key = f"{name}_path"
        sha_key = f"{name}_sha256"
        try:
            receipt_path = _safe_relative_path(str(receipts.get(path_key) or ""))
        except CuratedStoreError as exc:
            errors.append(str(exc))
            continue
        absolute_receipt = store_root / receipt_path
        if not absolute_receipt.is_file():
            errors.append(f"missing_receipt:{receipt_path}")
        elif receipts.get(sha_key) != sha256_path(absolute_receipt):
            errors.append(f"receipt_sha256_mismatch:{receipt_path}")
        elif name == "source_coverage":
            try:
                coverage = _load_json(absolute_receipt, label="source coverage receipt")
                coverage_sources = coverage.get("sources")
                if not isinstance(coverage_sources, list):
                    errors.append("source_coverage_sources_missing")
                    continue
                source_snapshot_is_valid = True
                if coverage.get("schema_version") != CURATED_STORE_RECEIPT_SCHEMA:
                    errors.append("invalid_source_coverage_schema")
                    source_snapshot_is_valid = False
                if coverage.get("receipt_type") != "source_coverage":
                    errors.append("invalid_source_coverage_receipt_type")
                    source_snapshot_is_valid = False
                if coverage.get("store_id") != manifest.get("store_id"):
                    errors.append("source_coverage_store_id_mismatch")
                    source_snapshot_is_valid = False
                duplicate_ids: set[str] = set()
                for row in coverage_sources:
                    if not isinstance(row, Mapping):
                        errors.append("source_coverage_record_not_object")
                        source_snapshot_is_valid = False
                        continue
                    source_id = str(row.get("source_id") or "")
                    if not _ID_RE.fullmatch(source_id):
                        errors.append(f"invalid_source_coverage_id:{source_id}")
                        source_snapshot_is_valid = False
                        continue
                    if source_id in source_snapshot_records:
                        duplicate_ids.add(source_id)
                    source_snapshot_records[source_id] = row
                for source_id in sorted(duplicate_ids):
                    errors.append(f"duplicate_source_coverage_id:{source_id}")
                if duplicate_ids:
                    source_snapshot_is_valid = False
            except CuratedStoreError as exc:
                errors.append(str(exc))

    # The store manifest records the complete source-registry digest observed at
    # build time.  That digest is useful provenance, but an append-only registry
    # will legitimately change as unrelated sources are admitted.  The
    # hash-bound source-coverage receipt is the stable validation boundary for a
    # promoted store: every included source record must still be byte-equivalent
    # in canonical form and retain safe current use-policy checks above.
    snapshot_source_ids = set(source_snapshot_records)
    if source_snapshot_is_valid and snapshot_source_ids != set(included_source_ids):
        errors.append("source_coverage_ids_mismatch")
        source_snapshot_is_valid = False
    for source_id in included_source_ids:
        snapshot = source_snapshot_records.get(str(source_id))
        source = source_by_id.get(str(source_id))
        if not isinstance(snapshot, Mapping) or source is None:
            source_snapshot_is_valid = False
            continue
        if snapshot.get("source_record_sha256") != _source_record_sha256(source):
            errors.append(f"source_record_sha256_mismatch:{source_id}")
            source_snapshot_is_valid = False
    if not source_registry_digest_match and not source_snapshot_is_valid:
        errors.append("source_registry_sha256_mismatch_without_valid_source_snapshot")

    profiles = manifest.get("profiles")
    profile_ids: set[str] = set()
    profile_by_id: dict[str, Mapping[str, Any]] = {}
    if not isinstance(profiles, list) or not profiles:
        errors.append("profiles_missing")
        profiles = []
    for index, profile in enumerate(profiles):
        if not isinstance(profile, Mapping):
            errors.append(f"profiles[{index}]_not_object")
            continue
        profile_id = str(profile.get("profile_id") or "")
        if not _ID_RE.fullmatch(profile_id) or profile_id in profile_ids:
            errors.append(f"invalid_or_duplicate_profile:{profile_id}")
            continue
        profile_ids.add(profile_id)
        profile_by_id[profile_id] = profile
        corpus_paths = profile.get("corpus_paths")
        if not isinstance(corpus_paths, list) or not corpus_paths:
            errors.append(f"profile_paths_missing:{profile_id}")
            continue
        corpus_paths = [str(path) for path in corpus_paths]
        if corpus_paths != _profile_paths_in_order(
            shard_by_path[path]
            for path in corpus_paths
            if path in shard_by_path
        ):
            errors.append(f"profile_paths_not_exact_order:{profile_id}")
        missing_profile_paths = sorted(set(corpus_paths) - set(shard_by_path))
        if missing_profile_paths:
            errors.append(f"profile_references_missing_shards:{profile_id}:{missing_profile_paths}")
        for artifact_name, expected_suffix in (
            ("policy_manifest", "runtime_corpus_policy.json"),
            ("rag_config", "rag.yaml"),
        ):
            path_key = f"{artifact_name}_path"
            sha_key = f"{artifact_name}_sha256"
            path_value = str(profile.get(path_key) or "")
            try:
                path_value = _safe_relative_path(path_value)
            except CuratedStoreError as exc:
                errors.append(str(exc))
                continue
            if not path_value.endswith(expected_suffix):
                errors.append(f"invalid_{artifact_name}_path:{profile_id}")
            artifact_path = store_root / path_value
            if not artifact_path.is_file():
                errors.append(f"missing_{artifact_name}:{profile_id}")
                continue
            if profile.get(sha_key) != sha256_path(artifact_path):
                errors.append(f"{artifact_name}_sha256_mismatch:{profile_id}")
        policy_path = store_root / str(profile.get("policy_manifest_path") or "")
        rag_path = store_root / str(profile.get("rag_config_path") or "")
        if policy_path.is_file():
            try:
                policy = _load_json(policy_path, label="runtime corpus policy")
                policy_paths = [str(item.get("path") or "") for item in policy.get("corpora") or []]
                if policy.get("schema_version") != CORPUS_POLICY_SCHEMA:
                    errors.append(f"invalid_runtime_policy_schema:{profile_id}")
                if policy_paths != corpus_paths:
                    errors.append(f"policy_paths_mismatch:{profile_id}")
                for item in policy.get("corpora") or []:
                    path = str(item.get("path") or "")
                    shard = shard_by_path.get(path)
                    if shard is None:
                        continue
                    if item.get("sha256") != shard.get("sha256"):
                        errors.append(f"policy_shard_hash_mismatch:{profile_id}:{path}")
            except CuratedStoreError as exc:
                errors.append(str(exc))
        if rag_path.is_file():
            try:
                config = yaml.safe_load(rag_path.read_text(encoding="utf-8")) or {}
                retrieval = config.get("retrieval") if isinstance(config, Mapping) else None
                config_paths = retrieval.get("corpus_paths") if isinstance(retrieval, Mapping) else None
                if config_paths != corpus_paths:
                    errors.append(f"rag_config_paths_mismatch:{profile_id}")
                if not isinstance(retrieval, Mapping) or retrieval.get("graph_paths") != []:
                    errors.append(f"rag_config_graph_scope_mismatch:{profile_id}")
                if (
                    not isinstance(retrieval, Mapping)
                    or retrieval.get("corpus_policy_manifest")
                    != profile.get("policy_manifest_path")
                ):
                    errors.append(f"rag_config_policy_path_mismatch:{profile_id}")
            except yaml.YAMLError as exc:
                errors.append(f"invalid_rag_yaml:{profile_id}:{exc}")
    for profile_id, profile in profile_by_id.items():
        source_ids = profile.get("source_ids")
        source_ids_added = profile.get("source_ids_added")
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or source_ids != sorted(set(str(item) for item in source_ids))
            or any(str(source_id) not in included_source_ids for source_id in source_ids)
        ):
            errors.append(f"invalid_profile_source_ids:{profile_id}")
            continue
        base_profile = profile.get("base_profile")
        if base_profile is not None and str(base_profile) not in profile_by_id:
            errors.append(f"missing_profile_base:{profile_id}:{base_profile}")
            continue
        base_source_ids = set(
            profile_by_id[str(base_profile)].get("source_ids") or []
        ) if base_profile is not None else set()
        expected_added = sorted(set(source_ids) - base_source_ids)
        if source_ids_added != expected_added:
            errors.append(f"profile_source_delta_mismatch:{profile_id}")
        corpus_paths = [str(path) for path in profile.get("corpus_paths") or []]
        observed_profile_source_ids = {
            source_id
            for path in corpus_paths
            for source_id in (shard_by_path.get(path, {}).get("source_ids") or [])
        }
        if observed_profile_source_ids != set(source_ids):
            errors.append(f"profile_source_coverage_mismatch:{profile_id}")
    if expected_profile_ids is not None and profile_ids != set(expected_profile_ids):
        errors.append(
            f"profile_ids_mismatch:expected={sorted(expected_profile_ids)} actual={sorted(profile_ids)}"
        )

    return {
        "schema_version": CURATED_STORE_SCHEMA,
        "store_root": str(store_root),
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "source_registry_digest_match": source_registry_digest_match,
        "source_registry_validation": (
            "exact_registry_digest"
            if source_registry_digest_match
            else "included_source_records_match_current_registry"
            if source_snapshot_is_valid
            else "failed"
        ),
        "profiles": sorted(profile_ids),
        "shards": len(raw_shards),
        "rows": actual_rows,
        "bytes": actual_bytes,
    }
