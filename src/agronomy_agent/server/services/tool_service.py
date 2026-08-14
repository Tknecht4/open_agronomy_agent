from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

from agronomy_agent import local_tools
from agronomy_agent.capability_registry import (
    ROUTE_REQUIRED_CAPABILITY_IDS,
    capability_catalog,
    capability_registry,
    execute_registered_capability,
    http_dispatch_name,
    normalize_surface_name,
)
from agronomy_agent.paths import repo_path


PUBLIC_ADAPTER_READINESS_SCHEMA_VERSION = "open_agronomy_agent.public_adapter_readiness.v1"

_PUBLIC_TOOL_CACHE_SUBDIRS = {
    "weather-power": "nasa_power",
    "daymet-single-pixel": "daymet",
    "openet-point-timeseries": "openet",
    "nrcs-soil-survey": "nrcs_sda",
    "nrcs-soil-survey-geometry": "nrcs_sda",
    "cropland-data-layer": "cdl",
    "cropland-data-layer-geometry": "cdl",
    "nass-quickstats-crop-stats": "nass_quickstats",
    "epa-ppls-product-search": "epa_ppls",
    "cansis-soil-landscapes-canada": "cansis_soil_landscapes",
    "aafc-annual-crop-inventory": "aafc_annual_crop_inventory",
    "statcan-field-crop-statistics": "statcan_field_crop_statistics",
    "health-canada-pmra-label-search": "pmra_ppid",
    "canada-et-or-water-use-source-needed": "aafc_nasdi_agroclimate",
    "aafc-nasdi-agroclimate": "aafc_nasdi_agroclimate",
}

_CAPABILITY_REGISTRY = capability_registry()
_NETWORK_DEPENDENT_TOOLS = frozenset(
    spec.surface_names("http")[0]
    for spec in _CAPABILITY_REGISTRY.for_surface("http")
    if spec.network.mode == "required"
)
_OFFLINE_CACHE_CAPABLE_TOOLS = frozenset(
    spec.surface_names("http")[0]
    for spec in _CAPABILITY_REGISTRY.for_surface("http")
    if spec.offline.mode in {"cached", "snapshot"}
)


PUBLIC_ADAPTER_SMOKE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "ppls_adapter_modes",
        "label": "EPA PPLS search-mode smoke",
        "artifact_path": "outputs/tool_smoke/ppls_adapter_modes_latest.json",
        "expected_schema_version": "open_agronomy_agent.ppls_adapter_smoke.v1",
        "expected_mode": "offline_fixture",
        "expected_case_count": 4,
        "adapter_ids": ("epa_ppls_product_search",),
        "blocking_for": "product-stewardship prompts",
        "boundary": "Offline PPLS smoke proves adapter routing/normalization, not legal label interpretation or local approval.",
    },
    {
        "id": "keyed_public_adapters",
        "label": "Key-gated Quick Stats/OpenET smoke",
        "artifact_path": "outputs/tool_smoke/keyed_public_adapters_latest.json",
        "expected_schema_version": "open_agronomy_agent.keyed_public_adapter_smoke.v1",
        "expected_mode": "offline_fixture",
        "expected_case_count": 4,
        "adapter_ids": ("nass_quickstats_crop_stats", "openet_point_timeseries"),
        "blocking_for": "crop-statistics and irrigation/ET prompts",
        "boundary": "Offline keyed-adapter smoke proves credential/error handling and fixture normalization, not live credentials or provider coverage.",
    },
    {
        "id": "public_adapter_regional_matrix",
        "label": "Regional public-adapter matrix smoke",
        "artifact_path": "outputs/tool_smoke/public_adapter_regional_matrix_latest.json",
        "expected_schema_version": "open_agronomy_agent.public_adapter_regional_matrix.v1",
        "expected_mode": "offline_fixture",
        "expected_case_count": 63,
        "adapter_ids": (
            "nrcs_soil_survey_point",
            "nrcs_soil_survey_geometry",
            "nasa_power_daily",
            "daymet_single_pixel_daily",
            "cropland_data_layer_point",
            "cropland_data_layer_geometry",
            "nass_quickstats_crop_stats",
            "epa_ppls_product_search",
            "openet_point_timeseries",
            "cansis_soil_landscapes_canada",
        "aafc_annual_crop_inventory",
        "aafc_nasdi_agroclimate",
        "statcan_field_crop_statistics",
            "health_canada_pmra_label_search",
            "canada_et_or_water_use_source_needed",
        ),
        "blocking_for": "field-context public-source walkthroughs, including Canadian public-adapter boundaries",
        "boundary": (
            "Offline regional matrix smoke proves adapter contracts across representative field contexts, including "
            "AAFC NASDI catalog selection and locked-raster normalization; it does not prove live provider uptime, "
            "credential validity, exhaustive regional coverage, or field-specific truth."
        ),
    },
)


def _deep_source_lane_adapter_spec(source_lane_id: str, definition: dict[str, Any]) -> dict[str, Any]:
    source_urls = list(definition.get("source_urls") or [])
    return {
        "id": source_lane_id,
        "label": f"{str(definition.get('source_name') or source_lane_id).replace(' lane', '')} source card",
        "provider": definition.get("provider") or "Open Agronomy Agent",
        "credential_env_vars": (),
        "source": source_urls[0] if source_urls else None,
        "cache_dir": "outputs/tool_cache/cansis_soil_landscapes",
        "trigger": "deep public-domain coverage source-lane prompts",
        "field_context_required": False,
        "demo_impact": definition.get("coverage") or "Frames public source-lane evidence for deep coverage prompts.",
        "boundary": definition.get("boundary") or "Deterministic source-lane card; not a live public-data query.",
    }


