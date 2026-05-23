from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from task_system.goal_profiles import TaskGoalProfile, task_goal_profiles

from .goal_hypothesis import GoalHypothesis, GoalHypothesisSet
from .task_goal_frame import TaskGoalCriterion, TaskGoalDeliverable, TaskGoalFrame
from .task_understanding_frame import TaskUnderstandingFrame, build_task_understanding_frame


@dataclass(frozen=True, slots=True)
class TaskGoalCandidate:
    task_goal_type: str
    task_domain: str
    matched_by: str
    score: float
    profile: TaskGoalProfile | None = None
    signals: tuple[str, ...] = ()
    rejection_reason: str = ""


def build_task_goal_frame(
    message: str,
    *,
    intent_frame: dict[str, Any] | None = None,
    intent_decision: dict[str, Any] | None = None,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
    model_understanding_draft: dict[str, Any] | None = None,
) -> TaskGoalFrame:
    text = str(message or "").strip()
    understanding = dict(query_understanding or {})
    intent = dict(intent_decision or {})
    frame = dict(intent_frame or {})
    current_turn = dict(current_turn_context or {})
    hypothesis_set = build_goal_hypothesis_set(
        text,
        intent_frame=frame,
        intent_decision=intent,
        query_understanding=understanding,
        current_turn_context=current_turn,
    )
    initial_candidate = _candidate_from_hypothesis(hypothesis_set.chosen)
    initial_understanding_frame = build_task_understanding_frame(
        text,
        intent_frame=frame,
        intent_decision=intent,
        query_understanding=understanding,
        task_goal_type_hint=initial_candidate.task_goal_type,
        task_domain_hint=initial_candidate.task_domain,
        goal_hint_source=initial_candidate.matched_by,
        domain_hint_source=initial_candidate.matched_by,
        model_understanding_draft=model_understanding_draft,
    )
    candidate = _candidate_from_understanding_frame(
        task_understanding_frame=initial_understanding_frame,
        fallback=initial_candidate,
        current_turn_context=current_turn,
    )
    task_understanding_frame = initial_understanding_frame
    if candidate.task_goal_type != initial_candidate.task_goal_type or candidate.task_domain != initial_candidate.task_domain:
        hypothesis_set = _hypothesis_set_with_selected_candidate(
            text=text,
            candidate=candidate,
            previous=hypothesis_set,
        )
        task_understanding_frame = build_task_understanding_frame(
            text,
            intent_frame=frame,
            intent_decision=intent,
            query_understanding=understanding,
            task_goal_type_hint=candidate.task_goal_type,
            task_domain_hint=candidate.task_domain,
            goal_hint_source=candidate.matched_by,
            domain_hint_source=candidate.matched_by,
            model_understanding_draft=model_understanding_draft,
        )
    profile = candidate.profile
    if profile is None:
        return _fallback_goal_frame(
            text,
            candidate=candidate,
            hypothesis_set=hypothesis_set,
            task_understanding_frame=task_understanding_frame,
            intent_frame=frame,
            intent_decision=intent,
            query_understanding=understanding,
        )
    return _profile_goal_frame(
        text,
        candidate=candidate,
        profile=profile,
        hypothesis_set=hypothesis_set,
        task_understanding_frame=task_understanding_frame,
        intent_frame=frame,
        intent_decision=intent,
        query_understanding=understanding,
    )


