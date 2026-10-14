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


def read_completed_run(
    directory: Path, *, _seen: frozenset[Path] = frozenset()
) -> dict[str, Any]:
    directory = directory.resolve()
    if directory in _seen or len(_seen) >= 32:
        raise ValueError("cyclic or excessive derived-analysis lineage")
    seen = _seen | {directory}
    verify_retention(directory)
    if not (directory / "plan.json").is_file():
        return _read_derived(directory, seen)
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
        if cell is None or any(row.get(key) != value for key, value in cell.items() if key not in {"comparison_cohort", "task_input_sha256", "task_input_status"}):
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
        "input_directory": directory,
        "plan": plan,
        "frozen_report": frozen_report,
        **ledgers,
    }


def _analysis_binding(directory: Path) -> dict[str, Any]:
    return {
        "directory": str(directory),
        "retention_sha256": file_digest(directory / "retention.json"),
        "report_sha256": file_digest(directory / "report.json"),
        "lineage_sha256": file_digest(directory / "lineage.json"),
    }


def _verify_analysis_binding(binding: Mapping[str, Any]) -> Path:
    directory = Path(binding["directory"]).resolve()
    if _analysis_binding(directory) != binding:
        raise ValueError("derived parent/reference analysis binding mismatch")
    return directory


def _read_derived(directory: Path, seen: frozenset[Path]) -> dict[str, Any]:
    lineage = json.loads((directory / "lineage.json").read_text())
    report = json.loads((directory / "report.json").read_text())
    if (
        lineage.get("schema_version")
        != "open_agronomy_agent.release_reanalysis_lineage.v1"
        or lineage.get("inference_executed") is not False
    ):
        raise ValueError("unsupported derived-analysis lineage")
    analysis_hash = digest(lineage.get("analysis_source", {}))
    if (
        lineage.get("analysis_source_sha256") != analysis_hash
        or report.get("reanalysis", {}).get("derived_analysis_sha256") != analysis_hash
    ):
        raise ValueError("derived analysis-source binding mismatch")
    if report.get("reanalysis", {}).get("lineage_sha256") != digest(lineage):
        raise ValueError("derived report/lineage binding mismatch")
    raw = read_completed_run(Path(lineage["raw_run"]["directory"]), _seen=seen)
    if (
        raw["input_directory"] != raw["directory"]
        or _lineage(raw) != lineage["raw_run"]
    ):
        raise ValueError("derived raw-run retention/file/plan binding mismatch")
    inherited = raw
    if lineage.get("parent_analysis"):
        parent_directory = _verify_analysis_binding(lineage["parent_analysis"])
        inherited = read_completed_run(parent_directory, _seen=seen)
        if _lineage(inherited) != lineage["raw_run"]:
            raise ValueError("parent analysis belongs to another raw run")
    supplied = []
    if lineage.get("reviews"):
        review_path = directory / "reviews.private.jsonl"
        supplied = _jsonl(review_path)
        binding = lineage["reviews"]
        if (
            file_digest(review_path) != binding["file_sha256"]
            or digest(supplied) != binding["records_sha256"]
            or len(supplied) != binding["record_count"]
        ):
            raise ValueError("derived retained review binding mismatch")
    bind_reviews(raw["observations"], supplied)
    override_ids = {row["observation_id"] for row in supplied}
    reviews = [
        row
        for row in _existing_reviews(inherited)
        if row["observation_id"] not in override_ids
    ] + supplied
    expected = _report(raw, reviews)
    if lineage.get("reference_run"):
        if lineage.get("reference_analysis"):
            reference_directory = _verify_analysis_binding(
                lineage["reference_analysis"]
            )
        else:
            reference_directory = Path(lineage["reference_run"]["directory"])
        reference = read_completed_run(reference_directory, _seen=seen)
        if _lineage(reference) != lineage["reference_run"]:
            raise ValueError("derived reference raw-run binding mismatch")
        expected["comparison"] = compare(
            reference["frozen_report"], expected, raw["plan"]["comparison_policy"]
        )
        if expected["comparison"]["status"] != "pass":
            expected["status"] = "blocked"
    elif raw["plan"]["profile"] == "release" or inherited["frozen_report"].get(
        "comparison"
    ):
        raise ValueError("derived comparison lacks retained reference binding")
    if {key: value for key, value in report.items() if key != "reanalysis"} != expected:
        raise ValueError(
            "derived report differs from controlled retained-evidence analysis"
        )
    if (
        report["reanalysis"].get("raw_report_sha256")
        != lineage["raw_run"]["files"]["report.json"]
        or report["reanalysis"].get("inference_executed") is not False
    ):
        raise ValueError("derived raw-report binding mismatch")
    return {
        **raw,
        "input_directory": directory,
        "frozen_report": report,
        "derived_lineage": lineage,
    }