PUBLIC_ADAPTER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "nrcs_soil_survey_point",
        "label": "NRCS point soil survey",
        "provider": "USDA NRCS",
        "credential_env_vars": (),
        "source": local_tools.NRCS_SDA_POST_REST_URL,
        "cache_dir": "outputs/tool_cache/nrcs_sda",
        "trigger": "point or representative boundary point",
        "field_context_required": True,
        "demo_impact": "Map-unit soil survey prior for point-based field questions.",
        "boundary": "Soil survey is a map-unit prior, not a lab result or field truth.",
    },
    {
        "id": "nrcs_soil_survey_geometry",
        "label": "NRCS boundary/component soil survey",
        "provider": "USDA NRCS",
        "credential_env_vars": (),
        "source": local_tools.NRCS_SDA_POST_REST_URL,
        "cache_dir": "outputs/tool_cache/nrcs_sda",
        "trigger": "drawn or uploaded polygon boundary",
        "field_context_required": True,
        "demo_impact": "Dominant component, drainage class, hydrologic group, and hydric-rating context.",
        "boundary": "Boundary/component results are soil-survey priors, not exact in-field soil conditions.",
    },
    {
        "id": "nasa_power_daily",
        "label": "NASA POWER daily weather",
        "provider": "NASA POWER",
        "credential_env_vars": (),
        "source": "https://power.larc.nasa.gov/api/temporal/daily/point",
        "cache_dir": "outputs/tool_cache/nasa_power",
        "trigger": "point or representative boundary point",
        "field_context_required": True,
        "demo_impact": "Recent gridded weather context for rainfall, wind, heat, leaching, and spray-window questions.",
        "boundary": "Gridded weather context is not an on-field sensor or local forecast advisory.",
    },
    {
        "id": "daymet_single_pixel_daily",
        "label": "ORNL Daymet climate window",
        "provider": "ORNL Daymet",
        "credential_env_vars": (),
        "source": local_tools.DAYMET_SINGLE_PIXEL_API_URL,
        "cache_dir": "outputs/tool_cache/daymet",
        "trigger": "climate, water-window, planting-window, frost, heat, cover-crop, or soil-moisture wording",
        "field_context_required": True,
        "demo_impact": "Historical daily climate-window precipitation and temperature facts.",
        "boundary": "Historical gridded climate context is not a current forecast, field sensor, or irrigation prescription.",
    },
    {
        "id": "openet_point_timeseries",
        "label": "OpenET evapotranspiration",
        "provider": "OpenET",
        "credential_env_vars": local_tools.OPENET_ENV_VARS,
        "source": local_tools.OPENET_RASTER_TIMESERIES_POINT_URL,
        "cache_dir": "outputs/tool_cache/openet",
        "trigger": "irrigation, evapotranspiration, crop water use, water budget, or water-demand wording",
        "field_context_required": True,
        "demo_impact": "Satellite/model ET context for western irrigated-field demos when a key is configured.",
        "boundary": "ET context is not an irrigation prescription, field sensor, or water-right accounting record.",
    },
    {
        "id": "cropland_data_layer_point",
        "label": "CDL point crop-cover class",
        "provider": "USDA NASS",
        "credential_env_vars": (),
        "source": local_tools.CROPSCAPE_CDL_VALUE_URL,
        "cache_dir": "outputs/tool_cache/cdl",
        "trigger": "point or representative boundary point",
        "field_context_required": True,
        "demo_impact": "Point crop-cover prior for crop-history and rotation questions.",
        "boundary": "CDL is land-cover context, not a grower planting record or acreage proof.",
    },
    {
        "id": "cropland_data_layer_geometry",
        "label": "CDL boundary crop-cover sample",
        "provider": "USDA NASS",
        "credential_env_vars": (),
        "source": local_tools.CROPSCAPE_CDL_VALUE_URL,
        "cache_dir": "outputs/tool_cache/cdl",
        "trigger": "drawn or uploaded polygon boundary",
        "field_context_required": True,
        "demo_impact": "Multi-year sampled crop-cover prior for boundary-level crop-history review.",
        "boundary": "Boundary sampling is not acreage accounting, crop-insurance evidence, or verified field history.",
    },
    {
        "id": "nass_quickstats_crop_stats",
        "label": "NASS Quick Stats crop statistics",
        "provider": "USDA NASS",
        "credential_env_vars": local_tools.NASS_QUICKSTATS_ENV_VARS,
        "source": local_tools.NASS_QUICKSTATS_API_URL,
        "cache_dir": "outputs/tool_cache/nass_quickstats",
        "offline_snapshot_path": local_tools.NASS_QUICKSTATS_SNAPSHOT_PATH,
        "trigger": "crop plus US state/county field context",
        "field_context_required": True,
        "demo_impact": "Regional yield, harvested area, and production context when a key is configured.",
        "boundary": "Regional statistics are not field-specific yield prediction, market advice, or grower records.",
    },
    {
        "id": "epa_ppls_product_search",
        "label": "EPA PPLS product metadata",
        "provider": "EPA",
        "credential_env_vars": (),
        "source": local_tools.EPA_PPLS_BASE_URL,
        "cache_dir": "outputs/tool_cache/epa_ppls",
        "trigger": "recognized product or ingredient term such as glyphosate, dicamba, atrazine, or paraquat",
        "field_context_required": False,
        "demo_impact": "Product/ingredient metadata and label-boundary evidence for stewardship questions.",
        "boundary": "PPLS metadata is not legal label interpretation, local approval, or exact rate advice.",
    },
    {
        "id": "cansis_soil_landscapes_canada",
        "label": "CanSIS soil landscape source lane",
        "provider": "Agriculture and Agri-Food Canada",
        "credential_env_vars": (),
        "source": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["cansis_soil_landscapes_canada"]["source"],
        "cache_dir": "",
        "trigger": "Canadian point or boundary soil questions",
        "field_context_required": True,
        "readiness_status": "ready",
        "status_label": "public point soil-landscape prior",
        "demo_impact": "Retrieves a broad AAFC Soil Landscapes of Canada point prior for Canadian field context.",
        "boundary": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["cansis_soil_landscapes_canada"]["boundary"],
    },
    {
        "id": "aafc_annual_crop_inventory",
        "label": "AAFC Annual Crop Inventory crop-cover sample",
        "provider": "Agriculture and Agri-Food Canada",
        "credential_env_vars": (),
        "source": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["aafc_annual_crop_inventory"]["source"],
        "cache_dir": "outputs/tool_cache/aafc_annual_crop_inventory",
        "trigger": "Canadian point or drawn/uploaded boundary crop-cover and crop-history questions",
        "field_context_required": True,
        "readiness_status": "ready",
        "status_label": "public point and boundary sample",
        "demo_impact": "Samples AAFC's annual 30 m crop-cover classification across a Canadian point or field boundary.",
        "boundary": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["aafc_annual_crop_inventory"]["boundary"],
    },
    {
        "id": "statcan_field_crop_statistics",
        "label": "Statistics Canada field-crop statistics",
        "provider": "Statistics Canada",
        "credential_env_vars": (),
        "source": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["statcan_field_crop_statistics"]["source"],
        "cache_dir": "outputs/tool_cache/statcan_field_crop_statistics",
        "offline_snapshot_path": local_tools.STATCAN_FIELD_CROP_SNAPSHOT_PATH,
        "trigger": "Canadian crop plus optional province yield, area, or production questions",
        "field_context_required": True,
        "readiness_status": "ready",
        "status_label": "public regional statistics",
        "demo_impact": "Retrieves published national or provincial crop area, yield, and production series from Statistics Canada.",
        "boundary": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["statcan_field_crop_statistics"]["boundary"],
    },
    {
        "id": "health_canada_pmra_label_search",
        "label": "Health Canada PMRA product registry metadata",
        "provider": "Health Canada PMRA",
        "credential_env_vars": (),
        "source": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["health_canada_pmra_label_search"]["source"],
        "cache_dir": "outputs/tool_cache/pmra_ppid",
        "trigger": "Canadian pesticide question with an exact 4- or 5-digit PMRA registration number",
        "field_context_required": False,
        "demo_impact": "Fetches Canadian PMRA product and label registry metadata for an exact registration number.",
        "boundary": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["health_canada_pmra_label_search"]["boundary"],
    },
    {
        "id": "aafc_nasdi_agroclimate",
        "label": "AAFC NASDI dated agroclimate context",
        "provider": "Agriculture and Agri-Food Canada",
        "credential_env_vars": (),
        "source": local_tools.AAFC_NASDI_OPEN_DATA_URL,
        "cache_dir": "outputs/tool_cache/aafc_nasdi_agroclimate",
        "trigger": "Canadian drought, SPI, SPEI, precipitation anomaly, temperature anomaly, irrigation, or water-stress questions",
        "field_context_required": True,
        "readiness_status": "ready",
        "status_label": "public dated regional grid sample",
        "demo_impact": "Samples exact dated AAFC NASDI catalog rasters for bounded Canadian point or boundary context.",
        "boundary": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["canada_et_or_water_use_source_needed"]["boundary"],
    },
    {
        "id": "canada_et_or_water_use_source_needed",
        "label": "Canadian agroclimate compatibility alias",
        "provider": "Agriculture and Agri-Food Canada",
        "credential_env_vars": (),
        "source": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["canada_et_or_water_use_source_needed"]["source"],
        "cache_dir": "outputs/tool_cache/aafc_nasdi_agroclimate",
        "trigger": "Canadian ET, irrigation, crop water use, or water-budget questions",
        "field_context_required": True,
        "readiness_status": "ready",
        "status_label": "live NASDI compatibility alias",
        "demo_impact": "Preserves old tool contracts while returning the live bounded AAFC NASDI result.",
        "boundary": local_tools.CANADA_SOURCE_LANE_DEFINITIONS["canada_et_or_water_use_source_needed"]["boundary"],
    },
    {
        "id": "disease_risk_context_adapter",
        "label": "Disease risk source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["disease_risk_context_adapter"]["provider"],
        "credential_env_vars": (),
        "source": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["disease_risk_context_adapter"]["source_urls"][0],
        "cache_dir": "",
        "trigger": "disease, fungicide ROI, weather disease risk, root rot, leaf spotting, or diagnostic uncertainty",
        "field_context_required": False,
        "demo_impact": "Frames disease-risk and fungicide-economics evidence before treatment claims.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["disease_risk_context_adapter"]["boundary"],
    },
    {
        "id": "public_variety_trial_ingest",
        "label": "Public variety trial source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["public_variety_trial_ingest"]["provider"],
        "credential_env_vars": (),
        "source": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["public_variety_trial_ingest"]["source_urls"][0],
        "cache_dir": "",
        "trigger": "hybrid, variety, seed selection, maturity group, or cultivar performance questions",
        "field_context_required": False,
        "demo_impact": "Frames public replicated variety-trial evidence and local adaptation boundaries.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["public_variety_trial_ingest"]["boundary"],
    },
    {
        "id": "specialty_crop_extension_corpus",
        "label": "Specialty-crop extension source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["specialty_crop_extension_corpus"]["provider"],
        "credential_env_vars": (),
        "source": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["specialty_crop_extension_corpus"]["source_urls"][0],
        "cache_dir": "",
        "trigger": "specialty crop, vegetable, fruit, horticulture, irrigation, quality, or IPM questions",
        "field_context_required": False,
        "demo_impact": "Keeps specialty-crop answers tied to crop-specific extension lanes.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["specialty_crop_extension_corpus"]["boundary"],
    },
    {
        "id": "conservation_practice_context_adapter",
        "label": "Conservation practice source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["conservation_practice_context_adapter"]["provider"],
        "credential_env_vars": (),
        "source": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["conservation_practice_context_adapter"]["source_urls"][0],
        "cache_dir": "",
        "trigger": "conservation practice, runoff, erosion, drainage, buffer, cover crop, water quality, or BMP questions",
        "field_context_required": True,
        "demo_impact": "Frames NRCS practice-standard and conservation-planning evidence without implying approval.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["conservation_practice_context_adapter"]["boundary"],
    },
    {
        "id": "canada_conservation_practice_context_source",
        "label": "Canadian conservation source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["canada_conservation_practice_context_source"]["provider"],
        "credential_env_vars": (),
        "source": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["canada_conservation_practice_context_source"]["source_urls"][0],
        "cache_dir": "",
        "trigger": "Canadian conservation, BMP, erosion, runoff, drainage, or water-quality questions",
        "field_context_required": True,
        "demo_impact": "Prevents Canadian conservation rows from falling back to U.S.-only program assumptions.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["canada_conservation_practice_context_source"]["boundary"],
    },
    {
        "id": "field_record_audit_card",
        "label": "Field-record audit source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["field_record_audit_card"]["provider"],
        "credential_env_vars": (),
        "source": None,
        "cache_dir": "",
        "trigger": "yield maps, soil zones, prescriptions, field records, as-applied data, or audit-trail questions",
        "field_context_required": True,
        "demo_impact": "Defines what must be true before field records support precision-ag recommendations.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["field_record_audit_card"]["boundary"],
    },
    {
        "id": "partial_budget_calculator",
        "label": "Partial-budget source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["partial_budget_calculator"]["provider"],
        "credential_env_vars": (),
        "source": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["partial_budget_calculator"]["source_urls"][0],
        "cache_dir": "",
        "trigger": "ROI, pay, economics, profitability, conservation economics, precision-ag economics, or farm books",
        "field_context_required": False,
        "demo_impact": "Frames the added returns/reduced costs/added costs/reduced returns evidence needed for payoff claims.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["partial_budget_calculator"]["boundary"],
    },
    {
        "id": "public_program_context_source",
        "label": "Public program source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["public_program_context_source"]["provider"],
        "credential_env_vars": (),
        "source": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["public_program_context_source"]["source_urls"][0],
        "cache_dir": "",
        "trigger": "cost share, public program, USDA, NRCS, conservation program, eligibility, or incentive questions",
        "field_context_required": False,
        "demo_impact": "Separates agronomic fit from program eligibility, ranking, and payment claims.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["public_program_context_source"]["boundary"],
    },
    {
        "id": "forage_livestock_extension_corpus",
        "label": "Forage/livestock safety source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["forage_livestock_extension_corpus"]["provider"],
        "credential_env_vars": (),
        "source": None,
        "cache_dir": "",
        "trigger": "forage, pasture, grazing, hay, nitrate, prussic acid, feed test, or livestock safety questions",
        "field_context_required": False,
        "demo_impact": "Frames forage and livestock-safety evidence before feeding or grazing claims.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["forage_livestock_extension_corpus"]["boundary"],
    },
    {
        "id": "postharvest_storage_quality_corpus",
        "label": "Postharvest storage/quality source card",
        "provider": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["postharvest_storage_quality_corpus"]["provider"],
        "credential_env_vars": (),
        "source": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["postharvest_storage_quality_corpus"]["source_urls"][0],
        "cache_dir": "",
        "trigger": "harvest moisture, drying, storage, quality, damaged grain, mycotoxin, or feed/marketability questions",
        "field_context_required": False,
        "demo_impact": "Frames drying, cooling, monitoring, testing, and quality-boundary evidence.",
        "boundary": local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS["postharvest_storage_quality_corpus"]["boundary"],
    },
    *tuple(
        _deep_source_lane_adapter_spec(source_lane_id, definition)
        for source_lane_id, definition in local_tools.DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS.items()
    ),
)


