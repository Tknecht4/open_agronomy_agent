from __future__ import annotations
from copy import deepcopy
import csv
import io
import json
import logging
from pathlib import Path
import re
import zipfile

import pytest
from fastapi.testclient import TestClient
from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.services import chat_service
from agronomy_agent.server.services.export_service import (
    _SpreadsheetSafeDictWriter, build_phase4_csv_thread_exports,
    build_phase4_zip_thread_export, build_phase6_source_evidence_bundle_csv,
    build_phase6_diagnostic_checklist_csv, build_phase6_data_source_audit_csv,
)

OWNER = {'X-Agronomy-User-Email':'synthetic-repair-owner@example.test'}
OTHER = {'X-Agronomy-User-Email':'synthetic-repair-other@example.test'}

def first_csv(text):
    return next(csv.DictReader(io.StringIO(text)))

@pytest.mark.parametrize('value', ['=1+1','+SUM(1,2)','-SUM(1,2)','@SUM(1,2)',
    ' =1+1','\t=1+1','\r=1+1','\n=1+1','\ufeff=1+1','\t @SUM(1,2)',
    '--42','+1-1','-1+1','-1e3+2','="quoted,\"cell\""'])
def test_csv_roundtrip_neutralizes_formulas_without_mutating_input(value):
    thread = {'id':'thread','messages':[{'id':'message','sequence_no':2,
        'actor':'assistant','created_at':'2026-10-09T00:00:00Z','content':value}]}
    original = deepcopy(thread)
    row = first_csv(build_phase4_csv_thread_exports(thread,[])['thread_messages.csv'])
    assert row['content'] == "'" + value
    assert row['sequence_no'] == '2'
    assert row['actor'] == 'assistant'
    assert thread == original

@pytest.mark.parametrize('value', ['ordinary crop notes','',"'already literal",'crop=rotation',
    'answer, with comma','multiple\nlines','"quoted text"','123','-42','+42',
    '-.5','+2.0e3',0,-2,1.25,True,None])
def test_csv_preserves_benign_and_numeric_cells(value):
    stream = io.StringIO()
    writer = _SpreadsheetSafeDictWriter(stream,fieldnames=['value'])
    writer.writeheader()
    writer.writerows([{'value':value}])
    row = first_csv(stream.getvalue())
    assert row['value'] == ('' if value is None else str(value))

def test_all_report_csv_surfaces_apply_the_same_cell_policy():
    source = first_csv(build_phase6_source_evidence_bundle_csv({'retrieved_docs':[{
        'rank':1,'doc_id':'=1+1','title':'@SUM(1,2)','score':-0.25,'relevance_note':'soil evidence'}],
        'kg_hits':[]}))
    assert source['id'] == "'=1+1" and source['title'] == "'@SUM(1,2)"
    assert source['score'] == '-0.25' and source['note'] == 'soil evidence'
    checklist = first_csv(build_phase6_diagnostic_checklist_csv({'triage_steps':[{
        'action':'\t=1+1','why':'check field','evidence_ref':'ref1'}],
        'measurement_plan':[],'safety_boundaries':[]}))
    assert checklist['item'] == "'\t=1+1" and checklist['sequence'] == '1'
    audit = first_csv(build_phase6_data_source_audit_csv({'sources':[{
        'source_id':'source1','title':'-SUM(1,2)','chunk_count':2,'rag_eligible':True,
        'gap_flags':[],'crops':[],'regions':[],'buckets':[]}]}))
    assert audit['title'] == "'-SUM(1,2)" and audit['chunk_count'] == '2'
    event = first_csv(build_phase4_csv_thread_exports({'id':'thread','messages':[]},[{
        'event_type':'=1+1','actor':'system','payload':{'content':'=1+1'}}])['thread_events.csv'])
    assert event['event_type'] == "'=1+1"
    assert json.loads(event['payload_json']) == {'content':'=1+1'}

