from __future__ import annotations

import time
from typing import Any

from .models import GraphHarnessConfig, GraphLoopState, GraphNodeWorkOrder, safe_id, stable_hash
from .scheduler_view import upstream_dependency_node_ids


class GraphContextMaterializer:
    """Builds graph node work orders and agent-visible input packages.

    GraphLoop owns state progression. This materializer owns the runtime packet
    that an agent node can understand.
    """

    authority = "harness.graph.context_materializer"

    def build_work_order(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        node: dict[str, Any],
    ) -> GraphNodeWorkOrder:
        node_id = str(node.get("node_id") or "")
        executor = dict(node.get("executor") or {})
        executor_type = str(executor.get("executor_type") or "agent")
        inbound_context = self.inbound_context_for_node(graph_config=graph_config, state=state, node_id=node_id)
        input_package = self.build_input_package(
            graph_config=graph_config,
            state=state,
            node=node,
            inbound_context=inbound_context,
        )
        environment_refs = _environment_refs(graph_config)
        dispatch_seq = len(tuple(dict(state.result_history or {}).get(node_id) or ())) + 1
        return GraphNodeWorkOrder(
            work_order_id=f"gwork:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{dispatch_seq}:{state.event_cursor + 1}:{int(time.time() * 1000)}",
            work_kind=_graph_work_kind(executor_type),
            graph_run_id=state.graph_run_id,
            task_run_id=state.task_run_id,
            config_id=graph_config.config_id,
            config_hash=graph_config.content_hash,
            task_ref=str(node.get("task_ref") or f"task_graph.node.{graph_config.graph_id}.{node_id}"),
            executor_type=executor_type,
            node_id=node_id,
            agent_id=str(node.get("agent_id") or ""),
            agent_profile_id=str(node.get("agent_profile_id") or ""),
            message=str(input_package.get("agent_instruction") or ""),
            explicit_inputs=dict(input_package.get("initial_inputs") or {}),
            input_package=input_package,
            graph_state={
                "graph_run_id": state.graph_run_id,
                "graph_id": graph_config.graph_id,
                "config_id": graph_config.config_id,
                "runtime_scope": _runtime_scope_from_state(state),
                "completed_node_ids": list(state.completed_node_ids),
                "failed_node_ids": list(state.failed_node_ids),
                "upstream_node_ids": list(upstream_dependency_node_ids(graph_config, node_id)),
                "available_result_node_ids": sorted(state.result_index.keys()),
                "authority": "harness.graph_loop.node_work_order_graph_state",
            },
            context_refs=dict(node.get("context") or {}),
            memory_view_request=dict(input_package.get("memory_view") or {}),
            artifact_view_request=dict(input_package.get("artifact_view") or {}),
            file_view_request=dict(input_package.get("file_view") or {}),
            artifact_space_ref=str(environment_refs.get("artifact_space_ref") or ""),
            memory_space_ref=str(environment_refs.get("memory_space_ref") or ""),
            file_access_table_refs=tuple(environment_refs.get("file_access_table_refs") or ()),
            artifact_repository_targets=tuple(dict(item) for item in list(environment_refs.get("artifact_repository_targets") or []) if isinstance(item, dict)),
            memory_repository_targets=tuple(dict(item) for item in list(environment_refs.get("memory_repository_targets") or []) if isinstance(item, dict)),
            permission_scope=dict(input_package.get("permission_summary") or graph_config.permissions or {}),
            tool_scope=dict(input_package.get("tool_capability_table") or graph_config.tools or {}),
            expected_result_contract=dict(input_package.get("expected_result_contract") or {}),
            async_policy=dict(node.get("async_policy") or {}),
            retry_policy=dict(node.get("retry") or {}),
            timeout_policy=dict(node.get("timeout") or {}),
            dispatch_context={
                "graph_run_id": state.graph_run_id,
                "config_id": graph_config.config_id,
                "runtime_scope": _runtime_scope_from_state(state),
                "dispatch_event_id": f"dispatch:{state.graph_run_id}:{node_id}:{int(time.time() * 1000)}",
                "executor": executor,
                "inbound_context_count": len(inbound_context),
                "materializer": self.authority,
            },
        )

    def build_input_package(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        node: dict[str, Any],
        inbound_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        node_id = str(node.get("node_id") or "")
        prompt_contract = _prompt_contract(node)
        initial_inputs = dict(state.initial_inputs or {})
        loop_context = _loop_context_for_node(state=state, node=node)
        environment_refs = _environment_refs(graph_config)
        return {
            "package_id": f"gin:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{safe_id(stable_hash([initial_inputs, loop_context, inbound_context])[:12])}",
            "authority": "harness.graph_node_input_package",
            "materializer_authority": self.authority,
            "node_identity": {
                "node_id": node_id,
                "title": str(node.get("title") or node_id),
                "node_type": str(node.get("node_type") or ""),
                "task_ref": str(node.get("task_ref") or ""),
                "agent_id": str(node.get("agent_id") or ""),
                "agent_profile_id": str(node.get("agent_profile_id") or ""),
            },
            "prompt_contract": prompt_contract,
            "prompt": prompt_contract,
            "task_environment_id": str(graph_config.task_environment_id or ""),
            "task_environment": dict(graph_config.environment or {}),
            "runtime_scope": _runtime_scope_from_state(state),
            "runtime_profile": _node_runtime_profile(graph_config=graph_config, node=node),
            "agent_instruction": _agent_instruction(prompt_contract=prompt_contract, node=node),
            "input_contract": dict(dict(node.get("contracts") or {}).get("contract_bindings") or {}).get("schema", {}),
            "output_contract": dict(node.get("contracts") or {}),
            "initial_inputs": initial_inputs,
            "loop_context": loop_context,
            "inbound_context": inbound_context,
            "memory_view": _memory_view_request(graph_config=graph_config, node=node),
            "artifact_view": _artifact_view_request(graph_config=graph_config, node=node),
            "file_view": _file_view_request(graph_config=graph_config, node=node),
            "environment_refs": environment_refs,
            "artifact_space_ref": str(environment_refs.get("artifact_space_ref") or ""),
            "memory_space_ref": str(environment_refs.get("memory_space_ref") or ""),
            "file_access_table_refs": list(environment_refs.get("file_access_table_refs") or []),
            "artifact_repository_targets": [dict(item) for item in list(environment_refs.get("artifact_repository_targets") or []) if isinstance(item, dict)],
            "memory_repository_targets": [dict(item) for item in list(environment_refs.get("memory_repository_targets") or []) if isinstance(item, dict)],
            "issue_view": _issue_view_request(graph_config=graph_config, node=node),
            "permission_summary": dict(node.get("permissions") or graph_config.permissions or {}),
            "tool_capability_table": dict(node.get("tools") or graph_config.tools or {}),
            "hidden_control_refs": {
                "graph_run_id": state.graph_run_id,
                "graph_id": graph_config.graph_id,
                "config_id": graph_config.config_id,
                "config_hash": graph_config.content_hash,
                "runtime_scope": _runtime_scope_from_state(state),
                "work_order_source": "GraphLoop.dispatch_ready",
            },
            "expected_result_contract": dict(node.get("contracts") or {}),
        }

    def inbound_context_for_node(self, *, graph_config: GraphHarnessConfig, state: GraphLoopState, node_id: str) -> list[dict[str, Any]]:
        context: list[dict[str, Any]] = []
        for edge in _incoming_dependency_edges(graph_config, node_id):
            upstream_id = str(edge.get("source_node_id") or "")
            result = dict(state.result_index.get(upstream_id) or {})
            if result:
                payload = _filtered_edge_payload(edge=edge, result=result)
                context.append(
                    {
                        "authority": "harness.graph.inbound_context",
                        "context_id": f"ginctx:{safe_id(state.graph_run_id)}:{safe_id(str(edge.get('edge_id') or upstream_id + '.' + node_id))}",
                        "source_node_id": upstream_id,
                        "target_node_id": node_id,
                        "source_edge_id": str(edge.get("edge_id") or ""),
                        "source_result_ref": str(result.get("result_id") or ""),
                        "source_status": str(result.get("status") or ""),
                        "payload_contract_id": str(edge.get("payload_contract_id") or ""),
                        "payload": payload,
                        "delivery_policy": str(edge.get("result_delivery_policy") or "summary_and_refs"),
                        "ack_required": bool(edge.get("ack_required", True)),
                        "edge_id": str(edge.get("edge_id") or ""),
                    }
                )
        return context


def _loop_context_for_node(*, state: GraphLoopState, node: dict[str, Any]) -> dict[str, Any]:
    node_loop = dict(node.get("loop") or {})
    scope_id = str(node_loop.get("scope_id") or "").strip()
    frames = dict(dict(state.loop_state or {}).get("frames") or {})
    active_frame = dict(frames.get(scope_id) or {}) if scope_id else {}
    history = [
        dict(item)
        for item in list(dict(state.loop_state or {}).get("route_history") or [])
        if isinstance(item, dict) and (not scope_id or str(item.get("scope_id") or "") == scope_id)
    ]
    return {
        "authority": "harness.graph.loop_context",
        "scope_id": scope_id,
        "node_loop": node_loop,
        "active_frame": active_frame,
        "route_history": history,
        "result_history_counts": {
            key: len(list(value or []))
            for key, value in dict(state.result_history or {}).items()
        },
        "contract_inputs": dict(state.initial_inputs or {}),
    }


def _incoming_dependency_edges(graph_config: GraphHarnessConfig, node_id: str) -> tuple[dict[str, Any], ...]:
    target = str(node_id or "")
    from .scheduler_view import build_scheduler_view

    return tuple(
        dict(edge)
        for edge in build_scheduler_view(graph_config).dependency_edges
        if str(edge.get("target_node_id") or "") == target
    )


def _filtered_edge_payload(*, edge: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    delivery_policy = str(edge.get("result_delivery_policy") or "summary_and_refs").strip() or "summary_and_refs"
    output_payload = _filter_outputs(
        dict(result.get("outputs") or {}),
        context_filter_policy=dict(edge.get("context_filter_policy") or {}),
    )
    artifact_refs = _filter_artifact_refs(
        list(result.get("artifact_refs") or []),
        artifact_ref_policy=dict(edge.get("artifact_ref_policy") or {}),
    )
    memory_candidates = _filter_memory_candidates(
        list(result.get("memory_candidates") or []),
        working_memory_handoff_policy=dict(edge.get("working_memory_handoff_policy") or {}),
        delivery_policy=delivery_policy,
    )
    base_refs = {
        "artifact_refs": artifact_refs,
        "artifact_materialization_receipts": list(result.get("artifact_materialization_receipts") or []),
        "memory_commit_receipts": list(result.get("memory_commit_receipts") or []),
        "handoff_summary": str(result.get("handoff_summary") or ""),
    }
    if delivery_policy in {"notification_only", "status_only"}:
        return {"handoff_summary": base_refs["handoff_summary"]}
    if delivery_policy in {"refs_only", "artifact_refs_only"}:
        return base_refs
    if delivery_policy == "summary_only":
        return {"handoff_summary": base_refs["handoff_summary"]}
    if delivery_policy in {"summary_and_refs", "contract_payload_and_refs"}:
        if output_payload:
            return {**base_refs, "bounded_outputs": output_payload}
        return base_refs
    return {
        "bounded_outputs": output_payload,
        "decisions": dict(result.get("decisions") or {}),
        "memory_candidates": memory_candidates,
        **base_refs,
    }


def _filter_outputs(outputs: dict[str, Any], *, context_filter_policy: dict[str, Any]) -> dict[str, Any]:
    include_keys = _string_set(
        context_filter_policy.get("include_output_keys")
        or context_filter_policy.get("allowed_output_keys")
        or context_filter_policy.get("include_keys")
        or context_filter_policy.get("allow")
    )
    exclude_keys = _string_set(
        context_filter_policy.get("exclude_output_keys")
        or context_filter_policy.get("blocked_output_keys")
        or context_filter_policy.get("exclude_keys")
        or context_filter_policy.get("deny")
    )
    if include_keys:
        filtered = {key: value for key, value in outputs.items() if str(key) in include_keys}
    else:
        filtered = dict(outputs)
    for key in exclude_keys:
        filtered.pop(key, None)
    max_chars = _int_value(context_filter_policy.get("max_chars") or context_filter_policy.get("max_output_chars"), 0)
    if max_chars > 0:
        return {key: _truncate_value(value, max_chars=max_chars) for key, value in filtered.items()}
    return filtered


def _filter_artifact_refs(refs: list[Any], *, artifact_ref_policy: dict[str, Any]) -> list[Any]:
    if artifact_ref_policy.get("include") is False or artifact_ref_policy.get("enabled") is False:
        return []
    max_refs = _int_value(artifact_ref_policy.get("max_refs") or artifact_ref_policy.get("limit"), 0)
    result = list(refs)
    if max_refs > 0:
        result = result[:max_refs]
    return result


def _filter_memory_candidates(
    candidates: list[Any],
    *,
    working_memory_handoff_policy: dict[str, Any],
    delivery_policy: str,
) -> list[Any]:
    if delivery_policy in {"refs_only", "artifact_refs_only", "summary_only", "summary_and_refs", "notification_only", "status_only"}:
        return []
    if working_memory_handoff_policy.get("include_candidates") is False:
        return []
    carry_kinds = _string_set(working_memory_handoff_policy.get("carry_kinds") or working_memory_handoff_policy.get("record_kinds"))
    if not carry_kinds:
        return [dict(item) for item in candidates if isinstance(item, dict)]
    return [
        dict(item)
        for item in candidates
        if isinstance(item, dict) and str(item.get("record_kind") or item.get("kind") or "") in carry_kinds
    ]


def _truncate_value(value: Any, *, max_chars: int) -> Any:
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars].rstrip()
    if isinstance(value, dict):
        return {key: _truncate_value(item, max_chars=max_chars) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_value(item, max_chars=max_chars) for item in value]
    return value


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    return {str(item).strip() for item in list(value or []) if str(item).strip()}


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _prompt_contract(node: dict[str, Any]) -> dict[str, Any]:
    prompt = dict(node.get("prompt") or {})
    return {
        "role_prompt": str(prompt.get("role_prompt") or "").strip(),
        "task_instruction": str(prompt.get("task_instruction") or "").strip(),
        "output_instruction": str(prompt.get("output_instruction") or "").strip(),
        "forbidden_behavior": list(prompt.get("forbidden_behavior") or []),
        "definition_of_done": list(prompt.get("definition_of_done") or []),
    }


def _agent_instruction(*, prompt_contract: dict[str, Any], node: dict[str, Any]) -> str:
    parts = [
        str(prompt_contract.get("role_prompt") or "").strip(),
        str(prompt_contract.get("task_instruction") or "").strip(),
        str(prompt_contract.get("output_instruction") or "").strip(),
    ]
    forbidden = [str(item).strip() for item in list(prompt_contract.get("forbidden_behavior") or []) if str(item).strip()]
    done = [str(item).strip() for item in list(prompt_contract.get("definition_of_done") or []) if str(item).strip()]
    if forbidden:
        parts.append("禁止事项：\n" + "\n".join(f"- {item}" for item in forbidden))
    if done:
        parts.append("完成标准：\n" + "\n".join(f"- {item}" for item in done))
    message = "\n".join(item for item in parts if item).strip()
    if message:
        return message
    return f"请根据你的角色职责完成当前节点任务：{str(node.get('title') or node.get('node_id') or '未命名节点')}。"


def _memory_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "environment_memory_space": dict(environment.get("memory_space") or {}),
        "memory_space_ref": _memory_space_ref(graph_config),
        "node_memory_policy": dict(node.get("memory") or {}),
        "graph_memory_policy": _node_memory_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _artifact_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    node_id = str(node.get("node_id") or "")
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "environment_artifact_policy": dict(environment.get("artifact_policy") or {}),
        "environment_storage_space": dict(environment.get("storage_space") or {}),
        "artifact_space_ref": _artifact_space_ref(graph_config),
        "node_artifact_policy": dict(node.get("artifacts") or {}),
        "graph_artifact_policy": _node_artifact_policy_view(graph_config=graph_config, node_id=node_id),
    }


