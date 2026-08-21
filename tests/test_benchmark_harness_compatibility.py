from __future__ import annotations

import json
from pathlib import Path

from agronomy_agent.benchmark_harness_compatibility import (
    EXECUTOR_CAPABILITIES_SCHEMA_VERSION,
    REQUIRED_ARTIFACT_RECEIPTS,
    compare_benchmark_receipts,
    derive_system_configuration_sha256,
    negotiate_harness,
    stable_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "configs/open_agronomy_benchmark_v2_harness_contract.json").read_text(
        encoding="utf-8"
    )
)
COMPONENTS = tuple(CONTRACT["component_contracts"])


def _receipts(seed: str = "a") -> dict[str, str]:
    return {
        role: stable_sha256([seed, role])
        for role in REQUIRED_ARTIFACT_RECEIPTS
    }


def _capabilities() -> dict:
    capabilities = {
        "schema_version": EXECUTOR_CAPABILITIES_SCHEMA_VERSION,
        "executor_id": "test_executor",
        "executor_version": "test-v1",
        "result_class": "observed_system_execution_nonclaim",
        "benchmark_id": "open_agronomy_benchmark_v2",
        "observation_schema_version": CONTRACT["observation_schema_version"],
        "metric_schema_version": CONTRACT["metric_schema_version"],
        "stage_topology": CONTRACT["stage_topology"],
        "component_contract_versions": {
            key: value["contract_version"]
            for key, value in CONTRACT["component_contracts"].items()
        },
        "feature_contract_versions": {
            key: value["contract_version"]
            for key, value in CONTRACT["feature_contracts"].items()
        },
        "implementation_receipts": {
            key: stable_sha256(["implementation", key])
            for key in CONTRACT["required_implementation_receipts"]
        },
        "component_configuration_receipts": {
            key: stable_sha256(["component-configuration", key])
            for key in CONTRACT["component_contracts"]
        },
        "semantic_profile": {
            "schema_version": CONTRACT["semantic_profile"]["schema_version"],
            "construct_profile_sha256": stable_sha256(CONTRACT["semantic_profile"]),
            "tool_implementations": {
                "test_calculator": {
                    "implementation_version": "test-v1",
                    "family": "supplied_input_arithmetic",
                    "operations": ["unit_conversion"],
                    "authority_roles": ["supplied_inputs_arithmetic_only"],
                }
            },
            "evidence_implementations": {
                "test_documents": {
                    "implementation_version": "test-v1",
                    "modality": "document",
                }
            },
        },
        "system_identity": {
            "system_id": "open_agronomy_agent",
            "system_revision": "test-revision",
            "system_configuration_sha256": "",
        },
    }
    capabilities["system_identity"][
        "system_configuration_sha256"
    ] = derive_system_configuration_sha256(capabilities)
    return capabilities


def test_exact_harness_negotiation_emits_separate_construct_cohort_and_system_identity() -> None:
    report = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=_capabilities(),
        artifact_receipts=_receipts(),
    )

    assert report["status"] == "comparable"
    assert report["run_permitted"] is True
    assert len(report["construct_fingerprint"]) == 64
    assert len(report["cohort_fingerprint"]) == 64
    assert len(report["system_fingerprint"]) == 64
    assert len({
        report["construct_fingerprint"],
        report["cohort_fingerprint"],
        report["system_fingerprint"],
    }) == 3


def test_unknown_active_feature_and_stage_change_fail_before_execution() -> None:
    capabilities = _capabilities()
    capabilities["feature_contract_versions"] = {
        **capabilities["feature_contract_versions"],
        "new_active_planning_stage": "v1",
    }
    capabilities["stage_topology"] = [*capabilities["stage_topology"], "planning_finalizer"]

    report = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=capabilities,
        artifact_receipts=_receipts(),
    )

    assert report["status"] == "new_benchmark_required"
    assert report["run_permitted"] is False
    assert "active_stage_topology_changed" in report["reason_codes"]
    assert any(reason.startswith("unknown_active_features:") for reason in report["reason_codes"])


