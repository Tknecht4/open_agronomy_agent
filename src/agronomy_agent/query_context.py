from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from agronomy_agent.decision_capsule import build_decision_capsule, merge_topics


_AAFC_CROP_HEALTH_PRODUCT_PATTERN = (
    r"(?:\baafc\b.{0,80}\b(?:crop[- ]health (?:index|indices|grids?|layers?|products?)|crop stress index|crop development stage|growth[- ]stage raster)\b|"
    r"\b(?:crop[- ]health (?:index|indices|grids?|layers?|products?)|crop stress index|water deficit index)\b|"
    r"\b(?:crop development|crop[- ]stage|growth[- ]stage) (?:layer|raster|product|values?)\b|"
    r"\b(?:indices? de sant[eé] des cultures|indice de stress des cultures|"
    r"stade de d[eé]veloppement de la culture)\b)"
)
_AAFC_ANNUAL_CROP_INVENTORY_PATTERN = (
    r"(?:\baafc\b.{0,100}\b(?:annual crop inventory|crop type mapping|crop[- ]class(?:ification)? raster)\b|"
    r"\bannual crop inventory(?:\s+\d{4})?\b)"
)

_AAFC_HISTORICAL_CROP_YIELD_SLC_PATTERN = (
    r"(?:\baafc\b.{0,100}\b(?:estimated )?(?:historical|hist)\w*\b.{0,30}\bcrop[- ]?(?:yield|yld)s?\b.{0,40}\bslc\b|"
    r"\baafc\b.{0,100}\bhistorical[- ]?yield[- ]?by[- ]?slc\b|"
    r"\b(?:estimated )?historical crop[- ]?yields? in canada by (?:soil landscapes? of canada|slc)\b|"
    r"\bhistorical crop[- ]?yields?[- ]by[- ]slc\b|"
    r"\bhistorical[- ]?yield[- ]?by[- ]?slc\b|"
    r"\bslc\b.{0,50}\b(?:historical|yield|yld|kg\s*/?\s*ha|kg ha)\b)"
)

_CANADIAN_REGIONAL_CONTEXT_PRODUCT_PATTERN = (
    r"(?:\b(?:quebec|québec) agro[- ]pedological atlas\b|\bagro[- ]pedological atlas of (?:quebec|québec)\b|"
    r"\brendement des cultures au canada\b|\bpr[eé]visions? canadiennes? du rendement des cultures\b|"
    r"\b(?:geonb|new brunswick) agricultural soil classes\b|"
    r"\bnewfoundland and labrador weather station climate monitoring data\b|"
    r"\baafc\b.{0,80}\bsoil (?:erosion|erision|eroshun) risk(?: indicator)?(?:\s+2021)?\b|"
    r"\baafc\b.{0,40}\b(?:erosion|erision|eroshun)(?: risk)? (?:class|map|layer)\b|\bsoileri\b|"
    r"\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)? (?:map|layer)\b|"
    r"\b(?:map|layer)\b.{0,40}\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)?\b)"
)
_GENERIC_CROP_CONTEXT = {"crop", "crops", "field crop", "field crops", "annual crop", "annual crops"}
_CROP_SCOPE_WILDCARDS = {"all"}
_DETAILED_SOIL_LAYER_IDS = {"ab_detailed_soil", "mb_detailed_soil"}


US_STATE_NAME_TO_ALPHA = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC",
    "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN",
    "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}

CANADIAN_PROVINCE_NAMES_TO_CODE = {
    "ALBERTA": "AB", "BRITISH COLUMBIA": "BC", "MANITOBA": "MB", "NEW BRUNSWICK": "NB",
    "NEWFOUNDLAND AND LABRADOR": "NL", "NOVA SCOTIA": "NS", "ONTARIO": "ON",
    "PRINCE EDWARD ISLAND": "PE", "QUEBEC": "QC", "SASKATCHEWAN": "SK",
    "NORTHWEST TERRITORIES": "NT", "NUNAVUT": "NU", "YUKON": "YT",
}
CANADIAN_PROVINCE_NAME_ALIASES = {
    "COLOMBIE-BRITANNIQUE": "BRITISH COLUMBIA",
    "COLOMBIE BRITANNIQUE": "BRITISH COLUMBIA",
    "NOUVEAU-BRUNSWICK": "NEW BRUNSWICK",
    "NOUVEAU BRUNSWICK": "NEW BRUNSWICK",
    "TERRE-NEUVE-ET-LABRADOR": "NEWFOUNDLAND AND LABRADOR",
    "TERRE-NEUVE ET LABRADOR": "NEWFOUNDLAND AND LABRADOR",
    "NOUVELLE-ÉCOSSE": "NOVA SCOTIA",
    "NOUVELLE ECOSSE": "NOVA SCOTIA",
    "ÎLE-DU-PRINCE-ÉDOUARD": "PRINCE EDWARD ISLAND",
    "ILE-DU-PRINCE-EDOUARD": "PRINCE EDWARD ISLAND",
    "ÎLE DU PRINCE ÉDOUARD": "PRINCE EDWARD ISLAND",
    "ILE DU PRINCE EDOUARD": "PRINCE EDWARD ISLAND",
    "QUÉBEC": "QUEBEC",
}
CANADIAN_PROVINCE_CODES = set(CANADIAN_PROVINCE_NAMES_TO_CODE.values())
CANADIAN_PROVINCE_TEXT_ALIASES = {
    "AB": "alberta",
    "BC": "british columbia",
    "MB": "manitoba",
    "NB": "new brunswick",
    "NL": "newfoundland and labrador",
    "NS": "nova scotia",
    "ON": "ontario",
    "PE": "prince edward island",
    "PEI": "prince edward island",
    "QC": "quebec",
    "SK": "saskatchewan",
}

