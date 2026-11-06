from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from harness.entrypoint.models import HarnessRuntimeRequest
from harness.runtime import assemble_runtime
from permissions.policy import normalize_permission_mode
from task_system.episodes import AgentExecutionEpisode, EpisodeRepository, EpisodeResult
from task_system.reducer import TaskReducer
from task_system.work_environments.models import TaskContextPackage, TaskEvent, stable_task_environment_id
from task_system.work_environments.repository import TaskEnvironmentRepository
from task_system.work_environments.service import TaskWorkEnvironmentService
from task_system.work_environments.view_service import TaskEnvironmentViewService
from task_system.work_products import WorkProduct


class TaskEnvironmentEpisodeBridge:
    authority = "harness.task_environment_episode_bridge"

    def __init__(self, facade: Any) -> None:
        self.facade = facade
        self.base_dir = Path(facade.base_dir)

    async def execute(
        self,
        *,
        task_environment_id: str,
        episode_id: str = "",
        max_steps: int = 12,
    ) -> dict[str, Any]:
        service = TaskWorkEnvironmentService(self.base_dir)
        episode_repository = EpisodeRepository(self.base_dir)
        environment = service.repository.get_task_environment(task_environment_id)
        if environment is None:
            raise KeyError(f"TaskWorkEnvironment not found: {task_environment_id}")
        episode = _task_episode_for_execution(
            episode_repository=episode_repository,
            task_environment_id=environment.task_environment_id,
            episode_id=episode_id,
        )
        if episode.task_environment_id != environment.task_environment_id:
            raise ValueError("episode does not belong to task environment")
        context_package = _task_episode_context_package(
            repository=service.repository,
            environment=environment,
            episode=episode,
        )
        agent_profile_resolution = self._resolve_agent_profile(episode)
        if not agent_profile_resolution.get("ok"):
            executor_result = _task_episode_executor_blocked_result(
                reason=str(agent_profile_resolution.get("reason") or "task_episode_agent_profile_unresolved"),
                environment=environment.to_dict(),
                episode=episode,
                context_package=context_package,
                diagnostics=dict(agent_profile_resolution.get("diagnostics") or {}),
            )
            preflight_record = _record_task_episode_preflight_blocked(
                base_dir=self.base_dir,
                repository=service.repository,
                episode_repository=episode_repository,
                environment=environment.to_dict(),
                episode=episode,
                executor_result=executor_result,
            )
            return {
                "ok": False,
                "status": "blocked",
                "executor_result": executor_result,
                "reduction": preflight_record,
                "task_environment_view": TaskEnvironmentViewService(self.base_dir).task_environment_detail(environment.task_environment_id),
                "lease": {},
                "lease_release": {},
                "authority": self.authority,
            }

        agent_runtime_profile = agent_profile_resolution["profile"]
        agent_profile_id = str(agent_profile_resolution.get("agent_profile_id") or "").strip()
        agent_id = str(agent_profile_resolution.get("agent_id") or "").strip()
        session_id = _task_episode_session_id(environment.to_dict(), episode=episode, context_package=context_package)
        self._ensure_execution_session(
            session_id=session_id,
            environment=environment.to_dict(),
            episode=episode,
            context_package=context_package,
        )
        turn_id = stable_task_environment_id(
            "turn",
            "task-environment-episode",
            environment.task_environment_id,
            episode.episode_id,
            context_package.package_hash,
        )
        message = _task_episode_user_message(
            environment=environment.to_dict(),
            episode=episode,
            context_package=context_package,
        )
        self.facade._commit_user_message(
            session_id=session_id,
            content=message,
            provider_protocol_content=message,
            turn_id=turn_id,
            message_id=stable_task_environment_id("user", "task-episode", episode.episode_id),
            source=self.authority,
        )
        lease_projection = service.acquire_episode_lease(
            task_environment_id=environment.task_environment_id,
            episode_id=episode.episode_id,
            lease_kind="task_episode_execution",
            holder_kind="harness_runtime",
            holder_id=f"task_episode:{episode.episode_id}",
            ttl_seconds=_task_episode_lease_ttl_seconds(context_package),
            idempotency_key=stable_task_environment_id("leasekey", "task-episode", episode.episode_id, context_package.package_hash),
            event_type="task_episode_execution_started",
            current_phase="task_episode",
            current_step="running",
            progress_label="task episode executing through harness",
        )
        runtime_contract = _task_episode_runtime_contract(
            environment=environment.to_dict(),
            episode=episode,
            context_package=context_package,
            agent_profile_id=agent_profile_id,
            agent_id=agent_id,
            turn_id=turn_id,
        )
        environment_binding = _task_episode_environment_binding(environment.to_dict(), context_package=context_package)
        model_selection = _task_episode_model_selection(context_package)
        workspace_root = _task_episode_workspace_root(environment.to_dict(), context_package=context_package)
        permission_mode = _permission_mode(self.facade.single_agent_runtime_host)
        runtime_assembly = assemble_runtime(
            backend_dir=self.base_dir,
            session_id=session_id,
            turn_id=turn_id,
            agent_invocation_id=f"aginvoke:{turn_id}:task_episode",
            runtime_contract=runtime_contract,
            model_selection=model_selection,
            environment_binding=environment_binding,
            agent_runtime_profile=agent_runtime_profile,
            tool_instances=self.facade._all_tool_instances(),
            definitions_by_name=dict(self.facade.single_agent_runtime_host.tool_authorization_index.definitions_by_name or {}),
            permission_mode=permission_mode,
            workspace_root=workspace_root,
        )
        self.facade._record_turn_environment_snapshot(
            session_id=session_id,
            turn_id=turn_id,
            runtime_assembly=runtime_assembly,
            execution_scope={
                "execution_scope_kind": "task_environment_episode",
                "task_environment_id": environment.task_environment_id,
                "task_instance_id": episode.task_instance_id,
                "episode_id": episode.episode_id,
                "context_package_id": context_package.package_id,
                "authority": f"{self.authority}.execution_scope",
            },
        )
        session_context = _task_episode_session_context(
            environment=environment.to_dict(),
            episode=episode,
            context_package=context_package,
            runtime_contract=runtime_contract,
            workspace_root=workspace_root,
        )
        events: list[dict[str, Any]] = []
        done_event: dict[str, Any] = {}
        terminal_event: dict[str, Any] = {}
        error_payload: dict[str, Any] = {}
        executor_result: dict[str, Any] = {}
        reduction_payload: dict[str, Any] = {}
        release_payload: dict[str, Any] = {}
        try:
            try:
                async for event in self.facade._run_single_agent_turn(
                    request=HarnessRuntimeRequest(
                        session_id=session_id,
                        message=message,
                        runtime_profile={
                            "agent_id": agent_id,
                            "agent_profile_id": agent_profile_id,
                            "task_environment_episode": True,
                        },
                        environment_binding=environment_binding,
                        runtime_contract=runtime_contract,
                        model_selection=model_selection,
                        permission_mode=permission_mode,
                    ),
                    turn_id=turn_id,
                    history=[],
                    session_context=session_context,
                    agent_invocation_id=f"aginvoke:{turn_id}:task_episode",
                    agent_runtime_profile=agent_runtime_profile,
                    runtime_assembly=runtime_assembly,
                    runtime_branch={
                        "branch_kind": "single_agent_turn",
                        "invocation_kind": "task_environment_episode",
                        "branch_id": stable_task_environment_id("branch", episode.episode_id, turn_id),
                        "task_environment_id": environment.task_environment_id,
                        "episode_id": episode.episode_id,
                        "authority": self.authority,
                    },
                    active_work_context=None,
                    current_work_boundary_receipt=_task_episode_current_work_boundary_receipt(
                        environment.to_dict(),
                        episode=episode,
                        turn_id=turn_id,
                    ),
                    max_steps=max_steps,
                ):
                    compact_event = _compact_harness_event(event)
                    if compact_event:
                        events.append(compact_event)
                    event_type = str(dict(event or {}).get("type") or "").strip()
                    if event_type == "done":
                        done_event = dict(event or {})
                    elif event_type == "agent_turn_terminal":
                        terminal_event = dict(event or {})
                    elif event_type == "error":
                        error_payload = dict(event or {})
                executor_result = _task_episode_executor_result_from_events(
                    environment=environment.to_dict(),
                    episode=episode,
                    context_package=context_package,
                    session_id=session_id,
                    turn_id=turn_id,
                    agent_id=agent_id,
                    agent_profile_id=agent_profile_id,
                    done_event=done_event,
                    terminal_event=terminal_event,
                    error_payload=error_payload,
                    events=tuple(events),
                    runtime_contract=runtime_contract,
                    model_selection=model_selection,
                )
            except Exception as exc:
                executor_result = _task_episode_exception_executor_result(
                    environment=environment.to_dict(),
                    episode=episode,
                    context_package=context_package,
                    session_id=session_id,
                    turn_id=turn_id,
                    agent_id=agent_id,
                    agent_profile_id=agent_profile_id,
                    exc=exc,
                    events=tuple(events),
                )
            reduction = _record_task_episode_execution_result(
                base_dir=self.base_dir,
                environment=environment.to_dict(),
                episode=episode,
                context_package=context_package,
                executor_result=executor_result,
            )
            reduction_payload = reduction.to_dict()
            release_payload = dict(reduction_payload.get("lease_release") or {})
        finally:
            if not release_payload:
                try:
                    release_projection = service.release_episode_lease(
                        task_environment_id=environment.task_environment_id,
                        lease_id=lease_projection.lease.lease_id,
                        release_reason="task_episode_execution_finished",
                        event_type="task_episode_execution_finished",
                        current_phase="task_episode",
                        current_step="lease_released",
                        progress_label="task episode execution lease released",
                    )
                    release_payload = release_projection.to_dict()
                except Exception as exc:
                    release_payload = {
                        "authority": f"{self.authority}.lease_release_error",
                        "error": str(exc) or exc.__class__.__name__,
                        "error_type": exc.__class__.__name__,
                        "lease_id": lease_projection.lease.lease_id,
                    }
        task_environment_view = TaskEnvironmentViewService(self.base_dir).task_environment_detail(environment.task_environment_id)
        return {
            "ok": bool(executor_result.get("ok") is True),
            "status": str(executor_result.get("status") or ""),
            "executor_result": executor_result,
            "reduction": reduction_payload,
            "task_environment_view": task_environment_view,
            "lease": lease_projection.to_dict(),
            "lease_release": release_payload,
            "authority": self.authority,
        }

    def _resolve_agent_profile(self, episode: AgentExecutionEpisode) -> dict[str, Any]:
        profile_ref = str(episode.agent_profile_id or "").strip()
        if not profile_ref:
            return {
                "ok": False,
                "reason": "task_episode_agent_profile_missing",
                "diagnostics": {
                    "required_source": "AgentExecutionEpisode.agent_profile_id",
                    "authority": f"{self.authority}.agent_profile_resolution",
                },
            }
        profile = self.facade.agent_runtime_registry.get_profile_by_profile_id(profile_ref)
        if profile is None:
            return {
                "ok": False,
                "reason": "task_episode_agent_profile_not_registered",
                "agent_profile_id": profile_ref,
                "diagnostics": {
                    "authority": f"{self.authority}.agent_profile_resolution",
                },
            }
        return {
            "ok": True,
            "profile": profile,
            "agent_profile_id": profile_ref,
            "agent_id": str(episode.agent_id or getattr(profile, "agent_id", "") or "").strip(),
            "authority": f"{self.authority}.agent_profile_resolution",
        }

    def _ensure_execution_session(
        self,
        *,
        session_id: str,
        environment: dict[str, Any],
        episode: AgentExecutionEpisode,
        context_package: TaskContextPackage,
    ) -> None:
        try:
            self.facade.session_manager.load_session_record(session_id)
            return
        except Exception:
            pass
        self.facade.session_manager.create_session(
            session_id=session_id,
            title=_task_episode_session_title(environment, episode=episode, context_package=context_package),
            scope={
                "task_environment_id": str(environment.get("task_environment_id") or ""),
                "task_instance_id": str(environment.get("task_instance_id") or ""),
                "episode_id": episode.episode_id,
                "scope_kind": "task_environment_episode",
            },
        )


