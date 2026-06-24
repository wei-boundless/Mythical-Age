from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.token_accounting import count_text_tokens


@dataclass(frozen=True, slots=True)
class TokenCountResult:
    tokens: int
    provider: str = ""
    model: str = ""
    mode: str = "local_predicted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
        }


class TokenCounterRegistry:
    """Local token prediction registry.

    Provider usage remains the billing truth. This registry is only the
    pre-request budget predictor used by runtime assembly and compression.
    """

    LOCAL_EXACT_ENCODINGS = {
        "openai:gpt-4.1",
        "openai:gpt-4.1-mini",
        "openai:gpt-4o",
        "openai:gpt-4o-mini",
    }

    def count_text(self, text: str, *, provider: str = "", model: str = "") -> TokenCountResult:
        tokens = count_text_tokens(str(text or ""))
        mode = "local_exact" if self._local_exact(provider=provider, model=model) else "local_predicted"
        return TokenCountResult(tokens=tokens, provider=str(provider or ""), model=str(model or ""), mode=mode)

    def count_messages(self, messages: list[Any], *, provider: str = "", model: str = "") -> TokenCountResult:
        from .serializer import canonical_json, normalize_messages

        payload = canonical_json({"messages": normalize_messages(messages)})
        return self.count_text(payload, provider=provider, model=model)

    def _local_exact(self, *, provider: str, model: str) -> bool:
        key = f"{str(provider or '').strip().lower()}:{str(model or '').strip().lower()}"
        return key in self.LOCAL_EXACT_ENCODINGS