def _file_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    environment = dict(graph_config.environment or {})
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "environment_storage_space": dict(environment.get("storage_space") or {}),
        "file_management": dict(environment.get("file_management") or {}),
        "file_access_tables": list(environment.get("file_access_tables") or []),
        "file_access_table_refs": _file_access_table_refs(graph_config),
        "node_file_policy": dict(node.get("files") or {}),
        "graph_resource_policy": _resource_policy_view(graph_config=graph_config),
    }


def _issue_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    del node
    return {
        "issue_ledgers": [
            _resource_node_summary(dict(item))
            for item in list(dict(graph_config.resources or {}).get("resource_nodes") or [])
            if str(dict(item).get("resource_type") or dict(item).get("node_type") or "") == "issue_ledger"
        ]
    }


def _node_memory_policy_view(*, graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any]:
    policy = dict(graph_config.memory or {})
    read_rules = _node_related_items(list(policy.get("read_rules") or []), node_id=node_id)
    return {
        "working_memory_policy_profile_id": str(policy.get("working_memory_policy_profile_id") or ""),
        "working_memory_policy": dict(policy.get("working_memory_policy") or {}),
        "read_rules": read_rules,
        "read_rule_count": len(read_rules),
        "total_read_rule_count": len(list(policy.get("read_rules") or [])),
        "memory_protocol": _memory_protocol_summary(dict(policy.get("memory_protocol") or {})),
        "authority": "harness.graph.context_materializer.node_memory_policy_view",
    }


