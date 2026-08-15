from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import yaml
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit_final_benchmark_readiness.py"
PLAN = ROOT / "configs/final_benchmark_round_rc3.json"
LIFECYCLE = ROOT / "configs/benchmark_round_lifecycle_v1.json"
FROZEN_PLAN_SHA256 = "f1fabf6ab5dca84acc41b8925663d11759ab9b86e8c5fa5ffeffe15e65e21ece"


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
        "schema_version": plan["egress"]["authorization_schema"],
        "authorization_decision": "authorized",
        "benchmark_id": _internal_contract(plan)["benchmark_id"],
        "benchmark_suite_sha256": plan["internal_benchmark"]["suite_sha256"],
        "authorization_source": "human-review-receipt-20260814",
        "authorized_by_key_id": "benchmark-authority-key-7",
        "authorized_at": "2026-08-14T11:00:00Z",
        "expires_at": "2026-08-14T13:00:00Z",
        "recipient_backend": plan["egress"]["recipient_backend"],
        "model_id": plan["egress"]["recipient_model_id"],
        "reasoning_effort": plan["egress"]["recipient_reasoning_effort"],
        "model_config_sha256": plan["egress"]["recipient_model_config_sha256"],
        "suite_case_contract_sha256": plan["egress"]["suite_case_contract_sha256"],
        "egress_artifact_contract_sha256": plan["egress"][
            "egress_artifact_contract_sha256"
        ],
        "static_prompt_contract_sha256": plan["egress"][
            "static_prompt_contract_sha256"
        ],
        "authorized_payload_classes": plan["egress"]["authorized_payload_classes_exact"],
        "excluded_payload_classes": plan["egress"]["excluded_payload_classes_exact"],
        "payload_classes_by_phase_and_arm": plan["egress"]["payload_classes_by_phase_and_arm"],
    }
    payload.update(overrides)
    path = tmp_path / "egress.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _verify_egress(module, path: Path) -> dict:
    plan = _plan()
    return module.verify_egress_authorization(
        path,
        authorization_schema=plan["egress"]["authorization_schema"],
        benchmark_id=_internal_contract(plan)["benchmark_id"],
        suite_sha256=plan["internal_benchmark"]["suite_sha256"],
        required_payloads=plan["egress"]["authorized_payload_classes_exact"],
        forbidden_payloads=plan["egress"]["excluded_payload_classes_exact"],
        required_phase_arm_map=plan["egress"]["payload_classes_by_phase_and_arm"],
        required_recipient={
            "recipient_backend": plan["egress"]["recipient_backend"],
            "model_id": plan["egress"]["recipient_model_id"],
            "reasoning_effort": plan["egress"]["recipient_reasoning_effort"],
            "model_config_sha256": plan["egress"]["recipient_model_config_sha256"],
        },
        required_contract_bindings={
            "suite_case_contract_sha256": plan["egress"][
                "suite_case_contract_sha256"
            ],
            "egress_artifact_contract_sha256": plan["egress"][
                "egress_artifact_contract_sha256"
            ],
            "static_prompt_contract_sha256": plan["egress"][
                "static_prompt_contract_sha256"
            ],
        },
        checked_at=dt.datetime(2026, 8, 14, 12, tzinfo=dt.UTC),
    )


