from __future__ import annotations

from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.evidence_handshake import (
    build_evidence_handshake,
    evidence_grounded_fallback,
    filter_decision_distractors,
    rerank_evidence_docs,
)
from agronomy_agent.decision_contract import build_decision_contract
from agronomy_agent.router import classify_query


def _doc(
    doc_id: str,
    title: str,
    text: str,
    *,
    tags: tuple[str, ...],
    score: float = 0.4,
    source_type: str = "applied_guidance",
) -> RetrievedDoc:
    return RetrievedDoc(
        doc_id=doc_id,
        title=title,
        text=text,
        source="University Extension",
        score=score,
        tags=tags,
        namespaces=("plant_health",),
        source_type=source_type,
        allowed_roles=("grower", "adviser"),
        knowledge_domains=("plant_health",),
        knowledge_bucket="farmer_knowledge",
    )


def test_raw_question_entity_fit_outranks_higher_scoring_distractor() -> None:
    right = _doc(
        "palmer",
        "Palmer amaranth and waterhemp identification",
        "Split the stem and check pith, petiole, and inflorescence traits before confirming Palmer amaranth.",
        tags=("palmer amaranth", "split stem", "pith", "petiole"),
        score=0.2,
    )
    distractor = _doc(
        "storage",
        "Stored grain insect management",
        "Inspect bins and grain temperature before choosing a storage treatment.",
        tags=("stored grain", "insect management", "temperature"),
        score=1.9,
    )

    ranked = rerank_evidence_docs(
        "A soybean field may contain Palmer amaranth. What stem features separate it from waterhemp?",
        (distractor, right),
        crops=("soybean",),
        pest_entities=("palmer amaranth", "waterhemp"),
        topics=("weed",),
        route_namespaces=("plant_health",),
    )

    assert ranked[0].doc_id == "palmer"


def test_fungicide_decision_rejects_freeze_recovery_as_decisive_evidence() -> None:
    freeze = _doc(
        "wheat-freeze",
        "Winter wheat freeze injury at jointing",
        "Wait for warm weather and split stems before deciding whether freeze injury changed the stand.",
        tags=("winter wheat", "freeze injury", "jointing", "split stems"),
        score=8.0,
    )
    label = _doc(
        "label-boundary",
        "Current pesticide label boundary",
        "Use the current label, rainfast interval, wind, drift, and crop stage before application.",
        tags=("current label", "rainfast", "wind", "drift"),
        score=3.0,
        source_type="boundary",
    )
    question = "Can I apply a fungicide to Ontario winter wheat before rain tomorrow?"

    kept, dropped = filter_decision_distractors(question, (freeze, label))
    handshake = build_evidence_handshake(question, kept, preserve_entities=("wheat", "disease", "product"))

    assert [doc.doc_id for doc in kept] == ["label-boundary"]
    assert dropped == (
        {"doc_id": "wheat-freeze", "reason": "freeze_recovery_not_fungicide_decision"},
    )
    assert handshake.primary_doc_id is None
    assert handshake.supporting_doc_ids == ("label-boundary",)


def test_capsule_rerank_keeps_seed_treatment_economics_ahead_of_foliar_ipm() -> None:
    treatment = _doc(
        "seed-treatment",
        "Seed treatment risk and value decision",
        "Compare target-pest history, planting conditions, treatment cost, expected avoided seedling loss, and an untreated comparison.",
        tags=("seed treatment", "pest history", "planting conditions", "untreated comparison"),
        score=0.2,
    )
    foliar = _doc(
        "foliar-ipm",
        "Foliar insect scouting and spray threshold",
        "Measure whole-canopy defoliation and insect count per plant before a foliar spray.",
        tags=("foliar spray", "whole-canopy defoliation", "economic threshold"),
        score=1.8,
    )
    question = "Is discounted insecticide-treated canola seed worthwhile without an early-pest loss history?"

    ranked = rerank_evidence_docs(question, (foliar, treatment), crops=("canola",), topics=("seed_treatment", "insect"))
    handshake = build_evidence_handshake(question, ranked, preserve_entities=("canola", "seed treatment"))

    assert ranked[0].doc_id == "seed-treatment"
    assert handshake.role_for("seed-treatment") == "decisive"
    assert handshake.role_for("foliar-ipm") == "distractor"


