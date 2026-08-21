from __future__ import annotations

import json
import sqlite3

from agronomy_agent.benchmark_report import _system_interface_results, render_markdown


def _interface_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE model (
            model_key TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            model_revision TEXT,
            model_config_sha256 TEXT
        );
        CREATE TABLE benchmark_run (
            run_id TEXT PRIMARY KEY,
            model_key TEXT NOT NULL,
            is_canonical INTEGER NOT NULL,
            system_variant TEXT NOT NULL,
            answer_profile TEXT NOT NULL
        );
        CREATE TABLE benchmark_case (
            eval_id TEXT PRIMARY KEY,
            ordinal INTEGER NOT NULL,
            eval_metadata_json TEXT NOT NULL
        );
        CREATE TABLE response (
            run_id TEXT NOT NULL,
            eval_id TEXT NOT NULL,
            output TEXT NOT NULL,
            exact_messages_json TEXT,
            context_block TEXT,
            field_context_json TEXT,
            metadata_json TEXT NOT NULL,
            generation_path TEXT
        );
        """
    )
    connection.execute(
        "INSERT INTO model VALUES (?, ?, ?, ?)",
        ("model-1", "Test model", "revision-1", "a" * 64),
    )
    connection.execute(
        "INSERT INTO benchmark_run VALUES (?, ?, ?, ?, ?)",
        ("run-1", "model-1", 1, "full_system", "benchmark"),
    )
    return connection


def _insert_interface_row(
    connection: sqlite3.Connection,
    *,
    ordinal: int,
    admission_policy: str,
    strong_primary: bool,
) -> None:
    eval_id = f"case-{ordinal}"
    connection.execute(
        "INSERT INTO benchmark_case VALUES (?, ?, ?)",
        (
            eval_id,
            ordinal,
            json.dumps({"benchmark_lane": "diagnostic", "language": "English"}),
        ),
    )
    handshake = (
        {
            "primary_doc_id": "primary-doc",
            "primary_query_coverage": 0.5,
            "primary_relevance_score": 7.0,
        }
        if strong_primary
        else {}
    )
    metadata = {
        "route": {
            "question_type": "conceptual",
            "risk_level": "low",
            "namespaces": ["general_agronomy"],
        },
        "evidence_fabric": {"record_sha256": "b" * 64, "evidence_packet": {}},
        "evidence_handshake": handshake,
        "context_admission": {
            "candidate_retrieval_present": True,
            "candidate_retrieval_admitted": True,
            "policy": admission_policy,
            "rejection_reason": None,
        },
        "expected_tools": [],
        "missing_expected_tools": [],
        "answer_verification": {"intervention_action": "preserve_draft"},
    }
    connection.execute(
        "INSERT INTO response VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "run-1",
            eval_id,
            "A direct bounded answer.\n\nA concise applicability boundary.",
            json.dumps(
                [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "question"},
                ]
            ),
            "",
            "{}",
            json.dumps(metadata),
            "generated_answer",
        ),
    )


def test_interface_report_separates_non_primary_admission_policy_paths() -> None:
    connection = _interface_database()
    _insert_interface_row(
        connection,
        ordinal=1,
        admission_policy="typed_capability_result",
        strong_primary=False,
    )
    _insert_interface_row(
        connection,
        ordinal=2,
        admission_policy="explicit_regional_context_interpretation",
        strong_primary=False,
    )
    _insert_interface_row(
        connection,
        ordinal=3,
        admission_policy="future_non_primary_policy",
        strong_primary=False,
    )
    _insert_interface_row(
        connection,
        ordinal=4,
        admission_policy="source_interpretation_primary",
        strong_primary=True,
    )

    rows = _system_interface_results(connection)

    assert len(rows) == 1
    row = rows[0]
    assert row["strong_primary_cases"] == 1
    assert "weak_retrieval_admitted" not in row
    assert row["context_admission_diagnostics"] == {
        "schema_version": "open_agronomy_agent.context_admission_diagnostics.v2",
        "trace_complete": True,
        "admitted_without_strong_primary": {
            "typed_capability_result": 1,
            "explicit_regional_context_interpretation": 1,
            "other": 1,
            "total": 3,
        },
    }

    markdown = render_markdown(
        {
            "run_status": "complete",
            "benchmark_id": "test-suite",
            "suite_rows": 4,
            "counts": {
                "models": 1,
                "responses": 4,
                "paired_responses": 0,
                "automated_triage_judgments": 0,
                "role_scoped_judge_assessments": 0,
            },
            "public_benchmark_score_claim_eligible": False,
            "lane_results": [],
            "evaluation_partition": "development",
            "system_interface_results": rows,
        }
    )
    assert "Weak retrieval admitted" not in markdown
    assert "typed / regional / other" in markdown
    assert "| 1 / 1 / 1 |" in markdown
