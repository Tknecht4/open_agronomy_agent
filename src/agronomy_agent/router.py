from __future__ import annotations

import re
from dataclasses import dataclass

from agronomy_agent.map_component_interpretation import is_map_component_explanation_question


_AAFC_CROP_HEALTH_PRODUCT_PATTERN = (
    r"(?:\baafc\b.{0,80}\b(?:crop[- ]health (?:index|indices)|crop stress index|crop development stage|growth[- ]stage raster)\b|"
    r"\b(?:crop[- ]health (?:index|indices)|crop stress index|water deficit index)\b|"
    r"\bcrop development stage (?:layer|raster|product|values?)\b|\bgrowth[- ]stage raster\b|"
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
    r"\bgeonb agricultural soil classes\b|\bnew brunswick agricultural soil classes\b|"
    r"\bnewfoundland and labrador weather station climate monitoring data\b|"
    r"\baafc\b.{0,80}\bsoil (?:erosion|erision|eroshun) risk(?: indicator)?(?:\s+2021)?\b|"
    r"\baafc\b.{0,40}\b(?:erosion|erision|eroshun)(?: risk)? (?:class|map|layer)\b|\bsoileri\b|"
    r"\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)? (?:map|layer)\b|"
    r"\b(?:map|layer)\b.{0,40}\b(?:soil )?(?:erosion|erision|eroshun)(?: risk)?\b)"
)

_AAFC_CROP_HEALTH_EXPANSIONS = {
    "AAFC crop health indices",
    "crop stress index",
    "crop development stage",
    "actual evapotranspiration AET",
    "potential evapotranspiration PET",
    "Versatile Soil Moisture Budget VSMB",
    "5 km regional model",
}

_AAFC_ANNUAL_CROP_INVENTORY_EXPANSIONS = {
    "AAFC Annual Crop Inventory",
    "crop classification",
    "30 m raster",
    "confidence raster",
    "ground data",
    "classification uncertainty",
    "not grower planting record",
}

_AAFC_HISTORICAL_CROP_YIELD_SLC_EXPANSIONS = {
    "AAFC Estimated Historical Crop Yields in Canada by SLC",
    "Soil Landscapes of Canada SLC",
    "historical crop yield kg per hectare",
    "provincial yield downscaling",
    "EVI2 adjustment",
    "EPIC forage yield",
    "Prairie insurance yield",
    "regional estimate not field truth",
}

_FRENCH_MAP_PATTERN = r"\b(?:carte|cartographi(?:e|é|ée)|polygone|couche|atlas)\b"
_FRENCH_SOIL_WATER_PATTERN = (
    r"\b(?:salinit(?:e|é)|sodicit(?:e|é)|gypse|drainage|irrigation|ruissellement|"
    r"erosion|érosion|sol humide|sol sature|sol saturé|nappe|eau du sol)\b"
)
_FRENCH_SALINITY_SODICITY_PATTERN = r"\b(?:salinit(?:e|é)|sodicit(?:e|é)|gypse)\b"

_FIELD_HISTORY_REFERENCE_PATTERN = (
    r"(?:\b(?:stored|saved|field[- ]linked|append[- ]only)\s+"
    r"(?:field\s+)?(?:observation|record|history|timeline)s?\b|"
    r"\b(?:stored|saved)\b[^.?\n]{0,50}\b(?:observation|record|history|timeline)s?\b|"
    r"\b(?:this|the|my|selected|current)\s+field(?:'s)?\s+"
    r"(?:observation|record|history|timeline)s?\b|"
    r"\bfield\s+(?:record|timeline)s?\b)"
)

_OPERATIONAL_TRAFFICABILITY_PATTERN = (
    r"(?:\btrafficability\b|\bfield traffic\b|"
    r"\bdriv(?:e|es|en|ing)\b[^.?\n]{0,35}\b(?:equipment|machinery|tractor|vehicle|field|corner|area)\b|"
    r"\b(?:equipment|machinery|tractor|vehicle)\b[^.?\n]{0,35}"
    r"\b(?:enter(?:s|ed|ing)?|driv(?:e|es|en|ing)|traffic(?:s|ked|king)?)\b|"
    r"\benter(?:s|ed|ing)?\b[^.?\n]{0,25}\b(?:field|corner|area)\b)"
)


_FRENCH_ROUTE_ANCHORS: tuple[tuple[str, str], ...] = (
    (r"\b(?:pommes? de terre|pomme de terre)\b", "potato"),
    (r"\bsoya\b", "soybean"),
    (r"\bma[iï]s\b", "corn"),
    (r"\bbleuet(?:s|i[eè]re)?\b", "blueberry"),
    (r"\b(?:l[eé]sions?|maladie|diagnostic)\b", "disease diagnosis"),
    (r"\b(?:fongicide|insecticide|herbicide|pesticide|traitement)\b", "pesticide fungicide insecticide treatment current label"),
    (r"\b(?:dose|combien|taux)\b", "rate how much"),
    (r"\b(?:azote|engrais|fertilis(?:ant|ation)|nutriment)\b|\bN\b", "nitrogen fertilizer nutrient"),
    (r"\b(?:jaunit|jaunissement|p[aâ]le)\b", "yellowing pale"),
    (r"\b(?:test|analyse) de sol\b", "soil test"),
    (r"\bchaux\b", "lime rate buffer pH"),
    (r"\b(?:carte|tableau|atlas|couche|polygone)\b", "map layer polygon"),
    (r"\b(?:composantes?|texture loameuse|loam argileux)\b", "soil component soil texture"),
    (r"\b(?:prouve|suffisant|tout mon champ)\b", "prove whole field"),
    (r"\b(?:drainer|drainage imparfait)\b", "drainage field"),
    (r"\b(?:humidit[eé] du sol|irriguer|irrigation)\b", "soil moisture irrigation field"),
    (r"\bpluie\b", "rain weather"),
    (r"\b(?:d[eé]pister|d[eé]pistage)\b", "scout scouting field"),
    (r"\b(?:insectes?|ravageurs?)\b", "insects pests"),
    (r"\b(?:vari[eé]t[eé]|mieux class[eé]e|choix)\b", "variety ranked choose local trials"),
    (r"\b(?:res[eè]me|ressemer|replanter)\b", "replant field"),
    (r"\b(?:peuplement|d[eé]g[aâ]ts)\b", "stand count damage field evidence"),
    (r"\b(?:reporter|attendre|j'attends)\b", "delay wait weather"),
    (r"\b(?:planter|plantation)\b", "planting field"),
    (r"\b(?:praticable|surface du champ)\b", "trafficability field surface soil moisture"),
    (r"\b(?:encore chaudes?|chaleur du champ)\b", "field heat postharvest"),
    (r"\b(?:peau fragile|meurtrissures?)\b", "fragile skin bruising storage quality"),
    (r"\b(?:ventile|ventiler|ventilation)\b", "aeration cooling storage"),
    (r"\b(?:guide ontarien|guide des l[eé]gumes de la c\.-?b\.)\b", "wrong jurisdiction guide local guidance"),
    (r"\b(?:comment|pourquoi|puis-je|dois-je|est-ce que)\b", "what should can verify"),
)


def _routing_text(question: str) -> str:
    """Add compact bilingual intent anchors without changing the user text.

    Retrieval and generation still receive the original question.  These
    anchors only let the deterministic router recognize common French
    agronomy concepts with the same policies used for English questions.
    """

    text = question.lower()
    if not re.search(
        r"\b(?:est-ce(?: que)?|puis-je|dois-je|j'ai|je |mon |ma |mes |cela|qu'il|dont|"
        r"aucun|seulement|avant d'|pourquoi ne pas|combien de|comment l'agent|"
        r"pommes? de terre|ma[iï]s|chaux|d[eé]pist(?:er|age)|res[eè]me)\b",
        text,
    ):
        return text
    anchors = [anchor for pattern, anchor in _FRENCH_ROUTE_ANCHORS if has(pattern, question)]
    return f"{text} {' '.join(anchors)}" if anchors else text


@dataclass(frozen=True)
class QueryRoute:
    question_type: str
    risk_level: str
    namespaces: tuple[str, ...]
    required_tools: tuple[str, ...]
    answer_style: str
    audience: str
    query_expansion: tuple[str, ...]
    guidance: str
    knowledge_bucket: str
    knowledge_domains: tuple[str, ...]


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def _is_named_product_permission_request(question: str) -> bool:
    """Detect a proper-named product permission or rate request without a brand list."""

    permission_request = re.search(
        r"\b(?:Can|May|Should)\s+(?:I|we)\s+(?:use|apply|spray)\s+"
        r"(?:the\s+)?[A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,2}\b|"
        r"\b(?:Is|Are)\s+[A-Z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,2}\s+"
        r"(?:allowed|permitted|registered|legal)\b",
        question,
    )
    if permission_request is not None:
        return True
    named_rate_request = re.search(
        r"\b(?:What\s+is|What's)\s+(?:the\s+)?"
        r"(?:[A-Z][A-Za-z0-9_.-]+\s+(?:rate|dose|dosage)|"
        r"(?:rate|dose|dosage)\s+(?:for|of)\s+[A-Z][A-Za-z0-9_.-]+)\b|"
        r"\bWhat\s+(?:rate|dose|dosage)\s+(?:of|for)\s+[A-Z][A-Za-z0-9_.-]+\b|"
        r"\bHow\s+much\s+[A-Z][A-Za-z0-9_.-]+\b",
        question,
    )
    if named_rate_request is None:
        return False
    return not has(
        r"\b(?:nitrogen|phosphorus|potassium|sulphur|sulfur|fertili[sz]er|urea|"
        r"lime|manure|compost|seed(?:ing)?|irrigation|water)\b",
        question,
    )


def _repair_interface_route(question: str, route: QueryRoute) -> QueryRoute:
    """Reconcile high-signal user intents after the broad lexical route.

    This is deliberately limited to cross-cutting interface invariants: an
    explicit nutrient-rate request cannot stay conceptual, a treatment request
    cannot lose regulated guards, and a mapped or regional prior cannot replace
    field evidence. It does not encode benchmark answers.
    """

    q = _routing_text(question)
    benign_conceptual_explanation = _is_benign_conceptual_explanation(question)
    qtype = route.question_type
    namespaces = set(route.namespaces)
    tools = set(route.required_tools)
    expansions = set(route.query_expansion)
    risk = route.risk_level
    guidance = route.guidance

    pesticide_terms = has(r"\b(?:herbicide|fungicide|insecticide|pesticide|spray|tank mix)\b", q)
    explicit_agrochemical_context = has(
        r"\b(?:herbicide|fungicide|insecticide|pesticide|spray|tank mix|active ingredient|"
        r"registration number|pcp number|pmra|epa(?:-registered)?|product[- ]label)\b",
        q,
    ) or _is_named_product_permission_request(question)
    regulated_land_application = has(
        r"\b(?:manure|digestate|biosolids?|organic nutrient|land[- ]application)\b",
        q,
    ) and has(
        r"\b(?:regulat\w*|legal|law|rule|permit|prohibit\w*|official scope|land[- ]application)\b",
        q,
    )
    nutrient_terms = has(
        r"\b(?:nitrogen|sulphur|sulfur|phosphorus|potassium|fertili[sz]er|urea|lime|chaux|azote|engrais)\b",
        q,
    )
    nutrient_action = has(
        r"\b(?:how much|how many|what rate|which rate|rate should|apply|add|calculate|incorporat|"
        r"guaranteed|cut the nitrogen plan|combien|dose|calculer|ajouter)\w*\b",
        q,
    )
    crop_stress = has(r"\b(?:pale|yellow|yellowing|chlorosis|jaunit|jaunissement|patch|strips?)\w*\b", q)

    classification_accuracy_prior = has(
        r"\b(?:crop classifier|crop classification|classification model|mapped crop|overall accuracy|"
        r"validation accuracy|classification accuracy|remote[- ]sensing classification)\b",
        q,
    )
    single_field_identity_claim = has(
        r"\b(?:guarantee|prove|establish|confirm)\w*\b[^?]{0,100}"
        r"\b(?:single|individual|one|specific)\b[^?]{0,40}\b(?:field|parcel|paddock)\b|"
        r"\b(?:single|individual|one|specific)\b[^?]{0,40}\b(?:field|parcel|paddock)\b"
        r"[^?]{0,100}\b(?:guarantee|prove|establish|confirm)\w*\b",
        q,
    )
    if classification_accuracy_prior and single_field_identity_claim and not explicit_agrochemical_context:
        qtype = "field_data"
        namespaces.update({"field_data_boundary", "crop_management", "regional_environment"})
        tools.add("field_data_guard")
        expansions.update({"classification uncertainty", "field record", "ground truth", "image date", "validation scope"})
        risk = "medium" if risk == "regulated" else risk
        guidance = (
            "Treat aggregate classification accuracy as a regional data-quality measure, not proof of one field's "
            "crop identity. Verify the field record or contemporaneous ground truth before using the class as history."
        )

    soil_conductivity_evidence = has(
        r"\b(?:soil|topsoil|root zone)\b[^.?]{0,100}\b(?:electrical conductivity|conductivity|ec|ds/m)\b|"
        r"\b(?:electrical conductivity|conductivity|ec|ds/m)\b[^.?]{0,100}\b(?:soil|topsoil|root zone)\b",
        q,
    )
    nutrient_rate_from_conductivity = has(
        r"\b(?:infer|derive|set|calculate|choose|support|justify|recommend)\w*\b[^?]{0,100}"
        r"\b(?:compost|manure|fertili[sz]er|nutrient|nitrogen|phosphorus|potassium|sulphur|sulfur)\b"
        r"[^?]{0,70}\b(?:rate|dose|amount|plan)\b|"
        r"\b(?:compost|manure|fertili[sz]er|nutrient|nitrogen|phosphorus|potassium|sulphur|sulfur)\b"
        r"[^?]{0,70}\b(?:rate|dose|amount|plan)\b[^?]{0,100}\b(?:from|using|based on)\b",
        q,
    )
    if soil_conductivity_evidence and nutrient_rate_from_conductivity and not explicit_agrochemical_context:
        qtype = "soil_water"
        namespaces.update({"soil_water", "soil_health", "fertility", "field_data_boundary"})
        tools.update({"field_data_guard", "fertility_guard", "nutrient_4r_guard", "salinity_sodicity_guard"})
        expansions.update({"soil EC", "salinity", "SAR", "ESP", "soil test", "crop need", "nutrient credits"})
        risk = "medium"
        guidance = (
            "Interpret soil electrical conductivity as salinity evidence, not a nutrient-rate calibration. "
            "Confirm sampling and salinity or sodium context, then use current calibrated fertility evidence and credits."
        )

    irrigation_depth_request = has(r"\b(?:mm|millimet(?:re|er)s?)\b", q) and has(
        r"\b(?:irrigat\w*|water(?:ing)?)\b", q
    ) and not has(r"\b(?:ml|millilit(?:re|er)s?|litres?|liters?|product rate|product volume)\b", q)
    if irrigation_depth_request and not explicit_agrochemical_context:
        qtype = "soil_water"
        namespaces.update({"soil_water", "field_data_boundary"})
        tools.update({"field_data_guard", "weather_guard"})
        expansions.update({"crop stage", "root-zone moisture", "soil water holding", "recent rainfall", "system capacity"})
        risk = "medium" if risk == "regulated" else risk
        guidance = (
            "Treat irrigation depth as a soil-water decision. Require crop stage, effective rooting depth, current "
            "root-zone water, soil water-holding capacity, recent rain and system constraints before naming millimetres."
        )
    if nutrient_terms and nutrient_action and not pesticide_terms:
        qtype = "fertility_diagnostic" if crop_stress else "fertility_rate"
        namespaces.update({"fertility", "soil_water", "field_data_boundary"})
        tools.update({"fertility_guard", "field_data_guard", "nutrient_4r_guard"})
        risk = "medium" if risk == "low" else risk
        if has(r"\b(?:rain|wet|weather|forecast|drought|dry|moisture|winter precipitation)\w*\b", q):
            tools.add("weather_guard")
        guidance = (
            "Treat the request as a calibrated nutrient decision. Separate crop stress from nutrient shortage, "
            "reconcile tests, credits, water and loss risk, and do not state a rate from symptoms, maps or weather alone."
        )

    variety_decision = (
        has(r"\b(?:variety|hybrid|cultivar|vari[eé]t[eé])\b", q)
        and has(r"\b(?:trial|rank|top yield|best|which|order|seed|class[eé]e|choix)\w*\b", q)
    ) or (
        has(r"\btrial\b", q) and has(r"\b(?:which one|which .* seed|seed across)\b", q)
    )
    if variety_decision:
        qtype = "crop_management"
        namespaces.update({"crop_management", "field_data_boundary", "economics"})
        tools.add("field_data_guard")
        expansions.update({"local multi-year trials", "maturity", "disease ratings", "yield stability", "standability"})
        variety_guidance = (
            "Use replicated multi-year local trials to narrow varieties, then match maturity, disease package, "
            "standability, field constraints and market fit; one ranking or regional map is not a field recommendation."
        )
        guidance = (
            f"{route.guidance} {variety_guidance}"
            if "regional_environment" in route.namespaces
            else variety_guidance
        )

    biological_problem = has(
        r"\b(?:clubroot|swollen roots?|disease|lesions?|blight|mildew|rust|aphids?|grasshoppers?|"
        r"drosophila|insects?|pests?|ravageurs?|l[eé]sions?|maladie)\b",
        q,
    )
    biological_decision = has(
        r"\b(?:diagnos|call|confirm|spray|treat|threshold|scout|count|should|what .*need|"
        r"d[eé]pist|traitement|pulv[eé]ris)\w*\b",
        q,
    )
    if biological_problem and biological_decision and qtype in {"conceptual", "exam_review", "plant_health"}:
        qtype = "plant_health"
        namespaces.update({"plant_health", "field_data_boundary"})
        tools.add("field_data_guard")
        if has(r"\b(?:rain|wet|humid|weather|forecast|tonight|wind|pluie)\w*\b", q):
            tools.add("weather_guard")
        if has(r"\b(?:spray|treat|fungicide|insecticide|pesticide|herbicide|traitement)\w*\b", q):
            namespaces.update({"product_stewardship", "label_boundary"})
            tools.update({"label_guard", "pesticide_safety_guard"})
            risk = "regulated"
        guidance = (
            "Diagnose and count before treatment: verify organism, field pattern, crop stage, severity or density, "
            "beneficials and current weather, then require current label fit before a product decision."
        )

    underspecified_herbicide = has(
        r"\b(?:usual broadleaf rate|usual herbicide rate|which herbicide|herbicide rate|weed .* rate|"
        r"rate .* weed|broadleaf rate)\b",
        q,
    )
    if underspecified_herbicide:
        qtype = "product_label"
        namespaces.update({"plant_health", "product_stewardship", "label_boundary", "field_data_boundary"})
        tools.update({"field_data_guard", "label_guard", "pesticide_safety_guard", "resistance_management_guard"})
        risk = "regulated"
        guidance = (
            "Do not infer a usual herbicide or rate. Require weed identity and stage, crop stage, field and product "
            "history, current label fit, application conditions and resistance-management context."
        )

    if qtype == "product_label" and has(r"\b(?:wild oats?|kochia|waterhemp|pigweed|ryegrass)\b", q):
        tools.add("resistance_management_guard")
    if qtype == "product_label" and has(
        r"\b(?:spray|fungicide|insecticide|pesticide|tonight|today|weather|forecast|wind|rain)\w*\b", q
    ):
        tools.add("weather_guard")

    if qtype.startswith("fertility"):
        tools.update({"fertility_guard", "field_data_guard"})
        if has(r"\b(?:rate|apply|application|fertilizer plan|nutrient plan|schedule|manure|starter|broadcast|banded)\b", q):
            tools.add("nutrient_4r_guard")
        if has(r"\b(?:fall[- ]applied nitrogen|fertilizer table|rate table)\b", q):
            tools.add("nutrient_4r_guard")
        if has(r"\b(?:rain|wet|dry|drought|weather|forecast|frost|moisture|temperature)\w*\b", q):
            tools.add("weather_guard")
        if has(r"\b(?:standing water|drainage|compaction|roots? turn|peat soil)\b", q):
            tools.add("soil_structure_guard")

    water_test_operation = has(r"\b(?:water test|\bEC\b|\bSAR\b|\bESP\b)\b", question) and has(
        r"\b(?:irrigat|pivot|running|season|drain)\w*\b", q
    )
    if water_test_operation:
        qtype = "soil_water"
        namespaces.update({"soil_water", "soil_health", "field_data_boundary"})
        tools.update({"field_data_guard", "salinity_sodicity_guard", "soil_structure_guard", "weather_guard"})
        risk = "medium" if risk == "low" else risk
        guidance = (
            "Interpret water EC and sodium hazard with soil salinity, drainage, leaching feasibility, crop stage, "
            "system performance and repeated seasonal evidence; one sample cannot authorize an unchanged season-long plan."
        )

    mapped_soil_action = has(r"\b(?:soileri|solonetzic|soil survey|soil map|mapped polygon)\b", q) and has(
        r"\b(?:prescrib|deep[- ]?rip|drain|practice|manage|losing|tillage)\w*\b", q
    )
    if mapped_soil_action:
        qtype = "soil_water"
        namespaces.update({"soil_water", "soil_health", "field_data_boundary", "regional_environment"})
        tools.update({"field_data_guard", "soil_structure_guard"})
        if has(r"\b(?:solonetzic|sodic|gypsum)\b", q):
            tools.update({"salinity_sodicity_guard", "fertility_guard"})
        guidance = (
            "Use mapped soil or erosion classes as screening context only. Ground-truth soil, slope, runoff, "
            "rooting, wetness and structure before drainage, tillage, amendment or conservation prescriptions."
        )

    regional_field_decision = has(
        r"\b(?:map|crop[- ]health|nasdi|spei|historical average|regional (?:alert|signal|index))\b", q
    ) and has(r"\b(?:damage|hail|seed|plant|irrigat|spray|record|cancel|turn cattle|field)\w*\b", q)
    operational_regional_decision = has(
        r"\b(?:damage|hail|seed|plant|irrigat|spray|cancel|turn cattle)\w*\b",
        q,
    )
    if regional_field_decision and (
        qtype == "conceptual" or (qtype == "regional_context" and operational_regional_decision)
    ):
        qtype = "field_data"
        namespaces.update({"field_data_boundary", "regional_environment", "crop_management"})
        tools.update({"field_data_guard", "weather_guard"})
        guidance = (
            "Treat the regional map, index or historical average as context only. Verify current field damage, crop "
            "stage, soil and weather observations before recording a cause or changing an operation."
        )

    if qtype == "soil_water":
        if has(r"\b(?:irrigat|pump|plant|seed|graz|turn cattle|nasdi|spei|weather|forecast|rain|wet)\w*\b", q):
            tools.add("weather_guard")
        if has(r"\b(?:drain|tile|deep[- ]?rip|compaction|rooting|roots? turn|standing water|traffic|ponding|gypsum)\w*\b", q):
            tools.add("soil_structure_guard")
        if has(r"\b(?:gypsum|lime|chaux|manure)\b", q):
            tools.add("fertility_guard")

    if qtype == "crop_management" and has(r"\b(?:nutrient plan|fertility|fertilizer|fertigation)\b", q):
        tools.add("fertility_guard")

    if qtype in {"crop_management", "regional_context"} and has(
        r"\b(?:weather|forecast|rain|wet|humid|wind|evaporative demand|nasdi)\b", q
    ):
        tools.add("weather_guard")
    if qtype == "crop_management" and has(r"\b(?:field|grower|map|trial|storage|planting)\b", q):
        tools.add("field_data_guard")
    if qtype == "crop_management" and has(r"\bnasdi\b", q) and has(r"\b(?:wet|graz|cattle|pasture)\w*\b", q):
        tools.update({"field_data_guard", "soil_structure_guard", "weather_guard"})
    if qtype == "crop_management" and has(r"\b(?:frost date|planting into|before planting)\b", q):
        tools.add("weather_guard")
    if qtype == "conceptual" and has(r"\b(?:from before|still haven't said|still have not said)\b", q):
        qtype = "field_data"
        namespaces.add("field_data_boundary")
        tools.add("field_data_guard")
        guidance = "Recover the missing crop, field, operation and prior record before continuing the decision."

    # Broad lexical collection deliberately errs toward safety, but a bare use
    # of words such as "label" (for a mapped crop class) or "application" (for
    # irrigation or nutrients) is not evidence of a pesticide decision.  Once
    # primary intent is reconciled, remove pesticide-only controls unless the
    # request actually names an agrochemical authority or a regulated organic-
    # nutrient land-application question.
    if qtype in {"field_data", "soil_water", "fertility_rate", "fertility_diagnostic"} and not (
        explicit_agrochemical_context or regulated_land_application
    ):
        namespaces.difference_update({"label_boundary", "product_stewardship"})
        tools.difference_update({"label_guard", "pesticide_safety_guard", "resistance_management_guard"})
        if risk == "regulated":
            risk = "medium"

    if benign_conceptual_explanation:
        qtype = "exam_review"
        namespaces.difference_update(
            {"plant_health", "product_stewardship", "label_boundary", "field_data_boundary"}
        )
        namespaces.update({"crop_management", "exam_review"})
        tools.clear()
        risk = "low"
        guidance = (
            "Explain the agronomy practice or mechanism directly. Distinguish the general concept from a "
            "field diagnosis or prescription without requesting case-specific evidence the user did not need."
        )

    return QueryRoute(
        question_type=qtype,
        risk_level=risk,
        namespaces=tuple(sorted(namespaces)),
        required_tools=tuple(sorted(tools)),
        answer_style="exam_review" if benign_conceptual_explanation else route.answer_style,
        audience=route.audience,
        query_expansion=tuple(sorted(expansions)),
        guidance=guidance,
        knowledge_bucket=(
            "regional_environment_context"
            if qtype == "regional_context" or (qtype == "soil_water" and "regional_environment" in namespaces)
            else "farmer_knowledge"
        ),
        knowledge_domains=tuple(sorted(_infer_knowledge_domains(q, namespaces))),
    )