def test_capsule_marks_grain_storage_as_distractor_for_produce_water_safety() -> None:
    safety = _doc(
        "produce-water",
        "Produce safety after a changed agricultural water condition",
        "A changed crop-contact water source requires assessment, records, and a supported hold or harvest disposition; washing alone is not proof of safety.",
        tags=("produce safety", "crop-contact water", "hold harvest", "washing"),
        score=0.3,
    )
    grain = _doc(
        "grain-storage",
        "Grain moisture and mycotoxin storage risk",
        "Measure grain moisture and use aeration before storage.",
        tags=("grain moisture", "aeration", "mycotoxin"),
        score=1.9,
    )
    question = "Livestock entered upstream of spinach crop-contact water before harvest. Can washing substitute?"

    ranked = rerank_evidence_docs(question, (grain, safety), crops=("spinach",), topics=("produce_safety", "soil_water"))
    handshake = build_evidence_handshake(question, ranked, preserve_entities=("spinach", "crop-contact water"))

    assert ranked[0].doc_id == "produce-water"
    assert handshake.role_for("produce-water") == "decisive"
    assert handshake.role_for("grain-storage") == "distractor"


def test_raw_query_rank_breaks_generic_route_overlap_in_favor_of_named_hazard() -> None:
    hail = _doc(
        "hail",
        "Corn hail injury and replant assessment",
        "Wait for regrowth, then inspect growing points, stalk bruising, whorl injury, and the surviving stand.",
        tags=("corn", "hail", "regrowth", "growing point", "stalk bruising", "replant"),
        score=4.4,
    )
    flood = _doc(
        "flood",
        "Young corn recovery after ponding",
        "Assess growing points, crop survival, and stand count before replanting.",
        tags=("corn", "growing point", "stand count", "replant"),
        score=5.5,
    )

    ranked = rerank_evidence_docs(
        "Hail shredded young corn yesterday. When should I decide whether it needs replanting?",
        (flood, hail),
        crops=("corn",),
        route_namespaces=("crop_management",),
        raw_query_ranks={"hail": 1, "flood": 2},
    )

    assert ranked[0].doc_id == "hail"


def test_required_nutrient_entities_outrank_generic_precision_guidance() -> None:
    generic = _doc(
        "generic-vra",
        "Variable-rate fertilizer economic defensibility",
        "Use calibrated yield maps, response evidence, check strips, and a partial budget.",
        tags=("variable rate", "yield map", "partial budget", "check strip"),
        score=1.9,
    )
    pk = _doc(
        "pk-vra",
        "Soil-test-driven phosphorus and potassium response economics",
        "Use method-specific phosphorus and potassium soil tests, local calibration, and response probability.",
        tags=("phosphorus", "potassium", "soil test", "local calibration", "response probability"),
        score=0.3,
    )

    ranked = rerank_evidence_docs(
        "What would make a variable-rate P and K prescription economically defensible?",
        (generic, pk),
        topics=("fertility", "precision", "economics"),
        route_namespaces=("fertility", "precision_ag", "economics"),
        raw_query_ranks={"generic-vra": 1, "pk-vra": 2},
        required_entities=("phosphorus", "potassium"),
    )

    assert ranked[0].doc_id == "pk-vra"


def test_obligation_rerank_prefers_current_in_jurisdiction_guidance() -> None:
    stale_template = _doc(
        "stale-ab",
        "Alberta wheat nitrogen rate",
        "Nitrogen rate guidance for wheat with soil testing and nutrient credits.",
        tags=("wheat", "nitrogen", "soil test", "rate"),
        score=1.8,
    )
    stale_other_province = RetrievedDoc(
        **{
            **stale_template.__dict__,
            "jurisdictions": ("Alberta",),
            "crops": ("wheat",),
            "currency_status": "historical",
        }
    )
    current_template = _doc(
        "current-sk",
        "Saskatchewan wheat nutrient guidance",
        "Use representative soil tests, realistic yield goals, credits, source, timing, and placement.",
        tags=("wheat", "soil test", "nutrient credits", "placement"),
        score=0.4,
    )
    current_local = RetrievedDoc(
        **{
            **current_template.__dict__,
            "jurisdictions": ("Saskatchewan",),
            "crops": ("wheat",),
            "currency_status": "current",
        }
    )
    question = "How should a Saskatchewan wheat nitrogen rate be checked?"
    contract = build_decision_contract(question, classify_query(question))

    ranked = rerank_evidence_docs(
        question,
        (stale_other_province, current_local),
        crops=("wheat",),
        jurisdictions=("Saskatchewan",),
        decision_contract=contract,
    )

    assert ranked[0].doc_id == "current-sk"