def _node_artifact_policy_view(*, graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any]:
    policy = dict(graph_config.artifacts or {})
    context_edges = _node_related_items(list(policy.get("context_edges") or []), node_id=node_id)
    return {
        "context_edges": context_edges,
        "context_edge_count": len(context_edges),
        "total_context_edge_count": len(list(policy.get("context_edges") or [])),
        "authority": "harness.graph.context_materializer.node_artifact_policy_view",
    }


def _resource_policy_view(*, graph_config: GraphHarnessConfig) -> dict[str, Any]:
    resources = [
        _resource_node_summary(dict(item))
        for item in list(dict(graph_config.resources or {}).get("resource_nodes") or [])
        if isinstance(item, dict)
    ]
    return {
        "resource_nodes": resources,
        "resource_node_count": len(resources),
        "authority": "harness.graph.context_materializer.resource_policy_view",
    }


def _resource_node_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": str(item.get("node_id") or ""),
        "title": str(item.get("title") or ""),
        "resource_type": str(item.get("resource_type") or item.get("node_type") or ""),
        "repository_id": str(item.get("repository_id") or ""),
        "collections": [str(value) for value in list(item.get("collections") or []) if str(value)],
        "readable_by": [str(value) for value in list(item.get("readable_by") or []) if str(value)],
        "write_owner_node_ids": [str(value) for value in list(item.get("write_owner_node_ids") or []) if str(value)],
        "authority": str(item.get("authority") or "task_system.resource_node"),
    }


