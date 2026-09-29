"""Shared bounded range transport for provider-admitted COG URLs.

Provider adapters validate asset host/path and source identity before calling.
This transport never follows redirects and preserves fixed range/transfer caps;
credentials, if a provider requires public short-lived signing, stay in memory.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
import httpx

MAX_COG_TRANSFER_BYTES = 256 * 1024 * 1024
MAX_SINGLE_RANGE_BYTES = 64 * 1024 * 1024
_PROXY_CHUNK_BYTES = 16 * 1024


class TransferBudget:
    """One invocation's actual COG payload/request accounting, including failures."""

    def __init__(self, max_bytes: int, per_scene_bytes: int, max_requests: int):
        if (type(max_bytes) is not int or not 1 <= max_bytes <= 1024**3 or
                type(per_scene_bytes) is not int or not 1 <= per_scene_bytes <= MAX_COG_TRANSFER_BYTES or
                type(max_requests) is not int or not 1 <= max_requests <= 4096):
            raise ValueError("invalid bounded COG budget")
        self.limit = max_bytes
        self.per_scene = per_scene_bytes
        self.max_requests = max_requests
        self.bytes = self.reserved = self.http_requests = 0
        self.byte_refusals = self.request_refusals = self.scene_refusals = 0
        self.lock = threading.Lock()

    def begin_request(self) -> bool:
        with self.lock:
            if self.http_requests >= self.max_requests:
                self.request_refusals += 1
                return False
            self.http_requests += 1
            return True

    def reserve(self, amount: int) -> bool:
        with self.lock:
            if self.bytes + self.reserved + amount > self.limit:
                self.byte_refusals += 1
                return False
            self.reserved += amount
            return True

    def reject_scene(self) -> None:
        with self.lock:
            self.scene_refusals += 1

    def consume(self, amount: int, released: int) -> None:
        with self.lock:
            self.bytes += amount
            self.reserved -= released
            if self.bytes > self.limit:
                self.byte_refusals += 1

    def release(self, amount: int) -> None:
        with self.lock:
            self.reserved -= amount

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return {"bytes": self.bytes, "reserved": self.reserved,
                    "http_requests": self.http_requests, "limit_bytes": self.limit,
                    "per_scene_limit_bytes": self.per_scene, "request_limit": self.max_requests,
                    "byte_limit_refusals": self.byte_refusals, "request_limit_refusals": self.request_refusals,
                    "scene_limit_refusals": self.scene_refusals}


_ACTIVE_BUDGET: ContextVar[TransferBudget | None] = ContextVar("imagery_cog_budget", default=None)


@contextmanager
def transfer_budget(max_bytes: int, per_scene_bytes: int, *, max_requests: int = 512):
    """Scope all shared proxies to a batch quota without mutable global limits.

    Cached reads consume no transfer. STAC/token JSON and HTTP headers are
    separately bounded by existing adapters and are not COG payload bytes.
    """
    if _ACTIVE_BUDGET.get() is not None:
        raise ValueError("nested imagery transfer budgets are not supported")
    budget = TransferBudget(max_bytes, per_scene_bytes, max_requests)
    token = _ACTIVE_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _ACTIVE_BUDGET.reset(token)


