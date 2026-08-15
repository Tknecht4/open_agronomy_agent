from __future__ import annotations

import json
from pathlib import Path

from agronomy_agent.agent import load_agent_resources
from scripts.build_edge_runtime_manifest import build_manifest
from scripts.build_portable_agent_bundle import (
    collect_bundle_files,
    select_curated_store_artifacts,
    select_conference_eval_fixtures,
    select_runtime_geospatial,
    select_runtime_knowledge,
)
from scripts.build_public_repository import _contains_literal, build


ROOT = Path(__file__).resolve().parents[1]


def test_literal_scan_finds_tokens_across_binary_read_blocks(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    user_prefix = "/" + "Users/"
    path.write_bytes(b"x" * (1024 * 1024 - 3) + user_prefix.encode() + b"example/private")

    assert _contains_literal(path, user_prefix) is True
    assert _contains_literal(path, "/" + "Volumes/") is False


def test_public_repository_build_has_no_unreceipted_generated_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1786665600")
    destination = tmp_path / "public-release"

    receipt = build(destination)

    assert receipt["built_at"] == "2026-08-14T00:00:00+00:00"

    receipted = {str(row["path"]) for row in receipt["files"]}
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert actual == receipted | {"PUBLIC_RELEASE_RECEIPT.json"}
    assert not any("__pycache__" in Path(path).parts or path.endswith(".pyc") for path in actual)
    assert not any(part.endswith(".egg-info") for path in actual for part in Path(path).parts)

    historical_curated_files = {
        path.relative_to(ROOT).as_posix()
        for version in ("v1", "v2", "v3", "v4")
        for path in (ROOT / f"data/derived/rag/curated_canada/{version}").rglob("*")
        if path.is_file()
    }
    active_release_files = {
        path.relative_to(ROOT).as_posix()
        for base in (
            ROOT / "data/derived/rag/curated_canada/releases/2026-08-14",
            ROOT / "data/derived/rag/curated_canada/inputs/2026-08-14",
        )
        for path in base.rglob("*")
        if path.is_file()
    }
    required_semantic_companions: set[str] = set()
    for shard in (ROOT / "data/derived/rag/curated_canada/releases/2026-08-14/shards").glob(
        "*.jsonl"
    ):
        for line in shard.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            for value in (
                (row.get("semantic_companion") or {}).get("companion_path"),
                ((row.get("lineage") or {}).get("semantic_companion") or {}).get("path"),
            ):
                if value:
                    required_semantic_companions.add(str(value))
    public_tests = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").glob("*.py")
        if path.is_file()
    }

    assert not historical_curated_files & actual
    assert active_release_files <= actual
    assert required_semantic_companions <= actual
    public_semantic_companions = {
        path
        for path in actual
        if path.startswith("data/curated/canada_agronomy/")
        and path.endswith(".semantic.json")
    }
    assert public_semantic_companions == required_semantic_companions
    assert public_tests <= actual
    assert "configs/runtime_profiles.json" in actual
    assert "configs/rag_governed_runtime_v2.yaml" in actual
    assert "requirements-benchmark-analysis.txt" in actual
    assert "tests/test_rc3_checkpoint_analysis.py" in actual
    checkpoint_prefix = "docs/public/development-benchmark-rc3-20260815/"
    assert {
        checkpoint_prefix + "README.md",
        checkpoint_prefix + "paper.pdf",
        checkpoint_prefix + "scripts/analyze_rc3_checkpoint.py",
        checkpoint_prefix + "source_data/public_safe_response_measurements.csv",
    } <= actual
    assert "configs/eval.yaml" not in actual
    assert "configs/full_system_benchmark_matrix_v1.json" not in actual
    assert "scripts/run_full_system_model_matrix.py" not in actual
    assert "scripts/analyze_full_system_model_matrix.py" not in actual
    assert "scripts/analyze_open_agronomy_internal_comparison.py" not in actual
    assert not any(path.startswith("configs/rag_canada_v") for path in actual)
    assert not any(
        path.startswith("data/raw/") and not path.endswith(".lineage.json")
        for path in actual
    )


