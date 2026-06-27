from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from prompt_library.tool_prompts import tool_guidance_payload_for_visible_tools
from runtime.shared.tool_schema_canonical import (
    canonical_provider_tool_input_schema_ref,
)

_MODEL_VISIBLE_PROMPT_POLICIES = {"schema_only", "schema_plus_guidance"}

_SYSTEM_INTERNAL_ARG_NAMES = {
    "agent_invocation_id",
    "event_log_id",
    "input_schema_ref",
    "operation_id",
    "project_id",
    "run_id",
    "schema_ref",
    "session_id",
    "stable_tool_catalog_hash",
    "stream_run_id",
    "task_id",
    "task_run_id",
    "tool_catalog_hash",
    "turn_id",
    "turn_run_id",
}

_ARG_TYPE_HINTS = {
    "allow_overwrite": "boolean",
    "all_branches": "boolean",
    "base_mtime_ns": "integer",
    "case_sensitive": "boolean",
    "context": "integer",
    "dry_run": "boolean",
    "head_limit": "integer",
    "line_count": "integer",
    "limit": "integer",
    "max_bytes": "integer",
    "max_entries": "integer",
    "max_results": "integer",
    "max_symbols": "integer",
    "max_text_chars": "integer",
    "offset": "integer",
    "overwrite": "boolean",
    "start_byte": "integer",
    "start_line": "integer",
    "timeout_ms": "integer",
}

