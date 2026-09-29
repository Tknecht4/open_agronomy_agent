"""Invocation-scoped transfer limits shared across processors and failures."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import httpx
import pytest

from agronomy_agent.geospatial import cog


@pytest.fixture
def origin(monkeypatch):
    monkeypatch.setattr(cog, '_PROXY_CHUNK_BYTES', 1)
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_HEAD(self):
            calls.append('HEAD');self.send_response(200);self.send_header('Content-Length','8');self.end_headers()
        def do_GET(self):
            calls.append('GET');start,end=map(int,self.headers['Range'].removeprefix('bytes=').split('-'))
            data=b'12345678'[start:end+1]
            self.send_response(206);self.send_header('Content-Length',str(len(data)))
            self.send_header('Content-Range',f'bytes {start}-{end}/8');self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield {'red':f'http://127.0.0.1:{server.server_port}/red.tif'},calls
    finally: server.shutdown();server.server_close();thread.join(timeout=5)


def fetch(url):
    return httpx.get(url,headers={'Range':'bytes=0-3'},timeout=5).status_code


def test_batch_counts_consumed_bytes_across_sequential_proxies_and_failure(origin):
    hrefs,calls=origin
    with cog.transfer_budget(6,8) as budget:
        with cog.bounded_cog_proxy(hrefs) as (urls,state): assert fetch(urls['red'])==206
        with pytest.raises(RuntimeError,match='budget exceeded'):
            with cog.bounded_cog_proxy(hrefs) as (urls,state): assert fetch(urls['red'])==429
        snap=budget.snapshot()
        assert snap['bytes']==4 and snap['reserved']==0 and snap['http_requests']==2
        assert snap['byte_limit_refusals']==1
    # Prior invocation's failure must not leak its quota into a new processor.
    with cog.bounded_cog_proxy(hrefs) as (urls,state): assert fetch(urls['red'])==206
    assert calls==['GET','GET','GET']


def test_batch_reservations_are_shared_across_concurrent_proxies(origin):
    hrefs,_=origin
    with cog.transfer_budget(6,8) as budget:
        with pytest.raises(RuntimeError,match='budget exceeded'):
            with ExitStack() as stack:
                first,_=stack.enter_context(cog.bounded_cog_proxy(hrefs))
                second,_=stack.enter_context(cog.bounded_cog_proxy(hrefs))
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results=list(pool.map(fetch,[first['red'],second['red']]))
                assert sorted(results)==[206,429]
        assert budget.snapshot()['bytes']==4 and budget.snapshot()['reserved']==0


def test_per_scene_budget_is_independent_of_batch_remaining(origin):
    hrefs,_=origin
    with cog.transfer_budget(20,3) as budget:
        with pytest.raises(RuntimeError,match='budget exceeded'):
            with cog.bounded_cog_proxy(hrefs) as (urls,state): assert fetch(urls['red'])==429
        assert budget.snapshot()['bytes']==0 and budget.snapshot()['scene_limit_refusals']==1
        assert budget.snapshot()['byte_limit_refusals']==0


def test_head_and_rejected_attempts_have_request_limit(origin):
    hrefs,calls=origin
    with cog.transfer_budget(20,8,max_requests=1) as budget:
        with pytest.raises(RuntimeError,match='budget exceeded'):
            with cog.bounded_cog_proxy(hrefs) as (urls,state):
                assert httpx.head(urls['red']).status_code==200
                assert fetch(urls['red'])==429
        assert calls==['HEAD'] and budget.snapshot()['http_requests']==1
        assert budget.snapshot()['request_limit_refusals']==1


def test_invalid_and_nested_budgets_are_rejected_without_egress():
    for args in [(True,8),(0,8),(2**30+1,8),(10,0),(10,2**28+1)]:
        with pytest.raises(ValueError):
            with cog.transfer_budget(*args): pass
    with cog.transfer_budget(20,8):
        with pytest.raises(ValueError,match='nested'):
            with cog.transfer_budget(20,8): pass
