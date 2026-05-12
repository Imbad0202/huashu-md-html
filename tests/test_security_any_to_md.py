"""
Security tests for any_to_md.py — scheme allowlist.

Threat model: when this script runs as part of a global Claude Code skill,
an LLM agent may be induced (via prompt injection in markdown content, or
a misleading user request) to pass a `file://` or `data:` URI as the
"source". markitdown happily reads those, giving the attacker an arbitrary
local-file-read primitive whose contents flow into LLM context or get
written to a markdown the user later publishes.

The script MUST reject these schemes before invoking markitdown.
Allowed: http://, https://, plain local paths (relative or absolute).
Rejected: file://, data:, ftp://, gopher://, javascript:, anything else.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "any_to_md.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def test_rejects_file_scheme(tmp_path: Path) -> None:
    secret = tmp_path / "fake-passwd"
    secret.write_text("root:x:0:0:fakehit\n", encoding="utf-8")
    out = tmp_path / "out.md"

    result = run(f"file://{secret}", "-o", str(out))

    assert result.returncode != 0, "expected non-zero exit when file:// scheme used"
    assert not out.exists() or out.read_text() == "", (
        f"output file must NOT contain secret content, got: {out.read_text() if out.exists() else '<no file>'}"
    )
    combined = (result.stderr + result.stdout).lower()
    assert "file://" in combined or "scheme" in combined or "not allowed" in combined, (
        f"error message should explain scheme rejection. stderr={result.stderr!r}"
    )


def test_rejects_data_scheme(tmp_path: Path) -> None:
    out = tmp_path / "out.md"
    result = run("data:text/plain;base64,aGVsbG8=", "-o", str(out))

    assert result.returncode != 0
    combined = (result.stderr + result.stdout).lower()
    assert "data:" in combined or "scheme" in combined or "not allowed" in combined


def test_rejects_gopher_scheme(tmp_path: Path) -> None:
    out = tmp_path / "out.md"
    result = run("gopher://example.com/", "-o", str(out))
    assert result.returncode != 0


def test_rejects_single_slash_file_uri(tmp_path: Path) -> None:
    """`file:/etc/passwd` (no `://`) must also be rejected.

    The earlier substring check missed this form — urlsplit catches it.
    """
    out = tmp_path / "out.md"
    result = run("file:/etc/hosts", "-o", str(out))
    assert result.returncode != 0


def test_rejects_uppercase_scheme(tmp_path: Path) -> None:
    """`FILE://...` and `DATA:...` must be rejected case-insensitively."""
    out = tmp_path / "out.md"
    result = run("FILE:///etc/hosts", "-o", str(out))
    assert result.returncode != 0


def test_rejects_leading_whitespace_scheme(tmp_path: Path) -> None:
    """Leading whitespace must not let a bad scheme through."""
    out = tmp_path / "out.md"
    result = run(" file:///etc/hosts", "-o", str(out))
    assert result.returncode != 0


def test_rejects_javascript_scheme(tmp_path: Path) -> None:
    out = tmp_path / "out.md"
    result = run("javascript:alert(1)", "-o", str(out))
    assert result.returncode != 0


def test_rejects_mailto_scheme(tmp_path: Path) -> None:
    out = tmp_path / "out.md"
    result = run("mailto:a@b.com", "-o", str(out))
    assert result.returncode != 0


def test_allows_http_scheme_reaches_markitdown(tmp_path: Path) -> None:
    """
    http:// MUST still pass our gate. We don't need to actually fetch — we
    just need to confirm the script doesn't reject it at the scheme stage.
    Using an unreachable host so the error comes from markitdown, not us.
    """
    out = tmp_path / "out.md"
    # Point at a definitely-non-routable IP to keep test fast and offline.
    result = run("http://127.0.0.1:1/nonexistent", "-o", str(out))
    # Either markitdown fails (non-zero) with a network error, or it
    # somehow succeeds — what we MUST NOT see is our scheme-rejection text.
    combined = (result.stderr + result.stdout).lower()
    assert "scheme" not in combined or "http" in combined, (
        f"http should pass scheme gate. stderr={result.stderr!r}"
    )


def test_allows_local_path(tmp_path: Path) -> None:
    """A plain local path MUST pass the scheme gate (markitdown handles it)."""
    f = tmp_path / "hello.txt"
    f.write_text("hello\n", encoding="utf-8")
    out = tmp_path / "out.md"
    result = run(str(f), "-o", str(out))
    combined = (result.stderr + result.stdout).lower()
    # Must not be rejected for scheme reasons. Markitdown might still fail
    # (e.g., if .txt isn't supported in slim install) — that's fine.
    assert "scheme" not in combined or "not allowed" not in combined