def build_goal_hypothesis_set(
    message: str,
    *,
    intent_frame: dict[str, Any] | None = None,
    intent_decision: dict[str, Any] | None = None,
    query_understanding: dict[str, Any] | None = None,
    current_turn_context: dict[str, Any] | None = None,
) -> GoalHypothesisSet:
    text = str(message or "").strip()
    frame = dict(intent_frame or {})
    intent = dict(intent_decision or {})
    understanding = dict(query_understanding or {})
    current_turn = dict(current_turn_context or {})
    explicit = _explicit_goal_candidate(current_turn)
    if explicit is not None:
        candidates = _goal_candidates(
            text,
            intent_frame=frame,
            intent_decision=intent,
            query_understanding=understanding,
        )
        if not any(item.task_goal_type == explicit.task_goal_type for item in candidates):
            candidates.append(explicit)
        return _hypothesis_set_from_candidate(
            text=text,
            selected=explicit,
            candidates=candidates,
            source="explicit_task_goal_type",
        )
    selected = _select_goal_candidate(
        text,
        intent_frame=frame,
        intent_decision=intent,
        query_understanding=understanding,
    )
    candidates = _goal_candidates(
        text,
        intent_frame=frame,
        intent_decision=intent,
        query_understanding=understanding,
    )
    if not candidates:
        candidates = [selected]
    rejected = _rejected_candidates(
        chosen=selected,
        candidates=candidates,
        lowered=text.lower(),
    )
    return GoalHypothesisSet(
        hypothesis_set_id=f"goalhyp:{_slug(text)[:48] or 'runtime'}",
        user_goal=text,
        chosen=_hypothesis_from_candidate(selected),
        candidates=tuple(_hypothesis_from_candidate(item) for item in candidates),
        rejected=tuple(rejected),
        ambiguity_points=tuple(_ambiguity_points(chosen=selected, candidates=candidates)),
        clarification_needed=False,
        clarification_question="",
    )


def _goal_candidates(
    text: str,
    *,
    intent_frame: dict[str, Any],
    intent_decision: dict[str, Any],
    query_understanding: dict[str, Any],
) -> list[TaskGoalCandidate]:
    lowered = text.lower()
    candidates = sorted(
        [
            candidate
            for candidate in (
                _candidate_from_profile(
                    profile,
                    lowered=lowered,
                    intent_frame=intent_frame,
                    intent_decision=intent_decision,
                    query_understanding=query_understanding,
                )
                for profile in task_goal_profiles()
            )
            if candidate is not None
        ],
        key=lambda item: item.score,
        reverse=True,
    )
    artifact_candidate = _artifact_candidate_from_output_path(
        lowered=lowered,
        query_understanding=query_understanding,
    )
    if artifact_candidate is not None and not any(item.task_goal_type == "artifact_delivery" for item in candidates):
        candidates.append(artifact_candidate)
    return candidates


def _select_goal_candidate(
    text: str,
    *,
    intent_frame: dict[str, Any],
    intent_decision: dict[str, Any],
    query_understanding: dict[str, Any],
) -> TaskGoalCandidate:
    candidates = [
        candidate
        for candidate in _goal_candidates(
            text,
            intent_frame=intent_frame,
            intent_decision=intent_decision,
            query_understanding=query_understanding,
        )
        if not candidate.rejection_reason
    ]
    if candidates:
        return max(candidates, key=lambda item: item.score)
    legacy_type = _semantic_type_from_legacy(query_understanding)
    return TaskGoalCandidate(
        task_goal_type=legacy_type,
        task_domain=str(query_understanding.get("source_kind") or intent_decision.get("target_domain_hint") or "general"),
        matched_by="legacy_fallback",
        score=float(query_understanding.get("confidence") or 0.42),
        profile=None,
        signals=("legacy_fallback",),
    )


def _candidate_from_profile(
    profile: TaskGoalProfile,
    *,
    lowered: str,
    intent_frame: dict[str, Any],
    intent_decision: dict[str, Any],
    query_understanding: dict[str, Any],
) -> TaskGoalCandidate | None:
    signals: list[str] = []
    score = 0.0
    for marker in profile.match_markers:
        token = str(marker or "").lower().strip()
        if token and token in lowered:
            signals.append(f"marker:{marker}")
            score += 0.18
    if _profile_delivery_shape_matches(profile, lowered):
        signals.append("delivery_shape")
        score += 0.34
    if _profile_route_matches(profile, query_understanding):
        signals.append("legacy_route")
        score += 0.16
    target_domain = str(
        intent_decision.get("target_domain_hint")
        or intent_decision.get("target_domain")
        or intent_frame.get("target_domain_hint")
        or ""
    ).strip()
    if target_domain and target_domain in {profile.task_domain, profile.task_goal_type}:
        signals.append("intent_domain")
        score += 0.22
    if profile.task_goal_type in {"game_vertical_slice_delivery", "frontend_app_delivery"} and _analysis_only(lowered):
        score -= 0.32
        signals.append("analysis_only_penalty")
    threshold = 0.32 if profile.task_goal_type in {"game_vertical_slice_delivery", "frontend_app_delivery"} else 0.36
    if score < threshold:
        return None
    return TaskGoalCandidate(
        task_goal_type=profile.task_goal_type,
        task_domain=profile.task_domain,
        matched_by="domain_profile",
        score=min(score, 0.94),
        profile=profile,
        signals=tuple(signals),
    )


