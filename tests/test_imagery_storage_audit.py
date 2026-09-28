"""Bounded, read-only and path-free storage inventory contracts."""

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from scripts.audit_imagery_storage import _hash_file, audit_roots, parse_root


def _chip(root: Path, marker: str, scene: str) -> int:
    chip_hash = marker * 64
    path = root / (chip_hash + ".npz")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bands.npy", b"same source pixels" * 100)
        archive.writestr("fmask.npy", b"same source mask" * 100)
        archive.writestr("field_weights.npy", marker.encode() * 100)
    receipt = {"chip_hash": chip_hash, "source": {"scene_id": scene}, "geometry_hash": marker * 64,
               "grid": {"width": 224, "height": 224},
               "cache_files": {"npz": path.name}, "cog_transfer_bytes": 512}
    (root / (chip_hash + ".json")).write_text(json.dumps(receipt))
    return path.stat().st_size


def test_inventory_reports_exact_duplicates_and_context_projection_without_paths(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    chip_size = _chip(first, "a", "scene-one")
    _chip(second, "b", "scene-one")
    (first / "duplicate.bin").write_bytes(b"same")
    (second / "duplicate.bin").write_bytes(b"same")
    (first / "escape").symlink_to(second, target_is_directory=True)
    result = audit_roots([("first", first), ("second", second)], verify_duplicates=True,
                         max_hash_bytes=10_000_000)
    assert result["status"] == "complete"
    assert result["aggregate"]["distinct_scene_ids_in_receipts"] == 1
    assert result["aggregate"]["distinct_geometry_hashes_in_receipts"] == 2
    assert result["aggregate"]["recorded_cog_transfer_bytes_sum"] == 1024
    assert result["roots"]["first"]["symlinks_skipped"] == 1
    assert result["duplicates"]["exact_duplicate_file_groups"] >= 1
    assert result["duplicates"]["redundant_logical_file_bytes"] >= 4
    assert result["duplicates"]["exact_duplicate_member_groups"] >= 2
    assert result["projection"]["median_compressed_chip_bytes"] == chip_size
    assert result["projection"]["same_context_reuse_scenarios"]["100"]["one_context_per_field_season_bytes"] == 400 * chip_size
    output = json.dumps(result)
    assert str(tmp_path) not in output
    assert "scene-one" not in output
    assert "duplicate.bin" not in output


def test_scan_and_hash_caps_preserve_incomplete_status(tmp_path):
    for index in range(5):
        (tmp_path / f"file-{index}.bin").write_bytes(b"12345")
    capped = audit_roots([("bounded", tmp_path)], max_files=2)
    assert capped["status"] == "incomplete"
    assert "file_limit" in capped["incomplete_reasons"]
    assert capped["aggregate"]["files"] == 2
    hash_capped = audit_roots([("bounded", tmp_path)], verify_duplicates=True,
                              max_hash_bytes=5)
    assert hash_capped["duplicates"]["status"] == "hash_byte_limit"
    assert hash_capped["status"] == "incomplete"
    assert hash_capped["duplicates"]["hashed_files"] == 1
    assert hash_capped["duplicates"]["exact_duplicate_file_groups"] == 0


def test_rejects_root_symlink_and_unsafe_label(tmp_path):
    link = tmp_path.parent / f"{tmp_path.name}-audit-link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        parse_root("private=" + str(link))
    with pytest.raises(ValueError):
        parse_root("../unsafe=" + str(tmp_path))
    with pytest.raises(ValueError):
        parse_root("relative=not/absolute")


def test_allocated_bytes_are_reported_separately_from_logical(tmp_path):
    (tmp_path / "sparse.bin").write_bytes(b"x" * 9)
    result = audit_roots([("small", tmp_path)])
    assert result["aggregate"]["logical_bytes"] == 9
    assert result["aggregate"]["allocated_bytes_sum_st_blocks"] >= 0
    assert "APFS" in result["aggregate"]["allocated_note"]


def test_receipt_cannot_escape_root_for_context_size(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.npz"
    outside.write_bytes(b"outside payload")
    chip_hash = "c" * 64
    (root / (chip_hash + ".json")).write_text(json.dumps({
        "chip_hash": chip_hash, "source": {"scene_id": "private-scene"},
        "geometry_hash": "d" * 64, "grid": {"width": 224, "height": 224},
        "cache_files": {"npz": "../outside.npz"}, "cog_transfer_bytes": 100,
    }))
    result = audit_roots([("safe", root)])
    assert result["status"] == "incomplete"
    assert result["aggregate"]["invalid_chip_receipts"] == 1
    assert result["aggregate"]["receipts_with_unknown_cog_transfer"] == 1
    assert result["aggregate"]["recorded_cog_transfer_bytes_sum"] == 0
    assert result["projection"]["measured_224_context_samples"] == 0
    assert "private-scene" not in json.dumps(result)


def test_hash_reopens_without_following_symlink_and_checks_size(tmp_path):
    target = tmp_path / "target.bin"
    target.write_bytes(b"private")
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        _hash_file(link, 7, 100)
    with pytest.raises(ValueError):
        _hash_file(target, 6, 100)


def test_oversized_npz_member_directory_is_incomplete(tmp_path):
    path = tmp_path / ("e" * 64 + ".npz")
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(33):
            archive.writestr(f"member-{index}", b"x")
    result = audit_roots([("bounded", tmp_path)])
    assert result["status"] == "incomplete"
    assert result["aggregate"]["invalid_npz"] == 1


def test_rejects_duplicate_and_ancestor_overlapping_roots(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    with pytest.raises(ValueError, match="overlapping"):
        audit_roots([("one", tmp_path), ("same", child / "..")], verify_duplicates=True)
    with pytest.raises(ValueError, match="overlapping"):
        audit_roots([("one", tmp_path), ("nested", child)])


def test_cli_refuses_dotdot_output_alias_and_existing_destination(tmp_path):
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    existing = root / "existing.json"
    existing.write_bytes(b"original source")
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_imagery_storage.py"
    aliased = subprocess.run([sys.executable, str(script), "--root", f"example={child / '..'}",
                              "--output", str(existing)], capture_output=True, text=True)
    assert aliased.returncode != 0
    assert existing.read_bytes() == b"original source"
    outside = tmp_path / "prior-audit.json"
    outside.write_bytes(b"historical audit")
    separate = subprocess.run([sys.executable, str(script), "--root", f"example={root}",
                               "--output", str(outside)], capture_output=True, text=True)
    assert separate.returncode != 0
    assert outside.read_bytes() == b"historical audit"
    overlap = subprocess.run([sys.executable, str(script), "--root", f"one={root}",
                              "--root", f"same={child / '..'}"], capture_output=True, text=True)
    assert overlap.returncode != 0
