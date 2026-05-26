from __future__ import annotations

from pathlib import Path

from capability_system.skill_registry import SkillRegistry
from capability_system.skill_scanner import refresh_snapshot
from capability_system.tool_registry import refresh_tool_registry
from capability_system.tool_runtime import ToolRuntime
from capability_system.paths import CapabilitySystemPaths
from memory_system import MemoryFacade
from permissions import PermissionService
from project_layout import ProjectLayout
from query import QueryRuntime
from bootstrap.settings import AppSettingsService
from knowledge_system import RetrievalService
from sessions import SessionManager
from runtime import ModelRuntime
from memory_system.storage.consolidation import ConsolidationConfig, ConsolidationReport, ConsolidationScheduler


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
        self.query_runtime: QueryRuntime | None = None
        self.consolidation_scheduler: ConsolidationScheduler | None = None

    def initialize(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        layout = ProjectLayout.from_backend_dir(base_dir)
        CapabilitySystemPaths.from_base_dir(base_dir).ensure()
        self.settings = AppSettingsService(base_dir)
        refresh_snapshot(base_dir)
        refresh_tool_registry(base_dir)
        self.session_manager = SessionManager(base_dir)
        self.skill_registry = SkillRegistry(base_dir)
        self.tool_runtime = ToolRuntime(base_dir)
        self.memory_facade = MemoryFacade(base_dir, context_budget_provider=self.settings.context_budget_settings)
        self.retrieval_service = RetrievalService(base_dir)
        self.permission_service = PermissionService(self.settings, self.tool_runtime)
        self.model_runtime = ModelRuntime(self.settings)
        self.memory_facade.set_model_invoker(self.model_runtime.invoke_messages)
        self.consolidation_scheduler = ConsolidationScheduler(
            layout.durable_memory_dir,
            config=ConsolidationConfig(
                min_saved_notes_between_runs=3,
                min_seconds_between_runs=1800,
            ),
            on_completed=self._on_durable_memory_consolidated,
        )
        self.memory_facade.set_durable_memory_saved_callback(self._on_durable_memory_saved)
        self.memory_facade.background_task_manager.register_handler(
            "durable_memory_index_rebuild",
            self._run_durable_memory_index_rebuild,
        )
        self.query_runtime = QueryRuntime(
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
            or self.query_runtime is None
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
        if normalized.startswith("capability_system/units/"):
            self.refresh_catalogs()
            return
        if normalized.startswith("durable_memory/"):
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_index_rebuild",
                payload={"collection": "durable_memory", "source_path": normalized},
                source="bootstrap.app_runtime",
                lane_id="durable_memory_extraction",
                coalesce_key="durable_memory",
            )
            return
        if normalized.startswith("session-memory/"):
            runtime.retrieval_service.rebuild_session_memory()
            return
        if normalized.startswith("knowledge/"):
            runtime.retrieval_service.rebuild_knowledge()

    def _on_durable_memory_saved(self, saved_count: int) -> None:
        runtime = self.require_ready()
        if saved_count <= 0:
            return
        if runtime.memory_facade is not None:
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_index_rebuild",
                payload={"collection": "durable_memory", "saved_count": saved_count},
                source="bootstrap.app_runtime",
                lane_id="durable_memory_extraction",
                coalesce_key="durable_memory",
            )
        if runtime.consolidation_scheduler is not None:
            runtime.consolidation_scheduler.notify_saved(saved_count)

    def _on_durable_memory_consolidated(self, report: ConsolidationReport) -> None:
        runtime = self.require_ready()
        if report.status != "ok":
            return
        if runtime.memory_facade is not None:
            runtime.memory_facade.background_task_manager.enqueue(
                "durable_memory_index_rebuild",
                payload={"collection": "durable_memory", "reason": "consolidation"},
                source="bootstrap.app_runtime",
                lane_id="durable_memory_extraction",
                coalesce_key="durable_memory",
            )

    async def _run_durable_memory_index_rebuild(self, payload: dict[str, object]) -> dict[str, object]:
        runtime = self.require_ready()
        collection = str(payload.get("collection") or "durable_memory")
        if collection != "durable_memory":
            return {"collection": collection, "status": "skipped"}
        result = runtime.retrieval_service.rebuild_durable_memory()
        return {"collection": collection, "status": "queued_or_completed", "result": result}


app_runtime = AppRuntime()

