from __future__ import annotations

from typing import Any

from task_system.compiler.coordination_graph_models import (
    TaskGraphRuntimeEdge,
    TaskGraphRuntimeNode,
    TaskGraphRuntimeValidationIssue,
)
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphValidationIssue
from task_system.planning.task_split_merge_models import SplitMergeIssue


def runtime_issue_from_task_graph_issue(issue: TaskGraphValidationIssue) -> TaskGraphRuntimeValidationIssue:
    return TaskGraphRuntimeValidationIssue(
        code=issue.code,
        message=issue.message,
        severity=issue.severity,
        node_id=issue.node_id,
        edge_id=issue.edge_id,
    )


def runtime_issues_from_split_merge_issues(issues: tuple[SplitMergeIssue, ...]) -> list[TaskGraphRuntimeValidationIssue]:
    return [
        TaskGraphRuntimeValidationIssue(
            code=issue.code,
            message=issue.message,
            severity=issue.severity,
            node_id=issue.node_id,
        )
        for issue in issues
    ]


def runtime_issues_from_length_budget(length_budget: Any) -> list[TaskGraphRuntimeValidationIssue]:
    diagnostics = dict(getattr(length_budget, "diagnostics", {}) or {})
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for issue_code in list(diagnostics.get("issues") or []):
        issues.append(
            TaskGraphRuntimeValidationIssue(
                code=str(issue_code),
                message=f"长度预算校验失败：{issue_code}",
                severity="warning",
            )
        )
    return issues


def runtime_issues_from_runtime_semantics(manifest: dict[str, Any]) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for item in list(manifest.get("diagnostics") or []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "warning")
        if severity != "error":
            continue
        scope = str(item.get("scope") or "")
        ref_id = str(item.get("ref_id") or "")
        issues.append(
            TaskGraphRuntimeValidationIssue(
                code=f"runtime_semantics_{item.get('code') or 'issue'}",
                message=str(item.get("message") or "Runtime semantics issue"),
                severity=severity,
                node_id=ref_id if scope == "node" else "",
                edge_id=ref_id if scope == "edge" else "",
            )
        )
    return issues


def runtime_issues_from_scheduler_support(report: dict[str, Any]) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for item in [*list(report.get("partial") or []), *list(report.get("unsupported") or [])]:
        scope = str(item.get("scope") or "")
        ref_id = str(item.get("ref_id") or "")
        field = str(item.get("field") or "")
        status = str(item.get("status") or "")
        reason = str(item.get("reason") or "")
        issues.append(
            TaskGraphRuntimeValidationIssue(
                code=f"scheduler_policy_{status}",
                message=f"{field} 当前调度支持状态为 {status}：{reason}",
                severity="warning",
                node_id=ref_id if scope == "node" else "",
                edge_id=ref_id if scope == "edge" else "",
            )
        )
    return issues


def runtime_issues_from_layered_graph(layered_graph: dict[str, Any]) -> list[TaskGraphRuntimeValidationIssue]:
    issues: list[TaskGraphRuntimeValidationIssue] = []
    for item in list(layered_graph.get("issues") or []):
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "warning")
        if severity == "info":
            continue
        issues.append(
            TaskGraphRuntimeValidationIssue(
                code=f"layered_graph_{item.get('code') or 'issue'}",
                message=str(item.get("message") or "Layered graph issue"),
                severity=severity,
                node_id=str(item.get("node_id") or ""),
                edge_id=str(item.get("edge_id") or ""),
            )
        )
    return issues


