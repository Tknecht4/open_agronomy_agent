from __future__ import annotations

import importlib
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache, partial
from typing import Any, Callable, Iterable, Literal, Mapping, Protocol, Sequence, runtime_checkable


CapabilityKind = Literal[
    "guard",
    "router",
    "retrieval",
    "calculator",
    "decision_frame",
    "public_adapter",
    "source_card",
]
CapabilitySurface = Literal["router", "cli", "http", "agno", "readiness", "docs"]
NetworkMode = Literal["none", "optional", "required"]
OfflineMode = Literal["native", "cached", "snapshot", "blocked"]

CAPABILITY_REGISTRY_SCHEMA_VERSION = "open_agronomy_agent.capability_registry.v1"
GRAPH_REGISTRY_SCHEMA_VERSION = "open_agronomy_agent.graph_registry.v1"

_SUPPORTED_SCHEMA_TYPES = frozenset(
    {
        "array[string]",
        "boolean",
        "date",
        "geojson",
        "integer",
        "list[string]",
        "number",
        "object",
        "string",
    }
)


@dataclass(frozen=True)
class SchemaField:
    name: str
    value_type: str
    required: bool = False
    description: str = ""

    def as_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.value_type,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True)
class DataSchema:
    schema_id: str
    fields: tuple[SchemaField, ...] = ()
    additional_properties: bool = False

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "type": "object",
            "fields": [item.as_record() for item in self.fields],
            "required": [item.name for item in self.fields if item.required],
            "additional_properties": self.additional_properties,
        }


@dataclass(frozen=True)
class NetworkPolicy:
    mode: NetworkMode = "none"
    credential_env_vars: tuple[str, ...] = ()
    allowed_in_chat: bool = False

    def as_record(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "credential_env_vars": list(self.credential_env_vars),
            "allowed_in_chat": self.allowed_in_chat,
        }


@dataclass(frozen=True)
class OfflinePolicy:
    mode: OfflineMode = "native"
    cache_path: str | None = None
    snapshot_path: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "cache_path": self.cache_path,
            "snapshot_path": self.snapshot_path,
        }


@dataclass(frozen=True)
class FreshnessPolicy:
    basis: str = "not_applicable"
    max_age_hours: int | None = None

    def as_record(self) -> dict[str, Any]:
        return {"basis": self.basis, "max_age_hours": self.max_age_hours}


@dataclass(frozen=True)
class PlannerMetadata:
    triggers: tuple[str, ...] = ()
    required_context: tuple[str, ...] = ()
    natural_language_enabled: bool = False
    natural_language_test_evidence: tuple[str, ...] = ()

    def as_record(self) -> dict[str, Any]:
        return {
            "triggers": list(self.triggers),
            "required_context": list(self.required_context),
            "natural_language_enabled": self.natural_language_enabled,
            "natural_language_test_evidence": list(self.natural_language_test_evidence),
        }


@dataclass(frozen=True)
class SurfaceBindings:
    router: tuple[str, ...] = ()
    cli: tuple[str, ...] = ()
    http: tuple[str, ...] = ()
    agno: tuple[str, ...] = ()
    readiness: tuple[str, ...] = ()

    def names(self, surface: CapabilitySurface) -> tuple[str, ...]:
        if surface == "docs":
            return ()
        return tuple(getattr(self, surface))

    def as_record(self) -> dict[str, list[str]]:
        return {
            surface: list(self.names(surface))
            for surface in ("router", "cli", "http", "agno", "readiness")
        }


