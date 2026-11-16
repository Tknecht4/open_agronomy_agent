from __future__ import annotations

import pytest

from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.evidence_handshake import (
    build_evidence_handshake,
    evidence_grounded_fallback,
    filter_decision_distractors,
    rerank_evidence_docs,
)
from agronomy_agent.decision_contract import build_decision_contract
from agronomy_agent.router import classify_query


REGIONAL_PRODUCTS = [
    ("AAFC crop health indices", "ca_aafc_crop_health_indices_specification"),
    ("British Columbia Detailed Soil Survey", "ca_aafc_bc_detailed_soil_survey_specification"),
    ("Nova Scotia Detailed Soil Survey", "ca_aafc_ns_detailed_soil_survey_specification"),
    ("Prince Edward Island Detailed Soil Survey", "ca_aafc_pei_detailed_soil_survey_specification"),
    ("agro-pedological atlas of Quebec", "ca_aafc_qc_agropedological_atlas_specification"),
    ("New Brunswick agricultural soil classes", "nb_geonb_agricultural_soil_classes"),
    ("Newfoundland and Labrador weather station climate monitoring data", "nl_historical_weather_station_climate_metadata"),
]


@pytest.mark.parametrize("requested", REGIONAL_PRODUCTS)
@pytest.mark.parametrize("retrieved", REGIONAL_PRODUCTS)
def test_named_regional_source_meaning_requires_the_requested_product_identity(requested, retrieved):
    title, source_id = retrieved
    document = RetrievedDoc(doc_id=source_id + ":passage", title=title,
        text="This specification describes mapped regional support, coverage and source limits.",
        source="Synthetic provincial or federal publisher", score=9.0,
        allowed_roles=("grower", "adviser"),
        tags=("coverage", "regional context"), namespaces=("regional_environment",),
        source_type="regional_environment_profile", source_id=source_id,
        retrieval_policy="context_only")
    handshake = build_evidence_handshake(f"What does the {requested[0]} describe?", (document,))
    if requested == retrieved:
        assert handshake.primary_doc_id == document.doc_id
        assert handshake.role_for(document.doc_id) == "interpretive"
        assert handshake.has_strong_primary
    else:
        assert handshake.primary_doc_id is None
        assert handshake.role_for(document.doc_id) == "boundary"
        assert not handshake.has_strong_primary
        assert not handshake.missing_decisive_terms("The requested product is not established here.")
    assert not handshake.has_field_action_primary
    assert handshake.authority_for(document.doc_id)[1] == "not_authorized"


def test_each_explicitly_requested_regional_product_can_keep_its_own_source():
    documents = tuple(RetrievedDoc(doc_id=source_id, title=title,
        text="Mapped regional information with coverage and scale limits.", source="Synthetic publisher",
        score=9.0, tags=("coverage",), namespaces=("regional_environment",),
        allowed_roles=("grower", "adviser"),
        source_type="regional_environment_profile", source_id=source_id, retrieval_policy="context_only")
        for title, source_id in REGIONAL_PRODUCTS[1:3])
    handshake = build_evidence_handshake(
        "Compare the British Columbia Detailed Soil Survey and Nova Scotia Detailed Soil Survey coverage.", documents)
    assert all(handshake.role_for(doc.doc_id) == "interpretive" for doc in documents)
    assert all(handshake.authority_for(doc.doc_id)[1] == "not_authorized" for doc in documents)


def test_named_product_fidelity_uses_requested_facts_instead_of_another_passages_tags():
    from agronomy_agent.answer_verifier import assess_claim_risk
    product = RetrievedDoc(doc_id="synthetic-stage", title="AAFC Crop Health Indices stage specification",
        text="The 5 km crop development layer is a modelled regional estimate; scout representative field areas.",
        source="Agriculture and Agri-Food Canada", score=9.0,
        allowed_roles=("grower", "adviser"),
        tags=("station precipitation temperature", "versatile soil moisture budget", "crop stress index"),
        namespaces=("regional_environment",), source_type="regional_environment_profile",
        source_id="ca_aafc_crop_health_indices_specification", retrieval_policy="context_only")
    question = "What can the AAFC crop development layer establish about crop stage?"
    answer = product.text
    assessment = assess_claim_risk(answer, question=question, evidence_text=product.text,
        evidence_docs=(product,), question_type="regional_context", risk_level="low")
    assert not assessment.missing_evidence_terms
    assert "missing_named_product_fidelity" not in assessment.reasons
    assert "weak_primary_evidence_alignment" not in assessment.reasons
    # Removing the requested scale and regional/field boundary still needs review.
    unsafe = assess_claim_risk("The layer establishes the stage of every plant.", question=question,
        evidence_text=product.text, evidence_docs=(product,), question_type="regional_context", risk_level="low")
    assert "missing_named_product_fidelity" in unsafe.reasons


