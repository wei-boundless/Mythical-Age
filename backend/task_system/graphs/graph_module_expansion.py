from __future__ import annotations

from typing import Any


GRAPH_MODULE_NODE_TYPES = {"graph_module"}
GRAPH_MODULE_EXECUTORS = {"graph_module", "imported_graph"}


def graph_module_expansion_plan_payloads(
    graph: Any,
    *,
    publish_version: str = "published",
) -> tuple[dict[str, Any], ...]:
    """Return compile-time graph-module expansion plans for a task graph."""
    plans: list[dict[str, Any]] = []
    graph_id = str(getattr(graph, "graph_id", "") or "").strip()
    for node in tuple(getattr(graph, "nodes", ()) or ()):
        plan = graph_module_expansion_plan_payload(
            graph_id=graph_id,
            node=node,
            publish_version=publish_version,
        )
        if plan:
            plans.append(plan)
    return tuple(plans)


def graph_module_expansion_plan_payload(
    *,
    graph_id: str,
    node: Any,
    publish_version: str = "published",
) -> dict[str, Any]:
    node_id = str(getattr(node, "node_id", "") or "").strip()
    if not node_id:
        return {}
    node_type = str(getattr(node, "node_type", "") or "").strip()
    metadata = dict(getattr(node, "metadata", {}) or {})
    executor_policy = dict(getattr(node, "executor_policy", {}) or {})
    bindings = dict(getattr(node, "contract_bindings", {}) or {})
    runtime_bindings = dict(bindings.get("runtime") or {})
    graph_module_expansion = dict(runtime_bindings.get("graph_module_expansion") or {})
    default_executor = str(executor_policy.get("default_executor") or executor_policy.get("executor") or "").strip()
    if not (
        node_type in GRAPH_MODULE_NODE_TYPES
        or bool(metadata.get("graph_module"))
        or default_executor in GRAPH_MODULE_EXECUTORS
    ):
        return {}
    linked_graph_id = str(
        graph_module_expansion.get("linked_graph_id")
        or metadata.get("linked_graph_id")
        or metadata.get("imported_graph_id")
        or executor_policy.get("linked_graph_id")
        or executor_policy.get("imported_graph_id")
        or ""
    ).strip()
    handoff = dict(bindings.get("handoff") or {})
    plan_id = str(
        metadata.get("graph_module_expansion_plan_id")
        or graph_module_expansion.get("plan_id")
        or f"graph_module_expansion.{_safe_identifier(node_id)}"
    ).strip()
    version_ref = str(
        graph_module_expansion.get("version_ref")
        or metadata.get("version_ref")
        or publish_version
        or "published"
    ).strip()
    return {
        "plan_id": plan_id,
        "composition_id": f"graph-module-expansion:{_safe_identifier(graph_id or 'graph')}:{_safe_identifier(node_id)}",
        "composition_node_id": node_id,
        "runtime_node_id": node_id,
        "importing_graph_id": graph_id,
        "unit_id": f"unit.node.{_safe_identifier(node_id)}",
        "linked_graph_id": linked_graph_id,
        "version_ref": version_ref,
        "handoff_contract_id": str(
            handoff.get("handoff_contract_id")
            or graph_module_expansion.get("handoff_contract_id")
            or ""
        ).strip(),
        "input_port_id": str(graph_module_expansion.get("input_port_id") or "input.default").strip() or "input.default",
        "output_port_id": str(graph_module_expansion.get("output_port_id") or "output.default").strip() or "output.default",
        "scope_prefix": str(metadata.get("composition_scope_prefix") or f"{node_id}::"),
        "isolation_policy": str(graph_module_expansion.get("isolation_policy") or "compile_time_inline_expansion").strip() or "compile_time_inline_expansion",
        "visibility_policy": str(handoff.get("visibility_policy") or graph_module_expansion.get("visibility_policy") or "expanded_internal_nodes").strip() or "expanded_internal_nodes",
        "detach_policy": str(graph_module_expansion.get("detach_policy") or "preserve_version_anchor").strip() or "preserve_version_anchor",
        "metadata": {
            "source_node_title": str(getattr(node, "title", "") or node_id),
            "source_node_type": node_type,
            "source_executor": default_executor,
            "expansion_mode": "compile_time_inline",
        },
    }


def _safe_identifier(value: str) -> str:
    sanitized = str(value or "").strip().replace(":", ".").replace("/", ".").replace("\\", ".")
    sanitized = ".".join(part for part in sanitized.split(".") if part)
    return sanitized or "unknown"
