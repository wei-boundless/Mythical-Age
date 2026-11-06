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
        if visibility == "agent_visible" and not physical_lane:
            issues.append(_issue(node, "missing_physical_assembly_lane", "Agent-visible context must carry an assembler-written physical lane."))
        refs = dict(node.get("refs") or {})
        has_confirmed_frame_replay_ref = _has_confirmed_frame_replay_ref(refs)
        if visibility == "agent_visible" and not str(refs.get("context_candidate_ref") or "").strip() and not has_confirmed_frame_replay_ref:
            issues.append(
                _issue(
                    node,
                    "missing_context_candidate_ref",
                    "Agent-visible current context must carry ContextCandidateGateway candidate identity; confirmed replay must carry physical frame identity.",
                )
            )
        if visibility == "agent_visible" and not str(refs.get("context_line_id") or "").strip() and not has_confirmed_frame_replay_ref:
            issues.append(
                _issue(
                    node,
                    "missing_context_line_id",
                    "Agent-visible current context must carry ContextCandidateGateway line identity; confirmed replay must carry physical frame identity.",
                )
            )
        if visibility == "agent_visible" and not str(refs.get("context_input_envelope_ref") or "").strip() and not has_confirmed_frame_replay_ref:
            issues.append(
                _issue(
                    node,
                    "missing_context_input_envelope_ref",
                    "Agent-visible context must carry ContextInputEnvelope identity from the candidate gateway.",
                )
            )
        node_diagnostics = dict(node.get("diagnostics") or {})
        if visibility == "agent_visible" and node_diagnostics.get("missing_physical_assembly_metadata") is True:
            issues.append(
                _issue(
                    node,
                    "missing_physical_assembly_metadata",
                    "Agent-visible context must pass through physical_context_assembler before contract projection.",
                )
            )
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


def _has_confirmed_frame_replay_ref(refs: dict[str, Any]) -> bool:
    return bool(
        str(refs.get("physical_prefix_frame_segment_id") or "").strip()
        and str(refs.get("physical_prefix_frame_id") or "").strip()
    )


