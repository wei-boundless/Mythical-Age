from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .models import GraphHarnessConfig, GraphNodeWorkOrder, NodeResultEnvelope, safe_id


@dataclass(frozen=True, slots=True)
class GraphWorkOrderExecution:
    work_order: GraphNodeWorkOrder
    node_result: NodeResultEnvelope
    task_run: Any | None = None
    executor_result: dict[str, Any] | None = None
    events: tuple[dict[str, Any], ...] = ()


class GraphNodeWorkOrderExecutor:
    """Executes graph work orders through the new graph harness contract."""

    def __init__(self, *, services: Any) -> None:
        self._services = services

    async def execute(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder | dict[str, Any],
        max_steps: int = 12,
    ) -> GraphWorkOrderExecution:
        order = work_order if isinstance(work_order, GraphNodeWorkOrder) else GraphNodeWorkOrder.from_dict(dict(work_order or {}))
        if order.config_id != graph_config.config_id:
            raise ValueError("GraphNodeWorkOrder config_id does not match GraphHarnessConfig")
        if order.work_kind == "agent":
            return await self._execute_agent_node(graph_config=graph_config, work_order=order, max_steps=max_steps)
        if order.work_kind == "human_gate":
            return self._unsupported_executor_result(
                graph_config=graph_config,
                work_order=order,
                reason="human_gate_requires_external_decision",
            )
        if order.work_kind == "tool":
            return self._unsupported_executor_result(
                graph_config=graph_config,
                work_order=order,
                reason="graph_tool_node_executor_not_connected",
            )
        return self._unsupported_executor_result(
            graph_config=graph_config,
            work_order=order,
            reason=f"unsupported_graph_work_kind:{order.work_kind}",
        )

    async def _execute_agent_node(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
        max_steps: int,
    ) -> GraphWorkOrderExecution:
        executor = self._services.execute_graph_agent_work_order_callback
        if not callable(executor):
            return self._unsupported_executor_result(
                graph_config=graph_config,
                work_order=work_order,
                reason="graph_agent_work_order_executor_unavailable",
            )
        executor_result = await executor(
            graph_config=graph_config,
            work_order=work_order,
            max_steps=max(1, int(max_steps or 12)),
        )
        task_run_payload = dict(dict(executor_result or {}).get("task_run") or {})
        result = self._node_result_from_agent_execution(
            graph_config=graph_config,
            work_order=work_order,
            task_run_id=str(task_run_payload.get("task_run_id") or ""),
            executor_result=dict(executor_result or {}),
        )
        event = self._services.event_log.append(
            work_order.task_run_id,
            "graph_node_work_order_executed",
            payload={
                "graph_run_id": work_order.graph_run_id,
                "node_id": work_order.node_id,
                "work_order": work_order.to_dict(),
                "node_executor_task_run_id": str(task_run_payload.get("task_run_id") or ""),
                "node_result": result.to_dict(),
                "executor_result": _public_executor_result(executor_result),
            },
            refs={
                "graph_run_ref": work_order.graph_run_id,
                "graph_harness_config_ref": graph_config.config_id,
                "node_ref": work_order.node_id,
                "work_order_ref": work_order.work_order_id,
                "node_executor_task_run_ref": str(task_run_payload.get("task_run_id") or ""),
            },
        )
        return GraphWorkOrderExecution(
            work_order=work_order,
            node_result=result,
            task_run=task_run_payload,
            executor_result=dict(executor_result or {}),
            events=(event.to_dict(),),
        )

    def _node_result_from_agent_execution(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
        task_run_id: str,
        executor_result: dict[str, Any],
    ) -> NodeResultEnvelope:
        ok = bool(executor_result.get("ok") is True)
        task_run_payload = dict(executor_result.get("task_run") or {})
        final_answer = str(executor_result.get("final_answer") or task_run_payload.get("diagnostics", {}).get("final_answer") or "")
        artifact_refs = _artifact_refs_from_executor_result(executor_result, task_run_payload=task_run_payload)
        return NodeResultEnvelope(
            result_id=f"nresult:{safe_id(work_order.graph_run_id)}:{safe_id(work_order.node_id)}:{safe_id(work_order.work_order_id)}",
            graph_run_id=work_order.graph_run_id,
            task_run_id=work_order.task_run_id,
            node_id=work_order.node_id,
            work_order_id=work_order.work_order_id,
            executor_type=work_order.executor_type,
            status="completed" if ok else "failed",
            outputs={
                "final_answer": final_answer,
                "node_executor_task_run_id": task_run_id,
                "executor_status": str(task_run_payload.get("status") or ("completed" if ok else "failed")),
                "artifact_refs": artifact_refs,
            },
            artifact_refs=tuple(str(item.get("path") or item.get("src") or item.get("absolute_path") or "") for item in artifact_refs if isinstance(item, dict)),
            handoff_summary=final_answer[:1200],
            error={} if ok else {"reason": str(executor_result.get("error") or task_run_payload.get("terminal_reason") or "node_executor_failed")},
            diagnostics={
                "authority": "harness.graph.work_order_executor.agent_result",
                "graph_harness_config_id": graph_config.config_id,
                "node_executor_task_run_id": task_run_id,
                "executor_result": _public_executor_result(executor_result),
            },
            created_at=time.time(),
        )

    def _unsupported_executor_result(
        self,
        *,
        graph_config: GraphHarnessConfig,
        work_order: GraphNodeWorkOrder,
        reason: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> GraphWorkOrderExecution:
        result = NodeResultEnvelope(
            result_id=f"nresult:{safe_id(work_order.graph_run_id)}:{safe_id(work_order.node_id)}:{safe_id(work_order.work_order_id)}:unsupported",
            graph_run_id=work_order.graph_run_id,
            task_run_id=work_order.task_run_id,
            node_id=work_order.node_id,
            work_order_id=work_order.work_order_id,
            executor_type=work_order.executor_type,
            status="failed",
            outputs={},
            error={"reason": reason},
            diagnostics={
                "authority": "harness.graph.work_order_executor.unsupported",
                "graph_harness_config_id": graph_config.config_id,
                **dict(diagnostics or {}),
            },
            created_at=time.time(),
        )
        return GraphWorkOrderExecution(work_order=work_order, node_result=result)


def _artifact_refs_from_executor_result(executor_result: dict[str, Any], *, task_run_payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in list(executor_result.get("artifact_refs") or []):
        if isinstance(item, dict):
            refs.append(dict(item))
    diagnostics = dict(task_run_payload.get("diagnostics") or {})
    for item in list(diagnostics.get("artifact_refs") or []):
        if isinstance(item, dict):
            refs.append(dict(item))
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        key = str(ref.get("path") or ref.get("absolute_path") or ref.get("src") or ref)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _public_executor_result(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(result or {})
    return {
        key: value
        for key, value in payload.items()
        if key in {"ok", "error", "final_answer", "artifact_refs", "task_run", "event", "lifecycle"}
    }
