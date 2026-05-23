from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .communication_frame import build_communication_frame
from .model_understanding_request import build_model_understanding_request
from .understanding_arbitration import (
    UnderstandingArbitration,
    arbitrate_task_understanding,
)


@dataclass(frozen=True, slots=True)
class TaskUnderstandingFrame:
    frame_id: str
    user_message: str
    interaction_intent: str
    action_intent: str
    communication_frame_ref: str = ""
    communication_frame: dict[str, Any] = field(default_factory=dict)
    model_understanding_request: dict[str, Any] = field(default_factory=dict)
    model_understanding_draft_ref: str = ""
    understanding_arbitration_ref: str = ""
    understanding_arbitration: dict[str, Any] = field(default_factory=dict)
    priority_stack: tuple[dict[str, Any], ...] = ()
    conflict_set: tuple[dict[str, Any], ...] = ()
    assumption_set: tuple[str, ...] = ()
    decision_trace: tuple[dict[str, Any], ...] = ()
    target_objects: tuple[str, ...] = ()
    desired_outcomes: tuple[str, ...] = ()
    explicit_constraints: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    user_provided_flow: tuple[str, ...] = ()
    context_binding: dict[str, Any] = field(default_factory=dict)
    execution_mode_hint: str = "answer"
    task_domain_hint: str = "general"
    task_goal_type_hint: str = ""
    evidence_requirements: tuple[str, ...] = ()
    ambiguity_points: tuple[str, ...] = ()
    clarification_needed: bool = False
    clarification_question: str = ""
    playbook_policy: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    authority: str = "intent.task_understanding_frame"

    def __post_init__(self) -> None:
        if self.authority != "intent.task_understanding_frame":
            raise ValueError("TaskUnderstandingFrame authority must be intent.task_understanding_frame")
        if not self.frame_id:
            raise ValueError("TaskUnderstandingFrame requires frame_id")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["communication_frame"] = dict(self.communication_frame or {})
        payload["model_understanding_request"] = dict(self.model_understanding_request or {})
        payload["understanding_arbitration"] = dict(self.understanding_arbitration or {})
        payload["priority_stack"] = [dict(item) for item in self.priority_stack]
        payload["conflict_set"] = [dict(item) for item in self.conflict_set]
        payload["assumption_set"] = list(self.assumption_set)
        payload["decision_trace"] = [dict(item) for item in self.decision_trace]
        payload["target_objects"] = list(self.target_objects)
        payload["desired_outcomes"] = list(self.desired_outcomes)
        payload["explicit_constraints"] = list(self.explicit_constraints)
        payload["forbidden_actions"] = list(self.forbidden_actions)
        payload["user_provided_flow"] = list(self.user_provided_flow)
        payload["context_binding"] = dict(self.context_binding or {})
        payload["evidence_requirements"] = list(self.evidence_requirements)
        payload["ambiguity_points"] = list(self.ambiguity_points)
        payload["playbook_policy"] = dict(self.playbook_policy or {})
        return payload


