from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agronomy_agent.skill_registry import skill_metadata


@dataclass(frozen=True)
class ToolNote:
    name: str
    text: str
    skill_id: str
    provenance: tuple[str, ...]
    boundary: str
    risk_class: str
    eval_tags: tuple[str, ...]


PRODUCT_RE = re.compile(
    r"\b(herbicide|fungicide|insecticide|pesticide|product|rate|spray|spray decision|apply|tank mix|burndown|labels?|label context|label metadata|ppls|epa registration|epa reg|current label|treatment|control|recommendation|weed control|disease|leaf spotting|confirmed disease|rotation restrictions?)\b",
    re.I,
)
FERTILITY_RE = re.compile(
    r"\b(fertil\w*|fertigation|nutrient|nutrient balance|micronutrient|deficien\w*|chlorosis|patchy chlorosis|nitrogen|phosphorus|potassium|sulfur|lime|soil[- ]tests?|tissue[- ]tests?|soil zones?|sampling design|management zones?|old soil tests?|ppm|cec|organic matter|pH|yield goal|crop removal|partial budget|net return|added cost|reduced cost|added return|reduced return|variable-rate|variable rate|roi|pay|payback|farm books|conservation practice|precision practice|remote imagery|yield maps?|weak zones?)\b",
    re.I,
)
WEATHER_RE = re.compile(
    r"\b(weather|wind|rain|rainfall|temperature|inversion|spray|spray window|spray decision|drift|volatilization|forecast|frost|cold|cool wet|hot dry|humid|humidity|leaf wetness|wet spring|warm forecast|heat|evaporative demand|evapotranspiration|leaching|leaching risk|irrigation|water quality|climate normals?|historical gridded|gridded weather|poorly drained|delayed|sensitive|downwind|buffer|openet|daymet|nasa power|et\b)\b",
    re.I,
)
FIELD_DATA_RE = re.compile(
    r"\b(yield maps?|variable rate|zone|weak zones?|prescription|soil ec|ndvi|satellite|remote imagery|as-applied|field data|records|grower records|field records|farm records|farm books|baseline records?|yield history|georeference|calibration|applied information technolog|source cards?|sources checked|source status|cache timestamp|provenance|trace|public priors?|public context|public adapter|adapter times out|live data|retrieved|unavailable|not configured|field boundary|uploaded boundary|draws? a field|shapefile|geojson|geopackage|geometry|polygon|crs|projection|coordinate|crop history|cropland data layer|cdl|quick stats|nass|field scouting|scouting|beneficial insects?|natural enemies|pest species|pest history|pest pressure|economic threshold|recurring insect pressure|repeated products|unknown weeds?|weed identification|weed control|escap\w+|patches|growth stage|seed treatment|planting conditions|on-farm trial|trial design|check strips?|yield monitor|public variety trials?|plot result|seed quality|germination|vigor|standability|agronomic evidence|field tests?|feed tests?|lab tests?|diagnostic lab|sample quality|photos?|samples?|visible runoff|tile outlet|drainage ditch|drainage improvements?|wet spots?|riparian|grazing access|harvest timing|testing|segregation|storage|moisture|drying|quality|mycotoxin|field truth|ground truth|soil-survey|soil survey|map context|soil context|weather context|label context|soil sampling|sampling design|management zones?|old soil tests?|field symptoms?|visual symptoms?|diagnosis|sample vs visual|leaf spotting|confirmed disease|patchy chlorosis|herbicide history|carryover|rotation restrictions?|preemergence|residual activation|activation|stand loss|weak transplants?|transplant quality|field measurement|surface condition|infiltration|climate normals?|historical gridded|flooding duration|conservation practice|precision practice|partial budget|sensitivity|uncertainty|new practice|payback|implementation cost|operating cost|cost-share|program eligibility|expected response|risk reduction|time horizon|water nitrate test|irrigation amount|applied water|flowmeter|pollinator habitat|refuge|worker safety|quarantine|movement boundary)\b",
    re.I,
)
SALINITY_RE = re.compile(r"\b(salinity|sodicity|saline|sodic|white crust|ec\b|electrical conductivity|sar\b|esp\b|irrigation water)\b", re.I)
COMPACTION_RE = re.compile(r"\b(compaction|traffic|restrictive layer|hardpan|plow pan|ponding|shallow roots?|rooting depth|penetrometer|soil pit|probe)\b", re.I)
PESTICIDE_SAFETY_RE = re.compile(
    r"\b(health|safety|environmental checks?|ppe|personal protective|restricted entry|rei\b|preharvest|preharvest interval|phi\b|storage|handling|sensitive area|drift|buffer|setback|recordkeeping|records?|spray record|application record|worker safety|pollinator|bee advisory|water protection|water quality|sensitive crop|refuge|stewardship|quarantine|regulated pest|invasive|movement boundary|do not move material|spray decision)\b",
    re.I,
)
RESISTANCE_RE = re.compile(r"\b(resistance|resistant|escapes?|mode of action|site of action|same herbicide|rotate)\b", re.I)
NUTRIENT_4R_RE = re.compile(
    r"\b(4r|right source|right rate|right time|right place|nutrient management plan|manure history|manure credit|manure analysis|tile drainage|tile outlet|drainage ditch|nitrate loss|nitrate-loss|edge-of-field|water quality|runoff|leaching|irrigation-water nitrate|irrigation water nitrate|water nitrate|nitrogen credit|fertilizer credit|nutrient credit|split timing|placement)\b",
    re.I,
)


