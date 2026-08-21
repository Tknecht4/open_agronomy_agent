"""Fail-closed compatibility contracts for evolving benchmark harnesses.

The benchmark construct, its serialized observation form, and the system being
measured are separate identities.  This module keeps those identities separate
so that continued agent development cannot silently turn unlike observations
into one cohort.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Any


HARNESS_CONTRACT_SCHEMA_VERSION = "open_agronomy_agent.benchmark_harness_contract.v1"
EXECUTOR_CAPABILITIES_SCHEMA_VERSION = (
    "open_agronomy_agent.benchmark_executor_capabilities.v1"
)
NEGOTIATION_SCHEMA_VERSION = "open_agronomy_agent.benchmark_harness_negotiation.v1"
COMPATIBILITY_DECISION_SCHEMA_VERSION = (
    "open_agronomy_agent.benchmark_compatibility_decision.v1"
)
SEMANTIC_PROFILE_SCHEMA_VERSION = (
    "open_agronomy_agent.benchmark_v2_semantic_profile.v1"
)
COMPATIBILITY_STATES = frozenset(
    {"comparable", "migration_required", "new_benchmark_required"}
)
REQUIRED_ARTIFACT_RECEIPTS = (
    "suite",
    "contract",
    "case_schema",
    "causal_interface",
    "preregistration",
    "exposure_amendment",
    "metrics",
    "runner",
    "runner_cli",
    "audit",
    "test_metrics",
    "test_design_audit",
    "test_tool_contract",
    "test_runner",
    "test_runtime_contract",
    "harness_contract",
    "harness_amendment",
    "harness_compatibility",
    "test_harness_compatibility",
)
CONSTRUCT_ARTIFACT_RECEIPTS = (
    "suite",
    "contract",
    "case_schema",
    "causal_interface",
    "preregistration",
    "harness_contract",
    "metrics",
)
COHORT_ARTIFACT_RECEIPTS = (
    "suite",
    "contract",
    "case_schema",
    "causal_interface",
    "preregistration",
    "exposure_amendment",
    "metrics",
    "runner",
    "harness_contract",
    "harness_amendment",
    "harness_compatibility",
)

_MIGRATION_RECEIPT_FIELDS = frozenset(
    {
        "adapter_id",
        "adapter_version",
        "from_observation_schema_version",
        "to_observation_schema_version",
        "adapter_declaration_sha256",
        "adapter_sha256",
        "test_artifact_sha256",
        "raw_observation_sha256",
        "migrated_observation_sha256",
        "lossless",
        "raw_observation_preserved",
    }
)
_MIGRATION_CATALOG_ENTRY_FIELDS = frozenset(
    {
        "adapter_version",
        "from_observation_schema_version",
        "to_observation_schema_version",
        "adapter_declaration_sha256",
        "adapter_sha256",
        "test_artifact_sha256",
        "implementation_receipt_id",
        "test_artifact_role",
        "lossless",
        "raw_observation_preserved",
    }
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _exact_string_inventory(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"semantic profile {field} must be an array")
    normalized = tuple(str(item) for item in value)
    if not normalized or any(not item for item in normalized) or len(normalized) != len(
        set(normalized)
    ):
        raise ValueError(
            f"semantic profile {field} must contain unique non-empty strings"
        )
    return normalized


def _validate_construct_semantic_profile(profile: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "profile_id",
        "profile_version",
        "tool_semantics",
        "evidence_semantics",
        "answerability_states",
        "verifier_semantics",
    }
    if not isinstance(profile, Mapping) or set(profile) != required:
        raise ValueError("harness semantic profile fields are not exact")
    if profile.get("schema_version") != SEMANTIC_PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported harness semantic profile schema")
    if not str(profile.get("profile_id") or "") or not str(
        profile.get("profile_version") or ""
    ):
        raise ValueError("harness semantic profile identity is missing")
    tool_semantics = profile.get("tool_semantics")
    if not isinstance(tool_semantics, Mapping) or set(tool_semantics) != {
        "plan_statuses",
        "families",
    }:
        raise ValueError("tool semantic profile fields are not exact")
    _exact_string_inventory(
        tool_semantics.get("plan_statuses"), field="tool plan_statuses"
    )
    families = tool_semantics.get("families")
    if not isinstance(families, Mapping) or not families:
        raise ValueError("tool semantic profile requires at least one family")
    for family_id, family in families.items():
        if not str(family_id) or not isinstance(family, Mapping) or set(family) != {
            "operations",
            "authority_roles",
            "invocation_statuses",
            "result_statuses",
        }:
            raise ValueError(f"tool semantic family is malformed: {family_id}")
        for field in (
            "operations",
            "authority_roles",
            "invocation_statuses",
            "result_statuses",
        ):
            _exact_string_inventory(
                family.get(field), field=f"tool family {family_id} {field}"
            )
    evidence = profile.get("evidence_semantics")
    if not isinstance(evidence, Mapping) or set(evidence) != {
        "modalities",
        "evidence_roles",
        "factual_authority_classes",
        "field_action_authority_classes",
        "retrieval_statuses",
    }:
        raise ValueError("evidence semantic profile fields are not exact")
    for field in evidence:
        _exact_string_inventory(evidence.get(field), field=f"evidence {field}")
    _exact_string_inventory(
        profile.get("answerability_states"), field="answerability_states"
    )
    verifier = profile.get("verifier_semantics")
    if not isinstance(verifier, Mapping) or set(verifier) != {
        "policy_id",
        "policy_version",
        "decision_unit",
        "outcome_schema_version",
        "outcomes",
    }:
        raise ValueError("verifier semantic profile fields are not exact")
    if not all(
        isinstance(verifier.get(field), str) and verifier.get(field)
        for field in (
            "policy_id",
            "policy_version",
            "decision_unit",
            "outcome_schema_version",
        )
    ):
        raise ValueError("verifier semantic profile identity is malformed")
    _exact_string_inventory(verifier.get("outcomes"), field="verifier outcomes")
    return json.loads(canonical_json(profile))


def _validate_executor_semantic_profile(
    *,
    capabilities: Mapping[str, Any],
    construct_profile: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    reasons: list[str] = []
    raw = capabilities.get("semantic_profile")
    required = {
        "schema_version",
        "construct_profile_sha256",
        "tool_implementations",
        "evidence_implementations",
    }
    if not isinstance(raw, Mapping) or set(raw) != required:
        return {}, ["executor_semantic_profile_missing_or_malformed"]
    if raw.get("schema_version") != SEMANTIC_PROFILE_SCHEMA_VERSION:
        reasons.append("executor_semantic_profile_schema_mismatch")
    expected_construct_sha256 = stable_sha256(construct_profile)
    if raw.get("construct_profile_sha256") != expected_construct_sha256:
        reasons.append("construct_semantic_profile_changed")
    tool_implementations = raw.get("tool_implementations")
    normalized_tools: dict[str, Any] = {}
    families = construct_profile["tool_semantics"]["families"]
    if not isinstance(tool_implementations, Mapping):
        reasons.append("tool_implementation_inventory_malformed")
    else:
        for tool_id, declaration in tool_implementations.items():
            if (
                not str(tool_id)
                or not isinstance(declaration, Mapping)
                or set(declaration)
                != {
                    "implementation_version",
                    "family",
                    "operations",
                    "authority_roles",
                }
            ):
                reasons.append(f"tool_implementation_mapping_malformed:{tool_id}")
                continue
            family_id = str(declaration.get("family") or "")
            family = families.get(family_id)
            operations = tuple(str(value) for value in declaration.get("operations") or ())
            authorities = tuple(
                str(value) for value in declaration.get("authority_roles") or ()
            )
            if (
                not isinstance(family, Mapping)
                or not str(declaration.get("implementation_version") or "")
                or not operations
                or not authorities
                or not set(operations).issubset(set(family.get("operations") or ()))
                or not set(authorities).issubset(
                    set(family.get("authority_roles") or ())
                )
            ):
                reasons.append(f"unknown_tool_semantic_mapping:{tool_id}")
                continue
            normalized_tools[str(tool_id)] = {
                "implementation_version": str(declaration["implementation_version"]),
                "family": family_id,
                "operations": list(operations),
                "authority_roles": list(authorities),
            }
    evidence_implementations = raw.get("evidence_implementations")
    normalized_evidence: dict[str, Any] = {}
    allowed_modalities = set(
        construct_profile["evidence_semantics"]["modalities"]
    )
    if not isinstance(evidence_implementations, Mapping):
        reasons.append("evidence_implementation_inventory_malformed")
    else:
        for implementation_id, declaration in evidence_implementations.items():
            if (
                not str(implementation_id)
                or not isinstance(declaration, Mapping)
                or set(declaration) != {"implementation_version", "modality"}
                or not str(declaration.get("implementation_version") or "")
                or str(declaration.get("modality") or "") not in allowed_modalities
            ):
                reasons.append(
                    f"unknown_evidence_semantic_mapping:{implementation_id}"
                )
                continue
            normalized_evidence[str(implementation_id)] = {
                "implementation_version": str(declaration["implementation_version"]),
                "modality": str(declaration["modality"]),
            }
    return {
        "schema_version": SEMANTIC_PROFILE_SCHEMA_VERSION,
        "construct_profile_sha256": expected_construct_sha256,
        "construct_semantics": json.loads(canonical_json(construct_profile)),
        "tool_implementations": normalized_tools,
        "evidence_implementations": normalized_evidence,
    }, reasons


def derive_system_configuration_sha256(capabilities: Mapping[str, Any]) -> str:
    """Derive system configuration identity from answer-affecting runtime facts.

    Executors report the resulting digest, but negotiation recomputes it rather
    than trusting an opaque caller-provided value.  The hash deliberately omits
    the reported digest itself so the identity is non-circular.
    """

    system_identity = capabilities.get("system_identity")
    identity = system_identity if isinstance(system_identity, Mapping) else {}
    return stable_sha256(
        {
            "system_id": str(identity.get("system_id") or ""),
            "system_revision": str(identity.get("system_revision") or ""),
            "executor_id": str(capabilities.get("executor_id") or ""),
            "executor_version": str(capabilities.get("executor_version") or ""),
            "result_class": str(capabilities.get("result_class") or ""),
            "benchmark_id": str(capabilities.get("benchmark_id") or ""),
            "observation_schema_version": str(
                capabilities.get("observation_schema_version") or ""
            ),
            "metric_schema_version": str(
                capabilities.get("metric_schema_version") or ""
            ),
            "stage_topology": [
                str(value) for value in capabilities.get("stage_topology") or ()
            ],
            "component_contract_versions": {
                str(key): str(value)
                for key, value in (
                    capabilities.get("component_contract_versions") or {}
                ).items()
            },
            "feature_contract_versions": {
                str(key): str(value)
                for key, value in (
                    capabilities.get("feature_contract_versions") or {}
                ).items()
            },
            "implementation_receipts": {
                str(key): str(value)
                for key, value in (
                    capabilities.get("implementation_receipts") or {}
                ).items()
            },
            "component_configuration_receipts": {
                str(key): str(value)
                for key, value in (
                    capabilities.get("component_configuration_receipts") or {}
                ).items()
            },
            "semantic_profile": capabilities.get("semantic_profile"),
        }
    )


def _migration_declarations(contract: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    declarations = contract.get("migration_adapters")
    if not isinstance(declarations, Sequence) or isinstance(declarations, (str, bytes)):
        raise ValueError("harness contract requires a migration_adapters array")
    normalized: dict[str, Mapping[str, Any]] = {}
    for declaration in declarations:
        if not isinstance(declaration, Mapping):
            raise ValueError("migration adapter declaration must be an object")
        adapter_id = str(declaration.get("adapter_id") or "")
        if not adapter_id or adapter_id in normalized:
            raise ValueError("migration adapter IDs must be unique and non-empty")
        required = {
            "adapter_id",
            "adapter_version",
            "from_observation_schema_version",
            "to_observation_schema_version",
            "implementation_receipt_id",
            "test_artifact_role",
            "eligible_change_classes",
            "lossless",
            "raw_observation_preserved",
        }
        if set(declaration) != required:
            raise ValueError(f"migration adapter declaration fields are not exact: {adapter_id}")
        if declaration.get("lossless") is not True or declaration.get(
            "raw_observation_preserved"
        ) is not True:
            raise ValueError(f"migration adapter must be lossless and raw-preserving: {adapter_id}")
        change_classes = declaration.get("eligible_change_classes")
        if change_classes != ["observation_schema"]:
            raise ValueError(f"unsupported migration change classes: {adapter_id}")
        normalized[adapter_id] = declaration
    return normalized


def _migration_adapter_catalog(
    *,
    contract: Mapping[str, Any],
    implementation_receipts: Mapping[str, str],
    artifacts: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for adapter_id, declaration in _migration_declarations(contract).items():
        implementation_receipt_id = str(declaration["implementation_receipt_id"])
        test_artifact_role = str(declaration["test_artifact_role"])
        catalog[adapter_id] = {
            "adapter_version": str(declaration["adapter_version"]),
            "from_observation_schema_version": str(
                declaration["from_observation_schema_version"]
            ),
            "to_observation_schema_version": str(
                declaration["to_observation_schema_version"]
            ),
            "adapter_declaration_sha256": stable_sha256(declaration),
            "adapter_sha256": implementation_receipts.get(
                implementation_receipt_id, ""
            ),
            "test_artifact_sha256": artifacts.get(test_artifact_role, ""),
            "implementation_receipt_id": implementation_receipt_id,
            "test_artifact_role": test_artifact_role,
            "lossless": True,
            "raw_observation_preserved": True,
        }
    return catalog


def _validated_negotiation_migration_receipt(
    *,
    contract: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    artifacts: Mapping[str, str],
    implementation_receipts: Mapping[str, str],
) -> dict[str, Any] | None:
    receipt = capabilities.get("migration_adapter_receipt")
    if not isinstance(receipt, Mapping) or set(receipt) != _MIGRATION_RECEIPT_FIELDS:
        return None
    declarations = _migration_declarations(contract)
    declaration = declarations.get(str(receipt.get("adapter_id") or ""))
    if declaration is None:
        return None
    implementation_receipt_id = str(declaration["implementation_receipt_id"])
    test_artifact_role = str(declaration["test_artifact_role"])
    expected = {
        "adapter_version": declaration["adapter_version"],
        "from_observation_schema_version": capabilities.get(
            "observation_schema_version"
        ),
        "to_observation_schema_version": contract.get(
            "observation_schema_version"
        ),
        "adapter_declaration_sha256": stable_sha256(declaration),
        "adapter_sha256": implementation_receipts.get(implementation_receipt_id),
        "test_artifact_sha256": artifacts.get(test_artifact_role),
        "lossless": True,
        "raw_observation_preserved": True,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        return None
    if receipt.get("from_observation_schema_version") != declaration.get(
        "from_observation_schema_version"
    ) or receipt.get("to_observation_schema_version") != declaration.get(
        "to_observation_schema_version"
    ):
        return None
    if not all(
        _is_sha256(receipt.get(key))
        for key in (
            "adapter_sha256",
            "adapter_declaration_sha256",
            "test_artifact_sha256",
            "raw_observation_sha256",
            "migrated_observation_sha256",
        )
    ):
        return None
    return {str(key): value for key, value in receipt.items()}


def validate_harness_contract(
    contract: Mapping[str, Any],
    *,
    interface_components: Sequence[str],
) -> dict[str, Any]:
    if contract.get("schema_version") != HARNESS_CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported benchmark harness contract schema")
    if contract.get("claim_eligible") is not False:
        raise ValueError("benchmark harness contract must remain claim_eligible=false")
    component_contracts = contract.get("component_contracts")
    feature_contracts = contract.get("feature_contracts")
    if not isinstance(component_contracts, Mapping) or not isinstance(
        feature_contracts,
        Mapping,
    ):
        raise ValueError("harness contract requires component and feature contracts")
    expected_components = tuple(str(value) for value in interface_components)
    if set(component_contracts) != set(expected_components):
        raise ValueError("harness component contracts must exactly match interface components")
    stages = tuple(str(value) for value in contract.get("stage_topology") or ())
    if stages != ("draft", "post_verification", "final"):
        raise ValueError("benchmark stage topology must preserve draft, post_verification, final")
    declared_features: set[str] = set()
    for component in expected_components:
        declaration = component_contracts[component]
        if not isinstance(declaration, Mapping):
            raise ValueError(f"component contract is not an object: {component}")
        for field in (
            "component_id",
            "contract_version",
            "applicability",
            "allowed_observed_statuses",
            "features",
        ):
            if not declaration.get(field):
                raise ValueError(f"component contract {component} is missing {field}")
        declared_features.update(str(value) for value in declaration["features"])
    if declared_features != set(str(value) for value in feature_contracts):
        raise ValueError("component feature inventory does not match feature_contracts")
    for feature_id, declaration in feature_contracts.items():
        if not isinstance(declaration, Mapping):
            raise ValueError(f"feature contract is not an object: {feature_id}")
        component = str(declaration.get("component") or "")
        if component not in component_contracts:
            raise ValueError(f"feature {feature_id} references unknown component {component}")
        if declaration.get("effect_class") not in {"answer_affecting", "trace_only"}:
            raise ValueError(f"feature {feature_id} has unknown effect_class")
    required_receipts = tuple(
        str(value) for value in contract.get("required_implementation_receipts") or ()
    )
    if not required_receipts or len(required_receipts) != len(set(required_receipts)):
        raise ValueError("required implementation receipt IDs must be unique and non-empty")
    migrations = _migration_declarations(contract)
    semantic_profile = _validate_construct_semantic_profile(
        contract.get("semantic_profile")
    )
    for adapter_id, declaration in migrations.items():
        if declaration.get("to_observation_schema_version") != contract.get(
            "observation_schema_version"
        ) or declaration.get("from_observation_schema_version") == declaration.get(
            "to_observation_schema_version"
        ):
            raise ValueError(
                f"migration adapter must target the frozen observation schema: {adapter_id}"
            )
        if str(declaration["implementation_receipt_id"]) not in required_receipts:
            raise ValueError(
                f"migration adapter implementation receipt is not required: {adapter_id}"
            )
        if str(declaration["test_artifact_role"]) not in REQUIRED_ARTIFACT_RECEIPTS:
            raise ValueError(
                f"migration adapter test artifact is not cohort-bound: {adapter_id}"
            )
    return {
        "components": expected_components,
        "stages": stages,
        "features": tuple(sorted(str(value) for value in feature_contracts)),
        "required_implementation_receipts": required_receipts,
        "migration_adapters": tuple(sorted(migrations)),
        "semantic_profile": semantic_profile,
        "contract_sha256": stable_sha256(contract),
    }


def validate_artifact_receipts(receipts: Mapping[str, Any]) -> dict[str, str]:
    if set(receipts) != set(REQUIRED_ARTIFACT_RECEIPTS):
        missing = sorted(set(REQUIRED_ARTIFACT_RECEIPTS) - set(receipts))
        extra = sorted(set(receipts) - set(REQUIRED_ARTIFACT_RECEIPTS))
        raise ValueError(
            f"benchmark artifact receipts must be exact: missing={missing}, extra={extra}"
        )
    normalized = {str(key): str(value) for key, value in receipts.items()}
    malformed = sorted(key for key, value in normalized.items() if not _is_sha256(value))
    if malformed:
        raise ValueError(f"benchmark artifact receipts are not SHA-256 values: {malformed}")
    return normalized


def negotiate_harness(
    *,
    contract: Mapping[str, Any],
    interface_components: Sequence[str],
    capabilities: Mapping[str, Any],
    artifact_receipts: Mapping[str, Any],
) -> dict[str, Any]:
    """Negotiate before execution; non-comparable executors are not run."""

    validated = validate_harness_contract(
        contract,
        interface_components=interface_components,
    )
    artifacts = validate_artifact_receipts(artifact_receipts)
    reasons: list[str] = []
    normalized_executor_identity = {
        "executor_id": str(capabilities.get("executor_id") or ""),
        "executor_version": str(capabilities.get("executor_version") or ""),
        "result_class": str(capabilities.get("result_class") or ""),
    }
    if not all(normalized_executor_identity.values()):
        reasons.append("executor_identity_missing")
    if capabilities.get("schema_version") != EXECUTOR_CAPABILITIES_SCHEMA_VERSION:
        reasons.append("executor_capabilities_schema_mismatch")
    if str(capabilities.get("benchmark_id") or "") != str(
        contract.get("benchmark_id") or ""
    ):
        reasons.append("benchmark_id_mismatch")
    if str(capabilities.get("observation_schema_version") or "") != str(
        contract.get("observation_schema_version") or ""
    ):
        reasons.append("observation_schema_mismatch")
    if str(capabilities.get("metric_schema_version") or "") != str(
        contract.get("metric_schema_version") or ""
    ):
        reasons.append("metric_schema_mismatch")
    observed_stages = tuple(str(value) for value in capabilities.get("stage_topology") or ())
    if observed_stages != validated["stages"]:
        reasons.append("active_stage_topology_changed")

    expected_component_versions = {
        component: str(declaration["contract_version"])
        for component, declaration in contract["component_contracts"].items()
    }
    observed_component_versions = {
        str(key): str(value)
        for key, value in (capabilities.get("component_contract_versions") or {}).items()
    }
    if observed_component_versions != expected_component_versions:
        reasons.append("component_contract_versions_changed")

    expected_feature_versions = {
        feature_id: str(declaration["contract_version"])
        for feature_id, declaration in contract["feature_contracts"].items()
    }
    observed_feature_versions = {
        str(key): str(value)
        for key, value in (capabilities.get("feature_contract_versions") or {}).items()
    }
    missing_features = sorted(set(expected_feature_versions) - set(observed_feature_versions))
    unknown_features = sorted(set(observed_feature_versions) - set(expected_feature_versions))
    changed_features = sorted(
        feature_id
        for feature_id in set(expected_feature_versions) & set(observed_feature_versions)
        if expected_feature_versions[feature_id] != observed_feature_versions[feature_id]
    )
    if missing_features:
        reasons.append("required_features_missing:" + ",".join(missing_features))
    if unknown_features:
        reasons.append("unknown_active_features:" + ",".join(unknown_features))
    if changed_features:
        reasons.append("feature_contract_versions_changed:" + ",".join(changed_features))

    semantic_profile, semantic_reasons = _validate_executor_semantic_profile(
        capabilities=capabilities,
        construct_profile=validated["semantic_profile"],
    )
    reasons.extend(semantic_reasons)

    expected_receipt_ids = set(validated["required_implementation_receipts"])
    implementation_receipts = {
        str(key): str(value)
        for key, value in (capabilities.get("implementation_receipts") or {}).items()
    }
    if set(implementation_receipts) != expected_receipt_ids:
        reasons.append("implementation_receipt_inventory_mismatch")
    elif any(not _is_sha256(value) for value in implementation_receipts.values()):
        reasons.append("malformed_implementation_receipt")

    component_configuration_receipts = {
        str(key): str(value)
        for key, value in (
            capabilities.get("component_configuration_receipts") or {}
        ).items()
    }
    if set(component_configuration_receipts) != set(validated["components"]):
        reasons.append("component_configuration_receipt_inventory_mismatch")
    elif any(
        not _is_sha256(value)
        for value in component_configuration_receipts.values()
    ):
        reasons.append("malformed_component_configuration_receipt")

    system_identity = capabilities.get("system_identity")
    if not isinstance(system_identity, Mapping):
        reasons.append("system_identity_missing")
        normalized_system_identity: dict[str, str] = {}
    else:
        normalized_system_identity = {
            "system_id": str(system_identity.get("system_id") or ""),
            "system_revision": str(system_identity.get("system_revision") or ""),
            "system_configuration_sha256": str(
                system_identity.get("system_configuration_sha256") or ""
            ),
        }
        if (
            not normalized_system_identity["system_id"]
            or not normalized_system_identity["system_revision"]
            or not _is_sha256(
                normalized_system_identity["system_configuration_sha256"]
            )
        ):
            reasons.append("system_identity_malformed")
        elif normalized_system_identity[
            "system_configuration_sha256"
        ] != derive_system_configuration_sha256(capabilities):
            reasons.append("system_configuration_hash_mismatch")

    observation_schema_mismatch = "observation_schema_mismatch" in reasons
    migration_receipt: dict[str, Any] | None = None
    if observation_schema_mismatch:
        migration_receipt = _validated_negotiation_migration_receipt(
            contract=contract,
            capabilities=capabilities,
            artifacts=artifacts,
            implementation_receipts=implementation_receipts,
        )
        if migration_receipt is None:
            reasons.append("migration_adapter_receipt_missing_or_invalid")
    elif capabilities.get("migration_adapter_receipt") is not None:
        reasons.append("unexpected_migration_adapter_receipt")

    construct_payload = {
        "benchmark_id": contract.get("benchmark_id"),
        "artifact_receipts": {
            key: artifacts[key] for key in CONSTRUCT_ARTIFACT_RECEIPTS
        },
        "component_contracts": contract.get("component_contracts"),
        "feature_contracts": contract.get("feature_contracts"),
        "semantic_profile": validated["semantic_profile"],
        "stage_topology": list(validated["stages"]),
    }
    construct_fingerprint = stable_sha256(construct_payload)
    cohort_payload = {
        "construct_fingerprint": construct_fingerprint,
        "artifact_receipts": {
            key: artifacts[key] for key in COHORT_ARTIFACT_RECEIPTS
        },
        "observation_schema_version": contract.get("observation_schema_version"),
        "metric_schema_version": contract.get("metric_schema_version"),
        "summary_schema_version": contract.get("summary_schema_version"),
    }
    cohort_fingerprint = stable_sha256(cohort_payload)
    executor_capabilities_sha256 = stable_sha256(capabilities)
    system_fingerprint = stable_sha256(
        {
            "system_identity": normalized_system_identity,
            "executor_identity": normalized_executor_identity,
            "implementation_receipts": implementation_receipts,
            "component_configuration_receipts": component_configuration_receipts,
            "semantic_profile": semantic_profile,
            "executor_capabilities_sha256": executor_capabilities_sha256,
        }
    )
    migration_adapter_catalog = _migration_adapter_catalog(
        contract=contract,
        implementation_receipts=implementation_receipts,
        artifacts=artifacts,
    )
    migration_eligible = bool(
        migration_receipt is not None
        and set(reasons) == {"observation_schema_mismatch"}
    )
    if not reasons:
        status = "comparable"
    elif migration_eligible:
        status = "migration_required"
    else:
        status = "new_benchmark_required"
    return {
        "schema_version": NEGOTIATION_SCHEMA_VERSION,
        "status": status,
        "run_permitted": status == "comparable",
        "reason_codes": reasons or ["exact_harness_contract_match"],
        "contract_id": contract.get("contract_id"),
        "contract_sha256": validated["contract_sha256"],
        "construct_fingerprint": construct_fingerprint,
        "cohort_fingerprint": cohort_fingerprint,
        "system_fingerprint": system_fingerprint,
        "system_identity": normalized_system_identity,
        "executor_identity": normalized_executor_identity,
        "implementation_receipts": implementation_receipts,
        "component_configuration_receipts": component_configuration_receipts,
        "component_contract_versions": observed_component_versions,
        "feature_contract_versions": observed_feature_versions,
        "semantic_profile": semantic_profile,
        "migration_adapter_receipt": migration_receipt,
        "migration_adapter_catalog": migration_adapter_catalog,
        "executor_capabilities_sha256": executor_capabilities_sha256,
        "artifact_receipts": artifacts,
        "interpretation": (
            "Comparable means the frozen construct and harness semantics match. "
            "System implementation identity remains separate and is never pooled."
        ),
    }


def _valid_negotiation_migration_receipt(receipt: Mapping[str, Any]) -> bool:
    migration_receipt = receipt.get("migration_adapter_receipt")
    catalog = receipt.get("migration_adapter_catalog")
    if (
        not isinstance(migration_receipt, Mapping)
        or set(migration_receipt) != _MIGRATION_RECEIPT_FIELDS
        or not isinstance(catalog, Mapping)
    ):
        return False
    adapter_id = str(migration_receipt.get("adapter_id") or "")
    catalog_entry = catalog.get(adapter_id)
    if not isinstance(catalog_entry, Mapping) or set(
        catalog_entry
    ) != _MIGRATION_CATALOG_ENTRY_FIELDS:
        return False
    if migration_receipt.get("lossless") is not True or migration_receipt.get(
        "raw_observation_preserved"
    ) is not True:
        return False
    for field in (
        "adapter_version",
        "from_observation_schema_version",
        "to_observation_schema_version",
        "adapter_declaration_sha256",
        "adapter_sha256",
        "test_artifact_sha256",
        "lossless",
        "raw_observation_preserved",
    ):
        if migration_receipt.get(field) != catalog_entry.get(field):
            return False
    implementation_receipts = receipt.get("implementation_receipts")
    artifacts = receipt.get("artifact_receipts")
    if not isinstance(implementation_receipts, Mapping) or not isinstance(
        artifacts, Mapping
    ):
        return False
    if migration_receipt.get("adapter_sha256") != implementation_receipts.get(
        catalog_entry.get("implementation_receipt_id")
    ) or migration_receipt.get("test_artifact_sha256") != artifacts.get(
        catalog_entry.get("test_artifact_role")
    ):
        return False
    if not all(
        isinstance(migration_receipt.get(field), str)
        and migration_receipt.get(field)
        for field in (
            "adapter_id",
            "adapter_version",
            "from_observation_schema_version",
            "to_observation_schema_version",
        )
    ):
        return False
    return all(
        _is_sha256(migration_receipt.get(field))
        for field in (
            "adapter_sha256",
            "adapter_declaration_sha256",
            "test_artifact_sha256",
            "raw_observation_sha256",
            "migrated_observation_sha256",
        )
    )


def _valid_negotiation_comparison_identity(receipt: Any) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    status = receipt.get("status")
    if (
        receipt.get("schema_version") != NEGOTIATION_SCHEMA_VERSION
        or status not in COMPATIBILITY_STATES
        or receipt.get("run_permitted") is not (status == "comparable")
    ):
        return False
    if not all(
        _is_sha256(receipt.get(field))
        for field in (
            "contract_sha256",
            "construct_fingerprint",
            "cohort_fingerprint",
            "system_fingerprint",
            "executor_capabilities_sha256",
        )
    ):
        return False
    system = receipt.get("system_identity")
    executor = receipt.get("executor_identity")
    if (
        not isinstance(system, Mapping)
        or set(system)
        != {"system_id", "system_revision", "system_configuration_sha256"}
        or not isinstance(executor, Mapping)
        or set(executor) != {"executor_id", "executor_version", "result_class"}
        or not all(
            isinstance(system.get(field), str) and system.get(field)
            for field in ("system_id", "system_revision")
        )
        or not _is_sha256(system.get("system_configuration_sha256"))
        or not all(
            isinstance(executor.get(field), str) and executor.get(field)
            for field in ("executor_id", "executor_version", "result_class")
        )
    ):
        return False
    artifacts = receipt.get("artifact_receipts")
    if (
        not isinstance(artifacts, Mapping)
        or set(artifacts) != set(REQUIRED_ARTIFACT_RECEIPTS)
        or any(not _is_sha256(value) for value in artifacts.values())
    ):
        return False
    if not isinstance(receipt.get("migration_adapter_catalog"), Mapping):
        return False
    if status == "migration_required":
        return _valid_negotiation_migration_receipt(receipt)
    return receipt.get("migration_adapter_receipt") is None


def compare_benchmark_receipts(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify whether two run receipts may share an analysis cohort."""

    valid_left = _valid_negotiation_comparison_identity(left)
    valid_right = _valid_negotiation_comparison_identity(right)
    left_construct = str(left.get("construct_fingerprint") or "")
    right_construct = str(right.get("construct_fingerprint") or "")
    left_cohort = str(left.get("cohort_fingerprint") or "")
    right_cohort = str(right.get("cohort_fingerprint") or "")
    if not valid_left or not valid_right:
        status = "new_benchmark_required"
        reasons = ["missing_or_malformed_negotiation_receipt"]
    elif left_construct != right_construct:
        status = "new_benchmark_required"
        reasons = ["benchmark_construct_changed"]
    elif left.get("contract_sha256") != right.get("contract_sha256"):
        status = "new_benchmark_required"
        reasons = ["benchmark_contract_changed"]
    elif "new_benchmark_required" in {left.get("status"), right.get("status")}:
        status = "new_benchmark_required"
        reasons = ["input_negotiation_requires_new_benchmark"]
    elif "migration_required" in {left.get("status"), right.get("status")}:
        catalogs_match = left.get("migration_adapter_catalog") == right.get(
            "migration_adapter_catalog"
        )
        if catalogs_match:
            status = "migration_required"
            reasons = ["declared_tested_lossless_representation_migration"]
        else:
            status = "new_benchmark_required"
            reasons = ["migration_adapter_catalog_mismatch"]
    elif left_cohort != right_cohort:
        status = "new_benchmark_required"
        reasons = ["benchmark_cohort_changed_without_valid_migration_receipt"]
    else:
        status = "comparable"
        reasons = ["exact_benchmark_cohort_match"]
    return {
        "schema_version": COMPATIBILITY_DECISION_SCHEMA_VERSION,
        "status": status,
        "reason_codes": reasons,
        # Negotiation receipts do not bind the evaluated model identity. Full
        # run/measurement receipts perform exact model+system pooling checks.
        "may_pool": False,
        "may_compare_as_distinct_systems": status == "comparable",
        "boundary": (
            "Negotiation receipts may authorize a distinct-system contrast but never "
            "pooling; pooling requires full model, run, system, and executor identity "
            "in measurement receipts. Migration never overwrites raw observations."
        ),
    }


__all__ = [
    "COMPATIBILITY_STATES",
    "EXECUTOR_CAPABILITIES_SCHEMA_VERSION",
    "HARNESS_CONTRACT_SCHEMA_VERSION",
    "REQUIRED_ARTIFACT_RECEIPTS",
    "compare_benchmark_receipts",
    "derive_system_configuration_sha256",
    "negotiate_harness",
    "stable_sha256",
    "validate_artifact_receipts",
    "validate_harness_contract",
]
