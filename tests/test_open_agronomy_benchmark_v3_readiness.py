from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_open_agronomy_benchmark_v3_readiness.py"


def _module():
    spec = importlib.util.spec_from_file_location("audit_open_agronomy_benchmark_v3_readiness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sealed_commitment() -> dict[str, object]:
    template = json.loads(
        (ROOT / "configs/open_agronomy_benchmark_v3_holdout_commitment.template.json").read_text(
            encoding="utf-8"
        )
    )
    template.update(
        {
            "cohort_id": "oab3_holdout_test_001",
            "status": "sealed_unexposed",
            "suite_sha256": hashlib.sha256(b"suite").hexdigest(),
            "rubric_sha256": hashlib.sha256(b"rubric").hexdigest(),
            "source_package_sha256": hashlib.sha256(b"sources").hexdigest(),
            "case_schema_sha256": hashlib.sha256(b"case-schema").hexdigest(),
            "access_log_sha256": hashlib.sha256(b"access-log").hexdigest(),
            "authorship_receipt_sha256": hashlib.sha256(b"authorship").hexdigest(),
            "review_receipt_sha256": hashlib.sha256(b"review").hexdigest(),
            "author_ids": ["author_alpha"],
            "reviewer_ids": ["reviewer_beta"],
        }
    )
    return template


def _calibrated_judge() -> dict[str, object]:
    payload = json.loads(
        (ROOT / "configs/benchmark_judge_calibration.template.json").read_text(
            encoding="utf-8"
        )
    )
    payload.update(
        {
            "calibration_id": "oaa_judge_calibration_test_001",
            "status": "calibrated_pass",
            "artifacts": {
                name: hashlib.sha256(name.encode("utf-8")).hexdigest()
                for name in (
                    "development_set_sha256",
                    "human_labels_sha256",
                    "prompt_sha256",
                    "rubric_sha256",
                    "parser_sha256",
                )
            },
            "observed": {
                "macro_f1": 0.9,
                "false_positive_rate": 0.05,
                "false_negative_rate": 0.05,
                "order_flip_rate": 0.02,
            },
        }
    )
    return payload


def _audit(
    tmp_path: Path,
    commitment: dict[str, object] | None,
    judge: dict[str, object] | None = None,
):
    module = _module()
    path = None
    if commitment is not None:
        path = tmp_path / "commitment.json"
        path.write_text(json.dumps(commitment), encoding="utf-8")
    judge_path = None
    if judge is not None:
        judge_path = tmp_path / "judge.json"
        judge_path.write_text(json.dumps(judge), encoding="utf-8")
    return module.audit(
        root=ROOT,
        protocol_path=ROOT / "configs/open_agronomy_benchmark_v3_protocol.json",
        schema_path=ROOT / "configs/schemas/benchmark_v3_holdout_commitment_v1.schema.json",
        commitment_path=path,
        judge_calibration_path=judge_path,
    )


def _audit_with_protocol(tmp_path: Path, protocol: dict[str, object]):
    module = _module()
    protocol_path = tmp_path / "protocol.json"
    commitment_path = tmp_path / "commitment.json"
    judge_path = tmp_path / "judge.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    commitment_path.write_text(json.dumps(_sealed_commitment()), encoding="utf-8")
    judge_path.write_text(json.dumps(_calibrated_judge()), encoding="utf-8")
    return module.audit(
        root=ROOT,
        protocol_path=protocol_path,
        schema_path=ROOT / "configs/schemas/benchmark_v3_holdout_commitment_v1.schema.json",
        commitment_path=commitment_path,
        judge_calibration_path=judge_path,
    )


def test_checked_in_template_is_explicitly_not_release_ready(tmp_path: Path) -> None:
    template = json.loads(
        (ROOT / "configs/open_agronomy_benchmark_v3_holdout_commitment.template.json").read_text(
            encoding="utf-8"
        )
    )
    report = _audit(tmp_path, template)

    assert report["development_protocol_status"] == "ready"
    assert report["sealed_release_status"] == "blocked"
    failures = {row["id"] for row in report["failures"]}
    assert "sealed_unexposed_commitment" in failures


def test_valid_sealed_commitment_passes_without_reading_private_cases(tmp_path: Path) -> None:
    report = _audit(tmp_path, _sealed_commitment(), _calibrated_judge())

    assert report["sealed_release_status"] == "ready"
    assert report["private_holdout_read"] is False
    assert report["generation_performed"] is False


def test_exposure_and_role_overlap_fail_closed(tmp_path: Path) -> None:
    commitment = _sealed_commitment()
    commitment["exposure_count"] = 1
    commitment["reviewer_ids"] = ["author_alpha"]
    report = _audit(tmp_path, commitment, _calibrated_judge())

    failures = {row["id"] for row in report["failures"]}
    assert "sealed_unexposed_commitment" in failures
    assert "independent_role_separation" in failures


def test_inconsistent_count_commitments_fail_closed(tmp_path: Path) -> None:
    commitment = _sealed_commitment()
    commitment["language_counts"] = {"en_ca": 59, "fr_ca": 12}
    report = _audit(tmp_path, commitment, _calibrated_judge())

    assert "count_commitments" in {row["id"] for row in report["failures"]}


def test_plaintext_v3_cases_under_data_eval_block_development_protocol(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "data/eval").mkdir(parents=True)
    (root / "data/eval/open_agronomy_benchmark_v3_cases.jsonl").write_text(
        '{"question":"private holdout leak"}\n', encoding="utf-8"
    )
    module = _module()
    commitment_path = tmp_path / "commitment.json"
    commitment_path.write_text(json.dumps(_sealed_commitment()), encoding="utf-8")
    judge_path = tmp_path / "judge.json"
    judge_path.write_text(json.dumps(_calibrated_judge()), encoding="utf-8")
    report = module.audit(
        root=root,
        protocol_path=ROOT / "configs/open_agronomy_benchmark_v3_protocol.json",
        schema_path=ROOT / "configs/schemas/benchmark_v3_holdout_commitment_v1.schema.json",
        commitment_path=commitment_path,
        judge_calibration_path=judge_path,
    )

    assert report["development_protocol_status"] == "blocked"
    assert "no_plaintext_holdout_in_repository" in {row["id"] for row in report["failures"]}


def test_uncalibrated_judge_blocks_release_but_not_development_protocol(tmp_path: Path) -> None:
    report = _audit(
        tmp_path,
        _sealed_commitment(),
        json.loads(
            (ROOT / "configs/benchmark_judge_calibration.template.json").read_text(
                encoding="utf-8"
            )
        ),
    )

    assert report["development_protocol_status"] == "ready"
    assert report["sealed_release_status"] == "blocked"
    assert "judge_calibration" in {row["id"] for row in report["failures"]}


def test_protocol_stage_reorder_fails_closed_against_execution_core(tmp_path: Path) -> None:
    protocol = json.loads(
        (ROOT / "configs/open_agronomy_benchmark_v3_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    protocol["active_stage_contract"] = list(
        reversed(protocol["active_stage_contract"])
    )

    report = _audit_with_protocol(tmp_path, protocol)

    assert report["development_protocol_status"] == "blocked"
    assert "execution_stage_topology_alignment" in {
        row["id"] for row in report["failures"]
    }


def test_protocol_topology_version_drift_fails_closed(tmp_path: Path) -> None:
    protocol = json.loads(
        (ROOT / "configs/open_agronomy_benchmark_v3_protocol.json").read_text(
            encoding="utf-8"
        )
    )
    protocol["active_stage_topology_version"] = (
        "open_agronomy_agent.production_stage_topology.forged"
    )

    report = _audit_with_protocol(tmp_path, protocol)

    assert report["development_protocol_status"] == "blocked"
    alignment = next(
        row
        for row in report["checks"]
        if row["id"] == "execution_stage_topology_alignment"
    )
    assert alignment["passed"] is False
    assert alignment["evidence"]["protocol_topology_version"].endswith(".forged")
