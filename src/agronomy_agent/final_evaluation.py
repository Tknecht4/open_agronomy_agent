"""Compile and account for the required question bank in a final evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

CATALOG_SCHEMA = "open_agronomy_agent.final_evaluation_catalog.v1"
CATALOG_PATH = Path("configs/final_evaluation_suite_v1.json")
FINAL_SUITE_ID = "open_agronomy_final_evaluation_v1"
CASE_FORMATS = {"scenario", "legacy_domain", "prepared_question"}
COMPONENT_INPUTS = {
    "field_data": "data/eval/field_data_pilot_v1/gold_cases.jsonl",
    "retrieval": "data/eval/offline_corpus_retrieval.jsonl",
}


def final_registry(catalog: Mapping[str, Any], *, root: Path) -> dict[str, Any]:
    from agronomy_agent.release_evaluation import checked_path, strict_json

    if catalog.get("suite_id") != FINAL_SUITE_ID:
        raise ValueError("invalid final evaluation suite identity")
    entries = catalog["entries"]
    by_id = {entry["id"]: entry for entry in entries}
    paths = {entry["path"] for entry in entries}
    if len(entries) != len(by_id) or len(entries) != len(paths):
        raise ValueError("final evaluation catalog requires unique suite IDs and paths")
    discovered = {
        path.relative_to(root).as_posix() for path in (root / "data/eval").rglob("*.jsonl")
    }
    uncataloged = discovered - paths
    if uncataloged:
        raise ValueError(f"final evaluation inputs lack a catalog entry: {sorted(uncataloged)}")

    inventory = []
    suites = []
    rows_by_suite = {}
    for entry in entries:
        suite_id, path, execution = (entry[key] for key in ("id", "path", "execution"))
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", suite_id):
            raise ValueError("invalid final evaluation catalog entry ID")
        if not path.startswith(("data/eval/", "outputs/")):
            raise ValueError(f"invalid final evaluation input location: {suite_id}")
        if path.startswith("outputs/") and not entry.get("sha256"):
            raise ValueError(f"retained final evaluation input requires a SHA-256 pin: {suite_id}")
        raw = checked_path(root, path).read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if entry.get("sha256", actual_hash) != actual_hash:
            raise ValueError(f"final evaluation input hash changed: {suite_id}")
        rows = [strict_json(line) for line in raw.splitlines() if line.strip()]
        if type(entry["rows"]) is not int or not rows or len(rows) != entry["rows"]:
            raise ValueError(f"final evaluation input row count changed: {suite_id}")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"final evaluation input must contain JSON objects: {suite_id}")
        rows_by_suite[suite_id] = rows
        inventory.append({**entry, "sha256": actual_hash})
        if execution in CASE_FORMATS:
            suites.append({
                "id": suite_id,
                "path": path,
                "format": execution,
                "profiles": ["baseline", "release"],
                "exposure": "exposed_development",
                "required": True,
            })
        elif execution in COMPONENT_INPUTS:
            if path != COMPONENT_INPUTS[execution]:
                raise ValueError(f"final evaluation component input mismatch: {suite_id}")
            if execution == "retrieval":
                blocked = sorted(row["case_id"] for row in rows if row["case_status"] != "active")
                if blocked != entry.get("expected_blocked_case_ids", []):
                    raise ValueError(f"final evaluation retrieval dispositions changed: {suite_id}")
        elif execution != "source_copy":
            raise ValueError(f"unknown final evaluation execution path: {execution}")

    for entry in inventory:
        if entry["execution"] != "source_copy":
            continue
        target = entry["covered_by"]
        if by_id[target]["execution"] not in CASE_FORMATS:
            raise ValueError("a final evaluation source copy must map to an executable suite")

        def question_references(suite_id: str) -> Counter:
            return Counter(
                (row["question"], row["reference_answer"]) for row in rows_by_suite[suite_id]
            )

        if question_references(entry["id"]) != question_references(target):
            raise ValueError(f"final evaluation source copy differs: {entry['id']}")

    registry = json.loads(checked_path(root, "configs/release_evaluation_v1.json").read_bytes())
    return {
        **registry,
        "suite_id": FINAL_SUITE_ID,
        "suites": suites,
        "arms": ["raw_model", "production_full"],
        "whole_run_timeout_seconds": catalog["whole_run_timeout_seconds"],
        "final_inventory": inventory,
    }


def final_coverage(
    inventory: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    components: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Report coverage against the entire catalog, including non-model components."""
    counts = defaultdict(Counter)
    case_ids = defaultdict(set)
    for row in observations:
        suite = counts[row["suite_id"]]
        suite["planned"] += 1
        suite[row["status"]] += 1
        case_ids[row["suite_id"]].add(row["case_id"])
    component_by_id = {row["component"]: row for row in components}
    results = {}
    for entry in inventory:
        suite_id, execution = entry["id"], entry["execution"]
        result = {"execution": execution, "case_rows": entry["rows"]}
        if execution in CASE_FORMATS:
            suite = counts[suite_id]
            result.update(
                planned_observations=suite["planned"],
                completed_observations=suite["completed"],
                missing_observations=suite["missing"],
                failed_observations=suite["planned"] - suite["completed"] - suite["missing"],
                complete=len(case_ids[suite_id]) == entry["rows"] and suite["completed"] == suite["planned"],
            )
        elif execution in COMPONENT_INPUTS:
            component = component_by_id.get(execution, {})
            metrics = component.get("metrics", {})
            observed = metrics.get("cases")
            blocked = metrics.get("blocked_case_ids", [])
            expected_blocked = entry.get("expected_blocked_case_ids", [])
            result.update(
                observed_case_rows=observed,
                blocked_case_ids=blocked,
                complete=(
                    component.get("status") == "pass"
                    and observed == entry["rows"] - len(expected_blocked)
                    and blocked == expected_blocked
                ),
            )
        else:
            result.update(covered_by=entry["covered_by"])
        results[suite_id] = result
    for result in results.values():
        if "covered_by" in result:
            result["complete"] = results[result["covered_by"]]["complete"]
    return {
        "status": "complete" if all(row["complete"] for row in results.values()) else "incomplete",
        "suites": results,
    }
