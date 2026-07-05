from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.entrypoint.models import HarnessRuntimeRequest
from harness.runtime import assemble_runtime
from permissions.policy import normalize_permission_mode
from agent_system.groups.registry import AgentGroupRegistry
from task_system.work_environments.models import stable_task_environment_id


AUTHORIZED_INPUT_GLOBAL_CHAR_LIMIT = 70000
AUTHORIZED_INPUT_DEFAULT_ITEM_CHAR_LIMIT = 12000
AUTHORIZED_INPUT_MAX_ITEM_CHAR_LIMIT = 30000


class GraphNodeWorkOrderBridge:
    authority = "harness.graph_node_work_order_bridge"

    def __init__(self, facade: Any) -> None:
        self.facade = facade
        self.base_dir = Path(facade.base_dir)

    async def execute(
        self,
        *,
        graph_config: Any,
        work_order: Any,
        max_steps: int = 12,
    ) -> dict[str, Any]:
        raw_work_order_payload = _object_payload(work_order)
        agent_profile_resolution = self._resolve_agent_profile(raw_work_order_payload)
        if not agent_profile_resolution.get("ok"):
            return _graph_node_executor_blocked_result(
                reason=str(agent_profile_resolution.get("reason") or "graph_node_agent_profile_unresolved"),
                graph_config=graph_config,
                work_order_payload=raw_work_order_payload,
                preparation_payload={},
                diagnostics=dict(agent_profile_resolution.get("diagnostics") or {}),
            )
        agent_runtime_profile = agent_profile_resolution["profile"]
        agent_profile_id = str(agent_profile_resolution.get("agent_profile_id") or "").strip()
        agent_id = str(agent_profile_resolution.get("agent_id") or "").strip()
        work_order_payload = {
            **raw_work_order_payload,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
        }
        preparation_payload = self._task_preparation_payload(work_order_payload)
        context_package = dict(preparation_payload.get("context_package") or {})
        task_environment = dict(preparation_payload.get("task_environment") or {})
        episode = dict(preparation_payload.get("episode") or {})
        session_id = _graph_node_session_id(work_order_payload)
        if not session_id:
            return _graph_node_executor_blocked_result(
                reason="graph_node_session_id_missing",
                graph_config=graph_config,
                work_order_payload=work_order_payload,
                preparation_payload=preparation_payload,
                diagnostics={
                    "expected_source": "GraphNodeWorkOrder.node_session_id",
                    "node_session_policy": dict(work_order_payload.get("node_session_policy") or {}),
                },
            )
        turn_id = stable_task_environment_id(
            "turn",
            "graph-node-work-order",
            work_order_payload.get("graph_run_id"),
            work_order_payload.get("node_id"),
            work_order_payload.get("work_order_id"),
            context_package.get("package_hash"),
        )
        self._ensure_execution_session(
            session_id=session_id,
            graph_config=graph_config,
            work_order_payload=work_order_payload,
            task_environment=task_environment,
        )
        message = _graph_node_work_order_user_message(
            work_order_payload=work_order_payload,
            context_package=context_package,
            episode=episode,
            task_environment=task_environment,
        )
        self.facade._commit_user_message(
            session_id=session_id,
            content=message,
            provider_protocol_content=message,
            turn_id=turn_id,
            message_id=stable_task_environment_id("user", "graph-node-work-order", work_order_payload.get("work_order_id")),
            source=self.authority,
        )
        runtime_contract = _graph_node_runtime_contract(
            work_order_payload=work_order_payload,
            context_package=context_package,
            agent_profile_id=agent_profile_id,
            agent_id=agent_id,
            turn_id=turn_id,
        )
        environment_binding = _graph_node_environment_binding(work_order_payload, context_package=context_package)
        model_selection = _graph_node_model_selection(work_order_payload)
        workspace_root = _graph_node_workspace_root(work_order_payload, context_package=context_package)
        permission_mode = _permission_mode(self.facade.single_agent_runtime_host)
        runtime_assembly = assemble_runtime(
            backend_dir=self.base_dir,
            session_id=session_id,
            turn_id=turn_id,
            agent_invocation_id=f"aginvoke:{turn_id}:graph_node",
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
                "execution_scope_kind": "graph_node_work_order",
                "task_environment_id": str(task_environment.get("task_environment_id") or context_package.get("task_environment_id") or ""),
                "task_instance_id": str(task_environment.get("task_instance_id") or ""),
                "episode_id": str(episode.get("episode_id") or ""),
                "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
                "task_run_id": str(work_order_payload.get("task_run_id") or ""),
                "node_id": str(work_order_payload.get("node_id") or ""),
                "work_order_id": str(work_order_payload.get("work_order_id") or ""),
                "context_package_id": str(context_package.get("package_id") or ""),
                "authority": f"{self.authority}.execution_scope",
            },
        )
        session_context = _graph_node_session_context(
            work_order_payload=work_order_payload,
            context_package=context_package,
            episode=episode,
            task_environment=task_environment,
            runtime_contract=runtime_contract,
            workspace_root=workspace_root,
        )
        events: list[dict[str, Any]] = []
        done_event: dict[str, Any] = {}
        terminal_event: dict[str, Any] = {}
        error_payload: dict[str, Any] = {}
        async for event in self.facade._run_single_agent_turn(
            request=HarnessRuntimeRequest(
                session_id=session_id,
                message=message,
                runtime_profile={
                    "agent_id": agent_id,
                    "agent_profile_id": agent_profile_id,
                    "graph_node_work_order": True,
                },
                environment_binding=environment_binding,
                runtime_contract=runtime_contract,
                model_selection=model_selection,
                permission_mode=permission_mode,
            ),
            turn_id=turn_id,
            history=[],
            session_context=session_context,
            agent_invocation_id=f"aginvoke:{turn_id}:graph_node",
            agent_runtime_profile=agent_runtime_profile,
            runtime_assembly=runtime_assembly,
            runtime_branch={
                "branch_kind": "single_agent_turn",
                "invocation_kind": "graph_node_work_order",
                "branch_id": stable_task_environment_id("branch", work_order_payload.get("work_order_id"), turn_id),
                "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
                "node_id": str(work_order_payload.get("node_id") or ""),
                "work_order_id": str(work_order_payload.get("work_order_id") or ""),
                "authority": self.authority,
            },
            active_work_context=None,
            current_work_boundary_receipt=_graph_node_current_work_boundary_receipt(work_order_payload, turn_id=turn_id),
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
        return _graph_node_executor_result_from_events(
            graph_config=graph_config,
            work_order_payload=work_order_payload,
            preparation_payload=preparation_payload,
            session_id=session_id,
            turn_id=turn_id,
            agent_profile_id=agent_profile_id,
            agent_id=agent_id,
            done_event=done_event,
            terminal_event=terminal_event,
            error_payload=error_payload,
            events=tuple(events),
            runtime_contract=runtime_contract,
            model_selection=model_selection,
        )

    def _task_preparation_payload(self, work_order: Any) -> dict[str, Any]:
        sink = getattr(self.facade.agent_runtime_services, "graph_node_task_preparation_sink", None)
        prepare = getattr(sink, "prepare_work_order", None)
        if not callable(prepare):
            return {}
        return _object_payload(prepare(work_order))

    def _resolve_agent_profile(self, work_order_payload: dict[str, Any]) -> dict[str, Any]:
        profile_ref = _explicit_graph_node_agent_profile_id(work_order_payload)
        agent_id = _explicit_graph_node_agent_id(work_order_payload, profile=None)
        if not agent_id:
            agent_id = self._agent_id_from_graph_contract(work_order_payload)
        if not profile_ref and agent_id:
            profile = self.facade.agent_runtime_registry.get_profile(agent_id)
            if profile is None:
                return {
                    "ok": False,
                    "reason": "graph_node_agent_id_not_registered",
                    "agent_id": agent_id,
                    "diagnostics": {
                        "agent_binding": _graph_node_agent_binding(work_order_payload),
                        "authority": f"{self.authority}.agent_profile_resolution",
                    },
                }
            profile_ref = str(getattr(profile, "agent_profile_id", "") or "").strip()
        if not profile_ref:
            return {
                "ok": False,
                "reason": "graph_node_agent_profile_missing",
                "diagnostics": {
                    "required_sources": [
                        "GraphNodeWorkOrder.agent_profile_id",
                        "GraphNodeWorkOrder.agent_id",
                        "graph_slot.agent_binding.agent_profile_id",
                        "graph_slot.agent_binding.agent_id",
                        "graph_slot.agent_binding.agent_group_id",
                    ],
                    "agent_binding": _graph_node_agent_binding(work_order_payload),
                    "authority": f"{self.authority}.agent_profile_resolution",
                },
            }
        profile = self.facade.agent_runtime_registry.get_profile_by_profile_id(profile_ref)
        if profile is None:
            return {
                "ok": False,
                "reason": "graph_node_agent_profile_not_registered",
                "agent_profile_id": profile_ref,
                "diagnostics": {
                    "authority": f"{self.authority}.agent_profile_resolution",
                },
            }
        agent_id = _explicit_graph_node_agent_id(work_order_payload, profile=profile)
        if not agent_id:
            return {
                "ok": False,
                "reason": "graph_node_agent_id_missing",
                "agent_profile_id": profile_ref,
                "diagnostics": {
                    "required_sources": [
                        "GraphNodeWorkOrder.agent_id",
                        "graph_slot.agent_binding.agent_id",
                        "AgentRuntimeProfile.agent_id",
                    ],
                    "authority": f"{self.authority}.agent_profile_resolution",
                },
            }
        return {
            "ok": True,
            "profile": profile,
            "agent_profile_id": profile_ref,
            "agent_id": agent_id,
            "authority": f"{self.authority}.agent_profile_resolution",
        }

    def _agent_id_from_graph_contract(self, work_order_payload: dict[str, Any]) -> str:
        binding = _graph_node_agent_binding(work_order_payload)
        group_id = str(binding.get("agent_group_id") or "").strip()
        if not group_id:
            return ""
        group = AgentGroupRegistry(self.base_dir).get_group(group_id)
        if group is None:
            return ""
        selection_policy = str(binding.get("agent_selection_policy") or "").strip()
        members = [str(item).strip() for item in tuple(getattr(group, "member_agent_ids", ()) or ()) if str(item).strip()]
        coordinator = str(getattr(group, "coordinator_agent_id", "") or "").strip()
        if selection_policy.startswith("member:"):
            requested = selection_policy.split(":", 1)[1].strip()
            return requested if requested in members else ""
        if selection_policy in {"first_member", "member", "worker"} and members:
            return members[0]
        return coordinator or (members[0] if members else "")

    def _ensure_execution_session(
        self,
        *,
        session_id: str,
        graph_config: Any,
        work_order_payload: dict[str, Any],
        task_environment: dict[str, Any],
    ) -> None:
        try:
            self.facade.session_manager.load_session_record(session_id)
            return
        except Exception:
            pass
        runtime_scope = dict(dict(work_order_payload.get("input_package") or {}).get("runtime_scope") or {})
        project_id = str(runtime_scope.get("project_id") or getattr(graph_config, "graph_id", "") or "").strip()
        self.facade.session_manager.create_session(
            session_id=session_id,
            title=_graph_node_session_title(work_order_payload),
            scope={
                "workspace_view": "graph_node",
                "task_environment_id": str(task_environment.get("task_environment_id") or ""),
                "project_id": project_id,
            },
        )


def _explicit_graph_node_agent_profile_id(work_order_payload: dict[str, Any]) -> str:
    input_package = dict(work_order_payload.get("input_package") or {})
    input_binding = dict(input_package.get("agent_binding") or {})
    agent_binding = _graph_node_agent_binding(work_order_payload)
    return _first_non_empty_string(
        work_order_payload.get("agent_profile_id"),
        input_binding.get("agent_profile_id"),
        agent_binding.get("agent_profile_id"),
    )


def _explicit_graph_node_agent_id(work_order_payload: dict[str, Any], *, profile: Any | None) -> str:
    input_package = dict(work_order_payload.get("input_package") or {})
    input_binding = dict(input_package.get("agent_binding") or {})
    agent_binding = _graph_node_agent_binding(work_order_payload)
    return _first_non_empty_string(
        work_order_payload.get("agent_id"),
        input_binding.get("agent_id"),
        agent_binding.get("agent_id"),
        getattr(profile, "agent_id", ""),
    )


def _graph_node_agent_binding(work_order_payload: dict[str, Any]) -> dict[str, Any]:
    graph_slot = dict(work_order_payload.get("graph_slot") or {})
    binding = dict(graph_slot.get("agent_binding") or {})
    if binding:
        return binding
    return dict(dict(work_order_payload.get("input_package") or {}).get("agent_binding") or {})


def _graph_node_task_contract(work_order_payload: dict[str, Any]) -> dict[str, Any]:
    graph_slot = dict(work_order_payload.get("graph_slot") or {})
    contract = dict(graph_slot.get("task_contract") or {})
    if contract:
        return contract
    return dict(dict(work_order_payload.get("input_package") or {}).get("task_contract") or {})


def _graph_node_session_id(work_order_payload: dict[str, Any]) -> str:
    return str(work_order_payload.get("node_session_id") or "").strip()


def _graph_node_session_title(work_order_payload: dict[str, Any]) -> str:
    input_package = dict(work_order_payload.get("input_package") or {})
    node_identity = dict(input_package.get("node_identity") or {})
    title = str(node_identity.get("title") or "").strip()
    node_id = str(work_order_payload.get("node_id") or node_identity.get("node_id") or "").strip()
    return f"Graph node: {title or node_id or 'work order'}"


def _graph_node_environment_binding(
    work_order_payload: dict[str, Any],
    *,
    context_package: dict[str, Any],
) -> dict[str, Any]:
    input_package = dict(work_order_payload.get("input_package") or {})
    graph_context = dict(context_package.get("graph_context") or {})
    agent_binding = _graph_node_agent_binding(work_order_payload)
    environment_lock = dict(agent_binding.get("environment_lock") or {})
    environment_id = _static_runtime_environment_id(
        _first_non_empty_string(
        input_package.get("task_environment_id"),
        environment_lock.get("environment_id"),
        environment_lock.get("task_environment_id"),
        context_package.get("task_environment_ref"),
        graph_context.get("task_environment_id"),
        )
    )
    return _drop_empty(
        {
            "task_environment_id": environment_id,
            "environment_id": environment_id,
            "source": "graph_node_work_order",
            "authority": "harness.graph_node_work_order_bridge.environment_binding",
        }
    )


def _graph_node_model_selection(work_order_payload: dict[str, Any]) -> dict[str, Any]:
    agent_binding = _graph_node_agent_binding(work_order_payload)
    model_requirement = dict(agent_binding.get("model_requirement") or {})
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


def _graph_node_runtime_contract(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
    agent_profile_id: str,
    agent_id: str,
    turn_id: str,
) -> dict[str, Any]:
    agent_binding = _graph_node_agent_binding(work_order_payload)
    runtime_policy = dict(agent_binding.get("runtime_policy") or {})
    operation_policy = _graph_node_operation_policy(agent_binding)
    control_capabilities = _graph_node_control_capabilities(agent_binding)
    task_lifecycle_policy = dict(runtime_policy.get("task_lifecycle_policy") or {})
    task_lifecycle_policy.setdefault("request_task_run", bool(control_capabilities.get("may_request_task_run") is True))
    runtime_policy["task_lifecycle_policy"] = task_lifecycle_policy
    context_policy = dict(runtime_policy.get("context_policy") or {})
    context_policy.setdefault(
        "active_work_context",
        "enabled" if bool(control_capabilities.get("may_control_active_work") is True) else "disabled",
    )
    context_policy.setdefault("history_scope", "graph_node_work_order")
    runtime_policy["context_policy"] = context_policy
    execution_task_environment_id = str(context_package.get("task_environment_id") or "").strip()
    return _drop_empty(
        {
            "turn_id": turn_id,
            "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
            "node_id": str(work_order_payload.get("node_id") or ""),
            "work_order_id": str(work_order_payload.get("work_order_id") or ""),
            "execution_task_environment_id": execution_task_environment_id,
            "allowed_operations": list(operation_policy.get("allowed_operations") or ()),
            "operation_requirement": {
                "required_operations": list(operation_policy.get("required_operations") or ()),
                "optional_operations": list(operation_policy.get("optional_operations") or ()),
                "denied_operations": list(operation_policy.get("denied_operations") or ()),
                "authority": "harness.graph_node_work_order_bridge.node_operation_requirement",
            },
            "execution_permit": {
                "allowed_operations": list(operation_policy.get("allowed_operations") or ()),
                "operation_ceiling": list(operation_policy.get("operation_ceiling") or ()),
                "authority": "harness.graph_node_work_order_bridge.node_operation_permit",
            },
            "runtime_profile": {
                "agent_id": agent_id,
                "agent_profile_id": agent_profile_id,
                "runtime_policy": runtime_policy,
                "control_capabilities": dict(control_capabilities),
            },
            "control_capabilities": dict(control_capabilities),
            "graph_slot": dict(work_order_payload.get("graph_slot") or {}),
            "graph_node_execution": {
                "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
                "node_id": str(work_order_payload.get("node_id") or ""),
                "work_order_id": str(work_order_payload.get("work_order_id") or ""),
                "task_environment_id": execution_task_environment_id,
                "context_package_id": str(context_package.get("package_id") or ""),
                "node_worker_only": True,
                "graph_state_owner": "graph_system_loop",
                "authority": "harness.graph_node_work_order_bridge.runtime_contract",
            },
            "authority": "harness.graph_node_work_order_bridge.runtime_contract",
        }
    )


def _graph_node_control_capabilities(agent_binding: dict[str, Any]) -> dict[str, Any]:
    runtime_policy = dict(dict(agent_binding or {}).get("runtime_policy") or {})
    configured = dict(runtime_policy.get("control_capabilities") or {})
    return {
        "may_call_tools": bool(configured.get("may_call_tools") is True),
        "may_request_task_run": bool(configured.get("may_request_task_run") is True),
        "may_control_active_work": bool(configured.get("may_control_active_work") is True),
        "may_use_subagents": bool(configured.get("may_use_subagents") is True),
        "requires_json_action_protocol": bool(configured.get("requires_json_action_protocol") is True),
        "authority": "harness.graph_node_work_order_bridge.node_control_capabilities",
        "source": "graph_slot.agent_binding.runtime_policy.control_capabilities",
    }


def _graph_node_operation_policy(agent_binding: dict[str, Any]) -> dict[str, Any]:
    tool_policy = dict(dict(agent_binding or {}).get("tool_policy") or {})
    permission_ceiling = dict(dict(agent_binding or {}).get("permission_ceiling") or {})
    allowed = _dedupe_strings(
        tool_policy.get("allowed_operations")
        or permission_ceiling.get("allowed_operations")
        or ("op.model_response",)
    )
    if "op.model_response" not in allowed:
        allowed = ("op.model_response", *allowed)
    allowed_set = set(allowed)
    required = tuple(item for item in _dedupe_strings(tool_policy.get("required_operations")) if item in allowed_set)
    optional = tuple(item for item in _dedupe_strings(tool_policy.get("optional_operations")) if item in allowed_set)
    denied = _dedupe_strings(
        [
            *_dedupe_strings(tool_policy.get("denied_operations")),
            *_dedupe_strings(tool_policy.get("blocked_operations")),
        ]
    )
    raw_ceiling = _dedupe_strings(tool_policy.get("operation_ceiling") or permission_ceiling.get("operation_ceiling"))
    ceiling = raw_ceiling or allowed
    ceiling_set = set(ceiling)
    allowed = tuple(item for item in allowed if item in ceiling_set)
    if "op.model_response" not in allowed:
        allowed = ("op.model_response", *allowed)
    return {
        "allowed_operations": allowed,
        "required_operations": required,
        "optional_operations": optional,
        "denied_operations": denied,
        "operation_ceiling": ceiling,
        "authority": "harness.graph_node_work_order_bridge.node_operation_policy",
    }


def _static_runtime_environment_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("taskenv:", "taskinst:", "episode:")):
        return ""
    return raw