@contextmanager
def bounded_cog_proxy(hrefs: dict[str, str]):
    """Serve fixed public COG assets to GDAL through a capped loopback proxy.

    All outward requests use httpx without redirects. This also prevents SAS
    query strings from entering GDAL paths, errors, and receipts.
    """
    state = {"bytes": 0, "reserved": 0, "requests": 0, "rejected": 0, "budget_rejected": 0, "protocol_errors": 0}
    lock = threading.Lock()
    batch = _ACTIVE_BUDGET.get()
    transfer_limit = min(MAX_COG_TRANSFER_BYTES, batch.per_scene) if batch else MAX_COG_TRANSFER_BYTES

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_HEAD(self) -> None:
            self._forward(head=True)

        def do_GET(self) -> None:
            self._forward(head=False)

        def _reject(self, status: int) -> None:
            with lock:
                state["rejected"] += 1
            self.send_error(status)

        def _forward(self, *, head: bool) -> None:
            key = self.path.removeprefix("/").removesuffix(".tif")
            if self.path != f"/{key}.tif" or key not in hrefs:
                self._reject(404)
                return
            requested = self.headers.get("Range")
            if not head:
                match = re.fullmatch(r"bytes=(\d+)-(\d+)", requested or "")
                if not match or int(match[2]) < int(match[1]) or int(match[2]) - int(match[1]) + 1 > MAX_SINGLE_RANGE_BYTES:
                    self._reject(416)
                    return
            if batch is not None and not batch.begin_request():
                with lock:
                    state["budget_rejected"] += 1
                self._reject(429)
                return
            try:
                with httpx.Client(timeout=30, follow_redirects=False) as client:
                    with client.stream("HEAD" if head else "GET", hrefs[key],
                                       headers={"Accept-Encoding": "identity", **({"Range": requested} if requested else {})}) as upstream:
                        if upstream.status_code != (200 if head else 206):
                            self._reject(502)
                            return
                        if upstream.headers.get("Content-Encoding", "identity").lower() != "identity":
                            self._reject(502)
                            return
                        # This proxy requires fixed-length identity bodies. HTTPX
                        # honors chunked framing over a simultaneous Content-Length;
                        # accepting both would invalidate our reservation bound.
                        if "Transfer-Encoding" in upstream.headers:
                            with lock:
                                state["protocol_errors"] += 1
                            self._reject(502)
                            return
                        length_text = upstream.headers.get("Content-Length")
                        if not length_text or not length_text.isdigit():
                            self._reject(502)
                            return
                        length = int(length_text)
                        if not head:
                            content_range = upstream.headers.get("Content-Range", "")
                            returned = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                            if (not returned or int(returned[1]) != int(match[1]) or
                                    int(returned[2]) != int(match[2]) or
                                    int(returned[2]) - int(returned[1]) + 1 != length or
                                    length > MAX_SINGLE_RANGE_BYTES):
                                self._reject(502)
                                return
                        reserved = 0
                        if not head:
                            with lock:
                                # Reserve the advertised body plus one raw chunk.
                                # A malformed Content-Length can overdeliver at
                                # most that chunk before we stop forwarding.
                                allowance = length + _PROXY_CHUNK_BYTES
                                if (state["bytes"] + state["reserved"] + allowance <= transfer_limit and
                                        (batch is None or batch.reserve(allowance))):
                                    state["reserved"] += allowance
                                    reserved = allowance
                            if not reserved:
                                with lock:
                                    state["budget_rejected"] += 1
                                    if batch is not None and state["bytes"] + state["reserved"] + allowance > transfer_limit:
                                        batch.reject_scene()
                                self._reject(429)
                                return
                        accounted = 0
                        try:
                            self.send_response(200 if head else 206)
                            self.send_header("Content-Length", str(length))
                            self.send_header("Content-Type", "image/tiff")
                            self.send_header("Accept-Ranges", "bytes")
                            if not head:
                                self.send_header("Content-Range", content_range)
                            self.end_headers()
                            if head:
                                return
                            with lock:
                                state["requests"] += 1
                            remaining_declared = length
                            for chunk in upstream.iter_raw(_PROXY_CHUNK_BYTES):
                                if not chunk:
                                    continue
                                with lock:
                                    state["bytes"] += len(chunk)
                                    accounted += len(chunk)
                                    if batch is not None:
                                        batch.consume(len(chunk), min(len(chunk), reserved))
                                    if len(chunk) > reserved or len(chunk) > remaining_declared:
                                        # A provider violated Content-Length. Count the bytes
                                        # already fetched, stop forwarding, and fail the chip.
                                        state["reserved"] -= min(len(chunk), reserved)
                                        reserved -= min(len(chunk), reserved)
                                        state["protocol_errors"] += 1
                                        overrun = True
                                    else:
                                        state["reserved"] -= len(chunk)
                                        reserved -= len(chunk)
                                        overrun = False
                                remaining_declared -= len(chunk)
                                if overrun:
                                    self.close_connection = True
                                    return
                                self.wfile.write(chunk)
                        finally:
                            # HTTPX may buffer a short raw chunk and then raise
                            # before yielding it (or we may stop forwarding while
                            # more data is already buffered). Those consumed bytes
                            # still spend quota. Reconcile before releasing capacity.
                            unreported = upstream.num_bytes_downloaded - accounted
                            if unreported > 0:
                                with lock:
                                    state["bytes"] += unreported
                                    released = min(unreported, reserved)
                                    state["reserved"] -= released
                                    reserved -= released
                                    if batch is not None:
                                        batch.consume(unreported, released)
                            with lock:
                                if upstream.num_bytes_downloaded > length:
                                    state["protocol_errors"] += 1
                                if state["bytes"] > transfer_limit:
                                    state["budget_rejected"] += 1
                                    if batch is not None:
                                        batch.reject_scene()
                            if reserved:
                                with lock:
                                    state["reserved"] -= reserved
                                    if batch is not None:
                                        batch.release(reserved)
            except (httpx.HTTPError, OSError, BrokenPipeError):
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        local = {key: f"http://127.0.0.1:{server.server_port}/{key}.tif" for key in hrefs}
        yield local, state
        if state["protocol_errors"]:
            raise RuntimeError("COG response framing rejected")
        if batch is not None and state["budget_rejected"]:
            raise RuntimeError("COG transfer budget exceeded")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

