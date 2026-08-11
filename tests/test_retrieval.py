import json
from pathlib import Path

from agronomy_agent.agno_runtime.knowledge_graph import KnowledgeGraph
from agronomy_agent.agno_runtime.knowledge_factory import build_knowledge
from agronomy_agent.agno_runtime.local_index import LexicalRetriever, infer_namespaces, infer_source_type, tokenize
from agronomy_agent.router import classify_query


ROOT = Path(__file__).resolve().parents[1]


def test_specialized_guidance_source_types_are_canonicalized_for_retrieval() -> None:
    assert infer_source_type({"source_type": "diagnostic_guidance"}) == "applied_guidance"
    assert infer_source_type({"source_type": "measurement_guidance"}) == "applied_guidance"
    assert infer_source_type({"source_type": "extension_document"}) == "applied_guidance"


def test_jsonl_loader_projects_corpus_context_policy_into_retrieved_docs(tmp_path: Path) -> None:
    corpus = tmp_path / "context.jsonl"
    corpus.write_text(
        "\n".join(
            [
                json.dumps({"doc_id": "default", "title": "Soil context", "text": "soil context"}),
                json.dumps(
                    {
                        "doc_id": "live",
                        "title": "Current label context",
                        "text": "current label context",
                        "retrieval_policy": "requires_live_authority",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    retriever = LexicalRetriever.from_jsonl_paths(
        [corpus],
        corpus_eligibility_by_path={str(corpus.resolve()): "context_only"},
    )

    assert retriever.docs[0]["retrieval_policy"] == "context_only"
    assert retriever.docs[1]["retrieval_policy"] == "requires_live_authority"
    hits = retriever.search("soil context", top_k=1)
    assert hits[0].retrieval_policy == "context_only"


def _agentic_doc_ids(question: str, docs: list[dict[str, object]], *, top_k: int = 3) -> list[str]:
    retriever = LexicalRetriever(docs)
    route = classify_query(question)
    knowledge = build_knowledge(
        {
            "agno": {
                "knowledge": {"reranker": "coverage"},
                "retrieval": {"enable_agentic_search": True, "max_agentic_subqueries": 2, "top_k": top_k, "min_agentic_candidates": 3},
            }
        },
        retriever,
    )
    result = knowledge.search(
        question,
        filters={
            "audience": ["farmer"],
            "knowledge_domains": list(route.knowledge_domains),
            "knowledge_bucket": route.knowledge_bucket,
            "source_type": ["applied_guidance", "boundary"],
            "risk_level": route.risk_level,
            "namespaces": list(route.namespaces),
            "query_expansion": list(route.query_expansion),
        },
        top_k=top_k,
    )
    return [doc.doc_id for doc in result.docs]


def test_tokenize_normalizes_soilwise_chemistry_spelling() -> None:
    assert tokenize("sulphur sulphate mineralisation") == ["sulfur", "sulfate", "mineralization"]


def test_tokenize_preserves_french_agronomy_terms_and_diacritics() -> None:
    assert tokenize("Prévisions de rendement, santé des cultures et résolution") == [
        "prévisions",
        "rendement",
        "santé",
        "cultures",
        "résolution",
    ]


def test_french_query_prefers_matching_language_without_excluding_other_evidence() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "english_metadata",
                "title": "Indice de stress des cultures",
                "text": "Indice de stress, résolution et interpolation.",
                "language": ["en-CA"],
            },
            {
                "doc_id": "french_metadata",
                "title": "Indice de stress des cultures",
                "text": "Indice de stress, résolution et interpolation.",
                "language": ["fr-CA"],
            },
        ]
    )

    hits = retriever.search(
        "Comment l'indice de stress des cultures est-il interpolé à cette résolution?",
        top_k=2,
    )

    assert [hit.doc_id for hit in hits] == ["french_metadata", "english_metadata"]


def test_tokenize_drops_generic_instruction_words() -> None:
    assert tokenize("What should I verify before side-dressing nitrogen after heavy rain?") == [
        "side-dressing",
        "nitrogen",
        "rain",
    ]


def test_tokenize_drops_broad_question_and_proximity_words() -> None:
    assert tokenize("Can I check drainage near a field and how should I start?") == [
        "check",
        "drainage",
        "start",
    ]


def test_tokenize_preserves_mlra_codes_without_general_number_noise() -> None:
    tokens = tokenize("MLRA 63B and 063B climate context in 2026")

    assert tokens.count("063b") == 2
    assert "2026" not in tokens


def test_weighted_expansion_does_not_overpower_direct_query_terms() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "sulfur",
                "title": "Sulfur deficiency triage",
                "text": "Sandy low organic matter soils after heavy rainfall can show sulfur deficiency.",
                "tags": ["sulfur", "deficiency"],
            },
            {
                "doc_id": "nitrogen",
                "title": "Nitrogen recommendation context",
                "text": "Nitrogen rates depend on yield goal, credits, calibration, and crop removal.",
                "tags": ["nitrogen", "fertility"],
            },
        ]
    )
    route = classify_query("Corn is pale on sandy knolls after heavy rain. Is sulfur deficiency likely?")

    hits = retriever.search("Corn is pale on sandy knolls after heavy rain. Is sulfur deficiency likely?", query_expansion=route.query_expansion)

    assert hits[0].doc_id == "sulfur"