def _graph_node_workspace_root(
    work_order_payload: dict[str, Any],
    *,
    context_package: dict[str, Any],
) -> str:
    agent_binding = _graph_node_agent_binding(work_order_payload)
    project_binding = dict(agent_binding.get("project_binding") or {})
    scope = dict(context_package.get("scope") or {})
    runtime_scope = dict(scope.get("runtime_scope") or dict(work_order_payload.get("graph_state") or {}).get("runtime_scope") or {})
    return _first_non_empty_string(
        project_binding.get("workspace_root"),
        runtime_scope.get("workspace_root"),
        runtime_scope.get("project_root"),
    )


def _graph_node_session_context(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
    episode: dict[str, Any],
    task_environment: dict[str, Any],
    runtime_contract: dict[str, Any],
    workspace_root: str,
) -> dict[str, Any]:
    return _drop_empty(
        {
            "compressed_context": "",
            "provider_protocol_timeline": [],
            "compaction_generation": "0",
            "task_context_package": context_package,
            "task_execution_episode": episode,
            "task_work_environment": task_environment,
            "graph_node_work_order": _public_graph_node_work_order_payload(work_order_payload),
            "graph_node_execution_boundary": {
                "node_worker_only": True,
                "graph_state_owner": "graph_system_loop",
                "forbidden_actions": [
                    "advance_graph_state",
                    "dispatch_downstream_node",
                    "write_graph_checkpoint",
                    "request_new_task_run",
                    "control_parent_active_work",
                ],
                "authority": "harness.graph_node_work_order_bridge.execution_boundary",
            },
            "runtime_contract": runtime_contract,
            "project_binding": (
                {
                    "workspace_root": workspace_root,
                    "authority": "harness.graph_node_work_order_bridge.project_binding",
                }
                if workspace_root
                else {}
            ),
        }
    )