def _task_episode_for_execution(
    *,
    episode_repository: EpisodeRepository,
    task_environment_id: str,
    episode_id: str = "",
) -> AgentExecutionEpisode:
    target = str(episode_id or "").strip()
    if target:
        episode = episode_repository.get_episode(target)
        if episode is None:
            raise KeyError(f"AgentExecutionEpisode not found: {target}")
        return episode
    candidates = episode_repository.list_episodes(task_environment_id, limit=20)
    for episode in candidates:
        if episode.status in {"scheduled", "interrupted", "waiting_user", "waiting_tool"}:
            return episode
    if candidates:
        return candidates[0]
    raise KeyError(f"No AgentExecutionEpisode found for task environment: {task_environment_id}")


def _task_episode_context_package(
    *,
    repository: TaskEnvironmentRepository,
    environment: Any,
    episode: AgentExecutionEpisode,
) -> TaskContextPackage:
    environment_payload = environment.to_dict() if hasattr(environment, "to_dict") else dict(environment or {})
    package_id = _first_non_empty_string(
        episode.input_context_package_id,
        environment_payload.get("latest_context_package_id"),
    )
    if not package_id:
        raise KeyError(f"TaskContextPackage missing for episode: {episode.episode_id}")
    package = repository.get_context_package(package_id)
    if package is None:
        raise KeyError(f"TaskContextPackage not found: {package_id}")
    if package.task_environment_id != episode.task_environment_id:
        raise ValueError("TaskContextPackage task_environment_id does not match episode")
    if package.episode_id != episode.episode_id:
        raise ValueError("TaskContextPackage episode_id does not match episode")
    return package


