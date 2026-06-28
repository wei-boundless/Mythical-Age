from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


def canonical_provider_input_schema(tool_payload: dict[str, Any]) -> dict[str, Any]:
    tool = dict(tool_payload or {})
    schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else tool.get("parameters")
    if isinstance(schema, dict) and schema:
        return canonical_json_schema_object(schema)
    return schema_from_contract(
        required_inputs=list(tool.get("required_inputs") or []),
        optional_inputs=list(tool.get("optional_inputs") or []),
    )


def canonical_json_schema_object(schema: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(schema or {}))
    payload.setdefault("type", "object")
    payload.setdefault("properties", {})
    if not isinstance(payload.get("properties"), dict):
        payload["properties"] = {}
    required = payload.get("required")
    payload["required"] = [str(item) for item in list(required or []) if str(item)]
    return json_stable(payload)


def schema_from_contract(*, required_inputs: list[Any], optional_inputs: list[Any]) -> dict[str, Any]:
    required = [str(item).strip() for item in required_inputs if str(item).strip()]
    optional = [str(item).strip() for item in optional_inputs if str(item).strip()]
    properties = {name: {"type": "string"} for name in [*required, *optional]}
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def provider_input_schema_ref(schema: Any, *, prefix_chars: int = 10) -> str:
    digest = stable_json_hash(canonical_json_schema_object(schema) if isinstance(schema, dict) else {})
    return "sha256:" + digest.removeprefix("sha256:")[:prefix_chars]


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