def test_compatibility_decision_separates_comparison_migration_and_new_construct() -> None:
    baseline = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=_capabilities(),
        artifact_receipts=_receipts(),
    )
    another_system = dict(baseline)
    another_system["system_fingerprint"] = stable_sha256("another-system")
    comparable = compare_benchmark_receipts(baseline, another_system)
    assert comparable["status"] == "comparable"
    assert comparable["may_compare_as_distinct_systems"] is True
    assert comparable["may_pool"] is False

    representation_change = dict(another_system)
    representation_change["cohort_fingerprint"] = stable_sha256("new-cohort")
    unreceipted = compare_benchmark_receipts(baseline, representation_change)
    assert unreceipted["status"] == "new_benchmark_required"

    representation_change["migration_receipt"] = {
        "adapter_id": "test_only_lossless_representation_adapter",
        "adapter_version": "test-v1",
        "from_observation_schema_version": "test.observation.v0",
        "to_observation_schema_version": "test.observation.v1",
        "adapter_declaration_sha256": stable_sha256("test-adapter-declaration"),
        "adapter_sha256": stable_sha256("test-adapter"),
        "test_artifact_sha256": stable_sha256("test-adapter-tests"),
        "raw_observation_sha256": stable_sha256("raw-observations"),
        "migrated_observation_sha256": stable_sha256("migrated-observations"),
        "lossless": True,
        "raw_observation_preserved": True,
        "from_cohort_fingerprint": baseline["cohort_fingerprint"],
        "to_cohort_fingerprint": representation_change["cohort_fingerprint"],
    }
    forged = compare_benchmark_receipts(baseline, representation_change)
    assert forged["status"] == "new_benchmark_required"
    assert forged["may_compare_as_distinct_systems"] is False

    construct_change = dict(representation_change)
    construct_change["construct_fingerprint"] = stable_sha256("new-construct")
    successor = compare_benchmark_receipts(baseline, construct_change)
    assert successor["status"] == "new_benchmark_required"
    assert successor["may_pool"] is False


def test_negotiation_emits_migration_required_only_for_declared_tested_adapter() -> None:
    contract = json.loads(json.dumps(CONTRACT))
    contract["required_implementation_receipts"].append("test_only_adapter")
    contract["migration_adapters"] = [
        {
            "adapter_id": "test_only_observation_v0_to_v1",
            "adapter_version": "test-v1",
            "from_observation_schema_version": "test.observation.v0",
            "to_observation_schema_version": CONTRACT["observation_schema_version"],
            "implementation_receipt_id": "test_only_adapter",
            "test_artifact_role": "test_harness_compatibility",
            "eligible_change_classes": ["observation_schema"],
            "lossless": True,
            "raw_observation_preserved": True,
        }
    ]
    adapter_declaration = contract["migration_adapters"][0]
    artifacts = _receipts()
    capabilities = _capabilities()
    capabilities["observation_schema_version"] = "test.observation.v0"
    capabilities["implementation_receipts"]["test_only_adapter"] = stable_sha256(
        "test-only-adapter-implementation"
    )
    capabilities["migration_adapter_receipt"] = {
        "adapter_id": "test_only_observation_v0_to_v1",
        "adapter_version": "test-v1",
        "from_observation_schema_version": "test.observation.v0",
        "to_observation_schema_version": CONTRACT["observation_schema_version"],
        "adapter_declaration_sha256": stable_sha256(adapter_declaration),
        "adapter_sha256": capabilities["implementation_receipts"]["test_only_adapter"],
        "test_artifact_sha256": artifacts["test_harness_compatibility"],
        "raw_observation_sha256": stable_sha256("test-raw-observation"),
        "migrated_observation_sha256": stable_sha256("test-migrated-observation"),
        "lossless": True,
        "raw_observation_preserved": True,
    }
    capabilities["system_identity"][
        "system_configuration_sha256"
    ] = derive_system_configuration_sha256(capabilities)

    report = negotiate_harness(
        contract=contract,
        interface_components=COMPONENTS,
        capabilities=capabilities,
        artifact_receipts=artifacts,
    )

    assert report["status"] == "migration_required"
    assert report["run_permitted"] is False
    assert report["reason_codes"] == ["observation_schema_mismatch"]
    assert report["migration_adapter_receipt"]["raw_observation_preserved"] is True

    baseline_capabilities = json.loads(json.dumps(capabilities))
    baseline_capabilities["observation_schema_version"] = CONTRACT[
        "observation_schema_version"
    ]
    baseline_capabilities.pop("migration_adapter_receipt")
    baseline_capabilities["system_identity"][
        "system_configuration_sha256"
    ] = derive_system_configuration_sha256(baseline_capabilities)
    baseline = negotiate_harness(
        contract=contract,
        interface_components=COMPONENTS,
        capabilities=baseline_capabilities,
        artifact_receipts=artifacts,
    )
    comparison = compare_benchmark_receipts(baseline, report)
    assert baseline["status"] == "comparable"
    assert comparison["status"] == "migration_required"
    assert comparison["reason_codes"] == [
        "declared_tested_lossless_representation_migration"
    ]
    assert comparison["may_pool"] is False

    forged_report = json.loads(json.dumps(report))
    forged_report["migration_adapter_receipt"]["adapter_sha256"] = stable_sha256(
        "forged-adapter"
    )
    forged = compare_benchmark_receipts(baseline, forged_report)
    assert forged["status"] == "new_benchmark_required"
    assert forged["reason_codes"] == ["missing_or_malformed_negotiation_receipt"]


def test_negotiation_recomputes_system_configuration_from_actual_receipts() -> None:
    capabilities = _capabilities()
    capabilities["component_configuration_receipts"]["retrieval"] = stable_sha256(
        "tampered-runtime-assets"
    )

    report = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=capabilities,
        artifact_receipts=_receipts(),
    )

    assert report["status"] == "new_benchmark_required"
    assert "system_configuration_hash_mismatch" in report["reason_codes"]


