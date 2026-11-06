from __future__ import annotations

import re
from typing import Any

from graph_system.models import ExecutableGraphConfig, GraphNodeWorkOrder
from graph_system.quality_gate_registry import QualityGateHandler
from task_system.runtime_semantics.quality_gates import stage_business_acceptance


AUTHORITY = "task_system.writing_graphs.quality_gate_handler.stage_business_acceptance"


def register_quality_gate_handlers(register) -> None:
    register(
        QualityGateHandler(
            handler_id="writing_stage_business_acceptance",
            evaluate=evaluate_writing_stage_business_acceptance,
            priority=200,
        )
    )


def evaluate_writing_stage_business_acceptance(
    *,
    graph_config: ExecutableGraphConfig,
    work_order: GraphNodeWorkOrder,
    final_answer: str,
    artifact_refs: list[dict[str, Any]],
    result_status: str,
) -> dict[str, Any] | None:
    node = _graph_node_by_id(graph_config, work_order.node_id)
    if not node:
        return None
    if str(node.get("node_type") or "").strip() == "review_gate":
        return None
    retry_policy = dict(node.get("retry") or work_order.retry_policy or {})
    accepted_policies = [
        str(item).strip()
        for item in list(retry_policy.get("acceptance_policies") or [])
        if str(item).strip()
    ]
    runtime_contract = dict(dict(node.get("contracts") or {}).get("contract_bindings") or {}).get("runtime") or {}
    length_budget = dict(runtime_contract.get("length_budget") or {})
    has_length_budget = bool(length_budget.get("enabled") is True or length_budget.get("configured") is True)
    if not has_length_budget and not accepted_policies:
        return None
    if not str(final_answer or "").strip():
        return None
    if has_length_budget:
        length_budget = {**length_budget, "configured": True}
    explicit_inputs = {
        **dict(dict(work_order.input_package or {}).get("initial_inputs") or {}),
        **dict(work_order.explicit_inputs or {}),
    }
    acceptance = stage_business_acceptance(
        stage_id=work_order.node_id,
        contract={
            "node_type": str(node.get("node_type") or ""),
            "length_budget": length_budget,
            "quality_retry_policy": retry_policy,
        },
        explicit_inputs=explicit_inputs,
        final_content=final_answer,
        output_refs=[
            str(item.get("path") or item.get("src") or item.get("absolute_path") or "")
            for item in list(artifact_refs or [])
            if isinstance(item, dict)
        ],
        terminal_status=result_status,
        requires_file_artifact_refs=False,
    )
    chapter_issues = _chapter_heading_quality_issues(explicit_inputs=explicit_inputs, final_answer=final_answer)
    if not chapter_issues:
        return {**acceptance, "authority": str(acceptance.get("authority") or AUTHORITY)}
    issues = [str(item) for item in list(acceptance.get("issues") or []) if str(item)]
    return {
        **acceptance,
        "accepted": False,
        "business_accepted": False,
        "policy": str(acceptance.get("policy") or "chapter_contract"),
        "issues": [*issues, *chapter_issues],
        "quality_issue_summary": _join_quality_summary(
            str(acceptance.get("quality_issue_summary") or ""),
            "当前章号与正文标题不匹配，必须完整重交当前章。",
        ),
        "authority": AUTHORITY,
    }


def _chapter_heading_quality_issues(*, explicit_inputs: dict[str, Any], final_answer: str) -> list[str]:
    expected = _int_value(explicit_inputs.get("current_chapter_index") or explicit_inputs.get("chapter_index"), 0)
    if expected <= 0:
        return []
    actual = _chapter_heading_index(final_answer)
    if actual is None or actual == expected:
        return []
    return [f"chapter_mismatch:{actual}!={expected}"]


def _chapter_heading_index(final_answer: str) -> int | None:
    text = str(final_answer or "")
    body = text
    marker = re.search(r"(?m)^#{1,4}\s*章节正文候选\s*$", text)
    if marker:
        body = text[marker.end() :]
    for match in re.finditer(r"(?m)^#{1,4}\s*第\s*0*(\d{1,4})\s*章\b", body):
        return int(match.group(1))
    for match in re.finditer(r"(?m)^第\s*0*(\d{1,4})\s*章\b", body):
        return int(match.group(1))
    return None


def _join_quality_summary(*parts: str) -> str:
    return "；".join(part for part in (str(item or "").strip() for item in parts) if part)


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _graph_node_by_id(graph_config: ExecutableGraphConfig, node_id: str) -> dict[str, Any]:
    target = str(node_id or "").strip()
    if not target:
        return {}
    for node in graph_config.nodes:
        current = str(dict(node).get("node_id") or "").strip()
        if current == target:
            return dict(node)
    return {}
