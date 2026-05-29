from __future__ import annotations

import time
from typing import Any

from .models import GraphHarnessConfig, GraphLoopState, GraphNodeWorkOrder, safe_id, stable_hash
from .scheduler_view import start_node_ids, upstream_dependency_node_ids


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
        upstream_packets = self.handoff_packets_for_node(graph_config=graph_config, state=state, node_id=node_id)
        upstream_results = self.upstream_results_for_node(graph_config=graph_config, state=state, node_id=node_id)
        input_package = self.build_input_package(
            graph_config=graph_config,
            state=state,
            node=node,
            upstream_packets=upstream_packets,
            upstream_results=upstream_results,
        )
        return GraphNodeWorkOrder(
            work_order_id=f"gwork:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{int(time.time() * 1000)}",
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
            permission_scope=dict(input_package.get("permission_summary") or graph_config.permissions or {}),
            tool_scope=dict(input_package.get("tool_capability_table") or graph_config.tools or {}),
            expected_result_contract=dict(input_package.get("expected_result_contract") or {}),
            async_policy=dict(node.get("async_policy") or {}),
            retry_policy=dict(node.get("retry") or {}),
            timeout_policy=dict(node.get("timeout") or {}),
            dispatch_context={
                "graph_run_id": state.graph_run_id,
                "config_id": graph_config.config_id,
                "dispatch_event_id": f"dispatch:{state.graph_run_id}:{node_id}:{int(time.time() * 1000)}",
                "executor": executor,
                "handoff_packet_count": len(upstream_packets),
                "upstream_result_count": len(upstream_results),
                "materializer": self.authority,
            },
        )

    def build_input_package(
        self,
        *,
        graph_config: GraphHarnessConfig,
        state: GraphLoopState,
        node: dict[str, Any],
        upstream_packets: list[dict[str, Any]],
        upstream_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        node_id = str(node.get("node_id") or "")
        prompt_contract = _prompt_contract(node)
        initial_inputs = dict(state.initial_inputs or {}) if node_id in start_node_ids(graph_config) else {}
        return {
            "package_id": f"gin:{safe_id(state.graph_run_id)}:{safe_id(node_id)}:{safe_id(stable_hash([upstream_packets, upstream_results])[:12])}",
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
            "agent_instruction": _agent_instruction(prompt_contract=prompt_contract, node=node),
            "input_contract": dict(dict(node.get("contracts") or {}).get("contract_bindings") or {}).get("schema", {}),
            "output_contract": dict(node.get("contracts") or {}),
            "initial_inputs": initial_inputs,
            "upstream_results": upstream_results,
            "upstream_handoff_packets": upstream_packets,
            "handoff_packets": upstream_packets,
            "memory_view": _memory_view_request(graph_config=graph_config, node=node),
            "artifact_view": _artifact_view_request(graph_config=graph_config, node=node),
            "file_view": _file_view_request(graph_config=graph_config, node=node),
            "issue_view": _issue_view_request(graph_config=graph_config, node=node),
            "permission_summary": dict(node.get("permissions") or graph_config.permissions or {}),
            "tool_capability_table": dict(node.get("tools") or graph_config.tools or {}),
            "hidden_control_refs": {
                "graph_run_id": state.graph_run_id,
                "graph_id": graph_config.graph_id,
                "config_id": graph_config.config_id,
                "config_hash": graph_config.content_hash,
                "work_order_source": "GraphLoop.dispatch_ready",
            },
            "expected_result_contract": dict(node.get("contracts") or {}),
        }

    def upstream_results_for_node(self, *, graph_config: GraphHarnessConfig, state: GraphLoopState, node_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for upstream_id in upstream_dependency_node_ids(graph_config, node_id):
            result = dict(state.result_index.get(upstream_id) or {})
            if result:
                results.append(
                    {
                        "source_node_id": upstream_id,
                        "result_id": str(result.get("result_id") or ""),
                        "status": str(result.get("status") or ""),
                        "outputs": dict(result.get("outputs") or {}),
                        "decisions": dict(result.get("decisions") or {}),
                        "artifact_refs": list(result.get("artifact_refs") or []),
                        "handoff_summary": str(result.get("handoff_summary") or ""),
                    }
                )
        return results

    def handoff_packets_for_node(self, *, graph_config: GraphHarnessConfig, state: GraphLoopState, node_id: str) -> list[dict[str, Any]]:
        packets: list[dict[str, Any]] = []
        for edge in _incoming_dependency_edges(graph_config, node_id):
            source_node_id = str(edge.get("source_node_id") or "")
            result = dict(state.result_index.get(source_node_id) or {})
            if not result:
                continue
            packets.append(
                {
                    "packet_id": f"ghandoff:{safe_id(state.graph_run_id)}:{safe_id(str(edge.get('edge_id') or source_node_id + '.' + node_id))}",
                    "authority": "harness.graph_edge_handoff_packet",
                    "graph_run_id": state.graph_run_id,
                    "config_id": state.config_id,
                    "edge_id": str(edge.get("edge_id") or ""),
                    "edge_type": str(edge.get("edge_type") or ""),
                    "semantic_role": str(edge.get("semantic_role") or ""),
                    "source_node_id": source_node_id,
                    "target_node_id": node_id,
                    "source_result_id": str(result.get("result_id") or ""),
                    "source_status": str(result.get("status") or ""),
                    "payload_contract_id": str(edge.get("payload_contract_id") or ""),
                    "payload": {
                        "outputs": dict(result.get("outputs") or {}),
                        "decisions": dict(result.get("decisions") or {}),
                        "artifact_refs": list(result.get("artifact_refs") or []),
                        "memory_candidates": list(result.get("memory_candidates") or []),
                        "handoff_summary": str(result.get("handoff_summary") or ""),
                    },
                    "delivery_policy": str(edge.get("result_delivery_policy") or "contract_payload_and_refs"),
                    "ack_required": bool(edge.get("ack_required", True)),
                }
            )
        return packets


def _incoming_dependency_edges(graph_config: GraphHarnessConfig, node_id: str) -> tuple[dict[str, Any], ...]:
    target = str(node_id or "")
    from .scheduler_view import build_scheduler_view

    return tuple(
        dict(edge)
        for edge in build_scheduler_view(graph_config).dependency_edges
        if str(edge.get("target_node_id") or "") == target
    )


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
    return {
        "node_memory_policy": dict(node.get("memory") or {}),
        "graph_memory_policy": dict(graph_config.memory or {}),
    }


def _artifact_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_artifact_policy": dict(node.get("artifacts") or {}),
        "graph_artifact_policy": dict(graph_config.artifacts or {}),
    }


def _file_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_file_policy": dict(node.get("files") or {}),
        "graph_resource_policy": dict(graph_config.resources or {}),
    }


def _issue_view_request(*, graph_config: GraphHarnessConfig, node: dict[str, Any]) -> dict[str, Any]:
    del node
    return {
        "issue_ledgers": [
            dict(item)
            for item in list(dict(graph_config.resources or {}).get("resource_nodes") or [])
            if str(dict(item).get("resource_type") or dict(item).get("node_type") or "") == "issue_ledger"
        ]
    }


def _graph_work_kind(executor_type: str) -> str:
    normalized = str(executor_type or "agent").strip()
    if normalized in {"human", "human_gate", "review_gate"}:
        return "human_gate"
    if normalized == "tool":
        return "tool"
    return "agent"
