from __future__ import annotations

import hashlib
from typing import Any

from runtime.context_management.system_asset_lines import ControlOutputLine

from .turn_operating_contract import TASK_ACCEPTANCE_MODES, TASK_RESOURCE_SHAPES, TASK_START_PRIMARY_MODES


CONTROL_ACTION_TOOL_NAMES = frozenset(
    {
        "respond",
        "ask_user",
        "block",
        "request_task_run",
        "active_work_control",
        "resume_task_recovery",
        "pause_for_user_steer",
    }
)

_ACTIVE_WORK_ACTIONS = (
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
)

CONTROL_OUTPUT_LINE_AUTHORITY = "harness.runtime.control_action_schema.control_output_line"


def is_control_action_tool_name(value: Any) -> bool:
    return str(value or "").strip().lower() in CONTROL_ACTION_TOOL_NAMES


def control_output_line_declarations(
    allowed_action_types: tuple[str, ...] | list[str] | None = None,
) -> tuple[ControlOutputLine, ...]:
    allowed = {
        str(item or "").strip().lower()
        for item in tuple(allowed_action_types or tuple(sorted(CONTROL_ACTION_TOOL_NAMES)))
        if str(item or "").strip()
    }
    return tuple(
        _control_output_line(action_type)
        for action_type in sorted(CONTROL_ACTION_TOOL_NAMES.intersection(allowed))
    )


def control_output_line_declaration(action_type: str) -> ControlOutputLine | None:
    normalized = str(action_type or "").strip().lower()
    if normalized not in CONTROL_ACTION_TOOL_NAMES:
        return None
    return _control_output_line(normalized)


def control_output_line_id(action_type: str) -> str:
    normalized = str(action_type or "").strip().lower()
    if normalized not in CONTROL_ACTION_TOOL_NAMES:
        return ""
    return f"control_output_line:{normalized}"


def control_output_line_binding(action_type: str) -> dict[str, Any]:
    line = control_output_line_declaration(action_type)
    if line is None:
        return {}
    return {
        "control_output_line_id": line.line_id,
        "control_output_line_ref": line.line_id,
        "control_output_line_action_type": line.action_type,
        "control_output_line_authority": line.authority,
        "permit_policy_ref": line.permit_policy_ref,
        "executor_ref": line.executor_ref,
        "observation_contract": line.observation_contract,
        "public_projection_policy": line.public_projection_policy,
        "commit_policy": line.commit_policy,
        "terminal_policy": line.terminal_policy,
        "failure_feedback_policy": line.failure_feedback_policy,
        "schema_revision": line.schema_revision,
    }


def control_action_arg_errors_from_native_tool_call(call: dict[str, Any]) -> list[str]:
    tool_name = str(dict(call or {}).get("name") or "").strip().lower()
    args = dict(dict(call or {}).get("args") or {})
    schema = _control_action_input_schema(tool_name)
    allowed = set(dict(schema.get("properties") or {})) if isinstance(schema, dict) else set()
    if not allowed:
        return []
    return [
        f"native_control_action_arg_not_allowed:{key}"
        for key in sorted(str(item) for item in args.keys())
        if key not in allowed
    ]