@dataclass(frozen=True)
class ToolSpec:
    capability_id: str
    version: str
    name: str
    description: str
    kind: CapabilityKind
    input_schema: DataSchema
    output_schema: DataSchema
    executor_ref: str
    risk_class: str
    authority_role: str
    boundary: str
    network: NetworkPolicy = NetworkPolicy()
    offline: OfflinePolicy = OfflinePolicy()
    freshness: FreshnessPolicy = FreshnessPolicy()
    planner: PlannerMetadata = PlannerMetadata()
    surfaces: SurfaceBindings = SurfaceBindings()
    aliases: tuple[str, ...] = ()
    executor_args: tuple[Any, ...] = ()
    renderer: str = "default_json"
    verifier_adapter: str = "typed_tool_evidence"
    trace_fields: tuple[str, ...] = ("capability_id", "version", "status", "payload_hash")
    test_fixtures: tuple[str, ...] = ()
    implemented: bool = False
    tested: bool = False
    benchmark_exercised: bool = False
    benchmark_evidence: tuple[str, ...] = ()
    docs_path: str | None = None

    def surface_names(self, surface: CapabilitySurface) -> tuple[str, ...]:
        if surface == "docs":
            return (self.capability_id,)
        return self.surfaces.names(surface)

    def as_record(self, *, surface: CapabilitySurface | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {
            "capability_id": self.capability_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "input_schema": self.input_schema.as_record(),
            "output_schema": self.output_schema.as_record(),
            "executor_ref": self.executor_ref,
            "risk_class": self.risk_class,
            "authority_role": self.authority_role,
            "boundary": self.boundary,
            "network": self.network.as_record(),
            "offline": self.offline.as_record(),
            "freshness": self.freshness.as_record(),
            "planner": self.planner.as_record(),
            "surfaces": self.surfaces.as_record(),
            "aliases": list(self.aliases),
            "renderer": self.renderer,
            "verifier_adapter": self.verifier_adapter,
            "trace_fields": list(self.trace_fields),
            "test_fixtures": list(self.test_fixtures),
            "status": {
                "implemented": self.implemented,
                "tested": self.tested,
                "natural_language_enabled": self.planner.natural_language_enabled,
                "benchmark_exercised": self.benchmark_exercised,
                "benchmark_evidence": list(self.benchmark_evidence),
            },
            "docs_path": self.docs_path,
        }
        if surface is not None:
            record["surface"] = surface
            record["surface_names"] = list(self.surface_names(surface))
        return record


@dataclass(frozen=True)
class GraphSpec:
    """Canonical catalog contract for a configured graph provider.

    Runtime loaders may need richer filesystem and manifest state while they
    validate and compose artifacts. They adapt that state into this stable
    registry record instead of defining a second, incompatible ``GraphSpec``.
    """

    graph_id: str
    version: str
    provider_ref: str
    paths: tuple[str, ...]
    namespaces: tuple[str, ...]
    schema_id: str
    source: str
    license: str
    checksum: str
    authority_role: str
    merge_priority: int = 0
    collision_policy: str = "error"
    relation_vocabulary: tuple[str, ...] = ()
    manifest_declared: bool = False

    def as_record(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "version": self.version,
            "provider_ref": self.provider_ref,
            "paths": list(self.paths),
            "namespaces": list(self.namespaces),
            "schema_id": self.schema_id,
            "source": self.source,
            "license": self.license,
            "checksum": self.checksum,
            "authority_role": self.authority_role,
            "merge_priority": self.merge_priority,
            "collision_policy": self.collision_policy,
            "relation_vocabulary": list(self.relation_vocabulary),
            "manifest_declared": self.manifest_declared,
        }


class GraphRegistry:
    """Deterministic registry view of the graphs loaded by one runtime."""

    def __init__(self, specs: Iterable[GraphSpec]):
        ordered = tuple(
            sorted(
                specs,
                key=lambda item: (-item.merge_priority, item.graph_id, item.version),
            )
        )
        graph_ids: set[str] = set()
        for spec in ordered:
            if spec.graph_id in graph_ids:
                raise ValueError(f"duplicate graph registry ID: {spec.graph_id}")
            graph_ids.add(spec.graph_id)
        self._specs = ordered

    @property
    def specs(self) -> tuple[GraphSpec, ...]:
        return self._specs

    def catalog(self) -> dict[str, Any]:
        return {
            "schema_version": GRAPH_REGISTRY_SCHEMA_VERSION,
            "graph_count": len(self._specs),
            "graphs": [spec.as_record() for spec in self._specs],
        }


@runtime_checkable
class ToolExecutor(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]: ...


@runtime_checkable
class GraphProvider(Protocol):
    def load(self, spec: GraphSpec) -> Any: ...


@runtime_checkable
class RetrieverBackend(Protocol):
    def retrieve(self, query: str, *, top_k: int) -> Sequence[Any]: ...


@runtime_checkable
class RouterRule(Protocol):
    def apply(self, question: str, state: Any) -> Any: ...


@runtime_checkable
class EvidenceContributor(Protocol):
    def contribute(self, context: Any) -> Sequence[Any]: ...


@runtime_checkable
class AnswerValidator(Protocol):
    def validate(self, answer: str, evidence: Sequence[Any]) -> Any: ...


@dataclass(frozen=True)
class RegistryIssue:
    code: str
    message: str
    capability_ids: tuple[str, ...] = ()
    surface: str | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "capability_ids": list(self.capability_ids),
            "surface": self.surface,
        }


class CapabilityRegistryError(ValueError):
    def __init__(self, issues: Iterable[RegistryIssue]):
        self.issues = tuple(issues)
        message = "; ".join(f"{item.code}: {item.message}" for item in self.issues)
        super().__init__(message or "capability registry validation failed")


class CapabilitySchemaValidationError(ValueError):
    """Raised when an executor input or output violates its declared schema."""

    def __init__(
        self,
        *,
        capability_id: str,
        direction: Literal["input", "output"],
        schema_id: str,
        problems: Iterable[str],
    ) -> None:
        self.capability_id = capability_id
        self.direction = direction
        self.schema_id = schema_id
        self.problems = tuple(problems)
        detail = "; ".join(self.problems) or "unknown schema violation"
        super().__init__(
            f"{capability_id} {direction} violates schema {schema_id}: {detail}"
        )


