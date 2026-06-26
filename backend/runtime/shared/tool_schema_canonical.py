from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


def canonical_provider_tool_input_schema(tool: Any) -> dict[str, Any]:
    if isinstance(tool, dict):
        schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else tool.get("parameters")
        if isinstance(schema, dict) and schema:
            return canonical_json_schema_object(schema)
        return schema_from_contract(
            required_inputs=list(tool.get("required_inputs") or []),
            optional_inputs=list(tool.get("optional_inputs") or []),
        )

    for schema_source in (getattr(tool, "input_schema", None), getattr(tool, "args_schema", None)):
        schema = schema_from_source(schema_source)
        if schema:
            return canonical_json_schema_object(schema)

    capability_definition = getattr(tool, "capability_definition", None)
    contract = getattr(capability_definition, "contract", None)
    return schema_from_contract(
        required_inputs=list(getattr(contract, "required_inputs", []) or []),
        optional_inputs=list(getattr(contract, "optional_inputs", []) or []),
    )


def canonical_provider_tool_input_schema_ref(tool: Any) -> str:
    return canonical_provider_schema_ref(canonical_provider_tool_input_schema(tool))


def canonical_provider_schema_ref(schema: Any, *, prefix_chars: int = 10) -> str:
    normalized = canonical_json_schema_object(schema) if isinstance(schema, dict) else json_stable(schema or {})
    digest = stable_json_hash(normalized)
    return "sha256:" + digest.removeprefix("sha256:")[: max(1, int(prefix_chars or 1))]


def canonical_json_schema_object(schema: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(schema)
    payload.setdefault("type", "object")
    payload.setdefault("properties", {})
    if not isinstance(payload.get("properties"), dict):
        payload["properties"] = {}
    required = payload.get("required")
    payload["required"] = [str(item) for item in list(required or []) if str(item)]
    return json_stable(payload)


def schema_from_source(schema_source: Any) -> dict[str, Any]:
    if schema_source is None:
        return {}
    if isinstance(schema_source, dict):
        return dict(schema_source)
    for method_name in ("model_json_schema", "schema"):
        method = getattr(schema_source, method_name, None)
        if callable(method):
            try:
                schema = method()
            except Exception:
                continue
            if isinstance(schema, dict):
                return dict(schema)
    return {}


def schema_from_contract(*, required_inputs: list[Any], optional_inputs: list[Any]) -> dict[str, Any]:
    required = [str(item).strip() for item in list(required_inputs or []) if str(item).strip()]
    optional = [str(item).strip() for item in list(optional_inputs or []) if str(item).strip()]
    properties = {name: {"type": "string"} for name in [*required, *optional]}
    return json_stable(
        {
            "type": "object",
            "properties": properties,
            "required": required,
        }
    )


def stable_json_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8", errors="ignore")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
