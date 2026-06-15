from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library.tool_prompts import tool_guidance_payload_for_visible_tools

_MODEL_VISIBLE_PROMPT_POLICIES = {"schema_only", "schema_plus_guidance"}
_SPECIAL_CONTRACT_TOOL_NAMES = {
    "agent_todo",
    "write_file",
    "edit_file",
    "spawn_subagent",
    "glob_paths",
    "search_files",
    "read_file",
    "search_text",
    "path_exists",
    "stat_path",
    "list_dir",
}


@dataclass(frozen=True, slots=True)
class ToolCatalogManifest:
    manifest_id: str
    invocation_kind: str
    source_ref: str
    raw_tool_count: int
    visible_tool_count: int
    tool_names: tuple[str, ...] = ()
    tool_catalog_hash: str = ""
    stable_tool_catalog_hash: str = ""
    tool_schema_refs: tuple[dict[str, str], ...] = ()
    exposure_policy_counts: dict[str, int] = field(default_factory=dict)
    model_visible_catalog: tuple[dict[str, Any], ...] = ()
    tool_guidance_payload: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.tool_catalog_manifest"

    def to_model_visible_payload(self, *, include_catalog_hash: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "available_tools": [dict(item) for item in self.model_visible_catalog],
        }
        if include_catalog_hash:
            payload["tool_catalog_hash"] = self.tool_catalog_hash
        payload.update(_deepcopy_json_dict(self.tool_guidance_payload))
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tool_names"] = list(self.tool_names)
        payload["tool_schema_refs"] = [dict(item) for item in self.tool_schema_refs]
        payload["exposure_policy_counts"] = dict(self.exposure_policy_counts)
        payload["model_visible_catalog"] = [dict(item) for item in self.model_visible_catalog]
        payload["tool_guidance_payload"] = _deepcopy_json_dict(self.tool_guidance_payload)
        return payload


def build_tool_catalog_manifest(
    *,
    invocation_kind: str,
    tool_payloads: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None,
    source_ref: str = "runtime.available_tools",
    tool_guidance_prompt_defaults: dict[str, str] | None = None,
    tool_guidance_prompt_overrides: dict[str, str] | None = None,
) -> ToolCatalogManifest:
    raw_tools = tuple(dict(item) for item in list(tool_payloads or []) if isinstance(item, dict))
    model_visible_catalog = tuple(_model_visible_tool_entry(item) for item in raw_tools)
    model_visible_catalog = tuple(item for item in model_visible_catalog if item)
    tool_names = tuple(str(item.get("tool_name") or "") for item in model_visible_catalog)
    guidance_payload = tool_guidance_payload_for_visible_tools(
        model_visible_catalog,
        guidance_prompt_defaults=tool_guidance_prompt_defaults,
        guidance_prompt_overrides=tool_guidance_prompt_overrides,
    )
    exposure_policy_counts: dict[str, int] = {}
    for item in raw_tools:
        policy = str(item.get("prompt_exposure_policy") or "schema_only").strip() or "schema_only"
        exposure_policy_counts[policy] = exposure_policy_counts.get(policy, 0) + 1
    tool_schema_refs = tuple(
        {
            "tool_name": str(item.get("tool_name") or ""),
            "input_schema_ref": str(item.get("input_schema_ref") or ""),
        }
        for item in model_visible_catalog
        if str(item.get("input_schema_ref") or "")
    )
    raw_catalog_hash = _stable_json_hash([dict(item) for item in raw_tools])
    stable_catalog_hash = _stable_json_hash([dict(item) for item in model_visible_catalog])
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "source_ref": str(source_ref or ""),
        "tool_catalog_hash": raw_catalog_hash,
        "stable_tool_catalog_hash": stable_catalog_hash,
        "tool_guidance_hash": str(guidance_payload.get("tool_guidance_hash") or ""),
    }
    return ToolCatalogManifest(
        manifest_id="toolcatalog:" + _digest(seed),
        invocation_kind=str(invocation_kind or ""),
        source_ref=str(source_ref or ""),
        raw_tool_count=len(raw_tools),
        visible_tool_count=len(model_visible_catalog),
        tool_names=tool_names,
        tool_catalog_hash=raw_catalog_hash,
        stable_tool_catalog_hash=stable_catalog_hash,
        tool_schema_refs=tool_schema_refs,
        exposure_policy_counts=exposure_policy_counts,
        model_visible_catalog=model_visible_catalog,
        tool_guidance_payload=guidance_payload,
    )