def build_task_understanding_frame(
    message: str,
    *,
    intent_frame: dict[str, Any] | None = None,
    intent_decision: dict[str, Any] | None = None,
    query_understanding: dict[str, Any] | None = None,
    task_goal_type_hint: str = "",
    task_domain_hint: str = "",
    model_understanding_draft: dict[str, Any] | None = None,
) -> TaskUnderstandingFrame:
    text = str(message or "").strip()
    lowered = text.lower()
    frame = dict(intent_frame or {})
    intent = dict(intent_decision or {})
    understanding = dict(query_understanding or {})
    deterministic_interaction_intent = _interaction_intent(lowered)
    deterministic_action_intent = _action_intent(lowered, understanding=understanding)
    deterministic_execution_mode = _execution_mode_hint(
        lowered,
        action_intent=deterministic_action_intent,
        query_understanding=understanding,
        intent_decision=intent,
    )
    deterministic_domain_hint = (
        str(task_domain_hint or "").strip()
        or _domain_hint(lowered, query_understanding=understanding, intent_decision=intent)
    )
    deterministic_goal_hint = str(task_goal_type_hint or "").strip()
    deterministic_flow = tuple(_extract_user_flow(text))
    deterministic_context_binding = _context_binding(lowered, query_understanding=understanding)
    deterministic_forbidden = tuple(_forbidden_actions(lowered))
    deterministic_constraints = tuple(_explicit_constraints(text))
    deterministic_ambiguity = tuple(
        _ambiguity_points(
            lowered,
            interaction_intent=deterministic_interaction_intent,
            action_intent=deterministic_action_intent,
        )
    )
    deterministic_values = {
        "frame_id": f"understanding:{_slug(text)[:48] or 'runtime'}",
        "interaction_intent": deterministic_interaction_intent,
        "action_intent": deterministic_action_intent,
        "target_objects": tuple(_target_objects(text, query_understanding=understanding)),
        "desired_outcomes": tuple(_desired_outcomes(lowered, action_intent=deterministic_action_intent)),
        "explicit_constraints": deterministic_constraints,
        "forbidden_actions": deterministic_forbidden,
        "user_provided_flow": deterministic_flow,
        "context_binding": deterministic_context_binding,
        "execution_mode_hint": deterministic_execution_mode,
        "task_domain_hint": deterministic_domain_hint,
        "task_goal_type_hint": deterministic_goal_hint,
        "evidence_requirements": tuple(
            _evidence_requirements(deterministic_execution_mode, deterministic_domain_hint, deterministic_goal_hint)
        ),
        "ambiguity_points": deterministic_ambiguity,
        "_source_strength": {
            "task_domain_hint": "caller_hint" if str(task_domain_hint or "").strip() else "deterministic_signal",
            "task_goal_type_hint": "caller_hint" if deterministic_goal_hint else "deterministic_signal",
        },
    }
    arbitration = arbitrate_task_understanding(
        user_message=text,
        deterministic_values=deterministic_values,
        model_understanding_draft=model_understanding_draft,
    )
    resolved = dict(arbitration.resolved_values or {})
    interaction_intent = str(resolved.get("interaction_intent") or deterministic_interaction_intent).strip()
    action_intent = str(resolved.get("action_intent") or deterministic_action_intent).strip()
    execution_mode = str(resolved.get("execution_mode_hint") or deterministic_execution_mode).strip()
    domain_hint = str(resolved.get("task_domain_hint") or deterministic_domain_hint).strip()
    goal_hint = str(resolved.get("task_goal_type_hint") or deterministic_goal_hint).strip()
    flow = tuple(_dedupe([str(item).strip() for item in list(resolved.get("user_provided_flow") or []) if str(item).strip()]))
    context_binding = dict(resolved.get("context_binding") or deterministic_context_binding)
    forbidden = tuple(_dedupe([str(item).strip() for item in list(resolved.get("forbidden_actions") or []) if str(item).strip()]))
    constraints = tuple(_dedupe([str(item).strip() for item in list(resolved.get("explicit_constraints") or []) if str(item).strip()]))
    ambiguity = tuple(_dedupe([str(item).strip() for item in list(resolved.get("ambiguity_points") or []) if str(item).strip()]))
    clarification_needed = bool(ambiguity and not flow and action_intent in {"modify", "create", "execute"})
    communication_frame = build_communication_frame(
        text,
        action_intent=action_intent,
        user_provided_flow=flow,
        ambiguity_points=ambiguity,
        forbidden_actions=forbidden,
        query_understanding=understanding,
    )
    model_understanding_request = build_model_understanding_request(
        request_id=f"model-understanding-request:{_slug(text)[:48] or 'runtime'}",
        user_message=text,
        deterministic_signals=deterministic_values,
        communication_frame=communication_frame.to_dict(),
    )
    return TaskUnderstandingFrame(
        frame_id=str(deterministic_values["frame_id"]),
        user_message=text,
        communication_frame_ref=communication_frame.frame_id,
        communication_frame=communication_frame.to_dict(),
        model_understanding_request=model_understanding_request.to_dict(),
        model_understanding_draft_ref=arbitration.model_draft_ref,
        understanding_arbitration_ref=arbitration.arbitration_id,
        understanding_arbitration=arbitration.to_dict(),
        priority_stack=arbitration.priority_stack,
        conflict_set=arbitration.conflict_set,
        assumption_set=arbitration.assumption_set,
        decision_trace=arbitration.decision_trace,
        interaction_intent=interaction_intent,
        action_intent=action_intent,
        target_objects=tuple(resolved.get("target_objects") or ()),
        desired_outcomes=tuple(resolved.get("desired_outcomes") or _desired_outcomes(lowered, action_intent=action_intent)),
        explicit_constraints=constraints,
        forbidden_actions=forbidden,
        user_provided_flow=flow,
        context_binding=context_binding,
        execution_mode_hint=execution_mode,
        task_domain_hint=domain_hint,
        task_goal_type_hint=goal_hint,
        evidence_requirements=tuple(resolved.get("evidence_requirements") or _evidence_requirements(execution_mode, domain_hint, goal_hint)),
        ambiguity_points=ambiguity,
        clarification_needed=clarification_needed,
        clarification_question="请确认你希望我先分析方案，还是直接执行修改？" if clarification_needed else "",
        playbook_policy=_playbook_policy(domain_hint=domain_hint, has_user_flow=bool(flow), forbidden_actions=forbidden),
        confidence=_understanding_confidence(
            base=_confidence(frame=frame, understanding=understanding, has_user_flow=bool(flow)),
            arbitration=arbitration,
        ),
    )