_CROP_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("alfalfa", ("alfalfa",)),
    ("almond", ("almond", "almonds")),
    ("apple", ("apple", "apples", "orchard", "pommier", "pommiers", "verger")),
    ("barley", ("barley", "orge")),
    ("blueberry", ("blueberry", "blueberries", "bleuet", "bleuets")),
    ("canola", ("canola", "rapeseed", "colza")),
    ("chickpea", ("chickpea", "garbanzo", "pois chiche", "pois chiches")),
    ("corn", ("corn", "maize", "maïs")),
    ("cotton", ("cotton",)),
    ("cucumber", ("cucumber", "cucumbers", "concombre", "concombres")),
    ("dry bean", ("dry bean", "dry beans", "navy bean", "pinto bean")),
    ("field pea", ("field pea", "field peas", "pois de grande culture", "pois de champ")),
    ("field vegetables", ("field vegetable", "field vegetables", "légume de plein champ", "légumes de plein champ", "culture maraîchère", "cultures maraîchères")),
    ("grape", ("grape", "grapes", "vineyard")),
    ("leafy greens", ("leafy green", "leafy greens")),
    ("lettuce", ("lettuce",)),
    ("lentil", ("lentil", "lentils", "lentille", "lentilles")),
    ("oat", ("oat", "oats", "avoine")),
    ("peanut", ("peanut", "peanuts")),
    ("pepper", ("pepper", "peppers")),
    ("potato", ("potato", "potatoes", "pomme de terre", "pommes de terre")),
    ("rice", ("rice",)),
    ("sorghum", ("sorghum", "milo", "sorghum-sudan", "sorghum sudan", "sorghum-sudangrass", "sorghum sudangrass", "sudangrass", "sudan grass")),
    ("soybean", ("soybean", "soybeans", "soya")),
    ("strawberry", ("strawberry", "strawberries")),
    ("spinach", ("spinach",)),
    ("sugar beet", ("sugar beet", "sugar beets")),
    ("sunflower", ("sunflower", "sunflowers")),
    ("tomato", ("tomato", "tomatoes")),
    ("wheat", ("wheat", "blé", "ble")),
)
_SPECIALTY_CROPS = {
    "almond",
    "apple",
    "blueberry",
    "cucumber",
    "field vegetables",
    "grape",
    "leafy greens",
    "lettuce",
    "pepper",
    "potato",
    "spinach",
    "strawberry",
    "tomato",
}

_SOURCE_GROUNDED_PATTERNS = (
    r"\busing only (?:the )?(?:supplied|provided|following)\b",
    r"\buse only (?:the )?(?:supplied|provided|following)\b",
    r"\banswer (?:the question )?from (?:the )?(?:supplied|provided|following) (?:excerpt|context|document|passage)\b",
    r"\bextension excerpt\b[\s\S]*\bquestion\b",
    r"\bbegin (?:supplied )?(?:context|excerpt|document)\b",
)


@dataclass(frozen=True)
class QueryContextSignals:
    query_text: str
    crops: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    target_jurisdictions: tuple[str, ...]
    regional_terms: tuple[str, ...]
    topics: tuple[str, ...]
    query_terms: tuple[str, ...]
    pest_entities: tuple[str, ...]
    country: str | None
    source_grounded: bool
    regional_context_requested: bool
    field_context: dict[str, Any]

    @property
    def primary_crop(self) -> str | None:
        return self.crops[0] if self.crops else None

    @property
    def primary_region(self) -> str | None:
        if self.target_jurisdictions:
            return self.target_jurisdictions[0]
        return self.jurisdictions[0] if self.jurisdictions else (self.regional_terms[0] if self.regional_terms else None)


@dataclass(frozen=True)
class EvidenceFitResult:
    docs: tuple[Any, ...]
    dropped: tuple[dict[str, str], ...]


def is_source_grounded_question(question: str) -> bool:
    return any(re.search(pattern, question, re.IGNORECASE) for pattern in _SOURCE_GROUNDED_PATTERNS)


