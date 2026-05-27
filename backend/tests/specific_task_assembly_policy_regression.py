from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from task_system.registry.flow_models import SpecificTaskRecord, TaskExecutionPolicy
from task_system.tasks import resolve_specific_task_assembly_policy


def test_specific_task_assembly_policy_extracts_environment_and_agent_selection() -> None:
    record = SpecificTaskRecord(
        task_id="task.frontend.fix",
        task_title="Frontend Fix",
        metadata={"environment_id": "env.vibe_coding"},
        output_contract_id="contract.frontend.patch",
        task_policy={
            "tool_capability_requirements": {
                "required_operations": ["op.read_file", "op.edit_file"],
                "optional_operations": ["op.shell"],
                "denied_operations": ["op.browser_control"],
            },
            "skill_requirements": {"required_skill_refs": ["codebase_search"]},
            "prompt_requirements": {"optional_prompt_refs": ["bug_fix"]},
        },
    )
    execution_policy = TaskExecutionPolicy(
        policy_id="taskexecpol:frontend.fix",
        task_id="task.frontend.fix",
        execution_mode="single_agent",
        default_agent_id="agent:codebase_searcher",
        allow_worker_agent_spawn=True,
        worker_agent_blueprint_id="worker.code_reviewer",
    )

    policy = resolve_specific_task_assembly_policy(task_record=record, execution_policy=execution_policy)

    assert policy.environment_id == "env.vibe_coding"
    assert policy.output_contract_ref == "contract.frontend.patch"
    assert policy.runtime_shape == "task_graph"
    assert policy.agent_selection.default_agent_id == "agent:codebase_searcher"
    assert policy.agent_selection.worker_blueprint_id == "worker.code_reviewer"
    assert policy.agent_selection.allow_worker_spawn is True
    assert policy.tool_capability_requirements.required_operations == ("op.read_file", "op.edit_file")
    assert policy.tool_capability_requirements.optional_operations == ("op.shell",)
    assert policy.tool_capability_requirements.denied_operations == ("op.browser_control",)
    assert policy.skill_requirements.required_refs == ("codebase_search",)
    assert policy.prompt_requirements.optional_refs == ("bug_fix",)


def test_specific_task_assembly_policy_selection_can_choose_environment_but_not_agent_runtime_behavior() -> None:
    record = SpecificTaskRecord(
        task_id="task.chapter.draft",
        task_title="Chapter Draft",
        domain_id="legacy.writing",
        metadata={"environment_id": "env.writing"},
    )

    policy = resolve_specific_task_assembly_policy(
        task_record=record,
        task_selection={
            "task_environment_id": "env.writing",
            "tool_requirements": {"required_operations": ["op.read_file", "op.write_file"]},
            "default_agent_id": "agent:0",
        },
    )

    assert policy.environment_id == "env.writing"
    assert policy.agent_selection.default_agent_id == "agent:0"
    assert policy.tool_capability_requirements.required_operations == ("op.read_file", "op.write_file")
    payload = policy.to_dict()
    assert payload["authority"] == "task_system.specific_task_assembly_policy"
    assert "TaskEnvironmentSpec" not in str(payload)


def test_specific_task_assembly_policy_does_not_use_legacy_domain_as_environment() -> None:
    policy = resolve_specific_task_assembly_policy(
        task_record=SpecificTaskRecord(
            task_id="task.legacy.writing",
            task_title="Legacy Writing",
            domain_id="domain.writing.modular_novel",
        )
    )

    assert policy.environment_id == "env.general_workspace"