def _task_episode_session_id(
    environment: dict[str, Any],
    *,
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
) -> str:
    packet_policy = dict(context_package.packet_policy or {})
    scope = dict(context_package.scope or {})
    return _first_non_empty_string(
        packet_policy.get("session_id"),
        scope.get("session_id"),
        dict(environment.get("metadata") or {}).get("session_id"),
        stable_task_environment_id("tsess", environment.get("task_environment_id"), episode.episode_id),
    )


def _task_episode_session_title(
    environment: dict[str, Any],
    *,
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
) -> str:
    scope = dict(context_package.scope or {})
    task_title = str(scope.get("task_title") or scope.get("title") or "").strip()
    return f"Task episode: {task_title or environment.get('task_environment_id') or episode.episode_id}"


def _task_episode_environment_binding(
    environment: dict[str, Any],
    *,
    context_package: TaskContextPackage,
) -> dict[str, Any]:
    task_environment_id = _first_non_empty_string(
        context_package.task_environment_id,
        environment.get("task_environment_id"),
    )
    return _drop_empty(
        {
            "task_environment_id": task_environment_id,
            "environment_id": task_environment_id,
            "source": "task_environment_episode",
            "authority": "harness.task_environment_episode_bridge.environment_binding",
        }
    )


def _task_episode_runtime_contract(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    agent_profile_id: str,
    agent_id: str,
    turn_id: str,
) -> dict[str, Any]:
    runtime_policy = dict(dict(context_package.packet_policy or {}).get("runtime_policy") or {})
    runtime_policy["task_lifecycle_policy"] = {
        **dict(runtime_policy.get("task_lifecycle_policy") or {}),
        "request_task_run": False,
    }
    runtime_policy["context_policy"] = {
        **dict(runtime_policy.get("context_policy") or {}),
        "active_work_context": "disabled",
        "history_scope": "task_context_package",
    }
    return _drop_empty(
        {
            "turn_id": turn_id,
            "task_environment_id": context_package.task_environment_id,
            "runtime_profile": {
                "agent_id": agent_id,
                "agent_profile_id": agent_profile_id,
                "runtime_policy": runtime_policy,
                "control_capabilities": {
                    "may_request_task_run": False,
                    "may_control_active_work": False,
                    "requires_json_action_protocol": False,
                },
            },
            "control_capabilities": {
                "may_request_task_run": False,
                "may_control_active_work": False,
                "requires_json_action_protocol": False,
            },
            "task_environment_episode_execution": {
                "task_environment_id": context_package.task_environment_id,
                "task_instance_id": episode.task_instance_id,
                "episode_id": episode.episode_id,
                "context_package_id": context_package.package_id,
                "task_environment_owner": "task_system",
                "authority": "harness.task_environment_episode_bridge.runtime_contract",
            },
            "authority": "harness.task_environment_episode_bridge.runtime_contract",
        }
    )


