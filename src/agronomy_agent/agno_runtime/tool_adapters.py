from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable

from agronomy_agent.local_tools import (
    DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS,
    aafc_annual_crop_inventory,
    aafc_nasdi_agroclimate,
    agronomic_calculator_tool,
    canada_conservation_practice_context_source,
    canada_et_or_water_use_source_needed,
    cansis_soil_landscapes_canada,
    conservation_practice_context_adapter,
    cropland_data_layer_geometry,
    cropland_data_layer_point,
    daymet_single_pixel_daily,
    diagnostic_frame,
    disease_risk_context_adapter,
    epa_ppls_product_search,
    fertility_frame,
    field_record_audit_card,
    forage_livestock_extension_corpus,
    health_canada_pmra_label_search,
    nass_quickstats_crop_stats,
    nasa_power_daily,
    nrcs_soil_survey_geometry,
    nrcs_soil_survey_point,
    openet_point_timeseries,
    partial_budget_calculator,
    postharvest_storage_quality_corpus,
    public_source_lane_card,
    public_program_context_source,
    public_variety_trial_ingest,
    retrieve_context,
    route_question,
    spray_window,
    statcan_field_crop_statistics,
    specialty_crop_extension_corpus,
)
from agronomy_agent.skill_registry import skill_metadata
from agronomy_agent.tools.registry import run_tools


@dataclass(frozen=True)
class AgnoToolAdapter:
    name: str
    skill_id: str
    eval_tags: tuple[str, ...]
    boundary: str
    callable: Callable[..., dict[str, Any]]

    def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        payload = self.callable(*args, **kwargs)
        return {
            **payload,
            "skill_id": payload.get("skill_id") or self.skill_id,
            "boundary": payload.get("boundary") or self.boundary,
            "provenance": payload.get("provenance") or "agronomy_agent.local_tools",
            "eval_tags": list(payload.get("eval_tags") or self.eval_tags),
            "payload_hash": hashlib.sha256(str(payload).encode("utf-8")).hexdigest(),
        }


