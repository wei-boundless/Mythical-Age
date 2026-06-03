from __future__ import annotations

from typing import Any

from agent_system.identity import normalize_agent_id
from harness.graph.models import safe_id, stable_hash
from harness.loop.task_lifecycle import TaskRunContract
from runtime.shared.models import TaskRun
def _graph_node_contract_from_work_order(work_order: Any) -> TaskRunContract:
    contracts = dict(getattr(work_order, "expected_result_contract", {}) or {})
    graph_slot = dict(getattr(work_order, "graph_slot", {}) or {})
    if not graph_slot:
        raise ValueError("GraphNodeWorkOrder missing graph_slot")
    if str(graph_slot.get("authority") or "") != "harness.graph.node_execution_slot":
        raise ValueError("GraphNodeWorkOrder graph_slot authority mismatch")
    node_contract = dict(graph_slot.get("node_contract") or {})
    prompt_contract = dict(node_contract.get("prompt_contract") or {})
    task_environment_id = _graph_slot_task_environment_id(graph_slot)
    runtime_profile = _graph_node_runtime_profile(
        node_contract=node_contract,
        task_environment_id=task_environment_id,
    )
    criteria = [
        "完成当前图节点职责，并输出可被下游节点消费的结果。",
        "如产生文件或记忆候选，需要在输出中列出真实引用。",
    ]
    output_contract_id = str(contracts.get("output_contract_id") or contracts.get("node_contract_id") or "")
    if output_contract_id:
        criteria.append(f"满足输出合同：{output_contract_id}。")
    return TaskRunContract(
        contract_id=f"gcontract:{safe_id(work_order.graph_run_id)}:{safe_id(work_order.node_id)}:{safe_id(work_order.work_order_id)}",
        contract_source="graph_node_work_order",
        user_visible_goal=work_order.message or f"完成图节点 {work_order.node_id}。",
        task_run_goal=work_order.message or f"完成图节点 {work_order.node_id}。",
        completion_criteria=tuple(criteria),
        resource_requirements={},
        permission_requirements=dict(getattr(work_order, "permission_scope", {}) or {}),
        acceptance_policy=contracts,
        recovery_policy=dict(getattr(work_order, "retry_policy", {}) or {}),
        created_from_packet_ref=work_order.work_order_id,
        task_environment_id=task_environment_id,
        runtime_profile=runtime_profile,
        prompt_contract=prompt_contract,
        graph_slot=graph_slot,
        origin=_graph_node_origin(work_order),
    )


def _graph_slot_task_environment_id(graph_slot: dict[str, Any]) -> str:
    output_contract = dict(graph_slot.get("output_contract") or {})
    environment_projection = dict(output_contract.get("environment_projection") or {})
    return str(
        environment_projection.get("task_environment_id")
        or environment_projection.get("target_environment_id")
        or environment_projection.get("environment_id")
        or ""
    ).strip()


def _graph_node_runtime_profile(
    *,
    node_contract: dict[str, Any],
    task_environment_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_policy": {
            "source": "graph_slot.node_contract",
            "context_policy": {"task_run_context": "disabled"},
            "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution.v1"]},
            "operation_authorization_projection": {
                "model_visible": "summary_without_denials",
                "reason": "图节点只需要知道本轮可用操作；被拒绝操作不参与节点交付判断。",
            },
            **dict(node_contract.get("runtime_policy") or node_contract.get("execution_policy") or {}),
        },
    }
    if task_environment_id:
        payload["task_environment_id"] = task_environment_id
    for key, value in {
        "model_requirement": node_contract.get("model_requirement"),
        "reasoning_policy": node_contract.get("reasoning_policy"),
        "tool_contract": node_contract.get("tool_contract"),
        "skill_contract": node_contract.get("skill_contract"),
        "permission_contract": node_contract.get("permission_contract"),
    }.items():
        if value:
            payload[key] = dict(value) if isinstance(value, dict) else value
    return payload


def _graph_node_task_selection(graph_config: Any, work_order: Any) -> dict[str, Any]:
    graph_slot = dict(getattr(work_order, "graph_slot", {}) or {})
    node_contract = dict(graph_slot.get("node_contract") or {})
    task_environment_id = str(
        getattr(graph_config, "task_environment_id", "")
        or _graph_slot_task_environment_id(graph_slot)
        or ""
    )
    runtime_profile = {
        "task_environment_id": task_environment_id,
        "model_requirement": dict(node_contract.get("model_requirement") or {}),
        "reasoning_policy": dict(node_contract.get("reasoning_policy") or {}),
        "tool_policy": dict(getattr(work_order, "tool_scope", {}) or node_contract.get("tool_contract") or getattr(graph_config, "tools", {}) or {}),
        "permission_policy": dict(getattr(work_order, "permission_scope", {}) or node_contract.get("permission_contract") or getattr(graph_config, "permissions", {}) or {}),
        "runtime_policy": {
            "source": "graph_slot.node_contract",
            "graph_run_id": work_order.graph_run_id,
            "node_id": work_order.node_id,
            "context_policy": {"task_run_context": "disabled"},
            "prompt_pack_refs_by_invocation": {"task_execution": ["runtime.pack.graph_node_execution.v1"]},
            "operation_authorization_projection": {
                "model_visible": "summary_without_denials",
                "reason": "图节点只需要知道本轮可用操作；被拒绝操作不参与节点交付判断。",
            },
            **dict(node_contract.get("runtime_policy") or node_contract.get("execution_policy") or {}),
        },
    }
    return {
        "selected_task_id": work_order.task_ref,
        "task_environment_id": task_environment_id,
        "runtime_profile": runtime_profile,
        "prompt_contract": dict(node_contract.get("prompt_contract") or {}),
        "allowed_operations": list(_graph_node_allowed_operations(work_order=work_order, node_contract=node_contract)),
    }


