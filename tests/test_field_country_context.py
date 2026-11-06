from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.query_context import analyze_query_context, filter_docs_for_query
from agronomy_agent.server.app import create_app
from agronomy_agent.server.services import chat_service
from agronomy_agent.server.settings import build_settings


OWNER = {"X-Agronomy-User-Email": "country-context@example.test"}
PROVIDER_WRAPPERS = (
    "_call_nrcs_soil_survey_for_field", "_call_nasa_power",
    "_call_daymet_single_pixel", "_call_openet_point_timeseries",
    "_call_cropland_data_layer_for_field", "_call_nass_quickstats",
    "_call_cansis_soil_landscapes", "_call_canada_et_source_lane",
    "_call_aafc_annual_crop_inventory", "_call_statcan_field_crop_statistics",
    "_call_health_canada_pmra", "_call_epa_ppls",
)


@pytest.fixture
def client(tmp_path):
    settings = build_settings(
        db_path=tmp_path / "country.sqlite3", artifact_root=tmp_path / "artifacts",
        network_mode="offline",
    )
    return TestClient(create_app(settings))


def _saved_field(client, jurisdiction):
    response = client.post("/api/demo/fields", headers=OWNER, json={
        "name": "Synthetic crop field", "field": {"crop": "corn", "jurisdiction": jurisdiction},
        "geometry": {"kind": "none"},
    })
    assert response.status_code == 201, response.text
    return response.json()["field"]["field_context_id"]


@pytest.mark.parametrize("jurisdiction,expected", [
    ("Canada", "Canada"), ("SK", "Canada"), ("Saskatchewan", "Canada"),
    ("Québec", "Canada"), ("QC", "Canada"), ("CA-QC", "Canada"),
    ("PEI", "Canada"), ("NT", "Canada"),
    ("United States", "United States"), ("US", "United States"),
    ("U.S.A.", "United States"), ("Iowa", "United States"),
    ("IA", "United States"), ("US-IA", "United States"), ("CA", "United States"),
    ("Atlantis", None), ("Mexico", None), ("", None),
])
def test_saved_field_country_uses_recognized_jurisdiction_without_us_fallback(client, jurisdiction, expected):
    field_id = _saved_field(client, jurisdiction)
    record = client.app.state.trace_store.get_phase4_field_context(field_id)
    assert record["country"] == expected
    assert record["province_state"] == (jurisdiction or None)


@pytest.mark.parametrize("jurisdiction,expected", [("SK", "Canada"), ("Québec", "Canada"), ("Atlantis", None)])
def test_legacy_saved_default_us_country_is_not_reused_or_silently_rewritten(client, jurisdiction, expected):
    field_id = _saved_field(client, jurisdiction)
    store = client.app.state.trace_store
    record = store.get_phase4_field_context(field_id)
    store.update_phase4_field_context(
        field_context_id=field_id, actor_user_id=record["created_by_user_id"], payload={"country": "United States"},
    )
    created = client.post("/api/sessions", headers=OWNER, json={
        "title": "Synthetic legacy field", "consent": {}, "context": {"field_context_id": field_id},
    })
    assert created.status_code == 200, created.text
    authorized = created.json()["context"]["field_context"]
    assert authorized["country"] == expected
    assert chat_service._field_country_from_context(authorized) == expected
    assert store.get_phase4_field_context(field_id)["country"] == "United States"