def test_support_artifact_changes_remain_integrity_bound_without_changing_cohort() -> None:
    baseline = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=_capabilities(),
        artifact_receipts=_receipts(),
    )
    receipts = _receipts()
    receipts["test_design_audit"] = stable_sha256("changed-test-comment")
    support_change = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=_capabilities(),
        artifact_receipts=receipts,
    )

    assert baseline["artifact_receipts"] != support_change["artifact_receipts"]
    assert baseline["cohort_fingerprint"] == support_change["cohort_fingerprint"]


def test_equivalent_new_tool_id_is_a_distinct_comparable_system() -> None:
    baseline = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=_capabilities(),
        artifact_receipts=_receipts(),
    )
    capabilities = _capabilities()
    capabilities["semantic_profile"]["tool_implementations"][
        "equivalent_calculator"
    ] = {
        "implementation_version": "equivalent-v1",
        "family": "supplied_input_arithmetic",
        "operations": ["unit_conversion"],
        "authority_roles": ["supplied_inputs_arithmetic_only"],
    }
    capabilities["system_identity"][
        "system_configuration_sha256"
    ] = derive_system_configuration_sha256(capabilities)

    replacement = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=capabilities,
        artifact_receipts=_receipts(),
    )

    assert replacement["status"] == "comparable"
    assert replacement["construct_fingerprint"] == baseline["construct_fingerprint"]
    assert replacement["cohort_fingerprint"] == baseline["cohort_fingerprint"]
    assert replacement["system_fingerprint"] != baseline["system_fingerprint"]
    comparison = compare_benchmark_receipts(baseline, replacement)
    assert comparison["status"] == "comparable"
    assert comparison["may_compare_as_distinct_systems"] is True
    assert comparison["may_pool"] is False


def test_unknown_semantic_mapping_fails_negotiation_closed() -> None:
    capabilities = _capabilities()
    capabilities["semantic_profile"]["tool_implementations"]["new_tool"] = {
        "implementation_version": "new-v1",
        "family": "new_unfrozen_family",
        "operations": ["new_operation"],
        "authority_roles": ["new_authority"],
    }
    capabilities["semantic_profile"]["evidence_implementations"]["new_evidence"] = {
        "implementation_version": "new-v1",
        "modality": "new_unfrozen_modality",
    }
    capabilities["system_identity"][
        "system_configuration_sha256"
    ] = derive_system_configuration_sha256(capabilities)

    report = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=capabilities,
        artifact_receipts=_receipts(),
    )

    assert report["status"] == "new_benchmark_required"
    assert "unknown_tool_semantic_mapping:new_tool" in report["reason_codes"]
    assert "unknown_evidence_semantic_mapping:new_evidence" in report["reason_codes"]


def test_construct_semantic_taxonomy_change_requires_new_benchmark() -> None:
    baseline = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=_capabilities(),
        artifact_receipts=_receipts(),
    )
    successor_contract = json.loads(json.dumps(CONTRACT))
    successor_contract["semantic_profile"]["verifier_semantics"][
        "decision_unit"
    ] = "field_recommendation"
    successor_capabilities = _capabilities()
    successor_capabilities["semantic_profile"][
        "construct_profile_sha256"
    ] = stable_sha256(successor_contract["semantic_profile"])
    successor_capabilities["system_identity"][
        "system_configuration_sha256"
    ] = derive_system_configuration_sha256(successor_capabilities)
    successor = negotiate_harness(
        contract=successor_contract,
        interface_components=COMPONENTS,
        capabilities=successor_capabilities,
        artifact_receipts=_receipts(),
    )

    assert successor["status"] == "comparable"
    comparison = compare_benchmark_receipts(baseline, successor)
    assert comparison["status"] == "new_benchmark_required"
    assert comparison["reason_codes"] == ["benchmark_construct_changed"]


def test_compare_requires_full_negotiation_identity_and_never_pools_it() -> None:
    digest = stable_sha256("same")
    malformed = {
        "construct_fingerprint": digest,
        "cohort_fingerprint": digest,
    }
    rejected = compare_benchmark_receipts(malformed, malformed)
    assert rejected["status"] == "new_benchmark_required"
    assert rejected["reason_codes"] == ["missing_or_malformed_negotiation_receipt"]
    assert rejected["may_pool"] is False

    negotiation = negotiate_harness(
        contract=CONTRACT,
        interface_components=COMPONENTS,
        capabilities=_capabilities(),
        artifact_receipts=_receipts(),
    )
    identical = compare_benchmark_receipts(negotiation, negotiation)
    assert identical["status"] == "comparable"
    assert identical["may_compare_as_distinct_systems"] is True
    assert identical["may_pool"] is False
