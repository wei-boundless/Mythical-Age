from __future__ import annotations

from typing import Any


def diagnose_context_contract_manifest(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    control_layer_counts: dict[str, int] = {}
    visibility_counts: dict[str, int] = {}
    agent_domain_counts: dict[str, int] = {}
    control_signal_counts: dict[str, int] = {}
    time_scope_counts: dict[str, int] = {}
    physical_lane_counts: dict[str, int] = {}
    edge_payloads = [dict(edge) for edge in list(edges or []) if isinstance(edge, dict)]
    edge_kind_counts: dict[str, int] = {}
    edge_authority_counts: dict[str, int] = {}
    edge_physical_lane_counts: dict[str, int] = {}
    edge_connection_contract_counts: dict[str, int] = {}
    node_by_id = {str(node.get("node_id") or ""): dict(node) for node in nodes if str(node.get("node_id") or "").strip()}
    for node in nodes:
        visibility = str(node.get("visibility") or "")
        agent_domain = str(node.get("agent_domain") or "")
        control_layer = str(node.get("control_layer") or "")
        control_signal = str(node.get("control_signal") or "")
        time_scope = str(node.get("time_scope") or "")
        physical_lane = str(node.get("physical_lane") or "")
        control_layer_counts[control_layer or "missing"] = control_layer_counts.get(control_layer or "missing", 0) + 1
        visibility_counts[visibility] = visibility_counts.get(visibility, 0) + 1
        agent_domain_counts[agent_domain or "missing"] = agent_domain_counts.get(agent_domain or "missing", 0) + 1
        control_signal_counts[control_signal or "missing"] = control_signal_counts.get(control_signal or "missing", 0) + 1
        time_scope_counts[time_scope or "missing"] = time_scope_counts.get(time_scope or "missing", 0) + 1
        physical_lane_counts[physical_lane or "missing"] = physical_lane_counts.get(physical_lane or "missing", 0) + 1
        if visibility == "agent_visible" and not str(node.get("agent_use_contract") or "").strip():
            issues.append(_issue(node, "missing_agent_use_contract", "Agent-visible context requires an explicit use contract."))
        if visibility == "agent_visible" and not agent_domain:
            issues.append(_issue(node, "missing_agent_domain", "Agent-visible context requires an explicit agent domain."))
        if visibility == "agent_visible" and not control_signal:
            issues.append(_issue(node, "missing_control_signal", "Agent-visible context requires an explicit control signal."))
        node_diagnostics = dict(node.get("diagnostics") or {})
        connection_contract_missing = (
            not str(node.get("connection_contract_ref") or "").strip()
            or node_diagnostics.get("missing_connection_contract") is True
        )
        if visibility == "agent_visible" and connection_contract_missing:
            issues.append(_issue(node, "missing_connection_contract", "Agent-visible context requires an explicit connection contract."))
        if visibility == "provider_transport" and agent_domain != "ProviderTransportDomain":
            issues.append(_issue(node, "transport_domain_mismatch", "Provider transport must remain in ProviderTransportDomain."))
        if agent_domain == "ProviderTransportDomain" and visibility != "provider_transport":
            issues.append(_issue(node, "provider_transport_agent_visible", "Provider transport domain must not be agent-visible."))
        if time_scope == "current_provider_request" and str(node.get("cache_tier") or "") != "hidden":
            issues.append(_issue(node, "hidden_transport_cache_tier", "Hidden transport must use hidden cache tier."))
        if str(node.get("ttl") or "") == "current_provider_request" and str(node.get("commit_policy") or "") != "never_commit":
            issues.append(_issue(node, "provider_request_commit_policy", "Current provider request nodes must never commit to history."))
        if time_scope in {"current_turn", "current_turn_never_replay"} and str(node.get("cache_tier") or "") in {"session", "provider_global"}:
            issues.append(_issue(node, "current_turn_in_stable_cache", "Current-turn context should not be placed in stable cache tiers."))
    issues.extend(_diagnose_context_contract_edges(edge_payloads, node_by_id))
    for edge in edge_payloads:
        edge_kind = str(edge.get("edge_kind") or "missing")
        authority = str(edge.get("authority") or "missing")
        physical_lane = str(edge.get("physical_lane") or "missing")
        connection_contract_ref = str(edge.get("connection_contract_ref") or "missing")
        edge_kind_counts[edge_kind] = edge_kind_counts.get(edge_kind, 0) + 1
        edge_authority_counts[authority] = edge_authority_counts.get(authority, 0) + 1
        edge_physical_lane_counts[physical_lane] = edge_physical_lane_counts.get(physical_lane, 0) + 1
        edge_connection_contract_counts[connection_contract_ref] = edge_connection_contract_counts.get(connection_contract_ref, 0) + 1
    return {
        "authority": "harness.runtime.context_contract.diagnostics",
        "issue_count": len(issues),
        "issues": issues,
        "edge_count": len(edge_payloads),
        "edge_kind_counts": edge_kind_counts,
        "edge_authority_counts": edge_authority_counts,
        "edge_physical_lane_counts": edge_physical_lane_counts,
        "edge_connection_contract_counts": edge_connection_contract_counts,
        "agent_domain_counts": agent_domain_counts,
        "control_signal_counts": control_signal_counts,
        "time_scope_counts": time_scope_counts,
        "physical_lane_counts": physical_lane_counts,
        "control_layer_counts": control_layer_counts,
        "visibility_counts": visibility_counts,
        "provider_transport_hidden": all(
            str(node.get("visibility") or "") != "provider_transport"
            or str(node.get("agent_domain") or "") == "ProviderTransportDomain"
            for node in nodes
        ),
    }


def _diagnose_context_contract_edges(
    edges: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    edge_ids = [str(edge.get("edge_id") or "") for edge in edges if str(edge.get("edge_id") or "").strip()]
    duplicate_edge_ids = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
    for edge_id in duplicate_edge_ids:
        issues.append(_edge_issue({"edge_id": edge_id}, "duplicate_edge_id", f"Duplicate context contract edge id: {edge_id}"))
    for edge in edges:
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        edge_kind = str(edge.get("edge_kind") or "")
        source_node = node_by_id.get(source, {})
        target_node = node_by_id.get(target, {})
        if not str(edge.get("edge_id") or "").strip():
            issues.append(_edge_issue(edge, "missing_edge_id", "Context contract edge requires a stable edge id."))
        if not source_node or not target_node:
            issues.append(
                _edge_issue(
                    edge,
                    "missing_edge_endpoint",
                    "Context contract edge endpoint is not present in manifest nodes.",
                    details={
                        "source_present": bool(source_node),
                        "target_present": bool(target_node),
                    },
                )
            )
        if not str(edge.get("authority") or "").strip():
            issues.append(_edge_issue(edge, "missing_edge_authority", "Context contract edge requires an explicit authority."))
        if not str(edge.get("payload_identity") or "").strip():
            issues.append(_edge_issue(edge, "missing_payload_identity", "Context contract edge requires a payload identity."))
        if not str(edge.get("payload_schema") or "").strip():
            issues.append(_edge_issue(edge, "missing_payload_schema", "Context contract edge requires a payload schema."))
        if edge_kind != "agent_visible_order" and not str(edge.get("connection_contract_ref") or "").strip():
            issues.append(_edge_issue(edge, "missing_edge_connection_contract", "Context connection edges require connection_contract_ref."))
        if edge_kind in {"provider_payload_binding", "cache_health_binding"}:
            target_visibility = str(target_node.get("visibility") or "")
            if target_visibility != "provider_transport":
                issues.append(
                    _edge_issue(
                        edge,
                        "provider_binding_target_mismatch",
                        "Provider/cache binding edges must target the provider transport node.",
                    )
                )
        if edge_kind == "agent_visible_order":
            if str(source_node.get("visibility") or "") != "agent_visible" or str(target_node.get("visibility") or "") != "agent_visible":
                issues.append(
                    _edge_issue(
                        edge,
                        "agent_visible_order_visibility_mismatch",
                        "Agent-visible order edges must connect only agent-visible nodes.",
                    )
                )
        if str(source_node.get("visibility") or "") == "provider_transport" and edge_kind != "provider_transport_internal":
            issues.append(
                _edge_issue(
                    edge,
                    "provider_transport_source_leak",
                    "Provider transport nodes must not become source nodes for context contract edges.",
                )
            )
    return issues


def diagnose_runtime_topology_projection(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    runtime_available: bool = False,
    runtime_host_available: bool = False,
) -> dict[str, Any]:
    node_ids = [str(node.get("id") or "") for node in nodes if str(node.get("id") or "").strip()]
    node_id_set = set(node_ids)
    duplicate_nodes = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    edge_ids = [str(edge.get("id") or "") for edge in edges if str(edge.get("id") or "").strip()]
    duplicate_edges = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
    missing_endpoints: list[dict[str, Any]] = []
    non_connected_edges: list[str] = []
    missing_authority_edges: list[str] = []
    for edge in edges:
        edge_id = str(edge.get("id") or "")
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_id_set or target not in node_id_set:
            missing_endpoints.append(
                {
                    "edge_id": edge_id,
                    "source": source,
                    "target": target,
                    "source_present": source in node_id_set,
                    "target_present": target in node_id_set,
                }
            )
        if str(edge.get("status") or "") != "connected":
            non_connected_edges.append(edge_id)
        if not str(edge.get("authority") or "").strip():
            missing_authority_edges.append(edge_id)
    issues: list[dict[str, Any]] = []
    for node_id in duplicate_nodes:
        issues.append(_runtime_issue("duplicate_node_id", f"Duplicate topology node id: {node_id}", subject=node_id))
    for edge_id in duplicate_edges:
        issues.append(_runtime_issue("duplicate_edge_id", f"Duplicate topology edge id: {edge_id}", subject=edge_id))
    for item in missing_endpoints:
        issues.append(
            _runtime_issue(
                "missing_edge_endpoint",
                f"Topology edge endpoint is missing: {item['edge_id']}",
                subject=str(item.get("edge_id") or ""),
                details=item,
            )
        )
    for edge_id in missing_authority_edges:
        issues.append(_runtime_issue("missing_edge_authority", f"Topology edge lacks authority: {edge_id}", subject=edge_id))
    return {
        "authority": "harness.runtime.context_contract.diagnostics.runtime_topology_projection",
        "issue_count": len(issues),
        "issues": issues,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "runtime_available": bool(runtime_available),
        "runtime_host_available": bool(runtime_host_available),
        "duplicate_node_ids": duplicate_nodes,
        "duplicate_edge_ids": duplicate_edges,
        "missing_endpoint_count": len(missing_endpoints),
        "missing_endpoints": missing_endpoints,
        "non_connected_edges": non_connected_edges,
        "missing_authority_edges": missing_authority_edges,
        "projection_read_only": True,
    }


def _issue(node: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "node_id": str(node.get("node_id") or ""),
        "agent_domain": str(node.get("agent_domain") or ""),
        "control_signal": str(node.get("control_signal") or ""),
        "control_layer": str(node.get("control_layer") or ""),
        "time_scope": str(node.get("time_scope") or ""),
        "physical_lane": str(node.get("physical_lane") or ""),
        "visibility": str(node.get("visibility") or ""),
        "authority": "harness.runtime.context_contract.diagnostics",
    }


def _edge_issue(
    edge: dict[str, Any],
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "edge_id": str(edge.get("edge_id") or ""),
        "source_node_id": str(edge.get("source_node_id") or ""),
        "target_node_id": str(edge.get("target_node_id") or ""),
        "edge_kind": str(edge.get("edge_kind") or ""),
        "authority": "harness.runtime.context_contract.diagnostics",
        "details": dict(details or {}),
    }


def _runtime_issue(
    code: str,
    message: str,
    *,
    subject: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "subject": subject,
        "details": dict(details or {}),
        "authority": "harness.runtime.context_contract.diagnostics.runtime_topology_projection",
    }
