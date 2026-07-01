from __future__ import annotations

from typing import Any

from capability_system.tools.contracts import is_prompt_visible_tool_policy


TOOL_SURFACE_AUTHORITY = "capability_system.tools.tool_surface"

AGENT_VISIBLE_TOOL_ORDER: tuple[str, ...] = (
    "agent_state",
    "workspace_search",
    "workspace_read",
    "workspace_edit",
    "code_structure",
    "git",
    "subagent",
    "project_network",
    "memory",
    "web",
    "browser",
    "image",
    "office_document",
    "local_execution",
)

ACTION_TOOL_NAMES = frozenset(
    {
        "agent_state",
        "workspace_search",
        "workspace_read",
        "workspace_edit",
        "code_structure",
        "git",
        "subagent",
        "project_network",
        "web",
        "browser",
        "office_document",
        "local_execution",
    }
)

AGENT_STATE_TOOL_NAME = "agent_state"
WORKSPACE_SEARCH_TOOL_NAME = "workspace_search"
WORKSPACE_READ_TOOL_NAME = "workspace_read"
WORKSPACE_EDIT_TOOL_NAME = "workspace_edit"
LOCAL_EXECUTION_TOOL_NAME = "local_execution"


def canonical_tool_definitions() -> tuple[Any, ...]:
    from capability_system.tools.native_tool_catalog import get_tool_definitions

    return tuple(get_tool_definitions())


def canonical_tool_names(*, prompt_visible_only: bool = False) -> tuple[str, ...]:
    definitions = canonical_tool_definitions()
    names = [
        str(getattr(definition, "name", "") or "").strip()
        for definition in definitions
        if _definition_visible(definition, prompt_visible_only=prompt_visible_only)
    ]
    order = {name: index for index, name in enumerate(AGENT_VISIBLE_TOOL_ORDER)}
    return tuple(sorted((name for name in names if name), key=lambda value: (order.get(value, 10_000), value)))


def canonical_tool_name_set(*, prompt_visible_only: bool = False) -> frozenset[str]:
    return frozenset(canonical_tool_names(prompt_visible_only=prompt_visible_only))


def operation_ids_for_tool(definition: Any) -> tuple[str, ...]:
    operation_ids: list[str] = []
    primary = str(getattr(definition, "operation_id", "") or "").strip()
    if primary:
        operation_ids.append(primary)
    for operation_id in dict(getattr(definition, "action_operation_ids", {}) or {}).values():
        value = str(operation_id or "").strip()
        if value:
            operation_ids.append(value)
    return tuple(dict.fromkeys(operation_ids))


def tool_names_by_operation_id(definitions: dict[str, Any] | None = None) -> dict[str, tuple[str, ...]]:
    source = dict(definitions or {definition.name: definition for definition in canonical_tool_definitions()})
    pairs: dict[str, list[str]] = {}
    for tool_name, definition in source.items():
        normalized_tool = str(tool_name or "").strip()
        if not normalized_tool:
            continue
        for operation_id in operation_ids_for_tool(definition):
            pairs.setdefault(operation_id, []).append(normalized_tool)
    return {operation_id: tuple(dict.fromkeys(tool_names)) for operation_id, tool_names in pairs.items()}


def primary_tool_name_for_operation(operation_id: str, definitions: dict[str, Any] | None = None) -> str:
    names = tool_names_by_operation_id(definitions).get(str(operation_id or "").strip(), ())
    return names[0] if names else ""


def is_agent_state_tool_name(tool_name: Any) -> bool:
    return str(tool_name or "").strip().lower() == AGENT_STATE_TOOL_NAME


def is_local_execution_tool_name(tool_name: Any) -> bool:
    return str(tool_name or "").strip().lower() == LOCAL_EXECUTION_TOOL_NAME


def public_tool_label(tool_name: Any) -> str:
    normalized = str(tool_name or "").strip().lower()
    return {
        "agent_state": "更新任务状态",
        "workspace_search": "搜索工作区",
        "workspace_read": "读取工作区",
        "workspace_edit": "更新文件",
        "code_structure": "读取代码结构",
        "git": "Git 操作",
        "subagent": "子 Agent",
        "project_network": "项目网络",
        "memory": "读取记忆",
        "web": "网络查询",
        "browser": "浏览器操作",
        "image": "生成图片",
        "office_document": "处理文档",
        "local_execution": "运行命令",
    }.get(normalized, "")


def action_kind_for_surface_tool(tool_name: Any, raw_target: Any = "") -> str:
    normalized = str(tool_name or "").strip().lower()
    target = str(raw_target or "").strip().lower()
    if normalized == "agent_state":
        return "state"
    if normalized == "workspace_search":
        return "search"
    if normalized in {"workspace_read", "code_structure", "project_network", "memory", "web"}:
        return "read" if normalized != "web" else "search"
    if normalized in {"workspace_edit", "office_document", "image"}:
        return "edit"
    if normalized == "git":
        return "edit" if any(token in target for token in ("stage", "commit", "push", "restore", "branch_create")) else "read"
    if normalized == "browser":
        return "work"
    if normalized == "local_execution":
        return "verify" if any(token in target for token in ("test", "pytest", "npm", "vitest", "pnpm")) else "run"
    if normalized == "subagent":
        return "subagent"
    return "work"


