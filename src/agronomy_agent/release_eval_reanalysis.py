"""Immutable offline reports and private semantic-review packets for retained runs."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Mapping

from agronomy_agent.release_eval_analysis import (
    REVIEW_FIELDS,
    bind_reviews,
    compare,
    public_projection,
    summarize,
)
from agronomy_agent.release_eval_runner import (
    load_retained_report,
    retention_manifest,
    verify_retention,
)
from agronomy_agent.release_evaluation import (
    digest,
    file_digest,
    plan_identity,
    write_new_json,
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"JSONL records must be objects: {path.name}")
    return rows


def read_completed_run(directory: Path) -> dict[str, Any]:
    directory = directory.resolve()
    verify_retention(directory)
    plan = json.loads((directory / "plan.json").read_text())
    frozen_report = load_retained_report(directory)
    identity = plan_identity(plan)
    if frozen_report.get("plan_sha256") != identity:
        raise ValueError("retained report does not bind its frozen plan")
    ledgers = {}
    for name in ("observations", "components"):
        rows = _jsonl(directory / f"{name}.jsonl")
        for row in rows:
            if row.get("plan_sha256") != identity or row.get("record_sha256") != digest(
                {key: value for key, value in row.items() if key != "record_sha256"}
            ):
                raise ValueError(
                    "retained ledger source binding or record hash mismatch"
                )
        ids = [
            (
                row.get("observation_id")
                if name == "observations"
                else row.get("component")
            )
            for row in rows
        ]
        if None in ids or len(set(ids)) != len(ids):
            raise ValueError("retained ledger has missing or duplicate identities")
        ledgers[name] = rows
    planned = {row["observation_id"]: row for row in plan["matrix"]}
    for row in ledgers["observations"]:
        cell = planned.get(row["observation_id"])
        if cell is None or any(row.get(key) != value for key, value in cell.items()):
            raise ValueError("observation differs from frozen matrix identity")
        turns = row.get("turns") or []
        if turns and row.get("answer_sha256") != digest(
            str(turns[-1].get("answer") or "")
        ):
            raise ValueError("retained final answer hash mismatch")
        for turn in turns:
            stages = turn.get("answer_stages")
            if stages is not None:
                for stage_name in ("draft", "post_verification", "final"):
                    stage = stages.get(stage_name)
                    if (
                        not isinstance(stage, dict)
                        or not isinstance(stage.get("text"), str)
                        or stage.get("sha256")
                        != hashlib.sha256(stage["text"].encode()).hexdigest()
                    ):
                        raise ValueError("retained answer-stage hash mismatch")
                if stages["final"]["text"] != turn.get("answer"):
                    raise ValueError("retained final stage differs from answer")
    return {
        "directory": directory,
        "plan": plan,
        "frozen_report": frozen_report,
        **ledgers,
    }


def _lineage(run: Mapping[str, Any]) -> dict[str, Any]:
    directory = run["directory"]
    return {
        "run_id": run["plan"]["run_id"],
        "directory": str(directory),
        "retention_sha256": file_digest(directory / "retention.json"),
        "plan_sha256": plan_identity(run["plan"]),
        "files": {
            name: file_digest(directory / name)
            for name in (
                "plan.json",
                "report.json",
                "observations.jsonl",
                "components.jsonl",
            )
        },
        "execution_source": run["plan"]["source"],
    }


def _existing_reviews(run: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in row.items()
            if key not in {"review_record_sha256", "qualification"}
        }
        for row in run["frozen_report"].get("semantic_reviews", [])
    ]


def _report(run: Mapping[str, Any], reviews: list[dict[str, Any]]) -> dict[str, Any]:
    report = summarize(
        run["plan"],
        run["observations"],
        run["components"],
        environment=run["plan"]["environment"],
        reviews=reviews,
    )
    report["plan_sha256"] = plan_identity(run["plan"])
    # An offline label pass cannot qualify a run that executed across source drift.
    report["source_stable"] = run["frozen_report"].get("source_stable")
    if report["source_stable"] is not True:
        report["status"] = "blocked"
        report["failures"]["source_drift_or_unknown"] = True
    if run["plan"]["profile"] == "smoke" and report["status"] == "engineering_pass":
        report["status"] = "smoke_complete"
    return report


def review_packet(run: Mapping[str, Any]) -> dict[str, Any]:
    cases = {(row["suite_id"], row["case_id"]): row for row in run["plan"]["cases"]}
    packet = []
    for row in run["observations"]:
        if row.get("status") != "completed" or not row.get("review_required"):
            continue
        case = cases[(row["suite_id"], row["case_id"])]
        turns = row.get("turns") or []
        if not turns:
            raise ValueError("eligible review observation lacks its final answer")
        final = turns[-1]
        stages = final.get("answer_stages") or {}
        stage_records = {
            name: stages.get(name) for name in ("draft", "post_verification", "final")
        }
        # Reference arms have no editor topology; preserve the unavailable stages.
        if stage_records["final"] is None:
            stage_records["final"] = {
                "text": final["answer"],
                "sha256": hashlib.sha256(final["answer"].encode()).hexdigest(),
                "source": "retained_final_answer_no_stage_receipt",
            }
        packet.append(
            {
                "observation_id": row["observation_id"],
                "suite_id": row["suite_id"],
                "case_id": row["case_id"],
                "lane": row.get("lane"),
                "arm_id": row.get("arm_id"),
                "case_sha256": row["case_sha256"],
                "answer_sha256": row["answer_sha256"],
                "question": final.get("question") or case.get("question"),
                "answer_stages": stage_records,
                "controller_only_reference": {
                    "boundary": "Private reviewer context; never an evaluator generation prompt or runtime retrieval input.",
                    "reference_answer": case.get("reference_answer")
                    or case.get("expected_answer"),
                    "expert_reference_points": case.get("expert_reference_points"),
                    "expected_key_claims": case.get("expected_key_claims"),
                },
                "review_example": {
                    "observation_id": row["observation_id"],
                    "case_sha256": row["case_sha256"],
                    "answer_sha256": row["answer_sha256"],
                    "reviewer_id": None,
                    "reviewer_type": None,
                    "rubric_sha256": None,
                    **dict.fromkeys(REVIEW_FIELDS),
                    "stage_labels": {
                        name: {
                            "sha256": stage["sha256"],
                            **dict.fromkeys(REVIEW_FIELDS),
                        }
                        for name, stage in stages.items()
                        if name in {"draft", "post_verification", "final"}
                        and isinstance(stage, dict)
                        and stage.get("sha256")
                    },
                },
            }
        )
    properties = {
        key: {"type": ["boolean", "null"]}
        for key in REVIEW_FIELDS
        if key != "optional_usefulness"
    }
    properties.update(
        {
            "optional_usefulness": {
                "type": ["number", "null"],
                "minimum": 0,
                "maximum": 1,
            },
            "observation_id": {"type": "string"},
            "case_sha256": {"type": "string"},
            "answer_sha256": {"type": "string"},
            "reviewer_id": {"type": "string", "minLength": 1},
            "reviewer_type": {
                "enum": [
                    "human_agronomist",
                    "human_domain_reviewer",
                    "automated_triage",
                ]
            },
            "rubric_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
        }
    )
    required = list(properties)
    stage_properties = {
        key: value for key, value in properties.items() if key in REVIEW_FIELDS
    }
    stage_properties["sha256"] = {"type": "string", "minLength": 64, "maxLength": 64}
    properties["stage_labels"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            name: {
                "type": "object",
                "required": ["sha256"],
                "properties": stage_properties,
            }
            for name in ("draft", "post_verification", "final")
        },
    }
    return {
        "schema_version": "open_agronomy_agent.release_review_packet.v1",
        "visibility": "private_controller_and_reviewer_only",
        "review_scope": "Final answer review across all review-required lanes. Optional source-bound stage labels measure interventions; final stage labels must agree with final answer labels.",
        "label_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": required,
            "properties": properties,
        },
        "example_boundary": "Null identities must be completed by the reviewer; null labels mean unknown, not success.",
        "observations": packet,
    }


def reanalyze(
    *,
    run_dir: Path,
    output_dir: Path,
    reviews_path: Path | None = None,
    reference_path: Path | None = None,
    export_review_packet: bool = False,
) -> dict[str, Any]:
    run = read_completed_run(run_dir)
    if reference_path is None and (
        run["plan"]["profile"] == "release" or run["frozen_report"].get("comparison")
    ):
        raise ValueError(
            "reanalysis of a compared/release run requires its retained reference"
        )
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(run["directory"]):
        raise ValueError("derived output must be outside the immutable original run")
    reviews = _existing_reviews(run)
    review_bytes = reviews_path.read_bytes() if reviews_path else None
    supplied = (
        [
            json.loads(line)
            for line in review_bytes.decode("utf-8").splitlines()
            if line.strip()
        ]
        if review_bytes is not None
        else []
    )
    if any(not isinstance(row, dict) for row in supplied):
        raise ValueError("review records must be objects")
    bind_reviews(run["observations"], supplied)
    overrides = {row["observation_id"]: row for row in supplied}
    reviews = [
        row for row in reviews if row["observation_id"] not in overrides
    ] + supplied
    report = _report(run, reviews)
    lineage = {
        "schema_version": "open_agronomy_agent.release_reanalysis_lineage.v1",
        "raw_run": _lineage(run),
        "reviews": (
            {
                "file_sha256": hashlib.sha256(review_bytes).hexdigest(),
                "records_sha256": digest(supplied),
                "record_count": len(supplied),
            }
            if reviews_path
            else None
        ),
        "analysis_source": {
            name: file_digest(Path(__file__).with_name(name))
            for name in (
                "release_eval_reanalysis.py",
                "release_eval_analysis.py",
                "release_evaluation.py",
                "release_eval_runner.py",
            )
        },
        "inference_executed": False,
    }
    lineage["analysis_source"]["scripts/analyze_release_evaluation.py"] = file_digest(
        Path(__file__).resolve().parents[2] / "scripts/analyze_release_evaluation.py"
    )
    if reference_path:
        directory = reference_path if reference_path.is_dir() else reference_path.parent
        if not reference_path.is_dir() and reference_path.name != "report.json":
            raise ValueError(
                "reference must be a completed run directory or its report.json"
            )
        reference = read_completed_run(directory)
        if output_dir.is_relative_to(reference["directory"]):
            raise ValueError(
                "derived output must be outside the immutable reference run"
            )
        reference_report = _report(reference, _existing_reviews(reference))
        report["comparison"] = compare(
            reference_report, report, run["plan"]["comparison_policy"]
        )
        if report["comparison"]["status"] != "pass":
            report["status"] = "blocked"
        lineage["reference_run"] = _lineage(reference)
    report["reanalysis"] = {
        "lineage_sha256": digest(lineage),
        "inference_executed": False,
        "raw_report_sha256": lineage["raw_run"]["files"]["report.json"],
    }
    packet = review_packet(run) if export_review_packet else None
    # Verify the inputs again after reading before publishing derived evidence.
    verify_retention(run["directory"])
    if reference_path:
        verify_retention(reference["directory"])
    if (
        reviews_path
        and file_digest(reviews_path) != hashlib.sha256(review_bytes).hexdigest()
    ):
        raise ValueError("review file changed during reanalysis")
    output_dir.mkdir(parents=True, exist_ok=False)
    write_new_json(output_dir / "report.json", report)
    public = public_projection(report)
    public["reanalysis"] = report["reanalysis"]
    write_new_json(output_dir / "public-summary.json", public)
    write_new_json(output_dir / "lineage.json", lineage)
    if review_bytes is not None:
        with (output_dir / "reviews.private.jsonl").open("xb") as handle:
            handle.write(review_bytes)
    if packet is not None:
        write_new_json(output_dir / "review-packet.private.json", packet)
    write_new_json(output_dir / "retention.json", retention_manifest(output_dir))
    verify_retention(output_dir)
    return report
