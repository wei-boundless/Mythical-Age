from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


CONTROL_ACTION_TYPES = (
    "respond",
    "ask_user",
    "block",
    "request_task_run",
    "active_work_control",
    "pause_for_user_steer",
)
TASK_START_PRIMARY_MODES = ("goal", "plan")
TASK_RESOURCE_SHAPES = ("standard", "investigation", "recovery", "monitor", "open_work")
TASK_ACCEPTANCE_MODES = ("checkpoint", "user_review", "best_effort", "strict", "none_yet")


@dataclass(frozen=True, slots=True)
class TurnActionSurface:
    surface_id: str
    allowed_action_types: tuple[str, ...]
    allowed_tool_names: tuple[str, ...] = ()
    control_action_names: tuple[str, ...] = ()
    ordinary_tool_submission: str = "none"
    control_action_submission: str = "none"
    operation_availability: dict[str, Any] = field(default_factory=dict)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    source_authority: str = "harness.runtime.packet_context.model_action_surface"
    diagnostics: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.turn_operating_contract.action_surface"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_action_types"] = list(self.allowed_action_types)
        payload["allowed_tool_names"] = list(self.allowed_tool_names)
        payload["control_action_names"] = list(self.control_action_names)
        payload["operation_availability"] = dict(self.operation_availability or {})
        payload["resource_requirements"] = dict(self.resource_requirements or {})
        payload["diagnostics"] = dict(self.diagnostics or {})
        return payload


@dataclass(frozen=True, slots=True)
class TurnActionTransport:
    transport_id: str
    ordinary_tool_submission: str = "none"
    control_action_submission: str = "none"
    provider_tools_enabled: bool = False
    provider_control_tools_enabled: bool = False
    control_schema_authority: str = "harness.runtime.control_action_schema"
    authority: str = "harness.runtime.turn_operating_contract.action_transport"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TurnAttentionIndex:
    index_id: str
    payload: dict[str, Any]
    cache_policy: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.turn_operating_contract.turn_attention_index"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_id": self.index_id,
            "payload": dict(self.payload or {}),
            "cache_policy": dict(self.cache_policy or {}),
            "authority": self.authority,
        }


@dataclass(frozen=True, slots=True)
class TurnOperatingContract:
    contract_id: str
    turn_id: str
    invocation_kind: str
    action_surface: TurnActionSurface
    action_transport: TurnActionTransport
    action_request_contract: dict[str, Any]
    output_commit_contract: dict[str, Any]
    trace_contract: dict[str, Any] = field(default_factory=dict)
    authority: str = "harness.runtime.turn_operating_contract"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "turn_id": self.turn_id,
            "invocation_kind": self.invocation_kind,
            "action_surface": self.action_surface.to_dict(),
            "action_transport": self.action_transport.to_dict(),
            "action_request_contract": dict(self.action_request_contract or {}),
            "output_commit_contract": dict(self.output_commit_contract or {}),
            "trace_contract": dict(self.trace_contract or {}),
            "authority": self.authority,
        }

    def to_agent_visible_payload(self) -> dict[str, Any]:
        return {
            "current_action_contract": {
                "identity": "你正在处理当前用户请求。所有工具、任务资源申请、控制和最终回复都只服务当前请求。",
                "allowed_action_types": list(self.action_surface.allowed_action_types),
                "action_transport": {
                    "ordinary_tool_submission": self.action_transport.ordinary_tool_submission,
                    "control_action_submission": self.action_transport.control_action_submission,
                    "provider_control_tools_enabled": self.action_transport.provider_control_tools_enabled,
                },
                "request_task_run": {
                    "meaning": "向系统申请长任务资源，用来保存目标、计划游标、检查点、验收边界和阶段反馈。",
                    "not_meaning": "不是普通工具调用，也不是把当前请求改写成另一个目标。",
                    "primary_mode_values": list(TASK_START_PRIMARY_MODES),
                    "task_shape_values": list(TASK_RESOURCE_SHAPES),
                },
            },
        }

    def to_hidden_control_payload(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "turn_id": self.turn_id,
            "invocation_kind": self.invocation_kind,
            "action_surface": self.action_surface.to_dict(),
            "action_transport": self.action_transport.to_dict(),
            "trace_contract": dict(self.trace_contract or {}),
            "authority": self.authority,
        }


