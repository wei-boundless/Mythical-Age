from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any


HTML_TAG_RE = re.compile(r"<[a-zA-Z!/][^>]*>")
NOISE_RE = re.compile(
    r"<(script|style|noscript|svg|canvas|template|header|footer|nav|aside)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
BLOCK_TAG_RE = re.compile(r"</?(p|br|div|section|article|main|li|ul|ol|h[1-6]|tr|td|th|blockquote)\b[^>]*>", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")


class _TitleDescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_parts: list[str] = []
        self.description = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self.in_title = True
        if normalized != "meta":
            return
        attr_map = {str(key or "").lower(): str(value or "") for key, value in attrs}
        name = attr_map.get("name", "").lower()
        prop = attr_map.get("property", "").lower()
        if name == "description" or prop in {"og:description", "twitter:description"}:
            content = attr_map.get("content", "").strip()
            if content and not self.description:
                self.description = content

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    def summary_parts(self) -> list[str]:
        return [_clean_spacing(" ".join(self.title_parts)), _clean_spacing(self.description)]


def clean_web_text(value: Any, *, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if _looks_like_html(text):
        return _html_to_text(text, limit=limit)
    return _clean_spacing(html.unescape(text))[:limit].strip()


def best_web_excerpt(item: dict[str, Any], *, limit: int = 900) -> str:
    for key in ("clean_text", "raw_content", "content", "answer"):
        text = clean_web_text(item.get(key), limit=max(limit * 2, 1200))
        if text:
            return text[:limit].strip()
    return ""


def normalize_web_result_item(item: dict[str, Any], *, fetched_payload: dict[str, Any] | None = None, limit: int = 3000) -> dict[str, Any]:
    result = dict(item)
    fetched = dict(fetched_payload or {})
    fetched_text = clean_web_text(fetched.get("content"), limit=limit)
    original_text = clean_web_text(result.get("raw_content") or result.get("content"), limit=limit)
    clean_text = fetched_text or original_text
    if clean_text:
        result["clean_text"] = clean_text
        if fetched_text:
            result["raw_content"] = fetched_text
        elif result.get("raw_content"):
            result["raw_content"] = original_text
        else:
            result["content"] = original_text
    if fetched:
        result["fetch"] = {
            "ok": bool(fetched.get("ok")),
            "content_type": str(fetched.get("content_type") or ""),
            "error": str(fetched.get("error") or ""),
        }
    return result


def _html_to_text(value: str, *, limit: int) -> str:
    parser = _TitleDescriptionParser()
    try:
        parser.feed(value[:20000])
    except Exception:
        pass
    text = NOISE_RE.sub(" ", value)
    text = re.sub(r"<style\b[^>]*>.*?(?:</style>|$)", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<script\b[^>]*>.*?(?:</script>|$)", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = BLOCK_TAG_RE.sub("\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(
        r"<(script|style|noscript|svg|canvas|template|header|footer|nav|aside)\b[^>]*>.*?(?:</\1>|$)",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<(meta|link)\b[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [_clean_spacing(line) for line in text.splitlines()]
    summary_parts = [part for part in parser.summary_parts() if part]
    useful_lines: list[str] = []
    seen: set[str] = set()
    for line in [*summary_parts, *lines]:
        if not _is_useful_line(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        useful_lines.append(line)
        seen.add(key)
        if sum(len(item) for item in useful_lines) >= limit:
            break
    return _clean_spacing(" ".join(useful_lines))[:limit].strip()


def _looks_like_html(value: str) -> bool:
    sample = value[:1000].lower()
    return "<!doctype html" in sample or "<html" in sample or bool(HTML_TAG_RE.search(sample))


def _clean_spacing(value: str) -> str:
    return SPACE_RE.sub(" ", str(value or "").replace("\u200b", " ")).strip()


def _is_useful_line(value: str) -> bool:
    text = _clean_spacing(value)
    if len(text) < 30:
        return False
    lowered = text.lower()
    if lowered.startswith(("function(", "window.", "document.", "var ", "const ", "let ")):
        return False
    if _looks_like_css_or_code(text):
        return False
    return True


def _looks_like_css_or_code(text: str) -> bool:
    if sum(1 for char in text if char in "{};<>=") > max(8, len(text) // 10):
        return True
    lowered = text.lower()
    css_tokens = (
        "{--",
        ":where(",
        "scrollbar-",
        "font-size:",
        "line-height:",
        "background:",
        "display:",
        "padding:",
        "margin:",
        "border:",
        "rgb(",
        "var(--",
    )
    if any(token in lowered for token in css_tokens):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", text)
    if not words:
        return True
    symbol_count = sum(1 for char in text if not char.isalnum() and not char.isspace())
    return symbol_count > max(20, len(text) // 4) and len(words) < 12
