from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from agronomy_agent.corpus_governance import audit_runtime_corpora
from agronomy_agent.curated_knowledge_store import (
    CURATED_PROFILE_SPEC_SCHEMA,
    CURATED_STORE_SCHEMA,
    CuratedStoreError,
    build_curated_knowledge_store,
    canonical_json_bytes,
    validate_curated_knowledge_store,
)


ROOT = Path(__file__).resolve().parents[1]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source(source_id: str, *, training: bool = False) -> dict:
    return {
        "id": source_id,
        "title": f"Verified source {source_id}",
        "publisher": "Example Canadian Publisher",
        "authority_type": "federal_government",
        "jurisdiction": ["Canada"],
        "language": ["en-CA"],
        "url": f"https://example.test/{source_id}",
        "download_url": f"https://example.test/{source_id}.html",
        "format": "html",
        "content_mode": "corpus_document",
        "runtime_source_type": "regional_environment_profile",
        "runtime_document_type": "test_document",
        "crops": ["wheat"],
        "buckets": ["soil_water"],
        "priority": "high",
        "currency": {
            "status": "current_test_source",
            "review_interval_days": 365,
            "volatile": False,
        },
        "regulatory": {"regulated_advice": False, "require_live_authority": False},
        "license": {
            "status": "redistributable",
            "identifier": "Test Open Licence",
            "evidence_url": f"https://example.test/{source_id}/licence",
            "scope_verified": True,
            "scope_basis": "source_specific_record",
            "scope_evidence_url": f"https://example.test/{source_id}/licence-scope",
            "permits_modification": True,
            "permits_commercial": True,
            "permits_redistribution": True,
            "reviewed_on": "2026-08-13",
            "attribution": f"Attribution for {source_id}",
            "notes": "Synthetic test record with a source-specific open licence.",
        },
        "use_policy": {
            "discover": True,
            "download": True,
            "local_rag": True,
            "distributable_bundle": True,
            "training": training,
            "live_retrieval": True,
        },
    }


def _source_manifest(tmp_path: Path, *sources: dict) -> Path:
    path = tmp_path / "canada_agronomy_sources.json"
    payload = {
        "schema_version": "open_agronomy_agent.canada_agronomy_sources.v1",
        "generated_at": "2026-08-13T00:00:00Z",
        "required_jurisdictions": ["Canada"],
        "sources": list(sources),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _license_snapshot(source: dict) -> dict:
    license_record = source["license"]
    return {
        "status": license_record["status"],
        "identifier": license_record["identifier"],
        "evidence_url": license_record["evidence_url"],
        "scope_verified": license_record["scope_verified"],
        "scope_basis": license_record["scope_basis"],
        "scope_evidence_url": license_record["scope_evidence_url"],
        "reviewed_on": license_record["reviewed_on"],
        "attribution": license_record["attribution"],
        "permits_modification": license_record["permits_modification"],
        "permits_commercial": license_record["permits_commercial"],
        "permits_redistribution": license_record["permits_redistribution"],
    }


def _row(source: dict, doc_id: str, text: str, retrieval_policy: str) -> dict:
    snapshot = _license_snapshot(source)
    chunk_sha = _sha(text)
    return {
        "doc_id": doc_id,
        "title": f"{source['title']} :: {doc_id}",
        "text": text,
        "source": source["url"],
        "source_id": source["id"],
        "language": ["en-CA"],
        "jurisdiction": ["Canada"],
        "retrieval_policy": retrieval_policy,
        "license_snapshot": snapshot,
        "lineage": {
            "source_id": source["id"],
            "fetched_at": "2026-08-13T00:00:00+00:00",
            "raw_sha256": _sha(f"raw:{source['id']}"),
            "extracted_text_sha256": _sha(f"extracted:{source['id']}"),
            "chunk_sha256": chunk_sha,
            "manifest_sha256": _sha("fixture-manifest"),
            "license_snapshot": snapshot,
            "retrieval_policy": retrieval_policy,
            "extractor": {
                "name": "fixture-extractor",
                "schema_version": 1,
                "max_words": 220,
                "overlap_words": 35,
            },
        },
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))