def load_reference_report(path: Path) -> dict[str, Any]:
    """Validate an original or derived retained report without rerunning inference."""
    path = path.resolve()
    if not path.is_dir() and path.name != "report.json":
        raise ValueError("reference must be a retained directory or its report.json")
    return read_completed_run(path if path.is_dir() else path.parent)["frozen_report"]


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
                *([name for name in ("closeout.json", "closeout-failure.json", "terminal-closeout.json") if (directory / name).is_file()]
                  if "bounded_stop_policy" in run["plan"] else []),
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
    bounded = run["frozen_report"].get("bounded_execution")
    if bounded is not None:
        report["bounded_execution"] = bounded
        if bounded.get("status") == "terminal_stopped":
            report["status"] = "blocked"
            report["failures"]["bounded_execution_stop"] = bounded.get("stop")
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
    model_rubrics_path: Path | None = None,
    criterion_reviews_path: Path | None = None,
    model_policy_path: Path | None = None,
) -> dict[str, Any]:
    run = read_completed_run(run_dir)
    prospective = run["plan"].get("controller_inputs", {}).get("files", {})
    if model_rubrics_path is None and "rubrics" in prospective:
        model_rubrics_path = run["directory"] / "model-rubrics.private.jsonl"
    if model_policy_path is None and "policy" in prospective:
        model_policy_path = run["directory"] / "model-policy.private.json"
    if reference_path is None and run.get("derived_lineage", {}).get("reference_run"):
        reference_binding = (
            run["derived_lineage"].get("reference_analysis")
            or run["derived_lineage"]["reference_run"]
        )
        reference_path = Path(reference_binding["directory"])
    if reference_path is None and (
        run["plan"]["profile"] == "release" or run["frozen_report"].get("comparison")
    ):
        raise ValueError(
            "reanalysis of a compared/release run requires its retained reference"
        )
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(run["directory"]) or output_dir.is_relative_to(
        run["input_directory"]
    ):
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
    if run["input_directory"] != run["directory"]:
        lineage["parent_analysis"] = _analysis_binding(run["input_directory"])
    lineage["analysis_source"]["scripts/analyze_release_evaluation.py"] = file_digest(
        Path(__file__).resolve().parents[2] / "scripts/analyze_release_evaluation.py"
    )
    lineage["analysis_source_sha256"] = digest(lineage["analysis_source"])
    if reference_path:
        directory = reference_path if reference_path.is_dir() else reference_path.parent
        if not reference_path.is_dir() and reference_path.name != "report.json":
            raise ValueError(
                "reference must be a completed run directory or its report.json"
            )
        reference = read_completed_run(directory)
        if output_dir.is_relative_to(
            reference["directory"]
        ) or output_dir.is_relative_to(reference["input_directory"]):
            raise ValueError(
                "derived output must be outside the immutable reference run"
            )
        reference_report = reference["frozen_report"]
        report["comparison"] = compare(
            reference_report, report, run["plan"]["comparison_policy"]
        )
        if report["comparison"]["status"] != "pass":
            report["status"] = "blocked"
        lineage["reference_run"] = _lineage(reference)
        if reference["input_directory"] != reference["directory"]:
            lineage["reference_analysis"] = _analysis_binding(
                reference["input_directory"]
            )
    report["reanalysis"] = {
        "lineage_sha256": digest(lineage),
        "derived_analysis_sha256": lineage["analysis_source_sha256"],
        "inference_executed": False,
        "raw_report_sha256": lineage["raw_run"]["files"]["report.json"],
    }
    packet = review_packet(run) if export_review_packet else None
    model_metrics = None
    if any((model_rubrics_path, criterion_reviews_path, model_policy_path)):
        model_metrics = _model_metrics_bundle(
            *_model_matrix(run),
            rubrics_path=model_rubrics_path,
            reviews_path=criterion_reviews_path,
            policy_path=model_policy_path,
        )
    # Verify the inputs again after reading before publishing derived evidence.
    verify_retention(run["directory"])
    verify_retention(run["input_directory"])
    if reference_path:
        verify_retention(reference["directory"])
        verify_retention(reference["input_directory"])
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
    if model_metrics is not None:
        _write_model_metrics(output_dir, model_metrics, raw_binding=_lineage(run))
    write_new_json(output_dir / "retention.json", retention_manifest(output_dir))
    verify_retention(output_dir)
    return report


