#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.parse
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agronomy_agent import local_tools
from agronomy_agent.paths import repo_path


SMOKE_SCHEMA_VERSION = "open_agronomy_agent.public_adapter_regional_matrix.v1"
DEFAULT_OUTPUT = "outputs/tool_smoke/public_adapter_regional_matrix_latest.json"
FIXTURE_NASS_KEY = "fixture-regional-nass-key"
FIXTURE_OPENET_KEY = "fixture-regional-openet-key"

REGIONAL_CONTEXTS: tuple[dict[str, Any], ...] = (
    {
        "context_id": "iowa_des_moines_lobe_corn",
        "label": "Iowa Des Moines Lobe corn field",
        "latitude": 42.03,
        "longitude": -93.62,
        "state_alpha": "IA",
        "crop": "corn",
        "product_term": "glyphosate",
        "openet": False,
    },
    {
        "context_id": "red_river_valley_spring_wheat",
        "label": "Red River Valley spring wheat field",
        "latitude": 47.93,
        "longitude": -97.03,
        "state_alpha": "ND",
        "crop": "wheat",
        "product_term": "glyphosate",
        "openet": False,
    },
    {
        "context_id": "california_central_valley_tomato",
        "label": "California Central Valley irrigated tomato field",
        "latitude": 36.73,
        "longitude": -119.79,
        "state_alpha": "CA",
        "crop": "tomatoes",
        "product_term": "glyphosate",
        "openet": True,
    },
    {
        "context_id": "florida_gulf_coast_potato",
        "label": "Florida Gulf Coast potato field",
        "latitude": 29.42,
        "longitude": -82.17,
        "state_alpha": "FL",
        "crop": "potato",
        "product_term": "glyphosate",
        "openet": False,
    },
    {
        "context_id": "kansas_high_plains_winter_wheat",
        "label": "Kansas High Plains winter wheat field",
        "latitude": 38.87,
        "longitude": -100.85,
        "state_alpha": "KS",
        "crop": "wheat",
        "product_term": "glyphosate",
        "openet": False,
    },
    {
        "context_id": "mississippi_delta_cotton",
        "label": "Mississippi Delta cotton field",
        "latitude": 33.41,
        "longitude": -90.90,
        "state_alpha": "MS",
        "crop": "cotton",
        "product_term": "glyphosate",
        "openet": False,
    },
    {
        "context_id": "ontario_clay_plain_soybean",
        "label": "Ontario Clay Plain soybean field",
        "latitude": 42.98,
        "longitude": -82.35,
        "country": "CA",
        "province": "ON",
        "crop": "soybean",
        "product_term": "glyphosate",
        "pmra_registration_number": "27313",
        "openet": False,
        "canada": True,
    },
    {
        "context_id": "saskatchewan_brown_soil_zone_canola",
        "label": "Saskatchewan Brown Soil Zone canola field",
        "latitude": 51.50,
        "longitude": -106.00,
        "country": "CA",
        "province": "SK",
        "crop": "canola",
        "product_term": "glyphosate",
        "pmra_registration_number": "27313",
        "openet": False,
        "canada": True,
    },
)

BASE_ADAPTERS: tuple[str, ...] = (
    "nrcs_soil_survey_point",
    "nrcs_soil_survey_geometry",
    "nasa_power_daily",
    "daymet_single_pixel_daily",
    "cropland_data_layer_point",
    "cropland_data_layer_geometry",
    "nass_quickstats_crop_stats",
    "epa_ppls_product_search",
)

CANADA_ADAPTERS: tuple[str, ...] = (
    "cansis_soil_landscapes_canada",
    "nasa_power_daily",
    "daymet_single_pixel_daily",
    "canada_et_or_water_use_source_needed",
    "aafc_annual_crop_inventory",
    "statcan_field_crop_statistics",
    "health_canada_pmra_label_search",
)