def _artifact_candidate_from_output_path(
    *,
    lowered: str,
    query_understanding: dict[str, Any],
) -> TaskGoalCandidate | None:
    task_kind = str(query_understanding.get("task_kind") or "").strip()
    has_output_path = _has_any(lowered, (".md", ".json", ".txt", "写入", "最终报告", "报告写入", "输出到"))
    if task_kind != "workspace_file_write" and not has_output_path:
        return None
    return TaskGoalCandidate(
        task_goal_type="artifact_delivery",
        task_domain="general",
        matched_by="legacy_or_output_path",
        score=0.28 if task_kind != "workspace_file_write" else 0.48,
        profile=next((profile for profile in task_goal_profiles() if profile.task_goal_type == "artifact_delivery"), None),
        signals=("legacy_workspace_file_write" if task_kind == "workspace_file_write" else "output_path_or_report",),
    )


def _profile_delivery_shape_matches(profile: TaskGoalProfile, lowered: str) -> bool:
    if profile.task_goal_type == "game_vertical_slice_delivery":
        return (
            _has_any(lowered, ("游戏", "肉鸽", "roguelike", "rougelike", "2d", "boss", "敌人", "玩家", "玩法", "hud"))
            and _has_any(lowered, ("开发", "实现", "可运行", "垂直切片", "原型", "启动", "验证"))
            and (_has_any(lowered, ("浏览器", "前端", "canvas", "网页", "web")) or "2d" in lowered)
        )
    if profile.task_goal_type == "frontend_app_delivery":
        return (
            _has_any(lowered, ("前端", "ui", "页面", "编辑器", "工作画布", "应用", "app", "dashboard"))
            and _has_any(lowered, ("重构", "开发", "实现", "可运行", "启动", "验证", "做成", "调整"))
            and not _analysis_only(lowered)
        )
    if profile.task_goal_type == "test_report_triage":
        return _has_any(lowered, ("失败", "fail", "failing", "测试报告", "长跑", "long_runner", "triage")) and _has_any(
            lowered,
            ("根因", "root cause", "结构性", "回归", "regression", "分析"),
        )
    if profile.task_goal_type == "runtime_trace_analysis":
        return _has_any(lowered, ("runtime trace", "运行追踪", "checkpoint", "事件链", "trace"))
    if profile.task_goal_type == "code_fix_execution":
        if _looks_like_product_delivery(lowered) and not _looks_like_bug_repair(lowered):
            return False
        return _has_any(lowered, ("修复", "修改代码", "改代码", "fix", "patch", "bug")) and not _has_any(
            lowered,
            ("修复建议", "只分析", "不要改", "不要修改", "read only", "readonly"),
        )
    if profile.task_goal_type == "regression_test_design":
        return _has_any(lowered, ("回归测试", "测试设计", "补测试", "regression test"))
    if profile.task_goal_type == "material_synthesis":
        return _has_any(lowered, ("综合", "总结", "分析这些", "材料"))
    return False


def _profile_route_matches(profile: TaskGoalProfile, query_understanding: dict[str, Any]) -> bool:
    task_kind = str(query_understanding.get("task_kind") or "").strip()
    route = str(query_understanding.get("route") or query_understanding.get("route_hint") or "").strip()
    if profile.task_goal_type == "artifact_delivery":
        return task_kind == "workspace_file_write"
    if profile.task_goal_type == "material_synthesis":
        return task_kind in {"document_read", "dataset_query"} and route in {"pdf", "structured_data"}
    return False