@pytest.mark.parametrize("title,source_id", REGIONAL_PRODUCTS[1:4])
def test_matched_soil_product_without_a_facet_contract_retains_primary_content_checks(title, source_id):
    from agronomy_agent.answer_verifier import assess_claim_risk
    document = RetrievedDoc(doc_id=source_id, title=title,
        text="The survey describes mapped soil units with survey coverage and mapping scale limits.",
        source="Synthetic publisher", score=9.0, allowed_roles=("grower",),
        tags=("mapped soil units", "survey coverage", "mapping scale"), namespaces=("regional_environment",),
        source_type="regional_environment_profile", source_id=source_id, retrieval_policy="context_only")
    assessment = assess_claim_risk("The product is a live rainfall sensor.",
        question=f"What does the {title} describe?", evidence_text=document.text,
        evidence_docs=(document,), question_type="regional_context", risk_level="low")
    assert assessment.requires_review and assessment.missing_evidence_terms
    assert "missing_named_product_fidelity" in assessment.reasons


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


def _synthetic_crop_health_passage(key, text, score=1):
    return RetrievedDoc(doc_id='ca_aafc_crop_health_indices_specification:' + key,
        title='AAFC Crop Health Indices specification', text=text, source='Synthetic product specification',
        source_id='ca_aafc_crop_health_indices_specification', score=score, tags=('unrelated metadata',),
        source_type='regional_environment_profile', namespaces=('regional_environment',), allowed_roles=('grower',),
        retrieval_policy='context_only')


@pytest.mark.parametrize('question,passage', [
    ('Are AAFC crop health grids remotely sensed or station-driven VSMB estimates?',
     'The VSMB uses station temperature and precipitation with crop-specific coefficients.'),
    ('Why does the AAFC crop development layer use different models for wheat and corn?',
     'The cool-season model differs from the warm-season model in its phenology and heat-unit assumptions.'),
    ('How should I read AAFC crop development stage values for small grains?',
     'Growth Stage codes include emergence, jointing and heading for small grains.'),
])
def test_requested_product_facet_selects_passage_content_before_shared_title_metadata(question, passage):
    metadata = _synthetic_crop_health_passage('metadata', 'Reference system WGS 84. Gregorian calendar. Data distribution and contact information.', score=100)
    relevant = _synthetic_crop_health_passage('requested-facet', passage)
    ranked = rerank_evidence_docs(question, (metadata, relevant), raw_query_ranks={metadata.doc_id: 1})
    assert ranked[0].doc_id == relevant.doc_id
    handshake = build_evidence_handshake(question, (metadata, relevant))
    assert handshake.primary_doc_id == relevant.doc_id
    assert not handshake.has_field_action_primary


@pytest.mark.parametrize('question,answer', [
    ('Why can I not interpret an AAFC crop development layer for wheat with the corn and soybean heat-unit model?',
     'The heat-unit model is specific to corn and soybean, not wheat. Use a wheat-specific interpretation and treat the regional layer as context, not a field measurement.'),
    ('How should I read AAFC crop development stage values for small grains?',
     'Use the small-grain code meanings for this regional model, not another crop family. The layer is not a field measurement; confirm the actual wheat stage by scouting.'),
])
def test_stage_facet_does_not_acquire_an_unasked_resolution_requirement(question, answer):
    from agronomy_agent.answer_verifier import assess_claim_risk
    passage = _synthetic_crop_health_passage('stage', 'A modelled regional crop-development layer; cool-season and warm-season model assumptions differ. Growth Stage includes emergence, jointing and heading.')
    assessment = assess_claim_risk(answer, question=question, evidence_text=passage.text,
        evidence_docs=(passage,), question_type='regional_context', risk_level='low')
    assert not assessment.missing_evidence_terms
    assert 'missing_named_product_fidelity' not in assessment.reasons
    if 'values' in question:
        explicit = assess_claim_risk(answer, question=question + ' What is its spatial resolution?',
            evidence_text=passage.text, evidence_docs=(passage,), question_type='regional_context', risk_level='low')
        assert '5 km modelled regional raster' in explicit.missing_evidence_terms


