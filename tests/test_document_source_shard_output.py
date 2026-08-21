from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "ingest_document_sources.py"


def _load_ingestor():
    spec = importlib.util.spec_from_file_location(
        "document_source_shard_ingestor_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(source_id: str, *, local_rag: bool = True) -> dict:
    return {
        "id": source_id,
        "title": "Verified Canadian fixture source",
        "publisher": "Example Canadian Publisher",
        "authority_type": "federal_government",
        "jurisdiction": ["Canada"],
        "language": ["en-CA"],
        "url": f"https://example.test/{source_id}",
        "download_url": f"https://example.test/{source_id}.html",
        "format": "html",
        "content_mode": "corpus_document",
        "runtime_source_type": "applied_guidance",
        "runtime_document_type": "fixture_document",
        "crops": ["wheat"],
        "buckets": ["soil_water"],
        "priority": "high",
        "currency": {
            "status": "current_fixture",
            "review_interval_days": 365,
            "volatile": False,
        },
        "regulatory": {"regulated_advice": False, "require_live_authority": False},
        "license": {
            "status": "redistributable",
            "identifier": "Fixture Open Licence",
            "evidence_url": f"https://example.test/{source_id}/licence",
            "scope_verified": True,
            "scope_basis": "source_specific_record",
            "scope_evidence_url": f"https://example.test/{source_id}/licence-scope",
            "permits_modification": True,
            "permits_commercial": True,
            "permits_redistribution": True,
            "reviewed_on": "2026-08-13",
            "attribution": f"Fixture attribution for {source_id}",
            "notes": "A synthetic source record with explicit fixture permissions.",
        },
        "use_policy": {
            "discover": True,
            "download": True,
            "local_rag": local_rag,
            "distributable_bundle": local_rag,
            "training": False,
            "live_retrieval": True,
        },
    }


def _manifest(path: Path, source: dict) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.canada_agronomy_sources.v1",
                "generated_at": "2026-08-13T00:00:00Z",
                "required_jurisdictions": ["Canada"],
                "sources": [source],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _current_shard(ingestor, manifest: Path, source: dict, shard_dir: Path) -> list[dict]:
    raw = b"fixture raw Canadian extension document bytes"
    raw_lineage = {
        "source_id": source["id"],
        "canonical_url": source["url"],
        "download_url": source["download_url"],
        "fetched_at": "2026-08-13T00:00:00+00:00",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
    }
    text = " ".join(
        [
            "This official Canadian agronomy fixture gives regional soil-water context "
            "and retains boundaries between mapped context and field observations."
        ]
        * 30
    )
    rows = ingestor.make_rows(
        source,
        text,
        {"pages": None, "low_text_pages": 0},
        220,
        35,
        raw_source_lineage=raw_lineage,
        manifest_sha256=ingestor.sha256_path(manifest),
        ingested_at=raw_lineage["fetched_at"],
    )
    assert rows
    ingestor.write_jsonl(shard_dir / f"{source['id']}.jsonl", rows)
    return rows


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_source_shards_emit_canonical_receipts_without_combined_monolith(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingestor = _load_ingestor()
    source = _source("fixture-source")
    manifest = _manifest(tmp_path / "canada_agronomy_sources.json", source)
    shard_dir = tmp_path / "source-shards"
    rows = _current_shard(ingestor, manifest, source, shard_dir)
    receipt_dir = tmp_path / "receipts"
    summary_path = receipt_dir / "ingest_summary.json"
    legacy_output = tmp_path / "legacy-combined.jsonl"
    monkeypatch.setattr(ingestor, "DEFAULT_OUTPUT", legacy_output)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_document_sources.py",
            "--manifest",
            str(manifest),
            "--shard-dir",
            str(shard_dir),
            "--receipt-dir",
            str(receipt_dir),
            "--summary",
            str(summary_path),
            "--output-mode",
            "source-shards",
            "--source-id",
            source["id"],
        ],
    )

    assert ingestor.main() == 0
    assert not legacy_output.exists()
    shard_path = shard_dir / "fixture-source.jsonl"
    receipt_path = receipt_dir / "fixture-source.receipt.json"
    index_path = receipt_dir / "source_shards_manifest.json"
    assert shard_path.is_file()
    assert receipt_path.is_file()
    assert index_path.is_file()
    assert summary_path.is_file()

    expected_shard = b"".join(ingestor.canonical_json_bytes(row) for row in rows)
    assert shard_path.read_bytes() == expected_shard
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == ingestor.SOURCE_SHARD_RECEIPT_SCHEMA_VERSION
    assert receipt["source"]["id"] == source["id"]
    assert receipt["source"]["source_record_sha256"] == ingestor.canonical_json_sha256(source)
    assert receipt["shard"]["sha256"] == ingestor.sha256_path(shard_path)
    assert receipt["training_authorization"] == {
        "registry_training_allowed": False,
        "artifact_is_training_dataset": False,
        "boundary": (
            "This source-shard extraction is not a training dataset or training approval; "
            "a downstream training workflow must enforce its own authorization."
        ),
    }
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["totals"] == {"sources": 1, "rows": len(rows)}
    assert index["sources"][0]["shard_path"] == shard_path.name
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["combined_corpus_created"] is False
    assert summary["source_shard_index"]["sha256"] == ingestor.sha256_path(index_path)

    first_tree = _tree_bytes(tmp_path)
    assert ingestor.main() == 0
    assert _tree_bytes(tmp_path) == first_tree


