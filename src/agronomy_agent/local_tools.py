from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agronomy_agent.agronomic_calculations import agronomic_calculator
from agronomy_agent.agent import build_context, load_agent_resources
from agronomy_agent.paths import repo_path
from agronomy_agent.router import classify_query


DEFAULT_POWER_PARAMETERS = ("T2M", "T2M_MIN", "T2M_MAX", "PRECTOTCORR", "WS2M", "RH2M")
NRCS_SDA_POST_REST_URL = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"
EPA_PPLS_BASE_URL = "https://ordspub.epa.gov/ords/pesticides/cswu/ProductSearch"
EPA_PPLS_CACHE_VERSION = "v3"
CROPSCAPE_CDL_VALUE_URL = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue"
DEFAULT_CDL_YEAR = 2025
NASS_QUICKSTATS_API_URL = "https://quickstats.nass.usda.gov/api/api_GET/"
NASS_QUICKSTATS_BULK_DATA_URL = "https://www.nass.usda.gov/datasets/"
NASS_QUICKSTATS_SNAPSHOT_PATH = "data/snapshots/nass_quickstats_state_crop_stats.jsonl"
NASS_QUICKSTATS_CACHE_VERSION = "v2"
NASS_QUICKSTATS_ENV_VARS = (
    "AGRONOMY_AGENT_NASS_QUICKSTATS_API_KEY",
    "USDA_NASS_QUICKSTATS_API_KEY",
    "NASS_API_KEY",
)
DEFAULT_QUICKSTATS_CATEGORIES = ("YIELD", "AREA HARVESTED", "PRODUCTION")
_NASS_QUICKSTATS_SNAPSHOT_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
DAYMET_SINGLE_PIXEL_API_URL = "https://daymet.ornl.gov/single-pixel/api/data"
DEFAULT_DAYMET_VARIABLES = ("tmax", "tmin", "prcp", "srad", "vp", "dayl")
OPENET_RASTER_TIMESERIES_POINT_URL = "https://openet-api.org/raster/timeseries/point"
OPENET_ENV_VARS = ("AGRONOMY_AGENT_OPENET_API_KEY", "OPENET_API_KEY")
DEFAULT_OPENET_MODEL = "Ensemble"
DEFAULT_OPENET_VARIABLE = "ET"
DEFAULT_OPENET_REFERENCE_ET = "gridMET"
DEFAULT_OPENET_UNITS = "mm"
PMRA_PPID_EXTRACT_BASE_URL = "https://pest-control.canada.ca/pesticide-registry-api/api/extract"
PMRA_PPID_OPEN_DATA_URL = "https://open.canada.ca/data/en/dataset/e10b0d6e-04ac-4014-a64a-666c3874bbe0"
PMRA_PPID_CACHE_VERSION = "v2"
PMRA_PPID_DEFAULT_CACHE_MAX_AGE_HOURS = 24
AAFC_ACI_IMAGE_SERVER_TEMPLATE = "https://agriculture.canada.ca/imagery-images/rest/services/annual_crop_inventory/{year}/ImageServer"
AAFC_ACI_CACHE_VERSION = "v1"
DEFAULT_AAFC_ACI_YEAR = 2024
AAFC_NASDI_OPEN_DATA_URL = "https://open.canada.ca/data/en/dataset/2b72996a-2905-4cea-a565-8bfb85cd42ac"
AAFC_NASDI_IMAGE_SERVER_TEMPLATE = "https://agriculture.canada.ca/imagery-images/rest/services/nasdi/{service}/ImageServer"
AAFC_NASDI_CACHE_VERSION = "v2"
AAFC_NASDI_DEFAULT_TIME_WINDOW = "013w"
AAFC_NASDI_CATALOG_CACHE_SECONDS = 6 * 60 * 60
AAFC_NASDI_WEEKLY_WINDOWS = ("004w", "009w", "013w", "026w", "039w", "052w", "078w", "104w")
AAFC_NASDI_MONTHLY_WINDOWS = ("01m", "02m", "03m", "06m", "09m", "12m", "18m", "24m")


class OfflineCacheMissError(RuntimeError):
    """Raised when an offline-only adapter has no local evidence and makes no request."""