def turn_action_surface_from_packet_context(packet_context: Any, *, tool_call_contract: Any | None = None) -> TurnActionSurface:
    model_surface = getattr(packet_context, "model_action_surface", None)
    allowed_actions = tuple(str(item) for item in tuple(getattr(packet_context, "allowed_action_types", ()) or ()) if str(item))
    tool_names = _tool_names(getattr(packet_context, "model_visible_tools", ()) or ())
    tool_contract = _tool_contract_payload(tool_call_contract)
    surface_identity = {
        "turn_id": str(getattr(packet_context, "turn_id", "") or ""),
        "invocation_kind": str(getattr(packet_context, "invocation_kind", "") or ""),
        "allowed_action_types": list(allowed_actions),
        "tool_names": list(tool_names),
        "operation_availability": dict(getattr(packet_context, "operation_availability", {}) or {}),
    }
    surface_id = str(getattr(model_surface, "surface_id", "") or "") or f"turn-action-surface:{_digest(surface_identity)}"
    return TurnActionSurface(
        surface_id=surface_id,
        allowed_action_types=allowed_actions,
        allowed_tool_names=tool_names,
        control_action_names=tuple(item for item in CONTROL_ACTION_TYPES if item in allowed_actions),
        ordinary_tool_submission=str(tool_contract.get("ordinary_tool_submission") or "none"),
        control_action_submission=str(tool_contract.get("control_action_submission") or "none"),
        operation_availability=dict(getattr(packet_context, "operation_availability", {}) or {}),
        resource_requirements=_resource_requirements_from_packet(packet_context),
        source_authority=str(getattr(model_surface, "source_authority", "") or "harness.runtime.packet_context.model_action_surface"),
        diagnostics=dict(getattr(model_surface, "diagnostics", {}) or {}),
    )


def build_turn_operating_contract(
    *,
    packet_context: Any,
    tool_call_contract: Any | None = None,
    output_contract: dict[str, Any] | None = None,
) -> TurnOperatingContract:
    surface = turn_action_surface_from_packet_context(packet_context, tool_call_contract=tool_call_contract)
    transport_payload = _tool_contract_payload(tool_call_contract)
    transport_identity = {
        "surface_id": surface.surface_id,
        "ordinary_tool_submission": transport_payload.get("ordinary_tool_submission"),
        "control_action_submission": transport_payload.get("control_action_submission"),
        "provider_control_tools_enabled": transport_payload.get("provider_control_tools_enabled"),
    }
    transport = TurnActionTransport(
        transport_id=f"turn-action-transport:{_digest(transport_identity)}",
        ordinary_tool_submission=str(transport_payload.get("ordinary_tool_submission") or "none"),
        control_action_submission=str(transport_payload.get("control_action_submission") or "none"),
        provider_tools_enabled=bool(transport_payload.get("provider_tools_enabled") is True),
        provider_control_tools_enabled=bool(transport_payload.get("provider_control_tools_enabled") is True),
    )
    action_request_contract = turn_action_request_contract_payload(
        allowed_action_types=surface.allowed_action_types,
        action_surface_ref=surface.surface_id,
    )
    identity = {
        "turn_id": str(getattr(packet_context, "turn_id", "") or ""),
        "packet_id": str(getattr(packet_context, "packet_id", "") or ""),
        "surface_id": surface.surface_id,
        "transport_id": transport.transport_id,
    }
    return TurnOperatingContract(
        contract_id=f"turn-operating-contract:{_digest(identity)}",
        turn_id=str(getattr(packet_context, "turn_id", "") or ""),
        invocation_kind=str(getattr(packet_context, "invocation_kind", "") or ""),
        action_surface=surface,
        action_transport=transport,
        action_request_contract=action_request_contract,
        output_commit_contract=dict(output_contract or {}),
        trace_contract={
            "packet_id": str(getattr(packet_context, "packet_id", "") or ""),
            "agent_invocation_id": str(getattr(packet_context, "agent_invocation_id", "") or ""),
            "single_model_lifecycle": "turn",
            "task_run_role": "system_allocated_long_task_resource",
        },
    )