def test_rc3_is_append_only_nonclaim_master_runtime_with_retired_external_v1() -> None:
    module = _module()
    plan = _plan()

    result = module.validate_plan_semantics(plan, root=ROOT, plan_path=PLAN)

    assert result["status"] == "blocked"
    assert result["failures"] == ["completed_plan_non_executable"]
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
    assert plan["egress"]["authorization_schema"] == module.BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA
    assert plan["egress"]["authorized_payload_classes_exact"] == list(
        module.BENCHMARK_EGRESS_AUTHORIZED_PAYLOAD_CLASSES
    )
    assert plan["egress"]["excluded_payload_classes_exact"] == list(
        module.BENCHMARK_EGRESS_FORBIDDEN_PAYLOAD_CLASSES
    )
    runtime_phase_arm_map = json.loads(
        json.dumps(module.BENCHMARK_EGRESS_PAYLOAD_CLASSES_BY_PHASE_AND_ARM)
    )
    assert plan["egress"]["payload_classes_by_phase_and_arm"] == runtime_phase_arm_map
    assert plan["egress"]["recipient_backend"] == "codex_app_server_chatgpt_auth"
    assert plan["egress"]["recipient_model_id"] == "gpt-5.6-luna"
    assert plan["egress"]["recipient_reasoning_effort"] == "high"
    assert plan["egress"]["recipient_model_config_sha256"] == plan["models"][2][
        "config_sha256"
    ]
    assert plan["judge"] == {
        "default_enabled": False,
        "execution_allowed": False,
        "payload_class_present": False,
        "role_boundary": "RC3 performs no automated semantic judging. Human review remains a separate post-run activity and is not an egress payload class.",
        "roles": [],
        "status": "disabled_for_rc3",
    }
    assert plan["replication"]["judge_seed_application"] == "not_requested"
    assert plan["private_knowledge_policy"]["policy_id"] == "disabled_for_all_benchmark_arms"
    assert plan["status"] == "candidate_generation_requires_clean_preflight"
    assert "completion" not in plan
    assert hashlib.sha256(PLAN.read_bytes()).hexdigest() == FROZEN_PLAN_SHA256
    lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
    assert lifecycle["schema_version"] == "open_agronomy_agent.benchmark_round_lifecycle.v1"
    assert len(lifecycle["records"]) == 1
    completion = lifecycle["records"][0]
    assert completion == {
        "artifact_manifest_path": "docs/public/development-benchmark-rc3-20260815/source_data/artifact_manifest.json",
        "artifact_manifest_sha256": "47bff35a2a645327378dab65a6ae080f119b9f3feca604322e2e1a3af01a22d4",
        "benchmark_source_commit": "3e30fb5de38105fa5bba3845411eb2174c21d3c4",
        "canonical_arm_executions": 36,
        "canonical_observations": 8676,
        "canonical_trials": 9,
        "checkpoint_receipt_path": "docs/public/development-benchmark-rc3-20260815/source_data/checkpoint_validation_receipt.json",
        "checkpoint_receipt_sha256": "898b689b7e07378f09cb2b1e9f8d444e8c44301a82166e5f635f10f5d50e3ccc",
        "completed_at": "2026-08-15",
        "new_observations_allowed": False,
        "plan_path": "configs/final_benchmark_round_rc3.json",
        "plan_sha256": FROZEN_PLAN_SHA256,
        "round_id": "open_agronomy_development_rc3_20260814",
        "status": "completed_frozen_nonclaim",
        "successor_round_required": True,
    }
    for path_key, sha_key in (
        ("artifact_manifest_path", "artifact_manifest_sha256"),
        ("checkpoint_receipt_path", "checkpoint_receipt_sha256"),
    ):
        artifact = ROOT / completion[path_key]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == completion[sha_key]


