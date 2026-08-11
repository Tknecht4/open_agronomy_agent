from __future__ import annotations

import importlib.util
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