def turn_action_request_contract_payload(
    *,
    allowed_action_types: tuple[str, ...] | list[str] = (),
    action_surface_ref: str = "",
) -> dict[str, Any]:
    allowed = tuple(dict.fromkeys(str(item) for item in tuple(allowed_action_types or ()) if str(item)))
    visible_allowed = allowed or (
        "respond",
        "ask_user",
        "tool_call",
        "request_task_run",
        "active_work_control",
        "block",
    )
    task_run_available = "request_task_run" in set(visible_allowed)
    active_work_available = "active_work_control" in set(visible_allowed)
    return {
        "contract_name": "current_action_request",
        "allowed_action_types": list(visible_allowed),
        "current_request_attention": {
            "identity": "你正在处理当前用户请求。先判断用户当前输入需要什么，再选择一个当前请求动作。",
            "current_request_lifecycle": (
                "所有动作都属于当前请求：工具用于取得事实，任务资源用于保存持续工作，最终回复由你自己写出。"
                if task_run_available or active_work_available
                else "所有动作都属于当前请求：工具用于取得事实，最终回复由你自己写出。"
            ),
            "selection": [
                "能完成并收口时，使用 respond。",
                "缺少用户信息时，使用 ask_user。",
                "需要观察、查证、读取、修改或验证时，使用 tool_call 或 tool_calls。",
                *(
                    ["需要系统分配长任务资源来保存目标、计划游标、检查点、验收边界或阶段反馈时，使用 request_task_run。"]
                    if task_run_available
                    else ["当前可用能力没有提供 task 开启入口；不要提交 request_task_run。"]
                ),
                *(
                    [
                        "当前请求已绑定可控工作且用户要求继续推进时，把 task 状态当作上下文，在当前 turn 里继续选择 tool_call、respond、ask_user 或 block。不要用 active_work_control 调度另一个执行器。",
                        "只有用户明确要求暂停、停止、记录补充要求或询问当前工作状态时，使用 active_work_control。",
                    ]
                    if active_work_available
                    else []
                ),
                "不能继续时，使用 block。",
            ],
        },
        "action_shape_rules": [
            "提交一个唯一动作；如果当前界面提供了对应动作入口，就直接选择并填写参数；否则提交顶层结构化 action object。",
            "respond 把用户可见最终回复写在顶层 final_answer。",
            "ask_user 把用户需要回答的问题写在顶层 user_question。",
            "block 把真实阻塞原因写在顶层 blocking_reason。",
            "tool_call 使用顶层 tool_call 或 tool_calls；工具名必须来自当前可见工具，args 必须是对象。",
            *(
                ["request_task_run 只在 task_run_contract_seed 内填写 TaskStartIntent；不要同时提交普通工具动作。"]
                if task_run_available
                else []
            ),
        ],
        "public_response_obligation": {
            "rule": "动作必须服务用户当前输入。工具可以帮助你取得事实，但工具动作本身不是给用户的回答；最终解释必须由你在可见回复字段中写出。",
            "public_progress_note": "它承载你给用户的短判断：当前请求要确认什么、为什么查证、或为什么申请资源。结构化 action object 使用顶层 public_progress_note；直接 provider 工具调用可以在同次输出的简短自然 preamble 中写公开反馈，或在工具参数 schema 明确提供 public_progress_note、public_note、current_judgment、public_action_state 这类公开 sidecar 字段时写入 sidecar。preamble 会被系统归一为 assistant_public_feedback，不是 final_answer。",
            "public_action_state": "只写当前可公开判断、下一步和已观察风险；不要写隐藏推理、内部事件或开发说明。",
        },
        **(
            {
                "request_task_run_intent_contract": task_start_intent_contract_payload(),
                "task_run_contract_seed": task_start_intent_seed_template(),
            }
            if task_run_available
            else {}
        ),
        "fields": {
            "final_answer": "",
            "user_question": "",
            "blocking_reason": "",
            "tool_call": {"tool_name": "单工具调用时填写；批量时不要同时填写", "args": {}},
            "tool_calls": [{"tool_name": "批量工具调用时填写；与 tool_call 二选一", "args": {}}],
            **({"task_run_contract_seed": {}} if task_run_available else {}),
            "public_progress_note": "",
            "public_action_state": {
                "visible_status": "thinking|waiting_for_tool|tool_returned|responding|blocked",
                "current_judgment": "",
                "next_action": "",
                "evidence_refs": [],
                "open_risks": [],
                "completion_status": "working|waiting_for_tool|verifying|ready_to_finish|blocked",
            },
        },
        "forbidden": [
            "用户可见解释必须由你自己判断并写出。",
            *(
                [
                    "不要把 request_task_run 写成普通工具调用。",
                    "不要把 todo 当 primary_mode；todo 是任务资源中的进度游标或工具。",
                    "不要把 unsupported primary_mode 自动改成 open_work。",
                ]
                if task_run_available
                else ["当前可用能力没有提供 task 开启入口；不要输出 request_task_run、task_run_contract_seed 或 TaskStartIntent。"]
            ),
        ],
    }


