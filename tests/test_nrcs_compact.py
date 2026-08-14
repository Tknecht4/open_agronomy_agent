from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_compact_nrcs_esd_corpus.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_compact_nrcs_esd_corpus", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(doc_id: str, chunk_index: int, text: str) -> dict[str, object]:
    return {
        "doc_id": doc_id,
        "chunk_index": chunk_index,
        "title": f"Site chunk {chunk_index}",
        "text": text,
    }


def test_section_balanced_projection_preserves_primary_facets_and_boundary() -> None:
    module = _module()
    candidates = [
        _row("climate", 2, "Climatic features: precipitation and temperature."),
        _row("soil", 3, "Soil features: drainage, texture, and water table."),
        _row("dynamics", 4, "Ecological dynamics: plant community transitions."),
        _row("interpretations", 5, "Interpretations: management limitations."),
        _row("general", 1, "General information: ecological site and MLRA notes."),
    ]

    selected = module.select_site_rows(candidates, chunks_per_site=4)

    assert [row["doc_id"] for row in selected] == [
        "general",
        "soil",
        "dynamics",
        "interpretations",
    ]
    assert all(row["retrieval_policy"] == "context_only" for row in selected)
    assert all(row["transfer_scope"] == "cross_border_analogue" for row in selected)
    assert all(row["jurisdiction"] == ["United States"] for row in selected)
    assert all("Canadian field validation required" in row["applicability_boundary"] for row in selected)


def test_section_balanced_projection_fills_missing_facets_by_priority() -> None:
    module = _module()
    candidates = [
        _row("general", 1, "General information: ecological site."),
        _row("water", 2, "Water features: drainage and water table."),
        _row("fallback", 3, "Plant community management and soil texture."),
    ]

    selected = module.select_site_rows(candidates, chunks_per_site=3)

    assert {row["doc_id"] for row in selected} == {"general", "water", "fallback"}


def test_projection_replaces_ingest_host_path_with_portable_locator() -> None:
    module = _module()
    row = _row("general", 1, "General information: ecological site.")
    row.update(
        {
            "mlra": "055A",
            "ecological_site_id": "R055AY001ND",
            "extraction": {
                "method": "official_edit_json",
                "raw_path": "/" + "Volumes/example/raw/055A/R055AY001ND.json",
                "structured_words": 200,
            },
        }
    )

    selected = module.select_site_rows([row], chunks_per_site=1)

    assert selected[0]["extraction"] == {
        "method": "official_edit_json",
        "raw_locator": {
            "base": "nrcs_esd_ingest_raw_dir",
            "path": "055A/R055AY001ND.json",
        },
        "structured_words": 200,
    }


def test_committed_v2_projection_is_portable_and_receipted() -> None:
    compact = ROOT / "data/derived/rag/nrcs_esd_rag_corpus_compact_v2.jsonl"
    receipt = json.loads(
        (ROOT / "data/manifests/source_retention_receipt.json").read_text(encoding="utf-8")
    )["nrcs_reference_projection"]
    with compact.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()

    assert receipt["compact_path"] == compact.relative_to(ROOT).as_posix()
    assert receipt["compact_sha256"] == digest
    assert receipt["compact_rows"] == 32_624

    row_count = 0
    with compact.open("r", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            row_count += 1
            extraction = row["extraction"]
            assert "raw_path" not in extraction
            assert extraction["raw_locator"]["base"] == "nrcs_esd_ingest_raw_dir"
            assert not Path(extraction["raw_locator"]["path"]).is_absolute()
    assert row_count == receipt["compact_rows"]