def _profile_goal_frame(
    text: str,
    *,
    candidate: TaskGoalCandidate,
    profile: TaskGoalProfile,
    hypothesis_set: GoalHypothesisSet,
    task_understanding_frame: TaskUnderstandingFrame,
    intent_frame: dict[str, Any],
    intent_decision: dict[str, Any],
    query_understanding: dict[str, Any],
) -> TaskGoalFrame:
    detail = _profile_detail(profile.task_goal_type)
    core = tuple(detail.get("core_deliverables") or _deliverables(profile.default_core_deliverables, role="core"))
    supporting = tuple(detail.get("supporting_deliverables") or _deliverables(profile.default_supporting_deliverables, role="supporting", required=False))
    success = tuple(detail.get("success_criteria") or _criteria(profile.default_success_criteria, verification_kind="acceptance"))
    verifications = tuple(detail.get("required_verifications") or _criteria(profile.default_verifications, verification_kind="evidence"))
    forbidden = tuple(_dedupe([*profile.forbidden_actions, *detail.get("forbidden_actions", ())]))
    return TaskGoalFrame(
        user_goal=text,
        goal_summary=str(detail.get("goal_summary") or profile.description or text[:180]),
        task_goal_type=profile.task_goal_type,
        task_domain=profile.task_domain,
        task_understanding_frame_ref=task_understanding_frame.frame_id,
        task_understanding_frame=task_understanding_frame.to_dict(),
        goal_hypothesis_set_ref=hypothesis_set.hypothesis_set_id,
        complexity=str(detail.get("complexity") or _complexity_for_profile(profile)),
        core_deliverables=core,
        supporting_deliverables=supporting,
        success_criteria=success,
        required_capabilities=tuple(profile.required_capabilities),
        required_verifications=verifications,
        explicit_constraints=tuple(_extract_constraints(text)),
        forbidden_actions=forbidden,
        rejected_goal_candidates=tuple(item.to_dict() for item in hypothesis_set.rejected),
        unacceptable_outcomes=tuple(detail.get("unacceptable_outcomes") or _unacceptable_outcomes_for_profile(profile.task_goal_type)),
        ambiguity_points=tuple(hypothesis_set.ambiguity_points),
        clarification_policy={
            "clarification_needed": hypothesis_set.clarification_needed,
            "question": hypothesis_set.clarification_question,
        },
        stage_prompt_profiles=tuple(detail.get("stage_prompt_profiles") or ()),
        evidence=_evidence(
            intent_frame=intent_frame,
            intent_decision=intent_decision,
            query_understanding=query_understanding,
            goal_signals=[candidate.matched_by, *candidate.signals],
            goal_hypothesis_set=hypothesis_set,
            task_understanding_frame=task_understanding_frame,
        ),
        confidence=candidate.score,
    )


def _profile_detail(task_goal_type: str) -> dict[str, Any]:
    if task_goal_type == "game_vertical_slice_delivery":
        return {
            "goal_summary": "开发一个可运行、可验证、可迭代的浏览器端游戏垂直切片。",
            "complexity": "long_running",
            "core_deliverables": (
                _deliverable("runnable_game", "可运行游戏入口", "application"),
                _deliverable("source_files", "游戏源码", "source_code"),
                _deliverable("visual_asset", "至少一个真实接入的视觉资源", "asset"),
                _deliverable("gameplay_features", "核心玩法功能", "feature_set"),
            ),
            "supporting_deliverables": (
                _deliverable("stage_docs", "阶段文档", "document", role="supporting", required=False),
                _deliverable("final_report", "最终报告", "document", role="supporting", required=False),
            ),
            "success_criteria": (
                _criterion("movement", "玩家可移动", "gameplay_acceptance"),
                _criterion("combat", "玩家攻击和敌人反馈存在", "gameplay_acceptance"),
                _criterion("progression", "存在波次、房间、经验、奖励或升级推进", "gameplay_acceptance"),
                _criterion("terminal_state", "存在死亡或胜利状态", "gameplay_acceptance"),
                _criterion("hud", "HUD 可见", "visual_acceptance"),
            ),
            "required_verifications": (
                _criterion("dev_server_or_static_open", "项目可启动或静态入口可打开", "runtime_verification"),
                _criterion("browser_open", "浏览器真实打开游戏入口", "browser_verification"),
                _criterion("visual_nonblank", "游戏画布或界面非空", "visual_verification"),
                _criterion("asset_visible", "至少一个图片资源真实显示", "asset_verification"),
                _criterion("gameplay_acceptance", "关键玩法 checklist 被验证", "gameplay_acceptance"),
            ),
            "unacceptable_outcomes": (
                "final_report_only",
                "design_doc_only",
                "unverified_game_claim",
                "asset_claim_without_visible_asset",
            ),
            "stage_prompt_profiles": (
                _stage_prompt("task_goal_understanding", "你只负责判断用户真正要完成的游戏产品目标、核心产物和验收标准，不负责写代码。"),
                _stage_prompt("execution_planning", "你是一名游戏原型开发负责人。你需要把目标拆成可执行阶段，并确保每个阶段有真实产物或观察。"),
                _stage_prompt("verification", "你是一名游戏验收员。你只根据真实运行、浏览器观察和产物证据判断是否通过。"),
            ),
        }
    if task_goal_type == "frontend_app_delivery":
        return {
            "goal_summary": "交付一个可运行、可验证的前端应用或编辑器体验。",
            "complexity": "long_running",
            "core_deliverables": (
                _deliverable("runnable_frontend", "可运行前端入口", "application"),
                _deliverable("source_changes", "前端源码变更", "source_code"),
                _deliverable("user_workflow", "核心用户工作流", "feature_set"),
            ),
            "supporting_deliverables": (
                _deliverable("implementation_notes", "实现说明", "document", role="supporting", required=False),
            ),
            "success_criteria": (
                _criterion("layout_usable", "主要界面结构可用", "visual_acceptance"),
                _criterion("workflow_complete", "核心工作流可完成", "workflow_acceptance"),
            ),
            "required_verifications": (
                _criterion("dev_server_or_build", "项目可启动或构建", "runtime_verification"),
                _criterion("browser_check", "浏览器打开并检查关键界面", "browser_verification"),
            ),
            "unacceptable_outcomes": (
                "surface_only_ui_claim",
                "unverified_frontend_claim",
                "workflow_claim_without_observation",
            ),
            "stage_prompt_profiles": (
                _stage_prompt("task_goal_understanding", "你只负责判断用户要交付的前端产品目标、核心工作流和验收标准。"),
                _stage_prompt("verification", "你只根据真实浏览器观察和运行证据判断前端交付是否通过。"),
            ),
        }
    return {}