@pytest.mark.parametrize('claim,contradiction', [
    ('The AAFC crop health grids are remotely sensed products, not station-driven VSMB estimates.', True),
    ('AAFC crop health grids are not station-driven regional estimates.', True),
    ('The AAFC crop health grids are station-driven VSMB regional estimates, not remotely sensed field measurements.', False),
    ('It is not true that the AAFC crop health grids are remotely sensed products.', False),
    ('NDVI satellite products are remotely sensed. AAFC crop health grids are modelled regional estimates.', False),
])
def test_crop_health_model_assertions_cannot_contradict_the_supplied_product_specification(claim, contradiction):
    from agronomy_agent.answer_verifier import assess_claim_risk, verify_answer
    question = 'Are AAFC crop health grids remotely sensed products or station-driven VSMB regional estimates?'
    passage = _synthetic_crop_health_passage('inputs', 'VSMB model estimates use station temperature and precipitation with crop-specific coefficients. A regional model is not a field measurement.')
    assessment = assess_claim_risk(claim, question=question, evidence_text=passage.text, evidence_docs=(passage,), question_type='field_data', risk_level='low')
    assert ('named_product_source_contradiction' in assessment.reasons) is contradiction
    if contradiction:
        class UnavailableEditor:
            def generate(self, messages):
                raise AssertionError('A supplied product contradiction has a reviewed source-bound fallback')
        result = verify_answer(claim, question=question, evidence_text=passage.text, evidence_docs=(passage,),
            question_type='field_data', risk_level='low', editor=UnavailableEditor(), review_mode='risk_conditioned_selective_v3')
        assert 'derived from station temperature and precipitation' in result.answer
        assert 'not remotely sensed field measurements' in result.answer
        assert not result.final_assessment.requires_review
    # Another product's document cannot provide the missing source premise.
    foreign = _synthetic_crop_health_passage('inputs', passage.text)
    assert 'named_product_source_contradiction' not in assess_claim_risk(claim,
        question='How are AAFC Annual Crop Inventory images obtained?', evidence_text=foreign.text,
        evidence_docs=(foreign,), question_type='field_data', risk_level='low').reasons


@pytest.mark.parametrize('denial', [
    'It is incorrect to say that AAFC crop health grids are remotely sensed products.',
    'The statement that AAFC crop health grids are remotely sensed is false.',
    'It is not the case that AAFC crop health grids are remotely sensed products.',
])
def test_product_source_contradiction_is_local_to_an_affirmed_claim(denial):
    from agronomy_agent.answer_verifier import _crop_health_source_contradiction
    question = 'Are AAFC crop health grids remotely sensed products or station-driven VSMB estimates?'
    source = _synthetic_crop_health_passage('inputs', 'VSMB uses station temperature and precipitation.')
    assert not _crop_health_source_contradiction(question, denial, (source,))
    assert _crop_health_source_contradiction(question, denial + ' AAFC crop health grids are remotely sensed products.', (source,))


def test_another_regional_products_question_cannot_select_crop_health_fallback():
    from agronomy_agent.answer_verifier import _named_crop_health_interpretation_fallback, _named_product_field_decision_fallback
    source = _synthetic_crop_health_passage('inputs', 'VSMB uses station temperature and precipitation.')
    question = 'What are the model inputs for the British Columbia Detailed Soil Survey?'
    assert _named_crop_health_interpretation_fallback(question, (source,)) is None
    assert _named_product_field_decision_fallback(question + ' Can I set a fertilizer rate?', (source,)) is None


@pytest.mark.parametrize('text', [
    'VSMB is not used for this product. Temperature and precipitation are not inputs to this product.',
    'VSMB uses no temperature and precipitation data.',
    'It is not true that VSMB uses station temperature and precipitation.',
    'The statement that VSMB uses station temperature and precipitation is false.',
])
def test_model_input_support_requires_an_affirmative_relation_not_token_cooccurrence(text):
    from agronomy_agent.evidence_handshake import crop_health_model_inputs_supported
    from agronomy_agent.answer_verifier import _crop_health_source_contradiction, _named_crop_health_interpretation_fallback
    source = _synthetic_crop_health_passage('inputs', text)
    question = 'Are AAFC crop health grids remotely sensed products or station-driven VSMB estimates?'
    assert not crop_health_model_inputs_supported(source)
    assert not _crop_health_source_contradiction(question, 'AAFC crop health grids are remotely sensed products.', (source,))
    answer = _named_crop_health_interpretation_fallback(question, (source,))
    assert answer is None or 'derived from station temperature and precipitation' not in answer
    assert build_evidence_handshake(question, (source,)).primary_doc_id is None


@pytest.mark.parametrize('text', [
    'It is unknown whether VSMB uses station temperature and precipitation.',
    'The report does not establish that VSMB uses station temperature and precipitation.',
    'Does VSMB use station temperature and precipitation?',
    'VSMB uses station temperature and precipitation?',
    'Could VSMB use station temperature and precipitation?',
    'Assuming VSMB uses station temperature and precipitation, the result follows.',
    'It is not clear whether VSMB uses station temperature and precipitation.',
])
def test_unknown_or_questioned_model_input_relation_is_not_affirmative_source_evidence(text):
    from agronomy_agent.evidence_handshake import crop_health_model_inputs_supported
    source = _synthetic_crop_health_passage('inputs', text)
    assert not crop_health_model_inputs_supported(source)


@pytest.mark.parametrize('prefix,suffix,status', [
    ('The report states that ', '.', 'asserted'),
    ('It is not true that ', '.', 'negated'),
    ('It is unknown whether ', '.', 'unknown'),
    ('Does ', '?', 'questioned'),
])
def test_proposition_scope_keeps_unknown_separate_from_denial(prefix, suffix, status):
    from agronomy_agent.request_scope import proposition_assertion_status
    assert proposition_assertion_status(prefix, suffix) == status
