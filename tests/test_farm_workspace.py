"""Farm migration, isolation, retained identities and optimistic edits."""
import importlib

from fastapi.testclient import TestClient
import pytest

from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings

OWNER = {"X-Agronomy-User-Email": "farm-owner@example.test"}
OTHER = {"X-Agronomy-User-Email": "other-grower@example.test"}


@pytest.fixture
def settings(tmp_path, monkeypatch):
    module = importlib.import_module("agronomy_agent.server.app")
    monkeypatch.setattr(module, "intersect_region_layers", lambda **_: {"intersections": [], "feature_collection": {"features": []}, "errors": [], "queried_layers": []})
    return build_settings(db_path=tmp_path / "workspace.sqlite3", artifact_root=tmp_path / "artifacts", network_mode="offline")


def create_field(client, geometry=None):
    response = client.post("/api/demo/fields", headers=OWNER, json={"name": "North quarter", "field": {"crop": "Wheat"}, "geometry": geometry or {"kind": "none"}})
    assert response.status_code == 201, response.text
    return response.json()["field"]


def test_farms_and_explicit_season_survive_reload_without_promoting_legacy_crop(settings):
    with TestClient(create_app(settings)) as client:
        field = create_field(client)
        response = client.get("/api/farms/overview?season=2026", headers=OWNER)
        assert response.status_code == 200, response.text
        row = response.json()["fields"][0]
        assert row["farm_id"] is None and row["crop"] is None
        assert row["legacy_undated_crop"] == "Wheat"
        assert row["boundary_area_m2"] is None
        assert response.json()["coverage"]["unknown_area_count"] == 1
        farm = client.post("/api/farms", headers=OWNER, json={"name": "Prairie Farm"}).json()
        move = client.patch(f"/api/fields/{field['id']}/farm", headers=OWNER, json={"farm_id": farm["id"], "expected_revision": 0})
        assert move.status_code == 200, move.text
        season = client.put(f"/api/fields/{field['id']}/seasons/2026", headers=OWNER, json={"crop": "Canola", "expected_revision": 0})
        assert season.status_code == 200, season.text
    with TestClient(create_app(settings)) as client:
        result = client.get(f"/api/farms/{farm['id']}/overview?season=2026", headers=OWNER).json()
        assert len(result["fields"]) == 1
        assert result["fields"][0]["id"] == field["id"]
        assert result["fields"][0]["crop"] == "Canola"
        assert client.get(f"/api/fields/{field['id']}/summary?season=2025", headers=OWNER).json()["crop"] is None
        assert client.get("/api/demo/fields", headers=OWNER).json()["fields"][0]["crop"] == "Wheat"


def test_cross_workspace_assignment_and_stale_updates_are_rejected(settings):
    with TestClient(create_app(settings)) as client:
        field = create_field(client)
        foreign_farm = client.post("/api/farms", headers=OTHER, json={"name": "Other farm"}).json()
        assert client.patch(f"/api/fields/{field['id']}/farm", headers=OWNER, json={"farm_id": foreign_farm["id"], "expected_revision": 0}).status_code == 404
        assert client.get(f"/api/fields/{field['id']}/summary", headers=OTHER).status_code in {403, 404}
        farm = client.post("/api/farms", headers=OWNER, json={"name": "Home"}).json()
        path = f"/api/fields/{field['id']}/farm"
        assert client.patch(path, headers=OWNER, json={"farm_id": farm["id"], "expected_revision": 0}).status_code == 200
        assert client.patch(path, headers=OWNER, json={"farm_id": None, "expected_revision": 0}).status_code == 409
        path = f"/api/fields/{field['id']}/seasons/2026"
        assert client.put(path, headers=OWNER, json={"crop": "Barley", "expected_revision": 0}).status_code == 200
        assert client.put(path, headers=OWNER, json={"crop": "Wheat", "expected_revision": 0}).status_code == 409
        assert client.patch(f"/api/farms/{farm['id']}", headers=OWNER, json={"name": "Home", "archived": True, "expected_revision": 1}).status_code == 409


