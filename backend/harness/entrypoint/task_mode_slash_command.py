from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from harness.loop.model_action_protocol import ModelActionRequest, model_action_request_from_payload


_TASK_MODE_ALIASES = {
    "goal": "goal",
    "g": "goal",
    "plan": "plan",
    "p": "plan",
    "todo": "todo",
    "todos": "todo",
    "td": "todo",
}


@dataclass(frozen=True, slots=True)
class TaskModeSlashSignal:
    command: str
    mode_kind: str
    body: str
    action_request: ModelActionRequest | None
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "mode_kind": self.mode_kind,
            "body": self.body,
            "action_request": self.action_request.to_dict() if self.action_request is not None else {},
            "diagnostics": dict(self.diagnostics or {}),
            "authority": "harness.entrypoint.task_mode_slash_command",
        }


def task_mode_slash_signal_from_message(message: str, *, turn_id: str) -> TaskModeSlashSignal | None:
    parsed = _parse_task_mode_slash_command(message)
    if parsed is None:
        return None
    command, mode_kind, body = parsed
    payload = _model_action_payload_for_task_mode_command(
        command=command,
        mode_kind=mode_kind,
        body=body,
        turn_id=turn_id,
    )
    action_request, diagnostics = model_action_request_from_payload(
        payload,
        turn_id=turn_id,
        require_public_progress_note=True,
        require_public_action_state=True,
        allowed_action_types=("request_task_run",),
    )
    return TaskModeSlashSignal(
        command=command,
        mode_kind=mode_kind,
        body=body,
        action_request=action_request,
        diagnostics=dict(diagnostics or {}),
    )


def _parse_task_mode_slash_command(message: str) -> tuple[str, str, str] | None:
    text = str(message or "").strip()
    if not text.startswith("/"):
        return None
    lines = text.splitlines()
    first_line = lines[0].strip()
    tail = "\n".join(line.rstrip() for line in lines[1:]).strip()
    parts = first_line.split(maxsplit=2)
    command = parts[0].lower()
    if command in {"/task", "/task-run", "/taskmode", "/task-mode"}:
        if len(parts) < 2:
            return None
        mode_kind = _TASK_MODE_ALIASES.get(parts[1].lower())
        body = parts[2].strip() if len(parts) >= 3 else ""
    else:
        mode_kind = _TASK_MODE_ALIASES.get(command.removeprefix("/"))
        body = first_line[len(parts[0]):].strip() if mode_kind else ""
    if not mode_kind:
        return None
    if tail:
        body = f"{body}\n{tail}".strip() if body else tail
    return command, mode_kind, body


def _model_action_payload_for_task_mode_command(
    *,
    command: str,
    mode_kind: str,
    body: str,
    turn_id: str,
) -> dict[str, Any]:
    mode_label = {"goal": "Goal", "plan": "Plan", "todo": "Todo"}.get(mode_kind, mode_kind)
    return {
        "authority": "harness.loop.model_action_request",
        "request_id": f"slash-task:{mode_kind}:{turn_id}:{uuid.uuid4().hex[:8]}",
        "turn_id": turn_id,
        "action_type": "request_task_run",
        "public_progress_note": f"已收到 {command} {mode_kind} 命令，正在申请长任务资源。",
        "public_action_state": {
            "current_judgment": f"用户显式选择 {mode_label} 意图，当前工作需要长任务资源保存目标和进度游标。",
            "next_action": "通过 request_task_run 申请长任务资源。",
            "completion_status": "working",
        },
        "task_run_contract_seed": _task_run_contract_seed_for_mode(mode_kind=mode_kind, body=body, command=command),
        "diagnostics": {
            "origin_kind": "slash_task_command",
            "origin_authority": "harness.entrypoint.task_mode_slash_command",
            "slash_command": command,
            "mode_kind": mode_kind,
        },
    }


def _task_run_contract_seed_for_mode(*, mode_kind: str, body: str, command: str) -> dict[str, Any]:
    title = _command_body_title(body, mode_kind=mode_kind)
    primary_mode = "goal" if mode_kind == "goal" else "plan"
    items = _split_command_items(body) or [title]
    return {
        "contract_shape": "compact_task_start_intent",
        "primary_mode": primary_mode,
        "task_shape": "standard",
        "minimum_viable_next_step": _minimum_next_step(mode_kind),
        "working_scope": {
            "target_objects": [title],
            "workspace_refs": [],
            "source_refs": [f"slash command {command}"],
            "excluded_scope": [],
            "known_constraints": [],
        },
        "acceptance": {
            "mode": "checkpoint",
            "criteria": ["形成可追踪进展", "在完成、阻塞或停止时给出明确收口反馈"],
            "final_answer_requirements": ["说明完成项", "说明验证结果", "说明未完成项和风险"],
        },
        "mode_payload": {
            "summary": title,
            "steps": items if primary_mode == "plan" else [_minimum_next_step(mode_kind)],
            "success_definition": title if primary_mode == "goal" else "",
            "notes": [f"source_command={command}", f"source_intent={mode_kind}"],
        },
        "todo_tool_contract": {
            "todo_is_tool": True,
            "cursor_updates": items if mode_kind == "todo" else [],
        },
    }

def _command_body_title(body: str, *, mode_kind: str) -> str:
    text = " ".join(str(body or "").split()).strip()
    if text:
        return text[:500]
    defaults = {
        "goal": "按用户当前意图申请 Goal 长任务资源。",
        "plan": "按用户当前意图申请 Plan 长任务资源。",
        "todo": "按用户当前意图申请带 todo 游标的长任务资源。",
    }
    return defaults.get(mode_kind, "按用户当前意图申请长任务资源。")


def _minimum_next_step(mode_kind: str) -> str:
    if mode_kind == "goal":
        return "确认目标边界，并推进第一项可验证工作。"
    if mode_kind == "plan":
        return "建立或校准计划，并推进第一个计划步骤。"
    return "执行或整理 Todo 列表的第一项。"


def _split_command_items(body: str) -> list[str]:
    text = str(body or "").strip()
    if not text:
        return []
    candidates = re.split(r"(?:\r?\n|；|;)+", text)
    return [" ".join(item.split()).strip()[:300] for item in candidates if " ".join(item.split()).strip()]
