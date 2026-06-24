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
        "public_progress_note": f"已收到 {command} {mode_kind} 命令，正在提交 {mode_label} Mode 任务启动信号。",
        "public_action_state": {
            "current_judgment": f"用户显式选择 {mode_label} Mode，当前工作需要持续任务生命周期。",
            "next_action": f"通过 request_task_run 启动 primary {mode_label} Work Mode。",
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
    primary_ref = f"work-mode:{mode_kind}:primary"
    title = _command_body_title(body, mode_kind=mode_kind)
    return {
        "contract_version": "task_run_contract_v1",
        "container_contract": {
            "entry_reason": f"用户通过 {command} 显式要求进入 {mode_kind} 工作模式。",
            "continuity_required": True,
            "control_required": True,
            "projection_required": True,
            "checkpoint_required": True,
            "minimum_viable_next_step": _minimum_next_step(mode_kind),
            "primary_work_mode_ref": primary_ref,
            "supporting_mode_refs": [],
            "mode_transition_policy": {
                "agent_may_propose_transition": True,
                "system_may_infer_transition": False,
                "requires_accepted_event": True,
            },
        },
        "work_modes": [
            {
                "mode_instance_id": primary_ref,
                "mode_kind": mode_kind,
                "mode_role": "primary",
                "status": "draft",
                "depends_on_mode_refs": [],
                "contract": _work_mode_contract(mode_kind=mode_kind, body=body, title=title),
            }
        ],
        "memory_contract": {
            "checkpoint_policy": {"write_checkpoint_on_step": True},
            "provider_visible_replay_policy": {"replay_only": True},
            "recovery_package_policy": {"include_active_work_mode_refs": True},
        },
        "acceptance_contract": {
            "acceptance_mode": "checkpoint",
            "final_answer_requirements": ["说明完成项", "说明验证结果", "说明未完成项和风险"],
            "evidence_refs_required": False,
        },
    }


def _work_mode_contract(*, mode_kind: str, body: str, title: str) -> dict[str, Any]:
    if mode_kind == "goal":
        return {
            "user_visible_goal": title,
            "task_run_goal": title,
            "success_definition": "围绕该目标形成可验证进展，并在完成、阻塞或停止时给出明确收口反馈。",
            "evidence_contract": {"evidence_required": True, "source": "slash_task_command"},
            "working_scope": {},
        }
    if mode_kind == "plan":
        steps = _split_command_items(body)
        return {
            "strategy_summary": title,
            "major_steps": steps or [title],
            "plan_status": "agent_managed",
            "allowed_plan_operations": ["create", "update", "replan", "explain_deviation"],
            "replan_policy": {"requires_reason": True, "version_must_change_or_reason_required": True},
            "working_scope": {},
        }
    items = _split_command_items(body) or [title]
    return {
        "todo_list_id": f"todo:slash:{uuid.uuid4().hex[:8]}",
        "items": [
            {
                "item_id": f"todo-item:{index + 1}",
                "title": item,
                "status": "pending",
            }
            for index, item in enumerate(items)
        ],
        "active_item_id": "todo-item:1",
        "completion_policy": "checkpoint_only",
        "working_scope": {},
    }


def _command_body_title(body: str, *, mode_kind: str) -> str:
    text = " ".join(str(body or "").split()).strip()
    if text:
        return text[:500]
    defaults = {
        "goal": "按用户当前意图建立 Goal Mode 持续任务。",
        "plan": "按用户当前意图建立 Plan Mode 持续任务。",
        "todo": "按用户当前意图建立 Todo Mode 持续任务。",
    }
    return defaults.get(mode_kind, "按用户当前意图建立持续任务。")


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
