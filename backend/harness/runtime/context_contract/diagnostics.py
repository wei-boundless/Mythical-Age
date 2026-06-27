from __future__ import annotations

from typing import Any


def diagnose_context_contract_manifest(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    layer_counts: dict[str, int] = {}
    time_counts: dict[str, int] = {}
    visibility_counts: dict[str, int] = {}
    for node in nodes:
        layer = str(node.get("semantic_layer") or "")
        semantic_time = str(node.get("semantic_time") or "")
        visibility = str(node.get("visibility") or "")
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
        time_counts[semantic_time] = time_counts.get(semantic_time, 0) + 1
        visibility_counts[visibility] = visibility_counts.get(visibility, 0) + 1
        if visibility == "agent_visible" and not str(node.get("agent_use_contract") or "").strip():
            issues.append(_issue(node, "missing_agent_use_contract", "Agent-visible context requires an explicit use contract."))
        if visibility == "provider_transport" and str(node.get("semantic_layer") or "") != "L8":
            issues.append(_issue(node, "transport_not_l8", "Provider transport must be represented as L8 hidden transport."))
        if str(node.get("semantic_layer") or "") == "L8" and visibility != "provider_transport":
            issues.append(_issue(node, "l8_agent_visible", "L8 provider transport must not be agent-visible."))
        if str(node.get("semantic_time") or "") == "HiddenTransport" and str(node.get("cache_tier") or "") != "hidden":
            issues.append(_issue(node, "hidden_transport_cache_tier", "Hidden transport must use hidden cache tier."))
        if str(node.get("ttl") or "") == "current_provider_request" and str(node.get("commit_policy") or "") != "never_commit":
            issues.append(_issue(node, "provider_request_commit_policy", "Current provider request nodes must never commit to history."))
        if str(node.get("semantic_time") or "") == "Present" and str(node.get("cache_tier") or "") in {"session", "provider_global"}:
            issues.append(_issue(node, "present_in_stable_cache", "Present-time context should not be placed in stable cache tiers."))
    return {
        "authority": "harness.runtime.context_contract.diagnostics",
        "issue_count": len(issues),
        "issues": issues,
        "layer_counts": layer_counts,
        "semantic_time_counts": time_counts,
        "visibility_counts": visibility_counts,
        "provider_transport_hidden": all(
            str(node.get("visibility") or "") != "provider_transport" or str(node.get("semantic_layer") or "") == "L8"
            for node in nodes
        ),
    }


def _issue(node: dict[str, Any], code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "node_id": str(node.get("node_id") or ""),
        "semantic_layer": str(node.get("semantic_layer") or ""),
        "semantic_time": str(node.get("semantic_time") or ""),
        "visibility": str(node.get("visibility") or ""),
        "authority": "harness.runtime.context_contract.diagnostics",
    }