def test_manitoba_2026_scouting_supplement_retrieves_for_field_question() -> None:
    rows = [
        json.loads(line)
        for line in (ROOT / "data/derived/rag/canada_agronomy_supplement_v3.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    retriever = LexicalRetriever(rows)

    hits = retriever.search(
        "In Manitoba seedling canola, how should I scout flea beetle leaf damage?",
        jurisdictions=("Manitoba",),
        strict_jurisdictions=True,
        top_k=3,
    )

    assert hits
    assert hits[0].doc_id == "mb_2026_canola_insect_scouting_semantic_0002"


def test_strict_jurisdiction_filter_excludes_unscoped_general_documents() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "unscoped",
                "title": "Generic soil polygon context",
                "text": "A soil polygon is screening context.",
            },
            {
                "doc_id": "canada",
                "title": "Soil Landscapes of Canada polygon context",
                "text": "A soil polygon is screening context.",
                "jurisdiction": ["Canada"],
            },
        ]
    )

    permissive = retriever.search("soil polygon context", jurisdictions=("Canada",), top_k=2)
    strict = retriever.search(
        "soil polygon context",
        jurisdictions=("Canada",),
        strict_jurisdictions=True,
        top_k=2,
    )

    assert {doc.doc_id for doc in permissive} == {"unscoped", "canada"}
    assert [doc.doc_id for doc in strict] == ["canada"]


def test_small_strict_lane_scores_globally_high_fanout_terms() -> None:
    docs = [
        {
            "doc_id": f"unscoped-{index:04d}",
            "title": "Generic drainage note",
            "text": "Drainage requires field verification.",
        }
        for index in range(1001)
    ]
    docs.extend(
        {
            "doc_id": f"canada-component-{index:02d}",
            "title": "Canadian mapped component",
            "text": "A mapped component is regional context.",
            "jurisdiction": ["Canada"],
        }
        for index in range(10)
    )
    docs.append(
        {
            "doc_id": "canada-drainage-definition",
            "title": "Canadian drainage definition",
            "text": "Drainage describes how water moves through soil.",
            "jurisdiction": ["Canada"],
        }
    )
    retriever = LexicalRetriever(docs)

    hits = retriever.search(
        "mapped component drainage",
        jurisdictions=("Canada",),
        strict_jurisdictions=True,
        top_k=20,
    )

    assert "canada-drainage-definition" in [doc.doc_id for doc in hits]


def test_sulfur_deficiency_does_not_prefer_sulfur_dioxide() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "sulfur_deficiency",
                "title": "Sulfur deficiency triage",
                "text": "Check sandy soil, rainfall, field pattern, and tissue test before recommending sulfur.",
                "tags": ["sulfur", "deficiency"],
            },
            {
                "doc_id": "sulfur_dioxide",
                "title": "Sulphur dioxide",
                "text": "Sulphur dioxide is an atmospheric compound.",
                "tags": ["soil health"],
            },
        ]
    )
    route = classify_query("Corn is pale after heavy rainfall. Could this be sulfur deficiency?")

    hits = retriever.search("Corn is pale after heavy rainfall. Could this be sulfur deficiency?", query_expansion=route.query_expansion)

    assert hits[0].doc_id == "sulfur_deficiency"