def test_handshake_preserves_entities_and_measures_evidence_commitment() -> None:
    primary = _doc(
        "pivot",
        "Center-pivot runoff diagnosis",
        "Check nozzle package, pressure, flow, distribution uniformity, infiltration, and wheel-track runoff before changing irrigation depth.",
        tags=("nozzle package", "pressure", "flow", "distribution uniformity", "wheel track runoff"),
    )
    state = build_evidence_handshake(
        "A corn field is ponding under a center pivot. What should be checked?",
        (primary,),
        preserve_entities=("corn", "center pivot", "ponding"),
    )

    assert state.primary_doc_id == "pivot"
    assert state.preserve_entities == ("corn", "center pivot", "ponding")
    assert state.commit_check_enabled is True
    assert state.answer_alignment("Check pressure, flow, nozzle package, and distribution uniformity first.") >= 0.8
    assert state.answer_alignment("Apply a pesticide before harvest.") == 0.0


def test_crop_index_tags_do_not_become_evidence_commitments() -> None:
    primary = _doc(
        "manure-credit",
        "Alberta wheat manure nutrient credit",
        "Use manure analysis and plant availability with soil tests before determining the fertilizer balance for "
        "wheat. The crop index also covers barley, canola, and oat.",
        tags=("fertility", "barley", "canola", "oat"),
        score=8.0,
    )

    state = build_evidence_handshake(
        "What information is needed to credit manure nutrients for wheat without double applying fertilizer?",
        (primary,),
        preserve_entities=("wheat", "fertility"),
        required_entities=("wheat",),
    )

    assert not {"barley", "canola", "oat"} & set(state.decisive_terms)
    assert state.commit_check_enabled is False


def test_evidence_fallback_uses_only_strong_primary_source() -> None:
    primary = _doc(
        "slake",
        "Interpreting a soil slake test",
        "A slake test is a qualitative indicator of aggregate stability. Compare intact air-dry aggregates in water and record how rapidly they break apart. It does not diagnose sodicity by itself.",
        tags=("slake test", "aggregate stability", "air dry aggregates", "break apart"),
    )
    distractor = _doc(
        "sodicity",
        "Sodicity laboratory measurements",
        "Use sodium adsorption ratio and exchangeable sodium evidence to assess sodicity.",
        tags=("sodicity", "sodium adsorption ratio"),
    )

    answer = evidence_grounded_fallback(
        "What does a soil slake test show and how should I run it?",
        (primary, distractor),
        preserve_entities=("slake test",),
    )

    assert answer is not None
    assert "aggregate stability" in answer
    assert "sodium adsorption ratio" not in answer


def test_unrelated_primary_does_not_activate_evidence_fallback() -> None:
    unrelated = _doc(
        "storage",
        "Stored grain aeration",
        "Use grain temperature and moisture to manage aeration.",
        tags=("grain storage", "aeration"),
    )

    assert evidence_grounded_fallback(
        "How do I diagnose powdery mildew in cucurbits?",
        (unrelated,),
        preserve_entities=("cucurbits", "powdery mildew"),
    ) is None


def test_generic_current_label_phrase_does_not_make_tangential_source_primary() -> None:
    tangential = _doc(
        "pollinator",
        "Pollinator-sensitive area communication",
        "Check pollinator activity, habitat, buffers, wind, and the current label.",
        tags=("pollinator", "communication", "current label", "buffer", "wind"),
        score=4.1,
    )
    state = build_evidence_handshake(
        "A public forecast suggests rising wind. Separate scouting from a spray decision and current label constraints.",
        (tangential,),
    )

    assert state.primary_doc_id is None
    assert state.has_strong_primary is False


