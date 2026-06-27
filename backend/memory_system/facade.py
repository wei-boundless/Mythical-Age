from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from core.project_layout import ProjectLayout
from runtime.shared.background_tasks import BackgroundTaskManager
from .bundle_service import MemoryBundleService
from .continuity import ForegroundContinuityStateStore, MemoryMessageAdapter, SessionMemoryLayer
from .conversation_memory import ConversationMemoryStoreAdapter
from .durable import DurableMemoryLayer
from .environment_context import resolve_memory_environment_context
from .governance_service import DurableMemoryGovernanceService
from .layout import environment_durable_memory_scope_from_backend_dir
from .maintenance import (
    MEMORY_MANAGER_AGENT_ID,
    MemoryMaintenanceAgent,
    MemoryMaintenanceCoordinator,
    memory_maintenance_registration_from_profile,
)
from .runtime_services import MemoryRuntimeServices
from .session_emphasis import SessionEmphasisStore
from .storage_layout import MemoryStorageLayout
from .state_memory import StateMemoryStoreAdapter


class MemoryFacade:
    def __init__(self, base_dir: Path, context_budget_provider: Callable[[], dict[str, Any]] | None = None) -> None:
        self.base_dir = base_dir
        self._context_budget_provider = context_budget_provider
        self._model_invoker: Callable[[list[dict[str, str]]], Any] | None = None
        self._external_durable_memory_saved_callback: Callable[[dict[str, int]], None] | None = None
        project_layout = ProjectLayout.from_backend_dir(base_dir)
        self.storage_layout = MemoryStorageLayout.from_project_layout(project_layout)
        self.storage_layout.ensure_dirs()
        self.adapter = MemoryMessageAdapter()
        self.session_memory = SessionMemoryLayer(
            base_dir,
            session_root=self.storage_layout.session_root,
            context_budget_provider=context_budget_provider,
        )
        self.foreground_state = ForegroundContinuityStateStore(self.session_memory.session_root)
        self.session_emphasis = SessionEmphasisStore(self.session_memory.session_root)
        self.durable_memory = DurableMemoryLayer(base_dir)
        self._environment_durable_layers: dict[str, DurableMemoryLayer] = {}
        self.memory_manager = self.durable_memory.memory_manager
        runtime_profile = AgentRuntimeRegistry(base_dir).get_profile(MEMORY_MANAGER_AGENT_ID)
        if runtime_profile is None:
            raise RuntimeError("memory maintenance agent runtime profile is not registered")
        self.maintenance_agent = MemoryMaintenanceAgent(
            registration=memory_maintenance_registration_from_profile(runtime_profile),
        )
        self.maintenance_coordinator = MemoryMaintenanceCoordinator(
            base_dir=base_dir,
            runtime_dir=self.storage_layout.maintenance_root,
            session_memory_layer=self.session_memory,
            session_emphasis_store=self.session_emphasis,
            memory_manager=self.memory_manager,
            memory_manager_resolver=self.resolve_durable_memory_manager,
            maintenance_agent=self.maintenance_agent,
        )
        self.background_task_manager = BackgroundTaskManager(base_dir)
        self.background_task_manager.register_handler(
            "memory_maintenance_after_commit",
            self._run_background_memory_maintenance,
        )
        self.session_root = self.session_memory.session_root
        self.conversation_memory = ConversationMemoryStoreAdapter(self.session_root)
        self.state_memory = StateMemoryStoreAdapter(self.session_root)
        self.runtime_services = MemoryRuntimeServices(self.storage_layout)
        self.working_memory = self.runtime_services.working_memory
        self.formal_memory = self.runtime_services.formal_memory
        self.working_memory_finalizer = self.runtime_services.working_memory_finalizer
        self.bundle_service = MemoryBundleService(
            session_memory=self.session_memory,
            conversation_memory=self.conversation_memory,
            state_memory=self.state_memory,
            working_memory=self.working_memory,
            durable_memory=self.durable_memory,
            durable_memory_resolver=self.resolve_durable_memory_layer,
            context_budget_provider=context_budget_provider,
        )
        self.governance_service = DurableMemoryGovernanceService(
            base_dir,
            memory_manager=self.memory_manager,
            runtime_dir=self.storage_layout.durable_governance_root,
        )
        self.maintenance_coordinator.set_durable_saved_callback(self._on_durable_memory_saved)

    def set_durable_memory_saved_callback(self, callback: Callable[[dict[str, int]], None] | None) -> None:
        self._external_durable_memory_saved_callback = callback

    def set_session_compactor_kwargs_provider(self, provider: Callable[[str], dict[str, Any]] | None) -> None:
        self.session_memory.set_compactor_kwargs_provider(provider)

    def mark_durable_memory_namespaces_dirty(
        self,
        saved_namespaces: dict[str, int] | None = None,
        *,
        reason: str = "durable_memory_saved",
    ) -> dict[str, Any]:
        return self.governance_service.mark_namespaces_dirty(saved_namespaces, reason=reason)

    def run_durable_memory_governance_tick(
        self,
        *,
        namespace_ids: list[str] | tuple[str, ...] | None = None,
        force: bool = False,
        min_interval_seconds: int | None = None,
        reason: str = "runtime_tick",
        source: str = "memory_system.facade",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "namespace_ids": namespace_ids,
            "force": force,
            "reason": reason,
            "source": source,
        }
        if min_interval_seconds is not None:
            payload["min_interval_seconds"] = min_interval_seconds
        return self.governance_service.run_governance_tick(**payload)

    def _on_durable_memory_saved(self, saved_namespaces: dict[str, int]) -> None:
        normalized = {
            str(namespace_id or "").strip() or "global_common": max(0, int(count or 0))
            for namespace_id, count in dict(saved_namespaces or {}).items()
        }
        normalized = {namespace_id: count for namespace_id, count in normalized.items() if count > 0}
        if not normalized:
            return
        self.mark_durable_memory_namespaces_dirty(normalized, reason="durable_memory_saved")
        if self._external_durable_memory_saved_callback is not None:
            self._external_durable_memory_saved_callback(normalized)

    def enqueue_memory_maintenance_after_commit(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        turn_id: str = "",
        main_context: dict[str, Any] | None = None,
        task_summary_refs: list[dict[str, Any]] | None = None,
        bundle_summary_refs: list[dict[str, Any]] | None = None,
        memory_environment_context: dict[str, Any] | None = None,
        event_coverage: dict[str, Any] | None = None,
        durable_lane_enabled: bool = True,
        force: bool = False,
    ):
        from .maintenance import MemoryMaintenanceReceipt

        opportunity = self.maintenance_coordinator.evaluate_opportunity_for_session(
            session_id=session_id,
            messages=list(messages or []),
            main_context=dict(main_context or {}),
            task_summary_refs=list(task_summary_refs or []),
            bundle_summary_refs=list(bundle_summary_refs or []),
            force=force,
        )
        if not opportunity.should_run:
            return MemoryMaintenanceReceipt(
                run_id=f"memory-maintenance:{session_id}:skipped",
                session_id=session_id,
                turn_id=turn_id,
                status="skipped",
                attempted=False,
                durable_skipped=True,
                durable_skip_reason=opportunity.reason,
                processed_message_count=len(messages or []),
                diagnostics={"maintenance_opportunity": opportunity.model_dump()},
            )
        payload = {
            "session_id": session_id,
            "messages": list(messages or []),
            "turn_id": turn_id,
            "main_context": dict(main_context or {}),
            "task_summary_refs": list(task_summary_refs or []),
            "bundle_summary_refs": list(bundle_summary_refs or []),
            "memory_environment_context": resolve_memory_environment_context(
                explicit=memory_environment_context,
                main_context=main_context,
                turn_id=turn_id,
            ).to_dict(),
            "event_coverage": dict(event_coverage or {}),
            "durable_lane_enabled": durable_lane_enabled,
            "force": force,
        }
        record = self.background_task_manager.enqueue(
            "memory_maintenance_after_commit",
            payload=payload,
            source="memory_system.facade",
            session_id=session_id,
        )
        return MemoryMaintenanceReceipt(
            run_id=record.task_id,
            session_id=session_id,
            turn_id=turn_id,
            status="queued",
            queued=True,
            durable_skipped=True,
            durable_skip_reason="queued_for_background_execution",
            processed_message_count=len(messages or []),
            diagnostics={
                "background_task_id": record.task_id,
                "background_task_kind": record.task_kind,
                "background_task_path": record.receipt_path,
            },
        )

    def resolve_durable_memory_layer(self, environment_scope: dict[str, Any] | None = None) -> DurableMemoryLayer:
        task_environment_id = str(dict(environment_scope or {}).get("task_environment_id") or "").strip()
        if not task_environment_id:
            return self.durable_memory
        scope = environment_durable_memory_scope_from_backend_dir(self.base_dir, task_environment_id)
        layer = self._environment_durable_layers.get(scope.namespace_id)
        if layer is None:
            layer = DurableMemoryLayer(self.base_dir, root_dir=scope.storage_root, namespace_id=scope.namespace_id)
            layer.set_message_invoker(self._model_invoker)
            self._environment_durable_layers[scope.namespace_id] = layer
        return layer

    def resolve_durable_memory_manager(self, environment_scope: dict[str, Any] | None = None):
        return self.resolve_durable_memory_layer(environment_scope).memory_manager

    def set_model_invoker(self, callback: Callable[[list[dict[str, str]]], Any] | None) -> None:
        self._model_invoker = callback
        self.durable_memory.set_message_invoker(callback)
        for layer in self._environment_durable_layers.values():
            layer.set_message_invoker(callback)
        self.maintenance_agent.set_message_invoker(callback)

    def run_memory_maintenance_after_commit(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        turn_id: str = "",
        main_context: dict[str, Any] | None = None,
        task_summary_refs: list[dict[str, Any]] | None = None,
        bundle_summary_refs: list[dict[str, Any]] | None = None,
        memory_environment_context: dict[str, Any] | None = None,
        event_coverage: dict[str, Any] | None = None,
        durable_lane_enabled: bool = True,
        force: bool = False,
    ):
        return self.maintenance_coordinator.run_after_commit_sync(
            session_id=session_id,
            messages=messages,
            turn_id=turn_id,
            main_context=main_context,
            task_summary_refs=task_summary_refs,
            bundle_summary_refs=bundle_summary_refs,
            memory_environment_context=memory_environment_context,
            event_coverage=event_coverage,
            durable_lane_enabled=durable_lane_enabled,
            force=force,
        )

    async def arun_memory_maintenance_after_commit(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        turn_id: str = "",
        main_context: dict[str, Any] | None = None,
        task_summary_refs: list[dict[str, Any]] | None = None,
        bundle_summary_refs: list[dict[str, Any]] | None = None,
        memory_environment_context: dict[str, Any] | None = None,
        event_coverage: dict[str, Any] | None = None,
        durable_lane_enabled: bool = True,
        force: bool = False,
    ):
        return self.enqueue_memory_maintenance_after_commit(
            session_id=session_id,
            messages=messages,
            turn_id=turn_id,
            main_context=main_context,
            task_summary_refs=task_summary_refs,
            bundle_summary_refs=bundle_summary_refs,
            memory_environment_context=memory_environment_context,
            event_coverage=event_coverage,
            durable_lane_enabled=durable_lane_enabled,
            force=force,
        )

    def describe_memory_maintenance_runtime(self) -> dict[str, Any]:
        return self.maintenance_coordinator.describe_runtime_state()

    def delete_session_memory(self, session_id: str) -> bool:
        return self.session_memory.delete_session(session_id)

    def load_foreground_continuity_state(self, session_id: str):
        return self.foreground_state.load(session_id)

    def save_foreground_continuity_state(self, **payload: Any):
        return self.foreground_state.project_from_commit(**payload)

    async def _run_background_memory_maintenance(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.maintenance_coordinator.run_after_commit(
            session_id=str(payload.get("session_id") or ""),
            messages=list(payload.get("messages") or []),
            turn_id=str(payload.get("turn_id") or ""),
            main_context=dict(payload.get("main_context") or {}),
            task_summary_refs=list(payload.get("task_summary_refs") or []),
            bundle_summary_refs=list(payload.get("bundle_summary_refs") or []),
            memory_environment_context=dict(payload.get("memory_environment_context") or {}),
            event_coverage=dict(payload.get("event_coverage") or {}),
            durable_lane_enabled=bool(payload.get("durable_lane_enabled", True)),
            force=bool(payload.get("force", False)),
        )

    def build_memory_context_package(
        self,
        *,
        session_id: str,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        memory_view: Any | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
    ):
        return self.bundle_service.build_memory_context_package(
            session_id=session_id,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            memory_view=memory_view,
            retrieval_results=retrieval_results,
            note_limit=note_limit,
        )

    def build_memory_bundle(
        self,
        *,
        task_id: str,
        session_id: str,
        agent_id: str,
        query: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        note_limit: int = 5,
    ):
        return self.bundle_service.build_memory_bundle(
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            note_limit=note_limit,
        )