def _profile_spec(tmp_path: Path, profiles: list[dict]) -> Path:
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"schema_version": CURATED_PROFILE_SPEC_SCHEMA, "profiles": profiles}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_build_is_deterministic_policy_segregated_and_generates_exact_profiles(
    tmp_path: Path,
) -> None:
    source_a = _source("source-a")
    source_b = _source("source-b")
    manifest_path = _source_manifest(tmp_path, source_a, source_b)
    profile_spec = _profile_spec(
        tmp_path,
        [
            {
                "id": "canada-offline-core",
                "description": "Small Canadian core.",
                "source_ids": ["source-a"],
            },
            {
                "id": "canada-offline-extended",
                "description": "Core plus an explicit supplemental source.",
                "base_profile": "canada-offline-core",
                "source_ids": ["source-a", "source-b"],
            },
        ],
    )
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(
        input_path,
        [
            _row(source_a, "source-a-002", "Context-only Canadian context.", "context_only"),
            _row(source_b, "source-b-003", "A live source must remain live.", "requires_live_authority"),
            _row(source_a, "source-a-001", "Decisive Canadian baseline.", "standard"),
        ],
    )

    first = build_curated_knowledge_store(
        store_id="curated-canada-v1",
        release_date="2026-08-13",
        source_manifest_path=manifest_path,
        profile_spec_path=profile_spec,
        input_paths=[input_path],
        output_root=tmp_path / "store-a",
        repository_root=tmp_path,
    )
    second = build_curated_knowledge_store(
        store_id="curated-canada-v1",
        release_date="2026-08-13",
        source_manifest_path=manifest_path,
        profile_spec_path=profile_spec,
        input_paths=[input_path],
        output_root=tmp_path / "store-b",
        repository_root=tmp_path,
    )

    assert first["validation"]["status"] == "pass"
    assert second["validation"]["status"] == "pass"
    assert _tree_bytes(tmp_path / "store-a") == _tree_bytes(tmp_path / "store-b")

    store = json.loads((tmp_path / "store-a" / "store_manifest.json").read_text(encoding="utf-8"))
    assert store["schema_version"] == CURATED_STORE_SCHEMA
    assert store["max_shard_bytes"] == 24 * 1024 * 1024
    assert store["training_authorization"]["granted"] is False
    assert [shard["policy_role"] for shard in store["shards"]] == [
        "decisive",
        "context_only",
        "requires_live_authority",
    ]
    assert all(shard["bytes"] <= 24 * 1024 * 1024 for shard in store["shards"])
    assert all(len(shard["row_retrieval_policy_counts"]) == 1 for shard in store["shards"])

    coverage = json.loads(
        (tmp_path / "store-a" / "receipts/source_coverage.json").read_text(encoding="utf-8")
    )
    assert coverage["sources"][0]["crops"] == ["wheat"]
    assert coverage["sources"][0]["topic_buckets"] == ["soil_water"]
    assert coverage["coverage_summary"]["source_declared_rows_by_crop"]["wheat"] == 3

    profiles = {profile["profile_id"]: profile for profile in store["profiles"]}
    core_paths = profiles["canada-offline-core"]["corpus_paths"]
    extended_paths = profiles["canada-offline-extended"]["corpus_paths"]
    assert len(core_paths) == 2
    assert set(core_paths) < set(extended_paths)
    assert profiles["canada-offline-extended"]["source_ids_added"] == ["source-b"]
    core_rag = yaml.safe_load(
        (tmp_path / "store-a" / profiles["canada-offline-core"]["rag_config_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert core_rag["retrieval"]["graph_paths"] == []

    policy = json.loads(
        (tmp_path / "store-a" / profiles["canada-offline-extended"]["policy_manifest_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert [entry["path"] for entry in policy["corpora"]] == extended_paths
    live_entry = next(
        entry for entry in policy["corpora"] if entry["shard_policy_role"] == "requires_live_authority"
    )
    assert live_entry["runtime_eligibility"] == "decisive"
    assert policy["training_authorization"]["granted"] is False

    report = validate_curated_knowledge_store(
        store_root=tmp_path / "store-a",
        source_manifest_path=manifest_path,
        expected_profile_ids={"canada-offline-core", "canada-offline-extended"},
    )
    assert report["status"] == "pass", report["errors"]
    runtime_audit = audit_runtime_corpora(
        root=tmp_path / "store-a",
        rag_config_path=tmp_path / "store-a" / profiles["canada-offline-core"]["rag_config_path"],
    )
    assert runtime_audit["status"] == "pass", runtime_audit["errors"]


def test_builder_splits_between_records_under_a_hard_shard_budget(tmp_path: Path) -> None:
    source = _source("source-a")
    manifest_path = _source_manifest(tmp_path, source)
    profile_spec = _profile_spec(
        tmp_path,
        [
            {
                "id": "canada-offline-core",
                "description": "Small Canadian core.",
                "source_ids": ["source-a"],
            }
        ],
    )
    rows = [
        _row(source, "source-a-001", "First complete JSON record with enough text to split.", "standard"),
        _row(source, "source-a-002", "Second complete JSON record with enough text to split.", "standard"),
    ]
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(input_path, rows)
    record_size = len(canonical_json_bytes(rows[0]))

    result = build_curated_knowledge_store(
        store_id="curated-canada-v1",
        release_date="2026-08-13",
        source_manifest_path=manifest_path,
        profile_spec_path=profile_spec,
        input_paths=[input_path],
        output_root=tmp_path / "store",
        max_shard_bytes=record_size + 1,
        repository_root=tmp_path,
    )

    shards = result["manifest"]["shards"]
    assert len(shards) == 2
    assert all(shard["rows"] == 1 for shard in shards)
    assert all(shard["bytes"] <= record_size + 1 for shard in shards)


def test_validator_accepts_registry_growth_but_rejects_included_source_drift(
    tmp_path: Path,
) -> None:
    source = _source("source-a")
    manifest_path = _source_manifest(tmp_path, source)
    profile_spec = _profile_spec(
        tmp_path,
        [
            {
                "id": "canada-offline-core",
                "description": "Small Canadian core.",
                "source_ids": ["source-a"],
            }
        ],
    )
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(
        input_path,
        [_row(source, "source-a-001", "Stable source-bound context.", "context_only")],
    )
    build_curated_knowledge_store(
        store_id="curated-canada-v1",
        release_date="2026-08-13",
        source_manifest_path=manifest_path,
        profile_spec_path=profile_spec,
        input_paths=[input_path],
        output_root=tmp_path / "store",
        repository_root=tmp_path,
    )

    registry = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry["sources"].append(_source("source-unrelated"))
    manifest_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")

    growth_report = validate_curated_knowledge_store(
        store_root=tmp_path / "store",
        source_manifest_path=manifest_path,
    )
    assert growth_report["status"] == "pass", growth_report["errors"]
    assert growth_report["source_registry_digest_match"] is False
    assert (
        growth_report["source_registry_validation"]
        == "included_source_records_match_current_registry"
    )

    registry["sources"][0]["title"] = "Changed included source record"
    manifest_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    drift_report = validate_curated_knowledge_store(
        store_root=tmp_path / "store",
        source_manifest_path=manifest_path,
    )
    assert drift_report["status"] == "fail"
    assert "source_record_sha256_mismatch:source-a" in drift_report["errors"]
    assert drift_report["source_registry_validation"] == "failed"


def test_builder_rejects_enabled_training_policy_and_validator_detects_tampering(
    tmp_path: Path,
) -> None:
    training_source = _source("source-training", training=True)
    training_manifest = _source_manifest(tmp_path, training_source)
    profile_spec = _profile_spec(
        tmp_path,
        [
            {
                "id": "canada-offline-core",
                "description": "Small Canadian core.",
                "source_ids": ["source-training"],
            }
        ],
    )
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(input_path, [_row(training_source, "source-training-001", "No training implied.", "standard")])

    with pytest.raises(CuratedStoreError, match="training"):
        build_curated_knowledge_store(
            store_id="curated-canada-v1",
            release_date="2026-08-13",
            source_manifest_path=training_manifest,
            profile_spec_path=profile_spec,
            input_paths=[input_path],
            output_root=tmp_path / "training-store",
            repository_root=tmp_path,
        )

    source = _source("source-a")
    manifest_path = _source_manifest(tmp_path, source)
    clean_profile_spec = _profile_spec(
        tmp_path,
        [
            {
                "id": "canada-offline-core",
                "description": "Small Canadian core.",
                "source_ids": ["source-a"],
            }
        ],
    )
    _write_jsonl(input_path, [_row(source, "source-a-001", "Hash-bound Canadian context.", "context_only")])
    built = build_curated_knowledge_store(
        store_id="curated-canada-v1",
        release_date="2026-08-13",
        source_manifest_path=manifest_path,
        profile_spec_path=clean_profile_spec,
        input_paths=[input_path],
        output_root=tmp_path / "clean-store",
        repository_root=tmp_path,
    )
    shard_path = tmp_path / "clean-store" / built["manifest"]["shards"][0]["path"]
    shard_path.write_bytes(shard_path.read_bytes() + b"\n")
    report = validate_curated_knowledge_store(
        store_root=tmp_path / "clean-store",
        source_manifest_path=manifest_path,
    )
    assert report["status"] == "fail"
    assert any(error.startswith("shard_sha256_mismatch:") for error in report["errors"])


def test_builder_receipts_unselected_mixed_corpus_rows_without_admitting_them(
    tmp_path: Path,
) -> None:
    selected = _source("source-selected")
    manifest_path = _source_manifest(tmp_path, selected)
    profile_spec = _profile_spec(
        tmp_path,
        [
            {
                "id": "canada-offline-core",
                "description": "Only the explicitly selected source is released.",
                "source_ids": ["source-selected"],
            }
        ],
    )
    input_path = tmp_path / "mixed.jsonl"
    ignored = _row(_source("source-pending"), "source-pending-001", "Pending source text.", "standard")
    _write_jsonl(
        input_path,
        [
            _row(selected, "source-selected-001", "Approved source text.", "context_only"),
            ignored,
        ],
    )

    built = build_curated_knowledge_store(
        store_id="curated-canada-v1",
        release_date="2026-08-13",
        source_manifest_path=manifest_path,
        profile_spec_path=profile_spec,
        input_paths=[input_path],
        output_root=tmp_path / "store",
        repository_root=tmp_path,
    )

    coverage = json.loads(
        (tmp_path / "store" / "receipts" / "source_coverage.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (tmp_path / "store" / "receipts" / "ingest_summary.json").read_text(encoding="utf-8")
    )
    assert built["validation"]["status"] == "pass"
    assert coverage["excluded_sources"] == [
        {
            "reason": "not_selected_by_profile_spec",
            "rows": 1,
            "source_id": "source-pending",
        }
    ]
    assert summary["input_rows"] == 2
    assert summary["selected_rows"] == 1
    assert summary["excluded_input_rows"] == 1


def test_semantic_companion_binding_is_hash_pinned_and_rebind_is_content_exact(
    tmp_path: Path,
) -> None:
    source = _source("source-a")
    text = "Reviewed Canadian context remains exactly bound to its inspected source pages."
    row = _row(source, "source-a_semantic_0001", text, "context_only")
    companion_path = tmp_path / "companions" / "source-a.2026-08-14.semantic.json"
    companion = {
        "schema_version": "open_agronomy_agent.reviewed_semantic_companion.v1",
        "source_id": "source-a",
        "source_raw_sha256": row["lineage"]["raw_sha256"],
        "reviewed_on": "2026-08-14",
        "review_method": "Exact fixture review.",
        "records": [
            {
                "title": row["title"],
                "source_pages": [1],
                "tags": ["fixture"],
                "text": text,
            }
        ],
    }
    companion_path.parent.mkdir()
    companion_path.write_text(json.dumps(companion, indent=2) + "\n", encoding="utf-8")
    companion_sha256 = hashlib.sha256(companion_path.read_bytes()).hexdigest()
    source["ingest_policy"] = {
        "include_page_ranges": [[1, 1]],
        "exclude_page_ranges": [],
        "exclude_line_patterns": [],
        "emit_source_chunks": False,
        "semantic_companion_path": "companions/source-a.2026-08-14.semantic.json",
        "semantic_companion_sha256": companion_sha256,
    }
    stale_binding = {
        "schema_version": companion["schema_version"],
        "reviewed_on": companion["reviewed_on"],
        "review_method": companion["review_method"],
        "source_pages": [1],
        "companion_path": "companions/source-a.semantic.json",
        "companion_sha256": _sha("old-companion"),
    }
    row["semantic_companion"] = dict(stale_binding)
    row["lineage"]["semantic_companion"] = {
        "schema_version": companion["schema_version"],
        "reviewed_on": companion["reviewed_on"],
        "review_method": companion["review_method"],
        "source_pages": [1],
        "path": "companions/source-a.semantic.json",
        "sha256": _sha("old-companion"),
        "parent_raw_sha256": row["lineage"]["raw_sha256"],
    }
    manifest_path = _source_manifest(tmp_path, source)
    profile_spec = _profile_spec(
        tmp_path,
        [
            {
                "id": "canada-offline-master",
                "description": "Single cumulative Canadian store.",
                "source_ids": ["source-a"],
            }
        ],
    )
    input_path = tmp_path / "input.jsonl"
    _write_jsonl(input_path, [row])

    with pytest.raises(CuratedStoreError, match="stale or ambiguous"):
        build_curated_knowledge_store(
            store_id="curated-canada-test",
            release_date="2026-08-14",
            source_manifest_path=manifest_path,
            profile_spec_path=profile_spec,
            input_paths=[input_path],
            output_root=tmp_path / "strict-store",
            repository_root=tmp_path,
        )

    built = build_curated_knowledge_store(
        store_id="curated-canada-test",
        release_date="2026-08-14",
        source_manifest_path=manifest_path,
        profile_spec_path=profile_spec,
        input_paths=[input_path],
        output_root=tmp_path / "rebound-store",
        repository_root=tmp_path,
        allow_semantic_rebind=True,
    )
    generated_shard = (
        tmp_path / "rebound-store" / built["manifest"]["shards"][0]["path"]
    )
    generated_row = json.loads(generated_shard.read_text(encoding="utf-8").splitlines()[0])
    assert generated_row["semantic_companion"]["companion_path"] == (
        "companions/source-a.2026-08-14.semantic.json"
    )
    assert generated_row["semantic_companion"]["companion_sha256"] == companion_sha256
    ingest_summary = json.loads(
        (tmp_path / "rebound-store/receipts/ingest_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert ingest_summary["semantic_companion_rebindings"] == 1

    companion_path.write_text("{}\n", encoding="utf-8")
    report = validate_curated_knowledge_store(
        store_root=tmp_path / "rebound-store",
        source_manifest_path=manifest_path,
        repository_root=tmp_path,
    )
    assert report["status"] == "fail"
    assert any("semantic companion SHA-256 mismatch" in error for error in report["errors"])


def test_manifest_schema_is_available_and_constrains_the_24_mib_limit() -> None:
    schema_path = ROOT / "configs" / "schemas" / "curated_knowledge_store_manifest_v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == CURATED_STORE_SCHEMA
    assert schema["properties"]["max_shard_bytes"]["maximum"] == 24 * 1024 * 1024
    assert schema["$defs"]["training_authorization"]["properties"]["granted"]["const"] is False
