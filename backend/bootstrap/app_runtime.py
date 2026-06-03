from __future__ import annotations

from pathlib import Path

from capability_system.skills.paths import CapabilitySkillPaths
from capability_system.skills.registry import SkillRegistry
from capability_system.skills.scanner import refresh_snapshot
from capability_system.tools.registry import refresh_tool_registry
from capability_system.tools.native_tool_runtime import ToolRuntime
from capability_system.mcp.paths import CapabilityMCPPaths
from capability_system.tools.paths import CapabilityToolPaths
from memory_system import MemoryFacade
from memory_system.governance_service import DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS
from memory_system.layout import durable_memory_namespace_id_for_task_environment
from permissions import PermissionService
from harness.entrypoint import HarnessRuntimeFacade
from bootstrap.settings import AppSettingsService
from capability_system.capabilities.retrieval import RetrievalService
from sessions import SessionManager
from runtime import ModelRuntime
from runtime.prompt_accounting import PromptAccountingLedger
from project_layout import ProjectLayout


class AppRuntime:
    def __init__(self) -> None:
        self.base_dir: Path | None = None
        self.settings: AppSettingsService | None = None
        self.session_manager: SessionManager | None = None
        self.skill_registry: SkillRegistry | None = None
        self.tool_runtime: ToolRuntime | None = None
        self.memory_facade: MemoryFacade | None = None
        self.retrieval_service: RetrievalService | None = None
        self.permission_service: PermissionService | None = None
        self.model_runtime: ModelRuntime | None = None
        self.harness_runtime: HarnessRuntimeFacade | None = None

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        CapabilitySkillPaths.from_base_dir(base_dir).ensure()
        CapabilityToolPaths.from_base_dir(base_dir).ensure()
        CapabilityMCPPaths.from_base_dir(base_dir).ensure()
        self.settings = AppSettingsService(base_dir)
        refresh_snapshot(base_dir)
        refresh_tool_registry(base_dir)
        self.session_manager = SessionManager(base_dir)
        self.skill_registry = SkillRegistry(base_dir)
        self.tool_runtime = ToolRuntime(base_dir)
        self.memory_facade = MemoryFacade(base_dir, context_budget_provider=self.settings.context_budget_settings)
        self.retrieval_service = RetrievalService(base_dir)
        self.permission_service = PermissionService(self.settings, self.tool_runtime)
        self.model_runtime = ModelRuntime(
            self.settings,
            prompt_accounting_ledger=PromptAccountingLedger(ProjectLayout.from_backend_dir(base_dir).runtime_state_dir),
        )
        self.memory_facade.set_model_invoker(self.model_runtime.invoke_messages)
        self.memory_facade.set_session_compactor_kwargs_provider(self._session_compactor_kwargs)
        self.memory_facade.set_durable_memory_saved_callback(self._on_durable_memory_saved)
        self.memory_facade.background_task_manager.register_handler(
            "durable_memory_index_rebuild",
            self._run_durable_memory_index_rebuild,
        )
        self.memory_facade.background_task_manager.register_handler(
            "durable_memory_governance_tick",
            self._run_durable_memory_governance_tick,
        )
        self.harness_runtime = HarnessRuntimeFacade(
            base_dir=base_dir,
            settings_service=self.settings,
            session_manager=self.session_manager,
            memory_facade=self.memory_facade,
            retrieval_service=self.retrieval_service,
            tool_runtime=self.tool_runtime,
            skill_registry=self.skill_registry,
            permission_service=self.permission_service,
            model_runtime=self.model_runtime,
        )

    def _session_compactor_kwargs(self, session_id: str) -> dict[str, object]:
        if self.base_dir is None or self.model_runtime is None:
            return {}
        from harness.runtime import build_registered_semantic_compaction_worker

        resolver = (
            self.harness_runtime.agent_runtime_registry.get_profile
            if self.harness_runtime is not None
            else None
        )
        worker = build_registered_semantic_compaction_worker(
            base_dir=self.base_dir,
            model_runtime=self.model_runtime,
            agent_runtime_profile_resolver=resolver,
        )
        if worker is None:
            return {}
        return {"semantic_compactor": worker}

    def require_ready(self) -> "AppRuntime":
        if (
            self.base_dir is None
            or self.settings is None
            or self.session_manager is None
            or self.skill_registry is None
            or self.tool_runtime is None
            or self.memory_facade is None
            or self.retrieval_service is None
            or self.permission_service is None
            or self.model_runtime is None
            or self.harness_runtime is None
        ):
            raise RuntimeError("App runtime is not initialized")
        return self

    def refresh_catalogs(self) -> None:
        runtime = self.require_ready()
        refresh_snapshot(runtime.base_dir)
        refresh_tool_registry(runtime.base_dir)
        runtime.skill_registry.reload()
        runtime.tool_runtime.reload()

    async def shutdown(self) -> None:
        model_runtime = self.model_runtime
        if model_runtime is not None:
            close = getattr(model_runtime, "close", None)
            if callable(close):
                await close()

    def refresh_indexes_for_path(self, relative_path: str) -> None:
        runtime = self.require_ready()
        normalized = relative_path.replace("\\", "/")
        if normalized.startswith("capability_system/skills/") or normalized.startswith("capability_system/tools/registries/"):
            self.refresh_catalogs()
            return
        if normalized.startswith("durable_memory/"):
            namespace_id = self._namespace_from_durable_relative_path(normalized)
            runtime.memory_facade.mark_durable_memory_namespaces_dirty(
                {namespace_id: 1},
                reason="durable_memory_path_refresh",
            )
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_index_rebuild",
                payload={"collection": "durable_memory", "source_path": normalized},
                source="bootstrap.app_runtime",
                coalesce_key="durable_memory",
            )
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_governance_tick",
                payload={
                    "reason": "durable_memory_path_refresh",
                    "source_path": normalized,
                },
                source="bootstrap.app_runtime",
                coalesce_key="durable_memory_governance",
            )
            return
        if normalized.startswith("session-memory/"):
            runtime.retrieval_service.rebuild_session_memory()
            return
        if normalized.startswith("knowledge/"):
            runtime.retrieval_service.rebuild_knowledge()

    def _on_durable_memory_saved(self, saved_namespaces: dict[str, int]) -> None:
        runtime = self.require_ready()
        normalized = {
            str(namespace_id or "").strip() or "global_common": max(0, int(count or 0))
            for namespace_id, count in dict(saved_namespaces or {}).items()
        }
        normalized = {namespace_id: count for namespace_id, count in normalized.items() if count > 0}
        saved_count = sum(normalized.values())
        if saved_count <= 0:
            return
        if runtime.memory_facade is not None:
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_index_rebuild",
                payload={
                    "collection": "durable_memory",
                    "saved_count": saved_count,
                    "saved_namespaces": normalized,
                },
                source="bootstrap.app_runtime",
                coalesce_key="durable_memory",
            )
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_governance_tick",
                payload={
                    "reason": "durable_memory_saved",
                    "saved_namespaces": normalized,
                },
                source="bootstrap.app_runtime",
                coalesce_key="durable_memory_governance",
            )

    async def _run_durable_memory_index_rebuild(self, payload: dict[str, object]) -> dict[str, object]:
        runtime = self.require_ready()
        collection = str(payload.get("collection") or "durable_memory")
        if collection != "durable_memory":
            return {"collection": collection, "status": "skipped"}
        result = runtime.retrieval_service.rebuild_durable_memory()
        return {"collection": collection, "status": "queued_or_completed", "result": result}

    async def _run_durable_memory_governance_tick(self, payload: dict[str, object]) -> dict[str, object]:
        runtime = self.require_ready()
        namespace_ids = [
            str(item or "").strip()
            for item in list(payload.get("namespace_ids") or [])
            if str(item or "").strip()
        ] or None
        result = runtime.memory_facade.run_durable_memory_governance_tick(
            namespace_ids=namespace_ids,
            force=bool(payload.get("force", False)),
            min_interval_seconds=int(payload.get("min_interval_seconds") or DEFAULT_GOVERNANCE_MIN_INTERVAL_SECONDS),
            reason=str(payload.get("reason") or "background_tick"),
            source="bootstrap.app_runtime",
        )
        ran = [dict(item or {}) for item in list(result.get("ran") or [])]
        if any(str(item.get("namespace_id") or "") == "global_common" and int(item.get("updated") or 0) > 0 for item in ran):
            runtime.retrieval_service.rebuild_durable_memory()
        return dict(result)

    def _namespace_from_durable_relative_path(self, normalized_path: str) -> str:
        parts = str(normalized_path or "").replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[0] == "durable_memory" and parts[1] == "environments":
            return durable_memory_namespace_id_for_task_environment(parts[2])
        return "global_common"


app_runtime = AppRuntime()