def task_start_intent_contract_payload() -> dict[str, Any]:
    return {
        "contract_shape": "compact_task_start_intent",
        "meaning": "agent 发出的长任务资源申请意图。",
        "required_task_start_intent_paths": [
            "contract_shape",
            "primary_mode",
            "task_shape",
            "minimum_viable_next_step",
            "working_scope",
            "acceptance.mode",
            "mode_payload",
        ],
        "primary_mode": {
            "goal": "目标已经明确，需要围绕完成标准持续推进。",
            "plan": "需要按步骤推进，计划本身是当前最稳定的执行骨架。",
        },
        "task_shape": {
            "standard": "普通长任务资源。",
            "investigation": "需要查明未知问题，最终给出证据化判断。",
            "recovery": "需要根据任务异常、暂停或任务执行恢复线索整理可继续推进的工作。",
            "monitor": "需要持续观察目标、触发条件或状态变化。",
            "open_work": "确需持续推进，但暂不能归入前述形态。",
        },
        "todo_tool_contract": "todo 不是 primary_mode；需要清单时，进入资源后用 todo cursor/tool 维护。",
        "minimal_action": {
            "action_type": "request_task_run",
            "public_progress_note": "我会申请一个长任务资源来保存目标、计划、进度和验收边界。",
            "public_action_state": {
                "current_judgment": "当前工作需要在后续请求中保留执行状态和收口边界。",
                "next_action": "申请长任务资源并绑定当前工作。",
            },
            "task_run_contract_seed": task_start_intent_seed_template(),
        },
    }


