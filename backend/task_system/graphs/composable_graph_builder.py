from __future__ import annotations

from typing import Any

from task_system.graphs.composable_graph_models import (
    ComposableGraphView,
    ComposableUnit,
    GraphModuleRuntimePlan,
    UnitInterface,
    UnitPort,
    UnitPortEdge,
)
from task_system.compiler.layered_graph_normalizer import normalize_task_graph_layers
from task_system.graphs.task_graph_models import TaskGraphDefinition, TaskGraphEdgeDefinition, TaskGraphNodeDefinition


RESOURCE_NODE_TYPES = {
    "memory",
    "memory_resource",
    "memory_repository",
    "memory_collection",
    "artifact_repository",
    "thread_ledger",
    "progress_ledger",
    "issue_ledger",
    "runtime_state_store",
    "working_memory_store",
}
TOOL_NODE_TYPES = {"tool"}
HUMAN_GATE_NODE_TYPES = {"manual_gate", "review_gate"}
RUNTIME_MONITOR_NODE_TYPES = {"runtime_monitor"}


def build_composable_graph_view(
    *,
    graph: TaskGraphDefinition,
    layered_graph: dict[str, Any] | None = None,
) -> ComposableGraphView:
    """Build the Unit/Port view from derived graph data plus explicit metadata overrides."""
    layered = layered_graph if layered_graph is not None else normalize_task_graph_layers(graph)
    timeline_blocks = [
        dict(item)
        for item in list(layered.get("timeline_blocks") or [])
        if isinstance(item, dict) and item.get("migration_only") is True
    ]
    units = [
        *[_unit_from_node(node) for node in graph.nodes],
        *[_unit_from_timeline_block(graph=graph, block=block, index=index) for index, block in enumerate(timeline_blocks)],
    ]
    interfaces = [
        *[_interface_from_node(node) for node in graph.nodes],
        *[
            _interface_from_timeline_block(block=block, unit_id=_graph_module_id_from_block(block, index))
            for index, block in enumerate(timeline_blocks)
        ],
    ]
    port_edges = [_port_edge_from_graph_edge(edge) for edge in graph.edges]
    graph_module_runtime = [
        _graph_module_runtime_from_timeline_block(graph=graph, block=block, unit_id=_graph_module_id_from_block(block, index))
        for index, block in enumerate(timeline_blocks)
        if str(block.get("linked_graph_id") or "").strip()
    ]
    overlay = _composable_overlay(graph)
    units = _merge_units(units, _units_from_overlay(overlay))
    interfaces = _merge_interfaces(interfaces, _interfaces_from_overlay(overlay))
    port_edges = _merge_port_edges(port_edges, _port_edges_from_overlay(overlay))
    graph_module_runtime = _merge_graph_module_runtime(graph_module_runtime, _graph_module_runtime_from_overlay(overlay, graph=graph))
    issues = tuple(
        [
            *_composable_issues(units=units, interfaces=interfaces, port_edges=port_edges, graph_module_runtime=graph_module_runtime),
            *_overlay_issues(overlay),
        ]
    )
    return ComposableGraphView(
        authority="task_system.composable_graph_view",
        graph={
            "graph_id": graph.graph_id,
            "title": graph.title,
            "domain_id": graph.domain_id,
            "graph_contract_id": graph.graph_contract_id,
            "contract_bindings": dict(graph.contract_bindings or {}),
            "default_protocol_id": graph.default_protocol_id,
            "source_model": "task_system.task_graph_definition",
        },
        units=tuple(units),
        interfaces=tuple(interfaces),
        port_edges=tuple(port_edges),
        graph_module_runtime=tuple(graph_module_runtime),
        diagnostics={
            "mode": "metadata_overlay_shadow_model" if overlay else "read_only_shadow_model",
            "source": "task_system.task_graph_definition",
            "node_unit_count": len(graph.nodes),
            "timeline_block_unit_count": len(timeline_blocks),
            "timeline_block_units_migration_only": True,
            "graph_module_runtime_count": len(graph_module_runtime),
            "legacy_edge_count": len(graph.edges),
            "overlay_unit_count": len(_overlay_list(overlay, "units")),
            "overlay_interface_count": len(_overlay_list(overlay, "interfaces")),
            "overlay_port_edge_count": len(_overlay_list(overlay, "port_edges")),
            "overlay_graph_module_runtime_count": len(_overlay_list(overlay, "graph_module_runtime")),
        },
        issues=issues,
    )


