from __future__ import annotations

import re
from math import ceil
from functools import lru_cache

try:
    import tiktoken
except ImportError:  # pragma: no cover - optional dependency at runtime
    tiktoken = None


_WHITESPACE_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]")
_JSON_SYMBOL_RE = re.compile(r"[{}\[\]\":,]")


@lru_cache(maxsize=1)
def _encoder():
    if tiktoken is None:
        return None
    return tiktoken.get_encoding("cl100k_base")


def count_text_tokens(text: str) -> int:
    value = str(text or "")
    encoder = _encoder()
    if encoder is not None:
        return len(encoder.encode(value))
    compact = _WHITESPACE_RE.sub(" ", value).strip()
    return _language_aware_estimate(compact)


def _language_aware_estimate(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    ascii_word = len(_ASCII_WORD_RE.findall(text))
    json_symbols = len(_JSON_SYMBOL_RE.findall(text))
    whitespace = sum(1 for char in text if char.isspace())
    other = max(0, len(text) - cjk - ascii_word - json_symbols - whitespace)
    estimated = cjk * 0.6 + ascii_word * 0.3 + json_symbols * 0.45 + other * 0.5
    return max(1, int(ceil(estimated)))


