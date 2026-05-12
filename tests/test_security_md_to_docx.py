"""
Security tests for md_to_docx.py — image resolver base_dir sandbox.

Threat model: same as md_to_html. Untrusted markdown referencing
`![alt](/etc/passwd)` or `![alt](../../../private.key)` would get embedded
into the docx by python-docx's add_picture. The image resolver MUST refuse
any path that isn't either:
  - under the markdown file's own directory
  - under the explicit `--images-dir` if the user passed one

Anything else is rejected (returns None / no picture embedded).
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# md_to_docx is heavy on top-level imports; we need a stub PIL/docx-free way.
# Instead of importing the whole script, we run the resolver as a smoke test
# via subprocess. But the resolver is a closure inside build_docx — to test
# it we extract the helper logic into a standalone function. So this test
# requires the patch to factor out `resolve_image_path`. The patch will add
# that helper to md_to_docx.py.
import md_to_docx  # noqa: E402


def test_resolver_rejects_absolute_outside_base(tmp_path: Path) -> None:
    """An absolute path outside md_dir + images_dir must resolve to None."""
    md_dir = tmp_path / "doc"
    md_dir.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"\x89PNG SECRET")

    result = md_to_docx.resolve_image_path(
        path_str=str(outside),
        md_dir=md_dir,
        images_dir=None,
    )
    assert result is None, f"absolute outside path must be refused; got {result}"


def test_resolver_rejects_path_traversal(tmp_path: Path) -> None:
    """`../secret.png` from md_dir must NOT be resolved."""
    md_dir = tmp_path / "doc"
    md_dir.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"\x89PNG SECRET")

    result = md_to_docx.resolve_image_path(
        path_str="../secret.png",
        md_dir=md_dir,
        images_dir=None,
    )
    assert result is None, f"traversal must be refused; got {result}"


def test_resolver_allows_within_md_dir(tmp_path: Path) -> None:
    """A normal relative image inside md_dir works."""
    md_dir = tmp_path / "doc"
    md_dir.mkdir()
    fig = md_dir / "fig.png"
    fig.write_bytes(b"\x89PNG normal")

    result = md_to_docx.resolve_image_path(
        path_str="fig.png",
        md_dir=md_dir,
        images_dir=None,
    )
    assert result is not None
    assert Path(result).resolve() == fig.resolve()


def test_resolver_allows_within_images_dir(tmp_path: Path) -> None:
    """A path under the user-specified --images-dir works."""
    md_dir = tmp_path / "doc"
    md_dir.mkdir()
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    fig = images_dir / "ch01-fig01.png"
    fig.write_bytes(b"\x89PNG in images-dir")

    # md doesn't have it locally; resolver should look in images_dir by basename
    result = md_to_docx.resolve_image_path(
        path_str="ch01-fig01.png",
        md_dir=md_dir,
        images_dir=images_dir,
    )
    assert result is not None
    assert Path(result).resolve() == fig.resolve()


def test_resolver_rejects_traversal_via_images_dir(tmp_path: Path) -> None:
    """Even with --images-dir set, ../escape paths must be refused."""
    md_dir = tmp_path / "doc"
    md_dir.mkdir()
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    outside = tmp_path / "evil.png"
    outside.write_bytes(b"\x89PNG EVIL")

    result = md_to_docx.resolve_image_path(
        path_str="../evil.png",
        md_dir=md_dir,
        images_dir=images_dir,
    )
    assert result is None
