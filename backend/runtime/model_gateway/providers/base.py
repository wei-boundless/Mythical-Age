from __future__ import annotations

from typing import Protocol

from .models import ProviderAdapterResult, ProviderRequestProfile


class ProviderAdapter(Protocol):
    provider_family: str

    def build(self, profile: ProviderRequestProfile) -> ProviderAdapterResult:
        ...
