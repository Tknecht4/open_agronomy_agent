"""Bulk import preserves complete source geometry, scopes commits, and retries once."""
import json
from uuid import uuid4

from fastapi.testclient import TestClient
from agronomy_agent.server.app import create_app
from test_farm_workspace import settings, OWNER, OTHER


def source_file():
    outer = [[-113.6,53.3],[-113.59,53.3],[-113.59,53.31],[-113.6,53.31],[-113.6,53.3]]
    hole = [[-113.598,53.302],[-113.598,53.304],[-113.596,53.304],[-113.596,53.302],[-113.598,53.302]]
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "west", "properties": {"name": "West", "crop": "Canola", "year": 2024}, "geometry": {"type": "Polygon", "coordinates": [outer, hole]}},
        {"type": "Feature", "id": "east", "properties": {"name": "East"}, "geometry": {"type": "MultiPolygon", "coordinates": [[[[x+.02,y] for x,y in outer]], [[[x+.04,y] for x,y in outer]]]}}
    ]}


def preview(client):
    result = client.post('/api/field-imports/preview', headers=OWNER, files={'file': ('fields.geojson', json.dumps(source_file()), 'application/geo+json')})
    assert result.status_code == 201, result.text
    return result.json()


def test_bulk_import_is_atomic_retryable_and_preserves_holes_parts_and_receipts(settings):
    with TestClient(create_app(settings)) as client:
        farm = client.post('/api/farms', headers=OWNER, json={'name':'Home'}).json()
        parsed = preview(client)
        body = {'operation_id': str(uuid4()), 'farm_id': farm['id'], 'jurisdiction': 'Alberta', 'features': [{'feature_id': item['id'], 'name': item['label']} for item in parsed['features']]}
        path = f"/api/field-imports/{parsed['id']}/commit"
        assert client.post(path, headers=OTHER, json=body).status_code == 404
        response = client.post(path, headers=OWNER, json=body)
        assert response.status_code == 200, response.text
        assert response.json() == client.post(path, headers=OWNER, json=body).json()
        rows = client.get(f"/api/farms/{farm['id']}/overview?season=2026", headers=OWNER).json()['fields']
        assert len(rows) == 2
        assert all(row['crop'] is None and row['legacy_undated_crop'] is None for row in rows)
        geometries = [row['geometry']['geojson'] for row in rows]
        assert any(g['type']=='Polygon' and len(g['coordinates'])==2 for g in geometries)
        assert any(g['type']=='MultiPolygon' and len(g['coordinates'])==2 for g in geometries)
        for row in rows:
            summary = client.get(f"/api/fields/{row['id']}/summary", headers=OWNER).json()
            assert summary['boundary_import']['import_receipt']['source_sha256'] == parsed['import_receipt']['source_sha256']
        body['features'][0]['name'] = 'Different name'
        assert client.post(path, headers=OWNER, json=body).status_code == 409
        duplicate = preview(client)
        assert all(item['duplicate'] for item in duplicate['features'])
        retry = client.post(f"/api/field-imports/{duplicate['id']}/commit", headers=OWNER, json=body)
        assert retry.status_code == 200, retry.text
        assert all(item['status']=='duplicate_skipped' for item in retry.json()['features'])
        assert len(client.get('/api/demo/fields', headers=OWNER).json()['fields']) == 2


def test_bulk_import_rejects_unreviewed_features_and_invalid_farm_without_partial_save(settings):
    with TestClient(create_app(settings)) as client:
        parsed = preview(client)
        path = f"/api/field-imports/{parsed['id']}/commit"
        body = {'operation_id':str(uuid4()), 'features':[{'feature_id': parsed['features'][0]['id'], 'name':'West'}, {'feature_id':'not-in-source', 'name':'Forged'}]}
        assert client.post(path, headers=OWNER, json=body).status_code == 422
        assert client.get('/api/demo/fields', headers=OWNER).json()['fields'] == []
        body['features'].pop(); body['farm_id'] = str(uuid4())
        assert client.post(path, headers=OWNER, json=body).status_code == 404
        assert client.get('/api/demo/fields', headers=OWNER).json()['fields'] == []
        with client.app.state.trace_store._cursor() as cursor:
            cursor.execute("UPDATE field_import_previews SET parsed_json='{}' WHERE id=?", (parsed['id'],))
        assert client.post(path, headers=OWNER, json=body).status_code == 409
