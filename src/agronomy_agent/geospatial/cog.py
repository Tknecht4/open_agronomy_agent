"""Shared bounded range transport for provider-admitted COG URLs.

Provider adapters validate asset host/path and source identity before calling.
This transport never follows redirects and preserves fixed range/transfer caps;
credentials, if a provider requires public short-lived signing, stay in memory.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
import httpx

MAX_COG_TRANSFER_BYTES = 256 * 1024 * 1024
MAX_SINGLE_RANGE_BYTES = 64 * 1024 * 1024
_PROXY_CHUNK_BYTES = 16 * 1024


@contextmanager
def bounded_cog_proxy(hrefs: dict[str, str]):
    """Serve fixed public COG assets to GDAL through a capped loopback proxy.

    All outward requests use httpx without redirects. This also prevents SAS
    query strings from entering GDAL paths, errors, and receipts.
    """
    state = {"bytes": 0, "reserved": 0, "requests": 0, "rejected": 0}
    lock = threading.Lock()

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
                                if state["bytes"] + state["reserved"] + allowance <= MAX_COG_TRANSFER_BYTES:
                                    state["reserved"] += allowance
                                    reserved = allowance
                            if not reserved:
                                self._reject(429)
                                return
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
                                    if len(chunk) > reserved or len(chunk) > remaining_declared:
                                        # A provider violated Content-Length. Count the bytes
                                        # already fetched, stop forwarding, and fail the chip.
                                        state["reserved"] -= min(len(chunk), reserved)
                                        reserved -= min(len(chunk), reserved)
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
                            if reserved:
                                with lock:
                                    state["reserved"] -= reserved
            except (httpx.HTTPError, OSError, BrokenPipeError):
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        local = {key: f"http://127.0.0.1:{server.server_port}/{key}.tif" for key in hrefs}
        yield local, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