def test_applied_guidance_beats_soilwise_ontology_for_field_advice() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "soilwise_high_screening_levels",
                "title": "High Screening Levels",
                "text": "High screening levels are unacceptable soil contamination thresholds in a soil health ontology.",
                "source": "SoilWise knowledge graph",
                "tags": ["soilwise", "knowledge graph", "soil health"],
            },
            {
                "doc_id": "cover_crop_water_tradeoffs",
                "title": "Cover crop water tradeoffs",
                "text": "Cover crops may use soil moisture before the next crop, so check water use, residue benefit, species mix, termination timing, and planting window.",
                "source": "seed conservation agronomy synthesis",
                "tags": ["cover crop", "soil water", "dryland"],
            },
        ]
    )
    route = classify_query("Cover crops before sorghum with hot dry forecast: what water tradeoffs matter?")

    hits = retriever.search(
        "Cover crops before sorghum with hot dry forecast: what water tradeoffs matter?",
        namespaces=route.namespaces,
        query_expansion=route.query_expansion,
    )

    assert hits[0].doc_id == "cover_crop_water_tradeoffs"
    assert hits[0].source_type == "applied_guidance"
    assert infer_source_type({"doc_id": "soilwise_x", "source": "SoilWise knowledge graph"}) == "ontology"


def test_seed_treatment_query_prefers_seed_treatment_evidence_over_drift_docs() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "label",
                "title": "Generic product label boundary",
                "text": "Verify the current product label, jurisdiction, buffers, and target pest before product advice.",
                "source_type": "boundary",
                "namespaces": ["label_boundary", "product_stewardship"],
            },
            {
                "doc_id": "drift",
                "title": "Spray drift timing",
                "text": "Wind speed, wind direction, gusts, buffer requirements, and sensitive crops drive spray drift decisions.",
                "source_type": "applied_guidance",
                "namespaces": ["product_stewardship", "label_boundary"],
            },
            {
                "doc_id": "seed_treatment",
                "title": "Cross-crop seed-treatment risk decision evidence",
                "text": "Insecticide seed treatment decisions should ask for early planting, soil temperature or cool wet soils, pest history, field history, planting conditions, pest pressure, seedcorn maggot, bean leaf beetle, wireworm, grub, threshold or risk, and label fit.",
                "source_type": "applied_guidance",
                "namespaces": ["plant_health", "product_stewardship", "crop_management"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
            },
        ]
    )
    question = "Is an insecticide seed treatment needed for early planted sorghum with a hot dry forecast?"
    route = classify_query(question)

    hits = retriever.search(
        question,
        top_k=3,
        namespaces=route.namespaces,
        knowledge_domains=route.knowledge_domains,
        knowledge_bucket=route.knowledge_bucket,
        query_expansion=route.query_expansion,
        source_types=["applied_guidance", "boundary"],
    )

    assert hits[0].doc_id == "seed_treatment"


def test_compaction_query_with_incidental_spray_window_prefers_soil_structure_evidence() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "spray",
                "title": "Spray window",
                "text": "Spray label decisions use wind, buffer, target pest, product, and rainfast guidance.",
                "source_type": "boundary",
                "namespaces": ["label_boundary", "product_stewardship"],
            },
            {
                "doc_id": "compaction",
                "title": "Traffic compaction diagnostics",
                "text": "Traffic compaction diagnosis should check traffic pattern, soil moisture, penetrometer or probe depth, soil pit evidence, rooting depth, controlled traffic, targeted tillage, and cover crop options.",
                "source_type": "applied_guidance",
                "namespaces": ["soil_water", "soil_health", "precision_ag"],
                "knowledge_domains": ["farmer_knowledge", "soil_water", "farm_management"],
                "knowledge_bucket": "farmer_knowledge",
            },
        ]
    )
    question = "Yield maps show low-yield strips after saturated soil and a narrow spray window. What diagnostic steps fit traffic compaction?"
    route = classify_query(question)

    hits = retriever.search(
        question,
        top_k=2,
        namespaces=route.namespaces,
        knowledge_domains=route.knowledge_domains,
        knowledge_bucket=route.knowledge_bucket,
        query_expansion=route.query_expansion,
        source_types=["applied_guidance", "boundary"],
    )

    assert hits[0].doc_id == "compaction"