def _fallback_goal_frame(
    text: str,
    *,
    candidate: TaskGoalCandidate,
    hypothesis_set: GoalHypothesisSet,
    task_understanding_frame: TaskUnderstandingFrame,
    intent_frame: dict[str, Any],
    intent_decision: dict[str, Any],
    query_understanding: dict[str, Any],
) -> TaskGoalFrame:
    return TaskGoalFrame(
        user_goal=text,
        goal_summary=text[:180],
        task_goal_type=candidate.task_goal_type,
        task_domain=candidate.task_domain,
        task_understanding_frame_ref=task_understanding_frame.frame_id,
        task_understanding_frame=task_understanding_frame.to_dict(),
        goal_hypothesis_set_ref=hypothesis_set.hypothesis_set_id,
        complexity=str(intent_frame.get("task_complexity") or "short"),
        core_deliverables=tuple(_fallback_deliverables(candidate.task_goal_type)),
        required_capabilities=tuple(str(item) for item in list(query_understanding.get("capability_requests") or []) if str(item).strip()),
        rejected_goal_candidates=tuple(item.to_dict() for item in hypothesis_set.rejected),
        unacceptable_outcomes=tuple(_unacceptable_outcomes_for_profile(candidate.task_goal_type)),
        ambiguity_points=tuple(hypothesis_set.ambiguity_points),
        clarification_policy={
            "clarification_needed": hypothesis_set.clarification_needed,
            "question": hypothesis_set.clarification_question,
        },
        evidence=_evidence(
            intent_frame=intent_frame,
            intent_decision=intent_decision,
            query_understanding=query_understanding,
            goal_signals=list(candidate.signals),
            goal_hypothesis_set=hypothesis_set,
            task_understanding_frame=task_understanding_frame,
        ),
        confidence=candidate.score,
    )


def _semantic_type_from_legacy(query_understanding: dict[str, Any]) -> str:
    task_kind = str(query_understanding.get("task_kind") or "").strip()
    route = str(query_understanding.get("route") or query_understanding.get("route_hint") or "").strip()
    if task_kind == "workspace_file_write":
        return "artifact_delivery"
    if task_kind in {"workspace_file_read", "workspace_file_search"} or route.startswith("workspace_"):
        return "bounded_tool_task"
    if task_kind in {"document_page", "document_section", "document_read", "dataset_query"}:
        return "bounded_tool_task"
    if route in {"realtime_network", "search"}:
        return "light_qa"
    return "light_qa"


