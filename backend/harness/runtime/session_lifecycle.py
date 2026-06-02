from __future__ import annotations

from typing import Any

from harness.graph.lifecycle_manager import GraphTaskLifecycleManager


class SessionRuntimeLifecycleManager:
    """Deletes runtime records that are owned by one session."""

    authority = "harness.runtime.session_lifecycle"

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.host = runtime.harness_runtime.single_agent_runtime_host
        self.graph_harness = runtime.harness_runtime.graph_harness

    async def delete_session_runtime(self, session_id: str) -> dict[str, Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is required")
        history = self.runtime.session_manager.get_history(normalized)
        binding = dict(history.get("task_binding") or {})
        task_run_ids = {
            str(getattr(item, "task_run_id", "") or "").strip()
            for item in self.host.state_index.list_session_task_runs(normalized)
            if str(getattr(item, "task_run_id", "") or "").strip()
        }
        turn_run_ids = {
            str(getattr(item, "turn_run_id", "") or "").strip()
            for item in self.host.state_index.list_session_turn_runs(normalized)
            if str(getattr(item, "turn_run_id", "") or "").strip()
        }
        runtime_runs = list(self.host.run_registry.list_session_runs(normalized))
        graph_run_ids = self._session_graph_run_ids(
            session_id=normalized,
            binding=binding,
            task_run_ids=task_run_ids,
        )
        cancel_effect = await self.host.cancel_background_tasks(
            names=self._background_task_names(task_run_ids=task_run_ids, runtime_runs=runtime_runs),
            reason="session_deleted",
        )
        graph_effects: list[dict[str, Any]] = []
        graph_manager = GraphTaskLifecycleManager(
            base_dir=self.runtime.base_dir,
            graph_harness=self.graph_harness,
        )
        for graph_run_id in sorted(graph_run_ids):
            try:
                graph_effects.append(graph_manager.delete_graph_run(graph_run_id))
            except ValueError as exc:
                graph_effects.append(
                    {
                        "authority": "harness.graph_task_lifecycle",
                        "mode": "delete",
                        "graph_run_id": graph_run_id,
                        "deleted": False,
                        "reason": str(exc),
                    }
                )
        active_turn_effect = self.host.active_turn_registry.clear_session(normalized, reason="session_deleted")
        runtime_run_effect = self.host.run_registry.delete_session_runs(normalized)
        event_log_effect = self._delete_event_logs(
            task_run_ids=task_run_ids,
            turn_run_ids=turn_run_ids,
            chat_event_log_ids={
                str(getattr(item, "event_log_id", "") or "").strip()
                for item in runtime_runs
                if str(getattr(item, "event_log_id", "") or "").strip()
            },
        )
        prompt_effect = self.host.prompt_accounting_ledger.prune_session(
            normalized,
            task_run_ids=task_run_ids | turn_run_ids,
        )
        execution_effect = self.host.execution_store.prune_task_runs(task_run_ids)
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
            "graph_run_ids": sorted(graph_run_ids),
            "effects": {
                "background_tasks": cancel_effect,
                "graph_runs": graph_effects,
                "active_turn": active_turn_effect,
                "runtime_runs": runtime_run_effect,
                "event_logs": event_log_effect,
                "prompt_accounting": prompt_effect,
                "executions": execution_effect,
                "state_index": state_effect,
                "project_maintenance": maintenance_effect,
            },
        }

    def _session_graph_run_ids(self, *, session_id: str, binding: dict[str, Any], task_run_ids: set[str]) -> set[str]:
        graph_run_ids = {
            str(binding.get("graph_run_id") or "").strip(),
        } - {""}
        for task_run_id in task_run_ids:
            task_run = self.host.state_index.get_task_run(task_run_id)
            diagnostics = dict(getattr(task_run, "diagnostics", {}) or {}) if task_run is not None else {}
            graph_run_id = str(diagnostics.get("graph_run_id") or "").strip()
            if graph_run_id:
                graph_run_ids.add(graph_run_id)
        for graph_run_id in list(graph_run_ids):
            graph_run = dict(self.graph_harness.get_graph_run(graph_run_id) or {})
            graph_session_id = str(graph_run.get("session_id") or "").strip()
            if graph_session_id and graph_session_id != session_id:
                graph_run_ids.discard(graph_run_id)
        return graph_run_ids

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

    def _delete_event_logs(
        self,
        *,
        task_run_ids: set[str],
        turn_run_ids: set[str],
        chat_event_log_ids: set[str],
    ) -> dict[str, Any]:
        deleted: list[str] = []
        for run_id in sorted(task_run_ids | turn_run_ids | chat_event_log_ids):
            if self.host.event_log.delete_events(run_id):
                deleted.append(run_id)
        return {
            "authority": "harness.runtime.session_lifecycle.event_logs",
            "deleted_run_ids": deleted,
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
