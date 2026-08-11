from __future__ import annotations

import json

from agronomy_agent.agno_runtime.tool_adapters import load_agno_tool_adapters
from agronomy_agent import local_tools
from agronomy_agent.server.services import tool_service


def test_tool_service_exposes_structured_agronomic_calculator() -> None:
    payload = tool_service.run_local_tool(
        "agronomic-calculator",
        {
            "operation": "fertilizer_product_mass",
            "inputs": {
                "nutrient_target_kg_per_ha": 80,
                "nutrient_percent": 46,
                "nutrient_label": "N",
            },
        },
        network_mode="offline",
    )

    assert payload["status"] == "calculated"
    assert payload["operation"] == "fertilizer_product_mass"
    assert payload["unit"] == "kg product/ha"
    assert payload["value"] == 173.91304347826087
    assert "does not choose an agronomic target" in payload["boundary"]


def test_tool_service_calculator_rejects_unstructured_text() -> None:
    try:
        tool_service.run_local_tool(
            "agronomic-calculator",
            {"question": "How much urea for 80 kilograms of nitrogen?"},
            network_mode="offline",
        )
    except ValueError as exc:
        assert str(exc) == "agronomic-calculator requires operation"
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("calculator accepted an unstructured prompt")


def test_tool_service_exposes_nrcs_soil_survey(monkeypatch, tmp_path) -> None:
    def fake_nrcs_soil_survey_point(**kwargs):  # noqa: ANN001
        return {"tool": "nrcs_soil_survey_point", "latitude": kwargs["latitude"], "longitude": kwargs["longitude"]}

    monkeypatch.setattr(tool_service.local_tools, "nrcs_soil_survey_point", fake_nrcs_soil_survey_point)

    payload = tool_service.run_local_tool(
        "nrcs-soil-survey",
        {"lat": 42.1, "lon": -93.5, "cache_dir": str(tmp_path / "nrcs")},
    )

    assert payload["tool"] == "nrcs_soil_survey_point"
    assert payload["latitude"] == 42.1
    assert payload["longitude"] == -93.5


def test_tool_service_exposes_nrcs_soil_survey_geometry(monkeypatch, tmp_path) -> None:
    def fake_nrcs_soil_survey_geometry(**kwargs):  # noqa: ANN001
        return {
            "tool": "nrcs_soil_survey_geometry",
            "geometry_type": kwargs["geometry"]["type"],
            "max_map_units": kwargs["max_map_units"],
            "max_components": kwargs["max_components"],
        }

    monkeypatch.setattr(tool_service.local_tools, "nrcs_soil_survey_geometry", fake_nrcs_soil_survey_geometry)

    payload = tool_service.run_local_tool(
        "nrcs-soil-survey-geometry",
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-93.72, 42.02], [-93.71, 42.02], [-93.71, 42.03], [-93.72, 42.03], [-93.72, 42.02]]],
            },
            "max_map_units": 5,
            "max_components": 10,
            "cache_dir": str(tmp_path / "nrcs"),
        },
    )

    assert payload["tool"] == "nrcs_soil_survey_geometry"
    assert payload["geometry_type"] == "Polygon"
    assert payload["max_map_units"] == 5
    assert payload["max_components"] == 10


def test_tool_service_exposes_cropland_data_layer(monkeypatch, tmp_path) -> None:
    def fake_cropland_data_layer_point(**kwargs):  # noqa: ANN001
        return {
            "tool": "cropland_data_layer_point",
            "latitude": kwargs["latitude"],
            "longitude": kwargs["longitude"],
            "year": kwargs["year"],
        }

    monkeypatch.setattr(tool_service.local_tools, "cropland_data_layer_point", fake_cropland_data_layer_point)

    payload = tool_service.run_local_tool(
        "cropland-data-layer",
        {"lat": 42.1, "lon": -93.5, "year": 2024, "cache_dir": str(tmp_path / "cdl")},
    )

    assert payload["tool"] == "cropland_data_layer_point"
    assert payload["year"] == 2024


