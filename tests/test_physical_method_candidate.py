"""Two non-active physical summaries; private DOM custody never ships here.

Local custody/rebuild tests require two explicit environment paths. Public
tests still exercise release hashes, method fit, authority and fail-closed
validation without redistributing the source DOM or controller scenarios.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from agronomy_agent.agent import build_context, load_agent_resources
from agronomy_agent.corpus_release import quality_ledger_status, source_locator_status
from agronomy_agent.method_context import (
    METHOD_SCHEMA, PHYSICAL_CAPTURE_KIND, PHYSICAL_METHOD_SCHEMA,
    PHYSICAL_REVIEW_SHA256, method_fit_reason, requested_methods, reviewed_method_ids,
)
from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = Path("data/manifests/physical_method_chapter_sources_v1.json")
SUPPORT = Path("data/manifests/physical_method_chapter_support_v1.json")
SEED = Path("data/seed/physical_method_context_v1.jsonl")
STORE = Path("data/derived/rag/offline_agronomy/physical_methods/v1")
CONFIG = "configs/rag_physical_method_candidate.yaml"
IDS = {"PROPOSED-KSTATE-MEASUREMENT-BASIS", "PROPOSED-KSTATE-WATER-ACCOUNTING"}
PHYSICAL_IDS = {"soil_measurement_basis", "layer_water_accounting"}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def builder_module():
    spec = importlib.util.spec_from_file_location("physical_builder", ROOT / "scripts/build_production_foundations_supplement.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def local_builder(tmp_path, monkeypatch):
    module = builder_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    for relative in (REGISTRY, SUPPORT, SEED):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
    return module, tmp_path


@pytest.fixture
def private_custody():
    packet = os.environ.get("AGRONOMY_AGENT_CHAPTER_EVIDENCE_ROOT")
    review = os.environ.get("AGRONOMY_AGENT_CHAPTER_REVIEW_RECEIPT")
    if not packet or not review:
        pytest.skip("Private source custody absent; no original DOM is distributed with the candidate")
    return Path(packet), Path(review)


def rebuild(local_builder, private_custody, name="build"):
    module, root = local_builder
    packet, review = private_custody
    return module.build(root / SEED, root / REGISTRY, root / name,
        store_id="physical-method-context-v1", support_receipt_path=root / SUPPORT,
        chapter_evidence_root=packet, chapter_review_receipt=review)


@pytest.fixture(scope="module")
def docs():
    resources = load_agent_resources(CONFIG)
    return {doc.doc_id: doc for doc in resources.retriever.search(
        "bulk density particle gravimetric volumetric layer water storage", top_k=30)
        if doc.doc_id in IDS}


def test_candidate_metadata_hashes_and_licence():
    registry = read(ROOT / REGISTRY)
    support = read(ROOT / SUPPORT)
    manifest = read(ROOT / STORE / "store_manifest.json")
    receipt = read(ROOT / STORE / "source_receipt.json")
    released = rows(ROOT / STORE / "shards/foundations-0001.jsonl")
    assert len(released) == manifest["row_count"] == 2
    assert manifest["shards"][0]["sha256"] == sha(ROOT / STORE / "shards/foundations-0001.jsonl")
    assert support["source_registry_sha256"] == receipt["external_source_registry_sha256"] == sha(ROOT / REGISTRY)
    assert receipt["source_support_receipt_sha256"] == sha(ROOT / SUPPORT)
    assert receipt["chapter_review_sha256"] == registry["independent_review_sha256"] == PHYSICAL_REVIEW_SHA256
    assert receipt["chapter_capture_kind"] == PHYSICAL_CAPTURE_KIND
    assert not receipt["external_snapshots_in_public_package"]
    for source in registry["sources"]:
        assert source["jurisdiction"] == "United States"
        assert source["chapter_doi"] is None
        assert source["snapshot_kind"] == PHYSICAL_CAPTURE_KIND
        assert source["original_http_response_sha256"] is None
        assert all("text" not in span for span in source["locators"])
    for item in released:
        assert item["license"] == item["license_snapshot"]["identifier"] == "CC-BY-4.0"
        assert item["training_allowed"] is False
        assert item["activation"] == "none"
        assert item["admission_status"] == "non_active_candidate"
        assert item["retrieval_policy"] == "context_only"
        assert item["authority_tier"] == "internal_synthesis"
        assert item["jurisdiction"] == ["Canada", "United States"]
        assert all(country == "United States" for country in item["source_jurisdictions"])
        assert source_locator_status(item["source_locator"])[0]
        assert quality_ledger_status(item)[0]


def test_no_native_dom_excerpts_or_controller_gold_in_publishable_candidate():
    released = rows(ROOT / SEED)
    for item in released:
        assert "<math" not in json.dumps(item)
        assert "paired_input_variants" not in item and "answer_rubric" not in item
        assert "supplied_facts" not in item and "facts_payload_sha256" not in item
        assert item["required_context"]["interpretation"].startswith("task-conditional")
        assert item["attribution"] and item["changes"]


def test_missing_custody_is_not_a_successful_rebuild(local_builder):
    module, root = local_builder
    with pytest.raises(ValueError, match="explicit private evidence"):
        module.build(root / SEED, root / REGISTRY, root / "missing",
            store_id="physical-method-context-v1", support_receipt_path=root / SUPPORT)
    assert not (root / "missing").exists()


@pytest.mark.parametrize("store", ["production-foundations-v1", "production-foundations-method-v2", "ask-science-context-v1"])
def test_chapter_registry_cannot_enter_legacy_or_article_store(local_builder, store):
    module, root = local_builder
    with pytest.raises(ValueError):
        module.build(root / SEED, root / REGISTRY, root / "wrong-store", store_id=store)
    assert not (root / "wrong-store").exists()


@pytest.mark.parametrize("html", ["<script>x</script>", "<figure>x</figure>", "<table>x</table>",
    "<blockquote>x</blockquote>", "<!DOCTYPE html><p>x</p>",
    '<math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mi>a</mi></mfrac></math>',
    '<math xmlns="http://www.w3.org/1998/Math/MathML"><annotation>x</annotation></math>'])
def test_normalizer_rejects_unreviewed_constructs(html):
    with pytest.raises(ValueError):
        builder_module()._normalize_chapter_fragment(html)


def test_synthetic_mathml_preserves_denominator_and_subscript():
    # Project-authored structural fixture, not captured publisher DOM.
    fragment = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><msub><mi>x</mi><mi>a</mi></msub><mi>y</mi></mfrac></math>'
    assert builder_module()._normalize_chapter_fragment(fragment) == "(x_a)/(y)"


@pytest.mark.parametrize("question,expected", [
    ("For my Alberta farm, explain bulk density versus particle density.", "soil_measurement_basis"),
    ("For my Kansas field, convert gravimetric moisture to volumetric moisture.", "soil_measurement_basis"),
    ("For our Saskatchewan soil layer, explain water storage.", "layer_water_accounting"),
    ("Explain soil water storage for a Wisconsin field.", "layer_water_accounting"),
    ("For Alberta, explain soil water storage for grain crops.", "layer_water_accounting"),
])
def test_reviewed_method_fit(question, expected, docs):
    signal = analyze_query_context(question)
    matched = filter_docs_for_query(list(docs.values()), signal)
    assert any(expected in reviewed_method_ids(doc) for doc in matched.docs)


@pytest.mark.parametrize("question", [
    "For my Australian operation, explain bulk density.",
    "For my farms in Ontario and Australia, explain water storage.",
    "Explain the county office address in Alberta.",
    "For our Alberta farm, skip bulk density; explain seed mass instead.",
    "An Alberta handout mentions bulk density as background; who wrote it?",
])
def test_unrequested_foreign_or_mixed_fit_stays_blocked(question, docs):
    fit = filter_docs_for_query(list(docs.values()), analyze_query_context(question))
    assert not fit.docs


@pytest.mark.parametrize("question", [
    "For my Alberta dairy, explain volumetric milk pricing.",
    "For my Alberta operation, calculate water storage in a rainwater tank.",
    "For my Alberta operation, explain bulk density of harvested wheat grain.",
    "For my Alberta operation, explain gravimetric seed-meter calibration.",
    "Using a soil manual, explain grain bulk density for my Alberta farm.",
    "For my Alberta business, compare bulk density versus particle density of concrete.",
    "For Alberta, explain volumetric measurements.",
    "Using a soil manual, explain water storage in a drinking-water cistern for Alberta.",
    "Using a soil manual, explain volumetric glassware calibration for my Alberta laboratory.",
    "Using the Soil Water chapter, explain water storage in our Alberta cistern.",
])
def test_non_soil_physical_words_do_not_admit_soil_evidence(question, docs):
    assert not requested_methods(question, permitted_methods=PHYSICAL_IDS)
    assert not filter_docs_for_query(list(docs.values()), analyze_query_context(question)).docs


def test_independent_soil_and_non_soil_clauses_keep_only_the_soil_method(docs):
    question = "For my Alberta farm, explain soil bulk density. Then explain volumetric milk pricing."
    assert requested_methods(question, permitted_methods=PHYSICAL_IDS) == ("soil_measurement_basis",)
    matched = filter_docs_for_query(list(docs.values()), analyze_query_context(question))
    assert {doc.doc_id for doc in matched.docs} == {"PROPOSED-KSTATE-MEASUREMENT-BASIS"}


def test_physical_obligations_are_scoped_to_the_new_profile():
    question = "For our Alberta soil layer, explain water storage and soil bulk density."
    physical = {"method:soil_measurement_basis", "method:layer_water_accounting"}
    assert requested_methods(question) == ()  # legacy API default is unchanged
    for profile, expected in [
        ("configs/rag.yaml", set()),
        ("configs/rag_production_foundations_method_candidate.yaml", set()),
        (CONFIG, physical),
    ]:
        context = build_context(question, rag_config=profile, use_context_cache=False, use_search_cache=False)
        keys = {row["key"] for row in context.runtime_metadata["decision_contract"]["evidence_obligations"]}
        assert keys & physical == expected
    question = "For an Alberta farm, explain a partial budget."
    for profile, expected in [("configs/rag_production_foundations_method_candidate.yaml", True), (CONFIG, False)]:
        context = build_context(question, rag_config=profile, use_context_cache=False, use_search_cache=False)
        keys = {row["key"] for row in context.runtime_metadata["decision_contract"]["evidence_obligations"]}
        assert ("method:partial_budget" in keys) is expected


@pytest.mark.parametrize("fault", ["legacy_schema", "wrong_review", "fake_HTTP", "wrong_basis", "wrong_country", "wrong_source", "unknown_method"])
def test_physical_scope_is_not_a_generic_single_source_exception(fault, docs):
    water = docs["PROPOSED-KSTATE-WATER-ACCOUNTING"]
    scope = dict(water.method_scope)
    extra = {}
    if fault == "legacy_schema": scope["schema_version"] = METHOD_SCHEMA
    elif fault == "wrong_review": scope["source_review_sha256"] = "0" * 64
    elif fault == "fake_HTTP": scope["capture_kind"] = "original_HTTP_response"
    elif fault == "wrong_basis": scope["basis"] = "field_calibration"
    elif fault == "wrong_country": extra["source_jurisdictions"] = ("Canada",)
    elif fault == "wrong_source": extra["supporting_source_ids"] = ("unknown",)
    else: scope["method_ids"] = ["enterprise_budget"]
    assert not reviewed_method_ids(replace(water, method_scope=scope, **extra))


def test_new_id_cannot_enter_two_source_legacy_schema(docs):
    density = docs["PROPOSED-KSTATE-MEASUREMENT-BASIS"]
    assert not reviewed_method_ids(replace(density, method_scope={**density.method_scope, "schema_version": METHOD_SCHEMA}))


def test_context_preserves_method_provenance_without_field_authority():
    question = "For our Alberta operation, explain soil water storage and soil bulk density before judging a field condition."
    context = build_context(question, rag_config=CONFIG, use_context_cache=False, use_search_cache=False)
    packet = context.runtime_metadata["evidence_fabric"]["evidence_packet"]
    assert any(doc.doc_id in IDS for doc in context.retrieved_docs)
    capsules = [row for row in packet["capsules"] if row["authority_role"] == "method_context"]
    assert capsules and all(row["field_action_authority"] == "not_authorized" for row in capsules)
    for span in packet["spans"]:
        locator = span["locator"]
        if locator.get("doc_id") in IDS:
            assert set(locator["source_jurisdictions"]) == {"United States"}
            assert locator["method_source_capture_kind"] == PHYSICAL_CAPTURE_KIND
            assert locator["method_source_review_sha256"] == PHYSICAL_REVIEW_SHA256
    assert "GENERAL METHOD ONLY" in context.packed_context.text


def test_task_conditional_inputs_are_preserved_without_new_calculator(docs):
    assert len(docs) == 2
    water = next(row for row in rows(ROOT / SEED) if row["doc_id"].endswith("WATER-ACCOUNTING"))
    inputs = water["required_context"]
    assert inputs["layer_storage"]["alternatives"][0] == ["supplied_volumetric_fraction", "layer_thickness", "compatible_units"]
    assert {"FC", "PWP", "crop_stage", "application_efficiency"} <= set(inputs["not_required_for_supplied_theta_depth_storage"])
    measurement = next(row for row in rows(ROOT / SEED) if row["doc_id"].endswith("MEASUREMENT-BASIS"))
    assert measurement["required_context"]["gravimetric_to_volumetric"]["alternatives"] == [[
        "supplied_gravimetric_fraction", "bulk_density", "water_density", "compatible_units"]]
    assert "Missing inputs block only outputs that depend on them." in measurement["text"]


def test_active_profile_and_obligations_do_not_include_candidate():
    context = build_context("For Alberta, explain soil water storage and bulk density.",
        rag_config="configs/rag.yaml", use_context_cache=False, use_search_cache=False)
    assert not any(doc.doc_id in IDS for doc in context.retrieved_docs)
    assert not any(row["key"] in {"method:soil_measurement_basis", "method:layer_water_accounting"}
        for row in context.runtime_metadata["decision_contract"]["evidence_obligations"])
    assert CONFIG not in (ROOT / "configs/runtime_profiles.json").read_text()


def test_compound_method_request_does_not_satisfy_local_action_authority():
    context = build_context(
        "For my Alberta farm, explain soil bulk density and soil water storage. Can these textbook methods establish today's measured field moisture or an irrigation target?",
        rag_config=CONFIG, use_context_cache=False, use_search_cache=False)
    assert any(doc.doc_id in IDS for doc in context.retrieved_docs)
    packet = context.runtime_metadata["evidence_fabric"]["evidence_packet"]
    methods = [row for row in packet["coverage"] if row["slot_key"].startswith("method:")]
    assert methods and all(row["required_authority"] == "method_context_only" for row in methods)
    assert all(row["field_action_authority"] == "not_authorized"
        for row in packet["capsules"] if row["authority_role"] == "method_context")


def test_custody_reader_enforces_file_bound_without_following_symlinks(tmp_path):
    module = builder_module()
    path = tmp_path / "oversized"
    path.write_bytes(b"x" * 131073)
    with pytest.raises(ValueError): module._bounded_bytes(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError): module._bounded_bytes(link)


def test_unknown_profile_method_schema_is_not_an_admission():
    from agronomy_agent.decision_contract import build_decision_contract

    with pytest.raises(ValueError, match="unknown method context schema"):
        build_decision_contract("For Alberta, explain soil water storage.", {},
            method_context_enabled=True, method_context_schema="unknown")


def test_exact_private_rebuild_reproduces_and_refuses_overwrite(local_builder, private_custody):
    rebuild(local_builder, private_custody)
    module, root = local_builder
    for file in ("shards/foundations-0001.jsonl", "quality_ledger.json", "source_receipt.json", "store_manifest.json"):
        assert (root / "build" / file).read_bytes() == (ROOT / STORE / file).read_bytes()
    rebuild(local_builder, private_custody, "second")
    assert (root / "build/store_manifest.json").read_bytes() == (root / "second/store_manifest.json").read_bytes()
    with pytest.raises(FileExistsError): rebuild(local_builder, private_custody)


@pytest.mark.parametrize("fault", ["authors", "rights", "kind", "HTTP", "span", "Canadian_source", "extra_source", "active", "review_pin", "base_registry"])
def test_private_registry_tamper_rejected_before_output(local_builder, private_custody, fault):
    module, root = local_builder
    registry = read(root / REGISTRY)
    source = registry["sources"][0]
    if fault == "authors": source["authors"] = ["Unknown"]
    elif fault == "rights": source["rights"] = "free_to_read"
    elif fault == "kind": source["snapshot_kind"] = "native_article_permissions"
    elif fault == "HTTP": source["original_http_response_sha256"] = "0" * 64
    elif fault == "span": source["locators"][0]["span_sha256"] = "0" * 64
    elif fault == "Canadian_source": source["jurisdiction"] = "Canada"
    elif fault == "extra_source": registry["sources"].append(source)
    elif fault == "active": registry["activation"] = "startup"
    elif fault == "review_pin": registry["independent_review_sha256"] = "0" * 64
    else: registry["base_registry_path"] = "data/manifests/production_foundations_sources_v1.json"
    (root / REGISTRY).write_text(json.dumps(registry))
    with pytest.raises(ValueError): rebuild(local_builder, private_custody)
    assert not (root / "build").exists()


@pytest.mark.parametrize("fault", ["text", "inputs", "method", "decisive", "gold", "single_source", "training", "missing_card"])
def test_private_seed_tamper_rejected_before_output(local_builder, private_custody, fault):
    module, root = local_builder
    items = rows(root / SEED)
    item = items[0]
    if fault == "text": item["text"] += " Universal field target."
    elif fault == "inputs": item["required_context"] = {"all_inputs_mandatory": True}
    elif fault == "method": item["method_scope"]["method_ids"] = ["enterprise_budget"]
    elif fault == "decisive": item["retrieval_policy"] = "decisive"
    elif fault == "gold": item["answer_rubric"] = ["fixture-only forbidden content"]
    elif fault == "single_source": item["supporting_source_ids"] = item["supporting_source_ids"][:1]
    elif fault == "training": item["training_allowed"] = True
    else: items.pop()
    (root / SEED).write_text("".join(json.dumps(item) + "\n" for item in items))
    with pytest.raises(ValueError): rebuild(local_builder, private_custody)
    assert not (root / "build").exists()


@pytest.mark.parametrize("fault", ["raw", "selected_text", "normalizer", "symlink", "missing", "bad_review"])
def test_private_custody_drift_or_escape_is_rejected(local_builder, private_custody, fault):
    module, root = local_builder
    original, review = private_custody
    packet = root / "owned-test-custody"
    packet.mkdir()
    for source in original.iterdir():
        if source.is_file(): (packet / source.name).write_bytes(source.read_bytes())
    name = {"raw": "soil-density.dom-fragments.json", "selected_text": "soil-density.selected-methods.txt",
        "normalizer": "verify_bindings.py", "symlink": "soil-density.dom-fragments.json",
        "missing": "parent-metadata.dom-fragments.json", "bad_review": "source-manifest.json"}[fault]
    file = packet / name
    if fault == "symlink":
        file.unlink()
        file.symlink_to(original / name)
    elif fault == "missing": file.unlink()
    else: file.write_bytes(file.read_bytes() + b" ")
    if fault == "bad_review":
        review = root / "owned-bad-review.json"
        review.write_text("{}")
    with pytest.raises(ValueError): rebuild(local_builder, (packet, review))
    assert not (root / "build").exists()