@pytest.mark.parametrize("jurisdiction,supplied,expected,code", [
    ("SK", {"country": "CAN", "country_code": "ca"}, "Canada", "CA"),
    ("Québec", {}, "Canada", "CA"),
    ("Iowa", {"country": "USA", "country_code": "US"}, "United States", "US"),
    ("IA", {}, "United States", "US"),
    ("CA", {}, "United States", "US"),
    ("Atlantis", {}, None, None),
    ("", {}, None, None),
    ("", {"jurisdiction": "IA", "state": "Iowa", "region": "Iowa"}, None, None),
    ("Saskatchewan", {"province": "Iowa", "state_alpha": "IA"}, "Canada", "CA"),
])
def test_turn_authorization_binds_country_and_location_aliases_to_saved_field(
    client, monkeypatch, jurisdiction, supplied, expected, code,
):
    field_id = _saved_field(client, jurisdiction)
    session = client.post("/api/sessions", headers=OWNER, json={
        "title": "Synthetic regional context", "consent": {}, "context": {"field_context_id": field_id},
    }).json()
    captured = {}

    def capture_turn(**kwargs):
        captured.update(kwargs["session_context"])
        return {"operation_replayed": True, "turn_id": "synthetic-capture",
                "turn": {"answer": "Synthetic capture; no model or provider executed.", "trace": {}}}

    app_module = importlib.import_module("agronomy_agent.server.app")
    monkeypatch.setattr(app_module, "run_turn", capture_turn)
    response = client.post(f"/api/sessions/{session['session_id']}/turns", headers=OWNER, json={
        "message": "Check regional crop context.", "mode": "agronomic_rag",
        "session_context": {"field_context_id": field_id, "field_context": supplied},
    })
    assert response.status_code == 200, response.text
    authorized = captured["field_context"]
    assert captured["field_access_authorized"] is True
    assert authorized["country"] == expected
    assert authorized["country_code"] == code
    assert authorized["province_state"] == (jurisdiction or None)
    assert authorized["jurisdiction"] == (jurisdiction or None)
    assert "province" not in authorized and "state_alpha" not in authorized
    assert analyze_query_context("Check regional crop context.", authorized).country == {
        "Canada": "canada", "United States": "united states",
    }.get(expected)
    assert chat_service._field_country_from_context(authorized) == expected
    if jurisdiction == "CA":
        fit = filter_docs_for_query(
            [_crop_rotation_doc("california", "California"), _crop_rotation_doc("canada", "Canada")],
            analyze_query_context("Explain corn crop rotation guidance.", authorized),
            primary_intent="crop_management",
        )
        assert [doc.doc_id for doc in fit.docs] == ["california"]
        assert fit.dropped == ({"doc_id": "canada", "reason": "jurisdiction_mismatch"},)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("jurisdiction,supplied_country", [
    ("Saskatchewan", {"country": "US"}), ("Iowa", {"country": "Canada"}),
    ("SK", {"country_code": "US"}), ("IA", {"country_code": "CA"}),
    ("Québec", {"country": "Mexico"}), ("Atlantis", {"country": "US"}),
])
def test_conflicting_client_country_is_rejected_before_either_turn_route(
    client, monkeypatch, stream, jurisdiction, supplied_country,
):
    field_id = _saved_field(client, jurisdiction)
    session = client.post("/api/sessions", headers=OWNER, json={
        "title": "Synthetic conflict", "consent": {}, "context": {"field_context_id": field_id},
    }).json()
    app_module = importlib.import_module("agronomy_agent.server.app")
    monkeypatch.setattr(app_module, "run_turn", lambda **kwargs: pytest.fail("Conflicting context reached execution"))
    endpoint = f"/api/sessions/{session['session_id']}/turns" + ("/stream" if stream else "")
    response = client.post(endpoint, headers=OWNER, json={
        "message": "Check crop context.", "mode": "agronomic_rag",
        "session_context": {"field_context_id": field_id, "field_context": supplied_country},
    })
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "field_context_snapshot_mismatch"
    assert detail["mismatch_fields"] == list(supplied_country)


