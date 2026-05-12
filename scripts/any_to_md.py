#!/usr/bin/env python3
"""
any_to_md.py — Convert any file to Markdown using Microsoft markitdown.

Supports: PDF, DOCX, PPTX, XLSX, XLS, HTML, CSV, JSON, XML, EPub, ZIP,
images (EXIF + optional LLM description), audio (with transcription),
YouTube URLs (with auto subtitles), Outlook .msg, and more.

Part of huashu-md-html skill — md is source, html is product.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


HELP_INSTALL = """\
markitdown is not installed. Install it with:

    pip install 'markitdown[all]'

Or, for a slimmer install (only the formats you need):

    pip install 'markitdown[pdf,docx,pptx,xlsx]'
"""


def ensure_markitdown():
    try:
        from markitdown import MarkItDown  # noqa: F401
    except ImportError:
        sys.stderr.write(HELP_INSTALL)
        sys.exit(2)


ALLOWED_URL_SCHEMES = ("http", "https")
BLOCKED_SCHEMES_HINT = (
    "Only http://, https://, or local file paths are accepted. "
    "file:, data:, ftp:, gopher:, javascript:, mailto:, etc. are rejected because "
    "this script is designed to run inside an AI agent harness where an "
    "untrusted source argument could otherwise read arbitrary local files "
    "and leak their contents into the generated markdown."
)


def validate_source(source: str) -> None:
    """Reject non-http(s) URI schemes; plain paths pass through.

    When an LLM agent auto-invokes this script, a `file://` or `data:`
    argument injected via prompt or filename gives the attacker an arbitrary
    local-file read whose content lands in the output markdown (and back into
    the agent's context). Block at the entrypoint before markitdown sees it.

    Uses urlsplit() so single-slash forms (`file:/etc/passwd`), leading
    whitespace, and case-variants (`FILE://`, ` DATA:`) are also caught.
    """
    from urllib.parse import urlsplit

    stripped = source.strip()
    parts = urlsplit(stripped)
    scheme = parts.scheme.lower()

    if not scheme:
        return  # plain local path — markitdown will validate existence

    if scheme not in ALLOWED_URL_SCHEMES:
        sys.stderr.write(
            f"[error] scheme {scheme!r}: is not allowed.\n{BLOCKED_SCHEMES_HINT}\n",
        )
        sys.exit(2)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Convert any file (or URL) to Markdown via Microsoft markitdown.",
    )
    p.add_argument(
        "source",
        help="File path or http(s):// URL (incl. YouTube). file://, data:, ftp://, etc. are rejected.",
    )
    p.add_argument(
        "-o", "--output",
        help="Output .md path. If omitted, writes to <source-stem>.md in CWD; use '-' for stdout.",
    )
    p.add_argument(
        "--llm-describe",
        action="store_true",
        help="Enable LLM-based image description. Requires OPENAI_API_KEY.",
    )
    p.add_argument(
        "--llm-model",
        default=os.environ.get("MARKITDOWN_LLM_MODEL", "gpt-4o"),
        help="LLM model for image description (default: gpt-4o, or env MARKITDOWN_LLM_MODEL).",
    )
    p.add_argument(
        "--azure-doc-intel",
        default=None,
        help=(
            "Azure Document Intelligence endpoint URL for high-fidelity PDF OCR. "
            "Must be passed explicitly — the AZURE_DOC_INTEL_ENDPOINT env var "
            "is intentionally NOT auto-read so an agent harness can't silently "
            "ship private documents to a cloud OCR service."
        ),
    )
    p.add_argument(
        "--enable-plugins",
        action="store_true",
        help=(
            "Enable third-party markitdown plugins. WARNING: plugins are arbitrary "
            "Python code; only enable if you have explicitly installed plugins you trust."
        ),
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-error stderr output.",
    )
    return p.parse_args()


def build_converter(args: argparse.Namespace):
    from markitdown import MarkItDown

    kwargs = {"enable_plugins": args.enable_plugins}

    if args.enable_plugins and not args.quiet:
        sys.stderr.write(
            "[warn] --enable-plugins is on. Third-party markitdown plugins run as "
            "arbitrary Python code; ensure you trust every installed plugin.\n",
        )

    if args.llm_describe:
        try:
            from openai import OpenAI
        except ImportError:
            sys.stderr.write(
                "--llm-describe requires the 'openai' package: pip install openai\n",
            )
            sys.exit(2)
        if not os.environ.get("OPENAI_API_KEY"):
            sys.stderr.write(
                "--llm-describe requires OPENAI_API_KEY environment variable.\n",
            )
            sys.exit(2)
        kwargs["llm_client"] = OpenAI()
        kwargs["llm_model"] = args.llm_model

    if args.azure_doc_intel:
        kwargs["docintel_endpoint"] = args.azure_doc_intel

    return MarkItDown(**kwargs)


def resolve_output_path(source: str, output: str | None) -> Path | None:
    if output == "-":
        return None
    if output:
        return Path(output)
    # Default: <source-stem>.md in CWD
    if source.startswith(("http://", "https://")):
        # URL → use a generic name
        return Path("converted.md")
    return Path(Path(source).stem + ".md")


def warn_known_pitfalls(source: str, content: str, quiet: bool) -> None:
    if quiet:
        return
    suffix = Path(source).suffix.lower() if "://" not in source else ""
    if suffix == ".pdf" and len(content.strip()) < 200:
        sys.stderr.write(
            "[hint] Output is very short — this PDF may be a scanned document.\n"
            "       Try --llm-describe or --azure-doc-intel for OCR.\n",
        )
    if suffix in {".pptx", ".ppt"}:
        sys.stderr.write(
            "[hint] PPTX text + speaker notes preserved; animations and layout are dropped.\n",
        )


def main() -> int:
    ensure_markitdown()
    args = parse_args()
    validate_source(args.source)

    converter = build_converter(args)

    try:
        result = converter.convert(args.source)
    except Exception as exc:  # noqa: BLE001 — markitdown wraps various errors
        sys.stderr.write(f"[error] markitdown failed: {exc}\n")
        return 1

    content = result.text_content or ""

    out_path = resolve_output_path(args.source, args.output)
    if out_path is None:
        sys.stdout.write(content)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        if not args.quiet:
            sys.stderr.write(f"[ok] {args.source} → {out_path}\n")

    warn_known_pitfalls(args.source, content, args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
