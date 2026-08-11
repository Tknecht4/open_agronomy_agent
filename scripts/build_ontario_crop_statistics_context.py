#!/usr/bin/env python3
"""Build a bilingual, context-only RAG corpus from Ontario's open crop workbook."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.canada_sources import (  # noqa: E402
    load_canada_source_manifest,
    source_allowed_for,
    source_license_snapshot,
)


SOURCE_ID = "on_field_crop_production_current"
DEFAULT_MANIFEST = ROOT / "data" / "manifests" / "canada_agronomy_sources.json"
DEFAULT_RAW = ROOT / "data" / "raw" / "documents" / SOURCE_ID / "source.xlsx"
DEFAULT_OUTPUT = ROOT / "data" / "derived" / "rag" / "canada_agronomy_ontario_context_v1.jsonl"
DEFAULT_SUMMARY = (
    ROOT / "data" / "derived" / "rag" / "canada_agronomy_ontario_context_v1_summary.json"
)
SCHEMA_VERSION = "open_agronomy_agent.ontario_crop_statistics_context.v1"
EXTRACTOR_SCHEMA_VERSION = 1
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_SHEET_RE = re.compile(
    r"^(?P<year>20\d{2})\s+(?P<section>Grains and Oilseeds|Dry Field Beans|Fodder Crops)\s*:?\s*$"
)
_CROP_TRANSLATIONS = {
    "Winter Wheat": "Blé d'hiver",
    "Spring Wheat": "Blé de printemps",
    "Fall Rye": "Seigle",
    "Oats": "Avoine",
    "Barley": "Orge",
    "Mixed Grain": "Céréales mélangées",
    "Grain Corn": "Maïs grain",
    "Canola": "Canola",
    "Soybeans": "Soya",
    "Dry White Beans": "Haricots blancs secs",
    "Coloured Beans": "Haricots colorés",
    "Fodder Corn": "Maïs fourrager",
    "Hay": "Foin",
}
_SECTION_TRANSLATIONS = {
    "Grains and Oilseeds": "Céréales et oléagineuses",
    "Dry Field Beans": "Haricots secs",
    "Fodder Crops": "Cultures fourragères",
}
_HEADER_TRANSLATIONS = {
    "Crops": "Cultures",
    "Acres Seeded": "Acres cultivées",
    "Acres Harvested": "Acres récoltées",
    "Yield (bu/acre)": "Rendement (boisseaux à l'acre)",
    "Production ('000 bu)": "Production (milliers de boisseaux)",
    "Farm Value per bu. ($)": "Valeur à la ferme ($ par boisseau)",
    "Total Farm Value ($'000)": "Valeur à la ferme totale (milliers de dollars)",
    "Yield (cwt/acre)a": "Rendement (quintaux à l'acre)",
    "Production ('000 cwt)a": "Production (milliers de quintaux)",
    "Farm Value per cwt ($)": "Valeur à la ferme ($ par quintal)",
    "Yield (tons/acre)": "Rendement (tonnes à l'acre)",
    "Production ('000 tons)": "Production (milliers de tonnes)",
    "Farm Value per ton ($)": "Valeur à la ferme ($ par tonne)",
}
_SOURCE_CROP_NAMES = frozenset(_CROP_TRANSLATIONS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_MAIN_NS}}}si")
    ]


def _column_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha())
    result = 0
    for character in letters:
        result = result * 26 + ord(character.upper()) - ord("A") + 1
    return result - 1


def _cell_value(cell: ET.Element, shared: list[str]) -> str | int | float | None:
    value = cell.find(f"{{{_MAIN_NS}}}v")
    if value is None or value.text is None:
        return None
    raw = value.text
    if cell.get("t") == "s":
        return shared[int(raw)]
    if cell.get("t") == "str":
        return raw
    try:
        number = float(raw)
    except ValueError:
        return raw
    return int(number) if number.is_integer() else number


def read_sheet_rows(raw_path: Path, sheet_path: str = "xl/worksheets/sheet1.xml") -> dict[int, list[Any]]:
    """Read the first seven columns of a worksheet without external XLSX dependencies."""
    with zipfile.ZipFile(raw_path) as archive:
        shared = _shared_strings(archive)
        root = ET.fromstring(archive.read(sheet_path))
    rows: dict[int, list[Any]] = {}
    for row in root.findall(f".//{{{_MAIN_NS}}}row"):
        row_number = int(row.get("r") or 0)
        values: list[Any] = [None] * 7
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            index = _column_index(str(cell.get("r") or ""))
            if 0 <= index < len(values):
                values[index] = _cell_value(cell, shared)
        rows[row_number] = values
    return rows


def _clean_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_sections(rows: dict[int, list[Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    row_numbers = sorted(rows)
    for position, row_number in enumerate(row_numbers):
        heading = _clean_header(rows[row_number][0])
        match = _SHEET_RE.match(heading)
        if not match:
            continue
        next_section_row = next(
            (
                candidate
                for candidate in row_numbers[position + 1 :]
                if _SHEET_RE.match(_clean_header(rows[candidate][0]))
            ),
            max(row_numbers) + 1,
        )
        header_row = next(
            (
                candidate
                for candidate in range(row_number + 1, next_section_row)
                if _clean_header(rows.get(candidate, [None])[0]) == "Crops"
            ),
            None,
        )
        if header_row is None:
            raise ValueError(f"No table header found after row {row_number}: {heading}")
        headers = [_clean_header(value) for value in rows[header_row]]
        records: list[dict[str, Any]] = []
        end_row = header_row
        for candidate in range(header_row + 1, next_section_row):
            values = rows.get(candidate, [None] * 7)
            crop = _clean_header(values[0])
            if not crop:
                break
            if crop not in _SOURCE_CROP_NAMES:
                break
            records.append(
                {
                    "crop": crop,
                    "values": {
                        headers[index]: values[index]
                        for index in range(1, 7)
                        if headers[index]
                    },
                    "source_row": candidate,
                }
            )
            end_row = candidate
        if not records:
            raise ValueError(f"No crop records found after row {header_row}: {heading}")
        sections.append(
            {
                "year": int(match.group("year")),
                "section": match.group("section"),
                "heading_row": row_number,
                "header_row": header_row,
                "end_row": end_row,
                "records": records,
            }
        )
    return sections


def _format_number(value: Any, *, language: str) -> str:
    if value is None or value == "":
        return "non disponible" if language == "fr-CA" else "not available"
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ") if language == "fr-CA" else f"{value:,}"
    if isinstance(value, float):
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
        if language == "fr-CA":
            text = text.replace(",", "\u00a0").replace(".", ",")
        return text
    text = _clean_header(value)
    if text in {"-", "NA", "N/A"}:
        return "non disponible" if language == "fr-CA" else "not available"
    return text


def _record_text(section: dict[str, Any], record: dict[str, Any], *, language: str) -> str:
    year = int(section["year"])
    category_en = str(section["section"])
    crop = str(record["crop"])
    crop_label = _CROP_TRANSLATIONS[crop] if language == "fr-CA" else crop
    if language == "fr-CA":
        prefix = (
            f"Statistiques provinciales de l'Ontario sur les grandes cultures — {year}, "
            f"{_SECTION_TRANSLATIONS[category_en].lower()}, {crop_label} (unités impériales). "
            "Ces estimations à l'échelle provinciale servent uniquement de contexte régional; "
            "elles ne mesurent pas un champ particulier, ne prédisent pas son rendement et ne constituent "
            "pas une recommandation agronomique. "
        )
    else:
        prefix = (
            f"Ontario provincial field-crop statistics — {year}, {category_en.lower()}, {crop_label} "
            "(imperial units). "
            "These province-level estimates are regional context only; they do not measure an individual "
            "field, predict its yield, or constitute an agronomic recommendation. "
        )
    measurements = []
    for header, value in record["values"].items():
        label = _HEADER_TRANSLATIONS.get(header, header) if language == "fr-CA" else header
        measurements.append(f"{label}: {_format_number(value, language=language)}")
    statement = f"{crop_label} — {'; '.join(measurements)}."
    note = ""
    if crop == "Grain Corn":
        note = (
            " Les estimations du maïs-grain utilisent une teneur en humidité standard de 15,5 %."
            if language == "fr-CA"
            else " Grain-corn estimates use a standard moisture content of 15.5%."
        )
    elif crop == "Fodder Corn":
        note = (
            " Les estimations du maïs fourrager utilisent une humidité standard de 70 %."
            if language == "fr-CA"
            else " Fodder-corn estimates use a standard moisture content of 70%."
        )
    elif crop == "Hay":
        note = (
            " Les estimations du foin, y compris les balles, l'ensilage préfané et l'ensilage, sont "
            "converties à une teneur en humidité standard de 10 %."
            if language == "fr-CA"
            else " Hay estimates, including bales, haylage, and silage, are converted to a standard "
            "moisture content of 10%."
        )
    reference = (
        " Source citée dans le classeur : Statistique Canada, Série de rapports sur les grandes cultures."
        if language == "fr-CA"
        else " Workbook reference: Statistics Canada, Field Crop Reporting Series."
    )
    return f"{prefix}{statement}{note}{reference}"


def build_rows(
    *,
    source: dict[str, Any],
    sections: list[dict[str, Any]],
    raw_path: Path,
    manifest_path: Path,
    generated_at: str,
) -> list[dict[str, Any]]:
    raw_sha256 = _sha256(raw_path)
    manifest_sha256 = _sha256(manifest_path)
    normalized_sha256 = _sha256_text(json.dumps(sections, ensure_ascii=False, sort_keys=True))
    fetched_at = dt.datetime.fromtimestamp(
        raw_path.stat().st_mtime, tz=dt.timezone.utc
    ).isoformat(timespec="seconds")
    licence = source_license_snapshot(source)
    rows: list[dict[str, Any]] = []
    for section in sections:
        for record in section["records"]:
            for language in ("en-CA", "fr-CA"):
                text = _record_text(section, record, language=language)
                year = int(section["year"])
                category = str(section["section"])
                category_slug = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")
                crop_en = str(record["crop"])
                crop_name = _CROP_TRANSLATIONS[crop_en] if language == "fr-CA" else crop_en
                crop_slug = re.sub(r"[^a-z0-9]+", "_", crop_en.lower()).strip("_")
                language_slug = language[:2]
                title_category = _SECTION_TRANSLATIONS[category] if language == "fr-CA" else category
                rows.append(
                    {
                    "doc_id": f"{SOURCE_ID}_{year}_{category_slug}_{crop_slug}_{language_slug}",
                    "title": (
                        f"{source['title']} :: {year} :: {title_category} :: "
                        f"{crop_name} :: {language}"
                    ),
                    "text": text,
                    "source": source["url"],
                    "source_id": SOURCE_ID,
                    "download_url": source["download_url"],
                    "publisher": source["publisher"],
                    "license": licence["status"],
                    "license_snapshot": licence,
                    "sft_status": "excluded_context_only_statistics",
                    "source_type": "regional_environment_profile",
                    "document_type": "provincial_crop_statistics",
                    "format": "xlsx",
                    "region": ["Ontario"],
                    "jurisdiction": ["Ontario"],
                    "language": [language],
                    "currency": source["currency"],
                    "regulatory": source["regulatory"],
                    "content_risk_tags": [
                        "regional_statistics_not_field_truth",
                        "not_management_authority",
                        "volatile_source_requires_currency_check",
                    ],
                    "retrieval_policy": "context_only",
                    "crops": [crop_name],
                    "chunk_crops": [crop_name],
                    "chunk_topics": ["regional_context", "field_data", "economics"],
                    "buckets": source["buckets"],
                    "tags": sorted(
                        {
                            "Ontario",
                            language,
                            str(year),
                            category,
                            crop_name,
                            *source["buckets"],
                        }
                    ),
                    "chunk_index": len(rows) + 1,
                    "extraction": {
                        "sheet": "English",
                        "heading_row": section["heading_row"],
                        "header_row": section["header_row"],
                        "source_row": record["source_row"],
                        "normalization": (
                            "Numeric values and units come from the workbook's English sheet. French crop "
                            "and measurement labels are mapped from the workbook's French sheet to avoid "
                            "treating cached zero values for unavailable formula cells as observations."
                        ),
                    },
                    "lineage": {
                        "source_id": SOURCE_ID,
                        "source_record_id": source["source_record_id"],
                        "resource_record_id": source["resource_record_id"],
                        "canonical_url": source["url"],
                        "download_url": source["download_url"],
                        "fetched_at": fetched_at,
                        "raw_sha256": raw_sha256,
                        "raw_bytes": raw_path.stat().st_size,
                        "extracted_text_sha256": normalized_sha256,
                        "chunk_sha256": _sha256_text(text),
                        "manifest_sha256": manifest_sha256,
                        "ingested_at": generated_at,
                        "license_snapshot": licence,
                        "language": [language],
                        "jurisdiction": ["Ontario"],
                        "currency": source["currency"],
                        "content_risk_tags": [
                            "regional_statistics_not_field_truth",
                            "not_management_authority",
                            "volatile_source_requires_currency_check",
                        ],
                        "retrieval_policy": "context_only",
                        "extractor": {
                            "name": "scripts/build_ontario_crop_statistics_context.py",
                            "schema_version": EXTRACTOR_SCHEMA_VERSION,
                            "format": "xlsx",
                            "source_sheet": "English",
                        },
                    },
                    }
                )
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()

    manifest = load_canada_source_manifest(args.manifest)
    source = next(item for item in manifest["sources"] if item["id"] == SOURCE_ID)
    for use_case in ("download", "local_rag", "distributable_bundle"):
        if not source_allowed_for(source, use_case):
            raise SystemExit(f"{SOURCE_ID} is not eligible for {use_case}")
    generated_at = args.generated_at or _utc_now()
    sections = extract_sections(read_sheet_rows(args.raw))
    rows = build_rows(
        source=source,
        sections=sections,
        raw_path=args.raw,
        manifest_path=args.manifest,
        generated_at=generated_at,
    )
    _write_jsonl(args.output, rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_id": SOURCE_ID,
        "source_record_id": source["source_record_id"],
        "resource_record_id": source["resource_record_id"],
        "raw_path": str(args.raw.relative_to(ROOT)),
        "raw_sha256": _sha256(args.raw),
        "raw_bytes": args.raw.stat().st_size,
        "manifest_path": str(args.manifest.relative_to(ROOT)),
        "manifest_sha256": _sha256(args.manifest),
        "output_path": str(args.output.relative_to(ROOT)),
        "output_sha256": _sha256(args.output),
        "rows": len(rows),
        "years": sorted({int(section["year"]) for section in sections}),
        "sections": len(sections),
        "rows_by_language": dict(sorted(Counter(row["language"][0] for row in rows).items())),
        "rows_by_retrieval_policy": dict(
            sorted(Counter(row["retrieval_policy"] for row in rows).items())
        ),
        "license_snapshot": source_license_snapshot(source),
        "limitations": [
            "Province-level estimates are regional context, not field observations or yield expectations.",
            "The corpus cannot support management rates, thresholds, timing, diagnosis, or product selection.",
            "The 2026 tables are partial: seeded area is present while later-season values are unavailable.",
            "French labels come from the workbook's French sheet; numeric values come from the English sheet to avoid cached zero values for unavailable formula cells.",
        ],
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