def test_required_crop_and_problem_must_appear_in_title_or_tags() -> None:
    generic = _doc(
        "generic",
        "Leafy vegetable foliar disease management",
        "Spinach downy mildew requires crop-specific diagnosis and current guidance.",
        tags=("leafy vegetable", "foliar disease", "current label"),
    )
    specific = _doc(
        "specific",
        "Spinach downy mildew management",
        "Confirm sporulation and crop stage before a treatment decision.",
        tags=("spinach", "downy mildew", "sporulation", "current label"),
    )

    weak = build_evidence_handshake(
        "Spinach has possible downy mildew. What should be checked?",
        (generic,),
        required_entities=("spinach", "downy mildew"),
    )
    strong = build_evidence_handshake(
        "Spinach has possible downy mildew. What should be checked?",
        (specific,),
        required_entities=("spinach", "downy mildew"),
    )

    assert weak.primary_doc_id is None
    assert strong.primary_doc_id == "specific"


def test_irrigation_nitrate_handshake_rejects_forage_distractor() -> None:
    forage = _doc(
        "forage-nitrate",
        "Forage nitrate and prussic-acid safety",
        "Test drought-stressed forage before grazing livestock.",
        tags=("forage", "nitrate", "prussic acid", "grazing"),
        score=8.0,
    )
    water_credit = _doc(
        "water-credit",
        "Irrigation-water nitrate nitrogen credit",
        "Use current well-water nitrate concentration, measured applied-water volume, timing, and crop uptake to calculate a nitrogen credit.",
        tags=("irrigation water", "nitrate", "applied water", "nitrogen credit", "flowmeter"),
        score=5.0,
    )
    state = build_evidence_handshake(
        "A well-water test reported nitrate. What makes the fertilizer credit defensible?",
        (forage, water_credit),
    )

    assert state.primary_doc_id == "water-credit"
    assert state.role_for("forage-nitrate") == "distractor"
    assert state.role_for("water-credit") == "decisive"
    assert state.distractor_doc_ids == ("forage-nitrate",)


def test_tile_drainage_handshake_does_not_promote_generic_et_guidance() -> None:
    et = _doc(
        "generic-et",
        "Public evapotranspiration and irrigation scheduling",
        "Use crop water use and a root-zone sensor before irrigation.",
        tags=("evapotranspiration", "crop water use", "irrigation prescription"),
        score=9.0,
    )
    drainage = _doc(
        "drainage-design",
        "Ground-truthing tile drainage decisions",
        "Inspect the water table, soil profile, restrictive layers, existing tile, and outlet capacity before drainage design.",
        tags=("tile", "drainage", "water table", "soil profile", "outlet"),
        score=5.0,
    )
    state = build_evidence_handshake(
        "A low area stays wet. Is crop color enough to place a tile drain?",
        (et, drainage),
    )

    assert state.primary_doc_id == "drainage-design"
    assert state.role_for("generic-et") == "distractor"


def test_forage_harvest_handshake_promotes_threshold_and_beneficial_evidence() -> None:
    ipm = _doc(
        "forage-ipm",
        "Hay field caterpillars on the field edge: spray, cut, or watch",
        "Use representative edge and interior sampling, crop stress, natural enemies, an economic threshold, planned cutting, and the current PHI.",
        tags=("hay field", "caterpillars", "edge", "interior", "spray", "cut", "watch", "economic threshold"),
        score=5.0,
    )
    state = build_evidence_handshake(
        "A drought-stressed hay field has caterpillars on one edge and is due to be cut. Spray, cut, or watch?",
        (ipm,),
    )

    assert state.primary_doc_id == "forage-ipm"
    assert state.role_for("forage-ipm") == "decisive"


def test_high_tunnel_handshake_promotes_integrated_delivery_evidence() -> None:
    integrated = _doc(
        "tunnel-integrated",
        "High-tunnel tomato fertigation and salinity diagnosis",
        "Check the fertigation injector, emitter uniformity, source-water EC, root-zone moisture, roots, soil tests, and tissue tests.",
        tags=("high tunnel", "fertigation", "injector", "emitter", "EC", "root-zone moisture"),
        score=5.0,
    )
    state = build_evidence_handshake(
        "High-tunnel tomatoes are yellowing near drip emitters after fertigation. Raise nitrogen?",
        (integrated,),
    )

    assert state.primary_doc_id == "tunnel-integrated"
    assert state.role_for("tunnel-integrated") == "decisive"


