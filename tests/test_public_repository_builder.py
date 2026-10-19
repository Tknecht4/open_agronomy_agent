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
from scripts.build_public_repository import _contains_literal, _copy_independent, build


ROOT = Path(__file__).resolve().parents[1]


def _tiny_manifest(tmp_path):
    (tmp_path / "source.txt").write_text("synthetic public content\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "open_agronomy_agent.public_repository_manifest.v1",
        "release_id": "synthetic", "paths": ["source.txt"],
    }))
    return manifest


def test_scope_check_creates_no_package_or_source_changes(tmp_path, monkeypatch):
    from scripts import build_public_repository as builder

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    manifest = _tiny_manifest(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    report = builder.check_scope(manifest)
    assert report["status"] == "pass" and report["materialized"] is False
    assert report["file_count"] == 1
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_materialization_verification_retires_only_owned_success(tmp_path, monkeypatch):
    from scripts import build_public_repository as builder

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    manifest = _tiny_manifest(tmp_path)
    unrelated = tmp_path / "outputs/keep-history"
    unrelated.mkdir(parents=True)
    (unrelated / "receipt").write_text("historical")
    path = tmp_path / "receipt.json"
    report = builder.verify(manifest, path)
    assert report["status"] == "pass" and report["stage_state"] == "retired"
    assert not Path(report["stage_path"]).exists()
    assert (unrelated / "receipt").read_text() == "historical"
    assert json.loads(path.read_text()) == report


def test_failed_verification_retains_owned_stage_and_new_receipt(tmp_path, monkeypatch):
    import pytest
    from scripts import build_public_repository as builder

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    manifest = _tiny_manifest(tmp_path)
    original = builder._copy_independent
    def fail_after_copy(source, target):
        original(source, target)
        raise RuntimeError("synthetic interrupted copy")
    monkeypatch.setattr(builder, "_copy_independent", fail_after_copy)
    receipt = tmp_path / "failed.json"
    with pytest.raises(RuntimeError, match="interrupted"):
        builder.verify(manifest, receipt)
    report = json.loads(receipt.read_text())
    assert report["status"] == "failed" and report["stage_state"] == "retained"
    stage = Path(report["stage_path"])
    assert stage.is_relative_to(tmp_path / "outputs/public-repository-verification")
    assert (stage / "source.txt").read_bytes() == (tmp_path / "source.txt").read_bytes()
    with pytest.raises(FileExistsError):
        builder.verify(manifest, receipt)


def test_verification_rejects_corrupted_copy_even_with_self_consistent_receipt(tmp_path, monkeypatch):
    import pytest
    from scripts import build_public_repository as builder

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    manifest = _tiny_manifest(tmp_path)
    original = builder._copy_independent
    def corrupt(source, target):
        original(source, target)
        target.write_bytes(b"altered copied bytes")
    monkeypatch.setattr(builder, "_copy_independent", corrupt)
    receipt = tmp_path / "corrupt.json"
    with pytest.raises(ValueError, match="differs from pinned"):
        builder.verify(manifest, receipt)
    report = json.loads(receipt.read_text())
    assert report["status"] == "failed"
    assert Path(report["stage_path"]).is_dir()
    assert (tmp_path / "source.txt").read_text() == "synthetic public content\n"


def test_public_package_total_budget_accounts_for_many_small_files(tmp_path, monkeypatch):
    import pytest
    from scripts import build_public_repository as builder

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    files = [tmp_path / "first", tmp_path / "second"]
    for path in files:
        path.write_bytes(b"123456")
    with pytest.raises(ValueError, match="total_oversized:12:10"):
        builder._validate_scope(files, {"maximum_total_bytes": 10})


def test_package_copy_has_independent_writes_on_clone_and_fallback(tmp_path, monkeypatch):
    from scripts import build_public_repository as builder
    source = tmp_path / "source"
    source.write_bytes(b"immutable source bytes")
    clone = tmp_path / "clone"
    _copy_independent(source, clone)
    assert clone.read_bytes() == source.read_bytes()
    assert clone.stat().st_ino != source.stat().st_ino
    clone.write_bytes(b"changed destination")
    assert source.read_bytes() == b"immutable source bytes"
    monkeypatch.setattr(builder, "_try_clone", lambda *_: False)
    fallback = tmp_path / "fallback"
    _copy_independent(source, fallback)
    assert fallback.read_bytes() == source.read_bytes()
    source.write_bytes(b"changed source")
    assert fallback.read_bytes() == b"immutable source bytes"


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
    assert "requirements/requirements-benchmark-analysis.txt" in actual
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


def test_nested_requirement_and_architecture_scope_has_no_root_stubs(tmp_path, monkeypatch):
    from scripts import build_public_repository as builder

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    requirements = "requirements/requirements-container.txt"
    architecture = "docs/public/developer/maintainer-architecture.md"
    files = {"requirements.txt": b"base\n", requirements: b"fastapi==0.1\n",
             architecture: b"# Maintainer architecture\n"}
    for name, data in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "open_agronomy_agent.public_repository_manifest.v1",
        "release_id": "synthetic", "paths": ["requirements.txt", requirements],
        "trees": ["docs/public"],
    }))
    report = builder.check_scope(manifest)
    assert report["status"] == "pass" and report["file_count"] == 3
    assert report["materialized"] is False
    receipt = builder.build(tmp_path / "package", manifest)
    assert {row["path"] for row in receipt["files"]} == set(files)
    for name, data in files.items():
        assert (tmp_path / "package" / name).read_bytes() == data
    assert not (tmp_path / "package/ARCHITECTURE.md").exists()
    assert not (tmp_path / "package/requirements-container.txt").exists()