AAFC_NASDI_INDICATORS: dict[str, dict[str, Any]] = {
    "spi": {
        "label": "Standardized Precipitation Index",
        "service": "standardized_precipitation_index",
        "raster_function": "nasdi_standardized_precipitation_index",
        "units": "standardized anomaly",
        "default_time_window": "013w",
    },
    "spei": {
        "label": "Standardized Precipitation Evapotranspiration Index",
        "service": "standardized_precipitation_evapotranspiration_index",
        "raster_function": "nasdi_standardized_precipitation_evapotranspiration_index",
        "units": "standardized anomaly",
        "default_time_window": "013w",
    },
    "temperature_anomaly": {
        "label": "Difference from normal temperature",
        "service": "difference_from_normal_temperature",
        "raster_function": "nasdi_difference_from_normal_temperature",
        "units": "degrees C",
        "default_time_window": "004w",
    },
    "percent_of_average_precipitation": {
        "label": "Percent of average precipitation",
        "service": "percent_of_average_precipitation",
        "raster_function": "nasdi_percent_of_average_precipitation",
        "units": "percent of 1991-2020 average",
        "default_time_window": "013w",
        "raw_scale_factor": 100.0,
    },
}
STATCAN_FIELD_CROP_PRODUCT_ID = 32100359
STATCAN_WDS_BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest"
STATCAN_FIELD_CROP_TABLE_URL = "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210035901"
STATCAN_FIELD_CROP_CACHE_VERSION = "v2"
STATCAN_FIELD_CROP_SNAPSHOT_PATH = "data/snapshots/statcan_field_crop_statistics.jsonl"
STATCAN_FIELD_CROP_SNAPSHOT_MANIFEST_PATH = "data/snapshots/statcan_field_crop_statistics_manifest.json"
_STATCAN_FIELD_CROP_SNAPSHOT_CACHE: dict[
    tuple[str, int, int, str, int, int],
    tuple[list[dict[str, Any]], dict[str, Any]],
] = {}
STATCAN_FIELD_CROP_STATISTICS = {
    "seeded_area_hectares": (16, "Seeded area (hectares)"),
    "harvested_area_hectares": (17, "Harvested area (hectares)"),
    "average_yield_kg_per_hectare": (18, "Average yield (kilograms per hectare)"),
    "production_metric_tonnes": (19, "Production (metric tonnes)"),
}
STATCAN_SYMBOL_CODES = {
    0: (None, None),
    1: ("p", "preliminary"),
    3: ("r", "revised"),
}
STATCAN_STATUS_CODES = {
    0: (None, "normal"),
    1: ("..", "not available for a specific reference period"),
    2: ("0s", "rounded to zero"),
    3: ("A", "data quality: excellent"),
    4: ("B", "data quality: very good"),
    5: ("C", "data quality: good"),
    6: ("D", "data quality: acceptable"),
    7: ("E", "use with caution"),
    8: ("F", "too unreliable to be published"),
    9: ("...", "not applicable"),
    10: ("<LOD", "less than the limit of detection"),
}
STATCAN_PROVINCE_MEMBER_IDS = {
    "CANADA": 1, "NL": 13, "PE": 3, "NS": 4, "NB": 5, "QC": 6, "ON": 7,
    "MB": 9, "SK": 10, "AB": 11, "BC": 12,
}
STATCAN_CROP_MEMBER_IDS = {
    "barley": 6, "beans": 39, "buckwheat": 12, "canola": 16, "canola rapeseed": 16,
    "chickpeas": 38, "corn": 11, "corn grain": 11, "flax": 14, "flaxseed": 14,
    "lentils": 32, "mustard": 30, "oats": 5, "peas": 13, "dry peas": 13,
    "soybean": 15, "soybeans": 15, "sunflower": 31, "wheat": 1,
}
CANADA_SOIL_LANDSCAPES_URL = "https://services.arcgis.com/lGOekm0RsNxYnT3j/ArcGIS/rest/services/Soil_landscapes_of_Canada/FeatureServer/0"
CANADA_SOIL_LANDSCAPES_CACHE_VERSION = "v1"
CANADA_SOURCE_LANE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "cansis_soil_landscapes_canada": {
        "tool": "cansis_soil_landscapes_canada",
        "source_lane_id": "cansis_soil_landscapes_canada",
        "source_name": "CanSIS National Soil Database / Soil Landscapes of Canada",
        "provider": "Agriculture and Agri-Food Canada",
        "source": CANADA_SOIL_LANDSCAPES_URL,
        "status": "available",
        "coverage": "Canadian Soil Landscapes of Canada point-level soil, drainage, and landscape context.",
        "decision_checks": [
            "confirm the province, coordinates, boundary, and map scale before using the soil landscape as evidence",
            "treat SLC/CanSIS polygons as regional soil-landscape priors, not a current soil test or in-field delineation",
            "ask for recent soil tests, drainage observations, salinity/sodicity evidence, and field scouting before field-specific advice",
            "avoid substituting USDA NRCS soil-survey facts for Canadian fields",
        ],
        "boundary": (
            "CanSIS/Soil Landscapes is a broad public soil-landscape prior. It does not replace a field soil test, "
            "in-field delineation, drainage assessment, management zones, or field truth."
        ),
    },
    "aafc_annual_crop_inventory": {
        "tool": "aafc_annual_crop_inventory",
        "source_lane_id": "aafc_annual_crop_inventory",
        "source_name": "AAFC Annual Crop Inventory",
        "provider": "Agriculture and Agri-Food Canada",
        "source": AAFC_ACI_IMAGE_SERVER_TEMPLATE.format(year=DEFAULT_AAFC_ACI_YEAR),
        "status": "available",
        "coverage": "Canadian annual crop-cover and land-cover classification samples from the AAFC Annual Crop Inventory.",
        "decision_checks": [
            "use AAFC Annual Crop Inventory for Canadian crop-cover priors instead of USDA CDL",
            "check crop year, classification resolution, mixed pixels, and whether the field boundary covers multiple classes",
            "separate satellite crop-cover class from grower planting records, crop-insurance acres, and rotation proof",
            "ask for local records when crop history affects disease, herbicide carryover, nutrient credit, or seed-selection decisions",
        ],
        "boundary": (
            "AAFC Annual Crop Inventory is a 30 m satellite-derived crop/land-cover classification. Point and boundary "
            "samples are crop-cover priors, not grower planting records, acreage proof, crop-insurance evidence, "
            "or verified field history."
        ),
    },
    "statcan_field_crop_statistics": {
        "tool": "statcan_field_crop_statistics",
        "source_lane_id": "statcan_field_crop_statistics",
        "source_name": "Statistics Canada field crop statistics",
        "provider": "Statistics Canada",
        "source": STATCAN_FIELD_CROP_TABLE_URL,
        "status": "available",
        "coverage": "Canadian regional field-crop area, yield, and production statistics.",
        "decision_checks": [
            "match crop, province or smaller published geography, statistic, units, and crop year before using the table",
            "separate regional area/yield/production statistics from field-specific yield potential or market advice",
            "watch for suppressed, revised, preliminary, or unavailable values before drawing a comparison",
            "ask for farm records, yield maps, local prices, and cost assumptions before economics or benchmark claims",
        ],
        "boundary": (
            "Statistics Canada field-crop table 32-10-0359-01 provides published provincial and national estimates. "
            "It is not field-specific yield prediction, market advice, grower records, or rate recommendations."
        ),
    },
    "health_canada_pmra_label_search": {
        "tool": "health_canada_pmra_label_search",
        "source_lane_id": "health_canada_pmra_label_search",
        "source_name": "Health Canada PMRA pesticide label search",
        "provider": "Health Canada PMRA",
        "source": PMRA_PPID_OPEN_DATA_URL,
        "status": "available",
        "coverage": "Canadian pesticide product and label registry metadata by exact PMRA registration number.",
        "decision_checks": [
            "provide or confirm the exact Canadian PMRA registration number before treating a product record as checked",
            "verify crop/site, pest/use, province if relevant, current label status, restrictions, PPE, REI, PHI, and buffers",
            "treat PPID registry metadata as label-access context, not legal interpretation or a replacement for the current authorized label",
            "do not use EPA PPLS as the label authority for Canadian product-use questions",
        ],
        "boundary": (
            "Health Canada PMRA PPID returns public registry metadata for an exact registration number. It is not legal "
            "label interpretation, local use approval, exact rate advice, current-label text, or a substitute for reading "
            "the current authorized label."
        ),
    },
    "canada_et_or_water_use_source_needed": {
        "tool": "canada_et_or_water_use_source_needed",
        "source_lane_id": "canada_et_or_water_use_source_needed",
        "source_name": "AAFC National Agroclimate Series of Derived Indicators",
        "provider": "Agriculture and Agri-Food Canada",
        "source": AAFC_NASDI_OPEN_DATA_URL,
        "status": "available",
        "coverage": (
            "Dated Canadian gridded SPI, SPEI, temperature-anomaly, and precipitation-anomaly context from NASDI."
        ),
        "decision_checks": [
            "check the exact indicator, accumulation window, observation end date, grid scale, and catalog raster before using the value",
            "separate SPI, SPEI, precipitation, and temperature anomaly context from field ET totals or measured soil water",
            "ask for field water balance, irrigation events, soil-moisture sensors, local forecast, and crop stage before timing advice",
            "do not convert a NASDI anomaly value into an irrigation, fertility, pesticide, or yield prescription",
        ],
        "boundary": (
            "AAFC NASDI values are dated regional grid-cell anomaly context. They are not field-intersected ET, a local "
            "forecast, an irrigation prescription, a water-right or applied-water record, a soil-moisture sensor reading, "
            "or field-specific consumptive-use truth."
        ),
    },
}
PUBLIC_SOURCE_LANE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "disease_risk_context_adapter": {
        "tool": "disease_risk_context_adapter",
        "source_lane_id": "disease_risk_context_adapter",
        "source_name": "Public disease risk and fungicide decision context",
        "provider": "Land-grant extension and regional IPM programs",
        "source_urls": ["https://ipmcenters.org/"],
        "status": "source_lane_available",
        "coverage": "Disease-risk framing from weather, host susceptibility, scouting, diagnosis, threshold, and economics.",
        "decision_checks": [
            "crop, growth stage, hybrid or variety susceptibility, and disease history",
            "recent and forecast weather separated from historical gridded weather",
            "scouting pattern, symptom distribution, and diagnostic confirmation when symptoms are ambiguous",
            "product label, resistance-management group, preharvest interval, and application window",
            "expected yield protection, application cost, commodity price, and uncertainty range",
        ],
        "boundary": (
            "This source card is a disease-risk decision framework. It does not identify the pathogen, confirm disease, "
            "recommend a fungicide product or rate, or prove that treatment will pay."
        ),
    },
    "public_variety_trial_ingest": {
        "tool": "public_variety_trial_ingest",
        "source_lane_id": "public_variety_trial_ingest",
        "source_name": "Public land-grant variety and hybrid trial lane",
        "provider": "Land-grant crop performance trials",
        "source_urls": ["https://www.croptesting.iastate.edu/"],
        "status": "source_lane_available",
        "coverage": "Public variety, hybrid, and cultivar trial evidence for local adaptation and yield-stability review.",
        "decision_checks": [
            "match trial region, maturity group, crop class, irrigation or dryland setting, and soil constraints",
            "compare multi-location and multi-year performance instead of one top-yielding plot",
            "review lodging, disease scores, grain or quality traits, harvest moisture, and management notes",
            "treat company plot data and public replicated trials as different evidence classes",
            "keep final selection tied to seed availability, risk tolerance, and local adviser input",
        ],
        "boundary": (
            "This source card identifies the public trial evidence lane. It is not a live variety-trial scraper, "
            "seed endorsement, yield guarantee, or substitute for local replicated results."
        ),
    },
    "specialty_crop_extension_corpus": {
        "tool": "specialty_crop_extension_corpus",
        "source_lane_id": "specialty_crop_extension_corpus",
        "source_name": "Specialty-crop extension and IPM guidance lane",
        "provider": "Cooperative extension specialty-crop programs",
        "source_urls": ["https://ipm.ucanr.edu/agriculture/"],
        "status": "source_lane_available",
        "coverage": "Specialty-crop production, irrigation, fertility, pest, disease, and crop-quality guidance.",
        "decision_checks": [
            "crop species, cultivar, production system, protected versus open-field setting, and market quality target",
            "local irrigation water quality, salinity, drainage, heat, humidity, and frost constraints",
            "scouting and diagnosis evidence before product, fertility, or irrigation actions",
            "food-safety, preharvest interval, worker-safety, and market-residue boundaries where relevant",
            "region-specific extension guidance before transferring row-crop assumptions to specialty crops",
        ],
        "boundary": (
            "This source card points to specialty-crop extension lanes. It is not a crop-specific prescription, "
            "product label interpretation, food-safety plan, or guarantee of local market acceptance."
        ),
    },
    "conservation_practice_context_adapter": {
        "tool": "conservation_practice_context_adapter",
        "source_lane_id": "conservation_practice_context_adapter",
        "source_name": "Conservation practice planning context",
        "provider": "USDA NRCS",
        "source_urls": [
            "https://www.nrcs.usda.gov/resources/guides-and-instructions/conservation-practice-standards",
            "https://www.farmers.gov/conservation",
        ],
        "status": "source_lane_available",
        "coverage": "Public conservation-practice standards, conservation concerns, and implementation-boundary context.",
        "decision_checks": [
            "resource concern, field slope, soil hydrologic group, drainage, erosion/runoff pathway, and receiving water",
            "practice standard, design criteria, operation and maintenance needs, and local NRCS technical review",
            "interaction with crop rotation, trafficability, drainage, tile outlets, grazing, and nutrient management",
            "cost-share or program eligibility kept separate from agronomic suitability",
            "monitoring plan for establishment, maintenance, and performance after installation",
        ],
        "boundary": (
            "This source card frames conservation-practice evidence. It is not an NRCS conservation plan, engineering design, "
            "program approval, or cost-share eligibility determination."
        ),
    },
    "canada_conservation_practice_context_source": {
        "tool": "canada_conservation_practice_context_source",
        "source_lane_id": "canada_conservation_practice_context_source",
        "source_name": "Canadian conservation and beneficial management practice context",
        "provider": "Canadian provincial and federal agriculture programs",
        "source_urls": ["https://agriculture.canada.ca/"],
        "status": "source_lane_available",
        "coverage": "Canadian conservation, beneficial management practice, soil, water, and erosion-context source selection.",
        "decision_checks": [
            "province, watershed, soil landscape, slope, drainage, erosion/runoff pathway, and receiving water",
            "provincial beneficial management practice guidance and local program rules",
            "crop rotation, trafficability, drainage, riparian, grazing, and nutrient-management interactions",
            "separate public agronomic suitability from cost-share eligibility or regulatory approval",
            "ask for local conservation authority, provincial specialist, or agronomist review before implementation",
        ],
        "boundary": (
            "This source card identifies Canada-appropriate conservation evidence lanes. It is not a provincial program "
            "eligibility decision, engineering design, regulatory approval, or field-specific conservation plan."
        ),
    },
    "field_record_audit_card": {
        "tool": "field_record_audit_card",
        "source_lane_id": "field_record_audit_card",
        "source_name": "Field-record audit and precision-ag evidence card",
        "provider": "Open Agronomy Agent deterministic audit card",
        "source_urls": [],
        "status": "source_lane_available",
        "coverage": "Audit requirements for yield maps, soil zones, prescriptions, as-applied records, and field observations.",
        "decision_checks": [
            "consistent field boundary, projection, crop year, hybrid/variety, and operation dates",
            "yield monitor calibration, moisture correction, outlier removal, and pass/edge cleanup",
            "soil-zone sampling design, lab method, sample age, and local calibration basis",
            "as-applied, weather, scouting, and harvest layers aligned to the same boundary",
            "versioned prescription, reviewer, assumptions, and post-season performance check",
        ],
        "boundary": (
            "This source card audits whether field records can support a recommendation. It does not validate proprietary "
            "files, prove yield response, create a prescription, or replace adviser review."
        ),
    },
    "partial_budget_calculator": {
        "tool": "partial_budget_calculator",
        "source_lane_id": "partial_budget_calculator",
        "source_name": "Partial-budget decision frame",
        "provider": "Extension farm management decision tools",
        "source_urls": ["https://www.extension.iastate.edu/agdm/wholefarm/html/c1-50.html"],
        "status": "source_lane_available",
        "coverage": "Added returns, reduced costs, added costs, reduced returns, and break-even framing for incremental changes.",
        "decision_checks": [
            "baseline practice and proposed change described as an incremental comparison",
            "added returns and reduced costs separated from added costs and reduced returns",
            "yield, price, input, machinery, labor, risk, and learning-curve assumptions stated as ranges",
            "one-time transition costs separated from recurring annual economics",
            "break-even yield, price, adoption, or cost threshold shown before claiming the practice pays",
        ],
        "boundary": (
            "This source card frames partial-budget arithmetic. It is not financial advice, tax advice, market forecasting, "
            "or proof of profitability without farm-specific records."
        ),
    },
    "public_program_context_source": {
        "tool": "public_program_context_source",
        "source_lane_id": "public_program_context_source",
        "source_name": "Public agricultural program context",
        "provider": "USDA Farmers.gov and public agency program pages",
        "source_urls": ["https://www.farmers.gov/conservation", "https://www.nrcs.usda.gov/programs-initiatives"],
        "status": "source_lane_available",
        "coverage": "Program-source boundaries for conservation, risk-management, and public assistance context.",
        "decision_checks": [
            "jurisdiction, agency, program name, sign-up window, eligibility rules, and local office process",
            "separate technical agronomic fit from application ranking, approval, payment, or compliance",
            "confirm deadlines, documentation, practice standards, and maintenance requirements",
            "avoid promising cost share, payment, insurance treatment, or regulatory outcome",
            "record the official source URL and date checked for reviewer follow-up",
        ],
        "boundary": (
            "This source card frames public program context. It is not eligibility advice, legal advice, guarantee of "
            "cost share, or substitute for the responsible agency or local office."
        ),
    },
    "forage_livestock_extension_corpus": {
        "tool": "forage_livestock_extension_corpus",
        "source_lane_id": "forage_livestock_extension_corpus",
        "source_name": "Forage, grazing, and livestock safety extension lane",
        "provider": "Land-grant forage and livestock extension programs",
        "source_urls": [],
        "status": "source_lane_available",
        "coverage": "Forage harvest timing, grazing readiness, nitrate/prussic-acid risk, feed testing, and livestock safety context.",
        "decision_checks": [
            "forage species, growth stage, stress event, harvest interval, grazing plan, and animal class",
            "weather stress, frost, drought, manure, herbicide, and nitrate or prussic-acid risk factors",
            "representative forage or feed test before high-risk feeding decisions",
            "withdrawal, grazing restriction, label, and feed-safety boundaries where products were used",
            "local extension or veterinarian review when toxicity, mycotoxin, or animal-health risk is plausible",
        ],
        "boundary": (
            "This source card frames forage and livestock-safety evidence. It is not veterinary advice, feed-test proof, "
            "product-label interpretation, or guarantee of animal safety."
        ),
    },
    "postharvest_storage_quality_corpus": {
        "tool": "postharvest_storage_quality_corpus",
        "source_lane_id": "postharvest_storage_quality_corpus",
        "source_name": "Postharvest drying, storage, quality, and mycotoxin lane",
        "provider": "Extension grain quality and Crop Protection Network resources",
        "source_urls": [
            "https://www.extension.iastate.edu/grain/tips-handling-drying-and-storing-damaged-grain",
            "https://cropprotectionnetwork.org/publications/storing-mycotoxin-affected-grain",
        ],
        "status": "source_lane_available",
        "coverage": "Harvest moisture, drying, cooling, storage monitoring, quality defects, and mycotoxin risk context.",
        "decision_checks": [
            "crop, harvest moisture, damage, test weight, weather delay, and intended storage duration",
            "drying target, kernel temperature, cooling, aeration, and bin-monitoring plan",
            "mycotoxin and quality testing before blending, feeding, or marketing high-risk grain",
            "insurance, elevator, feed, or regulatory quality requirements kept separate from agronomic advice",
            "worker safety, dust, mold, confined-space, and equipment hazards where relevant",
        ],
        "boundary": (
            "This source card frames storage and quality evidence. It is not a grain merchandizing decision, insurance "
            "adjustment, feed-safety clearance, or substitute for testing high-risk grain."
        ),
    },
}
DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "saskatchewan_official_crop_guidance": {
        "tool": "saskatchewan_official_crop_guidance",
        "source_lane_id": "saskatchewan_official_crop_guidance",
        "source_name": "Saskatchewan official crop guidance live reference",
        "provider": "Government of Saskatchewan",
        "source_urls": [
            "https://www.saskatchewan.ca/business/agriculture-natural-resources-and-industry/agribusiness-farmers-and-ranchers/crops-and-irrigation/soils-fertility-and-nutrients",
            "https://www.saskatchewan.ca/business/agriculture-natural-resources-and-industry/agribusiness-farmers-and-ranchers/crops-and-irrigation/crop-guides-and-publications",
        ],
        "status": "source_lane_available",
        "coverage": (
            "Current Government of Saskatchewan source hubs for soil, fertility, nutrient, crop-production, and "
            "crop-protection follow-up; checked as live references rather than copied into the distributable corpus."
        ),
        "decision_checks": [
            "open the current Saskatchewan topic page or publication that matches the crop and decision before acting",
            "confirm soil test method, crop stage, field history, moisture, and local recommendation basis for fertility decisions",
            "for pesticide decisions, use the current Health Canada PMRA label as the legal authority for crop, pest, rate, timing, restrictions, PPE, REI, PHI, and buffers",
            "record the exact official URL and date checked because provincial guidance and annual publications can change",
            "keep provincial reference material separate from field observations, laboratory results, grower records, and adviser judgment",
        ],
        "boundary": (
            "Live-reference card only. Saskatchewan Crown-copyright guidance is not copied into the distributable corpus, "
            "and this card does not return field-specific facts, reproduce provincial recommendations, interpret a product "
            "label, or replace the current PMRA label and qualified local advice."
        ),
    },
    "nutrient_4r_drainage_water_quality": {
        "tool": "nutrient_4r_drainage_water_quality",
        "source_lane_id": "nutrient_4r_drainage_water_quality",
        "source_name": "4R nutrient, drainage, and water-quality lane",
        "provider": "Land-grant nutrient management and NRCS conservation programs",
        "source_urls": ["https://www.nrcs.usda.gov/resources/guides-and-instructions/conservation-practice-standards"],
        "status": "source_lane_available",
        "coverage": "4R nutrient planning with tile, leaching, runoff, placement, timing, manure, and water-quality boundaries.",
        "decision_checks": [
            "soil test, crop removal, yield goal, manure or legume credits, and source-rate-time-place assumptions",
            "tile outlet, drainage ditch, slope, soil hydrologic group, runoff/leaching pathway, and receiving-water risk",
            "timing, placement, stabilizer, split-application, cover crop, buffer, and drainage-management tradeoffs",
            "records that show applied source/rate/date/place and post-season performance or loss indicators",
            "local nutrient-management standard, conservation-practice, and water-quality guidance before a prescription",
        ],
        "boundary": (
            "This source card frames nutrient and water-quality evidence. It is not a nutrient-management plan, regulatory "
            "compliance determination, field-specific rate, or proof that a practice will reduce measured losses."
        ),
    },
    "soil_water_salinity_irrigation_quality": {
        "tool": "soil_water_salinity_irrigation_quality",
        "source_lane_id": "soil_water_salinity_irrigation_quality",
        "source_name": "Soil-water salinity and irrigation-quality lane",
        "provider": "Extension irrigation, salinity, and soil-water programs",
        "source_urls": ["https://www.nrcs.usda.gov/resources/education-and-teaching-materials/soil-health-guides"],
        "status": "source_lane_available",
        "coverage": "Salinity, sodicity, irrigation water quality, drainage, infiltration, ET, and leaching-context checks.",
        "decision_checks": [
            "soil EC, pH, sodium hazard as SAR or ESP, texture, drainage, rooting depth, and field pattern",
            "irrigation-water EC, sodium, bicarbonate, chloride, boron, sampling date, and source variability",
            "crop salt tolerance, growth stage, ET demand, rainfall/leaching opportunity, and drainage feasibility",
            "soil-structure or infiltration constraints separated from nutrient deficiency or disease symptoms",
            "local irrigation specialist or lab interpretation before amendment, leaching, or water-source changes",
        ],
        "boundary": (
            "This source card is an evidence checklist for salinity, sodicity, and irrigation water quality. It does not "
            "diagnose a field from symptoms, design a reclamation plan, or prove water suitability without lab data."
        ),
    },
    "ipm_beneficials_and_thresholds": {
        "tool": "ipm_beneficials_and_thresholds",
        "source_lane_id": "ipm_beneficials_and_thresholds",
        "source_name": "IPM thresholds and beneficial insects lane",
        "provider": "Land-grant IPM and regional pest monitoring programs",
        "source_urls": ["https://ipmcenters.org/"],
        "status": "source_lane_available",
        "coverage": "Economic thresholds, pest stage, beneficial insects, resistance, scouting, and follow-up IPM evidence.",
        "decision_checks": [
            "pest species, life stage, crop stage, injury level, sampling method, and field distribution",
            "beneficial insects, natural enemies, weather, crop stress, and local pest advisories",
            "economic threshold, treatment cost, crop value, expected control, and uncertainty range",
            "mode-of-action rotation, resistance history, pollinator and sensitive-area risk, and label restrictions",
            "post-treatment scouting and local extension/adviser review for recurring or uncertain pressure",
        ],
        "boundary": (
            "This source card frames IPM evidence. It is not a pest identification, legal product recommendation, "
            "guarantee of control, or substitute for local scouting and threshold guidance."
        ),
    },
    "diagnostic_lab_and_sample_quality": {
        "tool": "diagnostic_lab_and_sample_quality",
        "source_lane_id": "diagnostic_lab_and_sample_quality",
        "source_name": "Diagnostic lab and sample-quality lane",
        "provider": "Land-grant plant diagnostic and soil/plant testing labs",
        "source_urls": ["https://www.npdn.org/"],
        "status": "source_lane_available",
        "coverage": "Diagnostic sampling, lab method, chain of custody, symptom pattern, and uncertainty boundaries.",
        "decision_checks": [
            "representative affected and unaffected plants, roots, soil, tissue, or water samples as appropriate",
            "symptom distribution, field pattern, recent weather, products used, crop stage, and management history",
            "sample timing, packaging, preservation, lab method, requested test, and chain-of-custody notes",
            "distinguish diagnosis from visual suspicion, nutrient stress, herbicide injury, pest injury, and abiotic stress",
            "hold irreversible product or rate decisions until diagnostic confidence and local guidance are adequate",
        ],
        "boundary": (
            "This source card frames diagnostic evidence. It does not identify a pathogen, confirm a nutrient problem, "
            "or replace a qualified lab result or local specialist diagnosis."
        ),
    },
    "pesticide_safety_and_drift_recordkeeping": {
        "tool": "pesticide_safety_and_drift_recordkeeping",
        "source_lane_id": "pesticide_safety_and_drift_recordkeeping",
        "source_name": "Pesticide safety, drift, and recordkeeping lane",
        "provider": "EPA, PMRA, and extension pesticide-safety programs",
        "source_urls": ["https://www.epa.gov/pesticide-labels/pesticide-product-label-system-ppls-application-program-interface-api"],
        "status": "source_lane_available",
        "coverage": "Label, PPE, REI, PHI, buffers, drift risk, sensitive areas, storage, disposal, and application records.",
        "decision_checks": [
            "exact product, registration number, crop/site, pest, rate range, application method, and current label",
            "wind speed/direction, inversion risk, nozzle/droplet class, boom height, buffers, and downwind sensitive areas",
            "PPE, REI, PHI, worker notification, water protection, endangered species, storage, disposal, and mixing rules",
            "application record with date/time, field, applicator, product, rate, weather, equipment, and observed issues",
            "local legal label review before any product, rate, tank mix, or timing recommendation",
        ],
        "boundary": (
            "This source card is a pesticide-safety checklist. It is not legal label interpretation, local approval, "
            "exact rate advice, or a guarantee that an application is safe or compliant."
        ),
    },
    "seed_quality_and_trait_stewardship": {
        "tool": "seed_quality_and_trait_stewardship",
        "source_lane_id": "seed_quality_and_trait_stewardship",
        "source_name": "Seed quality and trait stewardship lane",
        "provider": "Public seed-quality, extension, and trait-stewardship guidance",
        "source_urls": ["https://www.croptesting.iastate.edu/"],
        "status": "source_lane_available",
        "coverage": "Seed germination, vigor, lot quality, maturity, local trials, trait stewardship, refuge, and rotation boundaries.",
        "decision_checks": [
            "seed lot germination, vigor, seed treatment, storage, seed size, planting conditions, and stand target",
            "local multi-year/multi-location public trial fit by maturity, soil, irrigation, disease, lodging, and quality traits",
            "trait package, refuge or stewardship requirements, herbicide technology, resistance-management, and label fit",
            "avoid ranking products without local replicated evidence, availability, price, risk tolerance, and adviser input",
            "follow-up stand counts, emergence uniformity, and cause-of-loss diagnosis before replant or blame assignment",
        ],
        "boundary": (
            "This source card frames seed and trait evidence. It is not a product endorsement, yield guarantee, refuge "
            "compliance ruling, or substitute for seed-company and local trial documentation."
        ),
    },
    "produce_safety_and_irrigation_water": {
        "tool": "produce_safety_and_irrigation_water",
        "source_lane_id": "produce_safety_and_irrigation_water",
        "source_name": "Produce safety and irrigation-water lane",
        "provider": "Produce safety alliance, FDA FSMA, and extension produce-safety programs",
        "source_urls": ["https://www.fda.gov/food/food-safety-modernization-act-fsma/fsma-final-rule-produce-safety"],
        "status": "source_lane_available",
        "coverage": "Produce-safety water source, testing, timing, postharvest handling, wildlife, soil amendments, and worker hygiene checks.",
        "decision_checks": [
            "crop, edible portion, irrigation method, water source, timing to harvest, and contact with harvestable tissue",
            "water test history, sampling point, generic E. coli or required microbial indicator, and corrective action plan",
            "wildlife, flooding, adjacent land use, manure/compost, worker hygiene, harvest tools, and wash-water controls",
            "separate agronomic irrigation advice from food-safety plan, audit, market, and legal compliance decisions",
            "local produce-safety specialist review before making harvest, treatment, or marketability claims",
        ],
        "boundary": (
            "This source card frames produce-safety evidence. It is not a food-safety plan, legal compliance ruling, "
            "water-quality clearance, or market-acceptance decision."
        ),
    },
    "precision_ag_audit_and_trial_design": {
        "tool": "precision_ag_audit_and_trial_design",
        "source_lane_id": "precision_ag_audit_and_trial_design",
        "source_name": "Precision-ag audit and trial-design lane",
        "provider": "Extension precision-ag and on-farm research programs",
        "source_urls": ["https://www.extension.iastate.edu/agdm/wholefarm/html/c5-07.html"],
        "status": "source_lane_available",
        "coverage": "Yield-monitor cleanup, field-record alignment, prescription audit, check strips, replication, and trial interpretation.",
        "decision_checks": [
            "clean yield monitor data for calibration, moisture, swath/pass artifacts, edges, delays, and outliers",
            "align boundary, years, hybrids/varieties, soil zones, as-applied layers, weather, and scouting records",
            "include replicated strips, randomization or paired comparisons, buffer rules, and harvest data quality checks",
            "separate correlation from treatment response and include economics, operational risk, and uncertainty",
            "document prescription version, assumptions, reviewer, and post-season closeout before scaling a practice",
        ],
        "boundary": (
            "This source card frames precision-ag evidence quality. It does not validate proprietary files, prove response, "
            "create a prescription, or replace a statistically sound on-farm trial."
        ),
    },
    "public_statistics_context_boundary": {
        "tool": "public_statistics_context_boundary",
        "source_lane_id": "public_statistics_context_boundary",
        "source_name": "Public statistics context-boundary lane",
        "provider": "USDA NASS, Statistics Canada, and public agricultural statistics programs",
        "source_urls": ["https://quickstats.nass.usda.gov/api", "https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210035901"],
        "status": "source_lane_available",
        "coverage": "Regional crop statistics, suppression, aggregation, date, geography, and field-specific boundary checks.",
        "decision_checks": [
            "statistic, year, commodity, class, practice, unit, county/state/province, source, and publication date",
            "aggregation, suppression, sampling error, census/survey difference, and missing county or crop categories",
            "avoid treating regional averages as field yield prediction, crop-insurance evidence, or acreage proof",
            "pair public statistics with field records, soil/weather context, and local adviser interpretation for decisions",
            "state when a public statistic is unavailable, outdated, suppressed, or not comparable to the user's field",
        ],
        "boundary": (
            "This source card frames public statistics. It is not a field prediction, market forecast, insurance record, "
            "grower record, or proof of what happened inside a specific boundary."
        ),
    },
    "cross_border_crop_history_public_layers": {
        "tool": "cross_border_crop_history_public_layers",
        "source_lane_id": "cross_border_crop_history_public_layers",
        "source_name": "Cross-border crop-history public-layers lane",
        "provider": "USDA CDL, AAFC Annual Crop Inventory, and public land-cover programs",
        "source_urls": ["https://www.nass.usda.gov/Research_and_Science/Cropland/", "https://agriculture.canada.ca/atlas/aci/"],
        "status": "source_lane_available",
        "coverage": "U.S./Canada crop-cover source selection, resolution, mixed pixels, year availability, and crop-history boundaries.",
        "decision_checks": [
            "choose CDL for U.S. fields and AAFC Annual Crop Inventory for Canadian fields before interpreting crop history",
            "record year, resolution, confidence, mixed pixels, boundary sampling method, and unavailable years",
            "avoid using crop-cover classes as grower planting records, acreage accounting, or crop-insurance evidence",
            "ask for grower records when rotation, herbicide carryover, disease risk, or compliance depends on field truth",
            "show source availability and jurisdiction explicitly when a boundary crosses or sits near a border",
        ],
        "boundary": (
            "This source card frames crop-cover public layers. It is not verified field history, acreage proof, or "
            "a substitute for grower records and local source availability checks."
        ),
    },
    "source_availability_and_tool_choice": {
        "tool": "source_availability_and_tool_choice",
        "source_lane_id": "source_availability_and_tool_choice",
        "source_name": "Source availability and tool-choice lane",
        "provider": "Open Agronomy Agent source-orchestration checklist",
        "source_urls": [],
        "status": "source_lane_available",
        "coverage": "Which public sources are applicable, unavailable, key-gated, jurisdiction-specific, or insufficient for the request.",
        "decision_checks": [
            "identify geometry, jurisdiction, crop, decision type, and which public source lanes are relevant",
            "separate live adapters, key-gated adapters, deterministic source cards, monitor/planned lanes, and missing data",
            "state why a source was not used, unavailable, outside coverage, or not enough for a field-specific conclusion",
            "avoid filling unavailable public facts with model memory or generic agronomy prose",
            "ask for field records, labels, lab tests, scouting, or local adviser input when public context is insufficient",
        ],
        "boundary": (
            "This source card audits tool choice and source availability. It is not proof that every relevant public "
            "source was queried live, and it does not turn public priors into field truth."
        ),
    },
    "forage_feed_safety_extension": {
        "tool": "forage_feed_safety_extension",
        "source_lane_id": "forage_feed_safety_extension",
        "source_name": "Forage and feed-safety extension lane",
        "provider": "Land-grant forage, feed, and livestock safety extension programs",
        "source_urls": [],
        "status": "source_lane_available",
        "coverage": "Forage toxicity, nitrate/prussic acid, mycotoxin, regrowth, grazing timing, feed tests, and livestock safety.",
        "decision_checks": [
            "forage species, growth stage, frost/drought/manure stress, harvest interval, regrowth, and animal class",
            "nitrate, prussic-acid, mycotoxin, moisture, and feed-test evidence before feeding or grazing high-risk forage",
            "product label, grazing restriction, withdrawal, and residue boundaries when pesticides or herbicides were used",
            "separate agronomic forage management from veterinary advice, ration formulation, and feed clearance",
            "local extension, veterinarian, or nutritionist review when animal-health risk is plausible",
        ],
        "boundary": (
            "This source card frames forage and feed-safety evidence. It is not veterinary advice, feed-test clearance, "
            "ration formulation, or a guarantee of animal safety."
        ),
    },
    "postharvest_quality_storage_mycotoxin": {
        "tool": "postharvest_quality_storage_mycotoxin",
        "source_lane_id": "postharvest_quality_storage_mycotoxin",
        "source_name": "Postharvest quality, storage, and mycotoxin lane",
        "provider": "Extension grain quality and Crop Protection Network resources",
        "source_urls": [
            "https://www.extension.iastate.edu/grain/tips-handling-drying-and-storing-damaged-grain",
            "https://cropprotectionnetwork.org/publications/storing-mycotoxin-affected-grain",
        ],
        "status": "source_lane_available",
        "coverage": "Drying, cooling, aeration, storage monitoring, damaged grain, quality testing, segregation, and mycotoxin boundaries.",
        "decision_checks": [
            "crop, harvest moisture, damage, weather delay, test weight, grain temperature, and storage duration",
            "drying target, cooling schedule, aeration, bin monitoring, and spoilage or insect-risk indicators",
            "mycotoxin and quality testing before blending, feeding, shipping, or marketing high-risk grain",
            "segregation, documentation, elevator/feed/insurance requirements, and worker-safety hazards",
            "local grain-quality specialist, lab, buyer, or insurer review before marketability or feed-safety claims",
        ],
        "boundary": (
            "This source card frames storage and mycotoxin evidence. It is not a grain marketing decision, feed-safety "
            "clearance, insurance adjustment, or substitute for testing and buyer requirements."
        ),
    },
    "farm_economics_sensitivity_and_programs": {
        "tool": "farm_economics_sensitivity_and_programs",
        "source_lane_id": "farm_economics_sensitivity_and_programs",
        "source_name": "Farm economics sensitivity and public-program lane",
        "provider": "Extension farm management and public program guidance",
        "source_urls": ["https://www.extension.iastate.edu/agdm/wholefarm/html/c1-50.html", "https://www.farmers.gov/conservation"],
        "status": "source_lane_available",
        "coverage": "Partial budget sensitivity, break-even ranges, adoption risk, cost-share boundaries, and public program eligibility cautions.",
        "decision_checks": [
            "baseline practice, proposed change, added returns, reduced costs, added costs, and reduced returns",
            "yield, price, input cost, machinery, labor, risk, adoption, and one-time versus recurring costs as ranges",
            "break-even thresholds and sensitivity before claiming a practice pays or should be adopted",
            "program eligibility, sign-up, approval, payment, compliance, and maintenance kept separate from agronomic fit",
            "farm records, local office, lender/tax/legal adviser, or program administrator review where relevant",
        ],
        "boundary": (
            "This source card frames economics and program evidence. It is not financial, tax, legal, eligibility, or "
            "payment advice, and it does not prove profitability without farm-specific records."
        ),
    },
}
PUBLIC_SOURCE_LANE_DEFINITIONS.update(DEEP_PUBLIC_SOURCE_LANE_DEFINITIONS)
MAX_NRCS_GEOMETRY_VERTICES = 500
MAX_NRCS_GEOMETRY_BBOX_SPAN_DEGREES = 1.5
MAX_CDL_GEOMETRY_VERTICES = 500
MAX_CDL_GEOMETRY_BBOX_SPAN_DEGREES = 1.5
DEFAULT_CDL_GEOMETRY_YEARS = 3
DEFAULT_CDL_SAMPLE_POINTS = 9
AAFC_ACI_CODE_LABELS: dict[int, str] = {
    10: "Cloud", 20: "Water", 30: "Exposed land/barren", 34: "Urban/developed", 35: "Greenhouses",
    50: "Shrubland", 60: "Forest fire/burnt area", 80: "Wetland", 85: "Peatland", 110: "Grassland",
    120: "Agriculture (undifferentiated)", 121: "Cropland", 122: "Pasture/forages", 130: "Too wet to be seeded",
    131: "Fallow", 132: "Cereals", 133: "Barley", 134: "Other grains", 135: "Millet", 136: "Oats",
    137: "Rye", 138: "Spelt", 139: "Triticale", 140: "Wheat", 141: "Switchgrass", 142: "Sorghum",
    143: "Quinoa", 145: "Winter wheat", 146: "Spring wheat", 147: "Corn for grain", 148: "Tobacco",
    149: "Ginseng", 150: "Oilseeds", 151: "Borage", 152: "Camelina", 153: "Canola/rapeseed",
    154: "Flaxseed", 155: "Mustard", 156: "Safflower", 157: "Sunflower", 158: "Soybeans",
    159: "Other oilseeds", 160: "Pulses", 161: "Other pulses", 162: "Peas", 163: "Chickpeas",
    167: "Beans", 168: "Fababeans", 174: "Lentils", 175: "Vegetables", 176: "Tomatoes", 177: "Potatoes",
    178: "Sugarbeets", 179: "Other vegetables", 180: "Fruits", 181: "Berries", 182: "Blueberry",
    183: "Cranberry", 185: "Other berries", 188: "Orchards", 189: "Other fruits", 190: "Vineyards",
    191: "Hops", 192: "Sod", 193: "Herbs", 194: "Nursery", 195: "Buckwheat", 196: "Canaryseed",
    197: "Hemp", 198: "Vetch", 199: "Other crops", 200: "Forest (undifferentiated)",
    210: "Coniferous forest", 220: "Broadleaf forest", 230: "Mixedwood forest",
}
CDL_CODE_LABELS: dict[int, str] = {
    0: "Background",
    1: "Corn",
    2: "Cotton",
    3: "Rice",
    4: "Sorghum",
    5: "Soybeans",
    6: "Sunflower",
    10: "Peanuts",
    11: "Tobacco",
    12: "Sweet Corn",
    13: "Pop or Orn Corn",
    14: "Mint",
    21: "Barley",
    22: "Durum Wheat",
    23: "Spring Wheat",
    24: "Winter Wheat",
    25: "Other Small Grains",
    26: "Dbl Crop WinWht/Soybeans",
    27: "Rye",
    28: "Oats",
    29: "Millet",
    31: "Canola",
    36: "Alfalfa",
    37: "Other Hay/Non Alfalfa",
    41: "Sugarbeets",
    42: "Dry Beans",
    43: "Potatoes",
    44: "Other Crops",
    54: "Tomatoes",
    59: "Sod/Grass Seed",
    61: "Fallow/Idle Cropland",
    63: "Forest",
    64: "Shrubland",
    81: "Clouds/No Data",
    82: "Developed",
    83: "Water",
    87: "Wetlands",
    88: "Nonag/Undefined",
    111: "Open Water",
    112: "Perennial Ice/Snow",
    121: "Developed/Open Space",
    122: "Developed/Low Intensity",
    123: "Developed/Med Intensity",
    124: "Developed/High Intensity",
    131: "Barren",
    141: "Deciduous Forest",
    142: "Evergreen Forest",
    143: "Mixed Forest",
    152: "Shrubland",
    176: "Grassland/Pasture",
    190: "Woody Wetlands",
    195: "Herbaceous Wetlands",
}