def test_agentic_seed_treatment_search_prioritizes_seed_evidence_before_drift_boundaries() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "drift-boundary",
                "title": "Spray drift approval",
                "text": "Wind speed, drift, buffer, downwind sensitive crops, and current label drive spray timing approval.",
                "source_type": "boundary",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["label_boundary", "product_stewardship", "plant_health"],
            },
            {
                "doc_id": "seed-treatment",
                "title": "Cross-crop seed-treatment risk decision evidence",
                "text": "Insecticide seed treatment decisions should ask for early planting, soil temperature or cool wet soils, pest history, field history, planting conditions, pest pressure, seedcorn maggot, bean leaf beetle, wireworm, grub, threshold or risk, and label fit.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["plant_health", "product_stewardship", "crop_management"],
            },
            {
                "doc_id": "label-boundary",
                "title": "Product label boundary",
                "text": "Use the current product label, crop, target pest, site, and jurisdiction before product advice.",
                "source_type": "boundary",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["label_boundary", "product_stewardship", "plant_health"],
            },
        ]
    )
    question = "Is an insecticide seed treatment needed for early planted sorghum?"
    route = classify_query(question)
    knowledge = build_knowledge(
        {
            "agno": {
                "knowledge": {"reranker": "coverage"},
                "retrieval": {"enable_agentic_search": True, "max_agentic_subqueries": 2, "top_k": 3, "min_agentic_candidates": 3},
            }
        },
        retriever,
    )

    result = knowledge.search(
        question,
        filters={
            "audience": ["farmer"],
            "knowledge_domains": list(route.knowledge_domains),
            "knowledge_bucket": route.knowledge_bucket,
            "source_type": ["applied_guidance", "boundary"],
            "risk_level": route.risk_level,
            "namespaces": list(route.namespaces),
            "query_expansion": list(route.query_expansion),
        },
        top_k=3,
    )

    assert result.docs[0].doc_id == "seed-treatment"
    assert "label-boundary" in [doc.doc_id for doc in result.docs]


def test_agentic_aphid_search_prioritizes_ipm_threshold_evidence_before_drift_boundaries() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "drift-boundary",
                "title": "Spray drift approval",
                "text": "Wind speed, drift, buffer, downwind sensitive crops, and current label drive spray timing approval.",
                "source_type": "boundary",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["label_boundary", "product_stewardship", "plant_health"],
            },
            {
                "doc_id": "aphid-ipm",
                "title": "Aphid threshold and IPM evidence boundary",
                "text": "Aphid treatment advice should begin with scouting counts, aphids per plant, correct aphid species, crop stage, natural enemies or beneficial insects, regional economic threshold, and the current insecticide label.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["plant_health", "product_stewardship"],
            },
            {
                "doc_id": "label-boundary",
                "title": "Product label boundary",
                "text": "Use the current product label, crop, target pest, site, and jurisdiction before product advice.",
                "source_type": "boundary",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["label_boundary", "product_stewardship", "plant_health"],
            },
        ]
    )
    question = "A scout found aphids in soybeans. The retailer wants an insecticide recommendation today."
    route = classify_query(question)
    knowledge = build_knowledge(
        {
            "agno": {
                "knowledge": {"reranker": "coverage"},
                "retrieval": {"enable_agentic_search": True, "max_agentic_subqueries": 2, "top_k": 3, "min_agentic_candidates": 3},
            }
        },
        retriever,
    )

    result = knowledge.search(
        question,
        filters={
            "audience": ["farmer"],
            "knowledge_domains": list(route.knowledge_domains),
            "knowledge_bucket": route.knowledge_bucket,
            "source_type": ["applied_guidance", "boundary"],
            "risk_level": route.risk_level,
            "namespaces": list(route.namespaces),
            "query_expansion": list(route.query_expansion),
        },
        top_k=3,
    )

    assert result.docs[0].doc_id == "aphid-ipm"
    assert "label-boundary" in [doc.doc_id for doc in result.docs]


def test_agentic_cover_crop_search_prioritizes_public_moisture_termination_evidence() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "generic-soil-water",
                "title": "Generic water movement",
                "text": "Runoff, drainage, leaching, infiltration, water table, and soil texture affect soil-water management.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["soil_water", "soil_health"],
            },
            {
                "doc_id": "public-cover-crop",
                "title": "Cover-crop moisture and termination decision",
                "text": "Cover crop water tradeoff advice should balance stored soil moisture, water use, residue, erosion, species mix, termination timing, termination method, crop rotation, rainfall or irrigation outlook, and the next crop planting window.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water", "conservation", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["soil_water", "soil_health", "crop_management"],
            },
        ]
    )
    question = "The team wants cover crops before soybean with thunderstorms forecast. What water tradeoffs should the adviser discuss?"
    route = classify_query(question)
    knowledge = build_knowledge(
        {
            "agno": {
                "knowledge": {"reranker": "coverage"},
                "retrieval": {"enable_agentic_search": True, "max_agentic_subqueries": 2, "top_k": 3, "min_agentic_candidates": 3},
            }
        },
        retriever,
    )

    result = knowledge.search(
        question,
        filters={
            "audience": ["farmer"],
            "knowledge_domains": list(route.knowledge_domains),
            "knowledge_bucket": route.knowledge_bucket,
            "source_type": ["applied_guidance", "boundary"],
            "risk_level": route.risk_level,
            "namespaces": list(route.namespaces),
            "query_expansion": list(route.query_expansion),
        },
        top_k=3,
    )

    assert result.docs[0].doc_id == "public-cover-crop"


