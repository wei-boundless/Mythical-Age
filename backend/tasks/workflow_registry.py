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
        *_default_health_task_workflows(),
    )


def _default_health_task_workflows() -> tuple[TaskWorkflowBinding, ...]:
    return (
        TaskWorkflowBinding(
            workflow_id="workflow.health.issue_triage",
            title="健康问题分诊工作流",
            task_mode="issue_triage",
            steps=(
                {"step_id": "read_issue", "title": "读取健康问题"},
                {"step_id": "triage_risk", "title": "判断风险与影响"},
                {"step_id": "finalize_triage", "title": "输出分诊结论"},
            ),
            input_boundary="HealthIssue and linked runtime traces.",
            output_boundary="HealthTriageResult.",
            stop_conditions=("triage_ready",),
            output_contract_id="HealthTriageResult",
            prompt="你是一名健康系统维护分析员。你只负责判断当前问题的影响范围、风险等级和下一步处理建议。",
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "task.health.issue_triage"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.trace_analysis",
            title="健康链路分析工作流",
            task_mode="trace_analysis",
            steps=(
                {"step_id": "read_trace", "title": "读取链路"},
                {"step_id": "locate_breakpoint", "title": "定位异常断点"},
                {"step_id": "finalize_trace_analysis", "title": "输出链路分析"},
            ),
            input_boundary="HealthTrace and related runtime events.",
            output_boundary="HealthTraceAnalysis.",
            stop_conditions=("analysis_ready",),
            output_contract_id="HealthTraceAnalysis",
            prompt="你是一名健康链路分析员。你只负责根据运行链路定位异常阶段、证据和可能原因。",
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "task.health.trace_analysis"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.case_draft",
            title="健康用例草案工作流",
            task_mode="case_draft",
            steps=(
                {"step_id": "read_issue", "title": "读取问题"},
                {"step_id": "draft_repro_case", "title": "草拟复现用例"},
                {"step_id": "finalize_case_draft", "title": "输出用例草案"},
            ),
            input_boundary="HealthIssue and before/after evidence when available.",
            output_boundary="HealthCaseDraftProposal.",
            stop_conditions=("case_draft_ready",),
            output_contract_id="HealthCaseDraftProposal",
            prompt="你是一名复现用例设计员。你只负责把健康问题转化为可执行、可验证的复现草案。",
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "task.health.case_draft"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.fix_verification",
            title="健康修复验证工作流",
            task_mode="fix_verification",
            steps=(
                {"step_id": "read_before_after", "title": "读取修复前后证据"},
                {"step_id": "verify_delta", "title": "验证差异"},
                {"step_id": "finalize_fix_verification", "title": "输出验证结论"},
            ),
            input_boundary="HealthIssueWithBeforeAfterTrace.",
            output_boundary="HealthFixVerificationProposal.",
            stop_conditions=("verification_ready",),
            output_contract_id="HealthFixVerificationProposal",
            prompt="你是一名修复验证员。你只负责依据修复前后证据判断问题是否被解决，并说明残余风险。",
            enabled=True,
            metadata={"managed_by": "task_system", "task_resource": "task.health.fix_verification"},
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


def _merge_items_by_key(
    default_items: list[dict[str, Any]],
    stored_items: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in default_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    for item in stored_items:
        item_key = str(item.get(key) or "").strip()
        if item_key:
            merged[item_key] = dict(item)
    return list(merged.values())


def _next_prefixed_id(existing_ids: list[str], *, prefix: str, width: int = 6) -> str:
    max_value = 0
    for raw in existing_ids:
        value = str(raw or "").strip()
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix):]
        if suffix.isdigit():
            max_value = max(max_value, int(suffix))
    return f"{prefix}{max_value + 1:0{width}d}"


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
        default_payload = [item.to_dict() for item in default_task_workflows()]
        payload = _read_json(
            _workflows_path(self.base_dir),
            {"workflows": default_payload},
        )
        merged_payload = _merge_items_by_key(
            default_payload,
            [item for item in list(payload.get("workflows") or []) if isinstance(item, dict)],
            key="workflow_id",
        )
        workflows = [_workflow_from_dict(item) for item in merged_payload]
        normalized = [item.to_dict() for item in workflows]
        if payload.get("workflows") != normalized:
            _write_json(_workflows_path(self.base_dir), {"workflows": normalized})
        return workflows

    def get_workflow(self, workflow_id: str) -> TaskWorkflowBinding | None:
        target = str(workflow_id or "").strip()
        return next((item for item in self.list_workflows() if item.workflow_id == target), None)

    def next_workflow_id(self) -> str:
        return _next_prefixed_id(
            [item.workflow_id for item in self.list_workflows()],
            prefix="workflow.",
        )

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

    def delete_workflows(self, workflow_ids: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
        targets = {
            str(item or "").strip()
            for item in workflow_ids
            if str(item or "").strip()
        }
        if not targets:
            return ()
        default_ids = {item.workflow_id for item in default_task_workflows()}
        deletable = targets - default_ids
        if not deletable:
            return ()
        existing = self.list_workflows()
        kept = [item for item in existing if item.workflow_id not in deletable]
        deleted = tuple(sorted({item.workflow_id for item in existing} - {item.workflow_id for item in kept}))
        if deleted:
            _write_json(_workflows_path(self.base_dir), {"workflows": [item.to_dict() for item in kept]})
        return deleted

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
