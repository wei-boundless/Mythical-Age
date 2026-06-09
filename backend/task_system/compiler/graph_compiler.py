from __future__ import annotations

from typing import Any

from harness.graph.models import safe_id, stable_hash

from .configurator_write_contracts import build_configurator_write_contract, configuration_prototype_catalog
from .edge_contract_models import build_edge_contract_index
from .models import GraphCompilationUnit, GraphCompileIssue, compile_report
from .node_contract_models import build_node_contract_index
from .resource_contract_models import build_resource_contract_index
from .system_node_contracts import build_maintenance_contract, build_system_node_contract_index


GRAPH_COMPILER_VERSION = "graph_compiler.mvp.v1"


def build_graph_compilation_unit(
    *,
    graph_id: str,
    graph_title: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    resource_nodes: list[dict[str, Any]],
    environment: dict[str, Any],
    permissions: dict[str, Any],
    tools: dict[str, Any],
    control: dict[str, Any],
    protocol_index: dict[str, Any],
    graph_metadata: dict[str, Any] | None = None,
    graph_runtime_policy: dict[str, Any] | None = None,
    graph_context_policy: dict[str, Any] | None = None,
) -> GraphCompilationUnit:
    metadata = dict(graph_metadata or {})
    runtime_policy = dict(graph_runtime_policy or {})
    context_policy = dict(graph_context_policy or {})
    graph_binding_contract = _graph_binding_contract(
        graph_id=graph_id,
        metadata=metadata,
        runtime_policy=runtime_policy,
        context_policy=context_policy,
        environment=environment,
    )
    node_protocol_index = dict(protocol_index.get("node_protocol_index") or {})
    edge_protocol_index = dict(protocol_index.get("edge_protocol_index") or {})
    node_contract_index = build_node_contract_index(
        nodes=nodes,
        graph_environment=environment,
        graph_binding_contract=graph_binding_contract,
        graph_permissions=permissions,
        graph_tools=tools,
        node_protocol_index=node_protocol_index,
    )
    resource_contract_index = build_resource_contract_index(
        resource_nodes=resource_nodes,
        graph_environment=environment,
        graph_binding_contract=graph_binding_contract,
    )
    edge_contract_index = build_edge_contract_index(
        edges=edges,
        edge_protocol_index=edge_protocol_index,
        node_contract_index=node_contract_index,
    )
    issues = _compile_issues(
        nodes=nodes,
        edges=edges,
        node_contract_index=node_contract_index,
        edge_contract_index=edge_contract_index,
        protocol_issues=[dict(item) for item in list(protocol_index.get("issues") or []) if isinstance(item, dict)],
    )
    report = compile_report(
        graph_id=graph_id,
        summary=_compile_report_summary(
            graph_id=graph_id,
            graph_title=graph_title,
            nodes=nodes,
            edges=edges,
            node_contract_index=node_contract_index,
            resource_contract_index=resource_contract_index,
            edge_contract_index=edge_contract_index,
            graph_binding_contract=graph_binding_contract,
        ),
        issues=issues,
    )
    deployment_package = _deployment_package(
        graph_id=graph_id,
        graph_title=graph_title,
        graph_binding_contract=graph_binding_contract,
        node_contract_index=node_contract_index,
        resource_contract_index=resource_contract_index,
        edge_contract_index=edge_contract_index,
        report=report.to_dict(),
    )
    unit_seed = {
        "graph_id": graph_id,
        "compiler_version": GRAPH_COMPILER_VERSION,
        "node_contract_index": node_contract_index,
        "resource_contract_index": resource_contract_index,
        "edge_contract_index": edge_contract_index,
        "graph_binding_contract": graph_binding_contract,
        "deployment_package": deployment_package,
    }
    return GraphCompilationUnit(
        unit_id=f"gcompile:{safe_id(graph_id)}:{stable_hash(unit_seed)[:16]}",
        graph_id=graph_id,
        compiler_version=GRAPH_COMPILER_VERSION,
        node_contract_index=node_contract_index,
        resource_contract_index=resource_contract_index,
        edge_contract_index=edge_contract_index,
        configurator_write_contract=build_configurator_write_contract(graph_id=graph_id),
        system_node_contract_index=build_system_node_contract_index(graph_id=graph_id),
        maintenance_contract=build_maintenance_contract(graph_id=graph_id),
        graph_binding_contract=graph_binding_contract,
        deployment_package=deployment_package,
        compile_report=report,
    )