def _understanding_confidence(*, base: float, arbitration: UnderstandingArbitration) -> float:
    diagnostics = dict(arbitration.diagnostics or {})
    if diagnostics.get("model_draft_status") != "accepted":
        return base
    model_confidence = float(diagnostics.get("model_draft_confidence") or 0.0)
    if model_confidence <= 0:
        return base
    penalty = min(0.18, 0.04 * len(arbitration.conflict_set))
    return min(max((base * 0.45) + (model_confidence * 0.55) - penalty, 0.0), 0.98)


def _interaction_intent(lowered: str) -> str:
    if _has_any(lowered, ("继续", "接着", "下一步", "往下", "推进")):
        return "continue_task"
    if _has_any(lowered, ("审查", "review", "检查一下", "帮我看看", "评审")):
        return "review"
    if _has_any(lowered, ("解释", "说明", "为什么", "怎么理解", "是什么")):
        return "explain"
    if _has_any(lowered, ("设计", "规划", "计划", "方案", "架构")):
        return "plan"
    if _has_any(lowered, ("做", "实现", "开发", "修复", "修改", "写入", "生成", "创建", "执行")):
        return "execute"
    return "conversation"


def _action_intent(lowered: str, *, understanding: dict[str, Any]) -> str:
    task_kind = str(understanding.get("task_kind") or "").strip()
    route = str(understanding.get("route") or understanding.get("route_hint") or "").strip()
    if task_kind == "workspace_file_write" or _has_any(lowered, ("写入", "生成文件", "创建文件")):
        return "create"
    if _has_any(lowered, ("修复", "修改", "只改", "改代码", "改必要", "改成", "改动", "编辑", "重构", "实现", "开发", "fix", "patch")):
        return "modify"
    if task_kind in {"workspace_file_read", "workspace_file_search"} or route.startswith("workspace_"):
        return "inspect"
    if _has_any(lowered, ("审查", "review", "检查", "验证", "测试")):
        return "verify"
    if route in {"realtime_network", "search"} or _has_any(lowered, ("搜索", "查询", "最新", "今天")):
        return "research"
    if _has_any(lowered, ("解释", "说明", "为什么", "是什么")):
        return "answer"
    return "answer"


def _execution_mode_hint(
    lowered: str,
    *,
    action_intent: str,
    query_understanding: dict[str, Any],
    intent_decision: dict[str, Any],
) -> str:
    if _has_any(lowered, ("不要改", "不要修改", "只分析", "只读", "read only", "readonly")):
        return "analysis_only"
    strategy = str(intent_decision.get("execution_strategy") or "").strip()
    if strategy:
        return strategy
    posture = str(query_understanding.get("execution_posture") or "").strip()
    if posture in {"task_runtime", "bounded_agent"} and action_intent in {"modify", "create", "execute"}:
        return "agent_execution"
    if action_intent in {"modify", "create"}:
        return "implementation"
    if action_intent == "verify":
        return "verification"
    if action_intent in {"inspect", "research"}:
        return "investigation"
    return "answer"


def _domain_hint(
    lowered: str,
    *,
    query_understanding: dict[str, Any],
    intent_decision: dict[str, Any],
) -> str:
    target_domain = str(
        intent_decision.get("target_domain_hint")
        or intent_decision.get("target_domain")
        or ""
    ).strip()
    if target_domain:
        return target_domain
    if _has_any(lowered, ("代码", "前端", "后端", "api", "bug", "测试", "开发", "实现", "修复", "仓库", "项目")):
        return "development"
    if _has_any(lowered, ("pdf", "文档", "报告", "材料")):
        return "document"
    if _has_any(lowered, ("表格", "excel", "csv", "数据集", "统计")):
        return "data_analysis"
    if _has_any(lowered, ("写作", "小说", "世界观", "角色", "章节")):
        return "writing"
    source_kind = str(query_understanding.get("source_kind") or "").strip()
    if source_kind in {"workspace", "task_system"}:
        return "development"
    if source_kind:
        return source_kind
    return "general"