def test_named_aafc_product_specification_is_primary_for_product_interpretation() -> None:
    unrelated = _doc(
        "nitrate-leaching",
        "Nitrate leaching risk",
        "Use soil nitrate, rainfall, drainage, and crop uptake to assess leaching risk.",
        tags=("nitrate", "leaching", "drainage"),
        score=9.0,
    )
    product = RetrievedDoc(
        doc_id="crop-health-stage-models",
        title="Crop Health Indices: Data Product Specification - crop development stage models",
        text=(
            "AAFC uses the Robertson biometeorological time-scale model for cool-season small grains and the "
            "Brown and Bootsma Crop Heat Unit algorithm for warm-season corn and soybean. The result is a "
            "modelled regional crop development stage estimate."
        ),
        source="Agriculture and Agri-Food Canada",
        score=6.0,
        tags=("AAFC", "crop health indices", "crop development stage", "wheat", "corn", "soybean"),
        namespaces=("regional_environment", "crop_management"),
        source_type="regional_environment_profile",
        allowed_roles=("grower", "adviser"),
        crops=("wheat", "barley", "corn", "soybean"),
        source_id="ca_aafc_crop_health_indices_specification",
        jurisdictions=("Canada",),
        retrieval_policy="context_only",
    )

    state = build_evidence_handshake(
        "How does AAFC model crop development stage differently for cool-season small grains and warm-season corn or soybean?",
        (unrelated, product),
        preserve_entities=("wheat", "corn", "soybean"),
    )

    assert state.primary_doc_id == "crop-health-stage-models"
    assert state.role_for("crop-health-stage-models") == "interpretive"
    assert state.role_for("nitrate-leaching") == "supporting"


def test_named_aafc_product_specification_stays_boundary_for_field_prescription() -> None:
    product = RetrievedDoc(
        doc_id="crop-health-stage-table",
        title="Crop Health Indices: Data Product Specification - crop development stage table",
        text="For small grains, value 3 is a modelled regional heading estimate in the 5 km raster.",
        source="Agriculture and Agri-Food Canada",
        score=8.0,
        tags=("AAFC", "crop development stage", "wheat", "heading"),
        namespaces=("regional_environment", "crop_management"),
        source_type="regional_environment_profile",
        allowed_roles=("grower", "adviser"),
        crops=("wheat",),
        source_id="ca_aafc_crop_health_indices_specification",
        jurisdictions=("Canada",),
        retrieval_policy="context_only",
    )

    state = build_evidence_handshake(
        "The 5 km AAFC growth-stage raster says 3. Set an exact fungicide timing without scouting or a current label.",
        (product,),
        preserve_entities=("wheat",),
    )

    assert state.primary_doc_id is None
    assert state.role_for("crop-health-stage-table") == "boundary"


def test_named_french_aafc_product_specification_is_primary_for_interpretation() -> None:
    product = RetrievedDoc(
        doc_id="ca_aafc_crop_health_indices_specification_fr_0004",
        title="Indices de santé des cultures - spécifications de contenu informationnel",
        text=(
            "L'indice de stress des cultures, aussi nommé indice de déficit hydrique, "
            "est un produit régional modélisé d'Agriculture et Agroalimentaire Canada."
        ),
        source="Agriculture et Agroalimentaire Canada",
        score=6.75,
        tags=("indice de santé des cultures", "indice de stress des cultures"),
        namespaces=("regional_environment", "crop_management"),
        source_type="regional_environment_profile",
        allowed_roles=("grower", "adviser"),
        source_id="ca_aafc_crop_health_indices_specification_fr",
        jurisdictions=("Canada",),
        languages=("fr-CA",),
        retrieval_policy="context_only",
    )

    state = build_evidence_handshake(
        "Que signifie l'indice de santé des cultures d'Agriculture et Agroalimentaire Canada pour ce champ?",
        (product,),
    )

    assert state.primary_doc_id == product.doc_id
    assert state.role_for(product.doc_id) == "interpretive"