def test_agentic_precision_economics_search_prioritizes_public_partial_budget_evidence() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "field-records",
                "title": "Precision agriculture records and audit trail",
                "text": "Clean records, georeferenced boundaries, calibrated monitors, validated yield maps, as-applied layers, and an audit trail support precision agriculture.",
                "source_type": "boundary",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "farm_management", "operations"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["precision_ag", "field_data_boundary"],
            },
            {
                "doc_id": "public-precision-economics",
                "title": "Variable-rate fertilizer economic defensibility",
                "text": "For a variable-rate fertilizer map that increases total spend, evaluate soil-test zones, yield-response evidence, crop price, fertilizer and application cost, partial budget or ROI, check strips or replicated on-farm trials, profit, and uncertainty.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "farm_management", "operations", "market", "soil_health"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["precision_ag", "fertility", "field_data_boundary", "economics"],
            },
        ]
    )
    question = "A variable-rate fertilizer map increases total spend. How should the adviser evaluate whether the prescription is economically defensible?"
    route = classify_query(question)
    knowledge = build_knowledge(
        {
            "agno": {
                "knowledge": {"reranker": "coverage"},
                "retrieval": {"enable_agentic_search": True, "max_agentic_subqueries": 2, "top_k": 3, "min_agentic_candidates": 3},
            }
        },
        retriever,
    )

    result = knowledge.search(
        question,
        filters={
            "audience": ["farmer"],
            "knowledge_domains": list(route.knowledge_domains),
            "knowledge_bucket": route.knowledge_bucket,
            "source_type": ["applied_guidance", "boundary"],
            "risk_level": route.risk_level,
            "namespaces": list(route.namespaces),
            "query_expansion": list(route.query_expansion),
        },
        top_k=3,
    )

    assert result.docs[0].doc_id == "public-precision-economics"


def test_agentic_nitrate_leaching_search_prioritizes_mitigation_options() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "precision-records",
                "title": "Precision agriculture records",
                "text": "Audit trails, yield maps, field boundaries, crop price, and check strips support precision agriculture records.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "farm_management", "operations"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["precision_ag", "field_data_boundary"],
            },
            {
                "doc_id": "public-nitrate-leaching",
                "title": "Nitrate leaching mitigation on sandy soils",
                "text": "Nitrate leaching mitigation on sandy soil after heavy rain should discuss soil nitrate test, yield goal, crop uptake, split timing, sidedress, cover crop, nitrification inhibitor, stabilizer, irrigation scheduling, root zone, and credits.",
                "source": "University Extension",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water", "soil_health", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["fertility", "soil_water", "soil_health"],
            },
        ]
    )
    question = "A sandy field with heavy spring rain has nitrate leaching risk. What agronomic options should be discussed?"
    route = classify_query(question)
    knowledge = build_knowledge(
        {
            "agno": {
                "knowledge": {"reranker": "coverage"},
                "retrieval": {"enable_agentic_search": True, "max_agentic_subqueries": 2, "top_k": 3, "min_agentic_candidates": 3},
            }
        },
        retriever,
    )

    result = knowledge.search(
        question,
        filters={
            "audience": ["farmer"],
            "knowledge_domains": list(route.knowledge_domains),
            "knowledge_bucket": route.knowledge_bucket,
            "source_type": ["applied_guidance", "boundary"],
            "risk_level": route.risk_level,
            "namespaces": list(route.namespaces),
            "query_expansion": list(route.query_expansion),
        },
        top_k=3,
    )

    assert result.docs[0].doc_id == "public-nitrate-leaching"


