from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderRequestProfile:
    provider: str
    model: str
    base_url: str = ""
    max_output_tokens: int | None = None
    temperature: float | None = None
    thinking_mode: str = ""
    reasoning_effort: str = ""
    stream_policy: dict[str, Any] = field(default_factory=dict)
    response_format: dict[str, Any] = field(default_factory=dict)
    structured_output: str = ""
    completion_profile: dict[str, Any] = field(default_factory=dict)
    provider_extensions: dict[str, Any] = field(default_factory=dict)

    def normalized_response_format(self) -> dict[str, Any]:
        if self.response_format:
            return dict(self.response_format)
        if self.structured_output in {"json", "json_object"}:
            return {"type": "json_object"}
        return {}


@dataclass(frozen=True, slots=True)
class ProviderAdapterResult:
    provider: str
    effective_base_url: str
    model_kwargs: dict[str, Any] = field(default_factory=dict)
    request_params_for_accounting: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "runtime.model_gateway.providers.adapter_result"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def pool_key_hash(self) -> str:
        payload = {
            "provider": self.provider,
            "effective_base_url": self.effective_base_url,
            "model_kwargs": self.model_kwargs,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
