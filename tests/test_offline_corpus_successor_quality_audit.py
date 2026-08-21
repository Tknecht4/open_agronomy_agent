from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_offline_corpus_successor_quality.py"


def _module():
    spec = importlib.util.spec_from_file_location("audit_offline_corpus_successor_quality", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(*, complete: bool) -> dict[str, object]:
    row: dict[str, object] = {"doc_id": "d", "retrieval_policy": "context_only"}
    if complete:
        row["source_locator"] = {
            "precision": "json_document_chunk",
            "archive_relative_path": "data/raw/d.json",
            "raw_sha256": "a" * 64,
            "source_url": "https://example.test/d.json",
            "extraction_method": "test",
            "json_document_id": "d",
            "chunk_index": 0,
            "chunk_text_sha256": "b" * 64,
        }
        row["quality"] = {
            "extraction_fidelity": "test",
            "language": "English",
            "authority_tier": "government",
            "jurisdiction": "Canada",
            "temporal_scope": "dated",
            "risk_class": "context_only",
            "retrieval_eligibility": "context_only",
            "duplicate_disposition": "retained",
            "near_duplicate_disposition": "not_clustered",
        }
    return row


def test_successor_quality_audit_blocks_any_legacy_row_without_source_exact_fields(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "complete.jsonl").write_text(json.dumps(_row(complete=True)) + "\n", encoding="utf-8")
    (data / "legacy.jsonl").write_text(json.dumps(_row(complete=False)) + "\n", encoding="utf-8")
    policy = {"corpora": [{"path": "data/complete.jsonl", "evidence_tier": "official"}, {"path": "data/legacy.jsonl", "evidence_tier": "official"}]}
    (data / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
    config = {"retrieval": {"corpus_paths": ["data/complete.jsonl", "data/legacy.jsonl"], "corpus_policy_manifest": "data/policy.json"}}
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    report = _module().audit(config_path, root=tmp_path)
    assert report["promotion_gate"]["passed"] is False
    assert report["totals"] == {"rows": 2, "source_locator_complete_rows": 1, "quality_ledger_complete_rows": 1}
