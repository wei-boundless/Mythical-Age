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
    posture_tags: tuple[str, ...] = ()
    expression_density: str = "normal"
    attention_focus: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    guardrails: tuple[str, ...] = ()
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["posture_tags"] = list(self.posture_tags)
        payload["attention_focus"] = list(self.attention_focus)
        payload["risk_notes"] = list(self.risk_notes)
        payload["guardrails"] = list(self.guardrails)
        return payload


def default_projection_templates() -> tuple[ProjectionTemplate, ...]:
    return (
        ProjectionTemplate(
            template_id="primary_agent_default",
            title="主 Agent 默认投影",
            soul_id="active",
            agent_profile_id="main_interactive_agent",
            role_type="dispatcher",
            task_mode="interactive_dispatch",
            default_skill_workflow_id="workflow.main.dispatch",
            default_memory_policy="conversation_readonly",
            default_output_contract="AssistantFinalAnswer",
            projection_resolution_policy="hybrid",
            posture_tags=("dispatcher", "interactive", "coordination"),
            expression_density="normal",
            attention_focus=("task_intake", "delegation", "final_answer"),
            risk_notes=("主 Agent 可以协调任务，但不直接绕过能力系统授权。",),
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