def test_completed_rc3_lifecycle_fails_closed_on_plan_identity_drift(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    lifecycle = json.loads(LIFECYCLE.read_text(encoding="utf-8"))
    lifecycle["records"][0]["plan_sha256"] = "0" * 64
    altered = tmp_path / "benchmark_round_lifecycle_v1.json"
    altered.write_text(json.dumps(lifecycle), encoding="utf-8")

    result = module.validate_plan_semantics(
        plan,
        root=ROOT,
        plan_path=PLAN,
        lifecycle_path=altered,
    )

    assert result["status"] == "blocked"
    assert "round_lifecycle_plan_sha256_mismatch" in result["failures"]
    assert "completed_plan_non_executable" in result["failures"]


def test_completed_rc3_lifecycle_is_required(tmp_path: Path) -> None:
    module = _module()

    result = module.validate_plan_semantics(
        _plan(),
        root=ROOT,
        plan_path=PLAN,
        lifecycle_path=tmp_path / "missing-lifecycle.json",
    )

    assert result["status"] == "blocked"
    assert result["failures"] == ["round_lifecycle_missing"]


def test_completed_rc3_contract_stays_frozen_when_current_public_release_advances() -> None:
    from agronomy_agent.agent import (
        build_benchmark_egress_artifact_contract,
        load_agent_resources,
    )
    from agronomy_agent.codex_app_server import build_benchmark_static_prompt_contract
    from agronomy_agent.evals import build_benchmark_suite_case_contract, load_jsonl

    module = _module()
    plan = _plan()
    runtime_phase_arm_map = json.loads(
        json.dumps(module.BENCHMARK_EGRESS_PAYLOAD_CLASSES_BY_PHASE_AND_ARM)
    )
    contract = _internal_contract(plan)
    remote_model = next(
        model for model in plan["models"] if model["backend"] == "codex_app_server"
    )
    remote_config = yaml.safe_load(
        (ROOT / remote_model["config_path"]).read_text(encoding="utf-8")
    ) or {}
    rag_config = ROOT / contract["rag_config"]
    suite_case = build_benchmark_suite_case_contract(
        load_jsonl(ROOT / contract["suite_path"]),
        benchmark_suite_sha256=plan["internal_benchmark"]["suite_sha256"],
        answer_profile=contract["answer_profile"],
        prompt_profile=remote_config.get("prompt_profile") or "default",
        rag_resources=load_agent_resources(rag_config),
        use_eval_field_context=True,
    )
    artifact = build_benchmark_egress_artifact_contract(rag_config)
    static = build_benchmark_static_prompt_contract()

    assert len(suite_case["cases"]) == plan["internal_benchmark"]["rows"]
    assert plan["egress"]["suite_case_contract_sha256"] == suite_case["sha256"]
    frozen_artifact_sha256 = "df0e6b5d77a8ade022b075541046fefc07059ac0b14e36f1593130354a0c75ba"
    assert plan["egress"]["egress_artifact_contract_sha256"] == frozen_artifact_sha256
    assert artifact["sha256"] != frozen_artifact_sha256
    assert plan["egress"]["static_prompt_contract_sha256"] == static["sha256"]
    assert plan["private_knowledge_policy"]["child_cli_value"] == "disabled"
    assert plan["private_knowledge_policy"]["required_process_environment"] == {
        "AGRONOMY_AGENT_PRIVATE_KNOWLEDGE": "disabled"
    }
    assert plan["readiness"]["require_private_knowledge_disabled"] is True

    template = json.loads(
        (ROOT / "configs/benchmark_egress_authorization.template.json").read_text(
            encoding="utf-8"
        )
    )
    assert template["benchmark_id"] == "open_agronomy_canadian_performance_v1_runtime_v2"
    assert template["schema_version"] == module.BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA
    assert template["authorized_payload_classes"] == list(
        module.BENCHMARK_EGRESS_AUTHORIZED_PAYLOAD_CLASSES
    )
    assert template["excluded_payload_classes"] == list(
        module.BENCHMARK_EGRESS_FORBIDDEN_PAYLOAD_CLASSES
    )
    assert template["payload_classes_by_phase_and_arm"] == runtime_phase_arm_map
    assert template["recipient_backend"] == plan["egress"]["recipient_backend"]
    assert template["model_id"] == plan["egress"]["recipient_model_id"]
    assert template["reasoning_effort"] == plan["egress"]["recipient_reasoning_effort"]
    assert template["model_config_sha256"] == plan["egress"][
        "recipient_model_config_sha256"
    ]
    assert template["suite_case_contract_sha256"] == suite_case["sha256"]
    assert template["egress_artifact_contract_sha256"] == frozen_artifact_sha256
    assert template["static_prompt_contract_sha256"] == static["sha256"]


def test_readiness_contract_resource_load_forces_private_overlay_off_and_restores_env(
    monkeypatch,
) -> None:
    module = _module()
    observed: list[str | None] = []

    def fake_load(_path: Path):
        observed.append(os.environ.get("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"))
        return SimpleNamespace(private_knowledge_overlay=None)

    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "auto")
    monkeypatch.setattr(module, "load_agent_resources", fake_load)

    result = module.load_public_benchmark_resources(Path("fixture-rag.yaml"))

    assert result.private_knowledge_overlay is None
    assert observed == ["disabled"]
    assert os.environ["AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"] == "auto"

    monkeypatch.setattr(
        module,
        "load_agent_resources",
        lambda _path: SimpleNamespace(private_knowledge_overlay=object()),
    )
    with pytest.raises(ValueError, match="private knowledge overlay loaded"):
        module.load_public_benchmark_resources(Path("fixture-rag.yaml"))


def test_rc2_plan_is_byte_retained_but_legacy_schema_cannot_pass_current_readiness() -> None:
    module = _module()
    plan = json.loads(
        (ROOT / "configs/final_benchmark_round_rc2.json").read_text(encoding="utf-8")
    )

    result = module.validate_plan_semantics(plan)

    assert plan["status"] == "candidate_generation_requires_clean_preflight"
    assert result["status"] == "blocked"
    assert "historical_plan_non_executable" in result["failures"]


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


