from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


OrdinaryToolSubmission = Literal["provider_tool_selection", "action_object", "none"]
ControlActionSubmission = Literal["provider_tool_selection", "action_object", "none"]

_CONTROL_ACTION_TYPES = {
    "respond",
    "ask_user",
    "block",
    "request_task_run",
    "active_work_control",
    "resume_recoverable_work",
    "pause_for_user_steer",
}


@dataclass(frozen=True, slots=True)
class ToolCallContract:
    contract_id: str
    invocation_kind: str
    mounted_tool_names: tuple[str, ...] = ()
    ordinary_tool_submission: OrdinaryToolSubmission = "none"
    control_action_submission: ControlActionSubmission = "none"
    provider_tools_enabled: bool = False
    provider_control_tools_enabled: bool = False
    action_object_tool_fallback_enabled: bool = False
    multi_tool_calls_allowed: bool = False
    agent_visible_instruction: dict[str, Any] = field(default_factory=dict)
    hidden_transport_policy: dict[str, Any] = field(default_factory=dict)
    cache_policy: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.tool_call_contract"

    def __post_init__(self) -> None:
        if self.authority != "harness.runtime.tool_call_contract":
            raise ValueError("ToolCallContract authority must be harness.runtime.tool_call_contract")
        if not self.contract_id:
            raise ValueError("ToolCallContract requires contract_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mounted_tool_names"] = list(self.mounted_tool_names)
        payload["agent_visible_instruction"] = dict(self.agent_visible_instruction or {})
        payload["hidden_transport_policy"] = dict(self.hidden_transport_policy or {})
        payload["cache_policy"] = dict(self.cache_policy or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload

    def to_agent_visible_payload(self) -> dict[str, Any]:
        return {
            "contract_ref": self.contract_id,
            "tool_action": dict(self.agent_visible_instruction.get("tool_action") or {}),
            "control_action": dict(self.agent_visible_instruction.get("control_action") or {}),
            "feedback_rule": dict(self.agent_visible_instruction.get("feedback_rule") or {}),
            "authority": "harness.runtime.tool_call_contract.agent_visible",
        }

    def to_hidden_control_payload(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "invocation_kind": self.invocation_kind,
            "mounted_tool_names": list(self.mounted_tool_names),
            "ordinary_tool_submission": self.ordinary_tool_submission,
            "control_action_submission": self.control_action_submission,
            "provider_tools_enabled": self.provider_tools_enabled,
            "provider_control_tools_enabled": self.provider_control_tools_enabled,
            "action_object_tool_fallback_enabled": self.action_object_tool_fallback_enabled,
            "multi_tool_calls_allowed": self.multi_tool_calls_allowed,
            "hidden_transport_policy": dict(self.hidden_transport_policy or {}),
            "cache_policy": dict(self.cache_policy or {}),
            "diagnostics": dict(self.diagnostics or {}),
            "authority": self.authority,
        }


def build_tool_call_contract(
    *,
    invocation_kind: str,
    allowed_action_types: tuple[str, ...] | list[str],
    available_tools: tuple[dict[str, Any], ...] | list[dict[str, Any]] | None = None,
    runtime_assembly: dict[str, Any] | None = None,
    tool_plan: Any | None = None,
) -> ToolCallContract:
    allowed = tuple(str(item) for item in tuple(allowed_action_types or ()) if str(item))
    tools = tuple(dict(item) for item in tuple(available_tools or ()) if isinstance(item, dict))
    mounted_tool_names = tuple(sorted({name for name in (_tool_name(item) for item in tools) if name}))
    explicit_policy = _explicit_tool_call_policy(runtime_assembly)
    requested_submission = _requested_ordinary_submission(explicit_policy)
    tool_call_allowed = "tool_call" in set(allowed) and bool(mounted_tool_names)
    ordinary_submission: OrdinaryToolSubmission = "none"
    if tool_call_allowed:
        ordinary_submission = requested_submission or "provider_tool_selection"
    control_submission: ControlActionSubmission = (
        "provider_tool_selection" if set(allowed).intersection(_CONTROL_ACTION_TYPES) else "none"
    )
    provider_tools_enabled = ordinary_submission == "provider_tool_selection"
    provider_control_tools_enabled = control_submission == "provider_tool_selection"
    action_object_fallback = bool(
        ordinary_submission == "action_object"
        or explicit_policy.get("action_object_tool_fallback_enabled") is True
        or explicit_policy.get("tool_fallback_enabled") is True
    )
    multi_tool_calls_allowed = bool(tool_call_allowed and explicit_policy.get("multi_tool_calls_allowed") is not False)
    identity = {
        "invocation_kind": str(invocation_kind or ""),
        "allowed_action_types": list(allowed),
        "mounted_tool_names": list(mounted_tool_names),
        "ordinary_tool_submission": ordinary_submission,
        "control_action_submission": control_submission,
        "tool_plan_ref": _tool_plan_ref(tool_plan),
    }
    contract_id = "toolcallcontract:" + _digest(identity)
    cache_policy = {
        "tool_capability_surface": "session_stable_summary",
        "provider_tool_binding": "current_request_never_cache",
        "provider_tool_binding_prefix_component": False,
        "stable_tool_catalog_ref_required": True,
    }
    hidden_transport_policy = {
        "ordinary_tool_submission": ordinary_submission,
        "control_action_submission": control_submission,
        "provider_tools_enabled": provider_tools_enabled,
        "provider_control_tools_enabled": provider_control_tools_enabled,
        "action_object_tool_fallback_enabled": action_object_fallback,
        "mounted_tool_names": list(mounted_tool_names),
        "tool_plan_ref": _tool_plan_ref(tool_plan),
        "policy_source": str(explicit_policy.get("source") or "default_provider_tool_selection"),
    }
    return ToolCallContract(
        contract_id=contract_id,
        invocation_kind=str(invocation_kind or ""),
        mounted_tool_names=mounted_tool_names,
        ordinary_tool_submission=ordinary_submission,
        control_action_submission=control_submission,
        provider_tools_enabled=provider_tools_enabled,
        provider_control_tools_enabled=provider_control_tools_enabled,
        action_object_tool_fallback_enabled=action_object_fallback,
        multi_tool_calls_allowed=multi_tool_calls_allowed,
        agent_visible_instruction=_agent_visible_instruction(
            tool_call_allowed=tool_call_allowed,
            control_submission=control_submission,
            multi_tool_calls_allowed=multi_tool_calls_allowed,
        ),
        hidden_transport_policy=hidden_transport_policy,
        cache_policy=cache_policy,
        diagnostics={
            "allowed_action_types": list(allowed),
            "mounted_tool_count": len(mounted_tool_names),
            "tool_call_allowed": tool_call_allowed,
            "control_action_allowed": control_submission != "none",
            "explicit_policy_keys": sorted(str(key) for key in explicit_policy if key != "source"),
        },
    )


def provider_tools_enabled_from_contract(contract: dict[str, Any] | ToolCallContract | None) -> bool:
    payload = contract.to_hidden_control_payload() if isinstance(contract, ToolCallContract) else dict(contract or {})
    if not payload:
        return True
    return str(payload.get("ordinary_tool_submission") or "").strip() == "provider_tool_selection" and bool(
        payload.get("provider_tools_enabled") is True
    )


def provider_control_tools_enabled_from_contract(contract: dict[str, Any] | ToolCallContract | None) -> bool:
    payload = contract.to_hidden_control_payload() if isinstance(contract, ToolCallContract) else dict(contract or {})
    if not payload:
        return True
    return str(payload.get("control_action_submission") or "").strip() == "provider_tool_selection" and bool(
        payload.get("provider_control_tools_enabled") is not False
    )


def _agent_visible_instruction(
    *,
    tool_call_allowed: bool,
    control_submission: ControlActionSubmission,
    multi_tool_calls_allowed: bool,
) -> dict[str, Any]:
    return {
        "tool_action": {
            "available": bool(tool_call_allowed),
            "submission": "choose_available_tool_and_fill_arguments" if tool_call_allowed else "not_available",
            "multiple_tools_allowed": bool(multi_tool_calls_allowed),
            "instruction": (
                "需要读取、查证、修改、搜索或验证时，选择当前可用工具并填写参数。"
                "可以先给用户一个简短公开判断，说明本次工具行动要确认什么。"
            )
            if tool_call_allowed
            else "当前回合没有可用工具；请基于已知事实回答、询问或说明阻塞。",
        },
        "control_action": {
            "available": control_submission != "none",
            "submission": (
                "choose_matching_control_action_and_fill_arguments"
                if control_submission == "provider_tool_selection"
                else "submit_action_object"
                if control_submission == "action_object"
                else "not_available"
            ),
            "instruction": (
                "需要询问、阻塞、启动持续任务或控制当前工作时，选择匹配的控制动作并填写参数；"
                "request_task_run 只填写紧凑 TaskStartIntent，内部 TaskRunContract 由运行时生成。"
            )
            if control_submission == "provider_tool_selection"
            else "需要询问、阻塞、启动持续任务或控制当前工作时，提交本次行动对象。"
            if control_submission == "action_object"
            else "当前回合没有控制动作。",
        },
        "feedback_rule": {
            "tool_observation": (
                "工具返回观察后，重新判断用户目标、已确认事实和下一步；不要声称没有真实观察的工具已经执行。"
            ),
            "not_executed": "如果上一轮行动没有执行，保留你的判断，根据反馈原因重新选择可执行行动。",
        },
    }


def _explicit_tool_call_policy(runtime_assembly: dict[str, Any] | None) -> dict[str, Any]:
    assembly = dict(runtime_assembly or {})
    profile = dict(assembly.get("profile") or {})
    control = dict(assembly.get("control_capabilities") or {})
    candidates = (
        ("runtime_assembly.tool_call_contract", assembly.get("tool_call_contract")),
        ("runtime_assembly.tool_transport_policy", assembly.get("tool_transport_policy")),
        ("profile.tool_call_contract", profile.get("tool_call_contract")),
        ("profile.tool_transport_policy", profile.get("tool_transport_policy")),
        ("control.tool_call_contract", control.get("tool_call_contract")),
        ("control.tool_transport_policy", control.get("tool_transport_policy")),
    )
    for source, value in candidates:
        if isinstance(value, dict) and value:
            return {"source": source, **dict(value)}
    return {"source": "default_provider_tool_selection"}


def _requested_ordinary_submission(policy: dict[str, Any]) -> OrdinaryToolSubmission | None:
    raw = str(
        policy.get("ordinary_tool_submission")
        or policy.get("selected_tool_call_submission")
        or policy.get("selected_transport")
        or policy.get("transport_mode")
        or policy.get("mode")
        or ""
    ).strip().lower()
    if raw in {"provider_tool_selection", "provider_native", "direct_tool_selection", "provider"}:
        return "provider_tool_selection"
    if raw in {"action_object", "json_action", "json", "structured_action"}:
        return "action_object"
    if raw in {"none", "disabled", "off"}:
        return "none"
    if policy.get("provider_tools_enabled") is False:
        return "action_object"
    return None


def _tool_plan_ref(tool_plan: Any | None) -> str:
    if tool_plan is None:
        return ""
    if hasattr(tool_plan, "plan_id"):
        return str(getattr(tool_plan, "plan_id") or "")
    payload = tool_plan.to_dict() if hasattr(tool_plan, "to_dict") else dict(tool_plan or {})
    return str(payload.get("plan_id") or "")


def _tool_name(tool: dict[str, Any]) -> str:
    return str(tool.get("tool_name") or tool.get("name") or "").strip()


def _digest(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:20]
