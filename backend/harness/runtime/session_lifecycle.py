from __future__ import annotations

from typing import Any

from harness.graph.lifecycle_manager import GraphTaskLifecycleManager
from harness.loop.task_run_execution_control import request_executor_stop


class SessionRuntimeLifecycleManager:
    """Detaches runtime records from a deleted foreground session."""

    authority = "harness.runtime.session_lifecycle"

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.host = runtime.harness_runtime.single_agent_runtime_host

    async def detach_session_runtime(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is required")
        history = self._session_history(normalized)
        binding = dict(history.get("task_binding") or {})
        task_run_ids = self._session_task_run_ids(normalized)
        turn_run_ids = self._session_turn_run_ids(normalized)
        runtime_runs = list(self.host.run_registry.list_session_runs(normalized))
        executor_stop_effect = self._request_executor_stop(task_run_ids=task_run_ids)
        tombstone_effect = self.host.state_index.mark_session_deleted(normalized)
        cancel_effect = await self.host.cancel_background_tasks(
            names=self._background_task_names(task_run_ids=task_run_ids, runtime_runs=runtime_runs),
            reason="session_deleted",
        )
        late_task_run_ids = self._session_task_run_ids(normalized) - task_run_ids
        late_runtime_runs = [
            item
            for item in self.host.run_registry.list_session_runs(normalized)
            if str(getattr(item, "stream_run_id", "") or "").strip()
            not in {
                str(getattr(run, "stream_run_id", "") or "").strip()
                for run in runtime_runs
            }
        ]
        late_cancel_effect = {
            "authority": "single_agent_runtime_host.cancel_background_tasks",
            "requested_names": [],
            "cancelled_count": 0,
            "timed_out": False,
            "reason": "no_late_runtime_tasks",
        }
        late_executor_stop_effect = {
            "authority": "harness.runtime.session_lifecycle.executor_stop",
            "requested_task_run_ids": [],
            "accepted_task_run_ids": [],
        }
        if late_task_run_ids or late_runtime_runs:
            late_executor_stop_effect = self._request_executor_stop(task_run_ids=late_task_run_ids)
            late_cancel_effect = await self.host.cancel_background_tasks(
                names=self._background_task_names(task_run_ids=late_task_run_ids, runtime_runs=late_runtime_runs),
                reason="session_deleted",
            )
            task_run_ids |= late_task_run_ids
            runtime_runs.extend(late_runtime_runs)
        turn_run_ids |= self._session_turn_run_ids(normalized)
        active_turn_effect = self.host.active_turn_registry.clear_session(normalized, reason="session_deleted")
        runtime_run_effect = self.host.run_registry.delete_session_runs(normalized)
        graph_task_effect = self._delete_bound_graph_task(binding)
        state_effect = {
            "task_runs": self.host.state_index.prune_task_runs(task_run_ids),
            "turn_runs": self.host.state_index.prune_turn_runs(turn_run_ids),
        }
        maintenance_effect = self._mark_project_maintenance_ended(binding=binding)
        return {
            "authority": self.authority,
            "session_id": normalized,
            "task_binding": binding,
            "task_run_ids": sorted(task_run_ids),
            "turn_run_ids": sorted(turn_run_ids),
            "effects": {
                "background_tasks": cancel_effect,
                "late_background_tasks": late_cancel_effect,
                "executor_stop": executor_stop_effect,
                "late_executor_stop": late_executor_stop_effect,
                "session_deletion_tombstone": tombstone_effect,
                "active_turn": active_turn_effect,
                "runtime_runs": runtime_run_effect,
                "graph_task": graph_task_effect,
                "state_index": state_effect,
                "project_maintenance": maintenance_effect,
            },
        }

    def _session_history(self, session_id: str) -> dict[str, Any]:
        try:
            return dict(self.runtime.session_manager.get_history(session_id) or {})
        except ValueError as exc:
            if str(exc) == "Unknown session_id":
                return {}
            raise

    def _session_task_run_ids(self, session_id: str) -> set[str]:
        return {
            str(getattr(item, "task_run_id", "") or "").strip()
            for item in self.host.state_index.list_session_task_runs(session_id)
            if str(getattr(item, "task_run_id", "") or "").strip()
        }

    def _session_turn_run_ids(self, session_id: str) -> set[str]:
        return {
            str(getattr(item, "turn_run_id", "") or "").strip()
            for item in self.host.state_index.list_session_turn_runs(session_id)
            if str(getattr(item, "turn_run_id", "") or "").strip()
        }

    def _request_executor_stop(self, *, task_run_ids: set[str]) -> dict[str, Any]:
        accepted: list[str] = []
        for task_run_id in sorted(task_run_ids):
            if request_executor_stop(
                self.host,
                task_run_id=task_run_id,
                reason="session_deleted",
                requested_by="session_lifecycle",
            ):
                accepted.append(task_run_id)
        return {
            "authority": "harness.runtime.session_lifecycle.executor_stop",
            "requested_task_run_ids": sorted(task_run_ids),
            "accepted_task_run_ids": accepted,
        }

    @staticmethod
    def _background_task_names(*, task_run_ids: set[str], runtime_runs: list[Any]) -> set[str]:
        names: set[str] = set()
        for task_run_id in task_run_ids:
            names.add(f"task-run-executor:{task_run_id}")
            names.add(f"task-run-executor-recover:{task_run_id}")
        for run in runtime_runs:
            stream_run_id = str(getattr(run, "stream_run_id", "") or "").strip()
            if stream_run_id:
                names.add(f"chat-run-{stream_run_id}")
        return names

    def _delete_bound_graph_task(self, binding: dict[str, Any]) -> dict[str, Any]:
        graph_run_id = str(dict(binding or {}).get("graph_run_id") or "").strip()
        if not graph_run_id:
            return {
                "authority": "harness.runtime.session_lifecycle.graph_task",
                "deleted": False,
                "reason": "no_bound_graph_run",
            }
        graph_harness = getattr(self.runtime.harness_runtime, "graph_harness", None)
        if graph_harness is None:
            return {
                "authority": "harness.runtime.session_lifecycle.graph_task",
                "deleted": False,
                "reason": "graph_harness_unavailable",
                "graph_run_id": graph_run_id,
            }
        manager = GraphTaskLifecycleManager(base_dir=self.runtime.base_dir, graph_harness=graph_harness)
        try:
            preview = manager.preview_delete_graph_run(graph_run_id)
            if not str(preview.get("root_task_run_id") or "").strip():
                return {
                    "authority": "harness.runtime.session_lifecycle.graph_task",
                    "deleted": False,
                    "reason": "graph_root_already_missing",
                    "graph_run_id": graph_run_id,
                }
            result = manager.delete_graph_run(graph_run_id)
        except ValueError as exc:
            return {
                "authority": "harness.runtime.session_lifecycle.graph_task",
                "deleted": False,
                "reason": str(exc),
                "graph_run_id": graph_run_id,
            }
        return {
            "authority": "harness.runtime.session_lifecycle.graph_task",
            "deleted": True,
            "graph_run_id": graph_run_id,
            "task_run_ids": list(result.get("task_run_ids") or []),
        }

    @staticmethod
    def _mark_project_maintenance_ended(*, binding: dict[str, Any]) -> dict[str, Any]:
        project_id = str(binding.get("project_id") or "").strip()
        if not project_id:
            return {
                "authority": "harness.runtime.session_lifecycle.project_maintenance",
                "project_id": "",
                "recorded": False,
                "reason": "no_project_binding",
            }
        return {
            "authority": "harness.runtime.session_lifecycle.project_maintenance",
            "project_id": project_id,
            "recorded": False,
            "reason": "project_library_lifecycle_owns_project_resources",
        }
