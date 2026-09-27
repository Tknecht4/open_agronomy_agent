"""Capacity refuses new work; it never removes sources or blocks cached reads."""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from agronomy_agent import imagery_analytics as analytics
from agronomy_agent import imagery_budget as budget
from agronomy_agent.imagery_store import ImageryStore

GEOMETRY = {"type": "Polygon", "coordinates": [[[-103.15, 40.15], [-103.14, 40.15],
    [-103.14, 40.16], [-103.15, 40.15]]]}
PROVIDER = "hls-s30-planetary-computer"


def test_capacity_and_free_space_refuse_before_egress(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "_analyze_scene_admitted", lambda *a, **k: pytest.fail("must not launch processing"))
    result = analytics.analyze_scene(GEOMETRY, PROVIDER, cache_root=tmp_path / "cache",
        network_mode="online", start_date="2021-06-01", end_date="2021-06-15", max_cache_bytes=1024)
    assert result["status"] == "storage_limit"
    assert result["reason"] == "imagery_cache_capacity_reached"
    monkeypatch.setattr(budget.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    result = analytics.analyze_scene(GEOMETRY, PROVIDER, cache_root=tmp_path / "new-cache",
        network_mode="online", start_date="2021-06-01", end_date="2021-06-15")
    assert result["reason"] == "free_disk_reserve_reached"
    assert not (tmp_path / "new-cache").exists()


def test_shared_writer_lock_and_failed_job_release(tmp_path):
    root = tmp_path / "cache"
    with pytest.raises(RuntimeError, match="worker failure"):
        with budget.reserve_cache(root, min_free_bytes=0):
            with pytest.raises(budget.StorageRefusal) as exc:
                with budget.reserve_cache(root, min_free_bytes=0):
                    pass
            assert exc.value.status == "busy"
            raise RuntimeError("worker failure")
    with budget.reserve_cache(root, min_free_bytes=0):
        pass


def test_final_write_recheck_and_symlink_rejection(tmp_path):
    root = tmp_path / "cache"
    with budget.reserve_cache(root, min_free_bytes=0, max_cache_bytes=budget.MAX_NEW_CHIP_BYTES + 100) as admission:
        (root / "another-writer.bin").write_bytes(b"x" * 101)
        with pytest.raises(budget.StorageRefusal, match="capacity"):
            admission.ensure()
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    (root / "link").symlink_to(outside)
    with pytest.raises(budget.StorageRefusal):
        budget.cache_bytes(root)
    assert outside.read_bytes() == b"keep"


def test_verified_cache_hit_ignores_admission_limits(tmp_path, monkeypatch):
    _, bounds, geometry_hash, request_hash = analytics._request_identity(
        GEOMETRY, PROVIDER, None, "2021-06-01", "2021-06-15", 0, None)
    root = tmp_path / "cache"
    store = ImageryStore(root)
    chip = "a" * 64
    names = {"npz": chip + ".npz", "png": chip + ".png", "receipt": chip + ".json"}
    receipt = {"status": "available", "chip_hash": chip, "request_hash": request_hash,
        "geometry_hash": geometry_hash, "process_hash": "b" * 64, "provider_id": PROVIDER,
        "source": {"collection": "hls2-s30", "scene_id": "hls2-s30:fixture", "asset_ids": {}},
        "qa": {}, "zonal_stats": {}, "cache_files": names, "created_at": "2021-06-01"}
    (root / names["npz"]).write_bytes(b"fixture")
    (root / names["png"]).write_bytes(b"fixture")
    (root / names["receipt"]).write_text(json.dumps(receipt))
    store.put(receipt, bounds)
    monkeypatch.setattr(budget.shutil, "disk_usage", lambda _: pytest.fail("cached read must not need free space"))
    result = analytics.analyze_scene(GEOMETRY, PROVIDER, cache_root=root,
        network_mode="online", start_date="2021-06-01", end_date="2021-06-15", max_cache_bytes=1)
    assert result["cache_hit"] and result["chip_hash"] == chip


def test_budget_scope_cannot_escape_cache_parent(tmp_path):
    with pytest.raises(ValueError, match="budget root"):
        analytics.analyze_scene(GEOMETRY, PROVIDER, cache_root=tmp_path / "cache",
            budget_root=tmp_path / "unrelated", start_date="2021-06-01", end_date="2021-06-15")
    for value in [0, -1, True, 3.5]:
        with pytest.raises(ValueError):
            budget.validate_policy(value, 0)


def test_corrupt_index_fails_closed_without_processing(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    (root / "imagery-v1.sqlite3").write_bytes(b"not a database")
    monkeypatch.setattr(analytics, "_analyze_scene_admitted", lambda *a, **k: pytest.fail("corrupt cache must not trigger egress"))
    result = analytics.analyze_scene(GEOMETRY, PROVIDER, cache_root=root, network_mode="online",
        start_date="2021-06-01", end_date="2021-06-15")
    assert result["status"] == "storage_unavailable"
