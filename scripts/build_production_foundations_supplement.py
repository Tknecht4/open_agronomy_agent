#!/usr/bin/env python3
"""Build the bounded, source-linked production foundations context shard.

The checked-in text is project-authored synthesis. External source snapshots
are separately identified by URL and hash in the source registry; this builder
does not treat their pages as verbatim corpus text or decisive authority.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.corpus_release import (  # noqa: E402
    CORPUS_RELEASE_SCHEMA,
    canonical_json,
    normalized_text_sha256,
    quality_ledger_row,
    sha256_text,
    source_locator_status,
    write_jsonl,
)
from agronomy_agent.method_context import (  # noqa: E402
    PHYSICAL_CAPTURE_KIND,
    PHYSICAL_METHOD_SCHEMA,
    PHYSICAL_METHOD_SOURCE_IDS,
    PHYSICAL_REVIEW_SHA256,
)

DEFAULT_SEED = ROOT / "data/seed/production_foundations_v1.jsonl"
DEFAULT_SOURCES = ROOT / "data/manifests/production_foundations_sources_v1.json"
DEFAULT_OUTPUT = ROOT / "data/derived/rag/offline_agronomy/production_foundations/v1"
PHYSICAL_STORE = "physical-method-context-v1"
PHYSICAL_CARDS = {
    "PROPOSED-KSTATE-MEASUREMENT-BASIS": "soil_measurement_basis",
    "PROPOSED-KSTATE-WATER-ACCOUNTING": "layer_water_accounting",
}
PHYSICAL_SEMANTIC_FIELDS = (
    "doc_id", "title", "text", "required_context", "application_boundary",
    "attribution", "changes", "evidence_roles", "source_kind",
    "source_jurisdictions", "supporting_source_ids", "supporting_span_ids",
    "source_snapshot_sha256", "project_derivation_boundary",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bounded_bytes(path: Path, limit: int = 131072) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("chapter evidence must be a bounded regular file")
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError("chapter evidence exceeds its bound")
    return data


def _normalize_chapter_fragment(fragment: str) -> str:
    """Normalize only the reviewed prose/MathML vocabulary; never execute HTML."""
    if "<!" in fragment:
        raise ValueError("chapter declarations are not supported")
    if fragment.startswith("<math "):
        def render(node):
            tag = node.tag.rsplit("}", 1)[-1]
            if tag not in {"math", "mtext", "mi", "mo", "mn", "mrow", "mfrac", "msub", "msup"}:
                raise ValueError("unreviewed chapter MathML")
            children = list(node)
            if tag in {"mfrac", "msub", "msup"}:
                if len(children) != 2:
                    raise ValueError("malformed chapter MathML")
                left, right = map(render, children)
                return f"({left})/({right})" if tag == "mfrac" else left + ("_" if tag == "msub" else "^") + right
            return (node.text or "") + "".join(render(c) + (c.tail or "") for c in children)
        text = render(ET.fromstring(html.unescape(fragment)))
    else:
        class Prose(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.parts = []
            def handle_starttag(self, tag, attrs):
                if tag not in {"p", "em", "strong", "a", "span", "sup"}:
                    raise ValueError("excluded or unknown chapter HTML")
                if tag == "sup":
                    self.parts.append("^")
            def handle_data(self, value):
                self.parts.append(value)
        parser = Prose()
        parser.feed(fragment)
        text = "".join(parser.parts)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def chapter_source_metadata(source: dict) -> dict:
    """Publish provenance/locators, never the captured DOM or method excerpts."""
    fields = ("source_id", "source_type", "title", "chapter_number", "chapter_slug",
              "parent_book_title", "parent_edition", "parent_book_doi", "chapter_doi",
              "authors", "publisher", "url", "captured_at_utc", "jurisdiction", "rights",
              "snapshot_path", "snapshot_sha256", "snapshot_kind", "text_path", "text_sha256",
              "original_http_response_acquired", "original_http_response_sha256", "attribution", "changes")
    metadata = {field: source[field] for field in fields}
    metadata["locators"] = [{k: v for k, v in row.items() if k != "text"} for row in source["locators"]]
    rights = source["license_evidence"]
    metadata["license_evidence"] = {field: rights[field] for field in (
        "basis", "license_url", "native_footer_html_sha256", "native_footer_text_sha256",
        "exception_decision", "attribution_changes")}
    return metadata


def _validate_chapter_registry(registry: dict, evidence_root: Path | None, review_path: Path | None) -> dict:
    if evidence_root is None or review_path is None:
        raise ValueError("chapter build requires explicit private evidence and review receipt")
    review_bytes = _bounded_bytes(review_path)
    if hashlib.sha256(review_bytes).hexdigest() != PHYSICAL_REVIEW_SHA256:
        raise ValueError("chapter independent review pin mismatch")
    review = json.loads(review_bytes)
    evidence_root = evidence_root.resolve()
    pins = review["all_private_packet_file_pins"]
    if len(pins) != 9 or sum(row["bytes"] for row in pins.values()) > 2097152:
        raise ValueError("chapter evidence scope exceeds reviewed packet")
    files = {}
    for name, pin in pins.items():
        relative = Path(name)
        path = evidence_root / relative
        if relative.is_absolute() or len(relative.parts) != 1 or not path.resolve().is_relative_to(evidence_root):
            raise ValueError("chapter evidence path escape")
        data = _bounded_bytes(path)
        if len(data) != pin["bytes"] or hashlib.sha256(data).hexdigest() != pin["sha256"]:
            raise ValueError("chapter evidence hash drift")
        files[name] = data
    private = json.loads(files["source-manifest.json"])
    expected = {
        "schema_version": "open_agronomy_agent.chapter_DOM_sources.v1",
        "activation": "none",
        "independent_review_sha256": PHYSICAL_REVIEW_SHA256,
        "capture_manifest_sha256": review["exact_source_manifest_sha256"],
        "proposed_wording_sha256": review["exact_two_paraphrases_sha256"],
        "sources": [chapter_source_metadata(source) for source in private["sources"]],
    }
    if registry != expected:
        raise ValueError("chapter source identity, rights or scope differs from review")
    for source in private["sources"]:
        capture = json.loads(files[source["snapshot_path"]])
        text = files[source["text_path"]]
        if (source["snapshot_kind"] != PHYSICAL_CAPTURE_KIND
            or capture["capture_kind"] != PHYSICAL_CAPTURE_KIND
            or source["original_http_response_acquired"]
            or source["original_http_response_sha256"] is not None
            or source["source_type"] != "textbook_chapter"
            or source["jurisdiction"] != "United States"):
            raise ValueError("chapter capture kind or provenance mismatch")
        for locator in source["locators"]:
            fragment = capture["methods"][locator["source_fragment_index"]]
            normalized = _normalize_chapter_fragment(fragment["html"])
            start, end = locator["normalized_fragment_character_range_half_open"]
            first, last = locator["selected_text_utf8_byte_range_half_open"]
            if (normalized[start:end] != locator["text"]
                or text[first:last] != locator["text"].encode()
                or sha256_text(fragment["html"]) != locator["source_fragment_html_sha256"]
                or sha256_text(locator["text"]) != locator["span_sha256"]
                or fragment["dom_locator"] != locator["source_dom_locator"]):
                raise ValueError("chapter span or formula drift")
        if sha256_text(_normalize_chapter_fragment(capture["license"]["html"])) != source["license_evidence"]["native_footer_text_sha256"]:
            raise ValueError("chapter native permission notice drift")
    cards = [json.loads(line) for line in files["proposed-wording.jsonl"].decode().splitlines()]
    return {card["doc_id"]: card for card in cards}


def _validate_physical_item(item: dict, original: dict, method: dict, support_hash: str) -> None:
    semantic = {key: item.get(key) for key in PHYSICAL_SEMANTIC_FIELDS}
    if semantic != {key: original[key] for key in PHYSICAL_SEMANTIC_FIELDS}:
        raise ValueError("physical paraphrase or task dependencies differ from review")
    method_id = PHYSICAL_CARDS[item["doc_id"]]
    scope = {
        "schema_version": PHYSICAL_METHOD_SCHEMA,
        "review_status": "source_supported_method_scope_reviewed",
        "basis": "reviewed_physical_identity",
        "source_review_sha256": PHYSICAL_REVIEW_SHA256,
        "capture_kind": PHYSICAL_CAPTURE_KIND,
        "source_support_receipt_sha256": support_hash,
        "method_ids": [method_id],
        "applicability_countries": ["Canada", "United States"],
    }
    expected_method = {
        "method_id": method_id, "source_ids": list(PHYSICAL_METHOD_SOURCE_IDS[method_id]),
        "supporting_span_ids": original["supporting_span_ids"],
        "approved_text_sha256": sha256_text(original["text"]),
    }
    if (method != expected_method or item.get("method_scope") != scope
        or item.get("jurisdiction") != ["Canada", "United States"]
        or item.get("transfer_scope") != "general_method_only"
        or item.get("answer_role") != "method_context"
        or item.get("activation") != "none"
        or item.get("admission_status") != "non_active_candidate"
        or item.get("training_allowed") is not False
        or set(item) != set(PHYSICAL_SEMANTIC_FIELDS) | {
            "method_scope", "jurisdiction", "transfer_scope", "answer_role", "activation",
            "admission_status", "training_allowed", "knowledge_domains", "source"}
        or item.get("knowledge_domains") != ["soil_physics"]
        or item.get("source") != "K-State physical methods; attributed project paraphrase"):
        raise ValueError("physical method scope or authority mismatch")


def build(seed_path: Path, sources_path: Path, output: Path, *, store_id: str = "production-foundations-v1", support_receipt_path: Path | None = None, chapter_evidence_root: Path | None = None, chapter_review_receipt: Path | None = None) -> dict:
    seed_path = seed_path.resolve()
    sources_path = sources_path.resolve()
    output = output.resolve()
    if store_id not in {"production-foundations-v1", "production-foundations-method-v2", PHYSICAL_STORE}:
        raise ValueError("unsupported foundations store ID")
    if not seed_path.is_relative_to(ROOT) or not sources_path.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
        raise ValueError("seed, source registry and output must be inside this repository")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"refusing to overwrite nonempty output: {output}")
    registry = json.loads(sources_path.read_text(encoding="utf-8"))
    physical_cards = None
    if store_id == PHYSICAL_STORE:
        physical_cards = _validate_chapter_registry(registry, chapter_evidence_root, chapter_review_receipt)
    elif (registry.get("schema_version") == "open_agronomy_agent.chapter_DOM_sources.v1"
          or any(source.get("source_type") == "textbook_chapter" for source in registry.get("sources", []))):
        raise ValueError("chapter evidence requires its separately reviewed physical store")
    base_registry_value = registry.get("base_registry_path")
    if base_registry_value:
        base_registry_path = (ROOT / str(base_registry_value)).resolve()
        if not base_registry_path.is_relative_to(ROOT) or sha256(base_registry_path) != registry.get("base_registry_sha256"):
            raise ValueError("base source registry hash mismatch")
        base_registry = json.loads(base_registry_path.read_text(encoding="utf-8"))
        registry["sources"] = [*base_registry["sources"], *registry["sources"]]
    support_hash = None
    if store_id in {"production-foundations-method-v2", PHYSICAL_STORE}:
        if support_receipt_path is None:
            raise ValueError("method release requires a source-support receipt")
        support_receipt_path = support_receipt_path.resolve()
        if not support_receipt_path.is_relative_to(ROOT):
            raise ValueError("source-support receipt must be inside this repository")
        support_hash = sha256(support_receipt_path)
        support_receipt = json.loads(support_receipt_path.read_text(encoding="utf-8"))
        if support_receipt.get("source_registry_path") != sources_path.relative_to(ROOT).as_posix():
            raise ValueError("method source-support receipt names a different registry")
        support_rows = support_receipt.get("methods") or {}
        if store_id == PHYSICAL_STORE and support_receipt != {
            "schema_version": "open_agronomy_agent.chapter_method_source_support.v1",
            "source_registry_path": sources_path.relative_to(ROOT).as_posix(),
            "source_registry_sha256": sha256(sources_path),
            "independent_review_sha256": PHYSICAL_REVIEW_SHA256,
            "activation": "none",
            "methods": {doc_id: {
                "method_id": method_id, "source_ids": list(PHYSICAL_METHOD_SOURCE_IDS[method_id]),
                "supporting_span_ids": physical_cards[doc_id]["supporting_span_ids"],
                "approved_text_sha256": sha256_text(physical_cards[doc_id]["text"]),
            } for doc_id, method_id in PHYSICAL_CARDS.items()},
        }:
            raise ValueError("chapter support receipt differs from reviewed scope")
    sources = {str(row["source_id"]): row for row in registry["sources"]}
    if len(sources) != len(registry["sources"]):
        raise ValueError("duplicate source ID")
    for row in sources.values():
        if len(str(row.get("snapshot_sha256") or "")) != 64 or not row.get("url") or not row.get("rights"):
            raise ValueError(f"incomplete external source receipt: {row.get('source_id')}")
    raw_sha = sha256(seed_path)
    source_url = f"https://github.com/Tknecht4/open_agronomy_agent/blob/main/{seed_path.relative_to(ROOT).as_posix()}"
    records = []
    seen_ids = set()
    seen_texts = set()
    for index, line in enumerate(seed_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        item = json.loads(line)
        doc_id = str(item.get("doc_id") or "")
        content = str(item.get("text") or "").strip()
        support = item.get("supporting_source_ids") or []
        if not doc_id or doc_id in seen_ids or not content or not support or not set(support) <= set(sources):
            raise ValueError(f"invalid or duplicate seed record at line {index + 1}")
        if len(content) > 1800:
            raise ValueError(f"overlong summary card: {doc_id}")
        if physical_cards is not None:
            if doc_id not in physical_cards:
                raise ValueError("unreviewed physical card")
            _validate_physical_item(item, physical_cards[doc_id], support_rows.get(doc_id), support_hash)
        elif support_hash is not None:
            scope = item.get("method_scope") or {}
            source_jurisdictions = [str(sources[source_id].get("jurisdiction") or "") for source_id in support if source_id in sources]
            if (item.get("answer_role") != "method_context"
                or item.get("transfer_scope") != "general_method_only"
                or scope.get("source_support_receipt_sha256") != support_hash
                or set(support_rows.get(doc_id, {}).get("source_ids") or ()) != set(support)
                or scope.get("method_ids") != [support_rows.get(doc_id, {}).get("method_id")]
                or scope.get("applicability_countries") != ["Canada", "United States"]
                or item.get("jurisdiction") != ["Canada", "United States"]
                or item.get("source_jurisdictions") != source_jurisdictions
                or not any("Canada" in value for value in source_jurisdictions)
                or not any("United States" in value for value in source_jurisdictions)):
                raise ValueError(f"invalid method scope or source support: {doc_id}")
        normalized = normalized_text_sha256(content)
        if normalized in seen_texts:
            raise ValueError(f"duplicate card text: {doc_id}")
        seen_ids.add(doc_id)
        seen_texts.add(normalized)
        record = {
            **item,
            "text": content,
            # These values are retrieval facets, not evidence authority. The
            # router's live farmer_knowledge lane admits applied_guidance;
            # the separate tier and policy below keep this synthesis contextual.
            "source_kind": "project_authored_source_linked_synthesis",
            "source_type": "applied_guidance",
            "knowledge_bucket": "farmer_knowledge",
            "knowledge_domains": sorted(set(item.get("knowledge_domains") or []) | {"farmer_knowledge"}),
            "authority_tier": "internal_synthesis",
            "rights_status": "project_authored",
            "license": "Apache-2.0_project_text_only",
            "retrieval_policy": "context_only",
            "raw_sha256": raw_sha,
            "chunk_sha256": sha256_text(content),
            "source_locator": {
                "precision": "json_document_chunk",
                "archive_relative_path": seed_path.relative_to(ROOT).as_posix(),
                "raw_sha256": raw_sha,
                "source_url": source_url,
                "extraction_method": "checked_in_project_summary_record_v1" if support_hash is None else "checked_in_project_method_record_v2",
                "json_document_id": doc_id,
                "chunk_index": index,
                "chunk_text_sha256": sha256_text(content),
            },
            "quality": {
                "extraction_fidelity": "checked_in_project_summary_exact_hash_not_verbatim_external_source",
                "language": "English",
                "authority_tier": "internal_synthesis",
                "jurisdiction": "; ".join(item.get("jurisdiction") or []),
                "temporal_scope": "stable_method_summary; current farm and market inputs required",
                "risk_class": "context_only",
                "retrieval_eligibility": "context_only",
                "duplicate_disposition": "unique_normalized_text",
                "near_duplicate_disposition": "reviewed_small_card_set_not_clustered",
            },
        }
        if physical_cards is not None:
            record.update({
                "license": "CC-BY-4.0",
                "rights_status": "CC-BY-4.0_attributed_paraphrase",
                "license_snapshot": {"status": "reviewed_selected_chapter_paraphrase",
                    "identifier": "CC-BY-4.0", "distribution_scope": "attributed_paraphrases_only"},
            })
        if not source_locator_status(record["source_locator"])[0]:
            raise ValueError(f"incomplete source locator: {doc_id}")
        records.append(record)
    records.sort(key=lambda row: row["doc_id"])
    if not records:
        raise ValueError("no summary cards")
    if physical_cards is not None and seen_ids != set(PHYSICAL_CARDS):
        raise ValueError("physical release requires exactly the two reviewed cards")
    output.mkdir(parents=True)
    shard_path = output / "shards/foundations-0001.jsonl"
    row_count, shard_hash, shard_bytes = write_jsonl(shard_path, records)
    ledger_path = output / "quality_ledger.json"
    ledger = [quality_ledger_row(row, corpus_path="shards/foundations-0001.jsonl", duplicate_cluster=normalized_text_sha256(row["text"]), duplicate_disposition="unique_normalized_text") for row in records]
    ledger_path.write_text(json.dumps({"schema_version": "open_agronomy_agent.corpus_quality_ledger.v1", "rows": ledger}, indent=2) + "\n", encoding="utf-8")
    receipt_path = output / "source_receipt.json"
    receipt_path.write_text(json.dumps({
        "schema_version": "open_agronomy_agent.production_foundations_source_receipt.v1" if support_hash is None else "open_agronomy_agent.production_foundations_source_receipt.v2",
        "seed_path": seed_path.relative_to(ROOT).as_posix(),
        "seed_sha256": raw_sha,
        "external_source_registry_path": sources_path.relative_to(ROOT).as_posix(),
        "external_source_registry_sha256": sha256(sources_path),
        "external_snapshots_in_public_package": False,
        "source_ids": sorted(sources),
        **({"source_support_receipt_path": support_receipt_path.relative_to(ROOT).as_posix(), "source_support_receipt_sha256": support_hash} if support_hash else {}),
        **({"chapter_capture_kind": PHYSICAL_CAPTURE_KIND,
            "chapter_review_sha256": PHYSICAL_REVIEW_SHA256} if physical_cards is not None else {}),
        "rights_boundary": "Only project-authored summaries are distributed; source-specific terms remain with the publishers.",
    }, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": CORPUS_RELEASE_SCHEMA,
        "store_id": store_id,
        "profile": "source-linked-context-only",
        "shards": [{"path": "shards/foundations-0001.jsonl", "rows": row_count, "bytes": shard_bytes, "sha256": shard_hash, "retrieval_policies": ["context_only"]}],
        "row_count": row_count,
        "quality_ledger_path": "quality_ledger.json",
        "quality_ledger_sha256": sha256(ledger_path),
        "source_receipt_path": "source_receipt.json",
        "source_receipt_sha256": sha256(receipt_path),
        "authority_boundary": "Project-authored context only. No current price, field rate, legal authority, or local calibration.",
    }
    manifest["store_sha256"] = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
    (output / "store_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--store-id", default="production-foundations-v1")
    parser.add_argument("--support-receipt", type=Path)
    parser.add_argument("--chapter-evidence-root", type=Path, help="read-only private selected-DOM packet; physical store only")
    parser.add_argument("--chapter-review-receipt", type=Path, help="exact independent private source/method review; physical store only")
    args = parser.parse_args()
    manifest = build(args.seed, args.sources, args.output, store_id=args.store_id, support_receipt_path=args.support_receipt, chapter_evidence_root=args.chapter_evidence_root, chapter_review_receipt=args.chapter_review_receipt)
    print(json.dumps({"output": str(args.output), "rows": manifest["row_count"], "store_sha256": manifest["store_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
