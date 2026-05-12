"""
Security tests for md_to_html.py — base_dir sandbox for image handling.

Threat model: when a global Claude Code skill auto-renders untrusted
markdown to HTML, the markdown may reference image paths that escape the
markdown's own directory — either via path traversal (`../../../etc/passwd`)
or absolute paths (`/etc/shadow`). With `--inline-images`, the contents get
base64-embedded into the published HTML, leaking sensitive local files.
With `--copy-images`, files get copied out of their original location.

The patched functions MUST refuse to read/copy any path that doesn't
resolve under base_dir.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Import the script as a module to test pure functions in isolation.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import md_to_html  # noqa: E402


def test_collect_local_images_rejects_path_traversal(tmp_path: Path) -> None:
    """A markdown referencing ../secret outside base_dir must not be collected."""
    base_dir = tmp_path / "doc"
    base_dir.mkdir()
    outside_secret = tmp_path / "secret.png"
    outside_secret.write_bytes(b"\x89PNG fake png bytes")

    md = "![exfil](../secret.png)\n"
    found = md_to_html.collect_local_images(md, base_dir)
    assert found == [], (
        f"path traversal escape must be refused; got: {found}"
    )


def test_collect_local_images_rejects_absolute_path(tmp_path: Path) -> None:
    """Absolute paths outside base_dir must not be collected."""
    base_dir = tmp_path / "doc"
    base_dir.mkdir()
    outside_secret = tmp_path / "secret.png"
    outside_secret.write_bytes(b"\x89PNG fake png bytes")

    md = f"![exfil]({outside_secret})\n"
    found = md_to_html.collect_local_images(md, base_dir)
    assert found == [], f"absolute path escape must be refused; got: {found}"


def test_collect_local_images_allows_within_base_dir(tmp_path: Path) -> None:
    """Images inside base_dir (or subdirs) must still work."""
    base_dir = tmp_path / "doc"
    base_dir.mkdir()
    (base_dir / "images").mkdir()
    inside = base_dir / "images" / "fig.png"
    inside.write_bytes(b"\x89PNG inside")

    md = "![fig](images/fig.png)\n"
    found = md_to_html.collect_local_images(md, base_dir)
    assert len(found) == 1
    assert found[0].resolve() == inside.resolve()


def test_inline_images_refuses_path_traversal(tmp_path: Path) -> None:
    """Raw HTML <img src="../secret"> must NOT get inlined."""
    base_dir = tmp_path / "doc"
    base_dir.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"SECRET_BYTES_AAA111")

    html = '<img src="../secret.png" alt="x">'
    result = md_to_html.inline_images_in_html(html, base_dir)

    assert "SECRET_BYTES" not in result
    assert "base64," not in result, (
        f"traversal path must not produce a base64 data URI; got: {result}"
    )


def test_inline_images_refuses_absolute_outside(tmp_path: Path) -> None:
    """<img src="/abs/path/outside/base_dir"> must NOT get inlined."""
    base_dir = tmp_path / "doc"
    base_dir.mkdir()
    outside = tmp_path / "shadow"
    outside.write_text("root:!:fakehit\n")

    html = f'<img src="{outside}" alt="x">'
    result = md_to_html.inline_images_in_html(html, base_dir)

    assert "fakehit" not in result
    assert "base64," not in result


def test_inline_images_allows_within_base_dir(tmp_path: Path) -> None:
    """Legit images inside base_dir get inlined normally."""
    base_dir = tmp_path / "doc"
    base_dir.mkdir()
    fig = base_dir / "fig.png"
    fig.write_bytes(b"\x89PNG fake png")

    html = '<img src="fig.png" alt="ok">'
    result = md_to_html.inline_images_in_html(html, base_dir)

    assert "base64," in result, f"expected legit image to be inlined, got: {result}"


def test_copy_images_alongside_only_copies_within_base(tmp_path: Path) -> None:
    """copy_images_alongside given a path outside base_dir must not copy it."""
    base_dir = tmp_path / "doc"
    base_dir.mkdir()
    out_dir = tmp_path / "out"
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"OUTSIDE_BYTES")
    # Simulate the broken state: caller hands us a path outside base.
    md_to_html.copy_images_alongside([outside], base_dir, out_dir, quiet=True)

    # The outside file's content must not appear under out_dir.
    if out_dir.exists():
        for p in out_dir.rglob("*"):
            if p.is_file():
                assert b"OUTSIDE_BYTES" not in p.read_bytes(), (
                    f"path outside base_dir leaked to {p}"
                )