def _graph_node_current_work_boundary_receipt(work_order_payload: dict[str, Any], *, turn_id: str) -> dict[str, Any]:
    return {
        "receipt_id": stable_task_environment_id("cwreceipt", "graph-node", work_order_payload.get("work_order_id"), turn_id),
        "decision": "isolated_graph_node_execution",
        "active_work_control_available": False,
        "reason": "graph node workers cannot control parent active work; GraphSystem owns graph loop state",
        "authority": "harness.graph_node_work_order_bridge.current_work_boundary",
    }


def _graph_node_work_order_user_message(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
    episode: dict[str, Any],
    task_environment: dict[str, Any],
) -> str:
    input_package = dict(work_order_payload.get("input_package") or {})
    node_identity = dict(input_package.get("node_identity") or {})
    raw_task_contract = _graph_node_task_contract(work_order_payload)
    agent_binding = _graph_node_agent_binding(work_order_payload)
    task_contract = _graph_node_agent_visible_task_contract(raw_task_contract)
    role_contract = _first_non_empty_string(
        node_identity.get("role_prompt"),
        task_contract.get("role_prompt"),
        dict(task_contract.get("prompt_contract") or {}).get("role_prompt"),
    )
    title = _first_non_empty_string(node_identity.get("title"), work_order_payload.get("node_id"), "图节点执行者")
    authorized_input_summary = _graph_node_authorized_input_summary(
        work_order_payload=work_order_payload,
        context_package=context_package,
    )
    authorized_input_section = _graph_node_authorized_input_section(
        work_order_payload=work_order_payload,
        context_package=context_package,
        summary=authorized_input_summary,
    )
    payload = {
        "graph_node_identity": {
            "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
            "node_id": str(work_order_payload.get("node_id") or ""),
            "work_order_id": str(work_order_payload.get("work_order_id") or ""),
            "title": title,
        },
        "task_environment": {
            "task_environment_id": str(task_environment.get("task_environment_id") or ""),
            "task_instance_id": str(task_environment.get("task_instance_id") or ""),
            "episode_id": str(episode.get("episode_id") or ""),
            "context_package_id": str(context_package.get("package_id") or ""),
            "context_package_hash": str(context_package.get("package_hash") or ""),
        },
        "scope": dict(context_package.get("scope") or {}),
        "task_contract": task_contract,
        "agent_binding_summary": _graph_node_agent_visible_agent_binding_summary(agent_binding),
        "resource_handles": _graph_node_agent_visible_resource_handles(context_package),
        "authorized_input_summary": authorized_input_summary,
        "graph_context": _graph_node_agent_visible_graph_context(context_package),
        "task_state_context": dict(context_package.get("task_state_context") or {}),
        "output_contract": dict(context_package.get("output_contract") or {}),
        "expected_result_contract": dict(work_order_payload.get("expected_result_contract") or {}),
        "action_boundary": _graph_node_agent_visible_action_boundary(agent_binding),
        "tool_authority": {
            "source": "node_agent_config_and_runtime_action_surface",
            "rule": "任务环境负责提供本节点需要的上下文包；你只能使用本轮 runtime action surface 实际暴露的动作和工具。若动作面没有暴露工具，不得要求读取文件、记忆、搜索或子 agent，只能基于上下文包交付或明确阻塞。",
            "authority": "harness.graph_node_work_order_bridge.tool_authority",
        },
    }
    return (
        f"你是一名{title}。\n"
        "你只负责完成当前图节点分派给你的工作，并输出可被 GraphSystem 验收的节点结果。\n"
        "你不负责推进图状态、调度下游节点、写图 checkpoint、控制父级当前工作，或自行创建新任务。\n"
        "任务环境已经把本节点可用的上游交接、记忆快照、循环变量和输出要求整理到上下文包中；你必须先消费这些已授权上下文。\n"
        "你不得把“还需要读取文件、记忆或继续探索”当作节点交付；如果上下文包确实不足，只能明确说明缺失的输入事实和阻塞原因。\n"
        "如果输入足够，请直接在本轮交付完整节点产物，不要输出状态报告、进度说明或询问是否继续。\n\n"
        f"你的节点职责契约：\n{role_contract or '依据当前图节点上下文完成本节点交付。'}\n\n"
        f"{authorized_input_section}\n\n"
        "原始任务环境上下文包如下，用于追溯字段来源；优先消费上方“已授权输入”中的正文与状态：\n"
        f"```json\n{_json_for_prompt(payload, limit=30000)}\n```"
    )


