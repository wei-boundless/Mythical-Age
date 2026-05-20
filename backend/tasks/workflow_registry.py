from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_layout import ProjectLayout
from .workflow_models import TaskWorkflowBinding


def default_task_workflows() -> tuple[TaskWorkflowBinding, ...]:
    return _default_health_task_workflows()


def _default_health_task_workflows() -> tuple[TaskWorkflowBinding, ...]:
    return (
        TaskWorkflowBinding(
            workflow_id="workflow.health.issue_triage",
            title="健康问题分诊工作流",
            compatible_projection_ids=("xuannv__primary",),
            visible_skill_ids=("skill.health.issue_triage",),
            steps=(
                {
                    "step_id": "inspect_issue",
                    "title": "检查问题与证据",
                    "description": "读取问题、运行链路和证据引用，建立可诊断上下文。",
                },
                {
                    "step_id": "draft_triage",
                    "title": "输出分诊结论",
                    "description": "给出问题归属、风险、下一步建议和所需补充证据。",
                },
            ),
            input_boundary="HealthIssue",
            output_boundary="HealthTriageResult",
            stop_conditions=("evidence_insufficient", "triage_complete"),
            required_evidence_refs=("runtime_trace_refs", "conversation_ref"),
            output_contract_id="HealthTriageResult",
            prompt="你是一名健康问题分诊员。你只负责判断问题归属、风险和下一步，不负责修改系统。你需要基于证据引用给出结论，并标明证据不足时需要补充什么。",
            enabled=True,
            metadata={"task_resource": "task.health.issue_triage", "managed_by": "task_system"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.trace_analysis",
            title="健康链路分析工作流",
            compatible_projection_ids=("xuannv__primary",),
            visible_skill_ids=("skill.health.trace_analysis",),
            steps=(
                {
                    "step_id": "inspect_trace",
                    "title": "检查运行链路",
                    "description": "定位关键 runtime event、checkpoint 和可能的失败转折点。",
                },
                {
                    "step_id": "summarize_trace",
                    "title": "输出链路分析",
                    "description": "总结因果链、反证和恢复候选点。",
                },
            ),
            input_boundary="HealthTrace",
            output_boundary="HealthTraceAnalysis",
            stop_conditions=("analysis_complete",),
            required_evidence_refs=("runtime_trace_refs",),
            output_contract_id="HealthTraceAnalysis",
            prompt="你是一名运行链路分析员。你只负责解释 runtime trace 和 checkpoint，不负责扩展问题范围或改写系统状态。你需要指出关键转折点、反证和恢复候选。",
            enabled=True,
            metadata={"task_resource": "task.health.trace_analysis", "managed_by": "task_system"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.case_draft",
            title="健康复现用例草案工作流",
            compatible_projection_ids=("xuannv__primary",),
            visible_skill_ids=("skill.health.case_draft",),
            steps=(
                {
                    "step_id": "inspect_failure",
                    "title": "检查失败样本",
                    "description": "提取最小复现输入与必现条件。",
                },
                {
                    "step_id": "draft_case",
                    "title": "输出用例草案",
                    "description": "整理成可回归的场景契约和断言。",
                },
            ),
            input_boundary="HealthIssue",
            output_boundary="HealthCaseDraftProposal",
            stop_conditions=("case_draft_ready",),
            required_evidence_refs=("runtime_trace_refs", "assertion_refs"),
            output_contract_id="HealthCaseDraftProposal",
            prompt="你是一名复现用例草案编写员。你只负责把真实失败整理成最小可复现场景和断言，不负责修复实现。",
            enabled=True,
            metadata={"task_resource": "task.health.case_draft", "managed_by": "task_system"},
        ),
        TaskWorkflowBinding(
            workflow_id="workflow.health.fix_verification",
            title="健康修复验证工作流",
            compatible_projection_ids=("xuannv__primary",),
            visible_skill_ids=("skill.health.fix_verification",),
            steps=(
                {
                    "step_id": "inspect_fix",
                    "title": "检查修复结果",
                    "description": "验证修复前后证据是否一致，判断是否真实消除问题。",
                },
                {
                    "step_id": "final_verdict",
                    "title": "输出验证裁决",
                    "description": "给出通过、失败或仍需补证的裁决。",
                },
            ),
            input_boundary="HealthIssue",
            output_boundary="HealthFixVerificationProposal",
            stop_conditions=("verification_complete",),
            required_evidence_refs=("runtime_trace_refs", "report_refs"),
            output_contract_id="HealthFixVerificationProposal",
            prompt="你是一名修复验证员。你只负责验证修复是否真实生效、是否存在绕过测试的行为，不负责替实现方辩护。",
            enabled=True,
            metadata={"task_resource": "task.health.fix_verification", "managed_by": "task_system"},
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
