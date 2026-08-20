from __future__ import annotations

import argparse
import json
import sys

from agronomy_agent.capability_registry import cli_capability_listing
from agronomy_agent.local_tools import (
    DEFAULT_DAYMET_VARIABLES,
    DEFAULT_OPENET_MODEL,
    DEFAULT_OPENET_REFERENCE_ET,
    DEFAULT_OPENET_UNITS,
    DEFAULT_OPENET_VARIABLE,
    DEFAULT_POWER_PARAMETERS,
    DEFAULT_CDL_SAMPLE_POINTS,
    aafc_annual_crop_inventory,
    agronomic_calculator_tool,
    canada_et_or_water_use_source_needed,
    cansis_soil_landscapes_canada,
    cropland_data_layer_geometry,
    cropland_data_layer_point,
    daymet_single_pixel_daily,
    diagnostic_frame,
    epa_ppls_product_search,
    fertility_frame,
    health_canada_pmra_label_search,
    json_ready,
    nass_quickstats_crop_stats,
    nasa_power_daily,
    nrcs_soil_survey_geometry,
    nrcs_soil_survey_point,
    openet_point_timeseries,
    retrieve_context,
    route_question,
    soil_context,
    spray_window,
    statcan_field_crop_statistics,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="JSON-only local agronomy tools for model/tool-call experiments.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List available local tools and their intended use.")

    route = sub.add_parser("route", help="Classify a question and return router state.")
    route.add_argument("question")

    retrieve = sub.add_parser("retrieve", help="Return routed RAG/KG context for a question.")
    retrieve.add_argument("question")
    retrieve.add_argument("--top-k", type=int, default=5)
    retrieve.add_argument("--rag-config", default="configs/rag.yaml")

    soil = sub.add_parser("soil-context", help="Return regional soil/environment context from local corpora.")
    soil.add_argument("question")
    soil.add_argument("--top-k", type=int, default=6)

    spray = sub.add_parser("spray-window", help="Screen weather-sensitive product timing.")
    spray.add_argument("--wind-mph", type=float)
    spray.add_argument("--gust-mph", type=float)
    spray.add_argument("--temperature-f", type=float)
    spray.add_argument("--rain-hours", type=float)
    spray.add_argument("--inversion-risk", choices=["yes", "no", "high", "low", "likely", "unlikely", "true", "false"])
    spray.add_argument("--sensitive-downwind", action="store_true")
    spray.add_argument("--operation", default="spray")

    fert = sub.add_parser("fertility-frame", help="Return fertility data requirements and calibration boundaries.")
    fert.add_argument("--crop")
    fert.add_argument("--yield-goal", type=float)
    fert.add_argument("--soil-test-method")
    fert.add_argument("--soil-ph", type=float)
    fert.add_argument("--organic-matter-pct", type=float)
    fert.add_argument("--manure-or-legume-credit", action="store_true")

    diagnostic = sub.add_parser("diagnostic-frame", help="Return compact decision frames for common weak eval/tool scenarios.")
    diagnostic.add_argument("kind", choices=["4r", "pesticide-safety", "resistance", "compaction", "salinity-sodicity"])
    diagnostic.add_argument("--context", default="")

    calculate = sub.add_parser(
        "calculate",
        help="Run a typed offline agronomic calculation from structured JSON inputs.",
    )
    calculate.add_argument("operation")
    calculate.add_argument("--inputs-json", required=True, help="JSON object containing the operation's named inputs")

    power = sub.add_parser("weather-power", help="Fetch/cache NASA POWER daily agroclimate summary.")
    power.add_argument("--lat", type=float, required=True)
    power.add_argument("--lon", type=float, required=True)
    power.add_argument("--start", required=True, help="YYYYMMDD")
    power.add_argument("--end", required=True, help="YYYYMMDD")
    power.add_argument("--parameters", default=",".join(DEFAULT_POWER_PARAMETERS))

    daymet = sub.add_parser("daymet-single-pixel", help="Fetch/cache ORNL Daymet single-pixel daily climate summary.")
    daymet.add_argument("--lat", type=float, required=True)
    daymet.add_argument("--lon", type=float, required=True)
    daymet.add_argument("--start", required=True, help="YYYY-MM-DD")
    daymet.add_argument("--end", required=True, help="YYYY-MM-DD")
    daymet.add_argument("--variables", default=",".join(DEFAULT_DAYMET_VARIABLES))

    openet = sub.add_parser("openet-point-timeseries", help="Fetch/cache OpenET point evapotranspiration time-series context.")
    openet.add_argument("--lat", type=float, required=True)
    openet.add_argument("--lon", type=float, required=True)
    openet.add_argument("--start", required=True, help="YYYY-MM-DD")
    openet.add_argument("--end", required=True, help="YYYY-MM-DD")
    openet.add_argument("--interval", choices=["daily", "monthly"], default="monthly")
    openet.add_argument("--model", default=DEFAULT_OPENET_MODEL)
    openet.add_argument("--variable", default=DEFAULT_OPENET_VARIABLE)
    openet.add_argument("--reference-et", default=DEFAULT_OPENET_REFERENCE_ET)
    openet.add_argument("--units", default=DEFAULT_OPENET_UNITS)

    nrcs = sub.add_parser("nrcs-soil-survey", help="Fetch/cache NRCS Soil Data Access map-unit prior for a point.")
    nrcs.add_argument("--lat", type=float, required=True)
    nrcs.add_argument("--lon", type=float, required=True)

    nrcs_geometry = sub.add_parser("nrcs-soil-survey-geometry", help="Fetch/cache NRCS SDA map-unit/component prior for GeoJSON geometry.")
    nrcs_geometry.add_argument("--geometry-json", required=True, help="GeoJSON geometry object as JSON")
    nrcs_geometry.add_argument("--max-map-units", type=int, default=12)
    nrcs_geometry.add_argument("--max-components", type=int, default=40)

    cdl = sub.add_parser("cropland-data-layer", help="Fetch/cache USDA NASS CDL point crop-cover prior.")
    cdl.add_argument("--lat", type=float, required=True)
    cdl.add_argument("--lon", type=float, required=True)
    cdl.add_argument("--year", type=int)

    cdl_geometry = sub.add_parser("cropland-data-layer-geometry", help="Fetch/cache USDA NASS CDL sampled crop-cover prior for GeoJSON geometry.")
    cdl_geometry.add_argument("--geometry-json", required=True, help="GeoJSON geometry object as JSON")
    cdl_geometry.add_argument("--years", help="Comma-separated CDL years; defaults to the latest three available years")
    cdl_geometry.add_argument("--sample-points", type=int, default=DEFAULT_CDL_SAMPLE_POINTS)

    quickstats = sub.add_parser("nass-quickstats-crop-stats", help="Fetch/cache USDA NASS Quick Stats crop statistics.")
    quickstats.add_argument("--crop", required=True)
    quickstats.add_argument("--state-alpha", required=True)
    quickstats.add_argument("--county-name")
    quickstats.add_argument("--year-ge", type=int)
    quickstats.add_argument("--statistic-categories", default=",".join(("YIELD", "AREA HARVESTED", "PRODUCTION")))
    quickstats.add_argument("--source-desc", default="SURVEY")

    ppls = sub.add_parser("epa-ppls-product-search", help="Fetch/cache EPA PPLS product/ingredient metadata.")
    ppls.add_argument("--product-name")
    ppls.add_argument("--epa-reg-no")
    ppls.add_argument("--ingredient-name")
    ppls.add_argument("--pc-code")
    ppls.add_argument("--cas-number")

    canada_source = sub.add_parser("canada-source-lane", help="Fetch Canadian public-source context or return an explicit source-lane boundary.")
    canada_source.add_argument(
        "lane",
        choices=[
            "cansis-soil-landscapes-canada",
            "aafc-annual-crop-inventory",
            "statcan-field-crop-statistics",
            "health-canada-pmra-label-search",
            "canada-et-or-water-use-source-needed",
        ],
    )
    canada_source.add_argument("--lat", type=float)
    canada_source.add_argument("--lon", type=float)
    canada_source.add_argument("--geometry-json", help="GeoJSON geometry object as JSON")
    canada_source.add_argument("--crop")
    canada_source.add_argument("--province")
    canada_source.add_argument("--product-term")
    canada_source.add_argument("--search-kind")
    canada_source.add_argument("--registration-number", help="Exact 4- or 5-digit PMRA registration number for registry metadata.")
    canada_source.add_argument(
        "--language",
        choices=["en", "en-CA", "fr", "fr-CA"],
        default="en",
        help="PMRA registry response language.",
    )

    registered = sub.add_parser(
        "run",
        help="Run any HTTP-bound registered capability from a JSON payload.",
    )
    registered.add_argument("capability")
    registered.add_argument("--payload-json", default="{}", help="JSON object passed to the registered capability")
    registered.add_argument("--network-mode", choices=["online", "offline"], default="online")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "list":
            payload = {
                "tools": cli_capability_listing(),
                "contract": "Every command prints one JSON object to stdout; nonzero exit prints one JSON error object.",
            }
        elif args.cmd == "run":
            from agronomy_agent.server.services.tool_service import run_local_tool

            registered_payload = json.loads(args.payload_json)
            if not isinstance(registered_payload, dict):
                raise ValueError("--payload-json must decode to an object")
            payload = run_local_tool(
                args.capability,
                registered_payload,
                network_mode=args.network_mode,
            )
        elif args.cmd == "route":
            payload = route_question(args.question)
        elif args.cmd == "retrieve":
            payload = retrieve_context(args.question, top_k=args.top_k, rag_config=args.rag_config)
        elif args.cmd == "soil-context":
            payload = soil_context(args.question, top_k=args.top_k)
        elif args.cmd == "spray-window":
            payload = spray_window(
                wind_mph=args.wind_mph,
                gust_mph=args.gust_mph,
                temperature_f=args.temperature_f,
                rain_hours=args.rain_hours,
                inversion_risk=args.inversion_risk,
                sensitive_downwind=args.sensitive_downwind,
                operation=args.operation,
            )
        elif args.cmd == "fertility-frame":
            payload = fertility_frame(
                crop=args.crop,
                yield_goal=args.yield_goal,
                soil_test_method=args.soil_test_method,
                soil_ph=args.soil_ph,
                organic_matter_pct=args.organic_matter_pct,
                manure_or_legume_credit=args.manure_or_legume_credit,
            )
        elif args.cmd == "diagnostic-frame":
            payload = diagnostic_frame(args.kind, args.context)
        elif args.cmd == "calculate":
            inputs = json.loads(args.inputs_json)
            if not isinstance(inputs, dict):
                raise ValueError("--inputs-json must decode to an object")
            payload = agronomic_calculator_tool(args.operation, inputs)
        elif args.cmd == "weather-power":
            parameters = tuple(part.strip() for part in args.parameters.split(",") if part.strip())
            payload = nasa_power_daily(args.lat, args.lon, args.start, args.end, parameters=parameters)
        elif args.cmd == "daymet-single-pixel":
            variables = tuple(part.strip() for part in args.variables.split(",") if part.strip())
            payload = daymet_single_pixel_daily(args.lat, args.lon, args.start, args.end, variables=variables)
        elif args.cmd == "openet-point-timeseries":
            payload = openet_point_timeseries(
                args.lat,
                args.lon,
                args.start,
                args.end,
                interval=args.interval,
                model=args.model,
                variable=args.variable,
                reference_et=args.reference_et,
                units=args.units,
            )
        elif args.cmd == "nrcs-soil-survey":
            payload = nrcs_soil_survey_point(args.lat, args.lon)
        elif args.cmd == "nrcs-soil-survey-geometry":
            geometry = json.loads(args.geometry_json)
            payload = nrcs_soil_survey_geometry(
                geometry,
                max_map_units=args.max_map_units,
                max_components=args.max_components,
            )
        elif args.cmd == "cropland-data-layer":
            payload = cropland_data_layer_point(args.lat, args.lon, year=args.year)
        elif args.cmd == "cropland-data-layer-geometry":
            geometry = json.loads(args.geometry_json)
            years = tuple(int(part.strip()) for part in args.years.split(",") if part.strip()) if args.years else None
            payload = cropland_data_layer_geometry(
                geometry,
                years=years,
                sample_points=args.sample_points,
            )
        elif args.cmd == "nass-quickstats-crop-stats":
            payload = nass_quickstats_crop_stats(
                crop=args.crop,
                state_alpha=args.state_alpha,
                county_name=args.county_name,
                year_ge=args.year_ge,
                statistic_categories=tuple(part.strip() for part in args.statistic_categories.split(",") if part.strip()),
                source_desc=args.source_desc,
            )
        elif args.cmd == "epa-ppls-product-search":
            payload = epa_ppls_product_search(
                product_name=args.product_name,
                epa_reg_no=args.epa_reg_no,
                ingredient_name=args.ingredient_name,
                pc_code=args.pc_code,
                cas_number=args.cas_number,
            )
        elif args.cmd == "canada-source-lane":
            geometry = json.loads(args.geometry_json) if args.geometry_json else None
            if args.lane == "cansis-soil-landscapes-canada":
                payload = cansis_soil_landscapes_canada(args.lat, args.lon, geometry=geometry, crop=args.crop, province=args.province)
            elif args.lane == "aafc-annual-crop-inventory":
                payload = aafc_annual_crop_inventory(args.lat, args.lon, geometry=geometry, crop=args.crop, province=args.province)
            elif args.lane == "statcan-field-crop-statistics":
                payload = statcan_field_crop_statistics(crop=args.crop, province=args.province)
            elif args.lane == "health-canada-pmra-label-search":
                payload = health_canada_pmra_label_search(
                    product_term=args.product_term,
                    search_kind=args.search_kind,
                    registration_number=args.registration_number,
                    language=args.language,
                )
            elif args.lane == "canada-et-or-water-use-source-needed":
                payload = canada_et_or_water_use_source_needed(args.lat, args.lon, crop=args.crop, province=args.province)
            else:
                raise ValueError(f"unknown Canada source lane: {args.lane}")
        else:
            raise ValueError(f"unknown command: {args.cmd}")
        print(json_ready(payload))
        return 0
    except Exception as exc:
        print(json_ready({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