def _model_visible_tool_entry(tool_payload: dict[str, Any]) -> dict[str, Any]:
    tool = dict(tool_payload or {})
    name = str(tool.get("tool_name") or tool.get("name") or "").strip()
    if not name:
        return {}
    prompt_exposure_policy = str(tool.get("prompt_exposure_policy") or "schema_only").strip() or "schema_only"
    if prompt_exposure_policy not in _MODEL_VISIBLE_PROMPT_POLICIES:
        return {}
    required_inputs = [str(value) for value in list(tool.get("required_inputs") or []) if str(value)]
    optional_inputs = [str(value) for value in list(tool.get("optional_inputs") or []) if str(value)]
    payload: dict[str, Any] = {
        "tool_name": name,
        "operation_id": str(tool.get("operation_id") or ""),
    }
    if prompt_exposure_policy:
        payload["prompt_exposure_policy"] = prompt_exposure_policy
    if required_inputs:
        payload["required_inputs"] = required_inputs
    if optional_inputs:
        payload["optional_inputs"] = optional_inputs
    owner_scope = str(tool.get("owner_scope") or "")
    if owner_scope and owner_scope != "none":
        payload["owner_scope"] = owner_scope
    if "read_only" in tool:
        payload["read_only"] = bool(tool.get("read_only") is True)
    if "concurrency_safe" in tool:
        payload["concurrency_safe"] = bool(tool.get("concurrency_safe") is True)
    path_policy = dict(tool.get("path_policy") or {}) if isinstance(tool.get("path_policy"), dict) else {}
    if path_policy:
        payload["path_policy"] = {
            key: value
            for key, value in {
                "path_field": str(path_policy.get("path_field") or ""),
                "path_kind": str(path_policy.get("path_kind") or ""),
            }.items()
            if value
        }
    output_contract = dict(tool.get("output_contract") or {}) if isinstance(tool.get("output_contract"), dict) else {}
    if output_contract:
        payload["output_contract"] = {
            key: value
            for key, value in {
                "display_mode": str(output_contract.get("display_mode") or ""),
                "finalization_policy": str(output_contract.get("finalization_policy") or ""),
                "persistence_policy": str(output_contract.get("persistence_policy") or ""),
            }.items()
            if value
        }
    input_schema = dict(tool.get("input_schema") or {}) if isinstance(tool.get("input_schema"), dict) else {}
    if input_schema:
        input_schema_summary = _input_schema_summary(input_schema)
        payload["input_schema_summary"] = input_schema_summary
        payload["input_schema_ref"] = _short_hash(_stable_json_hash(input_schema))
        tool_contract_summary = _special_tool_contract_summary(
            tool_name=name,
            input_schema_summary=input_schema_summary,
        )
        if tool_contract_summary:
            payload["tool_contract_summary"] = tool_contract_summary
    return payload