def test_tool_service_exposes_cropland_data_layer_geometry(monkeypatch, tmp_path) -> None:
    def fake_cropland_data_layer_geometry(**kwargs):  # noqa: ANN001
        return {
            "tool": "cropland_data_layer_geometry",
            "geometry_type": kwargs["geometry"]["type"],
            "years": kwargs["years"],
            "sample_points": kwargs["sample_points"],
        }

    monkeypatch.setattr(tool_service.local_tools, "cropland_data_layer_geometry", fake_cropland_data_layer_geometry)

    payload = tool_service.run_local_tool(
        "cropland-data-layer-geometry",
        {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-93.72, 42.02], [-93.71, 42.02], [-93.71, 42.03], [-93.72, 42.03], [-93.72, 42.02]]],
            },
            "years": "2024,2023",
            "sample_points": 3,
            "cache_dir": str(tmp_path / "cdl"),
        },
    )

    assert payload["tool"] == "cropland_data_layer_geometry"
    assert payload["geometry_type"] == "Polygon"
    assert payload["years"] == (2024, 2023)
    assert payload["sample_points"] == 3


def test_tool_service_exposes_daymet_single_pixel(monkeypatch, tmp_path) -> None:
    def fake_daymet_single_pixel_daily(**kwargs):  # noqa: ANN001
        return {
            "tool": "daymet_single_pixel_daily",
            "latitude": kwargs["latitude"],
            "longitude": kwargs["longitude"],
            "start": kwargs["start"],
            "end": kwargs["end"],
        }

    monkeypatch.setattr(tool_service.local_tools, "daymet_single_pixel_daily", fake_daymet_single_pixel_daily)

    payload = tool_service.run_local_tool(
        "daymet-single-pixel",
        {"lat": 42.1, "lon": -93.5, "start": "2024-05-01", "end": "2024-05-15", "cache_dir": str(tmp_path / "daymet")},
    )

    assert payload["tool"] == "daymet_single_pixel_daily"
    assert payload["start"] == "2024-05-01"
    assert payload["end"] == "2024-05-15"


def test_tool_service_exposes_openet_point_timeseries(monkeypatch, tmp_path) -> None:
    def fake_openet_point_timeseries(**kwargs):  # noqa: ANN001
        return {
            "tool": "openet_point_timeseries",
            "latitude": kwargs["latitude"],
            "longitude": kwargs["longitude"],
            "start": kwargs["start"],
            "end": kwargs["end"],
            "interval": kwargs["interval"],
        }

    monkeypatch.setattr(tool_service.local_tools, "openet_point_timeseries", fake_openet_point_timeseries)

    payload = tool_service.run_local_tool(
        "openet-point-timeseries",
        {"lat": 36.73, "lon": -119.79, "start": "2024-04-01", "end": "2024-09-30", "cache_dir": str(tmp_path / "openet")},
    )

    assert payload["tool"] == "openet_point_timeseries"
    assert payload["latitude"] == 36.73
    assert payload["longitude"] == -119.79
    assert payload["interval"] == "monthly"


def test_tool_service_exposes_nass_quickstats_crop_stats(monkeypatch, tmp_path) -> None:
    def fake_nass_quickstats_crop_stats(**kwargs):  # noqa: ANN001
        return {
            "tool": "nass_quickstats_crop_stats",
            "crop": kwargs["crop"],
            "state_alpha": kwargs["state_alpha"],
            "county_name": kwargs["county_name"],
        }

    monkeypatch.setattr(tool_service.local_tools, "nass_quickstats_crop_stats", fake_nass_quickstats_crop_stats)

    payload = tool_service.run_local_tool(
        "nass-quickstats-crop-stats",
        {"crop": "corn", "state_alpha": "IA", "county_name": "Story", "cache_dir": str(tmp_path / "quickstats")},
    )

    assert payload["tool"] == "nass_quickstats_crop_stats"
    assert payload["crop"] == "corn"
    assert payload["state_alpha"] == "IA"
    assert payload["county_name"] == "Story"