def _graph_node_agent_visible_resource_handles(context_package: dict[str, Any]) -> dict[str, Any]:
    handles = dict(context_package.get("resource_handles") or {})
    return _drop_empty(
        {
            "workspace_root": handles.get("workspace_root"),
            "input_refs": handles.get("input_refs"),
            "artifact_refs": handles.get("artifact_refs"),
            "file_refs": handles.get("file_refs"),
            "authority": "harness.graph_node_work_order_bridge.resource_handles",
        }
    )


def _graph_node_agent_visible_graph_context(context_package: dict[str, Any]) -> dict[str, Any]:
    graph_context = dict(context_package.get("graph_context") or {})
    return _drop_empty(
        {
            "graph_identity": graph_context.get("graph_identity"),
            "node_identity": graph_context.get("node_identity"),
            "task_contract": graph_context.get("task_contract"),
            "initial_inputs": graph_context.get("initial_inputs"),
            "inbound_context": graph_context.get("inbound_context"),
            "memory_contract": graph_context.get("memory_contract"),
            "loop_context": graph_context.get("loop_context"),
            "loop_contract": graph_context.get("loop_contract"),
            "output_contract": graph_context.get("output_contract"),
            "runtime_scope": graph_context.get("runtime_scope"),
            "authority": "harness.graph_node_work_order_bridge.graph_context",
        }
    )


