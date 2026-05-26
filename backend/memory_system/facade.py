from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from project_layout import ProjectLayout
from orchestration import BackgroundTaskManager
from .bundle_service import MemoryBundleService
from .continuity import ForegroundContinuityStateStore, MemoryMessageAdapter, SessionMemoryLayer
from .conversation_memory import ConversationMemoryStoreAdapter
from .durable import DurableMemoryLayer
from .governance_service import DurableMemoryGovernanceService
from .maintenance import MemoryMaintenanceAgent, MemoryMaintenanceCoordinator
from .runtime_services import MemoryRuntimeServices
from .state_memory import StateMemoryStoreAdapter


class MemoryFacade:
    def __init__(self, base_dir: Path, context_budget_provider: Callable[[], dict[str, Any]] | None = None) -> None:
        self.base_dir = base_dir
        self._context_budget_provider = context_budget_provider
        self.adapter = MemoryMessageAdapter()
        self.session_memory = SessionMemoryLayer(base_dir, context_budget_provider=context_budget_provider)
        self.foreground_state = ForegroundContinuityStateStore(self.session_memory.session_root)
        self.durable_memory = DurableMemoryLayer(base_dir)
        self.memory_manager = self.durable_memory.memory_manager
        self.maintenance_agent = MemoryMaintenanceAgent()
        self.maintenance_coordinator = MemoryMaintenanceCoordinator(
            base_dir=base_dir,
            session_memory_layer=self.session_memory,
            memory_manager=self.memory_manager,
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
        layout = ProjectLayout.from_backend_dir(base_dir)
        self.runtime_services = MemoryRuntimeServices(layout.storage_root)
        self.working_memory = self.runtime_services.working_memory
        self.task_durable_memory = self.runtime_services.task_durable_memory
        self.formal_memory = self.runtime_services.formal_memory
        self.working_memory_finalizer = self.runtime_services.working_memory_finalizer
        self.bundle_service = MemoryBundleService(
            session_memory=self.session_memory,
            conversation_memory=self.conversation_memory,
            state_memory=self.state_memory,
            working_memory=self.working_memory,
            task_durable_memory=self.task_durable_memory,
            durable_memory=self.durable_memory,
            context_budget_provider=context_budget_provider,
        )
        self.governance_service = DurableMemoryGovernanceService(
            base_dir,
            memory_manager=self.memory_manager,
        )

    def set_durable_memory_saved_callback(self, callback: Callable[[int], None]) -> None:
        self.durable_memory.set_saved_callback(callback)
        self.maintenance_coordinator.set_durable_saved_callback(callback)

    def enqueue_memory_maintenance_after_commit(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        turn_id: str = "",
        main_context: dict[str, Any] | None = None,
        task_summary_refs: list[dict[str, Any]] | None = None,
        bundle_summary_refs: list[dict[str, Any]] | None = None,
        durable_lane_enabled: bool = True,
    ):
        payload = {
            "session_id": session_id,
            "messages": list(messages or []),
            "turn_id": turn_id,
            "main_context": dict(main_context or {}),
            "task_summary_refs": list(task_summary_refs or []),
            "bundle_summary_refs": list(bundle_summary_refs or []),
            "durable_lane_enabled": durable_lane_enabled,
        }
        record = self.background_task_manager.enqueue(
            "memory_maintenance_after_commit",
            payload=payload,
            source="memory_system.facade",
            session_id=session_id,
            lane_id="session_memory_maintenance",
        )
        from .maintenance import MemoryMaintenanceReceipt

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

    def set_model_invoker(self, callback: Callable[[list[dict[str, str]]], Any] | None) -> None:
        self.durable_memory.set_message_invoker(callback)
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
        durable_lane_enabled: bool = True,
    ):
        return self.maintenance_coordinator.run_after_commit_sync(
            session_id=session_id,
            messages=messages,
            turn_id=turn_id,
            main_context=main_context,
            task_summary_refs=task_summary_refs,
            bundle_summary_refs=bundle_summary_refs,
            durable_lane_enabled=durable_lane_enabled,
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
        durable_lane_enabled: bool = True,
    ):
        return self.enqueue_memory_maintenance_after_commit(
            session_id=session_id,
            messages=messages,
            turn_id=turn_id,
            main_context=main_context,
            task_summary_refs=task_summary_refs,
            bundle_summary_refs=bundle_summary_refs,
            durable_lane_enabled=durable_lane_enabled,
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
            durable_lane_enabled=bool(payload.get("durable_lane_enabled", True)),
        )

    def promote_working_memory_item_to_task_durable(self, work_memory_id: str, **payload: Any) -> dict[str, Any]:
        item = self.working_memory.get_item(work_memory_id)
        if item is None:
            raise KeyError(f"Unknown working memory item: {work_memory_id}")
        task_memory_item = self.task_durable_memory.promote_working_memory_item(item, **payload)
        updated = self.working_memory.store.update_item_lifecycle(
            item.work_memory_id,
            status="promoted",
            promotion_state="promoted_to_task_durable",
            authority="human_gate_adopted",
            actor_id=str(payload.get("actor_id") or "memory_governance_ui"),
            metadata={
                "promoted_task_memory_id": task_memory_item.task_memory_id,
                "promoted_task_memory_namespace_id": task_memory_item.namespace_id,
                "promoted_task_memory_title": task_memory_item.title,
                "promotion_reason": str(payload.get("reason") or "manual_working_memory_promotion"),
                "promotion_target": "task_durable_memory",
            },
            event_type="promoted_to_task_durable",
        )
        return {
            "task_memory": task_memory_item,
            "item": updated,
        }

    def mark_task_durable_item_global_candidate(self, task_memory_id: str, **payload: Any) -> dict[str, Any]:
        updated = self.task_durable_memory.store.update_lifecycle(
            task_memory_id,
            eligible_for_global_promotion=True,
            global_promotion_state="candidate",
            actor_id=str(payload.get("actor_id") or "memory_governance_ui"),
            metadata={
                "global_candidate_reason": str(payload.get("reason") or "manual_global_candidate"),
                "global_candidate_actor_id": str(payload.get("actor_id") or "memory_governance_ui"),
            },
            event_type="global_candidate_marked",
        )
        return {"task_memory": updated}

    def promote_task_durable_item_to_global_durable(self, task_memory_id: str, **payload: Any) -> dict[str, Any]:
        item = self.task_durable_memory.get_item(task_memory_id)
        if item is None:
            raise KeyError(f"Unknown task durable memory item: {task_memory_id}")
        if not item.eligible_for_global_promotion and item.global_promotion_state not in {"candidate", "approved"}:
            raise ValueError("Task durable memory item must be marked as global promotion candidate first")
        allowed_kinds = {"user_preference", "system_rule", "cross_task_policy", "global_working_convention"}
        promotion_kind = str(payload.get("global_kind") or item.metadata.get("global_kind") or item.kind or "").strip()
        if promotion_kind not in allowed_kinds:
            raise ValueError("Task durable memory item is not an allowed global promotion kind")
        result = self.governance_service.create_durable_memory_note(
            title=str(payload.get("title") or item.title or item.task_memory_id),
            canonical_statement=str(payload.get("canonical_statement") or item.canonical_statement or item.summary),
            summary=str(payload.get("summary") or item.summary or item.canonical_statement),
            memory_type=str(payload.get("memory_type") or "project"),
            memory_class=str(payload.get("memory_class") or "work"),
            retrieval_hints=list(item.retrieval_hints)[:8],
            confidence=str(payload.get("confidence") or item.confidence or "medium"),
            source_kind="task_durable_global_promotion",
            source_message_excerpt=(
                f"task_memory_id: {item.task_memory_id}\n"
                f"namespace_id: {item.namespace_id}\n"
                f"task_id: {item.task_id}\n"
                f"graph_id: {item.graph_id}\n"
                f"canonical_statement: {item.canonical_statement}\n"
            )[:1600],
        )
        updated = self.task_durable_memory.store.update_lifecycle(
            task_memory_id,
            eligible_for_global_promotion=True,
            global_promotion_state="promoted_to_global",
            actor_id=str(payload.get("actor_id") or "memory_governance_ui"),
            metadata={
                "promoted_global_durable_filename": result.get("filename", ""),
                "promoted_global_durable_title": str(payload.get("title") or item.title or item.task_memory_id),
                "global_promotion_reason": str(payload.get("reason") or "manual_task_durable_global_promotion"),
                "global_kind": promotion_kind,
            },
            event_type="promoted_to_global_durable",
        )
        return {
            "filename": result["filename"],
            "header": result.get("header"),
            "task_memory": updated,
        }

    def build_memory_context_package(
        self,
        *,
        session_id: str,
        pending_user_message: str | None = None,
        memory_intent: Any | None = None,
        memory_request_profile: dict[str, Any] | None = None,
        memory_view: Any | None = None,
        relevant_notes: list[Any] | None = None,
        retrieval_results: list[dict[str, Any]] | None = None,
        note_limit: int = 5,
    ):
        return self.bundle_service.build_memory_context_package(
            session_id=session_id,
            pending_user_message=pending_user_message,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            memory_view=memory_view,
            relevant_notes=relevant_notes,
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
        relevant_notes: list[Any] | None = None,
        note_limit: int = 5,
    ):
        return self.bundle_service.build_memory_bundle(
            task_id=task_id,
            session_id=session_id,
            agent_id=agent_id,
            query=query,
            memory_intent=memory_intent,
            memory_request_profile=memory_request_profile,
            relevant_notes=relevant_notes,
            note_limit=note_limit,
        )