def test_tool_service_exposes_epa_ppls_product_search(monkeypatch, tmp_path) -> None:
    def fake_epa_ppls_product_search(**kwargs):  # noqa: ANN001
        return {"tool": "epa_ppls_product_search", "search": kwargs["product_name"]}

    monkeypatch.setattr(tool_service.local_tools, "epa_ppls_product_search", fake_epa_ppls_product_search)

    payload = tool_service.run_local_tool(
        "epa-ppls-product-search",
        {"product_name": "Example", "cache_dir": str(tmp_path / "ppls")},
    )

    assert payload["tool"] == "epa_ppls_product_search"
    assert payload["search"] == "Example"


def test_container_runtime_redirects_default_public_tool_cache_to_state(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_nasdi(**kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return {"tool": "aafc_nasdi_agroclimate", "status": "available"}

    monkeypatch.setattr(tool_service.local_tools, "aafc_nasdi_agroclimate", fake_nasdi)
    monkeypatch.setenv("AGRONOMY_AGENT_TOOL_CACHE_ROOT", str(tmp_path / "public-tools"))

    payload = tool_service.run_local_tool(
        "aafc-nasdi-agroclimate",
        {"lat": 49.05, "lon": -122.30, "province": "British Columbia"},
    )

    assert payload["status"] == "available"
    assert captured["cache_dir"] == str(tmp_path / "public-tools" / "aafc_nasdi_agroclimate")


def test_tool_service_exposes_canadian_source_lane_tools(monkeypatch) -> None:
    monkeypatch.setattr(tool_service.local_tools, "cansis_soil_landscapes_canada", lambda **_: {"tool": "cansis_soil_landscapes_canada", "status": "available", "decision_checks": ["avoid substituting USDA NRCS"], "provenance": "aafc_soil_landscapes_of_canada_feature_service"})
    monkeypatch.setattr(
        tool_service.local_tools,
        "aafc_annual_crop_inventory",
        lambda **_: {
            "tool": "aafc_annual_crop_inventory",
            "status": "available",
            "source_lane_id": "aafc_annual_crop_inventory",
            "source_name": "AAFC Annual Crop Inventory",
            "decision_checks": ["use AAFC Annual Crop Inventory for Canadian crop-cover priors instead of USDA CDL"],
            "class_summary": {"dominant_class": {"aci_label": "Canola/rapeseed"}},
            "boundary": "AAFC crop-cover is not a grower planting record.",
        },
    )
    monkeypatch.setattr(
        tool_service.local_tools,
        "statcan_field_crop_statistics",
        lambda **_: {"tool": "statcan_field_crop_statistics", "status": "available", "geography": "Saskatchewan", "statistics": {"production_metric_tonnes": {"latest": {"value": 100}}}},
    )
    monkeypatch.setattr(
        tool_service.local_tools,
        "canada_et_or_water_use_source_needed",
        lambda **_: {
            "tool": "canada_et_or_water_use_source_needed",
            "canonical_tool": "aafc_nasdi_agroclimate",
            "status": "available",
            "source_lane_id": "canada_et_or_water_use_source_needed",
            "decision_checks": ["do not convert a NASDI anomaly value into a prescription"],
            "indicator_summary": {"spi": {"value": 0.43, "units": "standardized anomaly"}},
        },
    )
    soil = tool_service.run_local_tool(
        "cansis-soil-landscapes-canada",
        {"lat": 51.5, "lon": -106.0, "crop": "canola", "province": "SK"},
    )
    crop_cover = tool_service.run_local_tool(
        "aafc-annual-crop-inventory",
        {"lat": 51.5, "lon": -106.0, "crop": "canola", "province": "SK"},
    )
    stats = tool_service.run_local_tool(
        "statcan-field-crop-statistics",
        {"crop": "canola", "province": "SK"},
    )
    label = tool_service.run_local_tool(
        "health-canada-pmra-label-search",
        {"product_term": "glyphosate", "search_kind": "ingredient_name"},
    )
    water = tool_service.run_local_tool(
        "canada-et-or-water-use-source-needed",
        {"lat": 51.5, "lon": -106.0, "crop": "canola", "province": "SK"},
    )

    assert soil["tool"] == "cansis_soil_landscapes_canada"
    assert soil["status"] == "available"
    assert "avoid substituting USDA NRCS" in " ".join(soil["decision_checks"])
    assert soil["provenance"] == "aafc_soil_landscapes_of_canada_feature_service"
    assert crop_cover["source_lane_id"] == "aafc_annual_crop_inventory"
    assert crop_cover["status"] == "available"
    assert crop_cover["class_summary"]["dominant_class"]["aci_label"] == "Canola/rapeseed"
    assert "USDA CDL" in " ".join(crop_cover["decision_checks"])
    assert stats["status"] == "available"
    assert stats["geography"] == "Saskatchewan"
    assert label["source_lane_id"] == "health_canada_pmra_label_search"
    assert label["status"] == "registration_number_required"
    assert "EPA PPLS" in " ".join(label["decision_checks"])
    assert water["status"] == "available"
    assert water["canonical_tool"] == "aafc_nasdi_agroclimate"
    assert water["indicator_summary"]["spi"]["value"] == 0.43


def test_tool_service_passes_exact_pmra_registration_number(monkeypatch, tmp_path) -> None:
    def fake_pmra(**kwargs):  # noqa: ANN001
        return {
            "tool": "health_canada_pmra_label_search",
            "status": "available",
            "registration_number": kwargs["registration_number"],
            "language": kwargs["language"],
            "cache_dir": kwargs["cache_dir"],
            "cache_max_age_hours": kwargs["cache_max_age_hours"],
        }

    monkeypatch.setattr(tool_service.local_tools, "health_canada_pmra_label_search", fake_pmra)

    payload = tool_service.run_local_tool(
        "health-canada-pmra-label-search",
        {
            "registration_number": "27313",
            "language": "fr-CA",
            "cache_dir": str(tmp_path / "pmra"),
            "cache_max_age_hours": 12,
        },
    )

    assert payload["status"] == "available"
    assert payload["registration_number"] == "27313"
    assert payload["language"] == "fr-CA"
    assert payload["cache_dir"] == str(tmp_path / "pmra")
    assert payload["cache_max_age_hours"] == 12


def test_tool_service_exposes_public_source_card_tools() -> None:
    disease = tool_service.run_local_tool(
        "disease-risk-context-adapter",
        {"crop": "corn", "region": "Iowa", "weather_window": "wet spring"},
    )
    variety = tool_service.run_local_tool(
        "public-variety-trial-ingest",
        {"crop": "soybean", "region": "Red River Valley", "maturity_or_market_class": "early"},
    )
    specialty = tool_service.run_local_tool(
        "specialty-crop-extension-corpus",
        {"crop": "tomato", "region": "California Central Valley"},
    )
    conservation = tool_service.run_local_tool(
        "conservation-practice-context-adapter",
        {"resource_concern": "runoff", "practice": "cover crop"},
    )
    partial_budget = tool_service.run_local_tool(
        "partial-budget-calculator",
        {"proposed_change": "variable-rate seed", "crop": "corn"},
    )
    program = tool_service.run_local_tool(
        "public-program-context-source",
        {"program_area": "conservation", "jurisdiction": "Iowa"},
    )
    salinity = tool_service.run_local_tool(
        "soil-water-salinity-irrigation-quality",
        {
            "crop": "alfalfa",
            "region": "Snake River Plain",
            "concern": "white crust and salinity risk",
            "jurisdiction": "Idaho",
        },
    )
    source_choice = tool_service.run_local_tool(
        "source-availability-and-tool-choice",
        {"crop": "corn", "region": "Iowa", "concern": "which public sources were checked"},
    )
    saskatchewan = tool_service.run_local_tool(
        "saskatchewan-official-crop-guidance",
        {"crop": "canola", "jurisdiction": "Saskatchewan", "concern": "fertility planning"},
    )

    assert disease["tool"] == "disease_risk_context_adapter"
    assert disease["status"] == "source_lane_available"
    assert "diagnostic confirmation" in " ".join(disease["decision_checks"]).lower()
    assert variety["source_lane_id"] == "public_variety_trial_ingest"
    assert specialty["source_urls"]
    assert conservation["provider"] == "USDA NRCS"
    assert partial_budget["source_urls"] == ["https://www.extension.iastate.edu/agdm/wholefarm/html/c1-50.html"]
    assert "eligibility" in " ".join(program["decision_checks"]).lower()
    assert salinity["source_lane_id"] == "soil_water_salinity_irrigation_quality"
    assert salinity["status"] == "source_lane_available"
    assert "sar or esp" in " ".join(salinity["decision_checks"]).lower()
    assert source_choice["source_lane_id"] == "source_availability_and_tool_choice"
    assert "public sources" in source_choice["coverage"].lower()
    assert saskatchewan["provider"] == "Government of Saskatchewan"
    assert len(saskatchewan["source_urls"]) == 2
    assert "not copied into the distributable corpus" in saskatchewan["boundary"]


def test_agno_tool_adapters_include_live_public_data_lanes() -> None:
    adapters = load_agno_tool_adapters()

    assert "agronomic_calculator" in adapters
    assert "nasa_power_daily" in adapters
    assert "daymet_single_pixel_daily" in adapters
    assert "openet_point_timeseries" in adapters
    assert "nrcs_soil_survey_point" in adapters
    assert "nrcs_soil_survey_geometry" in adapters
    assert "cropland_data_layer_point" in adapters
    assert "cropland_data_layer_geometry" in adapters
    assert "nass_quickstats_crop_stats" in adapters
    assert "epa_ppls_product_search" in adapters
    assert "cansis_soil_landscapes_canada" in adapters
    assert "aafc_annual_crop_inventory" in adapters
    assert "statcan_field_crop_statistics" in adapters
    assert "health_canada_pmra_label_search" in adapters
    assert "canada_et_or_water_use_source_needed" in adapters
    assert "aafc_nasdi_agroclimate" in adapters
    assert "disease_risk_context_adapter" in adapters
    assert "public_variety_trial_ingest" in adapters
    assert "specialty_crop_extension_corpus" in adapters
    assert "conservation_practice_context_adapter" in adapters
    assert "canada_conservation_practice_context_source" in adapters
    assert "field_record_audit_card" in adapters
    assert "partial_budget_calculator" in adapters
    assert "public_program_context_source" in adapters
    assert "forage_livestock_extension_corpus" in adapters
    assert "postharvest_storage_quality_corpus" in adapters
    assert "saskatchewan_official_crop_guidance" in adapters
    for source_lane_id in local_tools.DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS:
        assert source_lane_id in adapters
    assert "crop_history" in adapters["cropland_data_layer_point"].eval_tags
    assert "boundary" in adapters["cropland_data_layer_geometry"].eval_tags
    assert "water_window" in adapters["daymet_single_pixel_daily"].eval_tags
    assert "evapotranspiration" in adapters["openet_point_timeseries"].eval_tags
    assert "boundary" in adapters["nrcs_soil_survey_geometry"].eval_tags
    assert "crop_statistics" in adapters["nass_quickstats_crop_stats"].eval_tags
    assert "public_data" in adapters["nrcs_soil_survey_point"].eval_tags
    assert "canada" in adapters["cansis_soil_landscapes_canada"].eval_tags
    assert "source_lane" in adapters["health_canada_pmra_label_search"].eval_tags
    assert "disease" in adapters["disease_risk_context_adapter"].eval_tags
    assert "variety_trials" in adapters["public_variety_trial_ingest"].eval_tags
    assert "partial_budget" in adapters["partial_budget_calculator"].eval_tags
    assert "deep_public_coverage" in adapters["soil_water_salinity_irrigation_quality"].eval_tags
    assert "source_lane" in adapters["source_availability_and_tool_choice"].eval_tags
    assert adapters["canada_et_or_water_use_source_needed"].boundary == "canada_regional_agroclimate_prior"
    assert "spei" in adapters["aafc_nasdi_agroclimate"].eval_tags
    assert adapters["epa_ppls_product_search"].boundary == "label_metadata_boundary"


def test_public_adapter_readiness_reports_offline_snapshot_without_secrets(monkeypatch) -> None:
    for name in (*local_tools.OPENET_ENV_VARS, *local_tools.NASS_QUICKSTATS_ENV_VARS):
        monkeypatch.delenv(name, raising=False)

    readiness = tool_service.public_adapter_readiness()
    by_id = {item["id"]: item for item in readiness["adapters"]}

    assert readiness["schema_version"] == "open_agronomy_agent.public_adapter_readiness.v1"
    assert readiness["summary"]["adapter_count"] >= 38
    assert readiness["summary"]["monitor_count"] == 0
    assert by_id["openet_point_timeseries"]["status"] == "needs_key"
    assert by_id["openet_point_timeseries"]["required_env_vars"] == list(local_tools.OPENET_ENV_VARS)
    assert by_id["nass_quickstats_crop_stats"]["status"] == "ready"
    assert by_id["nass_quickstats_crop_stats"]["required_env_vars"] == list(local_tools.NASS_QUICKSTATS_ENV_VARS)
    assert by_id["nass_quickstats_crop_stats"]["offline_snapshot_ready"] is True
    assert by_id["nasa_power_daily"]["status"] == "ready"
    assert by_id["epa_ppls_product_search"]["credential_required"] is False
    assert by_id["cansis_soil_landscapes_canada"]["status"] == "ready"
    assert by_id["aafc_annual_crop_inventory"]["status"] == "ready"
    assert by_id["aafc_annual_crop_inventory"]["cache_dir"] == "outputs/tool_cache/aafc_annual_crop_inventory"
    assert by_id["statcan_field_crop_statistics"]["status"] == "ready"
    assert by_id["statcan_field_crop_statistics"]["offline_snapshot_ready"] is True
    assert (
        by_id["statcan_field_crop_statistics"]["offline_snapshot_path"]
        == local_tools.STATCAN_FIELD_CROP_SNAPSHOT_PATH
    )
    assert by_id["cansis_soil_landscapes_canada"]["decision_checks"]
    assert by_id["canada_et_or_water_use_source_needed"]["status_label"] == "live NASDI compatibility alias"
    assert by_id["canada_et_or_water_use_source_needed"]["decision_checks"]
    assert by_id["aafc_nasdi_agroclimate"]["status"] == "ready"
    assert by_id["aafc_nasdi_agroclimate"]["cache_dir"] == "outputs/tool_cache/aafc_nasdi_agroclimate"
    assert by_id["health_canada_pmra_label_search"]["status"] == "ready"
    assert by_id["health_canada_pmra_label_search"]["cache_dir"] == "outputs/tool_cache/pmra_ppid"
    assert by_id["partial_budget_calculator"]["status"] == "ready"
    assert by_id["partial_budget_calculator"]["decision_checks"]
    assert by_id["disease_risk_context_adapter"]["smoke_status"] == "not_required"
    assert by_id["soil_water_salinity_irrigation_quality"]["status"] == "ready"
    assert by_id["soil_water_salinity_irrigation_quality"]["smoke_status"] == "not_required"
    assert by_id["source_availability_and_tool_choice"]["field_context_required"] is False
    assert "fake-secret" not in str(readiness)


def test_public_adapter_readiness_marks_key_gated_lanes_ready_when_env_present(monkeypatch) -> None:
    for name in (*local_tools.OPENET_ENV_VARS, *local_tools.NASS_QUICKSTATS_ENV_VARS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(local_tools.OPENET_ENV_VARS[0], "fake-secret-openet")
    monkeypatch.setenv(local_tools.NASS_QUICKSTATS_ENV_VARS[0], "fake-secret-nass")

    readiness = tool_service.public_adapter_readiness()
    by_id = {item["id"]: item for item in readiness["adapters"]}

    assert by_id["openet_point_timeseries"]["status"] == "ready"
    assert by_id["openet_point_timeseries"]["configured_env_vars"] == [local_tools.OPENET_ENV_VARS[0]]
    assert by_id["nass_quickstats_crop_stats"]["status"] == "ready"
    assert by_id["nass_quickstats_crop_stats"]["configured_env_vars"] == [local_tools.NASS_QUICKSTATS_ENV_VARS[0]]
    assert "fake-secret" not in str(readiness)


def test_public_adapter_readiness_attaches_smoke_artifact_status(monkeypatch, tmp_path) -> None:
    keyed_path = tmp_path / "keyed_public_adapters_latest.json"
    ppls_path = tmp_path / "ppls_adapter_modes_latest.json"
    regional_path = tmp_path / "public_adapter_regional_matrix_latest.json"
    keyed_path.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.keyed_public_adapter_smoke.v1",
                "mode": "offline_fixture",
                "providers": ["USDA NASS Quick Stats", "OpenET"],
                "case_count": 4,
                "passed": True,
                "failures": [],
                "cases": [
                    {"case_id": "nass_quickstats_missing_key"},
                    {"case_id": "nass_quickstats_fixture_success"},
                    {"case_id": "openet_missing_key"},
                    {"case_id": "openet_fixture_success"},
                ],
            }
        ),
        encoding="utf-8",
    )
    ppls_path.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.ppls_adapter_smoke.v1",
                "mode": "offline_fixture",
                "provider": "EPA PPLS",
                "case_count": 4,
                "passed": True,
                "failures": [],
                "cases": [
                    {"case_id": "ingredient_candidate_disambiguation"},
                    {"case_id": "product_name_candidate"},
                    {"case_id": "exact_registration_number"},
                    {"case_id": "no_records"},
                ],
            }
        ),
        encoding="utf-8",
    )
    regional_path.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.public_adapter_regional_matrix.v1",
                "mode": "offline_fixture",
                "context_count": 5,
                "adapter_count": 9,
                "case_count": 42,
                "passed": True,
                "failures": [],
                "cases": [
                    {"case_id": "central_iowa_corn_soy__nrcs_soil_survey_point"},
                    {"case_id": "california_central_valley_tomato__openet_point_timeseries"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tool_service,
        "PUBLIC_ADAPTER_SMOKE_SPECS",
        (
            {
                "id": "ppls_adapter_modes",
                "label": "EPA PPLS search-mode smoke",
                "artifact_path": str(ppls_path),
                "adapter_ids": ("epa_ppls_product_search",),
                "blocking_for": "product-stewardship prompts",
                "boundary": "PPLS smoke boundary.",
            },
            {
                "id": "keyed_public_adapters",
                "label": "Key-gated Quick Stats/OpenET smoke",
                "artifact_path": str(keyed_path),
                "adapter_ids": ("nass_quickstats_crop_stats", "openet_point_timeseries"),
                "blocking_for": "crop-statistics and irrigation/ET prompts",
                "boundary": "Keyed adapter smoke boundary.",
            },
            {
                "id": "public_adapter_regional_matrix",
                "label": "Regional public-adapter matrix smoke",
                "artifact_path": str(regional_path),
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
                ),
                "blocking_for": "field-context public-source walkthroughs",
                "boundary": "Regional matrix smoke boundary.",
            },
        ),
    )

    readiness = tool_service.public_adapter_readiness()
    by_id = {item["id"]: item for item in readiness["adapters"]}

    assert readiness["summary"]["smoke_check_count"] == 3
    assert readiness["summary"]["smoke_passed_count"] == 3
    assert readiness["summary"]["smoke_missing_count"] == 0
    assert readiness["summary"]["smoke_failed_count"] == 0
    assert [check["status"] for check in readiness["smoke_checks"]] == ["passed", "passed", "passed"]
    assert by_id["openet_point_timeseries"]["smoke_status"] == "passed"
    assert by_id["openet_point_timeseries"]["smoke_checks"][0]["case_count"] == 4
    assert by_id["openet_point_timeseries"]["smoke_checks"][1]["case_count"] == 42
    assert by_id["nass_quickstats_crop_stats"]["smoke_checks"][0]["mode"] == "offline_fixture"
    assert by_id["epa_ppls_product_search"]["smoke_status"] == "passed"
    assert by_id["epa_ppls_product_search"]["smoke_checks"][0]["case_ids"][-1] == "no_records"
    assert by_id["nrcs_soil_survey_geometry"]["smoke_checks"][0]["case_count"] == 42
    assert by_id["cansis_soil_landscapes_canada"]["smoke_status"] == "passed"
    assert by_id["cansis_soil_landscapes_canada"]["smoke_checks"][0]["boundary"] == "Regional matrix smoke boundary."
    assert by_id["cansis_soil_landscapes_canada"]["decision_checks"]


