from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .agent_models import AgentDescriptor
from .agent_registry import AgentRegistry
from .agent_runtime_models import AgentRuntimeProfile
from .agent_runtime_registry import AgentRuntimeRegistry
from .worker_agent_blueprints import (
    WorkerAgentBlueprint,
    WorkerAgentSpawnRequest,
    WorkerAgentSpawnResult,
)


def default_worker_agent_blueprints() -> tuple[WorkerAgentBlueprint, ...]:
    return (
        WorkerAgentBlueprint(
            blueprint_id="worker.dev.prototype",
            agent_name_template="开发工作Agent {n}",
            description="通用开发工作子 Agent，用于领取局部实现、检查和素材整理类任务。",
            allowed_task_modes=("light_web_game", "arcade_game_bundle", "bounded_patch", "task_execution"),
            default_runtime_lanes=("workspace_patch", "game_delivery"),
            allowed_operations=(
                "op.model_response",
                "op.read_file",
                "op.search_files",
                "op.search_text",
                "op.write_file",
                "op.edit_file",
            ),
            blocked_operations=("op.shell", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_read_write", "state_read_write"),
            allowed_context_sections=("conversation", "task", "projection", "tool"),
            output_contracts=("AssistantFinalAnswer", "LightWebGameResult"),
            approval_policy="default",
            trace_policy="runtime_event_log",
            metadata={"worker_kind": "development"},
        ),
    )


@dataclass(frozen=True, slots=True)
class ProvisionedWorkerAgent:
    agent: AgentDescriptor
    runtime_profile: AgentRuntimeProfile
    spawn_result: WorkerAgentSpawnResult


class WorkerAgentFactory:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.agent_registry = AgentRegistry(self.base_dir)
        self.agent_runtime_registry = AgentRuntimeRegistry(self.base_dir)
        self._blueprints = {item.blueprint_id: item for item in default_worker_agent_blueprints()}

    def get_blueprint(self, blueprint_id: str) -> WorkerAgentBlueprint | None:
        return self._blueprints.get(str(blueprint_id or "").strip())

    def provision_worker_agent(
        self,
        *,
        request: WorkerAgentSpawnRequest,
        requested_agent_name: str,
        task_scope: tuple[str, ...] = (),
    ) -> ProvisionedWorkerAgent:
        blueprint = self.get_blueprint(request.blueprint_id)
        if blueprint is None:
            raise KeyError(request.blueprint_id)
        agent_id = self.agent_registry.next_worker_agent_id()
        agent = self.agent_registry.upsert_agent(
            agent_id=agent_id,
            agent_name=requested_agent_name,
            agent_category="worker_sub_agent",
            interface_target="worker_task_console",
            description=blueprint.description,
            enabled=True,
            editable=True,
            task_scope=task_scope or blueprint.allowed_task_modes,
            metadata={
                **dict(blueprint.metadata),
                "spawn_request_id": request.spawn_request_id,
                "provisioned_by": "runtime_loop",
            },
        )
        runtime_profile = self.agent_runtime_registry.upsert_profile(
            agent_id=agent.agent_id,
            agent_profile_id=f"{agent.agent_id.removeprefix('agent:').replace(':', '_')}_runtime",
            allowed_task_modes=blueprint.allowed_task_modes,
            allowed_runtime_lanes=blueprint.default_runtime_lanes or (request.runtime_lane,),
            allowed_operations=blueprint.allowed_operations,
            blocked_operations=blueprint.blocked_operations,
            allowed_memory_scopes=blueprint.allowed_memory_scopes,
            allowed_context_sections=blueprint.allowed_context_sections,
            output_contracts=blueprint.output_contracts,
            approval_policy=blueprint.approval_policy,
            trace_policy=blueprint.trace_policy,
            lifecycle_policy="orchestration_managed",
            metadata={
                **dict(blueprint.metadata),
                "spawn_request_id": request.spawn_request_id,
            },
        )
        spawn_result = WorkerAgentSpawnResult(
            spawn_result_id=f"spawnresult:{request.spawn_request_id}",
            spawn_request_id=request.spawn_request_id,
            task_run_id=request.task_run_id,
            parent_agent_run_ref=request.parent_agent_run_ref,
            blueprint_id=request.blueprint_id,
            spawned_agent_id=agent.agent_id,
            spawned_agent_profile_id=runtime_profile.agent_profile_id,
            status="spawned",
            created_at=time.time(),
            diagnostics={"requested_agent_name": requested_agent_name},
        )
        return ProvisionedWorkerAgent(
            agent=agent,
            runtime_profile=runtime_profile,
            spawn_result=spawn_result,
        )