def _fallback_deliverables(task_goal_type: str) -> list[TaskGoalDeliverable]:
    if task_goal_type == "artifact_delivery":
        return [_deliverable("artifact", "用户要求的文件或产物", "artifact")]
    if task_goal_type == "bounded_tool_task":
        return [_deliverable("tool_grounded_answer", "基于工具结果的回答", "answer")]
    return [_deliverable("final_answer", "最终回答", "answer")]


def _extract_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for marker in ("必须", "不能", "不要", "需要", "至少", "真实"):
        if marker in text:
            constraints.append(marker)
    paths = re.findall(r"[\w./\\\-\u4e00-\u9fff]+?\.(?:md|html|css|js|jsx|ts|tsx|png|jpg|jpeg|webp)", text, flags=re.I)
    constraints.extend(f"path:{path}" for path in paths)
    return _dedupe(constraints)


def _deliverables(values: tuple[str, ...], *, role: str, required: bool = True) -> tuple[TaskGoalDeliverable, ...]:
    return tuple(_deliverable(_slug(value), value, "artifact", role=role, required=required) for value in values if str(value).strip())


def _criteria(values: tuple[str, ...], *, verification_kind: str) -> tuple[TaskGoalCriterion, ...]:
    return tuple(_criterion(_slug(value), value, verification_kind) for value in values if str(value).strip())


def _deliverable(
    deliverable_id: str,
    title: str,
    kind: str,
    *,
    role: str = "core",
    required: bool = True,
) -> TaskGoalDeliverable:
    return TaskGoalDeliverable(
        deliverable_id=deliverable_id,
        title=title,
        kind=kind,
        role=role,
        required=required,
    )


def _criterion(criterion_id: str, title: str, verification_kind: str) -> TaskGoalCriterion:
    return TaskGoalCriterion(
        criterion_id=criterion_id,
        title=title,
        verification_kind=verification_kind,
    )


def _stage_prompt(stage_id: str, prompt: str) -> dict[str, Any]:
    return {"stage_id": stage_id, "prompt": prompt}


def _evidence(
    *,
    intent_frame: dict[str, Any],
    intent_decision: dict[str, Any],
    query_understanding: dict[str, Any],
    goal_signals: list[str],
    goal_hypothesis_set: GoalHypothesisSet | None = None,
    task_understanding_frame: TaskUnderstandingFrame | None = None,
) -> dict[str, Any]:
    return {
        "goal_signals": list(goal_signals),
        "goal_hypothesis_set": goal_hypothesis_set.to_dict() if goal_hypothesis_set is not None else {},
        "task_understanding_frame": task_understanding_frame.to_dict() if task_understanding_frame is not None else {},
        "intent_frame": dict(intent_frame or {}),
        "intent_decision": dict(intent_decision or {}),
        "legacy_task_understanding": {
            "task_kind": str(query_understanding.get("task_kind") or ""),
            "route": str(query_understanding.get("route") or query_understanding.get("route_hint") or ""),
            "source_kind": str(query_understanding.get("source_kind") or ""),
            "direct_route_reason": str(query_understanding.get("direct_route_reason") or ""),
            "structural_signals": dict(query_understanding.get("structural_signals") or {}),
        },
    }


def _hypothesis_from_candidate(candidate: TaskGoalCandidate) -> GoalHypothesis:
    return GoalHypothesis(
        task_goal_type=candidate.task_goal_type,
        task_domain=candidate.task_domain,
        confidence=candidate.score,
        matched_by=tuple(item for item in (candidate.matched_by, *candidate.signals) if item),
        supporting_evidence=tuple(candidate.signals),
        rejection_reason=candidate.rejection_reason,
        risks=tuple(_candidate_risks(candidate)),
    )


def _candidate_from_hypothesis(hypothesis: GoalHypothesis) -> TaskGoalCandidate:
    profile = next((item for item in task_goal_profiles() if item.task_goal_type == hypothesis.task_goal_type), None)
    return TaskGoalCandidate(
        task_goal_type=hypothesis.task_goal_type,
        task_domain=hypothesis.task_domain,
        matched_by=next(iter(hypothesis.matched_by), "hypothesis_set"),
        score=hypothesis.confidence,
        profile=profile,
        signals=tuple(hypothesis.supporting_evidence),
        rejection_reason=hypothesis.rejection_reason,
    )


