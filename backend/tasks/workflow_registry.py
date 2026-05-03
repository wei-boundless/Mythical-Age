from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .workflow_models import TaskWorkflowBinding


def default_task_workflows() -> tuple[TaskWorkflowBinding, ...]:
    return (
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
    return Path(base_dir) / "storage" / "tasks"


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
            },
        }
