from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_final_benchmark_readiness.py"
PLAN = ROOT / "configs/final_benchmark_round_rc3.json"


def _module():
    spec = importlib.util.spec_from_file_location("audit_final_benchmark_readiness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan() -> dict:
    return json.loads(PLAN.read_text(encoding="utf-8"))


def _internal_contract(plan: dict | None = None) -> dict:
    selected = plan or _plan()
    return json.loads(
        (ROOT / selected["internal_benchmark"]["contract_path"]).read_text(encoding="utf-8")
    )


def _valid_egress(tmp_path: Path, **overrides: object) -> Path:
    plan = _plan()
    payload = {
        "schema_version": "open_agronomy_agent.benchmark_egress_authorization.v2",
        "authorization_decision": "authorized",
        "benchmark_id": _internal_contract(plan)["benchmark_id"],
        "benchmark_suite_sha256": plan["internal_benchmark"]["suite_sha256"],
        "authorization_source": "human-review-receipt-20260814",
        "authorized_by_key_id": "benchmark-authority-key-7",
        "authorized_at": "2026-08-14T11:00:00Z",
        "expires_at": "2026-08-14T13:00:00Z",
        "authorized_payload_classes": plan["egress"]["authorized_payload_classes_exact"],
        "excluded_payload_classes": plan["egress"]["excluded_payload_classes_exact"],
    }
    payload.update(overrides)
    path = tmp_path / "egress.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _verify_egress(module, path: Path) -> dict:
    plan = _plan()
    return module.verify_egress_authorization(
        path,
        benchmark_id=_internal_contract(plan)["benchmark_id"],
        suite_sha256=plan["internal_benchmark"]["suite_sha256"],
        required_payloads=plan["egress"]["authorized_payload_classes_exact"],
        forbidden_payloads=plan["egress"]["excluded_payload_classes_exact"],
        checked_at=dt.datetime(2026, 8, 14, 12, tzinfo=dt.UTC),
    )


def test_rc3_is_append_only_nonclaim_master_runtime_with_retired_external_v1() -> None:
    module = _module()
    plan = _plan()

    result = module.validate_plan_semantics(plan)

    assert result["status"] == "pass"
    assert plan["round_class"] == "development_rerun_nonclaim"
    assert plan["claim_eligible"] is False
    assert plan["v3_boundary"]["sealed_holdout_exercised"] is False
    assert plan["v3_boundary"]["v3_performance_claim_eligible"] is False
    assert plan["external_diagnostic"]["lifecycle"] == "retired_after_rc1_exposure"
    assert plan["external_diagnostic"]["execution_allowed"] is False
    assert plan["external_diagnostic"]["rerun_command_emitted"] is False
    assert (ROOT / "configs/final_benchmark_round_rc1.json").is_file()
    assert (ROOT / "configs/final_benchmark_round_rc2.json").is_file()
    assert plan["internal_benchmark"]["suite_exposure_status"] == "exposed_and_used_for_system_tuning"
    runtime = plan["internal_benchmark"]["runtime_profile"]
    assert runtime["rag_config_path"] == "configs/rag_governed_runtime_v2.yaml"
    assert runtime["master_profile_id"] == "canada-offline-master"
    assert runtime["knowledge_release_id"] == "curated-canada-2026-08-14"
    assert runtime["knowledge_release_rows"] == 969
    assert _internal_contract(plan)["rag_config"] == runtime["rag_config_path"]
    assert _internal_contract(plan)["contamination_policy"]["exclude_questions_from_deterministic_answer_repair"] is False


def test_plan_rejects_any_attempt_to_reenable_exposed_agroqa_v1() -> None:
    module = _module()
    plan = _plan()
    plan["external_diagnostic"]["execution_allowed"] = True
    plan["external_diagnostic"]["rerun_command_emitted"] = True
    plan["evaluation_order"].append("external_transfer_diagnostic")

    result = module.validate_plan_semantics(plan)

    assert result["status"] == "blocked"
    assert "retired_external_execution_must_be_false" in result["failures"]
    assert "retired_external_command_flag_must_be_false" in result["failures"]
    assert "retired_external_diagnostic_in_evaluation_order" in result["failures"]


def test_rc3_plan_rejects_unbound_or_pristine_runtime_claims() -> None:
    module = _module()
    plan = _plan()
    plan["internal_benchmark"]["suite_exposure_status"] = "pristine_holdout"
    plan["internal_benchmark"]["runtime_profile"]["rag_config_sha256"] = "not-a-digest"
    plan["internal_benchmark"]["runtime_profile"]["master_profile_id"] = "legacy-profile"

    result = module.validate_plan_semantics(plan)

    assert result["status"] == "blocked"
    assert "internal_suite_exposure_status_missing" in result["failures"]
    assert "runtime_profile_rag_config_sha256_invalid" in result["failures"]
    assert "master_profile_id_invalid" in result["failures"]


def test_commands_bind_every_trial_identity_and_isolate_outputs(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    egress = tmp_path / "egress.json"
    local_model = plan["models"][0]
    remote_model = plan["models"][2]
    trial_one, trial_two = plan["replication"]["trials"][:2]

    local_one = module.build_benchmark_command(plan, local_model, egress, trial_one)
    local_two = module.build_benchmark_command(plan, local_model, egress, trial_two)
    remote = module.build_benchmark_command(plan, remote_model, egress, trial_one)

    assert local_one[local_one.index("--modes") + 1] == "raw_model,baseline,kernel_field_context,agronomic_rag"
    assert local_one[local_one.index("--contract") + 1] == "configs/open_agronomy_canadian_performance_v1_runtime_v2.json"
    assert local_one[local_one.index("--trial-id") + 1] == "trial-001"
    assert local_one[local_one.index("--generation-seed") + 1] == "104729"
    assert local_one[local_one.index("--verification-seed") + 1] == "130363"
    assert local_one[local_one.index("--case-order-seed") + 1] == "15485863"
    assert local_one[local_one.index("--judge-seed") + 1] == "32452843"
    assert local_one[local_one.index("--temperature") + 1] == "0.0"
    assert local_one[local_one.index("--top-p") + 1] == "0.9"
    assert local_one[local_one.index("--top-k") + 1] == "0"
    assert local_one[local_one.index("--process-isolation-policy") + 1] == "fresh_process_per_run"
    assert local_one[local_one.index("--cache-policy") + 1] == "no_prompt_cache"
    assert local_one[local_one.index("--output-dir") + 1] != local_two[local_two.index("--output-dir") + 1]
    assert "--judge" not in local_one
    assert "--codex-app-server" not in local_one
    assert "--codex-app-server" in remote
    assert "--build-review-packet" in local_one
    assert "--resume-partial-runs" in local_one


def test_calibrated_judge_is_never_same_exact_candidate_model(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    egress = tmp_path / "egress.json"
    trial = plan["replication"]["trials"][0]

    gemma = module.build_benchmark_command(
        plan, plan["models"][0], egress, trial, calibrated_judge=True
    )
    luna = module.build_benchmark_command(
        plan, plan["models"][2], egress, trial, calibrated_judge=True
    )

    assert "--judge" in gemma
    assert gemma[gemma.index("--judge-model") + 1] == "gpt-5.6-luna"
    assert "--judge" not in luna


def test_no_generated_rc3_command_can_rerun_external_agroqa(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    commands = [
        module.build_benchmark_command(plan, model, tmp_path / "egress.json", trial)
        for model in plan["models"]
        for trial in plan["replication"]["trials"]
    ]

    assert len(commands) == 9
    for command in commands:
        joined = " ".join(command).lower()
        assert "--evaluation-set internal" in joined
        assert "open_agronomy_external_agroqa_v1" not in joined
        assert "--evaluation-set external" not in joined
        assert "agroqa" not in joined


def test_egress_v2_accepts_only_exact_current_human_authority(tmp_path: Path) -> None:
    module = _module()
    receipt = _valid_egress(tmp_path)

    result = _verify_egress(module, receipt)

    assert result["status"] == "pass"
    assert result["authorization_decision"] == "authorized"
    assert result["authorization_source"] == "human-review-receipt-20260814"
    assert result["authorized_by_key_id"] == "benchmark-authority-key-7"


def test_checked_egress_template_is_not_authorization() -> None:
    module = _module()

    result = _verify_egress(module, ROOT / "configs/benchmark_egress_authorization.template.json")

    assert result["status"] == "blocked"
    assert "authorization_decision_not_authorized" in result["failures"]
    assert "human_authority_provenance_missing_or_placeholder" in result["failures"]


def test_egress_rejects_v1_placeholder_expired_and_non_utc_receipts(tmp_path: Path) -> None:
    module = _module()
    cases = [
        ({"schema_version": "open_agronomy_agent.benchmark_egress_authorization.v1"}, "schema_mismatch"),
        ({"authorization_decision": "template_not_authorized"}, "authorization_decision_not_authorized"),
        ({"authorization_source": "replace-with-human-authority"}, "human_authority_provenance_missing_or_placeholder"),
        ({"authorized_by_key_id": "example-authorizer"}, "human_authority_provenance_missing_or_placeholder"),
        ({"expires_at": "2026-08-14T11:30:00Z"}, "authorization_expired"),
        ({"authorized_at": "2026-08-14T11:00:00-06:00"}, "authorized_at_must_be_utc"),
    ]
    for index, (overrides, expected) in enumerate(cases):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        result = _verify_egress(module, _valid_egress(case_dir, **overrides))
        assert result["status"] == "blocked"
        assert expected in result["failures"]


def test_egress_rejects_missing_extra_duplicate_or_overlapping_payload_classes(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    required = plan["egress"]["authorized_payload_classes_exact"]
    excluded = plan["egress"]["excluded_payload_classes_exact"]
    cases = [
        ({"authorized_payload_classes": required[:-1]}, "authorized_payload_classes_not_exact"),
        ({"authorized_payload_classes": [*required, "extra"]}, "authorized_payload_classes_not_exact"),
        ({"authorized_payload_classes": [*required, required[0]]}, "authorized_payload_classes_not_exact"),
        ({"excluded_payload_classes": excluded[:-1]}, "excluded_payload_classes_not_exact"),
        ({"excluded_payload_classes": [*excluded, "extra"]}, "excluded_payload_classes_not_exact"),
        (
            {"authorized_payload_classes": [*required, excluded[0]]},
            "forbidden_payload_class_authorized",
        ),
    ]
    for index, (overrides, expected) in enumerate(cases):
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        result = _verify_egress(module, _valid_egress(case_dir, **overrides))
        assert result["status"] == "blocked"
        assert expected in result["failures"]


def _calibration_payload() -> dict:
    payload = json.loads(
        (ROOT / "configs/benchmark_judge_calibration.template.json").read_text(encoding="utf-8")
    )
    payload.update(
        {
            "calibration_id": "oaa_judge_calibration_rc3_fixture",
            "status": "calibrated_pass",
            "created_at": "2026-08-14T00:00:00Z",
        }
    )
    payload["judge"] = {
        "backend": "codex_app_server",
        "model_id": "gpt-5.6-luna",
        "revision": None,
        "role": "semantic_answer_quality",
        "sampling": {"temperature": 0, "seed_policy": "backend_seed_unsupported_receipted"},
    }
    payload["human_review"] = {
        "reviewer_count": 2,
        "case_count": 20,
        "blinded": True,
        "disagreements_preserved": True,
    }
    payload["artifacts"] = {
        key: hashlib.sha256(key.encode("utf-8")).hexdigest()
        for key in payload["artifacts"]
    }
    payload["probe_counts"] = {key: 4 for key in payload["probe_counts"]}
    payload["observed"] = {
        "macro_f1": 0.9,
        "false_positive_rate": 0.1,
        "false_negative_rate": 0.1,
        "order_flip_rate": 0.05,
    }
    return payload


def test_judge_stays_blocked_without_real_calibration_and_template_fails() -> None:
    module = _module()
    plan = _plan()

    absent = module.verify_judge_calibration(None, root=ROOT, judge_contract=plan["judge"])
    template = module.verify_judge_calibration(
        ROOT / "configs/benchmark_judge_calibration.template.json",
        root=ROOT,
        judge_contract=plan["judge"],
    )

    assert absent["status"] == "blocked_not_requested"
    assert absent["judge_execution_enabled"] is False
    assert template["status"] == "blocked"
    assert template["judge_execution_enabled"] is False
    assert "judge_calibration_not_passed" in template["failures"]


def test_real_passing_calibration_can_enable_advisory_judging(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(_calibration_payload()), encoding="utf-8")

    result = module.verify_judge_calibration(path, root=ROOT, judge_contract=plan["judge"])

    assert result["status"] == "pass"
    assert result["judge_execution_enabled"] is True
    assert result["metrics_pass"] is True


def test_malformed_judge_metrics_fail_closed_without_enabling_execution(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    payload = _calibration_payload()
    payload["observed"]["macro_f1"] = "not-a-number"
    path = tmp_path / "malformed-calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = module.verify_judge_calibration(path, root=ROOT, judge_contract=plan["judge"])

    assert result["status"] == "blocked"
    assert result["judge_execution_enabled"] is False
    assert "judge_calibration_schema_invalid" in result["failures"]
    assert "judge_calibration_metrics_below_threshold" in result["failures"]


def test_output_start_state_rejects_existing_benchmark_results(tmp_path: Path) -> None:
    module = _module()

    assert module.verify_output_start_state(tmp_path, "outputs/final")["status"] == "pass"
    output = tmp_path / "outputs/final"
    output.mkdir(parents=True)
    assert module.verify_output_start_state(tmp_path, "outputs/final")["status"] == "pass"
    (output / "responses.sqlite").write_bytes(b"not fresh")

    result = module.verify_output_start_state(tmp_path, "outputs/final")
    assert result["status"] == "blocked"
    assert result["files"] == ["responses.sqlite"]


def test_output_schedule_rejects_model_trial_collisions(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    plan["internal_benchmark"]["output_layout"] = "{output_root}/one-shared-directory"

    result = module.verify_output_schedule(tmp_path, plan)

    assert result["status"] == "blocked"
    assert "per_model_trial_output_collision" in result["failures"]


def test_public_package_receipt_is_tied_to_exact_source_inventory(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "source"
    release = tmp_path / "release"
    (source / "configs").mkdir(parents=True)
    release.mkdir()
    (source / "README.md").write_text("source\n", encoding="utf-8")
    manifest = {
        "schema_version": "open_agronomy_agent.public_repository_manifest.v1",
        "release_id": "fixture",
        "paths": ["README.md"],
        "trees": [],
        "globs": [],
        "exclude_globs": [],
    }
    manifest_path = source / "configs/public_repository_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    packaged = release / "README.md"
    packaged.write_text("source\n", encoding="utf-8")
    row = {
        "path": "README.md",
        "bytes": packaged.stat().st_size,
        "sha256": hashlib.sha256(packaged.read_bytes()).hexdigest(),
    }
    receipt = {
        "schema_version": "open_agronomy_agent.public_repository_receipt.v1",
        "release_id": "fixture",
        "built_at": "2026-08-14T11:00:00Z",
        "manifest_path": "configs/public_repository_manifest.json",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "file_count": 1,
        "total_bytes": row["bytes"],
        "files": [row],
    }
    (release / "PUBLIC_RELEASE_RECEIPT.json").write_text(json.dumps(receipt), encoding="utf-8")

    passed = module.verify_public_release_receipt(
        source,
        release,
        manifest_path=manifest_path,
        checked_at=dt.datetime(2026, 8, 14, 12, tzinfo=dt.UTC),
    )
    (source / "README.md").write_text("changed after package\n", encoding="utf-8")
    stale = module.verify_public_release_receipt(
        source,
        release,
        manifest_path=manifest_path,
        checked_at=dt.datetime(2026, 8, 14, 12, tzinfo=dt.UTC),
    )

    assert passed["status"] == "pass"
    assert stale["status"] == "blocked"
    assert "public_release_not_bound_to_current_source" in stale["failures"]


def test_environment_receipt_must_match_commit_runtime_dependencies_and_packages(tmp_path: Path) -> None:
    module = _module()
    from scripts.capture_release_environment import build_environment_receipt

    receipt = build_environment_receipt(ROOT, captured_at="2026-08-14T11:00:00Z")
    receipt["source"]["commit"] = "fixture-commit"
    receipt["source"]["worktree_clean"] = True
    path = tmp_path / "environment.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")

    passed = module.verify_environment_receipt(
        ROOT,
        path,
        git_commit="fixture-commit",
        checked_at=dt.datetime(2026, 8, 14, 12, tzinfo=dt.UTC),
    )
    stale_receipt = copy.deepcopy(receipt)
    stale_receipt["source"]["commit"] = "stale-commit"
    stale_receipt["python_packages"] = stale_receipt["python_packages"][:-1]
    path.write_text(json.dumps(stale_receipt), encoding="utf-8")
    stale = module.verify_environment_receipt(
        ROOT,
        path,
        git_commit="fixture-commit",
        checked_at=dt.datetime(2026, 8, 14, 12, tzinfo=dt.UTC),
    )

    assert passed["status"] == "pass"
    assert stale["status"] == "blocked"
    assert "environment_receipt_commit_mismatch" in stale["failures"]
    assert "environment_python_packages_mismatch" in stale["failures"]
