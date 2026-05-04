from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout
from .workflow_models import TaskWorkflowBinding


def default_task_workflows() -> tuple[TaskWorkflowBinding, ...]:
    return (
        TaskWorkflowBinding(
            workflow_id="workflow.general.main_conversation",
            title="主会话通用工作流",
            task_mode="general_task",
            compatible_projection_ids=(),
            visible_skill_ids=(),
            steps=(
                {"step_id": "understand_request", "title": "理解当前请求"},
                {"step_id": "decide_route", "title": "判断是否直接回答或分流"},
                {"step_id": "finalize_response", "title": "输出主会话结果"},
            ),
            input_boundary="User dialogue, active conversation context, explicit task refs when present.",
            output_boundary="AssistantFinalAnswer or explicit handoff into a registered specific task.",
            stop_conditions=("answer_ready", "specific_task_selected"),
            required_evidence_refs=(),
            output_contract_id="AssistantFinalAnswer",
            prompt=(
                "主会话默认承接通用任务。"
                "只有在用户目标明显命中特定任务资源时，才切换到对应特定任务链路。"
            ),
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "general_conversation"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.dev.bounded_patch",
            title="受限补丁工作流",
            task_mode="bounded_patch",
            compatible_projection_ids=(),
            visible_skill_ids=("skill.implementation", "skill.review"),
            steps=(
                {"step_id": "scope_patch_area", "title": "锁定补丁范围与目标文件"},
                {"step_id": "inspect_related_code", "title": "阅读相关代码与依赖关系"},
                {"step_id": "apply_scoped_patch", "title": "在受限目录内实施补丁"},
                {"step_id": "verify_changed_behavior", "title": "验证变更结果与残余风险"},
                {"step_id": "finalize_patch_report", "title": "汇报修改内容与验证状态"},
            ),
            input_boundary="Patch goal, explicit target root, optional file refs, acceptance checks.",
            output_boundary="Scoped code changes, touched file refs, verification result, known limitations.",
            stop_conditions=("patch_applied", "verification_reported"),
            required_evidence_refs=("target_root", "changed_files"),
            output_contract_id="AssistantFinalAnswer",
            prompt=(
                "这是受限补丁任务。"
                "先界定补丁边界，再修改；"
                "不得越出任务写入目录，不得碰受禁路径；"
                "最终必须说明改了什么、验证了什么、还剩什么风险。"
            ),
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "bounded_patch"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.dev.light_web_game",
            title="轻量网页小游戏工作流",
            task_mode="light_web_game",
            compatible_projection_ids=(),
            visible_skill_ids=("skill.implementation", "skill.review"),
            steps=(
                {"step_id": "clarify_game_goal", "title": "收束玩法目标与交互边界"},
                {"step_id": "inspect_workspace", "title": "检查工作区与落点文件"},
                {"step_id": "design_runtime_shape", "title": "定义状态、循环与渲染结构"},
                {"step_id": "build_game_artifact", "title": "实现游戏文件与交互逻辑"},
                {"step_id": "verify_playability", "title": "验证可启动、可操作、可结束"},
                {"step_id": "finalize_report", "title": "输出真实结果与限制"},
            ),
            input_boundary="Game goal, explicit workspace target, optional style hints, optional asset refs.",
            output_boundary="Playable web game artifact refs plus validation state and known limitations.",
            stop_conditions=("game_artifact_created", "playability_checked", "result_reported"),
            required_evidence_refs=("workspace_path", "artifact_refs"),
            output_contract_id="LightWebGameResult",
            prompt=(
                "优先做轻量、可运行、可验证的网页小游戏。"
                "先收束玩法，再决定结构；不要堆砌无关特效；"
                "如果无法完成完整验证，必须明确说明未验证部分。"
            ),
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "light_web_game"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.dev.arcade_game_bundle",
            title="复合网页小游戏包工作流",
            task_mode="arcade_game_bundle",
            compatible_projection_ids=(),
            visible_skill_ids=("skill.implementation", "skill.review"),
            steps=(
                {"step_id": "scope_target_root", "title": "锁定目标目录与入口形式"},
                {"step_id": "inspect_existing_files", "title": "检查现有文件与可复用资源"},
                {"step_id": "design_bundle_structure", "title": "设计 HTML/CSS/JS 结构"},
                {"step_id": "implement_bundle_files", "title": "生成多文件游戏产物"},
                {"step_id": "verify_entry_relations", "title": "验证入口与资源关系"},
                {"step_id": "finalize_delivery", "title": "输出产物路径与已知限制"},
            ),
            input_boundary="Game goal, target root, optional asset hints, optional UI constraints.",
            output_boundary="Multi-file playable web game artifact refs with entry file and validation state.",
            stop_conditions=("bundle_artifacts_created", "entry_verified", "result_reported"),
            required_evidence_refs=("target_root", "artifact_refs", "entry_file"),
            output_contract_id="LightWebGameResult",
            prompt=(
                "优先用多文件但边界清晰的结构完成网页小游戏。"
                "文件数量只服务于清晰性，不为了复杂而复杂；"
                "必须明确入口文件、资源关系与未验证部分。"
            ),
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "arcade_game_bundle"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.issue_triage",
            title="健康问题分诊工作流",
            task_mode="issue_triage",
            compatible_projection_ids=("xuannv__primary",),
            visible_skill_ids=("skill.health.issue_triage", "skill.health.trace_reading"),
            steps=(
                {"step_id": "collect_refs", "title": "收集问题证据引用"},
                {"step_id": "classify_owner", "title": "判断归属系统"},
                {"step_id": "summarize_triage", "title": "输出分诊结果"},
            ),
            input_boundary="HealthIssue + explicit trace refs only.",
            output_boundary="HealthTriageResult candidate.",
            stop_conditions=("owner_system_identified", "needs_evidence_marked"),
            required_evidence_refs=("conversation_ref", "runtime_trace_refs"),
            output_contract_id="HealthTriageResult",
            enabled=True,
            metadata={"managed_by": "task_system"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.trace_analysis",
            title="健康链路分析工作流",
            task_mode="trace_analysis",
            compatible_projection_ids=("xuannv__primary",),
            visible_skill_ids=("skill.health.trace_reading", "skill.health.root_cause_analysis"),
            steps=(
                {"step_id": "read_runtime_events", "title": "读取运行事件"},
                {"step_id": "locate_problem_node", "title": "定位问题节点"},
                {"step_id": "propose_fix_area", "title": "提出修复范围"},
            ),
            input_boundary="HealthTrace refs, PromptManifest refs, MemoryRuntimeView refs.",
            output_boundary="HealthTraceAnalysis candidate.",
            stop_conditions=("problem_node_identified", "insufficient_trace_marked"),
            required_evidence_refs=("runtime_trace_refs", "prompt_manifest_refs"),
            output_contract_id="HealthTraceAnalysis",
            enabled=True,
            metadata={"managed_by": "task_system"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.case_draft",
            title="健康用例草案工作流",
            task_mode="case_draft",
            compatible_projection_ids=("xuannv__primary",),
            visible_skill_ids=("skill.health.case_draft", "skill.health.assertion_design"),
            steps=(
                {"step_id": "extract_trigger", "title": "提取复现触发条件"},
                {"step_id": "draft_assertions", "title": "设计断言"},
                {"step_id": "emit_case_draft", "title": "输出用例草案"},
            ),
            input_boundary="Triaged HealthIssue only.",
            output_boundary="HealthCaseDraftProposal candidate.",
            stop_conditions=("case_draft_ready",),
            required_evidence_refs=("issue_id",),
            output_contract_id="HealthCaseDraftProposal",
            enabled=True,
            metadata={"managed_by": "task_system"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.fix_verification",
            title="健康修复验证工作流",
            task_mode="fix_verification",
            compatible_projection_ids=("xuannv__primary",),
            visible_skill_ids=("skill.health.fix_verification", "skill.health.trace_reading"),
            steps=(
                {"step_id": "compare_before_after", "title": "比较修复前后链路"},
                {"step_id": "verify_problem_node", "title": "验证问题节点是否消失"},
                {"step_id": "emit_verification", "title": "输出验证建议"},
            ),
            input_boundary="HealthIssue with before/after trace refs.",
            output_boundary="HealthFixVerificationProposal candidate.",
            stop_conditions=("verification_result_ready",),
            required_evidence_refs=("before_trace", "after_trace"),
            output_contract_id="HealthFixVerificationProposal",
            enabled=True,
            metadata={"managed_by": "task_system"},
        ),
    )


def _storage_root(base_dir: Path) -> Path:
    return ProjectLayout.from_backend_dir(base_dir).tasks_dir


def _workflows_path(base_dir: Path) -> Path:
    return _storage_root(base_dir) / "task_workflows.json"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _workflow_from_dict(payload: dict[str, Any]) -> TaskWorkflowBinding:
    compatible_projection_ids = tuple(
        str(item)
        for item in list(
            payload.get("compatible_projection_ids")
            or payload.get("allowed_projection_ids")
            or payload.get("allowed_projection_template_ids")
            or []
        )
        if str(item)
    )
    return TaskWorkflowBinding(
        workflow_id=str(payload.get("workflow_id") or ""),
        title=str(payload.get("title") or ""),
        task_mode=str(payload.get("task_mode") or ""),
        compatible_projection_ids=compatible_projection_ids,
        visible_skill_ids=tuple(str(item) for item in list(payload.get("visible_skill_ids") or []) if str(item)),
        steps=tuple(dict(item) for item in list(payload.get("steps") or []) if isinstance(item, dict)),
        input_boundary=str(payload.get("input_boundary") or ""),
        output_boundary=str(payload.get("output_boundary") or ""),
        stop_conditions=tuple(str(item) for item in list(payload.get("stop_conditions") or []) if str(item)),
        required_evidence_refs=tuple(str(item) for item in list(payload.get("required_evidence_refs") or []) if str(item)),
        output_contract_id=str(payload.get("output_contract_id") or ""),
        prompt=str(payload.get("prompt") or ""),
        enabled=bool(payload.get("enabled", True)),
        metadata=dict(payload.get("metadata") or {}),
    )


class TaskWorkflowRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def list_workflows(self) -> list[TaskWorkflowBinding]:
        payload = _read_json(
            _workflows_path(self.base_dir),
            {"workflows": [item.to_dict() for item in default_task_workflows()]},
        )
        workflows = [_workflow_from_dict(item) for item in list(payload.get("workflows") or []) if isinstance(item, dict)]
        normalized = [item.to_dict() for item in workflows]
        if payload.get("workflows") != normalized:
            _write_json(_workflows_path(self.base_dir), {"workflows": normalized})
        return workflows

    def get_workflow(self, workflow_id: str) -> TaskWorkflowBinding | None:
        target = str(workflow_id or "").strip()
        return next((item for item in self.list_workflows() if item.workflow_id == target), None)

    def upsert_workflow(
        self,
        *,
        workflow_id: str,
        title: str,
        task_mode: str,
        compatible_projection_ids: tuple[str, ...] = (),
        visible_skill_ids: tuple[str, ...] = (),
        steps: tuple[dict[str, Any], ...] = (),
        input_boundary: str = "",
        output_boundary: str = "",
        stop_conditions: tuple[str, ...] = (),
        required_evidence_refs: tuple[str, ...] = (),
        output_contract_id: str = "",
        prompt: str = "",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> TaskWorkflowBinding:
        target = str(workflow_id or "").strip()
        if not target.startswith("workflow."):
            raise ValueError("workflow_id must start with workflow.")
        workflow = TaskWorkflowBinding(
            workflow_id=target,
            title=str(title or target).strip(),
            task_mode=str(task_mode or "").strip(),
            compatible_projection_ids=tuple(str(item).strip() for item in compatible_projection_ids if str(item).strip()),
            visible_skill_ids=tuple(str(item).strip() for item in visible_skill_ids if str(item).strip()),
            steps=tuple(dict(item) for item in steps if isinstance(item, dict)),
            input_boundary=str(input_boundary or "").strip(),
            output_boundary=str(output_boundary or "").strip(),
            stop_conditions=tuple(str(item).strip() for item in stop_conditions if str(item).strip()),
            required_evidence_refs=tuple(str(item).strip() for item in required_evidence_refs if str(item).strip()),
            output_contract_id=str(output_contract_id or "").strip(),
            prompt=str(prompt or ""),
            enabled=bool(enabled),
            metadata=dict(metadata or {}),
        )
        workflows = [item for item in self.list_workflows() if item.workflow_id != target]
        workflows.append(workflow)
        _write_json(_workflows_path(self.base_dir), {"workflows": [item.to_dict() for item in workflows]})
        return workflow

    def build_catalog(self) -> dict[str, object]:
        workflows = self.list_workflows()
        return {
            "authority": "task_system.workflow_registry",
            "workflows": [item.to_dict() for item in workflows],
            "summary": {
                "workflow_count": len(workflows),
                "enabled_workflow_count": sum(1 for item in workflows if item.enabled),
                "health_workflow_count": sum(1 for item in workflows if item.workflow_id.startswith("workflow.health.")),
                "development_workflow_count": sum(1 for item in workflows if item.workflow_id.startswith("workflow.dev.")),
            },
        }