def _explicit_goal_candidate(current_turn_context: dict[str, Any]) -> TaskGoalCandidate | None:
    goal_type = str(
        current_turn_context.get("semantic_task_type")
        or current_turn_context.get("task_goal_type")
        or dict(current_turn_context.get("semantic_task_contract") or {}).get("task_goal_type")
        or ""
    ).strip()
    if not goal_type:
        return None
    profile = next((item for item in task_goal_profiles() if item.task_goal_type == goal_type), None)
    return TaskGoalCandidate(
        task_goal_type=goal_type,
        task_domain=str(getattr(profile, "task_domain", "") or current_turn_context.get("task_domain") or "general"),
        matched_by="explicit_task_goal_type",
        score=0.99,
        profile=profile,
        signals=("explicit_task_selection",),
    )


def _candidate_from_understanding_frame(
    *,
    task_understanding_frame: TaskUnderstandingFrame,
    fallback: TaskGoalCandidate,
    current_turn_context: dict[str, Any],
) -> TaskGoalCandidate:
    explicit = _explicit_goal_candidate(current_turn_context)
    if explicit is not None:
        return explicit
    arbitration = dict(task_understanding_frame.understanding_arbitration or {})
    diagnostics = dict(arbitration.get("diagnostics") or {})
    if str(diagnostics.get("model_draft_status") or "") != "accepted":
        return fallback
    goal_type = str(task_understanding_frame.task_goal_type_hint or "").strip()
    if not goal_type or goal_type == fallback.task_goal_type:
        return fallback
    profile = next((item for item in task_goal_profiles() if item.task_goal_type == goal_type), None)
    if profile is None and not _known_fallback_goal_type(goal_type):
        return fallback
    domain = str(task_understanding_frame.task_domain_hint or getattr(profile, "task_domain", "") or fallback.task_domain or "general").strip()
    return TaskGoalCandidate(
        task_goal_type=goal_type,
        task_domain=domain,
        matched_by="model_understanding_draft",
        score=max(float(fallback.score or 0.0), float(diagnostics.get("model_draft_confidence") or 0.0), 0.62),
        profile=profile,
        signals=("model_goal_type_hint",),
    )


def _known_fallback_goal_type(goal_type: str) -> bool:
    return goal_type in {
        "bounded_tool_task",
        "light_qa",
        "role_conversation",
        "task_graph_node_execution",
    }


def _hypothesis_set_from_candidate(
    *,
    text: str,
    selected: TaskGoalCandidate,
    candidates: list[TaskGoalCandidate],
    source: str,
) -> GoalHypothesisSet:
    if not any(item.task_goal_type == selected.task_goal_type for item in candidates):
        candidates = [selected, *candidates]
    rejected = _rejected_candidates(
        chosen=selected,
        candidates=candidates,
        lowered=text.lower(),
    )
    ambiguity = _ambiguity_points(chosen=selected, candidates=candidates)
    if source == "model_understanding_draft":
        ambiguity = [item for item in ambiguity if not item.startswith("close_goal_candidate:")]
    return GoalHypothesisSet(
        hypothesis_set_id=f"goalhyp:{_slug(text)[:48] or 'runtime'}",
        user_goal=text,
        chosen=_hypothesis_from_candidate(selected),
        candidates=tuple(_hypothesis_from_candidate(item) for item in candidates),
        rejected=tuple(rejected),
        ambiguity_points=tuple(ambiguity),
        clarification_needed=False,
        clarification_question="",
    )


def _hypothesis_set_with_selected_candidate(
    *,
    text: str,
    candidate: TaskGoalCandidate,
    previous: GoalHypothesisSet,
) -> GoalHypothesisSet:
    candidates = [_candidate_from_hypothesis(item) for item in previous.candidates]
    return _hypothesis_set_from_candidate(
        text=text,
        selected=candidate,
        candidates=candidates,
        source=candidate.matched_by,
    )


