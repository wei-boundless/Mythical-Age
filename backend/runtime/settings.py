from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import Settings, get_settings, runtime_config


@dataclass(frozen=True, slots=True)
class RuntimeSettingsSnapshot:
    rag_mode: bool


@dataclass(frozen=True, slots=True)
class PolicySettingsSnapshot:
    permission_mode: str


@dataclass(frozen=True, slots=True)
class StaticSettingsSnapshot:
    llm_provider: str
    llm_model: str
    llm_timeout_seconds: float
    llm_max_retries: int
    embedding_provider: str
    embedding_model: str
    vector_store_backend: str
    component_char_limit: int
    terminal_timeout_seconds: int


class AppSettingsService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._static_settings = get_settings()

    @property
    def static(self) -> Settings:
        return self._static_settings

    def static_snapshot(self) -> StaticSettingsSnapshot:
        settings = self._static_settings
        return StaticSettingsSnapshot(
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
            llm_timeout_seconds=settings.llm_timeout_seconds,
            llm_max_retries=settings.llm_max_retries,
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            vector_store_backend=settings.vector_store_backend,
            component_char_limit=settings.component_char_limit,
            terminal_timeout_seconds=settings.terminal_timeout_seconds,
        )

    def runtime_snapshot(self) -> RuntimeSettingsSnapshot:
        payload = runtime_config.load()
        return RuntimeSettingsSnapshot(rag_mode=bool(payload.get("rag_mode", False)))

    def policy_snapshot(self) -> PolicySettingsSnapshot:
        payload = runtime_config.load()
        return PolicySettingsSnapshot(
            permission_mode=str(payload.get("permission_mode", "default") or "default"),
        )

    def get_rag_mode(self) -> bool:
        return bool(runtime_config.get_rag_mode())

    def set_rag_mode(self, enabled: bool) -> dict[str, Any]:
        return runtime_config.set_rag_mode(enabled)

    def get_permission_mode(self) -> str:
        getter = getattr(runtime_config, "get_permission_mode", None)
        if callable(getter):
            return str(getter() or "default")
        return str(self.policy_snapshot().permission_mode or "default")

    def set_permission_mode(self, mode: str) -> dict[str, Any]:
        setter = getattr(runtime_config, "set_permission_mode", None)
        if callable(setter):
            return setter(mode)
        current = runtime_config.load()
        current["permission_mode"] = mode
        return runtime_config.save(current)