def load_agno_tool_adapters() -> dict[str, AgnoToolAdapter]:
    adapters = {
        "label_guard": _guard_adapter("label_guard"),
        "weather_guard": _guard_adapter("weather_guard"),
        "fertility_guard": _guard_adapter("fertility_guard"),
        "field_data_guard": _guard_adapter("field_data_guard"),
        "pesticide_safety_guard": _guard_adapter("pesticide_safety_guard"),
        "resistance_management_guard": _guard_adapter("resistance_management_guard"),
        "nutrient_4r_guard": _guard_adapter("nutrient_4r_guard"),
        "salinity_sodicity_guard": _guard_adapter("salinity_sodicity_guard"),
        "soil_structure_guard": _guard_adapter("soil_structure_guard"),
        "route_question": AgnoToolAdapter("route_question", "route_probe_v1", ("router",), "admin_debug_only", route_question),
        "retrieve_context": AgnoToolAdapter("retrieve_context", "retrieve_probe_v1", ("retrieval",), "admin_debug_only", retrieve_context),
        "spray_window": AgnoToolAdapter("spray_window", "spray_window_screen_v1", ("product_stewardship", "weather_guard"), "regulated", spray_window),
        "agronomic_calculator": AgnoToolAdapter(
            "agronomic_calculator",
            "agronomic_calculator_v1",
            ("calculation", "offline", "deterministic"),
            "supplied_inputs_arithmetic_only",
            agronomic_calculator_tool,
        ),
        "nasa_power_daily": AgnoToolAdapter("nasa_power_daily", "nasa_power_daily_v1", ("weather", "public_data"), "public_weather_prior", nasa_power_daily),
        "daymet_single_pixel_daily": AgnoToolAdapter(
            "daymet_single_pixel_daily",
            "daymet_single_pixel_daily_v1",
            ("weather", "climate", "water_window", "public_data", "field_context"),
            "gridded_climate_prior",
            daymet_single_pixel_daily,
        ),
        "openet_point_timeseries": AgnoToolAdapter(
            "openet_point_timeseries",
            "openet_point_timeseries_v1",
            ("evapotranspiration", "irrigation", "water_use", "public_data", "field_context"),
            "satellite_et_prior",
            openet_point_timeseries,
        ),
        "nrcs_soil_survey_point": AgnoToolAdapter(
            "nrcs_soil_survey_point",
            "nrcs_soil_survey_point_v1",
            ("soil_survey", "public_data", "field_context"),
            "soil_survey_prior",
            nrcs_soil_survey_point,
        ),
        "nrcs_soil_survey_geometry": AgnoToolAdapter(
            "nrcs_soil_survey_geometry",
            "nrcs_soil_survey_geometry_v1",
            ("soil_survey", "boundary", "component", "public_data", "field_context"),
            "soil_survey_boundary_prior",
            nrcs_soil_survey_geometry,
        ),
        "cropland_data_layer_point": AgnoToolAdapter(
            "cropland_data_layer_point",
            "cropland_data_layer_point_v1",
            ("crop_history", "land_cover", "public_data", "field_context"),
            "crop_cover_prior",
            cropland_data_layer_point,
        ),
        "cropland_data_layer_geometry": AgnoToolAdapter(
            "cropland_data_layer_geometry",
            "cropland_data_layer_geometry_v1",
            ("crop_history", "land_cover", "boundary", "public_data", "field_context"),
            "crop_cover_boundary_prior",
            cropland_data_layer_geometry,
        ),
        "nass_quickstats_crop_stats": AgnoToolAdapter(
            "nass_quickstats_crop_stats",
            "nass_quickstats_crop_stats_v1",
            ("crop_statistics", "yield_context", "public_data", "field_context"),
            "regional_statistics_prior",
            nass_quickstats_crop_stats,
        ),
        "epa_ppls_product_search": AgnoToolAdapter(
            "epa_ppls_product_search",
            "epa_ppls_product_search_v1",
            ("label", "product_stewardship", "public_data"),
            "label_metadata_boundary",
            epa_ppls_product_search,
        ),
        "cansis_soil_landscapes_canada": AgnoToolAdapter(
            "cansis_soil_landscapes_canada",
            "cansis_soil_landscapes_canada_v1",
            ("soil_survey", "canada", "source_lane", "public_data", "field_context"),
            "canada_soil_source_lane_planned",
            cansis_soil_landscapes_canada,
        ),
        "aafc_annual_crop_inventory": AgnoToolAdapter(
            "aafc_annual_crop_inventory",
            "aafc_annual_crop_inventory_v2",
            ("crop_history", "land_cover", "canada", "source_lane", "public_data", "field_context"),
            "canada_crop_cover_classification_prior",
            aafc_annual_crop_inventory,
        ),
        "statcan_field_crop_statistics": AgnoToolAdapter(
            "statcan_field_crop_statistics",
            "statcan_field_crop_statistics_v2",
            ("crop_statistics", "yield_context", "canada", "source_lane", "public_data", "field_context"),
            "canada_regional_statistics_prior",
            statcan_field_crop_statistics,
        ),
        "health_canada_pmra_label_search": AgnoToolAdapter(
            "health_canada_pmra_label_search",
            "health_canada_pmra_label_search_v2",
            ("label", "product_stewardship", "canada", "source_lane", "public_data"),
            "canada_label_registration_metadata_boundary",
            health_canada_pmra_label_search,
        ),
        "canada_et_or_water_use_source_needed": AgnoToolAdapter(
            "canada_et_or_water_use_source_needed",
            "canada_et_or_water_use_source_needed_v2",
            ("evapotranspiration", "irrigation", "water_use", "canada", "source_lane", "public_data", "field_context"),
            "canada_regional_agroclimate_prior",
            canada_et_or_water_use_source_needed,
        ),
        "aafc_nasdi_agroclimate": AgnoToolAdapter(
            "aafc_nasdi_agroclimate",
            "aafc_nasdi_agroclimate_v1",
            ("drought", "spi", "spei", "agroclimate", "water_use", "canada", "public_data", "field_context"),
            "canada_regional_agroclimate_prior",
            aafc_nasdi_agroclimate,
        ),
        "disease_risk_context_adapter": AgnoToolAdapter(
            "disease_risk_context_adapter",
            "disease_risk_context_adapter_v1",
            ("disease", "fungicide_roi", "weather", "source_lane", "public_data"),
            "disease_risk_source_card",
            disease_risk_context_adapter,
        ),
        "public_variety_trial_ingest": AgnoToolAdapter(
            "public_variety_trial_ingest",
            "public_variety_trial_ingest_v1",
            ("seed_hybrid", "variety_trials", "source_lane", "public_data"),
            "variety_trial_source_card",
            public_variety_trial_ingest,
        ),
        "specialty_crop_extension_corpus": AgnoToolAdapter(
            "specialty_crop_extension_corpus",
            "specialty_crop_extension_corpus_v1",
            ("horticulture", "specialty_crop", "source_lane", "public_data"),
            "specialty_crop_extension_source_card",
            specialty_crop_extension_corpus,
        ),
        "conservation_practice_context_adapter": AgnoToolAdapter(
            "conservation_practice_context_adapter",
            "conservation_practice_context_adapter_v1",
            ("conservation", "nrcs", "source_lane", "public_data", "field_context"),
            "conservation_practice_source_card",
            conservation_practice_context_adapter,
        ),
        "canada_conservation_practice_context_source": AgnoToolAdapter(
            "canada_conservation_practice_context_source",
            "canada_conservation_practice_context_source_v1",
            ("conservation", "canada", "source_lane", "public_data", "field_context"),
            "canada_conservation_source_card",
            canada_conservation_practice_context_source,
        ),
        "field_record_audit_card": AgnoToolAdapter(
            "field_record_audit_card",
            "field_record_audit_card_v1",
            ("field_data", "precision_ag", "audit_trail", "source_lane"),
            "field_record_audit_source_card",
            field_record_audit_card,
        ),
        "partial_budget_calculator": AgnoToolAdapter(
            "partial_budget_calculator",
            "partial_budget_calculator_v1",
            ("farm_economics", "partial_budget", "source_lane", "public_data"),
            "partial_budget_source_card",
            partial_budget_calculator,
        ),
        "public_program_context_source": AgnoToolAdapter(
            "public_program_context_source",
            "public_program_context_source_v1",
            ("public_program", "conservation", "source_lane", "public_data"),
            "public_program_source_card",
            public_program_context_source,
        ),
        "forage_livestock_extension_corpus": AgnoToolAdapter(
            "forage_livestock_extension_corpus",
            "forage_livestock_extension_corpus_v1",
            ("forage", "livestock_safety", "source_lane", "public_data"),
            "forage_livestock_source_card",
            forage_livestock_extension_corpus,
        ),
        "postharvest_storage_quality_corpus": AgnoToolAdapter(
            "postharvest_storage_quality_corpus",
            "postharvest_storage_quality_corpus_v1",
            ("postharvest", "storage_quality", "mycotoxin", "source_lane", "public_data"),
            "postharvest_storage_source_card",
            postharvest_storage_quality_corpus,
        ),
        "fertility_frame": AgnoToolAdapter("fertility_frame", "fertility_frame_v1", ("fertility", "4r"), "decision_support", fertility_frame),
        "diagnostic_frame": AgnoToolAdapter("diagnostic_frame", "diagnostic_frame_v1", ("diagnostic",), "decision_support", diagnostic_frame),
        "guard_notes": AgnoToolAdapter("guard_notes", "agronomy_guard_notes_v1", ("guard",), "deterministic_boundary_notes", _guard_notes),
    }
    for source_lane_id, definition in DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS.items():
        adapters[source_lane_id] = AgnoToolAdapter(
            source_lane_id,
            f"{source_lane_id}_v1",
            ("deep_public_coverage", "source_lane", "public_data", source_lane_id),
            str(definition.get("boundary") or "deep_public_source_lane_card"),
            lambda source_lane_id=source_lane_id, **kwargs: public_source_lane_card(source_lane_id, **kwargs),
        )
    return adapters