def analyze_query_context(question: str, field_context: dict[str, Any] | None = None) -> QueryContextSignals:
    text = question.strip()
    lower = text.lower()
    provided = dict(field_context or {})

    crops = _extract_crops(lower)
    explicit_crop = _clean(provided.get("crop_current") or provided.get("crop") or provided.get("commodity"))
    if explicit_crop:
        normalized_explicit_crops = _extract_crops(explicit_crop.lower())
        fallback_crops = () if explicit_crop.lower() in _GENERIC_CROP_CONTEXT else (explicit_crop.lower(),)
        crops = _ordered_unique((*normalized_explicit_crops, *(crops or fallback_crops)))

    jurisdictions, country = _extract_jurisdictions(text)
    if country is None and re.search(r"\bcanada\b", lower):
        country = "canada"
    if country is None and re.search(
        r"\b(?:aafc|aac|agriculture and agri-food canada|agriculture et agroalimentaire canada|"
        r"canadien|canadienne|canadiens|canadiennes)\b",
        lower,
    ):
        country = "canada"
    explicit_jurisdiction = _clean(
        provided.get("province_state")
        or provided.get("province")
        or provided.get("state")
        or provided.get("jurisdiction")
    )
    if explicit_jurisdiction:
        jurisdictions = _ordered_unique((explicit_jurisdiction.lower(), *jurisdictions))
        explicit_upper = explicit_jurisdiction.upper()
        if explicit_upper == "CANADA":
            country = "canada"
        elif (
            explicit_upper in CANADIAN_PROVINCE_CODES
            or explicit_upper in CANADIAN_PROVINCE_NAMES_TO_CODE
            or explicit_upper in CANADIAN_PROVINCE_NAME_ALIASES
        ):
            country = "canada"
        elif explicit_upper in US_STATE_NAME_TO_ALPHA.values() or explicit_upper in US_STATE_NAME_TO_ALPHA:
            country = "united states"
    if explicit_jurisdiction:
        target_jurisdictions = (explicit_jurisdiction.lower(),)
    elif len(jurisdictions) > 1 and not _cross_jurisdiction_comparison_requested(text):
        target_jurisdictions = jurisdictions[-1:]
    else:
        target_jurisdictions = jurisdictions

    regional_terms = list(jurisdictions)
    regional_terms.extend(_extract_place_terms(text))
    for match in re.findall(r"\bMLRA\s*0?\d{2,3}[A-Za-z]?\b", text, re.IGNORECASE):
        normalized_mlra = match.lower()
        regional_terms.extend((normalized_mlra, re.sub(r"^mlra\s*0?", "", normalized_mlra)))
    for key in ("region_text", "county", "location", "mlra", "ecoregion", "ecodistrict", "soil_region"):
        value = _clean(provided.get(key))
        if value:
            regional_terms.extend(part.strip().lower() for part in re.split(r"[,/]", value) if len(part.strip()) >= 3)
    regional_terms = list(_ordered_unique(regional_terms))

    merged_context = dict(provided)
    if crops and not _clean(merged_context.get("crop_current")):
        merged_context["crop_current"] = crops[0]
    if jurisdictions and not _clean(merged_context.get("province_state")):
        merged_context["province_state"] = jurisdictions[0]
    if regional_terms and not _clean(merged_context.get("region_text")):
        merged_context["region_text"] = ", ".join(regional_terms[:4])

    regional_requested = bool(
        re.search(
            r"\b(mlra|major land resource|ecoregion|ecodistrict|ecological site|soil survey|soil map|map unit|"
            r"soil landscapes?|soil[- ]landscape|soil components?|landform components?|regional (?:soil|climate|environment|context)|"
            r"land resource region|agroclimate|nasdi|standardized precipitation index|"
            r"standardized precipitation evapotranspiration index|spi|spei|difference from (?:normal|average) (?:temperature|precipitation))\b",
            lower,
        )
        or re.search(_AAFC_CROP_HEALTH_PRODUCT_PATTERN, lower)
        or re.search(_AAFC_ANNUAL_CROP_INVENTORY_PATTERN, lower)
        or re.search(_AAFC_HISTORICAL_CROP_YIELD_SLC_PATTERN, lower)
        or re.search(_CANADIAN_REGIONAL_CONTEXT_PRODUCT_PATTERN, lower)
    )
    capsule = build_decision_capsule(text, crop=crops[0] if crops else None)
    return QueryContextSignals(
        query_text=text,
        crops=tuple(crops),
        jurisdictions=tuple(jurisdictions),
        target_jurisdictions=tuple(target_jurisdictions),
        regional_terms=tuple(regional_terms),
        topics=merge_topics(_topic_families(lower), capsule.retrieval_topics),
        query_terms=_meaningful_terms(lower),
        pest_entities=_pest_entities(lower),
        country=country,
        source_grounded=is_source_grounded_question(text),
        regional_context_requested=regional_requested,
        field_context=merged_context,
    )


def extract_field_graph_terms(field_context: dict[str, Any] | None) -> tuple[str, ...]:
    """Map governed DSS attributes to a small, injection-safe KG vocabulary.

    The detailed survey is spatial evidence; SoilWise is an ontology.  This
    bridge intentionally emits only fixed concepts selected from known DSS
    fields.  It never copies map-unit prose, component names, or user-provided
    text into a graph query, and it does not turn a mapped prior into a field
    observation or management recommendation.
    """

    if not isinstance(field_context, dict):
        return ()
    intersections = field_context.get("regional_intersections")
    if not isinstance(intersections, list):
        return ()

    terms: list[str] = []

    def add(term: str) -> None:
        if term not in terms and len(terms) < 12:
            terms.append(term)

    def add_drainage(value: Any) -> None:
        lowered = str(value or "").strip().lower()[:120]
        if not lowered:
            return
        if "poor" in lowered:
            add("poor drainage")
        elif "imperfect" in lowered:
            add("imperfect drainage")
        else:
            add("soil drainage")

    for item in intersections[:6]:
        if not isinstance(item, dict):
            continue
        layer_id = str(item.get("layer_id") or "").strip().lower()
        if layer_id not in _DETAILED_SOIL_LAYER_IDS:
            continue

        add_drainage(item.get("drainage_class"))
        if item.get("surface_texture_group"):
            add("soil texture")
        salinity = str(item.get("salinity_class") or "").strip().lower()[:120]
        if salinity and not re.search(r"\b(?:non[- ]?saline|none|nil)\b", salinity):
            add("soil salinity")
        if item.get("slope_class"):
            add("slope")
        limitations = str(item.get("management_limitations") or "").strip().lower()[:240]
        for pattern, concept in (
            (r"\b(?:wetness|drainage|flood)\b", "soil drainage"),
            (r"\b(?:stone\w*|rock fragment\w*)\b", "coarse mineral fragments"),
            (r"\b(?:salin|sodic)\w*\b", "soil salinity"),
            (r"\b(?:erosion|erod)\w*\b", "soil erosion"),
            (r"\b(?:fertility|nutrient)\b", "soil fertility"),
            (r"\btopograph\w*\b", "topography"),
        ):
            if re.search(pattern, limitations):
                add(concept)

        components = item.get("dominant_components")
        if not isinstance(components, list):
            continue
        for component in components[:3]:
            if not isinstance(component, dict):
                continue
            add_drainage(component.get("drainage_class"))
            water_table = str(component.get("water_table_presence") or "").strip().lower()[:80]
            if water_table and not re.search(r"\b(?:no|none|absent|unknown)\b", water_table):
                add("water table")
            restriction = " ".join(
                str(component.get(key) or "")[:80]
                for key in ("root_restriction_layer", "restriction_type")
            ).strip().lower()
            if restriction and not re.search(r"\b(?:none|absent|unknown)\b", restriction):
                add("root restriction")
            layer = component.get("surface_layer")
            if not isinstance(layer, dict):
                continue
            if any(layer.get(key) is not None for key in ("sand_percent_by_weight", "silt_percent_by_weight", "clay_percent_by_weight")):
                add("soil texture")
            if layer.get("organic_carbon_percent_by_weight") is not None:
                add("soil organic carbon")
            if layer.get("ph_cacl2") is not None or layer.get("ph_project_method") is not None:
                add("soil pH")
            if layer.get("cec") is not None:
                add("cation exchange capacity")
            if layer.get("bulk_density") is not None:
                add("bulk density")
            if layer.get("electrical_conductivity") is not None:
                add("electrical conductivity")
    return tuple(terms)