class CapabilityRegistry:
    def __init__(self, specs: Iterable[ToolSpec]):
        ordered = tuple(sorted(specs, key=lambda item: item.capability_id))
        issues: list[RegistryIssue] = []
        by_id: dict[str, ToolSpec] = {}
        aliases: dict[str, ToolSpec] = {}
        for spec in ordered:
            canonical = normalize_capability_name(spec.capability_id)
            if canonical != spec.capability_id:
                issues.append(
                    RegistryIssue(
                        "invalid_capability_id",
                        f"capability ID must be canonical snake_case: {spec.capability_id}",
                        (spec.capability_id,),
                    )
                )
            if canonical in by_id:
                issues.append(
                    RegistryIssue("duplicate_capability_id", f"duplicate capability ID: {canonical}", (canonical,))
                )
            by_id[canonical] = spec
            for raw_alias in (spec.capability_id, *spec.aliases):
                alias = normalize_capability_name(raw_alias)
                owner = aliases.get(alias)
                if owner is not None and owner.capability_id != spec.capability_id:
                    issues.append(
                        RegistryIssue(
                            "duplicate_alias",
                            f"alias {raw_alias!r} is owned by both {owner.capability_id} and {spec.capability_id}",
                            (owner.capability_id, spec.capability_id),
                        )
                    )
                aliases[alias] = spec
        issues.extend(_static_spec_issues(ordered))
        issues.extend(_surface_collision_issues(ordered))
        if issues:
            raise CapabilityRegistryError(issues)
        self._specs = ordered
        self._by_id = by_id
        self._aliases = aliases

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return self._specs

    def get(self, name: str) -> ToolSpec | None:
        return self._aliases.get(normalize_capability_name(name))

    def require(self, name: str) -> ToolSpec:
        spec = self.get(name)
        if spec is None:
            raise KeyError(f"unknown capability: {name}")
        return spec

    def for_surface(self, surface: CapabilitySurface) -> tuple[ToolSpec, ...]:
        if surface == "docs":
            return self._specs
        return tuple(spec for spec in self._specs if spec.surface_names(surface))

    def surface_names(self, surface: CapabilitySurface) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    name
                    for spec in self.for_surface(surface)
                    for name in spec.surface_names(surface)
                }
            )
        )

    def resolve_surface(self, surface: CapabilitySurface, name: str) -> ToolSpec:
        capability_match = self.get(name)
        if capability_match is not None and capability_match.surface_names(surface):
            return capability_match
        normalized = normalize_surface_name(name)
        matches = [
            spec
            for spec in self.for_surface(surface)
            if normalized in {normalize_surface_name(item) for item in spec.surface_names(surface)}
        ]
        if not matches:
            raise KeyError(f"unknown {surface} capability: {name}")
        if len(matches) > 1:
            raise KeyError(f"ambiguous {surface} capability: {name}")
        return matches[0]

    def catalog(self, surface: CapabilitySurface | None = None) -> dict[str, Any]:
        specs = self._specs if surface is None else self.for_surface(surface)
        return {
            "schema_version": CAPABILITY_REGISTRY_SCHEMA_VERSION,
            "surface": surface or "all",
            "capability_count": len(specs),
            "capabilities": [spec.as_record(surface=surface) for spec in specs],
        }

    def audit(
        self,
        *,
        required_tools: Iterable[str] = (),
        implementation_ids: Iterable[str] = (),
        surface_registrations: Mapping[str, Iterable[str]] | None = None,
    ) -> tuple[RegistryIssue, ...]:
        issues: list[RegistryIssue] = []
        for name in sorted(set(str(item) for item in required_tools)):
            spec = self.get(name)
            if spec is None or not spec.surface_names("router"):
                issues.append(
                    RegistryIssue(
                        "unknown_route_required_tool",
                        f"route requires unregistered capability: {name}",
                        (normalize_capability_name(name),),
                        "router",
                    )
                )
        for name in sorted(set(str(item) for item in implementation_ids)):
            if self.get(name) is None:
                issues.append(
                    RegistryIssue(
                        "orphan_implementation",
                        f"implementation is not represented by a capability spec: {name}",
                        (normalize_capability_name(name),),
                    )
                )
        if surface_registrations:
            for surface, actual_names in sorted(surface_registrations.items()):
                if surface not in {"router", "cli", "http", "agno", "readiness"}:
                    issues.append(RegistryIssue("unknown_surface", f"unknown capability surface: {surface}"))
                    continue
                expected = {
                    normalize_surface_name(item)
                    for item in self.surface_names(surface)  # type: ignore[arg-type]
                }
                actual = {normalize_surface_name(str(item)) for item in actual_names}
                for missing in sorted(expected - actual):
                    issues.append(
                        RegistryIssue(
                            "missing_surface_registration",
                            f"{surface} is missing registered name: {missing}",
                            surface=surface,
                        )
                    )
                for unexpected in sorted(actual - expected):
                    issues.append(
                        RegistryIssue(
                            "unexpected_surface_registration",
                            f"{surface} exposes a name absent from the registry: {unexpected}",
                            surface=surface,
                        )
                    )
        return tuple(issues)

    def assert_ready(self, **audit_kwargs: Any) -> None:
        issues = self.audit(**audit_kwargs)
        if issues:
            raise CapabilityRegistryError(issues)


def normalize_capability_name(name: str) -> str:
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


def normalize_surface_name(name: str) -> str:
    return str(name).strip().lower().replace("_", "-")


def load_executor(spec: ToolSpec) -> Callable[..., Any]:
    module_name, separator, attribute_name = spec.executor_ref.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError(f"invalid executor reference for {spec.capability_id}: {spec.executor_ref}")
    module = importlib.import_module(module_name)
    executor = getattr(module, attribute_name)
    if not callable(executor):
        raise TypeError(f"executor is not callable for {spec.capability_id}: {spec.executor_ref}")
    return partial(executor, *spec.executor_args) if spec.executor_args else executor


