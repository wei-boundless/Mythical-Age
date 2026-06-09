from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library.tool_prompts import tool_guidance_payload_for_visible_tools

_MODEL_VISIBLE_PROMPT_POLICIES = {"schema_only", "schema_plus_guidance"}


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
    payload: dict[str, Any] = {
        "tool_name": name,
        "operation_id": str(tool.get("operation_id") or ""),
    }
    if prompt_exposure_policy:
        payload["prompt_exposure_policy"] = prompt_exposure_policy
    if required_inputs:
        payload["required_inputs"] = required_inputs
    owner_scope = str(tool.get("owner_scope") or "")
    if owner_scope and owner_scope != "none":
        payload["owner_scope"] = owner_scope
    if bool(tool.get("read_only") is True):
        payload["read_only"] = True
    input_schema = dict(tool.get("input_schema") or {}) if isinstance(tool.get("input_schema"), dict) else {}
    if input_schema:
        payload["input_schema_summary"] = _input_schema_summary(input_schema)
        payload["input_schema_ref"] = _short_hash(_stable_json_hash(input_schema))
    return payload


def _input_schema_summary(schema: dict[str, Any]) -> dict[str, Any]:
    properties = dict(schema.get("properties") or {})
    summarized_properties: dict[str, str] = {}
    for name, value in properties.items():
        if not isinstance(value, dict):
            continue
        field_type = str(value.get("type") or "any")
        if isinstance(value.get("items"), dict):
            item_payload = dict(value.get("items") or {})
            item_type = str(item_payload.get("type") or "any")
            field_type = f"{field_type}<{item_type}>"
        parts = [field_type]
        if value.get("format"):
            parts.append(f"format={value.get('format')}")
        if "enum" in value:
            enum_values = [str(item) for item in list(value.get("enum") or [])]
            if enum_values:
                parts.append("enum=" + "|".join(enum_values))
        if "default" in value:
            parts.append("default=" + json.dumps(value.get("default"), ensure_ascii=False, separators=(",", ":")))
        summarized_properties[str(name)] = " ".join(parts)
    summary: dict[str, Any] = {"properties": summarized_properties}
    schema_type = str(schema.get("type") or "object")
    if schema_type != "object":
        summary["type"] = schema_type
    required = [str(item) for item in list(schema.get("required") or []) if str(item)]
    if required:
        summary["required"] = required
    return summary


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
