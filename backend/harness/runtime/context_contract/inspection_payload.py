from __future__ import annotations

from typing import Any

from .nodes import ContextContractManifest


def build_context_contract_inspection_payload(manifest: ContextContractManifest | dict[str, Any]) -> dict[str, Any]:
    payload = manifest.to_dict() if isinstance(manifest, ContextContractManifest) else dict(manifest or {})
    nodes = [dict(item) for item in list(payload.get("nodes") or []) if isinstance(item, dict)]
    return {
        "authority": "harness.runtime.context_contract.inspection_payload",
        "packet_id": str(payload.get("packet_id") or ""),
        "invocation_kind": str(payload.get("invocation_kind") or ""),
        "summary": {
            "node_count": len(nodes),
            "agent_visible_count": sum(1 for node in nodes if node.get("visibility") == "agent_visible"),
            "hidden_transport_count": sum(1 for node in nodes if node.get("visibility") == "provider_transport"),
            "issue_count": int(dict(payload.get("diagnostics") or {}).get("issue_count") or 0),
        },
        "layers": _group(nodes, "semantic_layer"),
        "semantic_times": _group(nodes, "semantic_time"),
        "cache_tiers": _group(nodes, "cache_tier"),
        "manifest": payload,
    }


def _group(nodes: list[dict[str, Any]], key: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for node in nodes:
        value = str(node.get(key) or "unknown")
        grouped.setdefault(value, []).append(str(node.get("node_id") or ""))
    return grouped