def _task_episode_model_selection(context_package: TaskContextPackage) -> dict[str, Any]:
    packet_policy = dict(context_package.packet_policy or {})
    model_requirement = dict(packet_policy.get("model_selection") or packet_policy.get("model_requirement") or {})
    allowed = {
        "provider",
        "provider_family",
        "model",
        "model_family",
        "credential_ref",
        "max_output_tokens",
        "preferred_output_tokens",
        "min_output_tokens",
        "action_max_output_tokens",
        "action_timeout_seconds",
        "action_long_output_timeout_seconds",
        "action_thinking_mode",
        "action_reasoning_effort",
        "timeout_seconds",
        "long_output_timeout_seconds",
        "max_retries",
        "temperature",
        "thinking_mode",
        "reasoning_effort",
        "stream_policy",
        "response_format",
        "structured_output",
        "streaming_required",
        "fallback_allowed",
    }
    return {
        key: value
        for key, value in model_requirement.items()
        if str(key or "").strip() in allowed and value not in ("", None, [], {})
    }


def _task_episode_workspace_root(
    environment: dict[str, Any],
    *,
    context_package: TaskContextPackage,
) -> str:
    scope = dict(context_package.scope or {})
    resources = dict(context_package.resource_handles or {})
    metadata = dict(environment.get("metadata") or {})
    project_binding = dict(metadata.get("project_binding") or {})
    return _first_non_empty_string(
        resources.get("workspace_root"),
        scope.get("workspace_root"),
        scope.get("project_root"),
        project_binding.get("workspace_root"),
    )


def _task_episode_session_context(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    runtime_contract: dict[str, Any],
    workspace_root: str,
) -> dict[str, Any]:
    return _drop_empty(
        {
            "compressed_context": "",
            "provider_protocol_timeline": [],
            "compaction_generation": "0",
            "task_context_package": context_package.to_dict(),
            "task_execution_episode": episode.to_dict(),
            "task_work_environment": dict(environment or {}),
            "task_episode_execution_boundary": {
                "task_environment_owner": "task_system",
                "forbidden_actions": [
                    "rewrite_task_goal",
                    "bypass_acceptance_contract",
                    "control_parent_active_work",
                    "create_unrequested_task_run",
                ],
                "authority": "harness.task_environment_episode_bridge.execution_boundary",
            },
            "runtime_contract": runtime_contract,
            "project_binding": (
                {
                    "workspace_root": workspace_root,
                    "authority": "harness.task_environment_episode_bridge.project_binding",
                }
                if workspace_root
                else {}
            ),
        }
    )


def _task_episode_current_work_boundary_receipt(
    environment: dict[str, Any],
    *,
    episode: AgentExecutionEpisode,
    turn_id: str,
) -> dict[str, Any]:
    return {
        "receipt_id": stable_task_environment_id("cwreceipt", "task-episode", environment.get("task_environment_id"), episode.episode_id, turn_id),
        "decision": "isolated_task_environment_episode_execution",
        "active_work_control_available": False,
        "reason": "task episode workers cannot control parent active work; TaskSystem owns task environment state",
        "authority": "harness.task_environment_episode_bridge.current_work_boundary",
    }