def diagnose_runtime_topology_projection(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    runtime_available: bool = False,
    runtime_host_available: bool = False,
    line_governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node_ids = [str(node.get("id") or "") for node in nodes if str(node.get("id") or "").strip()]
    node_id_set = set(node_ids)
    duplicate_nodes = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    edge_ids = [str(edge.get("id") or "") for edge in edges if str(edge.get("id") or "").strip()]
    duplicate_edges = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
    missing_endpoints: list[dict[str, Any]] = []
    non_connected_edges: list[str] = []
    missing_status_edges: list[str] = []
    missing_authority_edges: list[str] = []
    for edge in edges:
        edge_id = str(edge.get("id") or "")
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        edge_status = str(edge.get("status") or "").strip()
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
        if not edge_status:
            missing_status_edges.append(edge_id)
        elif edge_status != "connected":
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
    for edge_id in missing_status_edges:
        issues.append(_runtime_issue("missing_edge_status", f"Topology edge lacks explicit status: {edge_id}", subject=edge_id))
    line_governance_payload = dict(line_governance or {})
    line_governance_diagnostics = _diagnose_line_governance_projection(line_governance_payload)
    issues.extend(line_governance_diagnostics.get("issues") or [])
    diagnostic_issue_links = _diagnostic_issue_links(
        issues,
        node_ids=node_ids,
        edge_ids=edge_ids,
    )
    return {
        "authority": "harness.runtime.context_contract.diagnostics.runtime_topology_projection",
        "issue_count": len(issues),
        "issues": issues,
        "diagnostic_issue_links": diagnostic_issue_links,
        "diagnostic_issue_link_count": len(diagnostic_issue_links),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "runtime_available": bool(runtime_available),
        "runtime_host_available": bool(runtime_host_available),
        "duplicate_node_ids": duplicate_nodes,
        "duplicate_edge_ids": duplicate_edges,
        "missing_endpoint_count": len(missing_endpoints),
        "missing_endpoints": missing_endpoints,
        "non_connected_edges": non_connected_edges,
        "missing_status_edges": missing_status_edges,
        "missing_authority_edges": missing_authority_edges,
        "line_governance": line_governance_diagnostics,
        "projection_read_only": True,
    }


def _diagnose_line_governance_projection(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        issue = _runtime_issue(
            "missing_line_governance_projection",
            "Runtime topology projection should include read-only line governance inventory.",
            subject="line_governance",
        )
        return {"issue_count": 1, "issues": [issue]}
    issues: list[dict[str, Any]] = []
    summary = dict(payload.get("summary") or {})
    if int(summary.get("system_asset_line_count") or 0) <= 0:
        issues.append(
            _runtime_issue(
                "missing_system_asset_lines",
                "Line governance projection has no SystemAssetLine entries.",
                subject="line_governance.system_asset_lines",
            )
        )
    if int(summary.get("context_line_state_count") or 0) <= 0:
        issues.append(
            _runtime_issue(
                "missing_context_line_states",
                "Line governance projection has no ContextLineState inventory.",
                subject="line_governance.context_line_states",
            )
        )
    if int(summary.get("control_output_line_count") or 0) <= 0:
        issues.append(
            _runtime_issue(
                "missing_control_output_lines",
                "Line governance projection has no ControlOutputLine entries.",
                subject="line_governance.control_output_lines",
            )
        )
    if int(summary.get("harness_control_spine_line_count") or 0) <= 0:
        issues.append(
            _runtime_issue(
                "missing_harness_control_spine_lines",
                "Line governance projection has no HarnessControlSpineLine entries.",
                subject="line_governance.harness_control_spine_lines",
            )
        )
    if int(summary.get("harness_runtime_spine_contract_count") or 0) <= 0:
        issues.append(
            _runtime_issue(
                "missing_harness_runtime_spine_contracts",
                "Line governance projection has no harness runtime spine contracts.",
                subject="line_governance.harness_runtime_spine_contracts",
            )
        )
    control_lines = [dict(item) for item in list(payload.get("control_output_lines") or []) if isinstance(item, dict)]
    action_types = [str(item.get("action_type") or "") for item in control_lines if str(item.get("action_type") or "").strip()]
    duplicate_action_types = sorted({action for action in action_types if action_types.count(action) > 1})
    control_line_ids = [str(item.get("line_id") or "") for item in control_lines if str(item.get("line_id") or "").strip()]
    duplicate_control_line_ids = sorted({line_id for line_id in control_line_ids if control_line_ids.count(line_id) > 1})
    for action_type in duplicate_action_types:
        issues.append(
            _runtime_issue(
                "duplicate_control_output_line",
                f"Duplicate ControlOutputLine action_type: {action_type}",
                subject=action_type,
            )
        )
    for line_id in duplicate_control_line_ids:
        issues.append(
            _runtime_issue(
                "duplicate_control_output_line_id",
                f"Duplicate ControlOutputLine line_id: {line_id}",
                subject=line_id,
            )
        )
    for line in control_lines:
        action_type = str(line.get("action_type") or "")
        for field_name in (
            "line_id",
            "authority",
            "permit_policy_ref",
            "executor_ref",
            "observation_contract",
            "public_projection_policy",
            "commit_policy",
            "terminal_policy",
            "failure_feedback_policy",
        ):
            if not str(line.get(field_name) or "").strip():
                issues.append(
                    _runtime_issue(
                        "incomplete_control_output_line",
                        f"ControlOutputLine {action_type or '<missing action>'} lacks {field_name}.",
                        subject=action_type,
                        details={"field": field_name, "line": line},
                    )
                )
    spine_lines = [dict(item) for item in list(payload.get("harness_control_spine_lines") or []) if isinstance(item, dict)]
    spine_ids = [str(item.get("control_line_id") or "") for item in spine_lines if str(item.get("control_line_id") or "").strip()]
    duplicate_spine_ids = sorted({line_id for line_id in spine_ids if spine_ids.count(line_id) > 1})
    for line_id in duplicate_spine_ids:
        issues.append(
            _runtime_issue(
                "duplicate_harness_control_spine_line",
                f"Duplicate HarnessControlSpineLine id: {line_id}",
                subject=line_id,
            )
        )
    control_actions = {str(item.get("action_type") or "") for item in control_lines if str(item.get("action_type") or "").strip()}
    spine_actions = {str(item.get("action_type") or "") for item in spine_lines if str(item.get("action_type") or "").strip()}
    for action_type in sorted(control_actions - spine_actions):
        issues.append(
            _runtime_issue(
                "control_output_line_missing_harness_spine",
                f"ControlOutputLine has no HarnessControlSpineLine: {action_type}",
                subject=action_type,
            )
        )
    for action_type in sorted(spine_actions - control_actions):
        issues.append(
            _runtime_issue(
                "harness_spine_missing_control_output_line",
                f"HarnessControlSpineLine has no ControlOutputLine: {action_type}",
                subject=action_type,
            )
        )
    control_line_refs = {str(item.get("line_id") or "") for item in control_lines if str(item.get("line_id") or "").strip()}
    for spine in spine_lines:
        action_type = str(spine.get("action_type") or "")
        control_ref = str(spine.get("control_output_line_ref") or "")
        if not control_ref:
            issues.append(
                _runtime_issue(
                    "harness_spine_missing_control_output_ref",
                    f"HarnessControlSpineLine lacks control_output_line_ref: {action_type}",
                    subject=action_type,
                )
            )
        elif control_ref not in control_line_refs:
            issues.append(
                _runtime_issue(
                    "harness_spine_control_output_ref_not_declared",
                    f"HarnessControlSpineLine references undeclared ControlOutputLine: {control_ref}",
                    subject=control_ref,
                )
            )
    line_state_payload = dict(payload.get("context_line_states") or {})
    line_states = [dict(item) for item in list(line_state_payload.get("line_states") or []) if isinstance(item, dict)]
    line_state_ids = [str(item.get("line_id") or "") for item in line_states if str(item.get("line_id") or "").strip()]
    duplicate_line_state_ids = sorted({line_id for line_id in line_state_ids if line_state_ids.count(line_id) > 1})
    for line_id in duplicate_line_state_ids:
        issues.append(
            _runtime_issue(
                "duplicate_context_line_state",
                f"Duplicate ContextLineState line_id: {line_id}",
                subject=line_id,
            )
        )
    spine_contracts = [
        dict(item)
        for item in list(payload.get("harness_runtime_spine_contracts") or [])
        if isinstance(item, dict)
    ]
    contract_ids = [
        str(item.get("contract_id") or "")
        for item in spine_contracts
        if str(item.get("contract_id") or "").strip()
    ]
    duplicate_spine_contract_ids = sorted(
        {contract_id for contract_id in contract_ids if contract_ids.count(contract_id) > 1}
    )
    for contract_id in duplicate_spine_contract_ids:
        issues.append(
            _runtime_issue(
                "duplicate_harness_runtime_spine_contract",
                f"Duplicate harness runtime spine contract id: {contract_id}",
                subject=contract_id,
            )
        )
    for contract in spine_contracts:
        contract_id = str(contract.get("contract_id") or "")
        for field_name in (
            "authority",
            "runner_role",
            "default_model_entrypoint",
            "execution_entrypoint",
            "controller_ref",
            "control_gateway_ref",
            "packet_ref",
            "action_surface_authority",
            "action_schema_ref",
            "ordinary_turn_policy",
            "migration_target",
        ):
            if not str(contract.get(field_name) or "").strip():
                issues.append(
                    _runtime_issue(
                        "incomplete_harness_runtime_spine_contract",
                        f"Harness runtime spine contract {contract_id or '<missing id>'} lacks {field_name}.",
                        subject=contract_id,
                        details={"field": field_name, "contract": contract},
                    )
                )
        forbidden_routes = list(contract.get("forbidden_routes") or [])
        if not forbidden_routes:
            issues.append(
                _runtime_issue(
                    "harness_runtime_spine_contract_missing_forbidden_routes",
                    f"Harness runtime spine contract {contract_id or '<missing id>'} lacks forbidden routes.",
                    subject=contract_id,
                )
            )
        base_action_types = _string_set(contract.get("base_action_types"))
        conditional_action_types = _string_set(contract.get("conditional_action_types"))
        forbidden_action_types = _string_set(contract.get("forbidden_action_types"))
        if not base_action_types:
            issues.append(
                _runtime_issue(
                    "harness_runtime_spine_contract_missing_base_actions",
                    f"Harness runtime spine contract {contract_id or '<missing id>'} lacks base task execution actions.",
                    subject=contract_id,
                )
            )
        if not forbidden_action_types:
            issues.append(
                _runtime_issue(
                    "harness_runtime_spine_contract_missing_forbidden_actions",
                    f"Harness runtime spine contract {contract_id or '<missing id>'} lacks forbidden ordinary-turn actions.",
                    subject=contract_id,
                )
            )
        action_overlap = sorted((base_action_types | conditional_action_types) & forbidden_action_types)
        if action_overlap:
            issues.append(
                _runtime_issue(
                    "harness_runtime_spine_contract_action_overlap",
                    f"Harness runtime spine contract {contract_id or '<missing id>'} allows forbidden task execution actions.",
                    subject=contract_id,
                    details={"overlap": action_overlap, "contract": contract},
                )
            )
    return {
        "authority": "harness.runtime.context_contract.diagnostics.runtime_topology_projection.line_governance",
        "issue_count": len(issues),
        "issues": issues,
        "duplicate_control_action_types": duplicate_action_types,
        "duplicate_control_output_line_ids": duplicate_control_line_ids,
        "duplicate_harness_control_spine_line_ids": duplicate_spine_ids,
        "duplicate_context_line_state_ids": duplicate_line_state_ids,
        "duplicate_harness_runtime_spine_contract_ids": duplicate_spine_contract_ids,
    }


def _string_set(value: Any) -> set[str]:
    return {str(item).strip() for item in list(value or []) if str(item).strip()}


def _diagnostic_issue_links(
    issues: list[dict[str, Any]],
    *,
    node_ids: list[str],
    edge_ids: list[str],
) -> list[dict[str, Any]]:
    node_id_set = set(node_ids)
    edge_id_set = set(edge_ids)
    result: list[dict[str, Any]] = []
    seen_issue_ids: set[str] = set()
    for index, issue in enumerate(issues):
        code = str(issue.get("code") or "unknown_issue").strip()
        subject = str(issue.get("subject") or issue.get("edge_id") or issue.get("node_id") or "").strip()
        details = dict(issue.get("details") or {})
        affected_edge_id = _issue_edge_ref(code, subject, details, edge_id_set)
        affected_node_id = _issue_node_ref(code, subject, details, node_id_set)
        affected_line_id = _issue_line_id(code, subject, details)
        affected_action_type = _issue_action_type(code, subject, details)
        affected_contract_id = _issue_contract_id(code, subject, details)
        line_inventory_ref = _issue_line_inventory_ref(code, subject)
        issue_id = _diagnostic_issue_id(code, subject, index=index, seen=seen_issue_ids)
        result.append(
            {
                "issue_id": issue_id,
                "code": code,
                "severity": _issue_severity(code),
                "message": str(issue.get("message") or ""),
                "subject": subject,
                "subject_type": _issue_subject_type(
                    code,
                    subject,
                    affected_edge_id=affected_edge_id,
                    affected_node_id=affected_node_id,
                ),
                "affected_edge_id": affected_edge_id,
                "affected_node_id": affected_node_id,
                "affected_line_id": affected_line_id,
                "affected_action_type": affected_action_type,
                "affected_contract_id": affected_contract_id,
                "line_inventory_ref": line_inventory_ref,
                "governance_ref": _issue_governance_ref(
                    code,
                    subject,
                    affected_line_id=affected_line_id,
                    affected_action_type=affected_action_type,
                    affected_contract_id=affected_contract_id,
                    line_inventory_ref=line_inventory_ref,
                ),
                "line_domain": _issue_line_domain(code, subject),
                "broken_segment": _issue_broken_segment(code),
                "authority": str(issue.get("authority") or ""),
                "details": details,
            }
        )
    return result


def _diagnostic_issue_id(
    code: str,
    subject: str,
    *,
    index: int,
    seen: set[str],
) -> str:
    normalized_code = _identity_fragment(code or "unknown_issue")
    normalized_subject = _identity_fragment(subject or f"issue_{index + 1}")
    base = f"diagnostic_issue:{normalized_code}:{normalized_subject}"
    issue_id = base
    suffix = 2
    while issue_id in seen:
        issue_id = f"{base}:{suffix}"
        suffix += 1
    seen.add(issue_id)
    return issue_id


def _identity_fragment(value: str) -> str:
    normalized = str(value or "").strip().replace(" ", "_")
    return "".join(ch if ch.isalnum() or ch in {"_", "-", ".", ":"} else "_" for ch in normalized)[:120] or "unknown"


def _issue_edge_ref(
    code: str,
    subject: str,
    details: dict[str, Any],
    edge_ids: set[str],
) -> str:
    for candidate in (
        details.get("edge_id"),
        subject,
    ):
        edge_id = str(candidate or "").strip()
        if edge_id in edge_ids:
            return edge_id
    if str(code or "").startswith("missing_edge_") or str(code or "").startswith("duplicate_edge_"):
        return str(subject or "").strip()
    return ""


def _issue_node_ref(
    code: str,
    subject: str,
    details: dict[str, Any],
    node_ids: set[str],
) -> str:
    for candidate in (
        details.get("node_id"),
        subject,
    ):
        node_id = str(candidate or "").strip()
        if node_id in node_ids:
            return node_id
    if str(code or "").startswith("duplicate_node_"):
        return str(subject or "").strip()
    return ""


def _issue_line_id(code: str, subject: str, details: dict[str, Any]) -> str:
    line = dict(details.get("line") or {})
    for candidate in (
        details.get("line_id"),
        line.get("line_id"),
        line.get("control_line_id"),
        line.get("control_output_line_ref"),
        subject if str(subject or "").startswith("control_output_line:") else "",
        subject if "line_id" in str(code or "") else "",
    ):
        line_id = str(candidate or "").strip()
        if line_id:
            return line_id
    return ""


def _issue_action_type(code: str, subject: str, details: dict[str, Any]) -> str:
    line = dict(details.get("line") or {})
    for candidate in (
        details.get("action_type"),
        line.get("action_type"),
        subject if "control_output_line" in str(code or "") or "harness_spine" in str(code or "") else "",
    ):
        action_type = str(candidate or "").strip()
        if action_type and not action_type.startswith("control_output_line:"):
            return action_type
    return ""


def _issue_contract_id(code: str, subject: str, details: dict[str, Any]) -> str:
    contract = dict(details.get("contract") or {})
    for candidate in (
        details.get("contract_id"),
        contract.get("contract_id"),
        subject if "harness_runtime_spine_contract" in str(code or "") else "",
    ):
        contract_id = str(candidate or "").strip()
        if contract_id:
            return contract_id
    return ""


def _issue_line_inventory_ref(code: str, subject: str) -> str:
    value = f"{code} {subject}"
    if "system_asset" in value:
        return "line_governance.system_asset_lines"
    if "context_line_state" in value:
        return "line_governance.context_line_states"
    if "control_output_ref_not_declared" in value or str(subject or "").startswith("control_output_line:"):
        return "line_governance.control_output_lines"
    if "harness_runtime_spine_contract" in value:
        return "line_governance.harness_runtime_spine_contracts"
    if "harness_control_spine" in value or "harness_spine" in value:
        return "line_governance.harness_control_spine_lines"
    if "control_output_line" in value:
        return "line_governance.control_output_lines"
    if str(subject or "").startswith("line_governance"):
        return str(subject or "")
    return ""


def _issue_governance_ref(
    code: str,
    subject: str,
    *,
    affected_line_id: str,
    affected_action_type: str,
    affected_contract_id: str,
    line_inventory_ref: str,
) -> str:
    if affected_line_id:
        return f"{line_inventory_ref or _issue_line_inventory_ref(code, subject)}:{affected_line_id}"
    if affected_contract_id:
        return f"{line_inventory_ref or 'line_governance.harness_runtime_spine_contracts'}:{affected_contract_id}"
    if affected_action_type:
        return f"{line_inventory_ref or 'line_governance.control_output_lines'}:action:{affected_action_type}"
    return line_inventory_ref


def _issue_subject_type(
    code: str,
    subject: str,
    *,
    affected_edge_id: str,
    affected_node_id: str,
) -> str:
    if affected_edge_id:
        return "edge"
    if affected_node_id:
        return "node"
    if subject.startswith("line_governance"):
        return "line_governance"
    if "control_output_line" in code:
        return "control_output_line"
    if "harness_control_spine" in code:
        return "harness_control_spine_line"
    if "harness_runtime_spine_contract" in code:
        return "harness_runtime_spine_contract"
    if "context_line_state" in code:
        return "context_line_state"
    if "system_asset_line" in code:
        return "system_asset_line"
    return "topology"


def _issue_line_domain(code: str, subject: str) -> str:
    value = f"{code} {subject}"
    if "edge" in value or "node" in value:
        return "topology"
    if "system_asset" in value or "context_line_state" in value or "context" in value:
        return "context_input"
    if "control_output" in value or "harness_control_spine" in value:
        return "control_output"
    if "harness_runtime_spine" in value:
        return "harness_runtime_spine"
    return "line_governance"


def _issue_broken_segment(code: str) -> str:
    value = str(code or "")
    if "status" in value:
        return "status"
    if "authority" in value:
        return "authority"
    if "endpoint" in value:
        return "endpoint"
    if "duplicate" in value:
        return "identity"
    if "missing" in value:
        return "declaration"
    if "incomplete" in value:
        return "contract"
    if "overlap" in value or "forbidden" in value:
        return "boundary"
    return "diagnostic"


def _issue_severity(code: str) -> str:
    value = str(code or "")
    if value in {
        "missing_edge_endpoint",
        "harness_runtime_spine_contract_action_overlap",
        "harness_spine_control_output_ref_not_declared",
    }:
        return "P1"
    if (
        value.startswith("duplicate_")
        or value.startswith("missing_")
        or value.startswith("incomplete_")
        or value.endswith("_not_declared")
    ):
        return "P2"
    return "P3"


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
