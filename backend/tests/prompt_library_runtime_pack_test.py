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


def test_prompt_pack_assembly_enforces_pack_boundaries(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resource(
        PromptResource(
            prompt_id="runtime.professional.only.v1",
            resource_id="runtime.professional.only.v1",
            category="runtime",
            subtype="turn_action",
            resource_type="runtime.turn_action",
            title="Professional only",
            content="只允许专家模式使用。",
            allowed_invocation_kinds=("turn_action",),
            status="active",
        )
    )
    registry.upsert_pack(
        pack=PromptPack(
            pack_id="runtime.pack.professional-only.v1",
            invocation_kind="turn_action",
            ordered_prompt_refs=("runtime.professional.only.v1",),
            allowed_runtime_modes=("professional",),
            allowed_agent_refs=("main_interactive_agent",),
            allowed_environment_refs=("env.development.sandbox",),
        )
    )

    rejected = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="turn_action",
            prompt_pack_refs=("runtime.pack.professional-only.v1",),
            runtime_mode="standard",
            agent_profile_ref="main_interactive_agent",
            task_environment_ref="env.development.sandbox",
        )
    )
    accepted = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="turn_action",
            prompt_pack_refs=("runtime.pack.professional-only.v1",),
            runtime_mode="professional",
            agent_profile_ref="main_interactive_agent",
            task_environment_ref="env.development.sandbox",
        )
    )

    assert rejected.sections == ()
    assert rejected.rejected_refs == ({"ref": "runtime.pack.professional-only.v1", "reason": "pack_runtime_mode_mismatch"},)
    assert [section.prompt_ref for section in accepted.sections] == ["runtime.professional.only.v1"]


def test_prompt_assembly_accepts_explicit_task_and_graph_contracts(tmp_path: Path) -> None:
    result = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_pack_refs=(),
            prompt_refs=(),
            task_prompt_contract={
                "contract_id": "contract.delivery.test",
                "role_prompt": "你是一名交付执行员，只负责完成合同产物。",
                "task_instruction": "读取合同并真实创建交付物。",
                "output_instruction": "最终说明真实产物路径和验证结果。",
                "forbidden_behavior": ["不能把计划当作交付物", "不能伪造验证"],
                "definition_of_done": ["产物存在", "验证完成"],
            },
            graph_node_prompt_contract={
                "contract_id": "node.review.test",
                "role_prompt": "你是一名审核员，只负责裁决是否通过。",
                "definition_of_done": "给出明确裁决。",
            },
        )
    )

    sections = {(item.category, item.subtype): item for item in result.sections}

    assert sections[("task", "role")].content == "你是一名交付执行员，只负责完成合同产物。"
    assert sections[("task", "forbidden_behavior")].content == "- 不能把计划当作交付物\n- 不能伪造验证"
    assert sections[("graph_node", "role")].content == "你是一名审核员，只负责裁决是否通过。"
    assert sections[("graph_node", "definition_of_done")].source_ref == "graph_node_prompt_contract:node.review.test.definition_of_done"
    assert result.manifest["contract_section_count"] == 7


def test_prompt_assembly_adds_skill_and_soul_refs_only_when_explicit(tmp_path: Path) -> None:
    registry = PromptLibraryRegistry(tmp_path)
    registry.upsert_resources(
        (
            PromptResource(
                prompt_id="skill.imagegen.usage.v1",
                resource_id="skill.imagegen.usage.v1",
                category="skill",
                subtype="usage",
                resource_type="skill_prompt",
                title="Image generation skill",
                content="需要真实图片资源时，可以调用生图技能并保存产物。",
                allowed_invocation_kinds=("task_execution",),
                cache_scope="static",
            ),
            PromptResource(
                prompt_id="soul.writer.role.v1",
                resource_id="soul.writer.role.v1",
                category="soul",
                subtype="role_persona",
                resource_type="role_prompt",
                title="Writer soul",
                content="保持角色表达，但不得改变任务边界。",
                allowed_invocation_kinds=("task_execution",),
                cache_scope="static",
            ),
        )
    )

    empty = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(invocation_kind="task_execution", prompt_pack_refs=(), prompt_refs=())
    )
    explicit = PromptAssemblyService(tmp_path).assemble(
        PromptAssemblyRequest(
            invocation_kind="task_execution",
            prompt_pack_refs=(),
            prompt_refs=(),
            skill_prompt_refs=("skill.imagegen.usage.v1",),
            soul_prompt_ref="soul.writer.role.v1",
        )
    )

    assert [item.prompt_ref for item in empty.sections] == ["runtime.task_execution.v1"]
    assert [item.prompt_ref for item in explicit.sections] == [
        "runtime.task_execution.v1",
        "skill.imagegen.usage.v1",
        "soul.writer.role.v1",
    ]
    assert [item.category for item in explicit.sections] == ["runtime", "skill", "soul"]


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
    assert manifest["dynamic_projection_refs"] == ["agent_visible_runtime_projection", "operation_authorization"]
    assert manifest["volatile_state_refs"] == ["runtime_envelope", "turn_id", "history", "user_message"]
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
    assert manifest["cache_boundary"]["static_section_count"] == 3
    assert manifest["cache_boundary"]["cache_scope_counts"]["static_environment"] == 1
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


def test_stored_prompt_resources_use_current_runtime_mode_names() -> None:
    resources = PromptLibraryRegistry(BACKEND_DIR).list_resources()
    stale_modes = []
    for resource in resources:
        for mode in resource.allowed_runtime_modes:
            if str(mode).endswith("_mode"):
                stale_modes.append((resource.prompt_id, mode))

    assert stale_modes == []


def test_runtime_compiler_assembles_task_prompt_contract_into_task_execution_packet() -> None:
    result = RuntimeCompiler().compile_task_execution_packet(
        session_id="session:contract-prompt",
        task_run={"task_run_id": "taskrun:contract-prompt", "title": "合同 prompt 装配"},
        contract={
            "contract_id": "contract:prompt",
            "task_run_goal": "完成合同 prompt 装配验证",
            "completion_criteria": ["合同 prompt section 进入 runtime packet"],
            "prompt_contract": {
                "role_prompt": "你是一名合同执行员，只负责真实推进合同目标。",
                "task_instruction": "按合同完成稳定 prompt 装配验证。",
                "output_instruction": "最终输出真实验证结果。",
                "forbidden_behavior": ["不能伪造 manifest"],
                "definition_of_done": ["manifest 记录合同 section"],
            },
        },
        observations=[],
        execution_state={},
        available_tools=[],
        runtime_assembly={
            "profile": {"mode": "professional"},
            "task_environment": {"environment_id": "env.general.workspace"},
            "operation_authorization": {"allowed_operations": ["op.model_response"]},
        },
    )

    manifest = result.packet.diagnostics["prompt_manifest"]

    assert "你是一名合同执行员，只负责真实推进合同目标。" in result.packet.system_instructions
    assert "按合同完成稳定 prompt 装配验证。" in result.packet.system_instructions
    assert "runtime.task_execution.v1" in manifest["stable_prompt_refs"]
    assert "task_prompt_contract:contract:prompt.role_prompt" in manifest["stable_contract_refs"]
    assert "task_prompt_contract:contract:prompt.definition_of_done" in manifest["stable_contract_refs"]