def test_edge_staging_and_sbom_use_the_nested_requirement_input(tmp_path):
    from scripts.stage_edge_build_context import stage
    from scripts.build_runtime_sbom import build_sbom

    containerfile = (ROOT / "Containerfile").read_text()
    relative = "requirements/requirements-container.txt"
    instruction = next(line for line in containerfile.splitlines()
                       if line.startswith("COPY " + relative + " "))
    assert instruction.split()[-1] == "./" + relative
    source = tmp_path / "source"
    path = source / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fastapi==0.1\n")
    (source / "requirements-container.txt").write_bytes(b"wrong-package==0.1\n")
    (source / "Containerfile").write_text(instruction + "\n")
    (source / "container").mkdir()
    (source / "container/runtime_manifest.json").write_text('{}')
    (source / "frontend").mkdir()
    (source / "frontend/package-lock.json").write_text('{"packages":{}}')
    context = tmp_path / "context"
    context.mkdir()
    result = stage(source, context)
    assert result["source_count"] == 1
    assert (context / relative).read_bytes() == path.read_bytes()
    assert not (context / "requirements-container.txt").exists()
    sbom = build_sbom(source)
    assert {item["name"] for item in sbom["packages"][1:]} == {"fastapi"}
    annotation = json.loads(sbom["annotations"][0]["comment"])
    assert relative in {item["path"] for item in annotation["dependency_inputs"]}


def test_edge_frontend_build_helpers_are_staged_and_hash_bound(tmp_path):
    from scripts.stage_edge_build_context import stage, _copy_sources
    from scripts.build_edge_runtime_manifest import CONTROL_PATHS

    containerfile = (ROOT / "Containerfile").read_text()
    frontend_stage = containerfile.split("FROM python:", 1)[0]
    source = tmp_path / "source"
    source.mkdir()
    (source / "Containerfile").write_text(frontend_stage)
    for relative in _copy_sources(frontend_stage):
        original = ROOT / relative
        target = source / relative
        if original.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            (target / "sentinel").write_text("synthetic frontend tree")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
    (source / "container").mkdir()
    (source / "container/runtime_manifest.json").write_text('{}')
    context = tmp_path / "context"
    context.mkdir()
    stage(source, context)
    # Every relative Vite config import must exist in the staged frontend.
    import re
    imports = re.findall(r"from ['\"](\./[^'\"]+)['\"]", (context / "frontend/vite.config.ts").read_text())
    assert imports
    for specifier in imports:
        relative = Path("frontend") / (specifier[2:] + ".ts")
        assert (context / relative).is_file(), f"missing build helper: {relative}"
        assert relative.as_posix() in CONTROL_PATHS, f"unhashed build helper: {relative}"


