from __future__ import annotations

from typing import Any

from .coordination_graph_models import (
    CoordinationGraphEdge,
    CoordinationGraphNode,
    CoordinationGraphSpec,
    CoordinationGraphValidationIssue,
)
from .flow_models import CoordinationTaskDefinition, SpecificTaskRecord, TaskCommunicationProtocol, TopologyTemplate


def compile_coordination_graph_spec(
    *,
    coordination_task: CoordinationTaskDefinition,
    specific_tasks: tuple[SpecificTaskRecord, ...] = (),
    topology_template: TopologyTemplate | None = None,
    communication_protocol: TaskCommunicationProtocol | None = None,
) -> CoordinationGraphSpec:
    task_by_id = {item.task_id: item for item in specific_tasks}
    raw_nodes = list(coordination_task.graph_nodes or ())
    if (not raw_nodes or _prefer_topology_nodes(raw_nodes=raw_nodes, topology_template=topology_template)) and topology_template is not None:
        raw_nodes = list(topology_template.nodes or ())
    nodes = _normalize_nodes(
        raw_nodes=raw_nodes,
        coordination_task=coordination_task,
        task_by_id=task_by_id,
    )
    raw_edges = list(coordination_task.graph_edges or ())
    if (not raw_edges or _prefer_topology_edges(raw_edges=raw_edges, topology_template=topology_template)) and topology_template is not None:
        raw_edges = list(topology_template.edges or ())
    communication_modes = _communication_modes(
        coordination_task=coordination_task,
        raw_edges=raw_edges,
        protocol=communication_protocol,
    )
    edges = _normalize_edges(
        raw_edges=raw_edges,
        nodes=nodes,
        default_mode=communication_modes[0] if communication_modes else coordination_task.handoff_policy or "handoff",
    )
    if not edges and len(nodes) > 1:
        edges = _default_edges(nodes, default_mode=communication_modes[0] if communication_modes else "handoff")
    issues = _validate_graph(
        coordination_task=coordination_task,
        nodes=nodes,
        edges=edges,
        task_by_id=task_by_id,
    )
    source_ids = {edge.source_node_id for edge in edges}
    target_ids = {edge.target_node_id for edge in edges}
    node_ids = [node.node_id for node in nodes]
    start_node_ids = tuple(node_id for node_id in node_ids if node_id not in target_ids)
    terminal_node_ids = tuple(node_id for node_id in node_ids if node_id not in source_ids)
    subtask_refs = tuple(
        dict.fromkeys(
            [
                *coordination_task.subtask_refs,
                *[node.task_id for node in nodes if node.task_id],
            ]
        )
    )
    return CoordinationGraphSpec(
        graph_id=f"coordgraph:{coordination_task.coordination_task_id}",
        coordination_task_id=coordination_task.coordination_task_id,
        domain_id=coordination_task.domain_id,
        task_family=coordination_task.task_family,
        coordinator_agent_id=coordination_task.coordinator_agent_id,
        agent_group_id=coordination_task.agent_group_id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        subtask_refs=subtask_refs,
        communication_modes=communication_modes,
        start_node_ids=start_node_ids,
        terminal_node_ids=terminal_node_ids,
        issues=tuple(issues),
        diagnostics={
            "source": "task_system.coordination_graph_compiler",
            "topology_template_id": str(getattr(topology_template, "template_id", "") or ""),
            "communication_protocol_id": str(getattr(communication_protocol, "protocol_id", "") or ""),
        },
    )


def _normalize_nodes(
    *,
    raw_nodes: list[Any],
    coordination_task: CoordinationTaskDefinition,
    task_by_id: dict[str, SpecificTaskRecord],
) -> list[CoordinationGraphNode]:
    normalized: list[CoordinationGraphNode] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_nodes, start=1):
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("node_id") or raw.get("id") or f"node_{index}").strip()
        if not node_id or node_id in seen:
            continue
        task_id = str(raw.get("task_id") or raw.get("subtask_ref") or "").strip()
        task = task_by_id.get(task_id)
        agent_id = str(raw.get("agent_id") or "").strip()
        if not agent_id and str(raw.get("role") or "") == "coordinator":
            agent_id = coordination_task.coordinator_agent_id
        title = str(raw.get("title") or raw.get("label") or "").strip()
        if not title and task is not None:
            title = task.task_title
        normalized.append(
            CoordinationGraphNode(
                node_id=node_id,
                title=title or node_id,
                node_type=str(raw.get("node_type") or ("subtask" if task_id else "agent_role")).strip(),
                role=str(raw.get("role") or ("coordinator" if agent_id == coordination_task.coordinator_agent_id else "participant")).strip(),
                agent_id=agent_id or coordination_task.coordinator_agent_id,
                runtime_lane=str(raw.get("lane") or raw.get("runtime_lane") or "").strip(),
                task_id=task_id,
                task_family=str(raw.get("task_family") or getattr(task, "task_family", "") or coordination_task.task_family).strip(),
                metadata={
                    key: value
                    for key, value in raw.items()
                    if key not in {"node_id", "id", "title", "label", "node_type", "role", "agent_id", "lane", "runtime_lane", "task_id", "subtask_ref", "task_family"}
                },
            )
        )
        seen.add(node_id)
    if not normalized:
        normalized.append(
            CoordinationGraphNode(
                node_id="coordinator",
                title="协调者",
                node_type="coordinator",
                role="coordinator",
                agent_id=coordination_task.coordinator_agent_id,
                task_family=coordination_task.task_family,
            )
        )
    return normalized