def _task_episode_user_message(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
) -> str:
    role_contract = str(context_package.role_contract or "").strip()
    goal = str(context_package.goal or "").strip()
    payload = {
        "task_identity": {
            "task_environment_id": context_package.task_environment_id,
            "task_instance_id": episode.task_instance_id,
            "episode_id": episode.episode_id,
            "environment_kind": str(environment.get("environment_kind") or ""),
        },
        "scope": dict(context_package.scope or {}),
        "acceptance": dict(context_package.acceptance or {}),
        "resource_handles": dict(context_package.resource_handles or {}),
        "project_network_handles": dict(context_package.project_network_handles or {}),
        "graph_context": dict(context_package.graph_context or {}),
        "task_state_context": dict(context_package.task_state_context or {}),
        "output_contract": dict(context_package.output_contract or {}),
        "continuation_hint": str(context_package.continuation_hint or episode.continuation_hint or ""),
        "tool_authority": {
            "source": "agent_runtime_profile",
            "agent_profile_id": episode.agent_profile_id,
            "rule": "任务环境不授予工具；只能使用运行时已经展示给当前 agent profile 的工具。",
        },
    }
    return (
        "你是一名任务环境执行员。\n"
        "你只负责完成本次分派给你的工作：推进目标、整理证据、产出可归并结果，或在信息不足时给出清楚的阻塞说明。\n"
        "你不能改写任务目标，不能绕过验收边界，不能控制父级当前工作，也不能自行启动新任务。\n"
        "你只能使用运行时已经展示给你的工具；如果没有相关工具，就只基于输入上下文完成判断和交付。\n"
        "如果输入足够，请直接交付结果；如果输入不足，请说明缺少什么、为什么阻塞、下一步应由谁补充。\n\n"
        f"你的职责契约：\n{role_contract or '依据任务环境上下文推进本次 episode，并输出清晰、可归并的结果。'}\n\n"
        f"当前目标：\n{goal or '推进当前任务环境。'}\n\n"
        "你收到的任务输入、资源和输出契约如下：\n"
        f"```json\n{_json_for_prompt(payload, limit=30000)}\n```"
    )


