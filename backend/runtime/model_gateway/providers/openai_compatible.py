from __future__ import annotations

from typing import Any

from .models import ProviderAdapterResult, ProviderRequestProfile


class OpenAICompatibleProviderAdapter:
    provider_family = "openai_compatible"

    def build(self, profile: ProviderRequestProfile) -> ProviderAdapterResult:
        response_format = profile.normalized_response_format()
        model_kwargs: dict[str, Any] = {}
        request_params: dict[str, Any] = {
            "stream_policy": dict(profile.stream_policy or {}),
            "structured_output": str(profile.structured_output or ""),
        }
        if response_format:
            model_kwargs["model_kwargs"] = {"response_format": response_format}
            request_params["response_format"] = response_format
        return ProviderAdapterResult(
            provider=str(profile.provider or ""),
            effective_base_url=str(profile.base_url or ""),
            model_kwargs=model_kwargs,
            request_params_for_accounting={key: value for key, value in request_params.items() if value not in ({}, [], "", None)},
            diagnostics={
                "adapter": self.provider_family,
                "response_format_enabled": bool(response_format),
            },
        )
