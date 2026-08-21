#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://edit.sc.egov.usda.gov"
DEFAULT_RAW_DIR = ROOT / "data" / "raw" / "documents" / "nrcs_esd_json"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "rag" / "nrcs_esd_rag_corpus.jsonl"
DEFAULT_SUMMARY = ROOT / "data" / "derived" / "rag" / "nrcs_esd_summary.json"
DEFAULT_SHARD_DIR = ROOT / "data" / "derived" / "rag" / "nrcs_esd_shards"
DEFAULT_CLASS_LIST = ROOT / "data" / "derived" / "rag" / "nrcs_esd_class_list.json"

SKIP_KEYS = {"metadata", "images", "path", "source"}
SECTION_TITLES = {
    "generalInformation": "General information",
    "physiographicFeatures": "Physiographic features",
    "climaticFeatures": "Climatic features",
    "waterFeatures": "Water features",
    "soilFeatures": "Soil features",
    "ecologicalDynamics": "Ecological dynamics",
    "interpretations": "Interpretations",
    "supportingInformation": "Supporting information",
    "referenceSheet": "Reference sheet",
}


def safe_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80]
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}" if slug else digest


def fetch(url: str, timeout: int, attempts: int) -> bytes:
    req = Request(url, headers={"User-Agent": "agronomy-agent-nrcs-esd-json-ingest/0.1"})
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(req, timeout=timeout) as response:
                data = response.read()
            if len(data) < 32:
                raise RuntimeError(f"short response ({len(data)} bytes)")
            return data
        except Exception as exc:  # noqa: BLE001 - source diagnostics should preserve raw failure.
            errors.append(f"attempt {attempt}: {exc!r}")
            if attempt < attempts:
                time.sleep(min(12, attempt * 2))
    raise RuntimeError(f"fetch failed for {url}: {' | '.join(errors)}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def chunk_text(text: str, max_words: int, overlap_words: int) -> list[str]:
    text = text.replace("\u00ad", "")
    text = re.sub(r"([a-z])-\s+([a-z])", r"\1\2", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for paragraph in paragraphs:
        words = paragraph.split()
        if len(words) > max_words:
            if current:
                chunks.append(" ".join(current).strip())
                current, current_words = [], 0
            step = max(1, max_words - overlap_words)
            for i in range(0, len(words), step):
                piece = words[i : i + max_words]
                if len(piece) >= 50:
                    chunks.append(" ".join(piece).strip())
            continue
        if current and current_words + len(words) > max_words:
            chunks.append(" ".join(current).strip())
            tail = " ".join(current).split()[-overlap_words:] if overlap_words else []
            current = [" ".join(tail)] if tail else []
            current_words = len(tail)
        current.append(paragraph)
        current_words += len(words)
    if current:
        chunks.append(" ".join(current).strip())
    return [chunk for chunk in chunks if len(chunk.split()) >= 50]


def label(value: str) -> str:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    return spaced.replace("_", " ").replace("-", " ").strip().capitalize()


def flatten_json(value: Any, heading: str = "") -> list[str]:
    parts: list[str] = []
    if isinstance(value, dict):
        narrative = value.get("narratives")
        if isinstance(narrative, dict):
            narrative_parts = flatten_json(narrative, heading)
            parts.extend(narrative_parts)
        for key, child in value.items():
            if key in SKIP_KEYS or key == "narratives":
                continue
            child_heading = label(key) if not heading else f"{heading} - {label(key)}"
            parts.extend(flatten_json(child, child_heading))
    elif isinstance(value, list):
        for index, item in enumerate(value, start=1):
            item_heading = heading
            if isinstance(item, dict):
                name = (
                    item.get("name")
                    or item.get("commonName")
                    or item.get("scientificName")
                    or item.get("symbol")
                    or item.get("type")
                    or item.get("id")
                )
                if name:
                    item_heading = f"{heading} - {name}" if heading else str(name)
                elif heading:
                    item_heading = f"{heading} {index}"
            parts.extend(flatten_json(item, item_heading))
    elif value is not None:
        text = str(value).strip()
        if text and text not in {"--", "None", "null"}:
            parts.append(f"{heading}: {text}" if heading else text)
    return parts


def description_text(data: dict[str, Any], ecoclass: dict[str, Any]) -> str:
    header = [
        f"Ecological site {ecoclass['id']} ({ecoclass['geoUnit']}): {ecoclass.get('name') or ecoclass['id']}",
    ]
    if ecoclass.get("legacyId") and ecoclass["legacyId"] != ecoclass["id"]:
        header.append(f"Legacy ecological site ID: {ecoclass['legacyId']}")
    sections: list[str] = ["\n".join(header)]
    for key, title in SECTION_TITLES.items():
        if key not in data or not data[key]:
            continue
        body = "\n".join(flatten_json(data[key], title))
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        if body:
            sections.append(body)
    return "\n\n".join(sections).strip()


def load_class_list(path: Path, timeout: int, attempts: int, refresh: bool) -> list[dict[str, Any]]:
    if path.exists() and not refresh:
        data = read_json(path)
    else:
        raw = fetch(f"{BASE}/services/downloads/esd/class-list.json", timeout=timeout, attempts=attempts)
        data = json.loads(raw.decode("utf-8"))
        write_json(path, data)
    ecoclasses = data.get("ecoclasses", [])
    if not isinstance(ecoclasses, list) or not ecoclasses:
        raise RuntimeError("class-list.json did not contain ecoclasses")
    return ecoclasses


def fetch_description(
    ecoclass: dict[str, Any],
    raw_dir: Path,
    timeout: int,
    attempts: int,
    refresh: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    mlra = ecoclass["geoUnit"]
    site_id = ecoclass["id"]
    raw_path = raw_dir / mlra / f"{site_id}.json"
    url = f"{BASE}/services/descriptions/esd/{quote(mlra)}/{quote(site_id)}.json?images=false"
    if raw_path.exists() and not refresh:
        data = read_json(raw_path)
    else:
        raw = fetch(url, timeout=timeout, attempts=attempts)
        data = json.loads(raw.decode("utf-8"))
        write_json(raw_path, data)
    return data, {
        "raw_locator": {
            "base": "nrcs_esd_ingest_raw_dir",
            "path": raw_path.relative_to(raw_dir).as_posix(),
        },
        "url": url,
    }


def rows_for_ecoclass(
    ecoclass: dict[str, Any],
    raw_dir: Path,
    timeout: int,
    attempts: int,
    refresh: bool,
    max_words: int,
    overlap_words: int,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    mlra = ecoclass["geoUnit"]
    site_id = ecoclass["id"]
    try:
        data, meta = fetch_description(ecoclass, raw_dir, timeout, attempts, refresh)
        text = description_text(data, ecoclass)
        chunks = chunk_text(text, max_words=max_words, overlap_words=overlap_words)
        if not chunks:
            raise RuntimeError(f"site {site_id} produced zero chunks from {len(text.split())} structured words")
        rows = []
        for index, chunk in enumerate(chunks, start=1):
            rows.append(
                {
                    "doc_id": f"nrcs_esd_json_{safe_id(site_id)}_{index:04d}",
                    "title": f"NRCS ecological site {site_id} ({mlra}): {ecoclass.get('name') or site_id} :: chunk {index}",
                    "text": chunk,
                    "source": f"{BASE}/catalogs/esd/{mlra}/{site_id}",
                    "source_id": "nrcs_edit_ecological_site_description_json",
                    "download_url": meta["url"],
                    "publisher": "USDA NRCS Ecological Site Description Catalog",
                    "license": "us_government_public_source_with_citation",
                    "sft_status": "not_raw_text_training_without_review",
                    "source_type": "regional_environment_profile",
                    "format": "json",
                    "mlra": mlra,
                    "ecological_site_id": site_id,
                    "ecological_site_legacy_id": ecoclass.get("legacyId"),
                    "ecological_site_name": ecoclass.get("name"),
                    "buckets": ["regional_environment_context", "soil_water", "crop_management", "ontology_query_expansion"],
                    "tags": ["NRCS", "MLRA", mlra, "ecological site", "soil water", "climate", "physiography"],
                    "chunk_index": index,
                    "extraction": {
                        "method": "official_edit_json",
                        "raw_locator": meta["raw_locator"],
                        "structured_words": len(text.split()),
                    },
                }
            )
        return site_id, rows, None
    except Exception as exc:  # noqa: BLE001 - caller records source-level failures.
        return site_id, [], {"mlra": mlra, "site_id": site_id, "error": repr(exc)}


def combine_shards(shard_dir: Path, output: Path) -> int:
    rows: list[dict[str, Any]] = []
    for shard in sorted(shard_dir.glob("*.jsonl")):
        rows.extend(read_jsonl(shard))
    write_jsonl(output, rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest NRCS EDIT ecological-site descriptions from official JSON services.")
    parser.add_argument("--mlra", action="append", default=[], help="MLRA code, for example 102B or 055A.")
    parser.add_argument("--all-mlras", action="store_true", help="Ingest every MLRA listed in the EDIT class-list service.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--shard-dir", type=Path, default=DEFAULT_SHARD_DIR)
    parser.add_argument("--class-list", type=Path, default=DEFAULT_CLASS_LIST)
    parser.add_argument("--max-sites-per-mlra", type=int, default=0)
    parser.add_argument("--max-mlras", type=int, default=0)
    parser.add_argument("--max-words", type=int, default=220)
    parser.add_argument("--overlap-words", type=int, default=35)
    parser.add_argument("--timeout", type=int, default=75)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--retry-missing",
        action="store_true",
        help="When a shard exists, fetch only ecological-site IDs absent from that shard and merge them.",
    )
    parser.add_argument("--refresh-class-list", action="store_true")
    parser.add_argument("--no-combine", action="store_true")
    parser.add_argument("--list-mlras", action="store_true", help="Only print discovered MLRA codes from the class-list service.")
    parser.add_argument("--fail-on-site-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ecoclasses = load_class_list(args.class_list, timeout=args.timeout, attempts=args.attempts, refresh=args.refresh_class_list)
    by_mlra: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ecoclass in ecoclasses:
        by_mlra[ecoclass["geoUnit"].upper()].append(ecoclass)
    mlras = sorted(by_mlra)

    if args.list_mlras:
        print(json.dumps({"mlras": mlras, "count": len(mlras), "ecoclasses": len(ecoclasses)}, indent=2))
        return 0

    if args.all_mlras:
        selected_mlras = mlras
    else:
        selected_mlras = [raw.upper() for raw in args.mlra]
    if not selected_mlras:
        parser.error("provide --mlra at least once or use --all-mlras")
    unknown = [mlra for mlra in selected_mlras if mlra not in by_mlra]
    if unknown:
        raise RuntimeError(f"unknown MLRA code(s): {unknown}")
    if args.max_mlras:
        selected_mlras = selected_mlras[: args.max_mlras]

    summary: dict[str, Any] = {
        "method": "official_edit_json",
        "mlras_requested": len(selected_mlras),
        "ecoclasses_available": len(ecoclasses),
        "workers": args.workers,
        "mlras": {},
        "chunks": 0,
        "failures": [],
    }
    rows: list[dict[str, Any]] = []
    for mlra in selected_mlras:
        shard_path = args.shard_dir / f"{mlra}.jsonl"
        existing_rows: list[dict[str, Any]] = []
        if shard_path.exists() and not args.force and not args.dry_run and not args.retry_missing:
            shard_rows = read_jsonl(shard_path)
            rows.extend(shard_rows)
            summary["mlras"][mlra] = {
                "sites_discovered": len(by_mlra[mlra]),
                "sites_ingested": len({row.get("ecological_site_id") for row in shard_rows}),
                "chunks": len(shard_rows),
                "status": "skipped_existing_shard",
            }
            print(f"{mlra}: skipped existing shard ({len(shard_rows)} chunks)", file=sys.stderr)
            continue

        sites = by_mlra[mlra]
        if shard_path.exists() and args.retry_missing and not args.force:
            existing_rows = read_jsonl(shard_path)
            existing_site_ids = {
                str(row.get("ecological_site_id") or "")
                for row in existing_rows
            }
            sites = [site for site in sites if str(site.get("id") or "") not in existing_site_ids]
        if args.max_sites_per_mlra:
            sites = sites[: args.max_sites_per_mlra]
        summary["mlras"][mlra] = {
            "sites_discovered": len(by_mlra[mlra]),
            "sites_selected": len(sites),
            "sites_previously_ingested": len(
                {
                    str(row.get("ecological_site_id") or "")
                    for row in existing_rows
                }
            ),
            "sites_ingested": len(
                {
                    str(row.get("ecological_site_id") or "")
                    for row in existing_rows
                }
            ),
            "sites_ingested_this_run": 0,
            "chunks": len(existing_rows),
            "status": (
                "pending"
                if args.dry_run
                else "retry_missing"
                if args.retry_missing and existing_rows
                else "ingested"
            ),
        }
        if args.dry_run:
            print(f"{mlra}: {len(sites)} ecological classes", file=sys.stderr)
            continue

        mlra_rows: list[dict[str, Any]] = list(existing_rows)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            future_map = {
                executor.submit(
                    rows_for_ecoclass,
                    site,
                    args.raw_dir,
                    args.timeout,
                    args.attempts,
                    args.force,
                    args.max_words,
                    args.overlap_words,
                ): site
                for site in sites
            }
            for future in concurrent.futures.as_completed(future_map):
                site = future_map[future]
                site_id, site_rows, failure = future.result()
                if failure:
                    summary["failures"].append(failure)
                    print(f"{mlra}/{site_id}: failed {failure['error']}", file=sys.stderr)
                    continue
                mlra_rows.extend(site_rows)
                summary["mlras"][mlra]["sites_ingested"] += 1
                summary["mlras"][mlra]["sites_ingested_this_run"] += 1
                summary["mlras"][mlra]["chunks"] += len(site_rows)
                print(f"{mlra}/{site_id}: {len(site_rows)} chunks", file=sys.stderr)
        mlra_rows.sort(key=lambda row: (str(row.get("ecological_site_id")), int(row.get("chunk_index", 0))))
        write_jsonl(shard_path, mlra_rows)
        rows.extend(mlra_rows)

    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return 0

    summary["chunks"] = len(rows)
    if not args.no_combine:
        summary["combined_chunks"] = combine_shards(args.shard_dir, args.output)
    write_json(args.summary, summary)
    print(json.dumps(summary, indent=2))
    if summary["failures"] and args.fail_on_site_error:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