def _node_related_items(items: list[Any], *, node_id: str) -> list[dict[str, Any]]:
    target = str(node_id or "")
    if not target:
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        refs = {
            str(payload.get("source_node_id") or ""),
            str(payload.get("target_node_id") or ""),
            str(payload.get("node_id") or ""),
            str(payload.get("owner_node_id") or ""),
            str(payload.get("before_node_id") or ""),
            str(payload.get("after_node_id") or ""),
        }
        if target in refs:
            result.append(payload)
    return result


def _memory_protocol_summary(protocol: dict[str, Any]) -> dict[str, Any]:
    if not protocol:
        return {}
    return {
        "authority": str(protocol.get("authority") or ""),
        "repository_count": len(list(protocol.get("repositories") or [])),
        "read_rule_count": len(list(protocol.get("read_rules") or [])),
        "write_rule_count": len(list(protocol.get("write_rules") or [])),
    }


def _graph_work_kind(executor_type: str) -> str:
    normalized = str(executor_type or "agent").strip()
    if normalized in {"human", "human_gate", "review_gate"}:
        return "human_gate"
    if normalized == "tool":
        return "tool"
    return "agent"


def _node_runtime_profile(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    runtime_profile = dict(metadata.get("runtime_profile") or {})
    if not runtime_profile:
        runtime_profile = dict(metadata.get("runtime") or {})
    mode = str(
        runtime_profile.get("mode")
        or runtime_profile.get("runtime_mode")
        or metadata.get("runtime_mode")
        or dict(graph_config.agents or {}).get("runtime_mode")
        or "professional"
    ).strip() or "professional"
    return {
        **runtime_profile,
        "mode": mode,
        "runtime_mode": str(runtime_profile.get("runtime_mode") or mode),
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "tool_policy": dict(node.get("tools") or graph_config.tools or {}),
        "permission_policy": dict(node.get("permissions") or graph_config.permissions or {}),
        "runtime_mode_policy": {
            **dict(runtime_profile.get("runtime_mode_policy") or runtime_profile.get("mode_policy") or {}),
            "source": "graph_node_config",
            "node_id": str(node.get("node_id") or ""),
        },
    }


def _environment_refs(graph_config: GraphHarnessConfig) -> dict[str, Any]:
    return {
        "task_environment_id": str(graph_config.task_environment_id or ""),
        "artifact_space_ref": _artifact_space_ref(graph_config),
        "memory_space_ref": _memory_space_ref(graph_config),
        "file_access_table_refs": list(_file_access_table_refs(graph_config)),
        "artifact_repository_targets": _artifact_repository_targets(graph_config),
        "memory_repository_targets": _memory_repository_targets(graph_config),
        "authority": "harness.graph.context_materializer.environment_refs",
    }


def _artifact_space_ref(graph_config: GraphHarnessConfig) -> str:
    storage = dict(dict(graph_config.environment or {}).get("storage_space") or {})
    return str(storage.get("artifact_root") or "").strip()


def _memory_space_ref(graph_config: GraphHarnessConfig) -> str:
    memory_space = dict(dict(graph_config.environment or {}).get("memory_space") or {})
    for key in ("environment_memory_refs", "project_knowledge_refs", "shared_context_refs", "retrieval_index_refs"):
        refs = [str(item) for item in list(memory_space.get(key) or []) if str(item)]
        if refs:
            return refs[0]
    return str(graph_config.task_environment_id or "").strip()


def _file_access_table_refs(graph_config: GraphHarnessConfig) -> tuple[str, ...]:
    tables = list(dict(graph_config.environment or {}).get("file_access_tables") or [])
    refs: list[str] = []
    for item in tables:
        if not isinstance(item, dict):
            continue
        table_id = str(item.get("table_id") or "").strip()
        if table_id:
            refs.append(table_id)
    return tuple(dict.fromkeys(refs))


def _artifact_repository_targets(graph_config: GraphHarnessConfig) -> list[dict[str, Any]]:
    artifact_root = _artifact_space_ref(graph_config)
    if not artifact_root:
        return []
    return [
        {
            "target_ref": artifact_root,
            "target_kind": "task_environment_artifact_root",
            "task_environment_id": str(graph_config.task_environment_id or ""),
            "authority": "task_environment.artifact_policy",
        }
    ]


def _memory_repository_targets(graph_config: GraphHarnessConfig) -> list[dict[str, Any]]:
    memory_space = dict(dict(graph_config.environment or {}).get("memory_space") or {})
    targets: list[dict[str, Any]] = []
    for key in ("environment_memory_refs", "project_knowledge_refs", "shared_context_refs", "retrieval_index_refs"):
        for ref in [str(item).strip() for item in list(memory_space.get(key) or []) if str(item).strip()]:
            targets.append(
                {
                    "target_ref": ref,
                    "target_kind": key,
                    "task_environment_id": str(graph_config.task_environment_id or ""),
                    "authority": "task_environment.memory_space",
                }
            )
    return targets


def _runtime_scope_from_state(state: GraphLoopState) -> dict[str, Any]:
    return dict(dict(state.diagnostics or {}).get("runtime_scope") or {})