def request_focus(text: str) -> str:
    """Return the user's final request, excluding most incidental field detail."""

    request_split = re.split(r"\brequest\s*[:\n]", text, flags=re.IGNORECASE)
    if len(request_split) > 1:
        return request_split[-1].strip()
    question_end = text.rfind("?")
    if question_end >= 0:
        candidate = text[: question_end + 1]
        sentence_start = max(candidate.rfind(". "), candidate.rfind("\n"))
        sentence = candidate[sentence_start + 1 :]
        lead = re.search(r"\b(?:what|how|should|which|when|where|why|can|does|do|is|are|give)\b", sentence, re.IGNORECASE)
        if lead:
            return text[sentence_start + 1 + lead.start() :].strip()
    return text


def _is_benign_conceptual_explanation(text: str) -> bool:
    """Recognize non-operational agronomy concept and mechanism questions.

    Agronomic vocabulary such as ``disease`` or ``pest`` must not by itself
    turn an explanatory question into a field diagnosis.  This gate is
    intentionally conservative: field-specific evidence, a requested action,
    regulated products, rates, thresholds, or labels keep their existing
    diagnostic or product routes.
    """

    q = _routing_text(text).strip()
    focus = request_focus(q).strip()
    explanatory_form = has(
        r"^(?:please\s+)?(?:"
        r"what\s+(?:is|are)\b|"
        r"why\s+(?:does|do|can|is|are)\b|"
        r"how\s+(?:does|do|can|is|are)\b|"
        r"explain\b|describe\b)",
        focus,
    )
    if not explanatory_form:
        return False

    field_specific = has(
        r"\b(?:my|our)\b|"
        r"\bthis\s+(?:field|farm|crop|plant|stand|season|sample|test|map)\b|"
        r"\b(?:today|tomorrow|tonight|currently|right now|this week|this season)\b",
        q,
    )
    operational_request = has(
        r"\b(?:what\s+should|what\s+do|how\s+should|when\s+should)\b|"
        r"\b(?:can|may|do|should)\s+(?:i|we)\b|"
        r"\b(?:diagnos|identify|confirm|treat|spray|apply|prescrib|recommend|"
        r"choose|select)\w*\b",
        focus,
    )
    regulated_or_numeric_request = has(
        r"\b(?:herbicide|fungicide|insecticide|pesticide|tank mix|product[- ]?label|"
        r"label|rates?|dose|dosage|threshold|how much|"
        r"pre[- ]?harvest interval|restricted[- ]?entry interval|phi|rei|ppe)\b",
        focus,
    ) or _is_named_product_permission_request(text)
    diagnostic_observation = has(
        r"\b(?:symptoms?|lesions?|leaf spots?|root rot|yellow(?:ing)?|pale|wilting|"
        r"patch(?:y|es)?|stunt(?:ed|ing)?|stand loss|injury|infestation)\b",
        focus,
    )
    return not (
        field_specific
        or operational_request
        or regulated_or_numeric_request
        or diagnostic_observation
    )


def _resolve_primary_question_type(text: str, current: str) -> str:
    """Stabilize primary intent after the broad namespace and guard pass.

    The router intentionally gathers safety and retrieval signals from the full
    field description. Primary intent is different: it should follow the final
    request, not whichever incidental keyword happened to match last.
    """

    focus = request_focus(text.lower())
    if has(r"\busing only (?:the )?(?:supplied|provided|following)\b|\bextension excerpt\b", text):
        return "conceptual"
    if _is_named_product_permission_request(text) or has(
        r"\b(?:phi|rei|pre[- ]?harvest interval|restricted[- ]?entry interval)\b",
        focus,
    ):
        return "product_label"
    if _is_benign_conceptual_explanation(text):
        return "exam_review"

    if has(_FRENCH_SOIL_WATER_PATTERN, text) and (
        has(_FRENCH_MAP_PATTERN, text)
        or has(r"\b(?:appliquer|epandre|épandre|recommander|corriger|traiter)\b", focus)
    ):
        return "soil_water"

    if has(r"\b(?:soil[- ]?ec|sar|esp)\b", text) and has(
        r"\b(?:gypsum|amend|apply|spread|treat|reclaim)\w*\b", focus
    ):
        return "soil_water"

    if has(r"\bgypsum\b", text) and has(
        r"\b(?:white (?:crust|rings?)|thinning|bare patches?|poor infiltration|ponding)\b",
        text,
    ):
        return "soil_water"

    if has(r"\b(?:irrigation|water)\b[^.]{0,80}\b(?:mm|millimet(?:re|er)s?)\b", text) and has(
        r"\b(?:ml|millilit(?:re|er)s?|litres?|liters?|product)\b", focus
    ):
        return "product_label"

    map_context = has(
        r"\b(?:map|mapped|mapping|polygon|layer|atlas|land suitability|capability|regional product)\b",
        text,
    )
    if map_context and has(r"\b(?:choose|select|order)\w*\b", focus) and has(
        r"\b(?:variety|hybrid|cultivar|genetics)\b", focus
    ):
        return "crop_management"
    if map_context and (
        has(r"\bwhich crop\b|\bwhat crop\b|\bcrop (?:choice|selection)\b", focus)
        or has(r"\b(?:choose|select)\w*\b[^.?]{0,40}\bcrop\b", focus)
        or has(r"\bplant\b[^.?]{0,20}\bnext (?:year|season)\b", focus)
    ):
        return "field_data"

    if has(_OPERATIONAL_TRAFFICABILITY_PATTERN, focus):
        return "soil_water"

    if (
        has(_FIELD_HISTORY_REFERENCE_PATTERN, text)
        and has(
            r"\b(?:check|verify|decide|decision|next|before|change|support|show|tell|use)\b",
            focus,
        )
    ):
        return "field_data"

    if (
        has(r"\b(?:map|mapped|mapping|polygon|layer|geometry|spatial|capability|regional)\b", focus)
        and has(r"\b(?:intersection|intersected|intersects?|context|prior|capability)\b", focus)
        and has(r"\b(?:tell|support|prove|assume|evidence|collect|measure|before|change)\b", focus)
    ):
        return "field_data"

    if (
        has(r"\b(?:soil survey|soil map|map unit|mapped soil|polygon|regional data product)\b", text)
        and has(r"\b(?:intersection|intersected|intersects?|mapped|mapping|coverage)\b", text)
        and has(r"\b(?:tell|support|prove|assume|cover|coverage|verify|before|alone)\b", focus)
    ):
        return "field_data"

    if all(
        has(pattern, text)
        for pattern in (
            r"\bnutrient management\b",
            r"\bpest management\b",
            r"\bsoil[- ]water\b",
            r"\b(?:crop )?records?\b",
        )
    ):
        return "integrated_management"

    if has(r"\b(macronutrients?|micronutrients?)\b", text) and has(
        r"\b(mobility|mobile|immobile|exam|trainee)\b", text
    ):
        return "exam_review"

    if has(r"\b(?:sorghum[- ]?sudan(?:grass)?|sudangrass)\b", text) and has(
        r"\b(?:frost|freeze|drought|regrowth)\b", text
    ) and has(r"\b(?:graz|cattle|feed|hay|cut)\w*\b", text):
        return "crop_management"

    if has(r"\b(?:field heat|postharvest|pre[- ]?cool|cold chain|cooler)\b", text) and has(
        r"\b(?:fresh[- ]market|strawberr|berry|produce|tote|cool)\w*\b", text
    ):
        return "crop_management"

    if has(r"\b(?:variety|hybrid)\b", text) and has(r"\btrials?\b", text) and has(
        r"\b(?:one (?:dry )?(?:year|trial)|top(?:ped)?|highest[- ]yield|nearby trial|trial result|stable across|main silage|grain trial)\b",
        text,
    ):
        return "crop_management"

    if has(r"\b(?:nematodes?|nematicide)\b", text):
        return "plant_health"

    if has(r"\bvolunteer canola\b", text) and has(
        r"\b(?:trait|tolerance|system|records?|appearance|post product)\b", text
    ):
        return "product_label"

    if has(r"\b(?:pre[- ]?emergence|residual)\b", text) and has(
        r"\b(?:activation|almost no rain|no rain|incorporat\w*|emerg\w*|repeat|higher rate)\b", text
    ):
        return "product_label"

    if has(r"\bfurrow[- ]irrigat", text) and has(r"\b(?:tailwater|tail end|head|advance|set time|runoff)\b", text):
        return "soil_water"

    if has(r"\b(?:volumetric water content|soil[- ]moisture sensor|sensor reading|VWC)\b", text) and has(
        r"\b(?:texture|sandy|silt|gravel|rooting depth|roots?)\b", text
    ):
        return "soil_water"

    if has(r"\b(?:leafy greens?|fresh produce)\b", text) and has(
        r"\b(?:harvest|buyer|workers?|irrigation source|leaf spots?)\b", text
    ):
        return "crop_management"

    if has(r"\b(center pivot|pivot|drip tape|drip line|emitters?|laterals?)\b", text) and has(
        r"\b(pond\w*|runoff|infiltrat\w*|application rate|total water|flow|pressure|clog\w*|uniformity|flush\w*)\b",
        text,
    ):
        return "soil_water"

    if has(r"\b(slake test|aggregate stability|soil aggregates?)\b", text):
        return "soil_water"

    if has(r"\b(specialty crop|specialty|vegetable|produce safety)\b", text) and has(
        r"\b(irrigat\w*|water quality|water test)\b", text
    ) and has(r"\b(produce safety|food safety|disease)\b", text):
        return "crop_management"

    if has(r"\b(root rot|stem rot|powdery mildew|leaf spot|mold|blight|rust|disease)\b", text) and has(
        r"\b(diagnos\w*|separate|distinguish|manage|management|infect\w*|what should|what do)\b",
        text,
    ):
        return "plant_health"

    if not has(r"\b(?:seed treatment|treated seed)\b", text) and has(
        r"\b(?:insects?|pests?|caterpillars?|moths?|trap captures?|aphids?|rootworm beetles?|weevils?|leafhoppers?|defoliat\w*)\b", text
    ) and has(
        r"\b(?:spray|treat|insecticide|threshold)\w*\b", text
    ):
        return "plant_health"

    if (
        has(r"\b(?:weeds?|waterhemp|pigweed|ryegrass|kochia|palmer amaranth)\b", text)
        and has(r"\b(?:escape\w*|surviv\w*|resistan\w*|seed set|seedbank|burndown|contain\w*|before harvest|next season)\b", text)
    ) or (
        has(r"\bherbicide\b", text)
        and has(r"\b(?:escape\w*|surviv\w*|seed set|seedbank|burndown)\b", text)
    ):
        return "product_label"

    if has(r"\b(?:blossom[- ]end rot|tipburn)\b", text):
        return "fertility_diagnostic"

    if has(r"\blettuce\b", text) and has(r"\b(?:brown|necrotic) inner leaf margins?|\binner (?:lettuce )?leaves?\b[^.]{0,45}\b(?:brown|necrotic|margins?)\b", text) and has(
        r"\bcalcium\b", text
    ):
        return "fertility_diagnostic"

    if has(r"\b(?:soil |surface )?crust\w*\b", text) and has(r"\bemerg", text):
        return "soil_water"

    if has(r"\b(?:deep[- ]?rip|deep till|subsoil)\w*\b", text) or (
        has(r"\b(?:compaction|wheel tracks?)\b", focus)
        and has(r"\b(?:till|rip|alleviat|remediat|management options?)\w*\b", focus)
    ):
        return "soil_water"

    if (
        not has(r"\b(?:high[- ]tunnel|root rot|root disease|root discoloration)\b", text)
        and has(r"\b(?:saline|salinity|salty|salt)\b", text)
        and (
            has(r"\bsalty irrigation water\b|\bsaline (?:irrigation )?water\b|\birrigation water (?:is|looks) salty\b", text)
            or has(r"\b(?:saline|salinity|sodic|salt|leach)\w*\b", focus)
        )
    ):
        return "soil_water"

    if has(r"\b(?:ponded|ponding|flooded|flooding|standing water)\b", text) and has(
        r"\b(?:recover|surviv|replant|young corn|crop)\w*\b", text
    ):
        return "soil_water"

    if has(r"\b(?:freeze|frost)\b", text) and has(r"\b(?:recover|replant|stand|injur|surviv|developing head)\w*\b", text):
        return "crop_management"

    if has(r"\b(?:corn|silk|pollen|kernel set)\w*\b", text) and has(r"\b(?:pollinat|silk|pollen|kernel set)\w*\b", text) and has(
        r"\b(?:heat|hot|dry|drought|water stress)\b", text
    ):
        return "crop_management"

    if has(r"\b(?:relative maturity|maturity group)\b", text) and has(
        r"\b(?:late|delay\w*|planting date|switch)\b", text
    ):
        return "crop_management"

    if has(r"\bwilt\w*\b", text) and has(r"\b(?:water stress|disease|vascular|irrigat)\w*\b", text):
        return "plant_health"

    if has(r"\b(?:choose|select|compare|narrow)\w*\b", text) and has(
        r"\b(hybrid|variety|cultivar|genetics)\b", text
    ):
        return "crop_management"

    if has(r"\b(yield maps?|soil ec|ndvi|imagery|as[- ]applied|spatial layers?|soil test points?)\b", text) and has(
        r"\b(variable[- ]rate|prescription|management zones?|turn this into)\b", text
    ):
        return "field_data"

    if has(r"\b(sampling design|management zones?|old soil tests?)\b", text) and has(r"\b(soil tests?|samples?|sampling)\b", text):
        return "field_data"

    if has(r"\b(organic matter|soil organic carbon)\b", text) and (
        has(r"\b(?:organic matter|soil organic carbon)[^.?]{0,100}\b(?:trend|changing|sampling noise|recent soil tests?)\b", text)
        or has(r"\b(trend|sampling noise|management response)\b", focus)
    ):
        return "field_data"

    if has(r"\b(high[- ]tunnel|fertigation)\b", text) and has(r"\b(disease|food[- ]safety|salinity)\b", text):
        return "crop_management"

    if has(r"\b(pollinator|bees?|beekeeper|bee advisory)\b", text) and has(r"\b(spray|pesticide|insecticide|fungicide|herbicide)\b", text):
        return "product_label"

    if has(r"\b(conservation|precision)\b", text) and has(
        r"\b(pay|econom\w*|farm(?:'s)? books?|partial budget|ROI|net return)\b", text
    ):
        return "field_data"

    if has(r"\b(tank mix|adjuvant|compatibility)\b", text) and has(r"\b(herbicide|pesticide|product|label)\b", text):
        return "product_label"

    if has(r"\bmycotoxin\b", text) and has(r"\b(field disease|harvest|storage|testing|segregation)\b", text):
        return "crop_management"

    if has(r"\b(harvest|storage)\b", focus) and has(r"\b(moisture|drying|aeration|quality|mycotoxin)\b", text):
        return "crop_management"

    if has(r"\b(erosion|soil loss|visible runoff|conservation)\b", text) and has(
        r"\b(residue|cover crop|waterway|runoff|soil loss|conservation|drainage ditch)\b", text
    ):
        return "soil_water"

    if has(r"\b4r\b|\bright source\b|\bright rate\b|\bright time\b|\bright place\b", text):
        return "fertility_rate"

    if has(r"\bvariable[- ]rate nitrogen\b", text) and has(r"\b(?:increase|rate|prescription)\b", text):
        return "fertility_rate"

    if has(r"\bproduct timing\b", focus) and has(r"\b(?:approv|allow|acceptable|before)\w*\b", focus):
        return "product_label"

    if has(r"\bfungicide\b", text) and has(r"\b(?:justif|return|roi|economic|worth|pay|payback)\w*\b", text):
        return "plant_health"

    if has(r"\brescue nitrogen pass\b|\brescue n pass\b", text) and has(
        r"\b(justif|chang|adjust|needed|need)\w*\b", text
    ):
        return "fertility_rate"

    if has(r"\bmanure credits?\b", text) and has(r"\b(chang|fertility plan|nutrient availability)\w*\b", text):
        return "fertility_rate"

    if has(r"\bmicronutrient deficiency\b|\bmicronutrient\b[^?]{0,100}\bdifferential\b", text):
        return "fertility_diagnostic"

    if has(r"\b(herbicide carryover|carryover risk|rotation restrictions?|plant[- ]back)\b", text):
        return "product_label"

    if has(r"\bpre[- ]?emergence herbicide\b|\bresidual activation\b|\bresidual\b", text) and has(
        r"\b(activation|control failure|judging? (?:control )?failure|almost no rain|no rain|repeat|higher rate|emerg\w*)\b",
        text,
    ):
        return "product_label"

    if has(r"\b(seed lots?|seed quality|germination|germ test|cold test|accelerated aging|seed vigor|vigor test)\b", text) and has(
        r"\b(plant|planting|stand|replant|seeding rate)\b", text
    ):
        return "crop_management"

    if has(r"\b(trait packages?|technology traits?|trait stewardship|refuge)\b", text):
        return "crop_management"

    if has(r"\b(specialty|vegetable|produce)\b", text) and has(r"\b(irrigat\w*|water quality|water test)\b", text) and has(
        r"\b(food safety|produce safety|disease)\b", text
    ):
        return "crop_management"

    if has(r"\bfertigation\b", text) and has(r"\b(nutrient balance|water quality|EC|leaching risk|crop stage)\b", text):
        return "crop_management"

    if has(r"\b(poor fruit set|poor kernel set|fruit set)\b", text) and has(r"\b(pollination|flowering|bloom)\b", text):
        return "crop_management"

    if has(r"\b(tissue[- ]test results?|tissue testing|plant analysis)\b", text) and has(
        r"\b(interpret|sampling timing|growth stage|crop stage|soil tests?)\b", text
    ):
        return "fertility_diagnostic"

    if has(r"\bnematode risk\b|\bnematodes?\b|\bnematicide\b", text) and has(
        r"\b(rotation|variety|treatment|sample|population|first move|logical)\b", text
    ):
        return "plant_health"

    if has(r"\b(root rot|root disease|root discoloration)\b", text) and has(
        r"\b(drainage|compaction|salinity|nutrient stress|sample|diagnos)\b", text
    ):
        return "plant_health"

    if has(r"\b(herbicide drift|off[- ]target movement)\b", text) and has(r"\b(injury|separat|differential|symptom)\b", text):
        return "plant_health"

    if has(r"\b(volatilization|fertilizer source)\b", text) and has(r"\b(placement|rainfall timing|incorporation|injection)\b", text):
        return "fertility_rate"

    if has(r"\b(on[- ]farm trial|strip trial|trial design)\b", text) and has(r"\b(yield monitor|inference|credible|practice)\b", text):
        return "field_data"

    if has(r"\b(seed treatment|treated seed)\b", text) and has(
        r"\b(needed|need|risk|pest[- ]history|field evidence|field history|planting)\b", text
    ):
        return "seed_treatment"

    if has(r"\bforecast uncertainty\b", text) and sum(
        bool(has(pattern, text)) for pattern in (r"\bplant\w*\b", r"\bspray\w*\b", r"\bside[- ]?dress\w*\b")
    ) >= 2:
        return "soil_water"

    if has(r"\b(climate normals?|historical gridded|gridded climate)\b", text) and has(
        r"\b(forecast|current weather|short[- ]term|prove|prediction)\b", text
    ):
        return "soil_water"

    if has(r"\b(rainfall intensity|runoff risk)\b", text) and has(
        r"\b(rainfast|incorporation windows?|application window|fertilizer or pesticide)\b", text
    ):
        return "soil_water"

    if has(r"\b(high[- ]tunnel|fertigation)\b", text) and has(r"\b(disease|food[- ]safety|salinity)\b", text):
        return "crop_management"

    if has(r"\b(corn|soybeans?|crop)\b", text) and has(
        r"\b(rectangular|lesions?|leaf spots?|disease|aphids?|pest|economic thresholds?|beneficials?|natural enemies)\b",
        text,
    ) and has(r"\b(fungicide|insecticide|treat|treatment|recommend|product selection|threshold)\b", text):
        return "plant_health"

    if has(r"\b(scouts?|scouting|sampling)\b", text) and has(r"\b(insects?|pests?|aphids?)\b", text) and has(
        r"\b(insecticide|treat|treatment|justif|threshold)\w*\b", text
    ):
        return "plant_health"

    if has(r"\bpest management recommendations?\b", text) and has(
        r"\b(scouting|sampling|economic thresholds?|identification)\b", text
    ):
        return "plant_health"

    if has(r"\b(?:nitrogen|nitrate)\b", text) and has(r"\b(?:chang|increas|decreas|adjust)\w*\b[^?]{0,50}\brate\b", focus):
        return "fertility_rate"

    if has(r"\b(?:variable[- ]rate|prescription|response curve|check strip|partial budget)\b", text) and has(
        r"\b(?:economic|profit|roi|return|defensible|cost|spend)\w*\b", focus
    ):
        return "field_data"

    if has(r"\b(?:ORNL )?Daymet\b", text) and has(r"\b(climate[- ]window|soil moisture|cover[- ]crop water)\b", text):
        return "soil_water"

    if all(has(pattern, text) for pattern in (r"\bmap\b", r"\bsoil\b", r"\bweather\b", r"\blabel\b")) and has(
        r"\b(refuse|infer|what should the agent do)\b", text
    ):
        return "field_data"

    if has(
        r"\b(source cards?|sources? checked|provenance|adapter|not configured|unavailable|"
        r"shapefile|geojson|geopackage|uploaded boundary|drawn boundary|geometry|polygon|crs|"
        r"public soil map|soil survey|soil-survey|NRCS|SDA|map units?|dominant components?|component percent|soil map support|map unit.*(?:support|prove)|field-specific public sources?|"
        r"yield maps?|as-applied records?|prescription layers?|variable-rate.*(?:records?|maps?|support))\b",
        focus,
    ):
        return "field_data"

    if has(r"\b(seed treatment|treated seed)\b", focus):
        return "seed_treatment"

    direct_product_action = has(
        r"\b(spray|spraying|apply|application rate|application timing|weather and label checks|timing is approved|tank mix|product selection|which (?:herbicide|fungicide|insecticide|pesticide)|"
        r"label (?:allow|require|say)|preharvest interval|restricted entry interval|ppe)\b",
        focus,
    )
    fertility_focus = has(
        r"\b(nutrient plan|fertility|fertilizer|nitrogen|phosphorus|potassium|sulfur|lime|manure|"
        r"soil[- ]test|tissue[- ]test|4r)\b",
        focus,
    )
    if direct_product_action and not fertility_focus:
        return "product_label"

    if has(r"\b(crop-management|specialty-crop)\b", focus) or (
        has(r"\birrigation\b", focus)
        and has(r"\bfertility\b", focus)
        and has(r"\b(pest|disease|food-safety|market-quality)\b", focus)
    ):
        return "crop_management"

    if fertility_focus:
        return "fertility_rate" if has(r"\b(rates?|amount|how much|change|increase|decrease|apply)\b", focus) else "fertility_diagnostic"

    if has(
        r"\b(irrigation|evapotranspiration|soil water|water holding|infiltration|drainage|water table|"
        r"salinity|sodicity|compaction|restrictive layer|erosion|runoff|leaching|cover crop water)\b",
        focus,
    ):
        return "soil_water"

    if has(
        r"\b(crop-management|seed or variety|variety choices?|public (?:variety )?trials?|hybrid|cultivar|planting window|"
        r"replant|stand establishment|postharvest|harvest|storage|cooling|market-quality)\b",
        focus,
    ):
        return "crop_management"

    if has(r"\b(pale|yellow(?:ing)?|chlorosis|stunt\w*|patchy|uneven|poor stand|stand loss)\b", text) and has(
        r"\b(field read|agronomic read|what matters|what should|what do|next|diagnos\w*|cause|evidence)\b",
        text,
    ):
        return "fertility_diagnostic"

    if has(
        r"\b(pest|aphid|insect|disease|pathogen|differential(?: diagnosis)?|diagnos|symptom|leaf spot|root rot|"
        r"weed control|weed identification|economic threshold|beneficials?|natural enem|scouting|trap captures?|fruit injury)\b",
        focus,
    ):
        return "plant_health"

    return current