def task_start_intent_seed_template() -> dict[str, Any]:
    return {
        "contract_shape": "compact_task_start_intent",
        "primary_mode": "plan",
        "task_shape": "standard",
        "minimum_viable_next_step": "任务资源接受后的第一个可执行步骤。",
        "working_scope": {
            "target_objects": ["要处理的文件、模块、目录、对象或问题域"],
            "workspace_refs": [],
            "source_refs": ["用户消息或已观察证据"],
            "excluded_scope": [],
            "known_constraints": ["用户明确约束、质量要求或排除项"],
        },
        "acceptance": {
            "mode": "checkpoint",
            "criteria": ["完成这项工作所需满足的可观察标准"],
            "final_answer_requirements": ["说明完成内容、验证结果、未完成项和风险"],
        },
        "mode_payload": {
            "summary": "一句话说明任务资源内的推进策略。",
            "steps": ["第一阶段", "第二阶段", "验证与收口"],
            "success_definition": "",
            "notes": [],
        },
        "todo_tool_contract": {
            "todo_is_tool": True,
            "cursor_updates": [],
        },
    }


def turn_output_contract_payload(
    *,
    allowed_actions: tuple[str, ...],
    control_capabilities: dict[str, Any],
    planning_protocol: dict[str, Any] | None = None,
    phase: str = "initial_decision",
) -> dict[str, Any]:
    allowed = tuple(dict.fromkeys(str(item) for item in tuple(allowed_actions or ()) if str(item)))
    json_action_enabled = bool(control_capabilities.get("supports_json_action_protocol") is True)
    json_action_required = bool(control_capabilities.get("requires_json_action_protocol") is True)
    output_phase = str(phase or "initial_decision").strip() or "initial_decision"
    assistant_message_enabled = bool(control_capabilities.get("may_emit_assistant_message") is not False)
    respond_allowed = "respond" in set(allowed)
    raw_text_allowed = (
        assistant_message_enabled
        and respond_allowed
    )
    natural_response_carrier = (
        "assistant_message_or_respond.final_answer"
        if respond_allowed
        else "not_available"
    )
    forbidden: list[str] = ["delegate_subagent"]
    if not json_action_enabled:
        forbidden.append("action_object_protocol")
    if "tool_call" not in allowed:
        forbidden.append("general_tool_call")
    if "request_task_run" not in allowed:
        forbidden.append("task_run_request")
    if "active_work_control" not in allowed:
        forbidden.append("active_work_control")
    return {
        "format": "assistant_response_or_action" if raw_text_allowed else "action_phase_structured_action",
        "phase": output_phase,
        "raw_assistant_text_allowed": raw_text_allowed,
        "raw_assistant_text_allowed_when": "respond_allowed_and_no_other_action" if raw_text_allowed else "",
        "action_phase_natural_response_carrier": natural_response_carrier,
        "allowed_actions": list(allowed),
        "forbidden": list(dict.fromkeys(forbidden)),
        "action_protocol": {
            "single_control_action_per_request": True,
            "structured_action": {
                "enabled": json_action_enabled,
                "required": json_action_required,
                "required_for": "explicit_control_action" if json_action_required else "tool_or_control_action",
                "action_identity_bound_by_current_request": True,
            },
            "assistant_messages": {
                "enabled": assistant_message_enabled,
                "response_form": "assistant_message_as_respond" if raw_text_allowed else "not_available_for_this_phase",
                "terminal_when_no_action": raw_text_allowed,
                "raw_text_allowed": raw_text_allowed,
                "raw_text_allowed_when": "respond_allowed_and_no_other_action" if raw_text_allowed else "",
                "raw_text_is_not_a_control_action": True,
                "action_phase_natural_response_carrier": natural_response_carrier,
            },
            "ordinary_tool_calls": {
                "enabled": "tool_call" in allowed,
                "submission": "choose_available_tool_and_fill_arguments",
                "multi_tool_calls_allowed": True,
                "execution_policy": "tool_batch_plan_scheduled_by_safety_and_resource_locks",
                "boundary": "current_visible_tools_only",
                "denied_or_failed_tool_calls_return_observations": True,
            },
            "control_actions": {
                "enabled": json_action_enabled,
                "submission": "action_object_or_provider_control_tool",
                "allowed_action_types": [item for item in CONTROL_ACTION_TYPES if item in allowed],
                "parallel_allowed": False,
            },
            "public_feedback_contract": {
                "feedback_must_be_model_authored": True,
                "feedback_is_agent_obligation": True,
                "system_does_not_author_public_feedback": True,
                "missing_feedback_is_contract_gap_not_action_denial": True,
                "feedback_required_when": [
                    "semantic_phase_changes",
                    "user_asks_status_or_reason",
                    "tool_observations_change_plan_or_risk",
                    "failure_or_repeated_failure",
                    "before_or_after_risky_write",
                    "verification_result",
                    "request_task_run_or_active_work_control",
                    "final_closeout",
                ],
                "low_level_evidence_chain_may_defer_feedback_until_next_action": True,
                "feedback_should_match_action_type_when_present": True,
                "long_task_resource_claim_requires_request_task_run": True,
                "tool_events_are_not_user_responses": True,
            },
        },
        "control_actions": {
            "request_task_run": {
                "enabled": "request_task_run" in allowed,
                "required_fields": [
                    "task_run_contract_seed.contract_shape=compact_task_start_intent",
                    "task_run_contract_seed.primary_mode",
                    "task_run_contract_seed.task_shape",
                    "task_run_contract_seed.minimum_viable_next_step",
                    "task_run_contract_seed.working_scope",
                    "task_run_contract_seed.acceptance.mode",
                    "task_run_contract_seed.mode_payload",
                ],
                "operation_boundary": "request_task_run allocates a long-task resource for later user requests; it does not execute ordinary tools inside the same action.",
            },
            "active_work_control": {
                "enabled": "active_work_control" in allowed,
                "operation_availability_gate": "Use only when Current Request Context exposes active_work_control=true.",
                "allowed_control_actions": [
                    "pause_active_work",
                    "stop_active_work",
                    "append_instruction_to_active_work",
                    "answer_about_active_work",
                ],
                "not_for": "continuing execution; continue current work through this same turn's ordinary actions.",
            },
        },
        "planning_protocol": dict(planning_protocol or {}),
    }


