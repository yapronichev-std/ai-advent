"""HTML / MHTML text extraction for RAG document ingestion.

Converts HTML pages into clean plain text with Markdown-style headings
so the structural chunker in rag.py can split them correctly.
MHTML (saved web pages) is parsed via the stdlib email module.
"""

from __future__ import annotations

import email
import email.message
import html.parser
import logging
import re
from base64 import b64decode
from quopri import decodestring as quopri_decode
from typing import Any

logger = logging.getLogger(__name__)

# Tags whose *text* should be kept but whose tag wrappers are discarded.
# Inline elements that don't add structure — their text is extracted inline.
_INLINE_TAGS = frozenset({"span", "b", "strong", "i", "em", "u", "code", "kbd",
                          "samp", "sub", "sup", "small", "mark", "ins", "del",
                          "abbr", "cite", "q", "time", "var", "font", "tt", "big"})

# Tags that always produce a line break *after* their content (block-level).
_BLOCK_TAGS = frozenset({"p", "div", "section", "article", "main", "aside",
                          "header", "footer", "nav", "form", "fieldset",
                          "figure", "figcaption", "details", "summary"})

# Tags that produce a blank line *before* their content (headings and structural).
_HEADING_TAGS = {f"h{i}": i for i in range(1, 7)}  # h1->1, h2->2, …, h6->6

# Tags whose entire subtree is removed (no text content worth indexing).
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "iframe",
                         "canvas", "svg", "object", "embed", "applet", "video",
                         "audio", "source", "track"})


class _HtmlToText(html.parser.HTMLParser):
    """SAX-style HTML parser that extracts clean text with markdown headings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._lines: list[str] = []
        self._buf: list[str] = []          # current line buffer
        self._title: str = ""
        self._in_title = False
        self._skip_depth = 0
        self._headings: list[dict[str, Any]] = []

    # ── results ──────────────────────────────────────────────────────────────

    def result(self) -> dict[str, Any]:
        self._flush_buf()
        clean = "\n".join(self._lines).strip()
        # Collapse 3+ consecutive newlines into 2
        clean = re.sub(r"\n{3,}", "\n\n", clean)
        return {
            "clean_text": clean,
            "title": self._title.strip(),
            "headings": self._headings,
        }

    # ── helpers ──────────────────────────────────────────────────────────────

    def _flush_buf(self) -> None:
        text = " ".join(self._buf).strip()
        if text:
            self._lines.append(text)
        self._buf.clear()

    def _add_blank(self) -> None:
        self._flush_buf()
        if self._lines and self._lines[-1] != "":
            self._lines.append("")

    def _should_skip(self) -> bool:
        return self._skip_depth > 0

    # ── SAX callbacks ────────────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()

        if tag_l in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._should_skip():
            return

        if tag_l == "title":
            self._in_title = True
        elif tag_l in _HEADING_TAGS:
            self._flush_buf()
            level = _HEADING_TAGS[tag_l]
            self._lines.append("")  # blank before heading

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()

        if tag_l in _SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
            return
        if self._should_skip():
            return

        if tag_l == "title":
            self._in_title = False
            self._title = " ".join(self._buf).strip()
            self._buf.clear()
        elif tag_l in _HEADING_TAGS:
            heading_text = " ".join(self._buf).strip()
            if heading_text:
                level = _HEADING_TAGS[tag_l]
                self._lines.append(f"{'#' * level} {heading_text}")
                self._lines.append("")
                self._headings.append({"level": level, "text": heading_text})
            self._buf.clear()
        elif tag_l in _BLOCK_TAGS:
            self._flush_buf()
        elif tag_l == "br":
            self._flush_buf()
        elif tag_l in ("tr", "table"):
            self._flush_buf()
        elif tag_l == "li":
            text = " ".join(self._buf).strip()
            if text:
                self._lines.append(f"- {text}")
            self._buf.clear()

    def handle_data(self, data: str) -> None:
        if self._should_skip():
            return
        if not data or not data.strip():
            return
        self._buf.append(data.strip())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Self-closing tags like <br/>, <hr/>, <img/>."""
        if self._should_skip():
            return
        tag_l = tag.lower()
        if tag_l == "br":
            self._flush_buf()
        elif tag_l == "hr":
            self._flush_buf()
            self._lines.append("---")
        elif tag_l == "img":
            for k, v in attrs:
                if k == "alt" and v:
                    self._buf.append(f"[image: {v}]")
                    break


class HtmlExtractor:
    """Extract clean text and metadata from HTML or MHTML documents."""

    # Patterns for format detection
    _HTML_SNIFF = re.compile(
        r'<!DOCTYPE\s+html|<html[\s>]|<head[\s>]|<body[\s>]',
        re.IGNORECASE,
    )
    _MHTML_SNIFF = re.compile(
        r'^(From:|MIME-Version:|Content-Type:\s*(multipart/related|message/rfc822|text/html))',
        re.MULTILINE | re.IGNORECASE,
    )

    @staticmethod
    def detect_format(text: str) -> str:
        """Return 'html', 'mhtml' or 'text' based on content heuristics."""
        # Strip leading BOM / whitespace for sniffing
        sample = text.lstrip("﻿").strip()[:4096]
        if HtmlExtractor._MHTML_SNIFF.search(sample):
            return "mhtml"
        if HtmlExtractor._HTML_SNIFF.search(sample):
            return "html"
        return "text"

    @staticmethod
    def from_html(html_text: str) -> dict[str, Any]:
        """Parse HTML and return {'clean_text': ..., 'title': ..., 'headings': ...}.

        - <script>/<style>/<noscript> subtrees are removed entirely.
        - <h1>…<h6> are converted to Markdown-style ``# …`` / ``## …`` lines
          so that the structural chunker in rag.py can split on them.
        - Block-level tags produce paragraph breaks.
        - Inline tags are stripped, keeping their inner text.
        """
        parser = _HtmlToText()
        try:
            parser.feed(html_text)
            parser.close()
        except Exception as exc:
            logger.warning("[HtmlExtractor] from_html parse error: %s", exc)
        return parser.result()

    @staticmethod
    def from_mhtml(mhtml_text: str) -> dict[str, Any]:
        """Parse an MHTML (MIME HTML) document and return the same dict as from_html().

        MHTML is a multipart/related MIME message saved by browsers.
        We find the first text/html part, decode it (QP / base64), and
        hand it to from_html().
        """
        try:
            msg = email.message_from_string(mhtml_text)
        except Exception as exc:
            logger.warning("[HtmlExtractor] from_mhtml parse error: %s", exc)
            return {"clean_text": "", "title": "", "headings": []}

        html_payload = HtmlExtractor._find_html_part(msg)
        if html_payload is None:
            logger.warning("[HtmlExtractor] from_mhtml: no text/html part found")
            return {"clean_text": "", "title": "", "headings": []}

        return HtmlExtractor.from_html(html_payload)

    @staticmethod
    def _find_html_part(msg: email.message.Message) -> str | None:
        """Recursively walk a MIME tree for the first text/html part."""
        if msg.is_multipart():
            for part in msg.get_payload():
                result = HtmlExtractor._find_html_part(part)  # type: ignore[arg-type]
                if result is not None:
                    return result
            return None

        content_type = msg.get_content_type()
        if content_type != "text/html":
            return None

        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            # Handle charset if specified
            charset = msg.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                return payload.decode("utf-8", errors="replace")
        return str(payload) if payload else None
