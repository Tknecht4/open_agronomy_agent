"""A project wording change cannot silently alter the admitted external store."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("active_corpus_builder", ROOT / "scripts/build_active_offline_corpus.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
PREVIOUS = ROOT / "data/derived/rag/offline_agronomy/active"


@pytest.fixture
def seed(tmp_path, monkeypatch):
    path = tmp_path / "source" / builder.PROJECT_CONTEXT_SOURCE
    path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / builder.PROJECT_CONTEXT_SOURCE, path)
    monkeypatch.setattr(builder, "ROOT", tmp_path / "source")
    return path


def test_project_refresh_preserves_every_external_byte_and_source_receipt(tmp_path, seed):
    before = json.loads((PREVIOUS / "store_manifest.json").read_text())
    output = tmp_path / "refreshed"
    result = builder.refresh_project_context(previous=PREVIOUS, output=output)
    assert result["row_count"] == before["row_count"] == 3086
    for item in before["shards"]:
        if not Path(item["path"]).name.startswith("project_context-"):
            assert (output / item["path"]).read_bytes() == (PREVIOUS / item["path"]).read_bytes()
    for key in ("source_receipt_path", "exact_duplicate_clusters_path"):
        assert (output / before[key]).read_bytes() == (PREVIOUS / before[key]).read_bytes()
    records = [json.loads(line) for line in (output / "shards/project_context-0001.jsonl").read_text().splitlines()]
    assert all(row["raw_sha256"] == builder._sha256(seed) for row in records)
    assert all(row["retrieval_policy"] == "context_only" for row in records)
    # A second refresh of the same seed must be byte-identical, including ledger.
    again = tmp_path / "again"
    assert builder.refresh_project_context(previous=output, output=again) == result
    assert {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()} == {
        p.relative_to(again): p.read_bytes() for p in again.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("change", ["remove_id", "duplicate_text", "external_collision"])
def test_membership_and_duplicate_changes_need_full_rebuild(tmp_path, seed, change):
    rows = [json.loads(line) for line in seed.read_text().splitlines()]
    if change == "remove_id":
        rows.pop()
    elif change == "duplicate_text":
        rows[0]["text"] = rows[1]["text"]
    else:
        external = json.loads((PREVIOUS / "shards/canadian_context-0001.jsonl").read_text().splitlines()[0])
        rows[0]["text"] = external["text"]
    seed.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    output = tmp_path / "rejected"
    with pytest.raises(ValueError, match="full rebuild"):
        builder.refresh_project_context(previous=PREVIOUS, output=output)
    assert not output.exists()


def test_refresh_rejects_corrupt_prior_member_before_creating_output(tmp_path, seed):
    previous = tmp_path / "previous"
    shutil.copytree(PREVIOUS, previous)
    (previous / "source_receipt.json").write_text("{}\n")
    with pytest.raises(ValueError, match="member mismatch"):
        builder.refresh_project_context(previous=previous, output=tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_refresh_never_overwrites_a_release(seed):
    with pytest.raises(ValueError, match="separate output"):
        builder.refresh_project_context(previous=PREVIOUS, output=PREVIOUS)


@pytest.mark.parametrize("change", ["parent_alias", "absolute", "duplicate", "dot_alias"])
def test_hash_consistent_manifest_cannot_escape_or_alias_output(tmp_path, seed, change):
    previous = tmp_path / "previous"
    shutil.copytree(PREVIOUS, previous)
    manifest = json.loads((previous / "store_manifest.json").read_text())
    first = manifest["shards"][0]
    if change == "parent_alias":
        first["path"] = "../previous/" + first["path"]
    elif change == "absolute":
        first["path"] = str(previous / first["path"])
    elif change == "dot_alias":
        first["path"] = "./" + first["path"]
    else:
        manifest["source_receipt_path"] = first["path"]
        manifest["source_receipt_sha256"] = first["sha256"]
    manifest.pop("store_sha256")
    manifest["store_sha256"] = builder.sha256_text(builder.canonical_json(manifest))
    (previous / "store_manifest.json").write_text(json.dumps(manifest))
    original = {p.relative_to(previous): p.read_bytes() for p in previous.rglob("*") if p.is_file()}
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="member path"):
        builder.refresh_project_context(previous=previous, output=output)
    assert not output.exists()
    assert original == {p.relative_to(previous): p.read_bytes() for p in previous.rglob("*") if p.is_file()}