def scheduler_support_report(
    *,
    graph: TaskGraphDefinition,
    nodes: list[TaskGraphRuntimeNode],
    edges: list[TaskGraphRuntimeEdge],
) -> dict[str, Any]:
    supported: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []

    def mark(
        *,
        scope: str,
        ref_id: str,
        field: str,
        value: Any,
        status: str,
        reason: str,
    ) -> None:
        item = {
            "scope": scope,
            "ref_id": ref_id,
            "field": field,
            "value": value,
            "status": status,
            "reason": reason,
        }
        if status == "supported":
            supported.append(item)
        elif status == "partial":
            partial.append(item)
        else:
            unsupported.append(item)

    metadata = dict(graph.metadata or {})
    if metadata.get("timeline_policy"):
        mark(
            scope="graph",
            ref_id=graph.graph_id,
            field="metadata.timeline_policy",
            value=dict(metadata.get("timeline_policy") or {}),
            status="partial",
            reason="timeline_policy 只作为生命周期展示/诊断配置保留；运行调度不再按图级 phase/sequence 自动阻塞。",
        )
    if metadata.get("phase_definitions"):
        mark(
            scope="graph",
            ref_id=graph.graph_id,
            field="metadata.phase_definitions",
            value="configured",
            status="partial",
            reason="阶段定义已进入 RuntimeSpec diagnostics 和前端预检，但只表达 lifecycle coordinate，不是默认运行闸门。",
        )

    for node in nodes:
        if node.execution_mode in {"sync", "async", "background"}:
            mark(scope="node", ref_id=node.node_id, field="execution_mode", value=node.execution_mode, status="supported", reason="该执行模式已由统一调度决策消费，并可按是否阻塞主链区分同步与后台执行。")
        elif node.execution_mode in {"parallel", "barrier", "manual_gate"}:
            mark(scope="node", ref_id=node.node_id, field="execution_mode", value=node.execution_mode, status="supported", reason="该执行模式已有明确的运行语义，调度器可按节点等待与汇合策略消费。")
        else:
            mark(scope="node", ref_id=node.node_id, field="execution_mode", value=node.execution_mode, status="unsupported", reason="当前调度器未实现该执行模式。")

        if node.wait_policy in {"wait_all_upstream_completed", "wait_required_contracts"}:
            mark(scope="node", ref_id=node.node_id, field="wait_policy", value=node.wait_policy, status="supported", reason="运行层已按上游完成和输入绑定阻塞节点。")
        elif node.wait_policy in {"wait_any_upstream_completed", "wait_handoff_ack", "fire_and_continue", "manual_release"}:
            mark(scope="node", ref_id=node.node_id, field="wait_policy", value=node.wait_policy, status="supported", reason="TaskGraphSchedulerState 已消费该等待策略并参与 ready/blocked 判断。")
        else:
            mark(scope="node", ref_id=node.node_id, field="wait_policy", value=node.wait_policy, status="unsupported", reason="当前 ready/blocked 判断尚未完整消费该 wait_policy。")

        if node.join_policy == "all_success":
            mark(scope="node", ref_id=node.node_id, field="join_policy", value=node.join_policy, status="supported", reason="当前拓扑依赖等价于 all_success。")
        elif node.join_policy in {"allow_partial_with_issues", "coordinator_decides"}:
            mark(scope="node", ref_id=node.node_id, field="join_policy", value=node.join_policy, status="supported", reason="TaskGraphSchedulerState 已支持上游全部终态后的部分成功汇聚。")
        else:
            mark(scope="node", ref_id=node.node_id, field="join_policy", value=node.join_policy, status="unsupported", reason="当前调度器尚未实现该 join_policy。")

        if node.phase_id:
            mark(scope="node", ref_id=node.node_id, field="phase_id", value=node.phase_id, status="partial", reason="phase_id 只作为生命周期坐标和调度诊断保留；不再默认控制节点 ready/blocked。")
        if node.sequence_index:
            mark(scope="node", ref_id=node.node_id, field="sequence_index", value=node.sequence_index, status="partial", reason="sequence_index 只作为展示排序/生命周期坐标保留；需要顺序约束时必须使用显式边或显式 blocking temporal edge。")
        if node.timeline_group_id:
            mark(scope="node", ref_id=node.node_id, field="timeline_group_id", value=node.timeline_group_id, status="partial", reason="timeline_group_id 只作为旧展示坐标保留；运行调度不会按它同步启动或自动汇合。")
        if node.review_gate_policy:
            mark(scope="node", ref_id=node.node_id, field="review_gate_policy", value="configured", status="partial", reason="审核门策略已保留，但运行层仍主要依赖 stage contract / human gate 处理验收。")
        if node.loop_policy:
            mark(scope="node", ref_id=node.node_id, field="loop_policy", value="configured", status="partial", reason="节点循环策略已保留，但通用 TaskGraph loop 调度尚未实现。")

    for edge in edges:
        if edge.wait_policy:
            status, reason = _edge_wait_policy_support_status(edge.wait_policy)
            mark(scope="edge", ref_id=edge.edge_id, field="wait_policy", value=edge.wait_policy, status=status, reason=reason)
        if edge.ack_required or edge.ack_policy:
            status, reason = _edge_ack_policy_support_status(edge=edge)
            mark(scope="edge", ref_id=edge.edge_id, field="ack_policy", value=edge.ack_policy, status=status, reason=reason)
        temporal_bindings = dict(dict(edge.metadata or {}).get("contract_bindings") or {}).get("temporal")
        temporal_policy = dict(temporal_bindings or dict(edge.metadata or {}).get("temporal_semantics") or {})
        for field, value in temporal_policy.items():
            value = str(value or "").strip()
            if not value:
                continue
            status, reason = _edge_temporal_support_status(field=field, value=value)
            mark(scope="edge", ref_id=edge.edge_id, field=f"temporal.{field}", value=value, status=status, reason=reason)
        if edge.failure_propagation_policy in {"fail_downstream", "isolate_failure", "allow_partial", "coordinator_decides"}:
            mark(scope="edge", ref_id=edge.edge_id, field="failure_propagation_policy", value=edge.failure_propagation_policy, status="supported", reason="TaskGraphSchedulerState 已按边级失败传播策略计算有效节点状态，并由运行路由消费。")
        else:
            mark(scope="edge", ref_id=edge.edge_id, field="failure_propagation_policy", value=edge.failure_propagation_policy, status="unsupported", reason="当前调度器未实现该边级失败传播策略。")
        if edge.result_delivery_policy != "contract_payload_and_refs":
            mark(scope="edge", ref_id=edge.edge_id, field="result_delivery_policy", value=edge.result_delivery_policy, status="partial", reason="结果投递策略已保留，但运行视图和 handoff 状态尚未完整区分不同投递方式。")
        timeout_policy = str(dict(edge.metadata or {}).get("timeout_policy") or "")
        if timeout_policy and timeout_policy != "fail_closed":
            mark(scope="edge", ref_id=edge.edge_id, field="timeout_policy", value=timeout_policy, status="unsupported", reason="当前调度器尚未实现边级 timeout policy。")

    return {
        "authority": "task_system.scheduler_support_report",
        "runtime": "harness.graph_loop",
        "mode": "support_matrix",
        "supported": supported,
        "partial": partial,
        "unsupported": unsupported,
        "supported_count": len(supported),
        "partial_count": len(partial),
        "unsupported_count": len(unsupported),
    }


