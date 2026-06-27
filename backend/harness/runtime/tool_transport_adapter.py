from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.shared.tool_schema_canonical import canonical_provider_tool_input_schema, canonical_provider_tool_input_schema_ref


@dataclass(frozen=True, slots=True)
class ToolTransportContract:
    transport_mode: str
    tool_call_allowed: bool
    mounted_tool_names: tuple[str, ...]
    provider_native_tools: tuple[dict[str, Any], ...] = ()
    authority: str = "harness.runtime.tool_transport_contract"

    @property
    def json_action_enabled(self) -> bool:
        return self.transport_mode == "json_action" and self.tool_call_allowed and bool(self.mounted_tool_names)

    @property
    def provider_native_enabled(self) -> bool:
        return self.transport_mode == "provider_native" and bool(self.provider_native_tools)

    def to_model_visible_payload(self) -> dict[str, Any]:
        base_payload: dict[str, Any] = {
            "semantic_action": "tool_call",
            "tool_call_allowed": self.tool_call_allowed,
            "mounted_tool_names": list(self.mounted_tool_names),
        }
        if not self.tool_call_allowed or not self.mounted_tool_names:
            return {
                **base_payload,
                "tool_action_expression": "unavailable",
                "tool_action_language": {
                    "meaning": "本轮没有可执行工具行动；请在当前允许动作中回答、询问、阻塞或选择其它已开放动作。"
                },
            }
        if self.provider_native_enabled:
            return {
                **base_payload,
                "tool_action_expression": "tool_selector",
                "tool_action_language": {
                    "meaning": "当你需要查证、读取、搜索、执行或验证时，从当前可用工具中选择工具并填写参数；工具观察返回后再继续判断或回答。",
                    "tool_name_rule": "工具名必须精确使用 mounted_tool_names 中的名称。",
                    "args_rule": "参数只填写该工具需要的业务参数。",
                    "public_progress_rule": "如果需要先说明判断或依据，用简短公开进展说明本次工具行动要观察什么，不要宣称工具结果已经发生。",
                    "single_action_rule": "本轮只提交当前工具选择，不要同时提交另一个工具行动对象。",
                },
                "tool_selector_shape": {
                    "tool_name": "mounted_tool_names 中的一个工具名",
                    "args": {},
                    "public_progress_note": "说明本次要观察或查证什么，不宣称已经完成。",
                },
            }
        return {
            **base_payload,
            "tool_action_expression": "tool_action_object",
            "tool_action_language": {
                "meaning": "当你需要查证、读取、搜索、执行或验证时，提出一次工具行动；工具观察返回后再继续判断或回答。",
                "single_tool": "一次工具行动只需要一个工具时，表达为 tool_call。",
                "batch_tools": "同一个判断目标需要一组工具时，表达为 tool_calls[]；它仍然是一次工具行动。",
                "tool_name_rule": "tool_name 必须精确使用 mounted_tool_names 中的名称。",
                "args_rule": "args 只填写该工具需要的业务参数。",
                "json_action_rule": "选择工具行动时，本轮回复必须是一个可解析 JSON 对象；公开判断放入 public_progress_note 或 public_action_state.current_judgment，不要写在 JSON 外。",
                "single_action_rule": "本轮只提交当前工具行动对象，不要同时提交另一个工具选择。",
            },
            "single_tool_json_shape": {
                "action_type": "tool_call",
                "public_progress_note": "说明本次要观察或查证什么，不宣称已经完成。",
                "public_action_state": {"current_judgment": "", "next_action": "调用一个可见工具获取证据。", "completion_status": "working"},
                "tool_call": {"tool_name": "mounted_tool_names 中的一个工具名", "args": {}},
            },
            "batch_tools_json_shape": {
                "action_type": "tool_call",
                "public_progress_note": "说明这一组工具共同服务的同一个判断目标。",
                "public_action_state": {"current_judgment": "", "next_action": "调用一组可见工具获取证据。", "completion_status": "working"},
                "tool_calls": [{"tool_name": "mounted_tool_names 中的一个工具名", "args": {}}],
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "semantic_action": "tool_call",
            "selected_transport": self.transport_mode,
            "selected_tool_call_submission": "direct_tool_selection" if self.provider_native_enabled else "action_object",
            "supported_transports": ["json_action", "provider_native"],
            "tool_call_allowed": self.tool_call_allowed,
            "mounted_tool_names": list(self.mounted_tool_names),
            "json_action": {
                "enabled": self.json_action_enabled,
                "action_type": "tool_call",
                "single_tool_field": "tool_call",
                "batch_tool_field": "tool_calls",
            },
            "provider_native": {
                "enabled": self.provider_native_enabled,
                "bound_tool_count": len(self.provider_native_tools),
                "bound_tool_names": [str(item.get("name") or "") for item in self.provider_native_tools],
                "bound_schema_refs": [
                    {
                        "tool_name": str(item.get("name") or ""),
                        "input_schema_ref": canonical_provider_tool_input_schema_ref(item),
                    }
                    for item in self.provider_native_tools
                    if str(item.get("name") or "")
                ],
            },
        }


def build_tool_transport_contract(
    *,
    available_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    allowed_action_types: tuple[str, ...] | list[str],
    tool_transport_policy: dict[str, Any] | None,
) -> ToolTransportContract:
    mounted_tool_names = tuple(_mounted_tool_names(available_tools))
    tool_call_allowed = "tool_call" in {str(item) for item in tuple(allowed_action_types or ()) if str(item)} and bool(mounted_tool_names)
    policy = dict(tool_transport_policy or {})
    transport_mode = _transport_mode_from_policy(policy)
    provider_tools: tuple[dict[str, Any], ...] = ()
    if (
        tool_call_allowed
        and transport_mode == "provider_native"
        and policy.get("provider_native_tools_enabled") is True
    ):
        provider_tools = tuple(provider_native_tool_bindings_for_available_tools(available_tools))
    return ToolTransportContract(
        transport_mode=transport_mode,
        tool_call_allowed=tool_call_allowed,
        mounted_tool_names=mounted_tool_names,
        provider_native_tools=provider_tools,
    )


def provider_native_tools_for_policy(
    *,
    available_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    allowed_action_types: tuple[str, ...] | list[str],
    tool_transport_policy: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    contract = build_tool_transport_contract(
        available_tools=available_tools,
        allowed_action_types=allowed_action_types,
        tool_transport_policy=tool_transport_policy,
    )
    return [dict(item) for item in contract.provider_native_tools]


def provider_native_tool_bindings_for_available_tools(
    available_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for item in list(available_tools or []):
        tool = dict(item or {})
        name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        if not name:
            continue
        bindings.append(
            {
                "name": name,
                "description": str(tool.get("description") or tool.get("display_name") or name),
                "input_schema": canonical_provider_tool_input_schema(tool),
            }
        )
    return sorted(bindings, key=lambda item: str(item.get("name") or ""))


def tool_schema_refs_for_available_tools(
    available_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for item in list(available_tools or []):
        tool = dict(item or {})
        name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        if not name:
            continue
        refs.append({"tool_name": name, "input_schema_ref": canonical_provider_tool_input_schema_ref(tool)})
    return sorted(refs, key=lambda item: str(item.get("tool_name") or ""))


def _transport_mode_from_policy(policy: dict[str, Any]) -> str:
    mode = str(policy.get("transport_mode") or "json_action").strip().lower().replace("-", "_")
    if mode in {"provider_native", "native", "native_tools", "provider_tools", "tools_sidecar"}:
        return "provider_native"
    return "json_action"


def _mounted_tool_names(available_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for item in list(available_tools or []):
        tool = dict(item or {})
        name = str(tool.get("tool_name") or tool.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return sorted(names)
