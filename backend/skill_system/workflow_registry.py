from __future__ import annotations

from pathlib import Path

from .workflow_models import SkillWorkflowBinding


def default_skill_workflows() -> tuple[SkillWorkflowBinding, ...]:
    return (
        SkillWorkflowBinding(
            workflow_id="workflow.health.issue_triage",
            title="健康问题分诊工作流",
            task_mode="issue_triage",
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
        ),
        SkillWorkflowBinding(
            workflow_id="workflow.health.trace_analysis",
            title="健康链路分析工作流",
            task_mode="trace_analysis",
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
        ),
        SkillWorkflowBinding(
            workflow_id="workflow.health.case_draft",
            title="健康用例草案工作流",
            task_mode="case_draft",
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
        ),
        SkillWorkflowBinding(
            workflow_id="workflow.health.fix_verification",
            title="健康修复验证工作流",
            task_mode="fix_verification",
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
        ),
    )


class SkillWorkflowRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def list_workflows(self) -> list[SkillWorkflowBinding]:
        return list(default_skill_workflows())

    def get_workflow(self, workflow_id: str) -> SkillWorkflowBinding | None:
        target = str(workflow_id or "").strip()
        return next((item for item in self.list_workflows() if item.workflow_id == target), None)

    def build_catalog(self) -> dict[str, object]:
        workflows = self.list_workflows()
        return {
            "authority": "skill_system.workflow_registry",
            "workflows": [item.to_dict() for item in workflows],
            "summary": {
                "workflow_count": len(workflows),
                "health_workflow_count": sum(1 for item in workflows if item.workflow_id.startswith("workflow.health.")),
            },
        }