def test_public_adapter_readiness_reports_missing_smoke_artifact(monkeypatch, tmp_path) -> None:
    missing_path = tmp_path / "missing_keyed_public_adapters_latest.json"
    monkeypatch.setattr(
        tool_service,
        "PUBLIC_ADAPTER_SMOKE_SPECS",
        (
            {
                "id": "keyed_public_adapters",
                "label": "Key-gated Quick Stats/OpenET smoke",
                "artifact_path": str(missing_path),
                "adapter_ids": ("nass_quickstats_crop_stats", "openet_point_timeseries"),
                "blocking_for": "crop-statistics and irrigation/ET prompts",
                "boundary": "Keyed adapter smoke boundary.",
            },
        ),
    )

    readiness = tool_service.public_adapter_readiness()
    by_id = {item["id"]: item for item in readiness["adapters"]}

    assert readiness["summary"]["smoke_check_count"] == 1
    assert readiness["summary"]["smoke_passed_count"] == 0
    assert readiness["summary"]["smoke_missing_count"] == 1
    assert readiness["smoke_checks"][0]["status"] == "missing"
    assert by_id["openet_point_timeseries"]["smoke_status"] == "missing"
    assert by_id["nass_quickstats_crop_stats"]["smoke_checks"][0]["status_label"] == "smoke missing"


