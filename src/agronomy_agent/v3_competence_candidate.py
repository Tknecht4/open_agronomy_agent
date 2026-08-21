"""Build the public/reference-grounded v3 competence-candidate inputs.

The external source is public and exposed.  This module pins its bytes, keeps
all rows, records explicit dispositions, and never upgrades a mentioned place
or reference answer into current authority.  The sealed-v3 protocol remains a
separate, fail-closed contract.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "open_agronomy_agent.v3_competence_candidate_bundle.v1"
CASE_SCHEMA_VERSION = "open_agronomy_agent.v3_competence_candidate_case.v1"
REGION_TERMS = (
    "Alberta",
    "Saskatchewan",
    "Manitoba",
    "Ontario",
    "Quebec",
    "Québec",
    "British Columbia",
    "Canada",
    "Karnataka",
    "Kenya",
    "Uganda",
    "Nigeria",
    "Senegal",
    "Bangladesh",
    "India",
    "Africa",
)
_CURRENT_AUTHORITY_RE = re.compile(
    r"\b(current|recent|latest|label|herbicide|fungicide|insecticide|pesticide|rate|regulation|legal)\b",
    re.IGNORECASE,
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def explicit_regions(text: str) -> list[str]:
    return [term for term in REGION_TERMS if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE)]


def load_external_csv(path: Path, contract: Mapping[str, Any]) -> list[dict[str, str]]:
    payload = path.read_bytes()
    if sha256_bytes(payload) != contract["sha256"]:
        raise ValueError("external dataset sha256 does not match the frozen contract")
    if len(payload) != int(contract["bytes"]):
        raise ValueError("external dataset byte count does not match the frozen contract")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(contract["columns"]):
            raise ValueError(f"external dataset columns changed: {reader.fieldnames}")
        rows = [{key: str(value or "").strip() for key, value in row.items()} for row in reader]
    if len(rows) != int(contract["rows"]):
        raise ValueError("external dataset row count does not match the frozen contract")
    if any(not row["question"] or not row["answer"] for row in rows):
        raise ValueError("external dataset contains an empty question or answer")
    if len({normalized_text(row["question"]) for row in rows}) != len(rows):
        raise ValueError("external dataset contains duplicate normalized questions")
    return rows


def project_external_rows(rows: Iterable[Mapping[str, str]], contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        question = str(row["question"]).strip()
        answer = str(row["answer"]).strip()
        regions = explicit_regions(question)
        authority_sensitive = bool(_CURRENT_AUTHORITY_RE.search(question))
        disposition = (
            "included_diagnostic_authority_sensitive"
            if authority_sensitive
            else "included_reference_grounded"
        )
        projected.append(
            {
                "schema_version": CASE_SCHEMA_VERSION,
                "eval_id": f"oa-v3cc-ext-{index + 1:04d}",
                "lane": "public_external_competence_candidate",
                "source_dataset_id": contract["dataset_id"],
                "source_revision": contract["revision"],
                "source_row_index": index,
                "question": question,
                "reference_answer": answer,
                "question_sha256": sha256_bytes(question.encode("utf-8")),
                "reference_answer_sha256": sha256_bytes(answer.encode("utf-8")),
                "explicit_regions": regions,
                "region_provenance": "explicit_question_text" if regions else "none",
                "authority_sensitive": authority_sensitive,
                "disposition": disposition,
                "claim_eligible": False,
                "reference_status": "published_dataset_reference_not_current_authority",
            }
        )
    return projected


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"JSONL row {line_number} is not an object: {path}")
        rows.append(row)
    return rows


def _regional_source_geography(row: Mapping[str, Any]) -> tuple[list[str], str]:
    jurisdiction = str(row.get("jurisdiction") or "").strip()
    if jurisdiction:
        return [jurisdiction], "source_case_explicit_jurisdiction"
    regions = explicit_regions(str(row.get("question") or ""))
    return regions, "explicit_question_text" if regions else "none"


def _round_robin_priority(
    rows: Iterable[Mapping[str, Any]], priority_jurisdictions: tuple[str, ...]
) -> list[Mapping[str, Any]]:
    ordered = sorted(rows, key=lambda row: str(row.get("eval_id") or ""))
    buckets = {
        jurisdiction: [row for row in ordered if str(row.get("jurisdiction") or "") == jurisdiction]
        for jurisdiction in priority_jurisdictions
    }
    selected: list[Mapping[str, Any]] = []
    while any(buckets.values()):
        for jurisdiction in priority_jurisdictions:
            if buckets[jurisdiction]:
                selected.append(buckets[jurisdiction].pop(0))
    selected_ids = {str(row.get("eval_id") or "") for row in selected}
    selected.extend(row for row in ordered if str(row.get("eval_id") or "") not in selected_ids)
    return selected


def select_regional_cases(
    path: Path,
    *,
    strata: Mapping[str, int],
    priority_jurisdictions: Iterable[str],
    count: int = 72,
    french: int = 12,
) -> list[dict[str, Any]]:
    """Select a deterministic exposed regional diagnostic from the successor suite.

    The suite is already project-authored and exposed.  Selection therefore
    creates no holdout claim.  Source IDs and reference points are retained;
    they are not rewritten into stronger evidence.
    """

    rows = _load_jsonl(path)
    eligible = [
        row
        for row in rows
        if str(row.get("question") or "").strip()
        and str(row.get("benchmark_lane") or "") != "field_history_lineage"
    ]
    if sum(int(value) for value in strata.values()) != count:
        raise ValueError("regional stratum quotas do not sum to the frozen case count")
    priority = tuple(str(value) for value in priority_jurisdictions)
    selected: list[tuple[Mapping[str, Any], str]] = []
    selected_ids: set[str] = set()
    for lane, quota_value in strata.items():
        quota = int(quota_value)
        if lane == "cross_jurisdiction_boundary":
            candidates = [
                row
                for row in eligible
                if row.get("wrong_jurisdiction_policy")
                and str(row.get("benchmark_lane") or "")
                in {"canadian_decision_quality", "canadian_advisory_transfer", "official_source_answer_boundary"}
            ]
        else:
            candidates = [row for row in eligible if str(row.get("benchmark_lane")) == lane]
        candidates = [row for row in candidates if str(row.get("eval_id") or "") not in selected_ids]
        if lane == "canadian_decision_quality":
            french_candidates = sorted(
                (row for row in candidates if str(row.get("language")) == "French"),
                key=lambda row: str(row.get("eval_id") or ""),
            )
            lane_rows = french_candidates[:french]
            remaining = [row for row in candidates if row not in lane_rows]
            lane_rows.extend(_round_robin_priority(remaining, priority)[: quota - len(lane_rows)])
        else:
            lane_rows = _round_robin_priority(
                (row for row in candidates if str(row.get("language")) != "French"),
                priority,
            )[:quota]
        if len(lane_rows) != quota:
            raise ValueError(f"regional stratum cannot satisfy quota: {lane}")
        selected.extend((row, lane) for row in lane_rows)
        selected_ids.update(str(row.get("eval_id") or "") for row in lane_rows)
    observed_french = sum(str(row.get("language")) == "French" for row, _ in selected)
    if observed_french != french:
        raise ValueError("successor suite cannot satisfy the frozen regional language quotas")
    projected: list[dict[str, Any]] = []
    for index, (source, construct_stratum) in enumerate(selected):
        record = dict(source)
        regions, region_provenance = _regional_source_geography(source)
        record.update(
            {
                "schema_version": CASE_SCHEMA_VERSION,
                "eval_id": f"oa-v3cc-reg-{index + 1:03d}",
                "source_eval_id": source.get("eval_id"),
                "lane": "canadian_regional_competence_candidate",
                "construct_stratum": construct_stratum,
                "disposition": "included_exposed_source_grounded_regression",
                "claim_eligible": False,
                "explicit_regions": regions,
                "region_provenance": region_provenance,
            }
        )
        projected.append(record)
    return projected


def exact_duplicate_audit(external_rows: Iterable[Mapping[str, Any]], comparison_paths: Iterable[Path]) -> dict[str, Any]:
    external = {normalized_text(str(row.get("question") or "")): str(row.get("eval_id")) for row in external_rows}
    matches: list[dict[str, str]] = []
    compared = 0
    for path in comparison_paths:
        if not path.is_file() or path.suffix != ".jsonl":
            continue
        for row in _load_jsonl(path):
            question = str(row.get("question") or "").strip()
            if not question:
                continue
            compared += 1
            external_id = external.get(normalized_text(question))
            if external_id:
                matches.append(
                    {
                        "external_eval_id": external_id,
                        "comparison_path": str(path),
                        "comparison_eval_id": str(row.get("eval_id") or "unknown"),
                    }
                )
    return {
        "schema_version": "open_agronomy_agent.v3_competence_duplicate_audit.v1",
        "method": "exact_normalized_question_text",
        "comparison_questions": compared,
        "match_count": len(matches),
        "matches": matches,
        "model_pretraining_exposure": "unknown",
    }


def build_bundle(
    *,
    config: Mapping[str, Any],
    source_csv: Path,
    regional_source: Path,
    comparison_paths: Iterable[Path],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    external_contract = config["external_dataset"]
    external = project_external_rows(load_external_csv(source_csv, external_contract), external_contract)
    regional = select_regional_cases(
        regional_source,
        strata=config["regional_strata"],
        priority_jurisdictions=config["regional_priority_jurisdictions"],
        count=int(config["regional_case_count"]),
        french=int(config["regional_language_counts"]["French"]),
    )
    duplicate_audit = exact_duplicate_audit(external, comparison_paths)
    dispositions = Counter(row["disposition"] for row in external)
    languages = Counter(str(row.get("language") or "English") for row in regional)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": config["benchmark_id"],
        "status": "frozen_inputs_verified",
        "claim_eligible": False,
        "sealed_v3_satisfied": False,
        "external_rows": len(external),
        "regional_rows": len(regional),
        "external_dispositions": dict(sorted(dispositions.items())),
        "regional_language_counts": dict(sorted(languages.items())),
        "external_cases_sha256": sha256_bytes(("\n".join(canonical_json(row) for row in external) + "\n").encode("utf-8")),
        "regional_cases_sha256": sha256_bytes(("\n".join(canonical_json(row) for row in regional) + "\n").encode("utf-8")),
        "duplicate_audit": duplicate_audit,
        "claim_boundary": config["evaluation_policy"]["claim_boundary"],
    }
    return manifest, external, regional
