from __future__ import annotations

from typing import Any

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
        schema = _provider_input_schema(tool)
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
            "schema": _json_stable(dict(binding.get("input_schema") or {})),
        }
        for binding in provider_tool_bindings_for_available_tools(tool_payloads)
    ]
    if not tools:
        return {}
    return {
        "tool_catalog_hash": str(tool_catalog_manifest.tool_catalog_hash or ""),
        "stable_tool_catalog_hash": str(tool_catalog_manifest.stable_tool_catalog_hash or ""),
        "tool_schema_refs": [dict(item) for item in tuple(tool_catalog_manifest.tool_schema_refs or ())],
        "tools": tools,
    }


def _provider_input_schema(tool: dict[str, Any]) -> dict[str, Any]:
    schema = dict(tool.get("input_schema") or {}) if isinstance(tool.get("input_schema"), dict) else {}
    if schema:
        return _json_stable(schema)
    properties = {
        str(value): {"type": "string"}
        for value in list(tool.get("required_inputs") or [])
        if str(value)
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
    }


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
