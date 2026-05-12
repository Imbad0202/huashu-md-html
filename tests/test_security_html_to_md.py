"""
Security tests for html_to_md.py — fetch hardening.

Threat model: a global skill auto-fetches URLs the LLM agent receives via
prompt. An attacker who can influence those URLs can:
  - serve a 500MB response that exhausts the agent's memory
  - redirect from http(s) to a more dangerous scheme

The patched fetch MUST:
  1. cap response bytes (default 50MB, can be reduced for testing)
  2. reject any final response URL whose scheme is not http(s) — i.e., if
     a redirect somehow lands on file:// or gopher://, refuse it
"""
from __future__ import annotations

import http.server
import socket
import sys
import threading
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import html_to_md  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve_bytes(payload: bytes) -> tuple[str, http.server.HTTPServer]:
    port = _free_port()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a, **kw):  # silence
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/", srv


def test_response_size_cap_enforced(monkeypatch) -> None:
    """When response exceeds MAX_RESPONSE_BYTES, fetch_url must raise/abort."""
    big = b"<html><body>" + b"A" * 5000 + b"</body></html>"
    url, srv = _serve_bytes(big)
    try:
        # Squeeze cap below the response size
        monkeypatch.setattr(html_to_md, "MAX_RESPONSE_BYTES", 1000)
        import pytest
        with pytest.raises((ValueError, OSError)) as exc:
            html_to_md.fetch_url(url, "test-ua")
        msg = str(exc.value).lower()
        assert "size" in msg or "cap" in msg or "too large" in msg or "limit" in msg, (
            f"error message must mention size cap; got: {exc.value!r}"
        )
    finally:
        srv.shutdown()


def test_response_within_cap_succeeds(monkeypatch) -> None:
    """Small response stays well below cap and returns content."""
    payload = b"<html><body>tiny ok</body></html>"
    url, srv = _serve_bytes(payload)
    try:
        monkeypatch.setattr(html_to_md, "MAX_RESPONSE_BYTES", 1_000_000)
        out = html_to_md.fetch_url(url, "test-ua")
        assert "tiny ok" in out
    finally:
        srv.shutdown()


def test_max_response_bytes_default_reasonable() -> None:
    """Default cap should be defined and >= 10MB (so normal pages work)."""
    assert hasattr(html_to_md, "MAX_RESPONSE_BYTES")
    assert html_to_md.MAX_RESPONSE_BYTES >= 10_000_000


def test_block_private_ip_refuses_loopback() -> None:
    """When block_private_ip=True, fetch_url must refuse 127.0.0.1 URLs."""
    import pytest
    with pytest.raises(ValueError) as exc:
        html_to_md.fetch_url("http://127.0.0.1:1/", "test", block_private_ip=True)
    assert "private" in str(exc.value).lower() or "loopback" in str(exc.value).lower()


def test_block_private_ip_off_allows_loopback() -> None:
    """When block_private_ip=False (default), loopback fetches at least pass the
    SSRF gate (and fail later for normal reasons like connection refused)."""
    payload = b"<html><body>local ok</body></html>"
    url, srv = _serve_bytes(payload)
    try:
        out = html_to_md.fetch_url(url, "test", block_private_ip=False)
        assert "local ok" in out
    finally:
        srv.shutdown()