EXPLICIT_TOOL_FALLBACK_TEXT = {
    "label_guard": "Product or trait-stewardship context is label-bound. Keep advice at the decision-framework level until crop/site, jurisdiction, target use, and the current local label are verified.",
    "fertility_guard": "Fertility or economics context is decision-support only until recent soil tests, crop and yield goal, local calibration, cost assumptions, and field records are verified.",
    "weather_guard": "Weather-sensitive advice should expose source status and timing, then check wind, rainfall, temperature, humidity or leaf wetness, forecast window, and weather-data limits.",
    "field_data_guard": "Field-data workflows should show what was checked, what was unavailable, and what private field evidence is missing before turning public context into a field-specific recommendation.",
    "salinity_sodicity_guard": "Salinity or sodicity decisions need soil and water evidence, sodium hazard, drainage/leaching feasibility, and field pattern before symptoms are treated as proof.",
    "soil_structure_guard": "Soil-structure decisions need traffic, moisture, rooting-depth, infiltration or ponding evidence, and layer depth verified before management changes.",
    "pesticide_safety_guard": "Pesticide and trait-stewardship advice must keep label, PPE, REI, PHI, drift or buffer, water, pollinator, worker-safety, recordkeeping, and movement boundaries visible.",
    "resistance_management_guard": "Resistance reasoning should verify pest identity and field history, scout escapes, rotate or mix effective modes of action, and include nonchemical tactics.",
    "nutrient_4r_guard": "Nutrient decisions should cover right source, rate, time, and place, plus credits, soil tests, timing, placement, runoff, leaching, tile, and record boundaries.",
}


def label_guard(query: str) -> ToolNote | None:
    if not PRODUCT_RE.search(query):
        return None
    missing = []
    for label, pattern in {
        "crop": r"\b(corn|soybean|wheat|canola|cotton|rice|sorghum|alfalfa)\b",
        "target pest or use": r"\b(weed|grass|broadleaf|aphid|fungus|rust|blight|mildew|rootworm|burndown|residual)\b",
        "jurisdiction or label": r"\b(label|state|province|county|epa|pmra|registration)\b",
    }.items():
        if not re.search(pattern, query, re.I):
            missing.append(label)
    if missing:
        return _tool_note(
            "label_guard",
            "Product advice is label-bound. Before naming a product or rate, ask for: "
            + ", ".join(missing)
            + ". Keep advice at the mode-of-action or decision-framework level until label context is present.",
        )
    return _tool_note(
        "label_guard",
        "Product context includes enough detail to discuss options, but final rates and restrictions still require the current local label.",
    )


