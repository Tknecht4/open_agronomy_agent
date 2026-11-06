"""Durable imagery identity, authorization, historical geometry, retry and restart."""
from uuid import uuid4

from agronomy_agent.server.storage import imagery_job_store as jobs
from agronomy_agent.server.services import imagery_service
from agronomy_agent.server.imagery_job_routes import execute_job
from test_imagery_routes import runtime, OWNER, OUTSIDER, PAYLOAD, _worker


def body(client, field_id):
    summary = client.get(f'/api/fields/{field_id}/summary', headers=OWNER).json()
    return {**PAYLOAD, 'scene_id':'hls2-s30:fixture', 'expected_geometry_revision_id':summary['geometry_revision_id'], 'operation_id':str(uuid4())}


def test_jobs_retain_results_and_old_geometry_without_scope_leak(runtime, monkeypatch):
    client, field_id, settings = runtime
    monkeypatch.setattr(imagery_service, '_run_worker', _worker)
    request = body(client,field_id)
    response = client.post(f'/api/fields/{field_id}/imagery-jobs', headers=OWNER, json=request)
    assert response.status_code == 202, response.text
    job_id = response.json()['id']
    job = client.get(f'/api/imagery-jobs/{job_id}', headers=OWNER).json()
    assert job['status']=='completed' and job['current_geometry']
    assert client.get(job['result']['preview_url'],headers=OWNER).content==b'fixture PNG'
    assert client.get(f'/api/imagery-jobs/{job_id}', headers=OUTSIDER).status_code == 403
    assert client.get(job['result']['preview_url'],headers=OUTSIDER).status_code == 403
    retry = client.post(f'/api/fields/{field_id}/imagery-jobs', headers=OWNER, json=request)
    assert retry.json()['id']==job_id
    assert len(client.get(f'/api/fields/{field_id}/imagery-jobs', headers=OWNER).json()['jobs'])==1
    field = client.get('/api/demo/fields',headers=OWNER).json()['fields'][0]
    edited = client.patch(f'/api/demo/fields/{field_id}', headers=OWNER, json={'name':'Moved','field':{},'geometry':{'kind':'point','point':{'lat':40.2,'lon':-103.2}},'expectedUpdatedAt':field['updatedAt']})
    assert edited.status_code == 200, edited.text
    historical = client.get(f'/api/imagery-jobs/{job_id}',headers=OWNER).json()
    assert not historical['current_geometry']
    assert client.get(historical['result']['preview_url'],headers=OWNER).status_code == 200
    request['operation_id']=str(uuid4())
    assert client.post(f'/api/fields/{field_id}/imagery-jobs', headers=OWNER,json=request).status_code == 409


def test_cancel_and_restart_never_replay_and_tampered_result_is_hidden(runtime, monkeypatch):
    client, field_id, settings = runtime
    store = client.app.state.trace_store
    field = store.get_phase4_field_context(field_id)
    request = body(client,field_id)
    job, created = jobs.queue(store,field,PAYLOAD,request['operation_id'],request['expected_geometry_revision_id'])
    assert created
    assert client.post(f"/api/imagery-jobs/{job['id']}/cancel",headers=OWNER).json()['status']=='cancelled'
    monkeypatch.setattr(imagery_service,'analyze', lambda *args: (_ for _ in ()).throw(AssertionError('cancelled work must not run')))
    execute_job(store,settings,job['id'])
    assert jobs.get_job(store,job['id'])['status']=='cancelled'
    newer, _ = jobs.queue(store,field,PAYLOAD,str(uuid4()),request['expected_geometry_revision_id'])
    jobs.recover_interrupted(store)
    assert jobs.get_job(store,newer['id'])['status']=='interrupted'
    jobs.set_status(store,newer['id'],'completed', {'status':'available','chip_hash':'a'*64})
    with store._cursor() as cursor:
        cursor.execute("UPDATE field_imagery_jobs SET result_json='{}' WHERE id=?",(newer['id'],))
    assert jobs.get_job(store,newer['id'])['status']=='integrity_failed'
    assert client.get(f"/api/imagery-jobs/{newer['id']}/preview.png",headers=OWNER).status_code==404


def test_linked_analysis_record_is_bound_idempotent_and_authorized(runtime, monkeypatch):
    client, field_id, settings = runtime
    monkeypatch.setattr(imagery_service, '_run_worker', _worker)
    response = client.post(f'/api/fields/{field_id}/imagery-jobs', headers=OWNER, json=body(client,field_id))
    job_id = response.json()['id']
    path = f'/api/imagery-jobs/{job_id}/record'
    assert client.post(path,headers=OUTSIDER,json={'season':2026}).status_code==403
    first=client.post(path,headers=OWNER,json={'season':2026})
    assert first.status_code==201,first.text
    again=client.post(path,headers=OWNER,json={'season':2026})
    assert again.json()['events'][0]['id']==first.json()['events'][0]['id']
    event=first.json()['events'][0]
    assert event['provenance']['evidence_role']=='processed_observation'
    assert event['payload']['imagery_analysis']['job_id']==job_id
    assert 'not a grower observation' in event['payload']['summary']
    assert event['payload']['season']==2026


def test_worker_check_does_not_call_process_failure_missing_dependencies(monkeypatch):
    import subprocess
    imagery_service._worker_health.cache_clear()
    monkeypatch.setattr(imagery_service.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a[0], -9, b'', b''))
    result = imagery_service._worker_health('/synthetic/python', 1)
    assert result['reason'] == 'worker_check_failed'
    assert 'dependency' not in result['message']
    imagery_service._worker_health.cache_clear()
    monkeypatch.setattr(imagery_service.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a[0], 1, b'', b'ModuleNotFoundError: rasterio'))
    assert imagery_service._worker_health('/synthetic/python', 1)['reason'] == 'missing_dependency'
    imagery_service._worker_health.cache_clear()


def test_deduplicated_operations_remain_bound_after_completion_and_restart(runtime):
    import pytest
    client, field_id, _ = runtime
    store = client.app.state.trace_store
    field = store.get_phase4_field_context(field_id)
    revision = body(client, field_id)['expected_geometry_revision_id']
    original, created = jobs.queue(store, field, PAYLOAD, str(uuid4()), revision)
    assert created
    alias = str(uuid4())
    duplicate, created = jobs.queue(store, field, PAYLOAD, alias, revision)
    assert not created and duplicate['id'] == original['id']
    jobs.set_status(store, original['id'], 'completed')
    jobs.recover_interrupted(store)
    retry, created = jobs.queue(store, field, PAYLOAD, alias, revision)
    assert not created and retry['id'] == original['id']
    with pytest.raises(ValueError, match='another request'):
        jobs.queue(store, field, {**PAYLOAD, 'start_date': '2026-01-01'}, alias, revision)
    with store._cursor() as cursor:
        jobs.ensure_schema(cursor)
    assert jobs.queue(store, field, PAYLOAD, alias, revision)[0]['id'] == original['id']
    assert len(jobs.list_jobs(store, field_id)) == 1