def run_smoke(
    *,
    live: bool = False,
    output: str | Path = DEFAULT_OUTPUT,
    timeout: int = 12,
    cache_dir: str | Path = "outputs/tool_cache/public_adapter_regional_matrix",
    refresh_cache: bool = True,
) -> dict[str, Any]:
    output_path = repo_path(str(output))
    cache_root = repo_path(str(cache_dir))
    opener = None if live else _offline_urlopen
    if refresh_cache and cache_root.exists():
        shutil.rmtree(cache_root)
    with _patched_urlopen(opener), _offline_key_env(enabled=not live):
        cases = [
            _run_adapter_case(context, adapter_id, timeout=timeout, cache_root=cache_root, live=live)
            for context in REGIONAL_CONTEXTS
            for adapter_id in adapter_ids_for_context(context)
        ]
    failures = [failure for case in cases for failure in case["failures"]]
    adapter_counts: dict[str, int] = {}
    for case in cases:
        adapter_counts[case["adapter_id"]] = adapter_counts.get(case["adapter_id"], 0) + 1
    report = {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "mode": "live" if live else "offline_fixture",
        "context_count": len(REGIONAL_CONTEXTS),
        "adapter_count": len(adapter_counts),
        "case_count": len(cases),
        "passed": not failures,
        "failures": failures,
        "adapter_case_counts": adapter_counts,
        "contexts": [_context_summary(context) for context in REGIONAL_CONTEXTS],
        "cases": cases,
        "boundary": (
            "This matrix smoke checks regional public-adapter contracts across representative field contexts. "
            "Offline mode verifies request wiring, normalization, source-card facts, and boundary language; it does not "
            "prove live provider uptime, credential validity, exhaustive regional coverage, or field-specific truth."
        ),
    }
    _assert_no_fixture_secrets(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def adapter_ids_for_context(context: dict[str, Any]) -> tuple[str, ...]:
    if context.get("canada") or context.get("country") == "CA":
        return CANADA_ADAPTERS
    if context.get("openet"):
        return (*BASE_ADAPTERS, "openet_point_timeseries")
    return BASE_ADAPTERS


_adapter_ids_for_context = adapter_ids_for_context


def _run_adapter_case(
    context: dict[str, Any],
    adapter_id: str,
    *,
    timeout: int,
    cache_root: Path,
    live: bool,
) -> dict[str, Any]:
    case_id = f"{context['context_id']}__{adapter_id}"
    case_cache_dir = cache_root / context["context_id"] / adapter_id
    payload: dict[str, Any]
    try:
        payload = _call_adapter(context, adapter_id, timeout=timeout, cache_dir=str(case_cache_dir))
        failures = _case_failures(case_id, adapter_id, payload, live=live)
    except Exception as exc:  # noqa: BLE001 - smoke report should keep all cases visible.
        payload = {}
        failures = [f"{case_id}: {exc.__class__.__name__}: {str(exc)[:220]}"]
    return {
        "case_id": case_id,
        "context_id": context["context_id"],
        "context_label": context["label"],
        "adapter_id": adapter_id,
        "provider": _provider_for_adapter(adapter_id),
        "status": "pass" if not failures else "fail",
        "payload_status": payload.get("status") or ("available" if payload else "error"),
        "tool": payload.get("tool"),
        "record_count": payload.get("record_count"),
        "source": payload.get("source"),
        "key_facts": _case_key_facts(adapter_id, payload),
        "boundary": payload.get("boundary"),
        "failures": failures,
    }


def _call_adapter(context: dict[str, Any], adapter_id: str, *, timeout: int, cache_dir: str) -> dict[str, Any]:
    latitude = float(context["latitude"])
    longitude = float(context["longitude"])
    if adapter_id == "nrcs_soil_survey_point":
        return local_tools.nrcs_soil_survey_point(latitude, longitude, cache_dir=cache_dir, timeout=timeout)
    if adapter_id == "nrcs_soil_survey_geometry":
        return local_tools.nrcs_soil_survey_geometry(_field_polygon(longitude, latitude), cache_dir=cache_dir, timeout=timeout)
    if adapter_id == "nasa_power_daily":
        return local_tools.nasa_power_daily(latitude, longitude, "20240529", "20240530", cache_dir=cache_dir, timeout=timeout)
    if adapter_id == "daymet_single_pixel_daily":
        return local_tools.daymet_single_pixel_daily(
            latitude,
            longitude,
            "2024-05-29",
            "2024-05-30",
            variables=("tmax", "tmin", "prcp", "dayl"),
            cache_dir=cache_dir,
            timeout=timeout,
        )
    if adapter_id == "cropland_data_layer_point":
        return local_tools.cropland_data_layer_point(latitude, longitude, year=2024, cache_dir=cache_dir, timeout=timeout)
    if adapter_id == "cropland_data_layer_geometry":
        return local_tools.cropland_data_layer_geometry(
            _field_polygon(longitude, latitude),
            years=(2024, 2023),
            sample_points=2,
            cache_dir=cache_dir,
            timeout=timeout,
        )
    if adapter_id == "nass_quickstats_crop_stats":
        return local_tools.nass_quickstats_crop_stats(
            str(context["crop"]),
            str(context["state_alpha"]),
            statistic_categories=local_tools.DEFAULT_QUICKSTATS_CATEGORIES,
            year_ge=2022,
            cache_dir=cache_dir,
            timeout=timeout,
        )
    if adapter_id == "epa_ppls_product_search":
        return local_tools.epa_ppls_product_search(ingredient_name=str(context["product_term"]), cache_dir=cache_dir, timeout=timeout)
    if adapter_id == "openet_point_timeseries":
        return local_tools.openet_point_timeseries(
            latitude,
            longitude,
            "2024-04-01",
            "2024-05-31",
            cache_dir=cache_dir,
            timeout=timeout,
        )
    if adapter_id == "cansis_soil_landscapes_canada":
        return local_tools.cansis_soil_landscapes_canada(
            latitude,
            longitude,
            geometry=_field_polygon(longitude, latitude),
            crop=str(context["crop"]),
            province=str(context.get("province") or ""),
        )
    if adapter_id == "aafc_annual_crop_inventory":
        return local_tools.aafc_annual_crop_inventory(
            latitude,
            longitude,
            geometry=_field_polygon(longitude, latitude),
            crop=str(context["crop"]),
            province=str(context.get("province") or ""),
            sample_points=2,
            cache_dir=cache_dir,
            timeout=timeout,
        )
    if adapter_id == "statcan_field_crop_statistics":
        return local_tools.statcan_field_crop_statistics(
            crop=str(context["crop"]),
            province=str(context.get("province") or ""),
            cache_dir=cache_dir,
            timeout=timeout,
        )
    if adapter_id == "health_canada_pmra_label_search":
        return local_tools.health_canada_pmra_label_search(
            product_term=str(context["product_term"]),
            search_kind="ingredient_name",
            registration_number=str(context["pmra_registration_number"]),
            cache_dir=cache_dir,
            timeout=timeout,
        )
    if adapter_id == "canada_et_or_water_use_source_needed":
        return local_tools.canada_et_or_water_use_source_needed(
            latitude,
            longitude,
            crop=str(context["crop"]),
            province=str(context.get("province") or ""),
            cache_dir=cache_dir,
            timeout=timeout,
        )
    raise ValueError(f"unknown adapter id: {adapter_id}")


def _case_failures(case_id: str, adapter_id: str, payload: dict[str, Any], *, live: bool) -> list[str]:
    failures: list[str] = []
    if payload.get("tool") != adapter_id:
        failures.append(f"{case_id}: wrong tool {payload.get('tool')}")
    if adapter_id == "nrcs_soil_survey_point":
        if not payload.get("map_units"):
            failures.append(f"{case_id}: no NRCS point map units")
        if "soil-survey prior" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing soil-survey boundary")
    elif adapter_id == "nrcs_soil_survey_geometry":
        if int(payload.get("map_unit_count") or 0) < 1 or int(payload.get("component_count") or 0) < 1:
            failures.append(f"{case_id}: no NRCS boundary components")
        if "soil-survey priors" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing boundary/component limitation")
    elif adapter_id == "nasa_power_daily":
        summary = payload.get("parameter_summary") or {}
        if "T2M" not in summary or "PRECTOTCORR" not in summary:
            failures.append(f"{case_id}: NASA POWER weather summary missing required parameters")
        if "not a replacement for field sensors" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing NASA POWER field-sensor boundary")
    elif adapter_id == "daymet_single_pixel_daily":
        summary = payload.get("variable_summary") or {}
        if payload.get("status") != "available" or "prcp" not in summary or "tmax" not in summary:
            failures.append(f"{case_id}: Daymet climate-window summary missing precipitation/temperature")
        if "not a field sensor" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing Daymet boundary")
    elif adapter_id == "cropland_data_layer_point":
        if not payload.get("cdl_label"):
            failures.append(f"{case_id}: CDL point label missing")
        if "not a grower planting record" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing CDL point boundary")
    elif adapter_id == "cropland_data_layer_geometry":
        if payload.get("status") != "available" or not payload.get("year_summary"):
            failures.append(f"{case_id}: CDL boundary year summary missing")
        if "not acreage accounting" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing CDL boundary limitation")
    elif adapter_id == "nass_quickstats_crop_stats":
        if payload.get("status") == "not_configured" and live:
            failures.append(f"{case_id}: live Quick Stats credential is not configured")
        elif payload.get("status") != "available":
            failures.append(f"{case_id}: NASS Quick Stats rows unavailable")
        latest = payload.get("latest_by_statistic") or {}
        for statistic in local_tools.DEFAULT_QUICKSTATS_CATEGORIES:
            if statistic not in latest:
                failures.append(f"{case_id}: missing Quick Stats {statistic} row")
        if "field-specific yield guarantee" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing Quick Stats field-specific boundary")
    elif adapter_id == "epa_ppls_product_search":
        if int(payload.get("result_count") or 0) < 1 or not payload.get("top_candidate"):
            failures.append(f"{case_id}: PPLS product candidate missing")
        if payload.get("needs_product_disambiguation") is not True:
            failures.append(f"{case_id}: PPLS ingredient search should require product disambiguation")
        if "legal label interpretation" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing PPLS label boundary")
    elif adapter_id == "openet_point_timeseries":
        if payload.get("status") == "not_configured" and live:
            failures.append(f"{case_id}: live OpenET credential is not configured")
        elif payload.get("status") != "available":
            failures.append(f"{case_id}: OpenET rows unavailable")
        summary = payload.get("timeseries_summary") or {}
        if not summary.get("sum"):
            failures.append(f"{case_id}: OpenET ET summary missing")
        if "irrigation prescription" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing OpenET irrigation boundary")
    elif adapter_id == "health_canada_pmra_label_search":
        if payload.get("status") != "available":
            failures.append(f"{case_id}: PMRA registry metadata was unavailable")
        if not payload.get("registration_number") or int(payload.get("product_record_count") or 0) < 1:
            failures.append(f"{case_id}: PMRA registration or product record missing")
        if int(payload.get("label_record_count") or 0) < 1:
            failures.append(f"{case_id}: PMRA label record missing")
        if "not legal label interpretation" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing PMRA label boundary")
    elif adapter_id == "aafc_annual_crop_inventory":
        summary = payload.get("class_summary") or {}
        dominant = summary.get("dominant_class") or {}
        if payload.get("status") not in {"available", "partial_available"} or not dominant.get("aci_label"):
            failures.append(f"{case_id}: AAFC Annual Crop Inventory class sample missing")
        if "not a grower planting record" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing AAFC crop-cover boundary")
    elif adapter_id == "statcan_field_crop_statistics":
        production = ((payload.get("statistics") or {}).get("production_metric_tonnes") or {}).get("latest") or {}
        if payload.get("status") != "available" or production.get("value") is None:
            failures.append(f"{case_id}: Statistics Canada regional production record missing")
        if "not field-specific yield prediction" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing Statistics Canada regional-statistics boundary")
    elif adapter_id == "cansis_soil_landscapes_canada":
        if payload.get("status") != "available" or not payload.get("landscapes"):
            failures.append(f"{case_id}: CanSIS soil landscape record missing")
        if "not replace a field soil test" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing CanSIS field-truth boundary")
    elif adapter_id in CANADA_ADAPTERS:
        if adapter_id == "canada_et_or_water_use_source_needed":
            if payload.get("status") not in {"available", "partial_available"}:
                failures.append(f"{case_id}: AAFC NASDI live regional context unavailable")
            summary = payload.get("indicator_summary") or {}
            if not all(indicator in summary for indicator in local_tools.AAFC_NASDI_INDICATORS):
                failures.append(f"{case_id}: AAFC NASDI indicator summary incomplete")
            if not payload.get("observation_end") or not payload.get("time_window"):
                failures.append(f"{case_id}: AAFC NASDI date/window lineage missing")
            if not all(item.get("object_id") and item.get("catalog_name") for item in payload.get("observations") or []):
                failures.append(f"{case_id}: AAFC NASDI locked-raster lineage missing")
            boundary = str(payload.get("boundary") or "")
            if "not field-intersected ET" not in boundary or "not" not in boundary or "prescription" not in boundary:
                failures.append(f"{case_id}: missing AAFC NASDI non-prescriptive boundary")
        else:
            if payload.get("status") != "canada_source_lane_planned":
                failures.append(f"{case_id}: Canada source-lane planned status missing")
            if "currently identifies the source lane only" not in str(payload.get("boundary") or ""):
                failures.append(f"{case_id}: missing Canada planned source-lane boundary")
        if payload.get("source_lane_id") != adapter_id:
            failures.append(f"{case_id}: Canada source_lane_id mismatch")
        if not payload.get("provider") or not payload.get("coverage"):
            failures.append(f"{case_id}: Canada source-lane provider/coverage missing")
        if not payload.get("decision_checks"):
            failures.append(f"{case_id}: Canada source-lane decision checks missing")
    return failures


def _case_key_facts(adapter_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if adapter_id == "nrcs_soil_survey_point":
        return {"map_units": (payload.get("map_units") or [])[:2]}
    if adapter_id == "nrcs_soil_survey_geometry":
        return {
            "map_unit_count": payload.get("map_unit_count"),
            "component_count": payload.get("component_count"),
            "component_summary": payload.get("component_summary") or {},
        }
    if adapter_id == "nasa_power_daily":
        return {"parameter_summary": payload.get("parameter_summary") or {}}
    if adapter_id == "daymet_single_pixel_daily":
        return {"record_count": payload.get("record_count"), "variable_summary": payload.get("variable_summary") or {}}
    if adapter_id == "cropland_data_layer_point":
        return {"year": payload.get("year"), "cdl_code": payload.get("cdl_code"), "cdl_label": payload.get("cdl_label")}
    if adapter_id == "cropland_data_layer_geometry":
        return {"year_summary": payload.get("year_summary") or {}, "sample_point_count": payload.get("sample_point_count")}
    if adapter_id == "nass_quickstats_crop_stats":
        return {
            "crop": payload.get("crop"),
            "state_alpha": payload.get("state_alpha"),
            "record_count": payload.get("record_count"),
            "latest_by_statistic": payload.get("latest_by_statistic") or {},
        }
    if adapter_id == "epa_ppls_product_search":
        return {
            "result_count": payload.get("result_count"),
            "current_product_count": payload.get("current_product_count"),
            "inactive_product_count": payload.get("inactive_product_count"),
            "needs_product_disambiguation": payload.get("needs_product_disambiguation"),
            "top_candidate": payload.get("top_candidate") or {},
        }
    if adapter_id == "openet_point_timeseries":
        return {"record_count": payload.get("record_count"), "timeseries_summary": payload.get("timeseries_summary") or {}}
    if adapter_id == "health_canada_pmra_label_search":
        return {
            "registration_number": payload.get("registration_number"),
            "product_record_count": payload.get("product_record_count"),
            "label_record_count": payload.get("label_record_count"),
            "products": (payload.get("products") or [])[:2],
        }
    if adapter_id == "aafc_annual_crop_inventory":
        return {
            "year": payload.get("year"),
            "sample_point_count": payload.get("sample_point_count"),
            "class_summary": payload.get("class_summary") or {},
        }
    if adapter_id == "statcan_field_crop_statistics":
        return {
            "crop": payload.get("crop"),
            "geography": payload.get("geography"),
            "statistics": payload.get("statistics") or {},
        }
    if adapter_id == "cansis_soil_landscapes_canada":
        return {"landscape_count": payload.get("landscape_count"), "landscapes": (payload.get("landscapes") or [])[:2]}
    if adapter_id == "canada_et_or_water_use_source_needed":
        return {
            "canonical_tool": payload.get("canonical_tool"),
            "time_window": payload.get("time_window"),
            "observation_end": payload.get("observation_end"),
            "freshness_status": payload.get("freshness_status"),
            "indicator_summary": payload.get("indicator_summary") or {},
            "observations": (payload.get("observations") or [])[:4],
            "decision_checks": (payload.get("decision_checks") or [])[:4],
        }
    if adapter_id in CANADA_ADAPTERS:
        return {
            "source_lane_id": payload.get("source_lane_id"),
            "source_name": payload.get("source_name"),
            "provider": payload.get("provider"),
            "coverage": payload.get("coverage"),
            "context": payload.get("context") or {},
            "location": payload.get("location") or {},
            "decision_checks": (payload.get("decision_checks") or [])[:4],
        }
    return {}


def _provider_for_adapter(adapter_id: str) -> str:
    if adapter_id in local_tools.CANADA_SOURCE_LANE_DEFINITIONS:
        return str(local_tools.CANADA_SOURCE_LANE_DEFINITIONS[adapter_id]["provider"])
    return {
        "nrcs_soil_survey_point": "USDA NRCS",
        "nrcs_soil_survey_geometry": "USDA NRCS",
        "nasa_power_daily": "NASA POWER",
        "daymet_single_pixel_daily": "ORNL Daymet",
        "cropland_data_layer_point": "USDA NASS",
        "cropland_data_layer_geometry": "USDA NASS",
        "nass_quickstats_crop_stats": "USDA NASS",
        "epa_ppls_product_search": "EPA",
        "openet_point_timeseries": "OpenET",
    }.get(adapter_id, "public source")


def _context_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_id": context["context_id"],
        "label": context["label"],
        "latitude": context["latitude"],
        "longitude": context["longitude"],
        "country": context.get("country") or "US",
        "state_alpha": context.get("state_alpha"),
        "province": context.get("province"),
        "crop": context["crop"],
        "openet_expected": bool(context.get("openet")),
        "canada_source_lanes_expected": bool(context.get("canada") or context.get("country") == "CA"),
    }


def _field_polygon(longitude: float, latitude: float, delta: float = 0.01) -> dict[str, Any]:
    west = longitude - delta
    east = longitude + delta
    south = latitude - delta
    north = latitude + delta
    return {
        "type": "Polygon",
        "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
    }


@contextmanager
def _offline_key_env(*, enabled: bool):
    if not enabled:
        yield
        return
    updates = {
        local_tools.NASS_QUICKSTATS_ENV_VARS[0]: FIXTURE_NASS_KEY,
        local_tools.OPENET_ENV_VARS[0]: FIXTURE_OPENET_KEY,
    }
    with _patched_env(clear=(*local_tools.NASS_QUICKSTATS_ENV_VARS, *local_tools.OPENET_ENV_VARS), updates=updates):
        yield


@contextmanager
def _patched_env(*, clear: Iterable[str], updates: dict[str, str]):
    original = {key: os.environ.get(key) for key in clear}
    for key in clear:
        os.environ.pop(key, None)
    os.environ.update(updates)
    try:
        yield
    finally:
        for key in updates:
            os.environ.pop(key, None)
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _patched_urlopen(opener: Callable[..., Any] | None):
    if opener is None:
        yield
        return
    original = local_tools.urllib.request.urlopen
    local_tools.urllib.request.urlopen = opener
    try:
        yield
    finally:
        local_tools.urllib.request.urlopen = original


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


def _offline_urlopen(request: Any, timeout: int = 12) -> _FakeResponse:  # noqa: ARG001
    url = str(getattr(request, "full_url", request))
    decoded_url = urllib.parse.unquote(url)
    if "SDMDataAccess" in url:
        request_body = urllib.parse.unquote_plus((getattr(request, "data", b"") or b"").decode("utf-8", errors="replace"))
        if "component AS co" in request_body:
            return _FakeResponse(_nrcs_component_fixture())
        return _FakeResponse(_nrcs_point_fixture())
    if "power.larc.nasa.gov/api/temporal/daily/point" in url:
        return _FakeResponse(_nasa_power_fixture())
    if local_tools.DAYMET_SINGLE_PIXEL_API_URL in url:
        return _FakeResponse(_daymet_csv_fixture())
    if local_tools.CROPSCAPE_CDL_VALUE_URL in url:
        return _FakeResponse(_cdl_fixture(decoded_url))
    if url.startswith(local_tools.NASS_QUICKSTATS_API_URL):
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        return _FakeResponse(_quickstats_fixture(query))
    if url == local_tools.OPENET_RASTER_TIMESERIES_POINT_URL:
        return _FakeResponse(_openet_fixture())
    if "ordspub.epa.gov/ords/pesticides/cswu/ProductSearch" in url:
        return _FakeResponse(_ppls_fixture(decoded_url))
    if url.startswith(local_tools.PMRA_PPID_EXTRACT_BASE_URL):
        return _FakeResponse(_pmra_fixture(url))
    if "/annual_crop_inventory/" in url and "/ImageServer/identify" in url:
        return _FakeResponse(_aafc_aci_fixture(decoded_url))
    if "/rest/services/nasdi/" in url and "/ImageServer/query" in url:
        return _FakeResponse(_aafc_nasdi_catalog_fixture(url))
    if "/rest/services/nasdi/" in url and "/ImageServer/identify" in url:
        return _FakeResponse(_aafc_nasdi_identify_fixture(url))
    if "/Soil_landscapes_of_Canada/FeatureServer/0/query" in url:
        return _FakeResponse({"features": [{"attributes": {"SLC_V31_22_ID": "SLC-SMOKE", "DRAINAGE_CODE": "W", "KIND_MATERIAL_CODE": "L", "LOCAL_SURFACE_FORM_CODE": "R", "SOIL_ORDER_CODE": "Chernozemic", "SOIL_GREAT_GROUP_CODE": "Brown"}}]})
    if url == f"{local_tools.STATCAN_WDS_BASE_URL}/getDataFromCubePidCoordAndLatestNPeriods":
        return _FakeResponse(_statcan_fixture(getattr(request, "data", b"")))
    raise RuntimeError(f"unexpected offline regional smoke URL: {url}")


def _nrcs_point_fixture() -> dict[str, list[dict[str, str]]]:
    return {"Table": [{"mukey": "123", "musym": "A1", "muname": "Representative loam complex", "areasymbol": "SMOKE"}]}


def _nrcs_component_fixture() -> dict[str, list[dict[str, Any]]]:
    return {
        "Table": [
            {
                "mukey": "123",
                "musym": "A1",
                "muname": "Representative loam complex",
                "areasymbol": "SMOKE",
                "cokey": "456",
                "compname": "Representative",
                "comppct_r": 78,
                "majcompflag": "Yes",
                "slope_r": 3,
                "drainagecl": "Well drained",
                "hydgrp": "B",
                "hydricrating": "No",
                "taxorder": "Mollisols",
                "taxsubgrp": "Typic Hapludolls",
            }
        ]
    }


def _nasa_power_fixture() -> dict[str, Any]:
    values = {
        "T2M": {"20240529": 21.0, "20240530": 23.5},
        "T2M_MIN": {"20240529": 12.0, "20240530": 13.5},
        "T2M_MAX": {"20240529": 29.0, "20240530": 31.0},
        "PRECTOTCORR": {"20240529": 2.4, "20240530": 0.0},
        "WS2M": {"20240529": 3.2, "20240530": 4.1},
        "RH2M": {"20240529": 74.0, "20240530": 68.0},
    }
    return {"properties": {"parameter": values}}


def _daymet_csv_fixture() -> str:
    return "\n".join(
        [
            "Latitude,42.03",
            "Longitude,-93.62",
            "year,yday,tmax (deg c),tmin (deg c),prcp (mm/day),dayl (s)",
            "2024,150,24.5,12.0,2.0,52000",
            "2024,151,26.5,13.0,0.0,52100",
        ]
    )


def _cdl_fixture(decoded_url: str) -> str:
    if "year=2023" in decoded_url:
        return "5: Soybeans"
    return "1: Corn"


def _aafc_aci_fixture(decoded_url: str) -> dict[str, Any]:
    if "-106.0" in decoded_url or "-106%2E" in decoded_url:
        value = "153"
    else:
        value = "158"
    return {"objectId": 0, "name": "Pixel", "value": value, "properties": None}


def _aafc_nasdi_catalog_fixture(url: str) -> dict[str, Any]:
    service = url.split("/rest/services/nasdi/", 1)[1].split("/", 1)[0]
    object_id = {
        "standardized_precipitation_index": 4760,
        "standardized_precipitation_evapotranspiration_index": 5760,
        "difference_from_normal_temperature": 6760,
        "percent_of_average_precipitation": 7760,
    }[service]
    return {
        "features": [
            {"attributes": {"OBJECTID": object_id - 1, "Name": f"nasdi_{service}_004w_2026W28", "dateEnd": 1783857600000, "tType": "004w"}},
            {"attributes": {"OBJECTID": object_id, "Name": f"nasdi_{service}_013w_2026W28", "dateEnd": 1783857600000, "tType": "013w"}},
        ]
    }


def _aafc_nasdi_identify_fixture(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    mosaic_rule = json.loads(query["mosaicRule"][0])
    object_id = int(mosaic_rule["lockRasterIds"][0])
    values = {4760: 0.43, 5760: -0.21, 6759: 1.8, 6760: 1.8, 7760: 0.82}
    return {"objectId": object_id, "name": f"locked_{object_id}", "value": str(values[object_id])}


def _statcan_fixture(raw_request: bytes) -> list[dict[str, Any]]:
    requests = json.loads(raw_request.decode("utf-8"))
    values = [102_000.0, 95_000.0, 2_450.0, 233_000.0]
    return [
        {
            "status": "SUCCESS",
            "object": {
                "vectorId": 9000 + index,
                "vectorDataPoint": [
                    {"refPerRaw": "2025-01-01", "value": value - 1, "statusCode": 0, "symbolCode": 0, "scalarFactorCode": 0, "releaseTime": "2026-06-30T08:30"},
                    {"refPerRaw": "2026-01-01", "value": value, "statusCode": 0, "symbolCode": 0, "scalarFactorCode": 0, "releaseTime": "2026-06-30T08:30"},
                ],
            },
        }
        for index, _ in enumerate(requests)
        for value in [values[index % len(values)]]
    ]


def _quickstats_fixture(query: dict[str, list[str]]) -> dict[str, list[dict[str, str]]]:
    statistic = (query.get("statisticcat_desc") or ["YIELD"])[0].upper()
    crop = (query.get("commodity_desc") or ["CORN"])[0].upper()
    state = (query.get("state_alpha") or ["IA"])[0].upper()
    values = {
        "YIELD": {
            "short_desc": f"{crop} - YIELD, MEASURED IN BU / ACRE",
            "unit_desc": "BU / ACRE",
            "Value": "201.0",
        },
        "AREA HARVESTED": {
            "short_desc": f"{crop} - ACRES HARVESTED",
            "unit_desc": "ACRES",
            "Value": "123,000",
        },
        "PRODUCTION": {
            "short_desc": f"{crop} - PRODUCTION",
            "unit_desc": "UNITS",
            "Value": "24,723,000",
        },
    }
    return {
        "data": [
            {
                "year": "2024",
                "statisticcat_desc": statistic,
                "agg_level_desc": "STATE",
                "state_alpha": state,
                "source_desc": "SURVEY",
                "reference_period_desc": "YEAR",
                **values.get(statistic, values["YIELD"]),
            }
        ]
    }


def _openet_fixture() -> dict[str, Any]:
    return {"data": [{"date": "2024-04-01", "et": 112.4, "units": "mm"}, {"date": "2024-05-01", "et": 146.6, "units": "mm"}]}


def _ppls_fixture(decoded_url: str) -> dict[str, Any]:
    if "searchWithRegNo" in decoded_url:
        return {"items": [_active_product("123-45", "Example Herbicide")]}
    return {"items": [_cancelled_product("999-00", "Old Example Herbicide"), _active_product("123-45", "Example Herbicide")]}


def _pmra_fixture(url: str) -> str:
    if "/label/" in url:
        return "Registration number,Registrant name,Product name,Registration Status\n27313,Fixture Registrant,Fixture PMRA Product,Full Registration\n"
    return (
        "Registration number,Product name - English,Product name - French,Registration Status,Expiry date,Marketing type,Date first registered,Exclusive period start date,Active ingredients - English,Active ingredients - French,Product Type,Registrant name,Use Site Category,Sites of Use,Pests,Current / Historical\n"
        "27313,Fixture PMRA Product,Produit PMRA fictif,Full Registration,2027-12-31,COMMERCIAL,2003-01-20,1973-07-01,Fixture ingredient,,HERBICIDE,Fixture Registrant,AGRICULTURAL,CORN,WEEDS,Current\n"
    )


def _active_product(reg_no: str, name: str) -> dict[str, str]:
    return {
        "eparegnumber": reg_no,
        "productname": name,
        "registrationstatus": "Active",
        "productstatusdate": "July 1, 2026",
        "ingredientname": "Glyphosate",
        "PDFFILES": f"https://example.test/labels/{reg_no}.pdf",
    }


def _cancelled_product(reg_no: str, name: str) -> dict[str, str]:
    return {
        "eparegnumber": reg_no,
        "productname": name,
        "registrationstatus": "Cancelled",
        "productstatusdate": "January 1, 2020",
        "ingredientname": "Glyphosate",
    }


def _assert_no_fixture_secrets(report: dict[str, Any]) -> None:
    serialized = json.dumps(report)
    leaked = [secret for secret in (FIXTURE_NASS_KEY, FIXTURE_OPENET_KEY) if secret in serialized]
    if leaked:
        raise AssertionError("fixture credential leaked into regional smoke report")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test public adapters across representative regional field contexts.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--cache-dir", default="outputs/tool_cache/public_adapter_regional_matrix")
    parser.add_argument("--live", action="store_true", help="Call live provider APIs instead of offline fixtures.")
    parser.add_argument("--no-refresh-cache", action="store_true", help="Reuse existing smoke cache entries instead of refreshing.")
    args = parser.parse_args()
    report = run_smoke(
        live=args.live,
        output=args.output,
        timeout=args.timeout,
        cache_dir=args.cache_dir,
        refresh_cache=not args.no_refresh_cache,
    )
    print(json.dumps({"output": str(repo_path(args.output)), "passed": report["passed"], "failures": report["failures"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