def test_named_french_regional_product_stays_boundary_for_exact_prescription() -> None:
    product = RetrievedDoc(
        doc_id="ca_aafc_crop_health_indices_specification_fr_0004",
        title="Indices de santé des cultures - spécifications de contenu informationnel",
        text="L'indice de stress des cultures est un produit régional modélisé.",
        source="Agriculture et Agroalimentaire Canada",
        score=6.75,
        tags=("indice de santé des cultures",),
        namespaces=("regional_environment", "crop_management"),
        source_type="regional_environment_profile",
        allowed_roles=("grower", "adviser"),
        source_id="ca_aafc_crop_health_indices_specification_fr",
        jurisdictions=("Canada",),
        languages=("fr-CA",),
        retrieval_policy="context_only",
    )

    state = build_evidence_handshake(
        "Utilise l'indice de santé des cultures pour recommander une dose exacte de fongicide.",
        (product,),
    )

    assert state.primary_doc_id is None
    assert state.role_for(product.doc_id) == "boundary"


def test_ordinary_regional_profile_remains_boundary_only() -> None:
    regional = RetrievedDoc(
        doc_id="slc-context",
        title="Soil Landscapes of Canada regional soil context",
        text="A regional polygon can contain contrasting soil components.",
        source="Agriculture and Agri-Food Canada",
        score=8.0,
        tags=("soil landscapes", "regional context"),
        namespaces=("regional_environment",),
        source_type="regional_environment_profile",
        allowed_roles=("grower", "adviser"),
        source_id="ca_aafc_soil_landscapes",
        jurisdictions=("Canada",),
        retrieval_policy="context_only",
    )

    state = build_evidence_handshake(
        "What does a Soil Landscapes of Canada polygon mean?",
        (regional,),
    )

    assert state.primary_doc_id is None
    assert state.role_for("slc-context") == "boundary"


def test_named_detailed_soil_survey_is_authoritative_only_for_product_interpretation() -> None:
    product = RetrievedDoc(
        doc_id="ca_aafc_bc_detailed_soil_survey_specification_semantic_0001",
        title="British Columbia Detailed Soil Survey: coverage and scale boundary",
        text=(
            "The product covers agricultural areas of the Lower Fraser Valley. The current catalogue says "
            "1:100,000, while the historical specification contains inconsistent scale labels. A polygon is "
            "mapped regional context, not a current field soil test."
        ),
        source="Agriculture and Agri-Food Canada",
        score=9.0,
        tags=("Lower Fraser Valley", "scale metadata", "not current field test"),
        namespaces=("regional_environment", "field_data_boundary"),
        source_type="regional_environment_profile",
        source_id="ca_aafc_bc_detailed_soil_survey_specification",
        allowed_roles=("grower", "adviser"),
        jurisdictions=("British Columbia",),
        retrieval_policy="context_only",
    )

    state = build_evidence_handshake(
        "What does the British Columbia Detailed Soil Survey polygon cover and what can it prove?",
        (product,),
    )

    assert state.primary_doc_id == product.doc_id
    assert state.role_for(product.doc_id) == "interpretive"
    assert state.authority_for(product.doc_id)[:2] == (
        "authoritative_for_source_meaning",
        "not_authorized",
    )
    assert state.has_strong_primary is True
    assert state.has_field_action_primary is False
    assert state.primary_field_action_authority == "not_authorized"
    assert "lower fraser valley" in state.decisive_terms


def test_context_only_applied_guidance_cannot_become_decisive_or_primary() -> None:
    historical = RetrievedDoc(
        doc_id="historical-lentil-disease",
        title="Red Lentil Management in Alberta",
        text="Sclerotinia risk rises in a dense crop stand during wet weather.",
        source="Government of Alberta",
        score=9.0,
        tags=("lentil", "Alberta"),
        namespaces=("crop_management",),
        source_type="applied_guidance",
        allowed_roles=("grower",),
        crops=("lentil",),
        jurisdictions=("Alberta",),
        retrieval_policy="context_only",
    )

    state = build_evidence_handshake(
        "Red lentil, Alberta. Germination and thousand-kernel weight are supplied but target stand is missing.",
        [historical],
        preserve_entities=("lentil",),
        required_entities=("lentil",),
    )

    assert state.primary_doc_id is None
    assert state.decisive_terms == ()
    assert state.role_for(historical.doc_id) == "boundary"
    assert state.evidence_roles[0][2] == "context_only_not_decisive"