def test_agentic_erosion_search_prioritizes_public_conservation_practices() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "harvest-storage",
                "title": "Harvest and storage weather risk",
                "text": "Harvest risk answers should focus on crop moisture, drying, aeration, storage plan, mold, test weight, weather forecast, and field loss.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["crop_management", "plant_health", "economics"],
            },
            {
                "doc_id": "public-erosion",
                "title": "Erosion control practices for sloping fields",
                "text": "For erosion reduction on sloping ground, keep residue, use cover crops, reduce tillage or no-till, contour farming, strip cropping, terraces, grassed waterways, buffers, stable outlets, and match practices to slope, runoff, and soil.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water", "conservation", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["soil_water", "soil_health", "crop_management"],
            },
        ]
    )
    question = "What practices should be considered to reduce erosion on a sloping field after soybean harvest?"
    route = classify_query(question)
    knowledge = build_knowledge(
        {
            "agno": {
                "knowledge": {"reranker": "coverage"},
                "retrieval": {"enable_agentic_search": True, "max_agentic_subqueries": 2, "top_k": 3, "min_agentic_candidates": 3},
            }
        },
        retriever,
    )

    result = knowledge.search(
        question,
        filters={
            "audience": ["farmer"],
            "knowledge_domains": list(route.knowledge_domains),
            "knowledge_bucket": route.knowledge_bucket,
            "source_type": ["applied_guidance", "boundary"],
            "risk_level": route.risk_level,
            "namespaces": list(route.namespaces),
            "query_expansion": list(route.query_expansion),
        },
        top_k=3,
    )

    assert route.question_type == "soil_water"
    assert result.docs[0].doc_id == "public-erosion"


def test_agentic_conservation_plan_search_prioritizes_nrcs_local_guidance() -> None:
    doc_ids = _agentic_doc_ids(
        "A corn field has visible runoff toward a tile outlet and drainage ditch. What conservation evidence should shape the recommendation?",
        [
            {
                "doc_id": "generic-water",
                "title": "Generic drainage",
                "text": "Runoff, drainage, leaching, infiltration, water table, and texture affect soil-water management.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["soil_water", "soil_health"],
            },
            {
                "doc_id": "public-conservation-plan",
                "title": "Conservation planning for runoff, residue, buffers, and waterways",
                "text": "Runoff and erosion recommendations should check residue, cover crop, waterway, buffer, setback, grassed outlet, slope, soil texture, drainage, NRCS conservation plan, and local guidance.",
                "source": "USDA NRCS Extension",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water", "conservation", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["soil_water", "soil_health", "crop_management", "regional_environment"],
            },
        ],
    )

    assert doc_ids[0] == "public-conservation-plan"


def test_agentic_soil_survey_search_prioritizes_map_unit_boundary_language() -> None:
    doc_ids = _agentic_doc_ids(
        "A user drew a boundary and NRCS soil survey suggests map units and dominant components. How should this be used without overclaiming field truth?",
        [
            {
                "doc_id": "generic-soil",
                "title": "Soil properties",
                "text": "Soil texture, drainage, organic matter, and slope affect soil-water decisions.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["soil_water", "soil_health"],
            },
            {
                "doc_id": "public-soil-survey-prior",
                "title": "NRCS soil survey as map-unit prior",
                "text": "NRCS SDA soil survey map unit and component information is a prior and screening regional context. Drainage class, hydrologic group, hydric rating, texture, and slope do not replace soil test, field observation, ground truth, scouting, or soil pit evidence.",
                "source": "USDA NRCS",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water", "regional_environment_context"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["soil_water", "soil_health", "regional_environment", "field_data_boundary"],
            },
        ],
    )

    assert doc_ids[0] == "public-soil-survey-prior"


def test_agentic_crop_statistics_search_prioritizes_nass_regional_boundary() -> None:
    doc_ids = _agentic_doc_ids(
        "A spring wheat grower asks whether recent regional yield and acreage statistics should change this year's plan. How should USDA NASS Quick Stats be used?",
        [
            {
                "doc_id": "market-forecast",
                "title": "Crop prices",
                "text": "Market price, contracts, and revenue affect farm economics.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "market"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["economics"],
            },
            {
                "doc_id": "public-nass-regional",
                "title": "USDA NASS Quick Stats as regional statistics",
                "text": "USDA NASS Quick Stats provides county, state, and regional statistics for yield, acreage, and production. Treat it as a prior, not field-specific prediction; ask for field records, yield map, grower records, and crop year.",
                "source": "USDA NASS",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "market", "farm_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["crop_management", "economics", "field_data_boundary"],
            },
        ],
    )

    assert doc_ids[0] == "public-nass-regional"


