from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .model_action_runtime import call_model_invoker, parse_json_object
from harness.runtime.public_progress import public_runtime_progress_summary


ActiveWorkTurnAction = Literal[
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "ask_user",
    "start_new_work",
    "normal_response",
]

_ALLOWED_ACTIONS: set[str] = {
    "continue_active_work",
    "pause_active_work",
    "stop_active_work",
    "append_instruction_to_active_work",
    "answer_about_active_work",
    "ask_user",
    "start_new_work",
    "normal_response",
}
_ACTIVE_WORK_STATUSES = {"created", "running", "waiting_executor", "waiting_approval", "blocked"}
_TERMINAL_STATUSES = {"completed", "success", "failed", "aborted", "cancelled", "error"}


@dataclass(frozen=True, slots=True)
class ActiveWorkContext:
    session_id: str
    active_work_id: str
    task_run_id: str
    status: str
    control_state: str = ""
    user_visible_goal: str = ""
    latest_progress: str = ""
    latest_step_name: str = ""
    resumable: bool = False
    running: bool = False
    paused: bool = False
    queued_user_instruction_count: int = 0
    execution_runtime_kind: str = ""
    authority: str = "harness.loop.active_work_context"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_model_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("task_run_id", None)
        payload.pop("authority", None)
        payload["current_work_id"] = self.active_work_id
        payload["status_label"] = active_work_status_label(self)
        return payload


@dataclass(frozen=True, slots=True)
class ActiveWorkTurnDecision:
    action: ActiveWorkTurnAction
    response: str = ""
    appended_instruction: str = ""
    reason: str = ""
    confidence: float = 0.0
    authority: str = "harness.loop.active_work_turn_decision"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_active_work_context(runtime_host: Any, *, session_id: str) -> ActiveWorkContext | None:
    session_id = str(session_id or "").strip()
    if not session_id:
        return None
    try:
        monitor = runtime_host.get_session_live_monitor(session_id)
    except Exception:
        monitor = {}
    candidates: list[dict[str, Any]] = []
    direct = dict(monitor.get("monitor") or {}) if isinstance(monitor, dict) else {}
    if direct:
        candidates.append(direct)
    if isinstance(monitor, dict):
        candidates.extend([dict(item) for item in list(monitor.get("task_runs") or []) if isinstance(item, dict)])
    if not candidates:
        task_runs = getattr(getattr(runtime_host, "state_index", None), "list_session_task_runs", lambda _session_id: [])(session_id)
        for task_run in sorted(task_runs, key=lambda item: float(getattr(item, "updated_at", 0.0) or 0.0), reverse=True):
            if _is_candidate_task_run(task_run):
                try:
                    projected = runtime_host.monitor_projector.project_task_run(task_run, now=time.time())
                except Exception:
                    projected = task_run.to_dict() if hasattr(task_run, "to_dict") else {}
                candidates.append(dict(projected or {}))
    for item in candidates:
        context = _context_from_monitor_item(runtime_host, session_id=session_id, item=item)
        if context is not None:
            return context
    return None


