from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .agent_models import AgentCapabilityProfile, AgentDescriptor


def _storage_root(base_dir: Path) -> Path:
    return base_dir / "storage" / "operations"


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback
    return loaded if isinstance(loaded, dict) else fallback


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def default_agent_descriptors(now: float | None = None) -> tuple[AgentDescriptor, ...]:
    timestamp = time.time() if now is None else now
    return (
        AgentDescriptor(
            agent_id="agent:main",
            display_name="主 Agent",
            owner_system="task_system",
            profile_type="primary",
            lifecycle_state="system_builtin",
            default_soul_id="active",
            default_projection_template_id="primary_agent_default",
            created_at=timestamp,
            updated_at=timestamp,
            governance_status="system_builtin",
            deletable="never",
            disable_allowed=False,
            metadata={"role": "task_dispatch_and_final_integration"},
        ),
        AgentDescriptor(
            agent_id="agent:health:maintainer",
            display_name="玄女健康管家",
            owner_system="health_system",
            profile_type="sub_agent",
            lifecycle_state="enabled",
            default_soul_id="xuannv",
            default_projection_template_id="xuannv__health_maintainer",
            created_at=timestamp,
            updated_at=timestamp,
            governance_status="operation_managed",
            deletable="archive_only",
            disable_allowed=True,
            metadata={"role": "system_health_maintenance"},
        ),
    )


def default_agent_capabilities() -> tuple[AgentCapabilityProfile, ...]:
    return (
        AgentCapabilityProfile(
            agent_profile_id="main_interactive_agent",
            agent_id="agent:main",
            allowed_task_modes=("request_intake", "task_dispatch", "final_response", "general_qa"),
            allowed_runtime_lanes=("full_interactive", "task_dispatch", "final_integration"),
            allowed_operations=(
                "op.model_response",
                "op.read_file",
                "op.search_files",
                "op.search_text",
                "op.web_search",
                "op.fetch_url",
                "op.get_weather",
                "op.get_gold_price",
                "op.search_knowledge",
                "op.pdf_analysis",
                "op.structured_data_analysis",
                "op.analyze_multimodal_file",
                "op.index_multimodal_file",
                "op.write_file",
                "op.edit_file",
            ),
            blocked_operations=("op.shell", "op.python_repl", "op.memory_write_candidate"),
            allowed_skill_workflows=("workflow.main.dispatch",),
            allowed_projection_templates=("primary_agent_default",),
            allowed_memory_scopes=("conversation_read_write", "state_read_write", "long_term_candidate"),
            allowed_context_sections=("conversation", "state", "task", "projection", "tool"),
            output_contracts=("AssistantFinalAnswer",),
            lifecycle_policy="system_builtin",
        ),
        AgentCapabilityProfile(
            agent_profile_id="health_maintainer_agent",
            agent_id="agent:health:maintainer",
            allowed_task_modes=("issue_triage", "trace_analysis", "case_draft", "fix_verification"),
            allowed_runtime_lanes=(
                "health_issue_read",
                "health_trace_read",
                "prompt_trace_read",
                "memory_trace_read",
                "runtime_trace_read",
                "assertion_trace_read",
                "case_draft_candidate",
                "fix_verification_candidate",
            ),
            allowed_operations=("op.model_response", "op.read_file", "op.search_text", "op.memory_read"),
            blocked_operations=(
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.python_repl",
                "op.memory_write_candidate",
                "op.agent_bounded",
            ),
            allowed_skill_workflows=(
                "workflow.health.issue_triage",
                "workflow.health.trace_analysis",
                "workflow.health.case_draft",
                "workflow.health.fix_verification",
            ),
            allowed_projection_templates=("xuannv__health_maintainer",),
            allowed_memory_scopes=("issue_local_readonly", "health_trace_readonly"),
            allowed_context_sections=("health_issue", "runtime_trace", "prompt_manifest", "memory_runtime_view", "assertions"),
            output_contracts=(
                "HealthTriageResult",
                "HealthTraceAnalysis",
                "HealthCaseDraftProposal",
                "HealthFixVerificationProposal",
            ),
            approval_policy="read_only_first",
        ),
    )


class AgentRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.root = _storage_root(self.base_dir)
        self.agents_path = self.root / "agents.json"
        self.capabilities_path = self.root / "agent_capabilities.json"

    def list_agents(self) -> list[AgentDescriptor]:
        payload = _read_json(self.agents_path, {"agents": [item.to_dict() for item in default_agent_descriptors()]})
        return [_agent_from_dict(item) for item in list(payload.get("agents") or []) if isinstance(item, dict)]

    def list_capabilities(self) -> list[AgentCapabilityProfile]:
        payload = _read_json(
            self.capabilities_path,
            {"capabilities": [item.to_dict() for item in default_agent_capabilities()]},
        )
        return [_capability_from_dict(item) for item in list(payload.get("capabilities") or []) if isinstance(item, dict)]

    def get_agent(self, agent_id: str) -> AgentDescriptor | None:
        target = str(agent_id or "").strip()
        return next((item for item in self.list_agents() if item.agent_id == target), None)

    def get_capability_profile(self, agent_id: str) -> AgentCapabilityProfile | None:
        target = str(agent_id or "").strip()
        return next((item for item in self.list_capabilities() if item.agent_id == target), None)

    def set_agent_enabled(self, agent_id: str, enabled: bool) -> AgentDescriptor:
        current = self.get_agent(agent_id)
        if current is None:
            raise KeyError(agent_id)
        if current.lifecycle_state == "system_builtin" and not enabled:
            raise PermissionError("system builtin agent cannot be disabled")
        updated = AgentDescriptor(
            **{
                **current.to_dict(),
                "lifecycle_state": "enabled" if enabled else "disabled",
                "updated_at": time.time(),
            }
        )
        agents = [updated if item.agent_id == updated.agent_id else item for item in self.list_agents()]
        _write_json(self.agents_path, {"agents": [item.to_dict() for item in agents]})
        return updated

    def build_catalog(self) -> dict[str, Any]:
        agents = self.list_agents()
        capabilities = self.list_capabilities()
        capability_by_agent = {item.agent_id: item.to_dict() for item in capabilities}
        return {
            "authority": "operation_system.agent_registry",
            "agents": [
                {
                    **agent.to_dict(),
                    "capability_profile": capability_by_agent.get(agent.agent_id, {}),
                }
                for agent in agents
            ],
            "capabilities": [item.to_dict() for item in capabilities],
            "summary": {
                "agent_count": len(agents),
                "enabled_agent_count": sum(1 for item in agents if item.lifecycle_state in {"enabled", "system_builtin"}),
                "sub_agent_count": sum(1 for item in agents if item.profile_type == "sub_agent"),
                "system_builtin_count": sum(1 for item in agents if item.lifecycle_state == "system_builtin"),
            },
        }


def _agent_from_dict(payload: dict[str, Any]) -> AgentDescriptor:
    return AgentDescriptor(
        agent_id=str(payload.get("agent_id") or ""),
        display_name=str(payload.get("display_name") or ""),
        owner_system=str(payload.get("owner_system") or ""),
        profile_type=str(payload.get("profile_type") or "sub_agent"),
        lifecycle_state=str(payload.get("lifecycle_state") or "disabled"),
        default_soul_id=str(payload.get("default_soul_id") or ""),
        default_projection_template_id=str(payload.get("default_projection_template_id") or ""),
        created_at=float(payload.get("created_at") or 0.0),
        updated_at=float(payload.get("updated_at") or 0.0),
        governance_status=str(payload.get("governance_status") or "operation_managed"),
        deletable=str(payload.get("deletable") or "archive_only"),
        disable_allowed=bool(payload.get("disable_allowed", True)),
        metadata=dict(payload.get("metadata") or {}),
    )


def _capability_from_dict(payload: dict[str, Any]) -> AgentCapabilityProfile:
    return AgentCapabilityProfile(
        agent_profile_id=str(payload.get("agent_profile_id") or ""),
        agent_id=str(payload.get("agent_id") or ""),
        allowed_task_modes=tuple(str(item) for item in list(payload.get("allowed_task_modes") or [])),
        allowed_runtime_lanes=tuple(str(item) for item in list(payload.get("allowed_runtime_lanes") or [])),
        allowed_operations=tuple(str(item) for item in list(payload.get("allowed_operations") or [])),
        blocked_operations=tuple(str(item) for item in list(payload.get("blocked_operations") or [])),
        allowed_skill_workflows=tuple(str(item) for item in list(payload.get("allowed_skill_workflows") or [])),
        allowed_projection_templates=tuple(str(item) for item in list(payload.get("allowed_projection_templates") or [])),
        allowed_memory_scopes=tuple(str(item) for item in list(payload.get("allowed_memory_scopes") or [])),
        allowed_context_sections=tuple(str(item) for item in list(payload.get("allowed_context_sections") or [])),
        output_contracts=tuple(str(item) for item in list(payload.get("output_contracts") or [])),
        approval_policy=str(payload.get("approval_policy") or "default"),
        trace_policy=str(payload.get("trace_policy") or "runtime_event_log"),
        lifecycle_policy=str(payload.get("lifecycle_policy") or "operation_managed"),
        metadata=dict(payload.get("metadata") or {}),
    )