def _task_episode_lease_ttl_seconds(context_package: TaskContextPackage) -> float:
    policy = dict(context_package.packet_policy or {})
    for key in ("lease_ttl_seconds", "ttl_seconds", "timeout_seconds", "max_runtime_seconds"):
        try:
            value = float(policy.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return max(1.0, value)
    return 2 * 60 * 60


def _task_episode_executor_result_from_events(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    session_id: str,
    turn_id: str,
    agent_id: str,
    agent_profile_id: str,
    done_event: dict[str, Any],
    terminal_event: dict[str, Any],
    error_payload: dict[str, Any],
    events: tuple[dict[str, Any], ...],
    runtime_contract: dict[str, Any],
    model_selection: dict[str, Any],
) -> dict[str, Any]:
    terminal_reason = _first_non_empty_string(
        done_event.get("terminal_reason"),
        dict(dict(terminal_event.get("event") or {}).get("payload") or {}).get("terminal_reason"),
        error_payload.get("code"),
        "completed" if done_event else "task_episode_harness_no_terminal_event",
    )
    final_answer = str(done_event.get("content") or error_payload.get("content") or error_payload.get("error") or "").strip()
    answer_channel = str(done_event.get("answer_channel") or "").strip()
    done_status = str(done_event.get("status") or "").strip()
    blocked = bool(answer_channel in {"blocked", "ask_user"} or terminal_reason in {"blocked", "ask_user"})
    failed = bool(error_payload or (done_event and done_status == "failed") or not done_event)
    status = "completed" if done_event and not blocked and not failed else ("blocked" if blocked or done_event else "failed")
    final_action_diagnostics = _final_action_diagnostics_from_done_event(done_event)
    structured_output = _structured_output_from_final_action_diagnostics(final_action_diagnostics)
    turn_run_id = _first_event_value(events, "turn_run_id")
    return {
        "ok": status == "completed",
        "status": status,
        "error": "" if status == "completed" else terminal_reason,
        "final_answer": final_answer,
        "structured_output": structured_output,
        "artifact_refs": list(structured_output.get("artifact_refs") or []) if isinstance(structured_output, dict) else [],
        "task_environment_id": context_package.task_environment_id,
        "episode_id": episode.episode_id,
        "session_id": session_id,
        "event": {"turn_id": turn_id, "turn_run_id": turn_run_id, "terminal_reason": terminal_reason},
        "diagnostics": {
            "origin_kind": "task_environment_episode",
            "task_environment_id": context_package.task_environment_id,
            "task_instance_id": episode.task_instance_id,
            "episode_id": episode.episode_id,
            "context_package_id": context_package.package_id,
            "turn_id": turn_id,
            "turn_run_id": turn_run_id,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "environment_kind": str(environment.get("environment_kind") or ""),
            "final_action_diagnostics": final_action_diagnostics,
            "event_count": len(events),
            "harness_events": [dict(item) for item in events[:40]],
            "runtime_contract": {
                "control_capabilities": dict(runtime_contract.get("control_capabilities") or {}),
                "task_environment_episode_execution": dict(runtime_contract.get("task_environment_episode_execution") or {}),
                "tool_authority": "agent_runtime_profile_runtime_assembly",
            },
            "model_selection": dict(model_selection or {}),
            "authority": "harness.task_environment_episode_bridge.executor_result",
        },
        "authority": "harness.task_environment_episode_bridge",
    }


def _task_episode_exception_executor_result(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    session_id: str,
    turn_id: str,
    agent_id: str,
    agent_profile_id: str,
    exc: Exception,
    events: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    reason = str(exc) or exc.__class__.__name__
    return {
        "ok": False,
        "status": "failed",
        "error": reason,
        "final_answer": "",
        "structured_output": {},
        "artifact_refs": [],
        "task_environment_id": context_package.task_environment_id,
        "episode_id": episode.episode_id,
        "session_id": session_id,
        "event": {"turn_id": turn_id, "terminal_reason": "task_episode_harness_exception"},
        "diagnostics": {
            "origin_kind": "task_environment_episode",
            "task_environment_id": context_package.task_environment_id,
            "task_instance_id": episode.task_instance_id,
            "episode_id": episode.episode_id,
            "context_package_id": context_package.package_id,
            "turn_id": turn_id,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "environment_kind": str(environment.get("environment_kind") or ""),
            "event_count": len(events),
            "harness_events": [dict(item) for item in events[:40]],
            "exception": {"type": exc.__class__.__name__, "message": reason},
            "authority": "harness.task_environment_episode_bridge.executor_exception",
        },
        "authority": "harness.task_environment_episode_bridge",
    }


def _task_episode_executor_blocked_result(
    *,
    reason: str,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "error": str(reason or "task_episode_executor_blocked"),
        "final_answer": "",
        "structured_output": {},
        "artifact_refs": [],
        "task_environment_id": context_package.task_environment_id,
        "episode_id": episode.episode_id,
        "session_id": "",
        "event": {"terminal_reason": str(reason or "task_episode_executor_blocked")},
        "diagnostics": {
            "origin_kind": "task_environment_episode",
            "task_environment_id": context_package.task_environment_id,
            "task_instance_id": episode.task_instance_id,
            "episode_id": episode.episode_id,
            "context_package_id": context_package.package_id,
            "environment_kind": str(environment.get("environment_kind") or ""),
            "recoverable_error": {
                "retryable": True,
                "error_code": str(reason or "task_episode_executor_blocked"),
            },
            **dict(diagnostics or {}),
            "authority": "harness.task_environment_episode_bridge.blocked_result",
        },
        "authority": "harness.task_environment_episode_bridge",
    }


def _record_task_episode_execution_result(
    *,
    base_dir: Path,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    executor_result: dict[str, Any],
) -> Any:
    status = str(executor_result.get("status") or "failed")
    final_answer = str(executor_result.get("final_answer") or "").strip()
    terminal_reason = str(dict(executor_result.get("event") or {}).get("terminal_reason") or executor_result.get("error") or status)
    structured_output = dict(executor_result.get("structured_output") or {})
    summary = _first_non_empty_string(
        structured_output.get("summary"),
        structured_output.get("handoff_summary"),
        final_answer[:4000],
        terminal_reason,
    )
    episode_result_status = "completed" if status == "completed" else ("blocked" if status == "blocked" else "failed")
    work_products = _task_episode_work_products(
        environment=environment,
        episode=episode,
        context_package=context_package,
        executor_result=executor_result,
        summary=summary,
    )
    result = EpisodeResult(
        result_id=stable_task_environment_id("epresult", episode.task_environment_id, episode.episode_id, status, context_package.package_hash),
        episode_id=episode.episode_id,
        task_environment_id=episode.task_environment_id,
        status=episode_result_status,  # type: ignore[arg-type]
        summary=summary if episode_result_status == "completed" else "",
        state_update_proposals=tuple(dict(item) for item in list(structured_output.get("state_update_proposals") or []) if isinstance(item, dict)),
        plan_patch=dict(structured_output.get("plan_patch") or {}),
        todo_patch=dict(structured_output.get("todo_patch") or {}),
        memory_candidates=tuple(dict(item) for item in list(structured_output.get("memory_candidates") or []) if isinstance(item, dict)),
        artifact_refs=tuple(str(item) for item in list(executor_result.get("artifact_refs") or structured_output.get("artifact_refs") or []) if str(item)),
        evidence_refs=tuple(str(item) for item in list(structured_output.get("evidence_refs") or []) if str(item)),
        blocker=terminal_reason if episode_result_status == "blocked" else "",
        continuation_hint=str(structured_output.get("continuation_hint") or ""),
        output_contract_version=str(dict(context_package.output_contract or {}).get("version") or ""),
        diagnostics={
            "executor_result": _public_task_episode_executor_projection(executor_result),
            "structured_output": structured_output,
            "context_package_id": context_package.package_id,
            "authority": "harness.task_environment_episode_bridge.episode_result",
        },
    )
    event = TaskEvent(
        event_id=stable_task_environment_id("taskevent", episode.task_environment_id, "task_episode_result_recorded", result.result_id),
        task_environment_id=episode.task_environment_id,
        task_instance_id=episode.task_instance_id,
        event_seq=0,
        event_type="task_episode_result_recorded",
        actor_kind="system",
        source_episode_id=episode.episode_id,
        idempotency_key=f"task-episode-result:{result.result_id}",
        payload={
            "episode_result_id": result.result_id,
            "episode_result_status": result.status,
            "executor_status": status,
            "work_product_ids": [item.work_product_id for item in work_products],
        },
        refs={
            "task_environment_ref": episode.task_environment_id,
            "episode_ref": episode.episode_id,
            "context_package_ref": context_package.package_id,
        },
    )
    snapshot_patch = _task_episode_result_snapshot_patch(
        status=status,
        summary=summary,
        terminal_reason=terminal_reason,
        work_products=work_products,
    )
    return TaskReducer(base_dir).reduce_episode_result(
        episode=episode,
        episode_status="completed" if status == "completed" else ("interrupted" if status == "blocked" else "failed"),
        terminal_reason=terminal_reason,
        episode_result=result,
        work_product_candidates=tuple(work_products),
        event=event,
        snapshot_patch=snapshot_patch,
        episode_diagnostics_patch={
            "executor_status": status,
            "executor_authority": str(executor_result.get("authority") or ""),
        },
        release_reason="task_episode_execution_finished",
        release_event_type="task_episode_execution_finished",
        release_current_phase="task_episode",
        release_current_step="lease_released",
        release_progress_label="task episode execution lease released",
    )


def _record_task_episode_preflight_blocked(
    *,
    base_dir: Path,
    repository: TaskEnvironmentRepository,
    episode_repository: EpisodeRepository,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    executor_result: dict[str, Any],
) -> dict[str, Any]:
    reason = str(executor_result.get("error") or dict(executor_result.get("event") or {}).get("terminal_reason") or "task_episode_preflight_blocked")
    now = time.time()
    stored_episode = episode_repository.upsert_episode(
        replace(
            episode,
            status="interrupted",
            terminal_reason=reason,
            ended_at=now,
            diagnostics={
                **dict(episode.diagnostics or {}),
                "preflight_blocked": True,
                "executor_result": _public_task_episode_executor_projection(executor_result),
                "source_authority": "harness.task_environment_episode_bridge.preflight",
            },
        )
    )
    event = repository.append_event(
        TaskEvent(
            event_id=stable_task_environment_id("taskevent", episode.task_environment_id, "task_episode_preflight_blocked", episode.episode_id, reason),
            task_environment_id=episode.task_environment_id,
            task_instance_id=episode.task_instance_id,
            event_seq=0,
            event_type="task_episode_preflight_blocked",
            actor_kind="system",
            source_episode_id=episode.episode_id,
            idempotency_key=f"task-episode-preflight-blocked:{episode.episode_id}:{reason}",
            payload={
                "episode_id": episode.episode_id,
                "reason": reason,
                "executor_result": _public_task_episode_executor_projection(executor_result),
            },
            refs={
                "task_environment_ref": episode.task_environment_id,
                "episode_ref": episode.episode_id,
            },
            created_at=now,
        ),
        snapshot_patch={
            "status": "blocked",
            "current_phase": "task_episode",
            "current_step": "preflight_blocked",
            "progress_label": reason[:240],
            "blocked_reason": reason[:1200],
            "recovery_action": "prepare_task_episode",
        },
    )
    return {
        "authority": "harness.task_environment_episode_bridge.preflight_blocked",
        "episode": stored_episode.to_dict(),
        "event": event.to_dict(),
        "task_environment_id": str(environment.get("task_environment_id") or episode.task_environment_id),
    }


def _task_episode_work_products(
    *,
    environment: dict[str, Any],
    episode: AgentExecutionEpisode,
    context_package: TaskContextPackage,
    executor_result: dict[str, Any],
    summary: str,
) -> tuple[WorkProduct, ...]:
    if str(executor_result.get("status") or "") != "completed":
        return ()
    final_answer = str(executor_result.get("final_answer") or "").strip()
    structured_output = dict(executor_result.get("structured_output") or {})
    artifact_refs = tuple(str(item) for item in list(executor_result.get("artifact_refs") or []) if str(item))
    if not structured_output and not artifact_refs:
        return ()
    output_contract = dict(context_package.output_contract or {})
    product_kind = str(output_contract.get("product_kind") or output_contract.get("kind") or "episode_output").strip()
    return (
        WorkProduct(
            work_product_id=stable_task_environment_id("workproduct", episode.task_environment_id, episode.episode_id, context_package.package_hash),
            task_environment_id=episode.task_environment_id,
            task_instance_id=episode.task_instance_id,
            source_episode_id=episode.episode_id,
            product_domain=str(output_contract.get("product_domain") or "task_episode"),
            product_kind=product_kind,
            confidence="derived",
            status="candidate",
            stable_ref=f"{episode.task_environment_id}:{episode.episode_id}:{product_kind}",
            payload={
                "summary": summary,
                "structured_output": structured_output,
                **({"final_answer_receipt": final_answer} if final_answer else {}),
                "context_package_id": context_package.package_id,
            },
            artifact_refs=artifact_refs,
            evidence_refs=tuple(str(item) for item in list(structured_output.get("evidence_refs") or []) if str(item)),
            downstream_refs={
                "task_environment_id": episode.task_environment_id,
                "episode_id": episode.episode_id,
            },
            metadata={
                "source_authority": "harness.task_environment_episode_bridge",
                "environment_kind": str(environment.get("environment_kind") or ""),
            },
        ),
    )


def _task_episode_result_snapshot_patch(
    *,
    status: str,
    summary: str,
    terminal_reason: str,
    work_products: tuple[WorkProduct, ...],
) -> dict[str, Any]:
    if status == "completed":
        return _drop_empty(
            {
                "status": "ready",
                "current_phase": "task_episode",
                "current_step": "episode_completed",
                "progress_label": summary[:240],
                "blocked_reason": "",
                "continuation_hint": "Episode completed; prepare another episode if the task still needs work.",
                "latest_work_product_id": work_products[0].work_product_id if work_products else "",
            }
        )
    if status == "blocked":
        return {
            "status": "blocked",
            "current_phase": "task_episode",
            "current_step": "episode_blocked",
            "progress_label": summary[:240] or terminal_reason[:240],
            "blocked_reason": terminal_reason[:1200],
            "recovery_action": "prepare_task_episode",
        }
    return {
        "status": "failed",
        "current_phase": "task_episode",
        "current_step": "episode_failed",
        "progress_label": summary[:240] or terminal_reason[:240],
        "blocked_reason": terminal_reason[:1200],
        "recovery_action": "inspect_task_episode_failure",
    }


def _public_task_episode_executor_projection(executor_result: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(executor_result.get("diagnostics") or {})
    return {
        "ok": bool(executor_result.get("ok") is True),
        "status": str(executor_result.get("status") or ""),
        "authority": str(executor_result.get("authority") or ""),
        "event": dict(executor_result.get("event") or {}),
        "diagnostics": {
            "origin_kind": str(diagnostics.get("origin_kind") or ""),
            "turn_id": str(diagnostics.get("turn_id") or ""),
            "turn_run_id": str(diagnostics.get("turn_run_id") or ""),
            "agent_profile_id": str(diagnostics.get("agent_profile_id") or ""),
            "context_package_id": str(diagnostics.get("context_package_id") or ""),
        },
    }


def _permission_mode(runtime_host: Any | None) -> str:
    provider = getattr(runtime_host, "_current_permission_mode", None)
    if callable(provider):
        return normalize_permission_mode(str(provider() or "full_access"))
    return "full_access"


def _compact_harness_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event or {})
    event_type = str(payload.get("type") or "").strip()
    if not event_type:
        return {}
    if event_type == "done":
        final_action_diagnostics = dict(payload.get("final_action_diagnostics") or {}) if isinstance(payload.get("final_action_diagnostics"), dict) else {}
        return {
            "type": "done",
            "status": str(payload.get("status") or ""),
            "terminal_reason": str(payload.get("terminal_reason") or ""),
            "answer_channel": str(payload.get("answer_channel") or ""),
            "answer_source": str(payload.get("answer_source") or ""),
            "content_chars": len(str(payload.get("content") or "")),
            "final_action_diagnostic_keys": sorted(str(key) for key in final_action_diagnostics.keys()),
        }
    if event_type == "error":
        return {
            "type": "error",
            "code": str(payload.get("code") or ""),
            "content": str(payload.get("content") or payload.get("error") or "")[:500],
        }
    if event_type == "agent_turn_terminal":
        raw_event = dict(payload.get("event") or {})
        terminal_payload = dict(raw_event.get("payload") or {})
        return {
            "type": "agent_turn_terminal",
            "event_id": str(raw_event.get("event_id") or ""),
            "turn_run_id": str(raw_event.get("run_id") or raw_event.get("stream_id") or ""),
            "status": str(terminal_payload.get("status") or ""),
            "terminal_reason": str(terminal_payload.get("terminal_reason") or ""),
        }
    if event_type == "harness_run_started":
        turn_run = dict(payload.get("turn_run") or {})
        return {
            "type": "harness_run_started",
            "turn_run_id": str(turn_run.get("turn_run_id") or ""),
            "status": str(turn_run.get("status") or ""),
        }
    if event_type == "turn_runtime_control_signal_observed":
        raw_event = dict(payload.get("event") or {})
        signal = dict(dict(raw_event.get("payload") or {}).get("runtime_control_signal") or {})
        return {
            "type": "turn_runtime_control_signal_observed",
            "signal_kind": str(signal.get("signal_kind") or ""),
            "runtime_control_state": str(signal.get("runtime_control_state") or ""),
            "used_tool_iterations": signal.get("used_tool_iterations"),
            "max_tool_iterations": signal.get("max_tool_iterations"),
            "runtime_control_signal_ref": str(signal.get("runtime_control_signal_ref") or ""),
        }
    if event_type in {
        "single_agent_turn_started",
        "runtime_branch_decided",
        "tool_batch_planned",
        "tool_batch_group_completed",
        "tool_observation",
        "model_action_admission",
    }:
        return {"type": event_type}
    return {}


def _final_action_diagnostics_from_done_event(done_event: dict[str, Any]) -> dict[str, Any]:
    value = dict(done_event or {}).get("final_action_diagnostics")
    if not isinstance(value, dict):
        return {}
    payload = {
        str(key): item
        for key, item in dict(value or {}).items()
        if str(key).strip() and item not in ("", [], {}, None)
    }
    structured_output = payload.get("structured_output")
    node_output = payload.get("node_output")
    if isinstance(structured_output, dict) and not isinstance(node_output, dict):
        payload["node_output"] = dict(structured_output)
    if isinstance(node_output, dict) and not isinstance(structured_output, dict):
        payload["structured_output"] = dict(node_output)
    return payload


def _structured_output_from_final_action_diagnostics(final_action_diagnostics: dict[str, Any]) -> dict[str, Any]:
    payload = dict(final_action_diagnostics or {})
    for key in ("structured_output", "node_output"):
        value = payload.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _first_event_value(events: tuple[dict[str, Any], ...], key: str) -> str:
    target = str(key or "").strip()
    for event in events:
        value = str(dict(event or {}).get(target) or "").strip()
        if value:
            return value
    return ""


def _json_for_prompt(payload: Any, *, limit: int) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    max_chars = max(1000, int(limit or 1000))
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>"


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in ("", None, [], {})}


def _first_non_empty_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
