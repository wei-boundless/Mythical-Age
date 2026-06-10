from __future__ import annotations

from typing import Any

from .models import ProviderAdapterResult, ProviderRequestProfile


class DeepSeekProviderAdapter:
    provider_family = "deepseek"

    def build(self, profile: ProviderRequestProfile) -> ProviderAdapterResult:
        thinking_enabled = str(profile.thinking_mode or "disabled").strip().lower() == "enabled"
        response_format = profile.normalized_response_format()
        effective_base_url = _deepseek_effective_base_url(profile)
        extra_body: dict[str, Any] = {
            "thinking": {
                "type": "enabled" if thinking_enabled else "disabled",
            }
        }
        model_kwargs: dict[str, Any] = {"extra_body": extra_body}
        request_params: dict[str, Any] = {
            "thinking_mode": "enabled" if thinking_enabled else "disabled",
            "reasoning_effort": str(profile.reasoning_effort or "auto").strip().lower() or "auto",
            "stream_policy": dict(profile.stream_policy or {}),
            "completion_profile": dict(profile.completion_profile or {}),
            "structured_output": str(profile.structured_output or ""),
        }
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
            },
        )


def _deepseek_effective_base_url(profile: ProviderRequestProfile) -> str:
    base_url = str(profile.base_url or "").rstrip("/")
    completion = dict(profile.completion_profile or {})
    if (
        str(completion.get("mode") or "").strip() == "chat_prefix"
        and str(completion.get("provider_mode") or "").strip() == "deepseek_chat_prefix"
        and base_url
        and not base_url.endswith("/beta")
    ):
        return f"{base_url}/beta"
    return base_url