def test_geometry_revisions_and_field_edit_precondition(settings):
    with TestClient(create_app(settings)) as client:
        field = create_field(client, {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}})
        path = f"/api/demo/fields/{field['id']}"
        body = {"name": "Renamed", "field": {"crop": "Wheat"}, "geometry": field["geometry"], "expectedUpdatedAt": field["updatedAt"]}
        first = client.patch(path, headers=OWNER, json=body)
        assert first.status_code == 200, first.text
        assert client.patch(path, headers=OWNER, json=body).status_code == 409
        summary = client.get(f"/api/fields/{field['id']}/summary", headers=OWNER).json()
        assert len(summary["geometry_revisions"]) == 1
        body["expectedUpdatedAt"] = first.json()["field"]["updatedAt"]
        body["geometry"] = {"kind": "point", "point": {"lat": 53.4, "lon": -113.6}}
        assert client.patch(path, headers=OWNER, json=body).status_code == 200
        summary = client.get(f"/api/fields/{field['id']}/summary", headers=OWNER).json()
        assert len(summary["geometry_revisions"]) == 2
        assert summary["geometry_revisions"][0]["supersedes_id"] == summary["geometry_revisions"][1]["id"]
        assert summary["boundary_area_m2"] is None


def test_overlapping_boundaries_are_not_double_counted(settings):
    geometry = {"kind": "polygon", "points": [{"lat": 53.3, "lon": -113.6}, {"lat": 53.3, "lon": -113.59}, {"lat": 53.31, "lon": -113.59}, {"lat": 53.31, "lon": -113.6}], "acres": 1}
    with TestClient(create_app(settings)) as client:
        create_field(client, geometry)
        create_field(client, geometry)
        create_field(client, {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}})
        coverage = client.get("/api/farms/overview", headers=OWNER).json()["coverage"]
        assert coverage["boundary_count"] == 2 and coverage["unknown_area_count"] == 1
        assert coverage["boundary_area_m2"] == pytest.approx(coverage["summed_boundary_area_m2"] / 2)
        assert coverage["overlapping_area_m2"] == pytest.approx(coverage["boundary_area_m2"])


def test_complete_geometry_and_holes_survive_field_save_reload(settings):
    exterior = [[-113.6, 53.3], [-113.59, 53.3], [-113.59, 53.31], [-113.6, 53.31], [-113.6, 53.3]]
    hole = [[-113.598, 53.302], [-113.595, 53.302], [-113.595, 53.305], [-113.598, 53.305], [-113.598, 53.302]]
    other = [[-113.58, 53.3], [-113.57, 53.3], [-113.57, 53.31], [-113.58, 53.31], [-113.58, 53.3]]
    complete = {"type": "MultiPolygon", "coordinates": [[exterior, hole], [other]]}
    with TestClient(create_app(settings)) as client:
        field = create_field(client, {"kind": "geojson", "geojson": complete, "acres": 999999})
        assert field["geometry"]["geojson"] == complete
        assert 0 < field["geometry"]["acres"] < 1000
        assert client.get("/api/demo/fields", headers=OWNER).json()["fields"][0]["geometry"] == field["geometry"]
        summary = client.get(f"/api/fields/{field['id']}/summary", headers=OWNER).json()
        assert summary["geometry"]["geojson"] == complete
        assert summary["boundary_area_m2"] == pytest.approx(field["geometry"]["acres"] * 4046.8564224)


