from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_offline_corpus_successor_retrieval_suite.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_offline_corpus_successor_retrieval_suite", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_successor_suite_includes_admitted_table_and_blocks_spatial_partition(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    master = tmp_path / "canada"
    (master / "shards").mkdir(parents=True)
    source_ids = [source for _case, _question, source in module.CANADIAN_CASES]
    (master / "shards" / "one.jsonl").write_text(
        "".join(json.dumps({"source_id": source}) + "\n" for source in [*source_ids, "on_field_crop_production_current"]), encoding="utf-8"
    )
    (master / "store_manifest.json").write_text(
        json.dumps({"store_sha256": "b" * 64, "shards": [{"path": "shards/one.jsonl"}]}),
        encoding="utf-8",
    )
    store = tmp_path / "store_manifest.json"
    store.write_text(
        json.dumps({"store_sha256": "a" * 64, "mlra_shards": {mlra: ["shards/one.jsonl"] for mlra in ("001X", "002X", "003X", "004A", "005X", "006X", "007X", "008X", "009X", "010X", "011X", "012X")}}),
        encoding="utf-8",
    )
    cases, manifest = module.build_suite(active_store_path=master / "store_manifest.json", us_store_path=store)
    assert manifest["status"] == "frozen_before_retriever_tuning"
    assert manifest["active_case_count"] == 21
    by_id = {case["case_id"]: case for case in cases}
    assert by_id["table_ontario_field_crop_context"]["case_status"] == "active"
    assert by_id["spatial_context_blocked"]["case_status"].startswith("blocked_")