def turn_attention_index_payload(payload: dict[str, Any]) -> dict[str, Any]:
    content = dict(payload or {})
    if not content:
        return {}
    return {
        "current_attention_index": {
            "agent_use_contract": (
                "Before choosing the next action, re-anchor on this current attention index. "
                "It is a volatile attention guide for current goal, plan cursor, todo cursor, scope, "
                "acceptance, and current request context. Do not treat it as a separate task mode."
            ),
            **content,
            "cache_boundary": {
                "placement": "volatile_tail",
                "reason": "Current plan/todo cursor and execution focus may change on every invocation.",
            },
        }
    }


def _tool_contract_payload(tool_call_contract: Any | None) -> dict[str, Any]:
    if tool_call_contract is None:
        return {}
    if hasattr(tool_call_contract, "to_hidden_control_payload"):
        return dict(tool_call_contract.to_hidden_control_payload())
    if hasattr(tool_call_contract, "to_dict"):
        return dict(tool_call_contract.to_dict())
    if isinstance(tool_call_contract, dict):
        return dict(tool_call_contract)
    return {}


def _tool_names(values: Any) -> tuple[str, ...]:
    names: list[str] = []
    for item in tuple(values or ()):
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool_name") or item.get("name") or "").strip()
        if name:
            names.append(name)
    return tuple(sorted(dict.fromkeys(names)))


def _resource_requirements_from_packet(packet_context: Any) -> dict[str, Any]:
    operation_availability = dict(getattr(packet_context, "operation_availability", {}) or {})
    return {
        "request_task_run": {
            "available": "request_task_run" in set(getattr(packet_context, "allowed_action_types", ()) or ()),
            "resource_kind": "long_task_run",
        },
        "active_work_control": {
            "available": operation_availability.get("active_work_control") is True,
            "resource_kind": "active_work_binding",
        },
    }


def _digest(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:20]

