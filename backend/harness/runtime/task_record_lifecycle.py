from __future__ import annotations

from typing import Any

from harness.graph.lifecycle_manager import GraphTaskLifecycleManager
from harness.loop.task_run_execution_control import request_executor_stop


class TaskRecordLifecycleNotFound(LookupError):
    pass


class TaskRecordLifecycleConflict(RuntimeError):
    def __init__(self, reason: str, *, task_run_id: str = "", graph_run_id: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.task_run_id = task_run_id
        self.graph_run_id = graph_run_id


class TaskRecordLifecycleManager:
    authority = "harness.runtime.task_record_lifecycle"

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.host = runtime.harness_runtime.single_agent_runtime_host
        self.graph_harness = getattr(runtime.harness_runtime, "graph_harness", None)

    async def delete_task_record(self, task_run_id: str) -> dict[str, Any]:
        task_run_id = str(task_run_id or "").strip()
        if not task_run_id:
            raise ValueError("task_run_id is required")
        task_run = self.host.state_index.get_task_run(task_run_id)
        if task_run is None:
            raise TaskRecordLifecycleNotFound(task_run_id)
        diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
        graph_run_id = _graph_run_id(diagnostics)
        if _origin_kind(diagnostics) == "graph_node_assigned":
            raise TaskRecordLifecycleConflict(
                "graph_node_task_run_controlled_by_graph_runtime",
                task_run_id=task_run_id,
                graph_run_id=graph_run_id,
            )
        if graph_run_id and self._is_graph_root(task_run_id=task_run_id, graph_run_id=graph_run_id):
            return await self._delete_graph_root(task_run_id=task_run_id, graph_run_id=graph_run_id)
        await self._delete_single(task_run)
        return {
            "authority": self.authority,
            "mode": "single_task_record",
            "task_run_id": task_run_id,
            "deleted": True,
        }

    async def _delete_single(self, task_run: Any) -> None:
        task_run_id = str(getattr(task_run, "task_run_id", "") or "")
        session_id = str(getattr(task_run, "session_id", "") or "")
        self._stop_executors({task_run_id})
        self.host.state_index.mark_task_run_deleted(task_run_id)
        await self.host.cancel_background_tasks(names=_executor_task_names({task_run_id}), reason="task_record_deleted")
        if session_id:
            self.host.active_turn_registry.complete_bound_task(
                session_id=session_id,
                task_run_id=task_run_id,
                terminal_reason="task_record_deleted",
            )
        contract_ref = str(getattr(task_run, "task_contract_ref", "") or "")
        if contract_ref.startswith("rtobj:"):
            try:
                self.host.runtime_objects.delete_ref(contract_ref)
            except Exception:
                pass
        self.host.event_log.delete_events(task_run_id)
        self.host.prompt_accounting_ledger.prune_task_runs({task_run_id})
        self.host.execution_store.prune_task_runs({task_run_id})
        self.host.runtime_objects.delete_graph_run_objects(graph_run_id="", task_run_ids={task_run_id})
        self.host.state_index.prune_task_runs({task_run_id})

    async def _delete_graph_root(self, *, task_run_id: str, graph_run_id: str) -> dict[str, Any]:
        if self.graph_harness is None:
            raise TaskRecordLifecycleConflict(
                "graph_harness_unavailable_for_graph_root_task_run",
                task_run_id=task_run_id,
                graph_run_id=graph_run_id,
            )
        manager = GraphTaskLifecycleManager(base_dir=self.runtime.base_dir, graph_harness=self.graph_harness)
        task_run_ids = {
            str(item).strip()
            for item in list(manager.preview_delete_graph_run(graph_run_id).get("task_run_ids") or [])
            if str(item).strip()
        } | {task_run_id}
        self._stop_executors(task_run_ids)
        await self.host.cancel_background_tasks(names=_executor_task_names(task_run_ids), reason="graph_root_task_record_deleted")
        manager.delete_graph_run(graph_run_id)
        return {
            "authority": self.authority,
            "mode": "graph_root_delegated",
            "task_run_id": task_run_id,
            "graph_run_id": graph_run_id,
            "task_run_ids": sorted(task_run_ids),
            "deleted": True,
        }

    def _is_graph_root(self, *, task_run_id: str, graph_run_id: str) -> bool:
        if self.graph_harness is None:
            return False
        graph_run = dict(self.graph_harness.get_graph_run(graph_run_id) or {})
        root_task_run_id = str(graph_run.get("task_run_id") or "").strip()
        if root_task_run_id:
            return root_task_run_id == task_run_id
        return str(dict(self.graph_harness.get_checkpoint_state(graph_run_id) or {}).get("task_run_id") or "").strip() == task_run_id

    def _stop_executors(self, task_run_ids: set[str]) -> None:
        for task_run_id in task_run_ids:
            request_executor_stop(
                self.host,
                task_run_id=task_run_id,
                reason="task_record_deleted",
                requested_by="task_record_lifecycle",
            )


def _origin_kind(diagnostics: dict[str, Any]) -> str:
    return str(diagnostics.get("origin_kind") or dict(diagnostics.get("origin") or {}).get("origin_kind") or "").strip()


def _graph_run_id(diagnostics: dict[str, Any]) -> str:
    origin = dict(diagnostics.get("origin") or {})
    runtime_scope = dict(diagnostics.get("runtime_scope") or {})
    return str(diagnostics.get("graph_run_id") or origin.get("graph_run_id") or runtime_scope.get("graph_run_id") or "").strip()


def _executor_task_names(task_run_ids: set[str]) -> set[str]:
    return {
        name
        for task_run_id in task_run_ids
        for name in (f"task-run-executor:{task_run_id}", f"task-run-executor-recover:{task_run_id}")
    }