def special_tool_contract_summary(tool_name: str, input_schema_summary: dict[str, Any]) -> dict[str, Any]:
    name = str(tool_name or "").strip()
    if name not in canonical_tool_name_set(prompt_visible_only=True):
        return {}
    field_paths = dict(input_schema_summary.get("field_paths") or {})
    summary: dict[str, Any] = {
        "authority": f"{TOOL_SURFACE_AUTHORITY}.tool_contract_summary",
        "required_inputs": [str(item) for item in list(input_schema_summary.get("required") or []) if str(item)],
        "optional_inputs": [str(item) for item in list(input_schema_summary.get("optional") or []) if str(item)],
        "forbidden_unknown_fields": bool(input_schema_summary.get("forbidden_unknown_fields") is True),
    }
    if name in ACTION_TOOL_NAMES:
        summary["critical_fields"] = {"action": dict(field_paths.get("action") or {})}
        summary["usage_hint"] = _action_usage_hint(name)
    if name == "agent_state":
        summary.update(
            {
                "critical_fields": {
                    "action": dict(field_paths.get("action") or {}),
                    "items[].status": dict(field_paths.get("items[].status") or {}),
                    "todo_id": dict(field_paths.get("todo_id") or {}),
                    "status": dict(field_paths.get("status") or {}),
                },
                "forbidden_fields": ["id", "item_id", "todo", "todos"],
                "forbidden_values": {"items[].status": ["active"], "status": ["active"]},
            }
        )
    elif name == "workspace_search":
        summary.update(
            {
                "critical_fields": {
                    "action": dict(field_paths.get("action") or {}),
                    "query": dict(field_paths.get("query") or {}),
                    "roots": dict(field_paths.get("roots") or {}),
                    "paths": dict(field_paths.get("paths") or {}),
                    "glob": dict(field_paths.get("glob") or {}),
                    "pattern": dict(field_paths.get("pattern") or {}),
                },
                "allowed_actions": ["text", "path", "glob", "symbol"],
                "output_facts": ["matches", "candidate_read_windows", "searched_roots", "search_status", "applied_limit", "applied_offset"],
            }
        )
    elif name == "workspace_read":
        summary.update(
            {
                "critical_fields": {
                    "action": dict(field_paths.get("action") or {}),
                    "path": dict(field_paths.get("path") or {}),
                    "start_line": dict(field_paths.get("start_line") or {}),
                    "line_count": dict(field_paths.get("line_count") or {}),
                    "read_intent": dict(field_paths.get("read_intent") or {}),
                },
                "allowed_actions": ["file", "dir", "stat", "exists", "result"],
                "output_facts": ["path", "start_line", "end_line", "returned_lines", "line_count", "total_lines", "has_more", "next_start_line", "content_sha256", "exact_artifact_ref"],
            }
        )
    elif name == "workspace_edit":
        summary.update(
            {
                "critical_fields": {
                    "action": dict(field_paths.get("action") or {}),
                    "path": dict(field_paths.get("path") or {}),
                    "old_text": dict(field_paths.get("old_text") or {}),
                    "new_text": dict(field_paths.get("new_text") or {}),
                    "edits[].old_text": dict(field_paths.get("edits[].old_text") or {}),
                    "edits[].new_text": dict(field_paths.get("edits[].new_text") or {}),
                },
                "allowed_actions": ["write", "edit", "batch_edit"],
            }
        )
    elif name == "subagent":
        summary.update(
            {
                "critical_fields": {
                    "action": dict(field_paths.get("action") or {}),
                    "target_agent_id": dict(field_paths.get("target_agent_id") or {}),
                    "subagent_run_ref": dict(field_paths.get("subagent_run_ref") or {}),
                },
                "allowed_actions": ["spawn", "send", "wait", "list", "close"],
                "runtime_constraint": "target_agent_id must be one of runtime_boundary.tool_boundary.allowed_subagent_ids.",
                "forbidden_fields": ["agent_id", "target_subagent_id"],
            }
        )
    elif name == "git":
        summary["allowed_actions"] = ["status", "diff", "log", "show", "branch_list", "branch_create", "stage", "unstage", "commit", "restore", "push"]
    elif name == "project_network":
        summary["allowed_actions"] = ["build_skeleton", "read_node", "read_edge", "expand", "directory_relations", "collect_changes", "repair_items", "submit_overlay"]
    elif name == "web":
        summary["allowed_actions"] = ["search", "fetch"]
    return {key: _json_stable(value) for key, value in summary.items() if value not in ("", [], {})}


def _definition_visible(definition: Any, *, prompt_visible_only: bool) -> bool:
    if not prompt_visible_only:
        return True
    return is_prompt_visible_tool_policy(str(getattr(definition, "prompt_exposure_policy", "") or ""))


def _action_usage_hint(tool_name: str) -> str:
    return {
        "agent_state": "Use action to update visible task state; do not expose old task-state tool names.",
        "workspace_search": "Use action=text for rg-like text search, path for filename/path search, glob for explicit wildcard patterns, symbol for code symbols. Results are locators, not exact evidence.",
        "workspace_read": "Use action=file for exact file evidence, dir for known directories, stat/exists for known paths, and result for persisted tool output.",
        "workspace_edit": "Use action=write for new/full file writes, edit for one exact replacement, and batch_edit for multiple replacements in the same file.",
        "code_structure": "Use for AST-backed outline, symbols, and diagnostics; use workspace_read for exact source text.",
        "git": "Read actions inspect repository state; write and remote actions require the matching operation permission.",
        "subagent": "Use one lifecycle tool with action=spawn/send/wait/list/close; do not call old split subagent tools.",
        "project_network": "Use the project physical skeleton as the navigation authority; semantic overlays must attach to real skeleton refs.",
        "web": "Use action=search for candidates and action=fetch for a known URL.",
        "browser": "Observe before acting; use browser only for real page interaction or visual verification.",
        "office_document": "Use structured document operations for Office/PDF files; use workspace_edit only for plain text files.",
        "local_execution": "Run local commands only when needed for real verification or execution evidence.",
    }.get(tool_name, "")


def _json_stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_stable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_stable(item) for item in value]
    return value
