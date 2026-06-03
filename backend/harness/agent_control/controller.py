from __future__ import annotations

import inspect
import time
import uuid
import asyncio
from dataclasses import replace
from typing import Any

from artifact_system.artifact_authority import dedupe_artifact_refs, normalize_artifact_ref
from agent_system.identity import normalize_agent_id
from agent_system.profiles.runtime_profile_registry import AgentRuntimeRegistry
from runtime.shared.models import AgentRun
from runtime.shared.models import TaskRun

from .models import SubagentMessage


SUBAGENT_TOOL_NAMES = {
    "spawn_subagent",
    "send_subagent_message",
    "wait_subagent",
    "list_subagents",
    "close_subagent",
}


class SubagentControl:
    def __init__(self, runtime_host: Any, *, services: Any | None = None) -> None:
        self.runtime_host = runtime_host
        self.services = services

    async def execute_tool(
        self,
        *,
        tool_name: str,
        tool_args: dict[str, Any],
        task_run: Any,
        parent_agent_run: AgentRun,
        runtime_assembly: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "spawn_subagent":
            return await self.spawn_subagent(
                task_run=task_run,
                parent_agent_run=parent_agent_run,
                runtime_assembly=runtime_assembly,
                target_agent_id=str(tool_args.get("target_agent_id") or ""),
                goal=str(tool_args.get("goal") or ""),
                instructions=str(tool_args.get("instructions") or ""),
                context_refs=[str(item) for item in list(tool_args.get("context_refs") or []) if str(item)],
                expected_outputs=[str(item) for item in list(tool_args.get("expected_outputs") or []) if str(item)],
            )
        if tool_name == "send_subagent_message":
            return await self.send_message(
                task_run=task_run,
                parent_agent_run=parent_agent_run,
                subagent_run_ref=str(tool_args.get("subagent_run_ref") or ""),
                message=str(tool_args.get("message") or ""),
                context_refs=[str(item) for item in list(tool_args.get("context_refs") or []) if str(item)],
            )
        if tool_name == "wait_subagent":
            return await self.wait(
                task_run=task_run,
                parent_agent_run=parent_agent_run,
                subagent_run_ref=str(tool_args.get("subagent_run_ref") or ""),
                since_message_ref=str(tool_args.get("since_message_ref") or ""),
            )
        if tool_name == "list_subagents":
            return await self.list_subagents(
                task_run=task_run,
                parent_agent_run=parent_agent_run,
                status=str(tool_args.get("status") or ""),
            )
        if tool_name == "close_subagent":
            return await self.close(
                task_run=task_run,
                parent_agent_run=parent_agent_run,
                subagent_run_ref=str(tool_args.get("subagent_run_ref") or ""),
                reason=str(tool_args.get("reason") or ""),
            )
        return {"ok": False, "error": "unknown_subagent_tool", "tool_name": tool_name}

    async def spawn_subagent(
        self,
        *,
        task_run: Any,
        parent_agent_run: AgentRun,
        runtime_assembly: dict[str, Any],
        target_agent_id: str,
        goal: str,
        instructions: str,
        context_refs: list[str],
        expected_outputs: list[str],
    ) -> dict[str, Any]:
        policy = dict(dict(runtime_assembly.get("profile") or {}).get("subagent_policy") or {})
        allowed, reason = self._spawn_allowed(policy=policy, task_run=task_run, parent_agent_run=parent_agent_run, target_agent_id=target_agent_id)
        if not allowed:
            return {"ok": False, "status": "blocked", "error": reason, "target_agent_id": target_agent_id}
        if not goal.strip() and not instructions.strip():
            return {"ok": False, "status": "blocked", "error": "subagent_goal_required", "target_agent_id": target_agent_id}
        target_profile = AgentRuntimeRegistry(self.runtime_host.backend_dir).get_profile(target_agent_id)
        if target_profile is None:
            return {"ok": False, "status": "blocked", "error": "target_agent_profile_not_found", "target_agent_id": target_agent_id}
        now = time.time()
        normalized_target = normalize_agent_id(target_agent_id)
        suffix = uuid.uuid4().hex[:10]
        child_task_run_id = f"{task_run.task_run_id}:subagent:{suffix}"
        child_run = AgentRun(
            agent_run_id=f"agrun:{child_task_run_id}:main",
            task_run_id=child_task_run_id,
            agent_id=normalized_target,
            agent_profile_id=target_profile.agent_profile_id,
            role="subagent_worker",
            spawn_mode="subagent",
            context_scope="subagent_scoped",
            execution_runtime_kind="subagent_task",
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            status="pending",
            created_at=now,
            updated_at=now,
            diagnostics={
                "subagent_control": {
                    "parent_task_run_id": str(task_run.task_run_id),
                    "goal": goal.strip(),
                    "instructions": instructions.strip(),
                    "context_refs": list(context_refs),
                    "expected_outputs": list(expected_outputs),
                    "result_policy": str(policy.get("result_policy") or "observation_refs_only"),
                    "scheduler_status": "waiting_for_subagent_executor",
                }
            },
        )
        self.runtime_host.state_index.upsert_agent_run(child_run)
        message = self._append_message(
            task_run_id=child_task_run_id,
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            subagent_run_ref=child_run.agent_run_id,
            direction="parent_to_child",
            message_type="spawn",
            content=instructions.strip() or goal.strip(),
            refs={
                "target_agent_id": normalized_target,
                "context_refs": list(context_refs),
                "expected_outputs": list(expected_outputs),
            },
        )
        self._append_event(task_run.task_run_id, "subagent_spawned", child_run=child_run, message=message)
        self._append_child_task_run(
            parent_task_run=task_run,
            child_task_run_id=child_task_run_id,
            child_agent_run=child_run,
            target_profile=target_profile,
            goal=goal.strip(),
            instructions=instructions.strip(),
            context_refs=context_refs,
            expected_outputs=expected_outputs,
            runtime_assembly=runtime_assembly,
        )
        return {
            "ok": True,
            "status": child_run.status,
            "subagent_run_ref": child_run.agent_run_id,
            "subtask_run_ref": child_task_run_id,
            "target_agent_id": normalized_target,
            "message_ref": message.message_id,
            "scheduler_status": "scheduled",
        }

    async def send_message(
        self,
        *,
        task_run: Any,
        parent_agent_run: AgentRun,
        subagent_run_ref: str,
        message: str,
        context_refs: list[str],
    ) -> dict[str, Any]:
        child = self._owned_child(task_run.task_run_id, parent_agent_run.agent_run_id, subagent_run_ref)
        if child is None:
            return {"ok": False, "status": "blocked", "error": "subagent_run_not_found_or_not_owned", "subagent_run_ref": subagent_run_ref}
        if child.status in {"completed", "failed", "killed"}:
            return {"ok": False, "status": "blocked", "error": f"subagent_terminal:{child.status}", "subagent_run_ref": subagent_run_ref}
        if not message.strip():
            return {"ok": False, "status": "blocked", "error": "subagent_message_required", "subagent_run_ref": subagent_run_ref}
        saved = self._append_message(
            task_run_id=task_run.task_run_id,
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            subagent_run_ref=child.agent_run_id,
            direction="parent_to_child",
            message_type="message",
            content=message.strip(),
            refs={"context_refs": list(context_refs)},
        )
        self._append_event(task_run.task_run_id, "subagent_message_sent", child_run=child, message=saved)
        return {"ok": True, "status": child.status, "subagent_run_ref": child.agent_run_id, "message_ref": saved.message_id}

    async def wait(
        self,
        *,
        task_run: Any,
        parent_agent_run: AgentRun,
        subagent_run_ref: str,
        since_message_ref: str = "",
    ) -> dict[str, Any]:
        child = self._owned_child(task_run.task_run_id, parent_agent_run.agent_run_id, subagent_run_ref)
        if child is None:
            return {"ok": False, "status": "blocked", "error": "subagent_run_not_found_or_not_owned", "subagent_run_ref": subagent_run_ref}
        messages = self.runtime_host.state_index.list_subagent_run_messages(child.agent_run_id)
        if since_message_ref:
            seen = False
            filtered = []
            for item in messages:
                if seen:
                    filtered.append(item)
                elif item.message_id == since_message_ref:
                    seen = True
            messages = filtered
        visible = [item.to_dict() for item in messages if item.direction in {"child_to_parent", "system"}]
        result = _child_result_payload(self.runtime_host, child)
        return {
            "ok": True,
            "status": child.status,
            "subagent_run_ref": child.agent_run_id,
            "messages": visible,
            "no_update": not bool(visible or result),
            "result_ref": child.result_ref,
            "result_available": bool(result),
            "result": result,
        }

    async def list_subagents(self, *, task_run: Any, parent_agent_run: AgentRun, status: str = "") -> dict[str, Any]:
        children = self._child_agent_runs(task_run_id=task_run.task_run_id, parent_agent_run_ref=parent_agent_run.agent_run_id)
        if status:
            children = [item for item in children if item.status == status]
        return {
            "ok": True,
            "subagents": [_child_summary(item) for item in children],
            "count": len(children),
        }

    async def close(self, *, task_run: Any, parent_agent_run: AgentRun, subagent_run_ref: str, reason: str) -> dict[str, Any]:
        child = self._owned_child(task_run.task_run_id, parent_agent_run.agent_run_id, subagent_run_ref)
        if child is None:
            return {"ok": False, "status": "blocked", "error": "subagent_run_not_found_or_not_owned", "subagent_run_ref": subagent_run_ref}
        terminal = "completed" if child.status == "completed" else "killed"
        updated = replace(
            child,
            status=terminal,
            updated_at=time.time(),
            diagnostics={
                **dict(child.diagnostics or {}),
                "closed_by_parent": {"reason": reason.strip(), "closed_at": time.time()},
            },
        )
        self.runtime_host.state_index.upsert_agent_run(updated)
        message = self._append_message(
            task_run_id=task_run.task_run_id,
            parent_agent_run_ref=parent_agent_run.agent_run_id,
            subagent_run_ref=updated.agent_run_id,
            direction="system",
            message_type="close",
            content=reason.strip() or "closed by parent agent",
            refs={},
        )
        self._append_event(task_run.task_run_id, "subagent_closed", child_run=updated, message=message)
        return {"ok": True, "status": updated.status, "subagent_run_ref": updated.agent_run_id, "message_ref": message.message_id}

    def _spawn_allowed(self, *, policy: dict[str, Any], task_run: Any, parent_agent_run: AgentRun, target_agent_id: str) -> tuple[bool, str]:
        if not bool(policy.get("enabled") is True):
            return False, "subagent_policy_disabled"
        if parent_agent_run.spawn_mode == "subagent" and not bool(policy.get("allow_nested_subagents") is True):
            return False, "nested_subagent_denied"
        target = normalize_agent_id(target_agent_id)
        allowed_ids = {normalize_agent_id(item) for item in list(policy.get("allowed_subagent_ids") or []) if str(item)}
        if not target or target not in allowed_ids:
            return False, "target_subagent_not_allowed"
        children = self._child_agent_runs(task_run_id=task_run.task_run_id, parent_agent_run_ref=parent_agent_run.agent_run_id)
        max_runs = int(policy.get("max_subagent_runs_per_task") or 0)
        if max_runs > 0 and len(children) >= max_runs:
            return False, "max_subagent_runs_per_task_exceeded"
        active = [item for item in children if item.status in {"pending", "running"}]
        max_active = int(policy.get("max_active_subagents") or 0)
        if max_active > 0 and len(active) >= max_active:
            return False, "max_active_subagents_exceeded"
        return True, ""

    def _owned_child(self, task_run_id: str, parent_agent_run_ref: str, subagent_run_ref: str) -> AgentRun | None:
        for item in self._child_agent_runs(task_run_id=task_run_id, parent_agent_run_ref=parent_agent_run_ref):
            if item.agent_run_id == subagent_run_ref:
                return item
        return None

    def _child_agent_runs(self, *, task_run_id: str, parent_agent_run_ref: str) -> list[AgentRun]:
        snapshot = dict(self.runtime_host.state_index.read_snapshot() or {})
        runs = []
        for value in dict(snapshot.get("agent_runs") or {}).values():
            if not isinstance(value, dict):
                continue
            child = AgentRun(
                agent_run_id=str(value.get("agent_run_id") or ""),
                task_run_id=str(value.get("task_run_id") or ""),
                agent_id=str(value.get("agent_id") or ""),
                agent_profile_id=str(value.get("agent_profile_id") or ""),
                role=str(value.get("role") or "main_executor"),
                spawn_mode=str(value.get("spawn_mode") or "single_agent"),
                context_scope=str(value.get("context_scope") or "task_default"),
                execution_runtime_kind=str(value.get("execution_runtime_kind") or ""),
                parent_agent_run_ref=str(value.get("parent_agent_run_ref") or ""),
                status=value.get("status", "pending"),
                latest_checkpoint_ref=str(value.get("latest_checkpoint_ref") or ""),
                result_ref=str(value.get("result_ref") or ""),
                created_at=float(value.get("created_at") or 0.0),
                updated_at=float(value.get("updated_at") or 0.0),
                diagnostics=dict(value.get("diagnostics") or {}),
            )
            control = dict(dict(child.diagnostics or {}).get("subagent_control") or {})
            if (
                str(control.get("parent_task_run_id") or "") == task_run_id
                and child.parent_agent_run_ref == parent_agent_run_ref
                and child.spawn_mode == "subagent"
            ):
                runs.append(child)
        runs.sort(key=lambda item: item.created_at)
        return runs

    def _append_message(
        self,
        *,
        task_run_id: str,
        parent_agent_run_ref: str,
        subagent_run_ref: str,
        direction: str,
        message_type: str,
        content: str,
        refs: dict[str, Any],
    ) -> SubagentMessage:
        message = SubagentMessage(
            message_id=f"submsg:{task_run_id}:{uuid.uuid4().hex[:10]}",
            task_run_id=task_run_id,
            parent_agent_run_ref=parent_agent_run_ref,
            subagent_run_ref=subagent_run_ref,
            direction=direction,
            message_type=message_type,
            content=content,
            refs=dict(refs or {}),
            created_at=time.time(),
        )
        self.runtime_host.state_index.upsert_subagent_message(message)
        return message

    def _append_event(self, task_run_id: str, event_type: str, *, child_run: AgentRun, message: SubagentMessage) -> None:
        self.runtime_host.event_log.append(
            task_run_id,
            event_type,
            payload={"child_agent_run": child_run.to_dict(), "subagent_message": message.to_dict()},
            refs={
                "task_run_ref": task_run_id,
                "parent_agent_run_ref": child_run.parent_agent_run_ref,
                "subagent_run_ref": child_run.agent_run_id,
                "subagent_message_ref": message.message_id,
            },
        )

    def _append_child_task_run(
        self,
        *,
        parent_task_run: Any,
        child_task_run_id: str,
        child_agent_run: AgentRun,
        target_profile: Any,
        goal: str,
        instructions: str,
        context_refs: list[str],
        expected_outputs: list[str],
        runtime_assembly: dict[str, Any],
    ) -> None:
        task_selection = dict(dict(parent_task_run.diagnostics or {}).get("runtime_task_selection") or dict(parent_task_run.diagnostics or {}).get("task_selection") or {})
        runtime_profile = dict(task_selection.get("runtime_profile") or {})
        task_selection["runtime_profile"] = runtime_profile
        contract_payload = {
            "contract_id": f"subagent-contract:{child_task_run_id}",
            "contract_source": "subagent_control",
            "task_environment_id": str(dict(runtime_assembly.get("task_environment") or {}).get("environment_id") or ""),
            "task_goal_type": str(dict(parent_task_run.diagnostics or {}).get("task_goal_type") or "subagent_worker"),
            "user_visible_goal": goal,
            "task_run_goal": goal,
            "objective": goal,
            "instructions": instructions,
            "context_refs": list(context_refs),
            "expected_outputs": list(expected_outputs),
            "completion_criteria": list(expected_outputs) or ([goal] if goal else []),
            "output_contract": {"kind": "subagent_result", "required_refs": list(expected_outputs)},
            "origin": {
                "origin_kind": "subagent_spawned",
                "origin_authority": "orchestration.subagent_control",
                "parent_task_run_id": str(parent_task_run.task_run_id),
                "parent_agent_run_ref": str(child_agent_run.parent_agent_run_ref),
            },
            "authority": "task_system.task_contract",
        }
        child_task_run = TaskRun(
            task_run_id=child_task_run_id,
            session_id=str(parent_task_run.session_id),
            task_id=f"{parent_task_run.task_id}:subagent:{child_task_run_id.rsplit(':', 1)[-1]}",
            task_contract_ref="",
            owner_agent_seat_id=str(getattr(parent_task_run, "owner_agent_seat_id", "main") or "main"),
            agent_id=str(child_agent_run.agent_id),
            agent_profile_id=str(target_profile.agent_profile_id),
            execution_runtime_kind="subagent_task",
            status="waiting_executor",
            created_at=time.time(),
            updated_at=time.time(),
            diagnostics={
                "contract": contract_payload,
                "runtime_task_selection": task_selection,
                "model_selection": dict(dict(parent_task_run.diagnostics or {}).get("model_selection") or {}),
                "origin": {
                    "origin_kind": "subagent_spawned",
                    "origin_authority": "orchestration.subagent_control",
                    "parent_task_run_id": str(parent_task_run.task_run_id),
                    "parent_agent_run_ref": str(child_agent_run.parent_agent_run_ref),
                },
                "subagent_control": {
                    "parent_task_run_id": str(parent_task_run.task_run_id),
                    "parent_agent_run_ref": str(child_agent_run.parent_agent_run_ref),
                    "subagent_run_ref": str(child_agent_run.agent_run_id),
                    "goal": goal,
                    "instructions": instructions,
                    "context_refs": list(context_refs),
                    "expected_outputs": list(expected_outputs),
                },
                "executor_status": "waiting_executor",
            },
        )
        self.runtime_host.state_index.upsert_task_run(child_task_run)
        execute = _raw_service_callback(self.services, "execute_task_run_callback")
        if not callable(execute):
            return

        async def _runner() -> None:
            try:
                result = execute(child_task_run_id, max_steps=6)
                if hasattr(result, "__await__"):
                    await result
                latest_task_run = self.runtime_host.state_index.get_task_run(child_task_run_id)
                if latest_task_run is not None:
                    self._append_message(
                        task_run_id=child_task_run_id,
                        parent_agent_run_ref=str(child_agent_run.parent_agent_run_ref),
                        subagent_run_ref=str(child_agent_run.agent_run_id),
                        direction="system",
                        message_type="status",
                        content=_child_status_summary(latest_task_run),
                        refs={
                            "task_run_status": str(latest_task_run.status or ""),
                            "terminal_reason": str(latest_task_run.terminal_reason or ""),
                        },
                    )
            except Exception as exc:
                self._append_message(
                    task_run_id=child_task_run_id,
                    parent_agent_run_ref=str(child_agent_run.parent_agent_run_ref),
                    subagent_run_ref=str(child_agent_run.agent_run_id),
                    direction="system",
                    message_type="error",
                    content=str(exc),
                    refs={"error": str(exc)},
                )
                self.runtime_host.event_log.append(
                    child_task_run_id,
                    "subagent_executor_failed",
                    payload={"task_run_id": child_task_run_id, "error": str(exc)},
                    refs={"task_run_ref": child_task_run_id},
                )

        spawner = getattr(self.runtime_host, "spawn_background_task", None)
        if callable(spawner):
            spawner(_runner(), name=f"subagent-executor:{child_task_run_id}")
            return
        asyncio.create_task(_runner())


def _child_status_summary(task_run: Any) -> str:
    status = str(getattr(task_run, "status", "") or "")
    terminal_reason = str(getattr(task_run, "terminal_reason", "") or "")
    if terminal_reason:
        return f"subagent task status: {status}, reason: {terminal_reason}"
    return f"subagent task status: {status}"


def _child_summary(child: AgentRun) -> dict[str, Any]:
    diagnostics = dict(child.diagnostics or {})
    control = dict(diagnostics.get("subagent_control") or {})
    return {
        "subagent_run_ref": child.agent_run_id,
        "agent_id": child.agent_id,
        "agent_profile_id": child.agent_profile_id,
        "status": child.status,
        "goal": str(control.get("goal") or ""),
        "result_ref": child.result_ref,
        "created_at": child.created_at,
        "updated_at": child.updated_at,
    }


def _child_result_payload(runtime_host: Any, child: AgentRun) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    result_ref = str(child.result_ref or "").strip()
    if result_ref:
        store = getattr(runtime_host, "runtime_objects", None)
        get_object = getattr(store, "get_object", None)
        if callable(get_object):
            try:
                resolved = get_object(result_ref)
            except Exception:
                resolved = {}
            if isinstance(resolved, dict):
                payload.update(resolved)

    state_index = getattr(runtime_host, "state_index", None)
    list_results = getattr(state_index, "list_task_agent_run_results", None)
    if callable(list_results):
        try:
            results = list_results(child.task_run_id)
        except Exception:
            results = []
        for item in results:
            if str(getattr(item, "agent_run_id", "") or "") != child.agent_run_id:
                continue
            output_ref = str(getattr(item, "output_ref", "") or "").strip()
            if output_ref and not payload:
                store = getattr(runtime_host, "runtime_objects", None)
                get_object = getattr(store, "get_object", None)
                if callable(get_object):
                    try:
                        resolved = get_object(output_ref)
                    except Exception:
                        resolved = {}
                    if isinstance(resolved, dict):
                        payload.update(resolved)
            payload.setdefault("summary", str(getattr(item, "summary", "") or ""))
            payload.setdefault("artifact_refs", list(getattr(item, "artifact_refs", ()) or ()))
            payload.setdefault("result_ref", output_ref or result_ref)
            break

    final_answer = str(payload.get("final_answer") or "").strip()
    artifact_refs = (
        dedupe_artifact_refs([normalize_artifact_ref(item) for item in list(payload.get("artifact_refs") or [])])
        if isinstance(payload.get("artifact_refs"), list)
        else []
    )
    if not final_answer and not artifact_refs:
        return {}
    return {
        "status": str(child.status or ""),
        "result_ref": str(payload.get("result_ref") or result_ref),
        "final_answer": final_answer,
        "summary": str(payload.get("summary") or final_answer[:500]).strip(),
        "artifact_refs": artifact_refs,
        "observation_refs": list(payload.get("observation_refs") or []) if isinstance(payload.get("observation_refs"), list) else [],
        "authority": "orchestration.subagent_result_projection",
    }


def _raw_service_callback(services: Any, name: str) -> Any:
    if services is None:
        return None
    value = getattr(services, name, None)
    if inspect.ismethod(value) and getattr(value, "__self__", None) is services:
        static_value = inspect.getattr_static(services, name, None)
        if callable(static_value):
            return static_value
    return value
