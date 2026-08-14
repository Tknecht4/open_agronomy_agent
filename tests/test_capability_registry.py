from __future__ import annotations

import json
from dataclasses import replace

import pytest

import agronomy_agent.capability_registry as registry_module
from agronomy_agent.agno_runtime.tool_adapters import load_agno_tool_adapters
from agronomy_agent.capability_registry import (
    CAPABILITY_REGISTRY_SCHEMA_VERSION,
    CapabilityRegistry,
    CapabilityRegistryError,
    CapabilitySchemaValidationError,
    DataSchema,
    NetworkPolicy,
    OfflinePolicy,
    ROUTE_REQUIRED_CAPABILITY_IDS,
    SchemaField,
    SurfaceBindings,
    ToolSpec,
    capability_registry,
    cli_capability_listing,
    execute_registered_capability,
    render_capability_markdown,
)
from agronomy_agent.server.services.tool_service import (
    PUBLIC_ADAPTER_SPECS,
    capability_registry_view,
    tool_name_alias,
)
from agronomy_agent.skill_registry import SKILL_CONTRACTS
from agronomy_agent.tool_cli import main as tool_cli_main
from agronomy_agent.tools.registry import (
    EXPLICIT_TOOL_FALLBACK_TEXT,
    registered_guard_ids,
    run_tools,
)


def _spec(
    capability_id: str,
    *,
    aliases: tuple[str, ...] = (),
    surfaces: SurfaceBindings = SurfaceBindings(),
    network: NetworkPolicy = NetworkPolicy(),
    offline: OfflinePolicy = OfflinePolicy(),
) -> ToolSpec:
    return ToolSpec(
        capability_id=capability_id,
        version=f"{capability_id}_v1",
        name=capability_id.replace("_", " ").title(),
        description="Test capability.",
        kind="decision_frame",
        input_schema=DataSchema(f"{capability_id}.input.v1"),
        output_schema=DataSchema(f"{capability_id}.output.v1"),
        executor_ref="agronomy_agent.local_tools:diagnostic_frame",
        risk_class="low",
        authority_role="test",
        boundary="Test-only boundary.",
        aliases=aliases,
        surfaces=surfaces,
        network=network,
        offline=offline,
        test_fixtures=("tests/test_capability_registry.py",),
    )


def test_default_registry_covers_current_surfaces_without_drift() -> None:
    registry = capability_registry()

    assert len(registry.specs) == 57
    assert set(ROUTE_REQUIRED_CAPABILITY_IDS) == set(registry.surface_names("router"))
    assert set(registry.surface_names("agno")) == set(load_agno_tool_adapters())
    assert set(registry.surface_names("readiness")) == {
        str(spec["id"]) for spec in PUBLIC_ADAPTER_SPECS
    }
    assert registry.audit(
        required_tools=ROUTE_REQUIRED_CAPABILITY_IDS,
        surface_registrations={
            "agno": load_agno_tool_adapters(),
            "readiness": [str(spec["id"]) for spec in PUBLIC_ADAPTER_SPECS],
        },
    ) == ()


def test_capability_claims_require_specific_execution_evidence() -> None:
    registry = capability_registry()
    natural_language_ids = {
        spec.capability_id
        for spec in registry.specs
        if spec.planner.natural_language_enabled
    }
    benchmark_ids = {
        spec.capability_id
        for spec in registry.specs
        if spec.benchmark_exercised
    }

    assert natural_language_ids == {
        *ROUTE_REQUIRED_CAPABILITY_IDS,
        "agronomic_calculator",
    }
    assert all(
        spec.planner.natural_language_test_evidence
        for spec in registry.specs
        if spec.planner.natural_language_enabled
    )
    assert benchmark_ids == set()


def test_registry_rejects_unreceipted_status_claims() -> None:
    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityRegistry(
            (
                replace(
                    _spec("inflated_claim"),
                    planner=registry_module.PlannerMetadata(
                        natural_language_enabled=True,
                    ),
                    benchmark_exercised=True,
                ),
            )
        )

    assert {issue.code for issue in exc_info.value.issues} == {
        "missing_natural_language_test_evidence",
        "missing_benchmark_evidence",
    }


