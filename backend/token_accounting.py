from __future__ import annotations

import re
from functools import lru_cache

try:
    import tiktoken
except ImportError:  # pragma: no cover - optional dependency at runtime
    tiktoken = None


_WHITESPACE_RE = re.compile(r"\s+")


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
    return max(1, len(compact) // 4) if compact else 0