def test_record_bundle_is_atomic_idempotent_and_season_bound(settings):
    import uuid
    with TestClient(create_app(settings)) as client:
        field = create_field(client)
        path = f"/api/fields/{field['id']}/records"
        body = {"operation_id": str(uuid.uuid4()), "events": [
            {"event_type": "observation", "occurred_at": "2025-10-01T12:00:00Z", "payload": {"season": 2026, "summary": "Synthetic fall seeding observation"}},
            {"event_type": "note", "payload": {"season": 2026, "summary": "Synthetic follow-up"}},
        ]}
        first = client.post(path, headers=OWNER, json=body)
        assert first.status_code == 201, first.text
        assert client.post(path, headers=OWNER, json=body).json()["events"] == first.json()["events"]
        body["events"][0]["payload"]["summary"] = "Changed"
        assert client.post(path, headers=OWNER, json=body).status_code == 409
        records = client.get(f"/api/records?field_id={field['id']}&season=2026", headers=OWNER).json()
        assert records["total"] == 2
        assert client.get(f"/api/records?field_id={field['id']}&season=2025", headers=OWNER).json()["total"] == 0
        assert client.get(f"/api/records?field_id={field['id']}", headers=OTHER).status_code in {403, 404}
        # A late invalid correction must roll back the earlier event in the bundle.
        invalid = {"operation_id": str(uuid.uuid4()), "events": [body["events"][0], {"event_type": "correction", "corrects_event_id": str(uuid.uuid4()), "payload": {"summary": "No such record"}}]}
        assert client.post(path, headers=OWNER, json=invalid).status_code == 409
        assert client.get(f"/api/records?field_id={field['id']}", headers=OWNER).json()["total"] == 2
        assert client.get(f"/api/demo/fields/{field['id']}/events", headers=OWNER).json()["chain"]["valid"] is True


def test_field_creation_farm_assignment_and_retry_are_atomic(settings):
    import uuid
    with TestClient(create_app(settings)) as client:
        farm = client.post("/api/farms", headers=OWNER, json={"name": "Home"}).json()
        body = {"name": "North", "field": {}, "geometry": {"kind": "none"}, "farmId": farm["id"], "operationId": str(uuid.uuid4())}
        first = client.post("/api/demo/fields", headers=OWNER, json=body)
        assert first.status_code == 201, first.text
        second = client.post("/api/demo/fields", headers=OWNER, json=body)
        assert second.json()["field"]["id"] == first.json()["field"]["id"]
        assert len(client.get(f"/api/farms/{farm['id']}/overview", headers=OWNER).json()["fields"]) == 1
        body["farmId"] = str(uuid.uuid4()); body["operationId"] = str(uuid.uuid4())
        assert client.post("/api/demo/fields", headers=OWNER, json=body).status_code == 404
        assert len(client.get("/api/demo/fields", headers=OWNER).json()["fields"]) == 1


def test_enrichment_partial_results_cache_and_receipt_integrity(settings, monkeypatch):
    from agronomy_agent.server.services import field_enrichment
    calls = []
    def source(name, field, mode):
        calls.append(name)
        if name == "soil":
            raise RuntimeError("synthetic provider failure")
        return {"availability": "partial", "observed_at": "2026-10-31", "role": "regional_prior", "values": {"tool": "nasa_power_daily", "status": "partial_available", "observed_day_count": 2}}
    monkeypatch.setattr(field_enrichment, "run_source", source)
    with TestClient(create_app(settings)) as client:
        field = create_field(client, {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}})
        path = f"/api/fields/{field['id']}/enrichment-jobs"
        first = client.post(path, headers=OWNER, json={"sources": ["weather", "soil"]})
        assert first.status_code == 202, first.text
        job = client.get(f"/api/enrichment-jobs/{first.json()['id']}", headers=OWNER).json()
        assert job["status"] == "partial"
        summary = client.get(f"/api/fields/{field['id']}/summary", headers=OWNER).json()
        assert summary["source_status"]["weather"]["availability"] == "partial"
        assert summary["source_status"]["soil"]["availability"] == "provider_error"
        assert len(summary["source_status"]["weather"]["receipt_sha256"]) == 64
        client.post(path, headers=OWNER, json={"sources": ["weather"]})
        assert calls.count("weather") == 1
        assert client.get(f"/api/enrichment-jobs/{job['id']}", headers=OTHER).status_code in {403, 404}
        with client.app.state.trace_store._cursor() as cursor:
            cursor.execute("UPDATE field_context_snapshots SET result_json='{}' WHERE source_id='weather'")
        assert client.get(f"/api/fields/{field['id']}/summary", headers=OWNER).json()["source_status"]["weather"]["availability"] == "integrity_failed"


