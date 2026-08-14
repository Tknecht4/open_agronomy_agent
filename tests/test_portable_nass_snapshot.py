from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_portable_nass_snapshot.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_portable_nass_snapshot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_portable_path_hint_is_repository_relative() -> None:
    module = _module()

    assert module._portable_path_hint(
        ROOT / "data/snapshots/nass_quickstats_state_crop_stats.jsonl"
    ) == "data/snapshots/nass_quickstats_state_crop_stats.jsonl"


def test_portable_path_hint_does_not_expose_external_parent(tmp_path: Path) -> None:
    module = _module()

    assert module._portable_path_hint(tmp_path / "snapshot.jsonl") == "snapshot.jsonl"


def test_committed_snapshot_manifest_is_portable_and_hash_bound() -> None:
    snapshot = ROOT / "data/snapshots/nass_quickstats_state_crop_stats.jsonl"
    manifest = json.loads(
        (
            ROOT / "data/snapshots/nass_quickstats_state_crop_stats_manifest.json"
        ).read_text(encoding="utf-8")
    )
    with snapshot.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()

    assert manifest["output"] == snapshot.relative_to(ROOT).as_posix()
    assert not Path(manifest["output"]).is_absolute()
    assert manifest["sha256"] == digest
    assert manifest["row_count"] == 66_204
