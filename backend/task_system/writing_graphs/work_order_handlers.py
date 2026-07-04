from __future__ import annotations

import json
from typing import Any

from graph_system.models import ExecutableGraphConfig, GraphNodeWorkOrder, stable_safe_id
from graph_system.work_order_handler_registry import DeterministicWorkOrderHandler, DeterministicWorkOrderResult
from task_system.runtime_semantics.chapter_progress import (
    ChapterProgressReceiptError,
    build_chapter_progress_receipt,
)


def register_deterministic_work_order_handlers(register) -> None:
    register(
        DeterministicWorkOrderHandler(
            handler_id="writing_progress_receipt_router",
            handle=handle_writing_progress_receipt_router,
            priority=100,
        )
    )


def handle_writing_progress_receipt_router(
    *,
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
) -> DeterministicWorkOrderResult | None:
    if not _is_deterministic_progress_receipt_router_node(graph_config=graph_config, work_order=work_order):
        return None
    execution_id = f"system:{stable_safe_id(work_order.work_order_id)}"
    initial_inputs = _work_order_initial_inputs(work_order)
    try:
        if not _has_inbound_artifact_evidence(work_order):
            raise ChapterProgressReceiptError("chapter_progress_receipt_upstream_artifact_missing")
        receipt = build_chapter_progress_receipt(
            initial_inputs=initial_inputs,
            committed_words=_int_template_value(initial_inputs.get("committed_words"), 0),
        )
        final_answer = _deterministic_progress_receipt_final_answer(work_order=work_order, receipt=receipt)
        return DeterministicWorkOrderResult(
            executor_result={
                "ok": True,
                "final_answer": final_answer,
                "task_execution": {
                    "execution_id": execution_id,
                    "task_ref": work_order.task_ref,
                    "status": "completed",
                    "diagnostics": {
                        "final_answer": final_answer,
                        "final_action_diagnostics": {
                            "structured_output": {"chapter_progress_receipt": receipt},
                            "node_output": {"chapter_progress_receipt": receipt},
                        },
                        "deterministic_executor": {
                            "authority": "task_system.writing_graphs.work_order_handler.progress_receipt",
                            "reason": "self_sourced_progress_receipt_router",
                        },
                    },
                },
            },
            diagnostics={"deterministic_progress_receipt": True},
        )
    except ChapterProgressReceiptError as exc:
        return DeterministicWorkOrderResult(
            executor_result={
                "ok": False,
                "error": "deterministic_progress_receipt_invalid",
                "task_execution": {
                    "execution_id": execution_id,
                    "task_ref": work_order.task_ref,
                    "status": "failed",
                    "terminal_reason": "deterministic_progress_receipt_invalid",
                    "diagnostics": {
                        "recoverable_error": {
                            "error_code": str(exc),
                            "retryable": False,
                            "user_message": "章节进度路由输入不合法，系统没有生成可推进回执。",
                        },
                    },
                },
            },
            diagnostics={"deterministic_progress_receipt": True},
        )


def _progress_receipt_policy(*, graph_config: ExecutableGraphConfig, work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    node = next((dict(item) for item in graph_config.nodes if str(item.get("node_id") or "") == work_order.node_id), {})
    metadata = dict(node.get("metadata") or {})
    policy = dict(node.get("progress_receipt_policy") or metadata.get("progress_receipt_policy") or {})
    if policy:
        return policy
    bindings = dict(dict(node.get("contracts") or {}).get("contract_bindings") or {})
    progress = dict(bindings.get("progress") or {})
    if progress:
        return progress
    return {}


def _is_deterministic_progress_receipt_router_node(*, graph_config: ExecutableGraphConfig, work_order: GraphNodeWorkOrder) -> bool:
    node = _graph_node_by_id(graph_config, work_order.node_id)
    if not node:
        return False
    if not _progress_receipt_policy(graph_config=graph_config, work_order=work_order):
        return False
    route_policy = dict(dict(node.get("loop") or {}).get("route_policy") or {})
    if str(route_policy.get("mode") or "").strip() != "progress_receipt":
        return False
    sources = [
        str(item or "").strip()
        for item in list(route_policy.get("receipt_source_node_ids") or route_policy.get("progress_receipt_source_node_ids") or [])
        if str(item or "").strip()
    ]
    return sources == [work_order.node_id]


def _work_order_initial_inputs(work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    return {
        **dict(dict(work_order.input_package or {}).get("initial_inputs") or {}),
        **dict(work_order.explicit_inputs or {}),
    }


def _has_inbound_artifact_evidence(work_order: GraphNodeWorkOrder) -> bool:
    for item in list(dict(work_order.input_package or {}).get("inbound_context") or []):
        context = dict(item or {}) if isinstance(item, dict) else {}
        if _has_artifact_refs(context.get("artifact_refs")):
            return True
        payload = dict(context.get("payload") or {})
        if _has_artifact_refs(payload.get("artifact_refs")):
            return True
        for artifact_payload in list(payload.get("artifact_payloads") or []):
            if not isinstance(artifact_payload, dict):
                continue
            if str(artifact_payload.get("artifact_ref") or artifact_payload.get("path") or artifact_payload.get("absolute_path") or "").strip():
                return True
    return False


def _has_artifact_refs(value: Any) -> bool:
    for item in list(value or []):
        if isinstance(item, dict):
            if str(item.get("artifact_ref") or item.get("path") or item.get("absolute_path") or "").strip():
                return True
        elif str(item or "").strip():
            return True
    return False


def _deterministic_progress_receipt_final_answer(*, work_order: GraphNodeWorkOrder, receipt: dict[str, Any]) -> str:
    committed = list(receipt.get("committed_chapter_indexes") or [])
    chapter = _int_template_value(committed[-1] if committed else receipt.get("batch_start_index"), 1)
    next_chapter = _int_template_value(receipt.get("next_chapter_index"), chapter + 1)
    batch_start = _int_template_value(receipt.get("batch_start_index"), chapter)
    batch_end = _int_template_value(receipt.get("batch_end_index"), chapter)
    state = "当前批次已完成" if bool(receipt.get("batch_complete")) else f"继续到第{next_chapter:03d}章"
    payload = {"chapter_progress_receipt": dict(receipt)}
    return "\n".join(
        [
            "# 【节点交付内容】",
            "",
            f"第{chapter:03d}章正文候选已由上游节点完成并进入单章路由验收。",
            f"当前批次范围：第{batch_start:03d}章至第{batch_end:03d}章；路由裁决：{state}。",
            f"节点：{work_order.node_id}",
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "```",
        ]
    )


def _graph_node_by_id(graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    target = str(node_id or "").strip()
    if not target:
        return {}
    for node in graph_config.nodes:
        current = str(dict(node).get("node_id") or "").strip()
        if current == target:
            return dict(node)
    return {}


def _int_template_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