def test_rc3_plan_rejects_egress_judge_or_private_knowledge_drift() -> None:
    module = _module()
    plan = _plan()
    plan["egress"]["authorization_schema"] = module.EGRESS_SCHEMA_V2
    plan["egress"]["payload_classes_by_phase_and_arm"]["candidate_generation"]["baseline"].append(
        "synthetic_eval_field_context"
    )
    plan["judge"]["execution_allowed"] = True
    plan["replication"]["judge_seed_application"] = "applied"
    plan["private_knowledge_policy"]["child_cli_value"] = "enabled"

    result = module.validate_plan_semantics(plan)

    assert result["status"] == "blocked"
    assert "egress_v4_schema_required" in result["failures"]
    assert "rc3_payload_phase_arm_map_mismatch" in result["failures"]
    assert "rc3_judge_execution_must_be_false" in result["failures"]
    assert "rc3_judge_seed_application_must_be_not_requested" in result["failures"]
    assert "rc3_private_knowledge_policy_mismatch" in result["failures"]


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
    assert local_one[local_one.index("--private-knowledge-policy") + 1] == "disabled"
    assert local_one[local_one.index("--output-dir") + 1] != local_two[local_two.index("--output-dir") + 1]
    assert "--judge" not in local_one
    assert "--codex-app-server" not in local_one
    assert "--codex-app-server" in remote
    assert "--build-review-packet" in local_one
    assert "--resume-partial-runs" in local_one
    assert "--reuse-complete-runs" in local_one


def test_rc3_never_emits_judge_even_if_legacy_flag_is_requested(tmp_path: Path) -> None:
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

    assert "--judge" not in gemma
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


def test_egress_v4_accepts_only_exact_current_human_authority(tmp_path: Path) -> None:
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


def test_egress_rejects_wrong_schema_placeholder_expired_and_non_utc_receipts(tmp_path: Path) -> None:
    module = _module()
    cases = [
        ({"schema_version": "open_agronomy_agent.benchmark_egress_authorization.v2"}, "schema_mismatch"),
        ({"authorization_decision": "template_not_authorized"}, "authorization_decision_not_authorized"),
        ({"authorization_source": "replace-with-human-authority"}, "human_authority_provenance_missing_or_placeholder"),
        ({"authorized_by_key_id": "example-authorizer"}, "human_authority_provenance_missing_or_placeholder"),
        ({"expires_at": "2026-08-14T11:30:00Z"}, "authorization_expired"),
        ({"authorized_at": "2026-08-14T11:00:00-06:00"}, "authorized_at_must_be_utc"),
        ({"model_id": "gpt-5.6-other"}, "recipient_identity_not_exact"),
        ({"reasoning_effort": "medium"}, "recipient_identity_not_exact"),
        ({"suite_case_contract_sha256": "0" * 64}, "contract_bindings_not_exact"),
        ({"egress_artifact_contract_sha256": "1" * 64}, "contract_bindings_not_exact"),
        ({"static_prompt_contract_sha256": "2" * 64}, "contract_bindings_not_exact"),
        ({"unexpected_extension": "not authorized"}, "unknown_authorization_fields_present"),
        ({"boundary": ""}, "authorization_boundary_empty"),
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


def test_egress_rejects_any_phase_arm_payload_map_drift(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    wrong = copy.deepcopy(plan["egress"]["payload_classes_by_phase_and_arm"])
    wrong["candidate_generation"]["baseline"].append("synthetic_eval_field_context")

    result = _verify_egress(
        module,
        _valid_egress(tmp_path, payload_classes_by_phase_and_arm=wrong),
    )

    assert result["status"] == "blocked"
    assert "payload_classes_by_phase_and_arm_not_exact" in result["failures"]


def test_rc3_judge_is_disabled_when_no_calibration_is_requested() -> None:
    module = _module()
    plan = _plan()

    absent = module.verify_judge_calibration(None, root=ROOT, judge_contract=plan["judge"])

    assert absent["status"] == "pass_disabled"
    assert absent["judge_execution_enabled"] is False
    assert absent["judge_seed_application"] == "not_requested"
    assert absent["failures"] == []


def test_rc3_rejects_even_a_supplied_calibration_without_reading_it(tmp_path: Path) -> None:
    module = _module()
    plan = _plan()
    path = tmp_path / "calibration.json"
    path.write_text("not even parsed in RC3\n", encoding="utf-8")

    result = module.verify_judge_calibration(path, root=ROOT, judge_contract=plan["judge"])

    assert result["status"] == "blocked"
    assert result["judge_execution_enabled"] is False
    assert result["judge_seed_application"] == "not_requested"
    assert result["failures"] == ["judge_calibration_forbidden_for_rc3"]


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
