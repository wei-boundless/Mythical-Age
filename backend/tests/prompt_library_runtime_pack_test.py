from __future__ import annotations

from pathlib import Path

from harness.runtime.compiler import RuntimeCompiler
from prompt_library import (
    PromptAssemblyRequest,
    PromptAssemblyService,
    PromptLibraryRegistry,
    PromptPack,
    PromptResource,
)
from agent_system.profiles.runtime_profile_registry import default_agent_runtime_profiles
from capability_system.tool_authorization import build_tool_authorization_index
from capability_system.tool_definitions import build_tool_instances, get_tool_definitions
from harness.runtime import assemble_runtime


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_runtime_prompt_resources_have_single_clear_function() -> None:
    resources = PromptLibraryRegistry(Path(__file__).resolve().parents[1]).list_active_resources(
        category="runtime",
        sync_workflow_prompts=False,
    )
    by_id = {item.prompt_id: item for item in resources}

    assert by_id["runtime.turn_action.v1"].subtype == "turn_action"
    assert by_id["runtime.task_execution.v1"].subtype == "task_execution"
    assert by_id["runtime.observation_followup.v1"].subtype == "observation_followup"
    assert by_id["runtime.turn_action.v1"].allowed_invocation_kinds == ("turn_action",)
    assert by_id["runtime.task_execution.v1"].allowed_invocation_kinds == ("task_execution",)
    assert by_id["runtime.observation_followup.v1"].allowed_invocation_kinds == ("tool_observation_followup",)
    assert "当前 runtime 是 professional 模式" not in by_id["runtime.task_execution.v1"].content
    assert "当前任务环境说明" not in by_id["runtime.task_execution.v1"].content


def test_prompt_pack_assembly_rejects_deprecated_resources_for_new_runtime(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            prompt_id="runtime.deprecated.test.v1",
            resource_id="runtime.deprecated.test.v1",
            category="runtime",
            subtype="turn_action",
            resource_type="runtime.turn_action",
            title="Deprecated runtime prompt",
            content="不应该进入新 runtime。",
            allowed_invocation_kinds=("turn_action",),
            status="deprecated",
            metadata={"deprecated_for_new_runtime": True},
        )
    )
    registry.upsert_pack(
        pack=PromptPack(
            pack_id="runtime.pack.deprecated-test.v1",
            invocation_kind="turn_action",
            ordered_prompt_refs=("runtime.turn_action.v1", "runtime.deprecated.test.v1"),
        )
    )

    result = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="turn_action",
            prompt_pack_refs=("runtime.pack.deprecated-test.v1",),
            runtime_mode="professional",
        )
    )

    assert [section.prompt_ref for section in result.sections] == ["runtime.turn_action.v1"]
    assert result.rejected_refs == ({"ref": "runtime.deprecated.test.v1", "reason": "prompt_not_found_or_inactive"},)


def test_runtime_compiler_uses_prompt_manifest_and_runtime_pack_refs() -> None:
    result = RuntimeCompiler().compile_turn_action_packet(
        session_id="session:pack",
        turn_id="turn:pack",
        agent_invocation_id="aginvoke:pack",
        user_message="你好",
        history=[],
        runtime_assembly={
            "profile": {"mode": "standard"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
        },
    )

    manifest = result.packet.diagnostics["prompt_manifest"]

    assert result.packet.prompt_pack_refs == ("runtime.pack.turn_action.v1",)
    assert manifest["stable_prompt_refs"] == ["runtime.turn_action.v1"]
    assert "你是当前 turn 的主 agent" in result.packet.system_instructions
    assert "本次运行边界" in result.packet.system_instructions
    assert "当前 runtime 是 standard 模式" not in result.packet.system_instructions


def test_runtime_compiler_assembles_agent_and_environment_prompt_refs() -> None:
    profile = next(item for item in default_agent_runtime_profiles() if item.agent_profile_id == "main_interactive_agent")
    definitions = get_tool_definitions()
    index = build_tool_authorization_index(definitions)
    assembly = assemble_runtime(
        backend_dir=BACKEND_DIR,
        session_id="session:prompt-refs",
        turn_id="turn:prompt-refs",
        agent_invocation_id="aginvoke:prompt-refs",
        request_task_selection={"runtime_mode": "professional", "task_environment_id": "env.development.sandbox"},
        model_selection={},
        agent_runtime_profile=profile,
        tool_instances=build_tool_instances(BACKEND_DIR),
        definitions_by_name=index.definitions_by_name,
    )

    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:prompt-refs",
        task_run={"task_run_id": "taskrun:prompt-refs", "title": "验证 prompt refs"},
        contract={"task_run_goal": "验证 prompt refs", "completion_criteria": ["prompt refs 被装配"]},
        observations=[],
        execution_state={},
        available_tools=assembly.available_tools,
        runtime_assembly=assembly,
    )
    stable_payload = __import__("json").loads(result.packet.model_messages[1]["content"].split("\n", 1)[1])
    manifest = result.packet.diagnostics["prompt_manifest"]

    assert "agent.main_interactive_agent.work_role.v1" in manifest["stable_prompt_refs"]
    assert "environment.development.sandbox.v1" in manifest["stable_prompt_refs"]
    assert "通用主 agent" in result.packet.system_instructions
    assert "开发沙盒资源边界" in result.packet.system_instructions
    assert stable_payload["task_environment"]["environment_prompts"] == [
        {
            "prompt_id": "environment.development.sandbox.v1",
            "content_omitted": True,
            "content_source": "prompt_library",
        }
    ]
    assert "开发沙盒资源边界" not in result.packet.model_messages[1]["content"]
