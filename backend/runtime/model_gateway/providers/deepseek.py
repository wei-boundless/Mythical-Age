from __future__ import annotations

import hashlib
import string
from typing import Any

from .models import ProviderAdapterResult, ProviderRequestProfile


class DeepSeekProviderAdapter:
    provider_family = "deepseek"

    def build(self, profile: ProviderRequestProfile) -> ProviderAdapterResult:
        thinking_enabled = str(profile.thinking_mode or "disabled").strip().lower() == "enabled"
        response_format = profile.normalized_response_format()
        strict_tool_schema = bool(dict(profile.provider_extensions or {}).get("strict_tool_schema") is True)
        effective_base_url = _deepseek_effective_base_url(profile, strict_tool_schema=strict_tool_schema)
        extra_body: dict[str, Any] = {
            "thinking": {
                "type": "enabled" if thinking_enabled else "disabled",
            }
        }
        user_id, user_id_source = _deepseek_user_id_from_extensions(profile.provider_extensions)
        if user_id:
            extra_body["user_id"] = user_id
        model_kwargs: dict[str, Any] = {"extra_body": extra_body}
        request_params: dict[str, Any] = {
            "thinking_mode": "enabled" if thinking_enabled else "disabled",
            "stream_policy": dict(profile.stream_policy or {}),
            "completion_profile": dict(profile.completion_profile or {}),
            "structured_output": str(profile.structured_output or ""),
        }
        if user_id:
            request_params["user_id"] = {
                "present": True,
                "source": user_id_source,
                "fingerprint": hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16],
            }
        reasoning_effort = _normalize_deepseek_reasoning_effort(profile.reasoning_effort)
        if reasoning_effort:
            request_params["reasoning_effort"] = reasoning_effort
        if strict_tool_schema:
            request_params["strict_tool_schema"] = True
        if response_format:
            model_kwargs["model_kwargs"] = {"response_format": response_format}
            request_params["response_format"] = response_format
        return ProviderAdapterResult(
            provider="deepseek",
            effective_base_url=effective_base_url,
            model_kwargs=model_kwargs,
            request_params_for_accounting={key: value for key, value in request_params.items() if value not in ({}, [], "", None)},
            diagnostics={
                "adapter": self.provider_family,
                "thinking_enabled": thinking_enabled,
                "response_format_enabled": bool(response_format),
                "chat_prefix_endpoint": effective_base_url.rstrip("/").endswith("/beta"),
                "strict_tool_schema": strict_tool_schema,
                "user_id_present": bool(user_id),
                "user_id_source": user_id_source if user_id else "",
            },
        )


def _deepseek_effective_base_url(profile: ProviderRequestProfile, *, strict_tool_schema: bool = False) -> str:
    base_url = str(profile.base_url or "").rstrip("/")
    completion = dict(profile.completion_profile or {})
    needs_beta = strict_tool_schema or (
        str(completion.get("mode") or "").strip() == "chat_prefix"
        and str(completion.get("provider_mode") or "").strip() == "deepseek_chat_prefix"
    )
    if needs_beta and base_url and not base_url.endswith("/beta"):
        return f"{base_url}/beta"
    return base_url


def _normalize_deepseek_reasoning_effort(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "auto", "default", "adaptive"}:
        return ""
    if normalized in {"max", "xhigh"}:
        return "max"
    return "high"


def _deepseek_user_id_from_extensions(extensions: dict[str, Any] | None) -> tuple[str, str]:
    payload = dict(extensions or {})
    nested = dict(payload.get("deepseek") or {}) if isinstance(payload.get("deepseek"), dict) else {}
    candidates = (
        (nested.get("user_id"), str(nested.get("user_id_source") or "provider_extensions.deepseek.user_id")),
        (payload.get("deepseek_user_id"), "provider_extensions.deepseek_user_id"),
        (payload.get("user_id"), "provider_extensions.user_id"),
    )
    for raw_value, source in candidates:
        user_id = _normalize_deepseek_user_id(raw_value)
        if user_id:
            return user_id, source
    return "", ""


def _normalize_deepseek_user_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    allowed = set(string.ascii_letters + string.digits + "-_")
    sanitized = "".join(char if char in allowed else "_" for char in text)
    return sanitized[:512]
