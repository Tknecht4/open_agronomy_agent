from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
import tarfile

import pytest
import yaml

from agronomy_agent.knowledge_updates import (
    _extract_archive_safely,
    build_knowledge_update,
    validate_knowledge_update,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_minimal_store(
    repo_root: Path,
    *,
    profile_local: bool,
) -> tuple[Path, Path]:
    """Create a minimal profile-local or legacy repository-root RAG store."""

    if profile_local:
        artifact_root = repo_root / "data" / "derived" / "rag" / "curated" / "v2"
        shard = artifact_root / "shards" / "context_only.jsonl"
        policy = artifact_root / "profiles" / "offline-extended" / "runtime_corpus_policy.json"
        config = artifact_root / "profiles" / "offline-extended" / "rag.yaml"
        artifact_root_line = "  artifact_root: ../..\n"
        policy_reference = "profiles/offline-extended/runtime_corpus_policy.json"
        corpus_reference = "shards/context_only.jsonl"
    else:
        artifact_root = repo_root
        shard = artifact_root / "data" / "context_only.jsonl"
        policy = artifact_root / "data" / "runtime_corpus_policy.json"
        config = artifact_root / "configs" / "rag.yaml"
        artifact_root_line = ""
        policy_reference = "data/runtime_corpus_policy.json"
        corpus_reference = "data/context_only.jsonl"

    shard.parent.mkdir(parents=True, exist_ok=True)
    policy.parent.mkdir(parents=True, exist_ok=True)
    config.parent.mkdir(parents=True, exist_ok=True)
    shard.write_text(
        json.dumps(
            {
                "doc_id": "mb-context-0001",
                "source_id": "mb-context",
                "title": "Manitoba context",
                "text": "Context only scouting material.",
                "source": "https://example.test/mb",
                "retrieval_policy": "context_only",
                "jurisdiction": ["Manitoba"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    policy.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.runtime_corpus_policy.v1",
                "policy_id": "profile-local-test",
                "default_eligibility": "quarantined",
                "rules": {
                    "decisive": "bounded action support",
                    "context_only": "context only",
                    "quarantined": "not runtime eligible",
                },
                "corpora": [
                    {
                        "path": corpus_reference,
                        "sha256": _sha256(shard),
                        "runtime_eligibility": "context_only",
                        "evidence_tier": "curated_canadian_source",
                        "rights_status": "redistributable",
                        "reason": "reviewed context-only test source",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    config.write_text(
        """retrieval:
"""
        + artifact_root_line
        + f"""  corpus_policy_manifest: {policy_reference}
  corpus_paths:
    - {corpus_reference}
  graph_paths: []
""",
        encoding="utf-8",
    )
    return config, artifact_root


def test_knowledge_update_excludes_quarantined_missing_corpus_before_packaging(tmp_path) -> None:  # noqa: ANN001
    repo_root = tmp_path / "repository"
    repo_root.mkdir()
    rag_config, _ = _write_minimal_store(repo_root, profile_local=False)
    policy_path = repo_root / "data/runtime_corpus_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    quarantined_paths = (
        "data/missing_objective_corpus.jsonl",
        "data/missing_document_expansion_corpus.jsonl",
    )
    for path in quarantined_paths:
        policy["corpora"].append(
            {
                "path": path,
                "sha256": "0" * 64,
                "runtime_eligibility": "quarantined",
                "evidence_tier": "fixture_unreviewed",
                "rights_status": "not_admitted",
                "reason": "missing fixture corpus must be excluded before packaging",
            }
        )
    policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    rag = yaml.safe_load(rag_config.read_text(encoding="utf-8"))
    rag["retrieval"]["corpus_paths"].extend(quarantined_paths)
    rag_config.write_text(yaml.safe_dump(rag, sort_keys=False), encoding="utf-8")

    archive = tmp_path / "update.tar.gz"
    report = build_knowledge_update(
        repo_root=repo_root,
        rag_config=rag_config,
        output_archive=archive,
        package_id="governance-test",
        release_sequence=1,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    )

    with tarfile.open(archive, "r:gz") as package:
        manifest_file = package.extractfile("governance-test/knowledge_update_manifest.json")
        config_file = package.extractfile("governance-test/configs/rag.yaml")
        assert manifest_file is not None
        assert config_file is not None
        manifest = json.load(manifest_file)
        config = yaml.safe_load(
            config_file.read()
        )
        names = set(package.getnames())

    assert report["status"] == "built"
    assert "governance-test/data/missing_objective_corpus.jsonl" not in names
    excluded = manifest["excluded_configured_corpora"]
    assert {item["path"] for item in excluded} == set(quarantined_paths)
    assert not set(quarantined_paths) & set(config["retrieval"]["corpus_paths"])
    assert config["retrieval"]["excluded_configured_corpora"] == excluded
    assert config["retrieval"]["artifact_root"] == ".."


def test_knowledge_update_packages_and_validates_profile_local_artifact_root(tmp_path) -> None:  # noqa: ANN001
    repo_root = tmp_path / "repository"
    repo_root.mkdir()
    rag_config, source_artifact_root = _write_minimal_store(
        repo_root,
        profile_local=True,
    )
    archive = tmp_path / "profile-local.tar.gz"

    report = build_knowledge_update(
        repo_root=repo_root,
        rag_config=rag_config,
        output_archive=archive,
        package_id="profile-local-test",
        release_sequence=1,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    )

    package_root = _extract_archive_safely(archive, tmp_path / "unpacked")
    packaged_config_path = (
        package_root
        / "data"
        / "derived"
        / "rag"
        / "curated"
        / "v2"
        / "profiles"
        / "offline-extended"
        / "rag.yaml"
    )
    packaged_config = yaml.safe_load(packaged_config_path.read_text(encoding="utf-8"))
    packaged_artifact_root = (
        packaged_config_path.parent
        / packaged_config["retrieval"]["artifact_root"]
    ).resolve()
    validation = validate_knowledge_update(package_root, allow_unsigned=True)

    assert report["status"] == "built"
    assert packaged_artifact_root == package_root / source_artifact_root.relative_to(repo_root)
    assert packaged_config["retrieval"]["corpus_paths"] == ["shards/context_only.jsonl"]
    assert packaged_config["retrieval"]["corpus_policy_manifest"] == (
        "profiles/offline-extended/runtime_corpus_policy.json"
    )
    assert validation["status"] == "valid"
    assert validation["corpus_audit"]["configured_corpus_count"] == 1


def test_knowledge_update_packages_and_validates_legacy_repository_root_paths(tmp_path) -> None:  # noqa: ANN001
    repo_root = tmp_path / "repository"
    repo_root.mkdir()
    rag_config, _ = _write_minimal_store(repo_root, profile_local=False)
    archive = tmp_path / "legacy.tar.gz"

    build_knowledge_update(
        repo_root=repo_root,
        rag_config=rag_config,
        output_archive=archive,
        package_id="legacy-root-test",
        release_sequence=1,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
    )

    package_root = _extract_archive_safely(archive, tmp_path / "unpacked")
    packaged_config_path = package_root / "configs" / "rag.yaml"
    packaged_config = yaml.safe_load(packaged_config_path.read_text(encoding="utf-8"))
    packaged_artifact_root = (
        packaged_config_path.parent
        / packaged_config["retrieval"]["artifact_root"]
    ).resolve()
    validation = validate_knowledge_update(package_root, allow_unsigned=True)

    assert packaged_artifact_root == package_root
    assert packaged_config["retrieval"]["corpus_paths"] == ["data/context_only.jsonl"]
    assert packaged_config["retrieval"]["corpus_policy_manifest"] == (
        "data/runtime_corpus_policy.json"
    )
    assert validation["status"] == "valid"


def test_knowledge_update_rejects_artifact_root_outside_repository(tmp_path) -> None:  # noqa: ANN001
    repo_root = tmp_path / "repository"
    rag_config = repo_root / "configs" / "rag.yaml"
    rag_config.parent.mkdir(parents=True)
    rag_config.write_text(
        """retrieval:
  artifact_root: ../../outside
  corpus_paths: []
  graph_paths: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="artifact_root escapes"):
        build_knowledge_update(
            repo_root=repo_root,
            rag_config=rag_config,
            output_archive=tmp_path / "outside.tar.gz",
            package_id="outside-root-test",
            release_sequence=1,
            expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        )
