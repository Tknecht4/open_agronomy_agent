from __future__ import annotations

from agronomy_agent.corpus_release import (
    answer_evidence_disposition,
    quality_ledger_status,
    quality_ledger_row,
    shard_records,
    source_locator_status,
)
from agronomy_agent.agno_runtime.local_index import LexicalRetriever


def _locator(**extra: object) -> dict[str, object]:
    result: dict[str, object] = {
        "raw_sha256": "a" * 64,
        "source_url": "https://example.test/source",
        "extraction_method": "structured_json_v1",
        "precision": "json_document_chunk",
        "archive_relative_path": "data/raw/example.json",
        "json_document_id": "example",
        "chunk_index": 0,
        "chunk_text_sha256": "b" * 64,
    }
    result.update(extra)
    return result


def test_source_locator_requires_a_real_source_bound_locator() -> None:
    assert source_locator_status(_locator()) == (True, "complete")
    assert source_locator_status(_locator(raw_sha256="bad")) == (False, "invalid_raw_sha256")
    assert source_locator_status(_locator(archive_relative_path="")) == (False, "missing_document_locator")


def test_source_locator_requires_precise_page_section_and_table_coordinates() -> None:
    base = {"raw_sha256": "a" * 64, "source_url": "https://example.test/source", "extraction_method": "layout_v1"}
    assert source_locator_status({**base, "precision": "page_char_span", "page": 2, "char_start": 10, "char_end": 20}) == (True, "complete")
    assert source_locator_status({**base, "precision": "section_char_span", "char_start": 10, "char_end": 20, "heading_path": ["A", "B"]}) == (True, "complete")
    assert source_locator_status({**base, "precision": "table_cells", "table_title": "Rates", "column_headers": ["N"], "cells": [{"row": 1, "column": 0}]}) == (True, "complete")
    assert source_locator_status({**base, "precision": "table_cells", "table_title": "Rates", "column_headers": ["N"], "cells": [{"row": "1", "column": 0}]}) == (False, "invalid_table_cell_coordinates")


def test_page_markers_and_references_are_not_answer_evidence() -> None:
    assert answer_evidence_disposition("[page 7]") == "provenance_only_page_marker"
    assert answer_evidence_disposition("Smith et al.", title="References") == "provenance_only_references"
    assert answer_evidence_disposition("Soil moisture constrains rooting depth and crop response.") == "answer_evidence_candidate"


def test_quality_ledger_preserves_missing_locator_as_a_failure() -> None:
    row = quality_ledger_row(
        {"doc_id": "d", "source_id": "s", "text": "A sufficiently long agronomic statement."},
        corpus_path="data/example.jsonl",
        duplicate_cluster="x",
        duplicate_disposition="retained",
    )
    assert row["source_locator_complete"] is False
    assert row["source_locator_status"] == "missing_source_locator"
    assert row["quality_ledger_complete"] is False


def test_quality_ledger_requires_every_runtime_quality_field() -> None:
    record = {"retrieval_policy": "context_only", "quality": {"language": "English"}}
    assert quality_ledger_status(record) == (False, "missing_quality_extraction_fidelity")


def test_shards_are_bounded_and_deterministic() -> None:
    records = [{"doc_id": "a", "text": "a" * 30}, {"doc_id": "b", "text": "b" * 30}]
    shards = shard_records(records, maximum_bytes=70)
    assert [item[0]["doc_id"] for item in shards] == ["a", "b"]


def test_retrieval_preserves_successor_source_locator() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "nrcs-1",
                "title": "NRCS",
                "text": "Ecological site soil water context.",
                "source": "https://example.test/source",
                "jurisdiction": ["United States"],
                "source_locator": _locator(),
            }
        ]
    )
    [result] = retriever.search("ecological site", top_k=1)
    assert result.source_locator == _locator()