def test_agentic_cdl_history_search_prioritizes_crop_cover_prior_boundary() -> None:
    doc_ids = _agentic_doc_ids(
        "A user drew a boundary and the agent sampled USDA Cropland Data Layer classes across recent years. How should CDL be used without overclaiming planting history?",
        [
            {
                "doc_id": "rotation-general",
                "title": "Rotation planning",
                "text": "Crop rotation and field history shape disease and nutrient planning.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["crop_management"],
            },
            {
                "doc_id": "public-cdl-prior",
                "title": "Cropland Data Layer boundary sampling as crop-cover prior",
                "text": "USDA NASS Cropland Data Layer CDL boundary sample points summarize crop-cover class across multi-year recent years and rotation context. It is a prior, not grower planting record, not acreage, not crop insurance, and not field truth.",
                "source": "USDA NASS",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management", "regional_environment_context"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["crop_management", "field_data_boundary", "regional_environment"],
            },
        ],
    )

    assert doc_ids[0] == "public-cdl-prior"


def test_agentic_forage_search_prioritizes_livestock_safety_tests() -> None:
    doc_ids = _agentic_doc_ids(
        "A forage pasture was stressed by drought and frost regrowth, and livestock may graze or receive hay. What tests should shape nitrate or prussic acid risk advice?",
        [
            {
                "doc_id": "generic-pasture",
                "title": "Pasture management",
                "text": "Pasture rotation, stocking rate, and forage quality affect livestock performance.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management", "livestock"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["crop_management"],
            },
            {
                "doc_id": "public-forage-safety",
                "title": "Forage nitrate and prussic-acid livestock-safety triage",
                "text": "Forage pasture nitrate and prussic acid hydrocyanic acid risk after drought, frost, stress, or regrowth requires forage test, lab test, feed test, species such as sorghum sudan millet grass legume, and grazing hay silage livestock safety withdrawal guidance.",
                "source": "Extension",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management", "livestock"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["crop_management", "plant_health", "soil_water"],
            },
        ],
    )

    assert doc_ids[0] == "public-forage-safety"


def test_agentic_horticulture_search_prioritizes_irrigation_disease_stage_guidance() -> None:
    doc_ids = _agentic_doc_ids(
        "A tomato specialty crop field has humidity and leaf wetness. How should irrigation, disease risk, scouting, and crop stage be balanced?",
        [
            {
                "doc_id": "generic-irrigation",
                "title": "Irrigation scheduling",
                "text": "Irrigation timing depends on soil moisture and crop demand.",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "soil_water"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["soil_water"],
            },
            {
                "doc_id": "public-specialty-disease",
                "title": "Specialty-crop irrigation, disease risk, and crop-stage triage",
                "text": "Specialty vegetable tomato decisions balance soil moisture irrigation with disease risk, humidity, leaf wetness, field scouting, crop stage, local extension, label guidance, and market quality.",
                "source": "Extension",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management", "soil_water"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["crop_management", "plant_health", "soil_water", "product_stewardship"],
            },
        ],
    )

    assert doc_ids[0] == "public-specialty-disease"


def test_agentic_general_ipm_search_prioritizes_threshold_beneficials_guidance() -> None:
    doc_ids = _agentic_doc_ids(
        "Scouts found insects in wheat. What should be checked before deciding whether an insecticide is justified?",
        [
            {
                "doc_id": "generic-label",
                "title": "Product label boundary",
                "text": "Check crop, product, target pest, jurisdiction, application method, and label.",
                "source_type": "boundary",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["product_stewardship", "label_boundary", "plant_health"],
            },
            {
                "doc_id": "public-ipm-threshold",
                "title": "IPM insect threshold evidence before treatment",
                "text": "Insecticide IPM decisions need scout sampling count density, pest species, crop stage, economic threshold, beneficial insects or natural enemies, field history, and current local label before treatment.",
                "source": "Extension",
                "source_type": "applied_guidance",
                "allowed_roles": ["farmer"],
                "knowledge_domains": ["farmer_knowledge", "crop_management"],
                "knowledge_bucket": "farmer_knowledge",
                "namespaces": ["plant_health", "product_stewardship", "label_boundary", "crop_management"],
            },
        ],
    )

    assert doc_ids[0] == "public-ipm-threshold"