def _composable_overlay(graph: TaskGraphDefinition) -> dict[str, Any]:
    metadata = dict(graph.metadata or {})
    overlay = metadata.get("composable_graph")
    return dict(overlay) if isinstance(overlay, dict) else {}


def _overlay_list(overlay: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in list(overlay.get(key) or [])
        if isinstance(item, dict)
    ]


def _merge_units(derived: list[ComposableUnit], explicit: list[ComposableUnit]) -> list[ComposableUnit]:
    merged = {item.unit_id: item for item in derived}
    for item in explicit:
        if not item.unit_id:
            continue
        merged[item.unit_id] = item
    return list(merged.values())


def _merge_interfaces(derived: list[UnitInterface], explicit: list[UnitInterface]) -> list[UnitInterface]:
    merged = {item.interface_id: item for item in derived}
    for item in explicit:
        if not item.interface_id:
            continue
        merged[item.interface_id] = item
    return list(merged.values())


def _merge_port_edges(derived: list[UnitPortEdge], explicit: list[UnitPortEdge]) -> list[UnitPortEdge]:
    merged = {item.edge_id: item for item in derived}
    for item in explicit:
        if not item.edge_id:
            continue
        merged[item.edge_id] = item
    return list(merged.values())


def _merge_graph_module_runtime(derived: list[GraphModuleRuntimePlan], explicit: list[GraphModuleRuntimePlan]) -> list[GraphModuleRuntimePlan]:
    merged = {item.plan_id: item for item in derived}
    for item in explicit:
        if not item.plan_id:
            continue
        merged[item.plan_id] = item
    return list(merged.values())


def _units_from_overlay(overlay: dict[str, Any]) -> list[ComposableUnit]:
    return [_unit_from_overlay_payload(item) for item in _overlay_list(overlay, "units")]


def _interfaces_from_overlay(overlay: dict[str, Any]) -> list[UnitInterface]:
    return [_interface_from_overlay_payload(item) for item in _overlay_list(overlay, "interfaces")]


def _port_edges_from_overlay(overlay: dict[str, Any]) -> list[UnitPortEdge]:
    return [_port_edge_from_overlay_payload(item) for item in _overlay_list(overlay, "port_edges")]


def _graph_module_runtime_from_overlay(overlay: dict[str, Any], *, graph: TaskGraphDefinition) -> list[GraphModuleRuntimePlan]:
    return [_graph_module_runtime_from_overlay_payload(item, graph=graph) for item in _overlay_list(overlay, "graph_module_runtime")]


