#!/usr/bin/env python3
"""Audit evidence-fabric closure and pre-upgrade benchmark equivalence.

This audit is deliberately independent of answer scoring.  It verifies that
the canonical full-system runs carry internally consistent evidence records
and that an evidence-only upgrade did not change model inputs, retrieval order,
outputs, or proxy diagnostics relative to a named reference database.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.evidence_contracts import canonical_json, sha256_text  # noqa: E402


SCHEMA_VERSION = "open_agronomy_agent.evidence_fabric_benchmark_audit.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _selected_documents(connection: sqlite3.Connection) -> dict[str, list[str]]:
    selected: dict[str, list[str]] = defaultdict(list)
    for row in connection.execute(
        "SELECT response_id, doc_id FROM retrieved_document ORDER BY response_id, rank"
    ):
        selected[str(row["response_id"])].append(str(row["doc_id"]))
    return dict(selected)


def _response_snapshot(connection: sqlite3.Connection) -> dict[tuple[str, str, str], dict[str, Any]]:
    documents = _selected_documents(connection)
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in connection.execute(
        """
        SELECT resp.response_id, resp.eval_id, resp.output_sha256,
               resp.exact_messages_json, resp.context_block, resp.score_json,
               run.mode, model.model_id
        FROM response resp
        JOIN benchmark_run run ON run.run_id=resp.run_id AND run.is_canonical=1
        JOIN model ON model.model_key=run.model_key
        ORDER BY model.model_id, run.mode, resp.eval_id
        """
    ):
        key = (str(row["model_id"]), str(row["mode"]), str(row["eval_id"]))
        rows[key] = {
            "output_sha256": str(row["output_sha256"]),
            "exact_messages_json": str(row["exact_messages_json"]),
            "context_block": row["context_block"],
            "score_json": str(row["score_json"]),
            "selected_document_order": documents.get(str(row["response_id"]), []),
        }
    return rows


def _validate_evidence_records(connection: sqlite3.Connection) -> dict[str, Any]:
    selected = _selected_documents(connection)
    violations: list[dict[str, Any]] = []
    packet_status = Counter()
    coverage_status = Counter()
    source_version_status = Counter()
    query = """
        SELECT ep.*, resp.output, resp.context_block, bc.question, model.model_id
        FROM evidence_packet ep
        JOIN response resp ON resp.response_id=ep.response_id
        JOIN benchmark_case bc ON bc.eval_id=resp.eval_id
        JOIN benchmark_run run ON run.run_id=resp.run_id AND run.is_canonical=1
        JOIN model ON model.model_key=run.model_key
        WHERE run.mode='agronomic_rag'
        ORDER BY model.model_id, resp.eval_id
    """
    rows = list(connection.execute(query))
    for row in rows:
        response_id = str(row["response_id"])
        frame = json.loads(row["question_frame_json"])
        packet = json.loads(row["packet_json"])
        answer = json.loads(row["validated_answer_json"]) if row["validated_answer_json"] else None
        record = {
            "schema_version": str(row["fabric_schema_version"]),
            "status": "captured",
            "question_frame": frame,
            "evidence_packet": packet,
            "validated_answer": answer,
        }

        def require(condition: bool, kind: str, **details: Any) -> None:
            if not condition:
                violations.append({"kind": kind, "response_id": response_id, **details})

        require(
            sha256_text(canonical_json(record)) == row["fabric_record_sha256"],
            "fabric_record_hash_mismatch",
        )
        require(frame.get("question_sha256") == sha256_text(str(row["question"])), "question_hash_mismatch")
        require(packet.get("packet_id") == row["packet_id"], "packet_id_mismatch")
        require(
            packet.get("question_frame_id") == frame.get("question_frame_id") == row["question_frame_id"],
            "question_frame_link_mismatch",
        )
        require(
            packet.get("selected_document_order", []) == selected.get(response_id, []),
            "selected_document_order_mismatch",
        )
        packed_sha = sha256_text(str(row["context_block"])) if row["context_block"] else None
        require(packet.get("packed_context_sha256") == packed_sha, "packed_context_hash_mismatch")
        require(answer is not None, "validated_answer_missing")
        if answer is not None:
            require(answer.get("answer_sha256") == sha256_text(str(row["output"])), "answer_hash_mismatch")
            require(answer.get("evidence_packet_id") == packet.get("packet_id"), "answer_packet_link_mismatch")
            require(answer.get("validated_answer_id") == row["validated_answer_id"], "answer_id_mismatch")

        assets = {item.get("asset_id") for item in packet.get("source_assets", [])}
        versions = {item.get("version_id") for item in packet.get("source_versions", [])}
        spans = {item.get("span_id") for item in packet.get("spans", [])}
        applicability = {item.get("applicability_id") for item in packet.get("applicability", [])}
        capsules = {item.get("capsule_id") for item in packet.get("capsules", [])}
        for version in packet.get("source_versions", []):
            source_version_status[str(version.get("capture_status") or "unspecified")] += 1
            require(version.get("asset_id") in assets, "source_version_asset_missing", entity_id=version.get("version_id"))
        for span in packet.get("spans", []):
            require(span.get("source_version_id") in versions, "span_source_version_missing", entity_id=span.get("span_id"))
            require(span.get("exact_text_sha256") == sha256_text(str(span.get("exact_text") or "")), "span_hash_mismatch", entity_id=span.get("span_id"))
        for capsule in packet.get("capsules", []):
            require(capsule.get("source_version_id") in versions, "capsule_source_version_missing", entity_id=capsule.get("capsule_id"))
            require(capsule.get("applicability_id") in applicability, "capsule_applicability_missing", entity_id=capsule.get("capsule_id"))
            for span_id in capsule.get("span_ids", []):
                require(span_id in spans, "capsule_span_missing", entity_id=capsule.get("capsule_id"), span_id=span_id)
        for state in packet.get("coverage", []):
            coverage_status[str(state.get("status") or "unspecified")] += 1
            for capsule_id in state.get("evidence_capsule_ids", []):
                require(capsule_id in capsules, "coverage_capsule_missing", slot_key=state.get("slot_key"), capsule_id=capsule_id)
        packet_status[str(packet.get("capture_status") or "unspecified")] += 1

    return {
        "record_count": len(rows),
        "violation_count": len(violations),
        "packet_capture_status": dict(sorted(packet_status.items())),
        "coverage_status": dict(sorted(coverage_status.items())),
        "source_version_capture_status": dict(sorted(source_version_status.items())),
        "violations": violations,
    }


def audit(database: Path, reference_database: Path) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    reference = sqlite3.connect(reference_database)
    reference.row_factory = sqlite3.Row
    evidence = _validate_evidence_records(connection)
    current_rows = _response_snapshot(connection)
    reference_rows = _response_snapshot(reference)
    current_keys = set(current_rows)
    reference_keys = set(reference_rows)
    fields = (
        "output_sha256",
        "exact_messages_json",
        "context_block",
        "score_json",
        "selected_document_order",
    )
    arms: dict[str, Counter[str]] = defaultdict(Counter)
    for key in sorted(current_keys & reference_keys):
        arm = f"{key[0]}::{key[1]}"
        arms[arm]["compared"] += 1
        for field in fields:
            arms[arm][f"{field}_exact"] += current_rows[key][field] == reference_rows[key][field]
    comparison = {
        arm: dict(sorted(counts.items()))
        for arm, counts in sorted(arms.items())
    }
    exact = (
        current_keys == reference_keys
        and all(
            counts.get(f"{field}_exact", 0) == counts["compared"]
            for counts in comparison.values()
            for field in fields
        )
    )
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_key_errors = len(list(connection.execute("PRAGMA foreign_key_check")))
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "database_path": str(database),
        "database_sha256": _sha256(database),
        "reference_database_path": str(reference_database),
        "reference_database_sha256": _sha256(reference_database),
        "integrity_check": integrity,
        "foreign_key_errors": foreign_key_errors,
        "evidence_closure": evidence,
        "reference_equivalence": {
            "current_response_count": len(current_rows),
            "reference_response_count": len(reference_rows),
            "missing_current_keys": ["::".join(key) for key in sorted(reference_keys - current_keys)],
            "unexpected_current_keys": ["::".join(key) for key in sorted(current_keys - reference_keys)],
            "exact": exact,
            "by_model_arm": comparison,
        },
        "answer_quality_scored_by_this_audit": False,
        "status": (
            "pass"
            if integrity == "ok"
            and foreign_key_errors == 0
            and evidence["violation_count"] == 0
            and exact
            else "fail"
        ),
        "boundary": (
            "A pass establishes database integrity, evidence-record referential closure, and exact equivalence "
            "to the named reference run. It does not establish agronomic correctness or grower utility."
        ),
    }
    connection.close()
    reference.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--reference-database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.database.resolve(), args.reference_database.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "integrity_check", "foreign_key_errors")}, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
