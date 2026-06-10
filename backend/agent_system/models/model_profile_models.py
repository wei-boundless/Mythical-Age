from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SENSITIVE_MODEL_PROFILE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "token",
    "provider_secret",
    "credential",
    "credentials",
}


@dataclass(frozen=True, slots=True)
class AgentModelProfile:
    profile_id: str = ""
    display_name: str = ""
    provider: str = ""
    model: str = ""
    credential_ref: str = ""
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    long_output_timeout_seconds: float | None = None
    max_retries: int | None = None
    temperature: float | None = None
    thinking_mode: str = ""
    reasoning_effort: str = ""
    stream_policy: dict[str, Any] = field(default_factory=dict)
    response_format: dict[str, Any] = field(default_factory=dict)
    fallback_profile_ref: str = ""
    capability_tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["capability_tags"] = list(self.capability_tags)
        return sanitize_model_profile_payload(payload)


@dataclass(frozen=True, slots=True)
class ModelRequirement:
    profile_ref: str = ""
    provider_family: str = ""
    model_family: str = ""
    credential_ref: str = ""
    capability_tags: tuple[str, ...] = ()
    min_context_tokens: int | None = None
    min_output_tokens: int | None = None
    preferred_output_tokens: int | None = None
    thinking_mode: str = ""
    reasoning_required: bool | None = None
    streaming_required: bool | None = None
    response_format: dict[str, Any] = field(default_factory=dict)
    structured_output: str = ""
    temperature_profile: str = ""
    fallback_allowed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["capability_tags"] = list(self.capability_tags)
        return payload


@dataclass(frozen=True, slots=True)
class ResolvedModelSpec:
    provider: str
    model: str
    api_key: str | None
    base_url: str
    max_output_tokens: int
    timeout_seconds: float
    long_output_timeout_seconds: float
    max_retries: int
    temperature: float
    thinking_mode: str
    reasoning_effort: str
    stream_policy: dict[str, Any] = field(default_factory=dict)
    response_format: dict[str, Any] = field(default_factory=dict)
    structured_output: str = ""
    source_chain: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "authority": "orchestration.model_profile_resolver",
            "provider": self.provider,
            "model": self.model,
            "base_url_configured": bool(self.base_url),
            "credential_configured": bool(self.api_key) or self.provider == "ollama",
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "long_output_timeout_seconds": self.long_output_timeout_seconds,
            "max_retries": self.max_retries,
            "temperature": self.temperature,
            "thinking_mode": self.thinking_mode,
            "reasoning_effort": self.reasoning_effort,
            "stream_policy": dict(self.stream_policy or {}),
            "response_format": dict(self.response_format or {}),
            "structured_output": self.structured_output,
            "source_chain": list(self.source_chain),
            "diagnostics": dict(self.diagnostics or {}),
        }


def parse_agent_model_profile(value: Any) -> AgentModelProfile:
    payload = sanitize_model_profile_payload(value)
    return AgentModelProfile(
        profile_id=str(payload.get("profile_id") or "").strip(),
        display_name=str(payload.get("display_name") or "").strip(),
        provider=str(payload.get("provider") or "").strip().lower(),
        model=str(payload.get("model") or "").strip(),
        credential_ref=str(payload.get("credential_ref") or "").strip(),
        max_output_tokens=_optional_int(payload.get("max_output_tokens")),
        timeout_seconds=_optional_float(payload.get("timeout_seconds")),
        long_output_timeout_seconds=_optional_float(payload.get("long_output_timeout_seconds")),
        max_retries=_optional_int(payload.get("max_retries")),
        temperature=_optional_float(payload.get("temperature")),
        thinking_mode=str(payload.get("thinking_mode") or "").strip().lower(),
        reasoning_effort=str(payload.get("reasoning_effort") or "").strip().lower(),
        stream_policy=dict(payload.get("stream_policy") or {}),
        response_format=_dict_or_empty(payload.get("response_format")),
        fallback_profile_ref=str(payload.get("fallback_profile_ref") or "").strip(),
        capability_tags=tuple(_unique_texts(payload.get("capability_tags"))),
        metadata=dict(payload.get("metadata") or {}),
    )


def parse_model_requirement(value: Any) -> ModelRequirement:
    payload = sanitize_model_profile_payload(value)
    return ModelRequirement(
        profile_ref=str(payload.get("profile_ref") or "").strip(),
        provider_family=str(payload.get("provider_family") or "").strip().lower(),
        model_family=str(payload.get("model_family") or "").strip(),
        credential_ref=str(payload.get("credential_ref") or "").strip(),
        capability_tags=tuple(_unique_texts(payload.get("capability_tags"))),
        min_context_tokens=_optional_int(payload.get("min_context_tokens")),
        min_output_tokens=_optional_int(payload.get("min_output_tokens")),
        preferred_output_tokens=_optional_int(payload.get("preferred_output_tokens")),
        thinking_mode=str(payload.get("thinking_mode") or "").strip().lower(),
        reasoning_required=_optional_bool(payload.get("reasoning_required")),
        streaming_required=_optional_bool(payload.get("streaming_required")),
        response_format=_dict_or_empty(payload.get("response_format")),
        structured_output=str(payload.get("structured_output") or "").strip().lower(),
        temperature_profile=str(payload.get("temperature_profile") or "").strip(),
        fallback_allowed=bool(payload.get("fallback_allowed", True)),
        metadata=dict(payload.get("metadata") or {}),
    )


def sanitize_model_profile_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if _is_sensitive_key(normalized_key):
            continue
        if isinstance(item, dict):
            sanitized[normalized_key] = sanitize_model_profile_payload(item)
        elif isinstance(item, list):
            sanitized[normalized_key] = [
                sanitize_model_profile_payload(child) if isinstance(child, dict) else child
                for child in item
            ]
        else:
            sanitized[normalized_key] = item
    return sanitized


def contains_raw_secret(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_sensitive_key(str(key or "")):
                return True
            if contains_raw_secret(item):
                return True
    elif isinstance(value, list):
        return any(contains_raw_secret(item) for item in value)
    return False


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    return lowered in SENSITIVE_MODEL_PROFILE_KEYS or lowered.endswith("_api_key") or lowered.endswith("_secret")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "on", "enabled"}:
        return True
    if lowered in {"false", "0", "no", "off", "disabled"}:
        return False
    return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _unique_texts(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in list(value or []):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


