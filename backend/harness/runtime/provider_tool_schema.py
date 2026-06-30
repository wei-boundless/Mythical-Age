from __future__ import annotations

from typing import Any

from .tool_catalog_manifest import ToolCatalogManifest
from .tool_schema_identity import canonical_provider_tool_binding_schema, json_stable, schema_with_public_feedback_sidecar


def provider_tool_bindings_for_available_tools(
    available_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for item in list(available_tools or []):
        tool = dict(item or {})
        name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        if not name:
            continue
        schema = canonical_provider_tool_binding_schema(tool)
        binding = {
            "name": name,
            "description": str(tool.get("description") or tool.get("display_name") or name),
            "input_schema": schema,
        }
        if "strict" in tool and tool.get("strict") is not None:
            binding["strict"] = bool(tool.get("strict"))
        if isinstance(tool.get("metadata"), dict):
            binding["metadata"] = dict(tool.get("metadata") or {})
        bindings.append(binding)
    return sorted(bindings, key=lambda item: str(item.get("name") or ""))


def tool_schema_with_public_feedback_sidecar(schema: dict[str, Any] | None) -> dict[str, Any]:
    return schema_with_public_feedback_sidecar(schema)


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
            "native_binding": "provider_request.tools",
            "native_binding_semantics": "authoritative_structured_tool_call_schema",
            "cache_rule": "This message is the cacheable tool contract view; when the native tools payload matches this schema fingerprint, it is accounted as the provider physical tool schema prefix before messages.",
        },
        "tool_catalog_hash": str(tool_catalog_manifest.tool_catalog_hash or ""),
        "stable_tool_catalog_hash": str(tool_catalog_manifest.stable_tool_catalog_hash or ""),
        "tool_schema_refs": [dict(item) for item in tuple(tool_catalog_manifest.tool_schema_refs or ())],
        "tools": tools,
    }