def filter_docs_for_query(
    docs: Iterable[Any],
    signals: QueryContextSignals,
    *,
    primary_intent: str | None = None,
) -> EvidenceFitResult:
    kept: list[Any] = []
    dropped: list[dict[str, str]] = []
    for doc in docs:
        reason = _doc_rejection_reason(doc, signals, primary_intent=primary_intent)
        if reason:
            dropped.append({"doc_id": str(getattr(doc, "doc_id", "")), "reason": reason})
        else:
            kept.append(doc)
    return EvidenceFitResult(docs=tuple(kept), dropped=tuple(dropped))


def extract_crop_entities(text: str) -> tuple[str, ...]:
    """Expose the runtime crop vocabulary for ingestion-time chunk tagging."""

    return _extract_crops(text)


def extract_topic_entities(text: str) -> tuple[str, ...]:
    """Expose the runtime topic vocabulary for ingestion-time chunk tagging."""

    return _topic_families(text)


def filter_graph_hits_for_query(
    hits: Iterable[Any],
    signals: QueryContextSignals,
    *,
    required_terms: Iterable[str] = (),
    route_namespaces: Iterable[str] = (),
    field_terms: Iterable[str] = (),
) -> EvidenceFitResult:
    """Keep graph vocabulary only when it fits the question obligation.

    Imported ontology labels are not decision evidence.  Generic SoilWise nodes
    therefore require direct lexical/namespace fit and a substantive
    description rather than a restatement of the node name.
    """

    kept: list[Any] = []
    dropped: list[dict[str, str]] = []
    obligation_tokens = set(_meaningful_terms(" ".join(str(value) for value in required_terms)))
    route_namespace_set = {
        str(value).strip().lower() for value in route_namespaces if str(value).strip()
    }
    topic_kinds = {
        "disease": "disease",
        "pest": "insect",
        "insect": "insect",
        "weed": "weed",
        "product": "product",
    }
    for hit in hits:
        haystack = " ".join(
            [
                str(getattr(hit, "name", "")),
                str(getattr(hit, "evidence", "")),
                " ".join(str(item) for item in getattr(hit, "neighbors", ()) or ()),
            ]
        ).lower()
        hit_crops = set(_extract_crops(haystack))
        reason = None
        if signals.crops and hit_crops and hit_crops.isdisjoint(signals.crops):
            reason = "crop_mismatch"
        else:
            topic = topic_kinds.get(str(getattr(hit, "kind", "")).lower())
            if topic and topic not in signals.topics:
                reason = "topic_mismatch"
        kind = str(getattr(hit, "kind", "")).strip().lower()
        if reason is None and kind == "soil health concept":
            name = str(getattr(hit, "name", ""))
            evidence = str(getattr(hit, "evidence", ""))
            hit_terms = set(_meaningful_terms(f"{name} {evidence}"))
            direct_terms = (
                set(signals.query_terms)
                | obligation_tokens
                | set(_meaningful_terms(" ".join(str(value) for value in field_terms)))
            )
            namespaces = {
                str(value).strip().lower()
                for value in getattr(hit, "namespaces", ()) or ()
                if str(value).strip()
            }
            if not (hit_terms & direct_terms) or (
                route_namespace_set and namespaces and not route_namespace_set.intersection(namespaces)
            ):
                reason = "generic_graph_obligation_mismatch"
            elif not _graph_evidence_is_substantive(name, evidence):
                reason = "non_substantive_graph_evidence"
        if reason:
            dropped.append({"doc_id": str(getattr(hit, "node_id", "")), "reason": reason})
        else:
            kept.append(hit)
    return EvidenceFitResult(docs=tuple(kept), dropped=tuple(dropped))


def _graph_evidence_is_substantive(name: str, evidence: str) -> bool:
    normalized_name = " ".join(_meaningful_terms(name))
    normalized_evidence = re.sub(
        r"(?:aliases?|external vocabulary links?):.*$",
        "",
        str(evidence),
        flags=re.IGNORECASE,
    )
    evidence_terms = list(_meaningful_terms(normalized_evidence))
    name_terms = set(_meaningful_terms(normalized_name))
    additional = [term for term in evidence_terms if term not in name_terms]
    return len(additional) >= 3