def _edge_wait_policy_support_status(value: str) -> tuple[str, str]:
    value = str(value or "").strip()
    if value == "wait_handoff_ack":
        return "supported", "edge.wait_policy=wait_handoff_ack 已由 scheduler 消费，会要求 handoff ack 后才释放下游。"
    if value in {"wait_all_upstream_completed", "wait_required_contracts", "wait_any_upstream_completed"}:
        return "partial", "等价节点等待策略已支持，但 edge.wait_policy 目前只作为边级元数据保留；实际 ready 主要由目标节点 wait_policy 决定。"
    if value in {"fire_and_continue", "manual_release"}:
        return "unsupported", "当前 scheduler 尚未把该 edge.wait_policy 作为边级放行算子消费。"
    return "unsupported", "当前 scheduler 未实现该 edge.wait_policy。"


def _edge_ack_policy_support_status(*, edge: TaskGraphRuntimeEdge) -> tuple[str, str]:
    value = str(edge.ack_policy or "").strip()
    if bool(edge.ack_required) is False:
        return "supported", "ack_required=false 时 scheduler 不再要求 handoff ack；ack_policy 仅作为审计字段保留。"
    if value == "explicit_ack":
        return "supported", "显式 ack 已由 wait_handoff_ack / handoff envelope 状态参与下游 ready 判断。"
    if value in {"implicit_ack", "none"}:
        return "partial", "该 ack_policy 会被保存，但 scheduler 不会仅凭该值自动视为确认；若不需要确认，应设置 ack_required=false。"
    if value == "manual_ack":
        return "partial", "handoff envelope 可记录人工确认状态，但独立人工确认工作流尚未完整实现。"
    return "unsupported", "当前 scheduler 未声明支持该 ack_policy。"


def _edge_temporal_support_status(*, field: str, value: str) -> tuple[str, str]:
    field = str(field or "").strip()
    value = str(value or "").strip()
    if field == "trigger_timing":
        if value in {"after_source_success", "after_source_commit"}:
            return "supported", "调度器以源节点完成和有效结果记录作为边触发条件。"
        if value == "after_required_contracts":
            return "partial", "契约引用已进入 RuntimeSpec/Manifest，但 ready 判断仍主要按上游完成和输入绑定处理。"
        if value in {"manual_release", "phase_entry", "phase_exit", "phase_gate_passed"}:
            return "unsupported", "当前运行层尚未实现边级手动释放或 phase 事件触发。"
    if field == "visibility_timing":
        if value in {"after_commit", "next_clock"}:
            return "supported", "timeline gate 使用 accepted result record 和 effective clock 控制下游可见。"
        if value in {"same_clock", "after_ack"}:
            return "partial", "运行层可记录 handoff/ack 状态，但模型输入可见性仍未按该值单独分层。"
        if value in {"next_iteration", "manual_release"}:
            return "unsupported", "当前调度器尚未实现迭代级或边级人工可见性释放。"
    if field == "acknowledgement_timing":
        if value in {"explicit_ack", "ack_before_downstream", "before_downstream_ready"}:
            return "supported", "wait_handoff_ack 和 handoff ack envelope 会阻塞下游 ready。"
        if value in {"no_ack", "none", "implicit_ack"}:
            return "supported", "关闭 ack 或隐式确认时不会额外阻塞下游。"
        if value in {"manual_ack", "ack_before_phase_exit"}:
            return "partial", "ack envelope 可记录确认状态，但 phase exit 级确认尚未成为独立运行门。"
    if field == "propagation_timing":
        if value in {"buffer_until_commit", "blocked_on_failure"}:
            return "supported", "运行层按 accepted result packet 和失败传播策略控制下游释放。"
        if value in {"refs_only", "immediate_refs_only", "summary_only"}:
            return "partial", "结果包和引用可保留，但下游输入装配尚未完整区分该投递方式。"
        if value in {"immediate", "manual_release", "block_until_ack"}:
            return "partial", "调度器有 ack/结果门控，但尚未把该传播值作为独立时序算子。"
    if field in {"phase_timing", "dependency_gate"}:
        if field == "dependency_gate" and value == "handoff_ack":
            return "supported", "dependency_gate=handoff_ack 已由 scheduler 转换为 handoff ack 阻塞。"
        return "partial", "该时序字段会被保留到契约绑定，但运行层只兑现其中一部分门控语义。"
    return "unsupported", "当前调度器未声明支持该边时序字段。"


