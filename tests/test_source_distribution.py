"""Bounded split-package reconstruction, including hostile archive fixtures."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts import build_source_distribution as split


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture(tmp_path: Path, monkeypatch) -> tuple[Path, str, dict]:
    from scripts import build_public_repository as public

    files = {
        "README.md": b"source instructions\n",
        "scripts/run.sh": b"#!/bin/sh\necho ready\n",
        "configs/public_repository_manifest.json": b"{}",
        "data/derived/rag/context.jsonl": b'{"evidence":"retained"}\n',
        "docs/reviews/artifacts/probe.json": b'{"status":"failed"}\n',
    }

    def fake_public_build(destination: Path, _manifest: Path) -> dict:
        rows = []
        for name, value in files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
            if name == "scripts/run.sh":
                path.chmod(0o755)
            rows.append({"path": name, "bytes": len(value), "sha256": _sha(value)})
        receipt = {"schema_version": "open_agronomy_agent.public_repository_receipt.v1",
                   "files": rows, "file_count": len(rows),
                   "total_bytes": sum(len(value) for value in files.values()),
                   "manifest_path": "configs/public_repository_manifest.json",
                   "manifest_sha256": _sha(b"{}")}
        receipt_bytes = (json.dumps(receipt, sort_keys=True) + "\n").encode()
        (destination / "PUBLIC_RELEASE_RECEIPT.json").write_bytes(receipt_bytes)
        receipt["receipt_sha256"] = _sha(receipt_bytes)
        return receipt

    monkeypatch.setattr(public, "build", fake_public_build)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    distribution = tmp_path / "distribution"
    result = split.build(distribution, manifest)
    plan = json.loads((distribution / split.PLAN_NAME).read_text())
    return distribution, result["plan_sha256"], plan


def _rewrite_archive(distribution: Path, plan: dict, pack: str,
                     members: list[tuple[str, bytes, bytes | None]]) -> str:
    """Each member is (name, data, optional tar type)."""
    archive_path = distribution / split.ARCHIVES[pack]
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name, data, member_type in members:
                    info = tarfile.TarInfo(name)
                    info.type = member_type or tarfile.REGTYPE
                    info.size = len(data) if info.isfile() else 0
                    if member_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                        info.linkname = "README.md"
                    archive.addfile(info, io.BytesIO(data) if info.isfile() else None)
    plan["archives"][pack] = {"file": archive_path.name,
                              "bytes": archive_path.stat().st_size,
                              "sha256": split._hash_file(archive_path)}
    plan_path = distribution / split.PLAN_NAME
    plan_path.write_text(json.dumps(plan, sort_keys=True, indent=2) + "\n")
    return split._hash_file(plan_path)


def test_round_trip_is_deterministic_and_preserves_evidence(tmp_path, monkeypatch):
    first, digest, plan = _fixture(tmp_path, monkeypatch)
    second_root = tmp_path / "second"
    second_root.mkdir()
    second, other_digest, _ = _fixture(second_root, monkeypatch)
    assert digest == other_digest
    assert split._hash_file(first / "source.tar.gz") == split._hash_file(second / "source.tar.gz")
    assert plan["total_bytes"] > 0
    with tarfile.open(first / "source.tar.gz", "r:gz") as archive:
        assert not any(member.name.startswith("data/") for member in archive)
    restored = tmp_path / "restored"
    result = split.reconstruct(first, restored, digest)
    assert result["file_count"] == 6
    assert (restored / "scripts/run.sh").stat().st_mode & 0o111
    assert (restored / "data/derived/rag/context.jsonl").read_bytes() == b'{"evidence":"retained"}\n'
    assert (restored / "docs/reviews/artifacts/probe.json").read_bytes() == b'{"status":"failed"}\n'


def test_plan_digest_and_archive_inventory_are_independent_inputs(tmp_path, monkeypatch):
    distribution, digest, _ = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="plan digest"):
        split.reconstruct(distribution, tmp_path / "wrong", "0" * 64)
    (distribution / "evidence.tar.gz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="archive hash or size"):
        split.reconstruct(distribution, tmp_path / "corrupt", digest)
    assert not (tmp_path / "corrupt").exists()


def test_member_hash_and_extra_distribution_file_are_rejected(tmp_path, monkeypatch):
    distribution, digest, plan = _fixture(tmp_path, monkeypatch)
    (distribution / "extra.txt").write_text("unexpected")
    with pytest.raises(ValueError, match="unexpected or missing distribution files"):
        split.verify(distribution, digest)
    (distribution / "extra.txt").unlink()
    digest = _rewrite_archive(distribution, plan, "source", [("README.md", b"alterd instructions\n", None)])
    with pytest.raises(ValueError, match="member hash mismatch"):
        split.verify(distribution, digest)


def test_verify_only_does_not_materialize_corpus(tmp_path, monkeypatch):
    distribution, digest, _ = _fixture(tmp_path, monkeypatch)
    result = split.verify(distribution, digest)
    assert result["verified_only"] is True
    assert result["destination"] is None
    assert not any(path.name.startswith("reconstruct-") for path in tmp_path.iterdir())


@pytest.mark.parametrize("bad_name,bad_type", [
    ("../escape", None), ("/absolute", None), ("README.md", tarfile.SYMTYPE),
    ("README.md", tarfile.LNKTYPE), ("surprise.txt", None),
])
def test_reconstruct_rejects_unsafe_or_unexpected_members(tmp_path, monkeypatch, bad_name, bad_type):
    distribution, _, plan = _fixture(tmp_path, monkeypatch)
    digest = _rewrite_archive(distribution, plan, "source", [(bad_name, b"x", bad_type)])
    with pytest.raises(ValueError):
        split.reconstruct(distribution, tmp_path / "restored", digest)
    assert not (tmp_path / "restored").exists()


def test_reconstruct_rejects_duplicate_and_oversized_members(tmp_path, monkeypatch):
    distribution, _, plan = _fixture(tmp_path, monkeypatch)
    digest = _rewrite_archive(distribution, plan, "source", [
        ("README.md", b"source instructions\n", None),
        ("README.md", b"source instructions\n", None),
    ])
    with pytest.raises(ValueError, match="duplicate"):
        split.reconstruct(distribution, tmp_path / "duplicate", digest)
    digest = _rewrite_archive(distribution, plan, "source", [("README.md", b"x" * 10000, None)])
    with pytest.raises(ValueError, match="unsafe archive member"):
        split.reconstruct(distribution, tmp_path / "oversized", digest)


def test_reconstruct_rejects_missing_member_and_overwrite(tmp_path, monkeypatch):
    distribution, _, plan = _fixture(tmp_path, monkeypatch)
    digest = _rewrite_archive(distribution, plan, "evidence", [])
    with pytest.raises(ValueError, match="missing archive members"):
        split.reconstruct(distribution, tmp_path / "missing", digest)
    destination = tmp_path / "occupied"
    destination.mkdir()
    with pytest.raises(FileExistsError, match="must be new"):
        split.reconstruct(distribution, destination, digest)
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "absent")
    with pytest.raises(FileExistsError, match="must be new"):
        split.reconstruct(distribution, dangling, digest)


def test_plan_budgets_and_path_collisions(tmp_path, monkeypatch):
    distribution, _, plan = _fixture(tmp_path, monkeypatch)
    plan["files"][0]["bytes"] = split.MAX_TOTAL_BYTES + 1
    plan["total_bytes"] = sum(row["bytes"] for row in plan["files"])
    with pytest.raises(ValueError, match="size bound"):
        split._validate_plan(plan)
    plan["files"][0]["bytes"] = 1
    plan["files"].append(dict(plan["files"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        split._validate_plan(plan)


def test_failed_build_retains_failure_receipt(tmp_path, monkeypatch):
    from scripts import build_public_repository as public

    def fail(_destination, _manifest):
        raise RuntimeError("synthetic interrupted build")

    monkeypatch.setattr(public, "build", fail)
    destination = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="interrupted"):
        split.build(destination, tmp_path / "manifest.json")
    assert json.loads((destination / "BUILD_FAILED.json").read_text())["status"] == "failed"
    assert not (destination / split.PLAN_NAME).exists()


def test_build_refuses_existing_destination(tmp_path, monkeypatch):
    distribution, _, _ = _fixture(tmp_path, monkeypatch)
    with pytest.raises(FileExistsError, match="must be new"):
        split.build(distribution, tmp_path / "manifest.json")
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "absent")
    with pytest.raises(FileExistsError, match="must be new"):
        split.build(dangling, tmp_path / "manifest.json")


def test_bounded_gzip_reader_stops_expansion(tmp_path):
    compressed = tmp_path / "bomb.gz"
    with gzip.open(compressed, "wb") as stream:
        stream.write(b"z" * 200_000)
    with gzip.open(compressed, "rb") as stream:
        bounded = split._BoundedReader(stream, 1000)
        with pytest.raises(ValueError, match="decompressed byte bound"):
            bounded.read(200_000)