def _safe_domain_terms() -> dict[str, tuple[str, ...]]:
    return {
        "fertility": ("soil_health", "farmer_knowledge"),
        "soil_health": ("soil_health", "farmer_knowledge"),
        "soil_water": ("soil_water", "water_management", "soil_health", "farmer_knowledge"),
        "precision_ag": ("soil_health", "crop_management", "farmer_knowledge"),
        "crop_management": ("crop_management", "farmer_knowledge"),
        "plant_health": ("crop_management", "farmer_knowledge"),
        "field_data_boundary": ("farm_management", "operations", "farmer_knowledge"),
        "economics": ("market", "farmer_knowledge", "operations"),
        "exam_review": ("farmer_knowledge",),
        "regional_environment": ("regional_environment_context", "soil_water", "conservation", "farmer_knowledge"),
    }


def _infer_knowledge_domains(q: str, namespaces: set[str]) -> set[str]:
    domains: set[str] = {"farmer_knowledge"}
    namespace_map = _safe_domain_terms()
    for ns in namespaces:
        for domain in namespace_map.get(ns, ()):  # type: ignore[arg-type]
            domains.add(domain)

    if has(r"\b(livestock|cattle|beef|dairy|sow|cow|hog|sheep|pig|chicken)\b", q):
        domains.update({"livestock", "farmer_knowledge"})

    if has(r"\b(tractor|combine|plow|plough|machinery|implement|equipment|sprayer|harvester)\b", q):
        domains.update({"operations", "machinery", "farmer_knowledge"})

    if has(r"\b(market|price|profit|revenue|cost|margin|contract|forward contract|sell|storage)\b", q):
        domains.update({"market", "operations", "farmer_knowledge"})

    if has(r"\b(conservation|buffer strip|cover crop|erosion|wetland|wildlife)\b", q):
        domains.update({"conservation", "farmer_knowledge"})

    if has(r"\b(farm plan|farm schedule|field log|bookkeeping|labor|staff|farm business|cash flow)\b", q):
        domains.update({"farm_management", "operations", "farmer_knowledge"})

    if has(r"\b(water quality|irrig|irrigation|drainage|tile|leaching|runoff|salinity|sodicity)\b", q):
        domains.update({"soil_water", "water_management", "farmer_knowledge", "soil_health"})

    return domains