def test_enrichment_late_results_keep_original_geometry_scope(settings, monkeypatch):
    from agronomy_agent.server.services import field_enrichment
    from agronomy_agent.server.storage import field_context_store
    with TestClient(create_app(settings)) as client:
        saved = create_field(client, {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}})
        store = client.app.state.trace_store
        field = store.get_phase4_field_context(saved["id"])
        job, fresh = field_context_store.queue_job(store, field, ["weather"], "offline")
        same, fresh_again = field_context_store.queue_job(store, field, ["weather"], "offline")
        assert fresh and not fresh_again and same["id"] == job["id"]
        def slow_source(*args):
            current = store.get_phase4_field_context(saved["id"])
            metadata = current["metadata"]
            metadata["open_agronomy_agent"]["geometry"]["point"]["lat"] = 53.4
            store.update_phase4_field_context(field_context_id=saved["id"], actor_user_id=current["created_by_user_id"], payload={"metadata": metadata})
            return {"availability": "available", "values": {"synthetic": True}}
        monkeypatch.setattr(field_enrichment, "run_source", slow_source)
        field_enrichment.execute_job(store, settings, job["id"])
        assert field_context_store.get_job(store, job["id"])["status"] == "superseded"
        summary = client.get(f"/api/fields/{saved['id']}/summary", headers=OWNER).json()
        assert summary["source_status"]["weather"]["availability"] == "not_requested"
        with store._cursor() as cursor:
            assert cursor.execute("SELECT COUNT(*) FROM field_context_snapshots WHERE field_id=?", (saved["id"],)).fetchone()[0] == 1


def test_source_dispatch_uses_actual_adapter_contract_and_unknown_jurisdiction(settings, monkeypatch):
    from agronomy_agent.server.services import field_enrichment
    calls = []
    monkeypatch.setattr(field_enrichment, "run_local_tool", lambda name, payload, **kw: calls.append((name, payload, kw)) or {"status": "blocked_offline"})
    field = {"metadata": {"open_agronomy_agent": {"geometry": {"kind": "point", "point": {"lat": 53.3, "lon": -113.6}}}}, "country": None}
    assert field_enrichment.run_source("weather", field, "offline")["availability"] == "offline"
    assert calls[0][1]["lat"] == 53.3 and calls[0][1]["lon"] == -113.6
    assert calls[0][2]["network_mode"] == "offline"
    assert field_enrichment.run_source("soil", field, "online")["availability"] == "jurisdiction_unknown"
    assert len(calls) == 1


def test_mapped_location_requires_verified_complete_coverage_and_explicit_confirmation(settings, monkeypatch):
    from agronomy_agent.server.services import field_location
    source = {'status': 'verified', 'database_sha256': 'a' * 64}
    response = {'source_integrity': {field_location.LAYER: source}, 'errors': [],
        'intersections': [{'province_name': 'Alberta', 'coverage_estimate': 1., 'coverage_support_type': 'point_membership', 'source_url': 'https://www.statcan.gc.ca/'}]}
    def query(**kwargs):
        assert kwargs['network_mode'] == 'offline'
        assert kwargs['layer_ids'] == [field_location.LAYER]
        return response
    monkeypatch.setattr(field_location, 'intersect_region_layers', query)
    with TestClient(create_app(settings)) as client:
        field = create_field(client, {'kind': 'point', 'point': {'lat': 53.3, 'lon': -113.6}})
        url = f"/api/fields/{field['id']}"
        assert client.get(url + '/location-suggestions', headers=OTHER).status_code == 403
        suggestions = client.get(url + '/location-suggestions', headers=OWNER).json()
        assert suggestions['status'] == 'suggested'
        assert client.get(url + '/summary', headers=OWNER).json()['country'] is None
        body = {'suggestion_id': suggestions['candidates'][0]['id'], 'expected_updated_at': field['updatedAt']}
        assert client.post(url + '/confirm-location', headers=OTHER, json=body).status_code == 403
        assert client.post(url + '/confirm-location', headers=OWNER, json={**body, 'expected_updated_at': 'old'}).status_code == 409
        accepted = client.post(url + '/confirm-location', headers=OWNER, json=body)
        assert accepted.status_code == 200, accepted.text
        summary = client.get(url + '/summary?season=2026', headers=OWNER).json()
        assert summary['country'] == 'Canada' and summary['crop'] is None
        assert summary['legacy_undated_crop'] == 'Wheat'
        assert summary['location_confirmation']['suggestion']['receipt']['source_integrity'] == source
        # A source change invalidates the displayed candidate before any write.
        source['database_sha256'] = 'b' * 64
        body['expected_updated_at'] = summary['updated_at']
        assert client.post(url + '/confirm-location', headers=OWNER, json=body).status_code == 409