def provider_control_action_bindings(allowed_action_types: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    allowed = {str(item).strip() for item in tuple(allowed_action_types or ()) if str(item).strip()}
    bindings: list[dict[str, Any]] = []
    for action_name in sorted(CONTROL_ACTION_TOOL_NAMES.intersection(allowed)):
        schema = _control_action_input_schema(action_name)
        if not schema:
            continue
        bindings.append(
            {
                "name": action_name,
                "description": _control_action_description(action_name),
                "input_schema": schema,
                "strict": True,
                "metadata": {
                    "tool_plane": "model_control_action",
                    "action_type": action_name,
                    "authority": "harness.runtime.control_action_schema",
                    **control_output_line_binding(action_name),
                },
            }
        )
    return bindings


def control_action_request_payload_from_native_tool_call(
    call: dict[str, Any],
    *,
    turn_id: str,
    packet_ref: str,
    iteration: int,
) -> dict[str, Any]:
    tool_name = str(dict(call or {}).get("name") or "").strip()
    action_type = tool_name.lower()
    args = dict(dict(call or {}).get("args") or {})
    call_id = str(dict(call or {}).get("id") or "").strip()
    request_id = (
        f"model-action:{turn_id}:single-agent-control:{iteration}:"
        f"{_stable_action_suffix(call_id or action_type)}"
    )
    public_action_state = dict(args.get("public_action_state") or {}) if isinstance(args.get("public_action_state"), dict) else {}
    payload: dict[str, Any] = {
        "authority": "harness.loop.model_action_request",
        "request_id": request_id,
        "turn_id": str(turn_id or ""),
        "action_type": action_type,
        "public_progress_note": str(args.get("public_progress_note") or "").strip(),
        "public_action_state": public_action_state,
        "diagnostics": {
            "origin_kind": "single_agent_turn_native_control_action",
            "origin_authority": "harness.runtime.control_action_schema",
            "packet_ref": str(packet_ref or ""),
            "control_action_submission": "provider_tool_selection",
            "control_output_line": control_output_line_binding(action_type),
            "native_tool_call": {
                "id": call_id,
                "name": tool_name,
                "source": str(dict(call or {}).get("source") or ""),
            },
        },
    }
    if action_type == "respond":
        payload["final_answer"] = str(args.get("final_answer") or "").strip()
    elif action_type == "ask_user":
        payload["user_question"] = str(args.get("user_question") or "").strip()
    elif action_type == "block":
        payload["blocking_reason"] = str(args.get("blocking_reason") or "").strip()
    elif action_type == "request_task_run":
        payload["task_run_contract_seed"] = _compact_task_start_intent_from_args(args)
    elif action_type == "active_work_control":
        payload["active_work_control"] = _drop_empty_payload(
            {
                "action": str(args.get("action") or "").strip(),
                "appended_instruction": str(args.get("appended_instruction") or args.get("instruction") or "").strip(),
                "response": str(args.get("response") or args.get("answer") or "").strip(),
                "reason": str(args.get("reason") or "").strip(),
            }
        )
    elif action_type == "resume_task_recovery":
        payload["task_recovery_resume"] = _drop_empty_payload(
            {
                "work_ref": str(args.get("work_ref") or args.get("task_run_id") or "").strip(),
                "resume_ref": str(args.get("resume_ref") or args.get("continuation_id") or "").strip(),
                "task_run_id": str(args.get("task_run_id") or args.get("work_ref") or "").strip(),
                "continuation_id": str(args.get("continuation_id") or args.get("resume_ref") or "").strip(),
                "reason": str(args.get("reason") or "").strip(),
            }
        )
    elif action_type == "pause_for_user_steer":
        payload["pause_request"] = _drop_empty_payload(
            {
                "reason": str(args.get("reason") or "").strip(),
                "steer_ref": str(args.get("steer_ref") or "").strip(),
                "checkpoint_summary": str(args.get("checkpoint_summary") or "").strip(),
                "resume_hint": str(args.get("resume_hint") or "").strip(),
                "requires_user_input": bool(args.get("requires_user_input") is True),
            }
        )
    return payload


def provider_control_action_required_fields(action_type: str) -> list[str]:
    action = str(action_type or "").strip().lower()
    schema = _control_action_input_schema(action)
    return _semantic_required_fields(action) if schema else []


def _compact_task_start_intent_from_args(args: dict[str, Any]) -> dict[str, Any]:
    working_scope = dict(args.get("working_scope") or {}) if isinstance(args.get("working_scope"), dict) else {}
    acceptance = dict(args.get("acceptance") or {}) if isinstance(args.get("acceptance"), dict) else {}
    mode_payload = dict(args.get("mode_payload") or {}) if isinstance(args.get("mode_payload"), dict) else {}
    todo_tool_contract = (
        dict(args.get("todo_tool_contract") or {}) if isinstance(args.get("todo_tool_contract"), dict) else {}
    )
    return {
        "contract_shape": "compact_task_start_intent",
        "primary_mode": str(args.get("primary_mode") or "").strip(),
        "task_shape": str(args.get("task_shape") or "standard").strip() or "standard",
        "minimum_viable_next_step": str(args.get("minimum_viable_next_step") or "").strip(),
        "working_scope": _normalize_compact_working_scope(working_scope),
        "acceptance": {
            "mode": str(acceptance.get("mode") or "").strip(),
            "criteria": _string_list(acceptance.get("criteria")),
            "final_answer_requirements": _string_list(acceptance.get("final_answer_requirements")),
        },
        "mode_payload": _normalize_mode_payload(mode_payload),
        "todo_tool_contract": {
            "todo_is_tool": bool(todo_tool_contract.get("todo_is_tool") is not False),
            "cursor_updates": _string_list(todo_tool_contract.get("cursor_updates")),
        },
    }


def _control_action_description(action_name: str) -> str:
    return {
        "respond": "Finish the current turn with a user-visible answer.",
        "ask_user": "Ask the user for missing information needed before continuing.",
        "block": "Stop because the current work cannot continue reliably and explain the blocking reason.",
        "request_task_run": "Request a long-task resource from a compact TaskStartIntent.",
        "active_work_control": "Control an already active durable work item.",
        "resume_task_recovery": "Resume a paused task recovery boundary from runtime-provided handles.",
        "pause_for_user_steer": "Pause current task execution at a recoverable boundary because a user steer must be handled first.",
    }.get(action_name, action_name)


def _control_output_line(action_type: str) -> ControlOutputLine:
    action = str(action_type or "").strip().lower()
    defaults = _CONTROL_OUTPUT_LINE_DEFAULTS.get(action, {})
    return ControlOutputLine(
        action_type=action,
        line_id=control_output_line_id(action),
        model_decision_ref=f"model_action:{action}",
        authority=CONTROL_OUTPUT_LINE_AUTHORITY,
        permit_policy_ref=str(defaults.get("permit_policy_ref") or f"harness.loop.admission:{action}"),
        executor_ref=str(defaults.get("executor_ref") or "harness.loop.single_agent_turn"),
        observation_contract=str(defaults.get("observation_contract") or "runtime_observation"),
        public_projection_policy=str(defaults.get("public_projection_policy") or "public_projection_from_runtime_event"),
        commit_policy=str(defaults.get("commit_policy") or "no_direct_commit"),
        terminal_policy=str(defaults.get("terminal_policy") or "surface explicit observation or denial"),
        failure_feedback_policy=str(defaults.get("failure_feedback_policy") or "return structured denial to model-visible feedback"),
        diagnostics={
            "description": _control_action_description(action),
            "native_provider_tool": action in CONTROL_ACTION_TOOL_NAMES,
        },
    )


_CONTROL_OUTPUT_LINE_DEFAULTS: dict[str, dict[str, str]] = {
    "respond": {
        "permit_policy_ref": "harness.loop.admission.respond",
        "executor_ref": "harness.runtime.output_commit_authority",
        "observation_contract": "assistant_final_commit_result",
        "public_projection_policy": "assistant_final_public_projection",
        "commit_policy": "output_commit_authority_required",
        "terminal_policy": "turn completes only after OutputCommitAuthority accepts or explicitly skips",
        "failure_feedback_policy": "commit denial is surfaced as output boundary failure",
    },
    "ask_user": {
        "permit_policy_ref": "harness.loop.admission.ask_user",
        "executor_ref": "harness.runtime.output_commit_authority",
        "observation_contract": "assistant_question_commit_result",
        "public_projection_policy": "assistant_question_public_projection",
        "commit_policy": "output_commit_authority_required",
        "terminal_policy": "turn waits for user only after question is committed through output boundary",
        "failure_feedback_policy": "commit denial is surfaced as output boundary failure",
    },
    "block": {
        "permit_policy_ref": "harness.loop.admission.block",
        "executor_ref": "harness.runtime.output_commit_authority",
        "observation_contract": "assistant_block_commit_result",
        "public_projection_policy": "assistant_block_public_projection",
        "commit_policy": "output_commit_authority_required",
        "terminal_policy": "blocked turn emits visible reason through output boundary",
        "failure_feedback_policy": "commit denial is surfaced as output boundary failure",
    },
    "request_task_run": {
        "permit_policy_ref": "harness.loop.admission.request_task_run",
        "executor_ref": "harness.entrypoint.runtime_facade.task_environment_allocation",
        "observation_contract": "task_environment_allocation_observation",
        "public_projection_policy": "task_environment_allocation_public_projection",
        "commit_policy": "task_environment_allocation_event_not_final_answer",
        "terminal_policy": "missing task contract seed denies before task resource allocation",
        "failure_feedback_policy": "task environment allocation failure returns structured repair feedback",
    },
    "active_work_control": {
        "permit_policy_ref": "harness.current_work_receipt + harness.loop.admission.active_work_control",
        "executor_ref": "harness.entrypoint.runtime_facade.current_work_control",
        "observation_contract": "active_work_control_observation",
        "public_projection_policy": "active_work_control_public_projection",
        "commit_policy": "control_event_not_final_answer",
        "terminal_policy": "CurrentWorkBoundaryReceipt must allow active_work_control before dispatch",
        "failure_feedback_policy": "control denial returns receipt reason to model-visible feedback",
    },
    "resume_task_recovery": {
        "permit_policy_ref": "harness.recovery_receipt + harness.loop.admission.resume_task_recovery",
        "executor_ref": "harness.entrypoint.runtime_facade.legacy_task_recovery_removed",
        "observation_contract": "legacy_task_recovery_removed_observation",
        "public_projection_policy": "task_recovery_public_projection",
        "commit_policy": "legacy_recovery_removed_visible_status",
        "terminal_policy": "RecoveryReceipt is enforced; old TaskRun recovery returns visible removed-chain status",
        "failure_feedback_policy": "removed-chain status returns receipt reason to model-visible feedback",
    },
    "pause_for_user_steer": {
        "permit_policy_ref": "harness.loop.admission.pause_for_user_steer",
        "executor_ref": "harness.entrypoint.runtime_facade.legacy_task_pause_removed",
        "observation_contract": "pause_for_user_steer_observation",
        "public_projection_policy": "task_pause_public_projection",
        "commit_policy": "legacy_task_pause_removed_visible_status",
        "terminal_policy": "only a mounted task episode execution surface may pause for user steer; old task_executor pause is removed",
        "failure_feedback_policy": "invalid pause request returns structured admission denial",
    },
}


def _control_action_input_schema(action_name: str) -> dict[str, Any]:
    if action_name == "respond":
        return _strict_object(
            {
                "final_answer": _string("User-visible final answer."),
                "public_progress_note": _optional_string("Brief public note aligned with the answer when a separate progress note is useful."),
                "public_action_state": _optional_public_action_state_schema(),
            },
            ["final_answer"],
        )
    if action_name == "ask_user":
        return _strict_object(
            {
                "user_question": _string("The concrete question the user must answer."),
                "public_progress_note": _optional_string("Brief public reason why the question is needed."),
                "public_action_state": _optional_public_action_state_schema(),
            },
            ["user_question"],
        )
    if action_name == "block":
        return _strict_object(
            {
                "blocking_reason": _string("Concrete reason the work cannot continue."),
                "public_progress_note": _optional_string("Brief public blocking summary."),
                "public_action_state": _optional_public_action_state_schema(),
            },
            ["blocking_reason"],
        )
    if action_name == "request_task_run":
        return _strict_object(
            {
                "public_progress_note": _optional_string("User-visible reason for requesting a long-task resource."),
                "public_action_state": _optional_public_action_state_schema(),
                "primary_mode": {"type": "string", "enum": list(TASK_START_PRIMARY_MODES)},
                "task_shape": {"type": "string", "enum": list(TASK_RESOURCE_SHAPES)},
                "minimum_viable_next_step": _string("First executable step after the resource is accepted."),
                "working_scope": _strict_object(
                    {
                        "target_objects": _string_array(),
                        "workspace_refs": _string_array(),
                        "source_refs": _string_array(),
                        "excluded_scope": _string_array(),
                        "known_constraints": _string_array(),
                    },
                    ["target_objects", "workspace_refs", "source_refs", "excluded_scope", "known_constraints"],
                ),
                "acceptance": _strict_object(
                    {
                        "mode": {"type": "string", "enum": list(TASK_ACCEPTANCE_MODES)},
                        "criteria": _string_array(),
                        "final_answer_requirements": _string_array(),
                    },
                    ["mode", "criteria", "final_answer_requirements"],
                ),
                "mode_payload": _mode_payload_schema(),
                "todo_tool_contract": _strict_object(
                    {
                        "todo_is_tool": {"type": "boolean"},
                        "cursor_updates": _string_array(),
                    },
                    ["todo_is_tool", "cursor_updates"],
                ),
            },
            [
                "primary_mode",
                "task_shape",
                "minimum_viable_next_step",
                "working_scope",
                "acceptance",
                "mode_payload",
                "todo_tool_contract",
            ],
        )
    if action_name == "active_work_control":
        return _strict_object(
            {
                "action": {"type": "string", "enum": list(_ACTIVE_WORK_ACTIONS)},
                "appended_instruction": _string("Instruction to record when action is append_instruction_to_active_work; otherwise an empty string."),
                "response": _string("User-visible answer when action is answer_about_active_work; otherwise an empty string."),
                "reason": _string("Reason for this control decision."),
                "public_progress_note": _optional_string("Brief public note aligned with this control action."),
                "public_action_state": _optional_public_action_state_schema(),
            },
            ["action"],
        )
    if action_name == "resume_task_recovery":
        return _strict_object(
            {
                "work_ref": _string("Runtime-provided task recovery work reference."),
                "resume_ref": _string("Runtime-provided resume reference."),
                "task_run_id": _string("Optional canonical task_run_id if provided by runtime."),
                "continuation_id": _string("Optional canonical continuation_id if provided by runtime."),
                "reason": _string("Reason for resuming this work now."),
                "public_progress_note": _optional_string("Brief public resume note."),
                "public_action_state": _optional_public_action_state_schema(),
            },
            ["work_ref", "resume_ref"],
        )
    if action_name == "pause_for_user_steer":
        return _strict_object(
            {
                "reason": {"type": "string", "enum": ["user_steer_requires_pause"]},
                "steer_ref": _string("Pending user steer reference exposed by runtime."),
                "checkpoint_summary": _string("Recoverable checkpoint summary."),
                "resume_hint": _string("What to inspect first after resume."),
                "requires_user_input": {"type": "boolean"},
                "public_progress_note": _optional_string("Brief public pause note."),
                "public_action_state": _optional_public_action_state_schema(),
            },
            [
                "reason",
                "steer_ref",
                "checkpoint_summary",
                "resume_hint",
                "requires_user_input",
            ],
        )
    return {}


def _optional_public_action_state_schema() -> dict[str, Any]:
    return {
        "anyOf": [
            _public_action_state_schema(),
            {"type": "null"},
        ],
        "description": (
            "Public action state when it helps the user understand a semantic phase change. "
            "Use null rather than inventing feedback."
        ),
    }


def _public_action_state_schema() -> dict[str, Any]:
    return _strict_object(
        {
            "visible_status": {
                "type": "string",
                "enum": ["", "thinking", "waiting_for_tool", "tool_returned", "responding", "blocked"],
            },
            "current_judgment": _string("Short public judgment; no hidden reasoning."),
            "next_action": _string("Public next action aligned with this control action."),
            "evidence_refs": _string_array(),
            "open_risks": _string_array(),
            "completion_status": {
                "type": "string",
                "enum": ["", "working", "waiting_for_tool", "verifying", "ready_to_finish", "blocked"],
            },
        },
        ["visible_status", "current_judgment", "next_action", "evidence_refs", "open_risks", "completion_status"],
    )


def _optional_string(description: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"type": ["string", "null"]}
    if description:
        payload["description"] = f"{description} Use null rather than inventing feedback."
    return payload


def _mode_payload_schema() -> dict[str, Any]:
    return _strict_object(
        {
            "summary": _string("Compact summary of the primary work mode."),
            "steps": _string_array(),
            "success_definition": _string("Success definition when the primary mode is goal-like."),
            "question": _string("Problem statement or question when the primary mode is investigation-like."),
            "recovery_handle": _string("Recovery handle or previous-state reference for recovery mode."),
            "monitor_target": _string("Target to monitor when the primary mode is monitor."),
            "notes": _string_array(),
        },
        [],
    )


def _strict_object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    property_names = list(dict(properties or {}).keys())
    return {
        "type": "object",
        "properties": dict(properties or {}),
        "required": property_names,
        "additionalProperties": False,
    }


def _semantic_required_fields(action_name: str) -> list[str]:
    return {
        "respond": ["final_answer"],
        "ask_user": ["user_question"],
        "block": ["blocking_reason"],
        "request_task_run": [
            "primary_mode",
            "task_shape",
            "minimum_viable_next_step",
            "working_scope",
            "acceptance",
            "mode_payload",
            "todo_tool_contract",
        ],
        "active_work_control": ["action"],
        "resume_task_recovery": ["work_ref", "resume_ref"],
        "pause_for_user_steer": [
            "reason",
            "steer_ref",
            "checkpoint_summary",
            "resume_hint",
            "requires_user_input",
        ],
    }.get(action_name, [])


def _string(description: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "string"}
    if description:
        payload["description"] = description
    return payload


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


def _normalize_compact_working_scope(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_objects": _string_list(value.get("target_objects")),
        "workspace_refs": _string_list(value.get("workspace_refs")),
        "source_refs": _string_list(value.get("source_refs")),
        "excluded_scope": _string_list(value.get("excluded_scope")),
        "known_constraints": _string_list(value.get("known_constraints")),
    }


def _normalize_mode_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(value.get("summary") or value.get("strategy_summary") or "").strip(),
        "steps": _string_list(value.get("steps") or value.get("major_steps")),
        "success_definition": str(value.get("success_definition") or "").strip(),
        "question": str(value.get("question") or value.get("problem_statement") or "").strip(),
        "recovery_handle": str(value.get("recovery_handle") or value.get("previous_state") or "").strip(),
        "monitor_target": str(value.get("monitor_target") or "").strip(),
        "notes": _string_list(value.get("notes")),
    }


def _string_list(value: Any) -> list[str]:
    raw_items = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    return [str(item).strip() for item in raw_items if str(item or "").strip()]


def _drop_empty_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(payload or {}).items() if value not in ("", [], {}, None)}


def _stable_action_suffix(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = "control-action"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