def tool_name_alias(name: str) -> str:
    try:
        return http_dispatch_name(name)
    except KeyError:
        return normalize_surface_name(name)


def _runtime_tool_payload(tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    subdir = _PUBLIC_TOOL_CACHE_SUBDIRS.get(tool)
    if not subdir:
        return payload
    configured = str(payload.get("cache_dir") or f"outputs/tool_cache/{subdir}")
    runtime_root = os.getenv("AGRONOMY_AGENT_TOOL_CACHE_ROOT", "").strip()
    if runtime_root and (configured == "outputs/tool_cache" or configured.startswith("outputs/tool_cache/")):
        relative = configured.removeprefix("outputs/tool_cache").lstrip("/")
        configured = os.path.join(runtime_root, relative)
    return {**payload, "cache_dir": configured}


def public_adapter_readiness() -> dict[str, Any]:
    smoke_checks = [_public_adapter_smoke_check(spec) for spec in PUBLIC_ADAPTER_SMOKE_SPECS]
    adapters = [_public_adapter_readiness_item(spec, smoke_checks=smoke_checks) for spec in PUBLIC_ADAPTER_SPECS]
    status_counts: dict[str, int] = {}
    for item in adapters:
        status = str(item["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    smoke_counts: dict[str, int] = {}
    for check in smoke_checks:
        smoke_status = str(check["status"])
        smoke_counts[smoke_status] = smoke_counts.get(smoke_status, 0) + 1
    return {
        "schema_version": PUBLIC_ADAPTER_READINESS_SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "summary": {
            "adapter_count": len(adapters),
            "ready_count": status_counts.get("ready", 0),
            "needs_key_count": status_counts.get("needs_key", 0),
            "monitor_count": status_counts.get("monitor", 0),
            "key_gated_count": sum(1 for item in adapters if item["credential_required"]),
            "field_context_required_count": sum(1 for item in adapters if item["field_context_required"]),
            "smoke_check_count": len(smoke_checks),
            "smoke_passed_count": smoke_counts.get("passed", 0),
            "smoke_missing_count": smoke_counts.get("missing", 0),
            "smoke_failed_count": smoke_counts.get("failed", 0),
        },
        "smoke_checks": smoke_checks,
        "adapters": adapters,
        "capability_registry": {
            "schema_version": capability_catalog("readiness")["schema_version"],
            "capability_count": capability_catalog("readiness")["capability_count"],
            "parity_status": "passed"
            if not _CAPABILITY_REGISTRY.audit(
                surface_registrations={"readiness": [str(spec["id"]) for spec in PUBLIC_ADAPTER_SPECS]}
            )
            else "failed",
        },
        "boundary": (
            "Readiness reports configuration and local cache state only. It does not prove that a provider is currently reachable "
            "or that a returned public source is field truth. Offline smoke artifacts prove adapter contracts, not live provider coverage."
        ),
    }


def capability_registry_view(surface: str | None = None) -> dict[str, Any]:
    """Return the JSON-safe canonical capability catalog for HTTP and operator views."""

    allowed_surfaces = {None, "router", "cli", "http", "agno", "readiness", "docs"}
    if surface not in allowed_surfaces:
        raise ValueError(f"unknown capability surface: {surface}")
    catalog = capability_catalog(surface)  # type: ignore[arg-type]
    if surface is None:
        issues = _CAPABILITY_REGISTRY.audit(
            required_tools=ROUTE_REQUIRED_CAPABILITY_IDS,
            surface_registrations={
                "readiness": [str(spec["id"]) for spec in PUBLIC_ADAPTER_SPECS],
            },
        )
        catalog["preflight"] = {
            "status": "passed" if not issues else "failed",
            "issues": [issue.as_record() for issue in issues],
        }
    return catalog


def _public_adapter_readiness_item(spec: dict[str, Any], *, smoke_checks: list[dict[str, Any]]) -> dict[str, Any]:
    env_vars = tuple(str(item) for item in spec.get("credential_env_vars", ()))
    configured_env_vars = [name for name in env_vars if os.getenv(name)]
    credential_required = bool(env_vars)
    snapshot_value = str(spec.get("offline_snapshot_path") or "")
    snapshot_path = repo_path(snapshot_value) if snapshot_value else None
    offline_snapshot_ready = bool(snapshot_path and snapshot_path.is_file() and snapshot_path.stat().st_size > 0)
    configured = (bool(configured_env_vars) or offline_snapshot_ready) if credential_required else True
    status = str(spec.get("readiness_status") or "ready")
    if credential_required and not configured:
        status = "needs_key"
    cache_dir = str(spec.get("cache_dir") or "")
    cache_path = repo_path(cache_dir) if cache_dir else None
    cache_entries = _cache_entry_count(cache_path) if cache_path else 0
    adapter_smoke_checks = [
        _adapter_smoke_summary(check)
        for check in smoke_checks
        if str(spec["id"]) in set(str(item) for item in check.get("adapter_ids", []))
    ]
    return {
        "id": spec["id"],
        "label": spec["label"],
        "provider": spec["provider"],
        "status": status,
        "status_label": str(spec.get("status_label") or ("needs key" if status == "needs_key" else status)),
        "credential_required": credential_required,
        "configured": configured,
        "required_env_vars": list(env_vars),
        "configured_env_vars": configured_env_vars,
        "offline_snapshot_path": snapshot_value,
        "offline_snapshot_ready": offline_snapshot_ready,
        "source": spec.get("source"),
        "cache_dir": cache_dir,
        "cache_entries": cache_entries,
        "smoke_checks": adapter_smoke_checks,
        "smoke_status": _combined_smoke_status(adapter_smoke_checks),
        "field_context_required": bool(spec.get("field_context_required")),
        "trigger": spec.get("trigger"),
        "demo_impact": spec.get("demo_impact"),
        "boundary": spec.get("boundary"),
        "decision_checks": _source_lane_decision_checks(spec),
    }


def _source_lane_decision_checks(spec: dict[str, Any]) -> list[str]:
    adapter_id = str(spec["id"])
    for catalog in (
        local_tools.CANADA_SOURCE_LANE_DEFINITIONS,
        local_tools.PUBLIC_SOURCE_LANE_DEFINITIONS,
        local_tools.DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS,
    ):
        definition = catalog.get(adapter_id)
        if definition:
            return [str(item) for item in definition.get("decision_checks") or []]
    return [str(item) for item in spec.get("decision_checks") or []]


def _public_adapter_smoke_check(spec: dict[str, Any]) -> dict[str, Any]:
    artifact_path = str(spec["artifact_path"])
    path = repo_path(artifact_path)
    base = {
        "id": spec["id"],
        "label": spec["label"],
        "artifact_path": artifact_path,
        "adapter_ids": list(spec.get("adapter_ids") or []),
        "blocking_for": spec.get("blocking_for"),
        "boundary": spec.get("boundary"),
    }
    if not path.exists():
        return {
            **base,
            "status": "missing",
            "status_label": "smoke missing",
            "passed": False,
            "case_count": 0,
            "failure_count": 0,
            "case_ids": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            **base,
            "status": "failed",
            "status_label": "smoke unreadable",
            "passed": False,
            "case_count": 0,
            "failure_count": 1,
            "case_ids": [],
            "error": str(exc)[:220],
            "updated_at": _path_updated_at(path),
        }
    failures = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    validation_errors: list[str] = []
    expected_schema = spec.get("expected_schema_version")
    expected_mode = spec.get("expected_mode")
    expected_case_count = spec.get("expected_case_count")
    if expected_schema and payload.get("schema_version") != expected_schema:
        validation_errors.append("schema_version_mismatch")
    if expected_mode and payload.get("mode") != expected_mode:
        validation_errors.append("mode_mismatch")
    if (
        expected_case_count is not None
        and int(payload.get("case_count") or len(cases)) != int(expected_case_count)
    ):
        validation_errors.append("case_count_mismatch")
    passed = bool(payload.get("passed")) and not failures and not validation_errors
    return {
        **base,
        "status": "passed" if passed else "failed",
        "status_label": "smoke passed" if passed else "smoke failed",
        "passed": passed,
        "schema_version": payload.get("schema_version"),
        "mode": payload.get("mode"),
        "provider": payload.get("provider"),
        "providers": payload.get("providers") or [],
        "case_count": int(payload.get("case_count") or len(cases)),
        "failure_count": len(failures),
        "validation_errors": validation_errors,
        "case_ids": [str(case.get("case_id")) for case in cases if isinstance(case, dict) and case.get("case_id")],
        "updated_at": _path_updated_at(path),
    }


def _adapter_smoke_summary(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": check.get("id"),
        "label": check.get("label"),
        "status": check.get("status"),
        "status_label": check.get("status_label"),
        "passed": check.get("passed"),
        "mode": check.get("mode"),
        "artifact_path": check.get("artifact_path"),
        "case_count": check.get("case_count"),
        "failure_count": check.get("failure_count"),
        "case_ids": check.get("case_ids") or [],
        "updated_at": check.get("updated_at"),
        "boundary": check.get("boundary"),
    }


def _combined_smoke_status(smoke_checks: list[dict[str, Any]]) -> str:
    if not smoke_checks:
        return "not_required"
    statuses = {str(check.get("status")) for check in smoke_checks}
    if "failed" in statuses:
        return "failed"
    if "missing" in statuses:
        return "missing"
    if statuses == {"passed"}:
        return "passed"
    return "unknown"


def _path_updated_at(path: Any) -> str | None:
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).replace(microsecond=0).isoformat()
    except OSError:
        return None


def _cache_entry_count(path: Any) -> int:
    if path is None or not path.exists() or not path.is_dir():
        return 0
    return sum(1 for item in path.glob("*.json") if item.is_file())


def run_local_tool(
    name: str,
    payload: dict[str, Any],
    *,
    network_mode: str = "online",
) -> dict[str, Any]:
    tool = tool_name_alias(name)
    if network_mode not in {"online", "offline"}:
        raise ValueError("network_mode must be 'online' or 'offline'")
    payload = _runtime_tool_payload(tool, payload)
    allowed_tools = set(_CAPABILITY_REGISTRY.surface_names("http"))
    if tool not in allowed_tools:
        raise ValueError(f"unknown tool: {name}")
    if network_mode == "offline" and tool in _NETWORK_DEPENDENT_TOOLS:
        if tool in _OFFLINE_CACHE_CAPABLE_TOOLS:
            payload = {**payload, "offline_only": True}
        else:
            return {
                "tool": tool.replace("-", "_"),
                "status": "blocked_offline",
                "network": {
                    "mode": "offline",
                    "external_calls_attempted": 0,
                    "declaration": "Offline mode blocked this external adapter before any request was made.",
                },
                "boundary": (
                    "This source requires a live external request and has no governed offline snapshot for this "
                    "query. Reconnect or supply verified local evidence before using it."
                ),
            }

    if tool == "route":
        question = payload.get("question", "")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("route tool requires question")
        return local_tools.route_question(question)

    if tool in {"soil-context", "soil_context"}:
        question = payload.get("question", "")
        if not question.strip():
            raise ValueError("soil-context tool requires question")
        top_k = int(payload.get("top_k", 6))
        return local_tools.soil_context(question, top_k=top_k)

    if tool in {"spray-window", "spray_window"}:
        return local_tools.spray_window(
            wind_mph=_optional_float(payload.get("wind_mph")),
            gust_mph=_optional_float(payload.get("gust_mph")),
            temperature_f=_optional_float(payload.get("temperature_f")),
            rain_hours=_optional_float(payload.get("rain_hours")),
            inversion_risk=payload.get("inversion_risk"),
            sensitive_downwind=bool(payload.get("sensitive_downwind", False)),
            operation=payload.get("operation", "spray"),
        )

    if tool in {"fertility-frame", "fertility_frame"}:
        return local_tools.fertility_frame(
            crop=payload.get("crop"),
            yield_goal=_optional_float(payload.get("yield_goal")),
            soil_test_method=payload.get("soil_test_method"),
            soil_ph=_optional_float(payload.get("soil_ph")),
            organic_matter_pct=_optional_float(payload.get("organic_matter_pct")),
            manure_or_legume_credit=bool(payload.get("manure_or_legume_credit", False)),
        )

    if tool in {"diagnostic-frame", "diagnostic_frame"}:
        kind = payload.get("kind")
        if not kind:
            raise ValueError("diagnostic-frame requires kind")
        return local_tools.diagnostic_frame(
            kind=str(kind),
            context=str(payload.get("context", "")),
        )

    if tool in {"agronomic-calculator", "agronomic_calculator"}:
        operation = payload.get("operation")
        inputs = payload.get("inputs")
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("agronomic-calculator requires operation")
        if not isinstance(inputs, dict):
            raise ValueError("agronomic-calculator requires an inputs object")
        return local_tools.agronomic_calculator_tool(operation.strip(), inputs)

    if tool in {"weather-power", "weather_power"}:
        latitude = _required_float(payload, "lat")
        longitude = _required_float(payload, "lon")
        start = payload.get("start")
        end = payload.get("end")
        if not start or not end:
            raise ValueError("weather-power requires start and end")
        parameters = payload.get("parameters", local_tools.DEFAULT_POWER_PARAMETERS)
        if isinstance(parameters, str):
            parameters = tuple(part.strip() for part in parameters.split(",") if part.strip())
        return local_tools.nasa_power_daily(
            latitude=latitude,
            longitude=longitude,
            start=str(start),
            end=str(end),
            parameters=tuple(parameters),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/nasa_power")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"daymet-single-pixel", "daymet_single_pixel"}:
        latitude = _required_float(payload, "lat")
        longitude = _required_float(payload, "lon")
        start = payload.get("start")
        end = payload.get("end")
        if not start or not end:
            raise ValueError("daymet-single-pixel requires start and end")
        variables = payload.get("variables", local_tools.DEFAULT_DAYMET_VARIABLES)
        if isinstance(variables, str):
            variables = tuple(part.strip() for part in variables.split(",") if part.strip())
        return local_tools.daymet_single_pixel_daily(
            latitude=latitude,
            longitude=longitude,
            start=str(start),
            end=str(end),
            variables=tuple(variables),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/daymet")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"openet-point-timeseries", "openet_point_timeseries"}:
        latitude = _required_float(payload, "lat")
        longitude = _required_float(payload, "lon")
        start = payload.get("start")
        end = payload.get("end")
        if not start or not end:
            raise ValueError("openet-point-timeseries requires start and end")
        return local_tools.openet_point_timeseries(
            latitude=latitude,
            longitude=longitude,
            start=str(start),
            end=str(end),
            interval=str(payload.get("interval", "monthly")),
            model=str(payload.get("model", local_tools.DEFAULT_OPENET_MODEL)),
            variable=str(payload.get("variable", local_tools.DEFAULT_OPENET_VARIABLE)),
            reference_et=str(payload.get("reference_et", local_tools.DEFAULT_OPENET_REFERENCE_ET)),
            units=str(payload.get("units", local_tools.DEFAULT_OPENET_UNITS)),
            api_key=_optional_str(payload.get("api_key")),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/openet")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"nrcs-soil-survey", "nrcs_soil_survey"}:
        latitude = _required_float(payload, "lat")
        longitude = _required_float(payload, "lon")
        return local_tools.nrcs_soil_survey_point(
            latitude=latitude,
            longitude=longitude,
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/nrcs_sda")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"nrcs-soil-survey-geometry", "nrcs_soil_survey_geometry"}:
        geometry = payload.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError("nrcs-soil-survey-geometry requires GeoJSON geometry")
        return local_tools.nrcs_soil_survey_geometry(
            geometry=geometry,
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/nrcs_sda")),
            timeout=int(payload.get("timeout", 20)),
            max_map_units=int(payload.get("max_map_units", 12)),
            max_components=int(payload.get("max_components", 40)),
        )

    if tool in {"cropland-data-layer", "cropland_data_layer"}:
        latitude = _required_float(payload, "lat")
        longitude = _required_float(payload, "lon")
        year = payload.get("year")
        return local_tools.cropland_data_layer_point(
            latitude=latitude,
            longitude=longitude,
            year=int(year) if year not in (None, "") else None,
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/cdl")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"cropland-data-layer-geometry", "cropland_data_layer_geometry"}:
        geometry = payload.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError("cropland-data-layer-geometry requires GeoJSON geometry")
        years = payload.get("years")
        if isinstance(years, str):
            years = tuple(int(part.strip()) for part in years.split(",") if part.strip())
        elif isinstance(years, list):
            years = tuple(int(year) for year in years)
        elif years is not None:
            years = tuple(int(year) for year in years)
        return local_tools.cropland_data_layer_geometry(
            geometry=geometry,
            years=years,
            sample_points=int(payload.get("sample_points", local_tools.DEFAULT_CDL_SAMPLE_POINTS)),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/cdl")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"nass-quickstats-crop-stats", "nass_quickstats_crop_stats"}:
        crop = _optional_str(payload.get("crop"))
        state_alpha = _optional_str(payload.get("state_alpha"))
        if not crop:
            raise ValueError("nass-quickstats-crop-stats requires crop")
        if not state_alpha:
            raise ValueError("nass-quickstats-crop-stats requires state_alpha")
        categories = payload.get("statistic_categories", local_tools.DEFAULT_QUICKSTATS_CATEGORIES)
        if isinstance(categories, str):
            categories = tuple(part.strip() for part in categories.split(",") if part.strip())
        return local_tools.nass_quickstats_crop_stats(
            crop=crop,
            state_alpha=state_alpha,
            county_name=_optional_str(payload.get("county_name")),
            year_ge=int(payload["year_ge"]) if payload.get("year_ge") not in (None, "") else None,
            statistic_categories=tuple(categories),
            source_desc=str(payload.get("source_desc", "SURVEY")),
            api_key=_optional_str(payload.get("api_key")),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/nass_quickstats")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"epa-ppls-product-search", "epa_ppls_product_search"}:
        return local_tools.epa_ppls_product_search(
            product_name=_optional_str(payload.get("product_name")),
            epa_reg_no=_optional_str(payload.get("epa_reg_no")),
            ingredient_name=_optional_str(payload.get("ingredient_name")),
            pc_code=_optional_str(payload.get("pc_code")),
            cas_number=_optional_str(payload.get("cas_number")),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/epa_ppls")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"cansis-soil-landscapes-canada", "cansis_soil_landscapes_canada"}:
        return local_tools.cansis_soil_landscapes_canada(
            latitude=_optional_float(payload.get("lat")),
            longitude=_optional_float(payload.get("lon")),
            geometry=payload.get("geometry") if isinstance(payload.get("geometry"), dict) else None,
            crop=_optional_str(payload.get("crop")),
            province=_optional_str(payload.get("province")),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/cansis_soil_landscapes")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"aafc-annual-crop-inventory", "aafc_annual_crop_inventory"}:
        return local_tools.aafc_annual_crop_inventory(
            latitude=_optional_float(payload.get("lat")),
            longitude=_optional_float(payload.get("lon")),
            geometry=payload.get("geometry") if isinstance(payload.get("geometry"), dict) else None,
            crop=_optional_str(payload.get("crop")),
            province=_optional_str(payload.get("province")),
            year=int(payload.get("year", local_tools.DEFAULT_AAFC_ACI_YEAR)),
            sample_points=int(payload.get("sample_points", local_tools.DEFAULT_CDL_SAMPLE_POINTS)),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/aafc_annual_crop_inventory")),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"statcan-field-crop-statistics", "statcan_field_crop_statistics"}:
        return local_tools.statcan_field_crop_statistics(
            crop=_optional_str(payload.get("crop")),
            province=_optional_str(payload.get("province")),
            latest_periods=int(payload.get("latest_periods", 3)),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/statcan_field_crop_statistics")),
            snapshot_path=str(payload.get("snapshot_path", local_tools.STATCAN_FIELD_CROP_SNAPSHOT_PATH)),
            snapshot_manifest_path=str(
                payload.get(
                    "snapshot_manifest_path",
                    local_tools.STATCAN_FIELD_CROP_SNAPSHOT_MANIFEST_PATH,
                )
            ),
            offline_only=bool(payload.get("offline_only", False)),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"health-canada-pmra-label-search", "health_canada_pmra_label_search"}:
        return local_tools.health_canada_pmra_label_search(
            product_term=_optional_str(payload.get("product_term")),
            search_kind=_optional_str(payload.get("search_kind")),
            registration_number=_optional_str(payload.get("registration_number")),
            language=_optional_str(payload.get("language")) or "en",
            cache_dir=_optional_str(payload.get("cache_dir")) or "outputs/tool_cache/pmra_ppid",
            cache_max_age_hours=int(
                payload.get(
                    "cache_max_age_hours",
                    local_tools.PMRA_PPID_DEFAULT_CACHE_MAX_AGE_HOURS,
                )
            ),
            timeout=int(payload.get("timeout", 20)),
        )

    if tool in {"canada-et-or-water-use-source-needed", "canada_et_or_water_use_source_needed"}:
        return local_tools.canada_et_or_water_use_source_needed(
            latitude=_optional_float(payload.get("lat")),
            longitude=_optional_float(payload.get("lon")),
            geometry=payload.get("geometry") if isinstance(payload.get("geometry"), dict) else None,
            crop=_optional_str(payload.get("crop")),
            province=_optional_str(payload.get("province")),
            indicators=tuple(payload.get("indicators") or local_tools.AAFC_NASDI_INDICATORS),
            time_window=_optional_str(payload.get("time_window")),
            sample_points=int(payload.get("sample_points", 1)),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/aafc_nasdi_agroclimate")),
            timeout=int(payload.get("timeout", 20)),
            offline_only=bool(payload.get("offline_only", False)),
        )

    if tool in {"aafc-nasdi-agroclimate", "aafc_nasdi_agroclimate"}:
        return local_tools.aafc_nasdi_agroclimate(
            latitude=_optional_float(payload.get("lat")),
            longitude=_optional_float(payload.get("lon")),
            geometry=payload.get("geometry") if isinstance(payload.get("geometry"), dict) else None,
            crop=_optional_str(payload.get("crop")),
            province=_optional_str(payload.get("province")),
            indicators=tuple(payload.get("indicators") or local_tools.AAFC_NASDI_INDICATORS),
            time_window=_optional_str(payload.get("time_window")),
            sample_points=int(payload.get("sample_points", 1)),
            cache_dir=str(payload.get("cache_dir", "outputs/tool_cache/aafc_nasdi_agroclimate")),
            timeout=int(payload.get("timeout", 20)),
            offline_only=bool(payload.get("offline_only", False)),
        )

    if tool == "disease-risk-context-adapter":
        return local_tools.disease_risk_context_adapter(
            crop=_optional_str(payload.get("crop")),
            disease_or_symptom=_optional_str(payload.get("disease_or_symptom")),
            region=_optional_str(payload.get("region")),
            weather_window=_optional_str(payload.get("weather_window")),
        )

    if tool == "public-variety-trial-ingest":
        return local_tools.public_variety_trial_ingest(
            crop=_optional_str(payload.get("crop")),
            region=_optional_str(payload.get("region")),
            maturity_or_market_class=_optional_str(payload.get("maturity_or_market_class")),
        )

    if tool == "specialty-crop-extension-corpus":
        return local_tools.specialty_crop_extension_corpus(
            crop=_optional_str(payload.get("crop")),
            region=_optional_str(payload.get("region")),
            production_system=_optional_str(payload.get("production_system")),
        )

    if tool == "conservation-practice-context-adapter":
        return local_tools.conservation_practice_context_adapter(
            resource_concern=_optional_str(payload.get("resource_concern")),
            region=_optional_str(payload.get("region")),
            practice=_optional_str(payload.get("practice")),
        )

    if tool == "canada-conservation-practice-context-source":
        return local_tools.canada_conservation_practice_context_source(
            province=_optional_str(payload.get("province")),
            resource_concern=_optional_str(payload.get("resource_concern")),
            practice=_optional_str(payload.get("practice")),
        )

    if tool == "field-record-audit-card":
        return local_tools.field_record_audit_card(
            crop=_optional_str(payload.get("crop")),
            record_type=_optional_str(payload.get("record_type")),
            decision=_optional_str(payload.get("decision")),
        )

    if tool == "partial-budget-calculator":
        return local_tools.partial_budget_calculator(
            proposed_change=_optional_str(payload.get("proposed_change")),
            crop=_optional_str(payload.get("crop")),
            region=_optional_str(payload.get("region")),
        )

    if tool == "public-program-context-source":
        return local_tools.public_program_context_source(
            program_area=_optional_str(payload.get("program_area")),
            jurisdiction=_optional_str(payload.get("jurisdiction")),
            practice=_optional_str(payload.get("practice")),
        )

    if tool == "forage-livestock-extension-corpus":
        return local_tools.forage_livestock_extension_corpus(
            forage=_optional_str(payload.get("forage")),
            livestock_class=_optional_str(payload.get("livestock_class")),
            stress_event=_optional_str(payload.get("stress_event")),
        )

    if tool == "postharvest-storage-quality-corpus":
        return local_tools.postharvest_storage_quality_corpus(
            crop=_optional_str(payload.get("crop")),
            quality_concern=_optional_str(payload.get("quality_concern")),
            storage_duration=_optional_str(payload.get("storage_duration")),
        )

    source_lane_id = tool.replace("-", "_")
    if source_lane_id in local_tools.DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS:
        return local_tools.public_source_lane_card(
            source_lane_id,
            crop=_optional_str(payload.get("crop")),
            region=_optional_str(payload.get("region")),
            concern=_optional_str(payload.get("concern") or payload.get("decision_context")),
            jurisdiction=_optional_str(payload.get("jurisdiction") or payload.get("state") or payload.get("province")),
            practice=_optional_str(payload.get("practice") or payload.get("proposed_change")),
        )

    if tool == "retrieve":
        return local_tools.retrieve_context(
            payload.get("question", ""),
            top_k=int(payload.get("top_k", 5)),
            rag_config=payload.get("rag_config", "configs/rag_governed_runtime_v2.yaml"),
        )

    # Extension path: a new HTTP-bound capability can be added with one ToolSpec
    # and a mapping-returning executor. Existing adapters retain their explicit
    # argument normalization above for backwards compatibility.
    spec = _CAPABILITY_REGISTRY.resolve_surface("http", tool)
    return execute_registered_capability(spec.capability_id, payload)


def _required_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"{key} must be a number")


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"value must be numeric: {value}")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