def test_guard_capability_specs_derive_from_executable_inventory() -> None:
    guard_ids = registered_guard_ids()
    registry_guard_ids = {
        spec.capability_id
        for spec in capability_registry().specs
        if spec.surface_names("router")
    }

    assert ROUTE_REQUIRED_CAPABILITY_IDS == guard_ids
    assert registry_guard_ids == set(guard_ids)
    assert set(EXPLICIT_TOOL_FALLBACK_TEXT) == set(guard_ids)
    assert set(guard_ids).issubset(SKILL_CONTRACTS)


def test_run_tools_rejects_unknown_enabled_guard_fail_closed() -> None:
    with pytest.raises(
        ValueError,
        match=(
            r"unknown enabled guard\(s\): label_guard_typo; "
            r"registered guards: label_guard, fertility_guard"
        ),
    ):
        run_tools(
            "What should I verify before acting?",
            enabled_tools=("label_guard", "label_guard_typo"),
        )


def test_duplicate_aliases_fail_registry_construction() -> None:
    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityRegistry(
            (
                _spec("first_tool", aliases=("shared-name",)),
                _spec("second_tool", aliases=("shared_name",)),
            )
        )

    assert {issue.code for issue in exc_info.value.issues} == {"duplicate_alias"}


def test_audit_reports_unknown_route_tool_and_orphan_implementation() -> None:
    registry = CapabilityRegistry((_spec("known_tool", surfaces=SurfaceBindings(router=("known_tool",))),))

    issues = registry.audit(
        required_tools=("known_tool", "missing_guard"),
        implementation_ids=("known_tool", "orphan_executor"),
    )

    assert {issue.code for issue in issues} == {
        "unknown_route_required_tool",
        "orphan_implementation",
    }


def test_surface_parity_reports_missing_and_unexpected_names() -> None:
    registry = CapabilityRegistry((_spec("known_tool", surfaces=SurfaceBindings(http=("known-tool",))),))

    issues = registry.audit(surface_registrations={"http": ("different-tool",)})

    assert [issue.code for issue in issues] == [
        "missing_surface_registration",
        "unexpected_surface_registration",
    ]


def test_contradictory_network_and_offline_policy_fails_preflight() -> None:
    with pytest.raises(CapabilityRegistryError) as exc_info:
        CapabilityRegistry(
            (
                _spec(
                    "impossible_tool",
                    network=NetworkPolicy(mode="none"),
                    offline=OfflinePolicy(mode="blocked"),
                ),
            )
        )

    assert [issue.code for issue in exc_info.value.issues] == ["contradictory_availability"]


def test_registry_exposes_http_readiness_and_docs_views() -> None:
    view = capability_registry_view()
    http_view = capability_registry_view("http")
    markdown = render_capability_markdown()

    assert view["schema_version"] == CAPABILITY_REGISTRY_SCHEMA_VERSION
    assert view["preflight"] == {"status": "passed", "issues": []}
    assert http_view["capability_count"] == 47
    assert "`agronomic_calculator`" in markdown
    assert "docs/public/tools-and-adapters.md" == capability_registry().require(
        "agronomic_calculator"
    ).docs_path