def _doc_rejection_reason(doc: Any, signals: QueryContextSignals, *, primary_intent: str | None = None) -> str | None:
    source_type = str(getattr(doc, "source_type", "")).lower()
    source_id = str(getattr(doc, "source_id", "")).lower()
    haystack = _doc_text(doc)
    title_tags = " ".join(
        [str(getattr(doc, "title", "")), " ".join(str(item) for item in getattr(doc, "tags", ()) or ())]
    ).lower()
    country_only_canola_harvest_transfer = False

    named_regional_product_interpretation = False
    if source_type == "regional_environment_profile":
        named_regional_product_interpretation = bool(
            (
                source_id == "ca_aafc_sk_detailed_soil_survey_specification"
                and re.search(r"\bsaskatchewan detailed soil survey\b", signals.query_text, re.IGNORECASE)
            )
            or (
                source_id == "ca_aafc_annual_crop_inventory_specification"
                and re.search(r"\bannual crop inventory(?:\s+\d{4})?\b", signals.query_text, re.IGNORECASE)
            )
            or (
                source_id == "ca_aafc_qc_agropedological_atlas_specification"
                and re.search(r"\b(?:quebec|québec) agro[- ]pedological atlas\b|\bagro[- ]pedological atlas of (?:quebec|québec)\b", signals.query_text, re.IGNORECASE)
            )
            or (
                source_id == "nb_geonb_agricultural_soil_classes"
                and re.search(r"\b(?:geonb|new brunswick) agricultural soil classes\b", signals.query_text, re.IGNORECASE)
            )
            or (
                source_id == "nl_historical_weather_station_climate_metadata"
                and re.search(r"\bnewfoundland and labrador weather station climate monitoring data\b", signals.query_text, re.IGNORECASE)
            )
            or (
                source_id == "ca_aafc_historical_crop_yield_slc_specification"
                and re.search(
                    _AAFC_HISTORICAL_CROP_YIELD_SLC_PATTERN,
                    signals.query_text,
                    re.IGNORECASE,
                )
            )
            or (
                source_id in {
                    "ca_aafc_crop_health_indices_specification",
                    "ca_aafc_crop_health_indices_specification_fr",
                }
                and re.search(
                    _AAFC_CROP_HEALTH_PRODUCT_PATTERN,
                    signals.query_text,
                    re.IGNORECASE,
                )
            )
            or (
                source_id == "ca_aafc_canadian_crop_yields_specification_fr"
                and re.search(
                    r"\brendement des cultures au canada\b|"
                    r"\bpr[eé]visions? canadiennes? du rendement des cultures\b",
                    signals.query_text,
                    re.IGNORECASE,
                )
            )
            or (
                source_id == "ca_aafc_soil_erosion_risk_technical_chapter_2021"
                and re.search(
                    r"\baafc\b.{0,80}\bsoil (?:erosion|erision|eroshun) risk(?: indicator)?(?:\s+2021)?\b|"
                    r"\baafc\b.{0,40}\b(?:erosion|erision|eroshun)(?: risk)? (?:class|map|layer)\b|\bsoileri\b|"
                    r"\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)? (?:map|layer)\b|"
                    r"\b(?:map|layer)\b.{0,40}\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)?\b",
                    signals.query_text,
                    re.IGNORECASE,
                )
            )
        )
        specific_terms = tuple(term for term in signals.regional_terms if term not in signals.jurisdictions)
        _, doc_subdivisions = _normalize_jurisdiction_scope(
            getattr(doc, "jurisdictions", ()) or ()
        )
        _, query_subdivisions = _normalize_jurisdiction_scope(
            _applicable_query_jurisdictions(signals)
        )
        subdivision_scope_match = bool(doc_subdivisions & query_subdivisions)
        named_regional_product_interpretation = named_regional_product_interpretation or bool(
            signals.regional_context_requested
            and signals.country
            and signals.country in _normalize_jurisdiction_scope(
                getattr(doc, "jurisdictions", ()) or ()
            )[0]
            and re.search(
                r"\b(?:soil landscapes of canada|crop health indices?|crop stress index|"
                r"crop development stage|annual crop inventory|aafc crop type mapping|"
                r"estimated historical crop yields?|historical crop yield|"
                r"soil erosion risk indicator|soileri|national .*data product specification|"
                r"indices? de sant[eé] des cultures|indice de stress des cultures|"
                r"rendement des cultures au canada|pr[eé]visions? .*rendement des cultures)\b",
                haystack,
            )
        )
        if specific_terms and not named_regional_product_interpretation and not subdivision_scope_match:
            if not any(term in haystack for term in specific_terms):
                return "regional_context_mismatch"
        elif signals.jurisdictions and not signals.regional_context_requested:
            return "regional_scope_too_broad"
        elif not signals.regional_context_requested:
            return "regional_context_not_requested"

    if source_type in {"applied_guidance", "boundary", "regional_environment_profile"}:
        doc_countries, doc_subdivisions = _normalize_jurisdiction_scope(
            getattr(doc, "jurisdictions", ()) or ()
        )
        query_jurisdictions = _applicable_query_jurisdictions(signals)
        query_countries, query_subdivisions = _normalize_jurisdiction_scope(query_jurisdictions)
        if signals.country:
            query_countries.add(signals.country)
        if (
            source_type == "applied_guidance"
            and signals.country == "canada"
            and not doc_countries
            and not doc_subdivisions
        ):
            return "jurisdiction_unscoped"
        if doc_countries and query_countries and doc_countries.isdisjoint(query_countries):
            return "jurisdiction_mismatch"
        if doc_subdivisions and query_subdivisions and doc_subdivisions.isdisjoint(query_subdivisions):
            return "jurisdiction_mismatch"
        country_only_canola_harvest_transfer = bool(
            signals.country == "canada"
            and not query_subdivisions
            and source_type == "applied_guidance"
            and str(primary_intent or "") == "crop_management"
            and re.search(r"\bcanola\b", signals.query_text, re.IGNORECASE)
            and re.search(r"\bcanola\b", haystack)
            and re.search(r"\b(?:harvest|shatter|swath|straight[- ]?cut|direct combin)\w*\b", signals.query_text, re.IGNORECASE)
            and re.search(r"\b(?:harvest|shatter|swath|straight[- ]?cut|direct combin)\w*\b", haystack)
        )
        if doc_subdivisions and query_countries and not query_subdivisions and not country_only_canola_harvest_transfer:
            return "jurisdiction_too_specific"

    title_crops = set(_extract_crops(title_tags))
    declared_crops = {
        crop
        for value in getattr(doc, "crops", ()) or ()
        for crop in (_extract_crops(str(value).lower()) or (str(value).strip().lower(),))
        if crop and crop not in _GENERIC_CROP_CONTEXT and crop not in _CROP_SCOPE_WILDCARDS
    }
    doc_crops = title_crops | declared_crops
    generic_specialty_doc = "specialty crop" in title_tags or "specialty-crop" in title_tags or "vegetable" in title_tags
    specialty_query = bool(set(signals.crops) & _SPECIALTY_CROPS)
    if (
        signals.crops
        and doc_crops
        and doc_crops.isdisjoint(signals.crops)
        and not (generic_specialty_doc and specialty_query)
        and not named_regional_product_interpretation
    ):
        return "crop_mismatch"
    if (
        signals.primary_crop
        and doc_crops
        and signals.primary_crop not in doc_crops
        and str(primary_intent or "") in {"plant_health", "product_label", "crop_management"}
        and not (generic_specialty_doc and specialty_query)
        and not named_regional_product_interpretation
    ):
        return "primary_crop_mismatch"

    doc_topics = set(_topic_families(title_tags))
    title = str(getattr(doc, "title", "")).lower()
    title_topics = set(_topic_families(title))
    if source_type == "regional_environment_profile":
        doc_topics.add("regional")
        title_topics.add("regional")
    query = signals.query_text.lower()
    if re.search(r"\bfurrow[- ]irrigat", query) and re.search(
        r"\b(?:sprinkler|pivot|nozzle|drip emitter)\b", title_tags
    ) and not re.search(r"\bfurrow|surface irrigation\b", title_tags):
        return "irrigation_system_mismatch"
    if re.search(r"\b(?:volumetric water content|soil[- ]moisture sensor|sensor reading|VWC)\b", query, re.IGNORECASE) and re.search(
        r"\b(?:flood|submerg|ponding|pollination|salinity|sodicity)\b", title_tags
    ):
        return "decision_context_mismatch"
    if re.search(r"\bspring wheat\b", query) and re.search(r"\bwinter wheat\b", title_tags):
        return "crop_class_mismatch"
    if re.search(r"\b(?:freeze|freezing|frozen|frost)\s+(?:injury|damage)\b", title_tags) and not re.search(
        r"\b(?:freeze|freezing|frozen|frost|cold injury|cold damage|low[- ]temperature injury)\b",
        query,
    ):
        return "decision_context_mismatch"
    if re.search(r"\b(?:sorghum[- ]?sudan(?:grass)?|sudangrass)\b", query) and re.search(
        r"\b(?:frost|drought|regrowth|graz|feed|hay)\w*\b", query
    ) and re.search(r"\b(?:mycotoxin|grain mold|lot segregation)\b", title_tags) and not re.search(
        r"\b(?:prussic|hydrocyanic|nitrate|forage)\b", title_tags
    ):
        return "forage_hazard_mismatch"
    if re.search(r"\bvariable[- ]rate\s+P\s*(?:and|&)\s*K\b", signals.query_text, re.IGNORECASE) and re.search(
        r"\bnitrogen\b", title_tags
    ) and not re.search(r"\b(?:phosphorus|potassium|P and K)\b", title_tags, re.IGNORECASE):
        return "nutrient_entity_mismatch"
    if re.search(r"\b(?:fresh[- ]market|strawberr|leafy greens?)\b", query) and re.search(
        r"\b(?:field heat|cool|harvest|preharvest)\w*\b", query
    ) and re.search(r"\b(?:grain|kernel|ear mold|mycotoxin|sidewall|compaction|planting|seedbed)\b", title_tags):
        return "crop_system_mismatch"
    irrigation_context = _has_irrigation_context(signals)
    if (
        str(primary_intent or "").startswith("fertility")
        and re.search(r"\b(irrigation|chemigation|fertigation)\b", title)
        and not irrigation_context
    ):
        return "topic_mismatch"
    if re.search(r"\b(sandy|coarse[- ]textured)\b", title) and not any(
        term in signals.query_terms for term in ("sand", "sandy", "coarse", "coarse-textured")
    ):
        return "soil_context_mismatch"
    if re.search(r"\b(irrigation[- ]water|chemigation|applied water|flowmeter)\b", title) and not irrigation_context:
        return "topic_mismatch"
    for exclusive_topic in ("seed_treatment", "cover_crop", "precision", "economics"):
        if (
            exclusive_topic in title_topics
            and exclusive_topic not in signals.topics
            and not country_only_canola_harvest_transfer
        ):
            return "topic_mismatch"
    exclusive_domains = {"fertility", "disease", "insect", "weed", "product"}
    doc_exclusive_domains = title_topics & exclusive_domains
    query_exclusive_domains = set(signals.topics) & exclusive_domains
    if doc_exclusive_domains and query_exclusive_domains and doc_exclusive_domains.isdisjoint(query_exclusive_domains):
        forage_safety_bridge = bool(
            "fertility" in doc_exclusive_domains
            and "sorghum" in signals.crops
            and re.search(r"\b(?:forage|prussic|hydrocyanic|nitrate)\b", title_tags)
            and re.search(r"\b(?:frost|drought|regrowth|graz|feed|hay)\w*\b", query)
        )
        if not forage_safety_bridge:
            return "topic_mismatch"
    comparison_topics = title_topics or doc_topics
    primary_topics = _primary_topic_families(primary_intent, signals)
    if (
        primary_topics
        and title_topics
        and title_topics.isdisjoint(primary_topics)
        and not named_regional_product_interpretation
        and not country_only_canola_harvest_transfer
    ):
        return "primary_topic_mismatch"
    if (
        signals.topics
        and comparison_topics
        and comparison_topics.isdisjoint(signals.topics)
        and not (source_type == "regional_environment_profile" and signals.regional_terms)
        and not named_regional_product_interpretation
        and not country_only_canola_harvest_transfer
    ):
        return "topic_mismatch"
    title_pests = set(_pest_entities(title))
    if title_pests and title_pests.isdisjoint(signals.pest_entities):
        return "pest_entity_mismatch"
    if not title_topics and source_type != "boundary":
        title_terms = set(_meaningful_terms(title))
        if title_terms and title_terms.isdisjoint(signals.query_terms):
            return "lexical_topic_mismatch"

    us_federal = any(
        term in haystack
        for term in (
            "nrcs",
            "ssurgo",
            "soil data access",
            "usda nass",
            "quick stats",
            "cropland data layer",
            "epa.gov",
            "mlra",
            "census of agriculture",
            "openet",
        )
    )
    canadian_federal = any(term in haystack for term in ("aafc", "agriculture and agri-food canada", "canada.ca", "cansis"))
    jurisdiction_sensitive = source_type in {"regional_environment_profile", "boundary"}
    if signals.country == "canada" and us_federal:
        return "jurisdiction_mismatch"
    if jurisdiction_sensitive and signals.country == "united states" and canadian_federal:
        return "jurisdiction_mismatch"
    return None


