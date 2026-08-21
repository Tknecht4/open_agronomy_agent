#!/usr/bin/env python3
"""Acquire and freeze a rights-safe AgroQA external question set.

The upstream questions were collected from farmers in Uganda and the published
answers were prepared with agricultural-domain support.  They are not CCA exam
items, are not Canadian recommendations, and are not treated as verified gold.
The frozen subset is therefore a transfer and question-realism diagnostic only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import urllib.request
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_COMMIT = "91b5ae1c4a3779646907bf4dc5e507ae1efe366b"
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/JonaOmara/AgroQA-Dataset/"
    f"{UPSTREAM_COMMIT}/AgroQA%20Dataset.csv"
)
LICENSE_URL = (
    "https://raw.githubusercontent.com/JonaOmara/AgroQA-Dataset/"
    f"{UPSTREAM_COMMIT}/LICENSE"
)
UPSTREAM_SHA256 = "05f2775ce7ebfbe85cf24c86910f5761eefb1c1c12504233399231fca26d0e3f"
LICENSE_SHA256 = "a51ca1eea5706a5542e67289af5bbf9db7cdf54fda7511f425feadb9906dca8b"
SAMPLE_SEED = "open-agronomy-agroqa-external-v1"
ROWS_PER_CROP = 64
CROPS = ("beans", "cassava", "general", "maize")

RAW_PATH = ROOT / "data/eval/public/agroqa_dataset_91b5ae1c.csv"
LICENSE_PATH = ROOT / "data/eval/public/agroqa_dataset_LICENSE.txt"
OUTPUT_PATH = ROOT / "data/eval/public/agroqa_external_256_v1_source.jsonl"
AUDIT_PATH = ROOT / "data/eval/public/agroqa_external_256_v1_audit.json"

RISK_PATTERN = re.compile(
    r"\b(?:spray\w*|pesticid\w*|insecticid\w*|herbicid\w*|fungicid\w*|"
    r"chemical\w*|poison\w*|dosage\w*|dose\w*|\w+cide\w*|gramoxone|roundup|glyphosate)\b",
    re.IGNORECASE,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "OpenAgronomyAgent/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def normalized_text(value: str) -> str:
    return " ".join(value.replace("\x92", "'").replace("", "'").split())


def domain_alignment(question: str, answer: str) -> str:
    text = f"{question} {answer}".lower()
    if re.search(r"\b(fertili|nutrient|nitrogen|phosph|potassium|manure|compost|deficien)\w*\b", text):
        return "nutrient_management"
    if re.search(r"\b(soil|erosion|water|irrigat|drain|drought|moisture|terrac|mulch)\w*\b", text):
        return "soil_and_water_management"
    if re.search(r"\b(pest|disease|weed|virus|bacteria|fung|insect|rot|blight|mosaic)\w*\b", text):
        return "pest_management"
    return "crop_management"


def exclusion_reasons(
    *, question: str, answer: str, crop: str, seen: set[str], seen_tokens: list[set[str]]
) -> list[str]:
    reasons: list[str] = []
    normalized_question = re.sub(r"\W+", " ", question.lower()).strip()
    if crop not in CROPS:
        reasons.append("unsupported_crop_label")
    if normalized_question in seen:
        reasons.append("duplicate_question")
    tokens = set(normalized_question.split())
    if tokens and any(len(tokens & prior) / len(tokens | prior) >= 0.82 for prior in seen_tokens):
        reasons.append("near_duplicate_question")
    if not 5 <= len(question.split()) <= 45:
        reasons.append("question_length")
    if not 5 <= len(answer.split()) <= 80 or len(answer) < 25:
        reasons.append("answer_length")
    if RISK_PATTERN.search(f"{question} {answer}"):
        reasons.append("direct_chemical_or_pesticide_advice")
    if any(marker in answer.lower() for marker in ("i don't know", "not sure", "no idea")):
        reasons.append("non_answer")
    return reasons


def build_subset(raw: bytes) -> tuple[list[dict[str, object]], dict[str, object]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    accepted: dict[str, list[tuple[str, dict[str, object]]]] = {crop: [] for crop in CROPS}
    seen: set[str] = set()
    seen_tokens: dict[str, list[set[str]]] = {crop: [] for crop in CROPS}
    exclusions: Counter[str] = Counter()
    source_rows = 0
    for index, source in enumerate(reader):
        source_rows += 1
        crop = normalized_text(source.get("Crop") or "").lower()
        question = normalized_text(source.get("Question") or "")
        answer = normalized_text(source.get("Answer") or "")
        reasons = exclusion_reasons(
            question=question,
            answer=answer,
            crop=crop,
            seen=seen,
            seen_tokens=seen_tokens.get(crop, []),
        )
        if reasons:
            exclusions.update(reasons)
            continue
        seen.add(re.sub(r"\W+", " ", question.lower()).strip())
        seen_tokens[crop].append(set(re.sub(r"\W+", " ", question.lower()).strip().split()))
        domain = domain_alignment(question, answer)
        source_hash = hashlib.sha256(question.encode("utf-8")).hexdigest()
        row: dict[str, object] = {
            "eval_id": f"agroqa_{index:04d}",
            "question": question,
            "reference_answer": answer,
            "scoring_method": "reference_answer_token_f1",
            "task_family": "external_farmer_question_answering",
            "category": domain,
            "cca_domain_alignment": domain,
            "crop": crop,
            "jurisdiction": "Uganda (source collection setting)",
            "language": "English",
            "question_style": "real_farmer_question",
            "support_mode": "published_external_reference",
            "question_origin": "real_user_farmer_question_from_peer_reviewed_external_dataset",
            "reference_answer_status": "published_dataset_reference_not_independently_verified",
            "source_url": UPSTREAM_URL,
            "source_license": "MIT",
            "source_revision": UPSTREAM_COMMIT,
            "source_question_sha256": source_hash,
            "public_dataset_id": "JonaOmara/AgroQA-Dataset",
            "public_dataset_revision": UPSTREAM_COMMIT,
            "public_source_row_index": index,
            "source_use_boundary": (
                "External transfer diagnostic only. The source answer is not a Canadian recommendation, "
                "certification key, or independently revalidated agronomic gold answer."
            ),
            "safe_boundary": (
                "Do not apply Uganda-specific timing, varieties, rates, products, or regulatory assumptions "
                "to a Canadian field without local evidence."
            ),
            "required_patterns": [],
            "forbidden_patterns": [],
            "ask_for_patterns": [],
        }
        rank = hashlib.sha256(f"{SAMPLE_SEED}|{index}|{question}".encode("utf-8")).hexdigest()
        accepted[crop].append((rank, row))

    selected: list[dict[str, object]] = []
    eligible_counts = {crop: len(values) for crop, values in accepted.items()}
    for crop in CROPS:
        values = sorted(accepted[crop], key=lambda value: value[0])
        if len(values) < ROWS_PER_CROP:
            raise ValueError(f"not enough eligible {crop} rows: {len(values)}")
        selected.extend(row for _, row in values[:ROWS_PER_CROP])
    selected.sort(key=lambda row: str(row["eval_id"]))
    audit: dict[str, object] = {
        "schema_version": "open_agronomy_agent.external_source_audit.v1",
        "source_dataset": "JonaOmara/AgroQA-Dataset",
        "source_revision": UPSTREAM_COMMIT,
        "source_sha256": sha256_bytes(raw),
        "source_rows": source_rows,
        "sample_seed": SAMPLE_SEED,
        "selected_rows": len(selected),
        "selected_by_crop": dict(sorted(Counter(str(row["crop"]) for row in selected).items())),
        "selected_by_cca_alignment": dict(
            sorted(Counter(str(row["cca_domain_alignment"]) for row in selected).items())
        ),
        "eligible_by_crop": eligible_counts,
        "exclusions": dict(sorted(exclusions.items())),
        "reference_answer_status": "published_dataset_reference_not_independently_verified",
        "claim_boundary": (
            "This frozen sample measures response resemblance and cross-region transfer behavior. "
            "It does not measure CCA exam readiness or Canadian field-advisory validity."
        ),
    }
    return selected, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Use a previously downloaded pinned CSV.")
    parser.add_argument(
        "--license-input",
        type=Path,
        help="Pinned upstream license bytes required with --input when rebuilding.",
    )
    parser.add_argument("--acquire", action="store_true", help="Download the pinned CSV and MIT license.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if bool(args.input) == bool(args.acquire):
        raise ValueError("choose exactly one of --input or --acquire")
    if args.acquire and args.license_input:
        raise ValueError("--license-input cannot be combined with --acquire")
    if args.input and not args.check and not args.license_input:
        raise ValueError("--license-input is required with --input when rebuilding")
    raw = args.input.read_bytes() if args.input else fetch(UPSTREAM_URL)
    actual_sha = sha256_bytes(raw)
    if actual_sha != UPSTREAM_SHA256:
        raise ValueError(f"upstream SHA-256 mismatch: {actual_sha}")
    rows, audit = build_subset(raw)
    rendered = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    if args.check:
        if not RAW_PATH.exists() or sha256_bytes(RAW_PATH.read_bytes()) != UPSTREAM_SHA256:
            raise ValueError("frozen AgroQA CSV is missing or drifted")
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            raise ValueError("frozen AgroQA subset drift; rebuild it")
        if not AUDIT_PATH.exists() or json.loads(AUDIT_PATH.read_text(encoding="utf-8")) != audit:
            raise ValueError("AgroQA audit drift; rebuild it")
        print(json.dumps({"status": "pass", "rows": len(rows), "sha256": actual_sha}, sort_keys=True))
        return 0
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_bytes(raw)
    license_bytes = fetch(LICENSE_URL) if args.acquire else args.license_input.read_bytes()
    actual_license_sha = sha256_bytes(license_bytes)
    if actual_license_sha != LICENSE_SHA256:
        raise ValueError(f"upstream license SHA-256 mismatch: {actual_license_sha}")
    LICENSE_PATH.write_bytes(license_bytes)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    AUDIT_PATH.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "built", "rows": len(rows), "audit": audit}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
