"""Integrity, privacy and exact lookup contracts for the imagery sidecar."""

import json
import sqlite3
import stat

import pytest

from agronomy_agent.imagery_store import ImageryStore


def _stored(tmp_path):
    store = ImageryStore(tmp_path)
    chip_hash = "a" * 64
    names = {"npz": chip_hash + ".npz", "png": chip_hash + ".png",
             "receipt": chip_hash + ".json"}
    receipt = {"chip_hash": chip_hash, "request_hash": "request", "geometry_hash": "geometry",
               "process_hash": "process", "provider_id": "hls-s30-planetary-computer",
               "source": {"collection": "hls2-s30", "scene_id": "hls2-s30:item", "acquired_at": "2025-01-01T00:00:00Z",
                          "availability_at": None, "asset_ids": {"B02": "id"}},
               "qa": {"valid_area_fraction": 1}, "zonal_stats": {}, "cache_files": names,
               "created_at": "2025-01-01T00:00:00Z"}
    (tmp_path / names["npz"]).write_bytes(b"chip bytes")
    (tmp_path / names["png"]).write_bytes(b"png bytes")
    (tmp_path / names["receipt"]).write_text(json.dumps(receipt))
    store.put(receipt, (-105, 40, -104, 41))
    return store, receipt, names


def test_store_keeps_request_and_scene_identity_with_private_files(tmp_path):
    store, receipt, names = _stored(tmp_path)
    chip_hash = receipt["chip_hash"]
    assert store.get("request", scene_id="hls2-s30:item")["chip_hash"] == chip_hash
    assert store.get_by_chip_hash(chip_hash)["request_hash"] == "request"
    assert store.preview_bytes(chip_hash) == b"png bytes"
    assert store.get_by_chip_hash("../escape") is None
    assert store.get("request", scene_id="hls2-s30:other") is None
    assert store.get("other") is None
    assert store.intersects((-104.5, 40.5, -104.4, 40.6)) == [chip_hash]
    assert store.intersects((0, 0, 1, 1)) == []
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.database.stat().st_mode) == 0o600
    assert all(stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600 for name in names.values())


@pytest.mark.parametrize("kind,mutation", [
    ("png", b"changed png"), ("npz", b"changed npz"),
    ("receipt", b'{"changed":true}'),
])
def test_modified_artifact_is_never_returned(tmp_path, kind, mutation):
    store, receipt, names = _stored(tmp_path)
    (tmp_path / names[kind]).write_bytes(mutation)
    assert store.get("request") is None
    assert store.get_by_chip_hash(receipt["chip_hash"]) is None
    assert store.preview_bytes(receipt["chip_hash"]) is None
    assert store.intersects((-104.5, 40.5, -104.4, 40.6)) == []


def test_receipt_byte_change_rejected_even_when_canonical_json_is_identical(tmp_path):
    store, receipt, names = _stored(tmp_path)
    path = tmp_path / names["receipt"]
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    assert store.get_by_chip_hash(receipt["chip_hash"]) is None
    assert store.preview_bytes(receipt["chip_hash"]) is None