def _rejected_candidates(
    *,
    chosen: TaskGoalCandidate,
    candidates: list[TaskGoalCandidate],
    lowered: str,
) -> list[GoalHypothesis]:
    rejected: list[GoalHypothesis] = []
    for candidate in candidates:
        if candidate.task_goal_type == chosen.task_goal_type:
            continue
        reason = candidate.rejection_reason or _rejection_reason(chosen=chosen, candidate=candidate, lowered=lowered)
        rejected.append(
            GoalHypothesis(
                task_goal_type=candidate.task_goal_type,
                task_domain=candidate.task_domain,
                confidence=candidate.score,
                matched_by=tuple(item for item in (candidate.matched_by, *candidate.signals) if item),
                supporting_evidence=tuple(candidate.signals),
                rejection_reason=reason,
                risks=tuple(_candidate_risks(candidate)),
            )
        )
    return rejected


def _rejection_reason(*, chosen: TaskGoalCandidate, candidate: TaskGoalCandidate, lowered: str) -> str:
    if candidate.task_goal_type == "artifact_delivery" and chosen.task_goal_type in {"game_vertical_slice_delivery", "frontend_app_delivery"}:
        if _has_any(lowered, ("最终报告", "final_report", ".md", "报告")):
            return "用户提到的报告或路径是辅助产物，核心目标是可运行产品交付。"
        return "文件交付信号弱于产品开发目标。"
    if chosen.score > candidate.score:
        return "chosen_candidate_has_stronger_goal_evidence"
    return "candidate_not_selected"


def _candidate_risks(candidate: TaskGoalCandidate) -> list[str]:
    if candidate.task_goal_type == "artifact_delivery":
        return ["may_capture_supporting_report_instead_of_core_goal"]
    if candidate.task_goal_type in {"game_vertical_slice_delivery", "frontend_app_delivery"}:
        return ["requires_real_workspace_change_and_runtime_verification"]
    return []


def _ambiguity_points(*, chosen: TaskGoalCandidate, candidates: list[TaskGoalCandidate]) -> list[str]:
    points: list[str] = []
    runner_up = next((item for item in candidates if item.task_goal_type != chosen.task_goal_type), None)
    if runner_up is not None and chosen.score - runner_up.score < 0.12:
        points.append(f"close_goal_candidate:{runner_up.task_goal_type}")
    return points


def _unacceptable_outcomes_for_profile(task_goal_type: str) -> list[str]:
    if task_goal_type == "game_vertical_slice_delivery":
        return ["final_report_only", "design_doc_only", "unverified_game_claim", "asset_claim_without_visible_asset"]
    if task_goal_type == "frontend_app_delivery":
        return ["surface_only_ui_claim", "unverified_frontend_claim", "workflow_claim_without_observation"]
    if task_goal_type == "code_fix_execution":
        return ["claim_unrun_tests_as_passed", "surface_only_summary"]
    if task_goal_type == "artifact_delivery":
        return ["claim_artifact_written_without_write_evidence"]
    return ["invent_evidence"]


def _complexity_for_profile(profile: TaskGoalProfile) -> str:
    if profile.task_goal_type in {"game_vertical_slice_delivery", "frontend_app_delivery", "code_fix_execution"}:
        return "long_running"
    if profile.professional_profile_id:
        return "professional"
    return "short"


def _analysis_only(lowered: str) -> bool:
    if _looks_like_product_delivery(lowered):
        return _has_any(lowered, ("先看", "先分析", "只分析", "不要急着修", "不要改", "不要修改"))
    return _has_any(lowered, ("先看", "先分析", "排查", "为什么", "不要急着修", "只分析"))


def _looks_like_product_delivery(lowered: str) -> bool:
    return (
        (
            _has_any(lowered, ("游戏", "肉鸽", "roguelike", "垂直切片", "浏览器游戏"))
            and _has_any(lowered, ("开发", "实现", "可运行", "启动", "验证", "交付", "mvp"))
        )
        or (
            _has_any(lowered, ("前端", "ui", "页面", "编辑器", "应用", "app", "dashboard"))
            and _has_any(lowered, ("重构", "开发", "实现", "可运行", "启动", "验证", "交付", "做成"))
        )
    )


def _looks_like_bug_repair(lowered: str) -> bool:
    return _has_any(lowered, ("bug", "报错", "错误", "异常", "失败", "failing", "traceback", "修复这个问题", "修复它"))


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in str(value or "").lower()).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "item"


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