def _extract_crops(text: str) -> tuple[str, ...]:
    found: list[tuple[int, int, str]] = []
    for alias_order, (canonical, aliases) in enumerate(_CROP_ALIASES):
        positions = [
            match.start()
            for alias in aliases
            if (match := re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE)) is not None
        ]
        if positions:
            found.append((min(positions), alias_order, canonical))
    return tuple(canonical for _, _, canonical in sorted(found))


def _topic_families(text: str) -> tuple[str, ...]:
    patterns: tuple[tuple[str, str], ...] = (
        ("seed_treatment", r"\b(seed[- ]treatment|treated[- ]seed|seed-applied)\b|\b(?:insecticide|fungicide)[- ]treated\s+seed\b"),
        ("cover_crop", r"\bcover[- ]crops?\b"),
        ("fertility", r"\b(nitrogen|nitrate|phosphorus|potassium|sulfur|lime|aglime|calcium|bitter pit|blossom[- ]end rot|tipburn|fertility|fertilizer|manure|nutrient|soil tests?)\b|\bP\s*(?:and|&)\s*K\b"),
        ("soil_water", r"\b(drainage|compaction|irrigat(?:e|ed|ing|ion)|infiltration|salinity|sodicity|water table|erosion|runoff|leaching|soil water|soil moisture|rainfall|heavy rain|wet soil|seed[- ]zone|seedbed|trafficability|sidewall smearing|water[- ]quality|riparian|buffer)\b"),
        ("disease", r"\b(disease|pathogen|fungicide|leaf spot|root rot|mold|fungus|rust|blight|nematodes?|nematicide|plant diagnosis|photo diagnosis|diagnostic sample)\b"),
        ("insect", r"\b(aphids?|insects?|pests?|caterpillars?|moths?|trap captures?|fruit injury|defoliat\w*|leaf[- ]feed\w*|rootworms?|silk clipping|insecticide|beneficial|natural enemies|economic threshold|ipm|pest management|integrated pest)\b"),
        ("weed", r"\b(weeds?|waterhemp|pigweed|ryegrass|volunteer canola|burndown|glyphosate|herbicide|preemergence|residual activation|control failure|resistance management|mode of action|site of action)\b"),
        ("product", r"\b(sprays?|spraying|drift|pesticide|herbicide|glyphosate|fungicide|insecticide|label|tank mix|application window|application record)\b"),
        ("precision", r"\b(variable-rate|variable rate|prescription|yield map|precision|check strip|trial design)\b"),
        ("economics", r"\b(econom\w*|roi|net return|return on investment|partial budget|profit|payback|cost)\b"),
        ("regional", r"\b(mlra|ecoregion|ecological site|soil survey|soil map|map-unit|map unit|regional context)\b"),
        ("field_data", r"\b(source availability|adapter|geometry|shapefile|geojson|field-specific public|source card|provenance)\b"),
        ("produce_safety", r"\b(produce[- ]safety|food[- ]safety|crop[- ]contact water|agricultural water|water intake)\b"),
        ("transplant_establishment", r"\b(transplants?|root[- ]bound|root ball|hardening|transplant shock)\b"),
        ("planting_establishment", r"\b(seed[- ]zone|seedbed|planting depth|trafficability|sidewall smearing|stand establishment)\b"),
        ("crop_management", r"\b(variety|hybrid|cultivar|planting|replant|harvest|postharvest|field heat|cold chain|cooling|storage|forage|fourrages?|pâturages?|grazing|livestock|stand establishment|seed quality|germination|vigor|standability|crop stage|specialty[- ]crop|vegetable|leafy greens?|market quality|transplants?|root[- ]bound|root ball|hardening)\b"),
    )
    return tuple(name for name, pattern in patterns if re.search(pattern, text, re.IGNORECASE))


