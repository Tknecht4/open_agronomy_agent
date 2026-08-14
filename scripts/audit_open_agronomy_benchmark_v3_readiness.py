#!/usr/bin/env python3
"""Model-free governance audit for an Open Agronomy Agent v3 holdout.

This script does not read private cases, generate answers, or claim that a
holdout exists. It validates only a public cryptographic commitment and fails
closed when the checked-in template is used. Product-path, model, environment,
and run-level gates are handled by the benchmark release-candidate preflight.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = ROOT / "configs/open_agronomy_benchmark_v3_protocol.json"
DEFAULT_SCHEMA = ROOT / "configs/schemas/benchmark_v3_holdout_commitment_v1.schema.json"
DEFAULT_TEMPLATE = ROOT / "configs/open_agronomy_benchmark_v3_holdout_commitment.template.json"
DEFAULT_JUDGE_SCHEMA = ROOT / "configs/schemas/benchmark_judge_calibration_v1.schema.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_placeholder_digest(value: object) -> bool:
    text = str(value or "")
    return len(text) != 64 or text == "0" * 64 or len(set(text)) == 1


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    detail: str,
    evidence: Mapping[str, Any] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "passed": bool(passed),
            "detail": detail,
            "evidence": dict(evidence or {}),
        }
    )


def _schema_errors(schema: Mapping[str, Any], payload: object) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda row: list(row.absolute_path))
    ]


def _plaintext_candidates(root: Path) -> list[str]:
    candidates: list[str] = []
    for pattern in (
        "data/eval/open_agronomy_benchmark_v3*.jsonl",
        "data/eval/open_agronomy_benchmark_v3*cases*.json",
        "data/eval/open_agronomy_benchmark_v3*answers*.json",
        "data/eval/open_agronomy_benchmark_v3*rubric*.json",
    ):
        for path in root.glob(pattern):
            if path.is_file() and path.stat().st_size:
                candidates.append(str(path.relative_to(root)))
    return sorted(set(candidates))


def _execution_stage_contract(root: Path) -> tuple[str | None, list[str], list[str]]:
    """Read the literal production topology from execution_core without imports.

    The readiness audit can target another checkout, so importing the package
    from the auditor's own environment would compare against the wrong source.
    The two contract constants are deliberately literals and are extracted from
    the supplied root's source tree. Any syntax or representation drift fails
    closed instead of guessing at the active product path.
    """

    path = root / "src/agronomy_agent/execution_core.py"
    if not path.is_file():
        return None, [], [f"execution_core_missing:{path}"]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        return None, [], [f"execution_core_unreadable:{exc}"]

    values: dict[str, object] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if (
            isinstance(target, ast.Name)
            and target.id
            in {"EXECUTION_STAGE_TOPOLOGY_VERSION", "EXECUTION_STAGE_SPECS"}
            and value is not None
        ):
            try:
                values[target.id] = ast.literal_eval(value)
            except (TypeError, ValueError) as exc:
                return None, [], [f"execution_stage_contract_not_literal:{exc}"]

    version = values.get("EXECUTION_STAGE_TOPOLOGY_VERSION")
    raw_specs = values.get("EXECUTION_STAGE_SPECS")
    errors: list[str] = []
    if not isinstance(version, str) or not version:
        errors.append("execution_stage_topology_version_missing")
    stages: list[str] = []
    if not isinstance(raw_specs, tuple):
        errors.append("execution_stage_specs_missing")
    else:
        for position, spec in enumerate(raw_specs):
            if (
                not isinstance(spec, tuple)
                or len(spec) != 2
                or not isinstance(spec[0], str)
                or not spec[0]
                or spec[1] is not True
            ):
                errors.append(f"invalid_execution_stage_spec:{position}")
                continue
            stages.append(spec[0])
    if len(stages) != len(set(stages)):
        errors.append("duplicate_execution_stage_ids")
    return version if isinstance(version, str) else None, stages, errors


def audit(
    *,
    root: Path,
    protocol_path: Path,
    schema_path: Path,
    commitment_path: Path | None,
    judge_schema_path: Path = DEFAULT_JUDGE_SCHEMA,
    judge_calibration_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []

    stages = list(protocol.get("active_stage_contract") or [])
    protocol_topology_version = protocol.get("active_stage_topology_version")
    _check(
        checks,
        "protocol_contract",
        protocol.get("schema_version") == "open_agronomy_agent.benchmark_v3_protocol.v1"
        and protocol.get("benchmark_id") == "open_agronomy_benchmark_v3"
        and protocol.get("status") == "protocol_candidate_holdout_not_supplied"
        and isinstance(protocol_topology_version, str)
        and bool(protocol_topology_version)
        and len(stages) == len(set(stages))
        and {"document_retrieval", "graph_retrieval"} <= set(stages),
        "the public v3 protocol is explicit, non-claiming, and separates document from graph retrieval",
        {
            "path": str(protocol_path),
            "sha256": _sha256(protocol_path),
            "stage_count": len(stages),
            "stage_topology_version": protocol_topology_version,
        },
    )
    execution_topology_version, execution_stages, execution_contract_errors = (
        _execution_stage_contract(root)
    )
    _check(
        checks,
        "execution_stage_topology_alignment",
        not execution_contract_errors
        and protocol_topology_version == execution_topology_version
        and stages == execution_stages,
        "the v3 protocol is bound to the exact ordered production execution-stage topology",
        {
            "execution_core_path": str(
                root / "src/agronomy_agent/execution_core.py"
            ),
            "protocol_topology_version": protocol_topology_version,
            "execution_topology_version": execution_topology_version,
            "protocol_stages": stages,
            "execution_stages": execution_stages,
            "errors": execution_contract_errors,
        },
    )
    _check(
        checks,
        "holdout_schema",
        schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
        and schema.get("properties", {}).get("benchmark_id", {}).get("const")
        == "open_agronomy_benchmark_v3",
        "the holdout commitment schema is the expected fail-closed v1 contract",
        {"path": str(schema_path), "sha256": _sha256(schema_path)},
    )

    judge_schema = json.loads(judge_schema_path.read_text(encoding="utf-8"))
    judge_calibration: dict[str, Any] | None = None
    judge_errors: list[str] = []
    if judge_calibration_path is None or not judge_calibration_path.is_file():
        judge_errors = ["judge_calibration_missing"]
    else:
        try:
            loaded_judge = json.loads(judge_calibration_path.read_text(encoding="utf-8"))
            if not isinstance(loaded_judge, dict):
                judge_errors = ["judge_calibration_must_be_an_object"]
            else:
                judge_calibration = loaded_judge
                judge_errors = _schema_errors(judge_schema, judge_calibration)
        except (OSError, json.JSONDecodeError) as exc:
            judge_errors = [f"judge_calibration_unreadable:{exc}"]
    judge_artifacts = (judge_calibration or {}).get("artifacts") or {}
    judge_placeholders = [
        field
        for field in (
            "development_set_sha256",
            "human_labels_sha256",
            "prompt_sha256",
            "rubric_sha256",
            "parser_sha256",
        )
        if _is_placeholder_digest(judge_artifacts.get(field))
    ]
    thresholds = (judge_calibration or {}).get("acceptance_thresholds") or {}
    observed = (judge_calibration or {}).get("observed") or {}
    metrics_pass = bool(thresholds and observed) and (
        float(observed.get("macro_f1", -1)) >= float(thresholds.get("macro_f1", 2))
        and float(observed.get("false_positive_rate", 2))
        <= float(thresholds.get("false_positive_rate", -1))
        and float(observed.get("false_negative_rate", 2))
        <= float(thresholds.get("false_negative_rate", -1))
        and float(observed.get("order_flip_rate", 2))
        <= float(thresholds.get("order_flip_rate", -1))
    )
    _check(
        checks,
        "judge_calibration",
        judge_calibration is not None
        and not judge_errors
        and judge_calibration.get("status") == "calibrated_pass"
        and not judge_placeholders
        and metrics_pass,
        "semantic judging is frozen, human-calibrated, order-probed, and within preregistered thresholds",
        {
            "path": str(judge_calibration_path) if judge_calibration_path else None,
            "sha256": (
                _sha256(judge_calibration_path)
                if judge_calibration_path and judge_calibration_path.is_file()
                else None
            ),
            "errors": judge_errors,
            "status": (judge_calibration or {}).get("status"),
            "placeholder_digest_fields": judge_placeholders,
            "metrics_pass": metrics_pass,
        },
    )

    plaintext = _plaintext_candidates(root)
    _check(
        checks,
        "no_plaintext_holdout_in_repository",
        not plaintext,
        "no v3 plaintext cases, answers, or rubric are present under data/eval",
        {"unexpected_paths": plaintext},
    )

    commitment: dict[str, Any] | None = None
    errors: list[str] = []
    if commitment_path is None or not commitment_path.is_file():
        errors = ["commitment_missing"]
    else:
        try:
            loaded = json.loads(commitment_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                errors = ["commitment_must_be_an_object"]
            else:
                commitment = loaded
                errors = _schema_errors(schema, commitment)
        except (OSError, json.JSONDecodeError) as exc:
            errors = [f"commitment_unreadable:{exc}"]
    _check(
        checks,
        "commitment_schema_validation",
        commitment is not None and not errors,
        "the supplied private-holdout commitment validates against the public schema",
        {
            "path": str(commitment_path) if commitment_path else None,
            "sha256": _sha256(commitment_path) if commitment_path and commitment_path.is_file() else None,
            "errors": errors,
        },
    )

    if commitment is None or errors:
        commitment = {}
    digest_fields = [
        "suite_sha256",
        "rubric_sha256",
        "source_package_sha256",
        "case_schema_sha256",
        "access_log_sha256",
        "authorship_receipt_sha256",
        "review_receipt_sha256",
    ]
    placeholders = [field for field in digest_fields if _is_placeholder_digest(commitment.get(field))]
    _check(
        checks,
        "sealed_unexposed_commitment",
        commitment.get("status") == "sealed_unexposed"
        and commitment.get("authored_outside_repository") is True
        and commitment.get("plaintext_present_in_repository") is False
        and commitment.get("exposure_count") == 0
        and not placeholders,
        "the holdout is independently held, sealed, unexposed, and bound by non-placeholder digests",
        {
            "status": commitment.get("status"),
            "exposure_count": commitment.get("exposure_count"),
            "placeholder_digest_fields": placeholders,
        },
    )

    authors = set(commitment.get("author_ids") or [])
    reviewers = set(commitment.get("reviewer_ids") or [])
    _check(
        checks,
        "independent_role_separation",
        bool(authors) and bool(reviewers) and not (authors & reviewers),
        "holdout authors and independent reviewers are nonempty disjoint pseudonymous sets",
        {"author_count": len(authors), "reviewer_count": len(reviewers), "overlap": sorted(authors & reviewers)},
    )

    strata = commitment.get("strata_counts") or {}
    languages = commitment.get("language_counts") or {}
    case_count = int(commitment.get("case_count") or 0)
    strata_total = sum(value for value in strata.values() if isinstance(value, int) and not isinstance(value, bool))
    language_total = sum(value for value in languages.values() if isinstance(value, int) and not isinstance(value, bool))
    _check(
        checks,
        "count_commitments",
        case_count > 0
        and int(commitment.get("family_count") or 0) > 0
        and strata_total == case_count
        and language_total == case_count
        and int(languages.get("fr_ca") or 0) >= int(protocol.get("holdout_contract", {}).get("minimum_french_cases") or 1),
        "case, stratum, family, and language counts are internally consistent",
        {
            "case_count": case_count,
            "family_count": commitment.get("family_count"),
            "strata_total": strata_total,
            "language_total": language_total,
            "fr_ca": languages.get("fr_ca"),
        },
    )

    failures = [row for row in checks if not row["passed"]]
    governance_failures = {
        "commitment_schema_validation",
        "sealed_unexposed_commitment",
        "independent_role_separation",
        "count_commitments",
        "judge_calibration",
    }
    development_failures = [row for row in failures if row["id"] not in governance_failures]
    return {
        "schema_version": "open_agronomy_agent.benchmark_v3_readiness_audit.v1",
        "benchmark_id": "open_agronomy_benchmark_v3",
        "development_protocol_status": "ready" if not development_failures else "blocked",
        "sealed_release_status": "ready" if not failures else "blocked",
        "generation_performed": False,
        "private_holdout_read": False,
        "checks": checks,
        "failure_count": len(failures),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--commitment", type=Path)
    parser.add_argument("--judge-calibration", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    def resolved(path: Path | None) -> Path | None:
        if path is None:
            return None
        return path.resolve() if path.is_absolute() else (root / path).resolve()

    report = audit(
        root=root,
        protocol_path=resolved(args.protocol) or DEFAULT_PROTOCOL,
        schema_path=resolved(args.schema) or DEFAULT_SCHEMA,
        commitment_path=resolved(args.commitment),
        judge_calibration_path=resolved(args.judge_calibration),
    )
    if args.output:
        output = resolved(args.output)
        assert output is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["sealed_release_status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