@pytest.mark.parametrize('integrity,coverage,expected', [
    ('integrity_failed', 1., 'integrity_failed'), ('not_installed', 1., 'not_installed'),
    ('verified', .6, 'ambiguous'), ('verified', 0., 'no_match'),
])
def test_location_uncertainty_never_selects_a_country(settings, monkeypatch, integrity, coverage, expected):
    from agronomy_agent.server.services import field_location
    monkeypatch.setattr(field_location, 'intersect_region_layers', lambda **_: {
        'source_integrity': {field_location.LAYER: {'status': integrity}}, 'errors': [],
        'intersections': [{'province_name': 'Alberta', 'coverage_estimate': coverage}]})
    with TestClient(create_app(settings)) as client:
        field = create_field(client, {'kind': 'point', 'point': {'lat': 49., 'lon': -110.}})
        url = f"/api/fields/{field['id']}"
        result = client.get(url + '/location-suggestions', headers=OWNER).json()
        assert result['status'] == expected
        assert not any(item['confirmable'] for item in result['candidates'])
        assert client.get(url + '/summary', headers=OWNER).json()['country'] is None


def test_new_field_crop_is_explicitly_season_bound_and_retry_is_atomic(settings):
    from uuid import uuid4
    with TestClient(create_app(settings)) as client:
        body = {"name": "New dated field", "field": {"crop": "Wheat"}, "season": 2025,
                "geometry": {"kind": "none"}, "operationId": str(uuid4())}
        created = client.post("/api/demo/fields", headers=OWNER, json=body)
        assert created.status_code == 201, created.text
        field_id = created.json()["field"]["id"]
        assert client.post("/api/demo/fields", headers=OWNER, json=body).json()["field"]["id"] == field_id
        result = client.get(f"/api/fields/{field_id}/summary?season=2025", headers=OWNER).json()
        assert result["crop"] == "Wheat" and result["legacy_undated_crop"] is None
        assert len(result["seasons"]) == 1
        assert client.get(f"/api/fields/{field_id}/summary?season=2026", headers=OWNER).json()["crop"] is None
        assert client.post("/api/demo/fields", headers=OWNER, json={**body, "season": True}).status_code == 422
        assert len(client.get("/api/demo/fields", headers=OWNER).json()["fields"]) == 1