def test_source_shards_refuse_ineligible_requested_source_before_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingestor = _load_ingestor()
    source = _source("not-local-rag", local_rag=False)
    manifest = _manifest(tmp_path / "canada_agronomy_sources.json", source)
    download_attempts: list[str] = []

    def fail_if_downloaded(*args, **kwargs):  # type: ignore[no-untyped-def]
        download_attempts.append("called")
        raise AssertionError("an ineligible source must fail before a download is attempted")

    monkeypatch.setattr(ingestor, "download_source", fail_if_downloaded)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_document_sources.py",
            "--manifest",
            str(manifest),
            "--shard-dir",
            str(tmp_path / "source-shards"),
            "--output-mode",
            "source-shards",
            "--source-id",
            source["id"],
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        ingestor.main()
    assert exc_info.value.code == 2
    assert not download_attempts
    assert not (tmp_path / "source-shards").exists()


def test_combined_mode_retains_legacy_combined_output_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingestor = _load_ingestor()
    source = _source("fixture-source")
    manifest = _manifest(tmp_path / "canada_agronomy_sources.json", source)
    shard_dir = tmp_path / "source-shards"
    rows = _current_shard(ingestor, manifest, source, shard_dir)
    combined_output = tmp_path / "legacy-combined.jsonl"
    summary_path = tmp_path / "legacy-summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ingest_document_sources.py",
            "--manifest",
            str(manifest),
            "--shard-dir",
            str(shard_dir),
            "--output",
            str(combined_output),
            "--summary",
            str(summary_path),
            "--source-id",
            source["id"],
        ],
    )

    assert ingestor.main() == 0
    assert ingestor.read_jsonl(combined_output) == rows
    legacy_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert legacy_summary["schema_version"] == "open_agronomy_agent.document_ingest_summary.v2"
    assert legacy_summary["combined_chunks"] == len(rows)


def test_source_manifest_validates_optional_expected_raw_sha256(
    tmp_path: Path,
) -> None:
    ingestor = _load_ingestor()
    source = _source("pinned-source")
    source["expected_raw_sha256"] = hashlib.sha256(b"fixture bytes").hexdigest().upper()
    assert ingestor.load_manifest(_manifest(tmp_path / "valid.json", source))["sources"][0][
        "expected_raw_sha256"
    ] == source["expected_raw_sha256"]

    source["expected_raw_sha256"] = "not-a-sha256"
    with pytest.raises(ValueError, match="expected_raw_sha256"):
        ingestor.load_manifest(_manifest(tmp_path / "invalid.json", source))


