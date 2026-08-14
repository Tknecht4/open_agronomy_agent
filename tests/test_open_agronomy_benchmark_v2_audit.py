from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_open_agronomy_benchmark_v2.py"
MANIFEST = ROOT / "data/eval/open_agronomy_benchmark_v2_manifest.json"


def _module():
    spec = importlib.util.spec_from_file_location("audit_open_agronomy_benchmark_v2", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_bundle(tmp_path: Path) -> tuple[Path, dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for item in manifest["artifacts"]:
        source = ROOT / item["path"]
        target = tmp_path / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    target_manifest = tmp_path / "data/eval/open_agronomy_benchmark_v2_manifest.json"
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    target_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target_manifest, manifest


def _refresh_artifact(manifest: dict, root: Path, role: str) -> None:
    item = next(value for value in manifest["artifacts"] if value["role"] == role)
    path = root / item["path"]
    item["sha256"] = _sha256(path)
    item["bytes"] = path.stat().st_size
    if path.suffix == ".jsonl":
        item["rows"] = sum(bool(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


def _write_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_checked_in_benchmark_v2_design_audit_passes() -> None:
    report = _module().audit_benchmark_v2(ROOT, MANIFEST)

    assert report["status"] == "pass", report["failure_ids"]
    assert report["claim_eligible"] is False
    assert len(report["checks"]) >= 20


def test_audit_detects_content_hash_drift(tmp_path: Path) -> None:
    manifest_path, manifest = _copy_bundle(tmp_path)
    interface = tmp_path / next(item["path"] for item in manifest["artifacts"] if item["role"] == "causal_interface")
    interface.write_text(interface.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    report = _module().audit_benchmark_v2(tmp_path, manifest_path)

    assert report["status"] == "fail"
    assert f"artifact_sha256::{interface.relative_to(tmp_path)}" in report["failure_ids"]


def test_audit_detects_unmatched_caution_design_even_with_refreshed_hash(tmp_path: Path) -> None:
    manifest_path, manifest = _copy_bundle(tmp_path)
    suite_item = next(item for item in manifest["artifacts"] if item["role"] == "suite")
    suite = tmp_path / suite_item["path"]
    rows = [json.loads(line) for line in suite.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row["eval_id"] != "oab2::spring_wheat_stand::benign_explanation"]
    suite.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    _refresh_artifact(manifest, tmp_path, "suite")
    _write_manifest(manifest_path, manifest)

    report = _module().audit_benchmark_v2(tmp_path, manifest_path)

    assert report["status"] == "fail"
    assert "matched_group_topology" in report["failure_ids"]
    assert "caution_cases_have_answerable_counterparts" in report["failure_ids"]
    assert "strata_balanced" in report["failure_ids"]


def test_audit_rejects_fabricated_independent_review_status(tmp_path: Path) -> None:
    manifest_path, manifest = _copy_bundle(tmp_path)
    suite_item = next(item for item in manifest["artifacts"] if item["role"] == "suite")
    suite = tmp_path / suite_item["path"]
    rows = [json.loads(line) for line in suite.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["review_status"] = "independently_reviewed"
    rows[0]["independent_review_received"] = True
    suite.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    _refresh_artifact(manifest, tmp_path, "suite")
    _write_manifest(manifest_path, manifest)

    report = _module().audit_benchmark_v2(tmp_path, manifest_path)

    assert report["status"] == "fail"
    assert "case_schema_validation" in report["failure_ids"]
    assert "project_authored_pending_review_nonclaim_provenance" in report["failure_ids"]


def test_audit_rejects_confounding_in_named_causal_contrast(tmp_path: Path) -> None:
    manifest_path, manifest = _copy_bundle(tmp_path)
    interface_item = next(item for item in manifest["artifacts"] if item["role"] == "causal_interface")
    interface_path = tmp_path / interface_item["path"]
    interface = json.loads(interface_path.read_text(encoding="utf-8"))
    interface["arms"]["kernel_only"]["field_context"] = True
    interface_path.write_text(json.dumps(interface, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _refresh_artifact(manifest, tmp_path, "causal_interface")
    _write_manifest(manifest_path, manifest)

    report = _module().audit_benchmark_v2(tmp_path, manifest_path)

    assert report["status"] == "fail"
    assert "named_contrasts_change_one_component" in report["failure_ids"]


def test_audit_rejects_attempt_to_relabel_exposed_v2_as_pristine(tmp_path: Path) -> None:
    manifest_path, manifest = _copy_bundle(tmp_path)
    contract_item = next(item for item in manifest["artifacts"] if item["role"] == "contract")
    contract_path = tmp_path / contract_item["path"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["status"] = "pristine_untouched_evaluation"
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _refresh_artifact(manifest, tmp_path, "contract")
    _write_manifest(manifest_path, manifest)

    report = _module().audit_benchmark_v2(tmp_path, manifest_path)

    assert report["status"] == "fail"
    assert "v2_rejects_pristine_or_evaluation_status" in report["failure_ids"]


def test_audit_requires_append_only_exposure_receipt(tmp_path: Path) -> None:
    manifest_path, manifest = _copy_bundle(tmp_path)
    amendment_item = next(item for item in manifest["artifacts"] if item["role"] == "exposure_amendment")
    amendment_path = tmp_path / amendment_item["path"]
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    amendment["append_only"] = False
    amendment_path.write_text(json.dumps(amendment, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _refresh_artifact(manifest, tmp_path, "exposure_amendment")
    _write_manifest(manifest_path, manifest)

    report = _module().audit_benchmark_v2(tmp_path, manifest_path)

    assert report["status"] == "fail"
    assert "exposure_amendment_records_contamination_and_v3_requirement" in report["failure_ids"]


def test_audit_rejects_construct_semantic_profile_drift(tmp_path: Path) -> None:
    manifest_path, manifest = _copy_bundle(tmp_path)
    harness_item = next(
        item for item in manifest["artifacts"] if item["role"] == "harness_contract"
    )
    harness_path = tmp_path / harness_item["path"]
    harness = json.loads(harness_path.read_text(encoding="utf-8"))
    harness["semantic_profile"]["verifier_semantics"]["decision_unit"] = (
        "whole_answer_label"
    )
    harness_path.write_text(
        json.dumps(harness, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _refresh_artifact(manifest, tmp_path, "harness_contract")
    _write_manifest(manifest_path, manifest)

    report = _module().audit_benchmark_v2(tmp_path, manifest_path)

    assert report["status"] == "fail"
    assert (
        "harness_construct_semantic_profile_is_frozen_and_complete"
        in report["failure_ids"]
    )