@pytest.mark.parametrize('column,value', [('expires_at', '2099-01-01T00:00:00+00:00'), ('availability', 'no_match'), ('result_json', 'broken JSON')])
def test_retained_field_context_compiler_binds_season_freshness_and_receipt(settings, monkeypatch, column, value):
    from agronomy_agent.server.services import field_enrichment
    from agronomy_agent.server.services.chat_service import _with_stored_field_data, _safe_field_context_summary, _combined_verification_evidence
    from agronomy_agent.answer_verifier import assess_claim_risk
    from agronomy_agent.server.services.field_context_compiler import compile_field_context
    monkeypatch.setattr(field_enrichment, 'run_source', lambda *args: {'availability': 'partial', 'values': {
        'tool': 'nasa_power_daily', 'status': 'partial_available', 'source': 'https://example.test/synthetic',
        'parameter_summary': {'T2M': {'mean': 12.5}}, 'requested_day_count': 7, 'observed_day_count': 2,
        'available_days_by_parameter': {'T2M': 2}, 'observation_start': '2026-10-30', 'observation_end': '2026-10-31'}})
    with TestClient(create_app(settings)) as client:
        saved = create_field(client, {'kind': 'point', 'point': {'lat': 53.3, 'lon': -113.6}})
        store = client.app.state.trace_store
        field_id = saved['id']
        client.post(f'/api/fields/{field_id}/enrichment-jobs', headers=OWNER, json={'sources': ['weather']})
        auth = {'field_context_id': field_id, 'field_access_authorized': True, 'field_season': 2026}
        supplied = {'crop': 'Injected crop', 'retained_public_context': [{'name': 'untrusted'}]}
        projected = _with_stored_field_data(store, session_context=auth, field_context=supplied)
        assert projected['crop'] is None and projected['season_crop_status'] == 'unknown'
        compiled = compile_field_context(projected, [], safe_field_summary=_safe_field_context_summary)
        retained = compiled['receipt']['retained_context'][0]
        assert retained['snapshot_id'] and retained['receipt_sha256'] and retained['fetched_at']
        assert '2 of 7 requested days' in compiled['prompt']
        assert 'Injected crop' not in compiled['prompt']
        answer = 'Weather window UTC 2026-10-30 to 2026-10-31; 2 of 7 requested days. Mean temperature 12.5 °C.'
        evidence = _combined_verification_evidence(None, projected, compiled)
        assert not assess_claim_risk(answer, question='List retained weather.', evidence_text=evidence).unsupported_numbers
        assert assess_claim_risk('Mean temperature 998 °C.', question='List retained weather.', evidence_text=evidence).unsupported_numbers
        assert 'retained_public_context' not in _with_stored_field_data(store, session_context={}, field_context=supplied)
        with store._cursor() as cursor:
            cursor.execute(f'UPDATE field_context_snapshots SET {column}=? WHERE field_id=?', (value, field_id))
        projected = _with_stored_field_data(store, session_context=auth, field_context=supplied)
        assert 'retained_public_context' not in projected
        rejected = compile_field_context(projected, [], safe_field_summary=_safe_field_context_summary)
        assert assess_claim_risk(answer, question='List retained weather.', evidence_text=_combined_verification_evidence(None, projected, rejected)).unsupported_numbers
        summary = client.get(f'/api/fields/{field_id}/summary', headers=OWNER).json()
        assert summary['source_status']['weather']['availability'] == 'integrity_failed'
        overview = client.get('/api/farms/overview', headers=OWNER).json()
        assert overview['fields'][0]['context_status']['weather']['availability'] == 'integrity_failed'


def test_multipart_enrichment_preserves_boundary_and_explains_source_limit(monkeypatch):
    from copy import deepcopy
    from agronomy_agent.server.services import field_enrichment
    geometry = {'kind': 'geojson', 'geojson': {'type': 'MultiPolygon', 'coordinates': [[[[0, 0], [1, 0], [1, 1], [0, 0]]], [[[2, 0], [3, 0], [3, 1], [2, 0]]]]}}
    field = {'metadata': {'open_agronomy_agent': {'geometry': geometry}}}
    original = deepcopy(field)
    monkeypatch.setattr(field_enrichment, 'search_field_imagery', lambda *a, **k: pytest.fail('unsupported shape must not be submitted'))
    result = field_enrichment.run_source('imagery', field, 'offline')
    assert result['availability'] == 'unsupported_geometry'
    assert 'multipart boundary is retained unchanged' in result['message']
    assert field == original