def classify_query(question: str) -> QueryRoute:
    q = _routing_text(question)
    namespaces: set[str] = set()
    required_tools: set[str] = set()
    expansions: set[str] = set()
    risk = "low"
    qtype = "conceptual"
    style = "plain"
    guidance = "Answer directly. Use field caveats briefly when needed."
    knowledge_bucket = "farmer_knowledge"

    if has(r"\b(product|herbicide|fungicide|insecticide|pesticide|spray|tank mix|label|dicamba|volatile)\b", q):
        namespaces.update({"product_stewardship", "label_boundary", "plant_health"})
        required_tools.add("label_guard")
        risk = "regulated"
        qtype = "product_label"
        expansions.update({"label", "jurisdiction", "crop", "target pest", "wind", "buffer"})
        if has(r"\b(volatile|dicamba|drift|wind|sensitive|downwind)\b", q):
            required_tools.add("weather_guard")
            expansions.update({"wind speed", "wind direction", "gust", "downwind", "sensitive crop", "buffer", "drift", "delay", "do not spray"})
            guidance = "For volatile-herbicide drift risk, lead with delay or do-not-spray until label, wind speed and direction, gusts, downwind sensitive crops, buffers, inversions, and rainfall constraints are checked. Avoid unsourced product chemistry examples."
        else:
            guidance = "Keep product/rate claims label-bound. Discuss decision criteria before product specifics."
        if has(
            r"\b(health|safety|environmental checks?|ppe|personal protective|restricted entry|rei\b|preharvest|preharvest interval|phi\b|storage|handling|sensitive area|drift|buffer|setback|recordkeeping|records?|spray record|application record|worker safety|pollinator|bee advisory|water quality|refuge|stewardship|quarantine|regulated pest|invasive|movement boundary)\b",
            q,
        ):
            required_tools.add("pesticide_safety_guard")
            expansions.update({"PPE", "REI", "PHI", "buffer", "drift", "water", "sensitive area", "storage", "handling", "disposal", "records"})
            guidance = "For pesticide safety recommendations, lead with label, PPE, REI, PHI where relevant, buffer/drift controls, water or sensitive-area protection, storage/handling, disposal, and records."
        if has(r"\b(resistance|resistant|escapes?|same herbicide|mode of action|site of action|rotate)\b", q):
            required_tools.add("resistance_management_guard")
            expansions.update({"mode of action", "site of action", "weed species", "field history", "scout escapes", "rotate", "multiple effective", "nonchemical", "crop rotation", "mechanical control", "label"})
            guidance = "For resistance management, identify the pest or weed and field history, scout escapes, verify the label, rotate or mix multiple effective modes/sites of action, and include nonchemical tactics."

    if has(r"\b(fertil|nitrogen|phosphorus|potassium|sulfur|lime|manure|soil[- ]test|tissue[- ]test|ph\b|buffer ph|nutrient|nitrate)\b", q):
        namespaces.update({"fertility", "soil_water", "economics"})
        required_tools.add("fertility_guard")
        risk = "medium" if risk == "low" else risk
        qtype = "fertility_rate" if has(r"\b(rate|recommend|tons?|lb|pounds|kg|apply)\b", q) else "fertility_diagnostic"
        expansions.update({"soil test method", "yield goal", "credits", "calibration", "crop removal"})
        if has(
            r"\b(4r|right source|right rate|right time|right place|nutrient management plan|manure history|manure credit|manure analysis|tile drainage|tile outlet|drainage ditch|nitrate loss|edge-of-field|water quality|runoff|leaching|irrigation-water nitrate|irrigation water nitrate|water nitrate|nitrogen credit|fertilizer credit|nutrient credit|split timing|placement)\b",
            q,
        ):
            required_tools.add("nutrient_4r_guard")
            expansions.update({"right source", "right rate", "right time", "right place", "manure credit", "manure analysis", "tile drainage", "leaching", "runoff", "records", "soil test", "yield goal"})
            guidance = "For 4R nutrient planning, explicitly organize the answer around right source, right rate, right time, and right place; include soil test, yield goal, manure analysis/credits, tile or runoff risk, placement, timing, and records."
        if has(r"\b(lime|low ph|buffer ph|aglime|acidity)\b", q):
            expansions.update(
                {
                    "buffer pH",
                    "lime requirement",
                    "target pH",
                    "crop rotation",
                    "CCE",
                    "ECCE",
                    "neutralizing value",
                    "lime source",
                }
            )
            guidance = (
                "For lime advice, lead with soil-test pH plus buffer pH or lime requirement, target pH, "
                "crop or rotation, and CCE, ECCE, or neutralizing value of the lime source before any rate."
            )
        if has(r"\b(phosphorus|soil test reports phosphorus|bray|olsen|mehlich)\b", q):
            expansions.update(
                {
                    "Bray",
                    "Olsen",
                    "Mehlich",
                    "not interchangeable",
                    "do not convert",
                    "critical level",
                    "soil pH",
                    "crop removal",
                    "yield goal",
                }
            )
            guidance = (
                "For phosphorus without method context, explicitly say Bray, Olsen, and Mehlich are not "
                "interchangeable without calibration; ask for method, units, pH, crop, and yield goal."
            )
            if has(r"\b(high|very high|excess|elevated)\b", q) and has(r"\b(runoff|water quality|ditch|stream|surface water|rainfall|manure)\b", q):
                expansions.update(
                    {
                        "soil-test P",
                        "setback",
                        "buffer",
                        "runoff pathway",
                        "erosion",
                        "manure history",
                        "crop removal",
                        "drawdown",
                        "avoid additional P",
                        "do not apply P",
                        "P-index",
                    }
                )
                guidance = (
                    "For very high soil-test phosphorus with runoff or water-quality exposure, frame the risk with "
                    "soil-test P method and units, erosion or runoff pathway, setbacks or buffers, manure history, "
                    "crop removal or drawdown, and local P-index or calibration; avoid additional P or do not apply P "
                    "when risk is high unless local guidance supports an exception."
                )
        if has(r"\b(sulfur|sulphur)\b", q):
            expansions.update({"sulphur", "sulfur deficiency", "low organic matter", "sandy soil", "leaching", "rainfall", "tissue test", "field pattern", "nitrogen"})
            guidance = "For suspected sulfur deficiency, explicitly check sandy or low-organic-matter soil, recent rainfall or leaching, field pattern, tissue or soil test, and nitrogen or other deficiency before a sulfur recommendation. Do not drift into unrelated chlorosis or disease explanations."
        if has(r"\b(rain|rainfall|heavy rain|wet soil|saturated|leach|leaching|side[- ]?dress|sidedress)\b", q):
            expansions.update({"rainfall", "soil moisture", "wet soil", "nitrate leaching", "crop stage"})
            guidance = (
                guidance
                if guidance != "Answer directly. Use field caveats briefly when needed."
                else "For nitrogen decisions after rain, check crop stage, recent rainfall, soil moisture or trafficability, nitrate or leaching risk, credits, and local calibration before adding N."
            )
        else:
            guidance = guidance if guidance != "Answer directly. Use field caveats briefly when needed." else "Prioritize nutrient diagnostics and local calibration. Do not drift into unrelated chlorosis or disease explanations unless the prompt supplies that evidence."

    if has(
        r"\b(salinity|sodicity|irrigat\w*|drainage|tile|wet spots?|compaction|traffic|"
        r"trafficability|driv(?:e|ing) (?:equipment|machinery|tractor)|enter(?:ing)? (?:the )?field|"
        r"cover crops?|erosion|runoff|water quality|leaching|dryland|restrictive layers?|hardpan|"
        r"plow pan|ponding|shallow roots?)\b",
        q,
    ) or has(_OPERATIONAL_TRAFFICABILITY_PATTERN, q):
        namespaces.update({"soil_water", "soil_health", "fertility"})
        if has(r"\b(wind|rain|forecast|spray)\b", q):
            required_tools.add("weather_guard")
        if qtype == "conceptual":
            qtype = "soil_water"
            guidance = "Frame the answer as a soil-water diagnostic workflow with measurements and management tradeoffs."
        else:
            guidance += " Include soil-water loss, drainage, or runoff context where it changes the recommendation."
        expansions.update({"soil texture", "water table", "drainage", "infiltration", "runoff", "leaching"})
        if has(r"\b(wet spots?|delayed planting|drainage changes?|tile|outlet|ponding|water table)\b", q):
            qtype = "soil_water"
            required_tools.add("field_data_guard")
            expansions.update({"topography", "elevation", "low spots", "tile map", "outlet", "wetland regulation", "permeability"})
            guidance = "For persistent wet spots or drainage changes, ask for soil survey or map unit, topography or elevation, tile maps and outlets, water table or permeability, rainfall history, and wetland or drainage regulations before suggesting drainage changes."
        if has(r"\b(salinity|sodicity|saline|sodic|white crust|stunting|irrigation water)\b", q):
            required_tools.add("salinity_sodicity_guard")
            expansions.update({"electrical conductivity", "EC", "SAR", "ESP", "sodium", "irrigation water test", "soil test", "drainage", "leaching", "field pattern"})
            guidance = "For salinity or sodicity risk, ask for soil EC, irrigation-water test, sodium hazard as SAR or ESP, pH where relevant, drainage/leaching feasibility, and field pattern before treating symptoms as the cause."
        if has(
            r"\b(compaction|traffic|trafficability|driv(?:e|ing) (?:equipment|machinery|tractor)|"
            r"enter(?:ing)? (?:the )?field|restrictive layers?|hardpan|plow pan|ponding|"
            r"shallow roots?|rooting depth)\b",
            q,
        ) or has(_OPERATIONAL_TRAFFICABILITY_PATTERN, q):
            required_tools.add("soil_structure_guard")
            required_tools.add("field_data_guard")
            expansions.update({"compaction", "hardpan", "plow pan", "restrictive layer", "ponding", "infiltration", "rooting depth", "penetrometer", "probe", "soil pit", "traffic pattern", "soil moisture", "controlled traffic", "targeted tillage"})
            guidance = (
                "For field trafficability or compaction, do not infer a universal dry threshold. Verify standing "
                "water, ponding or infiltration, recent rain or irrigation, soil moisture below the surface, "
                "traffic pattern, rooting, and whether the intended equipment load would rut, smear, or compact "
                "the soil; delay and recheck when field condition is uncertain."
            )
            if not has(r"\b(product timing|spray near|spraying near|product label|specific product|tank mix|dicamba|volatile herbicide|fungicide pass|pesticide application)\b", q):
                namespaces.difference_update({"label_boundary", "product_stewardship"})
                required_tools.discard("label_guard")
                expansions.difference_update({"buffer", "jurisdiction", "label", "target pest", "wind"})
                risk = "medium"
                qtype = "soil_water"

    named_crop_health_product = has(_AAFC_CROP_HEALTH_PRODUCT_PATTERN, q)
    named_annual_crop_inventory = has(_AAFC_ANNUAL_CROP_INVENTORY_PATTERN, q)
    named_historical_crop_yield_slc = has(_AAFC_HISTORICAL_CROP_YIELD_SLC_PATTERN, q)
    named_canadian_context_product = has(_CANADIAN_REGIONAL_CONTEXT_PRODUCT_PATTERN, q)
    named_regional_product = (
        named_crop_health_product
        or named_annual_crop_inventory
        or named_historical_crop_yield_slc
        or named_canadian_context_product
    )
    if has(
        r"\b(mlra|major land resource|ecoregion|ecological site|regional (soil|climate|environment)|soil landscape|"
        r"physiograph|landform|soil zone|agroclimate|nasdi|standardized precipitation index|"
        r"standardized precipitation evapotranspiration index|spi|spei|difference from (?:normal|average) (?:temperature|precipitation))\b",
        q,
    ) or named_regional_product:
        namespaces.add("regional_environment")
        expansions.update({"MLRA", "ecoregion", "ecological site", "climate", "precipitation", "physiography", "landform", "soil landscape", "NASDI", "regional context"})
        if named_crop_health_product:
            expansions.update(_AAFC_CROP_HEALTH_EXPANSIONS)
        elif named_annual_crop_inventory:
            expansions.update(_AAFC_ANNUAL_CROP_INVENTORY_EXPANSIONS)
        elif named_historical_crop_yield_slc:
            expansions.update(_AAFC_HISTORICAL_CROP_YIELD_SLC_EXPANSIONS)
        elif named_canadian_context_product:
            expansions.update({"regional map context", "dataset scope", "not current field measurement", "field verification"})
            if has(r"\b(?:soileri|erosion|erision|eroshun)\b", q):
                expansions.update({"SoilERI", "wind water tillage erosion", "Soil Landscapes of Canada", "2021 modelled risk", "field-use limitations"})
        regional_context_request = (named_regional_product or has(
            r"\b(regional .*context|soil and climate context|mlra|major land resource|ecoregion|ecological site|"
            r"agroclimate|nasdi|standardized precipitation index|standardized precipitation evapotranspiration index|spi|spei)\b",
            q,
        )) and not has(
            r"\b(seed treatment|fungicide|insecticide|fertiliz|fertility|salinity|sodicity|irrigat\w*|"
            r"planting window|plant into|spray|product timing|variable[- ]rate|prescrib\w*|prescription)\b",
            q,
        )
        if qtype == "conceptual" or regional_context_request:
            qtype = "regional_context"
            knowledge_bucket = "regional_environment_context"
        if named_regional_product:
            product_boundary = (
                "Treat the named regional data product as context: explain its scope and interpretation, and do not "
                "use it as a current field measurement, grower record, current weather source, or prescription."
            )
            guidance = product_boundary if guidance == "Answer directly. Use field caveats briefly when needed." else f"{guidance} {product_boundary}"
        else:
            guidance = (
                guidance
                if guidance != "Answer directly. Use field caveats briefly when needed."
                else "Frame the answer with regional soil, climate, and landscape context before field-specific claims."
            )

    if has(r"\b(salinity|sodicity|saline|sodic)\b", q) and has(r"\b(evaluat|diagnos|risk)\b", q) and not has(
        r"\b(product timing|before product timing|spray near|spraying near|product label|specific product|tank mix|dicamba|volatile herbicide)\b",
        q,
    ) and not (
        has(r"\b(nitrogen|nitrate|fertiliz|fertility|rate|increase)\b", q)
        and has(r"\b(increase|change|changing|adjust|rate|apply|recommend)\b", q)
    ):
        namespaces.update({"soil_water", "soil_health", "fertility"})
        namespaces.difference_update({"label_boundary", "product_stewardship"})
        required_tools.discard("label_guard")
        required_tools.add("salinity_sodicity_guard")
        qtype = "soil_water"
        risk = "medium" if risk == "regulated" else risk
        expansions.difference_update({"buffer", "jurisdiction", "label", "target pest"})
        expansions.update({"electrical conductivity", "EC", "soil EC", "SAR", "ESP", "sodium", "irrigation water test", "water test", "soil test", "drainage", "leaching", "field pattern"})
        guidance = "For salinity or sodicity diagnosis, ignore incidental herbicide-window wording unless product timing is the ask. Lead with soil EC, irrigation-water test, sodium hazard as SAR or ESP, pH where relevant, drainage/leaching feasibility, and field pattern."
        if has(r"\b(cover crops?|dryland)\b", q):
            expansions.update({"termination timing", "planting window", "species mix", "soil moisture", "water use", "residue"})
            guidance = "Discuss dryland cover-crop tradeoffs explicitly: water use and soil moisture, erosion or residue benefits, species or mix, termination timing, and next-crop planting window."

    if has(r"\b(nitrogen|nitrate)\b", q) and has(r"\b(increase|change|changing|adjust|rate|apply|recommend)\b", q):
        namespaces.update({"fertility", "soil_water", "economics"})
        required_tools.add("fertility_guard")
        if has(r"\b(irrigation water nitrate|water nitrate|nitrogen credit|fertilizer credit|tile drainage|leaching|runoff|water quality)\b", q):
            required_tools.update({"nutrient_4r_guard", "field_data_guard"})
        qtype = "fertility_rate"
        risk = "medium" if risk == "low" else risk
        expansions.update(
            {
                "soil nitrate test",
                "nitrate test",
                "yield goal",
                "yield potential",
                "manure credits",
                "previous crop credits",
                "legume credits",
                "irrigation water nitrate",
                "water allocation",
                "split timing",
                "right source",
                "right rate",
                "right time",
                "right place",
                "crop uptake",
                "leaching",
                "soil moisture",
                "applied water",
                "flowmeter",
                "water nitrate test",
            }
        )
        guidance = (
            "For nitrogen rate changes under heat, irrigation, water-allocation, salinity, or leaching stress, keep the "
            "answer a nitrogen decision: check soil or nitrate test, yield goal or yield potential, manure, legume, "
            "previous-crop and irrigation-water credits, crop uptake timing, split timing, soil moisture, and loss risk "
            "before increasing N."
        )

    if has(r"\b(nitrate|nitrogen)\b", q) and has(r"\b(leach|leaching|loss|losses)\b", q):
        namespaces.update({"fertility", "soil_water", "soil_health"})
        required_tools.update({"fertility_guard", "nutrient_4r_guard"})
        qtype = "fertility_diagnostic" if qtype == "conceptual" else qtype
        risk = "medium" if risk == "low" else risk
        expansions.update(
            {
                "sandy soil",
                "heavy rain",
                "soil nitrate test",
                "yield goal",
                "crop uptake",
                "split timing",
                "sidedress",
                "cover crop",
                "cover crops",
                "nitrification inhibitor",
                "stabilizer",
                "irrigation scheduling",
                "root zone",
                "manure credits",
                "previous crop credits",
            }
        )
        guidance = (
            "For nitrate-leaching mitigation, discuss sandy soil or drainage risk, soil or nitrate testing, yield goal, "
            "credit accounting, split timing or sidedress close to crop uptake, cover crops where the rotation allows, "
            "irrigation scheduling or rainfall management, and nitrification inhibitor or stabilizer fit for the N source and timing."
        )

    if has(
        r"\b(edge[- ]of[- ]field|tile outlet|drainage ditch|saturated buffer|bioreactor|constructed wetland|controlled drainage|nitrate loss|water quality)\b",
        q,
    ) and has(r"\b(nitrate|nitrogen|nutrient|fertiliz|tile|drainage|runoff|leaching|outlet)\b", q):
        namespaces.update({"fertility", "soil_water", "soil_health", "regional_environment", "field_data_boundary"})
        required_tools.update({"fertility_guard", "nutrient_4r_guard", "field_data_guard", "weather_guard"})
        qtype = "soil_water" if qtype == "conceptual" else qtype
        risk = "medium" if risk == "low" else risk
        expansions.update(
            {
                "edge-of-field",
                "tile drainage",
                "tile outlet",
                "drainage ditch",
                "saturated buffer",
                "bioreactor",
                "constructed wetland",
                "controlled drainage",
                "site suitability",
                "soil",
                "slope",
                "outlet",
                "nutrient timing",
                "cover crop",
                "crop uptake",
                "maintenance",
                "monitoring",
                "NRCS",
            }
        )
        guidance = (
            "For edge-of-field nitrate practices, pair site suitability for the outlet, soil, slope, and drainage layout "
            "with 4R nutrient timing, cover crops or crop uptake, maintenance, monitoring, and local NRCS or conservation guidance."
        )

    if has(r"\b(yield maps?|variable[- ]rate|prescription|ndvi|as-applied|management zones?|georeference|records|precision)\b", q):
        namespaces.update({"precision_ag", "economics", "fertility", "field_data_boundary"})
        required_tools.add("field_data_guard")
        if has(r"\b(variable[- ]rate|prescription|soil zones?|yield maps?|weak zones?|management zones?|roi|economic|defensible|pay|partial budget)\b", q):
            required_tools.add("fertility_guard")
        expansions.update({"audit trail", "check strip", "partial budget", "validated layers", "zones"})
        if has(r"\b(compaction|traffic|restrictive layers?|hardpan|plow pan|ponding|shallow roots?|rooting depth)\b", q):
            qtype = "soil_water"
            expansions.update({"traffic pattern", "soil moisture", "rooting depth", "penetrometer", "soil pit"})
        elif has(r"\b(profit|spend|economic|defensible|roi)\b", q):
            qtype = "field_data"
            expansions.update({"yield response curve", "soil test zones", "crop price", "fertilizer cost", "partial budget", "ROI", "check strips", "trial"})
            guidance = "Evaluate economic defensibility with soil-test zones, yield response or response curves, crop price, fertilizer and application cost, partial budget or ROI, and check strips or trials."
        else:
            qtype = "field_data"
            guidance = "Separate raw field layers from a recommendation. Emphasize validation, economics, and audit trail."

    if has(r"\b(replant|stand|planting|hybrid|variety|white mold|harvest|storage|grain moisture|establishment)\b", q):
        namespaces.update({"crop_management", "plant_health", "economics"})
        expansions.update({"stand count", "growth stage", "field history", "yield potential", "economics"})
        if qtype not in {"product_label", "soil_water"}:
            qtype = "crop_management"
            guidance = "Answer as an applied crop-management checklist with decision variables, not a generic crop description."
        if has(r"\b(replant|uneven stand|stand)\b", q) and qtype not in {"product_label", "soil_water"}:
            expansions.update({"population", "uniformity", "gaps", "survival", "planting date", "calendar", "hybrid maturity", "yield potential", "economics"})
            guidance = "For replant decisions, explicitly cover stand count or population, uniformity or gaps, growth stage and survival, calendar or planting date, hybrid maturity, yield potential, and economics before recommending replant."
        if has(r"\b(white mold)\b", q) and qtype not in {"product_label", "soil_water"}:
            expansions.update({"variety tolerance", "variety ratings", "canopy", "row spacing", "population", "field history", "fungicide timing", "rotation"})
            guidance = "For white mold variety and management decisions, explicitly cover variety tolerance or ratings, field history, canopy density, row spacing, population, rotation, and fungicide timing or risk."
        if has(r"\b(hybrid|variety|varieties|selection|select)\b", q) and qtype not in {"product_label", "soil_water"}:
            expansions.update(
                {
                    "relative maturity",
                    "local multi-year trials",
                    "local trials",
                    "disease resistance",
                    "pest resistance",
                    "standability",
                    "lodging",
                    "drydown",
                    "field history",
                }
            )
            guidance = (
                "For hybrid or variety selection, lead with relative maturity, local multi-year trial performance, "
                "field fit, disease or pest resistance, standability or lodging risk, drydown, trait package, and field history."
            )

    if has(r"\b(harvest|storage|grain moisture|test weight|mycotoxin|standability)\b", q) and not has(
        r"\b(product timing|before product timing|spray near|spraying near|product label|specific product|tank mix|dicamba|volatile herbicide|fungicide pass)\b",
        q,
    ):
        namespaces.update({"crop_management", "plant_health", "economics", "soil_water"})
        namespaces.difference_update({"label_boundary", "product_stewardship"})
        required_tools.discard("label_guard")
        required_tools.update({"weather_guard", "field_data_guard"})
        expansions.difference_update({"buffer", "jurisdiction", "label", "target pest"})
        expansions.update({"grain moisture", "drying", "aeration", "test weight", "mold", "mycotoxin", "storage plan", "field loss", "standability", "weather forecast"})
        qtype = "crop_management"
        risk = "medium" if risk == "regulated" else risk
        guidance = (
            "For harvest and storage risk, ignore incidental spray-window wording unless product timing is the ask. "
            "Lead with grain moisture, drying or aeration, test weight or quality, mold or mycotoxin risk, storage plan, weather forecast, and field loss or standability."
        )

    canola_shatter_harvest = has(r"\bcanola\b", q) and has(
        r"\b(?:shatter|pod integrity|straight[- ]?cut|direct combin|swath)\w*\b",
        q,
    ) and has(r"\b(?:harvest|timing|loss)\w*\b", q)
    if canola_shatter_harvest:
        namespaces.update({"crop_management", "field_data_boundary", "soil_water"})
        namespaces.difference_update({"label_boundary", "product_stewardship"})
        required_tools.discard("label_guard")
        required_tools.update({"field_data_guard", "weather_guard"})
        expansions.difference_update({"cold chain", "field heat", "market requirement"})
        expansions.update(
            {
                "canola harvest",
                "pod shatter",
                "seed colour change",
                "seed moisture",
                "pod integrity",
                "shatter tolerance",
                "straight cutting",
                "direct combining",
                "swathing",
                "wind rain heat forecast",
                "header ground speed combine settings",
                "field loss checks",
            }
        )
        qtype = "crop_management"
        risk = "medium" if risk == "regulated" else risk
        guidance = (
            "For canola shatter-loss decisions, use representative seed colour and moisture, pod integrity and hybrid "
            "shatter tolerance, field maturity variation, wind/rain/heat risk, straight-cut versus swath fit, and "
            "header, ground-speed, combine-setting, and field-loss checks. Do not give one universal harvest date."
        )

    sample_handling_context = bool(
        has(r"\b(?:manure|soil|tissue|plant)\b", q)
        and has(r"\b(?:sample|sampling|lab|laboratory|nutrient plan|nutrient management)\b", q)
    )
    if (
        has(r"\b(postharvest|cooling|cold chain|field heat|handling|sanitation|storage temperature|market[- ]quality|decay|quality chain)\b", q)
        and not sample_handling_context
    ):
        namespaces.update({"crop_management", "plant_health", "soil_water", "field_data_boundary", "economics"})
        required_tools.update({"weather_guard", "field_data_guard"})
        expansions.update(
            {
                "postharvest",
                "cooling",
                "cold chain",
                "field heat",
                "time to cooling",
                "cooling method",
                "handling",
                "sanitation",
                "food safety",
                "storage temperature",
                "humidity",
                "aeration",
                "disease",
                "decay",
                "quality",
                "market quality",
                "local crop guide",
                "harvest temperature",
                "storage plan",
                "market requirement",
            }
        )
        qtype = "crop_management"
        risk = "medium" if risk == "low" else risk
        guidance = "For postharvest quality, connect field heat, time to cooling, handling and sanitation, storage temperature and humidity, disease or decay risk, weather, storage plan, and market quality requirements."

    if sample_handling_context:
        namespaces.update({"fertility", "field_data_boundary", "soil_water"})
        namespaces.difference_update({"plant_health", "label_boundary", "product_stewardship"})
        required_tools.discard("label_guard")
        required_tools.update({"fertility_guard", "field_data_guard"})
        expansions.difference_update(
            {
                "postharvest",
                "cold chain",
                "cooling method",
                "field heat",
                "market quality",
                "storage temperature",
                "time to cooling",
            }
        )
        expansions.update(
            {
                "manure analysis",
                "representative sample",
                "composite sample",
                "agitation",
                "sample handling",
                "sample preservation",
                "laboratory analysis",
                "nutrient transformation",
            }
        )
        qtype = "fertility_diagnostic"
        risk = "medium" if risk == "low" else risk
        guidance = (
            "For soil, plant, or manure sampling, lead with a representative sampling design, consistent timing and "
            "depth where applicable, mixing or agitation, clean containers, preservation and transport, laboratory "
            "method, and the field records needed before converting results into a nutrient credit or rate."
        )

    if has(r"\b(erosion|sloping|slope|runoff|rill|gully)\b", q) and has(
        r"\b(reduce|control|practices?|consider|management|residue|cover crops?|contour|strip|terrace|waterway|no[- ]?till|tillage)\b",
        q,
    ):
        namespaces.update({"soil_water", "soil_health", "crop_management"})
        namespaces.difference_update({"label_boundary", "product_stewardship"})
        required_tools.discard("label_guard")
        expansions.difference_update({"buffer", "jurisdiction", "label", "target pest"})
        expansions.update(
            {
                "erosion",
                "residue",
                "cover crop",
                "contour farming",
                "strip cropping",
                "terrace",
                "grassed waterway",
                "runoff",
                "slope",
                "tillage reduction",
                "no-till",
            }
        )
        qtype = "soil_water"
        risk = "medium" if risk == "regulated" else risk
        guidance = "For erosion-control questions, prioritize residue or cover crops, tillage reduction or no-till, contour or strip-cropping, terraces, grassed waterways, buffers, and stable runoff outlets matched to slope and soil."

    if has(r"\b(runoff|erosion|waterway|buffer|setback|grass(ed)? outlet|conservation plan|nrcs|residue|cover crops?)\b", q) and has(
        r"\b(recommendation|evidence|shape|plan|guidance|visible runoff|ditch|tile outlet|drainage)\b",
        q,
    ):
        namespaces.update({"soil_water", "soil_health", "crop_management", "regional_environment"})
        namespaces.difference_update({"label_boundary", "product_stewardship"})
        required_tools.discard("label_guard")
        required_tools.add("field_data_guard")
        expansions.difference_update({"buffer", "jurisdiction", "label", "target pest"})
        expansions.update(
            {
                "runoff",
                "erosion",
                "residue",
                "cover crop",
                "waterway",
                "grassed waterway",
                "buffer",
                "setback",
                "grass",
                "slope",
                "soil texture",
                "drainage",
                "NRCS",
                "conservation plan",
                "local guidance",
            }
        )
        qtype = "soil_water"
        risk = "medium" if risk == "low" else risk
        guidance = "For conservation planning, connect runoff or erosion to residue or cover, slope, soil texture, drainage, waterways, buffers, setbacks or grassed outlets, and NRCS conservation plan or local guidance."

    if has(r"\b(soil survey|nrcs|sda|map unit|component|hydrologic group|drainage class|hydric|field truth|ground truth)\b", q):
        namespaces.update({"soil_water", "soil_health", "regional_environment", "field_data_boundary"})
        required_tools.add("field_data_guard")
        expansions.update(
            {
                "soil survey",
                "NRCS",
                "SDA",
                "map unit",
                "component",
                "component percent",
                "drainage class",
                "hydrologic group",
                "hydric rating",
                "prior",
                "screening",
                "regional context",
                "soil test",
                "field observation",
                "ground truth",
                "restrictive layer",
                "not replacement",
            }
        )
        qtype = "soil_water" if qtype == "conceptual" else qtype
        guidance = "For soil-survey context, call NRCS map units and components a screening prior or regional context; ask for soil tests, field observations, soil pit or scouting, and do not treat the survey as exact field truth."

    if has(r"\b(nass|quick stats|regional statistics|yield statistics|acreage|production|county yield|state yield)\b", q):
        namespaces.update({"crop_management", "economics", "field_data_boundary"})
        required_tools.add("field_data_guard")
        expansions.update(
            {
                "USDA NASS",
                "Quick Stats",
                "regional statistics",
                "yield",
                "acreage",
                "production",
                "county",
                "state",
                "regional",
                "field records",
                "yield map",
                "grower records",
                "not field-specific",
                "prior",
            }
        )
        qtype = "field_data"
        guidance = "For NASS Quick Stats, frame yield, acreage, or production as county/state/regional context, not a field-specific prediction; ask for crop year, field yield history, yield maps, and grower records."

    if has(r"\b(cdl|cropland data layer|crop[- ]cover|crop cover|crop history|rotation|planting record|crop-insurance|acreage accounting)\b", q):
        namespaces.update({"crop_management", "field_data_boundary", "regional_environment"})
        required_tools.add("field_data_guard")
        if has(r"\b(weather|forecast|climate|rain|daymet|nasa power|soil, weather|weather, cdl)\b", q):
            required_tools.add("weather_guard")
        if has(r"\b(label|labels?|product|spray|herbicide|fungicide|insecticide|pesticide)\b", q):
            required_tools.add("label_guard")
        expansions.update(
            {
                "Cropland Data Layer",
                "CDL",
                "NASS",
                "boundary sample",
                "sample points",
                "crop-cover class",
                "multi-year",
                "recent years",
                "rotation",
                "grower record",
                "field history",
                "planting record",
                "prior",
                "screening",
                "not acreage",
                "not crop insurance",
                "not field truth",
            }
        )
        qtype = "field_data"
        guidance = "For CDL crop-history context, describe boundary samples or crop-cover classes as a public prior across recent years; ask for grower planting records and do not treat CDL as acreage accounting, crop-insurance evidence, or field truth."

    if has(r"\b(nematodes?|nematicide|sampling|rotation)\b", q) and has(
        r"\b(sample|sampling|field history|rotation|diagnostic|lab|threshold|first move|logical)\b", q
    ):
        namespaces.update({"plant_health", "field_data_boundary", "soil_water"})
        required_tools.add("field_data_guard")
        expansions.update(
            {
                "nematode",
                "sampling",
                "diagnostic lab",
                "sample quality",
                "field history",
                "crop rotation",
                "host crop",
                "soil texture",
                "patch pattern",
                "threshold",
                "local extension",
                "resistant variety",
            }
        )
        qtype = "field_data"
        guidance = "For nematode decisions, ask for representative soil or root samples, diagnostic lab result, field history, crop rotation, host crop, soil texture, patch pattern, thresholds where available, local extension guidance, and resistant-variety fit."

    if has(r"\b(forage|pasture|graze|grazing|hay|silage|livestock|cattle|prussic acid|hydrocyanic|sorghum|sudan|millet)\b", q) and has(
        r"\b(stress|drought|frost|regrowth|warm|wet|risk|test|feed|lab|withdrawal|safe)\b",
        q,
    ):
        namespaces.update({"crop_management", "plant_health", "soil_water"})
        required_tools.update({"weather_guard", "field_data_guard"})
        expansions.update(
            {
                "nitrate",
                "prussic acid",
                "hydrocyanic acid",
                "drought",
                "frost",
                "stress",
                "regrowth",
                "forage test",
                "lab test",
                "feed test",
                "species",
                "sorghum",
                "sudan",
                "millet",
                "grass",
                "legume",
                "grazing",
                "hay",
                "silage",
                "livestock safety",
                "withdrawal",
            }
        )
        qtype = "crop_management"
        risk = "medium" if risk == "low" else risk
        guidance = "For forage or pasture livestock safety, cover nitrate and prussic acid risk, drought/frost/stress/regrowth timing, forage species, forage/feed/lab testing, and grazing, hay, silage, livestock-safety, or withdrawal decisions."

    if has(r"\b(specialty crop|vegetable|tomato|irrigation|soil moisture|leaf wetness|humidity|market quality)\b", q) and has(
        r"\b(disease|scout|scouting|stage|irrigation|humidity|leaf wetness|label|extension)\b",
        q,
    ) and not (qtype.startswith("fertility") and has(r"\b(nitrate|nitrogen|fertiliz|nutrient credit|irrigation-water nitrogen credit)\b", q)):
        namespaces.update({"crop_management", "plant_health", "soil_water"})
        required_tools.add("weather_guard")
        expansions.update(
            {
                "soil moisture",
                "irrigation",
                "disease risk",
                "humidity",
                "leaf wetness",
                "field scouting",
                "crop stage",
                "local extension",
                "label",
                "market quality",
            }
        )
        qtype = "crop_management"
        risk = "medium" if risk == "low" else risk
        guidance = "For specialty-crop irrigation and disease questions, balance soil moisture or irrigation with humidity or leaf-wetness disease risk, field scouting, crop stage, local extension or label guidance, and market quality."

    if has(r"\b(produce safety|food safety|fsma|preharvest interval|worker safety|rei\b|phi\b|water test|water source|overhead|drip)\b", q):
        namespaces.update({"crop_management", "plant_health", "soil_water", "field_data_boundary"})
        required_tools.update({"weather_guard", "field_data_guard", "pesticide_safety_guard"})
        expansions.update(
            {
                "irrigation water test",
                "water quality",
                "produce safety",
                "food safety",
                "FSMA",
                "preharvest interval",
                "PHI",
                "worker safety",
                "REI",
                "irrigation method",
                "overhead",
                "drip",
                "disease risk",
                "leaf wetness",
                "local extension",
            }
        )
        qtype = "crop_management"
        risk = "medium" if risk == "low" else risk
        guidance = "For produce-safety water questions, check irrigation water source and test, irrigation method, disease and leaf-wetness risk, FSMA or market requirements, and PHI/REI or worker-safety boundaries where products are involved."

    if has(r"\b(aphid|weed|disease|leaf spot|gray leaf spot|mold|threshold|scout|insect|fungus|rust|blight|photo)\b", q):
        namespaces.add("plant_health")
        required_tools.add("field_data_guard")
        if has(r"\b(disease|leaf spot|gray leaf spot|mold|fungus|rust|blight|treatment|control)\b", q):
            required_tools.add("label_guard")
        if has(r"\b(fungicide|insecticide|herbicide|pesticide|spray|product|label|tank mix|application rate)\b", q):
            namespaces.update({"product_stewardship", "label_boundary"})
        if qtype == "conceptual":
            qtype = "plant_health"
        expansions.update({"scouting", "identification", "threshold", "growth stage", "field history"})
        if has(r"\b(fungicide|roi|price|retailer)\b", q):
            expansions.update({"disease severity", "scouting", "hybrid susceptibility", "growth stage", "weather", "yield potential", "economics", "label"})
            guidance = "For fungicide ROI decisions, explicitly cover disease severity or scouting, hybrid or variety susceptibility, growth stage, weather, yield potential or economics, and label fit. State that price alone is not enough."
        elif qtype == "plant_health":
            guidance = "Diagnose first. If identification or threshold data are missing, ask for them before treatment advice."

    if has(r"\b(insect|insects|aphid|threshold|scout|sampling|count|beneficial|natural enemies|insecticide justified)\b", q) and has(
        r"\b(insecticide|treatment|spray|justified|threshold|scout|count|crop stage)\b",
        q,
    ):
        namespaces.add("plant_health")
        required_tools.add("label_guard")
        expansions.update(
            {
                "scout",
                "count",
                "sampling",
                "pest species",
                "crop stage",
                "threshold",
                "economic threshold",
                "beneficial",
                "natural enemies",
                "current local label",
            }
        )
        if has(r"\b(insecticide|spray|product|label|application rate)\b", q):
            namespaces.update({"product_stewardship", "label_boundary"})
            risk = "regulated"
        if qtype == "conceptual":
            qtype = (
                "product_label"
                if has(r"\b(insecticide|spray|product|label|application rate)\b", q)
                else "plant_health"
            )
        guidance = "For insect IPM decisions, ask for pest species, scouting or sampling count, crop stage, economic threshold, beneficials or natural enemies, and current label before treatment."

    if has(r"\b(resistance|resistant|escapes?|same herbicide|mode of action|site of action)\b", q):
        namespaces.update({"plant_health", "product_stewardship", "label_boundary"})
        qtype = "product_label"
        risk = "regulated"
        required_tools.update({"label_guard", "resistance_management_guard"})
        expansions.update({"mode of action", "site of action", "weed species", "field history", "scout escapes", "rotate", "multiple effective", "nonchemical", "crop rotation", "mechanical control", "label"})
        guidance = "For resistance management, identify the pest or weed and field history, scout escapes, verify the label, rotate or mix multiple effective modes/sites of action, and include nonchemical tactics."

    if has(r"\b(preemergence|pre-emergence|residual activation|residual herbicide|activation|incorporation)\b", q) and has(
        r"\b(herbicide|weeds?|waterhemp|control failure|rain|rainfall|stormy|soil restriction|weed size|emerg\w*)\b",
        q,
    ):
        namespaces.update({"plant_health", "product_stewardship", "label_boundary", "field_data_boundary", "soil_water"})
        required_tools.update({"label_guard", "weather_guard", "field_data_guard"})
        qtype = "product_label"
        risk = "regulated"
        expansions.update(
            {
                "preemergence",
                "residual activation",
                "rainfall",
                "activation",
                "incorporation",
                "label",
                "rate",
                "soil restriction",
                "soil texture",
                "organic matter",
                "pH",
                "weed species",
                "emergence timing",
                "weed size",
                "scouting",
                "escapes",
                "resistance management",
            }
        )
        guidance = "For preemergence residual performance, check label rate and soil restrictions, rainfall or incorporation after application, weed species and emergence timing, weed size, soil texture, organic matter, pH, scouting, escapes, and resistance management before judging failure."

    if has(r"\b(regulated pest|invasive pest|quarantine|movement boundary|do not move)\b", q):
        namespaces.update({"plant_health", "product_stewardship", "label_boundary", "field_data_boundary"})
        required_tools.update({"field_data_guard", "label_guard", "pesticide_safety_guard"})
        qtype = "product_label" if has(r"\b(treatment|label|spray|pesticide)\b", q) else "field_data"
        risk = "regulated"
        expansions.update(
            {
                "identify",
                "diagnostic confirmation",
                "sample",
                "regulated pest",
                "invasive",
                "quarantine",
                "local extension",
                "state agency",
                "movement boundary",
                "do not move material",
                "sanitation",
                "label",
                "treatment only after confirmation",
            }
        )
        guidance = "For suspected regulated or invasive pests, do not diagnose from description alone. Ask for photos or a sample, confirm jurisdiction and host, involve local extension or the state/provincial agency, avoid moving material, and keep treatment label-bound after confirmation."

    if has(r"\b(trait package|technology trait|refuge|stewardship|herbicide tolerance|pest resistance)\b", q):
        namespaces.update({"crop_management", "plant_health", "product_stewardship", "label_boundary", "field_data_boundary"})
        required_tools.update({"label_guard", "field_data_guard", "pesticide_safety_guard"})
        risk = "regulated"
        expansions.update(
            {
                "trait package",
                "technology trait",
                "refuge",
                "stewardship",
                "label",
                "disease rating",
                "pest resistance",
                "herbicide tolerance",
                "local trials",
                "multi-year",
                "environment fit",
                "field history",
                "market requirement",
            }
        )
        guidance = "For trait-package selection, check refuge and stewardship requirements, current trait or label terms, disease and pest ratings, herbicide tolerance fit, local multi-year trials, field history, environment fit, and market requirements."

    if has(r"\b(drift|off-target movement|spray record|application record|recordkeeping|worker safety|pollinator|bee advisory|bloom|water protection|sensitive area|sensitive crop|refuge|stewardship)\b", q):
        namespaces.update({"product_stewardship", "label_boundary", "plant_health", "field_data_boundary"})
        required_tools.add("pesticide_safety_guard")
        if has(r"\b(spray|herbicide|fungicide|insecticide|pesticide|product|label|treatment|trait|refuge)\b", q):
            required_tools.add("label_guard")
            risk = "regulated"
        if has(r"\b(drift|wind|gust|inversion|weather|spray window|bloom)\b", q):
            required_tools.add("weather_guard")
        if has(r"\b(record|symptom|field edge|diagnostic|sample|pollinator|habitat|water|tile outlet|drainage ditch|sensitive area)\b", q):
            required_tools.add("field_data_guard")
        expansions.update(
            {
                "drift",
                "off-target movement",
                "wind direction",
                "gust",
                "inversion",
                "spray record",
                "application record",
                "timestamp",
                "symptom pattern",
                "field edge",
                "diagnostic sample",
                "PPE",
                "REI",
                "PHI",
                "reporting",
                "pollinator",
                "buffer",
                "setback",
            }
        )
        guidance = "For pesticide drift, safety, or stewardship questions, keep label, wind and inversion, buffer or setback, recordkeeping, symptom pattern, diagnostic sample, PPE/REI/PHI, reporting, and sensitive-area boundaries visible."

    if has(r"\b(seed treatment|seed treatments|seedcorn maggot|bean leaf beetle|wireworm|grub)\b", q):
        namespaces.update({"plant_health", "product_stewardship", "label_boundary"})
        qtype = "seed_treatment"
        risk = "regulated"
        required_tools.update({"label_guard", "field_data_guard"})
        expansions.difference_update({"buffer", "wind", "wind speed", "wind direction", "gust", "downwind", "sensitive crop", "drift", "delay", "do not spray"})
        expansions.update({"seed treatment", "insecticide seed treatment", "early planting", "soil temperature", "cool wet soils", "pest history", "field history", "planting conditions", "pest pressure", "seedcorn maggot", "bean leaf beetle", "wireworm", "grub", "threshold", "risk"})
        guidance = "Frame seed-treatment need as risk-based, not automatic. Explicitly ask for field history, planting conditions, and pest pressure; cover planting date, soil temperature or cool-wet soils, residue or manure history, target pest risk, threshold where available, and label fit."

    if has(r"\b(seed quality|germination|vigor|vigour|seed lot|seedling vigor)\b", q):
        namespaces.update({"crop_management", "plant_health", "field_data_boundary"})
        required_tools.add("field_data_guard")
        if has(r"\b(weather|cold|cool|wet|heat|stress|planting conditions|storage)\b", q):
            required_tools.add("weather_guard")
        expansions.update(
            {
                "seed quality",
                "germination",
                "vigor",
                "seed lot",
                "lab germination",
                "seedling vigor",
                "storage history",
                "planting conditions",
                "soil temperature",
                "soil moisture",
                "stand count",
                "field history",
                "local trials",
            }
        )
        qtype = "crop_management" if qtype == "conceptual" else qtype
        guidance = "For seed quality and vigor questions, separate lab germination and seed-lot history from planting conditions, soil temperature, soil moisture, stand count, field history, storage history, and local trial performance."

    if has(r"\b(exam|review|certified crop adviser|cca|explain|checklist|why|factors)\b", q):
        namespaces.add("exam_review")
        style = "exam_review"
        if qtype == "conceptual":
            qtype = "exam_review"
            guidance = "Answer directly as a study or checklist response, then add field caveats briefly."

    if has(r"\b(planting window|plant into|supporting the planting|before supporting the planting|crop establishment)\b", q):
        namespaces.update({"crop_management", "soil_water", "economics"})
        qtype = "crop_management"
        if not has(
            r"\b(product timing|before product timing|spray near|spraying near|product label|specific product|tank mix|dicamba|volatile herbicide|pesticide application|fungicide pass)\b",
            q,
        ):
            namespaces.difference_update({"label_boundary", "product_stewardship"})
            required_tools.discard("label_guard")
            expansions.difference_update({"buffer", "jurisdiction", "label", "target pest"})
            risk = "medium" if risk == "regulated" else risk
        required_tools.add("weather_guard")
        expansions.update({"soil temperature", "soil moisture", "seedbed", "sidewall compaction", "forecast", "emergence", "stand"})
        guidance = "For planting-window decisions, keep the answer about crop establishment: soil temperature, soil moisture, seedbed condition, sidewall compaction risk, short forecast, and emergence or stand risk."

    if has(r"\b(cover crops?|dryland)\b", q) and has(r"\b(tradeoffs?|water use|soil moisture|stored water|evapotranspiration|termination|planting window)\b", q):
        namespaces.update({"soil_water", "soil_health", "crop_management"})
        namespaces.difference_update({"label_boundary", "product_stewardship", "plant_health"})
        required_tools.discard("label_guard")
        expansions.difference_update({"buffer", "jurisdiction", "label", "target pest"})
        qtype = "soil_water"
        risk = "medium" if risk == "low" else risk
        expansions.difference_update(
            {
                "aeration",
                "drying",
                "field loss",
                "grain moisture",
                "mold",
                "mycotoxin",
                "standability",
                "storage plan",
                "test weight",
            }
        )
        expansions.update(
            {
                "cover crop",
                "stored water",
                "termination timing",
                "termination method",
                "planting window",
                "species mix",
                "soil moisture",
                "water use",
                "residue",
                "erosion",
                "crop rotation",
                "rainfall outlook",
            }
        )
        guidance = "Discuss cover-crop water tradeoffs explicitly: water use and soil moisture, erosion or residue benefits, species or mix, termination timing, and next-crop planting window."

    if has(r"\b(fungicide|fungicide pass)\b", q) and has(r"\b(roi|return|price|retailer|justified|economics|yield response)\b", q):
        namespaces.update({"plant_health", "product_stewardship", "label_boundary", "economics"})
        qtype = "product_label"
        risk = "regulated"
        required_tools.add("label_guard")
        expansions.update({"disease severity", "scouting", "hybrid susceptibility", "variety susceptibility", "growth stage", "weather", "yield potential", "economics", "label"})
        guidance = "For fungicide ROI decisions, explicitly cover disease severity or scouting, hybrid or variety susceptibility, growth stage, weather, yield potential or economics, and label fit. State that price alone is not enough."

    if has(r"\b(no soil test|no tissue test|phone description|yellow corn|yellowing)\b", q):
        expansions.update({"field pattern", "soil test", "tissue test", "photos", "scouting", "not enough to diagnose"})
        guidance = "For phone-only nutrient or crop-stress descriptions, say the information is not enough to diagnose, ask for field pattern, photos or scouting details, and request soil or tissue tests before recommending treatment."

    if has(
        r"\b(what (?:the )?agent checked|list what (?:it|the agent) checked|source cards?|sources checked|provenance|trace|public priors?|public context|public tools?|not configured|unavailable|adapter|cached)\b",
        q,
    ):
        namespaces.update({"field_data_boundary", "regional_environment", "soil_water"})
        required_tools.add("field_data_guard")
        if has(r"\b(weather|forecast|climate|rain|et|openet|daymet|nasa power|water|adapter|unavailable|not configured|cached|source status|timeout|failed)\b", q):
            required_tools.add("weather_guard")
        if has(r"\b(labels?|product|pesticide|herbicide|fungicide|insecticide|spray|ppls|epa)\b", q):
            required_tools.add("label_guard")
            risk = "regulated"
        expansions.update(
            {
                "source card",
                "provenance",
                "trace",
                "checked source",
                "not checked",
                "unavailable",
                "not configured",
                "cache timestamp",
                "field boundary",
                "public prior",
                "soil survey",
                "weather context",
                "label metadata",
            }
        )
        qtype = "field_data"
        guidance = (
            "For source-card or provenance questions, state what was checked, what was unavailable or not configured, "
            "source status and timestamp/query context, and what public sources cannot prove about field truth, diagnosis, exact rates, or labels."
        )

    if has(r"\b(shapefile|geojson|geopackage|uploaded boundary|drawn boundary|field boundary|geometry|polygon|self[- ]intersect|shifted|coordinate|projection|crs)\b", q):
        namespaces.update({"field_data_boundary", "regional_environment", "soil_water"})
        required_tools.add("field_data_guard")
        expansions.update(
            {
                "CRS",
                "projection",
                "coordinate order",
                "geometry validity",
                "self-intersection",
                "area sanity check",
                "boundary confirmation",
                "coordinate shift",
                "selected feature",
                "regional intersection",
                "not legal boundary",
            }
        )
        qtype = "field_data"
        guidance = (
            "For uploaded or drawn boundaries, check CRS/projection, coordinate order, geometry validity, selected feature, "
            "area sanity, possible coordinate shift, and user confirmation before using regional intersections as public priors."
        )

    if has(
        r"\b(exact rate|field-specific rate|exact (?:irrigation )?(?:depth|timing|schedule|date|interval)|"
        r"private data|public priors?|public map|public source|without private)\b",
        q,
    ):
        namespaces.update({"field_data_boundary", "fertility", "soil_water"})
        required_tools.add("field_data_guard")
        if has(r"\b(rate|fertil|nutrient|nitrogen|phosphorus|potassium|lime)\b", q):
            required_tools.add("fertility_guard")
        if has(r"\b(label|product|spray|herbicide|fungicide|insecticide|pesticide)\b", q):
            required_tools.add("label_guard")
            risk = "regulated"
        expansions.update(
            {
                "private field evidence",
                "soil test",
                "yield goal",
                "growth stage",
                "field history",
                "grower records",
                "label",
                "jurisdiction",
                "public prior",
                "not field truth",
            }
        )
        qtype = "field_data" if qtype == "conceptual" else qtype
        risk = "medium" if risk == "low" else risk
        guidance = (
            "For exact-rate or private-data boundary questions, refuse exact field-specific prescriptions from public priors alone, "
            "ask for missing private field evidence, and keep the answer as decision support rather than legal label interpretation."
        )

    if has(r"\b(fertigation|fertilizer source|volatilization|nutrient balance|tissue[- ]test|fertility|soil[- ]test)\b", q):
        namespaces.update({"fertility", "soil_water"})
        required_tools.add("fertility_guard")
        if has(r"\b(fertigation|water quality|ec\b|leaching|irrigation|crop stage|field scouting|weak transplants?)\b", q):
            required_tools.update({"weather_guard", "field_data_guard"})
        expansions.update({"soil test", "tissue test", "crop stage", "nutrient balance", "water quality", "leaching", "placement", "timing"})

    if has(
        r"\b(new practice|practice will pay|will pay|payback|partial budget|roi|net return|sensitivity|uncertainty|cost-share|program eligibility|public programs?|implementation cost|operating cost|added cost|reduced cost|added return|reduced return)\b",
        q,
    ) and has(r"\b(pay|pays|profit|roi|net return|partial budget|cost|return|sensitivity|uncertainty|program|eligibility)\b", q):
        namespaces.update({"economics", "precision_ag", "fertility", "field_data_boundary"})
        required_tools.update({"field_data_guard", "fertility_guard"})
        expansions.update(
            {
                "partial budget",
                "ROI",
                "net return",
                "added cost",
                "reduced cost",
                "added return",
                "reduced return",
                "yield response",
                "risk reduction",
                "sensitivity",
                "range",
                "uncertainty",
                "field records",
                "baseline",
                "check strip",
                "trial",
                "cost-share",
                "program eligibility",
            }
        )
        qtype = "field_data"
        guidance = (
            "For practice economics, do not guarantee payback. Present a partial budget with added and reduced costs, "
            "added and reduced returns, yield response or risk reduction, baseline field records, check strips or trials, "
            "and sensitivity to prices, weather, adoption cost, incentives, and time horizon."
        )

    if has(r"\b(wet spring|warm forecast|humid|humidity|leaf wetness|forecast|climate normals?|historical gridded|gridded weather|rain|rainfall|frost|heat|storage|mycotoxin|drying|harvest|spray decision|leaching risk|irrigation|water quality|poorly drained|delayed)\b", q):
        required_tools.add("weather_guard")

    if has(r"\b(beneficial insects?|natural enemies|pest species|pest history|pest pressure|field scouting|scouting count|sampling count|economic threshold|unknown weeds?|weed identification|weed control|visual symptoms|field symptoms?|diagnosis|sample vs visual|phone photo|leaf spotting|confirmed disease|patchy chlorosis|stand loss|field history|herbicide history|carryover|rotation restrictions?|preemergence|residual activation|activation|planting conditions|weak transplants?|transplant quality|yield monitor|on-farm trial|trial design|field records|grower records|yield history|yield maps?|remote imagery|weak zones?|public variety trials?|plot result|standability|seed quality|germination|vigor|soil sampling|sampling design|sampling timing|tissue testing|old soil tests?|field measurement|surface condition|infiltration|public adapter|adapter times out|live data|climate normals?|historical gridded|field truth|ground truth|flooding duration)\b", q):
        namespaces.add("field_data_boundary")
        required_tools.add("field_data_guard")
        expansions.update({"field records", "scouting", "field history", "ground truth", "audit trail"})

    if has(r"\b(conservation or precision practice|conservation practice|precision practice)\b", q) and has(
        r"\b(pay|pays|profit|roi|economics|books|partial budget|defensible)\b",
        q,
    ):
        namespaces.update({"economics", "precision_ag", "fertility", "field_data_boundary"})
        required_tools.update({"field_data_guard", "fertility_guard"})
        expansions.update({"partial budget", "farm records", "yield response", "soil tests", "cost-share", "check strips"})
        qtype = "field_data"
        guidance = (
            "For conservation or precision-practice economics, avoid pretending to know the farm books. "
            "Use a partial budget with field records, soil tests or yield response, cost-share, risk reduction, and check strips where possible."
        )

    if has(
        r"\b(draws? a field|map context|soil context|weather context|label context|"
        r"mapped capability|capability intersection|regional intersection|polygon intersection)\b",
        q,
    ):
        namespaces.update({"field_data_boundary", "regional_environment", "soil_water"})
        required_tools.add("field_data_guard")
        if qtype == "conceptual":
            qtype = "field_data"
        if has(r"\b(weather context|weather|forecast|rain|climate)\b", q):
            required_tools.add("weather_guard")
        if has(r"\b(label context|labels?|product|spray|pesticide|herbicide|fungicide|insecticide)\b", q):
            required_tools.add("label_guard")
            risk = "regulated"
        expansions.update(
            {
                "map context",
                "soil context",
                "weather context",
                "label context",
                "field boundary",
                "source card",
                "not field truth",
                "field evidence",
            }
        )
        guidance = (
            "State what the mapped intersection supports, what it cannot prove, and the few field observations, "
            "samples, records, and current authorities needed before a crop or input decision."
        )

    if has(r"\b(label metadata|ppls|epa registration|epa reg|product metadata|current label controls|product disambiguation|partial product name)\b", q):
        namespaces.update({"product_stewardship", "label_boundary"})
        required_tools.add("label_guard")
        risk = "regulated"
        qtype = "product_label"
        expansions.update({"EPA registration number", "full product name", "active ingredient", "current label", "jurisdiction", "crop/site"})
        guidance = (
            "For EPA PPLS or product metadata, ask for exact product identity and EPA registration number, separate candidate metadata from label interpretation, "
            "and state that the current local label controls."
        )

    if is_map_component_explanation_question(question):
        namespaces = {"regional_environment", "field_data_boundary", "soil_health"}
        required_tools = {"field_data_guard"}
        expansions = {"soil map", "map unit", "soil component", "representative profile", "mapping scale"}
        qtype = "field_data"
        risk = "low"
        guidance = (
            "Explain only the mapped component attributes supplied by the source. Distinguish a composite map unit "
            "from a point sample, name missing profile attributes explicitly, and do not add a management prescription "
            "unless the user asks for one."
        )

    if has(r"\b(farmer|grower)\b", q):
        audience = "farmer"
        style = "plain"
    elif has(r"\b(trainee|adviser|advisor|agronomist|certified)\b", q):
        audience = "crop_adviser"
    else:
        audience = "farmer"

    if not namespaces:
        namespaces.update({"crop_management", "soil_health", "exam_review"})

    qtype = _resolve_primary_question_type(q, qtype)
    benign_conceptual_explanation = _is_benign_conceptual_explanation(question)
    if _is_named_product_permission_request(question):
        qtype = "product_label"
        namespaces.update({"plant_health", "product_stewardship", "label_boundary"})
        required_tools.add("label_guard")
        risk = "regulated"
    elif benign_conceptual_explanation:
        qtype = "exam_review"
        namespaces.difference_update(
            {"plant_health", "product_stewardship", "label_boundary", "field_data_boundary"}
        )
        namespaces.update({"crop_management", "exam_review"})
        required_tools.clear()
        risk = "low"
        style = "exam_review"
        guidance = (
            "Explain the agronomy practice or mechanism directly. Distinguish the general concept from a "
            "field diagnosis or prescription without requesting case-specific evidence the user did not need."
        )
    elif qtype == "product_label":
        namespaces.update({"plant_health", "product_stewardship", "label_boundary"})
        required_tools.add("label_guard")
        risk = "regulated"
    elif qtype == "seed_treatment":
        namespaces.update({"plant_health", "crop_management", "product_stewardship", "label_boundary"})
        required_tools.update({"label_guard", "field_data_guard"})
        risk = "regulated"
    elif qtype == "field_data":
        namespaces.update({"field_data_boundary", "crop_management"})
        required_tools.add("field_data_guard")
        if has(_FIELD_HISTORY_REFERENCE_PATTERN, q):
            expansions.update({"stored field record", "current observation", "soil moisture", "trafficability", "drainage"})
            guidance = (
                "Use the integrity-checked field record as bounded user-supplied evidence. "
                "State what it supports, what must be checked now, and what current observation or measurement changes the decision."
            )

    return QueryRoute(
        question_type=qtype,
        risk_level=risk,
        namespaces=tuple(sorted(namespaces)),
        required_tools=tuple(sorted(required_tools)),
        answer_style=style,
        audience=audience,
        query_expansion=tuple(sorted(expansions)),
        guidance=guidance,
        knowledge_bucket=knowledge_bucket,
        knowledge_domains=tuple(sorted(_infer_knowledge_domains(q, namespaces))),
    )


