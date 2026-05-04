from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_registry import AgentRegistry

from .agent_runtime_models import AgentRuntimeProfile
from .agent_runtime_registry import AgentRuntimeRegistry
from .body_models import (
    AgentBodyProfile,
    MemoryScopeProfile,
    OutputBoundaryProfile,
    PromptStructureProfile,
    RuntimeLaneProfile,
)


class BodyProfileRegistry:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.runtime_registry = AgentRuntimeRegistry(self.base_dir)

    def build_agent_body_profile(
        self,
        *,
        agent_id: str,
        runtime_profile: AgentRuntimeProfile | None,
    ) -> AgentBodyProfile:
        prompt_profile_id = f"promptstruct:{agent_id}:single_agent"
        memory_profile_id = f"memscope:{agent_id}:default"
        lane_profile_id = f"lane:{agent_id}:default"
        output_profile_id = f"output:{agent_id}:default"
        descriptor = self.agent_registry.get_agent(agent_id)
        return AgentBodyProfile(
            body_profile_id=f"body:{agent_id}:single_agent",
            agent_id=agent_id,
            default_prompt_structure_profile_id=prompt_profile_id,
            default_memory_scope_profile_id=memory_profile_id,
            default_runtime_lane_profile_id=lane_profile_id,
            default_output_boundary_profile_id=output_profile_id,
            default_operation_policy_mode="fail_closed",
            default_projection_policy="task_projection_first",
            metadata={
                "agent_name": str(getattr(descriptor, "agent_name", "") or ""),
                "agent_category": str(getattr(descriptor, "agent_category", "") or ""),
                "default_soul_id": str(getattr(descriptor, "default_soul_id", "") or ""),
                "default_projection_id": str(getattr(descriptor, "default_projection_id", "") or ""),
                "runtime_profile_id": str(getattr(runtime_profile, "agent_profile_id", "") or ""),
            },
        )

    def build_prompt_structure_profile(
        self,
        *,
        agent_id: str,
        task_mode: str,
        output_contract_id: str,
    ) -> PromptStructureProfile:
        return PromptStructureProfile(
            profile_id=f"promptstruct:{agent_id}:single_agent",
            section_order=(
                "identity_view",
                "static_common_rules",
                "dynamic_task_contract",
                "role_view",
                "task_section",
                "workflow_section",
                "projection_section",
                "output_section",
                "memory_output_view",
            ),
            required_section_kinds=(
                "dynamic_task_contract",
                "task_section",
                "workflow_section",
                "projection_section",
                "output_section",
            ),
            optional_section_kinds=("skill_view", "tool_view", "memory_output_view"),
            stage_projection_policy="projection_snapshot_required",
            model_visible_rules={
                "strip_control_plane_sections": True,
                "allow_prompt_manifest_projection": True,
                "task_mode": task_mode,
                "output_contract_id": output_contract_id,
            },
            metadata={"agent_id": agent_id},
        )

    def build_memory_scope_profile(
        self,
        *,
        agent_id: str,
        runtime_profile: AgentRuntimeProfile | None,
        memory_request_profile: dict[str, Any],
    ) -> MemoryScopeProfile:
        requested_layers = tuple(
            str(item).strip()
            for item in list(memory_request_profile.get("requested_memory_layers") or ())
            if str(item).strip()
        )
        allowed_layers = tuple(str(item).strip() for item in getattr(runtime_profile, "allowed_memory_scopes", ()) if str(item).strip())
        layers = requested_layers or allowed_layers or ("conversation_read_write",)
        return MemoryScopeProfile(
            profile_id=f"memscope:{agent_id}:default",
            allowed_memory_layers=layers,
            read_scope="context_package",
            writeback_policy=str(memory_request_profile.get("writeback_policy") or "task_default"),
            token_budget_policy="context_package",
            restore_policy="session_state_first",
            metadata={
                "memory_priority": str(memory_request_profile.get("memory_priority") or "normal"),
                "requested_topics": list(memory_request_profile.get("requested_topics") or ()),
                "allow_long_term_memory": bool(memory_request_profile.get("allow_long_term_memory", False)),
            },
        )

    def build_runtime_lane_profile(
        self,
        *,
        agent_id: str,
        runtime_profile: AgentRuntimeProfile | None,
        task_mode: str,
    ) -> RuntimeLaneProfile:
        allowed_lanes = [
            str(item).strip()
            for item in getattr(runtime_profile, "allowed_runtime_lanes", ())
            if str(item).strip()
        ]
        lane_id = allowed_lanes[0] if allowed_lanes else "full_interactive"
        if task_mode == "task_dispatch" and "task_dispatch" in allowed_lanes:
            lane_id = "task_dispatch"
        elif task_mode == "light_web_game" and "game_delivery" in allowed_lanes:
            lane_id = "game_delivery"
        return RuntimeLaneProfile(
            profile_id=f"lane:{agent_id}:default",
            lane_id=lane_id,
            execution_style="single_agent_loop",
            tool_followup_policy="continue_until_terminal",
            checkpoint_policy="event_checkpoint_spine",
            resume_policy="checkpoint_replay",
            metadata={"agent_id": agent_id, "task_mode": task_mode},
        )

    def build_output_boundary_profile(
        self,
        *,
        agent_id: str,
        runtime_profile: AgentRuntimeProfile | None,
        output_contract_id: str,
    ) -> OutputBoundaryProfile:
        profile_contracts = tuple(
            str(item).strip()
            for item in getattr(runtime_profile, "output_contracts", ())
            if str(item).strip()
        )
        allowed_contracts = tuple(dict.fromkeys([output_contract_id, *profile_contracts])) if output_contract_id else profile_contracts
        if not allowed_contracts:
            allowed_contracts = ("AssistantFinalAnswer",)
        return OutputBoundaryProfile(
            profile_id=f"output:{agent_id}:default",
            allowed_output_contracts=allowed_contracts,
            citation_policy="task_default",
            artifact_commit_policy="bounded_by_output_contract",
            finalization_policy="assistant_message_commit",
            metadata={"agent_id": agent_id},
        )