def _input_schema_summary(schema: dict[str, Any]) -> dict[str, Any]:
    properties = dict(schema.get("properties") or {})
    summarized_properties: dict[str, str] = {}
    property_details: dict[str, dict[str, Any]] = {}
    for name, value in properties.items():
        if not isinstance(value, dict):
            continue
        summarized_properties[str(name)] = _field_summary(value, root_schema=schema)
        property_details[str(name)] = _field_detail(value, root_schema=schema)
    summary: dict[str, Any] = {"properties": summarized_properties}
    if property_details:
        summary["property_details"] = property_details
    field_paths = _schema_field_paths(properties, root_schema=schema)
    if field_paths:
        summary["field_paths"] = field_paths
    schema_type = str(schema.get("type") or "object")
    if schema_type != "object":
        summary["type"] = schema_type
    required = [str(item) for item in list(schema.get("required") or []) if str(item)]
    if required:
        summary["required"] = required
    optional = [str(name) for name in summarized_properties if str(name) not in set(required)]
    if optional:
        summary["optional"] = optional
    if "additionalProperties" in schema:
        summary["additionalProperties"] = bool(schema.get("additionalProperties") is True)
        summary["forbidden_unknown_fields"] = schema.get("additionalProperties") is False
    return summary


def _field_summary(schema: dict[str, Any], *, root_schema: dict[str, Any]) -> str:
    field_schema = _resolve_schema_ref(schema, root_schema=root_schema)
    field_type = _field_type_label(field_schema, root_schema=root_schema)
    parts = [field_type]
    if field_schema.get("format"):
        parts.append(f"format={field_schema.get('format')}")
    if "enum" in field_schema:
        enum_values = [str(item) for item in list(field_schema.get("enum") or [])]
        if enum_values:
            parts.append("enum=" + "|".join(enum_values))
    if "default" in field_schema:
        parts.append("default=" + json.dumps(field_schema.get("default"), ensure_ascii=False, separators=(",", ":")))
    return " ".join(parts)


def _field_detail(schema: dict[str, Any], *, root_schema: dict[str, Any]) -> dict[str, Any]:
    field_schema = _resolve_schema_ref(schema, root_schema=root_schema)
    detail: dict[str, Any] = {"type": _field_type_label(field_schema, root_schema=root_schema)}
    for key in ("format", "description"):
        value = field_schema.get(key)
        if value:
            detail[key] = str(value)
    if "enum" in field_schema:
        enum_values = [str(item) for item in list(field_schema.get("enum") or [])]
        if enum_values:
            detail["enum"] = enum_values
    if "default" in field_schema:
        detail["default"] = field_schema.get("default")
    for key in ("minimum", "maximum", "minLength", "maxLength"):
        if key in field_schema:
            detail[key] = field_schema.get(key)
    if "additionalProperties" in field_schema:
        detail["additionalProperties"] = bool(field_schema.get("additionalProperties") is True)
        detail["forbidden_unknown_fields"] = field_schema.get("additionalProperties") is False
    items = field_schema.get("items")
    if isinstance(items, dict):
        resolved_items = _resolve_schema_ref(items, root_schema=root_schema)
        detail["items"] = _field_detail(resolved_items, root_schema=root_schema)
    return {key: _json_stable(value) for key, value in detail.items() if value not in ("", [], {})}


def _schema_field_paths(
    properties: dict[str, Any],
    *,
    root_schema: dict[str, Any],
    parent: str = "",
    max_depth: int = 3,
) -> dict[str, dict[str, Any]]:
    if max_depth <= 0:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for raw_name, raw_schema in properties.items():
        if not isinstance(raw_schema, dict):
            continue
        name = str(raw_name or "").strip()
        if not name:
            continue
        field_schema = _resolve_schema_ref(raw_schema, root_schema=root_schema)
        path = f"{parent}.{name}" if parent else name
        result[path] = _field_detail(field_schema, root_schema=root_schema)
        items = field_schema.get("items")
        if isinstance(items, dict):
            item_schema = _resolve_schema_ref(items, root_schema=root_schema)
            item_properties = dict(item_schema.get("properties") or {}) if isinstance(item_schema.get("properties"), dict) else {}
            if item_properties:
                result.update(
                    _schema_field_paths(
                        item_properties,
                        root_schema=root_schema,
                        parent=f"{path}[]",
                        max_depth=max_depth - 1,
                    )
                )
        child_properties = dict(field_schema.get("properties") or {}) if isinstance(field_schema.get("properties"), dict) else {}
        if child_properties:
            result.update(
                _schema_field_paths(
                    child_properties,
                    root_schema=root_schema,
                    parent=path,
                    max_depth=max_depth - 1,
                )
            )
    return result


