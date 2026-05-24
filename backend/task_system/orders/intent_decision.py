from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .models import TaskIntentDecision


_EXECUTION_VERBS = (
    "implement",
    "refactor",
    "fix",
    "delete",
    "remove",
    "create",
    "write",
    "modify",
    "migrate",
    "run",
    "execute",
    "test",
    "build",
    "generate",
    "deploy",
    "实现",
    "重构",
    "修",
    "修复",
    "删除",
    "清理",
    "创建",
    "新增",
    "写入",
    "修改",
    "迁移",
    "运行",
    "执行",
    "测试",
    "生成",
    "实施",
)
_DISCUSSION_CUES = (
    "讨论",
    "分析",
    "计划",
    "计划书",
    "设计书",
    "方案",
    "思路",
    "怎么看",
    "为什么",
    "解释",
    "讲一下",
    "review",
    "discuss",
    "explain",
    "plan",
    "design",
)
_OBJECT_HINTS = (
    "file",
    "code",
    "test",
    "api",
    "ui",
    "frontend",
    "backend",
    "doc",
    "page",
    "文件",
    "代码",
    "测试",
    "接口",
    "前端",
    "后端",
    "文档",
    "页面",
    "任务",
    "任务图",
)
_LIFECYCLE_HINTS = (
    "后台",
    "并行",
    "监控",
    "恢复",
    "暂停",
    "审批",
    "人工",
    "写入",
    "修改",
    "删除",
    "测试",
    "运行",
    "长期",
    "background",
    "parallel",
    "monitor",
    "resume",
    "pause",
    "approval",
    "human",
    "write",
    "modify",
    "delete",
    "test",
    "run",
)


@dataclass(frozen=True, slots=True)
class TaskIntentDecisionService:
    """Deterministic first-pass classifier for task order authority."""

    authority: str = "task_system.intent_decision_service"

    def decide(
        self,
        *,
        turn_id: str,
        message: str,
        task_selection: dict[str, Any] | None = None,
        task_order_intent: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> TaskIntentDecision:
        selection = dict(task_selection or {})
        explicit_intent = dict(task_order_intent or {})
        text = str(message or "").strip()
        text_lower = text.lower()
        now = float(created_at if created_at is not None else time.time())
        hard_signals: list[str] = []
        contract_signals: list[str] = []
        weak_signals: list[str] = []
        lifecycle_needs: list[str] = []
        missing_fields: list[str] = []
        evidence_spans: list[dict[str, Any]] = []

        selected_task_id = str(selection.get("selected_task_id") or "").strip()
        mode = str(selection.get("mode") or selection.get("task_mode") or "").strip()
        explicit_action = str(explicit_intent.get("action") or explicit_intent.get("intent") or "").strip()
        explicit_order_kind = str(explicit_intent.get("order_kind") or "").strip()

        if explicit_action in {"run_task", "execute_task", "create_order", "start_graph"} or explicit_order_kind:
            hard_signals.append(f"task_order_intent:{explicit_action or explicit_order_kind}")
            evidence_spans.append(_evidence("task_order_intent", explicit_action or explicit_order_kind))
        if selected_task_id:
            if mode in {"single_task", "specific_task", "task_library_run", "run_task"}:
                hard_signals.append("legacy_task_selection:selected_task_id")
            else:
                weak_signals.append("task_selection:selected_task_id")
            evidence_spans.append(_evidence("selected_task_id", selected_task_id))

        agent_mode_fields = [
            key
            for key in ("agent_id", "agent_profile_id", "runtime_lane", "interaction_mode", "mode_policy")
            if str(selection.get(key) or "").strip()
        ]
        if agent_mode_fields:
            weak_signals.append("main_agent_mode_projection")

        has_discussion_cue = _contains_any(text_lower, _DISCUSSION_CUES)
        has_execution_verb = _contains_any(text_lower, _EXECUTION_VERBS)
        has_object_hint = _contains_any(text_lower, _OBJECT_HINTS)
        has_lifecycle_hint = _contains_any(text_lower, _LIFECYCLE_HINTS)
        if has_execution_verb:
            contract_signals.append("objective:execution_request")
            evidence_spans.append(_first_match_evidence(text, _EXECUTION_VERBS, "execution_verb"))
        if has_object_hint:
            contract_signals.append("object:work_target")
        if has_lifecycle_hint:
            lifecycle_needs.append("supervised_side_effect_or_delivery")

        if hard_signals:
            decision = "executable_task"
            confidence = 0.92 if selected_task_id or explicit_order_kind else 0.86
            reason = "A structured hard signal accepted this turn as a task contract."
        elif has_execution_verb and has_object_hint and not _discussion_only(text_lower, has_discussion_cue):
            decision = "executable_task"
            confidence = 0.72
            reason = "The user requested executable work with an identifiable work target."
        elif (selected_task_id or has_execution_verb) and not has_object_hint and not hard_signals:
            decision = "task_order_draft"
            confidence = 0.54
            reason = "The turn looks task-like but lacks enough contract fields to execute."
            if not has_object_hint:
                missing_fields.append("task_object")
            if not has_lifecycle_hint and not selected_task_id:
                missing_fields.append("lifecycle_need")
        else:
            decision = "chat_turn"
            confidence = 0.78 if has_discussion_cue else 0.66
            reason = "No reliable task order signal was present."

        return TaskIntentDecision(
            decision_id=f"intent:{turn_id}:{uuid.uuid4().hex[:8]}",
            turn_id=turn_id,
            decision=decision,  # type: ignore[arg-type]
            confidence=confidence,
            hard_signals=tuple(_dedupe(hard_signals)),
            contract_signals=tuple(_dedupe(contract_signals)),
            weak_signals=tuple(_dedupe(weak_signals)),
            evidence_spans=tuple(item for item in evidence_spans if item),
            missing_fields=tuple(_dedupe(missing_fields)),
            lifecycle_needs=tuple(_dedupe(lifecycle_needs)),
            reason=reason,
            created_at=now,
            metadata={
                "classifier": "deterministic_shadow_classifier",
                "discussion_cue": has_discussion_cue,
                "execution_verb": has_execution_verb,
                "object_hint": has_object_hint,
                "lifecycle_hint": has_lifecycle_hint,
            },
        )


def decision_with_created_order(decision: TaskIntentDecision, order_id: str) -> TaskIntentDecision:
    return TaskIntentDecision(
        **{
            **decision.to_dict(),
            "hard_signals": tuple(decision.hard_signals),
            "contract_signals": tuple(decision.contract_signals),
            "weak_signals": tuple(decision.weak_signals),
            "evidence_spans": tuple(decision.evidence_spans),
            "missing_fields": tuple(decision.missing_fields),
            "lifecycle_needs": tuple(decision.lifecycle_needs),
            "created_order_id": order_id,
        }
    )


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle.lower() in text for needle in needles)


def _discussion_only(text: str, has_discussion_cue: bool) -> bool:
    if not has_discussion_cue:
        return False
    strong_execute = any(needle in text for needle in ("实施", "执行", "run", "execute", "修复", "修改"))
    return not strong_execute


def _evidence(source: str, value: str) -> dict[str, Any]:
    return {"source": source, "text": str(value or "")[:240]}


def _first_match_evidence(text: str, needles: tuple[str, ...], source: str) -> dict[str, Any]:
    for needle in needles:
        match = re.search(re.escape(needle), text, flags=re.IGNORECASE)
        if match:
            return {
                "source": source,
                "text": text[max(0, match.start() - 24) : match.end() + 24],
                "start": match.start(),
                "end": match.end(),
            }
    return {}


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item)))
