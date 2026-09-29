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


@pytest.mark.parametrize('declared,delivered', [(16384,8192),(32768,24576)])
@pytest.mark.parametrize('limiter', ['batch','scene'])
def test_truncated_buffered_body_spends_quota_before_reservation_released(monkeypatch,declared,delivered,limiter):
    """Real HTTPX discards an unyielded partial chunk on RemoteProtocolError."""
    from types import SimpleNamespace
    responses=[]
    def client(*a,**kw):
        return httpx.Client(*a,event_hooks={'response':[responses.append]},**kw)
    monkeypatch.setattr(cog,'httpx',SimpleNamespace(Client=client,HTTPError=httpx.HTTPError))
    # Keep the production chunk size: the former one-byte test fixture hid this.
    assert cog._PROXY_CHUNK_BYTES==16384
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            self.send_response(206)
            self.send_header('Content-Length',str(declared))
            self.send_header('Content-Range',f'bytes 0-{declared-1}/{declared*2}')
            self.send_header('Connection','close');self.end_headers()
            try:self.wfile.write(b'x'*delivered);self.wfile.flush()
            except (OSError,BrokenPipeError):pass
            self.close_connection=True
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    cap=declared+cog._PROXY_CHUNK_BYTES
    batch_limit=cap if limiter=='batch' else cap*4
    scene_limit=cap if limiter=='scene' else cap*4
    try:
        with cog.transfer_budget(batch_limit,scene_limit,max_requests=8) as budget:
            with pytest.raises(RuntimeError,match='budget exceeded'):
                with cog.bounded_cog_proxy({'red':f'http://127.0.0.1:{server.server_port}/red.tif'}) as (urls,state):
                    with pytest.raises(httpx.RemoteProtocolError):
                        httpx.get(urls['red'],headers={'Range':f'bytes=0-{declared-1}'},timeout=5)
                    # The failed read spent bytes, so the next reservation fails.
                    assert httpx.get(urls['red'],headers={'Range':f'bytes=0-{declared-1}'},timeout=5).status_code==429
            snap=budget.snapshot()
            assert snap['bytes']==state['bytes']==delivered
            assert snap['bytes']==sum(r.num_bytes_downloaded for r in responses)
            assert snap['reserved']==state['reserved']==0
            assert snap['http_requests']==2
            assert snap['byte_limit_refusals' if limiter=='batch' else 'scene_limit_refusals']==1
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def test_conflicting_chunked_framing_is_rejected_before_consumption(monkeypatch):
    from types import SimpleNamespace
    responses=[]
    def client(*a,**kw):
        return httpx.Client(*a,event_hooks={'response':[responses.append]},**kw)
    monkeypatch.setattr(cog,'httpx',SimpleNamespace(Client=client,HTTPError=httpx.HTTPError))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            self.send_response(206)
            self.send_header('Content-Length','16384')
            self.send_header('Content-Range','bytes 0-16383/131072')
            self.send_header('Transfer-Encoding','chunked')
            self.send_header('Connection','close');self.end_headers()
            try:
                self.wfile.write(b'20000\r\n'+b'x'*131072+b'\r\n0\r\n\r\n')
                self.wfile.flush()
            except (OSError,BrokenPipeError):pass
            self.close_connection=True
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with cog.transfer_budget(32768,32768) as budget:
            with pytest.raises(RuntimeError,match='framing rejected'):
                with cog.bounded_cog_proxy({'red':f'http://127.0.0.1:{server.server_port}/red.tif'}) as (urls,state):
                    assert httpx.get(urls['red'],headers={'Range':'bytes=0-16383'},timeout=5).status_code==502
            assert sum(r.num_bytes_downloaded for r in responses)==0
            assert budget.snapshot()['bytes']==state['bytes']==0
            assert budget.snapshot()['reserved']==state['reserved']==0
            assert budget.snapshot()['http_requests']==1
            assert state['protocol_errors']==1
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
