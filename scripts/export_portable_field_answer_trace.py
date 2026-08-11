#!/usr/bin/env python3
"""Export one stored, model-bound field answer for portable-runtime evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

from agronomy_agent.answer_receipts import verify_answer_integrity_receipt


JSON_COLUMNS = ("system_state", "trace", "metadata")


def _load_turn(db_path: Path, turn_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT id, session_id, user_message, answer, answer_status, created_at,
                   system_state, trace, metadata
            FROM turns
            WHERE id = ?
            """,
            (turn_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError(f"turn not found: {turn_id}")
    turn = dict(row)
    turn["turn_id"] = turn.pop("id")
    for key in JSON_COLUMNS:
        value = turn.get(key)
        turn[key] = json.loads(value) if isinstance(value, str) else value
    return turn


def build_export(db_path: Path, turn_id: str) -> dict[str, Any]:
    turn = _load_turn(db_path, turn_id)
    trace = turn.get("trace") or {}
    lineage = ((trace.get("metadata") or {}).get("field_lineage") or {})
    identity = (turn.get("system_state") or {}).get("model_identity") or {}
    integrity = verify_answer_integrity_receipt(turn)
    errors: list[str] = []
    if integrity.get("status") != "verified":
        errors.append("stored answer-integrity receipt is not verified")
    if lineage.get("field_access_authorized") is not True:
        errors.append("turn is not authorized against a stored field")
    if not lineage.get("field_context_id") or not lineage.get("field_snapshot_sha256"):
        errors.append("turn does not carry exact field-context lineage")
    if identity.get("status") != "verified_runtime_receipt":
        errors.append("turn does not carry a verified runtime-model receipt")
    if not identity.get("response_model_id"):
        errors.append("turn response is not bound to a model identity")
    if errors:
        raise ValueError("; ".join(errors))
    turn["answer_integrity_receipt"] = integrity
    return {
        "schema_version": "open_agronomy_agent.portable_field_answer_trace.v1",
        "captured_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "network": {
            "mode": "offline",
            "external_calls_attempted": 0,
            "boundary": (
                "The portable receipt validator must independently bind this claim "
                "to the in-container public-egress probe."
            ),
        },
        "turn": turn,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite answer-trace evidence: {args.output}")
    payload = build_export(args.db, args.turn_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "pass",
                "output": str(args.output),
                "session_id": payload["turn"]["session_id"],
                "turn_id": payload["turn"]["turn_id"],
                "field_context_id": (
                    payload["turn"]["trace"]["metadata"]["field_lineage"][
                        "field_context_id"
                    ]
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
