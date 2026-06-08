from __future__ import annotations

from typing import Any

from harness.graph.models import safe_id, stable_hash

from .configurator_write_contracts import build_configurator_write_contract
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
        summary={
            "graph_title": graph_title,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "resource_contract_count": len(resource_contract_index),
            "edge_contract_count": len(edge_contract_index),
            "node_contract_count": len(node_contract_index),
            "node_interaction_contract_enabled": False,
            "authority": "task_system.graph_compiler.summary",
        },
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
    return _drop_empty(
        {
            "contract_id": f"graph-binding:{graph_id}",
            "binding_mode": binding_mode,
            "project_id": project_id,
            "workspace_view": str(configured.get("workspace_view") or ("project" if project_id else "task_environment")),
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