def json_ready(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def route_question(question: str) -> dict[str, Any]:
    route = classify_query(question)
    return {
        "tool": "route",
        "question": question,
        "route": {
            "question_type": route.question_type,
            "risk_level": route.risk_level,
            "namespaces": sorted(route.namespaces),
            "required_tools": sorted(route.required_tools),
            "query_expansion": sorted(route.query_expansion),
            "answer_style": route.answer_style,
            "audience": route.audience,
            "guidance": route.guidance,
        },
    }


def retrieve_context(question: str, top_k: int = 5, rag_config: str = "configs/rag_governed_runtime_v2.yaml") -> dict[str, Any]:
    resources = load_agent_resources(rag_config)
    context = build_context(question, resources=resources)
    return {
        "tool": "retrieve_context",
        "question": question,
        "route": {
            "question_type": context.route.question_type,
            "risk_level": context.route.risk_level,
            "namespaces": sorted(context.route.namespaces),
            "required_tools": sorted(context.route.required_tools),
        },
        "answer_coverage_checklist": list(context.coverage_checklist),
        "tool_notes": [asdict(note) for note in context.tool_notes],
        "retrieved_docs": [
            {
                "rank": idx,
                "doc_id": doc.doc_id,
                "title": doc.title,
                "source_type": doc.source_type,
                "score": round(doc.score, 4),
                "source": doc.source,
                "text": doc.text[:900],
            }
            for idx, doc in enumerate(context.retrieved_docs[:top_k], start=1)
        ],
        "graph_hits": [
            {
                "rank": idx,
                "node_id": hit.node_id,
                "name": hit.name,
                "kind": hit.kind,
                "evidence": hit.evidence,
                "neighbors": hit.neighbors[:8],
                "namespaces": hit.namespaces,
                "graph_id": hit.graph_id,
                "graph_version": hit.graph_version,
                "graph_source": hit.graph_source,
                "graph_license": hit.graph_license,
                "graph_sha256": hit.graph_sha256,
                "authority_role": hit.authority_role,
                "relation_paths": hit.relation_paths[:8],
            }
            for idx, hit in enumerate(context.graph_hits[:top_k], start=1)
        ],
    }


def soil_context(question: str, top_k: int = 6) -> dict[str, Any]:
    soil_question = (
        question
        + " soil water climate MLRA ecological site drainage texture parent material frost free precipitation"
    )
    payload = retrieve_context(soil_question, top_k=top_k)
    payload["tool"] = "soil_context"
    payload["note"] = (
        "Use as regional environmental context only. It does not replace a field soil test, SSURGO component lookup, "
        "or local extension calibration."
    )
    return payload


def spray_window(
    wind_mph: float | None = None,
    gust_mph: float | None = None,
    temperature_f: float | None = None,
    rain_hours: float | None = None,
    inversion_risk: str | None = None,
    sensitive_downwind: bool = False,
    operation: str = "spray",
) -> dict[str, Any]:
    flags: list[str] = []
    cautions: list[str] = []
    if wind_mph is not None:
        if wind_mph < 3:
            flags.append("low wind can indicate inversion or poor dispersion risk")
        if wind_mph > 10:
            flags.append("wind speed may exceed many label windows")
    if gust_mph is not None and wind_mph is not None and gust_mph - wind_mph >= 5:
        flags.append("gust spread is high enough to treat drift risk as elevated")
    if temperature_f is not None:
        if temperature_f >= 85:
            cautions.append("warm conditions can increase volatility or crop-stress concerns for some products")
        if temperature_f <= 40:
            cautions.append("cold conditions can reduce activity or increase crop-stress concerns for some products")
    if rain_hours is not None and rain_hours <= 24:
        cautions.append("near-term rainfall may affect rainfast interval, runoff risk, or field trafficability")
    if inversion_risk and inversion_risk.lower() in {"yes", "high", "likely", "true"}:
        flags.append("temperature inversion risk is present")
    if sensitive_downwind:
        flags.append("downwind sensitive crop/site is present")
    decision = "proceed_only_after_label_check"
    if flags:
        decision = "delay_or_no_spray_until_resolved"
    return {
        "tool": "spray_window",
        "operation": operation,
        "decision_frame": decision,
        "blocking_flags": flags,
        "cautions": cautions,
        "required_next_checks": [
            "current local product label",
            "wind speed, direction, and gusts at boom height",
            "temperature inversion likelihood",
            "downwind sensitive crops or sites",
            "rainfast interval and runoff/erosion exposure",
        ],
        "boundary": "This is a label-aware risk screen, not a product-specific legal recommendation.",
    }


def fertility_frame(
    crop: str | None = None,
    yield_goal: float | None = None,
    soil_test_method: str | None = None,
    soil_ph: float | None = None,
    organic_matter_pct: float | None = None,
    manure_or_legume_credit: bool = False,
) -> dict[str, Any]:
    missing = []
    if not crop:
        missing.append("crop")
    if yield_goal is None:
        missing.append("yield goal")
    if not soil_test_method:
        missing.append("soil test method/lab")
    if soil_ph is None:
        missing.append("soil pH")
    if organic_matter_pct is None:
        missing.append("organic matter")
    checks = [
        "recent representative soil sample",
        "soil test method and local calibration",
        "crop and realistic yield goal",
        "previous crop, manure, compost, irrigation water, or other nutrient credits",
        "loss pathway: leaching, denitrification, erosion, runoff, fixation, or volatilization",
        "split timing or placement option when loss risk is high",
    ]
    if soil_ph is not None and soil_ph < 6.0:
        checks.insert(0, "low pH may need lime requirement or buffer pH before nutrient-rate confidence")
    if soil_test_method and re.search(r"\b(bray|olsen|mehlich)\b", soil_test_method, re.I):
        checks.append("do not convert Bray, Olsen, and Mehlich values without local calibration")
    return {
        "tool": "fertility_frame",
        "missing_inputs": missing,
        "manure_or_legume_credit_present": manure_or_legume_credit,
        "decision_checks": checks,
        "rate_boundary": (
            "Use this to shape the answer and ask for missing inputs. Do not convert it into a local fertilizer rate "
            "without jurisdiction-specific calibration."
        ),
    }


def diagnostic_frame(kind: str, context: str = "") -> dict[str, Any]:
    normalized = kind.lower().strip().replace("_", "-")
    frames = {
        "4r": [
            "right source",
            "right rate",
            "right time",
            "right place",
            "soil test and yield goal",
            "manure analysis and manure or legume credit",
            "tile, leaching, runoff, or water-quality risk",
            "records and follow-up evaluation",
        ],
        "pesticide-safety": [
            "current local label",
            "PPE",
            "REI",
            "PHI when relevant",
            "buffer and drift controls",
            "water or sensitive-area protection",
            "storage, handling, disposal, and records",
        ],
        "resistance": [
            "weed species or target pest",
            "field history and previous program",
            "scout surviving escapes",
            "mode/site of action",
            "multiple effective modes of action",
            "nonchemical tactics",
            "current local label",
        ],
        "compaction": [
            "traffic pattern",
            "ponding or infiltration",
            "soil moisture at diagnosis",
            "rooting depth",
            "probe, penetrometer, or soil pit",
            "controlled traffic, targeted tillage, cover crops, or drainage changes",
        ],
        "salinity-sodicity": [
            "soil test",
            "soil EC or salinity test",
            "irrigation-water test",
            "sodium hazard as SAR or ESP",
            "pH where relevant",
            "drainage and leaching feasibility",
            "field pattern",
        ],
    }
    if normalized not in frames:
        raise ValueError(f"unknown diagnostic frame: {kind}")
    return {
        "tool": "diagnostic_frame",
        "kind": normalized,
        "context": context,
        "decision_checks": frames[normalized],
        "boundary": "Use this as a decision checklist. It supplies missing-evidence structure, not field-specific product, rate, or legal advice.",
    }


def cansis_soil_landscapes_canada(
    latitude: float | None = None,
    longitude: float | None = None,
    geometry: dict[str, Any] | None = None,
    crop: str | None = None,
    province: str | None = None,
    cache_dir: str = "outputs/tool_cache/cansis_soil_landscapes",
    timeout: int = 20,
) -> dict[str, Any]:
    if latitude is None or longitude is None:
        payload = _canada_source_lane_context("cansis_soil_landscapes_canada", crop=crop, province=province)
        payload["status"] = "location_required"
        return payload
    if not (-90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180):
        raise ValueError("latitude/longitude out of range")
    cache_path = repo_path(cache_dir) / _safe_name(
        f"cansis_slc_{CANADA_SOIL_LANDSCAPES_CACHE_VERSION}_{float(latitude):.7f}_{float(longitude):.7f}"
    )
    cache_path = cache_path.with_suffix(".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    query = urllib.parse.urlencode({
        "where": "1=1", "geometry": json.dumps({"x": float(longitude), "y": float(latitude), "spatialReference": {"wkid": 4326}}, separators=(",", ":")),
        "geometryType": "esriGeometryPoint", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
        "outFields": "SLC_V31_22_ID,DRAINAGE_CODE,KIND_MATERIAL_CODE,LOCAL_SURFACE_FORM_CODE,SOIL_ORDER_CODE,SOIL_GREAT_GROUP_CODE",
        "returnGeometry": "false", "f": "json",
    })
    request = urllib.request.Request(f"{CANADA_SOIL_LANDSCAPES_URL}/query?{query}", headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        payload = _canada_source_lane_context(
            "cansis_soil_landscapes_canada",
            latitude=latitude,
            longitude=longitude,
            geometry=geometry,
            crop=crop,
            province=province,
        )
        payload.update(
            {
                "status": "unavailable",
                "error_type": exc.__class__.__name__,
                "error": "CanSIS Soil Landscapes is temporarily unavailable; continue with clearly labeled local evidence only.",
                "provenance": "aafc_soil_landscapes_of_canada_feature_service",
            }
        )
        return payload
    if data.get("error"):
        raise RuntimeError(f"CanSIS Soil Landscapes query error: {data['error'].get('message') or data['error']}")
    landscapes = [
        {"slc_id": attrs.get("SLC_V31_22_ID"), "drainage_code": attrs.get("DRAINAGE_CODE"), "material_code": attrs.get("KIND_MATERIAL_CODE"), "surface_form_code": attrs.get("LOCAL_SURFACE_FORM_CODE"), "soil_order": attrs.get("SOIL_ORDER_CODE"), "soil_great_group": attrs.get("SOIL_GREAT_GROUP_CODE")}
        for feature in (data.get("features") or []) if isinstance(feature, dict)
        for attrs in [feature.get("attributes") or {}] if isinstance(attrs, dict)
    ]
    summary = {
        "tool": "cansis_soil_landscapes_canada", "status": "available" if landscapes else "no_records",
        "source": CANADA_SOIL_LANDSCAPES_URL, "cache_hit": False, "latitude": float(latitude), "longitude": float(longitude),
        "source_lane_id": "cansis_soil_landscapes_canada", "source_name": "Soil Landscapes of Canada", "provider": "Agriculture and Agri-Food Canada",
        "coverage": "Canadian broad soil-landscape context from Soil Landscapes of Canada.", "landscape_count": len(landscapes), "landscapes": landscapes[:8],
        "context": {key: value for key, value in {"crop": crop, "province": province, "geometry_type": (geometry or {}).get("type") if isinstance(geometry, dict) else None}.items() if value},
        "decision_checks": list(CANADA_SOURCE_LANE_DEFINITIONS["cansis_soil_landscapes_canada"]["decision_checks"]),
        "boundary": "CanSIS/Soil Landscapes is a broad public soil-landscape prior at the queried point. It does not replace a field soil test, in-field delineation, drainage assessment, management zones, or field truth.",
        "provenance": "aafc_soil_landscapes_of_canada_feature_service",
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def aafc_annual_crop_inventory(
    latitude: float | None = None,
    longitude: float | None = None,
    geometry: dict[str, Any] | None = None,
    crop: str | None = None,
    province: str | None = None,
    year: int = DEFAULT_AAFC_ACI_YEAR,
    sample_points: int = DEFAULT_CDL_SAMPLE_POINTS,
    cache_dir: str = "outputs/tool_cache/aafc_annual_crop_inventory",
    timeout: int = 20,
) -> dict[str, Any]:
    if not 2009 <= int(year) <= dt.datetime.now(dt.UTC).year:
        raise ValueError("AAFC Annual Crop Inventory year must be between 2009 and the current year")
    if geometry is None and (latitude is None or longitude is None):
        payload = _canada_source_lane_context(
            "aafc_annual_crop_inventory", crop=crop, province=province
        )
        payload["status"] = "location_required"
        payload["boundary"] = (
            "AAFC Annual Crop Inventory can provide a public crop-cover classification only for a supplied Canadian "
            "point or field boundary. It is not a grower planting record, acreage proof, crop-insurance evidence, "
            "or verified field history."
        )
        return payload
    if geometry is None:
        geometry = {"type": "Point", "coordinates": [float(longitude), float(latitude)]}
    geometry_type, bbox, vertex_count, points = _sample_geojson_geometry(geometry, max_points=sample_points)
    west, south, east, north = bbox
    if east - west > MAX_CDL_GEOMETRY_BBOX_SPAN_DEGREES or north - south > MAX_CDL_GEOMETRY_BBOX_SPAN_DEGREES:
        raise ValueError("AAFC Annual Crop Inventory geometry query span is too large for local field-context lookup")
    if vertex_count > MAX_CDL_GEOMETRY_VERTICES:
        raise ValueError(f"AAFC Annual Crop Inventory geometry has too many vertices; max is {MAX_CDL_GEOMETRY_VERTICES}")
    samples: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, (sample_lon, sample_lat) in enumerate(points, start=1):
        try:
            result = _aafc_annual_crop_inventory_point(
                latitude=sample_lat,
                longitude=sample_lon,
                year=int(year),
                cache_dir=cache_dir,
                timeout=timeout,
            )
            samples.append({"sample_index": index, **result})
        except Exception as exc:  # noqa: BLE001 - retain partial field evidence when one sample fails.
            errors.append({"sample_index": index, "error_type": exc.__class__.__name__, "error": str(exc)[:220]})
    classified = [sample for sample in samples if sample.get("aci_code") is not None]
    status = "available" if classified else "no_data"
    if classified and errors:
        status = "partial_available"
    sample_summary = _summarize_aafc_aci_samples(classified)
    source = AAFC_ACI_IMAGE_SERVER_TEMPLATE.format(year=int(year))
    return {
        "tool": "aafc_annual_crop_inventory",
        "status": status,
        "source": source,
        "cache_hit": bool(samples) and all(bool(sample.get("cache_hit")) for sample in samples),
        "year": int(year),
        "source_lane_id": "aafc_annual_crop_inventory",
        "source_name": "AAFC Annual Crop Inventory",
        "provider": "Agriculture and Agri-Food Canada",
        "coverage": "Canadian 30 m annual crop-cover and land-cover classification samples.",
        "geometry_type": geometry_type,
        "bbox": [round(value, 7) for value in bbox],
        "vertex_count": vertex_count,
        "sample_point_count": len(points),
        "samples": samples[:80],
        "sample_errors": errors[:20],
        "class_summary": sample_summary,
        "context": {key: value for key, value in {"crop": crop, "province": province}.items() if value},
        "decision_checks": list(CANADA_SOURCE_LANE_DEFINITIONS["aafc_annual_crop_inventory"]["decision_checks"]),
        "boundary": (
            "AAFC Annual Crop Inventory is a 30 m satellite-derived classification sampled across the supplied point "
            "or geometry. Use it as crop-cover/rotation context only; it is not a grower planting record, acreage "
            "accounting, crop-insurance evidence, field-boundary proof, or verified field history."
        ),
        "provenance": "aafc_annual_crop_inventory_public_image_service",
    }


def statcan_field_crop_statistics(
    crop: str | None = None,
    province: str | None = None,
    latest_periods: int = 3,
    cache_dir: str = "outputs/tool_cache/statcan_field_crop_statistics",
    snapshot_path: str = STATCAN_FIELD_CROP_SNAPSHOT_PATH,
    snapshot_manifest_path: str = STATCAN_FIELD_CROP_SNAPSHOT_MANIFEST_PATH,
    offline_only: bool = False,
    timeout: int = 20,
) -> dict[str, Any]:
    crop_key = _normalize_statcan_crop(crop)
    if not crop_key:
        payload = _canada_source_lane_context("statcan_field_crop_statistics", crop=crop, province=province)
        payload["status"] = "crop_required"
        payload["boundary"] = (
            "Statistics Canada regional crop statistics need a supported crop name and optional province before a "
            "published table series can be checked. They are not field-specific yield prediction, market advice, "
            "grower records, or rate recommendations."
        )
        return payload
    province_key = _normalize_statcan_province(province)
    crop_member = STATCAN_CROP_MEMBER_IDS.get(crop_key)
    if crop_member is None:
        payload = _canada_source_lane_context("statcan_field_crop_statistics", crop=crop, province=province)
        payload["status"] = "crop_not_supported"
        payload["supported_crops"] = sorted(STATCAN_CROP_MEMBER_IDS)
        return payload
    latest_count = max(1, min(int(latest_periods), 5))
    cache_path = repo_path(cache_dir) / _safe_name(
        f"statcan_field_crop_{STATCAN_FIELD_CROP_CACHE_VERSION}_{province_key}_{crop_key}_{latest_count}"
    )
    cache_path = cache_path.with_suffix(".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    geography_member = STATCAN_PROVINCE_MEMBER_IDS[province_key]
    requests = [
        {
            "productId": STATCAN_FIELD_CROP_PRODUCT_ID,
            "coordinate": _statcan_coordinate(geography_member, disposition_member, crop_member),
            "latestN": latest_count,
        }
        for disposition_member, _ in STATCAN_FIELD_CROP_STATISTICS.values()
    ]
    endpoint = f"{STATCAN_WDS_BASE_URL}/getDataFromCubePidCoordAndLatestNPeriods"
    network_error: Exception | None = None
    if offline_only:
        response_rows = None
    else:
        try:
            response_rows = _post_json(endpoint, requests, timeout=timeout)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            response_rows = None
            network_error = exc
    if response_rows is None:
        snapshot_payload, snapshot_error = _statcan_snapshot_summary(
            crop_key=crop_key,
            province_key=province_key,
            latest_count=latest_count,
            snapshot_path=snapshot_path,
            snapshot_manifest_path=snapshot_manifest_path,
            fallback_reason="offline_mode" if offline_only else "live_wds_unavailable",
        )
        if snapshot_payload is not None:
            if network_error is not None:
                snapshot_payload["live_error_type"] = network_error.__class__.__name__
            return snapshot_payload
        payload = _canada_source_lane_context(
            "statcan_field_crop_statistics",
            crop=crop,
            province=province,
        )
        payload.update(
            {
                "status": "unavailable",
                "error_type": (
                    network_error.__class__.__name__
                    if network_error is not None
                    else "OfflineSnapshotUnavailable"
                ),
                "error": (
                    "Statistics Canada live data and the verified local snapshot are unavailable; "
                    "do not infer regional statistics from the missing source."
                ),
                "snapshot_error": snapshot_error,
                "offline_only": offline_only,
                "provenance": "statistics_canada_wds_32100359",
            }
        )
        return payload
    statistics = _normalize_statcan_field_crop_response(response_rows, latest_count=latest_count)
    available = [item for item in statistics.values() if item.get("latest")]
    summary = {
        "tool": "statcan_field_crop_statistics",
        "status": "available" if available else "no_records",
        "source": STATCAN_FIELD_CROP_TABLE_URL,
        "source_api": endpoint,
        "cache_hit": False,
        "product_id": STATCAN_FIELD_CROP_PRODUCT_ID,
        "table": "32-10-0359-01",
        "crop": crop_key,
        "province": province_key if province_key != "CANADA" else None,
        "geography": _statcan_geography_label(province_key),
        "latest_periods": latest_count,
        "statistics": statistics,
        "available_statistic_count": len(available),
        "source_lane_id": "statcan_field_crop_statistics",
        "source_name": "Statistics Canada principal field-crop statistics",
        "provider": "Statistics Canada",
        "coverage": "Published national or provincial field-crop area, yield, and production estimates.",
        "access_mode": "live_wds",
        "snapshot_hit": False,
        "decision_checks": list(CANADA_SOURCE_LANE_DEFINITIONS["statcan_field_crop_statistics"]["decision_checks"]),
        "boundary": (
            "Statistics Canada table 32-10-0359-01 provides published regional field-crop estimates. Use it as "
            "regional context only; it is not field-specific yield prediction, a market forecast, grower records, "
            "or a rate recommendation. Check reference period, estimate status, revisions, and local farm records."
        ),
        "provenance": "statistics_canada_wds_32100359",
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def health_canada_pmra_label_search(
    product_term: str | None = None,
    search_kind: str | None = None,
    registration_number: str | int | None = None,
    language: str = "en",
    cache_dir: str = "outputs/tool_cache/pmra_ppid",
    cache_max_age_hours: int = PMRA_PPID_DEFAULT_CACHE_MAX_AGE_HOURS,
    timeout: int = 20,
) -> dict[str, Any]:
    """Fetch public PMRA registry metadata only when an exact Canadian registration number is supplied."""

    language_code = _normalize_pmra_language(language)
    if not 1 <= int(cache_max_age_hours) <= 168:
        raise ValueError("PMRA cache_max_age_hours must be between 1 and 168")
    registration = _normalize_pmra_registration_number(registration_number)
    if registration is None:
        payload = _canada_source_lane_context(
            "health_canada_pmra_label_search",
            product_term=product_term,
            search_kind=search_kind,
            language=language_code,
        )
        payload["status"] = "registration_number_required"
        payload["query_mode"] = "exact_registration_number"
        payload["registration_number"] = None
        payload["language"] = "fr-CA" if language_code == "fr" else "en-CA"
        payload["boundary"] = (
            "Health Canada PMRA PPID can retrieve public registry metadata only after the exact Canadian registration "
            "number is confirmed. Product or ingredient wording alone is not treated as a checked record. PPID metadata "
            "is not legal label interpretation, local approval, exact rate advice, or current-label text."
        )
        return payload

    cache_path = (
        repo_path(cache_dir)
        / f"pmra_ppid_{PMRA_PPID_CACHE_VERSION}_{language_code}_{registration}.json"
    )
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched_at = _parse_utc_datetime(payload.get("fetched_at"))
        if (
            fetched_at is not None
            and payload.get("language_code") == language_code
        ):
            age_seconds = max(
                0.0,
                (dt.datetime.now(dt.UTC) - fetched_at).total_seconds(),
            )
            if age_seconds <= int(cache_max_age_hours) * 60 * 60:
                payload["cache_hit"] = True
                payload["cache_fresh"] = True
                payload["cache_age_seconds"] = round(age_seconds, 3)
                return payload

    product_url = (
        f"{PMRA_PPID_EXTRACT_BASE_URL}/product/{registration}?lang={language_code}"
    )
    label_url = (
        f"{PMRA_PPID_EXTRACT_BASE_URL}/label/{registration}?lang={language_code}"
    )
    product_rows = _read_pmra_csv(product_url, timeout=timeout)
    label_rows = _read_pmra_csv(label_url, timeout=timeout)
    products = [
        _normalize_pmra_product_row(row, language=language_code)
        for row in product_rows
    ]
    labels = [
        _normalize_pmra_label_row(row, language=language_code)
        for row in label_rows
    ]
    fetched_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    summary = {
        "tool": "health_canada_pmra_label_search",
        "status": "available" if products else "no_product_record",
        "source": product_url,
        "source_urls": [product_url, label_url],
        "source_catalog_url": PMRA_PPID_OPEN_DATA_URL,
        "cache_hit": False,
        "cache_fresh": True,
        "cache_max_age_hours": int(cache_max_age_hours),
        "fetched_at": fetched_at.isoformat(),
        "query_mode": "exact_registration_number",
        "registration_number": registration,
        "language_code": language_code,
        "language": "fr-CA" if language_code == "fr" else "en-CA",
        "product_record_count": len(products),
        "label_record_count": len(labels),
        "products": products[:5],
        "labels": labels[:10],
        "source_lane_id": "health_canada_pmra_label_search",
        "source_name": "Health Canada PMRA Pesticide Product Information Database",
        "provider": "Health Canada PMRA",
        "coverage": "Public Canadian pesticide registry metadata and label-record availability for an exact registration number.",
        "license": {
            "identifier": "Open Government Licence - Canada 2.0",
            "url": "https://open.canada.ca/en/open-government-licence-canada",
            "catalog_record": PMRA_PPID_OPEN_DATA_URL,
        },
        "decision_checks": list(CANADA_SOURCE_LANE_DEFINITIONS["health_canada_pmra_label_search"]["decision_checks"]),
        "boundary": CANADA_SOURCE_LANE_DEFINITIONS["health_canada_pmra_label_search"]["boundary"],
        "provenance": "health_canada_pmra_ppid_api",
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(cache_path)
    return summary


def canada_et_or_water_use_source_needed(
    latitude: float | None = None,
    longitude: float | None = None,
    crop: str | None = None,
    province: str | None = None,
    geometry: dict[str, Any] | None = None,
    indicators: tuple[str, ...] = ("spi", "spei", "temperature_anomaly", "percent_of_average_precipitation"),
    time_window: str | None = None,
    sample_points: int = 1,
    cache_dir: str = "outputs/tool_cache/aafc_nasdi_agroclimate",
    timeout: int = 20,
    offline_only: bool = False,
) -> dict[str, Any]:
    payload = aafc_nasdi_agroclimate(
        latitude=latitude,
        longitude=longitude,
        geometry=geometry,
        crop=crop,
        province=province,
        indicators=indicators,
        time_window=time_window,
        sample_points=sample_points,
        cache_dir=cache_dir,
        timeout=timeout,
        offline_only=offline_only,
    )
    return {
        **payload,
        "tool": "canada_et_or_water_use_source_needed",
        "source_lane_id": "canada_et_or_water_use_source_needed",
        "canonical_tool": "aafc_nasdi_agroclimate",
    }


def aafc_nasdi_agroclimate(
    latitude: float | None = None,
    longitude: float | None = None,
    geometry: dict[str, Any] | None = None,
    crop: str | None = None,
    province: str | None = None,
    indicators: tuple[str, ...] = ("spi", "spei", "temperature_anomaly", "percent_of_average_precipitation"),
    time_window: str | None = None,
    sample_points: int = 1,
    cache_dir: str = "outputs/tool_cache/aafc_nasdi_agroclimate",
    timeout: int = 20,
    now: dt.datetime | None = None,
    offline_only: bool = False,
) -> dict[str, Any]:
    definition = CANADA_SOURCE_LANE_DEFINITIONS["canada_et_or_water_use_source_needed"]
    clean_indicators = tuple(dict.fromkeys(str(value).strip().lower() for value in indicators if str(value).strip()))
    unknown = sorted(set(clean_indicators) - set(AAFC_NASDI_INDICATORS))
    if unknown:
        raise ValueError(f"unsupported AAFC NASDI indicator(s): {', '.join(unknown)}")
    if not clean_indicators:
        raise ValueError("at least one AAFC NASDI indicator is required")
    if len(clean_indicators) > len(AAFC_NASDI_INDICATORS):
        raise ValueError("too many AAFC NASDI indicators")
    requested_time_window = str(time_window).strip().lower() if time_window is not None else None
    allowed_windows = {*AAFC_NASDI_WEEKLY_WINDOWS, *AAFC_NASDI_MONTHLY_WINDOWS}
    if requested_time_window is not None and requested_time_window not in allowed_windows:
        raise ValueError(f"unsupported AAFC NASDI time window: {requested_time_window}")
    indicator_time_windows = {
        indicator: requested_time_window or AAFC_NASDI_INDICATORS[indicator]["default_time_window"]
        for indicator in clean_indicators
    }
    distinct_windows = sorted(set(indicator_time_windows.values()))
    profile_time_window = distinct_windows[0] if len(distinct_windows) == 1 else "mixed"
    sample_points = int(sample_points)
    if not 1 <= sample_points <= 5:
        raise ValueError("AAFC NASDI geometry sampling supports between one and five points")
    if geometry is None and (latitude is None or longitude is None):
        payload = _canada_source_lane_context("canada_et_or_water_use_source_needed", crop=crop, province=province)
        payload.update(
            {
                "tool": "aafc_nasdi_agroclimate",
                "source_lane_id": "aafc_nasdi_agroclimate",
                "status": "location_required",
                "time_window": profile_time_window,
                "indicator_time_windows": indicator_time_windows,
                "indicators": list(clean_indicators),
                "boundary": "AAFC NASDI can return dated regional grid-cell context only for a supplied Canadian point or boundary.",
            }
        )
        return payload
    if geometry is None:
        geometry = {"type": "Point", "coordinates": [float(longitude), float(latitude)]}
    geometry_type, bbox, vertex_count, points = _sample_geojson_geometry(geometry, max_points=sample_points)
    west, south, east, north = bbox
    if east - west > MAX_CDL_GEOMETRY_BBOX_SPAN_DEGREES or north - south > MAX_CDL_GEOMETRY_BBOX_SPAN_DEGREES:
        raise ValueError("AAFC NASDI geometry query span is too large for local field-context lookup")
    if vertex_count > MAX_CDL_GEOMETRY_VERTICES:
        raise ValueError(f"AAFC NASDI geometry has too many vertices; max is {MAX_CDL_GEOMETRY_VERTICES}")
    for sample_lon, sample_lat in points:
        _validate_canadian_nasdi_point(latitude=sample_lat, longitude=sample_lon)

    observations: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for indicator in clean_indicators:
        indicator_time_window = indicator_time_windows[indicator]
        try:
            catalog_item = _aafc_nasdi_latest_catalog_item(
                indicator=indicator,
                time_window=indicator_time_window,
                cache_dir=cache_dir,
                timeout=timeout,
                offline_only=offline_only,
            )
        except Exception as exc:  # noqa: BLE001 - preserve partial evidence across independent official layers.
            errors.append({"indicator": indicator, "stage": "catalog", "error_type": exc.__class__.__name__, "error": str(exc)[:220]})
            continue
        for index, (sample_lon, sample_lat) in enumerate(points, start=1):
            try:
                observation = _aafc_nasdi_identify_point(
                    indicator=indicator,
                    time_window=indicator_time_window,
                    catalog_item=catalog_item,
                    latitude=sample_lat,
                    longitude=sample_lon,
                    cache_dir=cache_dir,
                    timeout=timeout,
                    offline_only=offline_only,
                )
                observations.append({"sample_index": index, **observation})
            except Exception as exc:  # noqa: BLE001 - retain other indicator and point results.
                errors.append({
                    "indicator": indicator,
                    "sample_index": index,
                    "stage": "identify",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc)[:220],
                })
    usable = [item for item in observations if item.get("value") is not None]
    status = "available" if usable else ("unavailable" if errors else "no_data")
    if usable and errors:
        status = "partial_available"
    current = now or dt.datetime.now(dt.UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.UTC)
    indicator_summary = _summarize_aafc_nasdi_observations(usable)
    end_dates = [dt.date.fromisoformat(str(item["observation_end"])) for item in usable if item.get("observation_end")]
    newest_end = max(end_dates) if end_dates else None
    data_age_days = (current.date() - newest_end).days if newest_end else None
    stale_after_days = 62 if all(window.endswith("m") for window in distinct_windows) else 21
    freshness_status = "current" if data_age_days is not None and data_age_days <= stale_after_days else "stale_or_unknown"
    source_services = sorted({str(item.get("source")) for item in usable if item.get("source")})
    return {
        "tool": "aafc_nasdi_agroclimate",
        "status": status,
        "source": AAFC_NASDI_OPEN_DATA_URL,
        "source_services": source_services,
        "cache_hit": bool(observations) and all(bool(item.get("cache_hit")) for item in observations),
        "offline_only": offline_only,
        "network": {
            "mode": "offline" if offline_only else "online",
            "external_calls_attempted": 0 if offline_only else None,
            "declaration": (
                "Offline mode used local cache entries only; no external request was made."
                if offline_only
                else "Online mode may query the official AAFC NASDI image service."
            ),
        },
        "source_lane_id": "aafc_nasdi_agroclimate",
        "source_name": definition["source_name"],
        "provider": definition["provider"],
        "coverage": definition["coverage"],
        "license": "Open Government Licence - Canada",
        "geometry_type": geometry_type,
        "bbox": [round(value, 7) for value in bbox],
        "vertex_count": vertex_count,
        "sample_point_count": len(points),
        "sample_method": "representative grid-cell point sample" if geometry_type != "Point" else "grid-cell point sample",
        "time_window": profile_time_window,
        "time_window_kind": "mixed" if profile_time_window == "mixed" else ("weekly" if profile_time_window.endswith("w") else "monthly"),
        "indicator_time_windows": indicator_time_windows,
        "indicators": list(clean_indicators),
        "observation_end": newest_end.isoformat() if newest_end else None,
        "data_age_days": data_age_days,
        "freshness_status": freshness_status,
        "indicator_summary": indicator_summary,
        "observations": observations[:20],
        "sample_errors": errors[:20],
        "context": {key: value for key, value in {"crop": crop, "province": province}.items() if value},
        "decision_checks": list(definition["decision_checks"]),
        "boundary": definition["boundary"],
        "provenance": "aafc_nasdi_public_image_service_locked_catalog_raster",
    }


def disease_risk_context_adapter(
    crop: str | None = None,
    disease_or_symptom: str | None = None,
    region: str | None = None,
    weather_window: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "disease_risk_context_adapter",
        crop=crop,
        disease_or_symptom=disease_or_symptom,
        region=region,
        weather_window=weather_window,
    )


def public_variety_trial_ingest(
    crop: str | None = None,
    region: str | None = None,
    maturity_or_market_class: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "public_variety_trial_ingest",
        crop=crop,
        region=region,
        maturity_or_market_class=maturity_or_market_class,
    )


def specialty_crop_extension_corpus(
    crop: str | None = None,
    region: str | None = None,
    production_system: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "specialty_crop_extension_corpus",
        crop=crop,
        region=region,
        production_system=production_system,
    )


def conservation_practice_context_adapter(
    resource_concern: str | None = None,
    region: str | None = None,
    practice: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "conservation_practice_context_adapter",
        resource_concern=resource_concern,
        region=region,
        practice=practice,
    )


def canada_conservation_practice_context_source(
    province: str | None = None,
    resource_concern: str | None = None,
    practice: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "canada_conservation_practice_context_source",
        province=province,
        resource_concern=resource_concern,
        practice=practice,
    )


def field_record_audit_card(
    crop: str | None = None,
    record_type: str | None = None,
    decision: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "field_record_audit_card",
        crop=crop,
        record_type=record_type,
        decision=decision,
    )


def partial_budget_calculator(
    proposed_change: str | None = None,
    crop: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "partial_budget_calculator",
        proposed_change=proposed_change,
        crop=crop,
        region=region,
    )


def agronomic_calculator_tool(operation: str, inputs: dict[str, Any]) -> dict[str, Any]:
    """Run offline arithmetic from an explicit, validated input schema."""

    return agronomic_calculator(operation, inputs)


def public_program_context_source(
    program_area: str | None = None,
    jurisdiction: str | None = None,
    practice: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "public_program_context_source",
        program_area=program_area,
        jurisdiction=jurisdiction,
        practice=practice,
    )


def forage_livestock_extension_corpus(
    forage: str | None = None,
    livestock_class: str | None = None,
    stress_event: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "forage_livestock_extension_corpus",
        forage=forage,
        livestock_class=livestock_class,
        stress_event=stress_event,
    )


def postharvest_storage_quality_corpus(
    crop: str | None = None,
    quality_concern: str | None = None,
    storage_duration: str | None = None,
) -> dict[str, Any]:
    return _public_source_lane_context(
        "postharvest_storage_quality_corpus",
        crop=crop,
        quality_concern=quality_concern,
        storage_duration=storage_duration,
    )


def public_source_lane_card(source_lane_id: str, **context: Any) -> dict[str, Any]:
    if source_lane_id not in PUBLIC_SOURCE_LANE_DEFINITIONS:
        raise ValueError(f"unknown public source lane: {source_lane_id}")
    return _public_source_lane_context(source_lane_id, **context)


def nasa_power_daily(
    latitude: float,
    longitude: float,
    start: str,
    end: str,
    parameters: tuple[str, ...] = DEFAULT_POWER_PARAMETERS,
    cache_dir: str = "outputs/tool_cache/nasa_power",
    timeout: int = 20,
) -> dict[str, Any]:
    _validate_date(start)
    _validate_date(end)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude/longitude out of range")
    params = ",".join(parameters)
    query = urllib.parse.urlencode(
        {
            "parameters": params,
            "community": "AG",
            "longitude": longitude,
            "latitude": latitude,
            "start": start,
            "end": end,
            "format": "JSON",
            "time-standard": "UTC",
        }
    )
    url = f"https://power.larc.nasa.gov/api/temporal/daily/point?{query}"
    cache_path = repo_path(cache_dir) / (_safe_name(f"{latitude}_{longitude}_{start}_{end}_{params}") + ".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    request = urllib.request.Request(url, headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    series = data.get("properties", {}).get("parameter", {})
    summary = {
        "tool": "nasa_power_daily",
        "source": url,
        "cache_hit": False,
        "latitude": latitude,
        "longitude": longitude,
        "start": start,
        "end": end,
        "parameters": list(parameters),
        "parameter_summary": _summarize_power_series(series),
        "boundary": "NASA POWER is gridded weather/agroclimatology support, not a replacement for field sensors or local forecast advisories.",
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def daymet_single_pixel_daily(
    latitude: float,
    longitude: float,
    start: str,
    end: str,
    variables: tuple[str, ...] = DEFAULT_DAYMET_VARIABLES,
    cache_dir: str = "outputs/tool_cache/daymet",
    timeout: int = 20,
) -> dict[str, Any]:
    start_date = _validate_iso_date(start)
    end_date = _validate_iso_date(end)
    if end_date < start_date:
        raise ValueError("end must be on or after start")
    if not (14.5 <= latitude <= 52.0 and -131.0 <= longitude <= -53.0):
        raise ValueError("latitude/longitude outside Daymet North America single-pixel bounds")
    max_year = dt.datetime.now(dt.UTC).year - 1
    if start_date.year < 1980 or end_date.year > max_year:
        raise ValueError(f"Daymet date range must be between 1980 and the latest full calendar year ({max_year})")
    clean_vars = tuple(str(item).strip().lower() for item in variables if str(item).strip())
    if not clean_vars:
        raise ValueError("at least one Daymet variable is required")
    query = urllib.parse.urlencode(
        {
            "lat": latitude,
            "lon": longitude,
            "vars": ",".join(clean_vars),
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        }
    )
    url = f"{DAYMET_SINGLE_PIXEL_API_URL}?{query}"
    cache_path = repo_path(cache_dir) / (_safe_name(f"{latitude}_{longitude}_{start_date}_{end_date}_{'_'.join(clean_vars)}") + ".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    request = urllib.request.Request(url, headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    records = _parse_daymet_records(raw)
    summary = {
        "tool": "daymet_single_pixel_daily",
        "status": "available" if records else "no_records",
        "source": url,
        "cache_hit": False,
        "latitude": latitude,
        "longitude": longitude,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "variables": list(clean_vars),
        "record_count": len(records),
        "daily_records": records[:60],
        "variable_summary": _summarize_daymet_records(records, clean_vars),
        "boundary": (
            "ORNL Daymet is a 1 km gridded daily weather and climatology prior. Use it for seasonal, historical, "
            "and water-window context only; it is not a field sensor, current forecast, irrigation prescription, "
            "or substitute for local observations."
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def openet_point_timeseries(
    latitude: float,
    longitude: float,
    start: str,
    end: str,
    interval: str = "monthly",
    model: str = DEFAULT_OPENET_MODEL,
    variable: str = DEFAULT_OPENET_VARIABLE,
    reference_et: str = DEFAULT_OPENET_REFERENCE_ET,
    units: str = DEFAULT_OPENET_UNITS,
    api_key: str | None = None,
    cache_dir: str = "outputs/tool_cache/openet",
    timeout: int = 20,
) -> dict[str, Any]:
    start_date = _validate_iso_date(start)
    end_date = _validate_iso_date(end)
    if end_date < start_date:
        raise ValueError("end must be on or after start")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude/longitude out of range")
    interval_value = str(interval or "").strip().lower()
    if interval_value not in {"daily", "monthly"}:
        raise ValueError("interval must be daily or monthly")
    if start_date.year < 2000:
        raise ValueError("OpenET monthly data starts in 2000; use a start date in 2000 or later")
    if interval_value == "daily" and start_date.year < 2016:
        raise ValueError("OpenET daily data starts in 2016; use monthly for older windows")
    if end_date > dt.datetime.now(dt.UTC).date():
        raise ValueError("OpenET end date cannot be in the future")

    model_value = str(model or DEFAULT_OPENET_MODEL).strip() or DEFAULT_OPENET_MODEL
    variable_value = str(variable or DEFAULT_OPENET_VARIABLE).strip() or DEFAULT_OPENET_VARIABLE
    reference_value = str(reference_et or DEFAULT_OPENET_REFERENCE_ET).strip() or DEFAULT_OPENET_REFERENCE_ET
    units_value = str(units or DEFAULT_OPENET_UNITS).strip() or DEFAULT_OPENET_UNITS
    query = {
        "date_range": [start_date.isoformat(), end_date.isoformat()],
        "interval": interval_value,
        "geometry": [longitude, latitude],
        "model": model_value,
        "variable": variable_value,
        "reference_et": reference_value,
        "units": units_value,
        "file_format": "JSON",
    }
    cache_key = _safe_name(json.dumps(query, sort_keys=True))
    cache_path = repo_path(cache_dir) / f"{cache_key}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload

    resolved_key = _openet_api_key(api_key)
    redacted_query = dict(query)
    if not resolved_key:
        return {
            "tool": "openet_point_timeseries",
            "status": "not_configured",
            "source": OPENET_RASTER_TIMESERIES_POINT_URL,
            "cache_hit": False,
            "required_env_vars": list(OPENET_ENV_VARS),
            "query": redacted_query,
            "latitude": latitude,
            "longitude": longitude,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "interval": interval_value,
            "model": model_value,
            "variable": variable_value,
            "reference_et": reference_value,
            "units": units_value,
            "record_count": 0,
            "records": [],
            "timeseries_summary": {},
            "boundary": (
                "OpenET needs a local API key before live evapotranspiration context can be queried. "
                "When configured, it provides satellite/model ET context for supported coverage areas; it is not a "
                "field sensor, irrigation prescription, water-right accounting record, or substitute for soil-moisture "
                "checks, flowmeter records, crop stage, and local irrigation guidance."
            ),
        }

    request = urllib.request.Request(
        OPENET_RASTER_TIMESERIES_POINT_URL,
        data=json.dumps(query).encode("utf-8"),
        headers={
            "User-Agent": "agronomy-agent-local-tools/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": resolved_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    records = _normalize_openet_records(data, variable_value)
    summary = {
        "tool": "openet_point_timeseries",
        "status": "available" if records else "no_records",
        "source": OPENET_RASTER_TIMESERIES_POINT_URL,
        "cache_hit": False,
        "query": redacted_query,
        "latitude": latitude,
        "longitude": longitude,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "interval": interval_value,
        "model": model_value,
        "variable": variable_value,
        "reference_et": reference_value,
        "units": units_value,
        "record_count": len(records),
        "records": records[:60],
        "timeseries_summary": _summarize_openet_records(records),
        "boundary": (
            "OpenET is a public satellite/model evapotranspiration context layer for supported coverage areas. "
            "Use it to frame crop water demand and irrigation questions only alongside field soil moisture, "
            "flowmeter/applied-water records, crop stage, salinity/drainage risk, and local guidance; it is not a "
            "field sensor, irrigation prescription, water-right accounting record, or guarantee of field truth."
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def nrcs_soil_survey_point(
    latitude: float,
    longitude: float,
    cache_dir: str = "outputs/tool_cache/nrcs_sda",
    timeout: int = 20,
) -> dict[str, Any]:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude/longitude out of range")
    point_wkt = f"point({longitude:.8f} {latitude:.8f})"
    query = (
        "SELECT TOP 8 mu.mukey, mu.musym, mu.muname, l.areasymbol "
        "FROM mapunit AS mu "
        "INNER JOIN legend AS l ON mu.lkey = l.lkey "
        "WHERE mu.mukey IN ("
        f"SELECT mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{point_wkt}')"
        ")"
    )
    cache_path = repo_path(cache_dir) / (_safe_name(f"{latitude}_{longitude}_mapunit") + ".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    data = _post_nrcs_sda(query, timeout=timeout)
    map_units = _normalize_sda_table(data)
    summary = {
        "tool": "nrcs_soil_survey_point",
        "source": NRCS_SDA_POST_REST_URL,
        "cache_hit": False,
        "latitude": latitude,
        "longitude": longitude,
        "query": query,
        "map_units": map_units,
        "boundary": (
            "NRCS Soil Data Access is a soil-survey prior for the point/boundary. It does not replace field "
            "soil tests, scouting, local calibration, or confirmation of the actual management zone."
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def nrcs_soil_survey_geometry(
    geometry: dict[str, Any],
    cache_dir: str = "outputs/tool_cache/nrcs_sda",
    timeout: int = 20,
    max_map_units: int = 12,
    max_components: int = 40,
) -> dict[str, Any]:
    wkt, geometry_type, bbox, vertex_count = _geojson_geometry_to_wkt(geometry)
    west, south, east, north = bbox
    if east - west > MAX_NRCS_GEOMETRY_BBOX_SPAN_DEGREES or north - south > MAX_NRCS_GEOMETRY_BBOX_SPAN_DEGREES:
        raise ValueError("NRCS geometry query span is too large for local field-context lookup")
    if vertex_count > MAX_NRCS_GEOMETRY_VERTICES:
        raise ValueError(f"NRCS geometry query has too many vertices; max is {MAX_NRCS_GEOMETRY_VERTICES}")
    max_map_units = max(1, min(int(max_map_units), 25))
    max_components = max(1, min(int(max_components), 100))
    query = (
        f"SELECT TOP {max_components} mu.mukey, mu.musym, mu.muname, l.areasymbol, "
        "co.cokey, co.compname, co.comppct_r, co.majcompflag, co.slope_r, co.drainagecl, "
        "co.hydgrp, co.hydricrating, co.taxorder, co.taxsubgrp "
        "FROM mapunit AS mu "
        "INNER JOIN legend AS l ON mu.lkey = l.lkey "
        "LEFT JOIN component AS co ON co.mukey = mu.mukey "
        "WHERE mu.mukey IN ("
        f"SELECT TOP {max_map_units} mukey FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}')"
        ") "
        "ORDER BY mu.muname, co.comppct_r DESC"
    )
    cache_key = hashlib.sha256(f"{geometry_type}_{wkt}_{max_map_units}_{max_components}".encode("utf-8")).hexdigest()
    cache_path = repo_path(cache_dir) / f"geometry_{cache_key}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    data = _post_nrcs_sda(query, timeout=timeout)
    rows = _normalize_sda_component_table(data)
    map_units = _group_sda_component_rows(rows)
    summary = {
        "tool": "nrcs_soil_survey_geometry",
        "status": "available" if map_units else "no_records",
        "source": NRCS_SDA_POST_REST_URL,
        "cache_hit": False,
        "geometry_type": geometry_type,
        "bbox": [round(value, 7) for value in bbox],
        "vertex_count": vertex_count,
        "query": query,
        "map_unit_count": len(map_units),
        "component_count": sum(len(unit.get("components") or []) for unit in map_units),
        "map_units": map_units,
        "component_summary": _summarize_sda_components(map_units),
        "boundary": (
            "NRCS Soil Data Access boundary/component results are soil-survey priors for the drawn or uploaded "
            "geometry. They do not prove exact in-field soil conditions, management-zone boundaries, lab soil-test "
            "values, compaction, salinity, drainage performance, or local calibration."
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def epa_ppls_product_search(
    product_name: str | None = None,
    epa_reg_no: str | None = None,
    ingredient_name: str | None = None,
    pc_code: str | None = None,
    cas_number: str | None = None,
    cache_dir: str = "outputs/tool_cache/epa_ppls",
    timeout: int = 20,
) -> dict[str, Any]:
    provided = {
        "product_name": product_name,
        "epa_reg_no": epa_reg_no,
        "ingredient_name": ingredient_name,
        "pc_code": pc_code,
        "cas_number": cas_number,
    }
    populated = {key: value for key, value in provided.items() if value}
    if len(populated) != 1:
        raise ValueError("provide exactly one PPLS search field")
    kind, raw_value = next(iter(populated.items()))
    value = str(raw_value).strip()
    if not value:
        raise ValueError("PPLS search value cannot be empty")
    endpoint = {
        "product_name": "searchWithProductName",
        "epa_reg_no": "searchWithRegNo",
        "ingredient_name": "searchWithIngName",
        "pc_code": "searchWithPcCode",
        "cas_number": "searchWithCasNum",
    }[kind]
    encoded = urllib.parse.quote(value, safe="")
    url = f"{EPA_PPLS_BASE_URL}/{endpoint}/v1/{encoded}"
    cache_path = repo_path(cache_dir) / (_safe_name(f"{EPA_PPLS_CACHE_VERSION}_{kind}_{value}") + ".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    request = urllib.request.Request(url, headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    products = _normalize_ppls_items(data)
    ppls_summary = _summarize_ppls_products(products, search_kind=kind)
    summary = {
        "tool": "epa_ppls_product_search",
        "source": url,
        "cache_hit": False,
        "search_kind": kind,
        "search_value": value,
        "result_count": len(products),
        **ppls_summary,
        "products": products,
        "boundary": (
            "EPA PPLS product metadata can identify registered product records and labels, but it is not a legal "
            "label interpretation, local use approval, rate recommendation, or substitute for reading the current label."
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def cropland_data_layer_point(
    latitude: float,
    longitude: float,
    year: int | None = None,
    cache_dir: str = "outputs/tool_cache/cdl",
    timeout: int = 20,
) -> dict[str, Any]:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude/longitude out of range")
    cdl_year = int(year or _default_cdl_year())
    if cdl_year < 2008 or cdl_year > dt.datetime.now(dt.UTC).year:
        raise ValueError("CDL year must be between 2008 and the current year")
    x_albers, y_albers = _lonlat_to_usgs_conus_albers(longitude=longitude, latitude=latitude)
    query = urllib.parse.urlencode(
        {
            "year": cdl_year,
            "x": f"{x_albers:.3f}",
            "y": f"{y_albers:.3f}",
        }
    )
    url = f"{CROPSCAPE_CDL_VALUE_URL}?{query}"
    cache_path = repo_path(cache_dir) / (_safe_name(f"{cdl_year}_{latitude}_{longitude}") + ".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    request = urllib.request.Request(url, headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    cdl_value, cdl_label = _parse_cdl_value_response(raw)
    summary = {
        "tool": "cropland_data_layer_point",
        "source": url,
        "cache_hit": False,
        "latitude": latitude,
        "longitude": longitude,
        "year": cdl_year,
        "albers_x": round(x_albers, 3),
        "albers_y": round(y_albers, 3),
        "cdl_code": cdl_value,
        "cdl_label": cdl_label,
        "raw_response": raw[:500],
        "boundary": (
            "USDA NASS Cropland Data Layer is a public land-cover classification prior at the queried point. "
            "It is not a grower planting record, field boundary proof, crop-insurance record, or substitute for field history."
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def cropland_data_layer_geometry(
    geometry: dict[str, Any],
    years: tuple[int, ...] | None = None,
    sample_points: int = DEFAULT_CDL_SAMPLE_POINTS,
    cache_dir: str = "outputs/tool_cache/cdl",
    timeout: int = 20,
) -> dict[str, Any]:
    geometry_type, bbox, vertex_count, points = _sample_geojson_geometry(geometry, max_points=sample_points)
    west, south, east, north = bbox
    if east - west > MAX_CDL_GEOMETRY_BBOX_SPAN_DEGREES or north - south > MAX_CDL_GEOMETRY_BBOX_SPAN_DEGREES:
        raise ValueError("CDL geometry query span is too large for local field-context lookup")
    if vertex_count > MAX_CDL_GEOMETRY_VERTICES:
        raise ValueError(f"CDL geometry query has too many vertices; max is {MAX_CDL_GEOMETRY_VERTICES}")
    clean_years = _cdl_geometry_years(years)
    sample_payloads: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for year in clean_years:
        for idx, (longitude, latitude) in enumerate(points, start=1):
            try:
                payload = cropland_data_layer_point(
                    latitude=latitude,
                    longitude=longitude,
                    year=year,
                    cache_dir=cache_dir,
                    timeout=timeout,
                )
                sample_payloads.append(
                    {
                        "sample_index": idx,
                        "latitude": round(latitude, 7),
                        "longitude": round(longitude, 7),
                        "year": year,
                        "cdl_code": payload.get("cdl_code"),
                        "cdl_label": payload.get("cdl_label"),
                        "source": payload.get("source"),
                        "cache_hit": payload.get("cache_hit"),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - one point should not sink the field summary.
                errors.append({"sample_index": idx, "year": year, "error_type": exc.__class__.__name__, "error": str(exc)[:220]})
    year_summary = _summarize_cdl_samples(sample_payloads)
    status = "available" if sample_payloads else "unavailable"
    return {
        "tool": "cropland_data_layer_geometry",
        "status": status,
        "source": CROPSCAPE_CDL_VALUE_URL,
        "cache_hit": all(bool(sample.get("cache_hit")) for sample in sample_payloads) if sample_payloads else False,
        "geometry_type": geometry_type,
        "bbox": [round(value, 7) for value in bbox],
        "vertex_count": vertex_count,
        "sample_point_count": len(points),
        "years": list(clean_years),
        "samples": sample_payloads[:80],
        "sample_errors": errors[:20],
        "year_summary": year_summary,
        "boundary": (
            "USDA NASS Cropland Data Layer boundary sampling is a small public crop-cover sample across the drawn "
            "or uploaded geometry. Use it as crop-history/rotation context only; it is not acreage accounting, a "
            "grower planting record, crop-insurance evidence, field boundary proof, or a substitute for local field history."
        ),
    }


def nass_quickstats_crop_stats(
    crop: str,
    state_alpha: str,
    county_name: str | None = None,
    year_ge: int | None = None,
    statistic_categories: tuple[str, ...] = DEFAULT_QUICKSTATS_CATEGORIES,
    source_desc: str = "SURVEY",
    api_key: str | None = None,
    cache_dir: str = "outputs/tool_cache/nass_quickstats",
    snapshot_path: str = NASS_QUICKSTATS_SNAPSHOT_PATH,
    timeout: int = 20,
) -> dict[str, Any]:
    crop_value = str(crop or "").strip().upper()
    state_value = str(state_alpha or "").strip().upper()
    county_value = str(county_name or "").strip().upper()
    if not crop_value:
        raise ValueError("crop is required")
    if not re.fullmatch(r"[A-Z]{2}", state_value):
        raise ValueError("state_alpha must be a two-letter postal abbreviation")
    categories = tuple(str(item).strip().upper() for item in statistic_categories if str(item).strip())
    if not categories:
        raise ValueError("at least one statistic category is required")
    min_year = int(year_ge or (dt.datetime.now(dt.UTC).year - 5))
    if min_year < 1866 or min_year > dt.datetime.now(dt.UTC).year:
        raise ValueError("year_ge must be between 1866 and the current year")
    resolved_key = _quickstats_api_key(api_key)
    redacted_query = {
        "commodity_desc": crop_value,
        "state_alpha": state_value,
        "agg_level_desc": "COUNTY" if county_value else "STATE",
        "year__GE": min_year,
        "source_desc": source_desc,
        "statisticcat_desc": list(categories),
        "format": "JSON",
    }
    if county_value:
        redacted_query["county_name"] = county_value
    cache_key = _safe_name(f"{NASS_QUICKSTATS_CACHE_VERSION}_{json.dumps(redacted_query, sort_keys=True)}")
    cache_path = repo_path(cache_dir) / f"{cache_key}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if not (resolved_key and payload.get("snapshot_hit")):
            payload["cache_hit"] = True
            return payload
    if not resolved_key:
        snapshot_records, snapshot_geography_fallback = _query_nass_quickstats_snapshot(
            snapshot_path=snapshot_path,
            crop=crop_value,
            state_alpha=state_value,
            county_name=county_value or None,
            year_ge=min_year,
            statistic_categories=categories,
        )
        if snapshot_records:
            summary = {
                "tool": "nass_quickstats_crop_stats",
                "status": "available",
                "source": NASS_QUICKSTATS_BULK_DATA_URL,
                "cache_hit": True,
                "snapshot_hit": True,
                "snapshot_path": snapshot_path,
                "snapshot_geography_fallback": snapshot_geography_fallback,
                "query": redacted_query,
                "crop": crop_value,
                "state_alpha": state_value,
                "county_name": county_value or None,
                "year_ge": min_year,
                "statistic_categories": list(categories),
                "record_count": len(snapshot_records),
                "records": snapshot_records[:25],
                "latest_by_statistic": _latest_quickstats_by_statistic(snapshot_records),
                "latest_series": _latest_quickstats_series(snapshot_records),
                "boundary": (
                    "USDA NASS downloadable Quick Stats files provide official published regional agricultural statistics. "
                    "This portable snapshot is state-level historical context and may be older than the live service; it is not "
                    "a county result, field-specific yield guarantee, market forecast, management-zone record, or rate recommendation."
                ),
                "provenance": "usda_nass_quickstats_bulk_snapshot",
            }
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            return summary
        return {
            "tool": "nass_quickstats_crop_stats",
            "status": "not_configured",
            "source": NASS_QUICKSTATS_API_URL,
            "cache_hit": False,
            "required_env_vars": list(NASS_QUICKSTATS_ENV_VARS),
            "query": redacted_query,
            "crop": crop_value,
            "state_alpha": state_value,
            "county_name": county_value or None,
            "record_count": 0,
            "records": [],
            "latest_by_statistic": {},
            "latest_series": [],
            "boundary": (
                "USDA NASS Quick Stats needs a local API key before live crop-statistics context can be queried. "
                "When configured, it provides public regional estimates, not field-specific yield prediction, market advice, "
                "or a substitute for grower records."
            ),
        }
    records: list[dict[str, Any]] = []
    for category in categories:
        query = {
            "key": resolved_key,
            "commodity_desc": crop_value,
            "state_alpha": state_value,
            "agg_level_desc": "COUNTY" if county_value else "STATE",
            "year__GE": min_year,
            "source_desc": source_desc,
            "statisticcat_desc": category,
            "format": "JSON",
        }
        if county_value:
            query["county_name"] = county_value
        data = _get_nass_quickstats(query, timeout=timeout)
        records.extend(_normalize_quickstats_rows(data))
    records = sorted(records, key=lambda row: (int(row.get("year") or 0), str(row.get("statisticcat_desc") or "")), reverse=True)
    summary = {
        "tool": "nass_quickstats_crop_stats",
        "status": "available" if records else "no_records",
        "source": NASS_QUICKSTATS_API_URL,
        "cache_hit": False,
        "query": redacted_query,
        "crop": crop_value,
        "state_alpha": state_value,
        "county_name": county_value or None,
        "year_ge": min_year,
        "statistic_categories": list(categories),
        "record_count": len(records),
        "records": records[:25],
        "latest_by_statistic": _latest_quickstats_by_statistic(records),
        "latest_series": _latest_quickstats_series(records),
        "boundary": (
            "USDA NASS Quick Stats provides official published regional agricultural statistics from public surveys "
            "and censuses. Use it as crop/yield/acreage context only; it is not a field-specific yield guarantee, "
            "market forecast, management-zone record, or rate recommendation."
        ),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _canada_source_lane_context(
    source_lane_id: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    geometry: dict[str, Any] | None = None,
    crop: str | None = None,
    province: str | None = None,
    product_term: str | None = None,
    search_kind: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    definition = CANADA_SOURCE_LANE_DEFINITIONS[source_lane_id]
    if latitude is not None and not (-90 <= float(latitude) <= 90):
        raise ValueError("latitude out of range")
    if longitude is not None and not (-180 <= float(longitude) <= 180):
        raise ValueError("longitude out of range")
    geometry_type = str((geometry or {}).get("type") or "") if isinstance(geometry, dict) else None
    location: dict[str, Any] = {}
    if latitude is not None:
        location["latitude"] = float(latitude)
    if longitude is not None:
        location["longitude"] = float(longitude)
    if geometry_type:
        location["geometry_type"] = geometry_type
    context = {
        key: value
        for key, value in {
            "crop": str(crop).strip() if crop else None,
            "province": str(province).strip() if province else None,
            "product_term": str(product_term).strip() if product_term else None,
            "search_kind": str(search_kind).strip() if search_kind else None,
            "language": str(language).strip() if language else None,
        }.items()
        if value
    }
    return {
        "tool": definition["tool"],
        "status": definition["status"],
        "source": definition.get("source"),
        "cache_hit": False,
        "source_lane_id": definition["source_lane_id"],
        "source_name": definition["source_name"],
        "provider": definition["provider"],
        "coverage": definition["coverage"],
        "location": location,
        "context": context,
        "decision_checks": list(definition.get("decision_checks") or []),
        "boundary": definition["boundary"],
        "provenance": "open_agronomy_agent.canada_public_source_lane_catalog",
    }


def _normalize_pmra_registration_number(value: str | int | None) -> str | None:
    if value is None:
        return None
    registration = str(value).strip()
    if not re.fullmatch(r"\d{4,5}", registration):
        raise ValueError("PMRA registration number must contain 4 or 5 digits")
    return registration


def _normalize_pmra_language(value: str | None) -> str:
    normalized = str(value or "en").strip().lower().replace("_", "-")
    if normalized in {"en", "en-ca"}:
        return "en"
    if normalized in {"fr", "fr-ca"}:
        return "fr"
    raise ValueError("PMRA language must be en, en-CA, fr, or fr-CA")


def _parse_utc_datetime(value: Any) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _read_pmra_csv(url: str, *, timeout: int) -> list[dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw_bytes = response.read()
        headers = getattr(response, "headers", None)
        declared_charset = (
            headers.get_content_charset()
            if headers is not None and hasattr(headers, "get_content_charset")
            else None
        )
    encodings = [
        str(declared_charset or "").strip(),
        "utf-8-sig",
        "windows-1252",
    ]
    raw = ""
    for encoding in encodings:
        if not encoding:
            continue
        try:
            raw = raw_bytes.decode(encoding)
            break
        except (LookupError, UnicodeDecodeError):
            continue
    else:
        raw = raw_bytes.decode("windows-1252", errors="replace")
    return [dict(row) for row in csv.DictReader(io.StringIO(raw)) if any(str(value).strip() for value in row.values())]


def _post_json(url: str, payload: Any, *, timeout: int) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": "agronomy-agent-local-tools/0.1", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _normalize_statcan_crop(value: str | None) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    aliases = {
        "canola rapeseed": "canola rapeseed",
        "corn for grain": "corn grain",
        "durum wheat": "wheat",
        "field peas": "dry peas",
        "spring wheat": "wheat",
        "winter wheat": "wheat",
    }
    return aliases.get(normalized, normalized) or None


def _normalize_statcan_province(value: str | None) -> str:
    normalized = re.sub(r"[^a-z]+", "", str(value or "").lower())
    aliases = {
        "": "CANADA", "canada": "CANADA", "nl": "NL", "newfoundlandandlabrador": "NL", "pe": "PE",
        "princeedwardisland": "PE", "ns": "NS", "novascotia": "NS", "nb": "NB", "newbrunswick": "NB",
        "qc": "QC", "quebec": "QC", "on": "ON", "ontario": "ON", "mb": "MB", "manitoba": "MB",
        "sk": "SK", "saskatchewan": "SK", "ab": "AB", "alberta": "AB", "bc": "BC", "britishcolumbia": "BC",
    }
    if normalized not in aliases:
        raise ValueError("province must be a Canadian province/territory supported by Statistics Canada table 32-10-0359-01")
    return aliases[normalized]


def _statcan_geography_label(province_key: str) -> str:
    return {"CANADA": "Canada", "ON": "Ontario", "SK": "Saskatchewan", "AB": "Alberta", "MB": "Manitoba", "QC": "Quebec", "BC": "British Columbia", "NL": "Newfoundland and Labrador", "PE": "Prince Edward Island", "NS": "Nova Scotia", "NB": "New Brunswick"}[province_key]


def _statcan_coordinate(geography_member: int, disposition_member: int, crop_member: int) -> str:
    return f"{geography_member}.{disposition_member}.{crop_member}.0.0.0.0.0.0.0"


def _statcan_data_qualifiers(
    *,
    status_code: Any,
    symbol_code: Any,
) -> dict[str, Any]:
    symbol_code_lookup = {
        "": 0,
        "p": 1,
        "r": 3,
    }
    status_code_lookup = {
        "": 0,
        "..": 1,
        "0s": 2,
        "A": 3,
        "B": 4,
        "C": 5,
        "D": 6,
        "E": 7,
        "F": 8,
        "...": 9,
        "<LOD": 10,
        "<LDD": 10,
    }

    def normalize_code(value: Any, lookup: dict[str, int]) -> int | None:
        if value is None:
            return 0
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        clean = str(value).strip()
        if clean in lookup:
            return lookup[clean]
        try:
            return int(clean)
        except ValueError:
            return None

    normalized_symbol_code = normalize_code(symbol_code, symbol_code_lookup)
    normalized_status_code = normalize_code(status_code, status_code_lookup)
    symbol, symbol_description = STATCAN_SYMBOL_CODES.get(
        normalized_symbol_code,
        (None, "unknown Statistics Canada symbol code"),
    )
    status, status_description = STATCAN_STATUS_CODES.get(
        normalized_status_code,
        (None, "unknown Statistics Canada status code"),
    )
    quality_flags = [
        value
        for value in (symbol_description, status_description)
        if value and value != "normal"
    ]
    return {
        "symbol": symbol,
        "symbol_description": symbol_description,
        "status": status,
        "status_description": status_description,
        "quality_flags": quality_flags,
    }


def _normalize_statcan_field_crop_response(response_rows: Any, *, latest_count: int) -> dict[str, dict[str, Any]]:
    rows = response_rows if isinstance(response_rows, list) else []
    output: dict[str, dict[str, Any]] = {}
    for (statistic_id, (disposition_member, label)), row in zip(STATCAN_FIELD_CROP_STATISTICS.items(), rows, strict=False):
        item = row.get("object") if isinstance(row, dict) else {}
        points = item.get("vectorDataPoint") if isinstance(item, dict) else []
        normalized = [
            {
                "reference_period": point.get("refPerRaw") or point.get("refPer"),
                "value": point.get("value"),
                "status_code": point.get("statusCode"),
                "symbol_code": point.get("symbolCode"),
                "scalar_factor_code": point.get("scalarFactorCode"),
                "release_time": point.get("releaseTime"),
                **_statcan_data_qualifiers(
                    status_code=point.get("statusCode"),
                    symbol_code=point.get("symbolCode"),
                ),
            }
            for point in points[:latest_count]
            if isinstance(point, dict) and point.get("value") is not None
        ]
        output[statistic_id] = {
            "label": label,
            "disposition_member_id": disposition_member,
            "vector_id": item.get("vectorId") if isinstance(item, dict) else None,
            "latest": normalized[-1] if normalized else None,
            "periods": normalized,
        }
    return output


def _load_statcan_field_crop_snapshot(
    snapshot_path: str,
    snapshot_manifest_path: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    path = repo_path(snapshot_path)
    manifest_path = repo_path(snapshot_manifest_path)
    if not path.is_file() or not manifest_path.is_file():
        return [], {}, "snapshot_or_manifest_missing"
    path_stat = path.stat()
    manifest_stat = manifest_path.stat()
    key = (
        str(path.resolve()),
        path_stat.st_mtime_ns,
        path_stat.st_size,
        str(manifest_path.resolve()),
        manifest_stat.st_mtime_ns,
        manifest_stat.st_size,
    )
    cached = _STATCAN_FIELD_CROP_SNAPSHOT_CACHE.get(key)
    if cached is not None:
        rows, manifest = cached
        return rows, manifest, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_sha = str((manifest.get("snapshot") or {}).get("sha256") or "")
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if not expected_sha or actual_sha != expected_sha:
            return [], manifest, "snapshot_sha256_mismatch"
        rows = [
            payload
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
            for payload in [json.loads(line)]
            if isinstance(payload, dict)
        ]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [], {}, f"{exc.__class__.__name__}: {str(exc)[:160]}"
    _STATCAN_FIELD_CROP_SNAPSHOT_CACHE.clear()
    _STATCAN_FIELD_CROP_SNAPSHOT_CACHE[key] = (rows, manifest)
    return rows, manifest, None


def _statcan_snapshot_summary(
    *,
    crop_key: str,
    province_key: str,
    latest_count: int,
    snapshot_path: str,
    snapshot_manifest_path: str,
    fallback_reason: str,
) -> tuple[dict[str, Any] | None, str | None]:
    rows, manifest, error = _load_statcan_field_crop_snapshot(snapshot_path, snapshot_manifest_path)
    if error:
        return None, error
    candidates = [
        row
        for row in rows
        if str(row.get("crop_key") or "") == crop_key
        and str(row.get("province_code") or "") == province_key
    ]
    statistics: dict[str, dict[str, Any]] = {}
    for statistic_id, (disposition_member, label) in STATCAN_FIELD_CROP_STATISTICS.items():
        series = sorted(
            (row for row in candidates if str(row.get("statistic_id") or "") == statistic_id),
            key=lambda row: str(row.get("reference_period") or ""),
        )[-latest_count:]
        periods = [
            {
                "reference_period": row.get("reference_period"),
                "value": row.get("value"),
                "status_code": row.get("status_code"),
                "symbol_code": row.get("symbol_code"),
                "scalar_factor_code": row.get("scalar_id"),
                "release_time": row.get("source_release_date"),
                **_statcan_data_qualifiers(
                    status_code=row.get("status_code"),
                    symbol_code=row.get("symbol_code"),
                ),
            }
            for row in series
            if row.get("value") is not None
        ]
        latest_row = series[-1] if series else {}
        statistics[statistic_id] = {
            "label": label,
            "disposition_member_id": disposition_member,
            "vector_id": latest_row.get("vector_id"),
            "latest": periods[-1] if periods else None,
            "periods": periods,
        }
    available = [item for item in statistics.values() if item.get("latest")]
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    snapshot = manifest.get("snapshot") if isinstance(manifest.get("snapshot"), dict) else {}
    release_date = str(source.get("release_date") or "")
    try:
        snapshot_age_days = (dt.datetime.now(dt.UTC).date() - dt.date.fromisoformat(release_date)).days
    except ValueError:
        snapshot_age_days = None
    return {
        "tool": "statcan_field_crop_statistics",
        "status": "available_offline_snapshot" if available else "no_records",
        "source": STATCAN_FIELD_CROP_TABLE_URL,
        "source_api": None,
        "cache_hit": False,
        "snapshot_hit": True,
        "snapshot_path": snapshot_path,
        "snapshot_manifest_path": snapshot_manifest_path,
        "snapshot_sha256": snapshot.get("sha256"),
        "snapshot_as_of": release_date or None,
        "snapshot_age_days": snapshot_age_days,
        "updated_at": release_date or None,
        "access_mode": "offline_snapshot",
        "fallback_reason": fallback_reason,
        "product_id": STATCAN_FIELD_CROP_PRODUCT_ID,
        "table": "32-10-0359-01",
        "crop": crop_key,
        "province": province_key if province_key != "CANADA" else None,
        "geography": _statcan_geography_label(province_key),
        "latest_periods": latest_count,
        "statistics": statistics,
        "available_statistic_count": len(available),
        "source_lane_id": "statcan_field_crop_statistics",
        "source_name": "Statistics Canada principal field-crop statistics",
        "provider": "Statistics Canada",
        "coverage": "Published national or provincial field-crop area, yield, and production estimates.",
        "license": manifest.get("license") or {},
        "decision_checks": list(CANADA_SOURCE_LANE_DEFINITIONS["statcan_field_crop_statistics"]["decision_checks"]),
        "boundary": (
            f"Statistics Canada table 32-10-0359-01 snapshot dated {release_date or 'unknown'} provides published "
            "regional field-crop estimates. It may be older than the live table. Use it as regional context only; "
            "it is not field-specific yield prediction, a market forecast, grower records, or a rate recommendation. "
            "Check reference period, estimate status, revisions, and local farm records."
        ),
        "provenance": "statistics_canada_table_32100359_portable_snapshot",
    }, None


def _pmra_row_value(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = _clean_pmra_value(row.get(key))
        if value is not None:
            return value
    return None


def _normalize_pmra_product_row(
    row: dict[str, str],
    *,
    language: str = "en",
) -> dict[str, Any]:
    french = language == "fr"
    return {
        "registration_number": _pmra_row_value(
            row,
            "Numéro d'homologation",
            "Registration number",
        ),
        "product_name": _pmra_row_value(
            row,
            *(
                (
                    "Nom du produit - français",
                    "Product name - French",
                    "Nom du produit - anglais",
                    "Product name - English",
                )
                if french
                else (
                    "Product name - English",
                    "Nom du produit - anglais",
                    "Product name - French",
                    "Nom du produit - français",
                )
            ),
        ),
        "registration_status": _pmra_row_value(
            row,
            "Statut de l'homologation",
            "Registration Status",
        ),
        "expiry_date": _pmra_row_value(
            row,
            "Date d'expiration du statut",
            "Expiry date",
        ),
        "marketing_type": _pmra_row_value(
            row,
            "Type de mise en marche",
            "Marketing type",
        ),
        "first_registered": _pmra_row_value(
            row,
            "Date de la première homologation",
            "Date first registered",
        ),
        "active_ingredients": _split_pmra_values(
            _pmra_row_value(
                row,
                *(
                    (
                        "Principes actifs - français",
                        "Active ingredients - French",
                        "Principes actifs - anglais",
                        "Active ingredients - English",
                    )
                    if french
                    else (
                        "Active ingredients - English",
                        "Principes actifs - anglais",
                        "Active ingredients - French",
                        "Principes actifs - français",
                    )
                ),
            )
        ),
        "product_type": _pmra_row_value(
            row,
            "Types du produit",
            "Product Type",
        ),
        "registrant": _pmra_row_value(
            row,
            "Nom du titulaire",
            "Registrant name",
        ),
        "use_site_category": _pmra_row_value(
            row,
            "Catégories d'utilisation",
            "Use Site Category",
        ),
        "sites_of_use": _split_pmra_values(
            _pmra_row_value(row, "Sites d'utilisation", "Sites of Use")
        ),
        "pests": _split_pmra_values(
            _pmra_row_value(row, "Organismes nuisibles", "Pests")
        ),
        "current_or_historical": _pmra_row_value(
            row,
            "En cours / Historique",
            "Current / Historical",
        ),
    }


def _normalize_pmra_label_row(
    row: dict[str, str],
    *,
    language: str = "en",
) -> dict[str, str | None]:
    del language
    return {
        "registration_number": _pmra_row_value(
            row,
            "Numéro d'homologation",
            "Registration number",
        ),
        "product_name": _pmra_row_value(row, "Nom du produit", "Product name"),
        "registrant": _pmra_row_value(
            row,
            "Nom du titulaire",
            "Registrant name",
        ),
        "registration_status": _pmra_row_value(
            row,
            "Statut de l'homologation",
            "Registration Status",
        ),
    }


def _clean_pmra_value(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _split_pmra_values(value: Any) -> list[str]:
    text = _clean_pmra_value(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"\s*;\s*", text) if item.strip()]


def _public_source_lane_context(source_lane_id: str, **context: Any) -> dict[str, Any]:
    definition = PUBLIC_SOURCE_LANE_DEFINITIONS[source_lane_id]
    clean_context = {key: value for key, value in context.items() if value not in (None, "")}
    return {
        "tool": definition["tool"],
        "status": definition["status"],
        "source_lane_id": definition["source_lane_id"],
        "source_name": definition["source_name"],
        "provider": definition["provider"],
        "source_urls": list(definition.get("source_urls") or []),
        "coverage": definition["coverage"],
        "context": clean_context,
        "decision_checks": list(definition["decision_checks"]),
        "boundary": definition["boundary"],
        "provenance": "open_agronomy_agent.static_public_source_lane_catalog",
    }


def _post_nrcs_sda(query: str, timeout: int = 20) -> dict[str, Any]:
    payload = urllib.parse.urlencode({"format": "JSON", "query": query}).encode("utf-8")
    request = urllib.request.Request(
        NRCS_SDA_POST_REST_URL,
        data=payload,
        headers={
            "User-Agent": "agronomy-agent-local-tools/0.1",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _get_nass_quickstats(query: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    url = f"{NASS_QUICKSTATS_API_URL}?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _normalize_sda_table(data: dict[str, Any]) -> list[dict[str, Any]]:
    table = data.get("Table") or data.get("table") or data.get("Table1") or data.get("items") or []
    if isinstance(table, dict):
        rows = table.get("Rows") or table.get("rows") or []
    else:
        rows = table
    out = []
    for row in rows:
        if isinstance(row, dict):
            out.append(
                {
                    "mukey": row.get("mukey") or row.get("MUKEY"),
                    "musym": row.get("musym") or row.get("MUSYM"),
                    "muname": row.get("muname") or row.get("MUNAME"),
                    "areasymbol": row.get("areasymbol") or row.get("AREASYMBOL"),
                }
            )
        elif isinstance(row, (list, tuple)) and len(row) >= 4:
            out.append({"mukey": row[0], "musym": row[1], "muname": row[2], "areasymbol": row[3]})
    return out


def _normalize_sda_component_table(data: dict[str, Any]) -> list[dict[str, Any]]:
    table = data.get("Table") or data.get("table") or data.get("Table1") or data.get("items") or []
    if isinstance(table, dict):
        rows = table.get("Rows") or table.get("rows") or []
    else:
        rows = table
    keys = (
        "mukey",
        "musym",
        "muname",
        "areasymbol",
        "cokey",
        "compname",
        "comppct_r",
        "majcompflag",
        "slope_r",
        "drainagecl",
        "hydgrp",
        "hydricrating",
        "taxorder",
        "taxsubgrp",
    )
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            lowered = {str(key).lower(): value for key, value in row.items()}
            normalized.append({key: lowered.get(key) for key in keys})
        elif isinstance(row, (list, tuple)):
            normalized.append({key: row[idx] if idx < len(row) else None for idx, key in enumerate(keys)})
    return normalized


def _group_sda_component_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        mukey = str(row.get("mukey") or "").strip()
        if not mukey:
            continue
        unit = grouped.setdefault(
            mukey,
            {
                "mukey": mukey,
                "musym": row.get("musym"),
                "muname": row.get("muname"),
                "areasymbol": row.get("areasymbol"),
                "components": [],
            },
        )
        compname = str(row.get("compname") or "").strip()
        if not compname:
            continue
        unit["components"].append(
            {
                "cokey": row.get("cokey"),
                "compname": compname,
                "comppct_r": _parse_number(row.get("comppct_r")),
                "majcompflag": row.get("majcompflag"),
                "slope_r": _parse_number(row.get("slope_r")),
                "drainagecl": row.get("drainagecl"),
                "hydgrp": row.get("hydgrp"),
                "hydricrating": row.get("hydricrating"),
                "taxorder": row.get("taxorder"),
                "taxsubgrp": row.get("taxsubgrp"),
            }
        )
    units = list(grouped.values())
    for unit in units:
        unit["components"] = sorted(
            unit["components"],
            key=lambda component: float(component.get("comppct_r") or 0),
            reverse=True,
        )[:8]
        unit["dominant_component"] = unit["components"][0] if unit["components"] else None
    units.sort(key=lambda unit: str(unit.get("muname") or ""))
    return units


def _summarize_sda_components(map_units: list[dict[str, Any]]) -> dict[str, Any]:
    components = [component for unit in map_units for component in (unit.get("components") or [])]
    dominant = [unit.get("dominant_component") for unit in map_units if unit.get("dominant_component")]
    return {
        "dominant_components": [
            {
                "map_unit": unit.get("muname"),
                "component": (unit.get("dominant_component") or {}).get("compname"),
                "comppct_r": (unit.get("dominant_component") or {}).get("comppct_r"),
                "drainagecl": (unit.get("dominant_component") or {}).get("drainagecl"),
                "hydgrp": (unit.get("dominant_component") or {}).get("hydgrp"),
            }
            for unit in map_units[:6]
        ],
        "drainage_classes": _count_values(component.get("drainagecl") for component in components),
        "hydrologic_groups": _count_values(component.get("hydgrp") for component in components),
        "hydric_ratings": _count_values(component.get("hydricrating") for component in components),
        "major_component_names": [str(component.get("compname")) for component in dominant[:8] if component.get("compname")],
    }


def _count_values(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    return counts


def _normalize_ppls_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items") or data.get("Items") or data.get("products") or data.get("PRODUCTS") or []
    else:
        items = []
    products = []
    for item in items:
        if not isinstance(item, dict):
            continue
        status = (
            item.get("PRODUCT_STATUS")
            or item.get("product_status")
            or item.get("registrationstatus")
            or item.get("productnamestatus")
            or item.get("status")
        )
        pdf_files = item.get("PDFFILES") or item.get("pdf_files") or item.get("pdfFiles")
        products.append(
            {
                "epa_reg_no": item.get("EPAREGNO")
                or item.get("eparegno")
                or item.get("eparegnumber")
                or item.get("epa_reg_no"),
                "product_name": item.get("PRODUCTNAME") or item.get("productname") or item.get("product_name"),
                "status": status,
                "status_bucket": _ppls_status_bucket(status),
                "status_date": item.get("PRODUCT_STATUS_DATE")
                or item.get("product_status_date")
                or item.get("productstatusdate"),
                "signal_word": item.get("SIGNAL_WORD") or item.get("signal_word"),
                "restricted_use": item.get("RUP_YN") or item.get("rup_yn"),
                "active_ingredients": item.get("ACTIVE_INGREDIENTS")
                or item.get("active_ingredients")
                or item.get("activeIngredients")
                or item.get("ingredientname"),
                "pdf_files": pdf_files,
                "label_pdf_urls": _extract_ppls_pdf_urls(pdf_files),
            }
        )
    return products


def _summarize_ppls_products(products: list[dict[str, Any]], *, search_kind: str) -> dict[str, Any]:
    status_counts = _count_values(product.get("status_bucket") for product in products)
    current_products = [product for product in products if product.get("status_bucket") == "current"]
    inactive_products = [product for product in products if product.get("status_bucket") == "inactive"]
    unknown_products = [product for product in products if product.get("status_bucket") == "unknown"]
    top_candidate = current_products[0] if current_products else (products[0] if products else {})
    needs_disambiguation = bool(products) and (
        search_kind != "epa_reg_no" or len(products) != 1 or len(current_products) != 1
    )
    if not products:
        note = "EPA PPLS returned no matching product records; do not infer label metadata from the model."
    elif needs_disambiguation:
        note = (
            "PPLS returned candidate product records. Ask for the exact product name or EPA registration number, "
            "then verify current label, crop, site, pest, rate, restrictions, and local registration before use."
        )
    else:
        note = (
            "PPLS returned one current-status product candidate. Still verify the current label, crop, site, pest, "
            "rate, restrictions, and local registration before use."
        )
    return {
        "status_counts": status_counts,
        "current_product_count": len(current_products),
        "inactive_product_count": len(inactive_products),
        "unknown_status_product_count": len(unknown_products),
        "top_candidate": _ppls_candidate_projection(top_candidate),
        "needs_product_disambiguation": needs_disambiguation,
        "disambiguation_note": note,
    }


def _ppls_candidate_projection(product: dict[str, Any]) -> dict[str, Any]:
    if not product:
        return {}
    return {
        key: product.get(key)
        for key in (
            "product_name",
            "epa_reg_no",
            "status",
            "status_bucket",
            "status_date",
            "active_ingredients",
            "restricted_use",
            "signal_word",
            "label_pdf_urls",
        )
        if product.get(key) not in (None, "", [])
    }


def _ppls_status_bucket(status: Any) -> str:
    text = str(status or "").strip().lower()
    if not text:
        return "unknown"
    inactive_terms = ("cancel", "expired", "inactive", "terminated", "suspended", "withdrawn", "unregistered")
    if any(term in text for term in inactive_terms):
        return "inactive"
    current_terms = ("active", "registered", "conditionally registered")
    if any(term in text for term in current_terms):
        return "current"
    return "unknown"


def _extract_ppls_pdf_urls(value: Any) -> list[str]:
    candidates: list[str] = []

    def collect(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            for nested in item.values():
                collect(nested)
            return
        if isinstance(item, (list, tuple)):
            for nested in item:
                collect(nested)
            return
        text = str(item).strip()
        if not text:
            return
        for part in re.split(r"[\s,;]+", text):
            cleaned = part.strip(" '\"")
            if cleaned.lower().startswith(("http://", "https://")):
                candidates.append(cleaned)

    collect(value)
    return list(dict.fromkeys(candidates))[:5]


def _normalize_quickstats_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("data") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        year_value = _parse_int(row.get("year"))
        value_text = str(row.get("Value") or row.get("value") or "").strip()
        out.append(
            {
                "year": year_value,
                "short_desc": row.get("short_desc"),
                "statisticcat_desc": row.get("statisticcat_desc"),
                "unit_desc": row.get("unit_desc"),
                "value": value_text,
                "value_numeric": _parse_number(value_text),
                "agg_level_desc": row.get("agg_level_desc"),
                "state_alpha": row.get("state_alpha"),
                "county_name": row.get("county_name"),
                "domain_desc": row.get("domain_desc"),
                "source_desc": row.get("source_desc"),
                "reference_period_desc": row.get("reference_period_desc"),
            }
        )
    return out


def _load_nass_quickstats_snapshot(snapshot_path: str) -> list[dict[str, Any]]:
    path = repo_path(snapshot_path)
    if not path.exists():
        return []
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _NASS_QUICKSTATS_SNAPSHOT_CACHE.get(key)
    if cached is not None:
        return cached
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    _NASS_QUICKSTATS_SNAPSHOT_CACHE.clear()
    _NASS_QUICKSTATS_SNAPSHOT_CACHE[key] = rows
    return rows


def _query_nass_quickstats_snapshot(
    *,
    snapshot_path: str,
    crop: str,
    state_alpha: str,
    county_name: str | None,
    year_ge: int,
    statistic_categories: tuple[str, ...],
) -> tuple[list[dict[str, Any]], str | None]:
    categories = set(statistic_categories)
    candidates = [
        row
        for row in _load_nass_quickstats_snapshot(snapshot_path)
        if str(row.get("commodity_desc") or "").upper() == crop
        and str(row.get("state_alpha") or "").upper() == state_alpha
        and int(row.get("year") or 0) >= year_ge
        and str(row.get("statisticcat_desc") or "").upper() in categories
    ]
    geography_fallback: str | None = None
    if county_name:
        county_rows = [row for row in candidates if str(row.get("county_name") or "").upper() == county_name]
        if county_rows:
            candidates = county_rows
        else:
            candidates = [row for row in candidates if str(row.get("agg_level_desc") or "").upper() == "STATE"]
            geography_fallback = "state_snapshot_used_for_county_request"
    else:
        candidates = [row for row in candidates if str(row.get("agg_level_desc") or "").upper() == "STATE"]
    normalized = _normalize_quickstats_rows({"data": candidates})
    return (
        sorted(normalized, key=lambda row: (int(row.get("year") or 0), str(row.get("statisticcat_desc") or "")), reverse=True),
        geography_fallback,
    )


def _latest_quickstats_by_statistic(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in records:
        key = str(row.get("statisticcat_desc") or "UNKNOWN")
        current = latest.get(key)
        if current is None or _quickstats_representative_rank(row) > _quickstats_representative_rank(current):
            latest[key] = {
                "year": row.get("year"),
                "short_desc": row.get("short_desc"),
                "unit_desc": row.get("unit_desc"),
                "value": row.get("value"),
                "value_numeric": row.get("value_numeric"),
                "agg_level_desc": row.get("agg_level_desc"),
                "state_alpha": row.get("state_alpha"),
                "county_name": row.get("county_name"),
                "reference_period_desc": row.get("reference_period_desc"),
            }
    return latest


def _quickstats_representative_rank(row: dict[str, Any]) -> tuple[int, int, int, int]:
    reference_period = str(row.get("reference_period_desc") or "").strip().upper()
    unit = str(row.get("unit_desc") or "").strip().upper()
    description = str(row.get("short_desc") or "").strip().upper()
    return (
        int(row.get("year") or 0),
        1 if reference_period == "YEAR" else 0,
        1 if unit not in {"$", "DOLLARS"} else 0,
        1 if ", SILAGE" not in description else 0,
    )


def _latest_quickstats_series(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in records:
        key = (
            str(row.get("statisticcat_desc") or "UNKNOWN"),
            str(row.get("short_desc") or ""),
            str(row.get("unit_desc") or ""),
        )
        current = latest.get(key)
        if current is None or _quickstats_representative_rank(row) > _quickstats_representative_rank(current):
            latest[key] = {
                "year": row.get("year"),
                "statisticcat_desc": row.get("statisticcat_desc"),
                "short_desc": row.get("short_desc"),
                "unit_desc": row.get("unit_desc"),
                "value": row.get("value"),
                "value_numeric": row.get("value_numeric"),
                "agg_level_desc": row.get("agg_level_desc"),
                "state_alpha": row.get("state_alpha"),
                "county_name": row.get("county_name"),
                "reference_period_desc": row.get("reference_period_desc"),
            }
    return sorted(
        latest.values(),
        key=lambda row: (
            str(row.get("statisticcat_desc") or ""),
            str(row.get("short_desc") or ""),
            str(row.get("unit_desc") or ""),
        ),
    )


def _parse_daymet_records(raw: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    header_index = next((idx for idx, line in enumerate(lines) if _looks_like_daymet_header(line)), None)
    if header_index is None:
        return []
    reader = csv.DictReader(lines[header_index:])
    records: list[dict[str, Any]] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        normalized = {_daymet_column_name(key): value for key, value in row.items() if key is not None}
        year = _parse_int(normalized.get("year"))
        yday = _parse_int(normalized.get("yday"))
        record: dict[str, Any] = {"year": year, "yday": yday}
        if year and yday:
            try:
                record["date"] = (dt.date(year, 1, 1) + dt.timedelta(days=yday - 1)).isoformat()
            except ValueError:
                record["date"] = None
        for key, value in normalized.items():
            if key in {"year", "yday"}:
                continue
            parsed = _parse_number(value)
            if parsed is not None:
                record[key] = parsed
        if year is not None:
            records.append(record)
    return records


def _looks_like_daymet_header(line: str) -> bool:
    normalized = line.lower().replace(" ", "")
    return normalized.startswith("year,") and "yday" in normalized


def _daymet_column_name(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    return text


def _summarize_daymet_records(records: list[dict[str, Any]], variables: tuple[str, ...]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for variable in variables:
        clean = [float(record[variable]) for record in records if _is_number(record.get(variable))]
        if clean:
            out[variable] = {
                "days": len(clean),
                "min": round(min(clean), 3),
                "mean": round(sum(clean) / len(clean), 3),
                "max": round(max(clean), 3),
                "sum": round(sum(clean), 3),
            }
    return out


def _summarize_power_series(series: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for name, values in series.items():
        clean = [float(value) for value in values.values() if value is not None and not _is_missing_power_value(value)]
        if clean:
            out[name] = {
                "days": len(clean),
                "min": round(min(clean), 3),
                "mean": round(sum(clean) / len(clean), 3),
                "max": round(max(clean), 3),
                "sum": round(sum(clean), 3),
            }
    return out


def _is_missing_power_value(value: Any) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return True
    return math.isclose(numeric, -999.0) or math.isclose(numeric, -9999.0)


def _default_cdl_year(today: dt.date | None = None) -> int:
    current = today or dt.datetime.now(dt.UTC).date()
    if current.month >= 3:
        return min(DEFAULT_CDL_YEAR, current.year - 1)
    return min(DEFAULT_CDL_YEAR, current.year - 2)


def _cdl_geometry_years(years: tuple[int, ...] | None = None) -> tuple[int, ...]:
    if years:
        clean = sorted({int(year) for year in years}, reverse=True)
    else:
        latest = _default_cdl_year()
        clean = [latest - offset for offset in range(DEFAULT_CDL_GEOMETRY_YEARS)]
    if not clean:
        raise ValueError("at least one CDL year is required")
    if len(clean) > 5:
        raise ValueError("CDL geometry sampling supports at most five years per call")
    current_year = dt.datetime.now(dt.UTC).year
    for year in clean:
        if year < 2008 or year > current_year:
            raise ValueError("CDL years must be between 2008 and the current year")
    return tuple(clean)


def _sample_geojson_geometry(geometry: dict[str, Any], max_points: int = DEFAULT_CDL_SAMPLE_POINTS) -> tuple[str, tuple[float, float, float, float], int, list[tuple[float, float]]]:
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be a GeoJSON geometry object")
    max_points = max(1, min(int(max_points), 16))
    geometry_type = str(geometry.get("type") or "").strip()
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        lon, lat = _validate_lon_lat_pair(coordinates)
        return geometry_type, (lon, lat, lon, lat), 1, [(lon, lat)]
    if geometry_type == "Polygon":
        rings = _validate_polygon_rings(coordinates)
        bbox, vertex_count = _bbox_for_points(point for ring in rings for point in ring)
        return geometry_type, bbox, vertex_count, _sample_polygon_points(rings, max_points=max_points)
    if geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError("MultiPolygon coordinates must be a non-empty list")
        polygons = [_validate_polygon_rings(polygon) for polygon in coordinates]
        bbox, vertex_count = _bbox_for_points(point for polygon in polygons for ring in polygon for point in ring)
        points: list[tuple[float, float]] = []
        per_polygon = max(1, math.ceil(max_points / len(polygons)))
        for polygon in polygons:
            points.extend(_sample_polygon_points(polygon, max_points=per_polygon))
        return geometry_type, bbox, vertex_count, points[:max_points]
    raise ValueError("CDL geometry lookup supports Point, Polygon, or MultiPolygon geometry")


def _sample_polygon_points(rings: list[list[tuple[float, float]]], max_points: int) -> list[tuple[float, float]]:
    bbox, _ = _bbox_for_points(point for ring in rings for point in ring)
    west, south, east, north = bbox
    candidates = [_ring_centroid(rings[0])]
    side = max(1, math.ceil(math.sqrt(max_points)))
    for row in range(side):
        lat = south + ((row + 0.5) / side) * (north - south)
        for col in range(side):
            lon = west + ((col + 0.5) / side) * (east - west)
            candidates.append((lon, lat))
    out: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for point in candidates:
        rounded = (round(point[0], 8), round(point[1], 8))
        if rounded in seen:
            continue
        if _point_in_polygon_rings(point, rings):
            out.append(rounded)
            seen.add(rounded)
        if len(out) >= max_points:
            break
    if not out:
        out.append((round((west + east) / 2, 8), round((south + north) / 2, 8)))
    return out


def _ring_centroid(ring: list[tuple[float, float]]) -> tuple[float, float]:
    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if not points:
        raise ValueError("polygon ring has no points")
    return sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points)


def _point_in_polygon_rings(point: tuple[float, float], rings: list[list[tuple[float, float]]]) -> bool:
    if not rings:
        return False
    if not _point_in_ring(point, rings[0]):
        return False
    return not any(_point_in_ring(point, hole) for hole in rings[1:])


def _point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    points = ring
    j = len(points) - 1
    for i, current in enumerate(points):
        xi, yi = current
        xj, yj = points[j]
        intersects = ((yi > y) != (yj > y)) and (x < ((xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi))
        if intersects:
            inside = not inside
        j = i
    return inside


def _summarize_cdl_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_year: dict[int, dict[str, Any]] = {}
    for sample in samples:
        year = int(sample.get("year") or 0)
        if not year:
            continue
        summary = by_year.setdefault(year, {"sample_count": 0, "classes": {}})
        summary["sample_count"] += 1
        code = sample.get("cdl_code")
        label = sample.get("cdl_label") or (CDL_CODE_LABELS.get(int(code)) if isinstance(code, int) else None) or "Unknown"
        key = str(code if code is not None else "unknown")
        item = summary["classes"].setdefault(key, {"cdl_code": code, "cdl_label": label, "count": 0})
        item["count"] += 1
    out: dict[str, Any] = {}
    for year, summary in sorted(by_year.items(), reverse=True):
        classes = sorted(summary["classes"].values(), key=lambda item: item["count"], reverse=True)
        dominant = classes[0] if classes else None
        out[str(year)] = {
            "sample_count": summary["sample_count"],
            "dominant_class": dominant,
            "classes": classes,
        }
    return out


def _aafc_annual_crop_inventory_point(
    *,
    latitude: float,
    longitude: float,
    year: int,
    cache_dir: str,
    timeout: int,
) -> dict[str, Any]:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("latitude/longitude out of range")
    cache_path = repo_path(cache_dir) / _safe_name(
        f"aafc_aci_{AAFC_ACI_CACHE_VERSION}_{year}_{latitude:.7f}_{longitude:.7f}"
    )
    cache_path = cache_path.with_suffix(".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        payload["cache_hit"] = True
        return payload
    source = AAFC_ACI_IMAGE_SERVER_TEMPLATE.format(year=year)
    geometry = {"x": longitude, "y": latitude, "spatialReference": {"wkid": 4326}}
    query = urllib.parse.urlencode(
        {
            "geometry": json.dumps(geometry, separators=(",", ":")),
            "geometryType": "esriGeometryPoint",
            "returnGeometry": "false",
            "returnCatalogItems": "false",
            "returnPixelValues": "true",
            "f": "json",
        }
    )
    url = f"{source}/identify?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    if data.get("error"):
        raise RuntimeError(f"AAFC Annual Crop Inventory identify error: {data['error'].get('message') or data['error']}")
    raw_value = data.get("value")
    try:
        code = int(str(raw_value)) if str(raw_value).strip().isdigit() else None
    except (TypeError, ValueError):
        code = None
    summary = {
        "latitude": round(latitude, 7),
        "longitude": round(longitude, 7),
        "aci_code": code,
        "aci_label": AAFC_ACI_CODE_LABELS.get(code) if code is not None else None,
        "raw_value": str(raw_value)[:80] if raw_value is not None else None,
        "source": source,
        "cache_hit": False,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _validate_canadian_nasdi_point(*, latitude: float, longitude: float) -> None:
    if not (41.0 <= float(latitude) <= 84.0 and -142.0 <= float(longitude) <= -50.0):
        raise ValueError("AAFC NASDI point must be within the Canadian service extent")


def _aafc_nasdi_latest_catalog_item(
    *,
    indicator: str,
    time_window: str,
    cache_dir: str,
    timeout: int,
    offline_only: bool = False,
) -> dict[str, Any]:
    definition = AAFC_NASDI_INDICATORS[indicator]
    source = AAFC_NASDI_IMAGE_SERVER_TEMPLATE.format(service=definition["service"])
    cache_path = (repo_path(cache_dir) / _safe_name(
        f"nasdi_catalog_{AAFC_NASDI_CACHE_VERSION}_{indicator}_{time_window}"
    )).with_suffix(".json")
    cached = _read_fresh_json_cache(cache_path, max_age_seconds=AAFC_NASDI_CATALOG_CACHE_SECONDS)
    if cached is not None:
        return {**cached, "cache_hit": True}
    if offline_only:
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return {**cached, "cache_hit": True, "cache_stale": True}
        raise OfflineCacheMissError("offline NASDI catalog cache miss; external request not attempted")
    query = urllib.parse.urlencode(
        {
            "where": "1=1",
            "outFields": "OBJECTID,Name,dateEnd,tType",
            "returnGeometry": "false",
            "orderByFields": "dateEnd DESC",
            "resultRecordCount": "128",
            "f": "json",
        }
    )
    request = urllib.request.Request(f"{source}/query?{query}", headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    if data.get("error"):
        raise RuntimeError(f"AAFC NASDI catalog error: {data['error'].get('message') or data['error']}")
    candidates: list[dict[str, Any]] = []
    for feature in data.get("features") or []:
        attributes = feature.get("attributes") if isinstance(feature, dict) else None
        if not isinstance(attributes, dict) or str(attributes.get("tType") or "").lower() != time_window:
            continue
        object_id = _parse_int(attributes.get("OBJECTID") if attributes.get("OBJECTID") is not None else attributes.get("objectid"))
        observation_end = _arcgis_date_to_iso(attributes.get("dateEnd"))
        if object_id is None or observation_end is None:
            continue
        candidates.append(
            {
                "indicator": indicator,
                "label": definition["label"],
                "units": definition["units"],
                "time_window": time_window,
                "object_id": object_id,
                "catalog_name": str(attributes.get("Name") or attributes.get("name") or "")[:160],
                "observation_end": observation_end,
                "source": source,
                "raster_function": definition["raster_function"],
                "cache_hit": False,
            }
        )
    if not candidates:
        raise RuntimeError(f"AAFC NASDI catalog returned no raster for {indicator}/{time_window}")
    selected = max(candidates, key=lambda item: (str(item["observation_end"]), int(item["object_id"])))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(selected, indent=2), encoding="utf-8")
    return selected


def _aafc_nasdi_identify_point(
    *,
    indicator: str,
    time_window: str,
    catalog_item: dict[str, Any],
    latitude: float,
    longitude: float,
    cache_dir: str,
    timeout: int,
    offline_only: bool = False,
) -> dict[str, Any]:
    _validate_canadian_nasdi_point(latitude=latitude, longitude=longitude)
    object_id = int(catalog_item["object_id"])
    cache_path = (repo_path(cache_dir) / _safe_name(
        f"nasdi_value_{AAFC_NASDI_CACHE_VERSION}_{indicator}_{time_window}_{object_id}_{latitude:.7f}_{longitude:.7f}"
    )).with_suffix(".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return {**payload, "cache_hit": True}
    if offline_only:
        raise OfflineCacheMissError("offline NASDI value cache miss; external request not attempted")
    x, y = _wgs84_to_web_mercator(longitude=longitude, latitude=latitude)
    geometry = {"x": x, "y": y, "spatialReference": {"wkid": 3857}}
    mosaic_rule = {"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [object_id]}
    query = urllib.parse.urlencode(
        {
            "geometry": json.dumps(geometry, separators=(",", ":")),
            "geometryType": "esriGeometryPoint",
            "mosaicRule": json.dumps(mosaic_rule, separators=(",", ":")),
            "returnGeometry": "false",
            "returnCatalogItems": "true",
            "returnPixelValues": "true",
            "f": "json",
        }
    )
    source = str(catalog_item["source"])
    request = urllib.request.Request(f"{source}/identify?{query}", headers={"User-Agent": "agronomy-agent-local-tools/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    if data.get("error"):
        raise RuntimeError(f"AAFC NASDI identify error: {data['error'].get('message') or data['error']}")
    raw_value = _parse_arcgis_pixel_value(data.get("value"))
    scale_factor = float(AAFC_NASDI_INDICATORS[indicator].get("raw_scale_factor") or 1.0)
    value = raw_value * scale_factor if raw_value is not None else None
    response_object_id = _parse_int(data.get("objectId"))
    if response_object_id not in {None, 0, object_id}:
        raise RuntimeError(f"AAFC NASDI identify returned catalog raster {response_object_id}, expected {object_id}")
    summary = {
        "indicator": indicator,
        "label": catalog_item["label"],
        "units": catalog_item["units"],
        "time_window": time_window,
        "value": value,
        "raw_value": raw_value,
        "normalization": "raw_ratio_times_100" if scale_factor == 100.0 else "none",
        "direction": _aafc_nasdi_value_direction(indicator, value),
        "latitude": round(latitude, 7),
        "longitude": round(longitude, 7),
        "object_id": object_id,
        "request_lock_object_id": object_id,
        "response_object_id": response_object_id,
        "catalog_name": catalog_item["catalog_name"],
        "observation_end": catalog_item["observation_end"],
        "source": source,
        "raster_function": catalog_item["raster_function"],
        "cache_hit": False,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _summarize_aafc_nasdi_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for indicator in AAFC_NASDI_INDICATORS:
        rows = [item for item in observations if item.get("indicator") == indicator and _is_number(item.get("value"))]
        if not rows:
            continue
        values = [float(item["value"]) for item in rows]
        summary[indicator] = {
            "label": rows[0].get("label"),
            "units": rows[0].get("units"),
            "time_window": rows[0].get("time_window"),
            "observation_end": max(str(item.get("observation_end") or "") for item in rows),
            "sample_count": len(rows),
            "value": round(values[0], 6) if len(values) == 1 else None,
            "min": round(min(values), 6),
            "mean": round(sum(values) / len(values), 6),
            "max": round(max(values), 6),
            "catalog_items": sorted({str(item.get("catalog_name") or "") for item in rows if item.get("catalog_name")}),
        }
    return summary


def _read_fresh_json_cache(path: Path, *, max_age_seconds: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    age_seconds = max(0.0, dt.datetime.now(dt.UTC).timestamp() - path.stat().st_mtime)
    if age_seconds > max_age_seconds:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _arcgis_date_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).strip().isdigit():
            return dt.datetime.fromtimestamp(float(value) / 1000.0, tz=dt.UTC).date().isoformat()
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def _wgs84_to_web_mercator(*, longitude: float, latitude: float) -> tuple[float, float]:
    clipped_latitude = max(-85.05112878, min(85.05112878, float(latitude)))
    x = float(longitude) * 20_037_508.342789244 / 180.0
    y = math.log(math.tan((90.0 + clipped_latitude) * math.pi / 360.0)) / math.pi * 20_037_508.342789244
    return x, y


def _parse_arcgis_pixel_value(value: Any) -> float | None:
    if value is None or str(value).strip().lower() in {"", "nodata", "no data", "nan", "null"}:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _aafc_nasdi_value_direction(indicator: str, value: float | None) -> str | None:
    if value is None or indicator not in {"spi", "spei"}:
        return None
    if abs(value) < 0.05:
        return "near_zero_standardized_anomaly"
    return "positive_standardized_anomaly" if value > 0 else "negative_standardized_anomaly"


def _summarize_aafc_aci_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    classes: dict[str, dict[str, Any]] = {}
    for sample in samples:
        code = sample.get("aci_code")
        label = sample.get("aci_label") or (AAFC_ACI_CODE_LABELS.get(int(code)) if isinstance(code, int) else None) or "Unknown"
        key = str(code if code is not None else "unknown")
        item = classes.setdefault(key, {"aci_code": code, "aci_label": label, "count": 0})
        item["count"] += 1
    ordered = sorted(classes.values(), key=lambda item: item["count"], reverse=True)
    return {"sample_count": len(samples), "dominant_class": ordered[0] if ordered else None, "classes": ordered}


def _parse_cdl_value_response(raw: str) -> tuple[int | None, str | None]:
    text = re.sub(r"<[^>]+>", " ", raw).strip()
    match = re.search(r"\b(\d{1,3})\b(?:\s*[:,-]\s*([A-Za-z0-9][A-Za-z0-9/ &._-]+))?", text)
    if not match:
        return None, None
    code = int(match.group(1))
    label = (match.group(2) or "").strip() or CDL_CODE_LABELS.get(code)
    return code, label


def _lonlat_to_usgs_conus_albers(*, longitude: float, latitude: float) -> tuple[float, float]:
    # CropScape expects the USA Contiguous Albers Equal Area Conic projection
    # documented by NASS. Parameters match the USGS/NAD83 Albers definition.
    semi_major = 6_378_137.0
    inverse_flattening = 298.257222101
    flattening = 1 / inverse_flattening
    eccentricity = math.sqrt(2 * flattening - flattening * flattening)
    lat_1 = math.radians(29.5)
    lat_2 = math.radians(45.5)
    lat_0 = math.radians(23.0)
    lon_0 = math.radians(-96.0)
    phi = math.radians(latitude)
    lam = math.radians(longitude)

    def m(angle: float) -> float:
        sin_phi = math.sin(angle)
        return math.cos(angle) / math.sqrt(1 - eccentricity * eccentricity * sin_phi * sin_phi)

    def q(angle: float) -> float:
        sin_phi = math.sin(angle)
        e_sin = eccentricity * sin_phi
        return (1 - eccentricity * eccentricity) * (
            sin_phi / (1 - e_sin * e_sin)
            - (1 / (2 * eccentricity)) * math.log((1 - e_sin) / (1 + e_sin))
        )

    m1 = m(lat_1)
    m2 = m(lat_2)
    q1 = q(lat_1)
    q2 = q(lat_2)
    q0 = q(lat_0)
    q_phi = q(phi)
    n = (m1 * m1 - m2 * m2) / (q2 - q1)
    c_value = m1 * m1 + n * q1
    rho = semi_major * math.sqrt(c_value - n * q_phi) / n
    rho0 = semi_major * math.sqrt(c_value - n * q0) / n
    theta = n * (lam - lon_0)
    x = rho * math.sin(theta)
    y = rho0 - rho * math.cos(theta)
    return x, y


def _quickstats_api_key(explicit_key: str | None = None) -> str | None:
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    for env_var in NASS_QUICKSTATS_ENV_VARS:
        value = os.getenv(env_var)
        if value and value.strip():
            return value.strip()
    return None


def _openet_api_key(explicit_key: str | None = None) -> str | None:
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    for env_var in OPENET_ENV_VARS:
        value = os.getenv(env_var)
        if value and value.strip():
            return value.strip()
    return None


def _normalize_openet_records(data: Any, variable: str) -> list[dict[str, Any]]:
    rows: list[Any]
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("data") or data.get("timeseries") or data.get("records") or data.get("items") or []
        if not rows and all(not isinstance(value, (list, tuple)) for value in data.values()):
            rows = [{"date": key, "value": value} for key, value in data.items()]
        if not rows and isinstance(data.get("features"), list):
            rows = [feature.get("properties") for feature in data["features"] if isinstance(feature, dict)]
    else:
        rows = []

    variable_key = str(variable or "").lower()
    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date_value = (
            row.get("date")
            or row.get("time")
            or row.get("start_date")
            or row.get("start")
            or row.get("system:time_start")
        )
        numeric_value = None
        for key, value in row.items():
            clean_key = str(key).lower()
            if clean_key in {variable_key, variable_key.lower(), "et", "value", "mean"}:
                numeric_value = _parse_number(value)
                if numeric_value is not None:
                    break
        if numeric_value is None:
            continue
        out: dict[str, Any] = {"value": numeric_value}
        if date_value is not None:
            out["date"] = str(date_value)
        for key in ("model", "variable", "units", "count", "et", "etof", "ndvi"):
            if key in row and key not in out:
                out[key] = row[key]
        records.append(out)
    return records


def _summarize_openet_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    clean = [float(record["value"]) for record in records if _is_number(record.get("value"))]
    if not clean:
        return {}
    return {
        "periods": len(clean),
        "min": round(min(clean), 3),
        "mean": round(sum(clean) / len(clean), 3),
        "max": round(max(clean), 3),
        "sum": round(sum(clean), 3),
    }


def _geojson_geometry_to_wkt(geometry: dict[str, Any]) -> tuple[str, str, tuple[float, float, float, float], int]:
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be a GeoJSON geometry object")
    geometry_type = str(geometry.get("type") or "").strip()
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        lon, lat = _validate_lon_lat_pair(coordinates)
        return f"point({_wkt_coord(lon, lat)})", geometry_type, (lon, lat, lon, lat), 1
    if geometry_type == "Polygon":
        rings = _validate_polygon_rings(coordinates)
        bbox, vertex_count = _bbox_for_points(point for ring in rings for point in ring)
        return f"polygon({_wkt_rings(rings)})", geometry_type, bbox, vertex_count
    if geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError("MultiPolygon coordinates must be a non-empty list")
        polygons = [_validate_polygon_rings(polygon) for polygon in coordinates]
        bbox, vertex_count = _bbox_for_points(point for polygon in polygons for ring in polygon for point in ring)
        polygon_text = ",".join(f"({_wkt_rings(polygon)})" for polygon in polygons)
        return f"multipolygon({polygon_text})", geometry_type, bbox, vertex_count
    raise ValueError("NRCS geometry lookup supports Point, Polygon, or MultiPolygon geometry")


def _validate_polygon_rings(value: Any) -> list[list[tuple[float, float]]]:
    if not isinstance(value, list) or not value:
        raise ValueError("Polygon coordinates must contain at least one ring")
    rings: list[list[tuple[float, float]]] = []
    for raw_ring in value:
        if not isinstance(raw_ring, list) or len(raw_ring) < 4:
            raise ValueError("Polygon rings must contain at least four coordinate pairs")
        ring = [_validate_lon_lat_pair(point) for point in raw_ring]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        if len(ring) < 4:
            raise ValueError("Polygon rings must contain at least four coordinate pairs")
        rings.append(ring)
    return rings


def _validate_lon_lat_pair(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("coordinate must be [longitude, latitude]")
    lon = float(value[0])
    lat = float(value[1])
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("coordinate longitude/latitude out of range")
    return lon, lat


def _bbox_for_points(points: Any) -> tuple[tuple[float, float, float, float], int]:
    coords = list(points)
    if not coords:
        raise ValueError("geometry has no coordinates")
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]
    return (min(xs), min(ys), max(xs), max(ys)), len(coords)


def _wkt_rings(rings: list[list[tuple[float, float]]]) -> str:
    return ",".join(f"({','.join(_wkt_coord(lon, lat) for lon, lat in ring)})" for ring in rings)


def _wkt_coord(lon: float, lat: float) -> str:
    return f"{lon:.8f} {lat:.8f}"


def _parse_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text.upper() in {"(D)", "(Z)", "NA"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_iso_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date must be YYYY-MM-DD: {value}") from exc


def _validate_date(value: str) -> None:
    try:
        dt.datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"date must be YYYYMMDD: {value}") from exc


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