def _graph_binding_contract(
    *,
    graph_id: str,
    metadata: dict[str, Any],
    runtime_policy: dict[str, Any],
    context_policy: dict[str, Any],
    environment: dict[str, Any],
) -> dict[str, Any]:
    configured = dict(
        runtime_policy.get("graph_binding")
        or runtime_policy.get("project_binding")
        or context_policy.get("graph_binding")
        or context_policy.get("project_binding")
        or metadata.get("graph_binding")
        or metadata.get("project_binding")
        or {}
    )
    project_id = str(
        configured.get("project_id")
        or runtime_policy.get("project_id")
        or context_policy.get("project_id")
        or metadata.get("project_id")
        or dict(environment.get("runtime_scope") or {}).get("project_id")
        or ""
    ).strip()
    binding_mode = str(configured.get("binding_mode") or configured.get("mode") or "project_scoped").strip() or "project_scoped"
    workspace_view = str(
        configured.get("workspace_view")
        or ("project" if binding_mode == "project_scoped" or project_id else "task_environment")
    )
    return _drop_empty(
        {
            "contract_id": f"graph-binding:{graph_id}",
            "binding_mode": binding_mode,
            "project_id": project_id,
            "workspace_view": workspace_view,
            "conversation_binding": "not_authoritative",
            "task_environment_id": str(
                configured.get("task_environment_id")
                or runtime_policy.get("task_environment_id")
                or context_policy.get("task_environment_id")
                or environment.get("task_environment_id")
                or environment.get("environment_id")
                or ""
            ).strip(),
            "node_session_default": "per_node_run_session",
            "authority": "task_system.graph_binding_contract",
        }
    )


def _compile_issues(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_contract_index: dict[str, dict[str, Any]],
    edge_contract_index: dict[str, dict[str, Any]],
    protocol_issues: list[dict[str, Any]],
) -> list[GraphCompileIssue]:
    issues: list[GraphCompileIssue] = [
        GraphCompileIssue(
            code=str(item.get("code") or "protocol_issue"),
            message=str(item.get("message") or "Graph protocol alignment issue"),
            severity=str(item.get("severity") or "error"),
            node_id=str(item.get("node_id") or ""),
            edge_id=str(item.get("edge_id") or ""),
        )
        for item in protocol_issues
    ]
    for node in nodes:
        node_id = str(node.get("node_id") or "")
        contract = dict(node_contract_index.get(node_id) or {})
        if not contract:
            issues.append(GraphCompileIssue(code="node_contract_missing", message="节点缺少编译后节点契约。", node_id=node_id))
            continue
        if str(contract.get("node_class") or "") == "executable" and not dict(contract.get("environment_lock") or {}):
            issues.append(
                GraphCompileIssue(
                    code="node_environment_lock_missing",
                    message="节点缺少 effective environment lock。",
                    severity="warning",
                    node_id=node_id,
                )
            )
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        contract = dict(edge_contract_index.get(edge_id) or {})
        if not contract:
            issues.append(GraphCompileIssue(code="edge_contract_missing", message="边缺少编译后边契约。", edge_id=edge_id))
            continue
        if not str(dict(contract.get("protocol") or {}).get("kind") or "").strip():
            issues.append(GraphCompileIssue(code="edge_protocol_kind_missing", message="边契约缺少 protocol.kind。", edge_id=edge_id))
    return issues


def _compile_report_summary(
    *,
    graph_id: str,
    graph_title: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_contract_index: dict[str, dict[str, Any]],
    resource_contract_index: dict[str, dict[str, Any]],
    edge_contract_index: dict[str, dict[str, Any]],
    graph_binding_contract: dict[str, Any],
) -> dict[str, Any]:
    return {
        "graph_title": graph_title,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "resource_contract_count": len(resource_contract_index),
        "edge_contract_count": len(edge_contract_index),
        "node_contract_count": len(node_contract_index),
        "node_interaction_contract_enabled": False,
        "graph_binding": dict(graph_binding_contract),
        "prototype_catalog": configuration_prototype_catalog(),
        "prototype_recommendations": _prototype_recommendations(
            node_contract_index=node_contract_index,
            resource_contract_index=resource_contract_index,
            edge_contract_index=edge_contract_index,
        ),
        "configuration_guidance": {
            "configurator_system_node_id": "__configurator__",
            "supervisor_system_node_id": "__supervisor__",
            "configurator_write_contract_id": f"configurator-write:{graph_id}",
            "recommended_authoring_flow": [
                "select_node_resource_edge_prototypes",
                "emit_graph_draft_patch",
                "validate_with_graph_compiler",
                "repair_until_no_blocking_compile_issues",
            ],
            "minimum_user_choices": [
                "business_goal",
                "task_environment_or_project_scope",
                "required_outputs",
            ],
            "advanced_fields_should_be_inferred": [
                "edge_protocol_kind",
                "payload_contract_id",
                "target_input_slot",
                "node_session_policy",
                "checkpoint_policy",
            ],
            "authority": "task_system.graph_compiler.configuration_guidance",
        },
        "authority": "task_system.graph_compiler.summary",
    }