def _target_objects(text: str, *, query_understanding: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    path = str(dict(query_understanding.get("tool_input") or {}).get("path") or "").strip()
    if path:
        targets.append(f"path:{path}")
    targets.extend(f"path:{item}" for item in _path_markers(text))
    for marker in ("理解系统", "任务域", "prompt", "todo", "状态机", "计划书", "代码", "文档"):
        if marker in text and marker not in targets:
            targets.append(marker)
    return _dedupe(targets)


def _desired_outcomes(lowered: str, *, action_intent: str) -> list[str]:
    outcomes: list[str] = []
    if action_intent in {"modify", "create"}:
        outcomes.append("real_workspace_change")
    if _has_any(lowered, ("计划书", "方案", "设计")):
        outcomes.append("implementation_plan")
    if _has_any(lowered, ("验证", "测试", "跑一下")):
        outcomes.append("verification_result")
    if _has_any(lowered, ("总结", "说明", "解释")):
        outcomes.append("clear_explanation")
    if not outcomes:
        outcomes.append("useful_answer")
    return outcomes


def _explicit_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for marker in ("必须", "不能", "不要", "需要", "最好", "先", "再", "最后", "通用", "高要求"):
        if marker in text:
            constraints.append(marker)
    constraints.extend(f"path:{item}" for item in _path_markers(text))
    return _dedupe(constraints)


def _forbidden_actions(lowered: str) -> list[str]:
    forbidden: list[str] = []
    if _has_any(lowered, ("不要改", "不要修改", "不用改", "只分析", "read only", "readonly")):
        forbidden.append("modify_workspace")
    if _has_any(lowered, ("不要联网", "不用搜索", "不要搜索")):
        forbidden.append("network_lookup")
    if _has_any(lowered, ("不要测试", "不用跑测试")):
        forbidden.append("run_verification")
    return forbidden


def _extract_user_flow(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not _has_any(normalized, ("先", "然后", "再", "最后", "第一", "第二", "第三", "1.", "2.", "3.")):
        return []
    parts = re.split(r"(?:，|,|；|;|\n|然后|再|最后)", normalized)
    flow: list[str] = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        if _has_any(item, ("先", "第一", "1.", "读", "看", "检查", "改", "跑", "验证", "写")):
            flow.append(item[:120])
    return _dedupe(flow)[:8]


def _context_binding(lowered: str, *, query_understanding: dict[str, Any]) -> dict[str, Any]:
    signals = dict(query_understanding.get("structural_signals") or {})
    if _has_any(lowered, ("继续", "接着", "刚才", "上面", "之前", "下一步")):
        return {"kind": "continuation", "source": "deictic_user_message"}
    followup = str(signals.get("followup_target_kind") or "").strip()
    if followup:
        return {"kind": followup, "source": "query_understanding"}
    return {"kind": "current_turn", "source": "user_message"}


def _evidence_requirements(execution_mode: str, domain_hint: str, goal_hint: str) -> list[str]:
    requirements: list[str] = []
    if execution_mode in {"implementation", "agent_execution"}:
        requirements.append("workspace_observation")
        requirements.append("change_evidence")
    if domain_hint == "development" or goal_hint in {"frontend_app_delivery", "game_vertical_slice_delivery", "code_fix_execution"}:
        requirements.append("verification_or_limitation")
    if goal_hint in {"frontend_app_delivery", "game_vertical_slice_delivery"}:
        requirements.append("browser_or_runtime_evidence")
    if execution_mode == "analysis_only":
        requirements.append("source_or_reasoning_boundary")
    return _dedupe(requirements)


def _ambiguity_points(lowered: str, *, interaction_intent: str, action_intent: str) -> list[str]:
    points: list[str] = []
    if _has_any(lowered, ("优化一下", "处理一下", "弄一下", "完善一下")):
        points.append("generic_change_request")
    if interaction_intent == "plan" and action_intent in {"modify", "create"} and _has_any(lowered, ("可以", "要不", "是否")):
        points.append("plan_vs_execute")
    return points


def _playbook_policy(*, domain_hint: str, has_user_flow: bool, forbidden_actions: tuple[str, ...]) -> dict[str, Any]:
    return {
        "domain_playbook_role": "mature_working_conventions",
        "domain_hint": domain_hint,
        "user_flow_priority": "higher_than_domain_playbook" if has_user_flow else "domain_playbook_can_fill_gaps",
        "must_not_override_forbidden_actions": list(forbidden_actions),
        "agent_generates_concrete_steps": True,
    }


def _confidence(*, frame: dict[str, Any], understanding: dict[str, Any], has_user_flow: bool) -> float:
    base = float(understanding.get("confidence") or 0.42)
    if frame.get("task_complexity"):
        base += 0.08
    if has_user_flow:
        base += 0.08
    return min(max(base, 0.0), 0.95)


def _path_markers(text: str) -> list[str]:
    return re.findall(
        r"[\w./\\\-\u4e00-\u9fff @()：:（），,]+?\.(?:md|txt|py|toml|ya?ml|ini|cfg|ts|tsx|js|jsx|css|html|sql|log|json|csv|xlsx|pdf)",
        text,
        flags=re.I,
    )


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "runtime"