def test_public_adapter_readiness_rejects_a_stale_or_wrong_smoke_contract(
    monkeypatch, tmp_path
) -> None:
    receipt = tmp_path / "regional.json"
    receipt.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.public_adapter_regional_matrix.v0",
                "mode": "live",
                "case_count": 1,
                "passed": True,
                "failures": [],
                "cases": [{"case_id": "one"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        tool_service,
        "PUBLIC_ADAPTER_SMOKE_SPECS",
        (
            {
                "id": "public_adapter_regional_matrix",
                "label": "Regional public-adapter matrix smoke",
                "artifact_path": str(receipt),
                "adapter_ids": ("nrcs_soil_survey_point",),
                "blocking_for": "field-context public-source walkthroughs",
                "boundary": "Regional matrix smoke boundary.",
                "expected_schema_version": "open_agronomy_agent.public_adapter_regional_matrix.v1",
                "expected_mode": "offline_fixture",
                "expected_case_count": 63,
            },
        ),
    )

    readiness = tool_service.public_adapter_readiness()

    assert readiness["summary"]["smoke_failed_count"] == 1
    assert readiness["smoke_checks"][0]["status"] == "failed"
    assert set(readiness["smoke_checks"][0]["validation_errors"]) == {
        "schema_version_mismatch",
        "mode_mismatch",
        "case_count_mismatch",
    }