def _prototype_recommendations(
    *,
    node_contract_index: dict[str, dict[str, Any]],
    resource_contract_index: dict[str, dict[str, Any]],
    edge_contract_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "nodes": [_node_prototype_recommendation(node_id, contract) for node_id, contract in sorted(node_contract_index.items())],
        "resources": [
            _resource_prototype_recommendation(resource_id, contract)
            for resource_id, contract in sorted(resource_contract_index.items())
        ],
        "edges": [_edge_prototype_recommendation(edge_id, contract) for edge_id, contract in sorted(edge_contract_index.items())],
        "authority": "task_system.graph_compiler.prototype_recommendations",
    }


def _node_prototype_recommendation(node_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    node_class = str(contract.get("node_class") or "")
    node_kind = str(contract.get("node_kind") or "")
    if node_class == "resource":
        prototype_id = "node.resource_repository"
        reason = "节点被编译为资源节点，应由资源契约约束读写。"
    elif node_kind == "ControlNode":
        prototype_id = "node.control_gate"
        reason = "节点是控制/门禁节点，应只表达调度或人工放行语义。"
    else:
        prototype_id = "node.agent_worker"
        reason = "节点是可执行 agent 节点，应通过单 agent worker 履行节点契约。"
    return {
        "node_id": str(node_id),
        "prototype_id": prototype_id,
        "reason": reason,
        "authority": "task_system.graph_compiler.node_prototype_recommendation",
    }


def _resource_prototype_recommendation(resource_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    resource_kind = str(contract.get("resource_kind") or "").strip()
    if resource_kind == "memory":
        prototype_id = "resource.memory_repository"
    elif resource_kind == "file":
        prototype_id = "resource.file_view"
    else:
        prototype_id = "resource.artifact_repository"
    return {
        "resource_id": str(resource_id),
        "prototype_id": prototype_id,
        "reason": "资源原型由 resource_kind 和编译后的读写策略推导。",
        "authority": "task_system.graph_compiler.resource_prototype_recommendation",
    }


def _edge_prototype_recommendation(edge_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    protocol = dict(contract.get("protocol") or {})
    protocol_kind = str(protocol.get("kind") or "node_handoff").strip() or "node_handoff"
    return {
        "edge_id": str(edge_id),
        "prototype_id": f"edge.{protocol_kind}",
        "protocol_kind": protocol_kind,
        "interaction_pattern": str(protocol.get("interaction_pattern") or ""),
        "reason": "边原型由 edge_type、scheduler_role 和显式 edge_protocol_kind 编译得到。",
        "authority": "task_system.graph_compiler.edge_prototype_recommendation",
    }


def _deployment_package(
    *,
    graph_id: str,
    graph_title: str,
    graph_binding_contract: dict[str, Any],
    node_contract_index: dict[str, Any],
    resource_contract_index: dict[str, Any],
    edge_contract_index: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    required_environments = sorted(
        {
            str(dict(contract.get("environment_lock") or {}).get("task_environment_id") or "")
            for contract in node_contract_index.values()
            if isinstance(contract, dict)
        }
        - {""}
    )
    return {
        "package_id": f"gdeploy:{safe_id(graph_id)}:{stable_hash([graph_id, node_contract_index, edge_contract_index])[:12]}",
        "graph_id": graph_id,
        "graph_title": graph_title,
        "binding": dict(graph_binding_contract),
        "required_environments": required_environments,
        "required_resources": sorted(resource_contract_index.keys()),
        "edge_contract_count": len(edge_contract_index),
        "launch_contract": {
            "required_inputs": [],
            "optional_inputs": ["project_id", "runtime_scope"],
        },
        "compile_report": report,
        "authority": "task_system.graph_deployment_package",
    }


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {}, ())
    }