_ARG_COLLECTION_HINTS = {
    "collections",
    "context_refs",
    "edits",
    "expected_outputs",
    "items",
    "paths",
    "repositories",
    "roots",
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

    def to_model_visible_payload(self, *, include_catalog_hash: bool = False) -> dict[str, Any]:
        del include_catalog_hash
        payload: dict[str, Any] = {
            "available_tools": [dict(item) for item in self.model_visible_catalog],
        }
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
    model_visible_catalog = tuple(agent_visible_tool_contract_entry(item) for item in raw_tools)
    model_visible_catalog = tuple(item for item in model_visible_catalog if item)
    tool_names = tuple(str(item.get("tool_name") or "") for item in model_visible_catalog)
    guidance_payload = tool_guidance_payload_for_visible_tools(
        raw_tools,
        guidance_prompt_defaults=tool_guidance_prompt_defaults,
        guidance_prompt_overrides=tool_guidance_prompt_overrides,
    )
    exposure_policy_counts: dict[str, int] = {}
    for item in raw_tools:
        policy = str(item.get("prompt_exposure_policy") or "schema_only").strip() or "schema_only"
        exposure_policy_counts[policy] = exposure_policy_counts.get(policy, 0) + 1
    tool_schema_refs = tuple(
        {
            "tool_name": str(item.get("tool_name") or item.get("name") or ""),
            "input_schema_ref": canonical_provider_tool_input_schema_ref(item),
        }
        for item in raw_tools
        if str(item.get("tool_name") or item.get("name") or "")
    )
    raw_catalog_hash = _stable_json_hash([dict(item) for item in raw_tools])
    stable_catalog_hash = _stable_json_hash([dict(item) for item in model_visible_catalog])
    seed = {
        "invocation_kind": str(invocation_kind or ""),
        "source_ref": str(source_ref or ""),
        "tool_catalog_hash": raw_catalog_hash,
        "stable_tool_catalog_hash": stable_catalog_hash,
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


def agent_visible_tool_contract_entry(tool_payload: dict[str, Any]) -> dict[str, Any]:
    tool = dict(tool_payload or {})
    name = str(tool.get("tool_name") or tool.get("name") or "").strip()
    if not name:
        return {}
    prompt_exposure_policy = str(tool.get("prompt_exposure_policy") or "schema_only").strip() or "schema_only"
    if prompt_exposure_policy not in _MODEL_VISIBLE_PROMPT_POLICIES:
        return {}
    contract = dict(tool.get("contract") or {}) if isinstance(tool.get("contract"), dict) else {}
    required_inputs = _agent_visible_arg_names(tool.get("required_inputs") or contract.get("required_inputs"))
    optional_inputs = _agent_visible_arg_names(
        tool.get("optional_inputs") or contract.get("optional_inputs"),
        exclude=set(required_inputs),
    )
    payload: dict[str, Any] = {
        "tool_name": name,
    }
    display_name = str(tool.get("display_name") or "").strip()
    if display_name and display_name != name:
        payload["title"] = display_name
    description = str(tool.get("description") or "").strip()
    if description:
        payload["purpose"] = description
    input_contract = _agent_visible_input_contract(
        tool_name=name,
        required_inputs=required_inputs,
        optional_inputs=optional_inputs,
    )
    if input_contract:
        payload["input_contract"] = input_contract
    capability_tags = _agent_visible_list(tool.get("capability_tags"))
    if capability_tags:
        payload["capabilities"] = capability_tags
    boundary = _agent_visible_tool_boundary(tool)
    if boundary:
        payload["boundary"] = boundary
    output_contract = _agent_visible_output_contract(tool)
    if output_contract:
        payload["result_contract"] = output_contract
    usage = _tool_usage_hint(name)
    if usage:
        payload["usage_hint"] = usage
    return {key: _json_stable(value) for key, value in payload.items() if value not in ("", [], {})}


def _agent_visible_arg_names(value: Any, *, exclude: set[str] | None = None) -> list[str]:
    excluded = set(exclude or ())
    result: list[str] = []
    seen: set[str] = set()
    for raw in list(value or []):
        name = str(raw or "").strip()
        if not name or name in seen or name in excluded or name in _SYSTEM_INTERNAL_ARG_NAMES:
            continue
        seen.add(name)
        result.append(name)
    return result


def _agent_visible_input_contract(
    *,
    tool_name: str,
    required_inputs: list[str],
    optional_inputs: list[str],
) -> dict[str, Any]:
    accepted_inputs = [*required_inputs, *optional_inputs]
    contract: dict[str, Any] = {
        "args_must_be_object": True,
        "args_rule": "只填写 accepted_args 中列出的业务参数；运行身份、执行路由和权限绑定由执行层根据本轮边界处理。",
    }
    if required_inputs:
        contract["required_args"] = required_inputs
    if optional_inputs:
        contract["optional_args"] = optional_inputs
    if accepted_inputs:
        contract["accepted_args"] = accepted_inputs
        contract["arg_types"] = {
            name: _semantic_arg_type(name)
            for name in accepted_inputs
            if _semantic_arg_type(name)
        }
    else:
        contract["accepted_args"] = []
    forbidden_fields = _tool_forbidden_fields(tool_name)
    if forbidden_fields:
        contract["forbidden_args"] = forbidden_fields
    return {key: _json_stable(value) for key, value in contract.items() if value not in ("", [], {})}


def _semantic_arg_type(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    if text in _ARG_TYPE_HINTS:
        return _ARG_TYPE_HINTS[text]
    if text in _ARG_COLLECTION_HINTS:
        return "array"
    if text == "args":
        return "object"
    return "string"


def _agent_visible_tool_boundary(tool: dict[str, Any]) -> dict[str, Any]:
    boundary: dict[str, Any] = {}
    if "read_only" in tool:
        boundary["read_only"] = bool(tool.get("read_only") is True)
    if "concurrency_safe" in tool:
        boundary["concurrency_safe"] = bool(tool.get("concurrency_safe") is True)
    path_policy = dict(tool.get("path_policy") or {}) if isinstance(tool.get("path_policy"), dict) else {}
    if path_policy:
        boundary["path_boundary"] = {
            key: value
            for key, value in {
                "path_field": str(path_policy.get("path_field") or ""),
                "path_kind": str(path_policy.get("path_kind") or ""),
            }.items()
            if value
        }
    return boundary


def _agent_visible_output_contract(tool: dict[str, Any]) -> dict[str, Any]:
    output_contract = dict(tool.get("output_contract") or {}) if isinstance(tool.get("output_contract"), dict) else {}
    if not output_contract:
        return {}
    return {
        key: value
        for key, value in {
            "display_mode": str(output_contract.get("display_mode") or ""),
            "finalization_policy": str(output_contract.get("finalization_policy") or ""),
            "persistence_policy": str(output_contract.get("persistence_policy") or ""),
        }.items()
        if value
    }


def _tool_usage_hint(tool_name: str) -> str:
    hints = {
        "batch_edit_file": (
            "同一个文件需要多处精确修改时使用；如果部分修改被拒绝，只针对被拒绝的位置重新读取和重试。"
        ),
        "glob_paths": "用于明确通配符路径，例如 *.html、**/*.py 或 backend/**/*.ts；返回路径，不返回文件内容。",
        "list_dir": "用于已知目录路径；不要用搜索工具重复发现已经知道的目录。",
        "path_exists": "用于确认已知路径是否存在；它是直接路径检查，不是搜索工具。",
        "read_file": (
            "用于已知文件路径。需要修改、逐行引用或验收当前内容时，优先读取当前窗口；"
            "has_more 只是窗口事实，只有目标行不在当前覆盖范围或确实需要更大上下文时再继续读取。"
        ),
        "search_files": "用于路径或文件名未知时按关键词找候选文件；搜索结果只是定位线索。",
        "search_text": (
            "用于搜索文件内容。已知具体文件时把文件放进 paths，目录范围放进 roots，文件类型范围放进 glob；"
            "不要用搜索结果预览替代当前文件读取。"
        ),
        "stat_path": "用于已知路径的元数据；路径已知时不要先搜索。",
        "web_search": "用于当前性、外部资料、官方文档、网页内容或需要来源的事实。",
        "fetch_url": "用于读取明确 URL 的页面内容；网页内容只能作为外部资料证据。",
    }
    return hints.get(str(tool_name or "").strip(), "")


def _tool_forbidden_fields(tool_name: str) -> list[str]:
    mapping = {
        "agent_todo": ["id", "item_id", "todo", "todos"],
        "search_text": ["path", "pattern"],
        "spawn_subagent": ["agent_id", "target_subagent_id"],
    }
    return mapping.get(str(tool_name or "").strip(), [])


def _agent_visible_list(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in list(value or []):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(_json_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


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