def _overlay_issues(overlay: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for index, unit in enumerate(_overlay_list(overlay, "units")):
        if not str(unit.get("unit_id") or "").strip():
            issues.append(_issue("overlay_unit_id_missing", f"显式 Unit 覆盖层第 {index + 1} 项缺少 unit_id", severity="error"))
    for index, interface in enumerate(_overlay_list(overlay, "interfaces")):
        if not str(interface.get("interface_id") or "").strip():
            issues.append(_issue("overlay_interface_id_missing", f"显式接口覆盖层第 {index + 1} 项缺少 interface_id", severity="error"))
        if not str(interface.get("unit_id") or "").strip():
            issues.append(_issue("overlay_interface_unit_missing", f"显式接口覆盖层第 {index + 1} 项缺少 unit_id", severity="error"))
        ports = [
            *_overlay_port_list(interface, "input_ports"),
            *_overlay_port_list(interface, "output_ports"),
        ]
        for port_index, port in enumerate(ports):
            if not str(port.get("port_id") or "").strip():
                issues.append(_issue("overlay_port_id_missing", f"显式接口覆盖层第 {index + 1} 项的第 {port_index + 1} 个端口缺少 port_id", severity="error"))
    for index, edge in enumerate(_overlay_list(overlay, "port_edges")):
        if not str(edge.get("edge_id") or "").strip():
            issues.append(_issue("overlay_port_edge_id_missing", f"显式端口边覆盖层第 {index + 1} 项缺少 edge_id", severity="error"))
    for index, plan in enumerate(_overlay_list(overlay, "graph_module_runtime")):
        if not str(plan.get("plan_id") or "").strip():
            issues.append(_issue("overlay_graph_module_runtime_plan_id_missing", f"显式图模块运行覆盖层第 {index + 1} 项缺少 plan_id", severity="error"))
    return issues


def _unit_from_overlay_payload(payload: dict[str, Any]) -> ComposableUnit:
    unit_id = str(payload.get("unit_id") or "").strip()
    unit_type = str(payload.get("unit_type") or "node").strip() or "node"
    return ComposableUnit(
        unit_id=unit_id,
        unit_type=unit_type,  # type: ignore[arg-type]
        title=str(payload.get("title") or unit_id or "可组合单元").strip(),
        ref=dict(payload.get("ref") or {}),
        interface_id=str(payload.get("interface_id") or "").strip(),
        runtime_policy=dict(payload.get("runtime_policy") or {}),
        phase_id=str(payload.get("phase_id") or "").strip(),
        sequence_index=int(payload.get("sequence_index") or 0),
        source_kind=str(payload.get("source_kind") or "metadata.composable_graph").strip() or "metadata.composable_graph",
        metadata={
            **dict(payload.get("metadata") or {}),
            "explicit_overlay": True,
        },
    )


def _interface_from_overlay_payload(payload: dict[str, Any]) -> UnitInterface:
    interface_id = str(payload.get("interface_id") or "").strip()
    unit_id = str(payload.get("unit_id") or "").strip()
    return UnitInterface(
        interface_id=interface_id,
        unit_id=unit_id,
        display_name_zh=str(payload.get("display_name_zh") or interface_id or unit_id or "可组合接口").strip(),
        input_ports=tuple(_port_from_overlay_payload(item, direction="input") for item in _overlay_port_list(payload, "input_ports")),
        output_ports=tuple(_port_from_overlay_payload(item, direction="output") for item in _overlay_port_list(payload, "output_ports")),
        memory_visibility_policy=str(payload.get("memory_visibility_policy") or "explicit_refs_only").strip() or "explicit_refs_only",
        artifact_visibility_policy=str(payload.get("artifact_visibility_policy") or "refs_only").strip() or "refs_only",
        runtime_state_policy=str(payload.get("runtime_state_policy") or "status_only").strip() or "status_only",
        version=str(payload.get("version") or "v1").strip() or "v1",
        metadata={
            **dict(payload.get("metadata") or {}),
            "explicit_overlay": True,
        },
    )


def _overlay_port_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [dict(item) for item in list(payload.get(key) or []) if isinstance(item, dict)]


def _port_from_overlay_payload(payload: dict[str, Any], *, direction: str) -> UnitPort:
    port_id = str(payload.get("port_id") or "").strip()
    return UnitPort(
        port_id=port_id,
        title=str(payload.get("title") or port_id or "端口").strip(),
        direction=direction,  # type: ignore[arg-type]
        payload_contract_id=str(payload.get("payload_contract_id") or "").strip(),
        required=bool(payload.get("required", True)),
        status_required=str(payload.get("status_required") or "").strip(),
        visibility_policy=str(payload.get("visibility_policy") or "").strip(),
        metadata=dict(payload.get("metadata") or {}),
    )


def _port_edge_from_overlay_payload(payload: dict[str, Any]) -> UnitPortEdge:
    return UnitPortEdge(
        edge_id=str(payload.get("edge_id") or "").strip(),
        source_unit_id=str(payload.get("source_unit_id") or "").strip(),
        source_port_id=str(payload.get("source_port_id") or "").strip(),
        target_unit_id=str(payload.get("target_unit_id") or "").strip(),
        target_port_id=str(payload.get("target_port_id") or "").strip(),
        payload_contract_id=str(payload.get("payload_contract_id") or "").strip(),
        edge_type=str(payload.get("edge_type") or "handoff").strip() or "handoff",
        temporal_semantics=dict(payload.get("temporal_semantics") or {}),
        handoff=dict(payload.get("handoff") or {}),
        metadata={
            **dict(payload.get("metadata") or {}),
            "explicit_overlay": True,
        },
    )


def _graph_module_runtime_from_overlay_payload(payload: dict[str, Any], *, graph: TaskGraphDefinition) -> GraphModuleRuntimePlan:
    plan_id = str(payload.get("plan_id") or "").strip()
    return GraphModuleRuntimePlan(
        plan_id=plan_id,
        importing_graph_id=str(payload.get("importing_graph_id") or graph.graph_id).strip(),
        unit_id=str(payload.get("unit_id") or "").strip(),
        linked_graph_id=str(payload.get("linked_graph_id") or "").strip(),
        version_ref=str(payload.get("version_ref") or "").strip(),
        handoff_contract_id=str(payload.get("handoff_contract_id") or "").strip(),
        input_port_id=str(payload.get("input_port_id") or "input.default").strip() or "input.default",
        output_port_id=str(payload.get("output_port_id") or "output.default").strip() or "output.default",
        isolation_policy=str(payload.get("isolation_policy") or "isolated_per_graph_module_run").strip() or "isolated_per_graph_module_run",
        visibility_policy=str(payload.get("visibility_policy") or "committed_only").strip() or "committed_only",
        detach_policy=str(payload.get("detach_policy") or "preserve_version_anchor").strip() or "preserve_version_anchor",
        metadata={
            **dict(payload.get("metadata") or {}),
            "explicit_overlay": True,
        },
    )


def _unit_from_node(node: TaskGraphNodeDefinition) -> ComposableUnit:
    node_type = str(node.node_type or "").strip()
    unit_type = _unit_type_from_node_type(node_type)
    unit_id = _node_unit_id(node.node_id)
    return ComposableUnit(
        unit_id=unit_id,
        unit_type=unit_type,
        title=str(node.title or node.node_id or "").strip(),
        ref={"node_id": node.node_id, "node_type": node_type},
        interface_id=_node_interface_id(node.node_id),
        runtime_policy={
            "execution_mode": node.execution_mode,
            "wait_policy": node.wait_policy,
            "join_policy": node.join_policy,
            "runtime_lane": node.runtime_lane,
        },
        phase_id=node.phase_id,
        sequence_index=int(node.sequence_index or 0),
        source_kind="task_graph_node",
        metadata={
            "task_id": node.task_id,
            "agent_id": node.agent_id,
            "agent_group_id": node.agent_group_id,
            "main_chain": bool(node.main_chain),
            "blocks_phase_exit": bool(node.blocks_phase_exit),
            "contract_bindings": dict(node.contract_bindings or {}),
            "raw_metadata": dict(node.metadata or {}),
        },
    )


def _unit_from_timeline_block(*, graph: TaskGraphDefinition, block: dict[str, Any], index: int) -> ComposableUnit:
    unit_id = _graph_module_id_from_block(block, index)
    linked_graph_id = str(block.get("linked_graph_id") or "").strip()
    version_ref = str(block.get("version_ref") or "").strip()
    handoff_contract_id = _timeline_block_handoff_contract_id(block)
    return ComposableUnit(
        unit_id=unit_id,
        unit_type="graph",
        title=str(block.get("title") or block.get("block_id") or f"图块 {index + 1}").strip(),
        ref={
            "graph_id": linked_graph_id,
            "importing_graph_id": graph.graph_id,
            "timeline_block_id": str(block.get("block_id") or "").strip(),
            "version_ref": version_ref,
        },
        interface_id=f"interface.graph.{_safe_identifier(str(block.get('block_id') or index + 1))}",
        runtime_policy={
            "execution_mode": "graph_module_run" if linked_graph_id else "phase_window",
            "task_run_scope_policy": "isolated_per_graph_module_run" if linked_graph_id else "same_graph_phase_window",
            "wait_policy": "wait_for_output_port_commit",
            "detach_policy": str(block.get("detach_policy") or "preserve_version_anchor").strip() or "preserve_version_anchor",
        },
        phase_id=str(block.get("phase_id") or "").strip(),
        sequence_index=index,
        source_kind="timeline_block",
        metadata={
            "derived": bool(block.get("derived", False)),
            "block_type": str(block.get("block_type") or "").strip(),
            "entry_node_id": str(block.get("entry_node_id") or "").strip(),
            "exit_node_id": str(block.get("exit_node_id") or "").strip(),
            "handoff_contract_id": handoff_contract_id,
            "contract_bindings": dict(block.get("contract_bindings") or {}),
            "visibility_policy": str(block.get("visibility_policy") or "committed_only").strip() or "committed_only",
            "raw_metadata": dict(block.get("metadata") or {}),
        },
    )


def _interface_from_node(node: TaskGraphNodeDefinition) -> UnitInterface:
    node_id = str(node.node_id or "").strip()
    input_contract_id = str(node.input_contract_id or "").strip()
    output_contract_id = str(node.output_contract_id or "").strip()
    node_contract_id = str(node.node_contract_id or "").strip()
    bindings = dict(getattr(node, "contract_bindings", {}) or {})
    schema_bindings = dict(bindings.get("schema") or {})
    execution_bindings = dict(bindings.get("execution") or {})
    input_contract_id = str(schema_bindings.get("input_contract_id") or input_contract_id).strip()
    output_contract_id = str(schema_bindings.get("output_contract_id") or output_contract_id).strip()
    node_contract_id = str(execution_bindings.get("node_contract_id") or node_contract_id).strip()
    metadata = dict(node.metadata or {})
    context_visibility = dict(node.context_visibility_policy or {})
    return UnitInterface(
        interface_id=_node_interface_id(node_id),
        unit_id=_node_unit_id(node_id),
        display_name_zh=f"{node.title or node_id}接口",
        input_ports=(
            UnitPort(
                port_id="input.default",
                title="默认输入",
                direction="input",
                payload_contract_id=input_contract_id or node_contract_id,
                required=True,
                visibility_policy=str(context_visibility.get("upstream_outputs") or "explicit_handoff").strip() or "explicit_handoff",
            ),
        ),
        output_ports=(
            UnitPort(
                port_id="output.default",
                title="默认输出",
                direction="output",
                payload_contract_id=output_contract_id or node_contract_id,
                required=True,
                status_required=str(metadata.get("output_status_required") or "").strip(),
                visibility_policy=str(metadata.get("output_visibility_policy") or "contract_payload_and_refs").strip() or "contract_payload_and_refs",
            ),
        ),
        memory_visibility_policy=str(context_visibility.get("memory_scopes") or "explicit_refs_only"),
        artifact_visibility_policy=str(dict(node.artifact_policy or {}).get("visibility_policy") or "refs_only"),
        runtime_state_policy="status_only",
        version=str(metadata.get("interface_version") or "v1").strip() or "v1",
        metadata={
            "node_contract_id": node_contract_id,
            "input_contract_id": input_contract_id,
            "output_contract_id": output_contract_id,
            "contract_bindings": bindings,
        },
    )


def _interface_from_timeline_block(*, block: dict[str, Any], unit_id: str) -> UnitInterface:
    handoff_contract_id = _timeline_block_handoff_contract_id(block)
    visibility_policy = str(block.get("visibility_policy") or "committed_only").strip() or "committed_only"
    block_id = str(block.get("block_id") or unit_id).strip()
    return UnitInterface(
        interface_id=f"interface.graph.{_safe_identifier(block_id)}",
        unit_id=unit_id,
        display_name_zh=f"{str(block.get('title') or block_id).strip()}接口",
        input_ports=(
            UnitPort(
                port_id="input.default",
                title="图输入包",
                direction="input",
                payload_contract_id=handoff_contract_id,
                required=True,
                visibility_policy="explicit_handoff_packet",
            ),
        ),
        output_ports=(
            UnitPort(
                port_id="output.default",
                title="图提交包",
                direction="output",
                payload_contract_id=handoff_contract_id,
                required=True,
                status_required="committed" if visibility_policy == "committed_only" else "",
                visibility_policy=visibility_policy,
            ),
        ),
        memory_visibility_policy="isolated_until_commit",
        artifact_visibility_policy=visibility_policy,
        runtime_state_policy="run_handle_and_status",
        version=str(block.get("version_ref") or "v1").strip() or "v1",
        metadata={
            "timeline_block_id": block_id,
            "linked_graph_id": str(block.get("linked_graph_id") or "").strip(),
            "entry_node_id": str(block.get("entry_node_id") or "").strip(),
            "exit_node_id": str(block.get("exit_node_id") or "").strip(),
            "contract_bindings": dict(block.get("contract_bindings") or {}),
        },
    )


def _port_edge_from_graph_edge(edge: TaskGraphEdgeDefinition) -> UnitPortEdge:
    bindings = dict(getattr(edge, "contract_bindings", {}) or {})
    schema_bindings = dict(bindings.get("schema") or {})
    return UnitPortEdge(
        edge_id=edge.edge_id,
        source_unit_id=_node_unit_id(edge.source_node_id),
        source_port_id=str(dict(edge.metadata or {}).get("source_port_id") or "output.default").strip() or "output.default",
        target_unit_id=_node_unit_id(edge.target_node_id),
        target_port_id=str(dict(edge.metadata or {}).get("target_port_id") or "input.default").strip() or "input.default",
        payload_contract_id=str(schema_bindings.get("payload_contract_id") or edge.payload_contract_id).strip(),
        edge_type=edge.edge_type,
        temporal_semantics=_temporal_semantics_from_edge(edge),
        handoff={
            "ack_policy": edge.ack_policy,
            "ack_required": bool(edge.ack_required),
            "timeout_policy": edge.timeout_policy,
            "wait_policy": edge.wait_policy,
            "failure_propagation_policy": edge.failure_propagation_policy,
            "result_delivery_policy": edge.result_delivery_policy,
        },
        metadata={
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "legacy_edge": True,
            "contract_bindings": bindings,
            "raw_metadata": dict(edge.metadata or {}),
        },
    )


def _graph_module_runtime_from_timeline_block(
    *,
    graph: TaskGraphDefinition,
    block: dict[str, Any],
    unit_id: str,
) -> GraphModuleRuntimePlan:
    block_id = str(block.get("block_id") or unit_id).strip()
    return GraphModuleRuntimePlan(
        plan_id=f"graph_module_runtime.{_safe_identifier(block_id)}",
        importing_graph_id=graph.graph_id,
        unit_id=unit_id,
        linked_graph_id=str(block.get("linked_graph_id") or "").strip(),
        version_ref=str(block.get("version_ref") or "").strip(),
        handoff_contract_id=_timeline_block_handoff_contract_id(block),
        input_port_id="input.default",
        output_port_id="output.default",
        isolation_policy="isolated_per_graph_module_run",
        visibility_policy=str(block.get("visibility_policy") or "committed_only").strip() or "committed_only",
        detach_policy=str(block.get("detach_policy") or "preserve_version_anchor").strip() or "preserve_version_anchor",
        metadata={
            "timeline_block_id": block_id,
            "phase_id": str(block.get("phase_id") or "").strip(),
            "entry_node_id": str(block.get("entry_node_id") or "").strip(),
            "exit_node_id": str(block.get("exit_node_id") or "").strip(),
            "contract_bindings": dict(block.get("contract_bindings") or {}),
        },
    )


def _timeline_block_handoff_contract_id(block: dict[str, Any]) -> str:
    bindings = dict(block.get("contract_bindings") or {})
    handoff = dict(bindings.get("handoff") or {})
    return str(handoff.get("handoff_contract_id") or block.get("handoff_contract_id") or "").strip()


def _unit_type_from_node_type(node_type: str) -> str:
    if node_type in RESOURCE_NODE_TYPES:
        return "resource"
    if node_type in HUMAN_GATE_NODE_TYPES:
        return "human_gate"
    if node_type in TOOL_NODE_TYPES:
        return "tool"
    if node_type in RUNTIME_MONITOR_NODE_TYPES:
        return "runtime_monitor"
    return "node"


def _temporal_semantics_from_edge(edge: TaskGraphEdgeDefinition) -> dict[str, Any]:
    metadata = dict(edge.metadata or {})
    return {
        "trigger_timing": str(metadata.get("trigger_timing") or "after_source_success"),
        "visibility_timing": str(metadata.get("visibility_timing") or "after_commit"),
        "acknowledgement_timing": str(metadata.get("acknowledgement_timing") or edge.ack_policy or "explicit_ack"),
        "propagation_timing": str(metadata.get("propagation_timing") or "buffer_until_commit"),
        "phase_timing": str(metadata.get("phase_timing") or metadata.get("temporal_type") or ""),
    }


def _composable_issues(
    *,
    units: list[ComposableUnit],
    interfaces: list[UnitInterface],
    port_edges: list[UnitPortEdge],
    graph_module_runtime: list[GraphModuleRuntimePlan],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    unit_ids = {unit.unit_id for unit in units}
    interface_by_unit = {interface.unit_id: interface for interface in interfaces}
    port_keys = {
        (interface.unit_id, port.port_id)
        for interface in interfaces
        for port in [*interface.input_ports, *interface.output_ports]
    }
    for unit in units:
        if not unit.unit_id:
            issues.append(_issue("unit_id_missing", "可组合单元缺少 unit_id", severity="error"))
            continue
        if unit.unit_id not in interface_by_unit:
            issues.append(_issue("unit_interface_missing", "可组合单元缺少接口", unit_id=unit.unit_id))
        if (
            unit.unit_type == "graph"
            and not str(unit.ref.get("graph_id") or "").strip()
            and not bool(unit.metadata.get("derived"))
        ):
            issues.append(_issue("graph_module_link_missing", "图模块缺少 linked_graph_id，只能作为本图阶段窗口处理", unit_id=unit.unit_id, severity="warning"))
    for interface in interfaces:
        if not interface.interface_id:
            issues.append(_issue("unit_interface_id_missing", "可组合接口缺少 interface_id", unit_id=interface.unit_id, severity="error"))
        if not interface.unit_id:
            issues.append(_issue("unit_interface_unit_missing", "可组合接口缺少 unit_id", severity="error"))
        if interface.unit_id and interface.unit_id not in unit_ids:
            issues.append(_issue("unit_interface_unit_missing", "可组合接口绑定的单元不存在", unit_id=interface.unit_id, severity="error"))
        if not [*interface.input_ports, *interface.output_ports]:
            issues.append(_issue("unit_interface_ports_missing", "可组合接口没有声明任何输入或输出端口", unit_id=interface.unit_id, severity="warning"))
        for port in [*interface.input_ports, *interface.output_ports]:
            if not port.port_id:
                issues.append(_issue("unit_port_id_missing", "可组合接口存在缺少 port_id 的端口", unit_id=interface.unit_id, severity="error"))
    for edge in port_edges:
        if not edge.edge_id:
            issues.append(_issue("port_edge_id_missing", "端口边缺少 edge_id", severity="error"))
            continue
        if edge.source_unit_id not in unit_ids:
            issues.append(_issue("port_edge_source_unit_missing", "端口边的源单元不存在", edge_id=edge.edge_id, severity="error"))
        if edge.target_unit_id not in unit_ids:
            issues.append(_issue("port_edge_target_unit_missing", "端口边的目标单元不存在", edge_id=edge.edge_id, severity="error"))
        if (edge.source_unit_id, edge.source_port_id) not in port_keys:
            issues.append(_issue("port_edge_source_port_missing", "端口边的源端口不存在", edge_id=edge.edge_id, severity="error"))
        if (edge.target_unit_id, edge.target_port_id) not in port_keys:
            issues.append(_issue("port_edge_target_port_missing", "端口边的目标端口不存在", edge_id=edge.edge_id, severity="error"))
    for plan in graph_module_runtime:
        if not plan.version_ref:
            issues.append(_issue("graph_module_version_anchor_missing", "图模块运行缺少版本锚点", unit_id=plan.unit_id, severity="warning"))
        if not plan.handoff_contract_id:
            issues.append(_issue("graph_module_handoff_contract_missing", "图模块运行缺少交接契约", unit_id=plan.unit_id, severity="warning"))
    return issues


def _issue(
    code: str,
    message: str,
    *,
    unit_id: str = "",
    edge_id: str = "",
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        "unit_id": unit_id,
        "edge_id": edge_id,
        "authority": "task_system.composable_graph_issue",
    }


def _node_unit_id(node_id: str) -> str:
    return f"unit.node.{_safe_identifier(node_id)}"


def _node_interface_id(node_id: str) -> str:
    return f"interface.node.{_safe_identifier(node_id)}"


def _graph_module_id_from_block(block: dict[str, Any], index: int) -> str:
    return f"unit.graph.{_safe_identifier(str(block.get('block_id') or index + 1))}"


def _safe_identifier(value: str) -> str:
    sanitized = str(value or "").strip().replace(":", ".").replace("/", ".").replace("\\", ".")
    sanitized = ".".join(part for part in sanitized.split(".") if part)
    return sanitized or "unknown"