def _primary_topic_families(primary_intent: str | None, signals: QueryContextSignals) -> set[str]:
    intent = str(primary_intent or "").lower()
    if intent == "product_label" and "fertility" in signals.topics and "product" not in signals.topics:
        return {"fertility"}
    if intent.startswith("fertility"):
        return {"fertility"}
    if intent == "soil_water":
        return {"soil_water", "cover_crop", "regional"}
    if intent == "plant_health":
        return set(signals.topics) & {"disease", "insect", "weed"}
    if intent in {"product_label", "seed_treatment"}:
        return ({"product", "seed_treatment"} | (set(signals.topics) & {"disease", "insect", "weed"}))
    if intent == "crop_management":
        specific_lanes = set(signals.topics) & {"produce_safety", "transplant_establishment", "planting_establishment"}
        if specific_lanes:
            return {"crop_management", *specific_lanes}
        multi_domain = set(signals.topics) & {"fertility", "soil_water", "disease", "insect", "weed", "product", "produce_safety", "transplant_establishment", "planting_establishment"}
        return ({"crop_management"} | multi_domain) if len(multi_domain) >= 3 else {"crop_management"}
    if intent == "field_data":
        return {"field_data", "regional"} | (set(signals.topics) & {"precision", "economics", "fertility", "soil_water"})
    return set()


def _meaningful_terms(text: str) -> tuple[str, ...]:
    stop = {
        "about", "actual", "advice", "agent", "and", "answer", "before", "change", "check", "context", "crop",
        "decision", "evidence", "field", "first", "grower", "likely", "management", "public", "question",
        "recommend", "should", "support", "the", "user", "what", "when", "where", "which", "with", "without",
    }
    return tuple(
        dict.fromkeys(
            token
            for token in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
            if token not in stop
        )
    )


def _has_irrigation_context(signals: QueryContextSignals) -> bool:
    return any(term.startswith("irrigat") for term in signals.query_terms)


def _pest_entities(text: str) -> tuple[str, ...]:
    aliases = {
        "aphid": r"\baphids?\b",
        "nematode": r"\b(?:nematodes?|nematicide)\b",
        "wireworm": r"\bwireworms?\b",
        "cutworm": r"\bcutworms?\b",
        "armyworm": r"\barmyworms?\b",
        "maggot": r"\bmaggots?\b",
        "beetle": r"\bbeetles?\b",
        "mite": r"\bmites?\b",
        "thrips": r"\bthrips\b",
        "moth": r"\bmoths?\b",
        "waterhemp": r"\bwaterhemp\b",
        "palmer amaranth": r"\bpalmer amaranth\b",
        "pigweed": r"\bpigweeds?\b",
        "kochia": r"\bkochia\b",
        "ryegrass": r"\bryegrass\b",
        "grassy weed": r"\bgrassy weeds?\b",
    }
    return tuple(name for name, pattern in aliases.items() if re.search(pattern, text, re.IGNORECASE))


