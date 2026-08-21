from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from agronomy_agent.corpus_release import canonical_json, sha256_bytes


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_historical_archive_admission_register.py"


def _module():
    spec = importlib.util.spec_from_file_location("historical_archive_admission_register", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_admission_register_binds_raw_inventory_store_and_historical_proxy(tmp_path: Path) -> None:
    archive = {"inventory_sha256": "a" * 64, "archive_git_revision": "archive-rev"}
    raw = {"inventory_sha256": "b" * 64, "source_archive_inventory_sha256": "a" * 64}
    catalog = {"catalog_sha256": "c" * 64, "archive_git_revision": "archive-rev"}
    store = {"store_sha256": "d" * 64, "raw_inventory_sha256": "b" * 64, "rows": 12}
    paths = {name: tmp_path / f"{name}.json" for name in ("archive", "raw", "catalog", "store")}
    for name, payload in (("archive", archive), ("raw", raw), ("catalog", catalog), ("store", store)):
        _write(paths[name], payload)
    module = _module()
    module.ROOT = tmp_path
    report = module.build_register(
        archive_inventory=paths["archive"],
        raw_nrcs_inventory=paths["raw"],
        evaluation_catalog=paths["catalog"],
        us_store=paths["store"],
    )
    by_family = {item["source_family"]: item for item in report["records"]}
    assert by_family["usda_nrcs_ecological_site_json"]["status"] == "admitted"
    assert by_family["historical_aiagribench_style_proxy"]["status"] == "candidate"
    assert "RC3 pooling" in by_family["historical_aiagribench_style_proxy"]["prohibitions"]
    unsigned = dict(report)
    assert unsigned.pop("register_sha256")
    assert report["register_sha256"] == sha256_bytes(canonical_json(unsigned).encode("utf-8"))


def test_admission_register_rejects_broken_archive_lineage(tmp_path: Path) -> None:
    paths = {name: tmp_path / f"{name}.json" for name in ("archive", "raw", "catalog", "store")}
    _write(paths["archive"], {"inventory_sha256": "a" * 64, "archive_git_revision": "archive-rev"})
    _write(paths["raw"], {"inventory_sha256": "b" * 64, "source_archive_inventory_sha256": "wrong"})
    _write(paths["catalog"], {"catalog_sha256": "c" * 64, "archive_git_revision": "archive-rev"})
    _write(paths["store"], {"store_sha256": "d" * 64, "raw_inventory_sha256": "b" * 64, "rows": 1})
    module = _module()
    try:
        module.build_register(
            archive_inventory=paths["archive"],
            raw_nrcs_inventory=paths["raw"],
            evaluation_catalog=paths["catalog"],
            us_store=paths["store"],
        )
    except ValueError as exc:
        assert "not bound" in str(exc)
    else:
        raise AssertionError("broken archive lineage must fail closed")