@pytest.mark.parametrize("context,country,soil_wrapper,cover_wrapper", [
    ({"country": "United States", "state": "Iowa"}, "United States", "_call_nrcs_soil_survey_for_field", "_call_cropland_data_layer_for_field"),
    ({"country_code": "US", "jurisdiction": "US-IA"}, "United States", "_call_nrcs_soil_survey_for_field", "_call_cropland_data_layer_for_field"),
    ({"country": "Canada", "province": "SK"}, "Canada", "_call_cansis_soil_landscapes", "_call_aafc_annual_crop_inventory"),
    ({"jurisdiction": "Québec"}, "Canada", "_call_cansis_soil_landscapes", "_call_aafc_annual_crop_inventory"),
    ({"country_code": "CA"}, "Canada", "_call_cansis_soil_landscapes", "_call_aafc_annual_crop_inventory"),
])
def test_preflight_selects_native_country_wrappers_without_provider_execution(
    monkeypatch, context, country, soil_wrapper, cover_wrapper,
):
    selected = []

    def stub(name):
        def call(*args, **kwargs):
            selected.append(name)
            return {"name": name, "payload": {"status": "synthetic_not_executed"}}
        return call

    for name in PROVIDER_WRAPPERS:
        monkeypatch.setattr(chat_service, name, stub(name))
    context = {"crop": "corn", "geometry": {"type": "Point", "coordinates": [-93.5, 42.1]},
               "enable_public_adapters": True, "enable_public_source_cards": False, **context}
    assert chat_service._field_country_from_context(context) == country
    chat_service._run_public_adapter_preflight("Check soil and crop history.", context, network_mode="online")
    assert soil_wrapper in selected and cover_wrapper in selected
    assert ({"_call_cansis_soil_landscapes", "_call_aafc_annual_crop_inventory"} if country == "United States"
            else {"_call_nrcs_soil_survey_for_field", "_call_cropland_data_layer_for_field"}).isdisjoint(selected)


@pytest.mark.parametrize("context", [
    {}, {"jurisdiction": "Atlantis"}, {"country": "Mexico", "jurisdiction": "Sonora"},
    {"country": "Mexico", "jurisdiction": "Iowa"},
    {"country": "US", "jurisdiction": "Saskatchewan"},
    {"country": "Canada", "state": "Iowa"}, {"country": "CA", "country_code": "US"},
    {"state_alpha": "ZZ"},
])
def test_unknown_unsupported_or_conflicting_country_abstains_without_us_sources(monkeypatch, context):
    for name in PROVIDER_WRAPPERS:
        monkeypatch.setattr(chat_service, name, lambda *args, **kwargs: pytest.fail("Unknown-country provider called"))
    monkeypatch.setattr(chat_service, "_public_source_card_tasks", lambda *args: pytest.fail("Unknown-country source cards selected"))
    context = {"crop": "corn", "geometry": {"type": "Point", "coordinates": [-93.5, 42.1]},
               "enable_public_adapters": True, **context}
    records = chat_service._run_public_adapter_preflight("Check soil, label and conservation sources.", context, network_mode="online")
    assert len(records) == 1
    assert records[0]["name"] == "field_jurisdiction"
    assert records[0]["payload"]["status"] == "jurisdiction_unknown"
    assert records[0]["payload"]["external_request_attempted"] is False


def test_french_quebec_province_and_invalid_state_alias_are_coherent():
    assert chat_service._canadian_province_from_context({"jurisdiction": "Québec"}) == "QC"
    assert chat_service._state_alpha_from_context({"state_alpha": "ZZ"}) is None
    assert chat_service._state_alpha_from_context({"jurisdiction": "US-IA"}) == "IA"


def _crop_rotation_doc(doc_id, jurisdiction):
    return RetrievedDoc(
        doc_id=doc_id, title="Corn crop rotation guidance", text="Compare corn crop rotation practices and field records.",
        source="Synthetic extension fixture", score=1.0, tags=("crop rotation",), namespaces=("crop_management",),
        source_type="applied_guidance", allowed_roles=("farmer",), crops=("corn",),
        jurisdictions=(jurisdiction,),
    )


@pytest.mark.parametrize("code,expected,matching,other", [
    ("US", "united states", "United States", "Canada"),
    ("CA", "canada", "Canada", "United States"),
])
def test_country_code_only_controls_native_query_and_actual_document_eligibility(code, expected, matching, other):
    context = {"country_code": code, "crop": "corn"}
    signals = analyze_query_context("Explain corn crop rotation guidance.", context)
    assert signals.country == expected
    assert chat_service._field_country_from_context(context) == {"US": "United States", "CA": "Canada"}[code]
    fit = filter_docs_for_query(
        [_crop_rotation_doc("native", matching), _crop_rotation_doc("other-country", other)],
        signals, primary_intent="crop_management",
    )
    assert [doc.doc_id for doc in fit.docs] == ["native"]
    assert fit.dropped == ({"doc_id": "other-country", "reason": "jurisdiction_mismatch"},)