def fertility_guard(query: str) -> ToolNote | None:
    if not FERTILITY_RE.search(query):
        return None
    missing = []
    for label, pattern in {
        "recent soil test": r"\b(soil test|ppm|bray|olsen|mehlich|cec|organic matter|om\b|pH)\b",
        "crop and yield goal": r"\b(corn|soybean|wheat|canola|cotton|rice|yield goal|bu/ac|t/ac)\b",
    }.items():
        if not re.search(pattern, query, re.I):
            missing.append(label)
    if missing:
        return _tool_note(
            "fertility_guard",
            "Fertility recommendations should not jump to a rate without "
            + ", ".join(missing)
            + ". Give a sampling/interpretation workflow and state what data would change the recommendation.",
        )
    return _tool_note(
        "fertility_guard",
        "Fertility context is partially specified. Tie recommendations to soil-test method, crop removal, yield goal, pH, and local calibration curves.",
    )


def weather_guard(query: str) -> ToolNote | None:
    if not WEATHER_RE.search(query):
        return None
    if re.search(r"\b(irrigation|evapotranspiration|openet|soil moisture|water scheduling)\b", query, re.I) and not re.search(
        r"\b(spray|herbicide|fungicide|insecticide|pesticide|drift|label)\b", query, re.I
    ):
        return _tool_note(
            "weather_guard",
            "Weather and evapotranspiration are planning priors for irrigation, not field sensors. Check source location and time, then combine them with root-zone soil moisture, crop stage, recent irrigation or rain, infiltration, drainage, and crop stress.",
        )
    if re.search(r"\b(disease|humidity|leaf wetness|canopy)\b", query, re.I) and not re.search(
        r"\b(spray|product|label)\b", query, re.I
    ):
        return _tool_note(
            "weather_guard",
            "Humidity, leaf wetness, rainfall, and temperature can indicate disease risk but do not identify a pathogen. Pair the weather window with symptoms, field pattern, crop stage, variety, and a representative diagnostic sample.",
        )
    return _tool_note(
        "weather_guard",
        "Weather-sensitive recommendations should check wind speed/direction, gusts, temperature inversions, rainfall timing, temperature, and label-specific buffers.",
    )


def field_data_guard(query: str) -> ToolNote | None:
    if not FIELD_DATA_RE.search(query):
        return None
    if re.search(r"\b(diagnosis|symptoms?|photos?|samples?|diagnostic lab|scouting)\b", query, re.I) and not re.search(
        r"\b(map|layer|boundary|yield map|prescription|geometry|georeference)\b", query, re.I
    ):
        return _tool_note(
            "field_data_guard",
            "Diagnostic evidence should preserve crop and stage, whole-plant and close-up symptoms, field pattern, timing, recent conditions, representative affected and unaffected samples, and confirmation status before treatment advice.",
        )
    if not re.search(r"\b(map|layer|boundary|yield map|prescription|geometry|georeference|as-applied|management zone)\b", query, re.I):
        return _tool_note(
            "field_data_guard",
            "Separate observations and public priors from measured field evidence. State what was actually checked, what remains unknown, and which local observation, measurement, or record would change the recommendation.",
        )
    return _tool_note(
        "field_data_guard",
        "Field-data workflows should distinguish raw observations from recommendations: validate layers, align boundaries, normalize years, define management zones, then generate a prescription with an audit trail.",
    )


def salinity_sodicity_guard(query: str) -> ToolNote | None:
    if not SALINITY_RE.search(query):
        return None
    return _tool_note(
        "salinity_sodicity_guard",
        "Salinity/sodicity diagnosis needs paired soil and water evidence: saturated-paste or equivalent soil EC, irrigation-water EC, sodium hazard as SAR or ESP, pH where relevant, drainage/leaching feasibility, and field pattern. Do not treat patchy stunting as salinity or sodicity from symptoms alone.",
    )