def test_symlink_and_path_escape_rejected(tmp_path):
    store, receipt, names = _stored(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-imagery-test.png"
    outside.write_bytes(b"png bytes")
    path = tmp_path / names["png"]
    path.unlink()
    path.symlink_to(outside)
    assert store.preview_bytes(receipt["chip_hash"]) is None
    assert store.get("request") is None
    assert outside.read_bytes() == b"png bytes"
    with pytest.raises(ValueError):
        store.put({**receipt, "cache_files": {**names, "png": "../escape.png"}}, (-105, 40, -104, 41))
    root_link = tmp_path.parent / "imagery-root-link"
    root_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        ImageryStore(root_link)


def test_incomplete_cache_and_schema_drift(tmp_path):
    store, receipt, names = _stored(tmp_path)
    (tmp_path / names["npz"]).unlink()
    assert store.get("request") is None
    with store._connect() as db:
        db.execute("UPDATE schema_identity SET version=3")
    with pytest.raises(RuntimeError):
        ImageryStore(tmp_path)


def test_read_only_missing_and_empty_index_never_create_or_chmod(tmp_path):
    missing = tmp_path / "missing"
    store = ImageryStore(missing, read_only=True)
    assert store.get("request") is None
    assert store.get_by_chip_hash("a" * 64) is None
    assert store.preview_bytes("a" * 64) is None
    assert store.intersects((-1, -1, 1, 1)) == []
    with pytest.raises(RuntimeError):
        store.put({}, (-1, -1, 1, 1))
    assert not missing.exists()

    empty = tmp_path / "empty"
    empty.mkdir(mode=0o755)
    empty.chmod(0o755)
    index = empty / "imagery-v1.sqlite3"
    index.write_bytes(b"")
    index.chmod(0o644)
    before = (index.stat().st_size, index.stat().st_mtime_ns)
    assert ImageryStore(empty, read_only=True).get("request") is None
    assert (index.stat().st_size, index.stat().st_mtime_ns) == before
    assert stat.S_IMODE(empty.stat().st_mode) == 0o755
    assert stat.S_IMODE(index.stat().st_mode) == 0o644
    assert not (empty / "imagery-v1.sqlite3-wal").exists()
    assert not (empty / "imagery-v1.sqlite3-shm").exists()


def test_read_only_legacy_index_is_unchanged_and_not_attested(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    index = root / "imagery-v1.sqlite3"
    with sqlite3.connect(index) as db:
        db.execute("CREATE TABLE schema_identity(version INTEGER NOT NULL)")
        db.execute("INSERT INTO schema_identity VALUES (1)")
    before = index.read_bytes()
    mtime = index.stat().st_mtime_ns
    store = ImageryStore(root, read_only=True)
    assert store.get("request") is None
    assert store.get_by_chip_hash("a" * 64) is None
    assert index.read_bytes() == before and index.stat().st_mtime_ns == mtime
    assert not (root / "imagery-v1.sqlite3-wal").exists()
    assert not (root / "imagery-v1.sqlite3-shm").exists()


def test_read_only_trusted_v2_reads_without_permission_changes(tmp_path):
    store, receipt, names = _stored(tmp_path)
    tmp_path.chmod(0o755)
    store.database.chmod(0o644)
    for name in names.values():
        (tmp_path / name).chmod(0o644)
    paths = [store.database, *(tmp_path / name for name in names.values())]
    before = [(path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode)) for path in paths]
    reader = ImageryStore(tmp_path, read_only=True)
    assert reader.get("request")["chip_hash"] == receipt["chip_hash"]
    assert reader.get_by_chip_hash(receipt["chip_hash"])["request_hash"] == "request"
    assert reader.preview_bytes(receipt["chip_hash"]) == b"png bytes"
    assert reader.intersects((-104.5, 40.5, -104.4, 40.6)) == [receipt["chip_hash"]]
    assert before == [(path.stat().st_mtime_ns, stat.S_IMODE(path.stat().st_mode)) for path in paths]
    assert not (tmp_path / "imagery-v1.sqlite3-wal").exists()
    assert not (tmp_path / "imagery-v1.sqlite3-shm").exists()


def test_read_only_never_attests_unhashed_v2_row(tmp_path):
    store, receipt, names = _stored(tmp_path)
    with store._connect() as db:
        db.execute("""UPDATE chips SET npz_sha256=NULL,png_sha256=NULL,
                      receipt_sha256=NULL,receipt_file_sha256=NULL""")
    before = store.database.read_bytes()
    mtime = store.database.stat().st_mtime_ns
    reader = ImageryStore(tmp_path, read_only=True)
    assert reader.get("request") is None
    assert reader.get_by_chip_hash(receipt["chip_hash"]) is None
    assert reader.preview_bytes(receipt["chip_hash"]) is None
    assert store.database.read_bytes() == before
    assert store.database.stat().st_mtime_ns == mtime


def test_read_only_rejects_corrupt_and_wal_headers_without_sidecars(tmp_path):
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    bad = corrupt / "imagery-v1.sqlite3"
    bad.write_bytes(b"bad SQLite content")
    with pytest.raises(ValueError, match="header"):
        ImageryStore(corrupt, read_only=True)
    assert bad.read_bytes() == b"bad SQLite content"

    wal_root = tmp_path / "wal"
    wal_root.mkdir()
    wal_index = wal_root / "imagery-v1.sqlite3"
    db = sqlite3.connect(wal_index)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE schema_identity(version INTEGER NOT NULL)")
        db.execute("INSERT INTO schema_identity VALUES (2)")
        db.commit()
    finally:
        db.close()
    sidecars = [wal_root / "imagery-v1.sqlite3-wal", wal_root / "imagery-v1.sqlite3-shm"]
    before = [(path.exists(), path.stat().st_size if path.exists() else None) for path in sidecars]
    with pytest.raises(RuntimeError, match="WAL-mode"):
        ImageryStore(wal_root, read_only=True)
    assert before == [(path.exists(), path.stat().st_size if path.exists() else None) for path in sidecars]