def test_zip_keeps_original_json_and_markdown_with_safe_csv_derivative():
    raw = {'original_content':'=1+1'}
    csv_files = build_phase4_csv_thread_exports({'id':'thread','messages':[{'content':'=1+1'}]},[])
    archive = build_phase4_zip_thread_export(trace_payload=json.dumps(raw),markdown_payload='=1+1',
                                             csv_payloads=csv_files,manifest={})
    with zipfile.ZipFile(io.BytesIO(archive)) as result:
        assert json.loads(result.read('thread_trace.json')) == raw
        assert result.read('thread.md') == b'=1+1'
        assert first_csv(result.read('thread_messages.csv').decode())['content'] == "'=1+1"

def test_export_refusals_preserve_owner_gate_and_normal_download(tmp_path):
    settings = build_settings(db_path=tmp_path/'repair.sqlite3',artifact_root=tmp_path/'artifacts',network_mode='offline')
    with TestClient(create_app(settings),raise_server_exceptions=False) as client:
        session = client.post('/api/sessions',headers=OWNER,json={'title':'Synthetic export','consent':{}}).json()
        response = client.post('/api/exports',headers=OWNER,json={'session_id':session['session_id'],
            'include_turns':False,'include_data_sources':False,'include_artifacts':False})
        assert response.status_code == 200
        export = response.json()
        route = '/api/exports/'+export['export_id']+'/download'
        for filename in ('.','..','nul\x00name','../outside','nested/file','back\\slash'):
            assert client.get(route,headers=OWNER,params={'filename':filename}).status_code == 400
            assert client.get(route,headers=OTHER,params={'filename':filename}).status_code == 404
        assert client.get(route,headers=OWNER,params={'filename':'missing.json'}).status_code == 404
        filename = next(iter(export['files']))
        result = client.get(route,headers=OWNER,params={'filename':filename})
        assert result.status_code == 200 and result.content
        assert result.content == (settings.artifact_root/export['export_id']/filename).read_bytes()
        assert client.get(route,headers=OTHER,params={'filename':filename}).status_code == 404
        (settings.artifact_root/export['export_id']/'directory').mkdir()
        assert client.get(route,headers=OWNER,params={'filename':'directory'}).status_code == 404

def test_opaque_stream_failure_binds_public_reference_to_safe_diagnostic(tmp_path,monkeypatch,caplog):
    settings = build_settings(db_path=tmp_path/'failure.sqlite3',artifact_root=tmp_path/'artifacts',network_mode='offline')
    canary = 'SYNTHETIC PRIVATE PATH /synthetic/private/secret'
    def fail(*args,**kwargs):
        raise RuntimeError(canary)
    monkeypatch.setattr(chat_service,'_build_mlx_generator',fail)
    caplog.set_level(logging.ERROR)
    with TestClient(create_app(settings)) as client:
        session = client.post('/api/sessions',headers=OWNER,json={'title':'Synthetic failure','consent':{}}).json()
        response = client.post('/api/sessions/'+session['session_id']+'/turns/stream',headers=OWNER,json={
            'message':'Explain crop rotation.','mode':'agronomic_rag','model_id':settings.default_model_id,
            'rag_config':'configs/rag.yaml'})
        errors = [block for block in response.text.split('\n\n') if block.startswith('event: error\n')]
        assert response.status_code == 200 and len(errors) == 1
        event = json.loads(errors[0].split('data: ',1)[1])
        assert event['code'] == 'generation_failed'
        assert re.fullmatch('[0-9a-f]{32}',event['failure_id'])
        assert 'Refresh the conversation' in event['message']
        assert canary not in response.text and canary not in caplog.text
        assert 'failure_id='+event['failure_id'] in caplog.text
        assert 'exception_type=RuntimeError' in caplog.text
        assert client.get('/api/sessions/'+session['session_id'],headers=OWNER).json()['turns'] == []