def test_personal_paths_are_detected_without_rejecting_hardware_or_source_urls():
    from agronomy_agent.publication_privacy import personal_path_lines
    from urllib.parse import quote
    import html
    personal = '/'.join(['', 'Users', 'synthetic-account', 'project', 'receipt.json'])
    for value in [personal, personal.replace('/', '\\/'), html.escape(personal).replace('/', '&#47;'),
                  quote(personal, safe=''), personal.replace('/', '\\u002f'),
                  'C:' + personal.replace('/', '\\\\'),
                  '/'.join(['','home','synthetic-account','project']),
                  '/'.join(['','Volumes','synthetic-volume','project'])]:
        assert personal_path_lines(value.encode()) == [1]
    assert personal_path_lines(('https://example.test/?path=' + quote(personal)).encode()) == [1]
    assert personal_path_lines(b'Apple M4 Max; 16 GB RAM; arm64; 42 tokens/s') == []
    assert personal_path_lines(b'www.example.gov/static/home/pdfs/public-source.pdf') == []
    assert personal_path_lines(b'https://example.gov/home/public/source.pdf') == []


def test_privacy_audit_checks_index_even_when_working_file_is_clean(tmp_path):
    import subprocess
    from scripts.audit_publication_privacy import audit_index
    subprocess.run(['git','init','-q',str(tmp_path)], check=True)
    path = tmp_path/'candidate.json'
    personal = '/'.join(['','Users','synthetic-account','project'])
    path.write_text(json.dumps({'location':personal}))
    subprocess.run(['git','add','candidate.json'],cwd=tmp_path,check=True)
    path.write_text('{"location":"redacted working copy"}')
    report = audit_index(tmp_path, staged=True)
    assert report['status'] == 'fail'
    assert report['findings'] == [{'path':'candidate.json','line':1,'category':'personal_filesystem_path'}]
    assert personal not in json.dumps(report)
    subprocess.run(['git','add','candidate.json'],cwd=tmp_path,check=True)
    assert audit_index(tmp_path, staged=True)['status'] == 'pass'


def test_package_copy_cannot_introduce_personal_path_after_source_validation(tmp_path, monkeypatch):
    import pytest
    from scripts import build_public_repository as builder
    monkeypatch.setattr(builder,'ROOT',tmp_path)
    manifest = _tiny_manifest(tmp_path)
    original = builder._copy_independent
    personal = '/'.join(['','Users','synthetic-account','private'])
    def inject(source,target):
        original(source,target)
        target.write_text(personal)
    monkeypatch.setattr(builder,'_copy_independent',inject)
    with pytest.raises(ValueError,match='personal filesystem paths') as failure:
        builder.build(tmp_path/'package',manifest)
    assert personal not in str(failure.value)
    assert not (tmp_path/'package/PUBLIC_RELEASE_RECEIPT.json').exists()


def test_rendered_docs_reject_paths_but_preserve_benchmark_hardware(tmp_path):
    from scripts.check_public_docs import audit_rendered_site
    personal = '/'.join(['','Users','synthetic-account','private'])
    (tmp_path/'index.html').write_text('<p>' + personal + '</p>')
    errors,_ = audit_rendered_site(tmp_path)
    assert any('personal_path:index.html' in error for error in errors)
    assert personal not in json.dumps(errors)
    (tmp_path/'index.html').write_text('<p>Apple M4 Max, 16 GB, 42 tokens/s</p>')
    errors,_ = audit_rendered_site(tmp_path)
    assert not any('personal_path' in error for error in errors)


def test_privacy_audit_checks_staged_symlink_type_changes(tmp_path):
    import subprocess
    from scripts.audit_publication_privacy import audit_index
    def git(*args):return subprocess.check_output(['git',*args],cwd=tmp_path)
    git('init','-q')
    path=tmp_path/'candidate'
    path.write_text('safe original')
    git('add','candidate')
    git('-c','user.name=Synthetic','-c','user.email=synthetic@example.test','commit','-qm','synthetic fixture')
    path.unlink()
    path.symlink_to('/'.join(['','Users','synthetic-account','private']))
    git('add','candidate')
    assert git('diff','--cached','--name-status').startswith(b'T')
    assert audit_index(tmp_path, staged=True)['status']=='fail'