def _graph_node_authorized_input_summary(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
) -> dict[str, Any]:
    expected_items = _graph_node_expected_input_items(work_order_payload=work_order_payload, context_package=context_package)
    inbound_contexts = _graph_node_authorized_inbound_contexts(work_order_payload=work_order_payload, context_package=context_package)
    return _drop_empty(
        {
            "required_inputs": _graph_node_required_input_statuses(expected_items=expected_items, inbound_contexts=inbound_contexts),
            "inbound_contexts": [_graph_node_inbound_context_summary(item) for item in inbound_contexts],
            "authority": "harness.graph_node_work_order_bridge.authorized_input_summary",
        }
    )


def _graph_node_authorized_input_section(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    expected_items = _graph_node_expected_input_items(work_order_payload=work_order_payload, context_package=context_package)
    inbound_contexts = _graph_node_authorized_inbound_contexts(work_order_payload=work_order_payload, context_package=context_package)
    expected_by_key = _expected_items_by_key(expected_items)
    consumed_ids: set[str] = set()
    lines: list[str] = [
        "## 已授权输入",
        "本段是任务环境已经交给你的上游输入。带“已提供”的必需输入视为可直接使用；不要再要求读取同一材料。",
        "",
        "### 输入状态",
    ]
    statuses = list(summary.get("required_inputs") or [])
    if statuses:
        for item in statuses:
            item = dict(item)
            marker = "已提供" if str(item.get("status") or "") == "present" else "缺失"
            required = "必需" if bool(item.get("required") is True) else "可选"
            label = str(item.get("label") or item.get("input_key") or "").strip()
            refs = ", ".join(str(ref) for ref in list(item.get("context_refs") or []) if str(ref))
            suffix = f"；来源：{refs}" if refs else ""
            lines.append(f"- {marker}｜{required}｜{label}{suffix}")
    else:
        lines.append("- 未声明必需上游输入；请只消费下方已经展示的上游交接。")
    lines.append("")
    remaining = AUTHORIZED_INPUT_GLOBAL_CHAR_LIMIT
    ordered_contexts: list[dict[str, Any]] = []
    for expected in expected_items:
        ordered_contexts.extend(
            item
            for item in inbound_contexts
            if _input_key_matches(expected.get("input_key"), expected.get("label"), item)
        )
    ordered_contexts.extend(inbound_contexts)
    for inbound in ordered_contexts:
        identity = _inbound_context_identity(inbound)
        if not identity or identity in consumed_ids:
            continue
        consumed_ids.add(identity)
        context_key = _first_non_empty_string(inbound.get("target_context_key"), inbound.get("target_input_slot"), "上游输入")
        expected = expected_by_key.get(_normalize_input_key(context_key), {})
        item_limit = _input_item_char_limit(expected)
        if remaining <= 0:
            lines.append("### 其余授权输入")
            lines.append("已达到本轮授权输入展示上限；请以原始上下文包中的引用为追溯依据。")
            break
        section, used_chars = _graph_node_inbound_context_block(inbound, item_limit=min(item_limit, remaining))
        if not section:
            continue
        lines.append(section)
        lines.append("")
        remaining -= used_chars
    return "\n".join(lines).strip()


def _graph_node_expected_input_items(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
) -> list[dict[str, Any]]:
    contracts = [
        dict(work_order_payload.get("expected_result_contract") or {}),
        dict(context_package.get("output_contract") or {}),
        dict(context_package.get("acceptance") or {}),
    ]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for contract in contracts:
        bindings = dict(contract.get("contract_bindings") or {})
        artifact_binding = dict(bindings.get("artifact") or {})
        policy = dict(
            artifact_binding.get("artifact_context_policy")
            or contract.get("artifact_context_policy")
            or {}
        )
        for raw_item in list(policy.get("items") or []):
            if not isinstance(raw_item, dict):
                continue
            input_key = _first_non_empty_string(
                raw_item.get("input_key"),
                raw_item.get("target_context_key"),
                raw_item.get("target_input_slot"),
                raw_item.get("label"),
            )
            label = _first_non_empty_string(raw_item.get("label"), input_key)
            identity = _normalize_input_key(input_key or label)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            result.append(
                _drop_empty(
                    {
                        "input_key": input_key,
                        "label": label,
                        "required": bool(raw_item.get("required") is True),
                        "max_chars": raw_item.get("max_chars"),
                        "max_refs": raw_item.get("max_refs"),
                        "source": "artifact_context_policy",
                    }
                )
            )
    return result


def _graph_node_authorized_inbound_contexts(
    *,
    work_order_payload: dict[str, Any],
    context_package: dict[str, Any],
) -> list[dict[str, Any]]:
    graph_context = dict(context_package.get("graph_context") or {})
    input_package = dict(work_order_payload.get("input_package") or {})
    graph_slot = dict(work_order_payload.get("graph_slot") or {})
    execution_context = dict(graph_slot.get("execution_context") or {})
    sources = (
        list(graph_context.get("inbound_context") or []),
        list(input_package.get("inbound_context") or []),
        list(execution_context.get("inbound_edge_contexts") or []),
    )
    contexts: list[dict[str, Any]] = []
    by_identity: dict[str, int] = {}
    for source in sources:
        for item in source:
            if not isinstance(item, dict):
                continue
            context = dict(item)
            identity = _inbound_context_identity(context)
            if not identity:
                continue
            existing_index = by_identity.get(identity)
            if existing_index is None:
                by_identity[identity] = len(contexts)
                contexts.append(context)
                continue
            if _inbound_context_content_score(context) > _inbound_context_content_score(contexts[existing_index]):
                contexts[existing_index] = context
    return contexts


def _graph_node_required_input_statuses(
    *,
    expected_items: list[dict[str, Any]],
    inbound_contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for expected in expected_items:
        matches = [
            item
            for item in inbound_contexts
            if _input_key_matches(expected.get("input_key"), expected.get("label"), item)
        ]
        statuses.append(
            _drop_empty(
                {
                    "input_key": str(expected.get("input_key") or ""),
                    "label": str(expected.get("label") or expected.get("input_key") or ""),
                    "required": bool(expected.get("required") is True),
                    "status": "present" if matches else "missing",
                    "context_refs": [
                        _first_non_empty_string(item.get("context_id"), item.get("packet_id"), item.get("edge_id"), item.get("source_edge_id"))
                        for item in matches
                    ],
                    "authority": "harness.graph_node_work_order_bridge.required_input_status",
                }
            )
        )
    return statuses


def _graph_node_inbound_context_summary(inbound: dict[str, Any]) -> dict[str, Any]:
    artifact_payloads = _artifact_payloads_from_inbound(inbound)
    return _drop_empty(
        {
            "target_context_key": str(inbound.get("target_context_key") or ""),
            "target_input_slot": str(inbound.get("target_input_slot") or ""),
            "source_node_id": str(inbound.get("source_node_id") or ""),
            "edge_id": str(inbound.get("edge_id") or inbound.get("source_edge_id") or ""),
            "artifact_refs": _artifact_ref_strings(inbound),
            "artifact_payload_count": len(artifact_payloads),
            "artifact_content_chars": sum(len(str(item.get("content") or "")) for item in artifact_payloads),
            "authority": "harness.graph_node_work_order_bridge.inbound_context_summary",
        }
    )


def _graph_node_inbound_context_block(inbound: dict[str, Any], *, item_limit: int) -> tuple[str, int]:
    target_key = _first_non_empty_string(inbound.get("target_context_key"), inbound.get("target_input_slot"), "上游输入")
    lines: list[str] = [f"### {target_key}"]
    source_node = str(inbound.get("source_node_id") or "").strip()
    edge_id = _first_non_empty_string(inbound.get("edge_id"), inbound.get("source_edge_id"))
    if source_node:
        lines.append(f"- 来源节点：`{source_node}`")
    if edge_id:
        lines.append(f"- 来源边：`{edge_id}`")
    refs = _artifact_ref_strings(inbound)
    if refs:
        lines.append("- 产物引用：")
        for ref in refs[:8]:
            lines.append(f"  - `{ref}`")
    payload = dict(inbound.get("payload") or {})
    handoff_summary = str(payload.get("handoff_summary") or "").strip()
    artifact_payloads = _artifact_payloads_from_inbound(inbound)
    used_chars = 0
    if handoff_summary and not artifact_payloads:
        excerpt = _clip_text(handoff_summary, min(2000, item_limit))
        used_chars += len(excerpt)
        lines.extend(["", "#### 上游交接摘要", excerpt])
    if artifact_payloads:
        lines.append("")
        lines.append("#### 授权正文")
        remaining = max(0, item_limit - used_chars)
        for index, artifact in enumerate(artifact_payloads[:8], start=1):
            if remaining <= 0:
                lines.append("已达到该输入的正文展示上限。")
                break
            artifact_ref = str(artifact.get("artifact_ref") or artifact.get("path") or f"artifact_{index}").strip()
            content = str(artifact.get("content") or "").strip()
            if not content:
                continue
            excerpt = _clip_text(content, remaining)
            used_chars += len(excerpt)
            remaining = max(0, item_limit - used_chars)
            lines.append(f"##### {artifact_ref}")
            lines.append("````text")
            lines.append(excerpt)
            lines.append("````")
    elif not handoff_summary:
        payload_excerpt = _clip_text(_json_for_prompt(payload, limit=min(item_limit, 6000)), min(item_limit, 6000))
        used_chars += len(payload_excerpt)
        lines.extend(["", "#### 上游载荷", "````json", payload_excerpt, "````"])
    return "\n".join(lines).strip(), used_chars


def _artifact_payloads_from_inbound(inbound: dict[str, Any]) -> list[dict[str, Any]]:
    payload = dict(inbound.get("payload") or {})
    return [dict(item) for item in list(payload.get("artifact_payloads") or []) if isinstance(item, dict)]


def _artifact_ref_strings(inbound: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for item in list(inbound.get("artifact_refs") or []):
        if isinstance(item, dict):
            ref = _first_non_empty_string(item.get("artifact_ref"), item.get("path"), item.get("ref"))
        else:
            ref = str(item or "").strip()
        if ref:
            refs.append(ref)
    for item in _artifact_payloads_from_inbound(inbound):
        ref = _first_non_empty_string(item.get("artifact_ref"), item.get("path"), item.get("ref"))
        if ref:
            refs.append(ref)
    return list(dict.fromkeys(refs))


def _expected_items_by_key(expected_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in expected_items:
        for key in (item.get("input_key"), item.get("label")):
            normalized = _normalize_input_key(key)
            if normalized and normalized not in result:
                result[normalized] = item
    return result


def _input_item_char_limit(expected: dict[str, Any]) -> int:
    raw = expected.get("max_chars")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = AUTHORIZED_INPUT_DEFAULT_ITEM_CHAR_LIMIT
    return max(1000, min(value, AUTHORIZED_INPUT_MAX_ITEM_CHAR_LIMIT))


def _input_key_matches(input_key: Any, label: Any, inbound: dict[str, Any]) -> bool:
    expected = {_normalize_input_key(input_key), _normalize_input_key(label)}
    expected.discard("")
    actual = {
        _normalize_input_key(inbound.get("target_context_key")),
        _normalize_input_key(inbound.get("target_input_slot")),
    }
    actual.discard("")
    return bool(expected and actual and expected.intersection(actual))


def _inbound_context_identity(inbound: dict[str, Any]) -> str:
    refs = "|".join(_artifact_ref_strings(inbound))
    return "|".join(
        item
        for item in (
            str(inbound.get("context_id") or "").strip(),
            str(inbound.get("packet_id") or "").strip(),
            str(inbound.get("edge_id") or inbound.get("source_edge_id") or "").strip(),
            str(inbound.get("target_context_key") or inbound.get("target_input_slot") or "").strip(),
            refs,
        )
        if item
    )


def _inbound_context_content_score(inbound: dict[str, Any]) -> int:
    payload = dict(inbound.get("payload") or {})
    artifact_payloads = _artifact_payloads_from_inbound(inbound)
    return (
        len(artifact_payloads) * 1000
        + sum(len(str(item.get("content") or "")) for item in artifact_payloads)
        + len(str(payload.get("handoff_summary") or ""))
    )


def _normalize_input_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "")
    max_chars = max(0, int(limit or 0))
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[已截断]"


def _graph_node_agent_visible_task_contract(value: Any) -> dict[str, Any]:
    contract = dict(value or {})
    return _drop_empty(
        {
            "contract_id": str(contract.get("contract_id") or ""),
            "node_id": str(contract.get("node_id") or ""),
            "node_kind": str(contract.get("node_kind") or ""),
            "node_class": str(contract.get("node_class") or ""),
            "node_identity": dict(contract.get("node_identity") or {}),
            "prompt_contract": dict(contract.get("prompt_contract") or {}),
            "input_contract": dict(contract.get("input_contract") or {}),
            "output_contract": dict(contract.get("output_contract") or {}),
            "acceptance_policy": dict(contract.get("acceptance_policy") or {}),
            "artifact_contract": dict(contract.get("artifact_contract") or {}),
            "state_policy": dict(contract.get("state_policy") or {}),
            "trace_policy": dict(contract.get("trace_policy") or {}),
            "authority": "harness.graph_node_work_order_bridge.agent_visible_task_contract",
        }
    )


def _graph_node_agent_visible_agent_binding_summary(value: Any) -> dict[str, Any]:
    binding = dict(value or {})
    return _drop_empty(
        {
            "binding_id": str(binding.get("binding_id") or ""),
            "binding_mode": str(binding.get("binding_mode") or ""),
            "node_id": str(binding.get("node_id") or ""),
            "executor_type": str(binding.get("executor_type") or ""),
            "agent_id": str(binding.get("agent_id") or ""),
            "agent_profile_id": str(binding.get("agent_profile_id") or ""),
            "agent_group_id": str(binding.get("agent_group_id") or ""),
            "agent_selection_policy": str(binding.get("agent_selection_policy") or ""),
            "authority": "harness.graph_node_work_order_bridge.agent_visible_agent_binding_summary",
        }
    )


def _graph_node_agent_visible_action_boundary(value: Any) -> dict[str, Any]:
    binding = dict(value or {})
    runtime_policy = dict(binding.get("runtime_policy") or {})
    control_capabilities = dict(runtime_policy.get("control_capabilities") or {})
    tool_policy = dict(binding.get("tool_policy") or {})
    permission_ceiling = dict(binding.get("permission_ceiling") or {})
    allowed_operations = _dedupe_strings(
        tool_policy.get("allowed_operations")
        or permission_ceiling.get("allowed_operations")
        or ()
    )
    return _drop_empty(
        {
            "may_call_tools": bool(control_capabilities.get("may_call_tools") is True),
            "allowed_operations": list(allowed_operations),
            "decision_source": "GraphNodeWorkOrder.graph_slot.agent_binding",
            "runtime_surface_rule": "只有 packet action schema 暴露 tool_call 且 available_tools 中存在具体工具时，才允许工具调用。",
            "authority": "harness.graph_node_work_order_bridge.agent_visible_action_boundary",
        }
    )


def _public_graph_node_work_order_payload(work_order_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
        "node_id": str(work_order_payload.get("node_id") or ""),
        "work_order_id": str(work_order_payload.get("work_order_id") or ""),
        "task_run_id": str(work_order_payload.get("task_run_id") or ""),
        "node_session_id": str(work_order_payload.get("node_session_id") or ""),
        "node_session_policy": dict(work_order_payload.get("node_session_policy") or {}),
        "agent_id": str(work_order_payload.get("agent_id") or ""),
        "agent_profile_id": str(work_order_payload.get("agent_profile_id") or ""),
        "expected_result_contract": dict(work_order_payload.get("expected_result_contract") or {}),
    }


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


def _graph_node_executor_result_from_events(
    *,
    graph_config: Any,
    work_order_payload: dict[str, Any],
    preparation_payload: dict[str, Any],
    session_id: str,
    turn_id: str,
    agent_profile_id: str,
    agent_id: str,
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
        "completed" if done_event else "graph_node_harness_no_terminal_event",
    )
    final_answer = str(done_event.get("content") or error_payload.get("content") or error_payload.get("error") or "").strip()
    answer_channel = str(done_event.get("answer_channel") or "").strip()
    done_status = str(done_event.get("status") or "").strip()
    blocked_reasons = {
        "blocked",
        "ask_user",
        "single_turn_tool_iteration_limit",
        "single_agent_turn_model_response_missing",
        "final_answer_required_for_respond",
    }
    blocked = bool(answer_channel in {"blocked", "ask_user"} or terminal_reason in blocked_reasons)
    failed = bool(error_payload or (done_event and done_status == "failed") or not done_event)
    status = "completed" if done_event and not blocked and not failed else ("blocked" if blocked or done_event else "failed")
    final_action_diagnostics = _final_action_diagnostics_from_done_event(done_event)
    episode = dict(preparation_payload.get("episode") or {})
    task_environment = dict(preparation_payload.get("task_environment") or {})
    node_execution_id = str(episode.get("episode_id") or "") or stable_task_environment_id(
        "nodeexec",
        work_order_payload.get("graph_run_id"),
        work_order_payload.get("node_id"),
        work_order_payload.get("work_order_id"),
    )
    turn_run_id = _first_event_value(events, "turn_run_id")
    task_execution_payload = {
        "execution_id": node_execution_id,
        "episode_id": str(episode.get("episode_id") or ""),
        "task_environment_id": str(task_environment.get("task_environment_id") or ""),
        "session_id": session_id,
        "task_ref": str(work_order_payload.get("task_ref") or work_order_payload.get("node_id") or ""),
        "status": status,
        "terminal_reason": terminal_reason,
        "diagnostics": {
            "origin": {"origin_kind": "graph_node_assigned"},
            "origin_kind": "graph_node_assigned",
            "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
            "graph_config_id": str(getattr(graph_config, "config_id", "") or work_order_payload.get("config_id") or ""),
            "graph_work_order_id": str(work_order_payload.get("work_order_id") or ""),
            "graph_node_id": str(work_order_payload.get("node_id") or ""),
            "runtime_scope": dict(dict(work_order_payload.get("input_package") or {}).get("runtime_scope") or {}),
            "task_environment_id": str(task_environment.get("task_environment_id") or ""),
            "episode_id": str(episode.get("episode_id") or ""),
            "turn_id": turn_id,
            "turn_run_id": turn_run_id,
            "agent_id": agent_id,
            "agent_profile_id": agent_profile_id,
            "final_answer": final_answer,
            "final_action_diagnostics": final_action_diagnostics,
            "event_count": len(events),
            "harness_events": [dict(item) for item in events[:40]],
            **(
                {
                    "recoverable_error": {
                        "retryable": True,
                        "error_code": terminal_reason,
                        "user_message": "图节点运行没有形成可验收产物，GraphSystem 不会把本次 closeout 物化为节点产物。",
                    }
                }
                if status == "blocked"
                else {}
            ),
            "runtime_contract": {
                "control_capabilities": dict(runtime_contract.get("control_capabilities") or {}),
                "graph_node_execution": dict(runtime_contract.get("graph_node_execution") or {}),
                "tool_authority": "agent_runtime_profile_runtime_assembly",
            },
            "model_selection": dict(model_selection or {}),
            "authority": "harness.graph_node_work_order_bridge.executor_result",
        },
    }
    return {
        "ok": status == "completed",
        "status": status,
        "error": "" if status == "completed" else terminal_reason,
        "final_answer": final_answer,
        "artifact_refs": [],
        "task_execution": task_execution_payload,
        "event": {"turn_id": turn_id, "turn_run_id": turn_run_id, "terminal_reason": terminal_reason},
        "lifecycle": {
            "executor": "harness.graph_node_work_order_bridge",
            "status": status,
            "event_count": len(events),
        },
        "authority": "harness.graph_node_work_order_bridge",
    }


def _graph_node_executor_blocked_result(
    *,
    reason: str,
    graph_config: Any,
    work_order_payload: dict[str, Any],
    preparation_payload: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    episode = dict(preparation_payload.get("episode") or {})
    node_execution_id = str(episode.get("episode_id") or "") or stable_task_environment_id(
        "nodeexec",
        work_order_payload.get("graph_run_id"),
        work_order_payload.get("node_id"),
        work_order_payload.get("work_order_id"),
    )
    task_environment = dict(preparation_payload.get("task_environment") or {})
    return {
        "ok": False,
        "status": "blocked",
        "error": str(reason or "graph_node_executor_blocked"),
        "final_answer": "",
        "artifact_refs": [],
        "task_execution": {
            "execution_id": node_execution_id,
            "episode_id": str(episode.get("episode_id") or ""),
            "task_environment_id": str(task_environment.get("task_environment_id") or ""),
            "session_id": str(work_order_payload.get("node_session_id") or ""),
            "task_ref": str(work_order_payload.get("task_ref") or work_order_payload.get("node_id") or ""),
            "status": "blocked",
            "terminal_reason": str(reason or "graph_node_executor_blocked"),
            "diagnostics": {
                "origin": {"origin_kind": "graph_node_assigned"},
                "origin_kind": "graph_node_assigned",
                "graph_run_id": str(work_order_payload.get("graph_run_id") or ""),
                "graph_config_id": str(getattr(graph_config, "config_id", "") or work_order_payload.get("config_id") or ""),
                "graph_work_order_id": str(work_order_payload.get("work_order_id") or ""),
                "graph_node_id": str(work_order_payload.get("node_id") or ""),
                "recoverable_error": {
                    "retryable": True,
                    "error_code": str(reason or "graph_node_executor_blocked"),
                },
                **dict(diagnostics or {}),
                "authority": "harness.graph_node_work_order_bridge.blocked_result",
            },
        },
        "event": {"terminal_reason": str(reason or "graph_node_executor_blocked")},
        "lifecycle": {"executor": "harness.graph_node_work_order_bridge", "status": "blocked"},
        "authority": "harness.graph_node_work_order_bridge",
    }


def _permission_mode(runtime_host: Any | None) -> str:
    provider = getattr(runtime_host, "_current_permission_mode", None)
    if callable(provider):
        return normalize_permission_mode(str(provider() or "full_access"))
    return "full_access"


def _object_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(value or {}) if isinstance(value, dict) else {}


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


def _dedupe_strings(value: Any) -> tuple[str, ...]:
    raw_values = value if isinstance(value, (list, tuple, set)) else ([value] if value else [])
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _first_non_empty_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
