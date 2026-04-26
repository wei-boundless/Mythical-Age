from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import Settings, get_settings, runtime_config


@dataclass(frozen=True, slots=True)
class RuntimeSettingsSnapshot:
    rag_mode: bool
    retrieval_shadow_compare: bool
    retrieval_cutover_mode: str
    orchestration_plan_mode: str


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
    document_conversion_backend: str
    retrieval_core_backend: str
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
            document_conversion_backend=settings.document_conversion_backend,
            retrieval_core_backend=settings.retrieval_core_backend,
            component_char_limit=settings.component_char_limit,
            terminal_timeout_seconds=settings.terminal_timeout_seconds,
        )

    def runtime_snapshot(self) -> RuntimeSettingsSnapshot:
        payload = runtime_config.load()
        return RuntimeSettingsSnapshot(
            rag_mode=bool(payload.get("rag_mode", False)),
            retrieval_shadow_compare=bool(payload.get("retrieval_shadow_compare", False)),
            retrieval_cutover_mode=str(payload.get("retrieval_cutover_mode", "v2_primary") or "v2_primary"),
            orchestration_plan_mode=str(payload.get("orchestration_plan_mode", "shadow") or "shadow"),
        )

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

    def get_retrieval_shadow_compare(self) -> bool:
        getter = getattr(runtime_config, "get_retrieval_shadow_compare", None)
        if callable(getter):
            return bool(getter())
        return bool(self.runtime_snapshot().retrieval_shadow_compare)

    def set_retrieval_shadow_compare(self, enabled: bool) -> dict[str, Any]:
        setter = getattr(runtime_config, "set_retrieval_shadow_compare", None)
        if callable(setter):
            return setter(enabled)
        current = runtime_config.load()
        current["retrieval_shadow_compare"] = bool(enabled)
        return runtime_config.save(current)

    def get_retrieval_cutover_mode(self) -> str:
        getter = getattr(runtime_config, "get_retrieval_cutover_mode", None)
        if callable(getter):
            return str(getter() or "v2_primary")
        return str(self.runtime_snapshot().retrieval_cutover_mode or "v2_primary")

    def set_retrieval_cutover_mode(self, mode: str) -> dict[str, Any]:
        setter = getattr(runtime_config, "set_retrieval_cutover_mode", None)
        if callable(setter):
            return setter(mode)
        current = runtime_config.load()
        current["retrieval_cutover_mode"] = str(mode or "v2_primary")
        return runtime_config.save(current)

    def get_orchestration_plan_mode(self) -> str:
        getter = getattr(runtime_config, "get_orchestration_plan_mode", None)
        if callable(getter):
            return str(getter() or "shadow")
        return str(self.runtime_snapshot().orchestration_plan_mode or "shadow")

    def set_orchestration_plan_mode(self, mode: str) -> dict[str, Any]:
        setter = getattr(runtime_config, "set_orchestration_plan_mode", None)
        if callable(setter):
            return setter(mode)
        current = runtime_config.load()
        current["orchestration_plan_mode"] = str(mode or "shadow")
        return runtime_config.save(current)
