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


def test_worker_spawn_closes_inherited_descriptors_and_avoids_fork(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    import pytest
    if sys.platform != "darwin":
        pytest.skip("macOS spawn regression")
    def forbidden_fork(*args, **kwargs):
        pytest.fail("GIS worker must not fork the multithreaded server")
    monkeypatch.setattr(subprocess, "_fork_exec", forbidden_fork)
    with (tmp_path / "private").open("wb") as private:
        os.set_inheritable(private.fileno(), True)
        code = "import os,sys; fd=int(sys.argv[1]);\ntry: os.fstat(fd)\nexcept OSError: print('closed')\nelse: print('leaked')\nprint(os.getcwd())"
        result = imagery_service._run_process([sys.executable, "-I", "-c", code, str(private.fileno())],
            cwd=tmp_path, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": os.defpath}, timeout=10, check=True)
    assert result.stdout.decode().splitlines() == ["closed", str(tmp_path)]


def test_scene_preview_checks_authority_and_revision_without_creating_analysis(runtime, monkeypatch):
    from agronomy_agent.imagery_scene_preview import request_identity, valid_preview
    import base64
    import hashlib

    client, field_id, _ = runtime
    path = f"/api/fields/{field_id}/imagery-preview"
    payload = body(client, field_id)
    payload.pop("operation_id")
    preview_calls = []

    def fake_worker(settings, cache, geometry, request, *, display_preview=False):
        assert display_preview
        preview_calls.append(request)
        _, identity = request_identity(geometry, request["provider_id"], request["scene_id"],
                                       request["start_date"], request["end_date"])
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X2FkAAAAASUVORK5CYII=")
        value = {**identity, "status": "available", "role": "display_only", "display_crs": "EPSG:3857",
                 "display_resampling": "nearest", "bounds": [[40.15, -103.15], [40.16, -103.14]],
                 "acquired_at": "2021-06-10T00:00:00Z", "png_base64": base64.b64encode(png).decode(),
                 "image_sha256": hashlib.sha256(png).hexdigest()}
        assert valid_preview(value, identity)
        assert not valid_preview({**value, "scene_id": "hls2-s30:other"}, identity)
        return value

    monkeypatch.setattr(imagery_service, "_run_worker", fake_worker)
    assert client.post(path, headers=OUTSIDER, json=payload).status_code == 403
    assert client.post(path, headers=OWNER, json={**payload, "expected_geometry_revision_id": "previous"}).status_code == 409
    assert client.post(path, headers=OWNER, json={**payload, "image_url": "https://fixture.invalid"}).status_code == 422
    assert not preview_calls
    response = client.post(path, headers=OWNER, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "available"
    assert response.json()["scene_id"] == payload["scene_id"]
    assert response.json()["geometry_revision_id"] == payload["expected_geometry_revision_id"]
    assert response.headers["Cache-Control"] == "private, no-store"
    assert len(preview_calls) == 1
    assert client.get(f"/api/fields/{field_id}/imagery-jobs", headers=OWNER).json()["jobs"] == []


def test_durable_series_retains_observations_and_exclusions(runtime, monkeypatch):
    from threading import Barrier
    from agronomy_agent.server.services import imagery_series

    client, field_id, _ = runtime
    path = f"/api/fields/{field_id}/imagery-series"
    revision = body(client, field_id)["expected_geometry_revision_id"]
    request = {"operation_id": str(uuid4()), "expected_geometry_revision_id": revision,
               "start_date": "2025-07-14", "end_date": "2025-07-15"}
    scenes = [
        {"scene_id": f"{collection}:fixture-{day}", "provider_id": provider,
         "acquired_at": f"2025-07-{day}T17:00:00.000000+00:00", "scene_cloud_percent": cloud}
        for collection, provider, day, cloud in (
            ("hls2-l30", "hls-l30-planetary-computer", 14, 10),
            ("hls2-s30", "hls-s30-planetary-computer", 15, 3),
        )
    ]
    monkeypatch.setattr(imagery_service, "readiness", lambda settings: {"status": "ready"})
    for scene in scenes:
        scene["catalog_item"] = {"id": scene["scene_id"].split(":")[1]}
    monkeypatch.setattr(imagery_series, "search_hls_series", lambda *args: {"status": "available", "scenes": scenes})
    executed = []
    both_scenes = Barrier(2)

    def analyze(settings, field, geometry, selection):
        executed.append(selection)
        both_scenes.wait(timeout=3)
        assert selection["catalog_item"]["id"] == selection["scene_id"].split(":")[1]
        scene = next(row for row in scenes if row["scene_id"] == selection["scene_id"])
        snow = selection["provider_id"] == "hls-s30-planetary-computer"
        return {
            "status": "empty_valid_area" if snow else "available",
            "scene_id": scene["scene_id"], "provider_id": scene["provider_id"],
            "source": {"acquired_at": scene["acquired_at"]},
            "qa": {"field_area_m2": 1000, "valid_area_fraction": 0 if snow else .7, "nodata_area_m2": 0,
                   "excluded_area_m2_by_reason": {"cloud": 0 if snow else 300, "snow_ice": 1000 if snow else 0}},
            "zonal_stats": {"NDVI": {"mean": None if snow else .6, "area_m2": 0 if snow else 700},
                            "NDMI": {"mean": None if snow else .2, "area_m2": 0 if snow else 700}},
            "chip_hash": "a" * 64,
        }

    monkeypatch.setattr(imagery_service, "analyze", analyze)
    assert client.post(path, headers=OUTSIDER, json=request).status_code == 403
    assert client.post(path, headers=OWNER, json={**request, "expected_geometry_revision_id": "stale"}).status_code == 409
    assert not executed
    created = client.post(path, headers=OWNER, json=request)
    assert created.status_code == 202, created.text
    parent_id = created.json()["id"]
    result = client.get(f"/api/imagery-jobs/{parent_id}", headers=OWNER).json()["result"]
    assert result["status"] == "complete" and result["total"] == 2
    assert result["processed"] == 2
    assert result["exclusions"] == {"low_coverage": 1, "unknown_coverage": 0, "no_usable_pixels": 0, "unavailable": 0}
    landsat, = result["scenes"]
    _, sentinel = jobs.get_job(client.app.state.trace_store, parent_id)["result"]["scenes"]
    assert "catalog_item" not in landsat
    assert landsat["indices"] == {"NDVI": .6, "NDMI": .2}
    assert landsat["field_cloud_fraction"] == .3
    assert sentinel["indices"] == {"NDVI": None, "NDMI": None}
    assert sentinel["main_exclusion"] == "Snow or ice"
    assert client.get(f"/api/imagery-jobs/{sentinel['job_id']}/overlay", headers=OWNER).status_code == 404
    assert client.get(f"/api/imagery-jobs/{landsat['job_id']}/overlay?index=NDMI", headers=OUTSIDER).status_code == 403
    assert client.post(path, headers=OWNER, json=request).json()["id"] == parent_id
    assert len(executed) == 2
    assert len(client.get(path, headers=OWNER).json()["jobs"]) == 1
    assert len(client.get(f"/api/fields/{field_id}/imagery-jobs", headers=OWNER).json()["jobs"]) == 2


def test_saved_series_applies_strict_coverage_cutoff_without_rewriting_results(runtime):
    client, field_id, _ = runtime
    store = client.app.state.trace_store
    field = store.get_phase4_field_context(field_id)
    revision = body(client, field_id)["expected_geometry_revision_id"]
    parent, _ = jobs.queue(store, field, {"kind": "series", "start_date": "2025-07-01", "end_date": "2025-07-31"},
                           str(uuid4()), revision)
    rows = [
        {"scene_id": str(i), "usable_fraction": fraction, "status": status}
        for i, (fraction, status) in enumerate((
            (.1, "observed"), (.6, "observed"), (.6001, "observed"), (1, "observed"),
            (None, "observed"), (.8, "no_usable_pixels"), (None, "unavailable"),
        ))
    ]
    saved = {"status": "complete", "scenes": rows, "total": len(rows)}
    jobs.set_status(store, parent["id"], "completed", saved)

    result = client.get(f"/api/imagery-jobs/{parent['id']}", headers=OWNER).json()["result"]
    assert result["scenes"] == [rows[2], rows[3]]
    assert result["minimum_usable_fraction"] == .6
    assert result["total"] == result["processed"] == len(rows)
    assert result["exclusions"] == {"low_coverage": 2, "unknown_coverage": 1, "no_usable_pixels": 1, "unavailable": 1}
    history = client.get(f"/api/fields/{field_id}/imagery-series", headers=OWNER).json()
    assert history["jobs"][0]["result"] == result
    assert jobs.get_job(store, parent["id"])["result"] == saved


def test_cancelling_a_series_stops_admitting_scenes(runtime, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

    from agronomy_agent.server.services import imagery_series

    client, field_id, settings = runtime
    store = client.app.state.trace_store
    field = store.get_phase4_field_context(field_id)
    revision = body(client, field_id)["expected_geometry_revision_id"]
    parent, _ = jobs.queue(store, field, {"kind": "series", "start_date": "2025-07-14", "end_date": "2025-07-15"}, str(uuid4()), revision)
    scenes = [{"scene_id": f"hls2-s30:scene-{i}", "provider_id": "hls-s30-planetary-computer",
               "acquired_at": "2025-07-14T17:00:00.000000+00:00", "scene_cloud_percent": 5}
              for i in range(imagery_series.SERIES_WORKERS * 2)]
    started = Barrier(imagery_series.SERIES_WORKERS + 1)
    release = Event()

    def analyze(*args):
        started.wait(timeout=5)
        assert release.wait(5)
        return {"status": "unavailable"}

    monkeypatch.setattr(imagery_service, "analyze", analyze)
    monkeypatch.setattr(imagery_series, "search_hls_series", lambda *args: {"status": "available", "scenes": scenes})
    with ThreadPoolExecutor(max_workers=1) as pool:
        run = pool.submit(execute_job, store, settings, parent["id"])
        try:
            started.wait(timeout=5)
            response = client.post(f"/api/imagery-jobs/{parent['id']}/cancel", headers=OWNER, json={})
            assert response.raise_for_status().json()["status"] == "cancelled"
        finally:
            release.set()
        run.result(timeout=5)
    assert len(jobs.list_jobs(store, field_id, include_series_children=True)) == imagery_series.SERIES_WORKERS
    assert jobs.get_job(store, parent["id"])["status"] == "cancelled"


def test_season_children_do_not_crowd_standalone_jobs_out_of_history(runtime):
    client, field_id, _ = runtime
    store = client.app.state.trace_store
    field = store.get_phase4_field_context(field_id)
    revision = body(client, field_id)["expected_geometry_revision_id"]
    standalone, _ = jobs.queue(store, field, PAYLOAD, str(uuid4()), revision)
    jobs.set_status(store, standalone["id"], "completed")
    series, _ = jobs.queue(store, field, {"kind": "series"}, str(uuid4()), revision)
    jobs.set_status(store, series["id"], "running")
    for index in range(31):
        payload = {**PAYLOAD, "series_job_id": series["id"], "scene_id": f"scene-{index}"}
        child, _ = jobs.queue(store, field, payload, str(uuid4()), revision, series_child=True)
        jobs.set_status(store, child["id"], "completed")

    history = client.get(f"/api/fields/{field_id}/imagery-jobs", headers=OWNER).json()["jobs"]
    assert [job["id"] for job in history] == [standalone["id"]]
    assert client.get(f"/api/imagery-jobs/{child['id']}", headers=OWNER).status_code == 200


def test_parallel_hls_workers_share_one_token_until_expiry(runtime, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    import subprocess

    _, _, settings = runtime
    requests = []
    public_token = "sp=r&sig=fixture"

    def access(url):
        requests.append(url)
        return {"token": public_token, "msft:expiry": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}

    monkeypatch.setattr(imagery_service, "_hls_token", None)
    monkeypatch.setattr(imagery_service, "_hls_retry_after", 0)
    monkeypatch.setattr(imagery_service, "_request_json", access)
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(lambda _: imagery_service._hls_access_token(), range(3))) == [public_token] * 3
    assert len(requests) == 1

    monkeypatch.setattr(imagery_service, "_hls_token", (public_token, datetime.now(timezone.utc)))

    def run(command, **kwargs):
        assert "--access-token-stdin" in command
        assert kwargs["input"] == public_token.encode()
        assert public_token not in str(command) and public_token not in str(kwargs["env"])
        if "--catalog-item" in command:
            item_path = command[command.index("--catalog-item") + 1]
            from pathlib import Path
            assert public_token not in Path(item_path).read_text()
        kwargs["stdout"].write(b'{"status":"available"}')
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(imagery_service, "_run_process", run)
    payload = {**PAYLOAD, "series_job_id": "parent", "catalog_item": {"id": "scene"}}
    result = imagery_service._run_worker(settings, tmp_path / "images", {"type": "Point", "coordinates": [-96, 40]}, payload)
    assert result == {"status": "available"}
    assert len(requests) == 2