def soil_structure_guard(query: str) -> ToolNote | None:
    if not COMPACTION_RE.search(query):
        return None
    return _tool_note(
        "soil_structure_guard",
        "Compaction or restrictive-layer diagnosis should verify traffic pattern, soil moisture at diagnosis, rooting depth, infiltration or ponding, and depth to the layer with a probe, penetrometer, or soil pit before choosing controlled traffic, targeted tillage, cover crops, or drainage changes.",
    )


def pesticide_safety_guard(query: str) -> ToolNote | None:
    if not PESTICIDE_SAFETY_RE.search(query):
        return None
    return _tool_note(
        "pesticide_safety_guard",
        "Pesticide recommendations must include label, PPE, REI, PHI where relevant, buffer/drift controls, water or sensitive-area protection, storage/handling, and disposal/recordkeeping boundaries before product convenience or timing.",
    )


def resistance_management_guard(query: str) -> ToolNote | None:
    if not RESISTANCE_RE.search(query):
        return None
    return _tool_note(
        "resistance_management_guard",
        "Resistance reasoning should identify the weed/pest and field history, scout surviving escapes, verify the label, rotate or mix multiple effective modes/sites of action, and include nonchemical tactics such as crop rotation, mechanical control, sanitation, or altered timing.",
    )


def nutrient_4r_guard(query: str) -> ToolNote | None:
    if not NUTRIENT_4R_RE.search(query):
        return None
    return _tool_note(
        "nutrient_4r_guard",
        "A 4R nutrient plan should explicitly cover right source, right rate, right time, and right place; account for soil test, yield goal, manure or legume credits, manure analysis, tile/leaching/runoff risk, placement/timing, and records.",
    )


GuardExecutor = Callable[[str], ToolNote | None]

_GUARD_EXECUTOR_INVENTORY: Mapping[str, GuardExecutor] = {
    "label_guard": label_guard,
    "fertility_guard": fertility_guard,
    "weather_guard": weather_guard,
    "field_data_guard": field_data_guard,
    "salinity_sodicity_guard": salinity_sodicity_guard,
    "soil_structure_guard": soil_structure_guard,
    "pesticide_safety_guard": pesticide_safety_guard,
    "resistance_management_guard": resistance_management_guard,
    "nutrient_4r_guard": nutrient_4r_guard,
}


def registered_guard_ids() -> tuple[str, ...]:
    """Return guard IDs from the executable inventory in stable order."""

    return tuple(_GUARD_EXECUTOR_INVENTORY)


def run_tools(query: str, enabled_tools: tuple[str, ...] | None = None) -> list[ToolNote]:
    if enabled_tools is None:
        selected_names = registered_guard_ids()
    else:
        selected_names = tuple(dict.fromkeys(str(name) for name in enabled_tools))
        unknown = tuple(
            name for name in selected_names if name not in _GUARD_EXECUTOR_INVENTORY
        )
        if unknown:
            raise ValueError(
                "unknown enabled guard(s): "
                f"{', '.join(unknown)}; registered guards: "
                f"{', '.join(registered_guard_ids())}"
            )
    notes: list[ToolNote] = []
    for name in selected_names:
        note = _GUARD_EXECUTOR_INVENTORY[name](query)
        if note is None and enabled_tools is not None:
            note = _tool_note(name, EXPLICIT_TOOL_FALLBACK_TEXT[name])
        if note is not None:
            notes.append(note)
    return notes


def _tool_note(name: str, text: str) -> ToolNote:
    metadata = skill_metadata(name)
    return ToolNote(
        name=name,
        text=text,
        skill_id=str(metadata["skill_id"]),
        provenance=tuple(str(item) for item in metadata["provenance"]),
        boundary=str(metadata["boundary"]),
        risk_class=str(metadata["risk_class"]),
        eval_tags=tuple(str(item) for item in metadata["eval_tags"]),
    )