def test_public_rehearsal_receipt_is_nonclaim_and_content_only() -> None:
    path = (
        ROOT
        / "docs/reviews/artifacts/gemma3-270m-observed-system-rehearsal-nonclaim-20260814.json"
    )
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert receipt["result_class"] == "observed_system_execution_nonclaim"
    assert receipt["claim_eligible"] is False
    assert receipt["diagnostic_status"] == "exposed_internal_rehearsal"
    assert receipt["source_receipt"]["sha256"] == (
        "d59e7cf66e403810e9b00035e924cee870824fb370b001014873bc3f7b80ca04"
    )
    assert receipt["source_receipt"]["bytes"] == 275147
    assert receipt["source_receipt"]["full_receipt_distribution"] == "not_in_public_repository"
    assert receipt["source_receipt"]["retained_projection"] is True

    topology = receipt["stage_topology"]
    assert topology["topology_version"] == "open_agronomy_agent.production_stage_topology.v3"
    assert topology["stage_count"] == 17
    assert [row["position"] for row in topology["ordered_receipts"]] == list(range(17))
    assert len({row["stage_id"] for row in topology["ordered_receipts"]}) == 17
    assert topology["ordered_receipts"][-1]["stage_id"] == "fallback_origin"

    lineage = receipt["answer_lineage"]
    assert lineage["origin_class"] == "verifier_conservative_fallback"
    assert lineage["fallback_used"] is True
    assert lineage["verification_action"] == "conservative_fallback"
    assert lineage["post_verification_sha256"] == lineage["final_sha256"]
    assert lineage["draft_sha256"] != lineage["final_sha256"]

    serialized = path.read_text(encoding="utf-8").lower()
    for prohibited in (
        '"prompt"',
        '"draft_text"',
        '"final_answer"',
        '"retrieved_content"',
        '"field_context"',
        '"tool_payload"',
        '"session_id"',
        '"local_path"',
        "/private/tmp/",
        "/users/",
    ):
        assert prohibited not in serialized


def test_curated_profile_and_spatial_contract_are_explicit_portable_inputs() -> None:
    release_root = ROOT / "data/derived/rag/curated_canada/releases/2026-08-14"
    master_config = release_root / "profiles/canada-offline-master/rag.yaml"

    master = select_runtime_knowledge(ROOT, master_config)
    geospatial = select_runtime_geospatial(ROOT)

    assert len(master.included_corpus_paths) == 2
    assert all(path.is_file() for path in master.included_corpus_paths)
    assert geospatial.profile_ids == (
        "canada-context-boundaries-v1",
        "prairie-dss-v1",
    )
    assert geospatial.layer_ids == ()
    assert all(path.suffix != ".sqlite3" for path in geospatial.included_paths)

    curated_artifacts = select_curated_store_artifacts(ROOT, master_config)
    assert {
        path.relative_to(ROOT).as_posix() for path in curated_artifacts
    } == {
        path.relative_to(ROOT).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
    }

    loaded_master = load_agent_resources(master_config)
    store_manifest = json.loads((release_root / "store_manifest.json").read_text(encoding="utf-8"))
    assert len(loaded_master.retriever.docs) == store_manifest["totals"]["rows"]
    assert len(loaded_master.graph.nodes) == 0

    public_manifest = json.loads((ROOT / "configs/public_repository_manifest.json").read_text(encoding="utf-8"))
    assert public_manifest["maximum_prefix_bytes"]["data/derived/rag/curated_canada/releases/2026-08-14/"] >= sum(
        path.stat().st_size
        for path in release_root.rglob("*")
        if path.is_file()
    )

    runtime_manifest = build_manifest(
        ROOT,
        rag_config=master_config.relative_to(ROOT),
    )
    assert runtime_manifest["rag_config"] == master_config.relative_to(ROOT).as_posix()
    assert runtime_manifest["included_corpus_count"] == 2
    assert runtime_manifest["bundled_geo_layers"]["content_class"] == "lineage_manifests_only"
    assert runtime_manifest["bundled_geo_layers"]["runtime_layer_assets_included"] is False
    assert runtime_manifest["corpus_policy_manifest"].endswith(
        "profiles/canada-offline-master/runtime_corpus_policy.json"
    )
    assert {
        entry["path"] for entry in runtime_manifest["runtime_knowledge"]
    } == {path.relative_to(ROOT).as_posix() for path in master.included_corpus_paths}

    conference_fixtures, fixture_status = select_conference_eval_fixtures(ROOT, required=False)
    if fixture_status["complete"]:
        assert len(conference_fixtures) == fixture_status["file_count"]
    else:
        assert conference_fixtures == ()
        assert fixture_status["missing"]
    bundle_files = collect_bundle_files(
        ROOT,
        master_config,
        conference_eval_paths=conference_fixtures,
    )
    assert {
        path.relative_to(ROOT).as_posix() for path in curated_artifacts
    } <= {path.relative_to(ROOT).as_posix() for path in bundle_files}
