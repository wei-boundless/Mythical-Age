from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProjectionTemplate:
    template_id: str
    title: str
    soul_id: str
    agent_profile_id: str
    role_type: str
    task_mode: str
    default_skill_workflow_id: str
    default_memory_policy: str
    default_output_contract: str
    projection_resolution_policy: str = "pinned"
    guardrails: tuple[str, ...] = ()
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["guardrails"] = list(self.guardrails)
        return payload


def default_projection_templates() -> tuple[ProjectionTemplate, ...]:
    return (
        ProjectionTemplate(
            template_id="xuannv__health_maintainer",
            title="玄女 / 健康维护投影",
            soul_id="xuannv",
            agent_profile_id="health_maintainer_agent",
            role_type="health_inspector",
            task_mode="health_maintenance",
            default_skill_workflow_id="workflow.health.issue_triage",
            default_memory_policy="issue_local_readonly",
            default_output_contract="HealthTriageResult",
            projection_resolution_policy="pinned",
            guardrails=(
                "只读取问题证据和显式 trace refs。",
                "不得扩大 ResourcePolicy 或声称拥有工具权限。",
                "只输出候选分析、用例草案或修复验证建议。",
            ),
            metadata={"default_agent_id": "agent:health:maintainer"},
        ),
        ProjectionTemplate(
            template_id="primary_agent_default",
            title="主 Agent 默认投影",
            soul_id="active",
            agent_profile_id="main_interactive_agent",
            role_type="dispatcher",
            task_mode="interactive_dispatch",
            default_skill_workflow_id="workflow.main.dispatch",
            default_memory_policy="conversation_read_write",
            default_output_contract="AssistantFinalAnswer",
            projection_resolution_policy="hybrid",
            guardrails=("主 Agent 负责任务识别、委派和最终整合。",),
            metadata={"default_agent_id": "agent:main"},
        ),
    )


class ProjectionTemplateRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

    def list_templates(self) -> list[ProjectionTemplate]:
        return list(default_projection_templates())

    def get_template(self, template_id: str) -> ProjectionTemplate | None:
        target = str(template_id or "").strip()
        return next((item for item in self.list_templates() if item.template_id == target), None)

    def build_catalog(self) -> dict[str, Any]:
        templates = self.list_templates()
        return {
            "authority": "soul.projection_template_registry",
            "templates": [item.to_dict() for item in templates],
            "summary": {
                "template_count": len(templates),
                "enabled_template_count": sum(1 for item in templates if item.enabled),
            },
        }