@pytest.mark.parametrize("context,country,matching,other", [
    ({"country_code": "US", "province_state": "US-IA"}, "united states", "Iowa", "North Dakota"),
    ({"country": "United States", "province_state": "US-CA"}, "united states", "California", "Iowa"),
    ({"country": "United States", "province_state": "CA"}, "united states", "California", "Iowa"),
    ({"country_code": "CA", "province_state": "CA-SK"}, "canada", "Saskatchewan", "Alberta"),
    ({"country": "Canada", "province_state": "CA-QC"}, "canada", "Quebec", "Ontario"),
])
def test_recognized_subdivision_accepts_matching_guidance_and_rejects_other_region(context, country, matching, other):
    context = {"crop": "corn", **context}
    signals = analyze_query_context("Explain corn crop rotation guidance.", context)
    assert signals.country == country
    assert chat_service._field_country_from_context(context) == {"canada": "Canada", "united states": "United States"}[country]
    fit = filter_docs_for_query(
        [_crop_rotation_doc("native", matching), _crop_rotation_doc("other-region", other)],
        signals, primary_intent="crop_management",
    )
    assert [doc.doc_id for doc in fit.docs] == ["native"]
    assert fit.dropped == ({"doc_id": "other-region", "reason": "jurisdiction_mismatch"},)


@pytest.mark.parametrize("country,unknown_subdivision,doc_region", [
    ("United States", "US-XX", "Iowa"), ("Canada", "CA-XX", "Saskatchewan"),
    ("United States", "US-SK", "Iowa"), ("Canada", "CA-IA", "Saskatchewan"),
])
def test_unrecognized_iso_subdivision_does_not_invent_specific_document_eligibility(country, unknown_subdivision, doc_region):
    signals = analyze_query_context(
        "Explain corn crop rotation guidance.",
        {"country": country, "province_state": unknown_subdivision, "crop": "corn"},
    )
    fit = filter_docs_for_query([_crop_rotation_doc("specific-region", doc_region)], signals, primary_intent="crop_management")
    assert fit.docs == ()
    assert fit.dropped == ({"doc_id": "specific-region", "reason": "jurisdiction_too_specific"},)


@pytest.mark.parametrize("context", [
    {"country": "Mexico", "country_code": "US"}, {"country": "Canada", "country_code": "US"},
    {"country_code": "MX"}, {"country_code": "US", "province_state": "CA-SK"},
    {"country": "Canada", "province_state": "US-IA"},
])
def test_country_code_cannot_resolve_unsupported_or_conflicting_explicit_country(context):
    assert analyze_query_context("Explain crop rotation guidance.", context).country is None
    assert chat_service._field_country_from_context(context) is None


def test_explicit_destination_intent_still_precedes_country_code_fallback():
    signals = analyze_query_context(
        "My Iowa farm found an Ontario guide. Explain corn crop rotation inputs for my farm.",
        {"country_code": "CA", "crop": "corn"},
    )
    assert signals.country == "united states"
    assert signals.target_jurisdictions == ("iowa",)


def test_us_province_state_alias_reaches_nass_wrapper_with_native_state_code(monkeypatch):
    captured = []

    def stub(name):
        return lambda *args, **kwargs: {"name": name, "payload": {"status": "synthetic_not_executed"}}

    for name in PROVIDER_WRAPPERS:
        monkeypatch.setattr(chat_service, name, stub(name))

    def capture_nass(crop, state_alpha, county_name, field_context, **kwargs):
        captured.append({"crop": crop, "state_alpha": state_alpha, "county_name": county_name})
        return {"name": "_call_nass_quickstats", "payload": {"status": "synthetic_not_executed"}}

    monkeypatch.setattr(chat_service, "_call_nass_quickstats", capture_nass)
    context = {
        "country_code": "US", "province_state": "US-IA", "crop": "corn", "county": "Story",
        "geometry": {"type": "Point", "coordinates": [-93.5, 42.1]},
        "enable_public_adapters": True, "enable_public_source_cards": False,
    }
    chat_service._run_public_adapter_preflight("Check regional yield and crop context.", context, network_mode="online")
    assert captured == [{"crop": "corn", "state_alpha": "IA", "county_name": "Story"}]