def test_cli_list_is_generated_from_registry(capsys: pytest.CaptureFixture[str]) -> None:
    assert tool_cli_main(["list"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["tools"] == cli_capability_listing()
    assert {item["name"] for item in payload["tools"]} == {
        "route",
        "retrieve",
        "soil-context",
        "spray-window",
        "fertility-frame",
        "diagnostic-frame",
        "calculate",
        "weather-power",
        "daymet-single-pixel",
        "openet-point-timeseries",
        "nrcs-soil-survey",
        "nrcs-soil-survey-geometry",
        "cropland-data-layer",
        "cropland-data-layer-geometry",
        "nass-quickstats-crop-stats",
        "epa-ppls-product-search",
        "canada-source-lane",
    }


def test_cli_generic_run_uses_registered_http_dispatch(capsys: pytest.CaptureFixture[str]) -> None:
    assert tool_cli_main(
        [
            "run",
            "agronomic_calculator",
            "--payload-json",
            json.dumps(
                {
                    "operation": "field_product_total",
                    "inputs": {"area_ha": 42, "product_rate_kg_per_ha": 75},
                }
            ),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["value"] == 3150
    assert payload["unit"] == "kg"


def test_http_aliases_resolve_through_registry() -> None:
    assert tool_name_alias("nasa_power_daily") == "weather-power"
    assert tool_name_alias("agronomic_calculator") == "agronomic-calculator"
    assert tool_name_alias("source_availability_and_tool_choice") == (
        "source-availability-and-tool-choice"
    )


def _install_schema_test_executor(
    monkeypatch: pytest.MonkeyPatch,
    *,
    output: object,
) -> list[dict[str, object]]:
    spec = replace(
        _spec("schema_tool"),
        input_schema=DataSchema(
            "schema_tool.input.v1",
            (
                SchemaField("name", "string", True),
                SchemaField("amount", "number", True),
                SchemaField("metadata", "object", True),
                SchemaField("tags", "array[string]", True),
                SchemaField("effective_date", "date", True),
                SchemaField("geometry", "geojson", True),
            ),
        ),
        output_schema=DataSchema(
            "schema_tool.output.v1",
            (
                SchemaField("status", "string", True),
                SchemaField("values", "list[string]", True),
            ),
        ),
    )
    calls: list[dict[str, object]] = []

    def executor(**payload: object) -> object:
        calls.append(payload)
        return output

    monkeypatch.setattr(registry_module, "capability_registry", lambda: CapabilityRegistry((spec,)))
    monkeypatch.setattr(registry_module, "load_executor", lambda _: executor)
    return calls


def _valid_schema_input() -> dict[str, object]:
    return {
        "name": "nitrogen conversion",
        "amount": 46.0,
        "metadata": {"basis": "supplied input"},
        "tags": ["calculation", "benign"],
        "effective_date": "2026-08-13",
        "geometry": {"type": "Point", "coordinates": [-113.5, 53.5]},
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"amount": None}, "property amount must be number; got null"),
        ({"amount": True}, "property amount must be number; got boolean"),
        ({"metadata": []}, "property metadata must be object; got array"),
        ({"tags": ["valid", 7]}, "property tags must be array[string]"),
        ({"effective_date": 20260813}, "property effective_date must be date"),
        ({"geometry": "POINT (-113.5 53.5)"}, "property geometry must be geojson"),
    ],
)
def test_execute_registered_capability_rejects_wrong_input_types_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict[str, object],
    message: str,
) -> None:
    calls = _install_schema_test_executor(
        monkeypatch,
        output={"status": "ok", "values": []},
    )
    payload = _valid_schema_input()
    payload.update(mutation)

    with pytest.raises(CapabilitySchemaValidationError, match=message.replace("[", r"\[").replace("]", r"\]")):
        execute_registered_capability("schema_tool", payload)

    assert calls == []


def test_execute_registered_capability_rejects_missing_and_extra_input_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_schema_test_executor(
        monkeypatch,
        output={"status": "ok", "values": []},
    )
    payload = _valid_schema_input()
    del payload["name"]
    payload["undeclared"] = "must fail closed"

    with pytest.raises(CapabilitySchemaValidationError) as exc_info:
        execute_registered_capability("schema_tool", payload)

    assert exc_info.value.direction == "input"
    assert exc_info.value.problems == (
        "missing required properties: name",
        "unexpected properties: undeclared",
    )
    assert calls == []


@pytest.mark.parametrize(
    ("output", "expected_problem"),
    [
        ({"values": []}, "missing required properties: status"),
        ({"status": "ok", "values": "not-an-array"}, "property values must be list[string]"),
        (
            {"status": "ok", "values": [], "undeclared": "must fail closed"},
            "unexpected properties: undeclared",
        ),
    ],
)
def test_execute_registered_capability_rejects_malformed_executor_output(
    monkeypatch: pytest.MonkeyPatch,
    output: dict[str, object],
    expected_problem: str,
) -> None:
    calls = _install_schema_test_executor(monkeypatch, output=output)

    with pytest.raises(CapabilitySchemaValidationError) as exc_info:
        execute_registered_capability("schema_tool", _valid_schema_input())

    assert exc_info.value.direction == "output"
    assert any(expected_problem in problem for problem in exc_info.value.problems)
    assert calls == [_valid_schema_input()]


def test_execute_registered_capability_preserves_valid_executor_payload_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {"status": "ok", "values": ["validated"]}
    calls = _install_schema_test_executor(monkeypatch, output=expected)

    result = execute_registered_capability("schema_tool", _valid_schema_input())

    assert calls == [_valid_schema_input()]
    assert result == expected


def test_existing_calculator_executor_passes_its_declared_contract() -> None:
    result = execute_registered_capability(
        "agronomic_calculator",
        {
            "operation": "field_product_total",
            "inputs": {"area_ha": 42, "product_rate_kg_per_ha": 75},
        },
    )

    assert result["value"] == 3150
    assert result["unit"] == "kg"