@pytest.mark.parametrize('system', ['intercrop', 'sequence', 'separate_areas'])
def test_structured_crops_survive_restart_and_enter_only_authorized_season_context(settings, system):
    from agronomy_agent.server.services.chat_service import _with_stored_field_data, _safe_field_context_summary
    from agronomy_agent.server.services.field_context_compiler import compile_field_context
    crops = [{'crop': 'Pea', 'cultivar': 'Synthetic A'}, {'crop': 'Barley', 'cultivar': None}]
    with TestClient(create_app(settings)) as client:
        field = create_field(client)
        url = f"/api/fields/{field['id']}/seasons/2026"
        response = client.put(url, headers=OWNER, json={'expected_revision': 0, 'crops': crops, 'crop_system': system})
        assert response.status_code == 200, response.text
        assert response.json()['crop'] == 'Pea + Barley'
        assert client.put(url, headers=OTHER, json={'expected_revision': 1, 'crops': []}).status_code in {403, 404}
        assert client.put(url, headers=OWNER, json={'expected_revision': 0, 'crop': 'Canola'}).status_code == 409
    with TestClient(create_app(settings)) as client:
        summary = client.get(f"/api/fields/{field['id']}/summary?season=2026", headers=OWNER).json()
        assert summary['seasons'][0]['crops'] == crops
        assert summary['seasons'][0]['crop_system'] == system
        context = _with_stored_field_data(client.app.state.trace_store,
            session_context={'field_context_id': field['id'], 'field_access_authorized': True, 'field_season': 2026},
            field_context={'field_season_lineage': {'crops': [{'crop': 'Injected'}]}})
        compiled = compile_field_context(context, [], safe_field_summary=_safe_field_context_summary)
        assert system in compiled['prompt'] and 'Synthetic A' in compiled['prompt']
        assert 'Injected' not in compiled['prompt']
        assert client.get(f"/api/fields/{field['id']}/summary?season=2025", headers=OWNER).json()['crop'] is None


@pytest.mark.parametrize('payload', [
    {'crops': [{'crop': 'Pea'}, {'crop': 'Barley'}]},
    {'crops': [{'crop': 'Pea'}, {'crop': 'pea'}], 'crop_system': 'intercrop'},
    {'crops': [{'crop': 'Pea'}], 'crop_system': 'sequence'},
    {'crops': [{'crop': 'Pea'}], 'crop': 'Wheat'},
    {'crop': 'Wheat', 'crop_system': 'intercrop'},
])
def test_ambiguous_crop_system_writes_are_rejected(settings, payload):
    with TestClient(create_app(settings)) as client:
        field = create_field(client)
        response = client.put(f"/api/fields/{field['id']}/seasons/2026", headers=OWNER,
            json={'expected_revision': 0, **payload})
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("status_key", ["sampling_time_status", "observation_time_status"])
def test_unknown_record_time_never_becomes_season_context(settings, status_key):
    import uuid
    from datetime import datetime, timezone
    from agronomy_agent.server.services.chat_service import _with_stored_field_events
    season = datetime.now(timezone.utc).year
    with TestClient(create_app(settings)) as client:
        field = create_field(client)
        events = [
            {"event_type": "note", "payload": {"summary": "Undated source note"}, "provenance": {status_key: "unknown"}},
            {"event_type": "note", "payload": {"summary": "Confirmed season note", "season": season}, "provenance": {status_key: "unknown"}},
            {"event_type": "note", "occurred_at": f"{season}-06-01T12:00:00Z", "payload": {"summary": "Dated source note"}},
        ]
        response = client.post(f"/api/fields/{field['id']}/records", headers=OWNER,
            json={"operation_id": str(uuid.uuid4()), "events": events})
        assert response.status_code == 201, response.text
        timeline = client.get(f"/api/records?field_id={field['id']}", headers=OWNER).json()
        assert {event['payload']['summary']: event['season_binding'] for event in timeline['events']} == {
            "Undated source note": "unknown", "Confirmed season note": "explicit", "Dated source note": "observation_year"}
        scoped = client.get(f"/api/records?field_id={field['id']}&season={season}", headers=OWNER).json()
        assert scoped['total'] == 2
        overview = client.get(f"/api/farms/overview?season={season}", headers=OWNER).json()
        assert overview['fields'][0]['record_count'] == 2
        projected = _with_stored_field_events(store=client.app.state.trace_store,
            session_context={'field_context_id': field['id'], 'field_access_authorized': True, 'field_season': season}, field_context={})
        assert len(projected['field_history']['events']) == 2
        assert all('Undated source note' not in event['summary'] for event in projected['field_history']['events'])