def execute_registered_capability(name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    spec = capability_registry().require(name)
    _validate_schema_payload(spec, "input", spec.input_schema, payload)
    executor = load_executor(spec)
    result = executor(**dict(payload))
    if not isinstance(result, Mapping):
        raise TypeError(f"executor for {spec.capability_id} must return a mapping")
    _validate_schema_payload(spec, "output", spec.output_schema, result)
    return dict(result)


def _validate_schema_payload(
    spec: ToolSpec,
    direction: Literal["input", "output"],
    schema: DataSchema,
    payload: Mapping[str, Any],
) -> None:
    if not isinstance(payload, Mapping):
        raise CapabilitySchemaValidationError(
            capability_id=spec.capability_id,
            direction=direction,
            schema_id=schema.schema_id,
            problems=(f"expected object, got {_value_type_name(payload)}",),
        )

    problems: list[str] = []
    non_string_keys = sorted(repr(key) for key in payload if not isinstance(key, str))
    if non_string_keys:
        problems.append(f"property names must be strings: {', '.join(non_string_keys)}")

    declared = {field.name: field for field in schema.fields}
    missing = sorted(
        field.name
        for field in schema.fields
        if field.required and field.name not in payload
    )
    if missing:
        problems.append(f"missing required properties: {', '.join(missing)}")

    if not schema.additional_properties:
        unexpected = sorted(
            str(key)
            for key in payload
            if isinstance(key, str) and key not in declared
        )
        if unexpected:
            problems.append(f"unexpected properties: {', '.join(unexpected)}")

    for field_name in sorted(set(payload).intersection(declared)):
        field = declared[field_name]
        value = payload[field_name]
        if field.value_type not in _SUPPORTED_SCHEMA_TYPES:
            problems.append(
                f"property {field_name} has unsupported declared type {field.value_type!r}"
            )
            continue
        if not _matches_schema_type(value, field.value_type):
            problems.append(
                f"property {field_name} must be {field.value_type}; "
                f"got {_value_type_name(value)}"
            )

    if problems:
        raise CapabilitySchemaValidationError(
            capability_id=spec.capability_id,
            direction=direction,
            schema_id=schema.schema_id,
            problems=problems,
        )


def _matches_schema_type(value: Any, value_type: str) -> bool:
    if value_type in {"string", "date"}:
        return isinstance(value, str)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if value_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if value_type in {"object", "geojson"}:
        return isinstance(value, Mapping)
    if value_type in {"array[string]", "list[string]"}:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def _value_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def http_dispatch_name(name: str) -> str:
    registry = capability_registry()
    spec = registry.resolve_surface("http", name)
    return spec.surface_names("http")[0]


def capability_catalog(surface: CapabilitySurface | None = None) -> dict[str, Any]:
    return capability_registry().catalog(surface)


def cli_capability_listing() -> list[dict[str, Any]]:
    grouped: dict[str, list[ToolSpec]] = defaultdict(list)
    for spec in capability_registry().for_surface("cli"):
        for command in spec.surface_names("cli"):
            grouped[command].append(spec)
    return [
        {
            "name": command,
            "purpose": _combined_cli_purpose(command, specs),
            "capability_ids": [spec.capability_id for spec in sorted(specs, key=lambda item: item.capability_id)],
        }
        for command, specs in sorted(grouped.items())
    ]


def render_capability_markdown() -> str:
    lines = [
        "| Capability | Kind | Runtime surfaces | Network | Offline | Implemented | Tested | Natural language | Benchmark |",
        "|---|---|---|---|---|---:|---:|---:|---:|",
    ]
    for spec in capability_registry().specs:
        surfaces = [
            surface
            for surface in ("router", "cli", "http", "agno", "readiness")
            if spec.surface_names(surface)  # type: ignore[arg-type]
        ]
        lines.append(
            f"| `{spec.capability_id}` | {spec.kind} | {', '.join(surfaces)} | {spec.network.mode} | "
            f"{spec.offline.mode} | {'yes' if spec.implemented else 'no'} | {'yes' if spec.tested else 'no'} | "
            f"{'yes' if spec.planner.natural_language_enabled else 'no'} | "
            f"{'yes' if spec.benchmark_exercised else 'no'} |"
        )
    return "\n".join(lines) + "\n"


@lru_cache(maxsize=1)
def capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry(_default_tool_specs())


def _static_spec_issues(specs: Sequence[ToolSpec]) -> list[RegistryIssue]:
    issues: list[RegistryIssue] = []
    valid_kinds = {"guard", "router", "retrieval", "calculator", "decision_frame", "public_adapter", "source_card"}
    for spec in specs:
        if spec.kind not in valid_kinds:
            issues.append(RegistryIssue("invalid_kind", f"invalid kind for {spec.capability_id}: {spec.kind}", (spec.capability_id,)))
        if spec.implemented and not spec.executor_ref:
            issues.append(RegistryIssue("missing_executor", f"implemented capability has no executor: {spec.capability_id}", (spec.capability_id,)))
        if spec.network.mode == "none" and spec.offline.mode == "blocked":
            issues.append(
                RegistryIssue(
                    "contradictory_availability",
                    f"network-free capability cannot be blocked offline: {spec.capability_id}",
                    (spec.capability_id,),
                )
            )
        if spec.tested and not spec.test_fixtures:
            issues.append(RegistryIssue("missing_test_reference", f"tested capability has no test reference: {spec.capability_id}", (spec.capability_id,)))
        if spec.planner.natural_language_enabled and not spec.planner.natural_language_test_evidence:
            issues.append(
                RegistryIssue(
                    "missing_natural_language_test_evidence",
                    f"natural-language-enabled capability has no conversational-path test evidence: {spec.capability_id}",
                    (spec.capability_id,),
                )
            )
        if spec.benchmark_exercised and not spec.benchmark_evidence:
            issues.append(
                RegistryIssue(
                    "missing_benchmark_evidence",
                    f"benchmark-exercised capability has no frozen execution receipt: {spec.capability_id}",
                    (spec.capability_id,),
                )
            )
    return issues


def _surface_collision_issues(specs: Sequence[ToolSpec]) -> list[RegistryIssue]:
    issues: list[RegistryIssue] = []
    for surface in ("router", "http", "agno", "readiness"):
        owners: dict[str, list[str]] = defaultdict(list)
        for spec in specs:
            for name in spec.surface_names(surface):  # type: ignore[arg-type]
                owners[normalize_surface_name(name)].append(spec.capability_id)
        for name, capability_ids in sorted(owners.items()):
            if len(capability_ids) > 1:
                issues.append(
                    RegistryIssue(
                        "duplicate_surface_name",
                        f"{surface} name {name!r} is registered by multiple capabilities",
                        tuple(capability_ids),
                        surface,
                    )
                )
    return issues


def _registered_guard_ids() -> tuple[str, ...]:
    # Import locally so the executor module remains independent of the
    # catalog module and can be used in minimal/offline contexts.
    from agronomy_agent.tools.registry import registered_guard_ids

    return registered_guard_ids()


ROUTE_REQUIRED_CAPABILITY_IDS = _registered_guard_ids()

_PUBLIC_ADAPTER_IDS = (
    "nrcs_soil_survey_point",
    "nrcs_soil_survey_geometry",
    "nasa_power_daily",
    "daymet_single_pixel_daily",
    "openet_point_timeseries",
    "cropland_data_layer_point",
    "cropland_data_layer_geometry",
    "nass_quickstats_crop_stats",
    "epa_ppls_product_search",
    "cansis_soil_landscapes_canada",
    "aafc_annual_crop_inventory",
    "statcan_field_crop_statistics",
    "health_canada_pmra_label_search",
    "aafc_nasdi_agroclimate",
    "canada_et_or_water_use_source_needed",
    "disease_risk_context_adapter",
    "public_variety_trial_ingest",
    "specialty_crop_extension_corpus",
    "conservation_practice_context_adapter",
    "canada_conservation_practice_context_source",
    "field_record_audit_card",
    "partial_budget_calculator",
    "public_program_context_source",
    "forage_livestock_extension_corpus",
    "postharvest_storage_quality_corpus",
    "saskatchewan_official_crop_guidance",
    "nutrient_4r_drainage_water_quality",
    "soil_water_salinity_irrigation_quality",
    "ipm_beneficials_and_thresholds",
    "diagnostic_lab_and_sample_quality",
    "pesticide_safety_and_drift_recordkeeping",
    "seed_quality_and_trait_stewardship",
    "produce_safety_and_irrigation_water",
    "precision_ag_audit_and_trial_design",
    "public_statistics_context_boundary",
    "cross_border_crop_history_public_layers",
    "source_availability_and_tool_choice",
    "forage_feed_safety_extension",
    "postharvest_quality_storage_mycotoxin",
    "farm_economics_sensitivity_and_programs",
)

_DEEP_SOURCE_CARD_IDS = frozenset(
    {
        "saskatchewan_official_crop_guidance",
        "nutrient_4r_drainage_water_quality",
        "soil_water_salinity_irrigation_quality",
        "ipm_beneficials_and_thresholds",
        "diagnostic_lab_and_sample_quality",
        "pesticide_safety_and_drift_recordkeeping",
        "seed_quality_and_trait_stewardship",
        "produce_safety_and_irrigation_water",
        "precision_ag_audit_and_trial_design",
        "public_statistics_context_boundary",
        "cross_border_crop_history_public_layers",
        "source_availability_and_tool_choice",
        "forage_feed_safety_extension",
        "postharvest_quality_storage_mycotoxin",
        "farm_economics_sensitivity_and_programs",
    }
)

_DETERMINISTIC_SOURCE_CARD_IDS = frozenset(
    {
        "disease_risk_context_adapter",
        "public_variety_trial_ingest",
        "specialty_crop_extension_corpus",
        "conservation_practice_context_adapter",
        "canada_conservation_practice_context_source",
        "field_record_audit_card",
        "partial_budget_calculator",
        "public_program_context_source",
        "forage_livestock_extension_corpus",
        "postharvest_storage_quality_corpus",
        *_DEEP_SOURCE_CARD_IDS,
    }
)

_NETWORK_REQUIRED_IDS = frozenset(
    {
        "nasa_power_daily",
        "daymet_single_pixel_daily",
        "openet_point_timeseries",
        "nrcs_soil_survey_point",
        "nrcs_soil_survey_geometry",
        "cropland_data_layer_point",
        "cropland_data_layer_geometry",
        "nass_quickstats_crop_stats",
        "epa_ppls_product_search",
        "cansis_soil_landscapes_canada",
        "aafc_annual_crop_inventory",
        "statcan_field_crop_statistics",
        "health_canada_pmra_label_search",
        "aafc_nasdi_agroclimate",
        "canada_et_or_water_use_source_needed",
    }
)

_OFFLINE_CACHED_IDS = frozenset(
    {"aafc_nasdi_agroclimate", "canada_et_or_water_use_source_needed"}
)

_OFFLINE_SNAPSHOT_IDS = frozenset({"statcan_field_crop_statistics"})

_CREDENTIAL_ENV_VARS: dict[str, tuple[str, ...]] = {
    "openet_point_timeseries": ("AGRONOMY_AGENT_OPENET_API_KEY", "OPENET_API_KEY"),
    "nass_quickstats_crop_stats": (
        "AGRONOMY_AGENT_NASS_QUICKSTATS_API_KEY",
        "USDA_NASS_QUICKSTATS_API_KEY",
        "NASS_API_KEY",
    ),
}

_ADAPTER_VERSIONS: dict[str, str] = {
    "aafc_annual_crop_inventory": "aafc_annual_crop_inventory_v2",
    "statcan_field_crop_statistics": "statcan_field_crop_statistics_v2",
    "health_canada_pmra_label_search": "health_canada_pmra_label_search_v2",
    "canada_et_or_water_use_source_needed": "canada_et_or_water_use_source_needed_v2",
}

_CACHE_PATHS: dict[str, str] = {
    "nasa_power_daily": "outputs/tool_cache/nasa_power",
    "daymet_single_pixel_daily": "outputs/tool_cache/daymet",
    "openet_point_timeseries": "outputs/tool_cache/openet",
    "nrcs_soil_survey_point": "outputs/tool_cache/nrcs_sda",
    "nrcs_soil_survey_geometry": "outputs/tool_cache/nrcs_sda",
    "cropland_data_layer_point": "outputs/tool_cache/cdl",
    "cropland_data_layer_geometry": "outputs/tool_cache/cdl",
    "nass_quickstats_crop_stats": "outputs/tool_cache/nass_quickstats",
    "epa_ppls_product_search": "outputs/tool_cache/epa_ppls",
    "cansis_soil_landscapes_canada": "outputs/tool_cache/cansis_soil_landscapes",
    "aafc_annual_crop_inventory": "outputs/tool_cache/aafc_annual_crop_inventory",
    "statcan_field_crop_statistics": "outputs/tool_cache/statcan_field_crop_statistics",
    "health_canada_pmra_label_search": "outputs/tool_cache/pmra_ppid",
    "aafc_nasdi_agroclimate": "outputs/tool_cache/aafc_nasdi_agroclimate",
    "canada_et_or_water_use_source_needed": "outputs/tool_cache/aafc_nasdi_agroclimate",
}

_DIRECT_CLI_COMMANDS: dict[str, str] = {
    "nasa_power_daily": "weather-power",
    "daymet_single_pixel_daily": "daymet-single-pixel",
    "openet_point_timeseries": "openet-point-timeseries",
    "nrcs_soil_survey_point": "nrcs-soil-survey",
    "nrcs_soil_survey_geometry": "nrcs-soil-survey-geometry",
    "cropland_data_layer_point": "cropland-data-layer",
    "cropland_data_layer_geometry": "cropland-data-layer-geometry",
    "nass_quickstats_crop_stats": "nass-quickstats-crop-stats",
    "epa_ppls_product_search": "epa-ppls-product-search",
}

_CANADA_CLI_LANE_IDS = frozenset(
    {
        "cansis_soil_landscapes_canada",
        "aafc_annual_crop_inventory",
        "statcan_field_crop_statistics",
        "health_canada_pmra_label_search",
        "canada_et_or_water_use_source_needed",
    }
)

_CORE_DECLARATIONS: tuple[dict[str, Any], ...] = (
    {
        "capability_id": "route_question",
        "version": "route_probe_v1",
        "name": "Question router",
        "description": "Classify a question and expose risk, namespaces, and required capabilities.",
        "kind": "router",
        "executor_ref": "agronomy_agent.local_tools:route_question",
        "authority_role": "internal_routing_control",
        "risk_class": "low",
        "surfaces": SurfaceBindings(cli=("route",), http=("route",), agno=("route_question",)),
        "aliases": ("route",),
        "benchmark_exercised": False,
    },
    {
        "capability_id": "retrieve_context",
        "version": "retrieve_probe_v1",
        "name": "Governed retrieval context",
        "description": "Return routed local retrieval and graph context for inspection.",
        "kind": "retrieval",
        "executor_ref": "agronomy_agent.local_tools:retrieve_context",
        "authority_role": "retrieved_context",
        "risk_class": "low",
        "surfaces": SurfaceBindings(cli=("retrieve",), http=("retrieve",), agno=("retrieve_context",)),
        "aliases": ("retrieve",),
        "benchmark_exercised": False,
    },
    {
        "capability_id": "soil_context",
        "version": "soil_context_v1",
        "name": "Regional soil context",
        "description": "Search local soil and environmental corpora for regional context.",
        "kind": "retrieval",
        "executor_ref": "agronomy_agent.local_tools:soil_context",
        "authority_role": "regional_public_prior",
        "risk_class": "low",
        "surfaces": SurfaceBindings(cli=("soil-context",), http=("soil-context",)),
    },
    {
        "capability_id": "spray_window",
        "version": "spray_window_screen_v1",
        "name": "Spray window screen",
        "description": "Screen supplied weather inputs without making a legal application recommendation.",
        "kind": "decision_frame",
        "executor_ref": "agronomy_agent.local_tools:spray_window",
        "authority_role": "deterministic_guardrail",
        "risk_class": "regulated",
        "surfaces": SurfaceBindings(cli=("spray-window",), http=("spray-window",), agno=("spray_window",)),
        "aliases": ("spray-window",),
        "benchmark_exercised": False,
    },
    {
        "capability_id": "fertility_frame",
        "version": "fertility_frame_v1",
        "name": "Fertility decision frame",
        "description": "Name required fertility inputs and calibration boundaries.",
        "kind": "decision_frame",
        "executor_ref": "agronomy_agent.local_tools:fertility_frame",
        "authority_role": "deterministic_guardrail",
        "risk_class": "medium",
        "surfaces": SurfaceBindings(cli=("fertility-frame",), http=("fertility-frame",), agno=("fertility_frame",)),
        "aliases": ("fertility-frame",),
    },
    {
        "capability_id": "diagnostic_frame",
        "version": "diagnostic_frame_v1",
        "name": "Diagnostic decision frame",
        "description": "Return bounded diagnostic and stewardship decision frames.",
        "kind": "decision_frame",
        "executor_ref": "agronomy_agent.local_tools:diagnostic_frame",
        "authority_role": "deterministic_guardrail",
        "risk_class": "medium",
        "surfaces": SurfaceBindings(cli=("diagnostic-frame",), http=("diagnostic-frame",), agno=("diagnostic_frame",)),
        "aliases": ("diagnostic-frame",),
    },
    {
        "capability_id": "agronomic_calculator",
        "version": "agronomic_calculator_v1",
        "name": "Structured agronomic calculator",
        "description": "Run deterministic agronomic arithmetic from explicitly supplied structured inputs.",
        "kind": "calculator",
        "executor_ref": "agronomy_agent.local_tools:agronomic_calculator_tool",
        "authority_role": "deterministic_calculation",
        "risk_class": "medium",
        "surfaces": SurfaceBindings(cli=("calculate",), http=("agronomic-calculator",), agno=("agronomic_calculator",)),
        "aliases": ("calculate", "agronomic-calculator"),
        # RC1 exposed the routing failure but never invoked this capability.
        # Keep this false until a frozen post-repair run exercises the typed path.
        "benchmark_exercised": False,
    },
    {
        "capability_id": "guard_notes",
        "version": "agronomy_guard_notes_v1",
        "name": "Guard-note bundle",
        "description": "Execute a named set of deterministic guard capabilities.",
        "kind": "guard",
        "executor_ref": "agronomy_agent.tools.registry:run_tools",
        "authority_role": "safety_policy",
        "risk_class": "mixed",
        "surfaces": SurfaceBindings(agno=("guard_notes",)),
    },
)


def _default_tool_specs() -> tuple[ToolSpec, ...]:
    specs: list[ToolSpec] = []
    specs.extend(_guard_specs())
    for declaration in _CORE_DECLARATIONS:
        specs.append(_core_spec(declaration))
    specs.extend(_public_adapter_specs())
    return tuple(specs)


def _guard_specs() -> list[ToolSpec]:
    from agronomy_agent.skill_registry import SKILL_CONTRACTS

    specs: list[ToolSpec] = []
    for capability_id in ROUTE_REQUIRED_CAPABILITY_IDS:
        contract = SKILL_CONTRACTS[capability_id]
        specs.append(
            ToolSpec(
                capability_id=capability_id,
                version=contract.skill_id,
                name=contract.name,
                description=f"Deterministic {contract.name.lower()} for routed agronomic questions.",
                kind="guard",
                input_schema=_schema_from_mapping(f"{contract.skill_id}.input", contract.inputs, required=("query",)),
                output_schema=_schema_from_mapping(f"{contract.skill_id}.output", contract.outputs),
                executor_ref=f"agronomy_agent.tools.registry:{capability_id}",
                risk_class=contract.risk_class,
                authority_role="safety_policy",
                boundary=contract.boundary,
                network=NetworkPolicy(mode="none", allowed_in_chat=True),
                offline=OfflinePolicy(mode="native"),
                planner=PlannerMetadata(
                    triggers=tuple(contract.eval_tags),
                    natural_language_enabled=True,
                    natural_language_test_evidence=(
                        "tests/test_evals.py",
                        "tests/test_capability_registry.py",
                    ),
                ),
                surfaces=SurfaceBindings(router=(capability_id,), agno=(capability_id,)),
                verifier_adapter="guard_note_evidence",
                test_fixtures=("tests/test_evals.py", "tests/test_capability_registry.py"),
                implemented=True,
                tested=True,
                benchmark_exercised=False,
                docs_path="docs/public/tools-and-adapters.md",
            )
        )
    return specs


def _core_spec(declaration: Mapping[str, Any]) -> ToolSpec:
    capability_id = str(declaration["capability_id"])
    if capability_id == "agronomic_calculator":
        input_schema = DataSchema(
            "agronomic_calculator_v1.input",
            (
                SchemaField("operation", "string", True),
                SchemaField("inputs", "object", True),
            ),
        )
        output_schema = DataSchema(
            "agronomic_calculator_v1.output",
            (
                SchemaField("value", "number"),
                SchemaField("unit", "string"),
                SchemaField("formula", "string"),
                SchemaField("assumptions", "array[string]"),
                SchemaField("boundary", "string"),
            ),
            additional_properties=True,
        )
    else:
        input_schema = DataSchema(
            f"{capability_id}.input.v1",
            (SchemaField("question", "string"),),
            additional_properties=True,
        )
        output_schema = DataSchema(f"{capability_id}.output.v1", additional_properties=True)
    return ToolSpec(
        capability_id=capability_id,
        version=str(declaration["version"]),
        name=str(declaration["name"]),
        description=str(declaration["description"]),
        kind=declaration["kind"],
        input_schema=input_schema,
        output_schema=output_schema,
        executor_ref=str(declaration["executor_ref"]),
        risk_class=str(declaration["risk_class"]),
        authority_role=str(declaration["authority_role"]),
        boundary=(
            "Arithmetic from supplied structured inputs only; the capability does not choose a target, "
            "confirm a label, or establish field suitability."
            if capability_id == "agronomic_calculator"
            else "Decision-support capability; preserve its declared evidence and authority limits."
        ),
        network=NetworkPolicy(mode="none", allowed_in_chat=True),
        offline=OfflinePolicy(mode="native"),
        planner=PlannerMetadata(
            natural_language_enabled=capability_id in {"agronomic_calculator"},
            natural_language_test_evidence=(
                ("tests/test_tool_planner_end_to_end.py",)
                if capability_id == "agronomic_calculator"
                else ()
            ),
        ),
        surfaces=declaration["surfaces"],
        aliases=tuple(declaration.get("aliases") or ()),
        test_fixtures=(
            "tests/test_agronomic_calculations.py",
            "tests/test_tool_planner_end_to_end.py",
            "tests/test_capability_registry.py",
        )
        if capability_id == "agronomic_calculator"
        else ("tests/test_public_tool_adapters.py", "tests/test_capability_registry.py"),
        implemented=True,
        tested=True,
        # No checked-in run receipt currently proves per-capability invocation
        # through this exact interface. Keep legacy/exposed suite expectations
        # separate from an execution claim.
        benchmark_exercised=False,
        docs_path="docs/public/tools-and-adapters.md",
    )


def _public_adapter_specs() -> list[ToolSpec]:
    from agronomy_agent import local_tools

    definitions: dict[str, Mapping[str, Any]] = {}
    definitions.update(local_tools.CANADA_SOURCE_LANE_DEFINITIONS)
    definitions.update(local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS)
    definitions.update(local_tools.DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS)
    specs: list[ToolSpec] = []
    for capability_id in _PUBLIC_ADAPTER_IDS:
        definition = definitions.get(capability_id, {})
        source_card = capability_id in _DETERMINISTIC_SOURCE_CARD_IDS
        network_required = capability_id in _NETWORK_REQUIRED_IDS
        offline_mode: OfflineMode
        if capability_id in _OFFLINE_SNAPSHOT_IDS:
            offline_mode = "snapshot"
        elif capability_id in _OFFLINE_CACHED_IDS:
            offline_mode = "cached"
        elif network_required:
            offline_mode = "blocked"
        else:
            offline_mode = "native"
        cli_names: tuple[str, ...] = ()
        if capability_id in _DIRECT_CLI_COMMANDS:
            cli_names = (_DIRECT_CLI_COMMANDS[capability_id],)
        elif capability_id in _CANADA_CLI_LANE_IDS:
            cli_names = ("canada-source-lane",)
        executor_ref = f"agronomy_agent.local_tools:{capability_id}"
        executor_args: tuple[Any, ...] = ()
        if capability_id in _DEEP_SOURCE_CARD_IDS:
            executor_ref = "agronomy_agent.local_tools:public_source_lane_card"
            executor_args = (capability_id,)
        name = str(
            definition.get("source_name")
            or definition.get("name")
            or capability_id.replace("_", " ").title()
        )
        description = str(
            definition.get("coverage")
            or definition.get("demo_impact")
            or f"Provide governed {name.lower()} context."
        )
        boundary = str(
            definition.get("boundary")
            or "Public context is a decision-support prior, not field truth or independent approval."
        )
        trigger = str(definition.get("trigger") or definition.get("coverage") or "")
        required_context = ("field_context",) if capability_id not in _DETERMINISTIC_SOURCE_CARD_IDS else ()
        risk_class = "regulated" if capability_id in {
            "epa_ppls_product_search",
            "health_canada_pmra_label_search",
            "pesticide_safety_and_drift_recordkeeping",
        } else "low"
        authority_role = "official_registry_metadata" if capability_id in {
            "epa_ppls_product_search",
            "health_canada_pmra_label_search",
        } else ("source_lane_card" if source_card else "public_context_prior")
        http_name = _DIRECT_CLI_COMMANDS.get(capability_id, capability_id.replace("_", "-"))
        specs.append(
            ToolSpec(
                capability_id=capability_id,
                version=_ADAPTER_VERSIONS.get(capability_id, f"{capability_id}_v1"),
                name=name,
                description=description,
                kind="source_card" if source_card else "public_adapter",
                input_schema=_public_input_schema(capability_id, source_card=source_card),
                output_schema=DataSchema(
                    f"{capability_id}.output.v1",
                    (
                        SchemaField("tool", "string"),
                        SchemaField("status", "string"),
                        SchemaField("boundary", "string"),
                    ),
                    additional_properties=True,
                ),
                executor_ref=executor_ref,
                executor_args=executor_args,
                risk_class=risk_class,
                authority_role=authority_role,
                boundary=boundary,
                network=NetworkPolicy(
                    mode="required" if network_required else "none",
                    credential_env_vars=_CREDENTIAL_ENV_VARS.get(capability_id, ()),
                    allowed_in_chat=True,
                ),
                offline=OfflinePolicy(
                    mode=offline_mode,
                    cache_path=_CACHE_PATHS.get(capability_id),
                    snapshot_path="data/snapshots/statcan_field_crop_statistics.jsonl"
                    if capability_id == "statcan_field_crop_statistics"
                    else None,
                ),
                freshness=FreshnessPolicy(
                    basis="provider_or_cache_timestamp" if network_required else "source_lane_manifest"
                ),
                planner=PlannerMetadata(
                    triggers=(trigger,) if trigger else (),
                    required_context=required_context,
                    # Product preflight contains selection rules, but focused
                    # tests currently prove the executor/surface contracts, not
                    # end-to-end conversational selection and final-answer use
                    # for every adapter. Do not promote that broader claim yet.
                    natural_language_enabled=False,
                ),
                surfaces=SurfaceBindings(
                    cli=cli_names,
                    http=(http_name,),
                    agno=(capability_id,),
                    readiness=(capability_id,),
                ),
                aliases=(capability_id.replace("_", "-"),),
                renderer="source_card" if source_card else "public_adapter_result",
                verifier_adapter="public_source_evidence",
                test_fixtures=("tests/test_public_tool_adapters.py", "tests/test_capability_registry.py"),
                implemented=True,
                tested=True,
                benchmark_exercised=False,
                docs_path="docs/public/tools-and-adapters.md",
            )
        )
    return specs


def _schema_from_mapping(
    schema_id: str,
    fields: Mapping[str, str],
    *,
    required: Iterable[str] = (),
) -> DataSchema:
    required_names = set(required)
    return DataSchema(
        schema_id,
        tuple(
            SchemaField(str(name), str(value_type), str(name) in required_names)
            for name, value_type in sorted(fields.items())
        ),
    )


def _public_input_schema(capability_id: str, *, source_card: bool) -> DataSchema:
    if source_card:
        fields = (
            SchemaField("crop", "string"),
            SchemaField("region", "string"),
            SchemaField("concern", "string"),
            SchemaField("jurisdiction", "string"),
            SchemaField("practice", "string"),
        )
    else:
        fields = (
            SchemaField("lat", "number"),
            SchemaField("lon", "number"),
            SchemaField("geometry", "geojson"),
            SchemaField("crop", "string"),
            SchemaField("region", "string"),
            SchemaField("province", "string"),
            SchemaField("start", "date"),
            SchemaField("end", "date"),
        )
    return DataSchema(f"{capability_id}.input.v1", fields, additional_properties=True)


def _combined_cli_purpose(command: str, specs: Sequence[ToolSpec]) -> str:
    if command == "canada-source-lane":
        return "Fetch Canadian public-source context through the selected governed source lane."
    if len(specs) == 1:
        return specs[0].description
    return f"Access {len(specs)} registered capabilities through the {command} command."
