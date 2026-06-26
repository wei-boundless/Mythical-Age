from __future__ import annotations

from typing import Any

from runtime.shared.tool_schema_canonical import canonical_provider_tool_input_schema, json_stable

from .tool_catalog_manifest import ToolCatalogManifest


def provider_tool_bindings_for_available_tools(
    available_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for item in list(available_tools or []):
        tool = dict(item or {})
        name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        if not name:
            continue
        schema = canonical_provider_tool_input_schema(tool)
        bindings.append(
            {
                "name": name,
                "description": str(tool.get("description") or tool.get("display_name") or name),
                "input_schema": schema,
            }
        )
    return sorted(bindings, key=lambda item: str(item.get("name") or ""))


def stable_tool_schema_catalog_payload(
    *,
    tool_payloads: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    tool_catalog_manifest: ToolCatalogManifest,
) -> dict[str, Any]:
    tools = [
        {
            "name": str(binding.get("name") or ""),
            "description": str(binding.get("description") or ""),
            "schema": json_stable(dict(binding.get("input_schema") or {})),
        }
        for binding in provider_tool_bindings_for_available_tools(tool_payloads)
    ]
    if not tools:
        return {}
    return {
        "tool_binding_contract": {
            "contract_role": "cacheable_tool_contract_view",
            "native_binding": "model_request.tools",
            "native_binding_semantics": "authoritative_structured_tool_call_schema",
            "cache_rule": "This message is the cacheable tool contract view; the native tools payload carries the same schema fingerprint for provider tool calling and is not prompt-prefix text.",
        },
        "tool_catalog_hash": str(tool_catalog_manifest.tool_catalog_hash or ""),
        "stable_tool_catalog_hash": str(tool_catalog_manifest.stable_tool_catalog_hash or ""),
        "tool_schema_refs": [dict(item) for item in tuple(tool_catalog_manifest.tool_schema_refs or ())],
        "tools": tools,
    }