def _prefer_topology_nodes(
    *,
    raw_nodes: list[Any],
    topology_template: TopologyTemplate | None,
) -> bool:
    if topology_template is None or not topology_template.nodes:
        return False
    node_types = {
        str(dict(item).get("node_type") or "").strip()
        for item in raw_nodes
        if isinstance(item, dict)
    }
    task_refs = [
        str(dict(item).get("task_id") or dict(item).get("subtask_ref") or "").strip()
        for item in raw_nodes
        if isinstance(item, dict)
    ]
    node_ids = {
        str(dict(item).get("node_id") or "").strip()
        for item in raw_nodes
        if isinstance(item, dict)
    }
    if any(task_refs):
        return False
    generic_ids = all(node_id == "coordinator" or node_id.startswith("agent_") for node_id in node_ids if node_id)
    generic_types = node_types.issubset({"", "coordinator", "agent_role"})
    return generic_ids and generic_types


def _normalize_edges(
    *,
    raw_edges: list[Any],
    nodes: list[CoordinationGraphNode],
    default_mode: str,
) -> list[CoordinationGraphEdge]:
    node_ids = {node.node_id for node in nodes}
    normalized: list[CoordinationGraphEdge] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(raw_edges, start=1):
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("from") or raw.get("source") or raw.get("source_node_id") or "").strip()
        target = str(raw.get("to") or raw.get("target") or raw.get("target_node_id") or "").strip()
        if not source or not target or source not in node_ids or target not in node_ids:
            continue
        if (source, target) in seen:
            continue
        normalized.append(
            CoordinationGraphEdge(
                edge_id=str(raw.get("edge_id") or raw.get("id") or f"edge_{index}").strip(),
                source_node_id=source,
                target_node_id=target,
                mode=str(raw.get("mode") or raw.get("policy") or raw.get("message_type") or default_mode).strip(),
                metadata={
                    key: value
                    for key, value in raw.items()
                    if key not in {"edge_id", "id", "from", "to", "source", "target", "source_node_id", "target_node_id", "mode", "policy", "message_type"}
                },
            )
        )
        seen.add((source, target))
    return normalized


def _prefer_topology_edges(
    *,
    raw_edges: list[Any],
    topology_template: TopologyTemplate | None,
) -> bool:
    if topology_template is None or not topology_template.edges:
        return False
    pairs = [
        (
            str(dict(item).get("from") or dict(item).get("source") or dict(item).get("source_node_id") or "").strip(),
            str(dict(item).get("to") or dict(item).get("target") or dict(item).get("target_node_id") or "").strip(),
        )
        for item in raw_edges
        if isinstance(item, dict)
    ]
    if not pairs:
        return True
    generic_pairs = all(
        (source == "coordinator" and target.startswith("agent_"))
        or (target == "coordinator" and source.startswith("agent_"))
        for source, target in pairs
        if source and target
    )
    return generic_pairs


def _default_edges(nodes: list[CoordinationGraphNode], *, default_mode: str) -> list[CoordinationGraphEdge]:
    coordinator = next((node.node_id for node in nodes if node.role == "coordinator"), nodes[0].node_id)
    return [
        CoordinationGraphEdge(
            edge_id=f"edge_{index}",
            source_node_id=node.node_id,
            target_node_id=coordinator,
            mode=default_mode,
        )
        for index, node in enumerate(nodes, start=1)
        if node.node_id != coordinator
    ]


def _communication_modes(
    *,
    coordination_task: CoordinationTaskDefinition,
    raw_edges: list[Any],
    protocol: TaskCommunicationProtocol | None,
) -> tuple[str, ...]:
    values: list[str] = []
    values.extend(str(item).strip() for item in coordination_task.communication_modes if str(item).strip())
    for edge in raw_edges:
        if isinstance(edge, dict):
            values.append(str(edge.get("mode") or edge.get("policy") or edge.get("message_type") or "").strip())
    if protocol is not None:
        values.extend(str(item).strip() for item in protocol.message_types if str(item).strip())
    return tuple(dict.fromkeys(value for value in values if value))


def _validate_graph(
    *,
    coordination_task: CoordinationTaskDefinition,
    nodes: list[CoordinationGraphNode],
    edges: list[CoordinationGraphEdge],
    task_by_id: dict[str, SpecificTaskRecord],
) -> list[CoordinationGraphValidationIssue]:
    issues: list[CoordinationGraphValidationIssue] = []
    if not nodes:
        issues.append(CoordinationGraphValidationIssue(code="empty_graph", message="协调任务图不能为空"))
        return issues
    node_ids = {node.node_id for node in nodes}
    if not any(node.role == "coordinator" for node in nodes):
        issues.append(CoordinationGraphValidationIssue(code="missing_coordinator", message="协调任务图必须有协调者节点"))
    if len(nodes) > 1 and not edges:
        issues.append(CoordinationGraphValidationIssue(code="missing_edges", message="多节点协调任务必须配置通信边"))
    for edge in edges:
        if edge.source_node_id not in node_ids or edge.target_node_id not in node_ids:
            issues.append(
                CoordinationGraphValidationIssue(
                    code="invalid_edge_endpoint",
                    message="通信边引用了不存在的节点",
                    edge_id=edge.edge_id,
                )
            )
    for node in nodes:
        if not node.task_id:
            continue
        task = task_by_id.get(node.task_id)
        if task is None:
            issues.append(
                CoordinationGraphValidationIssue(
                    code="missing_subtask",
                    message=f"节点引用的特定任务不存在：{node.task_id}",
                    node_id=node.node_id,
                )
            )
            continue
        if coordination_task.domain_id and task.task_family != coordination_task.task_family:
            issues.append(
                CoordinationGraphValidationIssue(
                    code="cross_domain_subtask",
                    message=f"节点引用了跨域特定任务：{node.task_id}",
                    node_id=node.node_id,
                )
            )
    return issues