def _field_type_label(schema: dict[str, Any], *, root_schema: dict[str, Any]) -> str:
    field_schema = _resolve_schema_ref(schema, root_schema=root_schema)
    raw_type = field_schema.get("type")
    if isinstance(raw_type, list):
        field_type = "|".join(str(item) for item in raw_type if str(item)) or "any"
    else:
        field_type = str(raw_type or ("string" if field_schema.get("enum") else "any"))
    items = field_schema.get("items")
    if isinstance(items, dict):
        item_schema = _resolve_schema_ref(items, root_schema=root_schema)
        item_type = _field_type_label(item_schema, root_schema=root_schema)
        field_type = f"{field_type}<{item_type}>"
    return field_type


def _resolve_schema_ref(schema: dict[str, Any], *, root_schema: dict[str, Any]) -> dict[str, Any]:
    ref = str(schema.get("$ref") or "").strip()
    if not ref.startswith("#/"):
        return dict(schema)
    target: Any = root_schema
    for part in ref[2:].split("/"):
        if not isinstance(target, dict):
            return dict(schema)
        target = target.get(part.replace("~1", "/").replace("~0", "~"))
    if not isinstance(target, dict):
        return dict(schema)
    merged = dict(target)
    for key, value in schema.items():
        if key != "$ref":
            merged[key] = value
    return merged