def _guard_adapter(tool_name: str) -> AgnoToolAdapter:
    metadata = skill_metadata(tool_name)
    return AgnoToolAdapter(
        tool_name,
        str(metadata["skill_id"]),
        tuple(str(item) for item in metadata["eval_tags"]),
        str(metadata["boundary"]),
        lambda query, _tool_name=tool_name: _guard_tool_payload(_tool_name, query),
    )


def _guard_tool_payload(tool_name: str, query: str) -> dict[str, Any]:
    notes = run_tools(query, (tool_name,))
    metadata = skill_metadata(tool_name)
    if not notes:
        return {
            "tool": tool_name,
            "status": "not_applicable",
            "note": "",
            "skill_id": metadata["skill_id"],
            "provenance": list(metadata["provenance"]),
            "boundary": metadata["boundary"],
            "risk_class": metadata["risk_class"],
            "eval_tags": list(metadata["eval_tags"]),
        }
    note = notes[0]
    return {
        "tool": tool_name,
        "status": "called",
        "note": note.text,
        "skill_id": note.skill_id,
        "provenance": list(note.provenance),
        "boundary": note.boundary,
        "risk_class": note.risk_class,
        "eval_tags": list(note.eval_tags),
    }


def _guard_notes(question: str, required_tools: list[str] | tuple[str, ...]) -> dict[str, Any]:
    notes = run_tools(question, required_tools)
    return {
        "tool": "guard_notes",
        "notes": [
            {
                "name": note.name,
                "text": note.text,
                "skill_id": note.skill_id,
                "provenance": list(note.provenance),
                "boundary": note.boundary,
                "risk_class": note.risk_class,
                "eval_tags": list(note.eval_tags),
            }
            for note in notes
        ],
    }