def test_download_source_rejects_reused_raw_pin_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingestor = _load_ingestor()
    source = _source("pinned-source")
    source["format"] = "pdf"
    source["download_url"] = "https://example.test/pinned-source.pdf"
    source["expected_raw_sha256"] = hashlib.sha256(b"expected fixture bytes").hexdigest()
    raw_path = tmp_path / "raw" / source["id"] / "source.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"different existing fixture bytes")
    monkeypatch.setattr(
        ingestor,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("a mismatched reused raw file must not download"),
    )

    with pytest.raises(RuntimeError, match="reused raw SHA-256 mismatch"):
        ingestor.download_source(source, tmp_path / "raw")
    assert raw_path.read_bytes() == b"different existing fixture bytes"


def test_download_source_verifies_pinned_bytes_before_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingestor = _load_ingestor()
    source = _source("pinned-source")
    source["format"] = "pdf"
    source["download_url"] = "https://example.test/pinned-source.pdf"
    downloaded = b"%PDF-1.7\n" + (b"verified fixture PDF bytes " * 80)
    source["expected_raw_sha256"] = hashlib.sha256(downloaded).hexdigest()
    monkeypatch.setattr(ingestor, "urlopen", lambda *args, **kwargs: io.BytesIO(downloaded))

    raw_dir = tmp_path / "raw"
    promoted = ingestor.download_source(source, raw_dir)
    assert promoted.read_bytes() == downloaded
    assert not promoted.with_suffix(".pdf.part").exists()
    lineage = ingestor.raw_lineage(source, promoted)
    assert lineage["raw_sha256"] == source["expected_raw_sha256"].lower()
    assert lineage["expected_raw_sha256"] == source["expected_raw_sha256"].lower()

    mismatched = _source("mismatched-pinned-source")
    mismatched["format"] = "pdf"
    mismatched["download_url"] = "https://example.test/mismatched-pinned-source.pdf"
    mismatched["expected_raw_sha256"] = hashlib.sha256(b"other expected bytes").hexdigest()
    old_path = raw_dir / mismatched["id"] / "source.pdf"
    old_path.parent.mkdir(parents=True)
    old_bytes = b"old raw artifact that must survive failed promotion"
    old_path.write_bytes(old_bytes)
    monkeypatch.setattr(ingestor, "urlopen", lambda *args, **kwargs: io.BytesIO(downloaded))
    monkeypatch.setattr(
        ingestor,
        "_download_with_curl",
        lambda _url, destination, _timeout: destination.write_bytes(downloaded),
    )

    with pytest.raises(ingestor.RawSha256MismatchError, match="downloaded raw SHA-256 mismatch"):
        ingestor.download_source(mismatched, raw_dir, force=True)
    assert old_path.read_bytes() == old_bytes
    assert not old_path.with_suffix(".pdf.part").exists()


@pytest.mark.parametrize("source_shard_mode", [False, True])
def test_existing_extraction_rejects_pinned_raw_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_shard_mode: bool
) -> None:
    ingestor = _load_ingestor()
    source = _source("pinned-source")
    expected_raw = b"fixture raw Canadian extension document bytes"
    source["expected_raw_sha256"] = hashlib.sha256(expected_raw).hexdigest()
    manifest = _manifest(tmp_path / "canada_agronomy_sources.json", source)
    shard_dir = tmp_path / "source-shards"
    _current_shard(ingestor, manifest, source, shard_dir)
    raw_dir = tmp_path / "raw"
    raw_path = raw_dir / source["id"] / "source.html"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"tampered raw bytes")

    argv = [
        "ingest_document_sources.py",
        "--manifest",
        str(manifest),
        "--raw-dir",
        str(raw_dir),
        "--shard-dir",
        str(shard_dir),
        "--source-id",
        source["id"],
    ]
    if source_shard_mode:
        argv.extend(
            [
                "--output-mode",
                "source-shards",
                "--receipt-dir",
                str(tmp_path / "receipts"),
            ]
        )
    else:
        argv.extend(
            [
                "--output",
                str(tmp_path / "combined.jsonl"),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )
    monkeypatch.setattr(sys, "argv", argv)

    assert ingestor.main() == 2
    assert raw_path.read_bytes() == b"tampered raw bytes"