def _special_tool_contract_summary(*, tool_name: str, input_schema_summary: dict[str, Any]) -> dict[str, Any]:
    name = str(tool_name or "").strip()
    if name not in _SPECIAL_CONTRACT_TOOL_NAMES:
        return {}
    summary: dict[str, Any] = {
        "authority": "harness.runtime.tool_catalog_manifest.tool_contract_summary",
        "required_inputs": [str(item) for item in list(input_schema_summary.get("required") or []) if str(item)],
        "optional_inputs": [str(item) for item in list(input_schema_summary.get("optional") or []) if str(item)],
        "forbidden_unknown_fields": bool(input_schema_summary.get("forbidden_unknown_fields") is True),
    }
    field_paths = dict(input_schema_summary.get("field_paths") or {})
    if name == "agent_todo":
        summary.update(
            {
                "critical_fields": {
                    "items[].status": dict(field_paths.get("items[].status") or {}),
                    "todo_id": dict(field_paths.get("todo_id") or {}),
                    "status": dict(field_paths.get("status") or {}),
                },
                "forbidden_fields": ["id", "item_id", "todo", "todos"],
                "forbidden_values": {"items[].status": ["active"], "status": ["active"]},
            }
        )
    elif name == "spawn_subagent":
        summary.update(
            {
                "critical_fields": {"target_agent_id": dict(field_paths.get("target_agent_id") or {})},
                "runtime_constraint": "target_agent_id must be one of runtime_boundary.tool_boundary.allowed_subagent_ids.",
                "forbidden_fields": ["agent_id", "target_subagent_id"],
            }
        )
    elif name == "write_file":
        summary.update(
            {
                "critical_fields": {
                    "path": dict(field_paths.get("path") or {}),
                    "content": dict(field_paths.get("content") or {}),
                    "allow_overwrite": dict(field_paths.get("allow_overwrite") or {}),
                    "expected_previous_sha256": dict(field_paths.get("expected_previous_sha256") or {}),
                }
            }
        )
    elif name == "edit_file":
        summary.update(
            {
                "critical_fields": {
                    "path": dict(field_paths.get("path") or {}),
                    "old_text": dict(field_paths.get("old_text") or {}),
                    "new_text": dict(field_paths.get("new_text") or {}),
                }
            }
        )
    elif name == "read_file":
        summary.update(
            {
                "critical_fields": {
                    "path": dict(field_paths.get("path") or {}),
                    "start_line": dict(field_paths.get("start_line") or {}),
                    "line_count": dict(field_paths.get("line_count") or {}),
                    "read_intent": dict(field_paths.get("read_intent") or {}),
                },
                "usage_hint": (
                    "Use directly for known file paths, including file-like task_contract.working_scope.target_objects, "
                    "source_refs, workspace_refs, or bound/editor paths. Do not call search_files first for a known path."
                ),
                "output_facts": ["start_line", "end_line", "total_lines", "has_more", "next_start_line", "content_sha256", "file_unchanged"],
            }
        )
    elif name == "path_exists":
        summary.update(
            {
                "critical_fields": {"path": dict(field_paths.get("path") or {})},
                "usage_hint": (
                    "Use to confirm a known path from task_contract.working_scope, bound context, or editor context. "
                    "It is a direct path check, not a search tool."
                ),
                "output_facts": ["path", "exists", "kind"],
            }
        )
    elif name == "stat_path":
        summary.update(
            {
                "critical_fields": {"path": dict(field_paths.get("path") or {})},
                "usage_hint": "Use for metadata about a known path. Do not use search_files first when the path is already known.",
                "output_facts": ["path", "exists", "kind", "size", "modified_at"],
            }
        )
    elif name == "list_dir":
        summary.update(
            {
                "critical_fields": {"path": dict(field_paths.get("path") or {})},
                "usage_hint": "Use for a known directory path. Do not use search_files to rediscover an already known directory.",
                "output_facts": ["path", "entries"],
            }
        )
    elif name == "glob_paths":
        summary.update(
            {
                "critical_fields": {"pattern": dict(field_paths.get("pattern") or {})},
                "usage_hint": "Use for explicit wildcard path patterns such as *.html, **/*.py, or backend/**/*.ts. It returns paths, not file contents.",
                "output_facts": ["pattern", "matches"],
            }
        )
    elif name == "search_files":
        summary.update(
            {
                "critical_fields": {
                    "query": dict(field_paths.get("query") or {}),
                    "roots": dict(field_paths.get("roots") or {}),
                },
                "usage_hint": (
                    "Use for filename or path keywords only when the exact path is unknown. "
                    "If task_contract.working_scope.target_objects/source_refs/workspace_refs or bound/editor context already gives a file-like path, "
                    "use path_exists/read_file directly instead of search_files."
                ),
                "output_facts": ["query", "matches", "searched_roots", "used_default_roots", "omitted_workspace_root", "search_meta"],
            }
        )
    elif name == "search_text":
        summary.update(
            {
                "critical_fields": {
                    "query": dict(field_paths.get("query") or {}),
                    "roots": dict(field_paths.get("roots") or {}),
                    "paths": dict(field_paths.get("paths") or {}),
                    "glob": dict(field_paths.get("glob") or {}),
                    "output_mode": dict(field_paths.get("output_mode") or {}),
                    "context": dict(field_paths.get("context") or {}),
                    "head_limit": dict(field_paths.get("head_limit") or {}),
                    "offset": dict(field_paths.get("offset") or {}),
                },
                "usage_hint": (
                    "Use for file contents. Put known files in paths, directory scopes in roots, and file-type filters in glob. "
                    "Do not use search_text to rediscover a known file-like target object; read_file is the direct path tool. "
                    "paths accepts files only; directories must go in roots."
                ),
                "output_facts": ["matches", "recommended_read_windows", "applied_limit", "applied_offset"],
            }
        )
    return {key: _json_stable(value) for key, value in summary.items() if value not in ("", [], {})}


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _short_hash(value: str, *, prefix_chars: int = 10) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("sha256:"):
        return "sha256:" + text.removeprefix("sha256:")[:prefix_chars]
    return text[:prefix_chars]


def _digest(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_json_stable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _deepcopy_json_dict(value: dict[str, Any]) -> dict[str, Any]:
    return dict(_json_stable(dict(value or {})))
