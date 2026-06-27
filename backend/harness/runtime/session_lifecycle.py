from __future__ import annotations

import asyncio
from typing import Any

from graph_system.lifecycle_manager import GraphTaskLifecycleManager
from harness.loop.task_run_execution_control import executor_control_signal_effect, request_executor_control_signal


class SessionRuntimeLifecycleManager:
    """Detaches runtime records from a deleted foreground session."""

    authority = "harness.runtime.session_lifecycle"

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.host = runtime.harness_runtime.single_agent_runtime_host

    async def detach_session_runtime(self, session_id: str, *, session_history: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is required")
        history = dict(session_history) if session_history is not None else await asyncio.to_thread(self._session_history, normalized)
        binding = dict(history.get("task_binding") or {})
        refs = await asyncio.to_thread(self._session_runtime_refs, normalized)
        task_run_ids = set(refs["task_run_ids"])
        turn_run_ids = set(refs["turn_run_ids"])
        runtime_runs = list(refs["runtime_runs"])
        task_run_sessions = await asyncio.to_thread(self._task_run_sessions, task_run_ids)
        runtime_run_sessions = self._runtime_run_sessions(runtime_runs)
        executor_stop_effect = self._request_executor_stop(task_run_ids=task_run_ids)
        tombstone_effect = await asyncio.to_thread(self.host.state_index.mark_session_deleted, normalized)
        cell_cancel_effect = self.host.cancel_task_run_cells(
            task_run_sessions=task_run_sessions,
            reason="session_deleted",
        )
        runtime_cell_cancel_effect = self.host.cancel_runtime_run_cells(
            runtime_run_sessions=runtime_run_sessions,
            reason="session_deleted",
        )
        cancel_effect = await self.host.cancel_background_tasks(
            names=self._background_task_names(session_id=normalized),
            reason="session_deleted",
        )
        late_refs = await asyncio.to_thread(
            self._late_runtime_refs,
            normalized,
            task_run_ids,
            runtime_runs,
        )
        late_task_run_ids = set(late_refs["task_run_ids"])
        late_runtime_runs = list(late_refs["runtime_runs"])
        late_cancel_effect = {
            "authority": "single_agent_runtime_host.cancel_background_tasks",
            "requested_names": [],
            "cancelled_count": 0,
            "timed_out": False,
            "reason": "no_late_runtime_tasks",
        }
        late_cell_cancel_effect = {
            "authority": "single_agent_runtime_host.cancel_task_run_cells",
            "requested_task_run_ids": [],
            "cancelled_count": 0,
            "cancelled_task_run_ids": [],
            "rejected": [],
            "missing_scope_task_run_ids": [],
            "reason": "no_late_runtime_tasks",
        }
        late_executor_stop_effect = {
            "authority": "harness.runtime.session_lifecycle.executor_stop",
            "requested_task_run_ids": [],
            "accepted_task_run_ids": [],
            "control_signals": [],
            "failed_task_run_ids": [],
        }
        late_runtime_cell_cancel_effect = {
            "authority": "single_agent_runtime_host.cancel_runtime_run_cells",
            "requested_stream_run_ids": [],
            "cancelled_count": 0,
            "cancelled_stream_run_ids": [],
            "rejected": [],
            "missing_scope_stream_run_ids": [],
            "reason": "no_late_runtime_tasks",
        }
        if late_task_run_ids or late_runtime_runs:
            late_task_run_sessions = await asyncio.to_thread(self._task_run_sessions, late_task_run_ids)
            late_runtime_run_sessions = self._runtime_run_sessions(late_runtime_runs)
            late_executor_stop_effect = self._request_executor_stop(task_run_ids=late_task_run_ids)
            late_cell_cancel_effect = self.host.cancel_task_run_cells(
                task_run_sessions=late_task_run_sessions,
                reason="session_deleted",
            )
            late_runtime_cell_cancel_effect = self.host.cancel_runtime_run_cells(
                runtime_run_sessions=late_runtime_run_sessions,
                reason="session_deleted",
            )
            late_cancel_effect = await self.host.cancel_background_tasks(
                names=self._background_task_names(session_id=normalized),
                reason="session_deleted",
            )
            task_run_ids |= late_task_run_ids
            task_run_sessions.update(late_task_run_sessions)
            runtime_run_sessions.update(late_runtime_run_sessions)
            runtime_runs.extend(late_runtime_runs)
        turn_run_ids |= await asyncio.to_thread(self._session_turn_run_ids, normalized)
        active_turn_effect = self.host.active_turn_registry.clear_session(normalized, reason="session_deleted")
        storage_effect = await asyncio.to_thread(
            self._detach_session_runtime_storage,
            normalized,
            binding,
            task_run_ids,
            turn_run_ids,
        )
        return {
            "authority": self.authority,
            "session_id": normalized,
            "task_binding": binding,
            "task_run_ids": sorted(task_run_ids),
            "turn_run_ids": sorted(turn_run_ids),
            "effects": {
                "agent_cells": cell_cancel_effect,
                "late_agent_cells": late_cell_cancel_effect,
                "runtime_run_cells": runtime_cell_cancel_effect,
                "late_runtime_run_cells": late_runtime_cell_cancel_effect,
                "background_tasks": cancel_effect,
                "late_background_tasks": late_cancel_effect,
                "executor_stop": executor_stop_effect,
                "late_executor_stop": late_executor_stop_effect,
                "session_deletion_tombstone": tombstone_effect,
                "active_turn": active_turn_effect,
                "runtime_runs": storage_effect["runtime_runs"],
                "graph_task": storage_effect["graph_task"],
                "state_index": storage_effect["state_index"],
                "project_maintenance": storage_effect["project_maintenance"],
            },
        }

    def _task_run_sessions(self, task_run_ids: set[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for task_run_id in task_run_ids:
            task_run = self.host.state_index.get_task_run(task_run_id)
            session_id = str(getattr(task_run, "session_id", "") or "").strip() if task_run is not None else ""
            if session_id:
                result[str(task_run_id or "").strip()] = session_id
        return result

    @staticmethod
    def _runtime_run_sessions(runtime_runs: list[Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for run in runtime_runs:
            stream_run_id = str(getattr(run, "stream_run_id", "") or "").strip()
            session_id = str(getattr(run, "session_id", "") or "").strip()
            if stream_run_id and session_id:
                result[stream_run_id] = session_id
        return result

    def _session_history(self, session_id: str) -> dict[str, Any]:
        try:
            return dict(self.runtime.session_manager.get_history(session_id) or {})
        except ValueError as exc:
            if str(exc) == "Unknown session_id":
                return {}
            raise

    def _session_runtime_refs(self, session_id: str) -> dict[str, Any]:
        return {
            "task_run_ids": self._session_task_run_ids(session_id),
            "turn_run_ids": self._session_turn_run_ids(session_id),
            "runtime_runs": list(self.host.run_registry.list_session_runs(session_id)),
        }

    def _late_runtime_refs(self, session_id: str, task_run_ids: set[str], runtime_runs: list[Any]) -> dict[str, Any]:
        known_stream_run_ids = {
            str(getattr(run, "stream_run_id", "") or "").strip()
            for run in runtime_runs
            if str(getattr(run, "stream_run_id", "") or "").strip()
        }
        return {
            "task_run_ids": self._session_task_run_ids(session_id) - set(task_run_ids),
            "runtime_runs": [
                item
                for item in self.host.run_registry.list_session_runs(session_id)
                if str(getattr(item, "stream_run_id", "") or "").strip() not in known_stream_run_ids
            ],
        }

    def _detach_session_runtime_storage(
        self,
        session_id: str,
        binding: dict[str, Any],
        task_run_ids: set[str],
        turn_run_ids: set[str],
    ) -> dict[str, Any]:
        return {
            "runtime_runs": self.host.run_registry.delete_session_runs(session_id),
            "graph_task": self._delete_bound_graph_task(binding),
            "state_index": {
                "task_runs": self.host.state_index.prune_task_runs(task_run_ids),
                "turn_runs": self.host.state_index.prune_turn_runs(turn_run_ids),
            },
            "project_maintenance": self._mark_project_maintenance_ended(binding=binding),
        }

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
        signals: list[dict[str, Any]] = []
        failed: list[str] = []
        for task_run_id in sorted(task_run_ids):
            signal = request_executor_control_signal(
                self.host,
                task_run_id=task_run_id,
                kind="stop",
                reason="session_deleted",
                requested_by="session_lifecycle",
                unavailable_reason="session_deleted",
            )
            if signal is None:
                failed.append(task_run_id)
                continue
            if signal.signal_id:
                accepted.append(task_run_id)
                signals.append(executor_control_signal_effect(signal))
            else:
                failed.append(task_run_id)
        return {
            "authority": "harness.runtime.session_lifecycle.executor_stop",
            "requested_task_run_ids": sorted(task_run_ids),
            "accepted_task_run_ids": accepted,
            "control_signals": signals,
            "failed_task_run_ids": failed,
        }

    @staticmethod
    def _background_task_names(*, session_id: str) -> set[str]:
        normalized = str(session_id or "").strip()
        return {f"queued-input-dispatch:{normalized}"} if normalized else set()

    def _delete_bound_graph_task(self, binding: dict[str, Any]) -> dict[str, Any]:
        graph_run_id = str(dict(binding or {}).get("graph_run_id") or "").strip()
        if not graph_run_id:
            return {
                "authority": "harness.runtime.session_lifecycle.graph_task",
                "deleted": False,
                "reason": "no_bound_graph_run",
            }
        graph_system = getattr(self.runtime.harness_runtime, "graph_system", None)
        if graph_system is None:
            return {
                "authority": "harness.runtime.session_lifecycle.graph_task",
                "deleted": False,
                "reason": "graph_system_unavailable",
                "graph_run_id": graph_run_id,
            }
        manager = GraphTaskLifecycleManager(base_dir=self.runtime.base_dir, graph_system=graph_system)
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
