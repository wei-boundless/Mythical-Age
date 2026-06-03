from __future__ import annotations

from dataclasses import replace
from typing import Any

from .models import GraphHarnessConfig, GraphNodeWorkOrder


_SECRET_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "client_secret",
    "clientsecret",
}
_ALLOWED_MODEL_FIELDS = {
    "provider",
    "provider_family",
    "model",
    "model_family",
    "credential_ref",
    "max_output_tokens",
    "preferred_output_tokens",
    "min_output_tokens",
    "timeout_seconds",
    "long_output_timeout_seconds",
    "max_retries",
    "temperature",
    "thinking_mode",
    "reasoning_effort",
    "stream_policy",
    "fallback_allowed",
}


def sanitize_runtime_overrides(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    _reject_raw_secret_keys(value)
    _reject_runtime_authority_expansion(value)
    payload = _sanitize_mapping(value)
    model_overrides = payload.get("model_overrides")
    if isinstance(model_overrides, dict):
        payload["model_overrides"] = _sanitize_model_overrides(model_overrides)
    return payload


def merge_runtime_settings(*, current: Any, patch: Any) -> dict[str, Any]:
    base = sanitize_runtime_overrides(current)
    update = sanitize_runtime_overrides(patch)
    if not update:
        return base
    return _deep_merge(base, update)


def merge_effective_runtime_overrides(*, persistent: Any, temporary: Any) -> dict[str, Any]:
    return merge_runtime_settings(current=persistent, patch=temporary)


def work_order_with_model_overrides(
    *,
    graph_config: GraphHarnessConfig,
    work_order: GraphNodeWorkOrder,
    runtime_overrides: Any,
) -> tuple[GraphNodeWorkOrder, dict[str, Any]]:
    overrides = sanitize_runtime_overrides(runtime_overrides)
    model_overrides = _model_overrides_payload(overrides)
    if not model_overrides:
        return work_order, {}
    node = _node_by_id(graph_config, work_order.node_id)
    if not node:
        return work_order, {}
    matched = _matched_model_override(model_overrides=model_overrides, node=node, work_order=work_order)
    override = dict(matched.get("override") or {})
    if not override:
        return work_order, {}

    graph_slot = dict(work_order.graph_slot or {})
    node_contract = dict(graph_slot.get("node_contract") or {})
    original_requirement = dict(node_contract.get("model_requirement") or {})
    effective_requirement = _merge_model_requirement(original_requirement, override)
    diagnostics = {
        "authority": "harness.graph.model_overrides",
        "matched_scope": str(matched.get("matched_scope") or ""),
        "matched_key": str(matched.get("matched_key") or ""),
        "source": str(overrides.get("source") or "graph_runtime_overrides"),
        "original": _public_model_requirement(original_requirement),
        "effective": _public_model_requirement(effective_requirement),
    }
    node_contract["model_requirement"] = effective_requirement
    graph_slot["node_contract"] = node_contract

    input_package = dict(work_order.input_package or {})
    runtime_profile = dict(input_package.get("runtime_profile") or {})
    runtime_profile["model_requirement"] = dict(effective_requirement)
    input_package["runtime_profile"] = runtime_profile
    input_package["model_override_diagnostics"] = dict(diagnostics)

    dispatch_context = dict(work_order.dispatch_context or {})
    dispatch_context["model_override_diagnostics"] = dict(diagnostics)

    return replace(
        work_order,
        graph_slot=graph_slot,
        input_package=input_package,
        dispatch_context=dispatch_context,
    ), diagnostics


def _sanitize_mapping(value: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(item, dict):
            payload[normalized_key] = _sanitize_mapping(item)
        elif isinstance(item, list):
            payload[normalized_key] = [
                _sanitize_mapping(child) if isinstance(child, dict) else child
                for child in item
            ]
        else:
            payload[normalized_key] = item
    return payload


def _sanitize_model_overrides(value: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for section in ("global", "role_groups", "roles", "agents", "agent_ids", "nodes", "node_ids"):
        item = value.get(section)
        if item is None:
            continue
        if section == "global":
            payload[section] = _model_field_payload(dict(item or {}) if isinstance(item, dict) else {})
        elif isinstance(item, dict):
            payload[section] = {
                str(key).strip(): _model_field_payload(dict(child or {}) if isinstance(child, dict) else {})
                for key, child in item.items()
                if str(key).strip()
            }
    return payload


def _model_field_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key).strip(): item
        for key, item in dict(value or {}).items()
        if str(key).strip() in _ALLOWED_MODEL_FIELDS
    }


def _reject_raw_secret_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            if normalized_key in _SECRET_KEYS:
                raise ValueError("runtime model overrides must use credential_ref and must not contain raw secrets")
            _reject_raw_secret_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_raw_secret_keys(item)


def _reject_runtime_authority_expansion(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            if normalized_key in {
                "tool_policy_overrides",
                "node_runtime_policy_overrides",
                "allowed_operations",
                "allowed_subagent_ids",
                "file_access_table_refs",
                "permission_scope",
                "network_policy",
            }:
                raise ValueError("runtime settings patch cannot expand graph node authorization; publish a compatible config with a static ceiling")
            if normalized_key == "subagent_policy" and bool(dict(item or {}).get("enabled") is True):
                raise ValueError("runtime settings patch cannot enable subagents beyond the graph node authorization ceiling")
            _reject_runtime_authority_expansion(item)
    elif isinstance(value, list):
        for item in value:
            _reject_runtime_authority_expansion(item)


def _model_overrides_payload(overrides: dict[str, Any]) -> dict[str, Any]:
    payload = overrides.get("model_overrides")
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _matched_model_override(*, model_overrides: dict[str, Any], node: dict[str, Any], work_order: GraphNodeWorkOrder) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    matched_scope = ""
    matched_key = ""

    def apply(scope: str, key: str, payload: Any) -> None:
        nonlocal merged, matched_scope, matched_key
        item = dict(payload or {}) if isinstance(payload, dict) else {}
        if not item:
            return
        merged = {**merged, **item}
        matched_scope = scope
        matched_key = key

    apply("global", "global", model_overrides.get("global"))

    role_group = _role_group_for_node(node=node, work_order=work_order)
    role_groups = {**dict(model_overrides.get("roles") or {}), **dict(model_overrides.get("role_groups") or {})}
    apply("role_group", role_group, role_groups.get(role_group))

    agent_id = str(work_order.agent_id or node.get("agent_id") or "").strip()
    agents = {**dict(model_overrides.get("agents") or {}), **dict(model_overrides.get("agent_ids") or {})}
    apply("agent_id", agent_id, agents.get(agent_id))

    full_node_id = str(work_order.node_id or node.get("node_id") or "").strip()
    bare_node_id = _bare_node_id(full_node_id)
    nodes = {**dict(model_overrides.get("nodes") or {}), **dict(model_overrides.get("node_ids") or {})}
    apply("node_id", bare_node_id, nodes.get(bare_node_id))
    apply("node_id", full_node_id, nodes.get(full_node_id))

    return {"override": merged, "matched_scope": matched_scope, "matched_key": matched_key}


def _merge_model_requirement(original: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    effective = dict(original or {})
    provider = str(override.get("provider") or override.get("provider_family") or "").strip()
    model = str(override.get("model") or override.get("model_family") or "").strip()
    if provider:
        effective["provider"] = provider
        effective["provider_family"] = provider
    if model:
        effective["model"] = model
        effective["model_family"] = model
    for key, value in override.items():
        normalized_key = str(key or "").strip()
        if normalized_key in {"provider", "provider_family", "model", "model_family"}:
            continue
        if normalized_key in _ALLOWED_MODEL_FIELDS:
            effective[normalized_key] = value
    return effective


def _public_model_requirement(value: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "profile_ref",
        "provider",
        "provider_family",
        "model",
        "model_family",
        "credential_ref",
        "preferred_output_tokens",
        "max_output_tokens",
        "thinking_mode",
        "reasoning_effort",
    )
    return {key: value.get(key) for key in keys if key in value}


def _node_by_id(graph_config: GraphHarnessConfig, node_id: str) -> dict[str, Any]:
    target = str(node_id or "").strip()
    for node in graph_config.nodes:
        current = str(dict(node).get("node_id") or "").strip()
        if current == target:
            return dict(node)
    return {}


def _bare_node_id(node_id: str) -> str:
    return str(node_id or "").rsplit("::", 1)[-1]


def _role_group_for_node(*, node: dict[str, Any], work_order: GraphNodeWorkOrder) -> str:
    node_id = _bare_node_id(str(work_order.node_id or node.get("node_id") or ""))
    agent_id = str(work_order.agent_id or node.get("agent_id") or "").strip()
    node_type = str(node.get("node_type") or "").strip()
    if "memory" in node_id or agent_id.endswith("memory_steward"):
        return "memory"
    if node_type == "review_gate" or "review" in node_id or agent_id.endswith("reviewer"):
        return "review"
    return "writing"


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in dict(update or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged.get(key) or {}), dict(value))
        else:
            merged[key] = value
    return merged
