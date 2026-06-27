from __future__ import annotations

import html
import json
import re
from typing import Any


CONTEXT_FRAGMENT_TAG = "context_fragment"
CONTEXT_FRAGMENT_PROTOCOL = "context_fragment.v1"

_CONTEXT_FRAGMENT_RE = re.compile(
    r"<context_fragment\b(?P<attrs>[^>]*)>\s*(?P<body>.*?)\s*</context_fragment>",
    re.DOTALL,
)
_ATTRIBUTE_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_:-]*)="([^"]*)"')


def render_context_fragment(
    *,
    kind: str,
    payload: Any,
    title: str = "",
    role: str = "",
    source_ref: str = "",
    cache_scope: str = "",
    cache_role: str = "",
    prefix_tier: str = "",
    compression_role: str = "",
    validity_scope: str = "",
) -> str:
    attributes = _context_fragment_attributes(
        kind=kind,
        title=title,
        role=role,
        source_ref=source_ref,
        cache_scope=cache_scope,
        cache_role=cache_role,
        prefix_tier=prefix_tier,
        compression_role=compression_role,
        validity_scope=validity_scope,
    )
    body = _json_for_fragment({"payload": _json_stable(payload)})
    return f"<{CONTEXT_FRAGMENT_TAG}{attributes}>\n{body}\n</{CONTEXT_FRAGMENT_TAG}>"


def render_text_context_fragment(
    *,
    kind: str,
    text: str,
    title: str = "",
    role: str = "system",
    source_ref: str = "",
    cache_scope: str = "",
    cache_role: str = "",
    prefix_tier: str = "",
    compression_role: str = "",
    validity_scope: str = "",
) -> str:
    attributes = _context_fragment_attributes(
        kind=kind,
        title=title,
        role=role,
        source_ref=source_ref,
        cache_scope=cache_scope,
        cache_role=cache_role,
        prefix_tier=prefix_tier,
        compression_role=compression_role,
        validity_scope=validity_scope,
    )
    body = _json_for_fragment({"text": str(text or "")})
    return f"<{CONTEXT_FRAGMENT_TAG}{attributes}>\n{body}\n</{CONTEXT_FRAGMENT_TAG}>"


def parse_context_fragments(text: str) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for match in _CONTEXT_FRAGMENT_RE.finditer(str(text or "")):
        body_text = str(match.group("body") or "").strip()
        if not body_text:
            continue
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            continue
        fragments.append(
            {
                "attributes": _parse_attributes(str(match.group("attrs") or "")),
                "body": body,
            }
        )
    return fragments


def parse_context_fragment_payload(text: str) -> Any | None:
    for fragment in parse_context_fragments(text):
        body = fragment.get("body")
        if isinstance(body, dict) and "payload" in body:
            return body.get("payload")
    return None


def is_context_fragment(text: str) -> bool:
    return bool(parse_context_fragments(text))


def _context_fragment_attributes(
    *,
    kind: str,
    title: str,
    role: str,
    source_ref: str,
    cache_scope: str,
    cache_role: str,
    prefix_tier: str,
    compression_role: str,
    validity_scope: str,
) -> str:
    attributes = {
        "protocol": CONTEXT_FRAGMENT_PROTOCOL,
        "kind": str(kind or "unknown_context").strip() or "unknown_context",
        "title": str(title or "").strip(),
        "role": str(role or "").strip(),
    }
    rendered = [
        f'{key}="{_escape_attr(value)}"'
        for key, value in attributes.items()
        if str(value or "").strip()
    ]
    return " " + " ".join(rendered) if rendered else ""


def _parse_attributes(raw: str) -> dict[str, str]:
    return {
        str(match.group(1)): html.unescape(str(match.group(2) or ""))
        for match in _ATTRIBUTE_RE.finditer(str(raw or ""))
    }


def _escape_attr(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def _json_for_fragment(value: Any) -> str:
    text = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
