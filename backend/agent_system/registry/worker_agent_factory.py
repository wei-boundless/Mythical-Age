from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..models.agent_models import AgentDescriptor
from .agent_registry import AgentRegistry
from ..profiles.runtime_profile_models import AgentRuntimeProfile
from ..profiles.runtime_profile_registry import AgentRuntimeRegistry
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
            description="你是一名开发工作子 Agent。你只处理父任务分配给你的局部实现、检查或素材整理工作。你需要先理解边界和已有上下文，再读取必要文件；可以在授权范围内修改文件，但不能扩大任务目标、替主 Agent 做最终答复，或把未经验证的假设当作结论。",
            allowed_operations=(
                "op.model_response",
                "op.codebase_search",
                "op.read_file",
                "op.python_code_outline",
                "op.python_parse_check",
                "op.python_symbol_search",
                "op.search_files",
                "op.search_text",
                "op.write_file",
                "op.edit_file",
            ),
            blocked_operations=("op.shell", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("conversation", "task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            approval_policy="default",
            trace_policy="runtime_event_log",
            metadata={"worker_kind": "development"},
        ),
        WorkerAgentBlueprint(
            blueprint_id="worker.explorer",
            agent_name_template="探索 Agent {n}",
            description="你是一名只读探索员。你只负责摸清代码、资料和上下文现状，返回可引用的文件路径、片段、线索和不确定性。你不能写入项目文件，不能执行破坏性操作，也不负责制定最终方案或交付最终答案。",
            allowed_operations=(
                "op.model_response",
                "op.read_file",
                "op.list_dir",
                "op.stat_path",
                "op.path_exists",
                "op.glob_paths",
                "op.search_files",
                "op.search_text",
                "op.web_search",
                "op.fetch_url",
            ),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            trace_policy="runtime_event_log",
            metadata={"worker_kind": "explorer", "prompt_role": "read_only_search_specialist"},
        ),
        WorkerAgentBlueprint(
            blueprint_id="worker.planner",
            agent_name_template="规划 Agent {n}",
            description="你是一名只读规划员。你负责基于已读取的代码、差异和上下文拆解方案、评估风险、列出实施步骤和验证方式。你不能修改文件或执行实现；如果信息不足，需要明确列出缺口，而不是替事实做假设。",
            allowed_operations=("op.model_response", "op.read_file", "op.search_files", "op.search_text", "op.git_status", "op.git_diff"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "runtime_contracts", "upstream_outputs", "artifact_refs"),
            approval_policy="read_only_first",
            trace_policy="runtime_event_log",
            metadata={"worker_kind": "planner", "prompt_role": "software_planning_specialist"},
        ),
        WorkerAgentBlueprint(
            blueprint_id="worker.verification",
            agent_name_template="验证 Agent {n}",
            description="你是一名验证员。你负责复核实现、运行检查并输出可复现证据。你需要优先寻找真实缺陷、回归风险和缺失验证；不能修改文件，不能替实现者修复问题，也不能用跳过、弱化或伪造检查来制造通过。",
            allowed_operations=("op.model_response", "op.read_file", "op.search_text", "op.shell"),
            blocked_operations=("op.write_file", "op.edit_file", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("issue_local_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "runtime_trace", "assertions", "runtime_contracts", "artifact_refs"),
            approval_policy="deny_destructive",
            trace_policy="full_trace",
            metadata={"worker_kind": "verification", "prompt_role": "adversarial_verification_specialist"},
        ),
        WorkerAgentBlueprint(
            blueprint_id="worker.execution",
            agent_name_template="执行 Agent {n}",
            description="你是一名边界执行员。你只执行父任务明确授权的实现、写入或修复工作。你需要先读取相关文件和当前状态，再做最小必要修改；遇到边界不清、旧内容不匹配或验证失败时，要报告阻断点和下一步，而不是扩大范围硬改。",
            allowed_operations=(
                "op.model_response",
                "op.read_file",
                "op.search_files",
                "op.search_text",
                "op.write_file",
                "op.edit_file",
                "op.shell",
            ),
            blocked_operations=("op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "upstream_outputs", "artifact_refs"),
            approval_policy="default",
            trace_policy="runtime_event_log",
            metadata={"worker_kind": "execution", "prompt_role": "bounded_execution_worker"},
        ),
        WorkerAgentBlueprint(
            blueprint_id="worker.code.executor",
            agent_name_template="代码执行 Agent {n}",
            description="你是一名代码执行员。你负责完成边界清楚的代码修改、测试修复或前端实现任务。你需要遵循项目现有架构和样式，先读文件再编辑，保留可追踪的验证结果；不能绕过测试、弱化断言、留下无用旧链路，或替主 Agent 做最终用户答复。",
            allowed_operations=(
                "op.model_response",
                "op.agent_todo",
                "op.codebase_search",
                "op.read_file",
                "op.read_structured_file",
                "op.list_dir",
                "op.stat_path",
                "op.path_exists",
                "op.glob_paths",
                "op.python_code_outline",
                "op.python_parse_check",
                "op.python_symbol_search",
                "op.search_files",
                "op.search_text",
                "op.git_status",
                "op.git_diff",
                "op.write_file",
                "op.edit_file",
                "op.shell",
                "op.browser_control",
            ),
            blocked_operations=("op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "tool", "runtime_contracts", "upstream_outputs", "artifact_refs"),
            approval_policy="task_bounded_write",
            trace_policy="full_trace",
            metadata={"worker_kind": "code_execution", "prompt_role": "bounded_code_executor"},
        ),
        WorkerAgentBlueprint(
            blueprint_id="worker.review",
            agent_name_template="审查 Agent {n}",
            description="你是一名审查员。你负责审查代码变更、交付产物和验证证据，优先指出真实 bug、行为回归、安全边界和缺失测试。你不能修改文件；输出需要包含问题位置、影响、证据和建议，不要把风格偏好当作缺陷。",
            allowed_operations=("op.model_response", "op.read_file", "op.search_files", "op.search_text", "op.git_diff", "op.git_show"),
            blocked_operations=("op.write_file", "op.edit_file", "op.shell", "op.python_repl", "op.memory_write_candidate"),
            allowed_memory_scopes=("conversation_readonly", "state_readonly"),
            allowed_context_sections=("task", "projection", "runtime_trace", "assertions", "runtime_contracts", "artifact_refs"),
            approval_policy="read_only_first",
            trace_policy="runtime_event_log",
            metadata={"worker_kind": "review", "prompt_role": "bug_first_review_specialist"},
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
    ) -> ProvisionedWorkerAgent:
        blueprint = self.get_blueprint(request.blueprint_id)
        if blueprint is None:
            raise KeyError(request.blueprint_id)
        agent_id = self.agent_registry.next_worker_agent_id()
        agent = self.agent_registry.upsert_agent(
            agent_id=agent_id,
            agent_name=requested_agent_name,
            agent_category="custom_agent",
            interface_target="worker_task_console",
            description=blueprint.description,
            enabled=True,
            editable=True,
            metadata={
                **dict(blueprint.metadata),
                "agent_template_id": str(blueprint.blueprint_id or "").strip(),
                "subagent_enabled": True,
                "group_eligible": True,
                "spawn_request_id": request.spawn_request_id,
                "provisioned_by": "runtime_loop",
            },
        )
        runtime_profile = self.agent_runtime_registry.upsert_profile(
            agent_id=agent.agent_id,
            agent_profile_id=f"{agent.agent_id.removeprefix('agent:').replace(':', '_')}_runtime",
            allowed_operations=blueprint.allowed_operations,
            blocked_operations=blueprint.blocked_operations,
            allowed_memory_scopes=blueprint.allowed_memory_scopes,
            allowed_context_sections=blueprint.allowed_context_sections,
            approval_policy=blueprint.approval_policy,
            trace_policy=blueprint.trace_policy,
            lifecycle_policy="orchestration_managed",
            metadata={
                **dict(blueprint.metadata),
                "runtime_template_id": str(blueprint.blueprint_id or "").strip(),
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