async def decide_active_work_turn(
    *,
    model_runtime: Any,
    user_message: str,
    active_work_context: ActiveWorkContext,
    model_selection: dict[str, Any] | None = None,
) -> ActiveWorkTurnDecision:
    invoker = getattr(model_runtime, "invoke_messages", None)
    if not callable(invoker):
        return ActiveWorkTurnDecision(
            action="ask_user",
            response="我需要确认一下：你是要继续处理当前这件事，还是开始新的请求？",
            reason="model_runtime_unavailable",
        )
    messages = [
        {
            "role": "system",
            "content": (
                "你负责判断用户这一句话和当前正在处理的工作之间的关系。\n"
                "用户仍然是在和同一个助手对话；不要把内部运行状态、执行器、TaskRun 或协议细节说给用户。\n"
                "请只输出一个 JSON 对象，不要输出 Markdown。\n"
                "可选 action：continue_active_work、pause_active_work、stop_active_work、"
                "append_instruction_to_active_work、answer_about_active_work、ask_user、start_new_work、normal_response。\n"
                "判断规则：如果用户是在让当前工作继续、暂停、停止、补充方向、询问进度，应选择对应当前工作的动作；"
                "如果用户明确开启无关新目标，选择 start_new_work；如果只是普通闲聊且不涉及当前工作，选择 normal_response。\n"
                "不要依赖单个关键词，必须结合当前工作状态和用户原话判断。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "authority": "harness.loop.active_work_turn_decision.input",
                    "user_message": str(user_message or ""),
                    "active_work_context": active_work_context.to_model_dict(),
                    "output_contract": {
                        "authority": "harness.loop.active_work_turn_decision",
                        "action": "one_allowed_action",
                        "response": "给用户看的简短自然回复；不能包含内部协议名",
                        "appended_instruction": "当 action 为 append_instruction_to_active_work 时，写入用户补充指令原意",
                        "reason": "简短判断依据",
                        "confidence": 0.0,
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        response = await call_model_invoker(
            invoker,
            messages,
            model_selection=dict(model_selection or {}),
            accounting_context={
                "source": "harness.loop.active_work_turn_decision",
                "session_id": active_work_context.session_id,
                "task_run_id": active_work_context.task_run_id,
                "request_id": f"modelreq:active-work:{uuid.uuid4().hex[:10]}",
            },
        )
    except Exception:
        return ActiveWorkTurnDecision(
            action="ask_user",
            response="我需要确认一下：你是要继续处理当前这件事，还是开始新的请求？",
            reason="active_work_decision_model_failed",
        )
    return active_work_turn_decision_from_payload(
        parse_json_object(getattr(response, "content", response)),
        user_message=user_message,
    )


def active_work_turn_decision_from_payload(payload: dict[str, Any] | None, *, user_message: str = "") -> ActiveWorkTurnDecision:
    raw = dict(payload or {})
    authority = str(raw.get("authority") or "harness.loop.active_work_turn_decision").strip()
    action = str(raw.get("action") or raw.get("intent") or "").strip()
    if authority != "harness.loop.active_work_turn_decision" or action not in _ALLOWED_ACTIONS:
        return ActiveWorkTurnDecision(
            action="ask_user",
            response="我需要确认一下：你是要继续处理当前这件事，还是开始新的请求？",
            reason="active_work_turn_decision_invalid",
        )
    response = public_active_work_text(str(raw.get("response") or ""))
    appended_instruction = str(raw.get("appended_instruction") or "").strip()
    if action == "append_instruction_to_active_work" and not appended_instruction:
        appended_instruction = str(user_message or "").strip()
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return ActiveWorkTurnDecision(
        action=action,  # type: ignore[arg-type]
        response=response,
        appended_instruction=appended_instruction,
        reason=str(raw.get("reason") or "").strip(),
        confidence=confidence,
    )


def public_active_work_text(value: str) -> str:
    text = str(value or "").strip()
    replacements = {
        "TaskRun": "当前工作",
        "task run": "当前工作",
        "runtime packet": "上下文",
        "执行器": "处理流程",
        "正式任务": "当前工作",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def active_work_status_label(context: ActiveWorkContext) -> str:
    if context.paused:
        return "已暂停"
    if context.control_state == "pause_requested":
        return "正在暂停"
    if context.control_state == "stop_requested":
        return "正在停止"
    if context.status in {"waiting_executor", "blocked"}:
        return "等待继续"
    if context.status == "waiting_approval":
        return "等待确认"
    if context.status in {"created", "running"}:
        return "正在处理"
    if context.status in {"completed", "success"}:
        return "已完成"
    if context.status in {"failed", "aborted", "cancelled", "error"}:
        return "已结束"
    return context.status or "处理中"


def active_work_status_reply(context: ActiveWorkContext) -> str:
    parts = [f"现在是{active_work_status_label(context)}。"]
    if context.user_visible_goal:
        parts.append(f"当前处理的是：{context.user_visible_goal}")
    if context.latest_progress:
        parts.append(f"最近进展：{context.latest_progress}")
    if context.paused:
        parts.append("你说继续后，我会从这里接着处理。")
    elif context.resumable:
        parts.append("目前可以继续推进。")
    elif context.running:
        parts.append("我会把新的进展继续更新在当前会话里。")
    return "\n".join(part for part in parts if part.strip())


def default_reply_for_action(action: str, context: ActiveWorkContext) -> str:
    if action == "continue_active_work":
        return "好，我接着处理。"
    if action == "pause_active_work":
        return "好，我先停在这里。后面你说继续，我会从这里接着做。"
    if action == "stop_active_work":
        return "好，我会停止当前处理。"
    if action == "append_instruction_to_active_work":
        return "收到，我会按这个补充方向继续处理。"
    if action == "answer_about_active_work":
        return active_work_status_reply(context)
    return "我需要确认一下：你是要继续处理当前这件事，还是开始新的请求？"


def _context_from_monitor_item(runtime_host: Any, *, session_id: str, item: dict[str, Any]) -> ActiveWorkContext | None:
    task_run_id = str(item.get("task_run_id") or dict(item.get("task_run") or {}).get("task_run_id") or "").strip()
    if not task_run_id:
        return None
    task_run = runtime_host.state_index.get_task_run(task_run_id)
    if task_run is None or not _is_candidate_task_run(task_run):
        return None
    status = str(item.get("status") or getattr(task_run, "status", "") or "").strip()
    if status in _TERMINAL_STATUSES or status not in _ACTIVE_WORK_STATUSES:
        return None
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    control = item.get("runtime_control")
    if not isinstance(control, dict):
        control = diagnostics.get("runtime_control") if isinstance(diagnostics.get("runtime_control"), dict) else {}
    control_state = str(item.get("control_state") or dict(control or {}).get("state") or "").strip()
    contract = _load_task_contract(runtime_host, task_run)
    latest_progress = _public_progress_text(
        str(
            item.get("latest_step_summary")
            or item.get("summary")
            or diagnostics.get("latest_step_summary")
            or ""
        )
    )
    goal = _first_text(
        item.get("title"),
        diagnostics.get("title"),
        diagnostics.get("goal"),
        contract.get("user_visible_goal"),
        contract.get("task_run_goal"),
    )
    return ActiveWorkContext(
        session_id=session_id,
        active_work_id=task_run_id,
        task_run_id=task_run_id,
        status=status,
        control_state=control_state,
        user_visible_goal=goal,
        latest_progress=latest_progress,
        latest_step_name=str(item.get("latest_step_name") or diagnostics.get("latest_step") or "").strip(),
        resumable=status == "waiting_executor" and control_state not in {"pause_requested", "stop_requested", "stopped"},
        running=status in {"created", "running"} or str(diagnostics.get("executor_status") or "") in {"scheduled", "running"},
        paused=control_state == "paused",
        queued_user_instruction_count=_user_instruction_count(runtime_host, task_run_id),
        execution_runtime_kind=str(getattr(task_run, "execution_runtime_kind", "") or ""),
    )


def _is_candidate_task_run(task_run: Any) -> bool:
    if str(getattr(task_run, "execution_runtime_kind", "") or "") != "single_agent_task":
        return False
    diagnostics = dict(getattr(task_run, "diagnostics", {}) or {})
    if str(diagnostics.get("origin_kind") or "") == "graph_node_assigned":
        return False
    if diagnostics.get("graph_run_id") or diagnostics.get("graph_harness_config_id"):
        return False
    return True


def _load_task_contract(runtime_host: Any, task_run: Any) -> dict[str, Any]:
    ref = str(getattr(task_run, "task_contract_ref", "") or "").strip()
    if not ref:
        return {}
    try:
        return dict(runtime_host.runtime_objects.get_object(ref) or {})
    except Exception:
        return {}


def _user_instruction_count(runtime_host: Any, task_run_id: str) -> int:
    count = 0
    try:
        events = runtime_host.event_log.list_events(task_run_id)
    except Exception:
        events = []
    for event in events:
        payload = dict(getattr(event, "payload", {}) or {})
        observation = payload.get("observation")
        if isinstance(observation, dict) and str(observation.get("observation_type") or "") == "user_work_instruction":
            count += 1
    return count


def _public_progress_text(value: str) -> str:
    text = public_runtime_progress_summary(public_active_work_text(str(value or "").strip()))
    replacements = {
        "系统已为当前任务步骤装配 上下文，并交给 助手 判断下一步。": "正在整理上下文，准备继续处理。",
        "任务 上下文 已送入模型，系统正在等待 助手 返回任务动作。": "正在处理这一步。",
        "运行包已交给模型，等待 助手 返回下一步动作。": "正在处理这一步。",
        "任务执行器已被调度，正在接管 当前工作。": "正在准备继续处理。",
    }
    for source, target in replacements.items():
        if text == source:
            return target
    return text


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and not _looks_internal_identifier(text):
            return text
    return ""


def _looks_internal_identifier(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("task:", "taskrun:", "turn:", "turnrun:", "session:", "rtobj:"))