def _graph_node_allowed_operations(*, work_order: Any, node_contract: dict[str, Any]) -> tuple[str, ...]:
    candidates: list[Any] = []
    tool_scope = dict(getattr(work_order, "tool_scope", {}) or {})
    candidates.extend(list(tool_scope.get("allowed_operations") or []))
    tool_contract = dict(node_contract.get("tool_contract") or {})
    candidates.extend(list(tool_contract.get("allowed_operations") or []))
    operation_policy = dict(tool_contract.get("operation_policy") or {})
    candidates.extend(list(operation_policy.get("allowed_operations") or []))
    bindings = dict(node_contract.get("contract_bindings") or {})
    execution = dict(bindings.get("execution") or {})
    executor_policy = dict(execution.get("executor_policy") or {})
    executor_operation_policy = dict(executor_policy.get("operation_policy") or {})
    candidates.extend(list(executor_operation_policy.get("allowed_operations") or []))
    normalized = tuple(dict.fromkeys(str(item).strip() for item in candidates if str(item).strip()))
    return normalized or ("op.model_response",)


def _graph_coordinator_profile_ref(graph_config: Any) -> str:
    return str(dict(getattr(graph_config, "agents", {}) or {}).get("coordinator_agent_profile_id") or "task_graph_node_executor")


def _graph_node_agent_id(graph_config: Any, work_order: Any) -> str:
    raw = str(
        getattr(work_order, "agent_id", "")
        or dict(getattr(graph_config, "agents", {}) or {}).get("coordinator_agent_id")
        or "agent:0"
    ).strip()
    normalized = normalize_agent_id(raw)
    return normalized if normalized.startswith("agent:") else "agent:0"


def _graph_node_origin(work_order: Any) -> dict[str, str]:
    return {
        "origin_kind": "graph_node_assigned",
        "origin_authority": "harness.graph_loop",
        "origin_ref": str(getattr(work_order, "work_order_id", "") or ""),
        "parent_run_ref": str(getattr(work_order, "graph_run_id", "") or ""),
        "graph_run_id": str(getattr(work_order, "graph_run_id", "") or ""),
        "node_id": str(getattr(work_order, "node_id", "") or ""),
    }


def _graph_node_runtime_scope(work_order: Any) -> dict[str, Any]:
    graph_state = dict(getattr(work_order, "graph_state", {}) or {})
    dispatch_context = dict(getattr(work_order, "dispatch_context", {}) or {})
    return {
        **dict(graph_state.get("runtime_scope") or {}),
        **dict(dispatch_context.get("runtime_scope") or {}),
        "graph_run_id": str(getattr(work_order, "graph_run_id", "") or ""),
        "task_run_id": str(getattr(work_order, "task_run_id", "") or ""),
        "authority": "harness.graph.work_order_contract.graph_node_runtime_scope",
    }


def _graph_node_clock_seq(work_order: Any) -> int:
    for payload in (
        dict(getattr(work_order, "dispatch_context", {}) or {}),
        dict(getattr(work_order, "graph_state", {}) or {}),
    ):
        try:
            return int(payload.get("graph_clock_seq"))
        except (TypeError, ValueError):
            continue
    return 0


def _graph_node_public_scope_fields(work_order: Any) -> dict[str, str]:
    runtime_scope = _graph_node_runtime_scope(work_order)
    result: dict[str, str] = {}
    for key in ("project_id", "scope_id"):
        value = str(runtime_scope.get(key) or "").strip()
        if value:
            result[key] = value
    return result


def _graph_node_task_run_id(work_order: Any) -> str:
    work_order_id = str(getattr(work_order, "work_order_id", "") or "")
    work_order_hash = stable_hash(work_order_id)[:16]
    graph_part = safe_id(getattr(work_order, "graph_run_id", ""), limit=56)
    node_part = safe_id(getattr(work_order, "node_id", ""), limit=48)
    order_part = safe_id(work_order_id, limit=32)
    return (
        f"gtask:{work_order_hash}:"
        f"{graph_part}:"
        f"{node_part}:"
        f"{order_part}"
    )


def _validate_existing_graph_node_task_run(task_run: TaskRun, *, graph_run_id: str, work_order_id: str) -> None:
    diagnostics = dict(task_run.diagnostics or {})
    if str(diagnostics.get("origin_kind") or "") != "graph_node_assigned":
        raise ValueError("Existing graph node TaskRun origin_kind mismatch")
    if str(diagnostics.get("graph_run_id") or "") != str(graph_run_id or ""):
        raise ValueError("Existing graph node TaskRun graph_run_id mismatch")
    if str(diagnostics.get("graph_work_order_id") or "") != str(work_order_id or ""):
        raise ValueError("Existing graph node TaskRun work_order_id mismatch")