def _merge_termination(recorded: Mapping[str, Any] | None, derived: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Known per-stage evidence survives missing duplicates; attempts beat N/A."""
    from agronomy_agent.release_eval_executor import generation_termination
    if recorded is None or derived is None:
        return derived if recorded is None else recorded
    grouped = {}
    for evidence in (recorded, derived):
        for stage in evidence["stages"]:
            grouped.setdefault((stage["turn_index"], stage["stage"]), []).append(stage)
    stages = []
    for (index, name), values in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1] == "editor", item[0][1])):
        reasons = {value["finish_reason"] for value in values if value["required"] and value["status"] == "observed"}
        if len(reasons) > 1:
            raise ValueError("contradictory recorded and derived terminal stage")
        stages.append({"turn_index": index, "stage": name,
                       **generation_termination({"finish_reason": next(iter(reasons), None)},
                                                required=any(value["required"] for value in values))})
    required = [stage for stage in stages if stage["required"]]
    status = "not_applicable" if stages and not required else "unknown" if not required or any(stage["status"] == "unknown" for stage in required) else "observed"
    flag = True if any(stage["truncated"] is True for stage in required) else None if status in {"unknown", "not_applicable"} else False
    return {"schema_version": "open_agronomy_agent.generation_termination.v1", "stages": stages,
            "status": status, "truncated": flag, "finish_reason": "length" if flag is True else "stop" if flag is False else None}


def _model_matrix(run: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Project recorded identities only; do not infer a matched comparison cohort."""
    from agronomy_agent.release_eval_executor import observation_termination
    from agronomy_agent.release_eval_model_metrics import termination_evidence
    from agronomy_agent.release_evaluation import validate_task_exposure, validate_worker_runtime, planned_analysis_condition
    plan = run["plan"]
    model = plan["model"]
    matrix = []
    recorded_rows = {row["observation_id"]: row for row in run["observations"]}
    for cell in plan["matrix"]:
        expected = planned_analysis_condition(plan, cell)
        row = recorded_rows.get(cell["observation_id"], {})
        observed = row.get("analysis_condition")
        if observed is not None:
            if not isinstance(observed, dict) or set(observed) - set(expected):
                raise ValueError("invalid observed analysis condition")
            source_bound = "controller_inputs" in plan or expected["source_sha256"] is not None and expected["model_config_sha256"] is not None
            if source_bound and any(value is not None and expected[key] is not None and value != expected[key] for key, value in observed.items()):
                raise ValueError("observed analysis condition differs from frozen plan")
        for key, value in (("model_id", model["id"]), ("model_revision", model["revision"]), ("backend_id", cell["backend"])):
            if row.get(key) is not None and row[key] != value:
                raise ValueError("observed model identity differs: " + key)
        condition = observed if observed is not None else None if "controller_inputs" in plan else expected
        matrix.append({**cell, "model_id": model["id"], "model_revision": model["revision"], "backend_id": cell["backend"],
                       "analysis_condition": condition,
                       **({"planned_analysis_condition": expected} if "controller_inputs" in plan else {})})
    cells = {cell["observation_id"]: cell for cell in matrix}
    observations = []
    for row in run["observations"]:
        cell = cells[row["observation_id"]]
        for key in ("case_id", "case_sha256", "suite_id", "arm_id", "trial_id", "backend"):
            if key in row and row[key] != cell.get(key):
                raise ValueError("retained observation plan identity mismatch: " + key)
        task_fields = {key: row.get(key) for key in ("comparison_cohort", "task_input_sha256", "task_input_status")}
        if "controller_inputs" in plan:
            runtime_status = validate_worker_runtime(plan, cell, row)
            if runtime_status != "verified_worker_config_bytes" and row.get("analysis_condition") is not None:
                # Keep the original claim visible, but missing actual config
                # evidence cannot be promoted to a complete observed condition.
                cell["analysis_condition"] = None
            case = next(case for case in plan["cases"] if case["case_id"] == cell["case_id"] and case["suite_id"] == cell["suite_id"])
            binding = validate_task_exposure(case, cell["arm_id"], row.get("task_exposure"))
            if row.get("task_input_sha256") is not None and (row["task_input_sha256"] != binding["task_input_sha256"] or row["task_input_sha256"] != cell.get("task_input_sha256")):
                raise ValueError("recorded task binding contradicts exposure/plan")
            if row.get("comparison_cohort") is not None and (binding["task_input_sha256"] is None or row["comparison_cohort"] != plan.get("comparison_cohort")):
                raise ValueError("recorded comparison cohort contradicts frozen inputs")
            task_fields["task_input_status"] = binding["status"] if row.get("task_input_sha256") is not None else "unknown_recorded_binding"
        turns = row.get("turns") or []
        derived_termination = observation_termination(turns) if turns else None
        recorded_terminal = termination_evidence(row)
        derived_terminal = termination_evidence({"termination": derived_termination})
        if (recorded_terminal["truncated"] is not None and derived_terminal["truncated"] is not None
                and recorded_terminal["truncated"] != derived_terminal["truncated"]):
            raise ValueError("contradictory recorded and derived terminal evidence")
        termination = _merge_termination(row.get("termination"), derived_termination)
        # Recorded terminal fields survive missing legacy turn telemetry. Known
        # contradictions refuse analysis; unknown derivation cannot erase data.
        terminal_fields = {
            key: next((value for value in (row.get(key), (termination or {}).get(key),
                                          (derived_termination or {}).get(key)) if value is not None), None)
            for key in ("finish_reason", "truncated")
        }
        termination_evidence({**row, **terminal_fields, "termination": termination})
        stats = (turns[-1].get("generation_stats") or {}) if turns else {}
        performance = {"elapsed_seconds": row.get("elapsed_seconds")}
        for field, key in (("load_seconds", "model_load_ms"),
                           ("ttft_seconds", "time_to_first_token_ms"),
                           ("first_response_seconds", "stream_time_to_first_token_ms"),
                           ("post_first_decode_seconds", "decode_ms")):
            value = stats.get(key)
            if value is not None:
                performance[field] = value / 1000
        for field, key in (("input_tokens", "prompt_tokens"),
                           ("output_tokens", "generation_tokens"),
                           ("decode_tokens_per_second", "generation_tps")):
            if stats.get(key) is not None:
                performance[field] = stats[key]
        observations.append({
            **row, **cells[row["observation_id"]], "performance": performance,
            "recorded_analysis_condition": row.get("analysis_condition"),
            "observed_model_identity": {key: row.get(key) for key in ("model_id", "model_revision", "backend_id")},
            "runtime_input_binding_status": runtime_status if "controller_inputs" in plan else "legacy_unknown",
            **task_fields,
            **terminal_fields, "termination": termination,
            "recorded_termination": row.get("termination"),
            "derived_termination": derived_termination,
            "performance_scope": {
                "elapsed_seconds": "recorded whole scenario; worker startup excluded",
                "generation_fields": "last turn draft generation_stats only; excludes editor; prior prompt-count loading may be outside TTFT",
                "prefill_harness_retrieval_transport_compile": "unmeasured; skipped zero spans not promoted",
                "recorded_generation_qualifiers": {
                    key: stats.get(key) for key in ("model_load_status", "cached_prompt_tokens",
                        "prompt_cache_status", "prompt_tps_basis", "generation_tps_basis")
                },
            },
            "tokens_scope": "last turn draft generation_stats only; not whole multi-turn or edited answer tokens",
            "identity_status": "configured_plan_identity; inspect original model_execution_eligible and turn runtime receipts",
        })
    return {**plan, "matrix": matrix}, observations


def _model_metrics_bundle(
    plan: Mapping[str, Any], observations: list[dict[str, Any]], *,
    rubrics_path: Path | None, reviews_path: Path | None, policy_path: Path | None,
    reviews_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from agronomy_agent.release_eval_model_metrics import score_model_matrix

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate model metric input key")
            value[key] = item
        return value

    def nonfinite(value: str) -> None:
        raise ValueError(f"nonfinite model metric input: {value}")

    def parse(raw: bytes) -> Any:
        return json.loads(raw, object_pairs_hook=unique_keys, parse_constant=nonfinite)

    inputs = {}
    for name, path in (("rubrics", rubrics_path), ("reviews", reviews_path), ("policy", policy_path)):
        if path is None:
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError(f"model metrics {name} input exceeds 2 MiB")
        raw = path.read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError(f"model metrics {name} input exceeds 2 MiB")
        value = parse(raw) if name == "policy" else [
            parse(line) for line in raw.splitlines() if line.strip()
        ]
        if (name == "policy" and not isinstance(value, dict)) or (
            name != "policy" and any(not isinstance(row, dict) for row in value)
        ):
            raise ValueError(f"model metrics {name} requires object records")
        inputs[name] = {"path": path, "bytes": raw, "value": value,
                        "sha256": hashlib.sha256(raw).hexdigest()}
    if "controller_inputs" in plan:
        for name, expected in plan["controller_inputs"]["files"].items():
            if name in inputs and (inputs[name]["sha256"] != expected["sha256"] or len(inputs[name]["bytes"]) != expected["bytes"]):
                raise ValueError("analysis controller bytes differ from prospective freeze")
    metrics = score_model_matrix(
        plan, observations,
        rubrics=inputs.get("rubrics", {}).get("value", []),
        reviews=reviews_override if reviews_override is not None else inputs.get("reviews", {}).get("value", []),
        policy=inputs.get("policy", {}).get("value"),
    )
    metrics["visibility"] = "private_controller_only"
    metrics["controller_byte_binding_status"] = "legacy_posthoc_unfrozen" if "controller_inputs" not in plan else "verified" if set(plan["controller_inputs"]["files"]).issubset(inputs) else "partial_unknown"
    sources = {
        name: file_digest(Path(__file__).with_name(name))
        for name in ("release_eval_reanalysis.py", "release_eval_model_metrics.py",
                     "release_eval_analysis.py", "release_evaluation.py",
                     "release_eval_runner.py", "benchmark_arms.py", "evals.py")
    }
    sources["scripts/analyze_release_evaluation.py"] = file_digest(
        Path(__file__).resolve().parents[2] / "scripts/analyze_release_evaluation.py"
    )
    return {"report": metrics, "inputs": inputs, "analysis_source": sources}


def _write_model_metrics(
    output_dir: Path, bundle: Mapping[str, Any], *, raw_binding: Mapping[str, Any]
) -> None:
    # Retain the exact private labels/policy so an output remains reviewable.
    pins = {}
    for name, item in bundle["inputs"].items():
        if file_digest(item["path"]) != item["sha256"]:
            raise ValueError("model metrics input changed during analysis")
        suffix = "json" if name == "policy" else "jsonl"
        filename = f"model-{name}.private.{suffix}"
        with (output_dir / filename).open("xb") as handle:
            handle.write(item["bytes"])
        pins[filename] = item["sha256"]
    write_new_json(output_dir / "model-metrics.json", bundle["report"])
    write_new_json(output_dir / "model-metrics-lineage.private.json", {
        "schema_version": "open_agronomy_agent.model_metrics_lineage.v1",
        "raw_binding": raw_binding, "input_sha256": pins,
        "analysis_source": bundle["analysis_source"],
        "metrics_sha256": digest(bundle["report"]), "inference_executed": False,
        "boundary": "Descriptive controller scoring; does not change recorded release gates or historical scores.",
    })


def analyze_diagnostic_closeout(
    *, directory: Path, output_dir: Path, rubrics_path: Path | None = None,
    reviews_path: Path | None = None, policy_path: Path | None = None,
) -> dict[str, Any]:
    """Analyze the sealed six-cell readout through the same optional metric path."""
    from agronomy_agent.release_eval_diagnostic_inputs import read_six_cell_closeout

    run = read_six_cell_closeout(directory)
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(directory.resolve()):
        raise ValueError("diagnostic output must be outside immutable source evidence")
    bundle = _model_metrics_bundle(
        run["plan"], run["observations"], rubrics_path=rubrics_path,
        reviews_path=reviews_path, policy_path=policy_path,
    )
    bundle["analysis_source"]["release_eval_diagnostic_inputs.py"] = file_digest(
        Path(__file__).with_name("release_eval_diagnostic_inputs.py")
    )
    bundle["report"]["evidence_limitations"] = run["evidence_limitations"]
    bundle["report"]["full_suite_executed"] = False
    bundle["report"]["current_JLens_executed"] = False
    # Confirm source pins again before creating immutable derived outputs.
    if read_six_cell_closeout(directory) != run:
        raise ValueError("diagnostic evidence changed during analysis")
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_model_metrics(output_dir, bundle, raw_binding=run["plan"])
    write_new_json(output_dir / "retention.json", retention_manifest(output_dir))
    verify_retention(output_dir)
    return bundle["report"]


def analyze_development_panel(
    *, directory: Path, output_dir: Path, policy_path: Path | None = None,
) -> dict[str, Any]:
    """Bind a sealed private panel's synthetic QA fixtures; execute no workers."""
    from agronomy_agent.release_evaluation import normalize_case, worker_case
    from agronomy_agent.release_eval_model_metrics import bind_fixture_review
    from agronomy_agent.benchmark_arms import ALL_ARM_IDS

    directory = directory.resolve()
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(directory):
        raise ValueError("panel output must be outside immutable source evidence")
    names = {"cases.jsonl", "rubrics.jsonl", "numeric-oracles.jsonl",
             "source-support.json", "deterministic-fixtures.jsonl", "verify-panel.py"}
    handoff_path = directory / "handoff.json"
    if handoff_path.is_symlink() or handoff_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("panel handoff must be a bounded regular file")
    handoff_bytes = handoff_path.read_bytes()
    handoff = json.loads(handoff_bytes)
    if handoff.get("schema_version") != "open_agronomy_agent.agronomic_skill_panel_handoff.development.v1":
        raise ValueError("unsupported development panel handoff")
    pins = handoff.get("files", {})
    if set(pins) != names:
        raise ValueError("development panel requires its complete six-file seal")
    arms = handoff.get("primary_arms")
    if not isinstance(arms, list) or not arms or len(set(arms)) != len(arms) or not set(arms).issubset(ALL_ARM_IDS):
        raise ValueError("panel must declare supported unique arms")
    contents = {}; total = len(handoff_bytes)
    for name in sorted(names):
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("panel input must be a bounded regular file")
        raw = path.read_bytes(); total += len(raw)
        if len(raw) != pins[name].get("size_bytes") or hashlib.sha256(raw).hexdigest() != pins[name].get("sha256"):
            raise ValueError("development panel source pin mismatch")
        contents[name] = raw
    if total > 2 * 1024 * 1024:
        raise ValueError("development panel exceeds 2 MiB")
    rows = lambda name: [json.loads(line) for line in contents[name].splitlines() if line.strip()]
    suite = {"id": handoff["panel_id"], "format": "scenario", "exposure": "exposed_development"}
    cases = [normalize_case(row, suite) for row in rows("cases.jsonl")]
    by_case = {case["case_id"]: case for case in cases}
    if not cases or len(by_case) != len(cases) or any(
        case.get("lane") != "agronomy" or case.get("review_required") is not True
        or case.get("assertions") != {} for case in cases
    ):
        raise ValueError("development cases require unique review-required agronomy identities and empty assertions")
    rubrics = rows("rubrics.jsonl"); by_rubric = {row["case_id"]: row for row in rubrics}
    if set(by_rubric) != set(by_case) or len(by_rubric) != len(rubrics):
        raise ValueError("panel requires exactly one rubric per case")
    matrix = []; observations = []; reviews = []; fixture_ids = set()
    for fixture in rows("deterministic-fixtures.jsonl"):
        if fixture.get("synthetic_fixture") is not True or fixture.get("fixture_id") in fixture_ids:
            raise ValueError("panel requires unique explicitly synthetic fixtures")
        fixture_ids.add(fixture["fixture_id"])
        case = by_case[fixture["case_id"]]
        if (fixture.get("case_sha256") != case["case_sha256"]
                or fixture.get("rubric_sha256") != by_rubric[case["case_id"]].get("rubric_sha256")):
            raise ValueError("fixture original case/rubric hash mismatch")
        if fixture["arm_id"] not in handoff["primary_arms"]:
            raise ValueError("fixture arm is outside the sealed panel contract")
        cell = {
            "observation_id": fixture["fixture_id"], "case_id": case["case_id"],
            "case_sha256": case["case_sha256"], "suite_id": suite["id"],
            "arm_id": fixture["arm_id"], "trial_id": fixture["fixture_id"],
            "model_id": "synthetic_QA_not_a_model", "model_revision": None,
            "backend_id": "synthetic_no_execution",
        }
        row = {**cell, "status": fixture["status"], "answer": fixture["answer"],
               "answer_sha256": fixture["answer_sha256"],
               "task_input_sha256": digest(worker_case(case)), "comparison_cohort": None,
               "truncated": fixture.get("truncated", False),
               "finish_reason": fixture.get("finish_reason"),
               "model_execution_eligible": False}
        review = bind_fixture_review(row, by_rubric[case["case_id"]], fixture)
        if row["status"] == "completed":
            reviews.append(review)
        elif (any(value is not None for value in review["criterion_scores"].values())
              or review["fatal_failures"] or review["fatal_review_complete"]):
            raise ValueError("noncompleted fixtures cannot supply semantic or safety labels")
        # Failed fixture rows remain planned/observed execution failures. They
        # receive the declared outcome penalty without inventing review labels.
        matrix.append(cell); observations.append(row)
    plan = {"cases": cases, "matrix": matrix, "execution_contract": "synthetic_fixture_only"}
    bundle = _model_metrics_bundle(plan, observations, rubrics_path=directory / "rubrics.jsonl",
                                   reviews_path=None, policy_path=policy_path,
                                   reviews_override=reviews)
    bundle["report"].update(visibility="private_controller_only", synthetic_fixture_only=True,
                             inference_executed=False, case_count=len(cases),
                             family_count=len({case["scenario_family"] for case in cases}),
                             numeric_oracles="controller_only; no autonomous vector extraction")
    binding = {"handoff_sha256": hashlib.sha256(handoff_bytes).hexdigest(), "files": pins}
    if file_digest(directory / "handoff.json") != binding["handoff_sha256"] or any(
        file_digest(directory / name) != pin["sha256"] for name, pin in pins.items()
    ):
        raise ValueError("panel changed during fixture analysis")
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_model_metrics(output_dir, bundle, raw_binding=binding)
    write_new_json(output_dir / "fixture-plan.private.json", plan)
    write_new_json(output_dir / "fixture-reviews.private.json", reviews)
    write_new_json(output_dir / "retention.json", retention_manifest(output_dir))
    verify_retention(output_dir)
    return bundle["report"]