def _extract_jurisdictions(text: str) -> tuple[tuple[str, ...], str | None]:
    upper = text.upper()
    canadian = _canadian_jurisdictions_in_text(text)
    united_states = _jurisdictions_in_text(upper, US_STATE_NAME_TO_ALPHA)
    if canadian:
        return _ordered_unique(canadian), "canada"
    if united_states:
        return _ordered_unique(united_states), "united states"
    if re.search(r"\b(?:CANADA|CANADIAN)\b", upper):
        return (), "canada"
    if re.search(r"\b(?:UNITED STATES|U\.S\.|USA|AMERICAN)\b", upper):
        return (), "united states"
    return (), None


def _canadian_jurisdictions_in_text(text: str) -> tuple[str, ...]:
    upper = text.upper()
    found: list[tuple[int, str]] = []
    for name in CANADIAN_PROVINCE_NAMES_TO_CODE:
        match = re.search(rf"\b{re.escape(name)}\b", upper)
        if match is not None:
            found.append((match.start(), name.lower()))
    for alias, canonical_name in CANADIAN_PROVINCE_NAME_ALIASES.items():
        match = re.search(rf"\b{re.escape(alias)}\b", upper)
        if match is not None:
            found.append((match.start(), canonical_name.lower()))
    for alias, name in CANADIAN_PROVINCE_TEXT_ALIASES.items():
        match = re.search(rf"\b{re.escape(alias)}\b", text)
        if match is not None:
            found.append((match.start(), name))
    return _ordered_unique(name for _, name in sorted(found))


def _jurisdictions_in_text(text: str, names_to_code: dict[str, str]) -> tuple[str, ...]:
    found: list[tuple[int, str]] = []
    for name in names_to_code:
        match = re.search(rf"\b{re.escape(name)}\b", text)
        if match is not None:
            found.append((match.start(), name.lower()))
    return tuple(name for _, name in sorted(found))


def _normalize_jurisdiction_scope(values: Iterable[str]) -> tuple[set[str], set[str]]:
    countries: set[str] = set()
    subdivisions: set[str] = set()
    canadian_codes = {code: name.lower() for name, code in CANADIAN_PROVINCE_NAMES_TO_CODE.items()}
    us_codes = {code: name.lower() for name, code in US_STATE_NAME_TO_ALPHA.items()}
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        upper = raw.upper()
        if re.search(r"\b(?:CANADA|CANADIAN)\b", upper):
            countries.add("canada")
        if re.search(r"\b(?:UNITED STATES|U\.S\.|USA|AMERICAN)\b", upper):
            countries.add("united states")
        for name, code in CANADIAN_PROVINCE_NAMES_TO_CODE.items():
            if upper == code or re.search(rf"\b{re.escape(name)}\b", upper):
                countries.add("canada")
                subdivisions.add(canadian_codes[code])
        for alias, canonical_name in CANADIAN_PROVINCE_NAME_ALIASES.items():
            if upper == alias or re.search(rf"\b{re.escape(alias)}\b", upper):
                countries.add("canada")
                subdivisions.add(canonical_name.lower())
        for name, code in US_STATE_NAME_TO_ALPHA.items():
            if upper == code or re.search(rf"\b{re.escape(name)}\b", upper):
                countries.add("united states")
                subdivisions.add(us_codes[code])
    return countries, subdivisions


def _applicable_query_jurisdictions(signals: QueryContextSignals) -> tuple[str, ...]:
    explicit_field_jurisdiction = _clean(
        signals.field_context.get("province_state")
        or signals.field_context.get("province")
        or signals.field_context.get("state")
        or signals.field_context.get("jurisdiction")
    )
    if explicit_field_jurisdiction:
        return tuple(signals.target_jurisdictions)
    if _cross_jurisdiction_comparison_requested(signals.query_text):
        return tuple(signals.jurisdictions)
    return tuple(signals.target_jurisdictions)


def _cross_jurisdiction_comparison_requested(text: str) -> bool:
    lower = text.lower()
    comparison_action = re.search(
        r"\b(compare|comparison|transfer|interpret|adapt|apply|use|used|using)\b",
        lower,
    )
    source_artifact = re.search(
        r"\b(table|guide|guidance|recommendation|calibration|source|material)\b",
        lower,
    )
    return bool(comparison_action and source_artifact)


def _extract_place_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in re.finditer(r"(?:^|\n)\s*(?:place|location|region)\s*:\s*([^\n]+)", text, re.IGNORECASE):
        terms.extend(part.strip().lower() for part in match.group(1).split(",") if len(part.strip()) >= 3)
    for match in re.finditer(
        r"\bnear\s+(?:the\s+)?([A-Z][A-Za-z.'-]*(?:\s+(?:(?:of|the)\s+)?[A-Z][A-Za-z.'-]*){0,4})",
        text,
    ):
        terms.append(match.group(1).strip().lower())
    for match in re.finditer(
        r"\b(?:in|within)\s+(?:the\s+)?([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,4}\s+"
        r"(?:Valley|Plain|Plateau|Basin|Delta|Prairie|Region|Zone|Lobe))\b",
        text,
    ):
        terms.append(match.group(1).strip().lower())
    return _ordered_unique(terms)


def _doc_text(doc: Any) -> str:
    return " ".join(
        [
            str(getattr(doc, "doc_id", "")),
            str(getattr(doc, "title", "")),
            str(getattr(doc, "text", "")),
            str(getattr(doc, "source", "")),
            " ".join(str(item) for item in getattr(doc, "tags", ()) or ()),
        ]
    ).lower()


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip().lower() for value in values if value and value.strip()))


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""
