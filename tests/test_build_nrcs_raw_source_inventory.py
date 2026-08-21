from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_nrcs_raw_source_inventory.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_nrcs_raw_source_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_raw_inventory_selects_only_hash_bound_nrcs_json(tmp_path: Path) -> None:
    archive = {
        "inventory_sha256": "a" * 64,
        "files": [
            {"path": "data/raw/documents/nrcs_esd_json/001X/site.json", "sha256": "b" * 64, "bytes": 1},
            {"path": "data/raw/documents/nrcs_esd_json/001X/._site.json", "sha256": "c" * 64, "bytes": 1},
            {"path": "data/derived/rag/nrcs.jsonl", "sha256": "d" * 64, "bytes": 1},
        ],
    }
    path = tmp_path / "archive.json"
    path.write_text(json.dumps(archive), encoding="utf-8")
    payload = _module().build_raw_inventory(path)
    assert payload["files"] == [
        {"path": "data/raw/documents/nrcs_esd_json/001X/site.json", "sha256": "b" * 64, "bytes": 1}
    ]
    assert len(str(payload["inventory_sha256"])) == 64