def test_explicit_agno_namespaces_are_preserved_for_search_filters() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "curated_nitrogen_boundary",
                "title": "Curated nitrogen note",
                "text": "This reviewed note mentions spray labels only as a contrast, but it is curated for nitrogen calibration.",
                "source_type": "applied_guidance",
                "namespaces": ["fertility"],
                "knowledge_domains": ["farmer_knowledge"],
                "knowledge_bucket": "farmer_knowledge",
            }
        ]
    )

    hits = retriever.search(
        "nitrogen calibration",
        namespaces=["fertility"],
        knowledge_domains=["farmer_knowledge"],
        knowledge_bucket="farmer_knowledge",
    )

    assert infer_namespaces(retriever.docs[0]) == ["fertility"]
    assert hits and hits[0].doc_id == "curated_nitrogen_boundary"
    assert hits[0].namespaces == ("fertility",)


def test_inferred_namespaces_use_token_phrase_hints_without_rescanning_text() -> None:
    doc = {
        "doc_id": "precision_note",
        "title": "Field data workflow",
        "text": "Yield map and as-applied records need georeference checks before a prescription.",
        "tags": [],
    }

    assert "precision_ag" in infer_namespaces(doc)


def test_retrieved_doc_token_cache_stays_json_serializable() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "nitrogen",
                "title": "Nitrogen side-dress",
                "text": "Check rainfall, soil moisture, crop stage, and calibration before side-dressing nitrogen.",
                "tags": ["fertility"],
            }
        ]
    )

    hit = retriever.search("nitrogen rainfall calibration", top_k=1)[0]

    assert isinstance(hit.token_set, tuple)
    assert "nitrogen" in hit.token_set
    json.dumps(hit.__dict__)


def test_graph_routes_sulfur_query_to_sulfur_not_idc(tmp_path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        """
        {
          "nodes": [
            {"id": "idc", "name": "iron deficiency chlorosis", "kind": "plant health issue", "description": "Soybean chlorosis risk from high pH and wet soils.", "aliases": ["IDC"]},
            {"id": "s", "name": "sulphur", "kind": "soil health concept", "description": "sulphur is a macronutrient.", "aliases": []}
          ],
          "edges": []
        }
        """,
        encoding="utf-8",
    )
    route = classify_query("Corn is pale on sandy knolls after heavy rain. Check sulfur deficiency.")
    graph = KnowledgeGraph.from_paths([graph_path])

    hits = graph.search("Corn is pale on sandy knolls after heavy rain. Check sulfur deficiency.", namespaces=route.namespaces, query_expansion=route.query_expansion)

    assert hits[0].node_id == "s"


def test_graph_exact_name_lookup_does_not_substitute_a_related_measurement(tmp_path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(
        """
        {
          "nodes": [
            {"id": "soc", "name": "soil organic carbon", "kind": "soil health concept", "description": "soil organic carbon", "aliases": ["SOC"]},
            {"id": "hwec", "name": "hot water extractable carbon", "kind": "soil health concept", "description": "A laboratory fraction of the soil organic carbon pool.", "aliases": []}
          ],
          "edges": []
        }
        """,
        encoding="utf-8",
    )
    graph = KnowledgeGraph.from_paths([graph_path])

    hits = graph.lookup_names(("soil organic carbon",))

    assert [hit.node_id for hit in hits] == ["soc"]


def test_retrieval_can_filter_by_knowledge_bucket_and_domains() -> None:
    retriever = LexicalRetriever(
        [
            {
                "doc_id": "forum_soil",
                "title": "Soil drainage field notes",
                "text": "Tile drainage failures, infiltration, and runoff mitigation planning.",
                "source": "forum",
                "knowledge_bucket": "farmer_knowledge",
                "knowledge_domains": ["soil_water", "water_management", "farmer_knowledge"],
            },
            {
                "doc_id": "forum_market",
                "title": "Pricing strategy for grains",
                "text": "Compare grain contracts and margin planning before locking forward contracts.",
                "source": "forum",
                "knowledge_bucket": "farmer_knowledge",
                "knowledge_domains": ["market", "farm_management"],
            },
        ]
    )

    hits = retriever.search(
        "field drainage and runoff",
        knowledge_bucket="farmer_knowledge",
        knowledge_domains=("soil_water", "water_management"),
    )

    assert hits and hits[0].doc_id == "forum_soil"
    assert hits[0].knowledge_bucket == "farmer_knowledge"
    assert "soil_water" in hits[0].knowledge_domains