def refine_query_route(question: str, route: QueryRoute) -> QueryRoute:
    """Build the compact route consumed by retrieval and answer generation.

    `classify_query` gathers broad safety signals for compatibility with older
    traces. This second pass removes incidental domains and keeps only the
    evidence lanes that can answer the user's final request.
    """

    q = _routing_text(question)
    focus = request_focus(q)
    benign_conceptual_explanation = _is_benign_conceptual_explanation(question)
    qtype = route.question_type
    namespaces: set[str] = set()
    tools: set[str] = set()
    expansions: set[str] = set()
    risk = "low"
    guidance = "Answer the named agronomic question directly and use only evidence that fits it."

    product_focus = qtype == "product_label" or has(
        r"\b(spray|spraying|herbicide|fungicide|insecticide|pesticide|tank mix|product[- ]label|application rate)\b",
        focus,
    )
    field_specific = has(r"\b(field|grower|farm|boundary|map|soil test|scout|crop stage)\b", q)

    organic_nutrient_land_application = has(
        r"\b(?:digestate|manure|biosolids?|organic nutrient)\b",
        q,
    ) and has(r"\b(?:land[- ]application|land application|apply to land|nutrient rules?|official scope)\b", q)
    if organic_nutrient_land_application:
        # "Application" here means applying an organic nutrient to land, not
        # applying a pesticide.  The lexical product route previously sent
        # these questions into label/PPE/REI handling.
        qtype = "fertility_diagnostic"
        product_focus = False

    if qtype.startswith("fertility"):
        namespaces.update({"fertility", "soil_water", "soil_health"})
        tools.add("fertility_guard")
        risk = "medium"
        if organic_nutrient_land_application:
            risk = "regulated"
        sulfur_differential = has(r"\bcanola\b", q) and has(r"\bsulfur\b", q) and has(r"\bnitrogen\b", q)
        expansions.update({"soil test method", "yield goal", "crop removal", "manure credits", "previous crop credits"})
        guidance = "Base nutrient changes on calibrated soil or tissue evidence, realistic yield potential, and all nutrient credits; do not invent a rate."
        if field_specific:
            tools.add("field_data_guard")
        if has(r"\b(4r|right source|right rate|right time|right place|manure|nitrate|leaching|runoff|tile)\b", q):
            tools.add("nutrient_4r_guard")
            expansions.update({"right source", "right rate", "right time", "right place", "split timing", "placement", "water quality"})
        if has(r"\b(irrigation[- ]water nitrate|nitrate in irrigation water|water nitrate)\b", q):
            expansions.update({"irrigation water nitrate", "water nitrate test", "applied water", "crop uptake"})
        if has(r"\b(nitrate leaching|sandy soil|heavy rain)\b", q) and not sulfur_differential:
            expansions.update({"soil moisture", "crop uptake", "cover crop", "nitrification inhibitor", "stabilizer"})
        if has(r"\b(lime|low ph|buffer ph|aglime)\b", q):
            expansions.update({"buffer pH", "CCE", "ECCE", "neutralizing value", "target pH"})
        if has(r"\b(phosphorus|soil-test p|soil test reports phosphorus)\b", q):
            expansions.update({"Bray", "Olsen", "Mehlich", "avoid additional P"})
            guidance = "Treat phosphorus methods as calibration-specific; when high P and runoff risk are confirmed, do not apply P until local guidance supports the plan."
        if has(r"\b(potassium|soil[- ]test k|marginal k)\b", q):
            expansions.update({"soil-test K method", "local calibration", "CEC", "soil texture", "crop removal", "yield history", "placement"})
        if sulfur_differential:
            expansions.update(
                {
                    "sulfur deficiency",
                    "nitrogen deficiency",
                    "young leaves",
                    "older leaves",
                    "flowering",
                    "affected and normal samples",
                    "soil texture",
                    "rainfall",
                    "fertilizer history",
                }
            )
            guidance = (
                "Separate sulfur from nitrogen or root stress using symptom position, field pattern, crop stage, "
                "soil texture, rainfall, fertilizer history, and paired affected-versus-normal samples before changing a rate."
            )
        if has(r"\b(tissue[- ]test results?|tissue testing|plant analysis)\b", q):
            expansions.update({"sampling date", "growth stage", "plant part", "soil test", "soil pH", "sufficiency range", "critical level", "symptom pattern"})
            guidance = "Interpret tissue results with crop stage, sampled plant part, local sufficiency ranges, soil evidence, and field symptoms; do not convert a tissue value directly into a rate."
        if has(r"\b(no soil test|no tissue test|phone description|phone photo|yellow corn|yellowing)\b", q):
            expansions.update({"field pattern", "symptom pattern", "photos", "scouting", "soil test", "tissue test", "rainfall", "drainage", "root stress"})
            guidance = (
                "For a phone- or photo-only crop-stress report, state that the evidence is not enough to diagnose or choose treatment. "
                "Ask for field and symptom pattern, crop stage, roots, photos or scouting, rainfall and drainage, and representative soil or tissue tests."
            )
        if has(r"\b(pale|yellow(?:ing)?|chlorosis|stunt\w*|patchy|uneven|poor stand|stand loss)\b", q):
            namespaces.update({"plant_health", "crop_management", "field_data_boundary"})
            tools.add("field_data_guard")
            expansions.update(
                {
                    "sulfur deficiency",
                    "nitrogen deficiency",
                    "young leaves",
                    "older leaves",
                    "field pattern",
                    "stand count",
                    "crop stage",
                    "roots",
                    "wetness",
                    "drainage",
                    "compaction",
                    "fertilizer history",
                    "affected and normal samples",
                    "soil test",
                    "tissue test",
                }
            )
            crop_stress_guidance = (
                "Treat pale or patchy crop stress as a differential, not a nutrient prescription. Separate sulfur and nitrogen patterns "
                "from waterlogging, restricted roots, compaction, establishment, disease, and injury using crop stage, leaf position, "
                "field pattern, roots, fertilizer history, and paired affected-versus-normal samples before recommending treatment."
            )
            guidance = (
                f"{guidance} {crop_stress_guidance}"
                if has(r"\b(no soil test|no tissue test|phone description|phone photo)\b", q)
                else crop_stress_guidance
            )
        if has(r"\b(volatilization|fertilizer source)\b", q):
            expansions.update({"urea", "UAN", "ammonium", "surface application", "incorporation", "injection", "rainfall timing", "temperature", "residue", "stabilizer", "crop uptake"})
            guidance = "Compare nitrogen source and placement with actual incorporation, rainfall or irrigation timing, temperature, residue, crop uptake, and locally supported loss-reduction options."
        if has(r"\b(nitrogen|nitrate)\b", focus) and not sulfur_differential:
            guidance = "Treat this as a nitrogen decision: verify available N, yield potential, previous-crop and manure credits, moisture and loss risk before changing the rate."

    elif qtype == "integrated_management":
        namespaces.update({"fertility", "plant_health", "soil_water", "crop_management", "field_data_boundary"})
        tools.update({"fertility_guard", "field_data_guard", "weather_guard"})
        risk = "medium"
        expansions.update({"soil test", "yield goal", "scouting", "economic threshold", "crop stage", "drainage", "runoff", "field records", "audit trail", "rotation"})
        guidance = "Build one auditable recommendation that connects nutrient evidence, pest scouting and thresholds, soil-water loss risk, crop rotation, and field records."

    elif qtype == "exam_review":
        namespaces.update({"crop_management", "exam_review"})
        if benign_conceptual_explanation:
            expansions.update(
                {
                    "agronomic mechanism",
                    "benefits",
                    "limitations",
                    "conditions where the practice helps",
                }
            )
            if has(r"\b(?:disease|pathogen|pest)\b", q):
                expansions.update({"host range", "life cycle", "rotation diversity", "integrated management"})
            if has(r"\b(?:nutrient|nitrogen|phosphorus|potassium|sulphur|sulfur|fixation)\b", q):
                namespaces.update({"fertility", "soil_health"})
                expansions.update({"nutrient cycling", "soil process", "crop rotation"})
            guidance = (
                "Explain the agronomy practice or mechanism directly, including its main benefit and limitation. "
                "Keep the general explanation distinct from a field diagnosis or prescription."
            )
        else:
            namespaces.add("fertility")
            expansions.update({"macronutrient", "micronutrient", "mobile nutrient", "immobile nutrient", "deficiency symptoms", "soil test", "tissue test"})
            guidance = "Answer the agronomy concept directly, then connect it to field diagnosis without inventing a prescription."

    elif qtype == "soil_water":
        namespaces.update({"soil_water", "soil_health"})
        expansions.update({"soil moisture", "drainage", "infiltration", "field observation", "local measurement"})
        guidance = "Use soil and water context as a prior, then anchor the decision to local measurements and field condition."
        if field_specific:
            tools.add("field_data_guard")
        operational_trafficability = has(_OPERATIONAL_TRAFFICABILITY_PATTERN, focus)
        if operational_trafficability:
            risk = "medium"
            tools.update({"field_data_guard", "soil_structure_guard"})
            expansions.update(
                {
                    "standing water",
                    "ponding duration",
                    "recent rain",
                    "recent irrigation",
                    "soil moisture below surface",
                    "intended equipment load",
                    "rutting",
                    "smearing",
                    "compaction",
                    "affected and normal areas",
                }
            )
            guidance = (
                "Treat trafficability as a fresh field-condition and intended-load decision, not a universal dry "
                "threshold. Compare the affected area with a normal area; verify standing water, ponding and "
                "drainage, recent rain or irrigation, moisture below the surface, and whether the intended load "
                "would rut, smear, or compact the soil. Delay and recheck when those conditions are uncertain."
            )
        if has(r"\b(compaction|traffic|restrictive layer|hardpan|ponding|shallow roots?)\b", q):
            tools.add("soil_structure_guard")
            expansions.update({"traffic pattern", "penetrometer", "soil pit", "rooting depth", "ponding"})
        if has(r"\b(salinity|sodicity|saline|salty|sodic|white crust|soil[- ]?ec|sar|esp|gypsum)\b", q) or has(
            _FRENCH_SALINITY_SODICITY_PATTERN, q
        ):
            tools.add("salinity_sodicity_guard")
            expansions.update({"EC", "SAR", "ESP", "irrigation water test", "leaching", "drainage"})
            guidance = (
                "Separate salinity from sodicity using soil EC plus SAR or ESP and irrigation-water quality. "
                "Do not recommend gypsum from a map, wet appearance, or EC alone; confirm sodium hazard and drainage or leaching feasibility."
            )
        if has(r"\bcover crops?\b", focus):
            namespaces.add("crop_management")
            expansions.update({"water use", "stored soil moisture", "termination timing", "next-crop planting window", "residue", "erosion"})
        if has(r"\b(erosion|slop|runoff)\b", focus):
            expansions.update({"residue", "cover crop", "grassed waterway", "buffer", "no-till", "local conservation plan"})
        if has(r"\b(wet spots?|drainage change|tile drainage)\b", focus):
            expansions.update({"topography", "elevation", "tile map", "outlet", "water table"})
        if has(r"\b(irrigation|evapotranspiration|forecast|weather|rain|heat)\b", focus):
            tools.add("weather_guard")
            expansions.update({"evapotranspiration", "weather context", "soil water holding", "sensor", "probe"})
        if has(r"\b(climate normals?|historical gridded|gridded climate)\b", q):
            tools.add("weather_guard")
            expansions.update({"historical average", "gridded climate", "current forecast", "short-term outlook", "forecast probability", "field condition", "operation timing"})
            guidance = "Separate historical climate context from the current forecast and on-field conditions; normals do not predict an operation window."
        if has(r"\b(rainfall intensity|runoff risk|rainfast|incorporation windows?|application window)\b", q):
            tools.update({"weather_guard", "field_data_guard"})
            expansions.update({"forecast rainfall amount", "rainfall intensity", "storm", "slope", "runoff path", "water quality", "rainfast interval", "incorporation", "setback", "buffer"})
            if has(r"\b(pesticide|herbicide|fungicide|insecticide|rainfast|label)\b", q):
                tools.add("label_guard")
                risk = "regulated"
            guidance = "Separate the fertilizer and pesticide rules, verify rainfall intensity and runoff paths, and delay when label, incorporation, runoff, or water-quality conditions are not satisfied."

    elif qtype == "plant_health":
        namespaces.update({"plant_health", "crop_management", "field_data_boundary"})
        tools.add("field_data_guard")
        expansions.update({"identification", "scouting", "field pattern", "crop stage", "field history"})
        guidance = "Diagnose before treatment: identify the organism or disorder, describe severity and field pattern, and separate likely causes from a confirmed diagnosis."
        if has(r"\b(disease|pathogen|leaf spot|root rot|mold|rust|blight|fungicide)\b", q):
            expansions.update({"pathogen identification", "disease severity", "variety susceptibility", "leaf wetness", "diagnostic sample"})
        if has(r"\b(pest|aphids?|insects?|caterpillars?|defoliat\w*|rootworms?|silk clipping|threshold|beneficial|natural enemies)\b", q):
            expansions.update({"pest species", "sampling count", "life stage", "whole canopy defoliation", "crop stage", "economic threshold", "beneficial insects", "natural enemies"})
        if has(r"\b(?:nematodes?|nematicide)\b", q):
            expansions.update({"nematode", "nematicide", "field pattern", "field history", "sample timing", "representative soil sample", "root sample", "diagnostic lab", "species identification", "population density", "host crop", "nonhost rotation", "resistant variety"})
        if has(r"\b(weed|resistant|escapes?)\b", q):
            expansions.update({"weed identification", "escape mapping", "growth stage", "density", "field history"})
        if has(r"\b(herbicide drift|off[- ]target movement)\b", q):
            namespaces.update({"product_stewardship", "label_boundary", "soil_water"})
            tools.update({"label_guard", "weather_guard"})
            risk = "regulated"
            expansions.update({"spray record", "active ingredient", "mode of action", "wind direction", "gusts", "inversion", "symptom pattern", "field edge", "gradient", "photos", "diagnostic sample"})
            guidance = "Treat drift as one injury hypothesis: reconstruct the spray and weather record, map the symptom gradient, and separate disease, nutrient, and weather stress before assigning cause."
        if has(r"\b(treat|treatment|current label|label fit|fungicide|insecticide|pesticide|spray)\b", q):
            namespaces.update({"product_stewardship", "label_boundary"})
            tools.add("label_guard")
            risk = "regulated"
            expansions.update({"current local label", "jurisdiction", "crop", "target", "timing", "restrictions"})

    elif qtype == "product_label":
        namespaces.update({"plant_health", "product_stewardship", "label_boundary"})
        tools.add("label_guard")
        risk = "regulated"
        expansions.update({"current local label", "jurisdiction", "crop", "target pest", "application method"})
        guidance = "Keep the decision label-bound: identify the crop, target, product and jurisdiction, then verify the current local label before application advice."
        if field_specific:
            tools.add("field_data_guard")
        if has(r"\b(?:irrigation|water)\b[^.]{0,80}\b(?:mm|millimet(?:re|er)s?)\b", q) and has(
            r"\b(?:ml|millilit(?:re|er)s?|litres?|liters?|product)\b", q
        ):
            tools.add("field_data_guard")
            expansions.update({"irrigation depth", "treated area", "carrier volume", "product rate", "current local label", "system calibration"})
            guidance = (
                "Do not convert irrigation depth into product volume. Identify the exact product and label rate, treated area, "
                "carrier volume and calibrated application system before calculating any amount."
            )
        if has(r"\b(resistance|resistant|escapes?|same herbicide|mode of action|site of action)\b", focus):
            tools.add("resistance_management_guard")
            expansions.update({"mode of action", "site of action", "scout escapes", "crop rotation", "nonchemical control"})
        if has(r"\b(?:waterhemp|pigweed|ryegrass|weed)\b", q) and has(
            r"\b(?:escape\w*|surviv\w*|seed set|seedbank|burndown|resistan\w*)\b", q
        ):
            tools.add("resistance_management_guard")
            expansions.update(
                {
                    "weed identity",
                    "growth stage",
                    "map escapes",
                    "prevent seed return",
                    "application failure",
                    "herbicide history",
                    "effective residual",
                    "multiple effective sites of action",
                    "crop competition",
                    "nonchemical control",
                }
            )
            guidance = "Prevent seed return, diagnose resistance versus application failure, and build a label-compliant integrated plan for the next crop cycle."
        residual_activation = has(r"\b(?:pre[- ]?emergence|residual)\b", q) and has(
            r"\b(?:activation|almost no rain|no rain|incorporat\w*|emerg\w*|repeat|higher rate)\b", q
        )
        if has(r"\b(spray|spraying|wind|drift|volatile|dicamba|sensitive|downwind|rain|forecast|weather|spray window)\b", q) and not residual_activation:
            tools.add("weather_guard")
            expansions.update({"wind speed", "wind direction", "gusts", "drift", "buffer", "inversion", "rainfastness"})
            guidance = "Use a do-not-spray or delay boundary until the current label, wind, gusts, inversion, downwind sensitivity, buffers and rain timing are verified."
        if residual_activation:
            namespaces.update({"soil_water", "field_data_boundary"})
            tools.update({"weather_guard", "field_data_guard"})
            expansions.update(
                {
                    "preemergence",
                    "residual activation",
                    "rainfall",
                    "incorporation",
                    "label",
                    "rate",
                    "maximum seasonal rate",
                    "soil restriction",
                    "soil texture",
                    "organic matter",
                    "pH",
                    "weed species",
                    "emergence timing",
                    "weed size",
                    "scouting",
                    "overlapping residual",
                }
            )
            guidance = (
                "Separate failure to activate the original residual from control of weeds that have already emerged. "
                "Check rainfall or incorporation, soil and label restrictions, emergence timing, and seasonal limits before choosing a labeled follow-up."
            )
        if has(r"\bvolunteer canola\b", q):
            tools.add("resistance_management_guard")
            expansions.update(
                {
                    "herbicide-tolerance system",
                    "previous crop records",
                    "seed records",
                    "volunteer stage",
                    "volunteer density",
                    "crop stage",
                    "crop safety",
                    "prevent seed return",
                    "integrated weed management",
                }
            )
            guidance = (
                "Do not infer the volunteer canola tolerance system from appearance. Recover prior records, verify the current crop label, "
                "and choose an integrated plan that fits crop stage, volunteer stage, density, and seed-return risk."
            )
        if has(r"\b(health|safety|ppe|rei|phi|restricted entry|preharvest|worker safety|pollinator|water quality)\b", q):
            tools.add("pesticide_safety_guard")
            expansions.update({"PPE", "REI", "PHI", "worker safety", "pollinator", "records"})

    elif qtype == "seed_treatment":
        namespaces.update({"plant_health", "crop_management", "product_stewardship", "label_boundary"})
        tools.update({"label_guard", "field_data_guard"})
        risk = "regulated"
        expansions.update({"seed treatment", "pest pressure", "field history", "soil temperature", "planting date", "threshold"})
        guidance = "Base seed-treatment need on planting conditions, pest pressure and field history; verify the current label without turning weather wording into a spray-drift decision."

    elif qtype == "crop_management":
        namespaces.add("crop_management")
        expansions.update({"field history", "local adaptation", "crop stage"})
        guidance = "Frame the management choice around local adaptation, field history, crop stage, and the evidence that would change the choice."
        canola_shatter_harvest = has(r"\bcanola\b", q) and has(
            r"\b(?:shatter|pod integrity|straight[- ]?cut|direct combin|swath)\w*\b",
            q,
        ) and has(r"\b(?:harvest|timing|loss)\w*\b", q)
        if canola_shatter_harvest:
            namespaces.update({"field_data_boundary", "soil_water"})
            tools.update({"field_data_guard", "weather_guard"})
            expansions.update(
                {
                    "canola harvest",
                    "pod shatter",
                    "seed colour change",
                    "seed moisture",
                    "pod integrity",
                    "shatter tolerance",
                    "straight cutting",
                    "direct combining",
                    "swathing",
                    "wind rain heat forecast",
                    "header ground speed combine settings",
                    "field loss checks",
                }
            )
            guidance = (
                "For canola shatter-loss decisions, use representative seed colour and moisture, pod integrity and "
                "hybrid shatter tolerance, field maturity variation, wind/rain/heat risk, straight-cut versus swath "
                "fit, and header, ground-speed, combine-setting, and field-loss checks. Do not give one universal date."
            )
        if has(r"\b(boundary|map|layer|yield map|as-applied|prescription|field data|public data|source card|geometry)\b", focus):
            namespaces.add("field_data_boundary")
            tools.add("field_data_guard")
        if has(r"\b(variety|hybrid|cultivar|public trials?|seed or variety|genetics)\b", q):
            namespaces.update({"plant_health", "economics"})
            expansions.update({"local multi-year trials", "relative maturity", "disease ratings", "standability", "lodging", "yield stability"})
            if has(r"\bsilage\b", q):
                expansions.update(
                    {
                        "silage trials",
                        "whole-plant yield",
                        "harvest moisture",
                        "starch",
                        "fiber digestibility",
                        "kernel processing",
                        "stay-green",
                        "ration",
                        "storage system",
                    }
                )
                guidance = (
                    "Do not project a grain-trial winner directly into silage use. Compare replicated local silage trials, "
                    "whole-plant yield and moisture, feed quality, harvest fit, ration, storage system, and downside cost."
                )
        if has(r"\b(poor fruit set|poor kernel set|fruit set)\b", q):
            namespaces.update({"plant_health", "soil_water", "fertility"})
            tools.update({"weather_guard", "field_data_guard"})
            expansions.update({"bloom timing", "flowering", "pollination", "pollinator activity", "temperature during bloom", "soil moisture", "tissue test", "disease scouting", "crop-specific extension"})
            guidance = "Build a crop-specific reproductive-set differential spanning pollination biology, bloom weather, water status, nutrition, and disease; do not assume one cause."
        if has(r"\b(seed lots?|seed quality|germination|germ test|vigor|cold test|accelerated aging)\b", q):
            expansions.update({"germination percentage", "vigor test", "seed lot", "soil temperature", "planting date", "seedbed", "stand establishment", "replant risk"})
            guidance = "Use lot-specific germination and vigor evidence with planting conditions to estimate stand-establishment risk; do not invent a seeding-rate adjustment."
        if has(r"\b(trait packages?|technology traits?|trait stewardship|refuge)\b", q):
            namespaces.update({"plant_health", "product_stewardship", "label_boundary", "field_data_boundary"})
            tools.update({"label_guard", "field_data_guard", "pesticide_safety_guard"})
            risk = "regulated"
            expansions.update({"trait package", "refuge", "trait stewardship", "disease rating", "pest resistance", "herbicide tolerance", "local multi-year trials", "field history", "market requirement"})
            guidance = "Compare trait fit beyond yield and preserve current refuge, label, and stewardship requirements."
        if has(r"\b(specialty|vegetable|produce)\b", q) and has(r"\b(irrigat\w*|water quality|water test)\b", q):
            namespaces.update({"soil_water", "plant_health", "field_data_boundary"})
            tools.update({"weather_guard", "field_data_guard", "pesticide_safety_guard"})
            expansions.update({"water source", "irrigation water test", "irrigation method", "produce safety", "food safety", "leaf wetness", "disease risk", "local extension", "crop-specific guidance"})
        if has(r"\b(planting window|plant into|establishment)\b", focus):
            namespaces.add("soil_water")
            tools.add("weather_guard")
            expansions.update({"soil temperature", "soil moisture", "seedbed condition", "emergence", "short forecast"})
        if has(r"\b(harvest|storage|cooling|market quality)\b", focus):
            expansions.update({"grain moisture", "storage plan", "drying", "aeration", "field heat", "cold chain", "market requirement"})
            tools.add("weather_guard")
        specialty_domains = sum(
            bool(has(pattern, focus))
            for pattern in (r"\birrigation\b", r"\bfertility\b", r"\b(pest|disease)\b", r"\bfood safety\b")
        )
        if has(r"\b(specialty crop|lettuce|vegetable)\b", focus) or specialty_domains >= 3:
            namespaces.update({"soil_water", "fertility", "plant_health"})
            tools.add("fertility_guard")
            if has(r"\b(irrigation|weather|forecast|evapotranspiration|humidity|leaf wetness)\b", focus):
                tools.add("weather_guard")
            expansions.update({"soil moisture", "irrigation", "nutrient balance", "scouting", "food safety", "market quality", "local extension"})
            risk = "medium"
            if has(r"\b(label|preharvest interval|restricted entry|worker safety)\b", focus):
                tools.update({"label_guard", "pesticide_safety_guard"})

    elif qtype == "field_data":
        namespaces.add("field_data_boundary")
        tools.add("field_data_guard")
        expansions.update({"field observation", "ground truth", "audit trail"})
        guidance = "State what the public or uploaded data can support, what it cannot prove, and which field evidence is needed before management changes."
        sampling_method_comparison = all(
            has(pattern, q)
            for pattern in (r"\brandom composite\b", r"\bbenchmark\b", r"\bdirected\b", r"\bgrid\b")
        ) and has(r"\b(?:soil sampl|nutrient zones?|variable[- ]rate)\b", q)
        if sampling_method_comparison:
            namespaces.update({"fertility", "precision_ag"})
            tools.add("fertility_guard")
            expansions.update(
                {
                    "sampling objective",
                    "random composite whole-field average",
                    "benchmark repeat location",
                    "directed management zones",
                    "grid spatial mapping",
                    "consistent depth timing laboratory method",
                    "ground truth zones",
                    "local calibration",
                }
            )
            guidance = (
                "Choose the soil-sampling design from the decision objective and spatial pattern: random composite "
                "for a whole-field average, benchmark for repeated tracking of a representative location, directed "
                "sampling for known stable zones, and grid sampling for dense spatial mapping. Keep depth, timing, "
                "georeferencing and laboratory method consistent, then ground-truth zones before setting rates."
            )
        if has(r"\b(?:map|mapped|mapping|polygon|layer|land suitability|capability)\b", q) and (
            has(r"\bwhich crop\b|\bwhat crop\b|\bcrop (?:choice|selection)\b", q)
            or has(r"\b(?:choose|select)\w*\b[^.?]{0,40}\bcrop\b", q)
            or has(r"\bplant\b[^.?]{0,20}\bnext (?:year|season)\b", q)
        ):
            namespaces.update({"regional_environment", "crop_management", "economics"})
            expansions.update({"land suitability", "crop rotation", "market class", "field history", "drainage", "soil test", "local trials", "economics"})
            guidance = (
                "Use the mapped suitability or capability class only to screen constraints. Choose a crop from rotation, "
                "field history, current soil and drainage evidence, local adaptation, market fit and economics; the map does not choose the crop."
            )
        if has(r"\b(soil survey|soil map|map unit|component|public soil|regional intersection)\b", q):
            namespaces.update({"soil_water", "soil_health", "regional_environment"})
            expansions.update({"soil survey", "map unit", "component", "prior", "screening", "not field truth", "soil test"})
        if has(r"\b(shapefile|geojson|geopackage|geometry|polygon|crs|projection|coordinate)\b", q):
            expansions.update({"CRS", "projection", "coordinate order", "geometry validity", "boundary confirmation", "coordinate shift"})
        if has(r"\b(source cards?|sources? checked|provenance|adapter|not configured|unavailable)\b", q):
            expansions.update({"source card", "not checked", "cache timestamp", "source status"})
        if not sampling_method_comparison and has(
            r"\b(yield maps?|as-applied records?|variable-rate|prescription layers?)\b",
            q,
        ):
            namespaces.update({"precision_ag", "fertility", "economics"})
            tools.add("fertility_guard")
            expansions.update({"yield map", "as-applied records", "calibration", "field data", "ground truth", "check strip", "audit trail"})
            guidance = "Treat yield maps and as-applied records as evidence only after calibration, cleanup, alignment, ground truth and an auditable check-strip design."
            if has(r"\bP\s*(?:and|&)\s*K\b", question):
                expansions.update(
                    {
                        "phosphorus",
                        "potassium",
                        "P and K",
                        "soil-test method",
                        "local calibration",
                        "response probability",
                        "fertilizer cost",
                        "partial budget",
                    }
                )
                guidance = (
                    "For variable-rate P and K, clean and calibrate the spatial layers, ground-truth stable zones, "
                    "use method-specific soil tests and local response calibration, then test economics with check strips and a partial budget."
                )
        if has(r"\b(weather|forecast)\b", focus):
            tools.add("weather_guard")
        if all(has(pattern, q) for pattern in (r"\bmap\b", r"\bsoil\b", r"\bweather\b", r"\blabel\b")):
            tools.update({"weather_guard", "label_guard"})
            risk = "regulated"
        if has(
            r"\b(?:label|product[- ]label|exact product|spray|pesticide|herbicide|fungicide|insecticide)\b",
            focus,
        ):
            tools.add("label_guard")
            risk = "regulated"
        if has(
            r"\b(exact rate|field-specific rate|exact (?:irrigation )?(?:depth|timing|schedule|date|interval)|"
            r"public priors?|without private)\b",
            q,
        ):
            namespaces.update({"fertility", "soil_water"})
            tools.add("field_data_guard")
            if has(r"\b(exact rate|field-specific rate|fertil|nutrient|nitrogen|phosphorus|potassium|lime)\b", q):
                tools.add("fertility_guard")
            risk = "medium" if risk == "low" else risk
            expansions.update({"private field evidence", "not field truth", "soil test", "yield goal"})
            guidance = "Refuse exact field-specific prescriptions from public priors alone and ask for the private field evidence needed to support the decision."
        if has(r"\b(pay|payback|partial budget|roi|net return|cost|sensitivity)\b", focus):
            namespaces.update({"economics", "precision_ag"})
            tools.add("fertility_guard")
            expansions.update({"partial budget", "sensitivity", "check strip", "field records", "yield response"})
            guidance = "Do not guarantee payback; use a partial budget, field records, check strips and sensitivity to prices, costs and response."

    if qtype == "soil_water" and has(
        r"\bexact (?:irrigation )?(?:depth|timing|schedule|date|interval)\b",
        q,
    ):
        tools.add("field_data_guard")
        risk = "medium" if risk == "low" else risk
        expansions.update({"root-zone measurement", "field-calibrated water balance", "irrigation system capacity"})
        guidance = (
            "Refuse exact irrigation depth or timing from a regional or public value alone; require current root-zone, "
            "crop, soil, weather, applied-water, and irrigation-system evidence."
        )

    if product_focus and qtype == "plant_health":
        namespaces.update({"product_stewardship", "label_boundary"})
        tools.add("label_guard")
        risk = "regulated"
        expansions.update({"current local label", "jurisdiction", "crop", "target pest"})
    if has(r"\b(regulated|invasive|quarantine|movement boundary)\b", q):
        namespaces.update({"plant_health", "field_data_boundary"})
        tools.update({"field_data_guard", "label_guard", "pesticide_safety_guard"})
        expansions.update({"quarantine", "movement boundary", "reporting", "diagnostic confirmation"})
        risk = "regulated"
    if has(r"\b(refuge|trait stewardship|trait package)\b", q):
        namespaces.update({"crop_management", "plant_health", "label_boundary"})
        tools.update({"field_data_guard", "label_guard", "pesticide_safety_guard"})
        expansions.update({"refuge", "local trials", "trait stewardship", "market restrictions"})
        risk = "regulated"

    named_crop_health_product = has(_AAFC_CROP_HEALTH_PRODUCT_PATTERN, q)
    named_annual_crop_inventory = has(_AAFC_ANNUAL_CROP_INVENTORY_PATTERN, q)
    named_historical_crop_yield_slc = has(_AAFC_HISTORICAL_CROP_YIELD_SLC_PATTERN, q)
    named_canadian_context_product = has(_CANADIAN_REGIONAL_CONTEXT_PRODUCT_PATTERN, q)
    named_regional_product = (
        named_crop_health_product
        or named_annual_crop_inventory
        or named_historical_crop_yield_slc
        or named_canadian_context_product
    )
    if has(
        r"\b(mlra|major land resource|ecoregion|ecodistrict|ecological site|soil survey|soil map|map unit|"
        r"soil landscapes?|soil[- ]landscape|soil components?|landform components?|regional soil and climate|"
        r"agroclimate|nasdi|standardized precipitation index|standardized precipitation evapotranspiration index|"
        r"spi|spei|difference from (?:normal|average) (?:temperature|precipitation))\b",
        q,
    ) or named_regional_product:
        namespaces.add("regional_environment")
        expansions.update({"MLRA", "climate", "soil", "regional context", "NASDI", "precipitation", "temperature"})
        if named_crop_health_product:
            expansions.update(_AAFC_CROP_HEALTH_EXPANSIONS)
            product_boundary = (
                "Treat the named AAFC crop-health layer as modelled regional context; it cannot replace field "
                "measurements, scouting, or current decision authorities."
            )
            guidance = f"{guidance} {product_boundary}"
        elif named_annual_crop_inventory:
            expansions.update(_AAFC_ANNUAL_CROP_INVENTORY_EXPANSIONS)
            guidance = (
                f"{guidance} Treat the named AAFC Annual Crop Inventory layer as a modelled crop-classification "
                "prior; it is not a grower planting record or complete field history."
            )
        elif named_historical_crop_yield_slc:
            expansions.update(_AAFC_HISTORICAL_CROP_YIELD_SLC_EXPANSIONS)
            guidance = (
                f"{guidance} Treat the named AAFC historical-yield-by-SLC value as a regional historical estimate "
                "with crop- and region-dependent provenance, not measured field yield, yield potential, or a forecast."
            )
        elif named_canadian_context_product:
            expansions.update({"regional map context", "dataset scope", "not current field measurement", "field verification"})
            if has(r"\b(?:soileri|erosion|erision|eroshun)\b", q):
                expansions.update({"SoilERI", "wind water tillage erosion", "Soil Landscapes of Canada", "2021 modelled risk", "field-use limitations"})
            guidance = (
                f"{guidance} Treat the named Canadian regional data product as bounded context, not as current field "
                "measurement, current weather, or a management prescription."
            )
    if has(r"\b(soil survey|soil map|map unit|soil landscapes?|soil[- ]landscape|soil components?|landform components?)\b", q):
        expansions.update(
            {
                "component location",
                "map scale",
                "not field truth",
                "screening prior",
                "within-polygon variability",
            }
        )

    # Reconcile the final decision object after broad retrieval signals have
    # been collected. These rules keep diagnosis ahead of treatment and make
    # missing-evidence guards consistent across unfamiliar question formats.
    diagnosis_first = has(
        r"\b(?:is it|confirm|diagnos|not sure what|drift or|tank injury|"
        r"swollen roots?|yellow[- ]orange stripes?|rapidly expanding .*lesions?|"
        r"dying .*roots?|twisted after spraying|stand can recover)\b|\bclubroot\?",
        q,
    )
    explicit_product_identity = has(
        r"\b(?:registration number|pcp number|active ingredient|full product name|exact product)\b",
        q,
    )
    current_weather_evidence = not has(r"\bafter wet planting\b", q) and (has(
        r"\b(?:after|following|forecast|today|tomorrow|tonight|last night|several|was|is|were)\b"
        r".{0,50}\b(?:rain|wet|humid|humidity|cold|freeze|frost|wind|weather)\w*\b",
        q,
    ) or has(
        r"\b(?:rain|wet|humid|humidity|cold|freeze|frost|wind|weather)\w*\b"
        r".{0,50}\b(?:after|following|forecast|today|tomorrow|tonight|last night)\b",
        q,
    ) or has(r"\b(?:had|experienced)\b.{0,30}\b(?:freeze|frost)\w*\b", q))
    if diagnosis_first and not explicit_product_identity:
        qtype = "plant_health"
        namespaces.update({"plant_health", "field_data_boundary"})
        namespaces.difference_update({"label_boundary", "product_stewardship"})
        tools.discard("label_guard")
        tools.add("field_data_guard")
        if current_weather_evidence:
            tools.add("weather_guard")
        if has(r"\b(?:spray|treat|apply|application|fungicide|herbicide|insecticide|pesticide)\w*\b", focus):
            # Diagnosis remains the primary task, but a treatment request still
            # crosses a regulated decision boundary.  Dropping the label and
            # pesticide guards here made diagnostic routing look safer than the
            # actual user request.
            namespaces.update({"label_boundary", "product_stewardship"})
            tools.update({"label_guard", "pesticide_safety_guard"})
            risk = "regulated"
        guidance = (
            "Diagnose from representative symptoms, field pattern, crop stage, roots, weather and history before "
            "moving to a product decision. Do not confirm the named cause from the description alone."
        )

    nutrient_symptom_rate_request = has(r"\b(?:yellow|pale)\w*\b", q) and has(
        r"\b(?:nitrogen|\bN\b|pounds?|rate)\b", question
    )
    if nutrient_symptom_rate_request and has(r"\b(?:no tests?|without .*test|cold|wet|strips?|patch)\w*\b", q):
        qtype = "fertility_diagnostic"
        namespaces.update({"fertility", "soil_water", "field_data_boundary"})
        tools.update({"fertility_guard", "field_data_guard"})
        guidance = "Treat colour and patch pattern as a nutrient differential, not as enough evidence to set a rate."

    ambiguous_rate_followup = has(r"\b(?:same rate|go at the same rate)\b", q) and has(
        r"\b(?:after (?:the )?rain|spray|insecticide|herbicide|fungicide|pesticide)\b", q
    )
    if ambiguous_rate_followup:
        qtype = "product_label"
        namespaces.update({"plant_health", "product_stewardship", "label_boundary", "field_data_boundary"})
        tools.update({"label_guard", "field_data_guard", "pesticide_safety_guard", "weather_guard"})
        risk = "regulated"
        guidance = "Ask for the missing product, target, prior application and rain timing; do not infer a rate from absent conversation history."

    named_product_prescription = has(
        r"\b(?:exact fungicide|fungicide timing|exact irrigation|irrigation depth|"
        r"prescrib\w*|product label|spray rate|fertilizer rate|nitrogen rate|safe for spray\w*|spray\w* today)\b",
        q,
    )
    explicit_regulated_product_route = qtype == "product_label" and has(
        r"\b(?:herbicide|fungicide|insecticide|pesticide|spray|tank mix|product label|"
        r"pmra|application permission|apply|application)\b",
        q,
    )
    operational_biological_decision = (
        qtype == "crop_management"
        and has(r"\b(?:choose|select|order|plant|harvest|store|manage|switch|replant)\w*\b", focus)
    ) or (
        qtype == "plant_health"
        and has(
            r"\b(?:diagnos\w*|identify\w*|confirm\w*|scout\w*|sampl\w*|treat\w*|spray\w*|manag\w*|"
            r"what should (?:i|we)|what do (?:i|we))\b",
            focus,
        )
    ) or (
        qtype == "soil_water"
        and has(
            r"\b(?:irrigat\w*|drain\w*|apply\w*|spread\w*|amend\w*|treat\w*|reclaim\w*|manag\w*|"
            r"what should (?:i|we)|what do (?:i|we))\b",
            focus,
        )
    )
    protected_decision_route = explicit_regulated_product_route or qtype in {
        "fertility_rate",
        "fertility_diagnostic",
    } or operational_biological_decision
    if named_regional_product and protected_decision_route:
        namespaces.add("field_data_boundary")
        tools.add("field_data_guard")
    if named_regional_product and not named_product_prescription and not protected_decision_route:
        qtype = "regional_context"
        namespaces.update({"regional_environment", "field_data_boundary"})
        tools.add("field_data_guard")
        guidance = (
            "Explain the named regional product as bounded context and require current field evidence before diagnosing "
            "a crop condition, treating a classification as field history, using historical data as current weather, "
            "or changing management."
        )

    if qtype.startswith("fertility"):
        tools.add("fertility_guard")
        if field_specific or has(r"\b(?:sample|block|strip|patch|point|boundary|map)\b", q):
            tools.add("field_data_guard")
        if has(r"\b(?:rate|pounds?|apply|application|pass|sidedress|starter|rescue|broadcast|banded?)\b", q):
            tools.add("nutrient_4r_guard")
        if has(r"\b(?:rain|wet|waterlog|drought|dry|weather|forecast|cold)\w*\b", q):
            tools.add("weather_guard")
    elif qtype == "product_label":
        namespaces.update({"plant_health", "product_stewardship", "label_boundary", "field_data_boundary"})
        tools.update({"label_guard", "field_data_guard", "pesticide_safety_guard"})
        risk = "regulated"
        if has(r"\b(?:rain|wet|weather|forecast|wind|today|tomorrow|afternoon)\w*\b", q):
            tools.add("weather_guard")
        resistance_decision = has(
            r"\b(?:resistan|surviv|escape|same (?:herbicide|mode|group))\w*\b",
            focus,
        ) or (
            has(r"\b(?:kochia|escape|surviv)\w*\b", q)
            and has(r"\b(?:herbicide|spray|rate|use)\w*\b", focus)
        )
        if resistance_decision:
            tools.add("resistance_management_guard")
    elif qtype == "plant_health":
        namespaces.update({"plant_health", "field_data_boundary"})
        tools.add("field_data_guard")
        if current_weather_evidence:
            tools.add("weather_guard")
        if has(r"\b(?:spray|treat|apply|application|fungicide|herbicide|insecticide|pesticide)\w*\b", focus):
            namespaces.update({"label_boundary", "product_stewardship"})
            tools.update({"label_guard", "pesticide_safety_guard"})
            risk = "regulated"
    elif qtype == "soil_water":
        tools.add("field_data_guard")
        if has(r"\b(?:erosion|tillage|compaction|soil structure|restrictive layer)\w*\b", q):
            tools.add("soil_structure_guard")
    elif qtype == "crop_management" and has(
        r"\b(?:calculat|target stand|germination|thousand[- ]kernel|missing|replant|seeding rate)\w*\b",
        q,
    ):
        tools.add("field_data_guard")

    # The public interface is bilingual.  The English intent anchors above
    # select the shared policy; this final pass preserves the few interface
    # distinctions that French syntax otherwise obscures (for example, a map
    # boundary question versus a salinity diagnosis).
    original = question.lower()
    french_question = bool(
        re.search(
            r"\b(?:est-ce que|puis-je|dois-je|comment|pourquoi|combien|champ|carte|"
            r"atlas|chaux|l[eé]gumes?|conseiller|pommes? de terre|ma[iï]s|soya|bleuets?|"
            r"qu[eé]bec|nouveau-brunswick)\b",
            original,
        )
    )
    if french_question:
        if has(r"\b(?:carte|tableau|atlas|polygone)\b", original) and has(
            r"\b(?:prouve|tout mon champ|suffisant)\b", original
        ) and not has(r"\bchaux\b", original):
            qtype = "field_data"
            namespaces.update({"field_data_boundary", "soil_water", "soil_health", "regional_environment"})
            tools.update({"field_data_guard", "soil_structure_guard"})
            tools.discard("salinity_sodicity_guard")
            guidance = (
                "Treat the map or atlas as regional screening context, not proof of one soil across the field; "
                "ground-truth components, drainage and current field condition before management changes."
            )
        if has(r"\bchaux\b", original) and has(r"\b(?:calculer|combien|suffisant)\b", original):
            qtype = "fertility_rate"
            namespaces.update({"fertility", "soil_water", "soil_health", "field_data_boundary"})
            tools.update({"fertility_guard", "field_data_guard", "soil_structure_guard"})
            tools.discard("salinity_sodicity_guard")
            risk = "medium"
            guidance = (
                "Do not calculate lime from an atlas. Require current laboratory pH and lime requirement, sampling "
                "depth and method, crop and rotation, field variability, and current local calibration."
            )
        if has(r"\b(?:fongicide|insecticide|herbicide|pesticide|traitement)\b", original):
            tools.update({"field_data_guard", "label_guard", "pesticide_safety_guard"})
            risk = "regulated"
            if has(r"\b(?:l[eé]sions?|maladie|diagnostic)\b", original):
                qtype = "plant_health"
            else:
                qtype = "product_label"
            if has(r"\b(?:d[eé]pister|carte|l[eé]sions?|traitement)\b", original):
                tools.add("weather_guard")
            if has(r"\b(?:fongicide|dose)\b", original):
                tools.add("resistance_management_guard")
        if has(r"\b(?:jaunit|jaunissement)\b", original) and has(r"\b(?:azote|\bN\b|combien)\b", question):
            qtype = "fertility_diagnostic"
            namespaces.update({"fertility", "soil_water", "field_data_boundary", "plant_health"})
            tools.update({"fertility_guard", "field_data_guard", "nutrient_4r_guard", "weather_guard"})
            risk = "medium"
        if has(r"\b(?:vari[eé]t[eé]|mieux class[eé]e)\b", original):
            qtype = "crop_management"
            namespaces.update({"crop_management", "field_data_boundary"})
            tools.add("field_data_guard")
        if has(r"\b(?:irriguer|irrigation|humidit[eé] du sol)\b", original):
            qtype = "soil_water"
            namespaces.update({"soil_water", "field_data_boundary"})
            tools.update({"field_data_guard", "weather_guard"})
            tools.discard("salinity_sodicity_guard")
        if has(r"\b(?:res[eè]me|ressemer|replanter)\b", original):
            qtype = "field_data"
            namespaces.update({"field_data_boundary", "crop_management", "regional_environment"})
            tools.update({"field_data_guard", "weather_guard"})
        if has(r"\b(?:pommes? de terre)\b", original) and has(
            r"\b(?:ventile|ventiler|meurtrissures?|peau fragile|encore chaudes?)\b", original
        ):
            qtype = "crop_management"
            namespaces.update({"crop_management", "field_data_boundary"})
            tools.update({"field_data_guard", "weather_guard"})
        if has(r"\b(?:pommes? de terre)\b", original) and has(r"\b(?:planter|praticable)\b", original):
            qtype = "crop_management"
            namespaces.update({"crop_management", "soil_water", "field_data_boundary"})
            tools.update({"field_data_guard", "weather_guard"})
            tools.discard("soil_structure_guard")
        if has(r"\bnasdi\b", original) and has(r"\b(?:reporter|d[eé]cision|v[eé]rifier)\b", original):
            tools.update({"field_data_guard", "weather_guard"})

    knowledge_bucket = (
        "regional_environment_context"
        if qtype == "regional_context" or (qtype == "soil_water" and "regional_environment" in namespaces)
        else "farmer_knowledge"
    )
    return _repair_interface_route(question, QueryRoute(
        question_type=qtype,
        risk_level=risk,
        namespaces=tuple(sorted(namespaces or {"crop_management", "soil_health"})),
        required_tools=tuple(sorted(tools)),
        answer_style=route.answer_style,
        audience=route.audience,
        query_expansion=tuple(sorted(expansions)),
        guidance=guidance,
        knowledge_bucket=knowledge_bucket,
        knowledge_domains=tuple(sorted(_infer_knowledge_domains(q, namespaces))),
    ))
