"""Integrity, privacy and exact lookup contracts for the imagery sidecar."""

import json
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
